"""What the environment says about the plant.

Round-trip and conformance tests prove the environment is well-formed. These prove it is
*right*: the facts established in the analysis and the operator's answers appear where the
design says they appear.
"""

from __future__ import annotations

import pytest
from basyx.aas import model

from aas_fluid_twin.aas import ids
from aas_fluid_twin.aas.builders.simulation_control import MODELICA_TABLE_COLUMNS
from aas_fluid_twin.aas.environment import BuiltEnvironment
from aas_fluid_twin.aas.traverse import semantic_iri, walk
from aas_fluid_twin.benchmark import SignalDictionary
from aas_fluid_twin.benchmark.modelica import ModelicaModel, load_modelica_model

pytestmark = pytest.mark.benchmark_data


def _submodel(
    env: BuiltEnvironment, aas: model.AssetAdministrationShell, id_short: str
) -> model.Submodel:
    for sm in env.submodels_of(aas):
        if sm.id_short == id_short:
            return sm
    raise AssertionError(f"{aas.id_short} has no submodel {id_short}")


def _at(container: object, *path: str) -> model.SubmodelElement:
    current: object = container
    for step in path:
        assert isinstance(current, model.UniqueIdShortNamespace), step
        current = current.get_referable(step)
    assert isinstance(current, model.SubmodelElement)
    return current


def _value(element: model.SubmodelElement) -> object:
    assert isinstance(element, model.Property)
    return element.value


# --- topology of shells -----------------------------------------------------------


def test_sixteen_shells_with_the_designed_submodels(env: BuiltEnvironment) -> None:
    assert len(env.shells) == 16
    assert {sm.id_short for sm in env.submodels_of(env.plant)} == {
        "Nameplate",
        "TechnicalData",
        "HandoverDocumentation",
        "HierarchicalStructures",
        "AssetInterfacesDescription",
        "TimeSeries",
        "FaultScenarioCatalogue",
        "TwinLinkage",
    }
    assert {sm.id_short for sm in env.submodels_of(env.simulation)} == {
        "SimulationModels",
        "TimeSeries",
        "SimulationControl",
        "TwinLinkage",
    }
    components = [
        s for s in env.shells.values() if s.id not in (ids.PLANT_AAS_ID, ids.SIMULATION_AAS_ID)
    ]
    assert len(components) == 14
    for shell in components:
        assert {sm.id_short for sm in env.submodels_of(shell)} == {"Nameplate", "TechnicalData"}
        assert shell.asset_information.global_asset_id is not None
        assert shell.asset_information.asset_kind is model.AssetKind.INSTANCE


def test_component_shells_are_the_controllable_or_observable_items(env: BuiltEnvironment) -> None:
    tags = {
        next(s.value for s in shell.asset_information.specific_asset_id if s.name == "PlantTag")
        for shell in env.shells.values()
        if shell.id.startswith(f"{ids.BASE}aas/Component/")
    }
    assert tags == {
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
        "V209",
    }


def test_manual_valves_are_bom_nodes_without_shells(env: BuiltEnvironment) -> None:
    bom = _submodel(env, env.plant, "HierarchicalStructures")
    entry = _at(bom, "EntryNode")
    assert isinstance(entry, model.Entity)
    for tag in ("V207", "V208", "V210", "V211", "V212"):
        node = entry.get_referable(tag)
        assert isinstance(node, model.Entity)
        assert node.entity_type is model.EntityType.CO_MANAGED_ENTITY
        assert node.global_asset_id is None
    b204 = entry.get_referable("B204")
    assert isinstance(b204, model.Entity)
    assert b204.entity_type is model.EntityType.SELF_MANAGED_ENTITY
    assert b204.global_asset_id == ids.component_asset_id("B204")
    # TI262 is mounted on B204 (operator's correction of the P&ID), TI261 on P201's line.
    assert isinstance(b204.get_referable("TI262"), model.Entity)
    p201 = entry.get_referable("P201")
    assert isinstance(p201, model.Entity)
    assert isinstance(p201.get_referable("TI261"), model.Entity)


