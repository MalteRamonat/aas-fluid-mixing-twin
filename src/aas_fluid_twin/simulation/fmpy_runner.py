"""Runs the exported FMU with FMPy — the default execution path.

The FMU is FMI 2.0 Co-Simulation, exported by OpenModelica with CVODE compiled in
(``--fmiFlags=s:cvode``), so the co-simulation master only sets the communication step; the
solver, tolerance and event handling live inside the FMU. The ``solver`` field of a request is
therefore informational here — the OpenModelica runner is the one that honours it.

The exported binary is ``linux64`` only: FMPy runs it inside the ``sim-runner`` container.
"""

from __future__ import annotations

import time
from pathlib import Path

from aas_fluid_twin.simulation.runner import SimulationError, SimulationRequest, SimulationResult

__all__ = ["FmpyRunner"]


class FmpyRunner:
    name = "fmpy"

    def __init__(self, fmu_path: Path) -> None:
        import fmpy  # heavy import, only where the runner is actually used

        if not fmu_path.is_file():
            raise FileNotFoundError(f"FMU not found at {fmu_path} — run scripts/export_fmu.py")
        self.fmu_path = fmu_path
        self._fmpy = fmpy
        self._description = fmpy.read_model_description(str(fmu_path))
        if self._description.coSimulation is None:
            raise SimulationError(f"{fmu_path.name} is not a co-simulation FMU")
        variables = self._description.modelVariables
        self._variables = frozenset(v.name for v in variables)
        self._parameters = frozenset(v.name for v in variables if v.causality == "parameter")

    @property
    def model_name(self) -> str:
        return str(self._description.modelName)

    @property
    def fmi_version(self) -> str:
        return str(self._description.fmiVersion)

    def variable_names(self) -> frozenset[str]:
        return self._variables

    def parameter_names(self) -> frozenset[str]:
        return self._parameters

    def run(self, request: SimulationRequest) -> SimulationResult:
        unknown = [v for v in request.outputs if v not in self._variables]
        if unknown:
            raise SimulationError(f"unknown output variables: {unknown[:5]}")
        not_settable = [p for p in request.start_values() if p not in self._parameters]
        if not_settable:
            raise SimulationError(f"not settable in the FMU: {not_settable[:5]}")

        started = time.perf_counter()
        try:
            rows = self._fmpy.simulate_fmu(
                str(self.fmu_path),
                model_description=self._description,
                fmi_type="CoSimulation",
                start_time=request.start_time,
                stop_time=request.stop_time,
                output_interval=request.output_interval,
                start_values=request.start_values(),
                output=list(request.outputs),
                validate=False,
            )
        except Exception as error:  # FMPy raises plain Exceptions from the C API
            raise SimulationError(f"FMU simulation failed: {error}") from error
        elapsed = time.perf_counter() - started

        return SimulationResult(
            time_s=[float(t) for t in rows["time"]],
            variables={v: [float(x) for x in rows[v]] for v in request.outputs},
            runner=self.name,
            model=self.model_name,
            wall_time_s=elapsed,
        )
