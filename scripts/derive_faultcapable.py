"""Derive ``ModVA_faultcapable.mo`` from the upstream ``ModVA_online_stable.mo``.

The fault-capable model version (design §5.3) adds the hydraulic elements the recorded
faults were induced with, and corrects deviation D4. Everything else is left byte-identical,
which is why this is a derivation script rather than a hand-edited copy: every change below
is one explicit replacement that must match exactly once, so the diff to upstream is exactly
the list in this file.

    python scripts/derive_faultcapable.py           # writes the packaged ModVA_faultcapable.mo
    python scripts/derive_faultcapable.py --check   # exit 1 if the checked-in file is stale

Changes (all defaults reproduce the nominal plant — see docs/benchmark-deviations.md, D8):

1. ``V207`` (pinned ``opening = 1``, sits between B204 and P202) becomes ``V212`` with
   ``opening = V212_opening`` — the clogging handle.
2. ``Tee4`` splits the FI271 -> B204 riser; ``V211`` leads from it through a junction either
   to the new boundary ``X203`` (leakage) or, with ``V211_return_to_B201``, into B201
   (reconfiguration A). The junction's two switch valves are complementary, so the route is
   a plain parameter, not a structural one.
3. ``Tee3`` splits the V203 -> Tee2 line and ``Tee5`` the B204 -> V212 line; ``V210`` joins
   them (reconfiguration B).
4. ``TI261`` and ``TI262`` exchange their connection points (deviation D4).
5. The 30x10 ``CombiTimeTable`` literal becomes a table **read from a file**, so a schedule of
   any length can be run without recompiling the model (deviation D9).
6. Every actuator gains a two-point controller that can take it off the schedule: parameters
   choose a measured signal and a hysteresis band, so a control law is a parameter set rather
   than generated code (deviation D9).

What the benchmark does not give — where along a pipe a tee sits, the length of the crossover,
how much the leak valve throttles — is declared as parameters whose description says so.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from aas_fluid_twin import config  # noqa: E402
from aas_fluid_twin.simulation.control import CONTROL_SIGNALS  # noqa: E402
from aas_fluid_twin.simulation.schedule import ACTUATORS  # noqa: E402

OUTPUT = config.FAULTCAPABLE_MODEL_FILE

#: The file the simulation runner writes the actuator schedule into, next to the compiled
#: model. The name is fixed in the model, so only its contents change from run to run — which
#: is what makes an arbitrary schedule a parameter change rather than a rebuild.
TABLE_FILE = "actuators.txt"
TABLE_NAME = "actuators"

HEADER = """\
// ModVA_faultcapable — derived from the benchmark's ModVA_online_stable.mo by
// scripts/derive_faultcapable.py (aas-fluid-mixing-twin). Do not edit by hand.
//
// Adds the elements the recorded faults were induced with (Tee4/V211/X203, Tee3/Tee5/V210,
// V212 as a parameter), corrects the TI261/TI262 placement (deviation D4) and reads the
// actuator table from "actuators.txt" instead of a 30-row literal (deviation D9). With the
// fault handles at their defaults, and the embedded schedule written to that file, the model
// behaves as the upstream one.
"""

VALVE = (
    "Modelica.Fluid.Valves.ValveLinear {name}(redeclare package Medium = Medium, "
    "dp_nominal = {dp_nominal}, dp_start = 0, m_flow_nominal = 0.1, m_flow_small = 0.000001, "
    "m_flow_start = 0)"
)


def _valve(name: str, dp_nominal: str = "20") -> str:
    """A valve like the model's own V201…V206: linear, 20 Pa at 0.1 kg/s when fully open."""
    return VALVE.format(name=name, dp_nominal=dp_nominal)


PIPE = (
    "Modelica.Fluid.Pipes.StaticPipe {name}(redeclare package Medium = Medium, "
    "diameter = 0.01, height_ab = {height}, length = {length})"
)
#: Junction volume, as the model's own tees use it. A dead-ended branch needs a volume to have
#: a pressure state of its own; ``TeeJunctionIdeal`` leaves one indeterminate.
TEE = (
    "Modelica.Fluid.Fittings.TeeJunctionVolume {name}(redeclare package Medium = Medium, "
    "V = {volume})"
)
#: Same value the upstream model gives Tee1, Tee2, Tee6 and Tee8.
TEE_VOLUME = "0.0000003"


