"""Reading samples out of a recorded run.

Two access shapes, because two consumers need different things:

* :func:`iter_samples` streams one :class:`Sample` at a time — what the time-series ingest
  wants, since it never needs the whole run resident.
* :func:`load_series` returns column arrays — what plotting and statistics want.

Both resolve the point-in-time anomaly label from the operator's onset times rather than
the file-level ``Anomaly`` column, which is constant for a whole run.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from aas_fluid_twin.benchmark.datasets import (
    ANOMALY_COLUMN,
    RELATIVE_TIME_COLUMN,
    SERVER_TIME_COLUMN,
    RunMetadata,
)

__all__ = ["RunSeries", "Sample", "iter_samples", "load_series"]


@dataclass(frozen=True, slots=True)
class Sample:
    """One row of a run."""

    timestamp: datetime
    relative_s: float
    values: Mapping[str, float]
    label: int
    """Point-in-time label, resolved from the run's fault events. See
    :meth:`RunMetadata.label_at`."""


@dataclass(frozen=True, slots=True)
class RunSeries:
    """A run in column form."""

    run: RunMetadata
    timestamps: tuple[datetime, ...]
    relative_s: tuple[float, ...]
    columns: Mapping[str, tuple[float, ...]]
    labels: tuple[int, ...]

    def __len__(self) -> int:
        return len(self.relative_s)

    def channel(self, name: str) -> tuple[float, ...]:
        try:
            return self.columns[name]
        except KeyError:
            available = "reduced schema" if name in self.run.missing_channels else "unknown"
            raise KeyError(f"channel {name!r} not in {self.run.run_id} ({available})") from None

    def has(self, name: str) -> bool:
        return name in self.columns


def _float(text: str) -> float:
    """Parse a CSV cell.

    Empty cells become NaN rather than raising: a missing sample is data, not corruption,
    and the ingest records it as NULL.
    """
    stripped = text.strip()
    if not stripped:
        return float("nan")
    return float(stripped)


def _channels_to_read(run: RunMetadata, channels: Iterable[str] | None) -> tuple[str, ...]:
    if channels is None:
        return tuple(c for c in run.channels if c != ANOMALY_COLUMN)
    requested = tuple(channels)
    unknown = [c for c in requested if c not in run.channels]
    if unknown:
        raise KeyError(f"{run.run_id} has no channel(s): {unknown}")
    return requested


def iter_samples(
    run: RunMetadata,
    channels: Sequence[str] | None = None,
) -> Iterator[Sample]:
    """Stream a run row by row, without holding it in memory."""
    wanted = _channels_to_read(run, channels)

    with run.path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            relative = _float(row[RELATIVE_TIME_COLUMN])
            yield Sample(
                timestamp=datetime.fromisoformat(row[SERVER_TIME_COLUMN].strip()),
                relative_s=relative,
                values={name: _float(row[name]) for name in wanted},
                label=run.label_at(relative),
            )


def load_series(
    run: RunMetadata,
    channels: Sequence[str] | None = None,
) -> RunSeries:
    """Load a whole run into column arrays."""
    wanted = _channels_to_read(run, channels)

    timestamps: list[datetime] = []
    relative: list[float] = []
    labels: list[int] = []
    columns: dict[str, list[float]] = {name: [] for name in wanted}

    for sample in iter_samples(run, wanted):
        timestamps.append(sample.timestamp)
        relative.append(sample.relative_s)
        labels.append(sample.label)
        for name in wanted:
            columns[name].append(sample.values[name])

    if len(relative) != run.record_count:
        raise ValueError(
            f"{run.run_id}: read {len(relative)} rows but the index says {run.record_count}"
        )

    return RunSeries(
        run=run,
        timestamps=tuple(timestamps),
        relative_s=tuple(relative),
        columns={name: tuple(values) for name, values in columns.items()},
        labels=tuple(labels),
    )
