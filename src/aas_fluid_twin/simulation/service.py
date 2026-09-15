"""The ``sim-runner`` service: runs simulations and publishes each run into the twin.

Two front doors, one queue:

* ``POST /invoke/run`` and ``POST /invoke/status`` — the endpoints the AAS ``Operation``s
  ``RunSimulation`` / ``GetRunStatus`` are delegated to by BaSyx. They speak the delegation
  contract: an ``OperationVariable[]`` in, an ``OperationVariable[]`` out.
* ``POST /runs`` / ``GET /runs/{id}`` — the same thing as plain JSON, for the dashboard's
  direct mode and for tests.

A completed run is (1) written to the time-series store, (2) appended to the simulation AAS
``TimeSeries`` submodel as an ``ExternalSegment`` (CSV attachment) + ``LinkedSegment`` pair,
and (3) logged under ``SimulationControl/Runs``. Steps 2 and 3 are skipped, with the reason
recorded on the job, when no AAS repository is configured.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import queue
import threading
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from basyx.aas import model
from basyx.aas.model import datatypes
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from aas_fluid_twin import config
from aas_fluid_twin.aas import ids
from aas_fluid_twin.aas.builders._common import package_path, prop, prop_typed, ref_element, smc
from aas_fluid_twin.aas.builders.simulation_control import SUBMODEL_ID as CONTROL_ID
from aas_fluid_twin.aas.builders.time_series import (
    SIMULATION_TIMESERIES_ID,
    segment_reference,
    simulated_run_segments,
)
from aas_fluid_twin.aas.semantics import semantic
from aas_fluid_twin.benchmark.modelica import load_modelica_model
from aas_fluid_twin.benchmark.signals import load_signal_dictionary
from aas_fluid_twin.client import BasyxClient, BasyxError
from aas_fluid_twin.simulation.mapping import ChannelMapping, build_channel_mapping
from aas_fluid_twin.simulation.runner import (
    TESTED_SOLVER,
    SimulationError,
    SimulationRequest,
    SimulationResult,
    SimulationRunner,
    resolve_parameters,
)
from aas_fluid_twin.simulation.schedule import ActuatorSchedule
from aas_fluid_twin.store.models import Origin, RunRecord, SampleRow, WritableTimeSeriesStore
from aas_fluid_twin.store.timescale import TimescaleStore

__all__ = ["JobStore", "RunSpec", "create_app", "operation_variables", "parse_operation_variables"]

log = logging.getLogger("sim-runner")

JobStatus = Literal["queued", "running", "completed", "failed"]

#: Fault handles whose non-default value labels a simulated run (label values as in the data).
_FAULT_LABELS: dict[str, tuple[str, int]] = {
    "V211_opening": ("leakage", 1),
    "V212_opening": ("clogging", 2),
    "V210_opening": ("reconfiguration", 5),
    "V211_return_to_B201": ("reconfiguration", 5),
}


# --- request model ------------------------------------------------------------------


class RunSpec(BaseModel):
    """What a caller asks for. Mirrors the ``RunSimulation`` operation's input variables."""

    start_time: float = 0.0
    stop_time: float = 600.0
    solver: str = TESTED_SOLVER
    tolerance: float = 1e-5
    output_interval: float = 1.0
    schedule: str | list[dict[str, float]] = Field(
        default="EmbeddedDefault",
        description="idShort of an ActuatorSchedules entry, or inline rows keyed by actuator",
    )
    parameter_overrides: dict[str, float | bool] = Field(default_factory=dict)
    model: str | None = Field(
        default=None,
        description="model version to run; None takes the service default (SIM_MODEL)",
    )
    label: str | None = Field(default=None, description="free-text tag stored with the run")

    @classmethod
    def from_operation_inputs(cls, values: Mapping[str, str]) -> RunSpec:
        """From the ``RunSimulation`` input variables (all values arrive as strings)."""
        raw: dict[str, Any] = {}
        if "startTime" in values:
            raw["start_time"] = float(values["startTime"])
        if "stopTime" in values:
            raw["stop_time"] = float(values["stopTime"])
        if "solver" in values:
            raw["solver"] = values["solver"]
        if "tolerance" in values:
            raw["tolerance"] = float(values["tolerance"])
        if values.get("outputInterval", "").strip():
            raw["output_interval"] = float(values["outputInterval"])
        if "schedule" in values:
            text = values["schedule"].strip()
            raw["schedule"] = json.loads(text) if text.startswith("[") else text
        if "parameterOverrides" in values and values["parameterOverrides"].strip():
            raw["parameter_overrides"] = json.loads(values["parameterOverrides"])
        if values.get("model", "").strip():
            raw["model"] = values["model"].strip()
        if values.get("label", "").strip():
            raw["label"] = values["label"].strip()
        return cls(**raw)


