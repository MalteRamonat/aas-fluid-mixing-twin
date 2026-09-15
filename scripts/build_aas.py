#!/usr/bin/env python
"""Build the AAS environment and write it to ``out/`` as JSON, XML and AASX.

Usage::

    python scripts/build_aas.py                 # JSON + XML + AASX with attachments
    python scripts/build_aas.py --no-attachments
    python scripts/build_aas.py --timeseries-endpoint http://api:8000/api/timeseries
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aas_fluid_twin import config
from aas_fluid_twin.aas import Endpoints, build_environment, load_context
from aas_fluid_twin.aas import io as aas_io


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=config.OUT_DIR, help="output directory")
    parser.add_argument(
        "--no-aasx",
        action="store_true",
        help="write JSON and XML only (the AASX embeds ~35 MB of attachments)",
    )
    parser.add_argument("--timeseries-endpoint", default=Endpoints().timeseries_api)
    parser.add_argument("--sim-runner-endpoint", default=Endpoints().sim_runner)
    args = parser.parse_args()

    started = time.perf_counter()
    ctx = load_context(
        endpoints=Endpoints(
            timeseries_api=args.timeseries_endpoint, sim_runner=args.sim_runner_endpoint
        ),
    )
    env = build_environment(ctx)
    print(
        f"built {len(env.shells)} shells, {len(env.submodels)} submodels, "
        f"{sum(1 for _ in env.concept_descriptions())} concept descriptions "
        f"in {time.perf_counter() - started:.1f} s"
    )

    out: Path = args.out
    written = [
        ("json", aas_io.write_json(env, out / "modva-environment.json")),
        ("xml", aas_io.write_xml(env, out / "modva-environment.xml")),
    ]
    if not args.no_aasx:
        written.append(("aasx", aas_io.write_aasx(env, out / "modva.aasx")))
    for label, path in written:
        print(f"  {label:5s} {path.stat().st_size / 1e6:7.2f} MB  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
