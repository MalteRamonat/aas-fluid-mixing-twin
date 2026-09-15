"""Serialisation round trips.

The environment must survive JSON, XML and AASX without loss: same identifiables, same
element trees, same values. AASX additionally has to carry the attachments byte-identically,
because an ExternalSegment that points at a corrupted CSV is worse than no segment.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from basyx.aas import model

from aas_fluid_twin.aas import io as aas_io
from aas_fluid_twin.aas.environment import BuiltEnvironment
from aas_fluid_twin.aas.traverse import fingerprint as _fingerprint
from aas_fluid_twin.aas.traverse import walk

pytestmark = pytest.mark.benchmark_data


def test_json_round_trip_is_lossless(env: BuiltEnvironment, tmp_path: Path) -> None:
    path = aas_io.write_json(env, tmp_path / "env.json")
    restored = aas_io.read_json(path)
    assert _fingerprint(restored) == _fingerprint(env.store)


def test_xml_round_trip_is_lossless(env: BuiltEnvironment, tmp_path: Path) -> None:
    path = aas_io.write_xml(env, tmp_path / "env.xml")
    restored = aas_io.read_xml(path)
    assert _fingerprint(restored) == _fingerprint(env.store)


def test_json_and_xml_agree(env: BuiltEnvironment, tmp_path: Path) -> None:
    from_json = aas_io.read_json(aas_io.write_json(env, tmp_path / "a.json"))
    from_xml = aas_io.read_xml(aas_io.write_xml(env, tmp_path / "a.xml"))
    assert _fingerprint(from_json) == _fingerprint(from_xml)


def test_aasx_round_trip_carries_objects_and_attachments(
    env: BuiltEnvironment, tmp_path: Path
) -> None:
    path = aas_io.write_aasx(env, tmp_path / "env.aasx")
    store, files = aas_io.read_aasx(path)

    assert _fingerprint(store) == _fingerprint(env.store)

    present = [a for a in env.attachments if a.exists]
    assert present, "no attachments on disk — fetch the benchmark first"
    for attachment in present:
        expected = hashlib.sha256(attachment.source.read_bytes()).hexdigest()
        assert files.get_sha256(attachment.package_path).hex() == expected, attachment.package_path


def test_every_file_element_resolves_inside_the_package(
    env: BuiltEnvironment, tmp_path: Path
) -> None:
    """A File whose value starts with /aasx/ must name a part that exists in the package."""
    path = aas_io.write_aasx(env, tmp_path / "env.aasx")
    _, files = aas_io.read_aasx(path)
    names = {a.package_path for a in env.attachments if a.exists}
    for submodel in env.submodels.values():
        for element_path, element in walk(submodel):
            if (
                isinstance(element, model.File)
                and element.value
                and element.value.startswith("/aasx/")
            ):
                assert (
                    element.value in names
                ), f"{submodel.id_short}/{element_path} -> {element.value}"
                files.get_content_type(element.value)  # raises if absent


def test_aasx_refuses_to_write_with_a_missing_attachment(
    env: BuiltEnvironment, tmp_path: Path
) -> None:
    """A package the reference reader cannot open must never be produced."""
    from dataclasses import replace

    from aas_fluid_twin.aas.environment import Attachment

    broken = replace(
        env,
        attachments=(
            *env.attachments,
            Attachment("/aasx/ghost.csv", tmp_path / "ghost.csv", "text/csv"),
        ),
    )
    with pytest.raises(FileNotFoundError, match="ghost"):
        aas_io.write_aasx(broken, tmp_path / "broken.aasx")