@dataclass
class Job:
    run_id: str
    spec: RunSpec
    status: JobStatus = "queued"
    progress: float = 0.0
    submitted_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    segment_id_short: str | None = None
    record_count: int | None = None
    wall_time_s: float | None = None
    aas_note: str | None = None
    scenario: str = "normal_behaviour"
    anomaly_label: int = 0
    model: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "progress": self.progress,
            "submitted_at": self.submitted_at.isoformat(),
            "started_at": None if self.started_at is None else self.started_at.isoformat(),
            "finished_at": None if self.finished_at is None else self.finished_at.isoformat(),
            "error": self.error,
            "segment_id_short": self.segment_id_short,
            "record_count": self.record_count,
            "wall_time_s": self.wall_time_s,
            "scenario": self.scenario,
            "anomaly_label": self.anomaly_label,
            "model": self.model,
            "aas_note": self.aas_note,
            "spec": self.spec.model_dump(),
        }


# --- the delegation contract ---------------------------------------------------------


def parse_operation_variables(body: Any) -> dict[str, str]:
    """``OperationVariable[]`` (or an ``{"inputArguments": [...]}`` wrapper) -> idShort -> value."""
    if isinstance(body, dict) and "inputArguments" in body:
        body = body["inputArguments"]
    if not isinstance(body, list):
        raise HTTPException(status_code=422, detail="expected an OperationVariable array")
    values: dict[str, str] = {}
    for entry in body:
        element = entry.get("value", entry) if isinstance(entry, dict) else None
        if not isinstance(element, dict) or "idShort" not in element:
            raise HTTPException(status_code=422, detail="malformed OperationVariable")
        values[str(element["idShort"])] = (
            "" if element.get("value") is None else str(element["value"])
        )
    return values


def operation_variables(values: Mapping[str, str | float]) -> list[dict[str, Any]]:
    """idShort -> value into ``OperationVariable[]`` Properties (the shape BaSyx expects back)."""
    out = []
    for id_short, value in values.items():
        value_type = "xs:double" if isinstance(value, float) else "xs:string"
        out.append(
            {
                "value": {
                    "modelType": "Property",
                    "idShort": id_short,
                    "valueType": value_type,
                    "value": str(value),
                }
            }
        )
    return out


# --- the worker ------------------------------------------------------------------------


