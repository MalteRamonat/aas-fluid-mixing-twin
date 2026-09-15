"""Units of the Modelica variables, and conversion to the plant's engineering units.

The benchmark's mapping table declares a simulation unit per variable, and for two families
it is wrong (deviation D5): ``Modelica.Fluid.Sensors.Pressure`` outputs pascal, not bar, and
``Modelica.Fluid.Sensors.Temperature`` outputs kelvin, not degrees Celsius. The units here are
derived from the Modelica *variable* — which sensor block it comes from — and a test pins
them, so the mapping table's column is never used for conversion.

Pressure needs two corrections, not one: the model's sensors read absolute pressure while the
plant's transmitters read gauge pressure, so the model's ambient reference is subtracted.
"""

from __future__ import annotations

import enum
from collections.abc import Callable
from typing import Final

__all__ = [
    "AMBIENT_PRESSURE_PA",
    "SimUnit",
    "sensor_to_sim",
    "sim_to_sensor",
    "sim_unit_of",
]

#: ``p_a_start = 100000`` on both pumps and the fixed boundary in ``ModVA_online_stable.mo``.
AMBIENT_PRESSURE_PA: Final[float] = 100_000.0

KELVIN_OFFSET: Final[float] = 273.15


class SimUnit(enum.StrEnum):
    CUBIC_METRE = "m3"
    PASCAL = "Pa"
    KELVIN = "K"
    CUBIC_METRE_PER_SECOND = "m3/s"
    METRE = "m"
    DIMENSIONLESS = "1"


#: Modelica variable suffix -> unit. Ordered: the first matching suffix wins.
_SUFFIX_UNITS: tuple[tuple[str, SimUnit], ...] = (
    (".V_flow", SimUnit.CUBIC_METRE_PER_SECOND),
    (".V", SimUnit.CUBIC_METRE),
    (".p", SimUnit.PASCAL),
    (".T", SimUnit.KELVIN),
    (".level", SimUnit.METRE),
    (".y", SimUnit.METRE),  # LI21x.y are RealExpression blocks on tank level
    (".opening", SimUnit.DIMENSIONLESS),
    (".u", SimUnit.DIMENSIONLESS),
    (".showActive", SimUnit.DIMENSIONLESS),
)


def sim_unit_of(sim_variable: str) -> SimUnit:
    """Unit of a Modelica variable, from the sensor block that produces it."""
    for suffix, unit in _SUFFIX_UNITS:
        if sim_variable.endswith(suffix):
            return unit
    raise KeyError(f"no unit rule for Modelica variable {sim_variable!r}")


#: (sensor unit, simulation unit) -> sensor value -> simulation value.
_TO_SIM: dict[tuple[str, SimUnit], Callable[[float], float]] = {
    ("ml", SimUnit.CUBIC_METRE): lambda v: v * 1e-6,
    ("kPa", SimUnit.PASCAL): lambda v: v * 1000.0 + AMBIENT_PRESSURE_PA,
    ("°C", SimUnit.KELVIN): lambda v: v + KELVIN_OFFSET,
    ("l/min", SimUnit.CUBIC_METRE_PER_SECOND): lambda v: v / 60_000.0,
    ("cm", SimUnit.METRE): lambda v: v / 100.0,
}

_TO_SENSOR: dict[tuple[str, SimUnit], Callable[[float], float]] = {
    ("ml", SimUnit.CUBIC_METRE): lambda v: v * 1e6,
    ("kPa", SimUnit.PASCAL): lambda v: (v - AMBIENT_PRESSURE_PA) / 1000.0,
    ("°C", SimUnit.KELVIN): lambda v: v - KELVIN_OFFSET,
    ("l/min", SimUnit.CUBIC_METRE_PER_SECOND): lambda v: v * 60_000.0,
    ("cm", SimUnit.METRE): lambda v: v * 100.0,
}


def sensor_to_sim(value: float, sensor_unit: str | None, sim_unit: SimUnit) -> float:
    if sensor_unit is None or sim_unit is SimUnit.DIMENSIONLESS:
        return value
    return _TO_SIM[(sensor_unit, sim_unit)](value)


def sim_to_sensor(value: float, sensor_unit: str | None, sim_unit: SimUnit) -> float:
    if sensor_unit is None or sim_unit is SimUnit.DIMENSIONLESS:
        return value
    return _TO_SENSOR[(sensor_unit, sim_unit)](value)
