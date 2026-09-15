"""From raw Modelica variables to the plant's channel names and engineering units.

This is the benchmark's ``Simulation_Utils.rename_and_convert_columns`` done right: the
variable-to-channel pairs come from the signal dictionary, the units come from the Modelica
variable itself (deviation D5), and the pressure conversion accounts for absolute vs gauge.
The result carries the same channel names and units as the recorded runs, which is what makes
a measured run and a simulated run directly comparable.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from aas_fluid_twin.benchmark.signals import Signal, SignalDictionary
from aas_fluid_twin.simulation.units import sim_to_sensor, sim_unit_of

__all__ = ["ChannelMapping", "MappedResult", "build_channel_mapping"]


@dataclass(frozen=True, slots=True)
class ChannelMapping:
    """Which Modelica variables to record and how each becomes a channel."""

    pairs: tuple[tuple[str, Signal], ...]
    """``(modelica_variable, signal)`` for every signal the model can produce."""
    unmapped: tuple[str, ...]
    """Channels the plant records but the model does not produce (e.g. binary level switches)."""

    @property
    def variables(self) -> tuple[str, ...]:
        return tuple(v for v, _ in self.pairs)

    @property
    def channels(self) -> tuple[str, ...]:
        return tuple(s.channel for _, s in self.pairs)

    def convert(self, raw: Mapping[str, Sequence[float]]) -> dict[str, list[float]]:
        """Rename and convert a raw result (``variable -> samples``) to channels."""
        out: dict[str, list[float]] = {}
        for variable, signal in self.pairs:
            if variable not in raw:
                continue
            unit = sim_unit_of(variable)
            out[signal.channel] = [
                sim_to_sensor(float(v), signal.unit, unit) for v in raw[variable]
            ]
        return out


@dataclass(frozen=True, slots=True)
class MappedResult:
    time_s: list[float]
    channels: dict[str, list[float]]

    def __len__(self) -> int:
        return len(self.time_s)


def build_channel_mapping(
    signals: SignalDictionary, available: Sequence[str] | None = None
) -> ChannelMapping:
    """Pair every mapped signal with its Modelica variable.

    ``available`` (the model's variable names) drops signals whose block is not in the
    compiled model — the binary ``LA_*`` level switches, whose StateGraph is commented out.
    """
    pairs: list[tuple[str, Signal]] = []
    unmapped: list[str] = []
    known = None if available is None else set(available)
    for signal in signals:
        variable = signal.sim_variable
        if variable is None or (known is not None and variable not in known):
            unmapped.append(signal.channel)
            continue
        sim_unit_of(variable)  # raises early for a variable without a unit rule
        pairs.append((variable, signal))
    return ChannelMapping(tuple(pairs), tuple(unmapped))
