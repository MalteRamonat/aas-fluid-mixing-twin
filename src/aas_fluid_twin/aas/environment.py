"""Assemble the whole AAS environment: 16 shells, their submodels, every concept description.

``build_environment`` is a pure function of the :class:`BuildContext`; the result is an
object store plus the list of files the package needs to carry. Nothing here talks to a
server or a disk — that is :mod:`aas_fluid_twin.aas.io` and the BaSyx client.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from basyx.aas import model

from aas_fluid_twin import config
from aas_fluid_twin.aas import ids
from aas_fluid_twin.aas.builders import (
    asset_interfaces,
    fault_catalogue,
    handover,
    hierarchical_structures,
    nameplate,
    simulation_control,
    simulation_models,
    technical_data,
    time_series,
    twin_linkage,
)
from aas_fluid_twin.aas.builders._common import name, package_path, submodel_ref, text
from aas_fluid_twin.aas.context import BuildContext
from aas_fluid_twin.aas.semantics import channel_concept, iter_concept_descriptions

__all__ = ["Attachment", "BuiltEnvironment", "build_environment"]


@dataclass(frozen=True, slots=True)
class Attachment:
    """A file the AASX package or the repository must carry alongside the environment."""

    package_path: str
    source: Path
    content_type: str

    @property
    def exists(self) -> bool:
        return self.source.is_file()


@dataclass(slots=True)
class BuiltEnvironment:
    store: model.DictIdentifiableStore[model.Identifiable]
    attachments: tuple[Attachment, ...] = ()
    shells: dict[str, model.AssetAdministrationShell] = field(default_factory=dict)
    submodels: dict[str, model.Submodel] = field(default_factory=dict)

    @property
    def plant(self) -> model.AssetAdministrationShell:
        return self.shells[ids.PLANT_AAS_ID]

    @property
    def simulation(self) -> model.AssetAdministrationShell:
        return self.shells[ids.SIMULATION_AAS_ID]

    def submodel(self, submodel_id: str) -> model.Submodel:
        return self.submodels[submodel_id]

    def submodels_of(self, aas: model.AssetAdministrationShell) -> Iterator[model.Submodel]:
        for reference in aas.submodel:
            yield self.submodels[reference.key[0].value]

    def concept_descriptions(self) -> Iterator[model.ConceptDescription]:
        for obj in self.store:
            if isinstance(obj, model.ConceptDescription):
                yield obj


def _shell(
    aas_id: str,
    asset_id: str,
    id_short: str,
    display: str,
    description: str,
    submodels: list[model.Submodel],
    *,
    asset_type: str,
    specific: dict[str, str],
) -> model.AssetAdministrationShell:
    return model.AssetAdministrationShell(
        id_=aas_id,
        id_short=id_short,
        display_name=name(display),
        description=text(description),
        asset_information=model.AssetInformation(
            asset_kind=model.AssetKind.INSTANCE,
            global_asset_id=asset_id,
            asset_type=asset_type,
            specific_asset_id=[model.SpecificAssetId(name=k, value=v) for k, v in specific.items()],
        ),
        submodel={submodel_ref(sm.id) for sm in submodels},
        administration=model.AdministrativeInformation(version="1", revision="0"),
    )


def _attachments(ctx: BuildContext) -> tuple[Attachment, ...]:
    out: list[Attachment] = [
        Attachment(
            simulation_models.MODEL_ATTACHMENT_PATH,
            ctx.benchmark_dir / "simulation" / "ModVA_online_stable.mo",
            "text/x-modelica",
        ),
        Attachment(
            simulation_control.SCHEDULE_ATTACHMENT_PATH,
            ctx.benchmark_dir
            / "Simulation_Model_Control"
            / "ActuatorControlMatrix_2024-12-06-16-06-17.csv",
            "text/csv",
        ),
        Attachment(
            package_path("simulation", time_series.REFERENCE_SIMULATION_RESULT.rsplit("/", 1)[-1]),
            ctx.benchmark_dir / time_series.REFERENCE_SIMULATION_RESULT,
            "text/csv",
        ),
    ]
    if config.FAULTCAPABLE_MODEL_FILE.is_file():
        out.append(
            Attachment(
                simulation_models.FAULTCAPABLE_ATTACHMENT_PATH,
                config.FAULTCAPABLE_MODEL_FILE,
                "text/x-modelica",
            )
        )
    fmu = config.ARTIFACT_DIR / "ModVA_online_stable.fmu"
    if fmu.is_file():
        out.append(
            Attachment(
                simulation_models.FMU_ATTACHMENT_PATH, fmu, "application/x-fmu-sharedlibrary"
            )
        )
    if ctx.include_data_files:
        for part, source, content_type in handover.iter_attachments(ctx):
            out.append(Attachment(part, Path(str(source)), content_type))
        for part, source, content_type in time_series.iter_dataset_attachments(ctx):
            out.append(Attachment(part, Path(str(source)), content_type))
    return tuple(out)


def build_environment(ctx: BuildContext) -> BuiltEnvironment:
    submodels: list[model.Submodel] = []
    shells: list[model.AssetAdministrationShell] = []

    # --- plant -------------------------------------------------------------------
    plant_submodels = [
        nameplate.build_plant_nameplate(ctx),
        technical_data.build_plant_technical_data(ctx),
        handover.build_handover_documentation(ctx),
        hierarchical_structures.build_hierarchical_structures(ctx),
        asset_interfaces.build_asset_interfaces_description(ctx),
        time_series.build_plant_time_series(ctx),
        fault_catalogue.build_fault_scenario_catalogue(ctx),
        twin_linkage.build_twin_linkage(ctx, for_simulation=False),
    ]
    shells.append(
        _shell(
            ids.PLANT_AAS_ID,
            ids.PLANT_ASSET_ID,
            "ModVA_FluidMixingPlant",
            "ModVA fluid mixing plant",
            "Real four-tank dosing and mixing plant. Source: the fluid mixing anomaly "
            f"benchmark, DOI {config.BENCHMARK_DOI}.",
            plant_submodels,
            asset_type="Plant",
            specific={"PlantTag": ids.PLANT_TAG},
        )
    )
    submodels.extend(plant_submodels)

    # --- simulation twin ------------------------------------------------------
    sim_submodels = [
        simulation_models.build_simulation_models(ctx),
        time_series.build_simulation_time_series(ctx),
        simulation_control.build_simulation_control(ctx),
        twin_linkage.build_twin_linkage(ctx, for_simulation=True),
    ]
    shells.append(
        _shell(
            ids.SIMULATION_AAS_ID,
            ids.SIMULATION_ASSET_ID,
            "ModVA_SimulationTwin",
            "ModVA simulation twin (ModVA_online_stable)",
            "Modelica model of the ModVA plant, linked to the plant shell by the TwinLinkage "
            "submodel and executable through SimulationControl.",
            sim_submodels,
            asset_type="SimulationModel",
            specific={"ModelName": ctx.modelica.name},
        )
    )
    submodels.extend(sim_submodels)

    # --- components ------------------------------------------------------------
    for component in ctx.topology.shell_components:
        component_submodels = [
            nameplate.build_component_nameplate(ctx, component),
            technical_data.build_component_technical_data(ctx, component),
        ]
        shells.append(
            _shell(
                ids.component_aas_id(component.tag),
                ids.component_asset_id(component.tag),
                f"ModVA_{component.tag}",
                component.display_name,
                f"{component.display_name} of the ModVA plant ({component.kind.value}).",
                component_submodels,
                asset_type=component.kind.value.capitalize(),
                specific={"PlantTag": component.tag},
            )
        )
        submodels.extend(component_submodels)

    # --- store -------------------------------------------------------------------
    store = model.DictIdentifiableStore[model.Identifiable]()
    for shell in shells:
        store.add(shell)
    for submodel in submodels:
        store.add(submodel)
    for concept in iter_concept_descriptions():
        store.add(concept)
    for signal in ctx.signals:
        store.add(channel_concept(signal))

    return BuiltEnvironment(
        store=store,
        attachments=_attachments(ctx),
        shells={s.id: s for s in shells},
        submodels={s.id: s for s in submodels},
    )