def _tee(name: str, volume: str = TEE_VOLUME) -> str:
    return TEE.format(name=name, volume=volume)


def _clogging_block() -> str:
    return """\
  // --- Clogging handle (ModVA_faultcapable) ------------------------------------------------
  parameter Real V212_opening(min = 0, max = 1) = 1 "Throttle between B204 and P202 (the clogging rig); below 1 reproduces clogging";
"""


def _leak_block(volume: str = TEE_VOLUME) -> str:
    return f"""\
  // --- Leak path and its two destinations (ModVA_faultcapable) -----------------------------
  parameter Real V211_opening(min = 0, max = 1) = 0 "Leak valve Tee4 -> X203; above 0 reproduces leakage";
  parameter Boolean V211_return_to_B201 = false "Reconfiguration A: route the V211 discharge into B201 instead of X203";
  parameter Real Tee4_position(min = 0.05, max = 0.95) = 0.5 "Assumed: where Tee4 sits along the FI271 -> B204 riser, as a fraction of its length";
  parameter Modelica.Units.SI.PressureDifference V211_dp_nominal = 20000 "Assumed: the leak valve is a needle valve, so it drops far more than a process valve (20 Pa) at the same flow";
  {_tee("Tee4", volume)};
  {PIPE.format(name="pipe_FI271_Tee4", height="0.405 * Tee4_position", length="0.57 * Tee4_position")};
  {PIPE.format(name="pipe_Tee4_B204", height="0.405 * (1 - Tee4_position)", length="0.57 * (1 - Tee4_position)")};
  {PIPE.format(name="pipe_Tee4_V211", height="0", length="0.1")};
  {_valve("V211", "V211_dp_nominal")};
  {_tee("Junction_V211", volume)};
  {_valve("V211_to_X203")};
  {_valve("V211_to_B201")};
  {PIPE.format(name="pipe_V211_B201", height="0", length="0.5")};
  Modelica.Fluid.Sources.FixedBoundary X203(redeclare package Medium = Medium, nPorts = 1);
"""


def _crossover_block(volume: str = TEE_VOLUME) -> str:
    return f"""\
  // --- V210 crossover (ModVA_faultcapable) -------------------------------------------------
  parameter Real V210_opening(min = 0, max = 1) = 0 "Crossover Tee3 <-> Tee5; above 0 reproduces reconfiguration B";
  parameter Modelica.Units.SI.Length crossover_length = 0.3 "Assumed: pipe length of the Tee3 -> V210 -> Tee5 crossover";
  parameter Modelica.Units.SI.Length crossover_stub_length = 0.115 "Assumed: pipe length from Tee5 to the V212 throttle";
  {_tee("Tee3", volume)};
  {PIPE.format(name="pipe_V203_Tee3", height="0", length="0.155")};
  {PIPE.format(name="pipe_Tee3_Tee2", height="0", length="0.155")};
  {_tee("Tee5", volume)};
  {PIPE.format(name="pipe_Tee5_V212", height="0", length="crossover_stub_length")};
  {PIPE.format(name="pipe_Tee3_V210", height="0", length="crossover_length / 2")};
  {_valve("V210")};
  {PIPE.format(name="pipe_V210_Tee5", height="0", length="crossover_length / 2")};
"""


CLOGGING_EQUATIONS = "  V212.opening = V212_opening;\n"
LEAK_EQUATIONS = """\
  V211.opening = V211_opening;
  V211_to_X203.opening = if V211_return_to_B201 then 0 else 1;
  V211_to_B201.opening = if V211_return_to_B201 then 1 else 0;
"""
CROSSOVER_EQUATIONS = "  V210.opening = V210_opening;\n"

