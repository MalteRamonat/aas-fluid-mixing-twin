"""The fault annotations are plant knowledge that exists nowhere else.

These tests pin the operator's answers so a careless edit to the YAML is caught, and they
enforce the invariant that matters most: an estimate must never be presented as ground truth.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from aas_fluid_twin.benchmark import FaultAnnotations, OnsetSource, load_fault_annotations
from aas_fluid_twin.benchmark.datasets import SCENARIO_LABELS, Scenario

#: Onsets as given by the plant author, 2026-09-11. Ground truth.
EXPECTED_ONSETS: dict[str, tuple[tuple[float, float | None], ...]] = {
    "dataset_10_leakage": ((66.0, None),),
    "dataset_11_leakage": ((322.0, None),),
    "dataset_13_leakage_and_clogging": ((69.0, None),),
    "dataset_15_clogging": ((77.0, None),),
    "dataset_40_clogging": ((84.0, None),),
    "dataset_42_clogging": ((120.0, None),),
    "dataset_12_reconfiguration": ((29.0, None),),
    "dataset_41_reconfiguration": ((34.0, None),),
    "dataset_26_reconfiguration": ((16.0, None),),
    "dataset_46_reconfiguration": ((20.0, None),),
    "dataset_43_sensor_errors": ((66.0, None),),
    "dataset_45_sensor_errors": ((0.0, None),),
    "dataset_44_stirring_error": ((84.0, 99.0), (267.0, 283.0), (450.0, 467.0)),
}


def test_every_scenario_label_matches_the_dataset_index(
    fault_annotations: FaultAnnotations,
) -> None:
    for scenario, label in SCENARIO_LABELS.items():
        assert fault_annotations.scenario(scenario.value).label == label


def test_onsets_match_the_operator_record(fault_annotations: FaultAnnotations) -> None:
    for run_id, expected in EXPECTED_ONSETS.items():
        events = fault_annotations.events_for(run_id)
        actual = tuple((e.onset_s, e.end_s) for e in events)
        assert actual == expected, run_id
        assert all(e.source is OnsetSource.OPERATOR_LOG for e in events), run_id


def test_only_the_stirring_error_run_has_bounded_windows(
    fault_annotations: FaultAnnotations,
) -> None:
    bounded = {
        run_id
        for run_id, annotation in fault_annotations.runs.items()
        if annotation.has_bounded_events
    }
    assert bounded == {"dataset_44_stirring_error"}


def test_runs_excluded_from_anomaly_detection(fault_annotations: FaultAnnotations) -> None:
    assert not fault_annotations.scenario(Scenario.MANUAL_MODE.value).use_for_anomaly_detection
    changed = fault_annotations.scenario(Scenario.CHANGED_INITIAL_STATE.value)
    assert not changed.use_for_anomaly_detection

    unusable = fault_annotations.for_run("dataset_14_changed_initial_state")
    assert unusable is not None
    assert unusable.usable is False
    assert unusable.reason


def test_reconfiguration_splits_into_two_sub_scenarios(fault_annotations: FaultAnnotations) -> None:
    spec = fault_annotations.scenario(Scenario.RECONFIGURATION.value)
    keys = {sub.key for sub in spec.sub_scenarios}
    assert keys == {"leak_recirculated_to_B201", "B204_crossover_via_V210"}

    assert spec.sub_scenario("leak_recirculated_to_B201").runs == (
        "dataset_12_reconfiguration",
        "dataset_41_reconfiguration",
    )
    assert spec.sub_scenario("B204_crossover_via_V210").runs == (
        "dataset_26_reconfiguration",
        "dataset_46_reconfiguration",
    )


def test_fault_injection_points_are_named(fault_annotations: FaultAnnotations) -> None:
    """The valves the author used must be reachable from the catalogue, not just prose."""
    assert "V211" in fault_annotations.scenario("leakage").affected_components
    assert "V212" in fault_annotations.scenario("clogging").affected_components
    assert (
        "V210"
        in fault_annotations.scenario("reconfiguration")
        .sub_scenario("B204_crossover_via_V210")
        .affected_components
    )
    assert "R201" in fault_annotations.scenario("stirring_error").affected_components


def test_event_covers_resolves_windows(fault_annotations: FaultAnnotations) -> None:
    first, second, third = fault_annotations.events_for("dataset_44_stirring_error")
    assert not first.covers(83.0)
    assert first.covers(84.0)
    assert first.covers(99.0)
    assert not first.covers(99.5)
    assert second.covers(275.0)
    assert third.covers(460.0)

    (leak,) = fault_annotations.events_for("dataset_10_leakage")
    assert leak.runs_to_end
    assert not leak.covers(65.9)
    assert leak.covers(600.0)


def _write(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "annotations.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def test_rejects_a_schema_version_it_does_not_understand(tmp_path: Path) -> None:
    path = _write(tmp_path, {"schema_version": 99, "scenarios": {}, "runs": {}})
    with pytest.raises(ValueError, match="schema_version"):
        load_fault_annotations(path)


def test_rejects_two_scenarios_sharing_a_label(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {
            "schema_version": 1,
            "scenarios": {
                "a": {"label": 1, "description": "a"},
                "b": {"label": 1, "description": "b"},
            },
            "runs": {},
        },
    )
    with pytest.raises(ValueError, match="share an Anomaly label"):
        load_fault_annotations(path)


def test_rejects_an_event_that_ends_before_it_starts(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {
            "schema_version": 1,
            "scenarios": {"a": {"label": 1, "description": "a"}},
            "runs": {
                "r": {
                    "scenario": "a",
                    "events": [{"onset_s": 100, "end_s": 50, "source": "operator_log"}],
                }
            },
        },
    )
    with pytest.raises(ValueError, match=r"ends .* before it starts"):
        load_fault_annotations(path)


def test_rejects_a_sub_scenario_claiming_an_unannotated_run(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        {
            "schema_version": 1,
            "scenarios": {
                "a": {
                    "label": 1,
                    "description": "a",
                    "sub_scenarios": {"variant": {"runs": ["ghost_run"]}},
                }
            },
            "runs": {},
        },
    )
    with pytest.raises(ValueError, match="not annotated with it"):
        load_fault_annotations(path)
