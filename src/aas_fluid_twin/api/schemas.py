"""Wire format of the API. Column-oriented series, because that is what a chart consumes."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from aas_fluid_twin.api.aas_metadata import (
    ChannelInfo,
    ModelVersionInfo,
    ParameterInfo,
    ScheduleInfo,
)
from aas_fluid_twin.store.models import RunRecord, SeriesResult

__all__ = [
    "AasOut",
    "ChannelOut",
    "FaultWindowOut",
    "ModelVersionOut",
    "ParameterOut",
    "RunOut",
    "ScheduleOut",
    "SeriesOut",
    "SimulationConfigOut",
    "SimulationRequestIn",
    "channel_out",
    "model_version_out",
    "parameter_out",
    "run_out",
    "schedule_out",
    "series_out",
]


class FaultWindowOut(BaseModel):
    label: int
    onset_s: float | None
    end_s: float | None
    source: str


class RunOut(BaseModel):
    run_id: str
    origin: str
    scenario: str
    anomaly_label: int
    started_at: datetime
    ended_at: datetime
    duration_s: float
    record_count: int
    schema_variant: str
    source_file: str | None
    usable: bool
    note: str | None
    fault_windows: list[FaultWindowOut]
    params: dict[str, object] | None


class SeriesOut(BaseModel):
    """A run (or a window of it). Every list is aligned with ``t_rel_s``."""

    run_id: str
    origin: str
    t_rel_s: list[float]
    timestamps: list[datetime]
    labels: list[int] = Field(description="Point-in-time anomaly label per sample")
    channels: dict[str, list[float | None]]


def run_out(record: RunRecord) -> RunOut:
    return RunOut(
        run_id=record.run_id,
        origin=str(record.origin),
        scenario=record.scenario,
        anomaly_label=record.anomaly_label,
        started_at=record.started_at,
        ended_at=record.ended_at,
        duration_s=record.duration_s,
        record_count=record.record_count,
        schema_variant=record.schema_variant,
        source_file=record.source_file,
        usable=record.usable,
        note=record.note,
        fault_windows=[
            FaultWindowOut(label=w.label, onset_s=w.onset_s, end_s=w.end_s, source=w.source)
            for w in record.fault_windows
        ],
        params=None if record.params is None else dict(record.params),
    )


def series_out(result: SeriesResult) -> SeriesOut:
    return SeriesOut(
        run_id=result.run_id,
        origin=str(result.origin),
        t_rel_s=result.t_rel_s,
        timestamps=result.timestamps,
        labels=result.labels,
        channels=result.channels,
    )


class ChannelOut(BaseModel):
    """What the AAS says about one recorded channel."""

    channel: str
    title: str
    unit: str | None
    data_type: str
    role: str
    quality: str
    quality_reason: str | None
    minimum: float | None
    maximum: float | None
    node_id: str | None
    semantic_id: str | None
    definition: str | None


class AasOut(BaseModel):
    repository: str
    web_ui: str | None
    submodels: dict[str, str]


class ParameterOut(BaseModel):
    id_short: str
    name: str
    default: float | bool | None
    unit: str | None
    minimum: float | None
    maximum: float | None
    fault_role: str | None
    description: str | None


class ScheduleOut(BaseModel):
    id_short: str
    name: str
    row_count: int | None
    column_order: str | None
    description: str | None


class ModelVersionOut(BaseModel):
    id_short: str
    version_id: str
    file: str | None
    notes: str | None


class SimulationConfigOut(BaseModel):
    """Everything the dashboard needs to render the run form."""

    models: list[str]
    default_model: str
    backend: str
    invoke_mode: str
    runnable_schedules: list[str]
    parameters: list[ParameterOut]
    schedules: list[ScheduleOut]
    model_versions: list[ModelVersionOut]
    operation_defaults: dict[str, str]


class SimulationRequestIn(BaseModel):
    """What the dashboard asks for. Mirrors the RunSimulation operation's inputs."""

    stop_time: float = Field(default=100.0, gt=0, le=3600)
    start_time: float = Field(default=0.0, ge=0)
    output_interval: float = Field(default=1.0, gt=0, le=60)
    solver: str = "ida"
    tolerance: float = Field(default=1e-5, gt=0, lt=1)
    schedule: str | list[dict[str, float]] = "EmbeddedDefault"
    parameter_overrides: dict[str, float | bool] = Field(default_factory=dict)
    model: str | None = None
    label: str | None = Field(default=None, max_length=200)

    def to_payload(self) -> dict[str, object]:
        payload = self.model_dump(exclude_none=True)
        return payload


def channel_out(info: ChannelInfo) -> ChannelOut:
    return ChannelOut(
        channel=info.channel,
        title=info.title,
        unit=info.unit,
        data_type=info.data_type,
        role=info.role,
        quality=info.quality,
        quality_reason=info.quality_reason,
        minimum=info.minimum,
        maximum=info.maximum,
        node_id=info.node_id,
        semantic_id=info.semantic_id,
        definition=info.definition,
    )


def parameter_out(info: ParameterInfo) -> ParameterOut:
    return ParameterOut(
        id_short=info.id_short,
        name=info.name,
        default=info.default,
        unit=info.unit,
        minimum=info.minimum,
        maximum=info.maximum,
        fault_role=info.fault_role,
        description=info.description,
    )


def schedule_out(info: ScheduleInfo) -> ScheduleOut:
    return ScheduleOut(
        id_short=info.id_short,
        name=info.name,
        row_count=info.row_count,
        column_order=info.column_order,
        description=info.description,
    )


def model_version_out(info: ModelVersionInfo) -> ModelVersionOut:
    return ModelVersionOut(
        id_short=info.id_short,
        version_id=info.version_id,
        file=info.file,
        notes=info.notes,
    )
