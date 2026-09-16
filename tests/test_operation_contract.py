"""The ``RunSimulation`` operation is the twin's command interface — it has to stay complete.

A field the dashboard sends but the operation does not declare is silently dropped on the
AAS-native path: the run then executes with a default nobody asked for. That happened once
(``outputInterval`` and ``label``), which is why the mapping is pinned here rather than left
to be noticed in a browser.
"""

from __future__ import annotations

import json

import pytest
from basyx.aas import model

from aas_fluid_twin.aas.builders.simulation_control import SUBMODEL_ID
from aas_fluid_twin.aas.environment import BuiltEnvironment
from aas_fluid_twin.simulation.service import RunSpec

pytestmark = pytest.mark.benchmark_data

#: ``RunSimulation`` input variable -> the :class:`RunSpec` field it fills.
OPERATION_INPUTS = {
    "startTime": "start_time",
    "stopTime": "stop_time",
    "outputInterval": "output_interval",
    "solver": "solver",
    "tolerance": "tolerance",
    "schedule": "schedule",
    "parameterOverrides": "parameter_overrides",
    "controlRules": "control_rules",
    "model": "model",
    "label": "label",
}


def _operation(env: BuiltEnvironment, id_short: str) -> model.Operation:
    element = env.submodels[SUBMODEL_ID].submodel_element.get("id_short", id_short)
    assert isinstance(element, model.Operation)
    return element


def _declared(operation: model.Operation, which: str = "input") -> dict[str, str]:
    """idShort -> declared default, for the operation's input or output variables.

    The SDK models an ``OperationVariable`` as the submodel element itself, so the variable's
    idShort and its declared value are read straight off the element.
    """
    variables = operation.input_variable if which == "input" else operation.output_variable
    declared: dict[str, str] = {}
    for variable in variables:
        assert isinstance(variable, model.Property)
        declared[str(variable.id_short)] = "" if variable.value is None else str(variable.value)
    return declared


def test_the_operation_declares_every_field_a_run_request_has(env: BuiltEnvironment) -> None:
    declared = set(_declared(_operation(env, "RunSimulation")))
    assert declared == set(OPERATION_INPUTS)
    # Every declared input has somewhere to go, and every RunSpec field can be asked for.
    assert set(OPERATION_INPUTS.values()) == set(RunSpec.model_fields)


def test_the_operation_defaults_parse_into_a_usable_request(env: BuiltEnvironment) -> None:
    """The declared defaults are what a consumer reading the AAS would send unchanged."""
    spec = RunSpec.from_operation_inputs(_declared(_operation(env, "RunSimulation")))
    assert spec.solver == "ida"  # deviation D6
    assert spec.stop_time == 600.0
    assert spec.output_interval == 1.0
    assert spec.schedule == "EmbeddedDefault"
    assert spec.parameter_overrides == {}
    assert spec.model is None  # an empty model means "the runner's default"
    assert spec.label is None
    assert spec.control_rules == []  # every actuator follows the schedule


def test_a_filled_in_form_survives_the_operation_encoding(env: BuiltEnvironment) -> None:
    """What the dashboard puts in the form must come out the other side unchanged."""
    sent = RunSpec(
        stop_time=45.0,
        output_interval=0.25,
        solver="dassl",
        tolerance=1e-6,
        schedule="BenchmarkMatrix",
        parameter_overrides={"V211_opening": 0.3, "V211_return_to_B201": True},
        control_rules=[
            {
                "actuator": "V204",
                "signal": "Tank_B201_Volume",
                "on_below": 500.0,
                "off_above": 2000.0,
            }
        ],
        model="ModVA_faultcapable",
        label="leak, recirculated",
    )
    wire = {
        "startTime": str(sent.start_time),
        "stopTime": str(sent.stop_time),
        "outputInterval": str(sent.output_interval),
        "solver": sent.solver,
        "tolerance": str(sent.tolerance),
        "schedule": str(sent.schedule),
        "parameterOverrides": json.dumps(sent.parameter_overrides),
        "controlRules": json.dumps(sent.control_rules),
        "model": sent.model or "",
        "label": sent.label or "",
    }
    assert RunSpec.from_operation_inputs(wire) == sent


def test_the_status_operation_reports_what_a_caller_needs(env: BuiltEnvironment) -> None:
    status = _operation(env, "GetRunStatus")
    assert set(_declared(status)) == {"runId"}
    assert set(_declared(status, "output")) == {"status", "progress", "segmentIdShort"}


def test_both_operations_are_delegated_to_the_runner(env: BuiltEnvironment) -> None:
    for id_short, path in (("RunSimulation", "/run"), ("GetRunStatus", "/status")):
        qualifiers = {q.type: q.value for q in _operation(env, id_short).qualifier}
        assert "invocationDelegation" in qualifiers, id_short
        assert str(qualifiers["invocationDelegation"]).endswith(f"/invoke{path}")
