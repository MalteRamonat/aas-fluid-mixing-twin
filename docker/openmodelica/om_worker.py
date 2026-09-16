"""OpenModelica worker: a minimal HTTP front for OMPython.

Runs inside ``openmodelica/openmodelica:<version>-ompython`` (Python 3.10, hence no project
imports — standard library + OMPython only). Every configured model is compiled once at
start-up; a request selects one by name, sets parameters, simulates and returns the requested
variables as JSON.

    GET  /health     -> {"status": "UP", "models": [...], "default_model": ..., "omc": ...}
    GET  /variables[?model=<name>]
                     -> {"model": ..., "variables": [...], "parameters": [...]}
    POST /simulate  <- {"model": "ModVA_faultcapable", "schedule": [[t, v1..v9], ...],
                        "start_values": {...}, "start_time": 0, "stop_time": 600,
                        "output_interval": 1, "tolerance": 1e-5, "solver": "ida",
                        "outputs": [...]}
                    -> {"model": ..., "time": [...], "variables": {name: [...]},
                        "wall_time_s": ...}

``OM_MODELS`` configures what is compiled: ``name=path`` entries separated by commas, the
first one being the default. Each model gets its own build directory and its own OMC session;
compilation takes ~25–40 s per model, so the container is slow to become healthy and fast
afterwards.
"""

import json
import os
import sys
import tempfile
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from OMPython import ModelicaSystem

DEFAULT_MODELS = (
    "ModVA_online_stable=/work/data/benchmark/simulation/ModVA_online_stable.mo,"
    "ModVA_faultcapable=/work/resources/modelica/ModVA_faultcapable.mo"
)
PORT = int(os.environ.get("OM_WORKER_PORT", "8010"))

#: How a model takes its actuator schedule. ModVA_faultcapable reads a table from this file
#: (deviation D9), so any number of rows costs nothing; the upstream model has a fixed 30x10
#: literal and takes the same numbers as parameters. The worker picks per model.
TABLE_FILE = "actuators.txt"
TABLE_NAME = "actuators"
TABLE_ROWS = 30

_lock = threading.Lock()  # OMC sessions are not thread-safe; one simulation at a time


def parse_models(spec):
    """``"name=path,name=path"`` -> ``[(name, path), ...]``, order preserved."""
    out = []
    for entry in spec.split(","):
        entry = entry.strip()
        if not entry:
            continue
        name, _, path = entry.partition("=")
        if not path:
            raise SystemExit(f"OM_MODELS entry {entry!r} is not name=path")
        out.append((name.strip(), path.strip()))
    if not out:
        raise SystemExit("OM_MODELS is empty")
    return out


def build_model(name, path):
    # OMPython 3.x (OpenModelica 1.22) builds in the working directory and takes options as
    # "key=value" strings; 4.x also accepts dicts. Both are handled below.
    build_dir = tempfile.mkdtemp(prefix=f"modva-om-{name}-")
    os.chdir(build_dir)
    # OpenModelica >= 1.25 fails to generate the analytic Jacobian of the non-linear
    # pipe/valve loops ("Jacobian A contains non-linear components"); numeric is fine.
    options = ["-d=-NLSanalyticJacobian"]
    try:
        system = ModelicaSystem(
            fileName=path, modelName=name, lmodel=["Modelica"], commandLineOptions=options
        )
    except TypeError:  # OMPython 3.x wants one string
        system = ModelicaSystem(
            fileName=path,
            modelName=name,
            lmodel=["Modelica"],
            commandLineOptions=" ".join(options),
        )
    defaults = dict(system.getParameters())
    if not defaults:
        # OMPython reports a failed build only on stdout; the object still exists, with nothing
        # in it. Served as a model, every request would fail with "not settable".
        raise RuntimeError(f"{name} did not build — see the omc errors above")
    return {
        # A model whose table is a literal exposes it as parameters; a file-backed one does not.
        "table_is_literal": "ActuatorControl.table[1,1]" in defaults,
        "name": name,
        "path": path,
        "system": system,
        "build_dir": build_dir,
        "dead": False,
        "defaults": defaults,
        # Parameters changed since the build; they are restored before the next simulation.
        "dirty": set(),
        "parameters": frozenset(defaults),
        "variables": frozenset(q["name"] for q in system.getQuantities()),
    }


