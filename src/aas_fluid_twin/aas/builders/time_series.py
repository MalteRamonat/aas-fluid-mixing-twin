"""Time Series Data — IDTA 02008-1-1.

This submodel is how the project keeps raw data out of the AAS. Every run becomes a pair of
segments:

* an ``ExternalSegment`` whose ``File`` is the run's CSV, attached to the package or the
  repository — self-contained and archival;
* a ``LinkedSegment`` whose ``Endpoint`` + ``Query`` address the same run in the time-series
  store — the live path the dashboard uses.

``Metadata/Record`` is the *channel schema*: one empty ``Property`` per channel whose
semanticId is that channel's concept. That is how the template intends metadata to be
conveyed. ``InternalSegment`` is deliberately never used.

Sampling on this plant is not uniform, so ``SamplingInterval`` is the run's mean Δt and
``SamplingRate`` is omitted rather than reporting a fictitious constant rate.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from basyx.aas import model
from basyx.aas.model import datatypes

from aas_fluid_twin.aas import ids
from aas_fluid_twin.aas.builders._common import (
    element_ref,
    ext_ref,
    file,
    mlp,
    package_path,
    prop,
    prop_typed,
    qualifier,
    smc,
)
from aas_fluid_twin.aas.context import BuildContext
from aas_fluid_twin.aas.semantics import channel_semantic, semantic
from aas_fluid_twin.aas.templates import template
from aas_fluid_twin.benchmark.datasets import RunMetadata
from aas_fluid_twin.benchmark.signals import Quality, Signal

__all__ = [
    "PLANT_TIMESERIES_ID",
    "SIMULATION_TIMESERIES_ID",
    "build_plant_time_series",
    "build_simulation_time_series",
    "dataset_attachment_path",
    "iter_dataset_attachments",
    "segment_reference",
    "simulated_run_segments",
]

T = template("time_series")
PLANT_TIMESERIES_ID = ids.submodel_id(ids.PLANT_TAG, T.submodel_id_short)
SIMULATION_TIMESERIES_ID = ids.submodel_id(ids.SIMULATION_TAG, T.submodel_id_short)

_EXT = "Segments/ExternalSegment"
_LNK = "Segments/LinkedSegment"

#: The clear-name simulation result published with the benchmark. Referenced, with a quality
#: qualifier naming deviation D5 (its pressure and temperature columns are mis-converted).
REFERENCE_SIMULATION_RESULT = (
    "simulation/simulation_datasets_clearnames/"
    "ModVA_online_stable_res_20241206_102432_clearnames.csv"
)


def _sem(path: str) -> model.ExternalReference:
    return ext_ref(T.semantic(path))


def dataset_attachment_path(run: RunMetadata) -> str:
    return package_path("datasets", run.path.name)


def segment_reference(
    submodel_id: str, id_short: str
) -> model.ModelReference[model.SubmodelElement]:
    return element_ref(
        submodel_id,
        [
            (model.SubmodelElementCollection, "Segments"),
            (model.SubmodelElementCollection, id_short),
        ],
    )


def _iso_duration(seconds: float) -> str:
    return f"PT{seconds:.3f}S"


def _record_schema(
    signals: Iterable[Signal], *, include_label: bool
) -> model.SubmodelElementCollection:
    """The channel schema. Properties are typed and empty: metadata, not data."""
    elements: list[model.SubmodelElement | None] = [
        prop_typed(
            "Time",
            datatypes.Long,
            None,
            _sem("Metadata/Record/Time"),
            description="Relative time since the first sample, in milliseconds "
            "(CSV column 'Session Time Stamps' holds seconds).",
        ),
        prop_typed(
            "ServerTime",
            datatypes.DateTime,
            None,
            semantic("Common", "WallClockTime"),
            description="Wall-clock timestamp (CSV column 'Server Time').",
        ),
    ]
    for signal in signals:
        value_type = datatypes.Boolean if signal.is_binary else datatypes.Double
        element = prop_typed(
            signal.channel,
            value_type,
            None,
            channel_semantic(signal),
            description=(
                f"{signal.display_name} [{signal.unit or 'binary'}], tag {signal.sensor_id}."
                + (
                    f" Quality {signal.quality.value}: {signal.quality_reason}"
                    if signal.quality_reason
                    else ""
                )
            ),
        )
        if signal.quality is not Quality.GOOD:
            element.qualifier.add(
                qualifier("DataQuality", signal.quality.value, semantic("Common", "DataQuality"))
            )
        elements.append(element)
    if include_label:
        elements.append(
            prop_typed(
                "Anomaly",
                datatypes.Int,
                None,
                semantic("Common", "AnomalyLabel"),
                description="File-level scenario label; per-sample labels are resolved "
                "from the FaultScenarioCatalogue onsets.",
            )
        )
    return smc("Record", _sem("Metadata/Record"), *elements)


def _segment_common(base: str, run: RunMetadata) -> list[model.SubmodelElement]:
    label = f"{run.scenario.value.replace('_', ' ')} (label {run.label})"
    description = f"Run {run.number}, {label}."
    if run.schema_variant.value != "full":
        description += (
            f" Reduced schema: {len(run.missing_channels)} pressure-derived " "channels absent."
        )
    if not run.usable:
        description += f" Unusable: {run.unusable_reason}"
    return [
        mlp("Name", run.run_id, _sem(f"{base}/Name")),
        mlp("Description", description, _sem(f"{base}/Description")),
        prop_typed("RecordCount", datatypes.Long, run.record_count, _sem(f"{base}/RecordCount")),
        prop("StartTime", run.started_at.isoformat(), _sem(f"{base}/StartTime")),
        prop("EndTime", run.ended_at.isoformat(), _sem(f"{base}/EndTime")),
        prop("Duration", _iso_duration(run.duration_s), _sem(f"{base}/Duration")),
        prop_typed(
            "SamplingInterval",
            datatypes.Long,
            round(run.sampling_interval_s * 1000),
            _sem(f"{base}/SamplingInterval"),
            description="Mean interval in ms. Sampling is not uniform on this plant.",
        ),
        prop("State", "completed", _sem(f"{base}/State")),
        prop(
            "LastUpdate",
            run.ended_at.isoformat(timespec="seconds"),
            _sem(f"{base}/LastUpdate"),
            description="Time of the run's last sample: a recorded run never changes after that.",
        ),
        prop("SchemaVariant", run.schema_variant.value, semantic("Common", "SchemaVariant")),
        prop("RunKind", "measured", semantic("Common", "RunKind")),
        prop("AnomalyLabel", run.label, semantic("Common", "AnomalyLabel")),
    ]


def _external_segment(run: RunMetadata) -> model.SubmodelElementCollection:
    return smc(
        f"Measured_{run.run_id}",
        _sem(_EXT),
        *_segment_common(_EXT, run),
        file(
            "File",
            dataset_attachment_path(run),
            "text/csv",
            _sem(f"{_EXT}/File"),
            description=f"Benchmark path: data/ModVA_Datasets/{run.path.name}",
        ),
    )


def _linked_segment(ctx: BuildContext, run: RunMetadata) -> model.SubmodelElementCollection:
    return smc(
        f"Linked_{run.run_id}",
        _sem(_LNK),
        *_segment_common(_LNK, run),
        prop_typed(
            "Endpoint", datatypes.AnyURI, ctx.endpoints.timeseries_api, _sem(f"{_LNK}/Endpoint")
        ),
        prop(
            "Query",
            f"run_id={run.run_id}",
            _sem(f"{_LNK}/Query"),
            description="Append '&channels=a,b' to restrict, '&from=..&to=..' (seconds) to window.",
        ),
    )


def _submodel(
    submodel_id: str,
    name: str,
    description: str,
    record: model.SubmodelElementCollection,
    segments: list[model.SubmodelElement],
) -> model.Submodel:
    return model.Submodel(
        id_=submodel_id,
        id_short=T.submodel_id_short,
        semantic_id=ext_ref(T.submodel_semantic_id),
        administration=model.AdministrativeInformation(
            version="1", revision="0", template_id=T.template_id
        ),
        submodel_element=[
            smc(
                "Metadata",
                _sem("Metadata"),
                mlp("Name", name, _sem("Metadata/Name")),
                mlp("Description", description, _sem("Metadata/Description")),
                record,
            ),
            smc("Segments", _sem("Segments"), *segments),
        ],
    )


def iter_dataset_attachments(ctx: BuildContext) -> Iterable[tuple[str, object, str]]:
    for run in ctx.index:
        yield dataset_attachment_path(run), run.path, "text/csv"


def build_plant_time_series(ctx: BuildContext) -> model.Submodel:
    first = min(r.started_at for r in ctx.index)
    last = max(r.ended_at for r in ctx.index)
    segments: list[model.SubmodelElement] = []
    for run in ctx.index:
        segments.append(_external_segment(run))
        segments.append(_linked_segment(ctx, run))
    return _submodel(
        PLANT_TIMESERIES_ID,
        "ModVA recorded operational data",
        f"{len(ctx.index)} runs recorded on the real plant between {first.date()} and "
        f"{last.date()}: {len(ctx.index.normal)} normal, {len(ctx.index.faulty)} with induced "
        "faults or non-nominal operation. Each run is one ExternalSegment (the CSV) and one "
        "LinkedSegment (the same run in the time-series store).",
        _record_schema(ctx.signals, include_label=True),
        segments,
    )


def build_simulation_time_series(ctx: BuildContext) -> model.Submodel:
    simulated = [s for s in ctx.signals if s.is_mapped_to_simulation]

    reference = smc(
        "Reference_ModVA_online_stable_res_20241206_102432",
        _sem(_EXT),
        mlp("Name", "ModVA_online_stable_res_20241206_102432_clearnames", _sem(f"{_EXT}/Name")),
        mlp(
            "Description",
            "Clear-name simulation result published with the benchmark. Its pressure and "
            "temperature columns are mis-converted (deviation D5: Pa treated as bar, K left as "
            "°C) and the file carries no time column, so it is referenced for provenance only.",
            _sem(f"{_EXT}/Description"),
        ),
        prop_typed("RecordCount", datatypes.Long, 180, _sem(f"{_EXT}/RecordCount")),
        prop("State", "completed", _sem(f"{_EXT}/State")),
        prop(
            "LastUpdate",
            "2024-12-06T10:24:32",
            _sem(f"{_EXT}/LastUpdate"),
            description="From the result file's timestamped name.",
        ),
        prop("RunKind", "simulated", semantic("Common", "RunKind")),
        file(
            "File",
            package_path("simulation", REFERENCE_SIMULATION_RESULT.rsplit("/", 1)[-1]),
            "text/csv",
            _sem(f"{_EXT}/File"),
            description=f"Benchmark path: {REFERENCE_SIMULATION_RESULT}",
        ),
    )
    reference.qualifier.add(
        qualifier("DataQuality", "unreliable", semantic("Common", "DataQuality"))
    )

    return _submodel(
        SIMULATION_TIMESERIES_ID,
        "ModVA simulation results",
        f"Runs of the simulation model. {len(simulated)} of the plant's channels are produced "
        "by the model; the binary level switches and the stirrer are not. New runs are appended "
        "by the simulation runner as ExternalSegment + LinkedSegment pairs.",
        _record_schema(simulated, include_label=False),
        [reference],
    )


def simulated_run_segments(
    run_id: str,
    *,
    description: str,
    started_at: datetime,
    ended_at: datetime,
    record_count: int,
    sampling_interval_s: float,
    timeseries_endpoint: str,
    attachment_path: str,
    anomaly_label: int = 0,
) -> tuple[model.SubmodelElementCollection, model.SubmodelElementCollection]:
    """The ExternalSegment + LinkedSegment pair the simulation runner appends for a new run.

    Same element set as the recorded runs, so a consumer reads both kinds identically; only
    ``RunKind`` differs. ``attachment_path`` is the ``File`` value under which the runner
    uploads the run's CSV.
    """

    def common(base: str) -> list[model.SubmodelElement]:
        return [
            mlp("Name", run_id, _sem(f"{base}/Name")),
            mlp("Description", description, _sem(f"{base}/Description")),
            prop_typed("RecordCount", datatypes.Long, record_count, _sem(f"{base}/RecordCount")),
            prop("StartTime", started_at.isoformat(), _sem(f"{base}/StartTime")),
            prop("EndTime", ended_at.isoformat(), _sem(f"{base}/EndTime")),
            prop(
                "Duration",
                _iso_duration((ended_at - started_at).total_seconds()),
                _sem(f"{base}/Duration"),
            ),
            prop_typed(
                "SamplingInterval",
                datatypes.Long,
                round(sampling_interval_s * 1000),
                _sem(f"{base}/SamplingInterval"),
                description="Output interval in ms.",
            ),
            prop("State", "completed", _sem(f"{base}/State")),
            prop("LastUpdate", ended_at.isoformat(timespec="seconds"), _sem(f"{base}/LastUpdate")),
            prop("SchemaVariant", "simulated", semantic("Common", "SchemaVariant")),
            prop("RunKind", "simulated", semantic("Common", "RunKind")),
            prop("AnomalyLabel", anomaly_label, semantic("Common", "AnomalyLabel")),
        ]

    external = smc(
        f"Simulated_{run_id}",
        _sem(_EXT),
        *common(_EXT),
        file("File", attachment_path, "text/csv", _sem(f"{_EXT}/File")),
    )
    linked = smc(
        f"Linked_{run_id}",
        _sem(_LNK),
        *common(_LNK),
        prop_typed("Endpoint", datatypes.AnyURI, timeseries_endpoint, _sem(f"{_LNK}/Endpoint")),
        prop("Query", f"run_id={run_id}", _sem(f"{_LNK}/Query")),
    )
    return external, linked
