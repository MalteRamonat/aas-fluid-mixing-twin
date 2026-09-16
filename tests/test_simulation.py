"""Simulation layer: schedules (D1/D2), channel mapping (D5), runner contract, sim-runner service.

Everything here runs without an FMU or OpenModelica: the runner is a fake that returns a
synthetic trajectory. The real runners are exercised by the integration tests.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable, Sequence
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aas_fluid_twin import config
from aas_fluid_twin.benchmark.modelica import load_modelica_model
from aas_fluid_twin.benchmark.signals import SignalDictionary
from aas_fluid_twin.simulation.mapping import build_channel_mapping
from aas_fluid_twin.simulation.runner import (
    PARAMETER_BOUNDS,
    IntegrationStoppedError,
    SimulationError,
    SimulationRequest,
    SimulationResult,
    resolve_parameters,
)
from aas_fluid_twin.simulation.schedule import (
    ACTUATORS,
    TABLE_COLUMNS,
    TABLE_ROWS,
    ActuatorSchedule,
    ScheduleRow,
    legacy_upstream_table,
)
from aas_fluid_twin.simulation.service import (
    RETRY_TOLERANCE,
    JobStore,
    RunSpec,
    actuator_channels,
    create_app,
    operation_variables,
    parse_operation_variables,
)
from aas_fluid_twin.store.models import Origin, RunRecord, SampleRow, SeriesResult

BENCHMARK_MATRIX = config.BENCHMARK_DIR / "Simulation_Model_Control"
UPSTREAM_HEADER = "Time,V201,V202,V203,V204,V205,V206,P201,P202"

# --- schedules ---------------------------------------------------------------------------


def _csv(tmp_path: Path, header: str, *rows: str) -> Path:
    path = tmp_path / "schedule.csv"
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


def test_csv_schedule_is_matched_by_name_not_position(tmp_path: Path) -> None:
    """Deviation D1: the CSV says V204, the table column 5 is V206 — we follow the name."""
    schedule = ActuatorSchedule.from_csv(_csv(tmp_path, UPSTREAM_HEADER, "0,0,0,0,1,0,0,1,0"))
    table = schedule.table()
    assert TABLE_COLUMNS.index("V204") == 6 and TABLE_COLUMNS.index("V206") == 4
    assert table[0][TABLE_COLUMNS.index("V204")] == 1.0
    assert table[0][TABLE_COLUMNS.index("V206")] == 0.0
    assert table[0][TABLE_COLUMNS.index("P201")] == 1.0
    assert table[0][TABLE_COLUMNS.index("V209")] == 0.0
    assert schedule.unspecified == ("V209",)


def test_legacy_upstream_layout_shows_the_defect(tmp_path: Path) -> None:
    path = _csv(tmp_path, UPSTREAM_HEADER, "0,0,0,0,1,0,0,1,0")
    embedded = [[float(i), *([0.0] * 8), 0.5] for i in range(TABLE_ROWS)]
    table = legacy_upstream_table(path, embedded)
    assert table[0][TABLE_COLUMNS.index("V206")] == 1.0  # the CSV's V204 lands on V206
    assert table[0][TABLE_COLUMNS.index("V209")] == 1.0  # the CSV's P201 lands on V209
    assert table[0][TABLE_COLUMNS.index("P202")] == 0.5  # column 10 keeps the embedded value
    assert len(table) == TABLE_ROWS and table[-1][0] == 0.0  # padded by repeating the row


def test_a_schedule_keeps_exactly_the_rows_it_was_given() -> None:
    schedule = ActuatorSchedule("s", (ScheduleRow(0.0, {"V201": 1.0}), ScheduleRow(10.0, {})))
    table = schedule.table()
    assert len(table) == 2
    assert table[0][TABLE_COLUMNS.index("V201")] == 1.0
    assert table[1][TABLE_COLUMNS.index("V201")] == 0.0
    values = schedule.start_values()
    assert values["ActuatorControl.table[1,2]"] == 1.0
    assert len(values) == TABLE_ROWS * len(TABLE_COLUMNS)


def test_a_schedule_may_be_longer_than_the_literal_table() -> None:
    """Deviation D9: the fault-capable model reads its table from a file, so length is data."""
    rows = tuple(ScheduleRow(float(i), {"V201": float(i % 2)}) for i in range(120))
    schedule = ActuatorSchedule("recorded replay", rows)
    table = schedule.table()
    assert len(table) == 120
    assert [row[0] for row in table] == [float(i) for i in range(120)]


def test_a_long_schedule_is_refused_by_a_fixed_table_model_not_truncated() -> None:
    """Deviation D2: upstream silently keeps the first 30 rows; here it is an error."""
    rows = tuple(ScheduleRow(float(i), {}) for i in range(TABLE_ROWS + 1))
    with pytest.raises(ValueError, match="31"):
        ActuatorSchedule("too long", rows).as_fixed_table()


def test_a_short_schedule_still_fills_a_fixed_table() -> None:
    schedule = ActuatorSchedule("s", (ScheduleRow(0.0, {"V201": 1.0}), ScheduleRow(10.0, {})))
    padded = schedule.as_fixed_table()
    assert len(padded) == TABLE_ROWS
    times = [row[0] for row in padded]
    assert times == sorted(times) and len(set(times)) == TABLE_ROWS


@pytest.mark.parametrize(
    "rows",
    [
        (ScheduleRow(5.0, {}), ScheduleRow(5.0, {})),
        (ScheduleRow(0.0, {"V299": 1.0}),),
    ],
)
def test_invalid_schedules_raise(rows: tuple[ScheduleRow, ...]) -> None:
    with pytest.raises(ValueError):
        ActuatorSchedule("bad", rows)


def test_inline_json_schedule_round_trips() -> None:
    schedule = ActuatorSchedule.from_json(
        json.dumps([{"time": 0, "P201": 1}, {"time": 30, "V201": 1}])
    )
    assert schedule.unspecified == tuple(a for a in ACTUATORS if a not in ("P201", "V201"))
    again = ActuatorSchedule.from_json(json.dumps(schedule.to_json()))
    assert again.table() == schedule.table()


@pytest.mark.benchmark_data
def test_embedded_table_and_benchmark_matrix_load() -> None:
    if not config.MODELICA_FILE.is_file():
        pytest.skip("benchmark data absent")
    embedded = ActuatorSchedule.from_table("EmbeddedDefault", load_modelica_model().actuator_table)
    assert len(embedded.rows) == 30 and embedded.end_time == 600.0
    (matrix,) = sorted(BENCHMARK_MATRIX.glob("ActuatorControlMatrix_*.csv"))
    benchmark = ActuatorSchedule.from_csv(matrix)
    assert len(benchmark.rows) == 11 and benchmark.unspecified == ("V209",)


# --- channel mapping -----------------------------------------------------------------------


@pytest.mark.benchmark_data
def test_mapping_renames_and_converts_units(signals: SignalDictionary) -> None:
    available = ["tank_B201.V", "PI251.p", "TI261.T", "FI271.V_flow", "V201.opening"]
    mapping = build_channel_mapping(signals, available)
    assert set(mapping.variables) == set(available)
    out = mapping.convert(
        {
            "tank_B201.V": [0.002],
            "PI251.p": [101_000.0],
            "TI261.T": [293.15],
            "FI271.V_flow": [1 / 60_000],
            "V201.opening": [1.0],
        }
    )
    assert out["Tank_B201_Volume"] == pytest.approx([2000.0])  # m3 -> ml
    assert out["Pressure_below_B201"] == pytest.approx([1.0])  # Pa abs -> kPa gauge (D5)
    assert out["Tempreature_before_Pump_P201"] == pytest.approx([20.0])  # K -> °C (D5)
    assert out["Flow_after_Pump_P201"] == pytest.approx([1.0])  # m3/s -> l/min
    assert out["Valve_V201_opening"] == [1.0]
    assert not any(c.startswith("Level_switch") for c in mapping.channels)


# --- runner contract ---------------------------------------------------------------------


def test_parameter_resolution_maps_id_shorts_and_rejects_unsupported() -> None:
    settable = frozenset({"tank_B201.level_start", "P201_head_max", "ActuatorControl.table[1,1]"})
    resolved = resolve_parameters({"tank_B201_level_start": 0.2, "P201_head_max": 3.0}, settable)
    assert resolved == {"tank_B201.level_start": 0.2, "P201_head_max": 3.0}
    with pytest.raises(SimulationError, match="V211_opening"):
        resolve_parameters({"V211_opening": 0.5}, settable)


def test_a_handle_outside_its_declared_range_is_refused_with_a_reason() -> None:
    """A shut throttle (V212 = 0) cannot be initialised; better a 422 than an empty result."""
    settable = frozenset({"V212_opening", "V211_opening", "V210_opening"})
    low, high = PARAMETER_BOUNDS["V212_opening"]
    assert resolve_parameters({"V212_opening": low}, settable) == {"V212_opening": low}
    with pytest.raises(SimulationError, match=r"V212_opening.*outside its range"):
        resolve_parameters({"V212_opening": 0.0}, settable)
    with pytest.raises(SimulationError, match="outside its range"):
        resolve_parameters({"V210_opening": high + 0.5}, settable)


def test_request_validates_time_window() -> None:
    schedule = ActuatorSchedule("s", (ScheduleRow(0.0, {}),))
    with pytest.raises(ValueError):
        SimulationRequest(schedule=schedule, outputs=("x",), start_time=10, stop_time=5)


# --- the service -------------------------------------------------------------------------


def _table_names() -> list[str]:
    return [f"ActuatorControl.table[{i},{j}]" for i in range(1, 31) for j in range(1, 11)]


class FakeRunner:
    """Returns a ramp on every requested variable; records what it was asked."""

    name = "fake"
    model_name = "FakeModel"

    def __init__(self) -> None:
        self.requests: list[SimulationRequest] = []
        self.control_capable = True
        self.survives_tolerance = 1.0  # a run at a looser tolerance than this stops early

    def variable_names(self) -> frozenset[str]:
        return frozenset({"tank_B201.V", "PI251.p", "tank_B201.level_start", *_table_names()})

    def parameter_names(self) -> frozenset[str]:
        names = {"tank_B201.level_start", *_table_names()}
        if self.control_capable:
            names |= {
                f"ctrl_{field}[{i}]"
                for field in ("mode", "source", "on_below", "off_above", "invert")
                for i in range(1, len(ACTUATORS) + 1)
            }
        return frozenset(names)

    def run(self, request: SimulationRequest) -> SimulationResult:
        self.requests.append(request)
        if request.tolerance > self.survives_tolerance:
            raise IntegrationStoppedError("fake: ida stopped at t = 102.2 s", reached=102.2)
        n = int((request.stop_time - request.start_time) / request.output_interval) + 1
        time_s = [request.start_time + i * request.output_interval for i in range(n)]
        return SimulationResult(
            time_s=time_s,
            variables={v: [float(i) for i in range(n)] for v in request.outputs},
            runner=self.name,
            model=self.model_name,
            wall_time_s=0.01,
        )


class RecordingStore:
    """A store that remembers what was written and can read it back, like the real one."""

    def __init__(self) -> None:
        self.records: list[RunRecord] = []
        self.samples: list[SampleRow] = []
        self.labels: list[tuple[float, int]] = []

    def write_run(
        self, record: RunRecord, samples: Iterable[SampleRow], labels: Iterable[tuple[float, int]]
    ) -> int:
        self.records.append(record)
        self.samples.extend(samples)
        self.labels.extend(labels)
        return len(self.samples)

    def list_runs(self, origin: Origin | None = None) -> list[RunRecord]:
        return [r for r in self.records if origin is None or r.origin is origin]

    def get_run(self, run_id: str) -> RunRecord | None:
        return next((r for r in self.records if r.run_id == run_id), None)

    def channels(self, run_id: str) -> list[str]:
        return sorted({s.channel for s in self.samples})

    def query(
        self,
        run_id: str,
        channels: Sequence[str] | None = None,
        *,
        from_s: float | None = None,
        to_s: float | None = None,
    ) -> SeriesResult | None:
        record = self.get_run(run_id)
        if record is None:
            return None
        times = sorted({s.t_rel_s for s in self.samples})
        wanted = list(channels) if channels else self.channels(run_id)
        by_key = {(s.channel, s.t_rel_s): s.value for s in self.samples}
        return SeriesResult(
            run_id=run_id,
            origin=record.origin,
            t_rel_s=times,
            timestamps=[record.started_at for _ in times],
            labels=[record.anomaly_label for _ in times],
            channels={name: [by_key.get((name, t)) for t in times] for name in wanted},
        )


Service = tuple[TestClient, FakeRunner, RecordingStore]


def client_of(service: Service) -> TestClient:
    return service[0]


@pytest.fixture
def service(signals: SignalDictionary) -> Service:
    runner = FakeRunner()
    store = RecordingStore()
    mapping = build_channel_mapping(signals, sorted(runner.variable_names()))
    schedules = {"EmbeddedDefault": ActuatorSchedule("EmbeddedDefault", (ScheduleRow(0.0, {}),))}
    jobs = JobStore(
        runners={runner.model_name: runner},
        mappings={runner.model_name: mapping},
        schedules=schedules,
        store=store,
        basyx=None,
        timeseries_endpoint="http://localhost:8000/api/timeseries",
    )
    return TestClient(create_app(jobs)), runner, store


def _wait(client: TestClient, run_id: str, timeout_s: float = 5.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        body = client.get(f"/runs/{run_id}").json()
        if body["status"] in ("completed", "failed"):
            return dict(body)
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not finish")


@pytest.mark.benchmark_data
def test_a_run_that_stops_early_is_retried_once_at_a_tighter_tolerance(service: Service) -> None:
    """IDA gives up on some rule runs at 1e-5 and survives at 1e-6: retry once, and say so."""
    client, runner, store = service
    runner.survives_tolerance = 1e-6
    run_id = client.post("/runs", json={"stop_time": 10}).json()["run_id"]
    final = _wait(client, run_id)
    assert final["status"] == "completed", final
    assert [r.tolerance for r in runner.requests] == [1e-5, RETRY_TOLERANCE]
    assert "retry with tolerance 1e-06" in str(final["note"])
    assert final["spec"]["tolerance"] == RETRY_TOLERANCE  # what the stored run says it ran at
    assert store.records[-1].params["note"] == final["note"]

    # Only once: a run that also fails at the tighter tolerance fails.
    runner.survives_tolerance = 1e-9
    run_id = client.post("/runs", json={"stop_time": 10}).json()["run_id"]
    final = _wait(client, run_id)
    assert final["status"] == "failed" and "stopped at t = 102.2" in str(final["error"])


@pytest.mark.benchmark_data
def test_delegated_operation_contract(service: Service) -> None:
    client, runner, store = service
    inputs = operation_variables(
        {
            "startTime": "0",
            "stopTime": "10",
            "solver": "cvode",
            "tolerance": "1e-5",
            "schedule": "EmbeddedDefault",
            "parameterOverrides": json.dumps({"tank_B201_level_start": 0.2}),
        }
    )
    response = client.post("/invoke/run", json=inputs)
    assert response.status_code == 200, response.text
    outputs = parse_operation_variables(response.json())
    assert set(outputs) == {"runId", "status"} and outputs["status"] == "queued"
    run_id = outputs["runId"]

    final = _wait(client, run_id)
    assert final["status"] == "completed", final
    status = client.post("/invoke/status", json=operation_variables({"runId": run_id})).json()
    values = parse_operation_variables(status)
    assert values["status"] == "completed" and float(values["progress"]) == 1.0
    assert values["segmentIdShort"] == ""  # no AAS configured in this test

    (request,) = runner.requests
    assert request.parameters == {"tank_B201.level_start": 0.2}
    assert request.stop_time == 10.0 and len(request.outputs) == 2
    (record,) = store.records
    assert record.origin.value == "simulated" and record.record_count == 11
    assert record.params is not None
    assert record.params["parameter_overrides"] == {"tank_B201_level_start": 0.2}
    assert {s.channel for s in store.samples} == {"Tank_B201_Volume", "Pressure_below_B201"}
    assert store.labels == [(float(t), 0) for t in range(11)]


@pytest.mark.benchmark_data
def test_fault_handle_on_upstream_model_is_refused(service: Service) -> None:
    client, _, _ = service
    response = client.post(
        "/runs", json={"stop_time": 5, "parameter_overrides": {"V211_opening": 0.3}}
    )
    assert response.status_code == 422 and "V211_opening" in response.json()["detail"]


@pytest.mark.benchmark_data
def test_inline_schedule_and_unknown_schedule(service: Service) -> None:
    client, runner, _ = service
    assert client.post("/runs", json={"schedule": "Nope"}).status_code == 422
    accepted = client.post(
        "/runs", json={"stop_time": 3, "schedule": [{"time": 0, "P201": 1}, {"time": 2}]}
    )
    assert accepted.status_code == 202
    final = _wait(client, accepted.json()["run_id"])
    assert final["status"] == "completed"
    assert runner.requests[-1].schedule.rows[0].value("P201") == 1.0


def test_unknown_model_is_refused(service: Service) -> None:
    response = client_of(service).post("/runs", json={"model": "ModVA_nonexistent"})
    assert response.status_code == 422 and "ModVA_nonexistent" in response.json()["detail"]


def test_health_lists_the_models_it_can_run(service: Service) -> None:
    body = client_of(service).get("/health").json()
    assert body["models"] == ["FakeModel"] and body["model"] == "FakeModel"


@pytest.mark.benchmark_data
def test_a_request_can_be_checked_without_running_it(service: Service) -> None:
    """The AAS path needs this: BaSyx relays a delegated failure's code, never its reason."""
    client, runner, _ = service
    assert client.post("/runs/validate", json={"stop_time": 10}).status_code == 204

    rejected = client.post(
        "/runs/validate", json={"stop_time": 10, "parameter_overrides": {"V211_opening": 0.3}}
    )
    assert rejected.status_code == 422 and "V211_opening" in rejected.json()["detail"]
    assert client.post("/runs/validate", json={"schedule": "Nope"}).status_code == 422
    assert client.post("/runs/validate", json={"model": "Nope"}).status_code == 422

    # Checking is not running.
    assert runner.requests == []
    assert client.get("/runs").json() == []


