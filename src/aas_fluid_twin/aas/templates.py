"""Access to the vendored IDTA submodel templates.

``resources/idta/*.json`` are distilled from the published template files by
``scripts/vendor_idta_templates.py``. They are the *only* source of IDTA semanticIds in the
project: builders look IRIs up by element path, and the conformance tests check emitted
submodels against the same files. A hand-typed IRI cannot drift from the standard because
there are none.

Paths use ``/`` between idShorts and ``[]`` for the anonymous children of a
``SubmodelElementList``, e.g. ``Documents/[]/DocumentVersions/[]/Title``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from typing import Any

from aas_fluid_twin import config

__all__ = ["Template", "TemplateElement", "template"]


@dataclass(frozen=True, slots=True)
class TemplateElement:
    path: str
    model_type: str
    semantic_id: str | None
    cardinality: str | None
    value_type: str | None
    semantic_id_list_element: str | None

    @property
    def mandatory(self) -> bool:
        return self.cardinality in ("One", "OneToMany")


@dataclass(frozen=True, slots=True)
class Template:
    key: str
    idta: str
    source: str
    submodel_id_short: str
    submodel_semantic_id: str
    template_id: str
    elements: Mapping[str, TemplateElement]

    def element(self, path: str) -> TemplateElement:
        try:
            return self.elements[path]
        except KeyError:
            raise KeyError(f"{self.idta}: no element at path {path!r}") from None

    def semantic(self, path: str) -> str:
        """The semanticId of the element at *path*. Raises if the template has none."""
        sem = self.element(path).semantic_id
        if sem is None:
            raise KeyError(f"{self.idta}: element {path!r} carries no semanticId")
        return sem

    def has(self, path: str) -> bool:
        return path in self.elements

    def mandatory_paths(self, under: str = "") -> tuple[str, ...]:
        prefix = f"{under}/" if under else ""
        return tuple(
            p
            for p, e in self.elements.items()
            if e.mandatory and p.startswith(prefix) and "/" not in p[len(prefix) :]
        )


@cache
def template(key: str) -> Template:
    path = config.RESOURCE_DIR / "idta" / f"{key}.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"vendored IDTA template {key!r} not found at {path}; "
            "run `python scripts/vendor_idta_templates.py`"
        )
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    elements = {
        p: TemplateElement(
            path=p,
            model_type=str(e["modelType"]),
            semantic_id=e.get("semanticId"),
            cardinality=e.get("cardinality"),
            value_type=e.get("valueType"),
            semantic_id_list_element=e.get("semanticIdListElement"),
        )
        for p, e in raw["elements"].items()
    }
    sm = raw["submodel"]
    return Template(
        key=raw["key"],
        idta=raw["idta"],
        source=raw["source"],
        submodel_id_short=str(sm["idShort"]),
        submodel_semantic_id=str(sm["semanticId"]),
        template_id=str(sm["id"]),
        elements=elements,
    )
