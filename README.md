# AAS Fluid Mixing Twin

A running digital twin of the **ModVA fluid mixing plant** — a real four-tank dosing and
mixing plant — built on the Asset Administration Shell (IEC 63278 / IDTA). The plant, its
55 recorded runs, its labelled fault scenarios and its Modelica model come from the published
benchmark [`MalteRamonat/fluid-mixing-anomaly-benchmark`](https://github.com/MalteRamonat/fluid-mixing-anomaly-benchmark)
(Ramonat et al., *A Fluid Mixing Benchmark for Anomaly Detection in CPS with Real & Simulated
Data*, IEEE Access 2025, [10.1109/ACCESS.2025.3592815](https://doi.org/10.1109/ACCESS.2025.3592815)).

`docker compose up` gives you, on one machine:

- **The plant as Asset Administration Shells** — 16 shells, 40 submodels, 149 concept
  descriptions — served by an Eclipse BaSyx repository, built from official IDTA templates
  wherever one exists, and browsable in the standard BaSyx web UI.
- **Its recorded data** — 55 runs, ~930 000 samples, 47 channels — in a TimescaleDB store,
  reachable through the Time Series Data submodel and through a dashboard.
- **A simulation twin that runs.** The Modelica model is compiled in an OpenModelica service
  and started by invoking an AAS *operation*. A simulated run lands in the same store and the
  same AAS as the recorded ones, so the two overlay channel by channel.
- **Control of the simulated plant from the dashboard**: replay a recorded run's actuator
  commands, draw a schedule on a timing grid, switch on the fault hardware (leak, clogging,
  crossover), or hand an actuator to a two-point control rule.

---

## What it looks like

The dashboard on a recorded leakage run. The sidebar lists every recorded and simulated run;
the charts group channels by unit, draw valves and pumps as a timing diagram, and shade the
fault window from the operator's annotation. Channel names, units and instrument spans are
read from the AAS, not hard-coded.

![The dashboard showing dataset_10_leakage: tank volumes and the actuator timing diagram, with the leak window shaded](docs/images/dashboard-run.png)

A recorded normal run with its own replay overlaid (dashed): the model was given the
commands the plant's actuators received, starting from the recorded tank levels.

![A measured run and its simulated replay on the same axes](docs/images/dashboard-overlay.png)

The *New simulation* drawer, generated from the `SimulationControl` submodel. Here the
actuators of `dataset_10_leakage` have been copied into the schedule grid, and V204 has been
taken off the schedule by a level rule.

![The simulation drawer: model version, schedule grid filled from a recorded run, a control rule, fault handles](docs/images/dashboard-simulate.png)

The same repository in the Eclipse BaSyx web UI — the plant shell, its submodels, and the
`TimeSeries` submodel with its 110 segments (two per recorded run).

![The BaSyx AAS web UI showing the plant shell and its TimeSeries submodel](docs/images/basyx-web-ui.png)

---

## Architecture

Ten containers (one of them the one-shot ingest), one `docker compose up`. Solid arrows are
the paths a request takes; dashed arrows are what happens once at start-up.

```mermaid
flowchart LR
    subgraph build["Build (once, on the host)"]
        BM[("benchmark files<br/>CSV · xlsx · .mo · PDF")]
        AASX[["out/modva.aasx<br/>16 shells · 40 submodels"]]
        BM -.->|"build_aas.py"| AASX
    end

    subgraph basyx["Eclipse BaSyx"]
        ENV["aas-env<br/>AAS + submodel repository<br/>:8081"]
        REG["registries · discovery<br/>:8082 · :8083 · :8084"]
        GUI["aas-web-ui<br/>:3000"]
    end

    subgraph data["Data"]
        TSDB[("TimescaleDB<br/>run · sample · sample_label<br/>:5432")]
    end

    subgraph twin["Twin services"]
        API["api<br/>dashboard + /api/*<br/>:8000"]
        RUNNER["sim-runner<br/>/invoke/run · /runs<br/>:8001"]
        OM["openmodelica<br/>OMC 1.22.1, both model versions<br/>:8010"]
    end

    BROWSER(["browser"])

    AASX -.->|"preload"| ENV
    BM -.->|"ingest"| TSDB
    ENV --- REG
    GUI --> ENV

    BROWSER --> API
    BROWSER --> GUI
    API -- "channels, parameters,<br/>schedules, signals" --> ENV
    API -- "series" --> TSDB
    API -- "invoke RunSimulation" --> ENV
    ENV -- "invocationDelegation" --> RUNNER
    RUNNER -- "compile once,<br/>simulate per run" --> OM
    RUNNER -- "samples" --> TSDB
    RUNNER -- "segments + CSV,<br/>Runs entry" --> ENV
```

Everything the twin knows *about* the plant is in the AAS; everything it has *measured* or
*simulated* is in the store; the dashboard and the runner are stateless glue between the two.

---

## The parts, one by one

### The benchmark layer (`src/aas_fluid_twin/benchmark/`)

The single source of plant facts, derived from the benchmark files rather than typed in:

- **Signal dictionary** — the 47 rows of `Simulation_Variable_Mapping.xlsx`: CSV column,
  OPC UA node, unit, Modelica variable, role. The CSV column name is the join key across the
  AAS, the store and the dashboard, typo and all (`Tempreature_before_Pump_P201`); corrected
  spelling appears only in display names. Every correction to what the table says is declared
  in code and tested.
- **Dataset index** — the 55 recordings, their scenario labels (`normal_behaviour`, `leakage`,
  `clogging`, … , `manual_mode`), their schema variant and their usability.
- **Fault annotations** — [`data/fault_annotations.yaml`](data/fault_annotations.yaml): how
  each fault was induced (which valve, how far) and *when*, as recorded by the plant operator.
  The benchmark itself labels whole files; the twin labels points in time.
- **Plant topology** — [`docs/plant-topology.md`](docs/plant-topology.md): vessels, valves,
  pumps, instruments and flow paths, reconstructed from the P&ID, the Modelica connection
  graph and the recorded data, and cross-checked between the three.

### The Asset Administration Shells (`src/aas_fluid_twin/aas/`)

Built offline with `basyx-python-sdk` and written as JSON, XML and a complete AASX package
(`python scripts/build_aas.py`). Sixteen shells:

| Shell | Submodels |
| --- | --- |
| **Plant** `ModVA_FluidMixingPlant` | `Nameplate`, `TechnicalData`, `HandoverDocumentation`, `HierarchicalStructures`, `AssetInterfacesDescription`, `TimeSeries`, `FaultScenarioCatalogue`, `TwinLinkage` |
| **Simulation twin** `ModVA_online_stable` | `SimulationModels`, `TimeSeries`, `SimulationControl`, `TwinLinkage` |
| **14 components** B201–B204, P201, P202, V201–V206, V209, R201 | `Nameplate`, `TechnicalData` |

What the submodels carry, and where it comes from:

| Submodel | Template | Content |
| --- | --- | --- |
| `Nameplate` | IDTA 02006 Digital Nameplate | Operating institution, product designation; component manufacturers and types recovered from the vendor datasheets |
| `TechnicalData` | IDTA 02003 | Tank geometry, pump characteristics, valve ratings — read from the Modelica model at build time |
| `HandoverDocumentation` | IDTA 02004 | The P&ID, the PLC program export and every datasheet, attached and classified |
| `HierarchicalStructures` | IDTA 02011 | The bill of material: tanks, pumps, valves (including the manual ones), instruments, with `HasPart` relations to the component shells |
| `AssetInterfacesDescription` | IDTA 02017 | The OPC UA interface: one `PropertyAffordance` per channel with node id, unit, instrument span and a `DataQuality` qualifier (the pressure sensors are marked unreliable, with the reason) |
| `TimeSeries` | IDTA 02008 | One `ExternalSegment` (the CSV as an attachment) **and** one `LinkedSegment` (endpoint + query into the store) per run — the values are referenced, never copied into properties |
| `SimulationModels` | IDTA 02005 | The two Modelica model versions and an FMI 2.0 export as attachments, solver, tolerance, ports, environment |
| `FaultScenarioCatalogue` | custom | Every scenario with its induction method, affected components (references into the BoM) and its fault events with onset times |
| `TwinLinkage` | custom | `IsSimulatedBy` between plant and twin, plus one annotated relationship per signal pair: sensor channel ↔ model variable, with both units and the conversion |
| `SimulationControl` | custom | The operations `RunSimulation` and `GetRunStatus`, the parameter set with defaults and ranges, the fault handles, the stored schedules, the control signals, and a log of every run |

Every custom element has a semantic id backed by a concept description with an IEC 61360
data specification, so the custom parts are as machine-readable as the template-based ones.
A conformance test checks every template-based element against the vendored IDTA template
index; a round-trip test checks that JSON, XML and AASX read back identically.

### The BaSyx stack (`docker-compose.yml`, `docker/basyx/`)

Eclipse BaSyx `2.0.0-milestone-15`: the AAS environment (shell, submodel and concept
description repository), the two registries, discovery, and the web UI. The environment
**preloads `out/modva.aasx`** at start, so the repository is a pure function of the build;
`scripts/push_to_basyx.py` re-pushes everything through the REST API and verifies the server
copy against the local build byte for byte, attachments included.

Operation delegation is switched on: the `RunSimulation` operation carries an
`invocationDelegation` qualifier, and the environment forwards an invocation to
`sim-runner`. A client therefore needs nothing but the AAS to command the twin.

### The time-series store (`src/aas_fluid_twin/store/`)

TimescaleDB with three tables: `run`, `sample` (a hypertable in long format —
`run_id, ts, t_rel_s, channel, value`) and `sample_label` (the point-in-time scenario label).
Long format because recorded runs have 47 or 41 channels and simulated ones 29, and the two
must sit side by side. `scripts/ingest_timeseries.py` loads the 55 recordings once (the
`ingest` container does it at start-up) and can verify the stored copy against the CSVs.

The `LinkedSegment` of every run in the `TimeSeries` submodel points at
`GET /api/timeseries?run_id=…` on this store, so a consumer that only reads the AAS can
still reach the values.

### The simulation (`src/aas_fluid_twin/simulation/`, `docker/openmodelica/`)

- **`openmodelica`** runs OpenModelica 1.22.1 — the version the benchmark was made with — and
  compiles both model versions once at start-up (about two minutes). Per run it writes the
  actuator schedule to a file, sets the parameters and simulates; no recompile.
- **Two model versions.** `ModVA_online_stable.mo` is the benchmark's own. `ModVA_faultcapable.mo`
  is derived from it by `scripts/derive_faultcapable.py` and adds the hardware the recorded
  faults were induced with — the leak valve V211 with its drain, the V210 crossover, the V212
  throttle — as parameters, plus the file-backed schedule and a two-point controller per
  actuator. With every handle at its default it behaves as the upstream model.
- **`sim-runner`** validates a request against the model it targets (a fault handle asked of
  the upstream version is refused, not ignored), runs it, converts the result to the plant's
  channel names and units, writes it to the store, and appends a segment pair and a run entry
  to the simulation AAS. It speaks the BaSyx delegation contract on `/invoke/*` and plain JSON
  on `/runs`.
- **Verified against the benchmark**: the published simulation result is reproduced to within
  5·10⁻⁴ relative on the tank volumes. Two findings on the way — the model's own `cvode`
  setting cannot run it and no FMU export of it runs outside OpenModelica — are recorded in
  [`docs/benchmark-deviations.md`](docs/benchmark-deviations.md) (D6, D7).

### The API and dashboard (`src/aas_fluid_twin/api/`, `src/aas_fluid_twin/web/`)

FastAPI serves `/api/*` and the dashboard, a vanilla-JavaScript page with a vendored chart
library — no build step, no CDN. The API reads channel metadata from the
`AssetInterfacesDescription` and its concept descriptions, and the simulation form from
`SimulationControl`; if the repository is unreachable it says so rather than drawing
unlabelled lines. The dashboard is a client of the AAS, not a second source of truth.

---

## How the parts work together

What happens when you press *Start run* in the drawer:

```mermaid
sequenceDiagram
    participant U as Dashboard
    participant A as api
    participant E as aas-env (BaSyx)
    participant R as sim-runner
    participant O as openmodelica
    participant S as TimescaleDB

    U->>A: POST /api/simulations (schedule, rules, handles)
    A->>R: POST /runs/validate
    R-->>A: 204 — or 422 with the reason
    A->>E: invoke SimulationControl/RunSimulation
    E->>R: POST /invoke/run (delegated)
    R-->>E: runId, status
    E-->>A: OperationResult
    A-->>U: 202 accepted
    R->>O: POST /simulate (actuators.txt, parameters)
    O-->>R: time series of the model variables
    R->>S: write run + samples
    R->>E: append Simulated_/Linked_ segments, CSV, Runs entry
    loop until finished
        U->>A: GET /api/simulations/{id}
        A->>R: GET /runs/{id} (GetRunStatus on the AAS reports the same state)
    end
    U->>A: GET /api/timeseries?run_id=…
    A->>S: read samples
```

The validation call exists because BaSyx relays only the status code of a failed delegation,
not the delegate's message; validating first lets the dashboard show *why* a request was
refused while the command itself still travels the AAS path.

Four ways to decide what the actuators do, all through the same operation:

| Source | What it is |
| --- | --- |
| Stored schedule | The 30-row table embedded in the benchmark's model, or the benchmark's control matrix |
| Replay of a recorded run | The commands the plant's actuators were given, compressed to switching points, with that run's initial tank levels |
| Drawn schedule | A timing grid in the drawer — click or drag a span per actuator |
| Control rule | *Keep V204 open while tank B201 volume is below 500 ml, switch back above 2000 ml* — a two-point controller that takes the actuator off the schedule for the whole run |

A replay is open loop: the model's flows differ slightly from the plant's, so a replayed
command sequence can drive a tank to a limit the real one never reached. That is what the
rules are for — the same replay under a level rule completes and holds the level.

---

## Getting started

Requires Python 3.11 or newer and, for the full stack, Docker (on Windows: Docker Desktop with
WSL 2; `memory=6GB` and `processors=4` in `%USERPROFILE%\.wslconfig` are comfortable).

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"        # Windows: .venv/Scripts/pip

python scripts/fetch_benchmark.py        # pull the benchmark into data/benchmark (~55 MB)
python scripts/build_aas.py              # -> out/modva-environment.{json,xml}, out/modva.aasx
pytest                                   # tests needing the benchmark or Docker skip without them
```

```bash
docker compose up -d                     # preloads the AASX, ingests the recordings, compiles
                                         # both model versions — allow two to four minutes
python scripts/push_to_basyx.py --verify        # server copy == local build, attachments included
python scripts/ingest_timeseries.py --verify    # store copy == the CSVs
pytest -m integration                    # round trips against the running stack
```

| Service | URL | What it is |
| --- | --- | --- |
| Dashboard and twin API | <http://localhost:8000> | This project's UI and `/api/*` |
| BaSyx AAS web UI | <http://localhost:3000> | Standards-compliant browser of the same repository |
| AAS repository | <http://localhost:8081> | `/shells`, `/submodels`, `/concept-descriptions` |
| AAS registry, submodel registry, discovery | 8082 / 8083 / 8084 | Descriptor registries and the asset-link lookup |
| Simulation runner | <http://localhost:8001> | `/runs`, `/health`, and the endpoints BaSyx delegates operations to |
| OpenModelica worker | <http://localhost:8010> | Compiles and simulates the two model versions |
| TimescaleDB | `postgresql://modva:modva@localhost:5432/modva` | The runs and their samples |

A run without the dashboard:

```bash
curl -X POST http://localhost:8001/runs -H "Content-Type: application/json" \
     -d '{"stop_time": 100, "schedule": "EmbeddedDefault", "parameter_overrides": {"V211_opening": 0.3}}'
curl http://localhost:8001/runs          # status; a finished run also appears in /api/runs
```

The benchmark files are not vendored into this repository; `fetch_benchmark.py` retrieves what
the project uses. The dashboard image and the runner image install the package, so after
editing `src/` run `docker compose build api sim-runner` and `docker compose up -d`.

---

## Repository layout

```
src/aas_fluid_twin/
  benchmark/     signal dictionary, dataset index, annotations, Modelica and topology parsers
  aas/           semantic ids, template index, one builder per submodel, environment, I/O
  client/        thin REST client for the BaSyx repository API
  store/         TimescaleDB schema, ingest, verify, the store protocol
  simulation/    schedules, control rules, unit conversion, runners, the sim-runner service
  api/           FastAPI: time series, AAS-sourced metadata, simulation proxy
  web/           the dashboard (no build step)
  resources/     vendored IDTA template indexes, instrument data, the derived Modelica model
scripts/         fetch_benchmark, build_aas, push_to_basyx, ingest_timeseries,
                 derive_faultcapable, export_fmu, vendor_idta_templates
docker/          BaSyx configuration and the api, sim-runner and openmodelica images
design/          the AAS design document
docs/            plant topology, benchmark deviations, images
data/            fault annotations (the benchmark itself is fetched, not vendored)
tests/           227 tests; those marked integration need the running stack
```

## Documentation

| Document | Contents |
| --- | --- |
| [`design/aas-design.md`](design/aas-design.md) | The AAS design: shell topology, submodel choices, semanticId strategy, runtime architecture, the control-logic design |
| [`docs/plant-topology.md`](docs/plant-topology.md) | The plant: vessels, valves, pumps, instruments, flow paths, fault injection points |
| [`docs/benchmark-deviations.md`](docs/benchmark-deviations.md) | Every difference from the upstream benchmark with its evidence — including the defects found in the benchmark's tooling and model, and what was changed here |
| [`data/fault_annotations.yaml`](data/fault_annotations.yaml) | How each fault was induced and when it started, as recorded by the plant operator |

## Known limits

- The pressure sensors PI251–PI254 are unreliable on this plant (static pressure only) and
  are carried with a `DataQuality = unreliable` qualifier rather than dropped.
- The benchmark's mapping table declares the ultrasonic level channels
  (`…level_calculated_via_LI21x`) in centimetres; they are millimetres, as the plant's author
  confirmed. The twin carries them as **mm** through a declared correction (deviation D10) and
  the *Tank levels* preset shows them; the table itself is left as published.
- The model's B201 never drains below about 84 ml — a rule "while volume above 1 ml" can never
  fire. Two-point rules need a band between their thresholds; the drawer proposes 5 %.
- Rules that fight each other (fill and drain the same tank) switch every second or two once
  the level reaches the band, and a 600 s run then takes several times the nominal three
  minutes. The worker stops any simulation after 15 minutes of wall time and says why.
- The OPC UA server of the real plant is no longer reachable; the interface is described in
  the AAS but marked as not live.

## Licence

MIT — see [`LICENSE`](LICENSE). The benchmark dataset, documents and simulation model remain
under their own licence in the upstream repository and are not redistributed here.