def _kv(options):
    return [f"{key}={value}" for key, value in options.items()]


def _write_table_file(directory, rows):
    """Write the schedule where the model's CombiTimeTable expects it, in Modelica's format."""
    path = os.path.join(directory, TABLE_FILE)
    lines = ["#1", f"double {TABLE_NAME}({len(rows)},{len(rows[0])})"]
    lines += [" ".join(f"{float(value):.10g}" for value in row) for row in rows]
    with open(path, "w") as handle:
        handle.write("\n".join(lines) + "\n")
    return path


def _table_parameters(rows):
    """The same schedule as ``ActuatorControl.table[i,j]``, padded to the literal's 30 rows."""
    if len(rows) > TABLE_ROWS:
        raise ValueError(
            f"this model's actuator table holds {TABLE_ROWS} rows and the schedule has "
            f"{len(rows)}; run it on a model that reads its table from a file"
        )
    padded = [list(map(float, row)) for row in rows]
    while len(padded) < TABLE_ROWS:
        padded.append([padded[-1][0] + 1.0, *padded[-1][1:]])
    return {
        f"ActuatorControl.table[{i},{j}]": value
        for i, row in enumerate(padded, start=1)
        for j, value in enumerate(row, start=1)
    }


def _as_modelica(value, default):
    """Format a JSON value the way the parameter's own default is written.

    The service sends every override as a number, but a Boolean parameter such as
    ``V211_return_to_B201`` has to be set as ``true``/``false``.
    """
    if str(default).strip().lower() in ("true", "false"):
        return "true" if float(value) else "false"
    return float(value)


def _isolated(model, start_values):
    """The values to set so this run sees only its own overrides.

    ``setParameters`` sticks to the session, so a run that does not mention a parameter would
    otherwise inherit whatever the previous run left there — a nominal run after a leakage run
    would silently leak. Everything touched since the build and not overridden now is put back
    to the model's own default.
    """
    defaults = model["defaults"]
    values = {
        name: _as_modelica(value, defaults.get(name, 0)) for name, value in start_values.items()
    }
    for name in model["dirty"] - set(values):
        values[name] = defaults[name]
    model["dirty"] = model["dirty"] | set(start_values)
    return values


def _omc_version(system):
    if hasattr(system, "sendExpression"):
        return str(system.sendExpression("getVersion()"))
    return str(system.getconn.sendExpression("getVersion()"))


MODELS = {}
for _name, _path in parse_models(os.environ.get("OM_MODELS", DEFAULT_MODELS)):
    _started = time.perf_counter()
    MODELS[_name] = build_model(_name, _path)
    print(
        f"om-worker: built {_name} in {time.perf_counter() - _started:.0f} s "
        f"({len(MODELS[_name]['parameters'])} parameters)",
        flush=True,
    )
DEFAULT_MODEL = next(iter(MODELS))
OMC_VERSION = _omc_version(MODELS[DEFAULT_MODEL]["system"])


def _model(name):
    model = MODELS.get(name or DEFAULT_MODEL)
    if model is None:
        raise ValueError(f"unknown model {name!r}; compiled: {sorted(MODELS)}")
    return model


#: A simulation that crashes can take the model's OMC session with it, and every later request
#: on that session then fails with this message. The session is rebuilt on the next request
#: instead — a recompile of ~40 s, which beats a worker that stays broken until restarted.
_SESSION_LOST = "No connection with OMC"

#: A simulation that runs longer than this is killed. A chattering event loop (100 state
#: events per step) never finishes on its own, and a client that gave up does not stop the
#: executable — one such run blocked the worker for twenty minutes.
MAX_WALL_S = float(os.environ.get("OM_MAX_WALL_S", "900"))


def _simulate_within(model, system, result_file, simflags, limit_s):
    """Run ``system.simulate`` and kill the executable if it exceeds ``limit_s``."""
    failure = []

    def target():
        try:
            if simflags:
                system.simulate(resultfile=result_file, simflags=simflags)
            else:
                system.simulate(resultfile=result_file)
        except Exception as error:  # re-raised on the calling thread
            failure.append(error)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(limit_s)
    if thread.is_alive():
        # OMPython runs the executable through a shell; the build directory is unique per model.
        os.system(f"pkill -f '{model['build_dir']}/{model['name']} ' >/dev/null 2>&1")
        thread.join(30.0)
        raise RuntimeError(
            f"simulation exceeded {limit_s:.0f} s of wall time and was stopped; a chattering "
            "event loop (an actuator switching back and forth at its threshold) is the usual "
            "cause"
        )
    if failure:
        raise failure[0]


