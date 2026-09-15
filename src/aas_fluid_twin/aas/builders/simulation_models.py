"""Provision of Simulation Models — IDTA 02005-1-1.

Describes ``ModVA_online_stable``: what it is for, what it needs to run, which files carry
it, and — the part that makes the twin usable rather than decorative — its ``Ports``: every
model variable that corresponds to a plant channel, with causality and unit.

Solver, tolerance, stop time and the MSL version are read from the model file at build time.
The FMU version is listed only when the artefact actually exists.
"""

from __future__ import annotations

from basyx.aas import model
from basyx.aas.model import datatypes

from aas_fluid_twin import config
from aas_fluid_twin.aas import ids
from aas_fluid_twin.aas.builders._common import (
    element_ref,
    ext_ref,
    file,
    mlp,
    package_path,
    prop,
    prop_typed,
    smc,
)
from aas_fluid_twin.aas.context import BuildContext
from aas_fluid_twin.aas.templates import template
from aas_fluid_twin.benchmark.signals import Role, Signal
from aas_fluid_twin.simulation.runner import TESTED_SOLVER
from aas_fluid_twin.simulation.units import sim_unit_of

__all__ = [
    "FAULTCAPABLE_ATTACHMENT_PATH",
    "FMU_ATTACHMENT_PATH",
    "MODEL_ATTACHMENT_PATH",
    "SUBMODEL_ID",
    "build_simulation_models",
    "variable_reference",
]

T = template("simulation_models")
SUBMODEL_ID = ids.submodel_id(ids.SIMULATION_TAG, T.submodel_id_short)

MODEL_ATTACHMENT_PATH = package_path("simulation", "ModVA_online_stable.mo")
FMU_ATTACHMENT_PATH = package_path("simulation", "ModVA_online_stable.fmu")
FAULTCAPABLE_ATTACHMENT_PATH = package_path("simulation", "ModVA_faultcapable.mo")

_M = "SimulationModel"
_ENV = f"{_M}/Environment"
_TOOL = f"{_ENV}/SimulationTool"
_SOLV = f"{_TOOL}/SolverAndTolerances"
_ALG = f"{_SOLV}/TestedToolSolverAlgorithm"
_MF = f"{_M}/ModelFile"
_MFV = f"{_MF}/ModelFileVersion"
_PORTS = f"{_M}/Ports"
_CONN = f"{_PORTS}/PortsConnector"
_VAR = f"{_CONN}/Variable"


def _sem(path: str) -> model.ExternalReference:
    return ext_ref(T.semantic(path))


def _variable_id_short(signal: Signal) -> str:
    return "Var_" + signal.channel


def variable_reference(signal: Signal) -> model.ModelReference[model.SubmodelElement]:
    """Model reference to the port variable of a channel — used by the twin linkage."""
    connector = "ActuatorInputs" if signal.role is Role.ACTUATOR else "MeasuredOutputs"
    return element_ref(
        SUBMODEL_ID,
        [
            (model.SubmodelElementCollection, "SimulationModel"),
            (model.SubmodelElementCollection, "Ports"),
            (model.SubmodelElementCollection, connector),
            (model.SubmodelElementCollection, _variable_id_short(signal)),
        ],
    )


def _variable(signal: Signal) -> model.SubmodelElementCollection:
    assert signal.sim_variable is not None
    unit = sim_unit_of(signal.sim_variable)
    causality = "input" if signal.role is Role.ACTUATOR else "output"
    description = (
        f"{signal.display_name}; plant channel '{signal.channel}' ({signal.unit or 'binary'})."
    )
    if signal.role is Role.ACTUATOR:
        description += " Driven through the CombiTimeTable ActuatorControl (open loop)."
    return smc(
        _variable_id_short(signal),
        _sem(_VAR),
        prop("VariableName", signal.sim_variable, _sem(f"{_VAR}/VariableName")),
        prop(
            "VariableType", "Boolean" if signal.is_binary else "Real", _sem(f"{_VAR}/VariableType")
        ),
        mlp("VariableDescription", description, _sem(f"{_VAR}/VariableDescription")),
        prop(
            "UnitList",
            unit.value,
            _sem(f"{_VAR}/UnitList"),
            description="Unit of the Modelica variable (deviation D5: the benchmark's mapping "
            "table declares bar and °C for pressure and temperature; the sensor "
            "blocks output Pa and K).",
        ),
        prop("VariableCausality", causality, _sem(f"{_VAR}/VariableCausality")),
    )


