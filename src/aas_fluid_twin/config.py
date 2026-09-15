"""Filesystem layout and benchmark source locations.

Paths are resolved relative to the repository root so scripts work from any cwd.
Every location can be overridden with an environment variable, which is what the
Docker services use.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

_THIS = Path(__file__).resolve()
PACKAGE_ROOT: Final[Path] = _THIS.parent
REPO_ROOT: Final[Path] = _THIS.parents[2]


def _path_from_env(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw).expanduser().resolve() if raw else default


#: Benchmark working copy. Git-ignored; populated by ``scripts/fetch_benchmark.py``.
BENCHMARK_DIR: Final[Path] = _path_from_env("AAS_BENCHMARK_DIR", REPO_ROOT / "data" / "benchmark")

#: Curated, version-controlled inputs that are *ours*, not the benchmark's.
DATA_DIR: Final[Path] = _path_from_env("AAS_DATA_DIR", REPO_ROOT / "data")
FAULT_ANNOTATIONS_FILE: Final[Path] = DATA_DIR / "fault_annotations.yaml"

#: Generated output (AASX/JSON environments, reports). Git-ignored.
OUT_DIR: Final[Path] = _path_from_env("AAS_OUT_DIR", REPO_ROOT / "out")

#: Built simulation artefacts (the exported FMU).
ARTIFACT_DIR: Final[Path] = _path_from_env("AAS_ARTIFACT_DIR", REPO_ROOT / "artifacts")

#: Packaged YAML resources.
RESOURCE_DIR: Final[Path] = PACKAGE_ROOT / "resources"

#: The fault-capable model version, derived from the upstream model by
#: ``scripts/derive_faultcapable.py`` (deviation D8). Shipped with the package because the
#: AAS build attaches it and the simulation worker compiles it.
FAULTCAPABLE_MODEL_FILE: Final[Path] = RESOURCE_DIR / "modelica" / "ModVA_faultcapable.mo"

# --- locations inside the benchmark working copy -----------------------------

#: The authoritative signal dictionary of the plant.
VARIABLE_MAPPING_FILE: Final[Path] = (
    BENCHMARK_DIR / "simulation" / "simulation_scripts" / "Simulation_Variable_Mapping.xlsx"
)
#: The 55 recorded runs.
DATASET_DIR: Final[Path] = BENCHMARK_DIR / "data" / "ModVA_Datasets"
#: The Modelica model.
MODELICA_FILE: Final[Path] = BENCHMARK_DIR / "simulation" / "ModVA_online_stable.mo"
#: Documents referenced by the Handover Documentation submodel.
DOCUMENT_DIR: Final[Path] = BENCHMARK_DIR / "documents"

#: Upstream repository, pinned to a branch rather than a tag because none is published.
BENCHMARK_REPO: Final[str] = "MalteRamonat/fluid-mixing-anomaly-benchmark"
BENCHMARK_REF: Final[str] = os.environ.get("AAS_BENCHMARK_REF", "main")
BENCHMARK_RAW_BASE: Final[str] = (
    f"https://raw.githubusercontent.com/{BENCHMARK_REPO}/{BENCHMARK_REF}/"
)
BENCHMARK_DOI: Final[str] = "10.1109/ACCESS.2025.3592815"