LEAK_CONNECTIONS = """\
  connect(FI271.port_b, pipe_FI271_Tee4.port_a);
  connect(pipe_FI271_Tee4.port_b, Tee4.port_1);
  connect(Tee4.port_2, pipe_Tee4_B204.port_a);
  connect(pipe_Tee4_B204.port_b, tank_B204.topPorts[1]);
  connect(Tee4.port_3, pipe_Tee4_V211.port_a);
  connect(pipe_Tee4_V211.port_b, V211.port_a);
  connect(V211.port_b, Junction_V211.port_1);
  connect(Junction_V211.port_2, V211_to_X203.port_a);
  connect(V211_to_X203.port_b, X203.ports[1]);
  connect(Junction_V211.port_3, V211_to_B201.port_a);
  connect(V211_to_B201.port_b, pipe_V211_B201.port_a);
  connect(pipe_V211_B201.port_b, tank_B201.topPorts[2]);
"""
CROSSOVER_CONNECTIONS = """\
  connect(V203.port_b, pipe_V203_Tee3.port_a);
  connect(pipe_V203_Tee3.port_b, Tee3.port_1);
  connect(Tee3.port_2, pipe_Tee3_Tee2.port_a);
  connect(pipe_Tee3_Tee2.port_b, Tee2.port_3);
  connect(Tee3.port_3, pipe_Tee3_V210.port_a);
  connect(pipe_Tee3_V210.port_b, V210.port_a);
  connect(V210.port_b, pipe_V210_Tee5.port_a);
  connect(pipe_V210_Tee5.port_b, Tee5.port_3);
  connect(Pipe_B204_V207.port_b, Tee5.port_1);
  connect(Tee5.port_2, pipe_Tee5_V212.port_a);
  connect(pipe_Tee5_V212.port_b, V212.port_a);
"""


