"""Simulation layer: schedules (D1/D2), channel mapping (D5), runner contract, sim-runner service.

Everything here runs without an FMU or OpenModelica: the runner is a fake that returns a
synthetic trajectory. The real runners are exercised by the integration tests.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aas_fluid_twin import config
from aas_fluid_twin.benchmark.modelica import load_modelica_model
from aas_fluid_twin.benchmark.signals import SignalDictionary
from aas_fluid_twin.simulation.mapping import build_channel_mapping
from aas_fluid_twin.simulation.runner import (
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
    JobStore,
    RunSpec,
    create_app,
    operation_variables,
    parse_operation_variables,
)
from aas_fluid_twin.store.models import RunRecord, SampleRow

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


def test_short_schedule_is_padded_with_increasing_times() -> None:
    schedule = ActuatorSchedule("s", (ScheduleRow(0.0, {"V201": 1.0}), ScheduleRow(10.0, {})))
    table = schedule.table()
    assert len(table) == TABLE_ROWS
    times = [row[0] for row in table]
    assert times == sorted(times) and len(set(times)) == TABLE_ROWS
    assert all(row[1:] == table[1][1:] for row in table[1:])
    values = schedule.start_values()
    assert values["ActuatorControl.table[1,2]"] == 1.0
    assert len(values) == TABLE_ROWS * len(TABLE_COLUMNS)


def test_long_schedule_is_refused_not_truncated() -> None:
    """Deviation D2: upstream silently keeps the first 30 rows."""
    rows = tuple(ScheduleRow(float(i), {}) for i in range(TABLE_ROWS + 1))
    with pytest.raises(ValueError, match="31 rows"):
        ActuatorSchedule("too long", rows)


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

    def variable_names(self) -> frozenset[str]:
        return frozenset({"tank_B201.V", "PI251.p", "tank_B201.level_start", *_table_names()})

    def parameter_names(self) -> frozenset[str]:
        return frozenset({"tank_B201.level_start", *_table_names()})

    def run(self, request: SimulationRequest) -> SimulationResult:
        self.requests.append(request)
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
