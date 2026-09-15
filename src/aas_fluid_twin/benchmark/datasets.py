"""Index of the 55 recorded runs.

Each CSV in ``data/ModVA_Datasets`` is one ~600 s run of the plant. This module discovers
them, reads just enough of each to describe it, and joins that with the fault annotations.

Two facts about the corpus shape this code:

* **Sampling is not uniform.** Δt averages ~1.6 s but varies within every run, so
  :attr:`RunMetadata.sampling_interval_s` is a mean and is reported as such. No nominal
  sampling rate is invented.
* **``dataset_0`` has a reduced schema.** It predates the eight pressure-derived level
  channels, so it carries 40 signal columns where every other run carries 48. It is kept
  (those channels were never used — the pressure sensors are unreliable) but flagged, so it
  is never silently mixed into an analysis that assumes the full schema.
"""

from __future__ import annotations

import csv
import enum
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from aas_fluid_twin import config
from aas_fluid_twin.benchmark.annotations import FaultAnnotations, FaultEvent

__all__ = [
    "ANOMALY_COLUMN",
    "RELATIVE_TIME_COLUMN",
    "SERVER_TIME_COLUMN",
    "DatasetIndex",
    "RunMetadata",
    "Scenario",
    "SchemaVariant",
    "build_dataset_index",
]

SERVER_TIME_COLUMN = "Server Time"
RELATIVE_TIME_COLUMN = "Session Time Stamps"
ANOMALY_COLUMN = "Anomaly"

_TIME_COLUMNS = (SERVER_TIME_COLUMN, RELATIVE_TIME_COLUMN)
_FILENAME_RE = re.compile(r"^dataset_(?P<number>\d+)_(?P<scenario>[a-z_]+)$")


class Scenario(enum.StrEnum):
    """Scenario names as they appear in the filenames and in ``fault_annotations.yaml``."""

    NORMAL_BEHAVIOUR = "normal_behaviour"
    LEAKAGE = "leakage"
    CLOGGING = "clogging"
    LEAKAGE_AND_CLOGGING = "leakage_and_clogging"
    CHANGED_INITIAL_STATE = "changed_initial_state"
    RECONFIGURATION = "reconfiguration"
    SENSOR_ERRORS = "sensor_errors"
    STIRRING_ERROR = "stirring_error"
    MANUAL_MODE = "manual_mode"


#: ``Anomaly`` column value for each scenario, derived by scanning all 55 files.
SCENARIO_LABELS: dict[Scenario, int] = {
    Scenario.NORMAL_BEHAVIOUR: 0,
    Scenario.LEAKAGE: 1,
    Scenario.CLOGGING: 2,
    Scenario.LEAKAGE_AND_CLOGGING: 3,
    Scenario.CHANGED_INITIAL_STATE: 4,
    Scenario.RECONFIGURATION: 5,
    Scenario.SENSOR_ERRORS: 6,
    Scenario.STIRRING_ERROR: 7,
    Scenario.MANUAL_MODE: 8,
}


class SchemaVariant(enum.StrEnum):
    FULL = "full"
    REDUCED = "reduced"


def _parse_server_time(value: str) -> datetime:
    return datetime.fromisoformat(value.strip())


@dataclass(frozen=True, slots=True)
class RunMetadata:
    """Everything about a run that can be known without loading its samples."""

    run_id: str
    number: int
    scenario: Scenario
    label: int
    path: Path
    channels: tuple[str, ...]
    record_count: int
    started_at: datetime
    ended_at: datetime
    first_relative_s: float
    last_relative_s: float
    schema_variant: SchemaVariant
    missing_channels: tuple[str, ...]
    usable: bool = True
    unusable_reason: str | None = None
    sub_scenario_key: str | None = None
    events: tuple[FaultEvent, ...] = ()
    note: str | None = None

    @property
    def duration_s(self) -> float:
        return self.last_relative_s - self.first_relative_s

    @property
    def sampling_interval_s(self) -> float:
        """Mean Δt. Sampling is *not* uniform — see the module docstring."""
        if self.record_count < 2:
            return 0.0
        return self.duration_s / (self.record_count - 1)

    @property
    def is_normal(self) -> bool:
        return self.scenario is Scenario.NORMAL_BEHAVIOUR

    @property
    def use_for_anomaly_detection(self) -> bool:
        return self.usable and self.scenario not in (
            Scenario.MANUAL_MODE,
            Scenario.CHANGED_INITIAL_STATE,
        )

    def label_at(self, t_relative_s: float) -> int:
        """Point-in-time label.

        The CSV's own ``Anomaly`` column is constant for the whole run. With the operator's
        onset times this can be resolved per sample, which is what a detector actually needs.
        A run whose events are unknown falls back to the file-level label.
        """
        if self.label == 0 or not self.events:
            return self.label
        return self.label if any(e.covers(t_relative_s) for e in self.events) else 0


