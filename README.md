# AAS Fluid Mixing Twin

An Asset Administration Shell (IEC 63278 / IDTA) representation of the **ModVA fluid mixing
plant** — a real four-tank dosing and mixing plant — together with its Modelica simulation
model, its recorded operational data, and its labelled fault scenarios.

The plant, the data and the model come from
[`MalteRamonat/fluid-mixing-anomaly-benchmark`](https://github.com/MalteRamonat/fluid-mixing-anomaly-benchmark)
(Ramonat et al., *A Fluid Mixing Benchmark for Anomaly Detection in CPS with Real & Simulated
Data*, IEEE Access 2025, [10.1109/ACCESS.2025.3592815](https://doi.org/10.1109/ACCESS.2025.3592815)).

> **Status.** The AAS design is complete ([`design/aas-design.md`](design/aas-design.md)) and
> six of eight implementation steps are done and verified against a running stack: the
> benchmark layer, the AAS builders, the BaSyx stack, the time-series store, the simulation
> runners and the dashboard. Still open: invoking a run through the AAS operation delegation
> end to end, and driving the simulated plant's control logic from the dashboard
> (design §12).

## What this is

- The plant and each of its components as Asset Administration Shells — 16 shells, 40
  submodels, 149 concept descriptions — served from a real Eclipse BaSyx repository rather
  than held in memory.
- Official IDTA submodel templates wherever one fits: Digital Nameplate, Technical Data,
  Handover Documentation, Hierarchical Structures (BoM), Asset Interfaces Description,
  Time Series Data, Provision of Simulation Models.
- The 55 recorded runs exposed through the Time Series Data submodel by **reference** — a
  file attachment and a query endpoint — never as raw values in AAS properties. The values
  themselves live in TimescaleDB, where the `LinkedSegment` endpoint reads them.
- The Modelica model as a linked simulation twin, tied to the plant AAS by a
  `RelationshipElement` and **runnable**: a simulated run is written to the same store and
  appended to the simulation AAS as a segment pair, so it can be compared channel by channel
  against a measured one.
- A dashboard that takes its values from the store and everything *about* those values — the
  names, units, instrument spans and data-quality flags — from the AAS.

## Documentation

| Document | Contents |
| --- | --- |
| [`design/aas-design.md`](design/aas-design.md) | The AAS design: shell topology, submodel choices, semanticId strategy, runtime architecture, and the plan for the remaining steps |
| [`docs/plant-topology.md`](docs/plant-topology.md) | The plant itself: vessels, valves, pumps, instruments, flow paths, fault injection points |
| [`docs/benchmark-deviations.md`](docs/benchmark-deviations.md) | Every difference from the upstream benchmark, with its evidence — including eight defects found and fixed or worked around |
| [`data/fault_annotations.yaml`](data/fault_annotations.yaml) | How each fault was induced and when it started, as recorded by the plant operator |

## Getting started

Requires Python 3.11 or newer.

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"        # Windows: .venv/Scripts/pip

python scripts/fetch_benchmark.py        # pull the benchmark into data/benchmark (~55 MB)
pytest                                   # tests needing the benchmark or Docker skip without them
python scripts/build_aas.py              # -> out/modva-environment.{json,xml}, out/modva.aasx
```

To run the whole twin (needs Docker):

```bash
docker compose up -d                     # BaSyx repository, registries, discovery and web UI,
                                         # TimescaleDB, the twin API and dashboard, OpenModelica
                                         # and the simulation runner. The recorded runs are
                                         # ingested and both model versions compiled at start-up,
                                         # so the stack needs about two minutes to settle.
python scripts/push_to_basyx.py --verify        # server copy == local build, attachments included
python scripts/ingest_timeseries.py --verify    # store copy == the CSVs
```

| Service | URL | What it is |
| --- | --- | --- |
| Dashboard and twin API | <http://localhost:8000> | This project's own UI and `/api/*` |
| BaSyx AAS Web UI | <http://localhost:3000> | Standards-compliant tree browser |
| AAS repository | <http://localhost:8081> | `/shells`, `/submodels`, `/concept-descriptions` |
| AAS registry, submodel registry, discovery | 8082 / 8083 / 8084 | Descriptor registries and the asset-link lookup |
| Simulation runner | <http://localhost:8001> | `/runs`, and the endpoints BaSyx delegates operations to |
| OpenModelica worker | <http://localhost:8010> | Compiles and simulates the two model versions |
| TimescaleDB | `postgresql://modva:modva@localhost:5432/modva` | The runs and their samples |

### The dashboard

Open <http://localhost:8000>. It lists every recorded and simulated run; charts any selection
of channels grouped by unit, with valves and pumps drawn as a timing diagram and fault windows
shaded from the operator's annotations; overlays any second run on the same axes; and starts a
new simulation from a form whose model versions, schedules, fault handles and parameter ranges
are all read from the `SimulationControl` submodel.

Channel names, units, instrument spans and the `unreliable` flag on the pressure channels come
from the AAS — the `AssetInterfacesDescription` joined to its concept descriptions — and from
nowhere else. If the repository is unreachable the dashboard says so instead of drawing
unlabelled lines.

### Simulation

`openmodelica` compiles both model versions at start-up and `sim-runner` executes runs against
them, stores each result next to the recorded data and appends the matching segments to the
simulation AAS:

```bash
curl -X POST http://localhost:8001/runs \
     -H "Content-Type: application/json" \
     -d '{"stop_time": 100, "schedule": "EmbeddedDefault"}'
curl http://localhost:8001/runs          # status; a finished run also appears in /api/runs
```

The same run can be started the AAS-native way, by invoking the `RunSimulation` operation on
the `SimulationControl` submodel: BaSyx forwards it to `sim-runner` through the
`invocationDelegation` qualifier. A simulated run carries the same channel names and units as a
recorded one, so the two overlay directly.

Two model versions are attached to the `SimulationModels` submodel: the benchmark's own
`ModVA_online_stable.mo`, and `ModVA_faultcapable.mo`, which adds the hardware the recorded
faults were induced with (the leak valve V211 with its drain, the V210 crossover, the V212
throttle) and is derived from the upstream file by `scripts/derive_faultcapable.py` — see
[`docs/benchmark-deviations.md`](docs/benchmark-deviations.md) entry D8. An FMI 2.0 export is
attached as well, but it is not the execution path; entry D7 explains why.

### Notes

On Windows, Docker Desktop's WSL 2 backend sizes itself through `%USERPROFILE%\.wslconfig`;
`memory=6GB` and `processors=4` are comfortable for this stack.

The benchmark files are **not** vendored into this repository; `fetch_benchmark.py` retrieves
only what the project actually uses. See [`docs/benchmark-deviations.md`](docs/benchmark-deviations.md)
entry C1.

## Licence

MIT — see [`LICENSE`](LICENSE). The benchmark dataset, documents and simulation model remain
under their own licence in the upstream repository and are not redistributed here.
