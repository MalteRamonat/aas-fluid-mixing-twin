"""Simulation endpoints: the dashboard's way to start a run and watch it.

The AAS-native path is an ``Operation`` invocation on the ``SimulationControl`` submodel,
which BaSyx forwards to ``sim-runner`` through the ``invocationDelegation`` qualifier
(design §6.1). ``SIM_INVOKE_MODE`` selects it:

* ``aas`` (the default) — this API invokes ``RunSimulation`` on the submodel repository and
  lets the delegation carry it to the runner;
* ``direct`` — this API posts to ``sim-runner`` itself, which is the fallback when the
  repository is unavailable or the delegation feature is switched off.

Either way the *form* the dashboard fills in comes from the AAS: parameter set, ranges, units
and fault roles are read from ``SimulationControl``, never from the local Python model.
"""

from __future__ import annotations

import os
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from aas_fluid_twin.aas.builders.simulation_control import SUBMODEL_ID as CONTROL_SUBMODEL_ID
from aas_fluid_twin.api.aas_metadata import AasMetadata, AasUnavailableError
from aas_fluid_twin.api.metadata import get_metadata
from aas_fluid_twin.api.schemas import (
    SimulationConfigOut,
    SimulationRequestIn,
    model_version_out,
    parameter_out,
    schedule_out,
)
from aas_fluid_twin.client import BasyxClient, BasyxError

__all__ = ["SimRunner", "get_runner", "router"]

router = APIRouter(prefix="/api", tags=["simulation"])