@pytest.mark.benchmark_data
def test_a_recorded_runs_commands_become_a_schedule(signals: SignalDictionary) -> None:
    """Capability 2 of design §12: replay what the plant's actuators actually did."""
    mapping = actuator_channels(signals)
    assert mapping["Valve_V201_opening"] == "V201"
    assert mapping["Pump_P201_active"] == "P201"  # through P201_Characteristic.u
    assert "Mixer_R201_of_B204_active" not in mapping  # the stirrer is not modelled

    # Two valves, sampled unevenly, each switching twice — plus a gap the reader must carry.
    times = [0.0, 1.6, 3.2, 4.8, 6.4, 8.0]
    columns: dict[str, list[float | None]] = {
        "Valve_V201_opening": [0.0, 1.0, 1.0, None, 0.0, 0.0],
        "Pump_P201_active": [0.0, 1.0, 1.0, 1.0, 0.0, 0.0],
    }
    schedule, notes = ActuatorSchedule.from_recorded("replay", times, columns, mapping)
    assert [row.time for row in schedule.rows] == [0.0, 1.6, 6.4]
    assert schedule.rows[1].value("V201") == 1.0 and schedule.rows[1].value("P201") == 1.0
    assert schedule.rows[2].value("V201") == 0.0
    assert any("driven closed" in note for note in notes)  # V202, V203, … were not recorded
    assert any("switching points" in note for note in notes)


