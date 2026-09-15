"""TwinLinkage — custom submodel (design §5.2).

The ``RelationshipElement`` that ties the physical plant to its simulation twin, plus the
per-signal correspondence: one ``AnnotatedRelationshipElement`` per channel from the AID
property to the model's port variable, annotated with both units and the conversion factor.
This is ``Simulation_Variable_Mapping.xlsx`` expressed natively in AAS, including its gaps —
``MappingStatus`` says which channels the model does not produce, in the mapping table's own
words (``not_in_model``, ``not_assigned``).

Built for both shells: from the plant side the relation reads *IsSimulatedBy*, from the
simulation side *SimulatesAsset*, so navigation works from either end.
"""

from __future__ import annotations

from basyx.aas import model
from basyx.aas.model import datatypes

from aas_fluid_twin.aas import ids
from aas_fluid_twin.aas.builders._common import aas_ref, mlp, prop, prop_typed, sml
from aas_fluid_twin.aas.builders.asset_interfaces import property_reference
from aas_fluid_twin.aas.builders.simulation_models import variable_reference
from aas_fluid_twin.aas.context import BuildContext
from aas_fluid_twin.aas.semantics import semantic
from aas_fluid_twin.benchmark.signals import Signal
from aas_fluid_twin.simulation.units import SimUnit, sensor_to_sim, sim_unit_of

__all__ = ["build_twin_linkage"]

_S = "TwinLinkage"

#: What the plant author documented in the model header, verbatim in substance.
MODEL_FIDELITY = (
    "Documented in the header of ModVA_online_stable.mo: (1) in the simulation B203 fills "
    "faster than B201 while in reality B201 fills faster — the tee flow split is not captured; "
    "(2) in reality P202 pumps faster than P201, which the model does not reproduce. Known "
    "additional deviations found in this project: D3 (pipe component names contradict the "
    "wiring; behaviour unaffected), D4 (TI261/TI262 swapped in the model), D5 (pressure and "
    "temperature units mis-declared in the mapping table)."
)


def _sem(element: str) -> model.ExternalReference:
    return semantic(_S, element)


def _conversion_factor(signal: Signal, sim_unit: SimUnit) -> float | None:
    """Sensor→simulation factor where the conversion is purely multiplicative."""
    if signal.unit is None or sim_unit is SimUnit.DIMENSIONLESS:
        return 1.0
    if signal.unit in ("kPa", "°C"):
        return None  # affine, not multiplicative: offset applies (D5)
    return sensor_to_sim(1.0, signal.unit, sim_unit)


def _mapping(signal: Signal) -> model.AnnotatedRelationshipElement:
    if signal.sim_variable is None:
        status = "not_in_model" if signal.sensor_id == "R201" else "not_assigned"
        sim_unit: SimUnit | None = None
    else:
        status = "mapped"
        sim_unit = sim_unit_of(signal.sim_variable)

    annotations: list[model.DataElement] = [
        prop("SensorId", signal.sensor_id, _sem("SensorId")),
        prop("MappingStatus", status, _sem("MappingStatus")),
        prop("UnitSensor", signal.unit or "binary", _sem("UnitSensor")),
    ]
    if signal.sim_variable is not None and sim_unit is not None:
        annotations.append(
            prop("SimulationVariable", signal.sim_variable, _sem("SimulationVariable"))
        )
        annotations.append(prop("UnitSimulation", sim_unit.value, _sem("UnitSimulation")))
        factor = _conversion_factor(signal, sim_unit)
        if factor is not None:
            annotations.append(
                prop_typed("ConversionFactor", datatypes.Double, factor, _sem("ConversionFactor"))
            )
        else:
            annotations.append(
                prop(
                    "ConversionNote",
                    "Affine conversion: kPa gauge -> Pa absolute adds the model's ambient "
                    "100000 Pa; °C -> K adds 273.15. See simulation/units.py.",
                    _sem("ConversionFactor"),
                )
            )

    description = f"{signal.display_name}: {status}."
    if status == "not_in_model":
        description += " The stirrer is not represented in the Modelica model."
    elif status == "not_assigned":
        description += (
            " Pressure-derived level; no Modelica variable is assigned in the mapping table."
        )

    return model.AnnotatedRelationshipElement(
        id_short=f"Map_{signal.channel}",
        first=property_reference(signal.channel),
        second=variable_reference(signal) if signal.sim_variable is not None else None,
        annotation=annotations,
        semantic_id=_sem("SignalMapping"),
        description=model.MultiLanguageTextType({"en": description}),
    )


def build_twin_linkage(ctx: BuildContext, *, for_simulation: bool) -> model.Submodel:
    if for_simulation:
        relation_id, relation_sem = "SimulatesAsset", "SimulatesAsset"
        first, second = aas_ref(ids.SIMULATION_AAS_ID), aas_ref(ids.PLANT_AAS_ID)
        owner_tag = ids.SIMULATION_TAG
    else:
        relation_id, relation_sem = "IsSimulatedBy", "IsSimulatedBy"
        first, second = aas_ref(ids.PLANT_AAS_ID), aas_ref(ids.SIMULATION_AAS_ID)
        owner_tag = ids.PLANT_TAG

    mapped = sum(1 for s in ctx.signals if s.sim_variable is not None)
    return model.Submodel(
        id_=ids.submodel_id(owner_tag, _S),
        id_short=_S,
        semantic_id=_sem("Submodel"),
        administration=model.AdministrativeInformation(version="1", revision="0"),
        submodel_element=[
            model.RelationshipElement(
                id_short=relation_id,
                first=first,
                second=second,
                semantic_id=_sem(relation_sem),
                description=model.MultiLanguageTextType(
                    {"en": "The Modelica model ModVA_online_stable represents the ModVA plant."}
                ),
            ),
            mlp("ModelFidelity", MODEL_FIDELITY, _sem("ModelFidelity")),
            sml(
                "SignalMappings",
                model.AnnotatedRelationshipElement,
                _sem("SignalMappings"),
                [_mapping(s) for s in ctx.signals],
                semantic_id_list_element=_sem("SignalMapping"),
            ),
        ],
        description=model.MultiLanguageTextType(
            {
                "en": f"{mapped} of {len(ctx.signals)} plant channels have a counterpart in the "
                "simulation model."
            }
        ),
    )