class SimRunner:
    """Thin client for the simulation runner, plus the AAS invocation path."""

    def __init__(
        self,
        base_url: str,
        *,
        invoke_mode: str = "direct",
        basyx_url: str | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.invoke_mode = invoke_mode
        self.basyx_url = basyx_url
        self._http = httpx.Client(base_url=self.base_url, timeout=timeout_s)

    # -- plumbing --

    def _get(self, path: str) -> Any:
        try:
            response = self._http.get(path)
        except httpx.HTTPError as error:
            raise HTTPException(
                status_code=503, detail=f"simulation runner at {self.base_url}: {error}"
            ) from error
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail=response.json().get("detail", "not found"))
        if response.status_code != 200:
            raise HTTPException(status_code=502, detail=f"simulation runner: {response.text}")
        return response.json()

    def health(self) -> dict[str, Any]:
        body: dict[str, Any] = self._get("/health")
        return body

    def runs(self) -> list[dict[str, Any]]:
        body: list[dict[str, Any]] = self._get("/runs")
        return body

    def run(self, run_id: str) -> dict[str, Any]:
        body: dict[str, Any] = self._get(f"/runs/{run_id}")
        return body

    # -- submission --

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.invoke_mode == "aas":
            return self._submit_through_aas(payload)
        try:
            response = self._http.post("/runs", json=payload)
        except httpx.HTTPError as error:
            raise HTTPException(
                status_code=503, detail=f"simulation runner at {self.base_url}: {error}"
            ) from error
        if response.status_code == 422:
            raise HTTPException(status_code=422, detail=response.json().get("detail", "rejected"))
        if response.status_code != 202:
            raise HTTPException(status_code=502, detail=f"simulation runner: {response.text}")
        accepted: dict[str, Any] = response.json()
        accepted["submitted_via"] = "direct"
        return accepted

    def validate(self, payload: dict[str, Any]) -> None:
        """Ask the runner whether it would accept this, and relay its reason if it would not."""
        try:
            response = self._http.post("/runs/validate", json=payload)
        except httpx.HTTPError:
            return  # the invocation below will fail loudly enough on its own
        if response.status_code == 422:
            raise HTTPException(status_code=422, detail=response.json().get("detail", "rejected"))

    def _submit_through_aas(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Invoke ``RunSimulation`` on the submodel repository; BaSyx delegates it onward."""
        if not self.basyx_url:
            raise HTTPException(status_code=503, detail="SIM_INVOKE_MODE=aas needs AAS_BASYX_URL")
        # A delegated failure comes back as "the delegate answered 422" and nothing more, so
        # the reason is fetched from the runner before the command goes through the AAS.
        self.validate(payload)
        import json

        from basyx.aas import model
        from basyx.aas.model import datatypes

        from aas_fluid_twin.aas.builders._common import prop, prop_typed

        inputs: list[model.SubmodelElement] = [
            prop_typed("startTime", datatypes.Double, float(payload.get("start_time", 0.0)), None),
            prop_typed("stopTime", datatypes.Double, float(payload["stop_time"]), None),
            prop("solver", str(payload.get("solver", "ida")), None),
            prop_typed("tolerance", datatypes.Double, float(payload.get("tolerance", 1e-5)), None),
            prop_typed(
                "outputInterval",
                datatypes.Double,
                float(payload.get("output_interval", 1.0)),
                None,
            ),
            prop(
                "schedule",
                (
                    payload["schedule"]
                    if isinstance(payload.get("schedule"), str)
                    else json.dumps(payload.get("schedule"))
                ),
                None,
            ),
            prop("parameterOverrides", json.dumps(payload.get("parameter_overrides") or {}), None),
        ]
        if payload.get("model"):
            inputs.append(prop("model", str(payload["model"]), None))
        if payload.get("label"):
            inputs.append(prop("label", str(payload["label"]), None))
        try:
            with BasyxClient(self.basyx_url) as client:
                result = client.invoke(CONTROL_SUBMODEL_ID, "RunSimulation", inputs)
        except BasyxError as error:
            raise HTTPException(
                status_code=502, detail=f"AAS invocation failed: {error}"
            ) from error
        except Exception as error:
            raise HTTPException(
                status_code=503, detail=f"AAS repository unreachable: {error}"
            ) from error
        values = dict(result.outputs)
        run_id = str(values.get("runId", ""))
        if not run_id:
            raise HTTPException(status_code=502, detail=f"AAS invocation returned {values}")
        # The operation's output variables are a contract, not a data feed: they carry the run
        # id and its state, nothing else. The dashboard wants the whole job, so the accepted
        # run is read back from the runner and only marked with how it was started.
        try:
            accepted = self.run(run_id)
        except HTTPException:
            accepted = {"run_id": run_id, "status": values.get("status", "queued")}
        accepted["submitted_via"] = "aas"
        return accepted


def get_runner(request: Request) -> SimRunner:
    runner: SimRunner | None = getattr(request.app.state, "sim_runner", None)
    if runner is None:
        raise HTTPException(status_code=503, detail="no simulation runner configured")
    return runner


Runner = Annotated[SimRunner, Depends(get_runner)]
Metadata = Annotated[AasMetadata, Depends(get_metadata)]


@router.get("/simulation/config", response_model=SimulationConfigOut)
def simulation_config(runner: Runner, metadata: Metadata) -> SimulationConfigOut:
    """The form the dashboard renders: AAS parameter set + what the runner can actually run."""
    try:
        config = metadata.simulation()
    except AasUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    health = runner.health()
    return SimulationConfigOut(
        models=[str(m) for m in health.get("models", [])],
        default_model=str(health.get("model", "")),
        backend=str(health.get("runner", "")),
        invoke_mode=runner.invoke_mode,
        runnable_schedules=[str(s) for s in health.get("schedules", [])],
        parameters=[parameter_out(p) for p in config.parameters],
        schedules=[schedule_out(s) for s in config.schedules],
        model_versions=[model_version_out(v) for v in config.model_versions],
        operation_defaults=config.operation_defaults,
    )


@router.post("/simulations", status_code=202)
def start_simulation(runner: Runner, request: SimulationRequestIn) -> dict[str, Any]:
    return runner.submit(request.to_payload())


@router.get("/simulations")
def list_simulations(runner: Runner) -> list[dict[str, Any]]:
    return runner.runs()


@router.get("/simulations/{run_id}")
def get_simulation(runner: Runner, run_id: str) -> dict[str, Any]:
    return runner.run(run_id)


def default_runner() -> SimRunner:
    """From the environment: ``AAS_SIM_RUNNER_URL``, ``SIM_INVOKE_MODE``, ``AAS_BASYX_URL``."""
    return SimRunner(
        os.environ.get("AAS_SIM_RUNNER_URL", "http://localhost:8001"),
        invoke_mode=os.environ.get("SIM_INVOKE_MODE", "aas"),
        basyx_url=os.environ.get("AAS_BASYX_URL"),
    )
