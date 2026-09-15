"""Shared fixtures.

Tests come in two flavours:

* Hermetic tests run anywhere. They use the version-controlled inputs that are *ours*
  (``data/fault_annotations.yaml``, the packaged YAML resources) and synthetic CSVs.
* Tests marked ``benchmark_data`` need the upstream benchmark, which is not vendored.
  They skip with a clear message when ``data/benchmark`` has not been populated.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from pathlib import Path

import pytest

from aas_fluid_twin import config
from aas_fluid_twin.aas.environment import BuiltEnvironment
from aas_fluid_twin.benchmark import (
    DatasetIndex,
    FaultAnnotations,
    SignalDictionary,
    build_dataset_index,
    load_fault_annotations,
    load_signal_dictionary,
)

_FETCH_HINT = "benchmark data not present — run `python scripts/fetch_benchmark.py`"


@pytest.fixture(scope="session")
def fault_annotations() -> FaultAnnotations:
    return load_fault_annotations()


@pytest.fixture(scope="session")
def signals() -> SignalDictionary:
    if not config.VARIABLE_MAPPING_FILE.is_file():
        pytest.skip(_FETCH_HINT)
    return load_signal_dictionary()


@pytest.fixture(scope="session")
def index(fault_annotations: FaultAnnotations) -> DatasetIndex:
    if not config.DATASET_DIR.is_dir():
        pytest.skip(_FETCH_HINT)
    return build_dataset_index(annotations=fault_annotations)


@pytest.fixture(scope="session")
def env() -> BuiltEnvironment:
    """The full AAS environment, built once per session. Needs the benchmark data."""
    if not config.VARIABLE_MAPPING_FILE.is_file() or not config.DATASET_DIR.is_dir():
        pytest.skip(_FETCH_HINT)
    from aas_fluid_twin.aas import build_environment, load_context

    return build_environment(load_context())


def write_csv(
    path: Path,
    channels: Sequence[str],
    rows: Sequence[Sequence[object]],
    *,
    start: str = "2024-01-13 00:43:31.525643",
) -> Path:
    """Write a synthetic run in the benchmark's exact CSV shape."""
    header = ["Server Time", "Session Time Stamps", *channels]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for offset, row in enumerate(rows):
            seconds = f"{float(offset) * 1.6:.6f}"
            stamp = start if offset == 0 else start[:17] + f"{31.525643 + offset * 1.6:09.6f}"
            writer.writerow([stamp, seconds, *row])
    return path


@pytest.fixture
def synthetic_dataset_dir(tmp_path: Path) -> Path:
    """Two tiny runs: one normal, one leakage with a reduced schema."""
    channels = ["Tank_B201_Volume", "Valve_V201_opening", "Anomaly"]
    write_csv(
        tmp_path / "dataset_0_normal_behaviour.csv",
        channels,
        [[1591.7, 1, 0], [1460.4, 1, 0], [1332.8, 0, 0]],
    )
    write_csv(
        tmp_path / "dataset_10_leakage.csv",
        [*channels[:-1], "Pressure_below_B201", "Anomaly"],
        [[2061.1, 0, 3.02, 1], [2061.0, 1, 2.11, 1], [2000.0, 1, 2.05, 1]],
    )
    return tmp_path
