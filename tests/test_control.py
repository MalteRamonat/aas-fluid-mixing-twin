"""Two-point control rules: what they mean, what they refuse, and what the model gets.

A rule is written in the plant's units and executed in the model's, so the conversion is the
part most worth pinning — a threshold of "2000 ml" that reached the model as 2000 m³ would
simply never fire, and the run would look plausible while ignoring the rule entirely.
"""

from __future__ import annotations

import json

import pytest

from aas_fluid_twin.simulation.control import (
    CONTROL_SIGNALS,
    UNBOUNDED,
    ControlRule,
    control_parameters,
    signal_index,
)
from aas_fluid_twin.simulation.schedule import ACTUATORS


def test_the_signal_bus_is_stable_and_addressable() -> None:
    """Rules store an index, so the order is an interface, not an implementation detail."""
    keys = [signal.key for signal in CONTROL_SIGNALS]
    assert len(keys) == len(set(keys))
    assert signal_index("Tank_B201_Volume") == 1  # first, and it must stay first
    assert [signal_index(key) for key in keys] == list(range(1, len(keys) + 1))
    for signal in CONTROL_SIGNALS:
        assert signal.variable  # every entry names a Modelica variable to read


def test_a_rule_reads_as_the_sentence_it_was_written_as() -> None:
    rule = ControlRule("V204", "Tank_B201_Volume", on_below=500, off_above=2000)
    assert (
        rule.describe() == "open V204 when Tank B201 volume is below 500 ml, close it above 2000 ml"
    )
    # Inverted: the actions swap, the thresholds keep their meaning. This is "drain B201":
    # V201 stays open while the tank still holds something.
    assert (
        ControlRule("V201", "Tank_B201_Volume", on_below=1, off_above=5, invert=True).describe()
        == "close V201 when Tank B201 volume is below 1 ml, open it above 5 ml"
    )
    assert (
        ControlRule("P201", "Tank_B204_Volume", off_above=4000, invert=True).describe()
        == "open P201 when Tank B204 volume is above 4000 ml"
    )


def test_thresholds_are_converted_into_the_models_units() -> None:
    """ml -> m³ for a volume, cm -> m for a level, kPa gauge -> Pa absolute for a pressure."""
    volume = ControlRule("V204", "Tank_B201_Volume", on_below=500, off_above=2000)
    assert volume.thresholds_in_si() == pytest.approx((5e-4, 2e-3))

    level = ControlRule("V205", "Tank_B202_level", on_below=5, off_above=15)
    assert level.thresholds_in_si() == pytest.approx((0.05, 0.15))

    pressure = ControlRule("V209", "Pressure_below_B204", off_above=3)
    low, high = pressure.thresholds_in_si()
    assert low == -UNBOUNDED
    assert high == pytest.approx(103_000.0)  # 3 kPa gauge on a 100 kPa ambient


def test_equal_thresholds_are_refused_because_they_chatter() -> None:
    """A comparator toggles at every solver step once the level settles on its threshold."""
    with pytest.raises(ValueError, match="band"):
        ControlRule("V201", "Tank_B201_Volume", on_below=100, off_above=100, invert=True)
    ControlRule("V201", "Tank_B201_Volume", on_below=100, off_above=105, invert=True)


def test_an_open_ended_rule_keeps_the_other_side_open() -> None:
    """The open side is the largest finite double, not inf: it must survive JSON and equal the
    model's own ``Modelica.Constants.inf`` default so the initial state is computed right."""
    low, high = ControlRule("V204", "Tank_B201_Volume", on_below=500).thresholds_in_si()
    assert low == pytest.approx(5e-4) and high == UNBOUNDED
    low, high = ControlRule("V204", "Tank_B201_Volume", off_above=2000).thresholds_in_si()
    assert low == -UNBOUNDED and high == pytest.approx(2e-3)
    assert UNBOUNDED == 1.7976931348623157e308
    json.dumps(control_parameters([ControlRule("V204", "Tank_B201_Volume", on_below=500)]))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"actuator": "V299", "signal": "Tank_B201_Volume", "on_below": 1}, "unknown actuator"),
        ({"actuator": "V204", "signal": "Nope", "on_below": 1}, "unknown control signal"),
        ({"actuator": "V204", "signal": "Tank_B201_Volume"}, "at least one threshold"),
        (
            {"actuator": "V204", "signal": "Tank_B201_Volume", "on_below": 2000, "off_above": 500},
            "band",
        ),
    ],
)
def test_a_rule_that_cannot_work_is_refused_when_it_is_written(
    kwargs: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        ControlRule(**kwargs)  # type: ignore[arg-type]


def test_rules_become_the_parameters_the_model_declares() -> None:
    parameters = control_parameters(
        [ControlRule("V204", "Tank_B201_Volume", on_below=500, off_above=2000)]
    )
    position = ACTUATORS.index("V204") + 1
    assert parameters[f"ctrl_mode[{position}]"] == 1
    assert parameters[f"ctrl_source[{position}]"] == signal_index("Tank_B201_Volume")
    assert parameters[f"ctrl_on_below[{position}]"] == pytest.approx(5e-4)
    assert parameters[f"ctrl_off_above[{position}]"] == pytest.approx(2e-3)
    assert parameters[f"ctrl_invert[{position}]"] == 0
    # Everything else keeps the model's default, which is to follow the schedule.
    assert not any(
        key.startswith("ctrl_mode[") and key != f"ctrl_mode[{position}]" for key in parameters
    )


def test_two_rules_for_one_actuator_are_a_contradiction() -> None:
    with pytest.raises(ValueError, match="One actuator has one control law"):
        control_parameters(
            [
                ControlRule("V204", "Tank_B201_Volume", on_below=500),
                ControlRule("V204", "Tank_B202_Volume", on_below=500),
            ]
        )


def test_no_rules_means_no_parameters() -> None:
    assert control_parameters([]) == {}
