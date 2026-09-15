"""Identifier scheme for every AAS, asset, submodel and concept in the project.

All identifiers are IRIs under one project namespace. The plant has no existing asset-ID
scheme (open item O7, resolved), so a project-local one is used. The base is a single
constant; changing it changes every identifier consistently.

Plant tags (``B201``, ``P201``, ``V204`` …) are the plant's own designations from the
signal dictionary and the P&ID, so every identifier stays traceable to the drawing.
"""

from __future__ import annotations

from typing import Final

BASE: Final[str] = "https://ramonat.dev/modva/"

PLANT_TAG: Final[str] = "ModVA"
SIMULATION_TAG: Final[str] = "ModVA_online_stable"
INSTANCE: Final[str] = "001"

# --- assets and shells -----------------------------------------------------


def asset_id(kind: str, tag: str, instance: str = INSTANCE) -> str:
    return f"{BASE}asset/{kind}/{tag}/{instance}"


def aas_id(kind: str, tag: str, instance: str = INSTANCE) -> str:
    return f"{BASE}aas/{kind}/{tag}/{instance}"


def submodel_id(tag: str, id_short: str, instance: str = INSTANCE) -> str:
    return f"{BASE}sm/{tag}/{id_short}/{instance}"


PLANT_ASSET_ID: Final[str] = asset_id("Plant", PLANT_TAG)
PLANT_AAS_ID: Final[str] = aas_id("Plant", PLANT_TAG)

SIMULATION_ASSET_ID: Final[str] = asset_id("SimulationTwin", SIMULATION_TAG)
SIMULATION_AAS_ID: Final[str] = aas_id("SimulationTwin", SIMULATION_TAG)


def component_asset_id(tag: str) -> str:
    return asset_id("Component", tag)


def component_aas_id(tag: str) -> str:
    return aas_id("Component", tag)


# --- semantics -------------------------------------------------------------

#: Custom semanticIds (elements no published IDTA template covers) live here.
EXTENSION_BASE: Final[str] = f"{BASE}idta-ext/"
#: ConceptDescriptions backing those custom semanticIds.
CONCEPT_BASE: Final[str] = f"{BASE}cd/"


def extension_semantic(submodel: str, element: str, version: str = "1/0") -> str:
    return f"{EXTENSION_BASE}{submodel}/{element}/{version}"


def concept_id(name: str, version: str = "1/0") -> str:
    return f"{CONCEPT_BASE}{name}/{version}"


# --- external services referenced from the AAS -----------------------------

#: Where the LinkedSegment endpoint lives. Overridable so the same environment can be built
#: for a local run and for the Docker network.
DEFAULT_TIMESERIES_ENDPOINT: Final[str] = "http://localhost:8000/api/timeseries"
DEFAULT_SIM_RUNNER_ENDPOINT: Final[str] = "http://sim-runner:8000/invoke"

#: The plant's OPC UA server is no longer reachable (open item O8). The interface is still
#: described — the NodeIds are documented in the signal dictionary — but marked not-live.
OPCUA_ENDPOINT_PLACEHOLDER: Final[str] = "opc.tcp://modva-plc.invalid:4840"
