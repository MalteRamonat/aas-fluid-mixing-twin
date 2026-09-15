"""The runner contract, shared by the FMU path and the OpenModelica path.

A runner takes a fully resolved :class:`SimulationRequest` — Modelica parameter names, a
schedule, the variables to record — and returns raw Modelica variables over time. Renaming to
plant channels happens afterwards (:mod:`aas_fluid_twin.simulation.mapping`), so the runners
know nothing about sensors.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final, Protocol

from aas_fluid_twin.simulation.schedule import ActuatorSchedule

__all__ = [
    "PARAMETER_TARGETS",
    "TESTED_SOLVER",
    "SimulationError",
    "SimulationRequest",
    "SimulationResult",
    "SimulationRunner",
    "resolve_parameters",
]


#: The solver that reproduces the benchmark's published simulation result. The model's own
#: annotation names ``cvode``, which fails at t ~ 0.26 s (deviation D6).
TESTED_SOLVER: Final[str] = "ida"


class SimulationError(RuntimeError):
    """The model could not be run as requested (unknown parameter, solver failure …)."""


#: ``SimulationControl/ParameterSet`` idShort -> Modelica parameter. Pump characteristic points
#: keep their names; the fault handles exist only in the fault-capable model version.
PARAMETER_TARGETS: Final[Mapping[str, str]] = {
    "tank_B201_level_start": "tank_B201.level_start",
    "tank_B202_level_start": "tank_B202.level_start",
    "tank_B203_level_start": "tank_B203.level_start",
    "tank_B204_level_start": "tank_B204.level_start",
    "V212_opening": "V212_opening",
    "V211_opening": "V211_opening",
    "V211_return_to_B201": "V211_return_to_B201",
    "V210_opening": "V210_opening",
}


@dataclass(frozen=True, slots=True)
class SimulationRequest:
    schedule: ActuatorSchedule
    outputs: tuple[str, ...]
    """Modelica variables to record."""
    start_time: float = 0.0
    stop_time: float = 600.0
    output_interval: float = 1.0
    tolerance: float = 1e-5
    solver: str = TESTED_SOLVER
    parameters: Mapping[str, float] = field(default_factory=dict)
    """Modelica parameter name -> value, already resolved."""

    def __post_init__(self) -> None:
        if self.stop_time <= self.start_time:
            raise ValueError("stop_time must exceed start_time")
        if self.output_interval <= 0:
            raise ValueError("output_interval must be positive")

    def start_values(self) -> dict[str, float]:
        return {**self.schedule.start_values(), **self.parameters}


@dataclass(frozen=True, slots=True)
class SimulationResult:
    time_s: list[float]
    variables: dict[str, list[float]]
    runner: str
    model: str
    wall_time_s: float

    def __len__(self) -> int:
        return len(self.time_s)


class SimulationRunner(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def variable_names(self) -> frozenset[str]:
        """Every variable the model exposes (used to filter outputs and validate parameters)."""
        ...

    def parameter_names(self) -> frozenset[str]:
        """The settable parameters of the model."""
        ...

    def run(self, request: SimulationRequest) -> SimulationResult: ...


def resolve_parameters(
    overrides: Mapping[str, float | bool], settable: frozenset[str]
) -> dict[str, float]:
    """Map ``ParameterSet`` idShorts (or raw Modelica names) onto the model's parameters.

    Raises :class:`SimulationError` for anything the loaded model cannot set — which is how a
    fault handle on the upstream model version fails: loudly, not silently ignored.
    """
    resolved: dict[str, float] = {}
    for key, value in overrides.items():
        target = PARAMETER_TARGETS.get(key, key)
        if target not in settable:
            raise SimulationError(
                f"parameter {key!r} (-> {target!r}) is not settable in this model version"
            )
        resolved[target] = float(value)
    return resolved
