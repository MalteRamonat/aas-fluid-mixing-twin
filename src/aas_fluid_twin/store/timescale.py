"""TimescaleDB implementation of the time-series store.

One connection per call — the workloads are a handful of queries per dashboard interaction and
a one-off bulk ingest, neither of which justifies a pool. Writes are transactional per run: a
run is either completely present or absent, and writing it again replaces it.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from importlib import resources
from typing import Any, Final

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from aas_fluid_twin.store.models import (
    FaultWindow,
    Origin,
    RunRecord,
    SampleRow,
    SeriesResult,
)

__all__ = ["DEFAULT_DSN", "TimescaleStore"]

#: Matches the ``timescaledb`` service in docker-compose.yml. Override with ``AAS_TIMESERIES_DSN``.
DEFAULT_DSN: Final[str] = os.environ.get(
    "AAS_TIMESERIES_DSN", "postgresql://modva:modva@localhost:5432/modva"
)

_RUN_COLUMNS: Final[tuple[str, ...]] = (
    "run_id",
    "origin",
    "scenario",
    "anomaly_label",
    "started_at",
    "ended_at",
    "duration_s",
    "record_count",
    "schema_variant",
    "source_file",
    "usable",
    "note",
    "fault_windows",
    "params",
)


def _run_from_row(row: tuple[Any, ...]) -> RunRecord:
    values = dict(zip(_RUN_COLUMNS, row, strict=True))
    return RunRecord(
        run_id=values["run_id"],
        origin=Origin(values["origin"]),
        scenario=values["scenario"],
        anomaly_label=int(values["anomaly_label"]),
        started_at=values["started_at"],
        ended_at=values["ended_at"],
        duration_s=float(values["duration_s"]),
        record_count=int(values["record_count"]),
        schema_variant=values["schema_variant"],
        source_file=values["source_file"],
        usable=bool(values["usable"]),
        note=values["note"],
        fault_windows=tuple(FaultWindow.from_json(w) for w in values["fault_windows"]),
        params=values["params"],
    )


class TimescaleStore:
    """See :class:`aas_fluid_twin.store.models.TimeSeriesStore` for the read contract."""

    def __init__(self, dsn: str = DEFAULT_DSN) -> None:
        self.dsn = dsn

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection[tuple[Any, ...]]]:
        with psycopg.connect(self.dsn) as connection:
            yield connection

    # --- lifecycle ---------------------------------------------------------------

    def is_up(self) -> bool:
        try:
            with self.connect() as connection:
                connection.execute("SELECT 1")
        except psycopg.OperationalError:
            return False
        return True

    def apply_schema(self) -> None:
        """Create the tables and the hypertable. Safe to run repeatedly."""
        ddl = resources.files("aas_fluid_twin.store").joinpath("schema.sql").read_text("utf-8")
        with self.connect() as connection:
            connection.execute(ddl.encode("utf-8"))  # bytes: the DDL is not a literal string

    # --- writes ------------------------------------------------------------------

    def write_run(
        self,
        record: RunRecord,
        samples: Iterable[SampleRow],
        labels: Iterable[tuple[float, int]],
    ) -> int:
        """Insert a run with its samples, replacing any run of the same id. Returns rows written."""
        written = 0
        with self.connect() as connection, connection.transaction():
            connection.execute("DELETE FROM run WHERE run_id = %s", (record.run_id,))
            connection.execute(
                sql.SQL("INSERT INTO run ({}) VALUES ({})").format(
                    sql.SQL(", ").join(map(sql.Identifier, _RUN_COLUMNS)),
                    sql.SQL(", ").join(sql.Placeholder() for _ in _RUN_COLUMNS),
                ),
                (
                    record.run_id,
                    str(record.origin),
                    record.scenario,
                    record.anomaly_label,
                    record.started_at,
                    record.ended_at,
                    record.duration_s,
                    record.record_count,
                    record.schema_variant,
                    record.source_file,
                    record.usable,
                    record.note,
                    Jsonb([w.to_json() for w in record.fault_windows]),
                    None if record.params is None else Jsonb(dict(record.params)),
                ),
            )
            with connection.cursor() as cursor:
                with cursor.copy(
                    "COPY sample (run_id, ts, t_rel_s, channel, value) FROM STDIN"
                ) as copy:
                    for row in samples:
                        copy.write_row((record.run_id, row.ts, row.t_rel_s, row.channel, row.value))
                        written += 1
                with cursor.copy("COPY sample_label (run_id, t_rel_s, label) FROM STDIN") as copy:
                    for t_rel_s, label in labels:
                        copy.write_row((record.run_id, t_rel_s, label))
        return written

    def delete_run(self, run_id: str) -> bool:
        with self.connect() as connection:
            result = connection.execute("DELETE FROM run WHERE run_id = %s", (run_id,))
            return result.rowcount > 0

    # --- reads -------------------------------------------------------------------

    def list_runs(self, origin: Origin | None = None) -> list[RunRecord]:
        query = sql.SQL("SELECT {} FROM run").format(
            sql.SQL(", ").join(map(sql.Identifier, _RUN_COLUMNS))
        )
        params: tuple[Any, ...] = ()
        if origin is not None:
            query += sql.SQL(" WHERE origin = %s")
            params = (str(origin),)
        query += sql.SQL(" ORDER BY origin, started_at, run_id")
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_run_from_row(row) for row in rows]

    def get_run(self, run_id: str) -> RunRecord | None:
        query = sql.SQL("SELECT {} FROM run WHERE run_id = %s").format(
            sql.SQL(", ").join(map(sql.Identifier, _RUN_COLUMNS))
        )
        with self.connect() as connection:
            row = connection.execute(query, (run_id,)).fetchone()
        return None if row is None else _run_from_row(row)

    def channels(self, run_id: str) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT channel FROM sample WHERE run_id = %s ORDER BY channel",
                (run_id,),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def sample_count(self, run_id: str) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT count(*) FROM sample WHERE run_id = %s", (run_id,)
            ).fetchone()
        return 0 if row is None else int(row[0])

    def query(
        self,
        run_id: str,
        channels: Sequence[str] | None = None,
        *,
        from_s: float | None = None,
        to_s: float | None = None,
    ) -> SeriesResult | None:
        """A run, or a time window of it, pivoted to column form.

        Every requested channel is present in the result even when the run does not carry it
        (all ``None``), so a caller comparing a reduced-schema run with a full one gets aligned
        columns rather than a KeyError.
        """
        record = self.get_run(run_id)
        if record is None:
            return None

        conditions = [sql.SQL("s.run_id = %s")]
        params: list[Any] = [run_id]
        if channels is not None:
            conditions.append(sql.SQL("s.channel = ANY(%s)"))
            params.append(list(channels))
        if from_s is not None:
            conditions.append(sql.SQL("s.t_rel_s >= %s"))
            params.append(from_s)
        if to_s is not None:
            conditions.append(sql.SQL("s.t_rel_s <= %s"))
            params.append(to_s)

        statement = sql.SQL(
            "SELECT s.t_rel_s, s.ts, s.channel, s.value, l.label "
            "FROM sample AS s "
            "LEFT JOIN sample_label AS l ON l.run_id = s.run_id AND l.t_rel_s = s.t_rel_s "
            "WHERE {} ORDER BY s.t_rel_s, s.channel"
        ).format(sql.SQL(" AND ").join(conditions))

        with self.connect() as connection:
            rows = connection.execute(statement, params).fetchall()

        t_rel: list[float] = []
        timestamps: list[datetime] = []
        labels: list[int] = []
        columns: dict[str, list[float | None]] = {c: [] for c in (channels or ())}
        index_of: dict[float, int] = {}
        for t_rel_s, ts, channel, value, label in rows:
            position = index_of.get(t_rel_s)
            if position is None:
                position = len(t_rel)
                index_of[t_rel_s] = position
                t_rel.append(float(t_rel_s))
                timestamps.append(ts)
                labels.append(0 if label is None else int(label))
                for column in columns.values():
                    column.append(None)
            if channel not in columns:
                columns[channel] = [None] * len(t_rel)
            columns[channel][position] = None if value is None else float(value)

        return SeriesResult(
            run_id=run_id,
            origin=record.origin,
            t_rel_s=t_rel,
            timestamps=timestamps,
            labels=labels,
            channels=columns,
        )

    def summary(self) -> dict[str, Any]:
        """Counts for health/status endpoints."""
        with self.connect() as connection:
            runs = connection.execute(
                "SELECT origin, count(*) FROM run GROUP BY origin ORDER BY origin"
            ).fetchall()
            samples = connection.execute("SELECT count(*) FROM sample").fetchone()
        return {
            "runs": {str(origin): int(count) for origin, count in runs},
            "samples": 0 if samples is None else int(samples[0]),
        }
