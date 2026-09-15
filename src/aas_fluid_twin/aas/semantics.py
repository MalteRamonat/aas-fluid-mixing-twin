"""Custom semanticIds and the ConceptDescriptions that back them.

Every element that no published IDTA template covers gets an IRI under
``ids.EXTENSION_BASE`` **and** a ConceptDescription carrying an IEC 61360 data specification
(preferred name, definition, data type, unit). That is what makes the custom parts of the
twin as machine-interpretable as the standardised parts. A custom IRI without a
ConceptDescription is a test failure.

The registry is static and explicit rather than filled as a side effect of building, so the
full vocabulary of the project is readable in one place.

ECLASS: physical-quantity properties would ideally carry ECLASS IRDIs as ``valueId``. No
IRDI is used here because none could be verified against the ECLASS dictionary offline, and
a wrong IRDI is worse than a project-local IRI. Adding verified IRDIs later is a pure
addition to :func:`channel_concept`; nothing else changes.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from basyx.aas import model

from aas_fluid_twin.aas import ids
from aas_fluid_twin.benchmark.signals import Signal

__all__ = [
    "CONCEPTS",
    "IEC61360_TEMPLATE_IRI",
    "Concept",
    "channel_concept",
    "channel_semantic",
    "concept_description",
    "iter_concept_descriptions",
    "semantic",
]

IEC61360_TEMPLATE_IRI = (
    "https://admin-shell.io/DataSpecificationTemplates/DataSpecificationIEC61360/3/0"
)


@dataclass(frozen=True, slots=True)
class Concept:
    submodel: str
    element: str
    preferred_name: str
    definition: str
    data_type: model.DataTypeIEC61360
    unit: str | None = None

    @property
    def iri(self) -> str:
        return ids.extension_semantic(self.submodel, self.element)


_D = model.DataTypeIEC61360

_VOCABULARY: tuple[Concept, ...] = (
    # --- FaultScenarioCatalogue ---------------------------------------------
    Concept(
        "FaultScenarioCatalogue",
        "Submodel",
        "Fault scenario catalogue",
        "Catalogue of the labelled operational scenarios of a CPS dataset: how each was "
        "induced, what it affects, and where it occurs in the recorded runs.",
        _D.STRING,
    ),
    Concept(
        "FaultScenarioCatalogue",
        "LabelingScheme",
        "Labeling scheme",
        "How scenario labels are encoded in the dataset.",
        _D.STRING,
    ),
    Concept("FaultScenarioCatalogue", "Scenarios", "Scenarios", "Scenario definitions.", _D.STRING),
    Concept(
        "FaultScenarioCatalogue",
        "Scenario",
        "Scenario",
        "One labelled operational scenario.",
        _D.STRING,
    ),
    Concept(
        "FaultScenarioCatalogue",
        "LabelValue",
        "Label value",
        "Integer value of the scenario in the dataset's label column.",
        _D.INTEGER_COUNT,
    ),
    Concept(
        "FaultScenarioCatalogue",
        "ScenarioName",
        "Scenario name",
        "Machine name of the scenario as used in dataset file names.",
        _D.STRING,
    ),
    Concept(
        "FaultScenarioCatalogue",
        "InductionMethod",
        "Induction method",
        "How the scenario was induced physically, as stated by the plant operator.",
        _D.STRING_TRANSLATABLE,
    ),
    Concept(
        "FaultScenarioCatalogue",
        "InjectionPoints",
        "Injection points",
        "References to the plant elements at which the fault was physically induced.",
        _D.STRING,
    ),
    Concept(
        "FaultScenarioCatalogue",
        "InjectionPoint",
        "Injection point",
        "Reference to the plant element at which the fault was induced.",
        _D.STRING,
    ),
    Concept(
        "FaultScenarioCatalogue",
        "AffectedComponents",
        "Affected components",
        "References to the plant elements whose behaviour or readings the scenario affects.",
        _D.STRING,
    ),
    Concept(
        "FaultScenarioCatalogue",
        "ObservableEffect",
        "Observable effect",
        "What the scenario looks like in the recorded signals.",
        _D.STRING_TRANSLATABLE,
    ),
    Concept(
        "FaultScenarioCatalogue",
        "UseForAnomalyDetection",
        "Use for anomaly detection",
        "Whether the plant operator considers runs of this scenario suitable for "
        "anomaly-detection evaluation.",
        _D.BOOLEAN,
    ),
    Concept(
        "FaultScenarioCatalogue",
        "SubScenarios",
        "Sub-scenarios",
        "Physically distinct variants that share the parent scenario's label.",
        _D.STRING,
    ),
    Concept(
        "FaultScenarioCatalogue",
        "SubScenario",
        "Sub-scenario",
        "One physically distinct variant of a scenario.",
        _D.STRING,
    ),
    Concept(
        "FaultScenarioCatalogue",
        "SubScenarioName",
        "Sub-scenario name",
        "Machine name of the sub-scenario.",
        _D.STRING,
    ),
    Concept(
        "FaultScenarioCatalogue",
        "Runs",
        "Runs",
        "The recorded runs in which this scenario occurs.",
        _D.STRING,
    ),
    Concept(
        "FaultScenarioCatalogue",
        "FaultEvent",
        "Fault event",
        "One occurrence of the scenario within one recorded run.",
        _D.STRING,
    ),
    Concept(
        "FaultScenarioCatalogue",
        "RunId",
        "Run identifier",
        "Identifier of the recorded run (the dataset file stem).",
        _D.STRING,
    ),
    Concept(
        "FaultScenarioCatalogue",
        "RunSegment",
        "Run segment",
        "Reference to the time-series segment holding the run.",
        _D.STRING,
    ),
    Concept(
        "FaultScenarioCatalogue",
        "OnsetTime",
        "Onset time",
        "Time at which the fault starts, in seconds from the first sample of the run.",
        _D.REAL_MEASURE,
        unit="s",
    ),
    Concept(
        "FaultScenarioCatalogue",
        "EndTime",
        "End time",
        "Time at which the fault ends, in seconds from the first sample. Absent when the "
        "fault persists to the end of the run.",
        _D.REAL_MEASURE,
        unit="s",
    ),
    Concept(
        "FaultScenarioCatalogue",
        "OnsetSource",
        "Onset source",
        "Provenance of the onset time: operator_log, estimated_changepoint or unknown. "
        "Only operator_log is ground truth.",
        _D.STRING,
    ),
    Concept(
        "FaultScenarioCatalogue",
        "Usable",
        "Usable",
        "Whether the run is fit for use, as judged by the plant operator.",
        _D.BOOLEAN,
    ),
    # --- TwinLinkage --------------------------------------------------------
    Concept(
        "TwinLinkage",
        "Submodel",
        "Twin linkage",
        "Links a physical asset to its simulation twin and maps their signals.",
        _D.STRING,
    ),
    Concept(
        "TwinLinkage",
        "IsSimulatedBy",
        "Is simulated by",
        "Relationship from a physical asset to the simulation model that represents it.",
        _D.STRING,
    ),
    Concept(
        "TwinLinkage",
        "SimulatesAsset",
        "Simulates asset",
        "Relationship from a simulation model to the physical asset it represents.",
        _D.STRING,
    ),
    Concept(
        "TwinLinkage",
        "ModelFidelity",
        "Model fidelity",
        "Known deviations between the simulation model and the physical asset.",
        _D.STRING_TRANSLATABLE,
    ),
    Concept(
        "TwinLinkage",
        "SignalMappings",
        "Signal mappings",
        "Per-signal correspondence between the asset's interface and the model's variables.",
        _D.STRING,
    ),
    Concept(
        "TwinLinkage",
        "SignalMapping",
        "Signal mapping",
        "Correspondence between one interface signal and one model variable, with unit "
        "conversion.",
        _D.STRING,
    ),
    Concept("TwinLinkage", "SensorId", "Sensor identifier", "The plant tag.", _D.STRING),
    Concept(
        "TwinLinkage",
        "SimulationVariable",
        "Simulation variable",
        "Fully qualified Modelica variable name.",
        _D.STRING,
    ),
    Concept(
        "TwinLinkage",
        "UnitSensor",
        "Unit at the sensor",
        "Engineering unit of the recorded signal.",
        _D.STRING,
    ),
    Concept(
        "TwinLinkage",
        "UnitSimulation",
        "Unit in the simulation",
        "Engineering unit of the corresponding model variable.",
        _D.STRING,
    ),
    Concept(
        "TwinLinkage",
        "ConversionFactor",
        "Conversion factor",
        "Multiply the sensor value by this factor to obtain the simulation value.",
        _D.REAL_MEASURE,
    ),
    Concept(
        "TwinLinkage",
        "MappingStatus",
        "Mapping status",
        "mapped, not_in_model, or not_assigned.",
        _D.STRING,
    ),
    # --- SimulationControl --------------------------------------------------
    Concept(
        "SimulationControl",
        "Submodel",
        "Simulation control",
        "Executes and tracks runs of the simulation model.",
        _D.STRING,
    ),
    Concept(
        "SimulationControl",
        "ParameterSet",
        "Parameter set",
        "Tunable parameters of the model with default and bounds.",
        _D.STRING,
    ),
    Concept("SimulationControl", "Parameter", "Parameter", "One tunable parameter.", _D.STRING),
    Concept(
        "SimulationControl",
        "ParameterName",
        "Parameter name",
        "Fully qualified Modelica parameter name.",
        _D.STRING,
    ),
    Concept(
        "SimulationControl",
        "DefaultValue",
        "Default value",
        "Value in the published model.",
        _D.REAL_MEASURE,
    ),
    Concept(
        "SimulationControl",
        "ValueRange",
        "Value range",
        "Admissible range of the parameter.",
        _D.REAL_MEASURE,
    ),
    Concept("SimulationControl", "Unit", "Unit", "Engineering unit of the parameter.", _D.STRING),
    Concept(
        "SimulationControl",
        "FaultRole",
        "Fault role",
        "The scenario this parameter reproduces when changed from its default.",
        _D.STRING,
    ),
    Concept(
        "SimulationControl",
        "ActuatorSchedules",
        "Actuator schedules",
        "Time-tabled actuator commands that drive the open-loop model.",
        _D.STRING,
    ),
    Concept("SimulationControl", "Schedule", "Schedule", "One actuator schedule.", _D.STRING),
    Concept(
        "SimulationControl",
        "RunSimulation",
        "Run simulation",
        "Start a simulation run.",
        _D.STRING,
    ),
    Concept(
        "SimulationControl",
        "GetRunStatus",
        "Get run status",
        "Query the state of a run.",
        _D.STRING,
    ),
    Concept("SimulationControl", "Runs", "Runs", "Simulation runs executed so far.", _D.STRING),
    Concept("SimulationControl", "Run", "Run", "One executed simulation run.", _D.STRING),
    Concept(
        "SimulationControl",
        "RunId",
        "Run identifier",
        "Identifier of the simulation run.",
        _D.STRING,
    ),
    Concept("SimulationControl", "StartedAt", "Started at", "Wall-clock start.", _D.TIMESTAMP),
    Concept("SimulationControl", "FinishedAt", "Finished at", "Wall-clock end.", _D.TIMESTAMP),
    Concept(
        "SimulationControl",
        "Status",
        "Status",
        "queued, running, completed or failed.",
        _D.STRING,
    ),
    Concept(
        "SimulationControl",
        "SegmentRef",
        "Segment reference",
        "Reference to the time-series segment holding the run's results.",
        _D.STRING,
    ),
    Concept(
        "SimulationControl",
        "ParametersUsed",
        "Parameters used",
        "JSON document of the parameter values the run was executed with.",
        _D.STRING,
    ),
    # --- TechnicalData property areas ---------------------------------------
    # Physical quantities of the plant's components. Units follow the topology resource.
    Concept("TechnicalData", "Vessels", "Vessels", "Tank geometry.", _D.STRING),
    Concept("TechnicalData", "Pumps", "Pumps", "Pump characteristics.", _D.STRING),
    Concept("TechnicalData", "Valves", "Valves", "Valve ratings.", _D.STRING),
    Concept("TechnicalData", "Piping", "Piping", "Pipe segments and fittings.", _D.STRING),
    Concept("TechnicalData", "Instruments", "Instruments", "Instrument type data.", _D.STRING),
    Concept("TechnicalData", "Medium", "Medium", "Process medium.", _D.STRING),
    Concept("TechnicalData", "Vessel", "Vessel", "One tank.", _D.STRING),
    Concept("TechnicalData", "Pump", "Pump", "One pump.", _D.STRING),
    Concept("TechnicalData", "Valve", "Valve", "One valve.", _D.STRING),
    Concept("TechnicalData", "PipeSegment", "Pipe segment", "One pipe segment.", _D.STRING),
    Concept("TechnicalData", "Instrument", "Instrument", "One instrument family.", _D.STRING),
    Concept(
        "TechnicalData",
        "CrossSectionalArea",
        "Cross-sectional area",
        "Inner cross-section of the vessel.",
        _D.REAL_MEASURE,
        unit="m2",
    ),
    Concept(
        "TechnicalData",
        "Height",
        "Height",
        "Inner height of the vessel.",
        _D.REAL_MEASURE,
        unit="m",
    ),
    Concept(
        "TechnicalData",
        "NominalVolume",
        "Nominal volume",
        "Cross-section times height.",
        _D.REAL_MEASURE,
        unit="L",
    ),
    Concept(
        "TechnicalData",
        "PortDiameter",
        "Port diameter",
        "Diameter of the vessel's bottom port.",
        _D.REAL_MEASURE,
        unit="m",
    ),
    Concept(
        "TechnicalData",
        "LevelStart",
        "Initial level",
        "Level at simulation start in the published model.",
        _D.REAL_MEASURE,
        unit="m",
    ),
    Concept(
        "TechnicalData",
        "NominalSpeed",
        "Nominal speed",
        "Pump nominal rotational speed.",
        _D.REAL_MEASURE,
        unit="1/s",
    ),
    Concept(
        "TechnicalData",
        "DisplacedVolume",
        "Displaced volume",
        "Fluid volume inside the pump.",
        _D.REAL_MEASURE,
        unit="m3",
    ),
    Concept(
        "TechnicalData",
        "FlowCharacteristic",
        "Flow characteristic",
        "Quadratic head-flow characteristic through three points.",
        _D.STRING,
    ),
    Concept(
        "TechnicalData",
        "CharacteristicPoint",
        "Characteristic point",
        "One (volume flow, head) point.",
        _D.STRING,
    ),
    Concept(
        "TechnicalData",
        "VolumeFlow",
        "Volume flow",
        "Volume flow rate.",
        _D.REAL_MEASURE,
        unit="m3/s",
    ),
    Concept("TechnicalData", "Head", "Head", "Pump head.", _D.REAL_MEASURE, unit="m"),
    Concept(
        "TechnicalData",
        "NominalPressureDrop",
        "Nominal pressure drop",
        "Pressure drop at nominal mass flow, fully open.",
        _D.REAL_MEASURE,
        unit="Pa",
    ),
    Concept(
        "TechnicalData",
        "NominalMassFlow",
        "Nominal mass flow",
        "Mass flow at nominal pressure drop, fully open.",
        _D.REAL_MEASURE,
        unit="kg/s",
    ),
    Concept("TechnicalData", "ValveType", "Valve type", "Constructive type.", _D.STRING),
    Concept("TechnicalData", "Actuation", "Actuation", "How the valve is operated.", _D.STRING),
    Concept(
        "TechnicalData",
        "PipeDiameter",
        "Pipe diameter",
        "Inner diameter.",
        _D.REAL_MEASURE,
        unit="m",
    ),
    Concept(
        "TechnicalData", "PipeLength", "Pipe length", "Segment length.", _D.REAL_MEASURE, unit="m"
    ),
    Concept(
        "TechnicalData",
        "ElevationChange",
        "Elevation change",
        "Height difference from inlet to outlet.",
        _D.REAL_MEASURE,
        unit="m",
    ),
    Concept("TechnicalData", "Fittings", "Fittings", "Fitting system used.", _D.STRING),
    Concept("TechnicalData", "MediumName", "Medium name", "Process medium.", _D.STRING),
    Concept(
        "TechnicalData",
        "MediumModel",
        "Medium model",
        "Modelica medium package used in the simulation.",
        _D.STRING,
    ),
    Concept("TechnicalData", "Manufacturer", "Manufacturer", "Instrument manufacturer.", _D.STRING),
    Concept("TechnicalData", "ProductType", "Product type", "Type designation.", _D.STRING),
    Concept("TechnicalData", "OrderCode", "Order code", "Order code.", _D.STRING),
    Concept(
        "TechnicalData",
        "MeasuringSpan",
        "Measuring span",
        "Instrument measuring span.",
        _D.REAL_MEASURE,
    ),
    Concept(
        "TechnicalData",
        "MeasuringUnit",
        "Measuring unit",
        "Unit of the measuring span.",
        _D.STRING,
    ),
    Concept(
        "TechnicalData",
        "BlindZone",
        "Blind zone",
        "Ultrasonic blind zone.",
        _D.REAL_MEASURE,
        unit="mm",
    ),
    Concept("TechnicalData", "Accuracy", "Accuracy", "Datasheet accuracy statement.", _D.STRING),
    Concept(
        "TechnicalData", "AppliesTo", "Applies to", "Instrument tags of this family.", _D.STRING
    ),
    # --- qualifiers and shared properties ----------------------------------
    Concept(
        "Common",
        "DataQuality",
        "Data quality",
        "Fitness of a channel for use: good or unreliable, with the reason in the element "
        "description.",
        _D.STRING,
    ),
    Concept(
        "Common",
        "SchemaVariant",
        "Schema variant",
        "full when a run carries every channel of the corpus, reduced otherwise.",
        _D.STRING,
    ),
    Concept(
        "Common",
        "AnomalyLabel",
        "Anomaly label",
        "Scenario label of a sample. Constant per run in the published files; resolved per "
        "sample here from the operator's onset times.",
        _D.INTEGER_COUNT,
    ),
    Concept(
        "Common",
        "LiveEndpoint",
        "Live endpoint",
        "Whether the described interface endpoint is currently reachable.",
        _D.BOOLEAN,
    ),
    Concept("Common", "RunKind", "Run kind", "measured or simulated.", _D.STRING),
    Concept(
        "Common",
        "WallClockTime",
        "Wall-clock time",
        "Absolute timestamp of a sample as recorded by the data logger.",
        _D.TIMESTAMP,
    ),
    Concept(
        "Common",
        "SourceDocument",
        "Source document",
        "The benchmark file or section a value was taken from.",
        _D.STRING,
    ),
)

#: The project vocabulary, keyed by ``"<Submodel>/<Element>"``.
CONCEPTS: dict[str, Concept] = {f"{c.submodel}/{c.element}": c for c in _VOCABULARY}


def _global_ref(iri: str) -> model.ExternalReference:
    return model.ExternalReference((model.Key(model.KeyTypes.GLOBAL_REFERENCE, iri),))


def semantic(submodel: str, element: str) -> model.ExternalReference:
    """The reference to use as ``semantic_id`` for a custom element. Must be registered."""
    key = f"{submodel}/{element}"
    if key not in CONCEPTS:
        raise KeyError(f"custom semantic {key!r} is not registered in CONCEPTS")
    return _global_ref(CONCEPTS[key].iri)


def _iec61360(
    preferred_name: str,
    definition: str,
    data_type: model.DataTypeIEC61360,
    unit: str | None,
) -> model.EmbeddedDataSpecification:
    return model.EmbeddedDataSpecification(
        data_specification=_global_ref(IEC61360_TEMPLATE_IRI),
        data_specification_content=model.DataSpecificationIEC61360(
            preferred_name=model.PreferredNameTypeIEC61360({"en": preferred_name}),
            short_name=model.ShortNameTypeIEC61360({"en": preferred_name[:18]}),
            definition=model.DefinitionTypeIEC61360({"en": definition}),
            data_type=data_type,
            unit=unit,
        ),
    )


def concept_description(concept: Concept) -> model.ConceptDescription:
    return model.ConceptDescription(
        id_=concept.iri,
        id_short=f"{concept.submodel}_{concept.element}",
        display_name=model.MultiLanguageNameType({"en": concept.preferred_name}),
        description=model.MultiLanguageTextType({"en": concept.definition}),
        embedded_data_specifications=(
            _iec61360(concept.preferred_name, concept.definition, concept.data_type, concept.unit),
        ),
    )


# --- channels -----------------------------------------------------------------

_CHANNEL = "Channel"


def channel_semantic_iri(signal: Signal) -> str:
    return ids.extension_semantic(_CHANNEL, signal.channel)


def channel_semantic(signal: Signal) -> model.ExternalReference:
    """semanticId of a recorded channel: one concept per CSV column."""
    return _global_ref(channel_semantic_iri(signal))


def channel_concept(signal: Signal) -> model.ConceptDescription:
    data_type = _D.BOOLEAN if signal.is_binary else _D.REAL_MEASURE
    definition = (
        f"{signal.display_name}. Tag {signal.sensor_id}; recorded as CSV column "
        f"'{signal.channel}'."
    )
    if signal.quality_reason:
        definition += f" Quality {signal.quality.value}: {signal.quality_reason}"
    return model.ConceptDescription(
        id_=channel_semantic_iri(signal),
        id_short=signal.channel,
        display_name=model.MultiLanguageNameType({"en": signal.display_name}),
        description=model.MultiLanguageTextType({"en": definition}),
        embedded_data_specifications=(
            _iec61360(signal.display_name, definition, data_type, signal.unit),
        ),
    )


def iter_concept_descriptions() -> Iterator[model.ConceptDescription]:
    """Every ConceptDescription of the static vocabulary (channel concepts are per signal)."""
    for concept in CONCEPTS.values():
        yield concept_description(concept)