def test_plant_nameplate_names_the_operating_institution(env: BuiltEnvironment) -> None:
    """O12: the plant is a research rig; its operator takes the manufacturer's place."""
    plate = _submodel(env, env.plant, "Nameplate")
    name = _at(plate, "ManufacturerName")
    assert isinstance(name, model.MultiLanguageProperty)
    assert name.value is not None
    assert name.value["en"] == "Helmut Schmidt University Hamburg"
    city = _at(plate, "AddressInformation", "CityTown")
    assert isinstance(city, model.MultiLanguageProperty)
    assert city.value is not None
    assert city.value["en"] == "Hamburg"


# --- the twin linkage -------------------------------------------------------------


def test_relationship_element_links_plant_and_simulation_both_ways(env: BuiltEnvironment) -> None:
    plant_side = _at(_submodel(env, env.plant, "TwinLinkage"), "IsSimulatedBy")
    sim_side = _at(_submodel(env, env.simulation, "TwinLinkage"), "SimulatesAsset")
    assert isinstance(plant_side, model.RelationshipElement)
    assert isinstance(sim_side, model.RelationshipElement)
    assert plant_side.first is not None and plant_side.second is not None
    assert plant_side.first.key[0].value == ids.PLANT_AAS_ID
    assert plant_side.second.key[0].value == ids.SIMULATION_AAS_ID
    assert sim_side.first is not None and sim_side.second is not None
    assert sim_side.first.key[0].value == ids.SIMULATION_AAS_ID
    assert sim_side.second.key[0].value == ids.PLANT_AAS_ID


def test_signal_mappings_mirror_the_mapping_table(
    env: BuiltEnvironment, signals: SignalDictionary
) -> None:
    mappings = _at(_submodel(env, env.plant, "TwinLinkage"), "SignalMappings")
    assert isinstance(mappings, model.SubmodelElementList)
    assert len(list(mappings.value)) == len(signals)
    statuses: dict[str, str] = {}
    for element in mappings.value:
        assert isinstance(element, model.AnnotatedRelationshipElement)
        annotations = {a.id_short: a for a in element.annotation}
        sensor_id = _value(annotations["SensorId"])
        assert isinstance(sensor_id, str)
        statuses[sensor_id] = str(_value(annotations["MappingStatus"]))
    assert statuses["R201"] == "not_in_model"
    assert statuses["Level_B201_via_PI251"] == "not_assigned"
    assert statuses["VolumeB201"] == "mapped"
    assert sum(1 for s in statuses.values() if s == "mapped") == 38


# --- the interface -----------------------------------------------------------------


def test_aid_carries_every_channel_with_its_node_id(
    env: BuiltEnvironment, signals: SignalDictionary
) -> None:
    aid = _submodel(env, env.plant, "AssetInterfacesDescription")
    properties = _at(aid, "InterfaceOPCUA", "InteractionMetadata", "properties")
    assert isinstance(properties, model.SubmodelElementCollection)
    assert len(list(properties.value)) == 47
    for signal in signals:
        element = properties.get_referable(signal.channel)
        assert isinstance(element, model.SubmodelElementCollection)
        assert _value(_at(element, "key")) == signal.channel
        assert _value(_at(element, "forms", "href")) == signal.opcua_node_id
    live = _value(_at(aid, "InterfaceOPCUA", "EndpointMetadata", "LiveEndpoint"))
    assert live is False


def test_measuring_spans_are_quoted_in_the_channel_unit(env: BuiltEnvironment) -> None:
    """Datasheets say 0..1 bar and 70..1000 mm; the channels are kPa and cm."""
    aid = _submodel(env, env.plant, "AssetInterfacesDescription")
    properties = _at(aid, "InterfaceOPCUA", "InteractionMetadata", "properties")
    pressure = _at(properties, "Pressure_below_B201", "min_max")
    assert isinstance(pressure, model.Range)
    assert (pressure.min, pressure.max) == (0.0, 100.0)
    level = _at(properties, "Tank_B201_level_calculated_via_LI211", "min_max")
    assert isinstance(level, model.Range)
    assert (level.min, level.max) == (7.0, 100.0)
    flow = _at(properties, "Flow_after_Pump_P201", "min_max")
    assert isinstance(flow, model.Range)
    assert (flow.min, flow.max) == (0.1, 25.0)


