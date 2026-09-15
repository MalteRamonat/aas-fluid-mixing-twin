"""Simulation units and conversions — the correction for deviation D5."""

from __future__ import annotations

import pytest

from aas_fluid_twin.simulation.units import (
    AMBIENT_PRESSURE_PA,
    SimUnit,
    sensor_to_sim,
    sim_to_sensor,
    sim_unit_of,
)


@pytest.mark.parametrize(
    ("variable", "unit"),
    [
        ("tank_B201.V", SimUnit.CUBIC_METRE),
        ("PI251.p", SimUnit.PASCAL),  # the mapping table says bar — D5
        ("TI261.T", SimUnit.KELVIN),  # the mapping table says °C — D5
        ("FI271.V_flow", SimUnit.CUBIC_METRE_PER_SECOND),
        ("LI211.y", SimUnit.METRE),
        ("tank_B204.level", SimUnit.METRE),
        ("V201.opening", SimUnit.DIMENSIONLESS),
        ("P201_Characteristic.u", SimUnit.DIMENSIONLESS),
        ("LA_201.showActive", SimUnit.DIMENSIONLESS),
    ],
)
def test_unit_is_derived_from_the_sensor_block(variable: str, unit: SimUnit) -> None:
    assert sim_unit_of(variable) is unit


def test_unknown_variable_is_an_error() -> None:
    with pytest.raises(KeyError):
        sim_unit_of("something.weird")


@pytest.mark.parametrize(
    ("sensor_unit", "sim_unit", "sensor_value", "sim_value"),
    [
        ("ml", SimUnit.CUBIC_METRE, 2061.07, 2.06107e-3),
        ("kPa", SimUnit.PASCAL, 3.0194, 3019.4 + AMBIENT_PRESSURE_PA),  # gauge -> absolute
        ("°C", SimUnit.KELVIN, 18.2365, 291.3865),
        ("l/min", SimUnit.CUBIC_METRE_PER_SECOND, 4.8229, 4.8229 / 60000),
        ("cm", SimUnit.METRE, 115.27, 1.1527),
    ],
)
def test_conversions_round_trip(
    sensor_unit: str, sim_unit: SimUnit, sensor_value: float, sim_value: float
) -> None:
    assert sensor_to_sim(sensor_value, sensor_unit, sim_unit) == pytest.approx(sim_value)
    assert sim_to_sensor(sim_value, sensor_unit, sim_unit) == pytest.approx(sensor_value)


def test_binary_channels_pass_through() -> None:
    assert sensor_to_sim(1.0, None, SimUnit.DIMENSIONLESS) == 1.0
    assert sim_to_sensor(0.0, None, SimUnit.DIMENSIONLESS) == 0.0


def test_the_published_clearnames_pressure_is_off_by_the_factor_d5_describes() -> None:
    """101 636 Pa absolute -> 1.6 kPa gauge, not the 10 163 621 the upstream file holds."""
    assert sim_to_sensor(101_636.2, "kPa", SimUnit.PASCAL) == pytest.approx(1.6362, abs=1e-3)
    assert pytest.approx(10_163_620) == 101_636.2 / 0.01  # what the upstream conversion did
