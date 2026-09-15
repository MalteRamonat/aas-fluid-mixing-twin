"""Typed access to the fluid mixing benchmark: signals, runs, annotations, samples."""

from aas_fluid_twin.benchmark.annotations import (
    FaultAnnotations,
    FaultEvent,
    OnsetSource,
    load_fault_annotations,
)
from aas_fluid_twin.benchmark.datasets import (
    DatasetIndex,
    RunMetadata,
    Scenario,
    SchemaVariant,
    build_dataset_index,
)
from aas_fluid_twin.benchmark.loader import RunSeries, Sample, iter_samples, load_series
from aas_fluid_twin.benchmark.signals import (
    ChannelGroup,
    DeviceType,
    Quality,
    Role,
    Signal,
    SignalDictionary,
    SignalKind,
    load_signal_dictionary,
)

__all__ = [
    "ChannelGroup",
    "DatasetIndex",
    "DeviceType",
    "FaultAnnotations",
    "FaultEvent",
    "OnsetSource",
    "Quality",
    "Role",
    "RunMetadata",
    "RunSeries",
    "Sample",
    "Scenario",
    "SchemaVariant",
    "Signal",
    "SignalDictionary",
    "SignalKind",
    "build_dataset_index",
    "iter_samples",
    "load_fault_annotations",
    "load_series",
    "load_signal_dictionary",
]
