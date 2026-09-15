"""Generic Technical Data — IDTA 02003-2-0.

The template's ``TechnicalPropertyAreas`` are free-form by design; the areas here follow the
plant's structure (vessels, pumps, valves, piping, instruments, medium). Every numeric value
is read from the Modelica model or from ``resources/instruments.yaml`` (the datasheets) at
build time — nothing is transcribed by hand, so a change upstream changes the AAS.

Each technical property carries a project ConceptDescription with its unit, because a bare
``Property`` has no unit of its own and the template's ``ArbitraryProperty`` semanticId only
says "something goes here".
"""

from __future__ import annotations

from datetime import date

from basyx.aas import model
from basyx.aas.model import datatypes

from aas_fluid_twin.aas import ids
from aas_fluid_twin.aas.builders._common import ext_ref, mlp, prop, prop_typed, range_, smc, sml
from aas_fluid_twin.aas.builders.nameplate import OPERATOR
from aas_fluid_twin.aas.context import BuildContext
from aas_fluid_twin.aas.semantics import semantic
from aas_fluid_twin.aas.templates import template
from aas_fluid_twin.benchmark.topology import Component, ComponentKind

__all__ = ["build_component_technical_data", "build_plant_technical_data"]

T = template("technical_data")
_TD = "TechnicalData"


def _sem(path: str) -> model.ExternalReference:
    return ext_ref(T.semantic(path))


def _td(element: str) -> model.ExternalReference:
    return semantic(_TD, element)


_AREA = "TechnicalPropertyAreas/[]"


def _quantity(id_short: str, component: Component, key: str, concept: str) -> model.Property | None:
    q = component.quantity(key)
    if q is None:
        return None
    return prop(id_short, q.value, _td(concept), description=f"Unit: {q.unit}")


# --- areas ----------------------------------------------------------------------


def _vessel(component: Component, ctx: BuildContext) -> model.SubmodelElementCollection:
    decl = ctx.modelica.declarations.get(f"tank_{component.tag}")
    level_start = decl.modifiers.get("level_start") if decl else None
    return smc(
        component.tag,
        _td("Vessel"),
        _quantity("CrossSectionalArea", component, "cross_section", "CrossSectionalArea"),
        _quantity("Height", component, "height", "Height"),
        _quantity("NominalVolume", component, "nominal_volume", "NominalVolume"),
        _quantity("PortDiameter", component, "port_diameter", "PortDiameter"),
        (
            prop("LevelStart", level_start, _td("LevelStart"), description="Unit: m")
            if level_start is not None
            else None
        ),
        description=component.display_name,
    )


def _pump(component: Component) -> model.SubmodelElementCollection:
    points = [
        smc(
            f"Point{i}",
            _td("CharacteristicPoint"),
            prop("VolumeFlow", v_flow, _td("VolumeFlow"), description="Unit: m3/s"),
            prop("Head", head, _td("Head"), description="Unit: m"),
        )
        for i, (v_flow, head) in enumerate(component.flow_characteristic, start=1)
    ]
    return smc(
        component.tag,
        _td("Pump"),
        _quantity("NominalSpeed", component, "nominal_speed", "NominalSpeed"),
        _quantity("DisplacedVolume", component, "displaced_volume", "DisplacedVolume"),
        (
            sml(
                "FlowCharacteristic",
                model.SubmodelElementCollection,
                _td("FlowCharacteristic"),
                points,
                semantic_id_list_element=_td("CharacteristicPoint"),
                description="Quadratic head-flow characteristic from the Modelica parameter block.",
            )
            if points
            else None
        ),
        description=component.function or component.display_name,
    )


def _valve(component: Component) -> model.SubmodelElementCollection:
    return smc(
        component.tag,
        _td("Valve"),
        prop("ValveType", component.valve_type, _td("ValveType")) if component.valve_type else None,
        prop("Actuation", component.actuation, _td("Actuation")) if component.actuation else None,
        _quantity("NominalPressureDrop", component, "nominal_pressure_drop", "NominalPressureDrop"),
        _quantity("NominalMassFlow", component, "nominal_mass_flow", "NominalMassFlow"),
        description=component.note or component.display_name,
    )


