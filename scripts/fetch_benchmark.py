#!/usr/bin/env python
"""Fetch the benchmark files this project needs into ``data/benchmark``.

The benchmark is not vendored into this repository — see ``docs/benchmark-deviations.md``
entry C1. This script pulls only what is actually used: the signal mapping table, the 55
recorded runs, the Modelica model, and the documents referenced by the Handover
Documentation submodel. The anomaly-detection framework and the pre-scaled dataset copies
are deliberately not fetched.

Usage::

    python scripts/fetch_benchmark.py            # fetch what is missing
    python scripts/fetch_benchmark.py --force    # re-download everything
    python scripts/fetch_benchmark.py --list     # show what would be fetched
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aas_fluid_twin import config

TREE_API = (
    f"https://api.github.com/repos/{config.BENCHMARK_REPO}/git/trees/{config.BENCHMARK_REF}"
    "?recursive=1"
)

#: Path prefixes we need. Everything else in the upstream repo is out of scope.
WANTED_PREFIXES: tuple[str, ...] = (
    "data/ModVA_Datasets/dataset_",
    "documents/",
    "simulation/ModVA_online_stable.mo",
    "simulation/simulation_scripts/Simulation_Variable_Mapping.xlsx",
    "simulation/simulation_datasets_clearnames/",
    # The raw omc result behind the published clear-name file: same run, with the time column
    # the clear-name file lacks. The simulation integration test reproduces it.
    "simulation/simulation_datasets/ModVA_online_stable_res_20241206_102432.csv",
    "Simulation_Model_Control/",
)

#: Excluded even though they sit under a wanted prefix.
SKIP_PREFIXES: tuple[str, ...] = (
    "data/ModVA_Datasets/scaled_",
    "data/Plots/",
)


def list_remote_files() -> list[tuple[str, int]]:
    request = urllib.request.Request(TREE_API, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        tree = json.load(response)
    if tree.get("truncated"):
        raise RuntimeError("GitHub truncated the tree listing; fetch by subdirectory instead")

    out: list[tuple[str, int]] = []
    for entry in tree["tree"]:
        if entry["type"] != "blob":
            continue
        path = entry["path"]
        if not path.startswith(WANTED_PREFIXES) or path.startswith(SKIP_PREFIXES):
            continue
        out.append((path, int(entry.get("size", 0))))
    return sorted(out)


def download(path: str, destination: Path, *, force: bool) -> tuple[str, str]:
    target = destination / path
    if target.exists() and not force:
        return path, "cached"
    target.parent.mkdir(parents=True, exist_ok=True)
    url = config.BENCHMARK_RAW_BASE + urllib.parse.quote(path)
    temporary = target.with_suffix(target.suffix + ".part")
    try:
        urllib.request.urlretrieve(url, temporary)
        temporary.replace(target)
    except urllib.error.HTTPError as error:
        temporary.unlink(missing_ok=True)
        return path, f"FAILED {error.code}"
    return path, "fetched"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-download files already present")
    parser.add_argument("--list", action="store_true", help="only print what would be fetched")
    parser.add_argument("--jobs", type=int, default=8, help="parallel downloads (default 8)")
    args = parser.parse_args()

    print(f"Benchmark: {config.BENCHMARK_REPO}@{config.BENCHMARK_REF}")
    files = list_remote_files()
    total_mb = sum(size for _, size in files) / 1e6
    print(f"{len(files)} files, {total_mb:.1f} MB  ->  {config.BENCHMARK_DIR}")

    if args.list:
        for path, size in files:
            print(f"  {size / 1e3:9.1f} kB  {path}")
        return 0

    config.BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    fetched = cached = failed = 0
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        futures = [
            pool.submit(download, path, config.BENCHMARK_DIR, force=args.force) for path, _ in files
        ]
        for future in concurrent.futures.as_completed(futures):
            path, status = future.result()
            if status == "fetched":
                fetched += 1
            elif status == "cached":
                cached += 1
            else:
                failed += 1
                print(f"  {status}: {path}", file=sys.stderr)

    print(f"fetched {fetched}, cached {cached}, failed {failed}")
    if failed:
        return 1

    missing = [
        p
        for p in (config.VARIABLE_MAPPING_FILE, config.MODELICA_FILE, config.DATASET_DIR)
        if not p.exists()
    ]
    if missing:
        print(f"expected paths still missing: {missing}", file=sys.stderr)
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
