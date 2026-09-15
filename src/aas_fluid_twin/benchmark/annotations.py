"""Fault annotations: how each scenario was induced, and when each fault started.

Backed by ``data/fault_annotations.yaml``, which is version-controlled and reviewable
because the values in it are plant knowledge that exists nowhere in the benchmark files.

The dataset's own ``Anomaly`` column is constant for a whole run, so it carries no onset.
Onsets therefore come from here, and every event records *where the value came from*
(:class:`OnsetSource`) so a consumer can always separate ground truth from an estimate.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from aas_fluid_twin import config

__all__ = [
    "FaultAnnotations",
    "FaultEvent",
    "OnsetSource",
    "RunAnnotation",
    "ScenarioSpec",
    "SubScenarioSpec",
    "load_fault_annotations",
]

SCHEMA_VERSION = 1


class OnsetSource(enum.StrEnum):
    """Where an onset time came from. Never upgrade an estimate to ``OPERATOR_LOG``."""

    OPERATOR_LOG = "operator_log"
    ESTIMATED_CHANGEPOINT = "estimated_changepoint"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class FaultEvent:
    """One fault window within a run, in seconds on ``Session Time Stamps``."""

    onset_s: float | None
    end_s: float | None
    source: OnsetSource

    @property
    def is_ground_truth(self) -> bool:
        return self.source is OnsetSource.OPERATOR_LOG

    @property
    def runs_to_end(self) -> bool:
        """True when the fault persists to the end of the run rather than being bounded."""
        return self.end_s is None

    def covers(self, t: float) -> bool:
        if self.onset_s is None:
            return False
        if t < self.onset_s:
            return False
        return self.end_s is None or t <= self.end_s


@dataclass(frozen=True, slots=True)
class SubScenarioSpec:
    """A physically distinct variant sharing a parent's ``Anomaly`` label."""

    key: str
    description: str
    induction: str
    affected_components: tuple[str, ...]
    runs: tuple[str, ...]
    injection_points: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScenarioSpec:
    key: str
    label: int
    description: str
    induction: str | None
    affected_components: tuple[str, ...]
    use_for_anomaly_detection: bool
    note: str | None = None
    sub_scenarios: tuple[SubScenarioSpec, ...] = ()
    injection_points: tuple[str, ...] = ()
    """Plant elements at which the fault was physically induced."""

    def sub_scenario(self, key: str) -> SubScenarioSpec:
        for sub in self.sub_scenarios:
            if sub.key == key:
                return sub
        raise KeyError(f"scenario {self.key!r} has no sub-scenario {key!r}")


@dataclass(frozen=True, slots=True)
class RunAnnotation:
    run_id: str
    scenario_key: str
    usable: bool
    events: tuple[FaultEvent, ...]
    sub_scenario_key: str | None = None
    reason: str | None = None
    note: str | None = None

    @property
    def has_bounded_events(self) -> bool:
        return any(not e.runs_to_end for e in self.events)


@dataclass(frozen=True, slots=True)
class FaultAnnotations:
    scenarios: Mapping[str, ScenarioSpec]
    runs: Mapping[str, RunAnnotation]

    def scenario(self, key: str) -> ScenarioSpec:
        try:
            return self.scenarios[key]
        except KeyError:
            raise KeyError(f"unknown scenario {key!r}") from None

    def scenario_for_label(self, label: int) -> ScenarioSpec:
        for spec in self.scenarios.values():
            if spec.label == label:
                return spec
        raise KeyError(f"no scenario with Anomaly label {label}")

    def for_run(self, run_id: str) -> RunAnnotation | None:
        return self.runs.get(run_id)

    def events_for(self, run_id: str) -> tuple[FaultEvent, ...]:
        annotation = self.runs.get(run_id)
        return annotation.events if annotation else ()


def _tuple_of_str(value: Any) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(str(item) for item in value)


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _parse_events(raw: Any) -> tuple[FaultEvent, ...]:
    if not raw:
        return ()
    events: list[FaultEvent] = []
    for item in raw:
        onset = _optional_float(item.get("onset_s"))
        end = _optional_float(item.get("end_s"))
        if onset is not None and end is not None and end < onset:
            raise ValueError(f"fault event ends ({end}) before it starts ({onset})")
        events.append(
            FaultEvent(
                onset_s=onset,
                end_s=end,
                source=OnsetSource(str(item.get("source", "unknown"))),
            )
        )
    return tuple(events)


def load_fault_annotations(path: Path | None = None) -> FaultAnnotations:
    """Read and validate ``data/fault_annotations.yaml``."""
    source = path or config.FAULT_ANNOTATIONS_FILE
    raw: dict[str, Any] = yaml.safe_load(source.read_text(encoding="utf-8"))

    version = int(raw.get("schema_version", 0))
    if version != SCHEMA_VERSION:
        raise ValueError(
            f"{source} has schema_version {version}, this code expects {SCHEMA_VERSION}"
        )

    scenarios: dict[str, ScenarioSpec] = {}
    for key, record in raw.get("scenarios", {}).items():
        subs = tuple(
            SubScenarioSpec(
                key=sub_key,
                description=str(sub.get("description", "")).strip(),
                induction=str(sub.get("induction", "")).strip(),
                affected_components=_tuple_of_str(sub.get("affected_components")),
                runs=_tuple_of_str(sub.get("runs")),
                injection_points=_tuple_of_str(sub.get("injection_points")),
            )
            for sub_key, sub in (record.get("sub_scenarios") or {}).items()
        )
        scenarios[key] = ScenarioSpec(
            key=key,
            label=int(record["label"]),
            description=str(record.get("description", "")).strip(),
            induction=(str(record["induction"]).strip() if record.get("induction") else None),
            affected_components=_tuple_of_str(record.get("affected_components")),
            use_for_anomaly_detection=bool(record.get("use_for_anomaly_detection", True)),
            note=(str(record["note"]).strip() if record.get("note") else None),
            sub_scenarios=subs,
            injection_points=_tuple_of_str(record.get("injection_points")),
        )

    labels = [spec.label for spec in scenarios.values()]
    if len(labels) != len(set(labels)):
        raise ValueError(f"{source}: two scenarios share an Anomaly label")

    runs: dict[str, RunAnnotation] = {}
    for run_id, record in (raw.get("runs") or {}).items():
        scenario_key = str(record["scenario"])
        if scenario_key not in scenarios:
            raise ValueError(f"{source}: run {run_id!r} names unknown scenario {scenario_key!r}")
        sub_key = record.get("sub_scenario")
        if sub_key is not None:
            scenarios[scenario_key].sub_scenario(str(sub_key))  # raises if undeclared
        runs[run_id] = RunAnnotation(
            run_id=run_id,
            scenario_key=scenario_key,
            usable=bool(record.get("usable", True)),
            events=_parse_events(record.get("events")),
            sub_scenario_key=None if sub_key is None else str(sub_key),
            reason=(str(record["reason"]).strip() if record.get("reason") else None),
            note=(str(record["note"]).strip() if record.get("note") else None),
        )

    # Cross-check: every run a sub-scenario claims must actually be annotated with it.
    for spec in scenarios.values():
        for sub in spec.sub_scenarios:
            for run_id in sub.runs:
                annotation = runs.get(run_id)
                if annotation is None or annotation.sub_scenario_key != sub.key:
                    raise ValueError(
                        f"{source}: sub-scenario {spec.key}/{sub.key} lists run {run_id!r}, "
                        "but that run is not annotated with it"
                    )

    return FaultAnnotations(scenarios=scenarios, runs=runs)