def _piping(ctx: BuildContext) -> model.SubmodelElementCollection:
    segments = []
    for pipe in ctx.modelica.of_type("StaticPipe"):
        segments.append(
            smc(
                pipe.name,
                _td("PipeSegment"),
                prop(
                    "PipeDiameter",
                    pipe.modifiers.get("diameter", 0.01),
                    _td("PipeDiameter"),
                    description="Unit: m",
                ),
                prop(
                    "PipeLength",
                    pipe.modifiers.get("length", 0.0),
                    _td("PipeLength"),
                    description="Unit: m",
                ),
                prop(
                    "ElevationChange",
                    pipe.modifiers.get("height_ab", 0.0),
                    _td("ElevationChange"),
                    description="Unit: m",
                ),
                description=(
                    "Segment as named in the Modelica model. Note deviation D3: some segment "
                    "names contradict the model's own wiring; the P&ID names are authoritative."
                ),
            )
        )
    return smc(
        "Piping",
        _td("Piping"),
        prop(
            "Fittings",
            "John Guest Speedfit push-fit, PEX barrier pipe",
            _td("Fittings"),
            description="From the datasheets in documents/Process_Equipment/Piping/.",
        ),
        sml(
            "Segments",
            model.SubmodelElementCollection,
            _td("PipeSegment"),
            segments,
            semantic_id_list_element=_td("PipeSegment"),
        ),
    )


def _applies_to(record: dict[str, object]) -> list[object]:
    raw = record.get("applies_to")
    return list(raw) if isinstance(raw, list) else []


def _instrument_family(name: str, record: dict[str, object]) -> model.SubmodelElementCollection:
    span = record.get("measuring_span")
    blind = record.get("blind_zone")
    elements: list[model.SubmodelElement | None] = [
        prop("AppliesTo", ", ".join(str(t) for t in _applies_to(record)), _td("AppliesTo")),
        (
            prop("Manufacturer", str(record["manufacturer"]), _td("Manufacturer"))
            if record.get("manufacturer")
            else None
        ),
        (
            prop("ProductType", str(record["product_type"]), _td("ProductType"))
            if record.get("product_type")
            else None
        ),
        (
            prop("OrderCode", str(record["order_code"]), _td("OrderCode"))
            if record.get("order_code")
            else None
        ),
    ]
    if isinstance(span, dict):
        elements.append(
            range_(
                "MeasuringSpan",
                float(span["min"]),
                float(span["max"]),
                _td("MeasuringSpan"),
                description=f"Unit: {span['unit']}",
            )
        )
        elements.append(prop("MeasuringUnit", str(span["unit"]), _td("MeasuringUnit")))
    if isinstance(blind, dict):
        elements.append(
            range_(
                "BlindZone",
                float(blind["min"]),
                float(blind["max"]),
                _td("BlindZone"),
                description=f"Unit: {blind['unit']}",
            )
        )
    if record.get("accuracy"):
        elements.append(prop("Accuracy", str(record["accuracy"]), _td("Accuracy")))
    return smc(
        name, _td("Instrument"), *elements, description=str(record.get("product_designation", name))
    )


def _area(
    id_short: str,
    concept: str,
    *children: model.SubmodelElement | None,
    description: str | None = None,
) -> model.SubmodelElementCollection:
    area = smc(id_short, _sem(_AREA), *children, description=description)
    area.supplemental_semantic_id = [_td(concept)]
    return area


# --- submodels ----------------------------------------------------------------


def _submodel(submodel_id: str, *elements: model.SubmodelElement | None) -> model.Submodel:
    return model.Submodel(
        id_=submodel_id,
        id_short=T.submodel_id_short,
        semantic_id=ext_ref(T.submodel_semantic_id),
        submodel_element=[e for e in elements if e is not None],
        administration=model.AdministrativeInformation(
            version="1", revision="0", template_id=T.template_id
        ),
    )


def _further_information(statement: str) -> model.SubmodelElementCollection:
    return smc(
        "FurtherInformation",
        _sem("FurtherInformation"),
        mlp("TextStatement", statement, _sem("FurtherInformation/TextStatement")),
        prop_typed("ValidDate", datatypes.Date, date.today(), _sem("FurtherInformation/ValidDate")),
    )


