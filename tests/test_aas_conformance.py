"""Conformance of the built environment to the IDTA templates and to the project vocabulary.

Three rules, checked over every element of every submodel:

1. An element in an IDTA-based submodel carries either a semanticId the template defines —
   and then its model type matches what the template says for that semanticId — or a
   project semanticId under the extension base (a documented custom addition). Nothing is
   unsemantic, except operation variables, which the metamodel leaves untyped.
2. Every project semanticId used anywhere has a ConceptDescription in the store.
3. Every template-mandatory element is present, except the ones listed in KNOWN_GAPS with a
   reason. A new gap fails the test; a gap that closes must be removed from the list.
"""

from __future__ import annotations

from collections import defaultdict

import pytest
from basyx.aas import model

from aas_fluid_twin.aas import ids
from aas_fluid_twin.aas.environment import BuiltEnvironment
from aas_fluid_twin.aas.templates import Template, template
from aas_fluid_twin.aas.traverse import semantic_iri, walk

pytestmark = pytest.mark.benchmark_data

ALL_TEMPLATES: tuple[str, ...] = (
    "nameplate",
    "contact_information",
    "technical_data",
    "handover_documentation",
    "hierarchical_structures",
    "asset_interfaces_description",
    "time_series",
    "simulation_models",
)

#: submodel idShort -> vendored template key
TEMPLATED: dict[str, str] = {
    "Nameplate": "nameplate",
    "TechnicalData": "technical_data",
    "HandoverDocumentation": "handover_documentation",
    "HierarchicalStructures": "hierarchical_structures",
    "AssetInterfacesDescription": "asset_interfaces_description",
    "TimeSeries": "time_series",
    "SimulationModels": "simulation_models",
}

#: Template-mandatory elements deliberately absent, with the reason. "Absent not invented."
KNOWN_GAPS: dict[str, dict[str, str]] = {
    "nameplate": {
        "ManufacturerName": "Tanks and stirrer have no datasheet and no maker on record.",
        "AddressInformation": "No manufacturer address is published in the component datasheets.",
        "OrderCodeOfManufacturer": "Only the flow and temperature sensors publish an order code.",
    },
    "technical_data": {
        "GeneralInformation/ManufacturerName": "Not known for the tanks and the stirrer.",
        "GeneralInformation/ManufacturerArticleNumber": "Not published in the datasheets.",
        "GeneralInformation/ManufacturerOrderCode": "Only some datasheets give one.",
    },
    "simulation_models": {
        "SimulationModel/Quality": "Usability/architecture/validation ratings would be invented.",
    },
}

_TYPE_NAMES: dict[type[model.SubmodelElement], str] = {
    model.Property: "Property",
    model.MultiLanguageProperty: "MultiLanguageProperty",
    model.Range: "Range",
    model.File: "File",
    model.Blob: "Blob",
    model.ReferenceElement: "ReferenceElement",
    model.SubmodelElementCollection: "SubmodelElementCollection",
    model.SubmodelElementList: "SubmodelElementList",
    model.Entity: "Entity",
    model.RelationshipElement: "RelationshipElement",
    model.AnnotatedRelationshipElement: "AnnotatedRelationshipElement",
    model.Operation: "Operation",
}


def _type_name(element: model.SubmodelElement) -> str:
    for cls, name in _TYPE_NAMES.items():
        if type(element) is cls:
            return name
    return type(element).__name__


def _template_types_by_semantic(tpl: Template) -> dict[str, set[str]]:
    """semanticId -> model types, from this template plus the ones it composes.

    Templates reference each other (the nameplate's ``AddressInformation`` is filled per the
    Contact Information template), so the vocabulary of every vendored template is admissible;
    the model-type check stays per semanticId.
    """
    out: defaultdict[str, set[str]] = defaultdict(set)
    for key in ALL_TEMPLATES:
        for element in template(key).elements.values():
            if element.semantic_id:
                out[element.semantic_id].add(element.model_type)
    return out


def _templated_submodels(env: BuiltEnvironment) -> list[tuple[model.Submodel, Template]]:
    out = []
    for submodel in env.submodels.values():
        key = TEMPLATED.get(submodel.id_short or "")
        if key:
            out.append((submodel, template(key)))
    return out


# --- rule 1 ---------------------------------------------------------------------


def test_templated_submodels_carry_the_template_semantic_id(env: BuiltEnvironment) -> None:
    for submodel, tpl in _templated_submodels(env):
        assert semantic_iri(submodel) == tpl.submodel_semantic_id, submodel.id
        assert submodel.administration is not None
        assert submodel.administration.template_id == tpl.template_id


