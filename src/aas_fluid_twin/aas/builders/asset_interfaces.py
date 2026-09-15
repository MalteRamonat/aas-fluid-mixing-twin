"""Asset Interfaces Description — IDTA 02017-1-1 (W3C WoT Thing Description in AAS).

The plant's OPC UA server, described property by property from the signal dictionary: one
``PropertyAffordance`` per recorded channel, keyed by the CSV column name and carrying the
OPC UA NodeId as the form's ``href``. That makes the AAS the join between the live interface,
the recorded files and the time-series store.

The server itself is no longer reachable (open item O8). The description is still accurate —
every NodeId comes from the plant's own mapping table — so it is published with a placeholder
``base`` and an explicit ``LiveEndpoint = false`` rather than dropped.
"""

from __future__ import annotations

from basyx.aas import model
from basyx.aas.model import datatypes

from aas_fluid_twin.aas import ids
from aas_fluid_twin.aas.builders._common import (
    ext_ref,
    prop,
    prop_typed,
    qualifier,
    range_,
    ref_element,
    smc,
    sml,
)
from aas_fluid_twin.aas.context import BuildContext
from aas_fluid_twin.aas.semantics import channel_semantic, semantic
from aas_fluid_twin.aas.templates import template
from aas_fluid_twin.benchmark.signals import Quality, Role, Signal

__all__ = [
    "INTERFACE_ID_SHORT",
    "build_asset_interfaces_description",
    "property_reference",
    "span_in_channel_unit",
]

T = template("asset_interfaces_description")
SUBMODEL_ID = ids.submodel_id(ids.PLANT_TAG, T.submodel_id_short)
INTERFACE_ID_SHORT = "InterfaceOPCUA"

_I = "InterfaceTemplateForOPCUA"
_P = f"{_I}/InteractionMetadata/properties/property_name"


def _sem(path: str) -> model.ExternalReference:
    return ext_ref(T.semantic(path))


#: Engineering unit -> UN/CEFACT common code, which is what ``schema.org/unitCode`` expects.
_UNIT_CODES: dict[str, str] = {
    "ml": "MLT",
    "kPa": "KPA",
    "°C": "CEL",
    "l/min": "L2",
    "cm": "CMT",
}

#: (datasheet unit, channel unit) -> factor. The datasheets quote spans in their own units
#: (bar, mm); the interface property must quote them in the channel's unit (kPa, cm).
_SPAN_FACTORS: dict[tuple[str, str], float] = {
    ("bar", "kPa"): 100.0,
    ("mm", "cm"): 0.1,
    ("L/min", "l/min"): 1.0,
    ("Cel", "°C"): 1.0,
}


def span_in_channel_unit(signal: Signal) -> tuple[float, float] | None:
    """The instrument's measuring span expressed in the channel's engineering unit."""
    span = signal.measuring_span
    if span is None or signal.unit is None:
        return None
    source_unit = str(span["unit"])
    if source_unit == signal.unit:
        factor = 1.0
    else:
        try:
            factor = _SPAN_FACTORS[(source_unit, signal.unit)]
        except KeyError:
            raise KeyError(
                f"{signal.sensor_id}: no conversion from datasheet unit {source_unit!r} to "
                f"channel unit {signal.unit!r}"
            ) from None
    return float(span["min"]) * factor, float(span["max"]) * factor


def property_reference(channel: str) -> model.ModelReference[model.SubmodelElement]:
    """Model reference to the AID property for a channel — used by the twin linkage."""
    from aas_fluid_twin.aas.builders._common import element_ref

    return element_ref(
        SUBMODEL_ID,
        [
            (model.SubmodelElementCollection, INTERFACE_ID_SHORT),
            (model.SubmodelElementCollection, "InteractionMetadata"),
            (model.SubmodelElementCollection, "properties"),
            (model.SubmodelElementCollection, channel),
        ],
    )


def _quality_qualifiers(signal: Signal) -> tuple[model.Qualifier, ...]:
    if signal.quality is Quality.GOOD:
        return ()
    return (qualifier("DataQuality", signal.quality.value, semantic("Common", "DataQuality")),)


