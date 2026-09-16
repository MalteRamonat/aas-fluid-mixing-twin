"""Two-point control rules for the simulated plant (design §12.4, deviation D9).

The plant's own PLC runs a step chain on level thresholds; what this offers is the piece of
that which can be expressed without generating and recompiling Modelica: per actuator, either
follow the schedule or switch on a measured signal with hysteresis.

    when Tank B201 volume falls below 4000 ml -> open V204, and close it again above 5000 ml

Everything is a *parameter* of the fault-capable model, so a new control law is a new run, not
a new build. The model carries a fixed bus of measured signals; a rule names one by index,
which is why :data:`CONTROL_SIGNALS` is the single place that order is defined — the Modelica
array in the derived model is generated from it.

Thresholds travel in the channel's own engineering unit (ml, cm, kPa, °C, l/min) and are
converted to the model's SI units here, so a dashboard can ask for "4000 ml" and a rule can be
read back in the same terms it was written in.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from aas_fluid_twin.simulation.schedule import ACTUATORS
from aas_fluid_twin.simulation.units import sensor_to_sim, sim_unit_of

__all__ = [
    "CONTROL_SIGNALS",
    "UNBOUNDED",
    "ControlRule",
    "ControlSignal",
    "control_parameters",
    "signal_index",
]


@dataclass(frozen=True, slots=True)
class ControlSignal:
    """One entry of the model's measured-signal bus."""

    key: str
    """Stable name a rule refers to; also the recorded channel it corresponds to."""
    variable: str
    """The Modelica variable read into the bus."""
    label: str
    unit: str | None
    """The engineering unit a threshold is given in — not the model's SI unit."""


#: The bus, in the order the derived model declares it. **Append only**: the index is what a
#: stored rule refers to, so reordering would silently repoint existing rules.
CONTROL_SIGNALS: Final[tuple[ControlSignal, ...]] = (
    ControlSignal("Tank_B201_Volume", "tank_B201.V", "Tank B201 volume", "ml"),
    ControlSignal("Tank_B202_Volume", "tank_B202.V", "Tank B202 volume", "ml"),
    ControlSignal("Tank_B203_Volume", "tank_B203.V", "Tank B203 volume", "ml"),
    ControlSignal("Tank_B204_Volume", "tank_B204.V", "Tank B204 volume", "ml"),
    ControlSignal("Tank_B201_level", "tank_B201.level", "Tank B201 level", "cm"),
    ControlSignal("Tank_B202_level", "tank_B202.level", "Tank B202 level", "cm"),
    ControlSignal("Tank_B203_level", "tank_B203.level", "Tank B203 level", "cm"),
    ControlSignal("Tank_B204_level", "tank_B204.level", "Tank B204 level", "cm"),
    ControlSignal("Flow_after_Pump_P201", "FI271.V_flow", "Flow after pump P201", "l/min"),
    ControlSignal("Flow_after_Pump_P202", "FI272.V_flow", "Flow after pump P202", "l/min"),
    ControlSignal("Pressure_below_B201", "PI251.p", "Pressure below B201", "kPa"),
    ControlSignal("Pressure_below_B202", "PI252.p", "Pressure below B202", "kPa"),
    ControlSignal("Pressure_below_B203", "PI253.p", "Pressure below B203", "kPa"),
    ControlSignal("Pressure_below_B204", "PI254.p", "Pressure below B204", "kPa"),
    ControlSignal("Temperature_manifold", "TI261.T", "Temperature at the manifold", "°C"),
    ControlSignal("Temperature_in_B204", "TI262.T", "Temperature in B204", "°C"),
)

_INDEX: Final[Mapping[str, int]] = {s.key: i + 1 for i, s in enumerate(CONTROL_SIGNALS)}

#: "No threshold on this side". The largest finite double rather than ``inf``: it is what
#: ``Modelica.Constants.inf`` is (``ModelicaServices.Machine.inf`` = 1.7976931348623157E+308),
#: so the model's ``ctrl_on_below[i] <= -Modelica.Constants.inf`` test recognises it — and it
#: survives JSON, which ``inf`` does not (the request to the worker would fail before it ran).
UNBOUNDED: Final[float] = sys.float_info.max


def signal_index(key: str) -> int:
    """1-based index into the model's bus, as Modelica counts."""
    if key not in _INDEX:
        raise ValueError(f"unknown control signal {key!r}; known: {sorted(_INDEX)}")
    return _INDEX[key]