def build_plant_technical_data(ctx: BuildContext) -> model.Submodel:
    topo = ctx.topology
    families = ctx.instruments["families"]
    instrument_areas = [
        _instrument_family(name, dict(rec))
        for name, rec in families.items()
        if name.startswith(("level", "pressure", "temperature", "flow"))
    ]
    medium_decl = ctx.modelica.declarations.get("system")
    dp_small = medium_decl.modifiers.get("dp_small") if medium_decl else "n/a"
    return _submodel(
        ids.submodel_id(ids.PLANT_TAG, T.submodel_id_short),
        smc(
            "GeneralInformation",
            _sem("GeneralInformation"),
            prop(
                "ManufacturerName",
                OPERATOR["en"],
                _sem("GeneralInformation/ManufacturerName"),
                description="Operating institution; the plant is a research rig.",
            ),
            mlp(
                "ManufacturerProductDesignation",
                "ModVA fluid mixing plant",
                _sem("GeneralInformation/ManufacturerProductDesignation"),
            ),
        ),
        sml(
            "TechnicalPropertyAreas",
            model.SubmodelElementCollection,
            _sem("TechnicalPropertyAreas"),
            [
                _area(
                    "Vessels",
                    "Vessels",
                    *(_vessel(c, ctx) for c in topo.of_kind(ComponentKind.TANK)),
                    description="Geometry from the Modelica model's TankWithTopPorts parameters.",
                ),
                _area(
                    "Pumps",
                    "Pumps",
                    *(_pump(c) for c in topo.of_kind(ComponentKind.PUMP)),
                    description="From the Modelica model's PrescribedPump parameter block.",
                ),
                _area(
                    "Valves",
                    "Valves",
                    *(_valve(c) for c in topo.of_kind(ComponentKind.VALVE)),
                    description="Ratings from the Modelica ValveLinear parameters.",
                ),
                _area("Piping", "Piping", _piping(ctx)),
                _area(
                    "Instruments",
                    "Instruments",
                    *instrument_areas,
                    description="Type data from the datasheets in documents/Process_Equipment/.",
                ),
                _area(
                    "Medium",
                    "Medium",
                    prop("MediumName", "Water", _td("MediumName")),
                    prop(
                        "MediumModel",
                        "Modelica.Media.Water.StandardWaterOnePhase",
                        _td("MediumModel"),
                    ),
                    description=f"Modelica.Fluid.System dp_small = {dp_small} Pa",
                ),
            ],
            semantic_id_list_element=_sem(_AREA),
        ),
        _further_information(
            "Values are read from simulation/ModVA_online_stable.mo and from the vendor "
            "datasheets under documents/Process_Equipment/ of the fluid mixing benchmark "
            "(DOI 10.1109/ACCESS.2025.3592815) at build time. Manufacturer identification of "
            "the plant as a whole is not available and is deliberately absent."
        ),
    )


def build_component_technical_data(ctx: BuildContext, component: Component) -> model.Submodel:
    family = ctx.instrument_for(component.tag)
    if component.kind is ComponentKind.TANK:
        area = _area("Vessel", "Vessels", _vessel(component, ctx))
    elif component.kind is ComponentKind.PUMP:
        area = _area("Pump", "Pumps", _pump(component))
    elif component.kind is ComponentKind.VALVE:
        area = _area("Valve", "Valves", _valve(component))
    else:
        area = _area(
            "General",
            "Instruments",
            prop("Note", component.note or component.display_name, _td("Instrument")),
        )

    general: list[model.SubmodelElement | None] = [
        mlp(
            "ManufacturerProductDesignation",
            (
                str(family.get("product_designation"))
                if family and family.get("product_designation")
                else component.display_name
            ),
            _sem("GeneralInformation/ManufacturerProductDesignation"),
        ),
    ]
    if family and family.get("manufacturer"):
        general.insert(
            0,
            prop(
                "ManufacturerName",
                str(family["manufacturer"]),
                _sem("GeneralInformation/ManufacturerName"),
            ),
        )
    if family and family.get("order_code"):
        general.append(
            prop(
                "ManufacturerOrderCode",
                str(family["order_code"]),
                _sem("GeneralInformation/ManufacturerOrderCode"),
            )
        )

    return _submodel(
        ids.submodel_id(component.tag, T.submodel_id_short),
        smc("GeneralInformation", _sem("GeneralInformation"), *general),
        sml(
            "TechnicalPropertyAreas",
            model.SubmodelElementCollection,
            _sem("TechnicalPropertyAreas"),
            [area],
            semantic_id_list_element=_sem(_AREA),
        ),
        _further_information(
            f"Component {component.tag} of the ModVA plant. Values from the Modelica model and, "
            "where a datasheet exists, from documents/Process_Equipment/."
        ),
    )
