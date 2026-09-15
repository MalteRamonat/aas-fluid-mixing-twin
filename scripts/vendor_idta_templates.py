#!/usr/bin/env python
"""Distil the IDTA submodel templates this project uses into small vendored indexes.

The full template JSONs from ``admin-shell-io/submodel-templates`` are 30 KB – 1.6 MB each.
What the builders and the conformance tests actually need is the *structure*: for every
element, its idShort path, its model type and its semanticId. This script downloads the
pinned template files and writes that structure to ``src/aas_fluid_twin/resources/idta/``.

The vendored files are the single source of semanticIds in this project. Builders read from
them, and the conformance tests check emitted submodels against them, so a hand-typed IRI
can never drift from the published template.

Usage::

    python scripts/vendor_idta_templates.py          # refresh all
    python scripts/vendor_idta_templates.py --check  # verify vendored files are current
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aas_fluid_twin import config

REPO = "admin-shell-io/submodel-templates"
REF = "main"
RAW = f"https://raw.githubusercontent.com/{REPO}/{REF}/"

#: key -> (IDTA number, upstream path). Metamodel-V3.1 variants where published.
TEMPLATES: dict[str, tuple[str, str]] = {
    "nameplate": (
        "IDTA 02006-3-0",
        "published/Digital nameplate/3/0/1/IDTA 02006-3-0-1_Template_Digital Nameplate.json",
    ),
    "contact_information": (
        "IDTA 02002-1-0",
        "published/Contact Information/1/0/1/"
        "IDTA 02002-1-0-1_Template_ContactInformation_forAASMetamodelV3.1.json",
    ),
    "technical_data": (
        "IDTA 02003-2-0",
        "published/Technical_Data/2/0/1/"
        "IDTA 02003_2-0-1_Template_TechnicalData_forAASMetamodelV3.1.json",
    ),
    "handover_documentation": (
        "IDTA 02004-2-0",
        "published/Handover Documentation/2/0/1/"
        "IDTA 02004-2-0-1_Template_HandoverDocumentation__forAASMetamodelV3.1.json",
    ),
    "hierarchical_structures": (
        "IDTA 02011-1-1",
        "published/Hierarchical Structures enabling Bills of Material/1/1/1/"
        "IDTA 02011-1-1-1_Template_HSEBoM_forAASMetamodelV3.1.json",
    ),
    "asset_interfaces_description": (
        "IDTA 02017-1-1",
        "published/Asset Interfaces Description/1/1/"
        "IDTA 02017-1-1_Template_Asset Interfaces Description.json",
    ),
    "time_series": (
        "IDTA 02008-1-1",
        "published/Time Series Data/1/1/1/"
        "IDTA 02008-1-1-1_Template_TimeSeriesData_forAASMetamodelV3.1.json",
    ),
    "simulation_models": (
        "IDTA 02005-1-1",
        "published/Provision of Simulation Models/1/1/"
        "IDTA 02005_Template_ProvisionOfSimulationModel.json",
    ),
}

OUT_DIR = config.RESOURCE_DIR / "idta"


def _semantic_id(element: dict[str, Any]) -> str | None:
    ref = element.get("semanticId")
    if not ref:
        return None
    keys = ref.get("keys") or []
    return str(keys[0]["value"]).strip() if keys else None


def _children(element: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("submodelElements", "value", "statements", "annotations"):
        items = element.get(key)
        if isinstance(items, list) and items and isinstance(items[0], dict):
            return [i for i in items if "modelType" in i]
    return []


def _walk(element: dict[str, Any], prefix: str, out: dict[str, dict[str, Any]]) -> None:
    for child in _children(element):
        id_short = child.get("idShort")
        # Elements inside a SubmodelElementList have no idShort; index them as [].
        segment = id_short if id_short else "[]"
        path = f"{prefix}/{segment}" if prefix else segment
        entry: dict[str, Any] = {
            "modelType": child.get("modelType"),
            "semanticId": _semantic_id(child),
        }
        if child.get("modelType") == "Property" and child.get("valueType"):
            entry["valueType"] = child["valueType"]
        if child.get("modelType") == "SubmodelElementList":
            entry["typeValueListElement"] = child.get("typeValueListElement")
            sem_list = child.get("semanticIdListElement")
            if sem_list and sem_list.get("keys"):
                entry["semanticIdListElement"] = sem_list["keys"][0]["value"]
        # Cardinality is conveyed by the template's Multiplicity qualifier.
        for qualifier in child.get("qualifiers") or ():
            if qualifier.get("type") in ("Multiplicity", "SMT/Cardinality"):
                entry["cardinality"] = qualifier.get("value")
        if path in out:
            # Same idShort twice under one parent — templates do this for "one of" examples.
            # Keep the first; record that alternatives exist.
            out[path].setdefault("alternatives", 0)
            out[path]["alternatives"] += 1
            continue
        out[path] = entry
        _walk(child, path, out)


def distil(key: str, idta: str, upstream_path: str) -> dict[str, Any]:
    url = RAW + urllib.parse.quote(upstream_path)
    with urllib.request.urlopen(url, timeout=60) as response:
        environment = json.load(response)

    submodels = environment.get("submodels") or []
    if len(submodels) != 1:
        raise ValueError(
            f"{key}: expected exactly one submodel in the template, got {len(submodels)}"
        )
    submodel = submodels[0]

    elements: dict[str, dict[str, Any]] = {}
    _walk(submodel, "", elements)

    return {
        "key": key,
        "idta": idta,
        "source": f"https://github.com/{REPO}/blob/{REF}/{upstream_path}",
        "submodel": {
            "idShort": submodel.get("idShort"),
            "id": submodel.get("id"),
            "semanticId": _semantic_id(submodel),
            "kind": submodel.get("kind"),
        },
        "elements": elements,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if vendored files differ")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stale: list[str] = []
    for key, (idta, upstream) in TEMPLATES.items():
        payload = distil(key, idta, upstream)
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        target = OUT_DIR / f"{key}.json"
        if args.check:
            if not target.exists() or target.read_text(encoding="utf-8") != text:
                stale.append(key)
            continue
        target.write_text(text, encoding="utf-8")
        print(f"{idta:16s} {len(payload['elements']):4d} elements -> {target.name}")

    if args.check:
        if stale:
            print(f"stale: {stale}", file=sys.stderr)
            return 1
        print("vendored IDTA templates are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
