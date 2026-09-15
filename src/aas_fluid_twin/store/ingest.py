"""Loading recorded runs into the store, and checking they arrived intact.

The ingest streams each CSV through :func:`iter_samples`, so memory stays flat, and writes a
run in one transaction. Re-running replaces runs in place, so the ingest is idempotent.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from aas_fluid_twin.benchmark.datasets import RunMetadata
from aas_fluid_twin.benchmark.loader import iter_samples, load_series
from aas_fluid_twin.store.models import iter_sample_rows, run_record_from_metadata
from aas_fluid_twin.store.timescale import TimescaleStore

__all__ = ["IngestReport", "ingest_index", "ingest_run", "verify_run"]


@dataclass(frozen=True, slots=True)
class IngestReport:
    run_id: str
    rows_written: int
    record_count: int
    channel_count: int


def ingest_run(store: TimescaleStore, run: RunMetadata) -> IngestReport:
    """Write one recorded run (samples + point-in-time labels)."""
    record = run_record_from_metadata(run)
    # Two passes over the file: one for the long-format rows, one for the per-timestamp labels.
    # The files are ~370 rows; simplicity wins over a single fused pass.
    rows = iter_sample_rows(iter_samples(run))
    labels = ((s.relative_s, s.label) for s in iter_samples(run))
    written = store.write_run(record, rows, labels)
    channel_count = len([c for c in run.channels if c != "Anomaly"])
    return IngestReport(run.run_id, written, run.record_count, channel_count)


def ingest_index(
    store: TimescaleStore,
    runs: Iterable[RunMetadata],
    *,
    progress: Callable[[IngestReport], None] | None = None,
) -> list[IngestReport]:
    reports: list[IngestReport] = []
    for run in runs:
        report = ingest_run(store, run)
        reports.append(report)
        if progress is not None:
            progress(report)
    return reports


def verify_run(store: TimescaleStore, run: RunMetadata) -> list[str]:
    """Read the run back and compare it with the CSV. Returns the discrepancies (empty = ok)."""
    problems: list[str] = []
    local = load_series(run)
    served = store.query(run.run_id)
    if served is None:
        return [f"{run.run_id}: not in the store"]

    if len(served) != len(local):
        problems.append(f"{run.run_id}: {len(served)} timestamps served, {len(local)} in the CSV")
        return problems
    if served.t_rel_s != list(local.relative_s):
        problems.append(f"{run.run_id}: relative time axis differs")
    if served.timestamps != list(local.timestamps):
        problems.append(f"{run.run_id}: wall-clock timestamps differ")
    if served.labels != list(local.labels):
        problems.append(f"{run.run_id}: point-in-time labels differ")

    missing = set(local.columns) - set(served.channels)
    extra = set(served.channels) - set(local.columns)
    if missing or extra:
        problems.append(f"{run.run_id}: channel set differs (missing {missing}, extra {extra})")
    for channel, values in local.columns.items():
        got = served.channels.get(channel)
        if got is None:
            continue
        for expected, actual in zip(values, got, strict=True):
            if math.isnan(expected):
                if actual is not None:
                    problems.append(f"{run.run_id}/{channel}: NaN became {actual}")
                    break
            elif actual != expected:
                problems.append(f"{run.run_id}/{channel}: {actual} != {expected}")
                break
    return problems