@dataclass(frozen=True, slots=True)
class DatasetIndex(Sequence[RunMetadata]):
    runs: tuple[RunMetadata, ...]

    def __len__(self) -> int:
        return len(self.runs)

    def __getitem__(self, index: int) -> RunMetadata:  # type: ignore[override]
        return self.runs[index]

    def __iter__(self) -> Iterator[RunMetadata]:
        return iter(self.runs)

    def by_id(self, run_id: str) -> RunMetadata:
        for run in self.runs:
            if run.run_id == run_id:
                return run
        raise KeyError(f"no run {run_id!r}")

    def with_scenario(self, scenario: Scenario) -> tuple[RunMetadata, ...]:
        return tuple(r for r in self.runs if r.scenario is scenario)

    @property
    def normal(self) -> tuple[RunMetadata, ...]:
        return tuple(r for r in self.runs if r.is_normal)

    @property
    def faulty(self) -> tuple[RunMetadata, ...]:
        return tuple(r for r in self.runs if not r.is_normal)

    @property
    def full_schema_channels(self) -> tuple[str, ...]:
        """Signal columns common to the majority of runs, i.e. the 48-column schema."""
        for run in self.runs:
            if run.schema_variant is SchemaVariant.FULL:
                return run.channels
        raise ValueError("no full-schema run in the index")


def _scan(path: Path) -> tuple[tuple[str, ...], int, str, str, float, float]:
    """One pass over a CSV: header, row count, and the first and last time values."""
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = tuple(next(reader))
        if header[: len(_TIME_COLUMNS)] != _TIME_COLUMNS:
            raise ValueError(f"{path.name}: unexpected leading columns {header[:2]}")

        first_row = next(reader, None)
        if first_row is None:
            raise ValueError(f"{path.name}: no data rows")

        count = 1
        last_row = first_row
        for row in reader:
            if not row:
                continue
            last_row = row
            count += 1

    return (
        header[len(_TIME_COLUMNS) :],
        count,
        first_row[0],
        last_row[0],
        float(first_row[1]),
        float(last_row[1]),
    )


def build_dataset_index(
    dataset_dir: Path | None = None,
    annotations: FaultAnnotations | None = None,
) -> DatasetIndex:
    """Discover and describe every recorded run, joined with the fault annotations."""
    directory = dataset_dir or config.DATASET_DIR
    if not directory.is_dir():
        raise FileNotFoundError(
            f"dataset directory not found at {directory}. "
            "Run `python scripts/fetch_benchmark.py` first."
        )

    paths = sorted(directory.glob("dataset_*.csv"))
    if not paths:
        raise FileNotFoundError(f"no dataset_*.csv files in {directory}")

    scanned: list[tuple[Path, int, Scenario, tuple[str, ...], int, str, str, float, float]] = []
    for path in paths:
        match = _FILENAME_RE.match(path.stem)
        if match is None:
            raise ValueError(f"unexpected dataset filename: {path.name}")
        channels, count, first_ts, last_ts, first_rel, last_rel = _scan(path)
        scenario = Scenario(match["scenario"])
        scanned.append(
            (
                path,
                int(match["number"]),
                scenario,
                channels,
                count,
                first_ts,
                last_ts,
                first_rel,
                last_rel,
            )
        )

    # The full schema is whichever channel set the majority of runs share. Ties break
    # towards the wider set, so a two-file corpus still treats the richer one as complete.
    tallies: dict[tuple[str, ...], int] = {}
    for entry in scanned:
        tallies[entry[3]] = tallies.get(entry[3], 0) + 1
    full_schema = max(tallies, key=lambda key: (tallies[key], len(key)))

    runs: list[RunMetadata] = []
    for path, number, scenario, channels, count, first_ts, last_ts, first_rel, last_rel in sorted(
        scanned, key=lambda e: e[1]
    ):
        run_id = path.stem
        annotation = annotations.for_run(run_id) if annotations else None
        missing = tuple(c for c in full_schema if c not in channels)

        if annotation is not None and annotation.scenario_key != scenario.value:
            raise ValueError(
                f"{run_id}: filename says scenario {scenario.value!r} but the annotations "
                f"say {annotation.scenario_key!r}"
            )

        runs.append(
            RunMetadata(
                run_id=run_id,
                number=number,
                scenario=scenario,
                label=SCENARIO_LABELS[scenario],
                path=path,
                channels=channels,
                record_count=count,
                started_at=_parse_server_time(first_ts),
                ended_at=_parse_server_time(last_ts),
                first_relative_s=first_rel,
                last_relative_s=last_rel,
                schema_variant=(
                    SchemaVariant.FULL if channels == full_schema else SchemaVariant.REDUCED
                ),
                missing_channels=missing,
                usable=annotation.usable if annotation else True,
                unusable_reason=annotation.reason if annotation else None,
                sub_scenario_key=annotation.sub_scenario_key if annotation else None,
                events=annotation.events if annotation else (),
                note=annotation.note if annotation else None,
            )
        )

    return DatasetIndex(runs=tuple(runs))
