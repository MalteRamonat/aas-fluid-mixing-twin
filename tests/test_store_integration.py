"""Round trip through a live TimescaleDB, and through the API container in front of it.

Needs the Docker stack (``docker compose up -d``) and the benchmark data. Skipped otherwise.
The tests write to a scratch run id and remove it afterwards, so they do not disturb the
ingested benchmark runs. Point ``AAS_TIMESERIES_DSN`` / ``AAS_API_URL`` elsewhere to test
against other instances.
"""

from __future__ import annotations

import dataclasses
import math
import os
from collections.abc import Iterator
from datetime import datetime

import httpx
import pytest

from aas_fluid_twin.benchmark.datasets import DatasetIndex, RunMetadata
from aas_fluid_twin.benchmark.loader import load_series
from aas_fluid_twin.store import (
    DEFAULT_DSN,
    Origin,
    RunRecord,
    SampleRow,
    TimescaleStore,
    ingest_run,
    verify_run,
)

pytestmark = [pytest.mark.integration, pytest.mark.benchmark_data]

API_URL = os.environ.get("AAS_API_URL", "http://localhost:8000")
SCRATCH_PREFIX = "test_scratch_"


@pytest.fixture(scope="module")
def store() -> TimescaleStore:
    instance = TimescaleStore(DEFAULT_DSN)
    if not instance.is_up():
        pytest.skip(f"no TimescaleDB at {DEFAULT_DSN} — `docker compose up -d`")
    instance.apply_schema()
    return instance


@pytest.fixture
def scratch_run(store: TimescaleStore, index: DatasetIndex) -> Iterator[RunMetadata]:
    """dataset_10 re-labelled with a scratch id, so the ingested copy stays untouched."""
    original = index.by_id("dataset_10_leakage")
    run = dataclasses.replace(original, run_id=SCRATCH_PREFIX + original.run_id)
    yield run
    store.delete_run(run.run_id)


def test_ingest_is_idempotent_and_verifies_against_the_csv(
    store: TimescaleStore, scratch_run: RunMetadata
) -> None:
    first = ingest_run(store, scratch_run)
    second = ingest_run(store, scratch_run)
    assert first.rows_written == second.rows_written == scratch_run.record_count * 47
    assert store.sample_count(scratch_run.run_id) == first.rows_written
    assert verify_run(store, scratch_run) == []


def test_window_and_channel_subset(store: TimescaleStore, scratch_run: RunMetadata) -> None:
    ingest_run(store, scratch_run)
    local = load_series(scratch_run, ["Tank_B201_Volume", "Flow_after_Pump_P201"])
    served = store.query(
        scratch_run.run_id, ["Tank_B201_Volume", "Flow_after_Pump_P201"], from_s=100, to_s=200
    )
    assert served is not None
    keep = [i for i, t in enumerate(local.relative_s) if 100 <= t <= 200]
    assert served.t_rel_s == [local.relative_s[i] for i in keep]
    assert served.channels["Tank_B201_Volume"] == [
        local.columns["Tank_B201_Volume"][i] for i in keep
    ]
    assert served.labels == [local.labels[i] for i in keep]
    assert set(served.channels) == {"Tank_B201_Volume", "Flow_after_Pump_P201"}


def test_requested_but_absent_channel_comes_back_as_nulls(
    store: TimescaleStore, scratch_run: RunMetadata
) -> None:
    ingest_run(store, scratch_run)
    served = store.query(scratch_run.run_id, ["Tank_B201_Volume", "not_a_channel"])
    assert served is not None
    assert served.channels["not_a_channel"] == [None] * len(served)


def test_simulated_run_shares_the_schema(store: TimescaleStore) -> None:
    run_id = SCRATCH_PREFIX + "sim"
    record = RunRecord(
        run_id=run_id,
        origin=Origin.SIMULATED,
        scenario="normal_behaviour",
        anomaly_label=0,
        started_at=datetime(2024, 12, 6, 10, 24, 32),
        ended_at=datetime(2024, 12, 6, 10, 34, 32),
        duration_s=600.0,
        record_count=2,
        schema_variant="simulated",
        params={"stopTime": 600, "solver": "cvode"},
    )
    rows = [
        SampleRow(record.started_at, 0.0, "Tank_B201_Volume", 1000.0),
        SampleRow(record.started_at, 0.0, "Flow_after_Pump_P201", math.nan),
        SampleRow(record.ended_at, 600.0, "Tank_B201_Volume", 900.0),
        SampleRow(record.ended_at, 600.0, "Flow_after_Pump_P201", 0.0),
    ]
    try:
        store.write_run(record, rows, [(0.0, 0), (600.0, 0)])
        back = store.get_run(run_id)
        assert back is not None
        assert back.origin is Origin.SIMULATED
        assert back.params == {"stopTime": 600, "solver": "cvode"}
        listed = {r.run_id for r in store.list_runs(Origin.SIMULATED)}
        assert run_id in listed
        assert store.channels(run_id) == ["Flow_after_Pump_P201", "Tank_B201_Volume"]
    finally:
        store.delete_run(run_id)
    assert store.get_run(run_id) is None


def test_ingested_benchmark_runs_are_all_present(
    store: TimescaleStore, index: DatasetIndex
) -> None:
    """After `docker compose up` (or scripts/ingest_timeseries.py) every recorded run is there."""
    present = {r.run_id for r in store.list_runs(Origin.MEASURED)}
    expected = {r.run_id for r in index}
    missing = expected - present
    if missing:
        pytest.skip(f"{len(missing)} runs not ingested yet — run scripts/ingest_timeseries.py")
    for run in list(index)[:3]:
        assert verify_run(store, run) == []


def test_api_container_resolves_the_linked_segment(index: DatasetIndex) -> None:
    """The AAS says Endpoint=http://localhost:8000/api/timeseries, Query=run_id=<id>."""
    try:
        health = httpx.get(f"{API_URL}/api/health", timeout=5.0)
    except httpx.HTTPError:
        pytest.skip(f"no API at {API_URL}")
    assert health.json()["status"] == "UP"

    run = index.by_id("dataset_10_leakage")
    response = httpx.get(f"{API_URL}/api/timeseries", params={"run_id": run.run_id}, timeout=30.0)
    if response.status_code == 404:
        pytest.skip("dataset_10_leakage not ingested yet")
    assert response.status_code == 200
    body = response.json()
    local = load_series(run)
    assert body["t_rel_s"] == list(local.relative_s)
    assert body["labels"] == list(local.labels)
    assert body["channels"]["Tank_B204_Volume"] == list(local.columns["Tank_B204_Volume"])
    assert len(body["channels"]) == 47
