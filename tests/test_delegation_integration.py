"""The AAS-native path, end to end: invoke an Operation, get a simulated run out of it.

This is the point of the exercise. A caller who has nothing but the AAS — no knowledge of the
simulation runner, its URL or its JSON — invokes ``RunSimulation`` on the submodel repository;
BaSyx forwards it through the ``invocationDelegation`` qualifier; the runner executes it,
writes the result to the store and appends the segments back to the same AAS.

Needs the whole stack (``docker compose up -d``) and the benchmark data.
"""

from __future__ import annotations

import time

import httpx
import pytest
from basyx.aas.model import datatypes

from aas_fluid_twin.aas.builders._common import prop, prop_typed
from aas_fluid_twin.aas.builders.simulation_control import SUBMODEL_ID as CONTROL_ID
from aas_fluid_twin.aas.builders.time_series import SIMULATION_TIMESERIES_ID
from aas_fluid_twin.client import BasyxClient
from aas_fluid_twin.client.basyx import encode_id, encode_path

pytestmark = [pytest.mark.integration, pytest.mark.benchmark_data]

BASYX = "http://localhost:8081"
API = "http://localhost:8000"

#: Short runs on the upstream model: this test is about the path, not about the physics.
STOP_TIME = 20.0
OUTPUT_INTERVAL = 0.5
MODEL = "ModVA_online_stable"


@pytest.fixture(scope="module")
def basyx() -> BasyxClient:
    client = BasyxClient(BASYX)
    if not client.is_up():
        pytest.skip("BaSyx not reachable — docker compose up -d")
    return client


def _await_status(basyx: BasyxClient, run_id: str, timeout_s: float = 600.0) -> dict[str, str]:
    """Poll through the AAS, not through the runner: GetRunStatus is delegated too."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = basyx.invoke(
            CONTROL_ID, "GetRunStatus", [prop("runId", run_id, None)], timeout_ms=30_000
        )
        outputs = {k: str(v) for k, v in result.outputs.items()}
        if outputs.get("status") in ("completed", "failed") or outputs.get("status", "").startswith(
            "failed"
        ):
            return outputs
        time.sleep(3.0)
    raise AssertionError(f"{run_id} did not finish within {timeout_s} s")


def test_a_run_invoked_through_the_aas_lands_in_the_store_and_back_in_the_aas(
    basyx: BasyxClient,
) -> None:
    label = f"delegation test {time.strftime('%H:%M:%S')}"
    invocation = basyx.invoke(
        CONTROL_ID,
        "RunSimulation",
        [
            prop_typed("stopTime", datatypes.Double, STOP_TIME, None),
            prop_typed("outputInterval", datatypes.Double, OUTPUT_INTERVAL, None),
            prop("solver", "ida", None),
            prop("schedule", "EmbeddedDefault", None),
            prop("model", MODEL, None),
            prop("label", label, None),
            prop("parameterOverrides", "{}", None),
        ],
        timeout_ms=60_000,
    )
    assert invocation.success, invocation.raw
    run_id = str(invocation.outputs["runId"])
    assert run_id.startswith("sim_")
    assert invocation.outputs["status"] in ("queued", "running")

    status = _await_status(basyx, run_id)
    assert status["status"] == "completed", status
    assert status["progress"] == "1.0"
    assert status["segmentIdShort"] == f"Simulated_{run_id}"

    # Every input the operation declares reached the runner — an undeclared or unparsed one
    # would silently fall back to a default here.
    record = httpx.get(f"{API}/api/runs/{run_id}", timeout=30).json()
    assert record["origin"] == "simulated"
    assert record["note"] == label
    assert record["params"]["model"] == MODEL
    assert record["params"]["output_interval"] == OUTPUT_INTERVAL
    assert record["duration_s"] == pytest.approx(STOP_TIME, abs=0.5)

    # …and the result is readable through the LinkedSegment endpoint like any other run.
    series = httpx.get(
        f"{API}/api/timeseries",
        params={"run_id": run_id, "channels": "Tank_B204_Volume"},
        timeout=30,
    ).json()
    assert series["t_rel_s"][-1] == pytest.approx(STOP_TIME, abs=0.5)

    # The AAS now describes the run it was asked to make.
    segments = {
        e["idShort"]
        for e in next(
            s
            for s in basyx.get_submodel_json(SIMULATION_TIMESERIES_ID)["submodelElements"]
            if s["idShort"] == "Segments"
        )["value"]
    }
    assert {f"Simulated_{run_id}", f"Linked_{run_id}"} <= segments
    attachment = httpx.get(
        f"{BASYX}/submodels/{encode_id(SIMULATION_TIMESERIES_ID)}"
        f"/submodel-elements/{encode_path(f'Segments.Simulated_{run_id}.File')}/attachment",
        timeout=30,
    )
    assert attachment.status_code == 200 and attachment.content.startswith(b"Session Time Stamps")

    runs = next(
        e for e in basyx.get_submodel_json(CONTROL_ID)["submodelElements"] if e["idShort"] == "Runs"
    )["value"]
    assert run_id in {r["idShort"] for r in runs}


def test_the_dashboard_uses_the_delegated_path(basyx: BasyxClient) -> None:
    """``SIM_INVOKE_MODE=aas``: the API commands the twin through its own AAS."""
    config = httpx.get(f"{API}/api/simulation/config", timeout=30).json()
    assert config["invoke_mode"] == "aas"
    accepted = httpx.post(
        f"{API}/api/simulations",
        json={"stop_time": 5, "model": MODEL, "schedule": "EmbeddedDefault"},
        timeout=60,
    ).json()
    assert accepted["submitted_via"] == "aas"
    assert accepted["run_id"].startswith("sim_")


def test_an_invalid_request_fails_the_invocation_rather_than_starting_a_run(
    basyx: BasyxClient,
) -> None:
    """A fault handle the upstream model does not have must not silently become a nominal run."""
    before = len(httpx.get(f"{API}/api/simulations", timeout=30).json())
    with pytest.raises(Exception) as error:
        basyx.invoke(
            CONTROL_ID,
            "RunSimulation",
            [
                prop_typed("stopTime", datatypes.Double, 5.0, None),
                prop("model", MODEL, None),
                prop("parameterOverrides", '{"V211_opening": 0.5}', None),
            ],
            timeout_ms=30_000,
        )
    # BaSyx relays the delegate's status code and nothing else, so the invocation itself can
    # only say that something was rejected…
    assert "424" in str(error.value) and "422" in str(error.value)
    # …which is why the API checks with the runner first and reports the actual reason.
    through_api = httpx.post(
        f"{API}/api/simulations",
        json={"stop_time": 5, "model": MODEL, "parameter_overrides": {"V211_opening": 0.5}},
        timeout=60,
    )
    assert through_api.status_code == 422
    assert "V211_opening" in through_api.json()["detail"]
    assert len(httpx.get(f"{API}/api/simulations", timeout=30).json()) == before