def test_unreliable_channels_carry_a_data_quality_qualifier(env: BuiltEnvironment) -> None:
    aid = _submodel(env, env.plant, "AssetInterfacesDescription")
    properties = _at(aid, "InterfaceOPCUA", "InteractionMetadata", "properties")
    assert isinstance(properties, model.SubmodelElementCollection)
    flagged = {
        e.id_short
        for e in properties.value
        if any(q.type == "DataQuality" and q.value == "unreliable" for q in e.qualifier)
    }
    assert len(flagged) == 12
    assert "Pressure_below_B201" in flagged
    assert "Tank_B204_level_calculated_via_PI254_until_zero_level" in flagged
    assert "Tank_B201_Volume" not in flagged


# --- time series ---------------------------------------------------------------------


def test_time_series_has_a_segment_pair_per_run_and_no_internal_segments(
    env: BuiltEnvironment,
) -> None:
    ts = _submodel(env, env.plant, "TimeSeries")
    segments = _at(ts, "Segments")
    assert isinstance(segments, model.SubmodelElementCollection)
    kinds = [semantic_iri(s) for s in segments.value]
    assert len(kinds) == 110
    assert sum(1 for k in kinds if k and k.endswith("ExternalSegment/1/1")) == 55
    assert sum(1 for k in kinds if k and k.endswith("LinkedSegment/1/1")) == 55
    assert not any(k and k.endswith("InternalSegment/1/1") for k in kinds)

    record = _at(ts, "Metadata", "Record")
    assert isinstance(record, model.SubmodelElementCollection)
    for element in record.value:
        assert isinstance(element, model.Property)
        assert element.value is None, "metadata, not data"


def test_reduced_schema_run_is_flagged_not_dropped(env: BuiltEnvironment) -> None:
    ts = _submodel(env, env.plant, "TimeSeries")
    seg = _at(ts, "Segments", "Measured_dataset_0_normal_behaviour")
    assert _value(_at(seg, "SchemaVariant")) == "reduced"
    seg = _at(ts, "Segments", "Measured_dataset_1_normal_behaviour")
    assert _value(_at(seg, "SchemaVariant")) == "full"


def test_linked_segment_points_at_the_query_api(env: BuiltEnvironment) -> None:
    ts = _submodel(env, env.plant, "TimeSeries")
    seg = _at(ts, "Segments", "Linked_dataset_10_leakage")
    assert _value(_at(seg, "Endpoint")) == ids.DEFAULT_TIMESERIES_ENDPOINT
    assert _value(_at(seg, "Query")) == "run_id=dataset_10_leakage"


# --- fault catalogue -----------------------------------------------------------------


def test_fault_catalogue_carries_the_operator_onsets(env: BuiltEnvironment) -> None:
    cat = _submodel(env, env.plant, "FaultScenarioCatalogue")
    leak = _at(cat, "Scenarios", "leakage", "Runs", "dataset_10_leakage", "Window_1")
    assert _value(_at(leak, "OnsetTime")) == 66.0
    assert _value(_at(leak, "OnsetSource")) == "operator_log"
    stir = _at(cat, "Scenarios", "stirring_error", "Runs", "dataset_44_stirring_error")
    assert _value(_at(stir, "Window_3", "OnsetTime")) == 450.0
    assert _value(_at(stir, "Window_3", "EndTime")) == 467.0


def test_reconfiguration_is_two_sub_scenarios_with_their_injection_points(
    env: BuiltEnvironment,
) -> None:
    cat = _submodel(env, env.plant, "FaultScenarioCatalogue")
    subs = _at(cat, "Scenarios", "reconfiguration", "SubScenarios")
    assert isinstance(subs, model.SubmodelElementCollection)
    assert {s.id_short for s in subs.value} == {
        "leak_recirculated_to_B201",
        "B204_crossover_via_V210",
    }
    points = _at(subs, "B204_crossover_via_V210", "InjectionPoints")
    assert isinstance(points, model.SubmodelElementList)
    (ref,) = points.value
    assert isinstance(ref, model.ReferenceElement)
    assert ref.value is not None
    assert ref.value.key[-1].value == "V210"


def test_excluded_runs_are_marked(env: BuiltEnvironment) -> None:
    cat = _submodel(env, env.plant, "FaultScenarioCatalogue")
    assert _value(_at(cat, "Scenarios", "manual_mode", "UseForAnomalyDetection")) is False
    unusable = _at(
        cat,
        "Scenarios",
        "changed_initial_state",
        "Runs",
        "dataset_14_changed_initial_state",
        "Usable",
    )
    assert _value(unusable) is False