def _live_model(name):
    model = _model(name)
    if not model["dead"]:
        return model
    print(f"om-worker: rebuilding the OMC session for {model['name']}", flush=True)
    rebuilt = build_model(model["name"], model["path"])
    MODELS[model["name"]] = rebuilt
    return rebuilt


def simulate(payload):
    model = _model(payload.get("model"))
    start_values = dict(payload.get("start_values", {}))
    schedule = payload.get("schedule") or []
    if schedule and model["table_is_literal"]:
        start_values.update(_table_parameters(schedule))
    unknown = [k for k in start_values if k not in model["parameters"]]
    if unknown:
        raise ValueError(f"not settable in {model['name']}: {unknown[:5]}")
    outputs = list(payload.get("outputs", []))
    missing = [v for v in outputs if v not in model["variables"]]
    if missing:
        raise ValueError(f"unknown output variables in {model['name']}: {missing[:5]}")

    started = time.perf_counter()
    with _lock:
        model = _live_model(model["name"])
        system = model["system"]
        # Each model builds in its own directory and OMPython runs the executable from the
        # process's cwd, so the cwd is restored before every simulation.
        os.chdir(model["build_dir"])
        try:
            if schedule and not model["table_is_literal"]:
                _write_table_file(model["build_dir"], schedule)
            values = _isolated(model, start_values)
            if values:
                system.setParameters(_kv(values))
            system.setSimulationOptions(
                _kv(
                    {
                        "startTime": float(payload.get("start_time", 0.0)),
                        "stopTime": float(payload.get("stop_time", 600.0)),
                        "stepSize": float(payload.get("output_interval", 1.0)),
                        "tolerance": float(payload.get("tolerance", 1e-5)),
                        "solver": str(payload.get("solver", "ida")),
                    }
                )
            )
            result_file = os.path.join(model["build_dir"], "result.mat")
            # Extra runtime flags for the simulation executable (``-noRestart`` and the like);
            # the request may add to the service-wide default.
            simflags = " ".join(
                part
                for part in (os.environ.get("OM_SIMFLAGS", ""), str(payload.get("simflags", "")))
                if part.strip()
            )
            _simulate_within(model, system, result_file, simflags, MAX_WALL_S)
            columns = system.getSolutions(["time", *outputs], resultfile=result_file)
        except Exception as error:
            if _SESSION_LOST in str(error):
                model["dead"] = True
            raise
    elapsed = time.perf_counter() - started
    time_s = [float(t) for t in columns[0]]
    variables = {
        name: [float(x) for x in column] for name, column in zip(outputs, columns[1:], strict=True)
    }
    return {
        "model": model["name"],
        "time": time_s,
        "variables": variables,
        "wall_time_s": elapsed,
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/health":
            self._send(
                200,
                {
                    "status": "UP",
                    "models": sorted(MODELS),
                    "default_model": DEFAULT_MODEL,
                    "omc": OMC_VERSION,
                },
            )
            return
        if path != "/variables":
            self._send(404, {"error": "not found"})
            return
        requested = None
        for part in query.split("&"):
            key, _, value = part.partition("=")
            if key == "model" and value:
                requested = value
        try:
            model = _model(requested)
        except ValueError as error:
            self._send(404, {"error": str(error)})
            return
        self._send(
            200,
            {
                "model": model["name"],
                "variables": sorted(model["variables"]),
                "parameters": sorted(model["parameters"]),
            },
        )

    def do_POST(self):
        if self.path != "/simulate":
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            self._send(200, simulate(payload))
        except ValueError as error:
            self._send(422, {"error": str(error)})
        except Exception as error:  # report, do not crash the worker
            traceback.print_exc()
            self._send(500, {"error": f"{type(error).__name__}: {error}"})

    def log_message(self, fmt, *args):
        sys.stderr.write("om-worker: %s\n" % (fmt % args))


if __name__ == "__main__":
    print(f"om-worker: {sorted(MODELS)} built, default {DEFAULT_MODEL}, serving on :{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
