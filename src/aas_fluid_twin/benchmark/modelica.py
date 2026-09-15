"""Structural facts read out of ``ModVA_online_stable.mo``.

A deliberately small parser: it does not understand Modelica, it extracts the three things
this project needs from the flat model file with regular expressions —

* component declarations with their numeric modifiers (pipe lengths, tank geometry …),
* the ``connect(a, b)`` equations, i.e. the model's real wiring, and
* the experiment annotation (stop time, tolerance, solver).

Reading these from the file rather than transcribing them keeps the AAS honest: if the
upstream model changes, the technical data changes with it, and the tests that pin known
facts (deviations D3 and D4) fail loudly instead of drifting.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from aas_fluid_twin import config

__all__ = [
    "Connection",
    "Declaration",
    "Experiment",
    "ModelicaModel",
    "load_modelica_model",
]

# A component declaration ends either at its graphical annotation (every declaration in the
# upstream model has one) or, in a generated model such as ModVA_faultcapable, at the ";" that
# closes the statement.
_DECL_RE = re.compile(
    r"^\s*(?P<type>[A-Z][\w.]*)\s+(?P<name>[A-Za-z_]\w*)\s*\((?P<mods>.*?)\)"
    r"\s*(?:annotation|;\s*$)",
    re.MULTILINE | re.DOTALL,
)
_NUMERIC_MOD_RE = re.compile(
    r"(?<![\w.])(?P<key>[A-Za-z_]\w*)\s*(?:\([^)]*\))?\s*=\s*(?P<value>-?\d+(?:\.\d+)?(?:[eE]-?\d+)?)(?![\w.])"
)
_CONNECT_RE = re.compile(r"connect\(\s*([\w.\[\]]+)\s*,\s*([\w.\[\]]+)\s*\)")
_PARAMETER_RE = re.compile(
    r"^\s*parameter\s+Real\s+(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<value>-?\d+(?:\.\d+)?(?:[eE]-?\d+)?)\s*;",
    re.MULTILINE,
)
_EXPERIMENT_RE = re.compile(r"experiment\((?P<body>[^)]*)\)")
_SOLVER_RE = re.compile(r'__OpenModelica_simulationFlags\([^)]*\bs\s*=\s*"(?P<solver>\w+)"')
_MSL_RE = re.compile(r'uses\(Modelica\(version\s*=\s*"(?P<version>[^"]+)"\)\)')
_TABLE_RE = re.compile(r"CombiTimeTable\s+(?P<name>\w+)\s*\(\s*table\s*=\s*\[(?P<body>[^\]]*)\]")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")


@dataclass(frozen=True, slots=True)
class Declaration:
    name: str
    type_name: str
    modifiers: Mapping[str, float] = field(default_factory=dict)

    @property
    def short_type(self) -> str:
        return self.type_name.rsplit(".", 1)[-1]


@dataclass(frozen=True, slots=True)
class Connection:
    first: str
    second: str

    @property
    def components(self) -> tuple[str, str]:
        return self.first.split(".")[0], self.second.split(".")[0]


@dataclass(frozen=True, slots=True)
class Experiment:
    start_time: float
    stop_time: float
    tolerance: float
    interval: float
    solver: str | None


@dataclass(frozen=True, slots=True)
class ModelicaModel:
    name: str
    path: Path
    msl_version: str | None
    declarations: Mapping[str, Declaration]
    parameters: Mapping[str, float]
    """Top-level ``parameter Real`` declarations, e.g. the pump characteristic points."""
    connections: tuple[Connection, ...]
    experiment: Experiment
    actuator_table: tuple[tuple[float, ...], ...] = ()
    """The ``CombiTimeTable ActuatorControl`` matrix literal, row by row (time first)."""

    def of_type(self, short_type: str) -> tuple[Declaration, ...]:
        return tuple(d for d in self.declarations.values() if d.short_type == short_type)

    def connected_to(self, component: str) -> tuple[Connection, ...]:
        return tuple(c for c in self.connections if component in c.components)

    def neighbours(self, component: str) -> tuple[str, ...]:
        out: list[str] = []
        for c in self.connected_to(component):
            a, b = c.components
            out.append(b if a == component else a)
        return tuple(out)


def _strip_comments(source: str) -> str:
    return _LINE_COMMENT_RE.sub("", _BLOCK_COMMENT_RE.sub("", source))


def _parse_declarations(body: str) -> dict[str, Declaration]:
    out: dict[str, Declaration] = {}
    for match in _DECL_RE.finditer(body):
        name = match["name"]
        if name in ("uses", "experiment"):
            continue
        # First occurrence wins: a top-level modifier precedes any nested record such as
        # portsData(diameter=..., height=0), whose keys would otherwise shadow it.
        mods: dict[str, float] = {}
        for m in _NUMERIC_MOD_RE.finditer(match["mods"]):
            mods.setdefault(m["key"], float(m["value"]))
        out[name] = Declaration(name=name, type_name=match["type"], modifiers=mods)
    return out


def _parse_actuator_table(source: str) -> tuple[tuple[float, ...], ...]:
    match = _TABLE_RE.search(source)
    if match is None:
        return ()
    rows = [row.strip() for row in match["body"].split(";") if row.strip()]
    table = tuple(tuple(float(cell) for cell in row.split(",")) for row in rows)
    widths = {len(row) for row in table}
    if len(widths) != 1:
        raise ValueError(f"ragged CombiTimeTable literal: row widths {sorted(widths)}")
    return table


def _parse_experiment(source: str) -> Experiment:
    match = _EXPERIMENT_RE.search(source)
    if match is None:
        raise ValueError("no experiment(...) annotation in the model")
    values = {m["key"]: float(m["value"]) for m in _NUMERIC_MOD_RE.finditer(match["body"])}
    solver = _SOLVER_RE.search(source)
    return Experiment(
        start_time=values.get("StartTime", 0.0),
        stop_time=values["StopTime"],
        tolerance=values.get("Tolerance", 1e-6),
        interval=values.get("Interval", 1.0),
        solver=solver["solver"] if solver else None,
    )


@cache
def load_modelica_model(path: Path | None = None) -> ModelicaModel:
    source_path = path or config.MODELICA_FILE
    if not source_path.is_file():
        raise FileNotFoundError(
            f"Modelica model not found at {source_path}. Run `python scripts/fetch_benchmark.py`."
        )
    raw = source_path.read_text(encoding="utf-8")
    source = _strip_comments(raw)

    header = re.search(r"^\s*model\s+(\w+)", source, re.MULTILINE)
    if header is None:
        raise ValueError(f"{source_path.name}: no `model` header")
    name = header[1]

    equation_at = source.find("\nequation")
    declaration_part = source if equation_at < 0 else source[:equation_at]
    equation_part = "" if equation_at < 0 else source[equation_at:]

    msl = _MSL_RE.search(source)
    return ModelicaModel(
        name=name,
        path=source_path,
        msl_version=msl["version"] if msl else None,
        declarations=_parse_declarations(declaration_part),
        parameters={m["name"]: float(m["value"]) for m in _PARAMETER_RE.finditer(declaration_part)},
        connections=tuple(Connection(a, b) for a, b in _CONNECT_RE.findall(equation_part)),
        experiment=_parse_experiment(raw),
        actuator_table=_parse_actuator_table(declaration_part),
    )