def _connector(
    id_short: str, name: str, description: str, signals: list[Signal]
) -> model.SubmodelElementCollection:
    return smc(
        id_short,
        _sem(_CONN),
        prop("PortConnectorName", name, _sem(f"{_CONN}/PortConnectorName")),
        mlp("PortConDescription", description, _sem(f"{_CONN}/PortConDescription")),
        *(_variable(s) for s in signals),
    )


def _model_file_version(
    id_short: str, version_id: str, path: str, content_type: str, notes: str
) -> model.SubmodelElementCollection:
    return smc(
        id_short,
        _sem(_MFV),
        prop("ModelVersionId", version_id, _sem(f"{_MFV}/ModelVersionId")),
        file("DigitalFile", path, content_type, _sem(f"{_MFV}/DigitalFile")),
        mlp("ModelFileReleaseNotesTxt", notes, _sem(f"{_MFV}/ModelFileReleaseNotesTxt")),
    )


def build_simulation_models(ctx: BuildContext) -> model.Submodel:
    mo = ctx.modelica
    exp = mo.experiment
    inputs = [s for s in ctx.signals if s.is_mapped_to_simulation and s.role is Role.ACTUATOR]
    outputs = [s for s in ctx.signals if s.is_mapped_to_simulation and s.role is Role.SENSOR]

    versions: list[model.SubmodelElement | None] = [
        _model_file_version(
            "ModelFileVersion_mo",
            "mo-upstream",
            MODEL_ATTACHMENT_PATH,
            "text/x-modelica",
            "Byte-identical copy of simulation/ModVA_online_stable.mo from the benchmark. Known "
            "issues carried by this version: D3 (pipe component names contradict the wiring) "
            "and D4 (TI261/TI262 swapped) — see docs/benchmark-deviations.md.",
        ),
    ]
    if config.FAULTCAPABLE_MODEL_FILE.is_file():
        versions.append(
            _model_file_version(
                "ModelFileVersion_faultcapable",
                "mo-faultcapable",
                FAULTCAPABLE_ATTACHMENT_PATH,
                "text/x-modelica",
                "Fault-capable model version, derived from the upstream model by "
                "scripts/derive_faultcapable.py: adds the hardware the recorded faults were "
                "induced with — the leak valve V211 with its drain X203 and the B201 return "
                "route, the V210 crossover, and V212 as a settable throttle — and corrects the "
                "TI261/TI262 placement (D4). Every handle defaults to the nominal plant, so "
                "with defaults it is hydraulically the upstream model. This is the version the "
                "RunSimulation operation's fault parameters address. See "
                "docs/benchmark-deviations.md, D8.",
            )
        )
    fmu = config.ARTIFACT_DIR / "ModVA_online_stable.fmu"
    if fmu.is_file():
        versions.append(
            _model_file_version(
                "ModelFileVersion_fmu",
                "fmu-2.0-me-cs",
                FMU_ATTACHMENT_PATH,
                "application/x-fmu-sharedlibrary",
                "FMI 2.0 Model-Exchange + Co-Simulation export of the upstream model, produced "
                "by scripts/export_fmu.py with OpenModelica 1.22.1 (linux64 binary). Provided "
                "as the standard's model artefact; the twin's runner drives OpenModelica "
                "directly because this export does not run under FMPy (deviation D7).",
            )
        )

    simulation_model = smc(
        "SimulationModel",
        _sem(_M),
        mlp(
            "Summary",
            "Lumped-parameter hydraulic model of the ModVA plant: four tanks, two centrifugal "
            "pumps, seven valves, an explicit pipe and tee network, water as medium. Open-loop: "
            "all actuators are driven by a time table; the PLC sequence is not modelled.",
            _sem(f"{_M}/Summary"),
        ),
        smc(
            "SimPurpose",
            _sem(f"{_M}/SimPurpose"),
            prop(
                "PosSimPurpose_1",
                "Generation of nominal and faulty operational data",
                _sem(f"{_M}/SimPurpose/PosSimPurpose"),
            ),
            prop(
                "PosSimPurpose_2",
                "Hydraulic behaviour study of the dosing and mixing cycle",
                _sem(f"{_M}/SimPurpose/PosSimPurpose"),
            ),
            prop(
                "PosSimPurpose_3",
                "Reference behaviour for anomaly-detection benchmarking",
                _sem(f"{_M}/SimPurpose/PosSimPurpose"),
            ),
            prop(
                "NegSimPurpose_1",
                "Mixing quality or stirring studies: R201 is not modelled",
                _sem(f"{_M}/SimPurpose/NegSimPurpose"),
            ),
            prop(
                "NegSimPurpose_2",
                "Thermal process design: no heat exchange is modelled",
                _sem(f"{_M}/SimPurpose/NegSimPurpose"),
            ),
            prop(
                "NegSimPurpose_3",
                "Closed-loop control studies: the PLC sequence is not modelled",
                _sem(f"{_M}/SimPurpose/NegSimPurpose"),
            ),
        ),
        prop("TypeOfModel", "Modelica (acausal, DAE)", _sem(f"{_M}/TypeOfModel")),
        prop(
            "ScopeOfModel",
            "System level, one-dimensional fluid network",
            _sem(f"{_M}/ScopeOfModel"),
        ),
        prop("LicenseModel", "See LICENSE of the benchmark repository", _sem(f"{_M}/LicenseModel")),
        prop(
            "EngineeringDomain",
            "Fluid mechanics / process hydraulics",
            _sem(f"{_M}/EngineeringDomain"),
        ),
        smc(
            "Environment",
            _sem(_ENV),
            prop(
                "OperatingSystem",
                "Any OpenModelica platform; this project runs it in "
                "openmodelica/openmodelica:v1.27.0-ompython (Linux) and executes the FMU on "
                "any FMI 2.0 host",
                _sem(f"{_ENV}/OperatingSystem"),
            ),
            prop(
                "ToolEnvironment",
                "OpenModelica (benchmark: v1.22.1; this project: v1.27.0)",
                _sem(f"{_ENV}/ToolEnvironment"),
            ),
            mlp(
                "DependencyEnvironment",
                f"Modelica Standard Library {mo.msl_version or 'unknown'}",
                _sem(f"{_ENV}/DependencyEnvironment"),
            ),
            smc(
                "SimulationTool",
                _sem(_TOOL),
                prop("SimToolName", "OpenModelica", _sem(f"{_TOOL}/SimToolName")),
                prop("Compiler", "OpenModelica Compiler (omc)", _sem(f"{_TOOL}/Compiler")),
                smc(
                    "SolverAndTolerances",
                    _sem(_SOLV),
                    prop("StepSizeControlNeeded", True, _sem(f"{_SOLV}/StepSizeControlNeeded")),
                    prop(
                        "StiffSolverNeeded",
                        True,
                        _sem(f"{_SOLV}/StiffSolverNeeded"),
                        description="The model annotation names CVODE, which fails at t ~ 0.26 s "
                        "on this model (OpenModelica 1.22.1 and 1.27.0); IDA is what produced "
                        "the published results (deviation D6).",
                    ),
                    prop("SolverIncluded", False, _sem(f"{_SOLV}/SolverIncluded")),
                    smc(
                        "TestedToolSolverAlgorithm",
                        _sem(_ALG),
                        prop(
                            "SolverAlgorithm",
                            TESTED_SOLVER,
                            _sem(f"{_ALG}/SolverAlgorithm"),
                            description=f"The annotation says {exp.solver or 'cvode'}; see "
                            "StiffSolverNeeded.",
                        ),
                        prop(
                            "ToolSolverFurtherDescription",
                            f"experiment(StartTime={exp.start_time:g}, StopTime={exp.stop_time:g}, "
                            f"Tolerance={exp.tolerance:g}, Interval={exp.interval:g}); "
                            "flags --matchingAlgorithm=PFPlusExt "
                            "--indexReductionMethod=dynamicStateSelection. Verified: "
                            "OpenModelica 1.22.1 + IDA + the embedded actuator table "
                            "reproduces the published result to 5e-4 relative.",
                            _sem(f"{_ALG}/ToolSolverFurtherDescription"),
                        ),
                        prop("Tolerance", exp.tolerance, _sem(f"{_ALG}/Tolerance")),
                    ),
                ),
            ),
        ),
        file(
            "RefSimDocumentation",
            f"https://doi.org/{config.BENCHMARK_DOI}",
            "text/html",
            _sem(f"{_M}/RefSimDocumentation"),
            description="The benchmark paper describes the model and its validation.",
        ),
        smc(
            "ModelFile",
            _sem(_MF),
            prop(
                "ModelFileType",
                "Modelica source (.mo); FMI 2.0 Co-Simulation (.fmu)",
                _sem(f"{_MF}/ModelFileType"),
            ),
            *versions,
        ),
        prop(
            "ParamMethod",
            "Parameters are set through the simulation API before the build "
            "(OMPython setParameters), or as FMU start values. Actuator schedules are written "
            "into ActuatorControl.table[i,j] with the column order "
            "[time, V201, V202, V203, V206, V205, V204, V209, P201, P202] (deviation D1).",
            _sem(f"{_M}/ParamMethod"),
        ),
        prop(
            "InitStateMethod",
            "Tank level_start (tank_B20x.level_start) and pipe p_b_start / m_flow_start "
            "parameters, per the Simulation_initialization_parameters column of the mapping "
            "table.",
            _sem(f"{_M}/InitStateMethod"),
        ),
        prop_typed(
            "DefaultSimTime",
            datatypes.Float,
            exp.stop_time - exp.start_time,
            _sem(f"{_M}/DefaultSimTime"),
            description="Seconds; matches the 600 s runs.",
        ),
        smc(
            "SimModManufacturerInformation",
            _sem(f"{_M}/SimModManufacturerInformation"),
            prop(
                "Company",
                "Authors of the fluid mixing benchmark (Ramonat et al.)",
                _sem(f"{_M}/SimModManufacturerInformation/Company"),
            ),
            prop("Language", "en", _sem(f"{_M}/SimModManufacturerInformation/Language")),
        ),
        smc(
            "Ports",
            _sem(_PORTS),
            _connector(
                "ActuatorInputs",
                "ActuatorControl",
                "Open-loop actuator commands, one table column per actuator.",
                inputs,
            ),
            _connector(
                "MeasuredOutputs",
                "Sensors",
                "Model variables corresponding to the plant's recorded channels.",
                outputs,
            ),
        ),
    )

    return model.Submodel(
        id_=SUBMODEL_ID,
        id_short=T.submodel_id_short,
        semantic_id=ext_ref(T.submodel_semantic_id),
        administration=model.AdministrativeInformation(
            version="1", revision="0", template_id=T.template_id
        ),
        submodel_element=[simulation_model],
        description=model.MultiLanguageTextType(
            {
                "en": f"{mo.name}: {len(inputs)} actuator inputs, {len(outputs)} measured outputs; "
                f"{len(ctx.signals) - len(inputs) - len(outputs)} plant channels have no "
                "counterpart in the model."
            }
        ),
    )
