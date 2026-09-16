"""The signal dictionary is the single source of truth every other module joins against.

The rule these tests exist to defend: **the CSV column name is a machine key and is never
altered**, including the upstream typo. Corrections are allowed only where declared.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from aas_fluid_twin.benchmark import (
    ChannelGroup,
    Quality,
    Role,
    SignalDictionary,
    SignalKind,
    load_signal_dictionary,
)
from aas_fluid_twin.benchmark.signals import CORRECTIONS

pytestmark = pytest.mark.benchmark_data

EXPECTED_SIGNAL_COUNT = 47

#: (channel, sensor_id, unit, sim_variable) for a representative signal of each family.
SPOT_CHECKS: tuple[tuple[str, str, str | None, str | None], ...] = (
    ("Tank_B201_empty", "LA-201", None, "LA_201.showActive"),
    ("Tank_B201_Volume", "VolumeB201", "ml", "tank_B201.V"),
    ("Pressure_below_B204", "PI254", "kPa", "PI254.p"),
    ("Tempreature_before_Pump_P201", "TI261", "°C", "TI261.T"),
    ("Temperature_in_B204", "TI262", "°C", "TI262.T"),
    ("Flow_after_Pump_P201", "FI271", "l/min", "FI271.V_flow"),
    ("Valve_V209_opening", "V209", None, "V209.opening"),
    ("Pump_P201_active", "P201", None, "P201_Characteristic.u"),
    ("Mixer_R201_of_B204_active", "R201", None, None),
    ("Tank_B203_level_calculated_via_LI213", "LI213", "mm", "LI213.y"),
    ("Tank_B204_level_calculated_via_PI254", "Level_B204_via_PI254", "cm", None),
)


def test_dictionary_has_every_signal(signals: SignalDictionary) -> None:
    assert len(signals) == EXPECTED_SIGNAL_COUNT
    assert len(set(signals.channels)) == EXPECTED_SIGNAL_COUNT


@pytest.mark.parametrize(("channel", "sensor_id", "unit", "sim_variable"), SPOT_CHECKS)
def test_signal_fields(
    signals: SignalDictionary,
    channel: str,
    sensor_id: str,
    unit: str | None,
    sim_variable: str | None,
) -> None:
    signal = signals.by_channel(channel)
    assert signal.sensor_id == sensor_id
    assert signal.unit == unit
    assert signal.sim_variable == sim_variable


def test_the_upstream_typo_survives_as_the_machine_key(signals: SignalDictionary) -> None:
    signal = signals.by_channel("Tempreature_before_Pump_P201")
    assert signal.channel == "Tempreature_before_Pump_P201"  # never corrected
    assert signal.display_name == "Temperature before pump P201"  # corrected for humans


def test_declared_corrections_are_applied_and_nothing_else(signals: SignalDictionary) -> None:
    assert len(CORRECTIONS) == 5
    assert sorted(signals.corrections_applied, key=lambda c: c.key) == sorted(
        CORRECTIONS, key=lambda c: c.key
    )

    # Mapping table row 39 repeats the B203 sensor id while describing B204.
    assert signals.by_channel("Tank_B204_level_calculated_via_VolumeB204").sensor_id == "Level_B204"
    assert signals.by_channel("Tank_B203_level_calculated_via_VolumeB203").sensor_id == "Level_B203"

    # The ultrasonic level is in millimetres (deviation D10, confirmed by the plant author);
    # the volume-derived level keeps the table's centimetres.
    for tank in (1, 2, 3, 4):
        assert signals.by_channel(f"Tank_B20{tank}_level_calculated_via_LI21{tank}").unit == "mm"
        assert (
            signals.by_channel(f"Tank_B20{tank}_level_calculated_via_VolumeB20{tank}").unit == "cm"
        )


def test_opcua_node_ids_identify_the_controller(signals: SignalDictionary) -> None:
    prefix = "ns=4;s=|var|WAGO 750-8212 PFC200 G2 2ETH RS.Application."
    assert all(s.opcua_node_id.startswith(prefix) for s in signals)


def test_roles_and_kinds(signals: SignalDictionary) -> None:
    actuators = signals.with_role(Role.ACTUATOR)
    assert {s.sensor_id for s in actuators} == {
        "V201",
        "V202",
        "V203",
        "V204",
        "V205",
        "V206",
        "V209",
        "P201",
        "P202",
        "R201",
    }
    assert all(s.kind is SignalKind.BINARY for s in actuators)

    analogue = [s for s in signals if s.kind is SignalKind.ANALOGUE]
    assert all(s.unit is not None for s in analogue)
    binary = [s for s in signals if s.is_binary]
    assert all(s.unit is None for s in binary)


def test_channel_groups_partition_the_dictionary(signals: SignalDictionary) -> None:
    counts = {group: len(signals.in_group(group)) for group in ChannelGroup}
    assert counts == {
        ChannelGroup.LEVEL_SWITCH: 9,
        ChannelGroup.VOLUME: 4,
        ChannelGroup.PRESSURE: 4,
        ChannelGroup.TEMPERATURE: 2,
        ChannelGroup.FLOW: 2,
        ChannelGroup.VALVE: 7,
        ChannelGroup.DRIVE: 3,
        ChannelGroup.LEVEL_ULTRASONIC: 4,
        ChannelGroup.LEVEL_FROM_VOLUME: 4,
        ChannelGroup.LEVEL_FROM_PRESSURE: 4,
        ChannelGroup.LEVEL_FROM_PRESSURE_REL: 4,
    }
    assert sum(counts.values()) == EXPECTED_SIGNAL_COUNT


def test_pressure_derived_channels_are_marked_unreliable(signals: SignalDictionary) -> None:
    """Static pressure only — wrong whenever fluid moves. Kept, but never unqualified."""
    for group in (
        ChannelGroup.PRESSURE,
        ChannelGroup.LEVEL_FROM_PRESSURE,
        ChannelGroup.LEVEL_FROM_PRESSURE_REL,
    ):
        for signal in signals.in_group(group):
            assert signal.quality is Quality.UNRELIABLE, signal.channel
            assert signal.quality_reason


def test_ultrasonic_derived_channels_are_good(signals: SignalDictionary) -> None:
    """Tank volumes come from the ultrasonic sensors, not from pressure."""
    for group in (
        ChannelGroup.VOLUME,
        ChannelGroup.LEVEL_ULTRASONIC,
        ChannelGroup.LEVEL_FROM_VOLUME,
    ):
        for signal in signals.in_group(group):
            assert signal.quality is Quality.GOOD, signal.channel


def test_instrument_spans_come_from_the_datasheets(signals: SignalDictionary) -> None:
    pressure = signals.by_sensor_id("PI251")
    assert pressure.measuring_span == {"min": 0.0, "max": 1.0, "unit": "bar"}
    assert pressure.instrument is not None
    assert pressure.instrument["manufacturer"] == "BD Sensors GmbH"

    flow = signals.by_sensor_id("FI271")
    assert flow.measuring_span == {"min": 0.1, "max": 25.0, "unit": "L/min"}

    level = signals.by_sensor_id("LI211")
    assert level.instrument is not None
    assert level.instrument["blind_zone"] == {"min": 0.0, "max": 70.0, "unit": "mm"}


def test_channels_not_represented_in_the_simulation(signals: SignalDictionary) -> None:
    unmapped = {s.channel for s in signals if not s.is_mapped_to_simulation}
    expected = {"Mixer_R201_of_B204_active"} | {
        s.channel
        for s in signals
        if s.group in (ChannelGroup.LEVEL_FROM_PRESSURE, ChannelGroup.LEVEL_FROM_PRESSURE_REL)
    }
    assert unmapped == expected


def test_asset_tags_resolve(signals: SignalDictionary) -> None:
    assert signals.by_channel("Tank_B204_Volume").asset_tag == "B204"
    assert signals.by_channel("Valve_V205_opening").asset_tag == "V205"
    assert signals.by_channel("Flow_after_Pump_P202").asset_tag == "P202"
    assert {s.asset_tag for s in signals.for_asset("B201")} == {"B201"}


def test_missing_mapping_file_says_what_to_do(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="fetch_benchmark"):
        load_signal_dictionary(tmp_path / "nope.xlsx")