# --- deviations pinned against the upstream model ----------------------------------------


@pytest.fixture(scope="module")
def modelica() -> ModelicaModel:
    return load_modelica_model()


def test_d1_table_column_order_matches_the_connect_equations(modelica: ModelicaModel) -> None:
    order = {}
    for c in modelica.connections:
        if c.first.startswith("ActuatorControl.y["):
            index = int(c.first[len("ActuatorControl.y[") : -1])
            order[index] = c.second.split(".")[0].removesuffix("_Characteristic")
    assert tuple(order[i] for i in sorted(order)) == MODELICA_TABLE_COLUMNS[1:]


def test_d3_valve_wiring_matches_the_empirical_assignment(modelica: ModelicaModel) -> None:
    """V204 fills B201, V206 fills B203 — the pipe *names* say otherwise (deviation D3)."""

    def tank_fed_by(valve: str) -> str:
        pipe = next(n for n in modelica.neighbours(valve) if n.startswith("pipe_") and "_B20" in n)
        return next(n for n in modelica.neighbours(pipe) if n.startswith("tank_")).removeprefix(
            "tank_"
        )

    assert tank_fed_by("V204") == "B201"
    assert tank_fed_by("V205") == "B202"
    assert tank_fed_by("V206") == "B203"
    assert "pipe_V206_B201" in modelica.neighbours("V204")  # the misleading name, still upstream


def test_d4_upstream_model_still_has_the_temperature_sensors_swapped(
    modelica: ModelicaModel,
) -> None:
    """Pins the defect. If upstream fixes it, this fails and deviation D4 is done."""
    assert modelica.neighbours("TI261") == ("Pipe_B204_V207",)  # on B204 in the model
    assert modelica.neighbours("TI262") == ("pipe_V203_Tee2",)  # on the suction manifold


def test_d5_simulation_units_are_declared_correctly_in_the_aas(env: BuiltEnvironment) -> None:
    sim = _submodel(env, env.simulation, "SimulationModels")
    outputs = _at(sim, "SimulationModel", "Ports", "MeasuredOutputs")
    assert _value(_at(outputs, "Var_Pressure_below_B201", "UnitList")) == "Pa"
    assert _value(_at(outputs, "Var_Temperature_in_B204", "UnitList")) == "K"
    assert _value(_at(outputs, "Var_Flow_after_Pump_P201", "UnitList")) == "m3/s"


def test_simulation_defaults_are_read_from_the_model_file(
    env: BuiltEnvironment, modelica: ModelicaModel
) -> None:
    sim = _submodel(env, env.simulation, "SimulationModels")
    assert _value(_at(sim, "SimulationModel", "DefaultSimTime")) == modelica.experiment.stop_time
    alg = _at(
        sim,
        "SimulationModel",
        "Environment",
        "SimulationTool",
        "SolverAndTolerances",
        "TestedToolSolverAlgorithm",
    )
    # The annotation says cvode; the tested (and only working) solver is IDA — deviation D6.
    assert modelica.experiment.solver == "cvode"
    assert _value(_at(alg, "SolverAlgorithm")) == "ida"
    assert _value(_at(alg, "Tolerance")) == 1e-05

    control = _submodel(env, env.simulation, "SimulationControl")
    b204 = _at(control, "ParameterSet", "tank_B204_level_start")
    assert (
        _value(_at(b204, "DefaultValue"))
        == modelica.declarations["tank_B204"].modifiers["level_start"]
    )
    run = _at(control, "RunSimulation")
    assert isinstance(run, model.Operation)
    assert any(q.type == "invocationDelegation" for q in run.qualifier)


def test_every_file_reference_names_a_benchmark_artefact(env: BuiltEnvironment) -> None:
    """Every File value that lives in the package has a real source in the benchmark tree."""
    by_path = {a.package_path: a for a in env.attachments}
    for submodel in env.submodels.values():
        for _, element in walk(submodel):
            if (
                isinstance(element, model.File)
                and element.value
                and element.value.startswith("/aasx/")
            ):
                assert element.value in by_path, element.value
                assert by_path[element.value].exists