@pytest.mark.benchmark_data
def test_a_replayed_schedule_is_longer_than_the_old_limit(
    service: Service, signals: SignalDictionary
) -> None:
    """A real run switches far more than 30 times; that is exactly what D9 unblocked."""
    mapping = actuator_channels(signals)
    times = [float(i) * 1.6 for i in range(200)]
    columns: dict[str, list[float | None]] = {
        "Valve_V201_opening": [float(i % 2) for i in range(200)]
    }
    schedule, _ = ActuatorSchedule.from_recorded("replay", times, columns, mapping)
    assert len(schedule.rows) > 30
    client, runner, _ = service
    accepted = client.post("/runs", json={"stop_time": 5, "schedule": schedule.to_json()})
    assert accepted.status_code == 202
    _wait(client, accepted.json()["run_id"])
    assert len(runner.requests[-1].schedule.rows) == len(schedule.rows)


@pytest.mark.benchmark_data
def test_control_rules_reach_the_model_as_parameters(service: Service) -> None:
    client, runner, _ = service
    accepted = client.post(
        "/runs",
        json={
            "stop_time": 5,
            "control_rules": [
                {
                    "actuator": "V204",
                    "signal": "Tank_B201_Volume",
                    "on_below": 500,
                    "off_above": 2000,
                }
            ],
        },
    )
    assert accepted.status_code == 202
    _wait(client, accepted.json()["run_id"])
    position = ACTUATORS.index("V204") + 1
    parameters = runner.requests[-1].parameters
    assert parameters[f"ctrl_mode[{position}]"] == 1
    assert parameters[f"ctrl_on_below[{position}]"] == pytest.approx(5e-4)  # 500 ml


@pytest.mark.benchmark_data
def test_a_rule_a_model_cannot_honour_is_refused(service: Service) -> None:
    """Better an error than a run that quietly ignores the control law it was given."""
    client, runner, _ = service
    runner.control_capable = False
    response = client.post(
        "/runs",
        json={
            "stop_time": 5,
            "control_rules": [{"actuator": "V204", "signal": "Tank_B201_Volume", "on_below": 500}],
        },
    )
    assert response.status_code == 422 and "two-point control" in response.json()["detail"]


def test_run_spec_parses_operation_inputs() -> None:
    spec = RunSpec.from_operation_inputs(
        {
            "stopTime": "120",
            "schedule": json.dumps([{"time": 0, "V201": 1}]),
            "parameterOverrides": "",
        }
    )
    assert spec.stop_time == 120.0 and isinstance(spec.schedule, list)
    assert spec.parameter_overrides == {}


def test_operation_variables_accept_basyx_wrapper() -> None:
    wrapped = {"inputArguments": operation_variables({"runId": "x"})}
    assert parse_operation_variables(wrapped) == {"runId": "x"}
    with pytest.raises(Exception, match="OperationVariable"):
        parse_operation_variables({"nope": 1})
