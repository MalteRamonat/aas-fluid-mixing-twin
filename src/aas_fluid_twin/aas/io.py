"""Serialise a built environment to JSON, XML and AASX, and read it back.

JSON and XML carry the environment alone. The AASX package additionally carries every
attachment the submodels refer to — dataset CSVs, documents, the Modelica source, the
reference simulation result — so the package is self-contained: an ``ExternalSegment`` in
the package resolves inside the package.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from basyx.aas import model
from basyx.aas.adapter import aasx
from basyx.aas.adapter import json as aas_json
from basyx.aas.adapter import xml as aas_xml
from pyecma376_2 import OPCCoreProperties

from aas_fluid_twin import config
from aas_fluid_twin.aas.environment import BuiltEnvironment

__all__ = [
    "read_aasx",
    "read_json",
    "read_xml",
    "write_aasx",
    "write_json",
    "write_xml",
]


def write_json(env: BuiltEnvironment, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        aas_json.write_aas_json_file(handle, env.store, indent=2)
    return path


def write_xml(env: BuiltEnvironment, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        aas_xml.write_aas_xml_file(handle, env.store)
    return path


def write_aasx(env: BuiltEnvironment, path: Path) -> Path:
    """Write an AASX package with every shell, submodel, concept and attachment.

    The package is always complete. An AASX whose ``File`` elements point at parts that are
    not in the package cannot be read back by the reference SDK, so a missing attachment is an
    error here, not a warning. JSON and XML are the formats to use without the files.
    """
    missing = [a.package_path for a in env.attachments if not a.exists]
    if missing:
        raise FileNotFoundError(
            f"{len(missing)} attachment(s) referenced by the environment are not on disk, "
            f"e.g. {missing[0]}. Run `python scripts/fetch_benchmark.py`."
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    files = aasx.DictSupplementaryFileContainer()
    for attachment in env.attachments:
        with attachment.source.open("rb") as handle:
            files.add_file(attachment.package_path, handle, attachment.content_type)

    # The AAS part is JSON, not XML: the Python SDK writes metamodel-3.1 XML, and the aas4j XML
    # deserializer behind Eclipse BaSyx (2.0.0-milestone-15) fails on AnnotatedRelationshipElement
    # annotations in that form. The JSON path deserialises the whole environment cleanly.
    with aasx.AASXWriter(path, failsafe=False) as writer:
        writer.write_all_aas_objects("/aasx/data.json", env.store, files, write_json=True)
        properties = OPCCoreProperties()
        properties.created = dt.datetime.now(dt.UTC)
        properties.creator = "aas-fluid-twin"
        properties.title = "ModVA fluid mixing plant — AAS environment"
        properties.description = (
            f"Plant, simulation twin and {len(env.shells) - 2} component shells built from the "
            f"fluid mixing benchmark (DOI {config.BENCHMARK_DOI})."
        )
        writer.write_core_properties(properties)
    return path


def read_json(path: Path) -> model.DictIdentifiableStore[model.Identifiable]:
    with path.open("r", encoding="utf-8") as handle:
        return aas_json.read_aas_json_file(handle, failsafe=False)


def read_xml(path: Path) -> model.DictIdentifiableStore[model.Identifiable]:
    with path.open("rb") as handle:
        return aas_xml.read_aas_xml_file(handle, failsafe=False)


def read_aasx(
    path: Path,
) -> tuple[model.DictIdentifiableStore[model.Identifiable], aasx.DictSupplementaryFileContainer]:
    store = model.DictIdentifiableStore[model.Identifiable]()
    files = aasx.DictSupplementaryFileContainer()
    with aasx.AASXReader(path) as reader:
        reader.read_into(store, files)
    return store, files
