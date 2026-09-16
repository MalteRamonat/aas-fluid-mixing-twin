"""Runs the Modelica source through OpenModelica — the twin's execution path.

The OpenModelica image ships Python 3.10, so this runner does not import OMPython itself; it
talks HTTP to ``docker/openmodelica/om_worker.py``, which holds the compiled models. One
runner instance is bound to one model version (the worker compiles several), because a
runner's variable and parameter sets are what the service validates requests against.

This is the default path because no FMU export of this model runs under FMPy — deviation D7.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Final

import httpx

from aas_fluid_twin.simulation.runner import (
    IntegrationStoppedError,
    SimulationError,
    SimulationRequest,
    SimulationResult,
)

__all__ = ["DEFAULT_OM_WORKER_URL", "OmRunner", "worker_models"]

log = logging.getLogger("sim-runner")

DEFAULT_OM_WORKER_URL: Final[str] = os.environ.get("AAS_OM_WORKER_URL", "http://openmodelica:8010")


def worker_models(
    worker_url: str = DEFAULT_OM_WORKER_URL, timeout_s: float = 30.0, wait_s: float = 0.0
) -> list[str]:
    """The model versions the worker has compiled, default first.

    The worker does not listen until every model is compiled (a few minutes after a stack
    restart), so a service starting alongside it keeps trying for ``wait_s`` before giving up.
    """
    deadline = time.monotonic() + wait_s
    waited = False
    while True:
        try:
            response = httpx.get(f"{worker_url.rstrip('/')}/health", timeout=timeout_s)
            response.raise_for_status()
            break
        except httpx.HTTPError as error:
            if time.monotonic() >= deadline:
                raise SimulationError(f"OpenModelica worker at {worker_url}: {error}") from error
            if not waited:
                log.info("waiting for the OpenModelica worker at %s to compile", worker_url)
            waited = True
            time.sleep(5.0)
    body = response.json()
    models = [str(m) for m in body.get("models", [])]
    default = str(body.get("default_model", ""))
    return sorted(models, key=lambda name: (name != default, name))


class OmRunner:
    name = "openmodelica"

    def __init__(
        self,
        worker_url: str = DEFAULT_OM_WORKER_URL,
        model: str | None = None,
        timeout_s: float = 900.0,
    ) -> None:
        """``model`` selects one of the worker's compiled models; ``None`` takes its default."""
        self.worker_url = worker_url.rstrip("/")
        self._http = httpx.Client(base_url=self.worker_url, timeout=timeout_s)
        health = self._get("/health")
        self.omc_version = str(health.get("omc", "unknown"))
        available = [str(m) for m in health.get("models", [])]
        if model is not None and model not in available:
            raise SimulationError(
                f"the worker at {self.worker_url} has no model {model!r}; compiled: {available}"
            )
        listing = self._get("/variables" if model is None else f"/variables?model={model}")
        self._model_name = str(listing.get("model", health.get("default_model", "unknown")))
        self._variables = frozenset(str(v) for v in listing["variables"])
        self._parameters = frozenset(str(p) for p in listing["parameters"])

    def _get(self, path: str) -> dict[str, Any]:
        try:
            response = self._http.get(path)
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise SimulationError(f"OpenModelica worker at {self.worker_url}: {error}") from error
        body: dict[str, Any] = response.json()
        return body

    @property
    def model_name(self) -> str:
        return self._model_name

    def variable_names(self) -> frozenset[str]:
        return self._variables

    def parameter_names(self) -> frozenset[str]:
        return self._parameters

    def run(self, request: SimulationRequest) -> SimulationResult:
        payload = {
            "model": self._model_name,
            # The worker decides how the schedule reaches the model: a table file for the
            # fault-capable version, table parameters for the fixed-table upstream one.
            "schedule": request.schedule.table(),
            "start_values": request.start_values(),
            "start_time": request.start_time,
            "stop_time": request.stop_time,
            "output_interval": request.output_interval,
            "tolerance": request.tolerance,
            "solver": request.solver,
            "outputs": list(request.outputs),
        }
        started = time.perf_counter()
        try:
            response = self._http.post("/simulate", json=payload)
        except httpx.HTTPError as error:
            raise SimulationError(f"OpenModelica worker: {error}") from error
        if response.status_code != 200:
            detail = response.json().get("error", response.text) if response.content else ""
            raise SimulationError(f"OpenModelica simulation failed: {detail}")
        body = response.json()
        elapsed = time.perf_counter() - started

        # A failed integration is not an error to OpenModelica: it writes the result up to the
        # point where it gave up and exits 0. Without this check a run that died after 35 s of
        # a 600 s horizon would be stored and published as a completed run.
        times = [float(t) for t in body["time"]]
        if not times:
            raise SimulationError(
                f"{self._model_name}: the model could not be initialised with these parameters "
                "and this schedule (the solver produced no output); a shut valve in front of a "
                "running pump or a tank filled past its height are the usual causes"
            )
        shortfall = request.stop_time - times[-1]
        if shortfall > max(1e-6, request.output_interval / 2):
            raise IntegrationStoppedError(
                f"{self._model_name}: {request.solver} stopped at t = {times[-1]:.4g} s of the "
                f"requested {request.stop_time:g} s (integrator failure or an event it could "
                f"not resolve); the partial result is discarded",
                reached=times[-1],
            )

        # OpenModelica writes every event instant twice (before/after); keep the after-value so
        # the time axis is strictly increasing, which the store's label table requires.
        keep = [i for i, t in enumerate(times) if i + 1 == len(times) or times[i + 1] > t]
        return SimulationResult(
            time_s=[times[i] for i in keep],
            variables={
                name: [float(column[i]) for i in keep] for name, column in body["variables"].items()
            },
            runner=self.name,
            model=self._model_name,
            wall_time_s=elapsed,
        )
