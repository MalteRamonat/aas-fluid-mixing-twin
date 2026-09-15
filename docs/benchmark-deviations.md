# Deviations from the upstream benchmark

Every difference between this project and
[`MalteRamonat/fluid-mixing-anomaly-benchmark`](https://github.com/MalteRamonat/fluid-mixing-anomaly-benchmark)
(**[BM]**, branch `main`) is recorded here with its evidence and its reason. Nothing in `[BM]` is
modified silently.

Categories:

- **D** — functional defect in `[BM]` fixed here.
- **C** — deliberate change of representation (no defect; different purpose).
- **N** — note: an upstream inconsistency preserved on purpose.

---

## D1 — Actuator control matrix column mis-mapping

**Status:** fixed here. Not yet reported upstream.

**Evidence**

- `[BM]/Simulation_Model_Control/ActuatorControlMatrix_2024-12-06-16-06-17.csv` header:
  `Time,V201,V202,V203,V204,V205,V206,P201,P202` — **9 columns**.
- `[BM]/simulation/ModVA_online_stable.mo`, connection equations:
  ```
  connect(ActuatorControl.y[1], V201.opening)
  connect(ActuatorControl.y[2], V202.opening)
  connect(ActuatorControl.y[3], V203.opening)
  connect(ActuatorControl.y[4], V206.opening)     <-- V206, not V204
  connect(ActuatorControl.y[5], V205.opening)
  connect(ActuatorControl.y[6], V204.opening)     <-- V204, not V206
  connect(ActuatorControl.y[7], V209.opening)
  connect(ActuatorControl.y[8], P201_Characteristic.u)
  connect(ActuatorControl.y[9], P202_Characteristic.u)
  ```
  ⇒ the `CombiTimeTable` has **10 columns**: `[time, V201, V202, V203, V206, V205, V204, V209, P201, P202]`.
- `[BM]/simulation/simulation_scripts/Simulation_Config.py` confirms the order:
  ```python
  actuator_order_in_modelica = ['V201','V202','V203','V206','V205','V204','V209','P201','P202']
  ```
- `[BM]/simulation/simulation_scripts/Simulation_GUI.py`, `ActuatorMatrixTab.convert_to_dict`:
  ```python
  key = f"ActuatorControl.table[{row_index+1},{col_index+1}]"
  ```
  i.e. CSV column *k* is written into table column *k*, positionally.

**Consequence of the upstream behaviour**

| CSV column | Intended actuator | Actually driven |
| --- | --- | --- |
| 5 | V204 | **V206** |
| 6 | V205 | V205 |
| 7 | V206 | **V204** |
| 8 | P201 | **V209** |
| 9 | P202 | **P201** |
| — | — | **P202 is never driven** |

**Fix here**

Actuator schedules are expressed by actuator *name*, never by position. A single constant

```python
MODELICA_TABLE_COLUMNS = ("time", "V201", "V202", "V203", "V206", "V205", "V204", "V209", "P201", "P202")
```

drives the mapping onto `ActuatorControl.table[i,j]`, and V209 is a first-class schedule column.
A unit test asserts the constant against the `connect(...)` equations parsed out of the `.mo` file,
so the two cannot drift apart.

---

## D2 — Silent 30-row padding / truncation of actuator schedules

**Status:** fixed here.

**Evidence** — `[BM]/simulation/simulation_scripts/Simulation_GUI.py`,
`ActuatorMatrixTab.load_and_process_matrix`:

```python
if df.shape[0] > 30:
    messagebox.showwarning(...)
    df = df.iloc[:30]            # extra switching events discarded
while len(df) < 30:
    df = pd.concat([df, df.iloc[[-1]]], ignore_index=True)   # last row repeated
```

The model's `ActuatorControl.table` is declared with 30 rows, so the dimension itself is real — but
truncating a longer schedule changes the commanded sequence without failing, and padding by
repeating the final row inserts duplicate time stamps into a `CombiTimeTable`.

**Fix here** — the schedule length is validated against the model's table dimension. A schedule with
more rows than the table raises with an explicit message naming both counts. Padding repeats the
final actuator *state* at a strictly increasing time stamp (`stopTime`), never a duplicate time.

---

## D3 — Modelica pipe component names contradict the model's own `connect(...)` equations

**Status:** upstream naming defect. The *wiring* is correct; only the component names are
wrong, so nothing in the model's behaviour changes. Recorded here because anyone reading
the `.mo` file will otherwise draw the wrong topology.

**Evidence** — `ModVA_online_stable.mo`:

```
connect(pipe_Tee7_V206.port_b, V204.port_a)        // pipe named …V206, connects to V204
connect(V204.port_b,          pipe_V206_B201.port_a)
connect(pipe_V206_B201.port_b, tank_B201.topPorts[1])   // so V204 fills B201
connect(V206.port_b,          pipe_V204_B203.port_a)
connect(pipe_V204_B203.port_b, tank_B203.topPorts[1])   // so V206 fills B203
connect(V203.port_b,          pipe_V203_Tee2.port_a)    // P&ID calls this Tee3
```

Three independent sources agree that **V204 fills B201, V205 fills B202, V206 fills B203**:

- the P&ID names these pipes `Pipe_V204_B201`, `Pipe_V205_B202`, `Pipe_V206_B203`;
- the `connect(...)` equations above wire them that way;
- the recorded data settles it empirically — mean level rate per tank while each valve is
  commanded open, over all 33 normal runs (cm/s):

  | Valve | B201 | B202 | B203 | B204 |
  | --- | ---: | ---: | ---: | ---: |
  | V204 | **+5.41** | 0.00 | 0.00 | −2.25 |
  | V205 | 0.00 | **+5.38** | 0.00 | −2.40 |
  | V206 | 0.00 | 0.01 | **+5.19** | −2.44 |

So the mislabelled items are the Modelica pipe *names* `pipe_V206_B201`, `pipe_V204_B203`,
`pipe_Tee7_V206` and `pipe_V203_Tee2`.

**Consequence** — none for simulation results. But it compounds D1: reading the pipe names
suggests the actuator table order is a bug in the *wiring* when it is in fact only a bug in
the *loader*.

**Fix here** — the derived topology in [`plant-topology.md`](plant-topology.md) uses the
P&ID names. Where this project regenerates or extends the Modelica model, the pipe names
are corrected to match the connections.

---

## D5 — Simulation unit conversion produces pressures in the wrong order of magnitude and temperatures in kelvin

**Status:** upstream defect in the mapping table's `Unit_Simulation_variable` column; fixed in
this project's simulation runner.

**Evidence** — `simulation/simulation_datasets_clearnames/ModVA_online_stable_res_20241206_102432_clearnames.csv`,
first data row:

| Column | Value in the clear-name file | What the sensor records |
| --- | ---: | ---: |
| `Pressure_below_B201` | 10 163 621 | ≈ 0 … 3 kPa (gauge) |
| `Tempreature_before_Pump_P201` | 293.17 | ≈ 18 … 37 °C |
| `Tank_B201_Volume` | 2262.49 | ≈ 0 … 2100 ml — this one matches |

`Simulation_Variable_Mapping.xlsx` declares `PI25x.p` as **bar** and `TI26x.T` as **°C**.
`Modelica.Fluid.Sensors.Pressure` outputs **Pa** and `Modelica.Fluid.Sensors.Temperature`
outputs **K**. `Simulation_Utils.rename_and_convert_columns` therefore

- divides the Pa value by the bar→kPa factor 0.01 (i.e. multiplies by 100) — 101 636 Pa
  becomes 10 163 621 in a column labelled kPa, and
- applies no conversion to the temperature (°C → °C), leaving kelvin in a °C column.

A second, smaller issue: the model's pressure sensors read **absolute** pressure
(`p_a_start = 100000`), the plant's transmitters read **gauge** pressure. Even with the right
factor the simulated column would be offset by roughly 100 kPa.

**Consequence** — the published clear-name simulation result is not comparable to the recorded
data on its pressure and temperature columns. Volumes, levels, flows and valve/pump commands are
unaffected.

**Fix here** — the runner converts Pa → kPa (÷1000) and subtracts the model's ambient
reference pressure to obtain gauge pressure, and converts K → °C (−273.15). The upstream
clear-name file is still referenced from the simulation twin's `TimeSeries` submodel — it is a
published artefact — but its segment carries a `DataQuality = "unreliable"` qualifier naming
this deviation, so nobody overlays it against measured data by accident. The mapping table is
left untouched; the correct simulation units are declared in the project's own conversion
table (`simulation/units.py`) with a test that pins them.

---

## D6 — The model's declared solver cannot run the model; the published results were produced with IDA

**Status:** fixed here (the twin runs IDA and says so in the AAS). The `.mo` annotation is
left untouched.

**Evidence**

`ModVA_online_stable.mo` declares

```modelica
annotation(experiment(StartTime = 0, StopTime = 600, Tolerance = 1e-05, Interval = 1),
           __OpenModelica_simulationFlags(lv = "LOG_STATS", s = "cvode", ...));
```

Running exactly that — the unmodified model, the embedded actuator table, `StopTime = 100`,
`Tolerance = 1e-5`, solver `cvode` — terminates after 0.26 s of model time:

```
LOG_STDOUT | warning | While solving non-linear system an assertion failed at time 0.307885.
LOG_STDOUT | info    | ##CVODE## -4 error occurred at time = 0.304045034616122
LOG_STDOUT | info    | model terminate | Integrator failed. | Simulation terminated at time 0.304045
```

Reproduced on **OpenModelica 1.22.1** (the version `[BM]/readme.md` names) and on **1.27.0**,
with and without an analytic Jacobian. `ida` and `dassl` both run the full horizon; IDA needs
≈ 44 s for 100 s of model time, CVODE fails after ≈ 17 s of wall time.

**Which run produced the published results.** `[BM]` ships
`simulation/simulation_datasets/ModVA_online_stable_res_20241206_102432.csv` (and its
clear-name twin). Comparing three candidate configurations against it at every whole second
of the 100 s it covers — all with IDA, 1 s output interval:

| Actuator table | Tank volumes | Valve openings | FI271 / TI261 |
| --- | --- | --- | --- |
| The model's **embedded** `CombiTimeTable` | ≤ 4.6e-4 relative | exact | ≤ 8e-5 relative |
| `ActuatorControlMatrix_2024-12-06-16-06-17.csv` loaded the upstream way (D1) | ≈ 0.95 relative | differ by 1.0 | ≈ 0.53 relative |
| the same CSV loaded by column name | ≈ 0.91 relative | differ by 1.0 | ≈ 0.52 relative |

So the published result is **IDA + the model's own embedded table**; the
`ActuatorControlMatrix` CSV was not involved, in either reading. Since the GUI writes the
solver from `Simulation_Config.solver` rather than from the annotation, the annotation was
simply never exercised.

**Consequence.** Anyone following the model's own annotation gets a run that dies in the
first second and no result file. The provenance of the published result is also not stated
anywhere in `[BM]`.

**Fix here**

- `simulation/runner.TESTED_SOLVER = "ida"` is the single source: it is the default of the
  `RunSimulation` operation's `solver` input, the value of
  `SimulationModels/…/TestedToolSolverAlgorithm/SolverAlgorithm`, and the worker's default.
  `SimulationModels/…/StiffSolverNeeded` carries the reason in its description.
- `tests/test_aas_content.py` pins both facts: the parsed annotation still says `cvode`, the
  AAS says `ida`.
- `tests/test_simulation_integration.py::test_openmodelica_reproduces_the_published_result`
  reproduces the published file from the embedded table with IDA on every run of the live
  suite, so the finding cannot silently rot. Pressures are compared by median deviation — see
  the note in that test: below a closed valve the trapped pressure is solver-path dependent
  and the reference itself dips to 33 kPa absolute at t = 87 s.

---

## D7 — No FMU export of this model runs outside OpenModelica

**Status:** worked around here (the runner drives OpenModelica directly). Not reported
upstream: `[BM]` never exports an FMU, so this is a limitation the twin ran into, not an
upstream defect.

**Evidence** — every FMI 2.0 export of the unmodified model that OpenModelica can produce was
tried and executed with FMPy 0.3 in the `sim-runner` container (linux64):

| Export | Result |
| --- | --- |
| OM 1.27.0, `fmuType="cs"`, `--fmiFlags=s:cvode` | `fmi2ExitInitializationMode` → error: *IF97 medium function tsat called with too low pressure, p = 0 Pa* |
| OM 1.27.0, `cs`, `--fmiFilter=none` / `internal`; `me_cs` in ME and CS mode | same failure |
| OM 1.22.1, `me_cs`, `--fmiFlags=s:cvode` | binary needs `libsundials_cvode.so.5` at run time; not in the FMU |
| OM 1.22.1, `cs`, `--fmiFlags=none` (fixed-step Euler master) | `fmi2DoStep` → error at the first step; min/max assertions violated at t = 0 |
| OM 1.22.1, `me_cs` (default flags), FMPy's own CVode over Model Exchange | segmentation fault during initialisation (24 states, 20 event indicators) |

The 1.27 initialisation failure is a regression in that OpenModelica version: the same model
initialises fine when simulated by `omc` itself, in both 1.22.1 and 1.27.0.

**Consequence.** The originally planned default execution path (FMU + FMPy, C2) is not
available for this model with the tooling at hand.

**Fix here**

- `sim-runner` drives OpenModelica 1.22.1 through `docker/openmodelica/om_worker.py` by
  default (`SIM_BACKEND=openmodelica`). The model is compiled once at container start.
- `scripts/export_fmu.py` still produces `artifacts/ModVA_online_stable.fmu` (FMI 2.0
  ME + CS, OM 1.22.1). It is attached to `SimulationModels` as a second
  `ModelFileVersion` — an FMU is the artefact IDTA 02005 is modelled on, and it is useful to
  whoever has a working FMI toolchain — but the submodel's description says plainly that the
  twin does not execute it.
- `simulation/fmpy_runner.FmpyRunner` is kept and reachable as `SIM_BACKEND=fmpy`, so the
  moment an export works the path is one environment variable away.

---

## D8 — Fault-capable model version: the recorded faults have no hydraulic representation upstream

**Status:** added here as a separate model version. The upstream `.mo` is not modified.

**Evidence.** Every recorded fault was induced with a piece of hardware that is absent from
`ModVA_online_stable.mo` (see `docs/plant-topology.md` §5): the leak valve **V211** on the
P201 → B204 riser with its drain **X203**, the crossover **V210** between the suction
manifold and P202's inlet, and the clogging throttle **V212** between B204 and P202.
Simulating a leakage or clogging run against the upstream model is therefore impossible, and
any "fault" produced by tweaking unrelated parameters would be a surrogate.

**Fix here** — `scripts/derive_faultcapable.py` derives
`src/aas_fluid_twin/resources/modelica/ModVA_faultcapable.mo` from the upstream file by a fixed list of
replacements, each of which must match exactly once, so the diff is exactly this list:

1. `V207` — pinned to `opening = 1` in the upstream equation section and sitting in exactly the
   B204 → P202 line where the physical throttle was installed — becomes **`V212`**, driven by
   the parameter `V212_opening` (default `1` = fully open). *Clogging.*
2. **`Tee4`** splits the `FI271` → B204 riser at `Tee4_position`; from it `pipe_Tee4_V211` →
   **`V211`** (`V211_opening`, default `0` = closed) → `Junction_V211` → two complementary
   switch valves into either the new boundary **`X203`** or, via `pipe_V211_B201`, B201's
   second top port. *Leakage, and reconfiguration A (`V211_return_to_B201`, default `false`).*
3. **`Tee3`** splits the V203 → Tee2 line, **`Tee5`** the B204 → V212 line, and **`V210`**
   (`V210_opening`, default `0`) joins them through `pipe_Tee3_V210` + `pipe_V210_Tee5`.
   *Reconfiguration B.* Tee5 sits on the B204 side of the throttle, leaving the V212 → P202
   pipe exactly as upstream: with the junction directly at the pump's inlet, P202's check valve
   chatters (100 state events in a row around t = 10 s) and the run never finishes. Which side
   of V212 the crossover joins is undocumented — V212 is not in the P&ID at all — so both
   placements are consistent with the topology and this one integrates.
4. `TI261` and `TI262` exchange their connection points, so the model matches the tags (D4).

All handles default to the nominal plant, so with the defaults the model is the upstream model
hydraulically. The added junctions are `TeeJunctionVolume` with the same 0.3 ml the upstream
model gives Tee1, Tee2, Tee6 and Tee8: a dead-ended branch (a closed V211 or V210) needs a
junction with a volume to have a pressure state of its own — with the volume-free
`TeeJunctionIdeal` the integration fails (IDA residual failure at t ≈ 35 s).

**Assumptions, declared in the model as parameters with their reason in the description:**

| Parameter | Default | Why it is an assumption |
| --- | --- | --- |
| `Tee4_position` | `0.5` | `[BM]` gives the riser's length (0.57 m) and height (0.405 m) but not where the leak tee sits on it. The parameter splits both proportionally. |
| `crossover_length` | `0.3 m` | The V210 crossover is not in the P&ID and its pipe run was never measured. |
| `crossover_stub_length` | `0.115 m` | Distance from Tee5 to the V212 throttle, likewise undrawn. |
| `V211_dp_nominal` | `20 000 Pa` | The leak valve is a needle valve. Left at the 20 Pa the model's process valves use, opening it drains the riser at several kg/s and the integration fails within a second. The recorded runs do not state the leak rate, so this is the knob to turn when fitting one. |

Sensor errors and the stirring error are deliberately **not** added: they are measurement
faults, not hydraulic ones (design §5.3).

`python scripts/derive_faultcapable.py --check` fails if the checked-in file is no longer
what the script produces from the current upstream model.

---

## N1 — CSV column typo `Tempreature_before_Pump_P201` preserved

**Evidence** — the column appears with this spelling in all 55 files in
`[BM]/data/ModVA_Datasets/` and in the `Name` column of
`[BM]/simulation/simulation_scripts/Simulation_Variable_Mapping.xlsx` (row 18, `Sensor_ID` = `TI261`).

**Decision** — preserved verbatim wherever it is used as a machine key: the AAS
`AssetInterfacesDescription` property `key`, the `TimeSeries/Metadata/Record` element `idShort`,
and the `channel` column in the time-series store. Correcting it would break the join between the
AAS, the CSV files and the database, and would diverge from every published artefact of the
benchmark.

The correct spelling is used in human-readable positions only: AAS `displayName`, the AID `title`,
and dashboard labels.

---

## N2 — Duplicate `Sensor_ID` in the variable mapping table

**Evidence** — `Simulation_Variable_Mapping.xlsx`:

| ID | Sensor_ID | Name |
| --- | --- | --- |
| 38 | `Level_B203` | `Tank_B203_level_calculated_via_VolumeB203` |
| 39 | `Level_B203` | `Tank_B204_level_calculated_via_VolumeB204` |

Row 39 describes B204 (`Simulation_variable_name = tank_B204.level`,
`Simulation_initialization_parameters = tank_B204.level_start`) but repeats the B203 sensor id.

**Decision** — the derived signal dictionary corrects row 39 to `Level_B204`. The `Name` column
(the CSV column, which is already correct) is untouched, so no data join is affected. A test pins
this correction so it stays visible.

---

## D4 — TI261 and TI262 are swapped in the P&ID and in the Modelica model

**Status:** confirmed by the plant author. **TI261 is at Tee2** (suction manifold, upstream of
P201); **TI262 is in B204**. Fixed here; the simulation pipeline defect below is real.

**Evidence**

| Source | TI261 | TI262 | Correct? |
| --- | --- | --- | --- |
| Plant author | suction manifold at Tee2 | in B204 | — (ground truth) |
| `Simulation_Variable_Mapping.xlsx`, `Name` column | `Tempreature_before_Pump_P201` | `Temperature_in_B204` | correct |
| `Simulation_Variable_Mapping.xlsx`, `Simulation_initialization_parameters` | `pipe_V203_Tee2.T_start` | `tank_B204.T_start` | correct |
| `PID-Diagram.pdf` | drawn on **B204** | drawn at **Tee2** | swapped |
| `ModVA_online_stable.mo` | `connect(TI261.port, Pipe_B204_V207.port_a)` → B204 | `connect(TI262.port, pipe_V203_Tee2.port_b)` → Tee2 | swapped |

The mapping table is internally consistent and correct on both of its columns. The P&ID
drawing carries the labels the wrong way round, and the Modelica model inherited that error.

**Consequence — simulated temperatures land in the wrong columns.**
`Simulation_Utils.rename_and_convert_columns` renames by the mapping table, so the model
variable `TI261.T` — which in the model is B204's temperature — is written to the column
`Tempreature_before_Pump_P201`, and `TI262.T` (the suction manifold) is written to
`Temperature_in_B204`. Every `*_clearnames.csv` therefore has its two temperature columns
exchanged relative to the recorded data. The magnitude is small in the published runs
(temperatures barely vary within a 600 s run) but the defect is systematic, and it would
corrupt any real-vs-simulation temperature comparison.

**Fix here**

- The recorded data and the mapping table are **left untouched** — they are correct. No CSV
  column name changes, no `Sensor_ID` changes.
- In the `ModVA_faultcapable` model version (D8), the `TI261` and `TI262` connection points are
  exchanged so the model matches the tags. `tests/test_faultcapable.py` reads the derived
  model's `connect(...)` graph and asserts both placements, so a future re-swap — upstream or
  in the derivation — fails loudly instead of silently.
- The P&ID label swap is recorded here; the published PDF is not modified.

---

## N5 — Pressure-derived level channels carried but marked unreliable

**Evidence** — stated by the plant author: PI251–PI254 measure static pressure only and do
not account for dynamic pressure, so the readings are wrong whenever fluid is moving past
the sensor. The eight `..._level_calculated_via_PI25x...` channels and the four
`Pressure_below_B20x` channels inherit that limitation. This is also why the author never
used them, and therefore why `dataset_0` missing them is harmless (see N3).

**Decision** — the channels are kept, not dropped, and carry an explicit quality
qualifier in the AAS (`DataQuality = "unreliable"` plus the reason). Dropping them would
lose information; publishing them unqualified would invite misuse. The tank volume
channels are derived from the **ultrasonic** LI sensors, not from pressure, and are sound.

---

## N3 — `dataset_0_normal_behaviour.csv` reduced schema

**Evidence** — 42 columns versus 50 for the other 54 files; the eight `…_via_PI25x…` derived level
columns are absent. `[BM]/scripts/Preprocess_datasets.py` drops any file whose columns differ from
`dataset_1`, so `dataset_0` is absent from `scaled_minmax/`, `scaled_standard/` and every published
result.

**Decision** — **resolved: keep it.** Confirmed by the plant author: the eight missing
channels are the pressure-derived levels, which were never used because the pressure
sensors are unreliable on this plant (see N5). `dataset_0` is therefore a fully valid
normal run. It is flagged `schema_variant = "reduced"` in the store and carries a
corresponding marker on its `TimeSeries` segment, so it is never silently mixed into an
analysis that assumes all 48 channels.

---

## C1 — Time-series data is not re-published, only referenced

The benchmark CSVs are not vendored into this repository. `scripts/fetch_benchmark.py` downloads
them into the git-ignored `data/benchmark/`. The AAS references them as
`TimeSeries/Segments/ExternalSegment/File` attachments uploaded to the BaSyx repository, and as
`LinkedSegment/Endpoint` queries into TimescaleDB.

Reason: the project brief forbids storing raw time-series as AAS Properties, and re-hosting ~40 MB
of a published dataset adds no value while creating a second source of truth.

## C2 — Simulation executed through a containerised OpenModelica worker

`[BM]` drives the model through OMPython + a Tk GUI with hard-coded Windows paths
(`Simulation_Config.py`). This project keeps OMPython but puts it behind an HTTP worker
(`docker/openmodelica/om_worker.py`) that compiles the model once at container start and
simulates on request, and behind a `SimulationRunner` protocol so the execution engine is
swappable. The model is also exported to FMI 2.0 (`scripts/export_fmu.py`) and attached to
the `SimulationModels` submodel, because an FMU is a legitimate
`ModelFileVersion/DigitalFile` under IDTA 02005 — which is explicitly modelled on FMI — but
it is not the execution path: see D7 for why no export of this model runs under FMPy.

Reason: reproducibility (no local toolchain, no GUI, no absolute paths) and a documented
contract between the twin and whatever runs the physics.

## C3 — OpenModelica version

`[BM]/readme.md` states OpenModelica 1.22.1, and this project pins exactly that
(`openmodelica/openmodelica:v1.22.1-ompython`, plus MSL 4.0.0 installed at image build time
because the model's `uses`-annotation demands it). 1.27.0 was tried first and rejected: it
cannot export a usable FMU of this model (D7), while 1.22.1 reproduces the published
simulation result (D6). The image also adds `cmake`, which the FMU export's build step needs
and the base image lacks, and runs as a non-root user because `omc` refuses to act as a
server when running as root.

## C4 — Anomaly-detection framework not carried over

`[BM]/src/AD_Benchmark/`, `configs/` and `results/Comparison/` are out of scope. The evaluation
results may later be surfaced as a KPI submodel, but no model training is reproduced here.