def test_every_element_is_semantically_typed_and_conformant(env: BuiltEnvironment) -> None:
    problems: list[str] = []
    for submodel, tpl in _templated_submodels(env):
        allowed = _template_types_by_semantic(tpl)
        for path, element in walk(submodel):
            iri = semantic_iri(element)
            if iri is None:
                # Operation variables are the one place the metamodel leaves untyped.
                if "/" in path and any(
                    isinstance(parent, model.Operation)
                    for _, parent in walk(submodel)
                    if parent.id_short and path.startswith(parent.id_short + "/")
                ):
                    continue
                problems.append(f"{submodel.id_short}/{path}: no semanticId")
                continue
            if iri.startswith(ids.EXTENSION_BASE):
                continue  # documented custom addition, checked by rule 2
            if iri not in allowed:
                problems.append(f"{submodel.id_short}/{path}: semanticId not in {tpl.idta}: {iri}")
                continue
            if _type_name(element) not in allowed[iri]:
                problems.append(
                    f"{submodel.id_short}/{path}: {tpl.idta} says {sorted(allowed[iri])} "
                    f"for this semanticId, got {_type_name(element)}"
                )
    assert not problems, "\n".join(problems[:40])


# --- rule 2 ---------------------------------------------------------------------


def test_every_custom_semantic_id_has_a_concept_description(env: BuiltEnvironment) -> None:
    known = {cd.id for cd in env.concept_descriptions()}
    missing: set[str] = set()
    for submodel in env.submodels.values():
        iri = semantic_iri(submodel)
        if iri and iri.startswith(ids.EXTENSION_BASE) and iri not in known:
            missing.add(iri)
        for _, element in walk(submodel):
            iri = semantic_iri(element)
            if iri and iri.startswith(ids.EXTENSION_BASE) and iri not in known:
                missing.add(iri)
            for qualifier in element.qualifier:
                q = qualifier.semantic_id
                if (
                    q
                    and q.key
                    and q.key[0].value.startswith(ids.EXTENSION_BASE)
                    and q.key[0].value not in known
                ):
                    missing.add(q.key[0].value)
    assert not missing, sorted(missing)


def test_concept_descriptions_carry_iec61360_data_specifications(env: BuiltEnvironment) -> None:
    for cd in env.concept_descriptions():
        specs = list(cd.embedded_data_specifications)
        assert specs, cd.id
        content = specs[0].data_specification_content
        assert isinstance(content, model.DataSpecificationIEC61360), cd.id
        assert content.preferred_name, cd.id
        assert content.definition, cd.id


# --- rule 3 ---------------------------------------------------------------------


def _present_paths(submodel: model.Submodel) -> set[str]:
    return {path for path, _ in walk(submodel)}


def test_mandatory_template_elements_are_present_or_explained(env: BuiltEnvironment) -> None:
    unexplained: list[str] = []
    closed: list[str] = []
    for submodel, tpl in _templated_submodels(env):
        present = _present_paths(submodel)
        gaps = KNOWN_GAPS.get(tpl.key, {})
        # Only top-level mandatory elements; nested ones are conditional on their parent.
        for path in tpl.mandatory_paths():
            element = tpl.element(path)
            if element.model_type == "SubmodelElementList" or path.endswith("/[]"):
                continue
            if path not in present and path not in gaps:
                unexplained.append(f"{submodel.id_short} ({submodel.id}): missing {path}")
    assert not unexplained, "\n".join(unexplained)
    # A gap listed for a template must be a real gap in at least one submodel of that kind;
    # otherwise the allowlist is stale.
    for tpl_key, gaps in KNOWN_GAPS.items():
        subs = [s for s, t in _templated_submodels(env) if t.key == tpl_key]
        for path in gaps:
            if all(path in _present_paths(s) for s in subs):
                closed.append(f"{tpl_key}: {path} is present everywhere — remove from KNOWN_GAPS")
    assert not closed, "\n".join(closed)


# --- id_short hygiene -----------------------------------------------------------


def test_id_shorts_are_unique_within_each_container(env: BuiltEnvironment) -> None:
    """Siblings must have distinct idShorts; list children must have none at all."""

    def check(container: str, children: list[model.SubmodelElement], in_list: bool) -> None:
        names = [c.id_short for c in children]
        if in_list:
            # The SDK assigns list children an internal placeholder that serialisation drops.
            assert all(
                n is None or n.startswith("generated_submodel_list_hack") for n in names
            ), f"{container}: list children carry idShorts"
            return
        dupes = {n for n in names if names.count(n) > 1}
        assert not dupes, f"{container}: duplicate idShorts {dupes}"

    for submodel in env.submodels.values():
        check(submodel.id_short or "", list(submodel.submodel_element), False)
        for path, element in walk(submodel):
            label = f"{submodel.id_short}/{path}"
            if isinstance(element, model.SubmodelElementList):
                check(label, list(element.value), True)
            elif isinstance(element, model.SubmodelElementCollection):
                check(label, list(element.value), False)
            elif isinstance(element, model.Entity):
                check(label, list(element.statement), False)
            elif isinstance(element, model.AnnotatedRelationshipElement):
                check(label, list(element.annotation), False)
