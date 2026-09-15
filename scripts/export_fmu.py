"""Export the Modelica model as an FMI 2.0 Model-Exchange + Co-Simulation FMU.

Runs ``omc`` inside the project's OpenModelica image (``docker/openmodelica/Dockerfile``), so
the export needs Docker but no local OpenModelica. Output: ``artifacts/<model>.fmu`` with a
``linux64`` binary. The FMU is the model artefact the SimulationModels submodel (IDTA 02005)
attaches; it is *not* the default execution path — see deviation D7: no export of this model
runs outside OpenModelica with the tooling at hand (the co-simulation build is fixed-step Euler
or needs Sundials at runtime, and FMPy's CVode crashes on the model-exchange build).
``sim-runner`` therefore drives OpenModelica directly; ``SIM_BACKEND=fmpy`` uses this file.

    python scripts/export_fmu.py                 # data/benchmark/simulation/ModVA_online_stable.mo
    python scripts/export_fmu.py path/to/other.mo --model OtherModel
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from aas_fluid_twin import config  # noqa: E402

IMAGE = "modva-twin/openmodelica:local"

MOS_TEMPLATE = """\
loadModel(Modelica, {{"4.0.0"}}); getErrorString();
loadFile("/work/{model_file}"); getErrorString();
r := buildModelFMU({model}, version="2.0", fmuType="me_cs", fileNamePrefix="{model}",
                   platforms={{"static"}});
print("FMU: " + r + "\n"); print(getErrorString());
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("model_file", nargs="?", type=Path, default=config.MODELICA_FILE)
    parser.add_argument("--model", default=None, help="model name (default: file stem)")
    parser.add_argument("--image", default=IMAGE)
    parser.add_argument("--build", action="store_true", help="(re)build the OpenModelica image")
    args = parser.parse_args()

    model_file = args.model_file.resolve()
    if not model_file.is_file():
        print(f"model file not found: {model_file}", file=sys.stderr)
        return 2
    try:
        rel = model_file.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        print(f"{model_file} must lie inside the repository (it is bind-mounted)", file=sys.stderr)
        return 2
    model = args.model or model_file.stem
    artifacts = config.ARTIFACT_DIR
    artifacts.mkdir(parents=True, exist_ok=True)

    if args.build:
        subprocess.run(
            ["docker", "build", "-t", args.image, "-f", "docker/openmodelica/Dockerfile", "."],
            cwd=REPO_ROOT,
            check=True,
        )

    script = artifacts / f"_export_{model}.mos"
    script.write_text(MOS_TEMPLATE.format(model_file=rel, model=model), encoding="utf-8")
    try:
        completed = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{REPO_ROOT}:/work",
                "-w",
                "/work/artifacts",
                args.image,
                "omc",
                script.name,
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env={"MSYS_NO_PATHCONV": "1", **__import__("os").environ},
        )
    finally:
        script.unlink(missing_ok=True)
        for leftover in artifacts.glob(f"{model}_*"):
            if leftover.suffix != ".fmu":
                leftover.unlink()
        (artifacts / "index.html").unlink(missing_ok=True)
        (artifacts / f"{model}.log").unlink(missing_ok=True)

    fmu = artifacts / f"{model}.fmu"
    errors = [line for line in completed.stdout.splitlines() if line.startswith("Error")]
    if completed.returncode != 0 or not fmu.is_file():
        print(completed.stdout[-3000:], file=sys.stderr)
        print(completed.stderr[-1000:], file=sys.stderr)
        print(f"export failed (exit {completed.returncode})", file=sys.stderr)
        return 1
    for line in errors:
        print(line, file=sys.stderr)
    print(f"{fmu} ({fmu.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
