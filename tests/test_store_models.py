"""The store's adapters from the benchmark layer — no database needed."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from aas_fluid_twin.benchmark.annotations import FaultEvent, OnsetSource
from aas_fluid_twin.benchmark.datasets import RunMetadata, Scenario, SchemaVariant
from aas_fluid_twin.benchmark.loader import Sample
from aas_fluid_twin.store import (
    FaultWindow,
    Origin,
    iter_sample_rows,
    run_record_from_metadata,
)


def _run(**overrides: object) -> RunMetadata:
    base: dict[str, object] = {
        "run_id": "dataset_10_leakage",
        "number": 10,
        "scenario": Scenario.LEAKAGE,
        "label": 1,
        "path": Path("dataset_10_leakage.csv"),
        "channels": ("a", "b", "Anomaly"),
        "record_count": 2,
        "started_at": datetime(2024, 1, 22, 0, 24, 59),
        "ended_at": datetime(2024, 1, 22, 0, 34, 59),
        "first_relative_s": 0.6,
        "last_relative_s": 600.6,
        "schema_variant": SchemaVariant.FULL,
        "missing_channels": (),
        "events": (FaultEvent(onset_s=66.0, end_s=None, source=OnsetSource.OPERATOR_LOG),),
    }
    base.update(overrides)
    return RunMetadata(**base)  # type: ignore[arg-type]


def test_run_record_carries_fault_windows_and_provenance() -> None:
    record = run_record_from_metadata(_run())
    assert record.origin is Origin.MEASURED
    assert record.scenario == "leakage"
    assert record.anomaly_label == 1
    assert record.schema_variant == "full"
    assert record.source_file == "dataset_10_leakage.csv"
    assert record.duration_s == 600.0
    assert record.fault_windows == (
        FaultWindow(label=1, onset_s=66.0, end_s=None, source="operator_log"),
    )
    assert record.params is None


def test_unusable_run_keeps_its_reason() -> None:
    record = run_record_from_metadata(
        _run(usable=False, unusable_reason="not to be used", events=())
    )
    assert record.usable is False
    assert record.note == "not to be used"
    assert record.fault_windows == ()


def test_fault_window_json_round_trip() -> None:
    window = FaultWindow(label=7, onset_s=84.0, end_s=99.0, source="operator_log")
    assert FaultWindow.from_json(window.to_json()) == window
    assert FaultWindow.from_json({"label": 1, "source": "unknown"}) == FaultWindow(
        1, None, None, "unknown"
    )


def test_sample_rows_are_long_format_with_nan_as_null() -> None:
    samples = [
        Sample(datetime(2024, 1, 1), 0.5, {"a": 1.0, "b": float("nan")}, 0),
        Sample(datetime(2024, 1, 1, 0, 0, 2), 2.5, {"a": 3.0, "b": 4.0}, 1),
    ]
    rows = list(iter_sample_rows(samples))
    assert [(r.t_rel_s, r.channel, r.value) for r in rows] == [
        (0.5, "a", 1.0),
        (0.5, "b", None),
        (2.5, "a", 3.0),
        (2.5, "b", 4.0),
    ]
    assert rows[0].ts == datetime(2024, 1, 1)
