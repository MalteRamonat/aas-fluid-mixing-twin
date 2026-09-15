"""Walking submodel trees, and naming the elements in them.

Two path conventions exist and both are needed:

* the *template* convention — ``Documents/[]/DocumentVersions/[]/Title`` — where list children
  are anonymous; that is how the vendored IDTA indexes are keyed;
* the *API* convention — ``Documents[0].DocumentVersions[0].Title`` — the ``idShortPath`` the
  AAS Part-2 HTTP API addresses elements by.

:func:`walk` yields the first, :func:`id_short_paths` the second.
"""

from __future__ import annotations

from collections.abc import Iterator

from basyx.aas import model

__all__ = ["children", "fingerprint", "id_short_paths", "semantic_iri", "walk"]


def children(element: model.SubmodelElement) -> list[model.SubmodelElement]:
    if isinstance(element, model.SubmodelElementCollection | model.SubmodelElementList):
        return list(element.value)
    if isinstance(element, model.Entity):
        return list(element.statement)
    if isinstance(element, model.AnnotatedRelationshipElement):
        return list(element.annotation)
    if isinstance(element, model.Operation):
        return [*element.input_variable, *element.output_variable, *element.in_output_variable]
    return []


def walk(submodel: model.Submodel) -> Iterator[tuple[str, model.SubmodelElement]]:
    """Depth-first, template-convention paths (``[]`` for list children)."""
    stack: list[tuple[str, model.SubmodelElement, bool]] = [
        ("", e, False) for e in reversed(list(submodel.submodel_element))
    ]
    while stack:
        prefix, element, in_list = stack.pop()
        segment = "[]" if in_list else (element.id_short or "?")
        path = f"{prefix}/{segment}" if prefix else segment
        yield path, element
        child_in_list = isinstance(element, model.SubmodelElementList)
        for child in reversed(children(element)):
            stack.append((path, child, child_in_list))


def id_short_paths(submodel: model.Submodel) -> Iterator[tuple[str, model.SubmodelElement]]:
    """Depth-first, API-convention ``idShortPath`` for every element."""

    def visit(
        prefix: str, element: model.SubmodelElement, index: int | None
    ) -> Iterator[tuple[str, model.SubmodelElement]]:
        if index is not None:
            path = f"{prefix}[{index}]"
        else:
            path = f"{prefix}.{element.id_short}" if prefix else str(element.id_short)
        yield path, element
        if isinstance(element, model.SubmodelElementList):
            for i, child in enumerate(element.value):
                yield from visit(path, child, i)
        else:
            for child in children(element):
                yield from visit(path, child, None)

    for top in submodel.submodel_element:
        yield from visit("", top, None)


def semantic_iri(element: model.SubmodelElement | model.Submodel) -> str | None:
    ref = element.semantic_id
    if ref is None or not ref.key:
        return None
    return ref.key[0].value


def fingerprint(
    store: model.AbstractObjectStore[str, model.Identifiable], *, ignore_file_values: bool = False
) -> dict[str, list[str]]:
    """A structural digest of every identifiable: paths, types and scalar values.

    Equal fingerprints mean two environments say the same thing, regardless of the route
    they took (JSON, XML, AASX, or a round trip through a repository server). A repository
    rewrites ``File.value`` to wherever it stores the bytes, so a server comparison passes
    ``ignore_file_values=True`` and checks the bytes themselves separately.
    """
    out: dict[str, list[str]] = {}
    for obj in store:
        if isinstance(obj, model.Submodel):
            lines: list[str] = []
            for path, element in walk(obj):
                value = getattr(element, "value", None)
                if isinstance(value, model.MultiLanguageTextType):
                    value = dict(value)
                if isinstance(element, model.File) and ignore_file_values:
                    lines.append(f"{path}|File|{element.content_type!r}|{value is not None}")
                elif isinstance(element, model.Property | model.File | model.MultiLanguageProperty):
                    lines.append(f"{path}|{type(element).__name__}|{value!r}")
                elif isinstance(element, model.Range):
                    lines.append(f"{path}|Range|{element.min!r}|{element.max!r}")
                else:
                    lines.append(f"{path}|{type(element).__name__}")
            out[obj.id] = sorted(lines)
        elif isinstance(obj, model.AssetAdministrationShell):
            out[obj.id] = sorted(r.key[0].value for r in obj.submodel)
        elif isinstance(obj, model.ConceptDescription):
            out[obj.id] = [obj.id_short or ""]
    return out
