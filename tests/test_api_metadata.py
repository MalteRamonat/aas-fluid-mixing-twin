"""The dashboard's metadata comes from the AAS — these tests prove it, on the real submodels.

Rather than hand-written fixtures, the parsers here are fed the JSON the builders actually
produce, so a change to the AssetInterfacesDescription or SimulationControl layout that would
strip the dashboard of its labels fails here instead of in a browser.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from basyx.aas import model
from basyx.aas.adapter.json import AASToJsonEncoder
from fastapi.testclient import TestClient

from aas_fluid_twin.aas.builders.asset_interfaces import SUBMODEL_ID as AID_SUBMODEL_ID
from aas_fluid_twin.aas.builders.simulation_control import SUBMODEL_ID as CONTROL_SUBMODEL_ID
from aas_fluid_twin.aas.builders.simulation_models import (
    SUBMODEL_ID as SIMULATION_MODELS_SUBMODEL_ID,
)
from aas_fluid_twin.aas.environment import BuiltEnvironment
from aas_fluid_twin.aas.semantics import channel_concept
from aas_fluid_twin.api.aas_metadata import (
    AasMetadata,
    AasUnavailableError,
    ChannelInfo,
    SimulationConfig,
    _parse_channels,
    _parse_simulation,
)
from aas_fluid_twin.api.app import create_app
from aas_fluid_twin.api.simulations import SimRunner
from aas_fluid_twin.benchmark.signals import SignalDictionary

pytestmark = pytest.mark.benchmark_data


def as_json(obj: model.Referable | model.Identifiable) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(json.dumps(obj, cls=AASToJsonEncoder))
    return payload


@pytest.fixture(scope="module")
def channels(env: BuiltEnvironment, signals: SignalDictionary) -> list[ChannelInfo]:
    interface = as_json(env.submodels[AID_SUBMODEL_ID])
    concepts = {c.id: as_json(c) for c in (channel_concept(s) for s in signals)}
    return _parse_channels(interface, concepts)


def test_every_recorded_channel_is_described(
    channels: list[ChannelInfo], signals: SignalDictionary
) -> None:
    assert {c.channel for c in channels} == {s.channel for s in signals}


def test_channel_metadata_comes_from_the_concept_description(channels: list[ChannelInfo]) -> None:
    volume = next(c for c in channels if c.channel == "Tank_B204_Volume")
    assert volume.title == "Tank B204 Volume"
    assert volume.unit == "ml"  # the IEC 61360 unit, not the UN/CEFACT code
    assert volume.data_type == "number"
    assert volume.role == "sensor"
    assert volume.definition and "B204" in volume.definition


def test_actuators_are_marked_as_such(channels: list[ChannelInfo]) -> None:
    valve = next(c for c in channels if c.channel == "Valve_V201_opening")
    assert valve.role == "actuator" and valve.data_type == "boolean"


def test_unreliable_pressure_channels_carry_their_qualifier(channels: list[ChannelInfo]) -> None:
    """N5/D5: the dashboard must be able to warn about these, so the flag has to survive."""
    pressure = next(c for c in channels if c.channel == "Pressure_below_B201")
    assert pressure.quality == "unreliable"
    assert pressure.quality_reason
    assert (pressure.minimum, pressure.maximum) == (0.0, 100.0)


def test_instrument_span_and_node_id_survive(channels: list[ChannelInfo]) -> None:
    flow = next(c for c in channels if c.channel == "Flow_after_Pump_P201")
    assert (flow.minimum, flow.maximum) == (0.1, 25.0)
    assert flow.node_id and flow.node_id.startswith("ns=")


def test_simulation_config_is_read_from_the_control_submodel(env: BuiltEnvironment) -> None:
    config = _parse_simulation(
        as_json(env.submodels[CONTROL_SUBMODEL_ID]),
        as_json(env.submodels[SIMULATION_MODELS_SUBMODEL_ID]),
    )
    handles = {p.id_short: p for p in config.parameters if p.fault_role}
    assert set(handles) == {
        "V211_opening",
        "V212_opening",
        "V210_opening",
        "V211_return_to_B201",
    }
    # The name the runner sets must be the Modelica parameter, not the idShort by accident.
    assert handles["V211_opening"].name == "V211_opening"
    assert handles["V211_opening"].default == 0.0
    assert (handles["V211_opening"].minimum, handles["V211_opening"].maximum) == (0.0, 1.0)
    assert handles["V211_return_to_B201"].default is False

    assert {s.id_short for s in config.schedules} == {"EmbeddedDefault", "BenchmarkMatrix"}
    assert config.operation_defaults["solver"] == "ida"  # deviation D6
    assert "mo-faultcapable" in {v.version_id for v in config.model_versions}


# --- the endpoints ---------------------------------------------------------------------


class FakeMetadata(AasMetadata):
    def __init__(
        self,
        channels: list[ChannelInfo],
        simulation: SimulationConfig | None = None,
        fail: bool = False,
    ) -> None:
        super().__init__("http://aas.invalid", "http://ui.invalid")
        self._fake_channels: tuple[ChannelInfo, ...] = tuple(channels)
        self._fake_simulation: SimulationConfig | None = simulation
        self._fail = fail

    def channels(self) -> tuple[ChannelInfo, ...]:
        if self._fail:
            raise AasUnavailableError("repository is down")
        return self._fake_channels

    def simulation(self) -> SimulationConfig:
        if self._fail or self._fake_simulation is None:
            raise AasUnavailableError("repository is down")
        return self._fake_simulation


class FakeRunner(SimRunner):
    def __init__(self) -> None:
        super().__init__("http://runner.invalid", invoke_mode="direct")
        self.submitted: list[dict[str, Any]] = []

    def health(self) -> dict[str, Any]:
        return {
            "status": "UP",
            "runner": "openmodelica",
            "model": "ModVA_faultcapable",
            "models": ["ModVA_faultcapable", "ModVA_online_stable"],
            "schedules": ["EmbeddedDefault"],
        }

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.submitted.append(payload)
        return {"run_id": "sim_test", "status": "queued", "submitted_via": "direct"}

    def runs(self) -> list[dict[str, Any]]:
        return []

    def run(self, run_id: str) -> dict[str, Any]:
        return {"run_id": run_id, "status": "completed", "progress": 1.0}


#: Every client fixture registers its runner here, so a test can see what was submitted.
FAKE_RUNNERS: list[FakeRunner] = []


@pytest.fixture
def client(env: BuiltEnvironment, channels: list[ChannelInfo]) -> TestClient:
    simulation = _parse_simulation(
        as_json(env.submodels[CONTROL_SUBMODEL_ID]),
        as_json(env.submodels[SIMULATION_MODELS_SUBMODEL_ID]),
    )
    runner = FakeRunner()
    FAKE_RUNNERS.append(runner)
    app = create_app(
        store=None,
        metadata=FakeMetadata(channels, simulation),
        sim_runner=runner,
        serve_dashboard=False,
    )
    return TestClient(app)


def test_channels_endpoint_serves_the_aas_view(client: TestClient) -> None:
    body = client.get("/api/channels").json()
    assert len(body) == 47
    volume = next(c for c in body if c["channel"] == "Tank_B204_Volume")
    assert volume["unit"] == "ml" and volume["title"] == "Tank B204 Volume"


def test_channels_endpoint_reports_an_unreachable_repository(env: BuiltEnvironment) -> None:
    app = create_app(
        store=None,
        metadata=FakeMetadata([], fail=True),
        sim_runner=FakeRunner(),
        serve_dashboard=False,
    )
    response = TestClient(app).get("/api/channels")
    assert response.status_code == 503 and "down" in response.json()["detail"]


def test_simulation_config_merges_the_aas_and_the_runner(client: TestClient) -> None:
    body = client.get("/api/simulation/config").json()
    assert body["models"] == ["ModVA_faultcapable", "ModVA_online_stable"]
    assert body["default_model"] == "ModVA_faultcapable"
    assert body["runnable_schedules"] == ["EmbeddedDefault"]
    assert body["invoke_mode"] == "direct"
    assert any(p["fault_role"] == "leakage" for p in body["parameters"])


def test_starting_a_run_passes_the_dashboard_form_through(client: TestClient) -> None:
    response = client.post(
        "/api/simulations",
        json={"stop_time": 60, "parameter_overrides": {"V211_opening": 0.3}, "label": "leak"},
    )
    assert response.status_code == 202
    assert response.json()["run_id"] == "sim_test"
    runner = FAKE_RUNNERS[-1]
    assert runner.submitted[-1]["parameter_overrides"] == {"V211_opening": 0.3}
    assert runner.submitted[-1]["stop_time"] == 60


def test_a_run_request_is_validated_before_it_reaches_the_runner(client: TestClient) -> None:
    assert client.post("/api/simulations", json={"stop_time": 0}).status_code == 422
    assert client.post("/api/simulations", json={"stop_time": 99999}).status_code == 422


def test_aas_links_point_at_the_submodels(client: TestClient) -> None:
    body = client.get("/api/aas").json()
    assert body["web_ui"] == "http://ui.invalid"
    assert body["submodels"]["plant_time_series"].endswith("/TimeSeries/001")
    assert "simulation_control" in body["submodels"]
