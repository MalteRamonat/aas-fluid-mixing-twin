"""The dataset index and the sample loader.

The hermetic tests use synthetic CSVs written in the benchmark's exact shape. The
``benchmark_data`` tests pin facts about the real corpus that the AAS builders rely on.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from aas_fluid_twin.benchmark import (
    DatasetIndex,
    Scenario,
    SchemaVariant,
    SignalDictionary,
    build_dataset_index,
    iter_samples,
    load_series,
)
from aas_fluid_twin.benchmark.datasets import ANOMALY_COLUMN

# --- hermetic -----------------------------------------------------------------


def test_index_reads_synthetic_runs(synthetic_dataset_dir: Path) -> None:
    index = build_dataset_index(synthetic_dataset_dir)
    assert [r.run_id for r in index] == [
        "dataset_0_normal_behaviour",
        "dataset_10_leakage",
    ]
    normal = index.by_id("dataset_0_normal_behaviour")
    assert normal.scenario is Scenario.NORMAL_BEHAVIOUR
    assert normal.label == 0
    assert normal.record_count == 3
    assert normal.is_normal


def test_reduced_schema_is_detected_not_dropped(synthetic_dataset_dir: Path) -> None:
    """The majority channel set defines the full schema; the odd one out is flagged."""
    index = build_dataset_index(synthetic_dataset_dir)
    reduced = index.by_id("dataset_0_normal_behaviour")
    full = index.by_id("dataset_10_leakage")
    assert full.schema_variant is SchemaVariant.FULL
    assert reduced.schema_variant is SchemaVariant.REDUCED
    assert reduced.missing_channels == ("Pressure_below_B201",)


def test_index_rejects_a_filename_it_cannot_parse(tmp_path: Path) -> None:
    (tmp_path / "dataset_nope.csv").write_text("Server Time,Session Time Stamps\n", "utf-8")
    with pytest.raises(ValueError, match="unexpected dataset filename"):
        build_dataset_index(tmp_path)


def test_index_rejects_unexpected_leading_columns(tmp_path: Path) -> None:
    (tmp_path / "dataset_1_normal_behaviour.csv").write_text("t,x,Anomaly\n1,2,0\n", "utf-8")
    with pytest.raises(ValueError, match="unexpected leading columns"):
        build_dataset_index(tmp_path)


def test_missing_dataset_dir_says_what_to_do(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="fetch_benchmark"):
        build_dataset_index(tmp_path / "absent")


def test_loader_returns_columns_and_streams_identically(synthetic_dataset_dir: Path) -> None:
    index = build_dataset_index(synthetic_dataset_dir)
    run = index.by_id("dataset_10_leakage")

    series = load_series(run)
    assert len(series) == 3
    assert series.channel("Tank_B201_Volume") == (2061.1, 2061.0, 2000.0)
    assert series.channel("Valve_V201_opening") == (0.0, 1.0, 1.0)
    assert not series.has("Anomaly")  # the label is resolved, not passed through

    streamed = [s.values["Tank_B201_Volume"] for s in iter_samples(run)]
    assert tuple(streamed) == series.channel("Tank_B201_Volume")


def test_loader_rejects_an_unknown_channel(synthetic_dataset_dir: Path) -> None:
    index = build_dataset_index(synthetic_dataset_dir)
    run = index.by_id("dataset_0_normal_behaviour")
    with pytest.raises(KeyError, match="no channel"):
        load_series(run, ["Pressure_below_B201"])


def test_empty_cells_become_nan_rather_than_raising(tmp_path: Path) -> None:
    from tests.conftest import write_csv

    write_csv(tmp_path / "dataset_1_normal_behaviour.csv", ["X", "Anomaly"], [[1.0, 0], ["", 0]])
    index = build_dataset_index(tmp_path)
    series = load_series(index.by_id("dataset_1_normal_behaviour"))
    values = series.channel("X")
    assert values[0] == 1.0
    assert math.isnan(values[1])


# --- point-in-time labelling --------------------------------------------------


def test_label_at_resolves_onsets(index: DatasetIndex) -> None:
    """The CSV's Anomaly column is constant per run; the onsets make it per sample."""
    leakage = index.by_id("dataset_10_leakage")
    assert leakage.label == 1
    assert leakage.label_at(0.0) == 0
    assert leakage.label_at(65.9) == 0
    assert leakage.label_at(66.0) == 1
    assert leakage.label_at(599.0) == 1


