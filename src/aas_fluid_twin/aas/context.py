"""Everything a builder needs, loaded once.

The builders are pure functions of this context: same inputs, same submodels. That is what
makes the round-trip and conformance tests meaningful, and it is what lets the same
environment be built for a local run, for the Docker network, or for an AASX package.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from aas_fluid_twin import config
from aas_fluid_twin.aas import ids
from aas_fluid_twin.benchmark.annotations import FaultAnnotations, load_fault_annotations
from aas_fluid_twin.benchmark.datasets import DatasetIndex, build_dataset_index
from aas_fluid_twin.benchmark.modelica import ModelicaModel, load_modelica_model
from aas_fluid_twin.benchmark.signals import SignalDictionary, load_signal_dictionary
from aas_fluid_twin.benchmark.topology import Topology, load_topology

__all__ = ["BuildContext", "Endpoints", "load_context"]


@dataclass(frozen=True, slots=True)
class Endpoints:
    """External services the environment refers to. Vary by deployment, not by plant."""

    timeseries_api: str = ids.DEFAULT_TIMESERIES_ENDPOINT
    sim_runner: str = ids.DEFAULT_SIM_RUNNER_ENDPOINT
    opcua_server: str = ids.OPCUA_ENDPOINT_PLACEHOLDER
    opcua_live: bool = False


@dataclass(frozen=True, slots=True)
class BuildContext:
    signals: SignalDictionary
    index: DatasetIndex
    annotations: FaultAnnotations
    topology: Topology
    modelica: ModelicaModel
    instruments: Mapping[str, Any]
    """Raw ``resources/instruments.yaml`` (families and controller)."""
    endpoints: Endpoints = field(default_factory=Endpoints)
    benchmark_dir: Path = config.BENCHMARK_DIR
    include_data_files: bool = True
    """Whether the AASX package embeds the dataset CSVs and documents as supplementary files."""

    def instrument_family(self, family: str) -> Mapping[str, Any]:
        return dict(self.instruments["families"][family])

    def instrument_for(self, sensor_id: str) -> Mapping[str, Any] | None:
        for record in self.instruments["families"].values():
            if sensor_id in record.get("applies_to", ()):
                return dict(record)
        return None

    @property
    def controller(self) -> Mapping[str, Any]:
        return dict(self.instruments["controller"])


def load_context(
    *,
    endpoints: Endpoints | None = None,
    include_data_files: bool = True,
    benchmark_dir: Path | None = None,
) -> BuildContext:
    """Load every input the builders need from the benchmark and the packaged resources."""
    annotations = load_fault_annotations()
    instruments: dict[str, Any] = yaml.safe_load(
        (config.RESOURCE_DIR / "instruments.yaml").read_text(encoding="utf-8")
    )
    root = benchmark_dir or config.BENCHMARK_DIR
    mapping = root / "simulation" / "simulation_scripts" / "Simulation_Variable_Mapping.xlsx"
    datasets = root / "data" / "ModVA_Datasets"
    modelica = root / "simulation" / "ModVA_online_stable.mo"
    return BuildContext(
        signals=load_signal_dictionary(mapping),
        index=build_dataset_index(datasets, annotations=annotations),
        annotations=annotations,
        topology=load_topology(),
        modelica=load_modelica_model(modelica),
        instruments=instruments,
        endpoints=endpoints or Endpoints(),
        benchmark_dir=root,
        include_data_files=include_data_files,
    )