def _property(signal: Signal) -> model.SubmodelElementCollection:
    span = span_in_channel_unit(signal)
    role = "Actuator command" if signal.role is Role.ACTUATOR else "Sensor reading"
    description = f"{role}. {signal.display_name}."
    if signal.quality_reason:
        description += f" Quality {signal.quality.value}: {signal.quality_reason}"

    unit_code = _UNIT_CODES.get(signal.unit or "")
    element = smc(
        signal.channel,
        _sem(_P),
        prop("key", signal.channel, _sem(f"{_P}/key")),
        prop("type", "boolean" if signal.is_binary else "number", _sem(f"{_P}/type")),
        prop("title", signal.display_name, _sem(f"{_P}/title")),
        prop("observable", True, _sem(f"{_P}/observable")),
        (
            prop(
                "unit",
                unit_code,
                _sem(f"{_P}/unit"),
                description=f"UN/CEFACT code for {signal.unit}",
            )
            if unit_code
            else None
        ),
        (
            range_(
                "min_max",
                span[0],
                span[1],
                _sem(f"{_P}/min_max"),
                description=f"Instrument measuring span from the datasheet, in {signal.unit}.",
            )
            if span
            else None
        ),
        ref_element("valueSemantics", channel_semantic(signal), _sem(f"{_P}/valueSemantics")),
        smc(
            "forms",
            _sem(f"{_P}/forms"),
            prop_typed(
                "href",
                datatypes.String,
                signal.opcua_node_id,
                _sem(f"{_P}/forms/href"),
                description="OPC UA NodeId on the plant controller.",
            ),
        ),
        description=description,
    )
    for q in _quality_qualifiers(signal):
        element.qualifier.add(q)
    return element


def build_asset_interfaces_description(ctx: BuildContext) -> model.Submodel:
    endpoints = ctx.endpoints
    controller = ctx.controller

    interface = smc(
        INTERFACE_ID_SHORT,
        _sem(_I),
        prop(
            "title",
            f"{controller['manufacturer']} {controller['product_type']} OPC UA server",
            _sem(f"{_I}/title"),
        ),
        smc(
            "EndpointMetadata",
            _sem(f"{_I}/EndpointMetadata"),
            prop_typed(
                "base",
                datatypes.AnyURI,
                endpoints.opcua_server,
                _sem(f"{_I}/EndpointMetadata/base"),
                description=(
                    "Placeholder. The plant's OPC UA server is no longer accessible; the "
                    "NodeIds below are nevertheless exact, from the plant's mapping table."
                    if not endpoints.opcua_live
                    else None
                ),
            ),
            prop(
                "contentType",
                "application/x.opcua-binary",
                _sem(f"{_I}/EndpointMetadata/contentType"),
            ),
            prop("LiveEndpoint", endpoints.opcua_live, semantic("Common", "LiveEndpoint")),
            sml(
                "security",
                model.ReferenceElement,
                _sem(f"{_I}/EndpointMetadata/security"),
                [
                    ref_element(
                        "nosec",
                        ext_ref("https://www.w3.org/2019/wot/security#NoSecurityScheme"),
                        _sem(f"{_I}/EndpointMetadata/security/definesSecurityScheme"),
                    )
                ],
                semantic_id_list_element=_sem(
                    f"{_I}/EndpointMetadata/security/definesSecurityScheme"
                ),
            ),
            smc(
                "securityDefinitions",
                _sem(f"{_I}/EndpointMetadata/securityDefinitions"),
                smc(
                    "nosec_sc",
                    _sem(f"{_I}/EndpointMetadata/securityDefinitions/nosec_sc"),
                    prop(
                        "scheme",
                        "nosec",
                        _sem(f"{_I}/EndpointMetadata/securityDefinitions/nosec_sc/scheme"),
                    ),
                ),
            ),
        ),
        smc(
            "InteractionMetadata",
            _sem(f"{_I}/InteractionMetadata"),
            smc(
                "properties",
                _sem(f"{_I}/InteractionMetadata/properties"),
                *(_property(s) for s in ctx.signals),
            ),
        ),
    )

    return model.Submodel(
        id_=SUBMODEL_ID,
        id_short=T.submodel_id_short,
        semantic_id=ext_ref(T.submodel_semantic_id),
        administration=model.AdministrativeInformation(
            version="1", revision="0", template_id=T.template_id
        ),
        submodel_element=[interface],
        description=model.MultiLanguageTextType(
            {
                "en": f"{len(ctx.signals)} OPC UA properties of the plant controller, from "
                "Simulation_Variable_Mapping.xlsx. Channel keys are the CSV column names."
            }
        ),
    )
