"""FaultScenarioCatalogue — custom submodel (design §5.1).

No published IDTA template describes labelled fault scenarios of a CPS dataset, so this one
is project-defined; every element carries a ConceptDescription from :mod:`semantics`.

The content is the plant operator's own account: how each scenario was induced, where, what
it affects, and when it starts in each run. Label 5 (``reconfiguration``) is two physically
different scenarios and is modelled as two sub-scenarios, because a detector trained on the
merged label is being asked to learn two unrelated things.
"""

from __future__ import annotations

from basyx.aas import model
from basyx.aas.model import datatypes

from aas_fluid_twin.aas import ids
from aas_fluid_twin.aas.builders._common import (
    id_short_for,
    mlp,
    prop,
    prop_typed,
    ref_element,
    smc,
    sml,
)
from aas_fluid_twin.aas.builders.hierarchical_structures import bom_reference
from aas_fluid_twin.aas.builders.time_series import PLANT_TIMESERIES_ID, segment_reference
from aas_fluid_twin.aas.context import BuildContext
from aas_fluid_twin.aas.semantics import semantic
from aas_fluid_twin.benchmark.annotations import ScenarioSpec, SubScenarioSpec
from aas_fluid_twin.benchmark.datasets import RunMetadata, Scenario

__all__ = ["SUBMODEL_ID", "build_fault_scenario_catalogue"]

_S = "FaultScenarioCatalogue"
SUBMODEL_ID = ids.submodel_id(ids.PLANT_TAG, _S)


def _sem(element: str) -> model.ExternalReference:
    return semantic(_S, element)


def _references(
    ctx: BuildContext, id_short: str, tags: tuple[str, ...], element: str
) -> model.SubmodelElementList[model.ReferenceElement] | None:
    if not tags:
        return None
    return sml(
        id_short,
        model.ReferenceElement,
        _sem(id_short),
        [ref_element(id_short_for(tag), bom_reference(ctx, tag), _sem(element)) for tag in tags],
        semantic_id_list_element=_sem(element),
    )


def _fault_event(run: RunMetadata) -> model.SubmodelElementCollection:
    """One run of a scenario, with its operator-recorded windows."""
    windows: list[model.SubmodelElement | None] = []
    for i, event in enumerate(run.events, start=1):
        windows.append(
            smc(
                f"Window_{i}",
                _sem("FaultEvent"),
                prop_typed("OnsetTime", datatypes.Double, event.onset_s, _sem("OnsetTime")),
                prop_typed(
                    "EndTime",
                    datatypes.Double,
                    event.end_s,
                    _sem("EndTime"),
                    description=(
                        None
                        if event.end_s is not None
                        else "Absent: the fault persists to the end of the run."
                    ),
                ),
                prop("OnsetSource", event.source.value, _sem("OnsetSource")),
            )
        )
    description = (
        f"Anomaly label {run.label}; {run.record_count} samples over {run.duration_s:.0f} s."
    )
    if run.note:
        description += f" {run.note}"
    if not run.usable:
        description += f" Unusable: {run.unusable_reason}"
    return smc(
        run.run_id,
        _sem("FaultEvent"),
        prop("RunId", run.run_id, _sem("RunId")),
        ref_element(
            "RunSegment",
            segment_reference(PLANT_TIMESERIES_ID, f"Measured_{run.run_id}"),
            _sem("RunSegment"),
        ),
        prop("Usable", run.usable, _sem("Usable")),
        *windows,
        description=description,
    )


def _sub_scenario(ctx: BuildContext, spec: SubScenarioSpec) -> model.SubmodelElementCollection:
    runs = [ctx.index.by_id(run_id) for run_id in spec.runs]
    return smc(
        spec.key,
        _sem("SubScenario"),
        prop("SubScenarioName", spec.key, _sem("SubScenarioName")),
        mlp("Description", spec.description, _sem("ObservableEffect")),
        mlp("InductionMethod", spec.induction, _sem("InductionMethod")),
        _references(ctx, "InjectionPoints", spec.injection_points, "InjectionPoint"),
        _references(ctx, "AffectedComponents", spec.affected_components, "AffectedComponents"),
        smc("Runs", _sem("Runs"), *(_fault_event(r) for r in runs)),
    )


def _scenario(ctx: BuildContext, spec: ScenarioSpec) -> model.SubmodelElementCollection:
    scenario = Scenario(spec.key)
    runs = list(ctx.index.with_scenario(scenario))
    # Runs that belong to a sub-scenario are listed there, not twice.
    in_sub = {run_id for sub in spec.sub_scenarios for run_id in sub.runs}
    own_runs = [r for r in runs if r.run_id not in in_sub]

    elements: list[model.SubmodelElement | None] = [
        prop("LabelValue", spec.label, _sem("LabelValue")),
        prop("ScenarioName", spec.key, _sem("ScenarioName")),
        mlp("Description", spec.description, _sem("ObservableEffect")),
        mlp("InductionMethod", spec.induction, _sem("InductionMethod")) if spec.induction else None,
        _references(ctx, "InjectionPoints", spec.injection_points, "InjectionPoint"),
        _references(ctx, "AffectedComponents", spec.affected_components, "AffectedComponents"),
        prop(
            "UseForAnomalyDetection", spec.use_for_anomaly_detection, _sem("UseForAnomalyDetection")
        ),
        mlp("Note", spec.note, _sem("ObservableEffect")) if spec.note else None,
    ]
    if spec.sub_scenarios:
        elements.append(
            smc(
                "SubScenarios",
                _sem("SubScenarios"),
                *(_sub_scenario(ctx, sub) for sub in spec.sub_scenarios),
            )
        )
    if own_runs and scenario is not Scenario.NORMAL_BEHAVIOUR:
        elements.append(smc("Runs", _sem("Runs"), *(_fault_event(r) for r in own_runs)))
    elif scenario is Scenario.NORMAL_BEHAVIOUR:
        elements.append(
            prop(
                "RunCount",
                len(runs),
                _sem("Runs"),
                description="Normal runs are referenced from the TimeSeries submodel; they "
                "carry no fault events.",
            )
        )
    return smc(spec.key, _sem("Scenario"), *elements)


def build_fault_scenario_catalogue(ctx: BuildContext) -> model.Submodel:
    specs = sorted(ctx.annotations.scenarios.values(), key=lambda s: s.label)
    return model.Submodel(
        id_=SUBMODEL_ID,
        id_short=_S,
        semantic_id=_sem("Submodel"),
        administration=model.AdministrativeInformation(version="1", revision="0"),
        submodel_element=[
            prop(
                "LabelingScheme",
                "CSV column 'Anomaly', integer, constant for the whole run. Per-sample labels "
                "follow from the onset windows recorded here.",
                _sem("LabelingScheme"),
            ),
            smc("Scenarios", _sem("Scenarios"), *(_scenario(ctx, s) for s in specs)),
        ],
        description=model.MultiLanguageTextType(
            {
                "en": f"{len(specs)} scenarios over {len(ctx.index)} recorded runs. Induction "
                "methods and onset times as stated by the plant operator; all onsets are "
                "operator_log, none are estimates."
            }
        ),
    )
