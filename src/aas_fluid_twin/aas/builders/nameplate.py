"""Digital Nameplate — IDTA 02006-3-0.

Built for the plant and for each component shell. Every value comes from a vendor datasheet
in the benchmark or from the plant author; where neither gives a value the element is
**absent**, including template-mandatory ones. A conformance report lists those gaps; the
alternative — a plausible-looking wrong manufacturer — would poison the twin.
"""

from __future__ import annotations

from basyx.aas import model
from basyx.aas.model import datatypes

from aas_fluid_twin.aas import ids
from aas_fluid_twin.aas.builders._common import ext_ref, mlp, prop, prop_typed, smc
from aas_fluid_twin.aas.context import BuildContext
from aas_fluid_twin.aas.templates import template
from aas_fluid_twin.benchmark.topology import Component

__all__ = ["build_component_nameplate", "build_plant_nameplate"]

T = template("nameplate")
#: ``AddressInformation`` is empty in the nameplate template; its children are defined by the
#: Contact Information template (IDTA 02002), which the nameplate template references.
CONTACT = template("contact_information")

#: The plant's operating institution (open item O12, answered by the plant author).
OPERATOR = {
    "en": "Helmut Schmidt University Hamburg",
    "de": "Helmut-Schmidt-Universität / Universität der Bundeswehr Hamburg",
}
OPERATOR_ADDRESS = {
    "Street": "Holstenhofweg 85",
    "Zipcode": "22043",
    "CityTown": "Hamburg",
    "NationalCode": "DE",
}


def _sem(path: str) -> model.ExternalReference:
    return ext_ref(T.semantic(path))


def _contact(path: str) -> model.ExternalReference:
    return ext_ref(CONTACT.semantic(f"ContactInformation/{path}"))


def _operator_address() -> model.SubmodelElementCollection:
    return smc(
        "AddressInformation",
        _sem("AddressInformation"),
        mlp("Company", OPERATOR["en"], _contact("Company"), de=OPERATOR["de"]),
        *(mlp(key, value, _contact(key)) for key, value in OPERATOR_ADDRESS.items()),
        description="Operating institution of the plant, as stated by the plant author.",
    )


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


def build_plant_nameplate(ctx: BuildContext) -> model.Submodel:
    """The plant's own nameplate.

    The plant is a one-off research rig; the operating institution takes the manufacturer's
    place (open item O12). The controller, the one commercially identifiable part, goes in
    ``AssetSpecificProperties``.
    """
    plc = ctx.controller
    return _submodel(
        ids.submodel_id(ids.PLANT_TAG, T.submodel_id_short),
        prop_typed(
            "URIOfTheProduct", datatypes.AnyURI, ids.PLANT_ASSET_ID, _sem("URIOfTheProduct")
        ),
        mlp("ManufacturerName", OPERATOR["en"], _sem("ManufacturerName"), de=OPERATOR["de"]),
        mlp(
            "ManufacturerProductDesignation",
            "ModVA fluid mixing plant — four-tank dosing and mixing rig",
            _sem("ManufacturerProductDesignation"),
            de="ModVA Mischmodul — Dosier- und Mischanlage mit vier Behältern",
        ),
        mlp(
            "ManufacturerProductFamily",
            "Fluid mixing test plant",
            _sem("ManufacturerProductFamily"),
        ),
        _operator_address(),
        prop("UniqueFacilityIdentifier", ids.PLANT_TAG, _sem("UniqueFacilityIdentifier")),
        smc(
            "AssetSpecificProperties",
            _sem("AssetSpecificProperties"),
            prop(
                "ControllerManufacturer",
                str(plc["manufacturer"]),
                _sem("AssetSpecificProperties/ArbitraryProperty"),
            ),
            prop(
                "ControllerType",
                str(plc["product_type"]),
                _sem("AssetSpecificProperties/ArbitraryProperty"),
            ),
            prop(
                "ControllerProgrammingSystem",
                str(plc["programming_system"]),
                _sem("AssetSpecificProperties/ArbitraryProperty"),
            ),
            prop(
                "ControllerProject",
                str(plc["project"]),
                _sem("AssetSpecificProperties/ArbitraryProperty"),
            ),
        ),
    )


def build_component_nameplate(ctx: BuildContext, component: Component) -> model.Submodel:
    """A component's nameplate from its datasheet family, if one exists."""
    family = ctx.instrument_for(component.tag)
    tag = component.tag

    manufacturer = family.get("manufacturer") if family else None
    designation = (family.get("product_designation") if family else None) or component.display_name
    product_type = family.get("product_type") if family else None
    order_code = family.get("order_code") if family else None
    pilot_type = family.get("pilot_product_type") if family else None
    pilot_note = family.get("pilot_note") if family else None
    source = family.get("source") if family else None

    specific: list[model.SubmodelElement | None] = []
    if pilot_type:
        specific.append(
            prop(
                "PilotValveType",
                str(pilot_type),
                _sem("AssetSpecificProperties/ArbitraryProperty"),
                description=str(pilot_note) if pilot_note else None,
            )
        )
    if component.valve_type:
        specific.append(
            prop(
                "ValveType", component.valve_type, _sem("AssetSpecificProperties/ArbitraryProperty")
            )
        )
    if component.actuation:
        specific.append(
            prop(
                "Actuation", component.actuation, _sem("AssetSpecificProperties/ArbitraryProperty")
            )
        )
    if source:
        specific.append(
            prop(
                "Datasheet",
                str(source),
                _sem("AssetSpecificProperties/ArbitraryProperty"),
                description="Path of the vendor datasheet inside the benchmark repository.",
            )
        )

    return _submodel(
        ids.submodel_id(tag, T.submodel_id_short),
        prop_typed(
            "URIOfTheProduct",
            datatypes.AnyURI,
            ids.component_asset_id(tag),
            _sem("URIOfTheProduct"),
        ),
        (
            mlp("ManufacturerName", str(manufacturer), _sem("ManufacturerName"))
            if manufacturer
            else None
        ),
        mlp(
            "ManufacturerProductDesignation",
            str(designation),
            _sem("ManufacturerProductDesignation"),
        ),
        (
            prop("ManufacturerProductType", str(product_type), _sem("ManufacturerProductType"))
            if product_type
            else None
        ),
        (
            prop("OrderCodeOfManufacturer", str(order_code), _sem("OrderCodeOfManufacturer"))
            if order_code
            else None
        ),
        prop("UniqueFacilityIdentifier", tag, _sem("UniqueFacilityIdentifier")),
        (
            smc("AssetSpecificProperties", _sem("AssetSpecificProperties"), *specific)
            if any(specific)
            else None
        ),
    )
