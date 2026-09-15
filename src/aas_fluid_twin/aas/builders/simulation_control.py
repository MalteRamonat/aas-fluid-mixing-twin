"""SimulationControl — custom submodel (design §5.3).

IDTA 02005 describes a simulation model; it offers no way to *run* one. This submodel adds
the tunable parameter set, the actuator schedules the open-loop model is driven with, two
``Operation`` elements, and the log of executed runs.

The ``RunSimulation`` operation carries BaSyx's ``invocationDelegation`` qualifier, so an
invocation on the AAS server is forwarded to the simulation runner: that is the AAS-native
execution path. The parameter set is grounded in the model — every default is read from the
``.mo`` file — and the fault handles map one-to-one onto the operator's injection points.
"""

from __future__ import annotations

from collections.abc import Iterable

from basyx.aas import model
from basyx.aas.model import datatypes

from aas_fluid_twin.aas import ids
from aas_fluid_twin.aas.builders._common import (
    file,
    mlp,
    package_path,
    prop,
    prop_typed,
    qualifier,
    range_,
    smc,
)
from aas_fluid_twin.aas.context import BuildContext
from aas_fluid_twin.aas.semantics import semantic
from aas_fluid_twin.simulation.runner import TESTED_SOLVER

__all__ = ["SCHEDULE_ATTACHMENT_PATH", "SUBMODEL_ID", "build_simulation_control"]

_S = "SimulationControl"
SUBMODEL_ID = ids.submodel_id(ids.SIMULATION_TAG, _S)
SCHEDULE_ATTACHMENT_PATH = package_path(
    "simulation", "ActuatorControlMatrix_2024-12-06-16-06-17.csv"
)

#: The model's table column order (deviation D1). Schedules are expressed by actuator name;
#: this is the only place the positional layout is spelled out.
MODELICA_TABLE_COLUMNS: tuple[str, ...] = (
    "time",
    "V201",
    "V202",
    "V203",
    "V206",
    "V205",
    "V204",
    "V209",
    "P201",
    "P202",
)


def _sem(element: str) -> model.ExternalReference:
    return semantic(_S, element)


def _parameter(
    id_short: str,
    name: str,
    default: float | bool,
    unit: str,
    minimum: float | None,
    maximum: float | None,
    description: str,
    fault_role: str | None = None,
) -> model.SubmodelElementCollection:
    return smc(
        id_short,
        _sem("Parameter"),
        prop("ParameterName", name, _sem("ParameterName")),
        prop_typed(
            "DefaultValue",
            datatypes.Boolean if isinstance(default, bool) else datatypes.Double,
            default,
            _sem("DefaultValue"),
        ),
        range_("ValueRange", minimum, maximum, _sem("ValueRange")) if minimum is not None else None,
        prop("Unit", unit, _sem("Unit")),
        prop("FaultRole", fault_role, _sem("FaultRole")) if fault_role else None,
        description=description,
    )


def _model_parameters(ctx: BuildContext) -> Iterable[model.SubmodelElementCollection]:
    mo = ctx.modelica
    for tank in ("B201", "B202", "B203", "B204"):
        decl = mo.declarations[f"tank_{tank}"]
        height = decl.modifiers["height"]
        yield _parameter(
            f"tank_{tank}_level_start",
            f"tank_{tank}.level_start",
            decl.modifiers["level_start"],
            "m",
            0.0,
            height,
            f"Initial level of {tank}. Upper bound is the tank height.",
        )
    for name, value in mo.parameters.items():
        is_flow = "V_flow" in name
        yield _parameter(
            name,
            name,
            value,
            "m3/s" if is_flow else "m",
            value * 0.5,
            value * 1.5,
            "Pump characteristic point from the model's parameter block; the model header "
            "gives plausible ranges in comments.",
        )


def _fault_handles(ctx: BuildContext) -> Iterable[model.SubmodelElementCollection]:
    """The four handles of the fault-capable model version (deviation D8).

    ``ParameterName`` is the Modelica parameter the simulation runner sets, verbatim — these
    exist only in ``ModVA_faultcapable``, and a run against the upstream version is refused
    rather than silently ignored.
    """
    v207 = ctx.modelica.declarations["V207"]
    yield _parameter(
        "V212_opening",
        "V212_opening",
        1.0,
        "1",
        0.0,
        1.0,
        "Clogging handle. The upstream model's V207 sits exactly where the physical throttle "
        "V212 was installed (B204 -> P202) and is pinned to 1 there "
        f"(dp_nominal = {v207.modifiers.get('dp_nominal'):g} Pa); the fault-capable version "
        "renames it V212 and makes its opening a parameter. Below 1 reproduces clogging.",
        fault_role="clogging",
    )
    yield _parameter(
        "V211_opening",
        "V211_opening",
        0.0,
        "1",
        0.0,
        1.0,
        "Leakage handle. Requires the fault-capable model version (adds Tee4, V211 and the "
        "boundary X203). Above 0 reproduces leakage.",
        fault_role="leakage",
    )
    yield _parameter(
        "V211_return_to_B201",
        "V211_return_to_B201",
        False,
        "boolean",
        None,
        None,
        "Reconfiguration A. Routes the V211 discharge back into B201 instead of X203 "
        "(fault-capable model version).",
        fault_role="reconfiguration/leak_recirculated_to_B201",
    )
    yield _parameter(
        "V210_opening",
        "V210_opening",
        0.0,
        "1",
        0.0,
        1.0,
        "Reconfiguration B. Requires the fault-capable model version (adds Tee3, Tee5 and "
        "V210). Above 0 opens the hydrostatic crossover.",
        fault_role="reconfiguration/B204_crossover_via_V210",
    )


