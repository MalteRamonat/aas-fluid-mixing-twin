"""Handover Documentation — IDTA 02004-2-0 (VDI 2770 structure).

One ``Document`` per artefact under ``documents/`` in the benchmark, classified per
VDI 2770 and linked to the BoM entities it documents. The digital files are attached to the
AASX package (or uploaded to the repository) under ``/aasx/documents/``; the benchmark paper
is referenced by DOI as an external document.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from basyx.aas import model
from basyx.aas.model import datatypes

from aas_fluid_twin import config
from aas_fluid_twin.aas import ids
from aas_fluid_twin.aas.builders._common import (
    ext_ref,
    file,
    mlp,
    package_path,
    prop,
    prop_typed,
    ref_element,
    smc,
    sml,
)
from aas_fluid_twin.aas.builders.hierarchical_structures import bom_reference
from aas_fluid_twin.aas.context import BuildContext
from aas_fluid_twin.aas.templates import template

__all__ = ["DOCUMENTS", "Document", "attachment_path", "build_handover_documentation"]

T = template("handover_documentation")


def _sem(path: str) -> model.ExternalReference:
    return ext_ref(T.semantic(path))


_DOC = "Documents/[]"
_VER = f"{_DOC}/DocumentVersions/[]"


@dataclass(frozen=True, slots=True)
class Document:
    key: str
    title: str
    relative_path: str | None
    """Path under the benchmark's ``documents/`` directory, or ``None`` for external."""
    vdi_class_id: str
    vdi_class_name: str
    language: str
    content_type: str
    documents: tuple[str, ...] = ()
    """Component tags this document describes (become ``DocumentedEntities``)."""
    external_url: str | None = None
    organization: str = "unknown"

    @property
    def is_external(self) -> bool:
        return self.relative_path is None


_PE = "Process_Equipment"