@dataclass(frozen=True, slots=True)
class ControlRule:
    """Switch one actuator on a measured signal, with hysteresis.

    ``on_below`` and ``off_above`` are in the signal's engineering unit and must leave a band
    between them: with the two equal the actuator toggles at every solver step once the level
    settles on the threshold — eight such rules turned a 600 s run into one that hit the
    worker's 15-minute cap. A rule with only one of them latches: it switches once and never
    back, which is what a one-sided rule can only mean.
    """

    actuator: str
    signal: str
    on_below: float | None = None
    off_above: float | None = None
    invert: bool = False
    """Drive the actuator closed where it would open — for an interlock."""

    def __post_init__(self) -> None:
        if self.actuator not in ACTUATORS:
            raise ValueError(f"unknown actuator {self.actuator!r}; known: {list(ACTUATORS)}")
        signal_index(self.signal)
        if self.on_below is None and self.off_above is None:
            raise ValueError(
                f"rule for {self.actuator}: give at least one threshold "
                f"(on_below, off_above or both)"
            )
        if (
            self.on_below is not None
            and self.off_above is not None
            and self.off_above <= self.on_below
        ):
            raise ValueError(
                f"rule for {self.actuator}: off_above ({self.off_above}) must be above "
                f"on_below ({self.on_below}) — without a band between them the actuator "
                "switches at every solver step once the signal settles on the threshold"
            )

    @property
    def signal_unit(self) -> str | None:
        return CONTROL_SIGNALS[signal_index(self.signal) - 1].unit

    def thresholds_in_si(self) -> tuple[float, float]:
        """The band as the model reads it: ``(on_below, off_above)`` in the model's units."""
        entry = CONTROL_SIGNALS[signal_index(self.signal) - 1]
        unit = sim_unit_of(entry.variable)
        return (
            -UNBOUNDED if self.on_below is None else sensor_to_sim(self.on_below, entry.unit, unit),
            (
                UNBOUNDED
                if self.off_above is None
                else sensor_to_sim(self.off_above, entry.unit, unit)
            ),
        )

    def describe(self) -> str:
        """The rule as a sentence, in the direction it was written.

        ``invert`` swaps the actions, not the thresholds: "open V204 below 500 ml, close it
        above 2000 ml" becomes "close V201 below 1 ml, open it above 5 ml" — which is how
        "keep V201 open while B201 still holds something" is expressed.
        """
        entry = CONTROL_SIGNALS[signal_index(self.signal) - 1]
        unit = f" {entry.unit}" if entry.unit else ""
        on, off = ("close", "open") if self.invert else ("open", "close")
        parts = []
        if self.on_below is not None:
            parts.append(
                f"{on} {self.actuator} when {entry.label} is below {self.on_below:g}{unit}"
            )
        if self.off_above is not None:
            verb = f"{off} it" if parts else f"{off} {self.actuator} when {entry.label} is"
            parts.append(f"{verb} above {self.off_above:g}{unit}")
        return ", ".join(parts)


#: Values that mean "this actuator follows the schedule" — the model's defaults.
_FOLLOW_SCHEDULE = 0
_TWO_POINT = 1


def control_parameters(rules: Sequence[ControlRule]) -> dict[str, float]:
    """Turn rules into the model parameters that implement them.

    One rule per actuator: a second rule for the same actuator is a contradiction, not an
    addition, so it is refused rather than silently winning.
    """
    seen: dict[str, ControlRule] = {}
    for rule in rules:
        if rule.actuator in seen:
            raise ValueError(
                f"two rules for {rule.actuator}: {seen[rule.actuator].describe()!r} and "
                f"{rule.describe()!r}. One actuator has one control law."
            )
        seen[rule.actuator] = rule

    parameters: dict[str, float] = {}
    for position, actuator in enumerate(ACTUATORS, start=1):
        active = seen.get(actuator)
        if active is None:
            continue  # leave the model's default: follow the schedule
        low, high = active.thresholds_in_si()
        parameters[f"ctrl_mode[{position}]"] = _TWO_POINT
        parameters[f"ctrl_source[{position}]"] = signal_index(active.signal)
        parameters[f"ctrl_on_below[{position}]"] = low
        parameters[f"ctrl_off_above[{position}]"] = high
        parameters[f"ctrl_invert[{position}]"] = 1 if active.invert else 0
    return parameters
