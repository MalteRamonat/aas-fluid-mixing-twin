"""Live simulation stack: OpenModelica worker, sim-runner, store, AAS — and the reproduction of
the benchmark's published simulation result.

Needs ``docker compose up -d`` (the `openmodelica` and `sim-runner` services) and the
benchmark data. Skips otherwise.
"""

from __future__ import annotations

import csv
import time

import httpx
import pytest

from aas_fluid_twin import config
from aas_fluid_twin.aas.builders.simulation_control import SUBMODEL_ID as CONTROL_ID
from aas_fluid_twin.aas.builders.time_series import SIMULATION_TIMESERIES_ID
from aas_fluid_twin.benchmark.modelica import load_modelica_model
from aas_fluid_twin.benchmark.signals import SignalDictionary
from aas_fluid_twin.client import BasyxClient
from aas_fluid_twin.simulation.mapping import build_channel_mapping
from aas_fluid_twin.simulation.om_runner import OmRunner
from aas_fluid_twin.simulation.runner import SimulationRequest
from aas_fluid_twin.simulation.schedule import ActuatorSchedule

pytestmark = [pytest.mark.integration, pytest.mark.benchmark_data]

SIM_RUNNER = "http://localhost:8001"
OM_WORKER = "http://localhost:8010"
API = "http://localhost:8000"
BASYX = "http://localhost:8081"

UPSTREAM_MODEL = "ModVA_online_stable"
FAULTCAPABLE_MODEL = "ModVA_faultcapable"

#: The raw omc result behind the published clear-name file (100 s, IDA, embedded schedule).
REFERENCE_RAW = (
    config.BENCHMARK_DIR
    / "simulation"
    / "simulation_datasets"
    / "ModVA_online_stable_res_20241206_102432.csv"
)


@pytest.fixture(scope="module")
def sim_runner() -> httpx.Client:
    client = httpx.Client(base_url=SIM_RUNNER, timeout=30.0)
    try:
        health = client.get("/health").json()
    except httpx.HTTPError:
        pytest.skip("sim-runner not reachable — docker compose up -d")
    assert health["status"] == "UP" and health["channels"] == 29
    assert set(health["models"]) == {UPSTREAM_MODEL, FAULTCAPABLE_MODEL}
    return client


