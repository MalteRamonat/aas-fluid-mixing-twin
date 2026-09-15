"""The plant's component inventory and flow graph.

Backed by ``resources/topology.yaml``, which was reconstructed from three sources that
cross-check each other (the rasterised P&ID, the Modelica ``connect(...)`` graph, and the
recorded data) — see ``docs/plant-topology.md``. Loaded once, read everywhere a builder
needs to know what exists and what is connected to what.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from aas_fluid_twin import config

__all__ = [
    "Component",
    "ComponentKind",
    "Connection",
    "Quantity",
    "Section",
    "Topology",
    "load_topology",
]


class ComponentKind(enum.StrEnum):
    TANK = "tank"
    PUMP = "pump"
    MIXER = "mixer"
    VALVE = "valve"
    CONTROLLER = "controller"


@dataclass(frozen=True, slots=True)
class Quantity:
    value: float
    unit: str


@dataclass(frozen=True, slots=True)
class Component:
    tag: str
    kind: ComponentKind
    shell: bool
    display_name: str
    instruments: tuple[str, ...] = ()
    note: str | None = None
    function: str | None = None
    actuation: str | None = None
    valve_type: str | None = None
    quantities: Mapping[str, Quantity] = field(default_factory=dict)
    flow_characteristic: tuple[tuple[float, float], ...] = ()
    """(V_flow [m³/s], head [m]) points of a pump's quadratic characteristic."""

    def quantity(self, key: str) -> Quantity | None:
        return self.quantities.get(key)


@dataclass(frozen=True, slots=True)
class Section:
    id: str
    display_name: str
    members: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Connection:
    source: str
    target: str
    via: str | None
    pipe: str | None


@dataclass(frozen=True, slots=True)
class Topology:
    sections: tuple[Section, ...]
    components: Mapping[str, Component]
    boundaries: Mapping[str, Mapping[str, Any]]
    junctions: tuple[str, ...]
    connections: tuple[Connection, ...]
    valve_tank_roles: Mapping[str, Mapping[str, str]]

    def component(self, tag: str) -> Component:
        try:
            return self.components[tag]
        except KeyError:
            raise KeyError(f"no component {tag!r} in the topology") from None

    @property
    def shell_components(self) -> tuple[Component, ...]:
        return tuple(c for c in self.components.values() if c.shell)

    def of_kind(self, kind: ComponentKind) -> tuple[Component, ...]:
        return tuple(c for c in self.components.values() if c.kind is kind)

    def connections_via(self, tag: str) -> tuple[Connection, ...]:
        return tuple(c for c in self.connections if c.via == tag)


_QUANTITY_KEYS = (
    "cross_section",
    "height",
    "nominal_volume",
    "port_diameter",
    "nominal_speed",
    "displaced_volume",
    "nominal_pressure_drop",
    "nominal_mass_flow",
)


def _quantity(raw: Any) -> Quantity | None:
    if not isinstance(raw, dict) or "value" not in raw:
        return None
    return Quantity(value=float(raw["value"]), unit=str(raw["unit"]))


def _component(tag: str, raw: dict[str, Any]) -> Component:
    quantities: dict[str, Quantity] = {}
    for key in _QUANTITY_KEYS:
        q = _quantity(raw.get(key))
        if q is not None:
            quantities[key] = q
    characteristic = tuple(
        (float(p["v_flow"]), float(p["head"])) for p in raw.get("flow_characteristic") or ()
    )
    return Component(
        tag=tag,
        kind=ComponentKind(str(raw["kind"])),
        shell=bool(raw.get("shell", False)),
        display_name=str(raw.get("display_name", tag)),
        instruments=tuple(str(i) for i in raw.get("instruments") or ()),
        note=(str(raw["note"]).strip() if raw.get("note") else None),
        function=(str(raw["function"]).strip() if raw.get("function") else None),
        actuation=raw.get("actuation"),
        valve_type=raw.get("valve_type"),
        quantities=quantities,
        flow_characteristic=characteristic,
    )


@cache
def load_topology(path: Path | None = None) -> Topology:
    source = path or (config.RESOURCE_DIR / "topology.yaml")
    raw: dict[str, Any] = yaml.safe_load(source.read_text(encoding="utf-8"))

    components = {tag: _component(tag, rec) for tag, rec in raw["components"].items()}
    sections = tuple(
        Section(
            id=str(s["id"]),
            display_name=str(s["display_name"]),
            members=tuple(str(m) for m in s["members"]),
        )
        for s in raw["sections"]
    )
    for section in sections:
        unknown = [m for m in section.members if m not in components]
        if unknown:
            raise ValueError(f"section {section.id} lists unknown components {unknown}")

    connections = tuple(
        Connection(
            source=str(c["from"]),
            target=str(c["to"]),
            via=(str(c["via"]) if c.get("via") else None),
            pipe=(str(c["pipe"]) if c.get("pipe") else None),
        )
        for c in raw.get("connections") or ()
    )
    return Topology(
        sections=sections,
        components=components,
        boundaries=dict(raw.get("boundaries") or {}),
        junctions=tuple(str(j) for j in raw.get("junctions") or ()),
        connections=connections,
        valve_tank_roles=dict(raw.get("valve_tank_roles") or {}),
    )
