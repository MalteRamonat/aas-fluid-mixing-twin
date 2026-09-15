"""The Modelica parser — structural facts read from the upstream model."""

from __future__ import annotations

from pathlib import Path

import pytest

from aas_fluid_twin.benchmark.modelica import load_modelica_model

pytestmark = pytest.mark.benchmark_data


def test_experiment_annotation() -> None:
    m = load_modelica_model()
    assert m.name == "ModVA_online_stable"
    assert m.msl_version == "4.0.0"
    assert m.experiment.stop_time == 600.0
    assert m.experiment.tolerance == 1e-05
    assert m.experiment.interval == 1.0
    assert m.experiment.solver == "cvode"


def test_component_geometry_ignores_nested_records() -> None:
    m = load_modelica_model()
    tanks = {t.name: t.modifiers for t in m.of_type("TankWithTopPorts")}
    assert tanks["tank_B201"]["height"] == 0.22  # not the portsData height = 0
    assert tanks["tank_B201"]["crossArea"] == 0.01431355
    assert tanks["tank_B204"]["height"] == 0.35
    assert tanks["tank_B204"]["crossArea"] == 0.0324


def test_pipes_valves_pumps_are_found() -> None:
    m = load_modelica_model()
    assert len(m.of_type("StaticPipe")) == 23
    assert {v.name for v in m.of_type("ValveLinear")} == {
        "V201",
        "V202",
        "V203",
        "V204",
        "V205",
        "V206",
        "V207",
        "V209",
    }
    assert {p.name for p in m.of_type("PrescribedPump")} == {"P201", "P202"}
    assert len(m.parameters) == 12  # six characteristic points per pump


def test_connections_are_parsed_from_the_equation_section_only() -> None:
    m = load_modelica_model()
    assert len(m.connections) == 82
    assert all("connect" not in c.first for c in m.connections)


def test_missing_model_says_what_to_do(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="fetch_benchmark"):
        load_modelica_model(tmp_path / "absent.mo")