class JobStore:
    """In-memory job registry plus a single worker thread; one simulation at a time.

    One runner per model version: a request names the version it wants (or takes the default),
    and the runner it resolves to is what validates the parameters — which is how a fault
    handle asked of the upstream model version is refused instead of ignored.
    """

    def __init__(
        self,
        runners: Mapping[str, SimulationRunner],
        mappings: Mapping[str, ChannelMapping],
        schedules: Mapping[str, ActuatorSchedule],
        store: WritableTimeSeriesStore | None,
        basyx: BasyxClient | None,
        timeseries_endpoint: str,
        default_model: str | None = None,
    ) -> None:
        if not runners:
            raise ValueError("at least one runner is required")
        if set(runners) != set(mappings):
            raise ValueError("every runner needs a channel mapping")
        self.runners = dict(runners)
        self.mappings = dict(mappings)
        self.default_model = default_model or next(iter(self.runners))
        if self.default_model not in self.runners:
            raise ValueError(f"default model {self.default_model!r} has no runner")
        self.schedules = dict(schedules)
        self.store = store
        self.basyx = basyx
        self.timeseries_endpoint = timeseries_endpoint
        self.jobs: dict[str, Job] = {}
        self._queue: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop, name="sim-worker", daemon=True)
        self._thread.start()

    # -- submission --

    def runner_for(self, model: str | None) -> tuple[str, SimulationRunner, ChannelMapping]:
        name = model or self.default_model
        runner = self.runners.get(name)
        if runner is None:
            raise ValueError(f"unknown model {name!r}; available: {sorted(self.runners)}")
        return name, runner, self.mappings[name]

    def validate(self, spec: RunSpec) -> None:
        """Raise if this request could not run. Used by the dry-run endpoint and by submit."""
        self.runner_for(spec.model)
        self._to_request(spec)

    def submit(self, spec: RunSpec) -> dict[str, Any]:
        """Validate, register and enqueue; returns the job as it was *accepted* (``queued``).

        The snapshot is taken before the worker can touch the job, so a caller never sees a
        run that is already ``running`` in the acceptance reply.
        """
        name, _, _ = self.runner_for(spec.model)
        request = self._to_request(spec)  # validates before queuing
        run_id = f"sim_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"
        job = Job(run_id=run_id, spec=spec, model=name)
        job.scenario, job.anomaly_label = _classify(spec.parameter_overrides)
        with self._lock:
            self.jobs[run_id] = job
        accepted = job.to_json()
        self._queue.put(run_id)
        log.info(
            "queued %s on %s (%d outputs, stop %.0f s)",
            run_id,
            name,
            len(request.outputs),
            spec.stop_time,
        )
        return accepted

    def get(self, run_id: str) -> Job | None:
        with self._lock:
            return self.jobs.get(run_id)

    def all(self) -> list[Job]:
        with self._lock:
            return sorted(self.jobs.values(), key=lambda j: j.submitted_at)

    def _to_request(self, spec: RunSpec) -> SimulationRequest:
        _, runner, mapping = self.runner_for(spec.model)
        if isinstance(spec.schedule, str):
            schedule = self.schedules.get(spec.schedule)
            if schedule is None:
                raise ValueError(
                    f"unknown schedule {spec.schedule!r}; known: {sorted(self.schedules)}"
                )
        else:
            schedule = ActuatorSchedule.from_json(json.dumps(spec.schedule), name="inline")
        parameters = resolve_parameters(spec.parameter_overrides, runner.parameter_names())
        return SimulationRequest(
            schedule=schedule,
            outputs=mapping.variables,
            start_time=spec.start_time,
            stop_time=spec.stop_time,
            output_interval=spec.output_interval,
            tolerance=spec.tolerance,
            solver=spec.solver,
            parameters=parameters,
        )

    # -- execution --

    def _loop(self) -> None:
        while True:
            run_id = self._queue.get()
            job = self.get(run_id)
            if job is None:
                continue
            try:
                self._execute(job)
            except Exception as error:  # a failed run must not take the worker down
                log.exception("%s failed", run_id)
                job.status, job.error = "failed", f"{type(error).__name__}: {error}"
                job.finished_at = datetime.now()

    def _execute(self, job: Job) -> None:
        job.status, job.started_at, job.progress = "running", datetime.now(), 0.05
        _, runner, mapping = self.runner_for(job.spec.model)
        result = runner.run(self._to_request(job.spec))
        job.progress, job.wall_time_s = 0.6, result.wall_time_s

        channels = mapping.convert(result.variables)
        started_at = job.started_at.replace(microsecond=0)
        record = RunRecord(
            run_id=job.run_id,
            origin=Origin.SIMULATED,
            scenario=job.scenario,
            anomaly_label=job.anomaly_label,
            started_at=started_at,
            ended_at=started_at + timedelta(seconds=result.time_s[-1] - result.time_s[0]),
            duration_s=result.time_s[-1] - result.time_s[0],
            record_count=len(result),
            schema_variant="simulated",
            source_file=None,
            note=job.spec.label,
            params={
                "runner": result.runner,
                "model": result.model,
                "solver": job.spec.solver,
                "tolerance": job.spec.tolerance,
                "output_interval": job.spec.output_interval,
                "schedule": job.spec.schedule,
                "parameter_overrides": job.spec.parameter_overrides,
            },
        )
        job.record_count = len(result)

        if self.store is not None:
            self.store.write_run(
                record,
                _sample_rows(started_at, result, channels),
                ((t, job.anomaly_label) for t in result.time_s),
            )
        job.progress = 0.8

        if self.basyx is not None:
            try:
                job.segment_id_short = self._publish_to_aas(job, record, result, channels)
            except BasyxError as error:
                job.aas_note = f"AAS update failed: {error}"
                log.warning("%s: %s", job.run_id, job.aas_note)
        else:
            job.aas_note = "no AAS repository configured; run stored only"

        job.status, job.progress, job.finished_at = "completed", 1.0, datetime.now()
        log.info("%s completed: %d records in %.1f s", job.run_id, len(result), result.wall_time_s)

    def _publish_to_aas(
        self,
        job: Job,
        record: RunRecord,
        result: SimulationResult,
        channels: Mapping[str, list[float]],
    ) -> str:
        assert self.basyx is not None
        attachment_path = package_path("simulation", f"{job.run_id}.csv")
        external, linked = simulated_run_segments(
            job.run_id,
            description=(
                f"{job.scenario.replace('_', ' ')} run of {result.model} via {result.runner}, "
                f"schedule {job.spec.schedule if isinstance(job.spec.schedule, str) else 'inline'}"
                + (
                    f", overrides {json.dumps(job.spec.parameter_overrides)}"
                    if job.spec.parameter_overrides
                    else ""
                )
            ),
            started_at=record.started_at,
            ended_at=record.ended_at,
            record_count=record.record_count,
            sampling_interval_s=job.spec.output_interval,
            timeseries_endpoint=self.timeseries_endpoint,
            attachment_path=attachment_path,
            anomaly_label=job.anomaly_label,
        )
        self.basyx.post_element(SIMULATION_TIMESERIES_ID, "Segments", external)
        self.basyx.post_element(SIMULATION_TIMESERIES_ID, "Segments", linked)
        self.basyx.upload_attachment(
            SIMULATION_TIMESERIES_ID,
            f"Segments.{external.id_short}.File",
            f"{job.run_id}.csv",
            _to_csv(result.time_s, channels),
            "text/csv",
        )
        self.basyx.post_element(CONTROL_ID, "Runs", _run_log_entry(job, record, external.id_short))
        return str(external.id_short)