#: Every artefact in ``[BM]/documents/`` plus the paper. Titles are the filenames' meaning,
#: classes follow VDI 2770 Part 1, languages were read from the documents themselves.
DOCUMENTS: tuple[Document, ...] = (
    Document(
        "pid",
        "Piping and instrumentation diagram",
        "PID-Diagram.pdf",
        "02-02",
        "Drawings, plans",
        "en",
        "application/pdf",
        documents=(
            "B201",
            "B202",
            "B203",
            "B204",
            "P201",
            "P202",
            "R201",
            "V201",
            "V202",
            "V203",
            "V204",
            "V205",
            "V206",
            "V207",
            "V208",
            "V209",
            "V210",
            "V211",
        ),
    ),
    Document(
        "plc_program",
        "PLC program Anlagensteuerung (PLCopen XML export)",
        "PLC_Code/Application.Anlagensteuerung.xml",
        "02-01",
        "Technical specification",
        "de",
        "application/xml",
        documents=("PLC",),
        organization="WAGO e!COCKPIT export",
    ),
    Document(
        "plc_manual_1",
        "Controller manual, part 1",
        f"{_PE}/PLC/d0750xxxx-xxxxxxxx-0de.pdf",
        "03-02",
        "Operation",
        "de",
        "application/pdf",
        documents=("PLC",),
        organization="WAGO",
    ),
    Document(
        "plc_manual_2",
        "Controller manual, part 2",
        f"{_PE}/PLC/m075xxxxx-xxxxxxxx-0de.pdf",
        "03-02",
        "Operation",
        "de",
        "application/pdf",
        documents=("PLC",),
        organization="WAGO",
    ),
    Document(
        "pumps",
        "Instruction manual, circulating pumps CM10P7-1 / CM30P7-1",
        f"{_PE}/Pumps/P201 + P202 Pumps.pdf",
        "03-02",
        "Operation",
        "en",
        "application/pdf",
        documents=("P201", "P202"),
    ),
    Document(
        "flow_sensor",
        "Datasheet, magnetic-inductive flow sensor SM6000",
        f"{_PE}/Sensors/Flow_Sensor.pdf",
        "02-01",
        "Technical specification",
        "de",
        "application/pdf",
        documents=("P201", "P202"),
        organization="ifm electronic",
    ),
    Document(
        "level_sensor",
        "Datasheet, ultrasonic sensor UC1000-18GS-IUEP-IO-V15",
        f"{_PE}/Sensors/Level_Sensor.pdf",
        "02-01",
        "Technical specification",
        "de",
        "application/pdf",
        documents=("B201", "B202", "B203", "B204"),
        organization="Pepperl+Fuchs",
    ),
    Document(
        "pressure_sensor",
        "Datasheet, pressure transmitter 26.600 G",
        f"{_PE}/Sensors/Pressure_Sensor.pdf",
        "02-01",
        "Technical specification",
        "de",
        "application/pdf",
        documents=("B201", "B202", "B203", "B204"),
        organization="BD Sensors",
    ),
    Document(
        "temperature_sensor",
        "Datasheet, temperature sensor TM4411",
        f"{_PE}/Sensors/Temperature_Sensor.pdf",
        "02-01",
        "Technical specification",
        "en",
        "application/pdf",
        documents=("P201", "B204"),
        organization="ifm electronic",
    ),
    Document(
        "valves_gate",
        "Catalogue, NAMUR pilot solenoid valves NVF3 (V201-V203 actuation)",
        f"{_PE}/Valves/V201_V202_V203.PDF",
        "02-01",
        "Technical specification",
        "de",
        "application/pdf",
        documents=("V201", "V202", "V203"),
        organization="Festo",
    ),
    Document(
        "valves_pinch",
        "Operating instructions, pinch valve VZQA-C-M22U",
        f"{_PE}/Valves/V204_V205_V206.pdf",
        "03-02",
        "Operation",
        "de",
        "application/pdf",
        documents=("V204", "V205", "V206"),
        organization="Festo",
    ),
    Document(
        "valve_solenoid",
        "Datasheet, solenoid valve type 6013",
        f"{_PE}/Valves/V209.pdf",
        "02-01",
        "Technical specification",
        "de",
        "application/pdf",
        documents=("V209",),
        organization="Bürkert",
    ),
    Document(
        "piping_elbow",
        "Datasheet, Speedfit equal elbow",
        f"{_PE}/Piping/JG Speedfit Equal Elbow Data Sheet.pdf",
        "02-01",
        "Technical specification",
        "en",
        "application/pdf",
        organization="John Guest",
    ),
    Document(
        "piping_straight",
        "Datasheet, Speedfit equal straight connector",
        f"{_PE}/Piping/JG Speedfit Equal Straight Connector Data Sheet.pdf",
        "02-01",
        "Technical specification",
        "en",
        "application/pdf",
        organization="John Guest",
    ),
    Document(
        "piping_tee",
        "Datasheet, Speedfit equal tee",
        f"{_PE}/Piping/JG Speedfit Equal Tee Data Sheet.pdf",
        "02-01",
        "Technical specification",
        "en",
        "application/pdf",
        organization="John Guest",
    ),
    Document(
        "piping_specs",
        "Speedfit technical specifications guide",
        f"{_PE}/Piping/JG Speedfit Technical Specs Guide_0322.pdf",
        "02-01",
        "Technical specification",
        "en",
        "application/pdf",
        organization="John Guest",
    ),
    Document(
        "piping_pex",
        "Datasheet, Speedfit white PEX barrier pipe",
        f"{_PE}/Piping/JG Speedfit White PEX Barrier Pipe Length Data Sheet.pdf",
        "02-01",
        "Technical specification",
        "en",
        "application/pdf",
        organization="John Guest",
    ),
    Document(
        "piping_connectors",
        "Catalogue, John Guest push-fit connectors",
        f"{_PE}/Piping/JohnGuest-Steckverbinder.pdf",
        "02-01",
        "Technical specification",
        "de",
        "application/pdf",
        organization="John Guest",
    ),
    Document(
        "paper",
        "A Fluid Mixing Benchmark for Anomaly Detection in CPS with Real & Simulated Data",
        None,
        "01-01",
        "Identification",
        "en",
        "text/html",
        external_url=f"https://doi.org/{config.BENCHMARK_DOI}",
        organization="IEEE Access",
    ),
)


def attachment_path(document: Document) -> str:
    """Where the file lives inside the AASX package / repository attachment store."""
    assert document.relative_path is not None
    return package_path("documents", document.relative_path.rsplit("/", 1)[-1])


