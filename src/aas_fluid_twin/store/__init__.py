"""Time-series store: TimescaleDB schema, ingest and query.

The AAS ``TimeSeries`` submodels reference runs here through ``LinkedSegment.Endpoint`` +
``Query``; the API in :mod:`aas_fluid_twin.api` resolves those against this store.
"""

from aas_fluid_twin.store.ingest import ingest_index, ingest_run, verify_run
from aas_fluid_twin.store.models import (
    FaultWindow,
    Origin,
    RunRecord,
    SampleRow,
    SeriesResult,
    TimeSeriesStore,
    iter_sample_rows,
    run_record_from_metadata,
)
from aas_fluid_twin.store.timescale import DEFAULT_DSN, TimescaleStore

__all__ = [
    "DEFAULT_DSN",
    "FaultWindow",
    "Origin",
    "RunRecord",
    "SampleRow",
    "SeriesResult",
    "TimeSeriesStore",
    "TimescaleStore",
    "ingest_index",
    "ingest_run",
    "iter_sample_rows",
    "run_record_from_metadata",
    "verify_run",
]