def _classify(overrides: Mapping[str, float | bool]) -> tuple[str, int]:
    active = []
    for key, value in overrides.items():
        if key in _FAULT_LABELS and (
            (key == "V212_opening" and float(value) < 1.0)
            or (key != "V212_opening" and float(value) > 0.0)
        ):
            active.append(_FAULT_LABELS[key])
    if not active:
        return "normal_behaviour", 0
    if len({name for name, _ in active}) > 1 and {n for n, _ in active} >= {"leakage", "clogging"}:
        return "leakage_and_clogging", 3
    return active[0]


def _sample_rows(
    started_at: datetime, result: SimulationResult, channels: Mapping[str, list[float]]
) -> list[SampleRow]:
    rows: list[SampleRow] = []
    for i, t in enumerate(result.time_s):
        ts = started_at + timedelta(seconds=t - result.time_s[0])
        for channel, values in channels.items():
            rows.append(SampleRow(ts, t, channel, values[i]))
    return rows


def _to_csv(time_s: list[float], channels: Mapping[str, list[float]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    names = list(channels)
    writer.writerow(["Session Time Stamps", *names])
    for i, t in enumerate(time_s):
        writer.writerow([f"{t:.6f}", *(f"{channels[n][i]:.10g}" for n in names)])
    return buffer.getvalue().encode("utf-8")


def _run_log_entry(
    job: Job, record: RunRecord, segment_id_short: str
) -> model.SubmodelElementCollection:
    def sem(element: str) -> model.ExternalReference:
        return semantic("SimulationControl", element)

    finished = job.finished_at or datetime.now()
    return smc(
        job.run_id,
        sem("Run"),
        prop("RunId", job.run_id, sem("RunId")),
        prop("Status", "completed", sem("Status")),
        prop("StartedAt", record.started_at.isoformat(), sem("StartedAt")),
        prop("FinishedAt", finished.isoformat(timespec="seconds"), sem("FinishedAt")),
        prop_typed(
            "AnomalyLabel", datatypes.Int, job.anomaly_label, semantic("Common", "AnomalyLabel")
        ),
        ref_element(
            "SegmentRef",
            segment_reference(SIMULATION_TIMESERIES_ID, segment_id_short),
            sem("SegmentRef"),
        ),
        prop("ParametersUsed", json.dumps(record.params, sort_keys=True), sem("ParametersUsed")),
    )


# --- app ---------------------------------------------------------------------------------


def _default_runners() -> dict[str, SimulationRunner]:
    """``SIM_BACKEND=openmodelica`` (default) or ``fmpy``, as ``{model name: runner}``.

    OpenModelica is the default because no FMU of this model runs outside OpenModelica with
    the tooling at hand (design §6.2, deviation D7); the FMPy path stays for an FMU that does.
    The OpenModelica worker compiles several model versions and each gets its own runner.
    """
    backend = os.environ.get("SIM_BACKEND", "openmodelica")
    if backend == "fmpy":
        from aas_fluid_twin.simulation.fmpy_runner import FmpyRunner

        fmu = config.ARTIFACT_DIR / os.environ.get("SIM_FMU_NAME", "ModVA_online_stable.fmu")
        runner: SimulationRunner = FmpyRunner(fmu)
        return {runner.model_name: runner}
    if backend != "openmodelica":
        raise SystemExit(f"unknown SIM_BACKEND {backend!r}; use openmodelica or fmpy")
    from aas_fluid_twin.simulation.om_runner import OmRunner, worker_models

    return {name: OmRunner(model=name) for name in worker_models()}


def _default_schedules() -> dict[str, ActuatorSchedule]:
    modelica = load_modelica_model()
    schedules = {
        "EmbeddedDefault": ActuatorSchedule.from_table("EmbeddedDefault", modelica.actuator_table)
    }
    matrix = config.BENCHMARK_DIR / "Simulation_Model_Control"
    for path in sorted(matrix.glob("ActuatorControlMatrix_*.csv")):
        schedules["BenchmarkMatrix"] = ActuatorSchedule.from_csv(path, "BenchmarkMatrix")
    return schedules


def create_app(jobs: JobStore | None = None) -> FastAPI:
    app = FastAPI(title="ModVA simulation runner", version="0.1.0")

    if jobs is None:
        backend = os.environ.get("SIM_BACKEND", "openmodelica")
        runners = _default_runners()
        signals = load_signal_dictionary()
        mappings = {
            name: build_channel_mapping(signals, sorted(runner.variable_names()))
            for name, runner in runners.items()
        }
        dsn = os.environ.get("AAS_TIMESERIES_DSN")
        basyx_url = os.environ.get("AAS_BASYX_URL")
        jobs = JobStore(
            runners=runners,
            mappings=mappings,
            default_model=os.environ.get("SIM_MODEL") or None,
            schedules=_default_schedules(),
            store=TimescaleStore(dsn) if dsn else None,
            basyx=BasyxClient(basyx_url) if basyx_url else None,
            timeseries_endpoint=os.environ.get(
                "AAS_TIMESERIES_ENDPOINT", ids.DEFAULT_TIMESERIES_ENDPOINT
            ),
        )
        log.info(
            "backend %s, models %s (default %s), %d channels mapped, schedules %s",
            backend,
            sorted(runners),
            jobs.default_model,
            len(mappings[jobs.default_model].pairs),
            sorted(jobs.schedules),
        )
    app.state.jobs = jobs

    @app.get("/health")
    def health() -> dict[str, Any]:
        active: JobStore = app.state.jobs
        default = active.runners[active.default_model]
        return {
            "status": "UP",
            "runner": default.name,
            "model": active.default_model,
            "models": sorted(active.runners),
            "channels": len(active.mappings[active.default_model].pairs),
            "schedules": sorted(active.schedules),
            "jobs": len(active.jobs),
        }

    # -- delegation contract --

    @app.post("/invoke/run")
    async def invoke_run(request: Request) -> list[dict[str, Any]]:
        values = parse_operation_variables(await request.json())
        try:
            spec = RunSpec.from_operation_inputs(values)
            accepted = app.state.jobs.submit(spec)
        except (ValueError, SimulationError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return operation_variables({"runId": accepted["run_id"], "status": accepted["status"]})

    @app.post("/invoke/status")
    async def invoke_status(request: Request) -> list[dict[str, Any]]:
        values = parse_operation_variables(await request.json())
        job = app.state.jobs.get(values.get("runId", ""))
        if job is None:
            raise HTTPException(status_code=404, detail=f"unknown run {values.get('runId')!r}")
        return operation_variables(
            {
                "status": job.status if job.error is None else f"failed: {job.error}",
                "progress": float(job.progress),
                "segmentIdShort": job.segment_id_short or "",
            }
        )

    # -- plain JSON --

    @app.post("/runs", status_code=202)
    def submit(spec: RunSpec) -> dict[str, Any]:
        try:
            accepted: dict[str, Any] = app.state.jobs.submit(spec)
        except (ValueError, SimulationError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return accepted

    @app.post("/runs/validate", status_code=204)
    def validate(spec: RunSpec) -> None:
        """Check a request without running it.

        BaSyx relays only the status code of a failed delegation, not the delegate's message,
        so a caller coming through the AAS operation would otherwise learn that something was
        rejected but not what. The API validates here first and reports the reason itself.
        """
        try:
            app.state.jobs.validate(spec)
        except (ValueError, SimulationError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/runs")
    def list_runs() -> list[dict[str, Any]]:
        return [job.to_json() for job in app.state.jobs.all()]

    @app.get("/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        job: Job | None = app.state.jobs.get(run_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}")
        return job.to_json()

    @app.get("/schedules")
    def schedules() -> dict[str, list[dict[str, float]]]:
        return {name: s.to_json() for name, s in app.state.jobs.schedules.items()}

    return app


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    uvicorn.run(
        create_app(),
        host=os.environ.get("SIM_RUNNER_HOST", "0.0.0.0"),
        port=int(os.environ.get("SIM_RUNNER_PORT", "8000")),
    )


if __name__ == "__main__":
    main()
