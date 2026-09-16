"""Actuator schedules for the open-loop model.

``ModVA_online_stable`` is driven entirely by a ``CombiTimeTable`` with a fixed 30×10 layout
whose column order is ``[time, V201, V202, V203, V206, V205, V204, V209, P201, P202]``. That
order is the source of deviation D1 upstream: the benchmark's GUI writes a 9-column CSV
(``Time, V201 … V206, P201, P202``) into the table *positionally*, so V204/V206 swap, P201
lands on V209, P202 lands on P201, and P202 keeps whatever the embedded table had. Here a
schedule is keyed by actuator **name** and laid out into the table by name, so the CSV is
driven the way its header says.

A schedule may be any length. The fault-capable model reads its table from a file, so the row
count is data (deviation D9); only the fixed 30x10 literal — the upstream model and the FMU
built from it — still constrains it, and :meth:`ActuatorSchedule.as_fixed_table` is the one
place that limit is enforced. Short schedules are padded there with copies of the last row at
strictly increasing times, which leaves the trajectory unchanged under ``ConstantSegments``;
longer ones are refused rather than truncated (deviation D2 — upstream truncates silently).
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Final

__all__ = [
    "ACTUATORS",
    "TABLE_COLUMNS",
    "TABLE_ROWS",
    "ActuatorSchedule",
    "ScheduleRow",
    "legacy_upstream_table",
]

#: The actuators the model accepts, in the model's own table order (time excluded).
ACTUATORS: Final[tuple[str, ...]] = (
    "V201",
    "V202",
    "V203",
    "V206",
    "V205",
    "V204",
    "V209",
    "P201",
    "P202",
)
TABLE_COLUMNS: Final[tuple[str, ...]] = ("time", *ACTUATORS)
TABLE_ROWS: Final[int] = 30

#: Header of the benchmark's ``ActuatorControlMatrix_*.csv`` — note: no V209.
UPSTREAM_CSV_COLUMNS: Final[tuple[str, ...]] = (
    "Time",
    "V201",
    "V202",
    "V203",
    "V204",
    "V205",
    "V206",
    "P201",
    "P202",
)


@dataclass(frozen=True, slots=True)
class ScheduleRow:
    time: float
    values: Mapping[str, float]

    def value(self, actuator: str) -> float:
        return float(self.values.get(actuator, 0.0))


@dataclass(frozen=True, slots=True)
class ActuatorSchedule:
    name: str
    rows: tuple[ScheduleRow, ...]
    unspecified: tuple[str, ...] = ()
    """Actuators the source did not mention; they are driven with 0 (closed / off)."""

    def __post_init__(self) -> None:
        if not self.rows:
            raise ValueError(f"schedule {self.name!r} has no rows")
        times = [row.time for row in self.rows]
        if any(b <= a for a, b in pairwise(times)):
            raise ValueError(f"schedule {self.name!r}: times must be strictly increasing")
        unknown = {a for row in self.rows for a in row.values} - set(ACTUATORS)
        if unknown:
            raise ValueError(f"schedule {self.name!r}: unknown actuators {sorted(unknown)}")

    @property
    def end_time(self) -> float:
        return self.rows[-1].time

    def table(self) -> list[list[float]]:
        """The schedule in the model's column order, one row per switching time."""
        return [[row.time, *(row.value(a) for a in ACTUATORS)] for row in self.rows]

    def as_fixed_table(self) -> list[list[float]]:
        """The same schedule shaped for a model whose table is a fixed 30×10 literal.

        That is the upstream model and the FMU exported from it. The fault-capable model reads
        its table from a file and has no such limit, so this is where the limit lives.
        """
        if len(self.rows) > TABLE_ROWS:
            raise ValueError(
                f"schedule {self.name!r} has {len(self.rows)} rows; this model's table holds "
                f"{TABLE_ROWS}. Run it on ModVA_faultcapable, which reads its table from a "
                f"file, or coarsen the schedule."
            )
        out = self.table()
        last = out[-1]
        while len(out) < TABLE_ROWS:
            out.append([out[-1][0] + 1.0, *last[1:]])
        return out

    def start_values(self, block: str = "ActuatorControl") -> dict[str, float]:
        """``{"ActuatorControl.table[i,j]": value}`` — for a fixed-table model only."""
        return {
            f"{block}.table[{i},{j}]": value
            for i, row in enumerate(self.as_fixed_table(), start=1)
            for j, value in enumerate(row, start=1)
        }

    # --- constructors ----------------------------------------------------------------

    @classmethod
    def from_table(cls, name: str, table: Iterable[Sequence[float]]) -> ActuatorSchedule:
        """From a matrix in the model's own column order (e.g. the embedded default)."""
        rows = []
        for raw in table:
            if len(raw) != len(TABLE_COLUMNS):
                raise ValueError(f"expected {len(TABLE_COLUMNS)} columns, got {len(raw)}")
            rows.append(ScheduleRow(float(raw[0]), dict(zip(ACTUATORS, raw[1:], strict=True))))
        return cls(name, tuple(_dedupe_trailing(rows)))

    @classmethod
    def from_csv(cls, path: Path, name: str | None = None) -> ActuatorSchedule:
        """From a ``Time,<actuator>,…`` CSV, columns matched **by name**."""
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            header = tuple(reader.fieldnames or ())
            if not header or header[0].lower() != "time":
                raise ValueError(f"{path.name}: first column must be Time, got {header[:1]}")
            unknown = [c for c in header[1:] if c not in ACTUATORS]
            if unknown:
                raise ValueError(f"{path.name}: unknown actuator columns {unknown}")
            rows = tuple(
                ScheduleRow(
                    float(record[header[0]]),
                    {c: float(record[c]) for c in header[1:]},
                )
                for record in reader
            )
        unspecified = tuple(a for a in ACTUATORS if a not in header)
        return cls(name or path.stem, rows, unspecified)

    @classmethod
    def from_recorded(
        cls,
        name: str,
        times: Sequence[float],
        columns: Mapping[str, Sequence[float | None]],
        actuator_of: Mapping[str, str],
        *,
        threshold: float = 0.5,
    ) -> tuple[ActuatorSchedule, list[str]]:
        """Reconstruct the schedule a recorded run was driven with.

        ``columns`` is the run as the store returns it and ``actuator_of`` maps each recorded
        channel onto a model actuator. Only switching points are kept — the recording samples
        every ~1.6 s, while the commands change a few dozen times in 600 s — and the states are
        quantised, because a valve command is open or shut and a fractional value in the file
        is a sampling artefact.

        Returns the schedule and the notes a caller should show with it: what was left out and
        what the model will ignore.
        """
        notes: list[str] = []
        usable = {channel: actuator_of[channel] for channel in columns if channel in actuator_of}
        missing = [a for a in ACTUATORS if a not in usable.values()]
        if missing:
            notes.append(
                f"not recorded in this run, so driven closed: {', '.join(sorted(missing))}"
            )
        ignored = [c for c in columns if c not in actuator_of]
        if ignored:
            notes.append(f"recorded but not an actuator of the model: {', '.join(sorted(ignored))}")

        rows: list[ScheduleRow] = []
        current: dict[str, float] = {}
        for index, time in enumerate(times):
            state = dict(current)
            for channel, actuator in usable.items():
                value = columns[channel][index]
                if value is not None:  # a gap keeps the last commanded state
                    state[actuator] = 1.0 if float(value) >= threshold else 0.0
            if not rows or state != current:
                rows.append(ScheduleRow(float(time), state))
                current = state
        if not rows:
            raise ValueError(f"{name}: the run has no actuator samples to read a schedule from")
        if rows[0].time > 0:
            rows.insert(0, ScheduleRow(0.0, dict(rows[0].values)))
        notes.append(f"{len(rows)} switching points read from {len(times)} samples")
        return cls(name, tuple(rows), tuple(missing)), notes

    @classmethod
    def from_json(cls, text: str, name: str = "inline") -> ActuatorSchedule:
        """From ``[{"time": 0, "V201": 1, …}, …]`` as passed through the AAS operation."""
        raw = json.loads(text)
        if not isinstance(raw, list):
            raise ValueError("inline schedule must be a JSON array of rows")
        rows = []
        seen: set[str] = set()
        for entry in raw:
            if not isinstance(entry, dict) or "time" not in entry:
                raise ValueError("each schedule row needs a 'time' key")
            values = {k: float(v) for k, v in entry.items() if k != "time"}
            seen.update(values)
            rows.append(ScheduleRow(float(entry["time"]), values))
        return cls(name, tuple(rows), tuple(a for a in ACTUATORS if a not in seen))

    def to_json(self) -> list[dict[str, float]]:
        return [{"time": row.time, **{a: row.value(a) for a in ACTUATORS}} for row in self.rows]


def _dedupe_trailing(rows: list[ScheduleRow]) -> list[ScheduleRow]:
    """Drop trailing rows that only repeat the previous time (padding in the source)."""
    out: list[ScheduleRow] = []
    for row in rows:
        if out and row.time <= out[-1].time:
            continue
        out.append(row)
    return out


def legacy_upstream_table(csv_path: Path, embedded: Sequence[Sequence[float]]) -> list[list[float]]:
    """Reproduce what the benchmark's GUI actually loaded into the model (D1 + D2).

    Column *k* of the CSV is written to table column *k* regardless of name, rows beyond 30 are
    cut, rows short of 30 are filled by repeating the last one (same time), and table column 10
    (P202) keeps the embedded default because the CSV has only nine columns. This is used only
    to reproduce the published simulation result, never to run a schedule.
    """
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        raw = [r for r in csv.reader(handle) if r][1:]
    rows = [[float(c) for c in r] for r in raw]
    rows = rows[:TABLE_ROWS]
    while len(rows) < TABLE_ROWS:
        rows.append(list(rows[-1]))
    table = [list(map(float, r)) for r in embedded]
    for i, row in enumerate(rows):
        for j, value in enumerate(row):
            table[i][j] = value
    return table