def test_label_at_handles_bounded_windows(index: DatasetIndex) -> None:
    stirring = index.by_id("dataset_44_stirring_error")
    assert stirring.label == 7
    assert stirring.label_at(50.0) == 0
    assert stirring.label_at(90.0) == 7
    assert stirring.label_at(150.0) == 0
    assert stirring.label_at(275.0) == 7
    assert stirring.label_at(460.0) == 7
    assert stirring.label_at(500.0) == 0


def test_normal_runs_stay_labelled_zero(index: DatasetIndex) -> None:
    run = index.by_id("dataset_1_normal_behaviour")
    assert run.label_at(0.0) == 0
    assert run.label_at(300.0) == 0


# --- the real corpus ----------------------------------------------------------


@pytest.mark.benchmark_data
def test_corpus_shape(index: DatasetIndex) -> None:
    assert len(index) == 55
    assert len(index.normal) == 33
    assert len(index.faulty) == 22


@pytest.mark.benchmark_data
def test_scenario_counts(index: DatasetIndex) -> None:
    counts = {s: len(index.with_scenario(s)) for s in Scenario}
    assert counts == {
        Scenario.NORMAL_BEHAVIOUR: 33,
        Scenario.LEAKAGE: 2,
        Scenario.CLOGGING: 3,
        Scenario.LEAKAGE_AND_CLOGGING: 1,
        Scenario.CHANGED_INITIAL_STATE: 1,
        Scenario.RECONFIGURATION: 4,
        Scenario.SENSOR_ERRORS: 2,
        Scenario.STIRRING_ERROR: 1,
        Scenario.MANUAL_MODE: 8,
    }


@pytest.mark.benchmark_data
def test_only_dataset_0_has_the_reduced_schema(index: DatasetIndex) -> None:
    reduced = [r for r in index if r.schema_variant is SchemaVariant.REDUCED]
    assert [r.run_id for r in reduced] == ["dataset_0_normal_behaviour"]
    assert len(index.full_schema_channels) == 48
    assert len(reduced[0].channels) == 40
    # The eight it lacks are exactly the pressure-derived levels.
    assert all("_via_PI25" in c for c in reduced[0].missing_channels)
    assert len(reduced[0].missing_channels) == 8


@pytest.mark.benchmark_data
def test_runs_are_about_ten_minutes_at_roughly_1_6_seconds(index: DatasetIndex) -> None:
    short = {r.run_id for r in index if r.duration_s < 300}
    assert short == {"dataset_47_manual_mode"}  # 179 s, the one deliberate exception

    for run in index:
        if run.run_id in short:
            continue
        assert 598.0 <= run.duration_s <= 601.0, run.run_id
        assert 1.5 <= run.sampling_interval_s <= 1.8, run.run_id


@pytest.mark.benchmark_data
def test_file_level_anomaly_column_matches_the_scenario(index: DatasetIndex) -> None:
    """Guards the label encoding derived in Phase 1 against an upstream change."""
    for run in index:
        series = load_series(run, ["Anomaly"])
        values = set(series.channel("Anomaly"))
        assert values == {float(run.label)}, run.run_id


@pytest.mark.benchmark_data
def test_unusable_and_excluded_runs_are_flagged(index: DatasetIndex) -> None:
    changed = index.by_id("dataset_14_changed_initial_state")
    assert not changed.usable
    assert changed.unusable_reason
    assert not changed.use_for_anomaly_detection

    for run in index.with_scenario(Scenario.MANUAL_MODE):
        assert not run.use_for_anomaly_detection

    assert index.by_id("dataset_10_leakage").use_for_anomaly_detection


@pytest.mark.benchmark_data
def test_reconfiguration_runs_carry_their_sub_scenario(index: DatasetIndex) -> None:
    assert index.by_id("dataset_12_reconfiguration").sub_scenario_key == "leak_recirculated_to_B201"
    assert index.by_id("dataset_41_reconfiguration").sub_scenario_key == "leak_recirculated_to_B201"
    assert index.by_id("dataset_26_reconfiguration").sub_scenario_key == "B204_crossover_via_V210"
    assert index.by_id("dataset_46_reconfiguration").sub_scenario_key == "B204_crossover_via_V210"


@pytest.mark.benchmark_data
def test_every_channel_is_in_the_signal_dictionary(
    index: DatasetIndex, signals: SignalDictionary
) -> None:
    known = set(signals.channels) | {ANOMALY_COLUMN}
    for run in index:
        unknown = set(run.channels) - known
        assert not unknown, f"{run.run_id}: {unknown}"
