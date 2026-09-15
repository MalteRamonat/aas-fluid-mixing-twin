"""Round trip through a live Eclipse BaSyx AAS environment.

Needs the Docker stack (``docker compose up -d``) and the benchmark data. Skipped otherwise.
Point ``AAS_BASYX_URL`` elsewhere to test against another server.

This is the test that settles two questions the design left open until now:

1. Does the Java server (AAS metamodel 3.0) accept what ``basyx-python-sdk`` 2.1 (metamodel
   3.1.2) serialises? — ``test_server_copy_matches_local_build``.
2. Does the pinned image honour the ``invocationDelegation`` qualifier? — the qualifier must
   survive the round trip here; the delegated call itself is exercised in the end-to-end test
   once the simulation runner exists.
"""

from __future__ import annotations

import hashlib
import os

import pytest
from basyx.aas import model

from aas_fluid_twin.aas import ids
from aas_fluid_twin.aas.environment import BuiltEnvironment
from aas_fluid_twin.aas.traverse import fingerprint, id_short_paths
from aas_fluid_twin.client import BasyxClient

pytestmark = [pytest.mark.integration, pytest.mark.benchmark_data]

BASYX_URL = os.environ.get("AAS_BASYX_URL", "http://localhost:8081")


@pytest.fixture(scope="module")
def basyx() -> BasyxClient:
    client = BasyxClient(BASYX_URL)
    if not client.is_up():
        pytest.skip(f"no BaSyx AAS environment at {BASYX_URL} — `docker compose up -d`")
    return client


@pytest.fixture(scope="module")
def pushed(basyx: BasyxClient, env: BuiltEnvironment) -> BuiltEnvironment:
    for concept in env.concept_descriptions():
        basyx.put_concept_description(concept)
    for submodel in env.submodels.values():
        basyx.put_submodel(submodel)
    for shell in env.shells.values():
        basyx.put_shell(shell)
    return env


def test_server_copy_matches_local_build(basyx: BasyxClient, pushed: BuiltEnvironment) -> None:
    remote = model.DictIdentifiableStore[model.Identifiable]()
    for aas_id in pushed.shells:
        remote.add(basyx.get_shell(aas_id))
    for submodel_id in pushed.submodels:
        remote.add(basyx.get_submodel(submodel_id))
    local = fingerprint(pushed.store, ignore_file_values=True)
    served = fingerprint(remote, ignore_file_values=True)
    for identifier in list(pushed.shells) + list(pushed.submodels):
        assert served[identifier] == local[identifier], identifier


def test_all_shells_are_listed(basyx: BasyxClient, pushed: BuiltEnvironment) -> None:
    assert set(pushed.shells) <= set(basyx.list_shell_ids())
    assert set(pushed.submodels) <= set(basyx.list_submodel_ids())


def test_attachment_round_trip_is_byte_identical(
    basyx: BasyxClient, pushed: BuiltEnvironment
) -> None:
    by_part = {a.package_path: a for a in pushed.attachments}
    submodel = pushed.submodel(ids.submodel_id(ids.PLANT_TAG, "TimeSeries"))
    checked = 0
    for path, element in id_short_paths(submodel):
        if not isinstance(element, model.File) or not element.value:
            continue
        attachment = by_part[element.value]
        payload = attachment.source.read_bytes()
        basyx.upload_attachment(
            submodel.id, path, attachment.source.name, payload, attachment.content_type
        )
        served = basyx.download_attachment(submodel.id, path)
        assert hashlib.sha256(served).digest() == hashlib.sha256(payload).digest(), path
        checked += 1
        if checked == 3:  # three runs prove the mechanism; all 55 take a while
            break
    assert checked == 3


def test_delegation_qualifier_survives_the_round_trip(
    basyx: BasyxClient, pushed: BuiltEnvironment
) -> None:
    control = basyx.get_submodel(ids.submodel_id(ids.SIMULATION_TAG, "SimulationControl"))
    operation = control.get_referable("RunSimulation")
    assert isinstance(operation, model.Operation)
    delegations = [q for q in operation.qualifier if q.type == "invocationDelegation"]
    assert len(delegations) == 1
    assert str(delegations[0].value).startswith("http://sim-runner:8000/")


def test_element_value_endpoint(basyx: BasyxClient, pushed: BuiltEnvironment) -> None:
    value = basyx.get_element_value(
        ids.submodel_id(ids.PLANT_TAG, "TimeSeries"),
        "Segments.Linked_dataset_10_leakage.Query",
    )
    assert value == "run_id=dataset_10_leakage"