def _schedules() -> model.SubmodelElementCollection:
    return smc(
        "ActuatorSchedules",
        _sem("ActuatorSchedules"),
        smc(
            "EmbeddedDefault",
            _sem("Schedule"),
            prop(
                "Name", "ActuatorControl table embedded in ModVA_online_stable.mo", _sem("Schedule")
            ),
            prop_typed("RowCount", datatypes.Int, 30, _sem("Schedule")),
            prop(
                "ColumnOrder",
                ", ".join(MODELICA_TABLE_COLUMNS),
                _sem("Schedule"),
                description="Table column order in the model; note V206/V205/V204 (D1).",
            ),
            description="The 30x10 CombiTimeTable the published model ships with: a nominal "
            "dosing cycle over 600 s.",
        ),
        smc(
            "BenchmarkMatrix",
            _sem("Schedule"),
            prop("Name", "ActuatorControlMatrix_2024-12-06-16-06-17.csv", _sem("Schedule")),
            prop_typed("RowCount", datatypes.Int, 11, _sem("Schedule")),
            prop(
                "ColumnOrder",
                "Time, V201, V202, V203, V204, V205, V206, P201, P202",
                _sem("Schedule"),
                description="The CSV's own order — 9 columns, no V209. Loaded positionally "
                "by the upstream GUI it mis-drives four actuators (deviation D1); "
                "this project maps columns by name.",
            ),
            file("File", SCHEDULE_ATTACHMENT_PATH, "text/csv", _sem("Schedule")),
            description="Schedule published with the benchmark under Simulation_Model_Control/.",
        ),
    )


def _operations(ctx: BuildContext) -> list[model.SubmodelElement]:
    delegate = qualifier("invocationDelegation", f"{ctx.endpoints.sim_runner}/run")
    run = model.Operation(
        id_short="RunSimulation",
        semantic_id=_sem("RunSimulation"),
        input_variable=[
            prop_typed("startTime", datatypes.Double, 0.0, None, description="s"),
            prop_typed(
                "stopTime",
                datatypes.Double,
                ctx.modelica.experiment.stop_time,
                None,
                description="s",
            ),
            prop(
                "solver",
                TESTED_SOLVER,
                None,
                description="OpenModelica solver name. The model annotation says cvode, which "
                "fails on this model; ida is what the published results used (D6).",
            ),
            prop_typed("tolerance", datatypes.Double, ctx.modelica.experiment.tolerance, None),
            prop(
                "schedule",
                "EmbeddedDefault",
                None,
                description="idShort of an ActuatorSchedules entry, or an inline JSON schedule "
                "keyed by actuator name.",
            ),
            prop(
                "parameterOverrides",
                "{}",
                None,
                description="JSON object of ParameterSet idShort -> value.",
            ),
        ],
        output_variable=[
            prop("runId", "", None),
            prop("status", "queued", None),
        ],
        qualifier=[delegate],
        description=model.MultiLanguageTextType(
            {
                "en": "Start a run. Delegated by the AAS server to the simulation runner; the "
                "result is appended to the TimeSeries submodel as a new segment pair."
            }
        ),
    )
    status = model.Operation(
        id_short="GetRunStatus",
        semantic_id=_sem("GetRunStatus"),
        input_variable=[prop("runId", "", None)],
        output_variable=[
            prop("status", "", None),
            prop_typed("progress", datatypes.Double, 0.0, None),
            prop("segmentIdShort", "", None),
        ],
        qualifier=[qualifier("invocationDelegation", f"{ctx.endpoints.sim_runner}/status")],
    )
    return [run, status]


def build_simulation_control(ctx: BuildContext) -> model.Submodel:
    return model.Submodel(
        id_=SUBMODEL_ID,
        id_short=_S,
        semantic_id=_sem("Submodel"),
        administration=model.AdministrativeInformation(version="1", revision="0"),
        submodel_element=[
            smc(
                "ParameterSet",
                _sem("ParameterSet"),
                *_model_parameters(ctx),
                *_fault_handles(ctx),
                description="Defaults read from ModVA_online_stable.mo at build time.",
            ),
            _schedules(),
            *_operations(ctx),
            smc(
                "Runs",
                _sem("Runs"),
                description="Executed runs are appended here by the simulation runner.",
            ),
            mlp(
                "Notes",
                "Sensor errors and the stirring error are measurement faults, not hydraulic "
                "ones; they are injected in post-processing on the LI channels rather than "
                "modelled. See design/aas-design.md section 5.3.",
                _sem("Submodel"),
            ),
        ],
    )
