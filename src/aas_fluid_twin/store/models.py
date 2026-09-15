"""Records exchanged with the time-series store.

These are deliberately independent of both the benchmark loader and the database driver: the
ingest turns :class:`~aas_fluid_twin.benchmark.datasets.RunMetadata` into a :class:`RunRecord`,
the simulation runner builds one from its own result, and the API serialises whichever it
reads back. The store itself never imports from ``benchmark``.
"""

from __future__ import annotations

import enum
import math
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from aas_fluid_twin.benchmark.datasets import RunMetadata
from aas_fluid_twin.benchmark.loader import Sample

__all__ = [
    "FaultWindow",
    "Origin",
    "RunRecord",
    "SampleRow",
    "SeriesResult",
    "TimeSeriesStore",
    "WritableTimeSeriesStore",
    "iter_sample_rows",
    "run_record_from_metadata",
]


class Origin(enum.StrEnum):
    MEASURED = "measured"
    SIMULATED = "simulated"


@dataclass(frozen=True, slots=True)
class FaultWindow:
    """One fault interval of a run, in seconds on the run's relative time axis."""

    label: int
    onset_s: float | None
    end_s: float | None
    source: str

    def to_json(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "onset_s": self.onset_s,
            "end_s": self.end_s,
            "source": self.source,
        }

    @classmethod
    def from_json(cls, raw: Mapping[str, Any]) -> FaultWindow:
        return cls(
            label=int(raw["label"]),
            onset_s=None if raw.get("onset_s") is None else float(raw["onset_s"]),
            end_s=None if raw.get("end_s") is None else float(raw["end_s"]),
            source=str(raw["source"]),
        )


@dataclass(frozen=True, slots=True)
class RunRecord:
    """The ``run`` row: everything about a run except its samples."""

    run_id: str
    origin: Origin
    scenario: str
    anomaly_label: int
    started_at: datetime
    ended_at: datetime
    duration_s: float
    record_count: int
    schema_variant: str
    source_file: str | None = None
    usable: bool = True
    note: str | None = None
    fault_windows: tuple[FaultWindow, ...] = ()
    params: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class SampleRow:
    """One ``sample`` row. ``value`` is ``None`` for an empty CSV cell."""

    ts: datetime
    t_rel_s: float
    channel: str
    value: float | None


@dataclass(frozen=True, slots=True)
class SeriesResult:
    """A run, or a window of it, in column form — the shape the API returns."""

    run_id: str
    origin: Origin
    t_rel_s: list[float]
    timestamps: list[datetime]
    labels: list[int]
    channels: dict[str, list[float | None]] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.t_rel_s)


class TimeSeriesStore(Protocol):
    """What the API needs from a store. ``TimescaleStore`` implements it; tests fake it."""

    def list_runs(self, origin: Origin | None = None) -> list[RunRecord]: ...

    def get_run(self, run_id: str) -> RunRecord | None: ...

    def channels(self, run_id: str) -> list[str]: ...

    def query(
        self,
        run_id: str,
        channels: Sequence[str] | None = None,
        *,
        from_s: float | None = None,
        to_s: float | None = None,
    ) -> SeriesResult | None: ...


# --- adapters from the benchmark layer -------------------------------------------


class WritableTimeSeriesStore(Protocol):
    """The write side, all the simulation runner needs (``TimescaleStore`` implements both)."""

    def write_run(
        self,
        record: RunRecord,
        samples: Iterable[SampleRow],
        labels: Iterable[tuple[float, int]],
    ) -> int: ...


def run_record_from_metadata(run: RunMetadata) -> RunRecord:
    windows = tuple(
        FaultWindow(label=run.label, onset_s=e.onset_s, end_s=e.end_s, source=str(e.source))
        for e in run.events
    )
    return RunRecord(
        run_id=run.run_id,
        origin=Origin.MEASURED,
        scenario=str(run.scenario),
        anomaly_label=run.label,
        started_at=run.started_at,
        ended_at=run.ended_at,
        duration_s=run.duration_s,
        record_count=run.record_count,
        schema_variant=str(run.schema_variant),
        source_file=run.path.name,
        usable=run.usable,
        note=run.unusable_reason or run.note,
        fault_windows=windows,
        params=None,
    )


def iter_sample_rows(samples: Iterator[Sample] | Sequence[Sample]) -> Iterator[SampleRow]:
    """Flatten loader samples into long-format rows. NaN becomes NULL."""
    for sample in samples:
        for channel, value in sample.values.items():
            yield SampleRow(
                ts=sample.timestamp,
                t_rel_s=sample.relative_s,
                channel=channel,
                value=None if math.isnan(value) else value,
            )
