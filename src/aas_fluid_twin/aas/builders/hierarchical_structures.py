"""Hierarchical Structures enabling Bills of Material — IDTA 02011-1-1.

The plant as a two-level bill of material: the entry node is the plant, its direct children
are the components (vessels, pumps, valves, stirrer, controller, external connections), and
each component's children are the instruments mounted on it. ``ArcheType = OneDown`` states
exactly that: the entry node knows its direct parts, and parts with their own shell are
self-managed entities carrying their asset id.

Nodes are flat under the entry node on purpose. Process sections (dosing, mixing, discharge)
are a *grouping*, not a part relationship, so they stay in the topology resource for the
dashboard rather than becoming BoM levels.

This module is also the one place that knows the reference path of every plant element, so
the fault catalogue and the handover documentation can point at BoM nodes without
duplicating the layout.
"""

from __future__ import annotations

import contextlib
from collections.abc import Sequence
from typing import Any

from basyx.aas import model

from aas_fluid_twin.aas import ids
from aas_fluid_twin.aas.builders._common import element_ref, entity, ext_ref, id_short_for, prop
from aas_fluid_twin.aas.context import BuildContext
from aas_fluid_twin.aas.templates import template
from aas_fluid_twin.benchmark.topology import Component, ComponentKind

__all__ = ["bom_reference", "build_hierarchical_structures", "instrument_parent"]

T = template("hierarchical_structures")
SUBMODEL_ID = ids.submodel_id(ids.PLANT_TAG, T.submodel_id_short)


def _sem(path: str) -> model.ExternalReference:
    return ext_ref(T.semantic(path))


def instrument_parent(ctx: BuildContext, sensor_id: str) -> str | None:
    """The component an instrument is mounted on, or ``None`` for one that is not mounted."""
    for component in ctx.topology.components.values():
        if sensor_id in component.instruments:
            return component.tag
    return None


def bom_reference(ctx: BuildContext, tag: str) -> model.ModelReference[model.SubmodelElement]:
    """Model reference to the BoM entity for a component tag or an instrument id."""
    if tag in ctx.topology.components or tag in ctx.topology.boundaries:
        path = [(model.Entity, "EntryNode"), (model.Entity, tag)]
    else:
        parent = instrument_parent(ctx, tag)
        if parent is None:
            raise KeyError(f"{tag!r} is neither a component nor a mounted instrument")
        path = [
            (model.Entity, "EntryNode"),
            (model.Entity, parent),
            (model.Entity, id_short_for(tag)),
        ]
    return element_ref(SUBMODEL_ID, path)


def _has_part(
    parent_path: Sequence[tuple[type[Any], str]], child: str
) -> model.RelationshipElement:
    return model.RelationshipElement(
        id_short=f"HasPart_{child}",
        first=element_ref(SUBMODEL_ID, parent_path),
        second=element_ref(SUBMODEL_ID, [*parent_path, (model.Entity, child)]),
        semantic_id=_sem("EntryNode/HasPart"),
    )


def _instrument_node(ctx: BuildContext, sensor_id: str) -> model.Entity:
    signal = None
    with contextlib.suppress(KeyError):
        signal = ctx.signals.by_sensor_id(sensor_id)
    description = f"{sensor_id}: {signal.display_name}" if signal else sensor_id
    if signal and signal.quality_reason:
        description += f" — quality {signal.quality.value}: {signal.quality_reason}"
    return entity(
        id_short_for(sensor_id),
        _sem("EntryNode/Node/Node"),
        description=description,
    )


def _component_node(ctx: BuildContext, component: Component) -> model.Entity:
    node_path = [(model.Entity, "EntryNode"), (model.Entity, component.tag)]
    statements: list[model.SubmodelElement | None] = []
    for sensor_id in component.instruments:
        statements.append(_instrument_node(ctx, sensor_id))
        statements.append(_has_part(node_path, id_short_for(sensor_id)))
    return entity(
        component.tag,
        _sem("EntryNode/Node"),
        *statements,
        global_asset_id=ids.component_asset_id(component.tag) if component.shell else None,
        description=component.note or component.display_name,
    )


def _boundary_node(tag: str, record: dict[str, object]) -> model.Entity:
    via = record.get("via")
    direction = record.get("direction")
    return entity(
        tag,
        _sem("EntryNode/Node"),
        description=f"{record.get('display_name', tag)} ({direction}, via {via}).",
    )


def build_hierarchical_structures(ctx: BuildContext) -> model.Submodel:
    entry_path = [(model.Entity, "EntryNode")]
    components = list(ctx.topology.components.values())
    boundaries = ctx.topology.boundaries

    statements: list[model.SubmodelElement | None] = []
    for component in components:
        statements.append(_component_node(ctx, component))
        statements.append(_has_part(entry_path, component.tag))
    for tag, record in boundaries.items():
        statements.append(_boundary_node(tag, dict(record)))
        statements.append(_has_part(entry_path, tag))

    entry = entity(
        "EntryNode",
        _sem("EntryNode"),
        *statements,
        global_asset_id=ids.PLANT_ASSET_ID,
        description=(
            "The ModVA fluid mixing plant. Direct parts are its components; each component's "
            "parts are the instruments mounted on it. Reconstructed from the P&ID, the Modelica "
            "connect() graph and the recorded data (docs/plant-topology.md)."
        ),
    )

    valve_kind = ComponentKind.VALVE
    controllable = [c.tag for c in components if c.shell and c.kind is valve_kind]
    return model.Submodel(
        id_=SUBMODEL_ID,
        id_short=T.submodel_id_short,
        semantic_id=ext_ref(T.submodel_semantic_id),
        administration=model.AdministrativeInformation(
            version="1", revision="0", template_id=T.template_id
        ),
        submodel_element=[
            entry,
            prop("ArcheType", "OneDown", _sem("ArcheType")),
        ],
        description=model.MultiLanguageTextType(
            {
                "en": f"{len(components)} components, {len(boundaries)} external connections; "
                f"actuated valves: {', '.join(controllable)}."
            }
        ),
    )