def _wait(client: httpx.Client, run_id: str, timeout_s: float = 300.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        body = client.get(f"/runs/{run_id}").json()
        if body["status"] in ("completed", "failed"):
            return dict(body)
        time.sleep(2.0)
    raise AssertionError(f"run {run_id} did not finish within {timeout_s} s")


def test_run_lands_in_store_and_aas(sim_runner: httpx.Client) -> None:
    submitted = sim_runner.post(
        "/runs",
        json={
            "stop_time": 20,
            "label": "integration test",
            "schedule": "BenchmarkMatrix",
            "model": UPSTREAM_MODEL,  # this test is about the plumbing, so take the fast model
        },
    )
    assert submitted.status_code == 202, submitted.text
    run_id = submitted.json()["run_id"]
    final = _wait(sim_runner, run_id)
    assert final["status"] == "completed", final
    assert final["segment_id_short"] == f"Simulated_{run_id}"

    # store, through the API the LinkedSegment points at
    record = httpx.get(f"{API}/api/runs/{run_id}", timeout=30).json()
    assert record["origin"] == "simulated" and record["record_count"] == final["record_count"]
    series = httpx.get(
        f"{API}/api/timeseries",
        params={"run_id": run_id, "channels": "Tank_B201_Volume,Tempreature_before_Pump_P201"},
        timeout=30,
    ).json()
    assert series["t_rel_s"][0] == 0.0 and series["t_rel_s"][-1] == pytest.approx(20.0)
    assert 15 < series["channels"]["Tempreature_before_Pump_P201"][0] < 25  # °C, not K (D5)
    assert 2000 < series["channels"]["Tank_B201_Volume"][0] < 2500  # ml, not m3

    # AAS: segment pair + attachment + run log
    basyx = BasyxClient(BASYX)
    segments = {
        e["idShort"]: e
        for e in next(
            s
            for s in basyx.get_submodel_json(SIMULATION_TIMESERIES_ID)["submodelElements"]
            if s["idShort"] == "Segments"
        )["value"]
    }
    linked = {e["idShort"]: e.get("value") for e in segments[f"Linked_{run_id}"]["value"]}
    assert linked["Query"] == f"run_id={run_id}"
    assert httpx.get(f"{linked['Endpoint']}?{linked['Query']}", timeout=30).status_code == 200
    external = segments[f"Simulated_{run_id}"]
    assert any(e["idShort"] == "File" for e in external["value"])
    runs = next(
        e for e in basyx.get_submodel_json(CONTROL_ID)["submodelElements"] if e["idShort"] == "Runs"
    )["value"]
    assert run_id in {r["idShort"] for r in runs}


def test_fault_handle_is_refused_by_the_upstream_model_version(sim_runner: httpx.Client) -> None:
    """The upstream model has no leak valve, so asking it for one must fail, not be ignored."""
    response = sim_runner.post(
        "/runs", json={"model": UPSTREAM_MODEL, "parameter_overrides": {"V211_opening": 0.5}}
    )
    assert response.status_code == 422 and "V211_opening" in response.text


def test_unknown_parameter_is_refused_on_either_model(sim_runner: httpx.Client) -> None:
    for name in (UPSTREAM_MODEL, FAULTCAPABLE_MODEL):
        response = sim_runner.post(
            "/runs", json={"model": name, "parameter_overrides": {"V999_opening": 0.5}}
        )
        assert response.status_code == 422, name
        assert "V999_opening" in response.text


def _mixing_tank_volume(run_id: str) -> list[float]:
    series = httpx.get(
        f"{API}/api/timeseries",
        params={"run_id": run_id, "channels": "Tank_B204_Volume"},
        timeout=30,
    ).json()
    return [v for v in series["channels"]["Tank_B204_Volume"] if v is not None]


def test_leakage_diverts_flow_away_from_the_mixing_tank(sim_runner: httpx.Client) -> None:
    """The fault-capable model's leak valve must move liquid out of the process, not relabel it.

    P201 starts pumping into B204 at t ~ 9.8 s in the embedded schedule, so by t = 40 s an
    open V211 has to show up as less liquid arriving in B204.
    """
    spec = {"stop_time": 40.0, "model": FAULTCAPABLE_MODEL, "schedule": "EmbeddedDefault"}
    nominal = sim_runner.post("/runs", json={**spec, "label": "nominal"})
    leaking = sim_runner.post(
        "/runs",
        json={**spec, "label": "leakage", "parameter_overrides": {"V211_opening": 0.3}},
    )
    assert nominal.status_code == 202 and leaking.status_code == 202
    nominal_run = _wait(sim_runner, nominal.json()["run_id"], timeout_s=900)
    leaking_run = _wait(sim_runner, leaking.json()["run_id"], timeout_s=900)
    assert nominal_run["status"] == "completed", nominal_run
    assert leaking_run["status"] == "completed", leaking_run

    assert nominal_run["scenario"] == "normal_behaviour" and nominal_run["anomaly_label"] == 0
    assert leaking_run["scenario"] == "leakage" and leaking_run["anomaly_label"] == 1

    filled = _mixing_tank_volume(str(nominal_run["run_id"]))[-1]
    leaked = _mixing_tank_volume(str(leaking_run["run_id"]))[-1]
    assert filled > leaked, f"B204 held {filled:.1f} ml nominally and {leaked:.1f} ml while leaking"


def test_delegation_contract_over_http(sim_runner: httpx.Client) -> None:
    body = [
        {
            "value": {
                "modelType": "Property",
                "idShort": "stopTime",
                "valueType": "xs:double",
                "value": "5",
            }
        },
        {
            "value": {
                "modelType": "Property",
                "idShort": "schedule",
                "valueType": "xs:string",
                "value": "EmbeddedDefault",
            }
        },
    ]
    response = sim_runner.post("/invoke/run", json=body)
    assert response.status_code == 200, response.text
    outputs = {v["value"]["idShort"]: v["value"]["value"] for v in response.json()}
    assert outputs["status"] == "queued"
    final = _wait(sim_runner, outputs["runId"])
    assert final["status"] == "completed"
    status = sim_runner.post(
        "/invoke/status",
        json=[{"value": {"modelType": "Property", "idShort": "runId", "value": outputs["runId"]}}],
    ).json()
    values = {v["value"]["idShort"]: v["value"]["value"] for v in status}
    assert values["status"] == "completed" and values["progress"] == "1.0"


def _reference_on_grid(variables: list[str]) -> dict[str, dict[int, float]]:
    with REFERENCE_RAW.open(newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        index = {name: header.index(name) for name in ["time", *variables]}
        out: dict[str, dict[int, float]] = {v: {} for v in variables}
        for row in reader:
            t = float(row[index["time"]])
            if abs(t - round(t)) < 1e-9:
                for v in variables:
                    out[v][round(t)] = float(row[index[v]])
    return out


def test_openmodelica_reproduces_the_published_result(signals: SignalDictionary) -> None:
    """The published result = IDA + the embedded actuator table (design §6.2, deviation D6).

    Explicitly against the *upstream* model version: this asserts a property of the benchmark,
    not of the twin's own fault-capable derivative.

    States (tank volumes, levels), valve openings, flows and temperatures must agree at every
    whole second. Pressures are compared by their median deviation: below a closed valve the
    pipe is a dead leg whose trapped pressure depends on the solver's path through the
    switching event — the reference itself dips to 33 kPa absolute at t = 87 s — so the
    instantaneous values there are not reproducible by any solver, including the original.
    """
    if not REFERENCE_RAW.is_file():
        pytest.skip("raw reference result absent — rerun scripts/fetch_benchmark.py")
    try:
        runner = OmRunner(OM_WORKER, model=UPSTREAM_MODEL)
    except Exception:
        pytest.skip("OpenModelica worker not reachable — docker compose up -d")
    mapping = build_channel_mapping(signals, sorted(runner.variable_names()))
    schedule = ActuatorSchedule.from_table("EmbeddedDefault", load_modelica_model().actuator_table)
    result = runner.run(
        SimulationRequest(schedule=schedule, outputs=mapping.variables, stop_time=100.0)
    )
    ours: dict[str, dict[int, float]] = {v: {} for v in mapping.variables}
    for k, t in enumerate(result.time_s):
        if abs(t - round(t)) < 1e-9:
            for v in mapping.variables:
                ours[v][round(t)] = result.variables[v][k]
    reference = _reference_on_grid(list(mapping.variables))

    for variable in mapping.variables:
        common = sorted(set(ours[variable]) & set(reference[variable]))
        assert len(common) >= 80, variable
        deviations = sorted(abs(ours[variable][t] - reference[variable][t]) for t in common)
        if variable.endswith(".p"):
            assert deviations[len(deviations) // 2] <= 10.0, f"{variable}: median {deviations}"
            continue
        scale = max(abs(reference[variable][t]) for t in common) or 1.0
        tolerance = 0.0 if variable.endswith(".opening") else 1e-3
        assert deviations[-1] / scale <= tolerance, f"{variable}: {deviations[-1] / scale:.2e}"


# --- step 8: driving the plant from the dashboard ----------------------------------------


def test_a_recorded_runs_actuators_can_be_replayed(sim_runner: httpx.Client) -> None:
    """Capability 2 of design §12: the commands the plant was given become a schedule."""
    plan = httpx.get(f"{API}/api/runs/dataset_10_leakage/schedule", timeout=60).json()
    assert plan["source_run"] == "dataset_10_leakage"
    # A real run switches far more than the 30 rows the literal table could hold — that limit
    # is what deviation D9 removed.
    assert len(plan["rows"]) > 30
    assert all(set(row) >= {"time", "V201", "P201"} for row in plan["rows"])
    assert plan["rows"][0]["time"] == 0.0
    # The tanks start where the recording started, or the replay diverges immediately.
    assert set(plan["initial_state"]) == {f"tank_B20{i}_level_start" for i in (1, 2, 3, 4)}
    assert all(0.0 <= level <= 0.35 for level in plan["initial_state"].values())
    assert any("switching points" in note for note in plan["notes"])


def test_a_schedule_longer_than_the_old_limit_runs(sim_runner: httpx.Client) -> None:
    """Capability 3: an authored schedule of any length, straight from the dashboard."""
    rows = [
        {"time": float(second), "V201": float(second % 20 < 10), "P201": float(second % 20 < 10)}
        for second in range(0, 40, 2)
    ]
    assert len(rows) > 15
    submitted = sim_runner.post(
        "/runs",
        json={"stop_time": 20, "schedule": rows, "label": "authored schedule"},
    )
    assert submitted.status_code == 202, submitted.text
    final = _wait(sim_runner, submitted.json()["run_id"], timeout_s=900)
    assert final["status"] == "completed", final


def test_a_control_rule_holds_a_tank_at_its_threshold(sim_runner: httpx.Client) -> None:
    """Capability 4: the rule, not the schedule, decides what V204 does.

    The recorded run's commands alone overfill B201 in the model — the plant's own level
    supervision is not part of a replayed command sequence — so this is both the feature and
    the fix for it.
    """
    plan = httpx.get(f"{API}/api/runs/dataset_10_leakage/schedule", timeout=60).json()
    rows = [row for row in plan["rows"] if row["time"] <= 120]
    submitted = sim_runner.post(
        "/runs",
        json={
            "stop_time": 120,
            "model": FAULTCAPABLE_MODEL,
            "schedule": rows,
            "parameter_overrides": plan["initial_state"],
            "control_rules": [
                {
                    "actuator": "V204",
                    "signal": "Tank_B201_Volume",
                    "on_below": 500.0,
                    "off_above": 2000.0,
                }
            ],
            "label": "replay under a level rule",
        },
    )
    assert submitted.status_code == 202, submitted.text
    run_id = submitted.json()["run_id"]
    final = _wait(sim_runner, run_id, timeout_s=900)
    assert final["status"] == "completed", final

    series = httpx.get(
        f"{API}/api/timeseries",
        params={"run_id": run_id, "channels": "Tank_B201_Volume"},
        timeout=60,
    ).json()
    volumes = [v for v in series["channels"]["Tank_B201_Volume"] if v is not None]
    # The rule closes V204 above 2000 ml, so B201 never approaches its 3149 ml brim.
    assert max(volumes) <= 2100, max(volumes)
    assert max(volumes) > 1500  # …and it did fill, so the rule is holding a level, not blocking


def test_a_rule_reads_the_signal_it_names_and_holds_from_t0(sim_runner: httpx.Client) -> None:
    """A one-sided rule on a signal that is not bus entry 1, evaluated at t = 0.

    Two defects hid behind the first rule test using ``Tank_B201_Volume`` (entry 1): a
    parameter used as an array subscript is compiled in, so every rule read entry 1; and a
    ``when`` clause never fires on the initial value. P201 must run from t = 0 (B204 starts
    below the threshold) and stop for good once B204 holds 3000 ml.
    """
    submitted = sim_runner.post(
        "/runs",
        json={
            "stop_time": 60,
            "model": FAULTCAPABLE_MODEL,
            "schedule": "EmbeddedDefault",
            "control_rules": [
                {"actuator": "P201", "signal": "Tank_B204_Volume", "off_above": 3000.0}
            ],
            "label": "P201 off above 3000 ml in B204",
        },
    )
    assert submitted.status_code == 202, submitted.text
    run_id = submitted.json()["run_id"]
    final = _wait(sim_runner, run_id, timeout_s=900)
    assert final["status"] == "completed", final

    series = httpx.get(
        f"{API}/api/timeseries",
        params={"run_id": run_id, "channels": "Tank_B204_Volume,Pump_P201_active"},
        timeout=60,
    ).json()
    pump = series["channels"]["Pump_P201_active"]
    volume = series["channels"]["Tank_B204_Volume"]
    assert pump[0] == 1.0  # the rule, not the schedule (P201 is off until 9.8 s there)
    assert pump[-1] == 0.0 and max(volume) < 3300, (pump[-1], max(volume))


def test_rules_are_refused_where_the_model_cannot_honour_them(sim_runner: httpx.Client) -> None:
    rejected = sim_runner.post(
        "/runs",
        json={
            "stop_time": 5,
            "model": UPSTREAM_MODEL,
            "control_rules": [{"actuator": "V204", "signal": "Tank_B201_Volume", "on_below": 500}],
        },
    )
    assert rejected.status_code == 422 and "two-point control" in rejected.text
