#!/usr/bin/env python
"""Load the 55 recorded runs into TimescaleDB and check they arrived intact.

Usage::

    python scripts/ingest_timeseries.py            # apply schema, ingest every run, verify
    python scripts/ingest_timeseries.py --verify   # only read back and compare with the CSVs
    python scripts/ingest_timeseries.py --runs dataset_10_leakage dataset_0_normal_behaviour

The DSN comes from ``AAS_TIMESERIES_DSN`` (default: the compose ``timescaledb`` service on
localhost:5432). Exit status is non-zero when any run differs from its CSV.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aas_fluid_twin.benchmark.annotations import load_fault_annotations
from aas_fluid_twin.benchmark.datasets import build_dataset_index
from aas_fluid_twin.store import DEFAULT_DSN, TimescaleStore, ingest_run, verify_run


def wait_until_up(store: TimescaleStore, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if store.is_up():
            return
        time.sleep(2.0)
    raise SystemExit(f"TimescaleDB at {store.dsn} did not answer within {seconds:.0f} s")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", default=DEFAULT_DSN)
    parser.add_argument("--verify", action="store_true", help="only read back and compare")
    parser.add_argument("--runs", nargs="*", help="run ids to restrict to (default: all)")
    parser.add_argument("--wait", type=float, default=120.0, help="seconds to wait for the DB")
    args = parser.parse_args()

    # The annotations are what turn the file-level label into the point-in-time label and
    # the fault windows; an index built without them would store constant labels.
    index = build_dataset_index(annotations=load_fault_annotations())
    if not any(run.events for run in index):
        raise SystemExit("no fault events resolved — annotations missing?")
    runs = list(index) if not args.runs else [index.by_id(r) for r in args.runs]

    store = TimescaleStore(args.dsn)
    wait_until_up(store, args.wait)
    print(f"TimescaleDB at {store.dsn} is up")

    if not args.verify:
        store.apply_schema()
        total = 0
        for run in runs:
            report = ingest_run(store, run)
            total += report.rows_written
            print(
                f"  {report.run_id:<40} {report.record_count:>4} records x "
                f"{report.channel_count:>2} channels = {report.rows_written:>6} rows"
            )
        print(f"ingested {len(runs)} runs, {total} sample rows")

    print("verifying …")
    problems: list[str] = []
    for run in runs:
        problems.extend(verify_run(store, run))
    for problem in problems[:20]:
        print(f"  ✗ {problem}")
    if len(problems) > 20:
        print(f"  … and {len(problems) - 20} more")
    print(
        f"{len(runs)} runs match their CSVs" if not problems else "MISMATCH — see above",
    )
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