def _document(ctx: BuildContext, doc: Document) -> model.SubmodelElementCollection:
    if doc.is_external:
        digital = file(
            "ExternalDocument",
            str(doc.external_url),
            doc.content_type,
            _sem(f"{_VER}/DigitalFiles/[]"),
            description="External document, referenced by DOI.",
        )
    else:
        digital = file(
            "DigitalFile",
            attachment_path(doc),
            doc.content_type,
            _sem(f"{_VER}/DigitalFiles/[]"),
            description=f"Benchmark path: documents/{doc.relative_path}",
        )

    version = smc(
        "Version",
        _sem(_VER),
        sml(
            "Language",
            model.Property,
            _sem(f"{_VER}/Language"),
            [prop("Language", doc.language, _sem(f"{_VER}/Language/[]"))],
            semantic_id_list_element=_sem(f"{_VER}/Language/[]"),
        ),
        prop("Version", "1", _sem(f"{_VER}/Version")),
        mlp("Title", doc.title, _sem(f"{_VER}/Title")),
        mlp("Description", doc.title, _sem(f"{_VER}/Description")),
        prop_typed("StatusSetDate", datatypes.Date, date.today(), _sem(f"{_VER}/StatusSetDate")),
        prop("StatusValue", "Released", _sem(f"{_VER}/StatusValue")),
        prop("OrganizationShortName", doc.organization, _sem(f"{_VER}/OrganizationShortName")),
        prop(
            "OrganizationOfficialName", doc.organization, _sem(f"{_VER}/OrganizationOfficialName")
        ),
        sml(
            "DigitalFiles",
            model.File,
            _sem(f"{_VER}/DigitalFiles"),
            [digital],
            semantic_id_list_element=_sem(f"{_VER}/DigitalFiles/[]"),
        ),
    )

    documented = (
        sml(
            "DocumentedEntities",
            model.ReferenceElement,
            _sem(f"{_DOC}/DocumentedEntities"),
            [
                ref_element(tag, bom_reference(ctx, tag), _sem(f"{_DOC}/DocumentedEntities/[]"))
                for tag in doc.documents
            ],
            semantic_id_list_element=_sem(f"{_DOC}/DocumentedEntities/[]"),
        )
        if doc.documents
        else None
    )

    return smc(
        doc.key,
        _sem(_DOC),
        sml(
            "DocumentIds",
            model.SubmodelElementCollection,
            _sem(f"{_DOC}/DocumentIds"),
            [
                smc(
                    "Id",
                    _sem(f"{_DOC}/DocumentIds/[]"),
                    prop(
                        "DocumentDomainId",
                        "fluid-mixing-anomaly-benchmark",
                        _sem(f"{_DOC}/DocumentIds/[]/DocumentDomainId"),
                    ),
                    prop(
                        "DocumentIdentifier",
                        doc.relative_path or f"doi:{config.BENCHMARK_DOI}",
                        _sem(f"{_DOC}/DocumentIds/[]/DocumentIdentifier"),
                    ),
                    prop(
                        "DocumentIsPrimary", True, _sem(f"{_DOC}/DocumentIds/[]/DocumentIsPrimary")
                    ),
                )
            ],
            semantic_id_list_element=_sem(f"{_DOC}/DocumentIds/[]"),
        ),
        sml(
            "DocumentClassifications",
            model.SubmodelElementCollection,
            _sem(f"{_DOC}/DocumentClassifications"),
            [
                smc(
                    "Classification",
                    _sem(f"{_DOC}/DocumentClassifications/[]"),
                    prop(
                        "ClassId",
                        doc.vdi_class_id,
                        _sem(f"{_DOC}/DocumentClassifications/[]/ClassId"),
                    ),
                    mlp(
                        "ClassName",
                        doc.vdi_class_name,
                        _sem(f"{_DOC}/DocumentClassifications/[]/ClassName"),
                    ),
                    prop(
                        "ClassificationSystem",
                        "VDI2770 Blatt 1:2020-04",
                        _sem(f"{_DOC}/DocumentClassifications/[]/ClassificationSystem"),
                    ),
                )
            ],
            semantic_id_list_element=_sem(f"{_DOC}/DocumentClassifications/[]"),
        ),
        sml(
            "DocumentVersions",
            model.SubmodelElementCollection,
            _sem(f"{_DOC}/DocumentVersions"),
            [version],
            semantic_id_list_element=_sem(_VER),
        ),
        documented,
    )


def iter_attachments(ctx: BuildContext) -> Iterable[tuple[str, object, str]]:
    """(package path, source file, content type) for every document with a file."""
    for doc in DOCUMENTS:
        if doc.relative_path is None:
            continue
        source = ctx.benchmark_dir / "documents" / doc.relative_path
        yield attachment_path(doc), source, doc.content_type


def build_handover_documentation(ctx: BuildContext) -> model.Submodel:
    return model.Submodel(
        id_=ids.submodel_id(ids.PLANT_TAG, T.submodel_id_short),
        id_short=T.submodel_id_short,
        semantic_id=ext_ref(T.submodel_semantic_id),
        administration=model.AdministrativeInformation(
            version="1", revision="0", template_id=T.template_id
        ),
        submodel_element=[
            sml(
                "Documents",
                model.SubmodelElementCollection,
                _sem("Documents"),
                [_document(ctx, d) for d in DOCUMENTS],
                semantic_id_list_element=_sem(_DOC),
            ),
        ],
    )