def _replace_once(source: str, old: str, new: str, what: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{what}: expected exactly one match, found {count}:\n  {old[:120]!r}")
    return source.replace(old, new)


def _drop_connect(source: str, a: str, b: str) -> str:
    """Remove a connect(...) statement including its annotation and trailing ';'."""
    start = source.index(f"connect({a}, {b})")
    end = source.index(";", start) + 1
    line_start = source.rfind("\n", 0, start) + 1
    line_end = source.find("\n", end) + 1
    return source[:line_start] + source[line_end:]


def _comment_out_declaration(source: str, opener: str, why: str) -> str:
    """Comment out the declaration starting with ``opener`` (up to its closing ';')."""
    marked = _replace_once(source, f"  {opener}", f"  // {why}\n  /* {opener}", opener[:60])
    return _close_comment_after(marked, f"/* {opener}")


def _add_declarations(source: str, block: str) -> str:
    return _replace_once(source, "\nequation\n", "\n" + block + "equation\n", "equation section")


def _add_equations(source: str, block: str) -> str:
    return _replace_once(source, "\nequation\n", "\nequation\n" + block, "equation keyword")


def _add_connections(source: str, block: str) -> str:
    return _replace_once(
        source, "\nend ModVA_faultcapable;", "\n" + block + "end ModVA_faultcapable;", "model end"
    )


def apply_clogging(source: str) -> str:
    """V207, pinned open between B204 and P202, becomes V212 with a settable opening."""
    s = _replace_once(
        source,
        "Modelica.Fluid.Valves.ValveLinear V207(",
        "Modelica.Fluid.Valves.ValveLinear V212(",
        "V207 declaration",
    )
    s = _replace_once(s, "  V207.opening = 1;\n", CLOGGING_EQUATIONS, "V207.opening equation")
    s = _replace_once(
        s,
        "connect(Pipe_B204_V207.port_b, V207.port_a)",
        "connect(Pipe_B204_V207.port_b, V212.port_a)",
        "V207 inlet",
    )
    s = _replace_once(
        s,
        "connect(V207.port_b, Pipe_V207_P202.port_a)",
        "connect(V212.port_b, Pipe_V207_P202.port_a)",
        "V207 outlet",
    )
    return _add_declarations(s, _clogging_block())


def apply_leak(source: str, volume: str = TEE_VOLUME) -> str:
    """Split the FI271 -> B204 riser with Tee4 and hang V211 -> X203 / B201 off it."""
    s = _comment_out_declaration(
        source,
        "Modelica.Fluid.Pipes.StaticPipe pipe_FI271_B204(",
        "pipe_FI271_B204 is replaced by pipe_FI271_Tee4 + Tee4 + pipe_Tee4_B204",
    )
    s = _drop_connect(s, "FI271.port_b", "pipe_FI271_B204.port_a")
    s = _drop_connect(s, "pipe_FI271_B204.port_b", "tank_B204.topPorts[1]")
    s = _replace_once(
        s,
        # tank_B203 shares the level; the component name is what makes this unique.
        "tank_B201(redeclare package Medium = Medium, V0 = 0.0001, crossArea = 0.01431355, "
        "height = 0.22, level_start = 0.15108, nPorts = 1, nTopPorts = 1,",
        "tank_B201(redeclare package Medium = Medium, V0 = 0.0001, crossArea = 0.01431355, "
        "height = 0.22, level_start = 0.15108, nPorts = 1, nTopPorts = 2,",
        "tank_B201 top ports",
    )
    s = _add_declarations(s, _leak_block(volume))
    s = _add_equations(s, LEAK_EQUATIONS)
    return _add_connections(s, LEAK_CONNECTIONS)


def apply_crossover(source: str, volume: str = TEE_VOLUME) -> str:
    """Split the V203 -> Tee2 line at Tee3 and the B204 -> V212 line at Tee5, and join them.

    Tee5 sits between B204 and the V212 throttle, not between V212 and P202. Both are
    consistent with the topology — V212 is undocumented in the P&ID, so which side of it the
    crossover joins is a choice — but a junction volume directly at the pump's inlet makes
    P202's check valve chatter (100 state events in a row around t = 10 s, the run never
    finishes). The line from V212 to P202 is therefore left exactly as upstream.

    Afterwards ``TI262`` still refers to ``pipe_V203_Tee2``, which no longer exists;
    :func:`apply_temperature_placement` re-points it. ``derive`` applies them in that order.
    """
    s = _comment_out_declaration(
        source,
        "Modelica.Fluid.Pipes.StaticPipe pipe_V203_Tee2(",
        "pipe_V203_Tee2 is replaced by pipe_V203_Tee3 + Tee3 + pipe_Tee3_Tee2",
    )
    s = _drop_connect(s, "V203.port_b", "pipe_V203_Tee2.port_a")
    s = _drop_connect(s, "pipe_V203_Tee2.port_b", "Tee2.port_3")
    s = _drop_connect(s, "Pipe_B204_V207.port_b", "V212.port_a")
    s = _add_declarations(s, _crossover_block(volume))
    s = _add_equations(s, CROSSOVER_EQUATIONS)
    return _add_connections(s, CROSSOVER_CONNECTIONS)


def apply_file_backed_table(source: str) -> str:
    """Read the actuator table from a file instead of a literal (deviation D9).

    The literal is 30 rows by construction, and the row count is structural: a longer schedule
    means a recompile. Reading the same table from a file keeps the block and its settings
    identical while making the schedule data rather than code, so replaying a recorded run
    (40-120 switching points) or an authored one costs nothing.

    ``columns`` has to be spelled out: without the literal there is nothing to infer the nine
    actuator outputs from, and ``ActuatorControl.y[2]`` would not exist.

    ``extrapolation`` changes from the block's default ``LastTwoPoints`` to ``HoldLastPoint``.
    The upstream table starts at t = 0.667 s, and before its first row the default
    *extrapolates the first two rows linearly*: V201's opening is -0.073 at t = 0. The nominal
    plant tolerates that; with the V210 crossover open the flow network cannot be solved and
    IDA stops at t = 0.657 s. Holding the first row is what a schedule means.
    """
    start = source.index("Modelica.Blocks.Sources.CombiTimeTable ActuatorControl(table = [")
    end = source.index("annotation(", start)
    declaration = (
        "Modelica.Blocks.Sources.CombiTimeTable ActuatorControl("
        f'tableOnFile = true, tableName = "{TABLE_NAME}", fileName = "{TABLE_FILE}", '
        "columns = 2:10, "
        "extrapolation = Modelica.Blocks.Types.Extrapolation.HoldLastPoint, "
        "timeEvents = Modelica.Blocks.Types.TimeEvents.NoTimeEvents, "
        "smoothness = Modelica.Blocks.Types.Smoothness.ConstantSegments) "
    )
    return source[:start] + declaration + source[end:]


def _control_block() -> str:
    """Declarations for the per-actuator two-point controllers and their signal bus."""
    n = len(ACTUATORS)
    names = ", ".join(f'"{actuator}"' for actuator in ACTUATORS)
    return f"""  // --- Two-point control (ModVA_faultcapable) ----------------------------------------------
  // Each actuator either follows the schedule (mode 0) or switches on one of the measured
  // signals below with hysteresis (mode 1). Everything here is a parameter, so a control law
  // costs a simulation, not a recompile. The bus order is defined in
  // src/aas_fluid_twin/simulation/control.py and generated from it.
  constant String ctrl_actuator[{n}] = {{{names}}} "Actuator per control slot, in table order";
  parameter Integer ctrl_mode[{n}] = zeros({n}) "0 = follow the schedule, 1 = two-point control";
  parameter Integer ctrl_source[{n}] = ones({n}) "Index into ctrl_signal";
  parameter Real ctrl_on_below[{n}] = fill(-Modelica.Constants.inf, {n}) "Switch on below this value (model units)";
  parameter Real ctrl_off_above[{n}] = fill(Modelica.Constants.inf, {n}) "Switch off above this value (model units)";
  parameter Integer ctrl_invert[{n}] = zeros({n}) "1 drives the actuator closed where it would open";
  Real ctrl_signal[{len(CONTROL_SIGNALS)}] "The measured signals a rule may switch on";
  Boolean ctrl_state[{n}](start = fill(false, {n})) "Latched state of each two-point controller";
  Real ctrl_input[{n}] "The bus entry each controller reads (selected without indexing)";
  parameter Modelica.Units.SI.Time ctrl_tau = 0.1 "Measurement lag of the controllers' inputs";
  Real ctrl_measured[{n}] "ctrl_input through a first-order lag of ctrl_tau — a sensor's response, and what keeps the switching condition out of the hydraulic equation system";
  Real ctrl_command[{n}] "What the controller asks of each actuator";
"""


def _control_initial_equations() -> str:
    """The controllers' state at t = 0.

    A ``when`` clause fires on a crossing, never on the initial value, so without this a rule
    "open V204 below 500 ml" on a tank that *starts* at 84 ml would wait for the level to rise
    above 500 ml and fall back — which may never happen. The state starts where the signal
    already is: past the switch-on threshold → on; a rule with only a switch-off threshold and
    the signal still below it → on; inside a hysteresis band → off, the resting state.
    """
    n = len(ACTUATORS)
    return f"""initial equation
  // --- Two-point control: a rule is evaluated at t = 0, not only on a crossing ------------
  for i in 1:{n} loop
    ctrl_measured[i] = ctrl_input[i];
    pre(ctrl_state[i]) = ctrl_measured[i] < ctrl_on_below[i]
      or (ctrl_on_below[i] <= -Modelica.Constants.inf
          and ctrl_measured[i] <= ctrl_off_above[i]);
  end for;
"""


def _control_equations() -> str:
    n = len(ACTUATORS)
    m = len(CONTROL_SIGNALS)
    bus = ";\n    ".join(
        f"ctrl_signal[{i + 1}] = {s.variable}" for i, s in enumerate(CONTROL_SIGNALS)
    )
    return f"""  // --- Two-point control ---------------------------------------------------------------
  {bus};
  for i in 1:{n} loop
    // Not ``ctrl_signal[ctrl_source[i]]``: a parameter used as a subscript is evaluated at
    // compile time and can no longer be overridden per run — every rule then silently read
    // bus entry 1 whatever it named. The sum selects the entry with a plain comparison.
    ctrl_input[i] = sum({{if ctrl_source[i] == k then ctrl_signal[k] else 0.0 for k in 1:{m}}});
    // The condition is on a state, not on the algebraic pressures and flows: a switching
    // condition inside the hydraulic equation system is a when-equation inside a non-linear
    // system, which OpenModelica refuses to compile ("non-linear equations within
    // when-equations"). The lag is a sensor's, and short against the plant's 1.6 s sampling.
    der(ctrl_measured[i]) = (ctrl_input[i] - ctrl_measured[i]) / ctrl_tau;
    when ctrl_measured[i] < ctrl_on_below[i] then
      ctrl_state[i] = true;
    elsewhen ctrl_measured[i] > ctrl_off_above[i] then
      ctrl_state[i] = false;
    end when;
    ctrl_command[i] = if ctrl_state[i] then (if ctrl_invert[i] == 1 then 0 else 1)
                      else (if ctrl_invert[i] == 1 then 1 else 0);
  end for;
"""


def _actuator_equations() -> str:
    """Drive each actuator from the schedule or from its controller.

    The upstream model wires ``ActuatorControl.y[k]`` straight into the actuator with a
    ``connect``; those connections are replaced by equations so the controller can take over.
    """
    targets = {
        "V201": "V201.opening",
        "V202": "V202.opening",
        "V203": "V203.opening",
        "V206": "V206.opening",
        "V205": "V205.opening",
        "V204": "V204.opening",
        "V209": "V209.opening",
        "P201": "P201_Characteristic.u",
        "P202": "P202_Characteristic.u",
    }
    lines = []
    for position, actuator in enumerate(ACTUATORS, start=1):
        lines.append(
            f"  {targets[actuator]} = if ctrl_mode[{position}] == 0 then "
            f"ActuatorControl.y[{position}] else ctrl_command[{position}];"
        )
    return "\n".join(lines) + "\n"


def apply_two_point_control(source: str) -> str:
    """Give every actuator a controller it can be switched over to (deviation D9)."""
    s = source
    for position in range(1, len(ACTUATORS) + 1):
        s = _drop_connect_prefix(s, f"ActuatorControl.y[{position}]")
    s = _add_declarations(s, _control_block())
    s = _replace_once(
        s, "\nequation\n", "\n" + _control_initial_equations() + "equation\n", "equation keyword"
    )
    return _add_equations(s, _control_equations() + _actuator_equations())


def _drop_connect_prefix(source: str, first: str) -> str:
    """Remove the connect whose first argument is ``first`` (its target varies)."""
    marker = f"connect({first}, "
    start = source.index(marker)
    end = source.index(";", start) + 1
    line_start = source.rfind("\n", 0, start) + 1
    line_end = source.find("\n", end) + 1
    return source[:line_start] + source[line_end:]


def apply_temperature_placement(source: str) -> str:
    """Deviation D4: TI261 belongs at the suction manifold, TI262 in B204."""
    s = _replace_once(
        source,
        "connect(TI262.port, pipe_V203_Tee2.port_b)",
        "connect(TI261.port, pipe_Tee3_Tee2.port_b)",
        "TI at the manifold",
    )
    return _replace_once(
        s,
        "connect(TI261.port, Pipe_B204_V207.port_a)",
        "connect(TI262.port, Pipe_B204_V207.port_a)",
        "TI in B204",
    )


def derive(upstream: str) -> str:
    """The upstream model with all four changes applied, in order."""
    s = _replace_once(
        upstream, "model ModVA_online_stable\n", "model ModVA_faultcapable\n", "model header"
    )
    s = _replace_once(s, "end ModVA_online_stable;", "end ModVA_faultcapable;", "model end")
    s = apply_clogging(s)
    s = apply_leak(s)
    s = apply_crossover(s)
    s = apply_temperature_placement(s)
    s = apply_file_backed_table(s)
    s = apply_two_point_control(s)
    return HEADER + s


def _close_comment_after(source: str, opener: str) -> str:
    """Turn the declaration that starts with ``opener`` (ends at the next ';') into a comment."""
    start = source.index(opener)
    end = source.index(";", start) + 1
    return source[:end] + " */" + source[end:]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not config.MODELICA_FILE.is_file():
        print(f"upstream model missing: {config.MODELICA_FILE}", file=sys.stderr)
        return 2
    derived = derive(config.MODELICA_FILE.read_text(encoding="utf-8"))
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.is_file() else ""
        if current != derived:
            print(f"{OUTPUT} is stale — rerun scripts/derive_faultcapable.py", file=sys.stderr)
            return 1
        print(f"{OUTPUT} is up to date")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(derived, encoding="utf-8")
    print(f"wrote {OUTPUT} ({len(derived.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
