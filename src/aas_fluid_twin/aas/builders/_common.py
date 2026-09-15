"""Small constructors shared by every builder.

They exist to keep the builders readable: a submodel built with the raw SDK constructors is
three times the length and the structure disappears under keyword arguments. Nothing here
adds semantics; each helper is a thin wrapper that fixes the one or two arguments every call
would otherwise repeat.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from typing import Any, TypeVar

from basyx.aas import model
from basyx.aas.model import datatypes

__all__ = [
    "aas_ref",
    "element_ref",
    "entity",
    "ext_ref",
    "file",
    "id_short_for",
    "mlp",
    "package_path",
    "prop",
    "prop_typed",
    "qualifier",
    "range_",
    "ref_element",
    "smc",
    "sml",
    "submodel_ref",
    "text",
]

_SE = TypeVar("_SE", bound=model.SubmodelElement)


# --- references ---------------------------------------------------------------


def ext_ref(iri: str) -> model.ExternalReference:
    """A global (external) reference to an IRI or IRDI."""
    return model.ExternalReference((model.Key(model.KeyTypes.GLOBAL_REFERENCE, iri),))


def aas_ref(aas_id: str) -> model.ModelReference[model.AssetAdministrationShell]:
    return model.ModelReference(
        (model.Key(model.KeyTypes.ASSET_ADMINISTRATION_SHELL, aas_id),),
        model.AssetAdministrationShell,
    )


def submodel_ref(submodel_id: str) -> model.ModelReference[model.Submodel]:
    return model.ModelReference((model.Key(model.KeyTypes.SUBMODEL, submodel_id),), model.Submodel)


_KEY_TYPE_FOR: Mapping[type[model.SubmodelElement], model.KeyTypes] = {
    model.Property: model.KeyTypes.PROPERTY,
    model.MultiLanguageProperty: model.KeyTypes.MULTI_LANGUAGE_PROPERTY,
    model.Range: model.KeyTypes.RANGE,
    model.File: model.KeyTypes.FILE,
    model.ReferenceElement: model.KeyTypes.REFERENCE_ELEMENT,
    model.SubmodelElementCollection: model.KeyTypes.SUBMODEL_ELEMENT_COLLECTION,
    model.SubmodelElementList: model.KeyTypes.SUBMODEL_ELEMENT_LIST,
    model.Entity: model.KeyTypes.ENTITY,
    model.RelationshipElement: model.KeyTypes.RELATIONSHIP_ELEMENT,
    model.AnnotatedRelationshipElement: model.KeyTypes.ANNOTATED_RELATIONSHIP_ELEMENT,
    model.Operation: model.KeyTypes.OPERATION,
}


def element_ref(
    submodel_id: str,
    path: Iterable[tuple[type[Any], str]],
) -> model.ModelReference[model.SubmodelElement]:
    """A model reference into a submodel: ``[(SubmodelElementCollection, "Metadata"), ...]``.

    Every key carries the concrete element type, which is what the AAS spec requires and what
    lets a client resolve the path without loading the whole submodel.
    """
    keys: list[model.Key] = [model.Key(model.KeyTypes.SUBMODEL, submodel_id)]
    last_type: type[Any] = model.SubmodelElement
    for element_type, id_short in path:
        keys.append(model.Key(_KEY_TYPE_FOR[element_type], id_short))
        last_type = element_type
    return model.ModelReference(tuple(keys), last_type)


# --- identifiers --------------------------------------------------------------


def id_short_for(tag: str) -> str:
    """An idShort for a plant tag.

    AASd-002 allows letters, digits, underscore and hyphen. The level-switch tags carry a sign
    (``LA-201`` low, ``LA+210`` high); it is replaced by an underscore, which is also how the
    Modelica model names those blocks (``LA_201``). The original tag stays in descriptions.
    """
    return tag.replace("+", "_").replace("-", "_")


_PART_NAME_SAFE = re.compile(r"[^a-z0-9._-]+")


def package_path(folder: str, filename: str) -> str:
    """A supplementary-file part name inside the AASX package.

    OPC part names are URI segments. Apache POI (the reader behind Eclipse BaSyx) rejects
    spaces and ``+`` outright, and part names are case-insensitive, so the name is lower-cased
    and every character outside ``[a-z0-9._-]`` becomes ``_``:
    ``P201 + P202 Pumps.pdf`` → ``p201_p202_pumps.pdf``.
    """
    safe = _PART_NAME_SAFE.sub("_", filename.lower()).strip("_")
    return f"/aasx/{folder}/{safe}"


# --- language strings ---------------------------------------------------------


def text(en: str, de: str | None = None) -> model.MultiLanguageTextType:
    langs = {"en": en}
    if de:
        langs["de"] = de
    return model.MultiLanguageTextType(langs)


def name(en: str) -> model.MultiLanguageNameType:
    return model.MultiLanguageNameType({"en": en})


# --- data elements ------------------------------------------------------------


def _value_type(value: Any) -> type:
    if isinstance(value, bool):
        return datatypes.Boolean
    if isinstance(value, int):
        return datatypes.Int
    if isinstance(value, float):
        return datatypes.Double
    if isinstance(value, datetime):
        return datatypes.DateTime
    if isinstance(value, date):
        return datatypes.Date
    return datatypes.String


def prop(
    id_short: str,
    value: Any,
    semantic_id: model.Reference | None = None,
    *,
    description: str | None = None,
    qualifiers: Iterable[model.Qualifier] = (),
) -> model.Property:
    """A Property whose XSD type is inferred from the Python value."""
    return model.Property(
        id_short=id_short,
        value_type=_value_type(value),
        value=value,
        semantic_id=semantic_id,
        description=text(description) if description else None,
        qualifier=qualifiers,
    )


def prop_typed(
    id_short: str,
    value_type: type,
    value: Any,
    semantic_id: model.Reference | None = None,
    *,
    description: str | None = None,
    qualifiers: Iterable[model.Qualifier] = (),
) -> model.Property:
    """A Property with an explicit XSD type, e.g. ``datatypes.AnyURI``."""
    return model.Property(
        id_short=id_short,
        value_type=value_type,
        value=value,
        semantic_id=semantic_id,
        description=text(description) if description else None,
        qualifier=qualifiers,
    )


def mlp(
    id_short: str,
    en: str,
    semantic_id: model.Reference | None = None,
    *,
    de: str | None = None,
) -> model.MultiLanguageProperty:
    return model.MultiLanguageProperty(
        id_short=id_short, value=text(en, de), semantic_id=semantic_id
    )


def range_(
    id_short: str,
    minimum: float | None,
    maximum: float | None,
    semantic_id: model.Reference | None = None,
    *,
    description: str | None = None,
) -> model.Range:
    return model.Range(
        id_short=id_short,
        value_type=datatypes.Double,
        min=minimum,
        max=maximum,
        semantic_id=semantic_id,
        description=text(description) if description else None,
    )


def file(
    id_short: str,
    path: str,
    content_type: str,
    semantic_id: model.Reference | None = None,
    *,
    description: str | None = None,
) -> model.File:
    return model.File(
        id_short=id_short,
        content_type=content_type,
        value=path,
        semantic_id=semantic_id,
        description=text(description) if description else None,
    )


def ref_element(
    id_short: str,
    target: model.Reference,
    semantic_id: model.Reference | None = None,
) -> model.ReferenceElement:
    return model.ReferenceElement(id_short=id_short, value=target, semantic_id=semantic_id)


def qualifier(
    type_: str, value: str, semantic_id: model.Reference | None = None
) -> model.Qualifier:
    return model.Qualifier(
        type_=type_,
        value_type=datatypes.String,
        value=value,
        kind=model.QualifierKind.CONCEPT_QUALIFIER,
        semantic_id=semantic_id,
    )


# --- containers ---------------------------------------------------------------


def smc(
    id_short: str,
    semantic_id: model.Reference | None,
    *children: model.SubmodelElement | None,
    description: str | None = None,
) -> model.SubmodelElementCollection:
    """A collection. ``None`` children are skipped, so optional elements can be inlined."""
    return model.SubmodelElementCollection(
        id_short=id_short,
        value=[c for c in children if c is not None],
        semantic_id=semantic_id,
        description=text(description) if description else None,
    )


def sml(
    id_short: str,
    element_type: type[_SE],
    semantic_id: model.Reference | None,
    children: Iterable[_SE],
    *,
    semantic_id_list_element: model.Reference | None = None,
    description: str | None = None,
) -> model.SubmodelElementList[_SE]:
    """A list. List children must not carry an idShort; it is cleared here so callers can
    build them with one for readability and still get a valid list."""
    items = list(children)
    for item in items:
        item.id_short = None
    # AASd-109: a list of Property/Range must declare the value type of its elements.
    value_type = None
    if items and isinstance(items[0], model.Property | model.Range):
        value_type = items[0].value_type
    return model.SubmodelElementList(
        id_short=id_short,
        type_value_list_element=element_type,
        value=items,
        value_type_list_element=value_type,
        semantic_id=semantic_id,
        semantic_id_list_element=semantic_id_list_element,
        description=text(description) if description else None,
    )


def entity(
    id_short: str,
    semantic_id: model.Reference | None,
    *statements: model.SubmodelElement | None,
    global_asset_id: str | None = None,
    description: str | None = None,
) -> model.Entity:
    """A BoM node. Self-managed when it has its own asset id, co-managed otherwise."""
    kind = (
        model.EntityType.SELF_MANAGED_ENTITY
        if global_asset_id
        else model.EntityType.CO_MANAGED_ENTITY
    )
    return model.Entity(
        id_short=id_short,
        entity_type=kind,
        statement=[s for s in statements if s is not None],
        global_asset_id=global_asset_id,
        semantic_id=semantic_id,
        description=text(description) if description else None,
    )
