// The simulation drawer. Every control in it is generated from the AAS ``SimulationControl``
// submodel — parameter names, defaults, ranges, units and fault roles — so the form cannot
// drift from what the twin actually accepts. Only parameters the operator changed are sent.

import { api } from "./api.js";
import { formatDuration } from "./format.js";

const FAULT_TITLES = {
  leakage: "Leakage",
  clogging: "Clogging",
  "reconfiguration/leak_recirculated_to_B201": "Reconfiguration A — leak back into B201",
  "reconfiguration/B204_crossover_via_V210": "Reconfiguration B — V210 crossover",
};

export class SimulationPanel {
  constructor(elements, { onRunFinished, onStatus }) {
    this.el = elements;
    this.onRunFinished = onRunFinished;
    this.onStatus = onStatus;
    this.config = null;
    this.watching = new Map(); // run_id -> job json
    this.timer = null;

    this.el.form.addEventListener("submit", (event) => this.submit(event));
    this.el.open.addEventListener("click", () => this.open());
    this.el.close.addEventListener("click", () => this.hide());
    this.el.scrim.addEventListener("click", () => this.hide());
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !this.el.drawer.hidden) this.hide();
    });
  }

  async load() {
    try {
      this.config = await api.simulationConfig();
      this.onStatus?.("sim", "up", `${this.config.backend} · ${this.config.models.length} models`);
      this.renderForm();
    } catch (error) {
      this.onStatus?.("sim", "down", error.message);
      this.el.error.textContent = error.message;
      this.el.error.hidden = false;
      this.el.submit.disabled = true;
    }
    await this.refreshRuns();
  }

  open() {
    this.el.drawer.hidden = false;
    this.el.scrim.hidden = false;
    this.el.drawer.querySelector("select, input")?.focus();
    this.refreshRuns();
  }

  hide() {
    this.el.drawer.hidden = true;
    this.el.scrim.hidden = true;
    this.el.open.focus();
  }

  renderForm() {
    const config = this.config;
    this.el.model.replaceChildren(
      ...config.models.map((name) => new Option(name, name, false, name === config.default_model))
    );
    this.el.modelHint.textContent = modelHint(config, this.el.model.value);
    this.el.model.addEventListener("change", () => {
      this.el.modelHint.textContent = modelHint(config, this.el.model.value);
      this.renderHandles();
    });

    const runnable = new Set(config.runnable_schedules);
    this.el.schedule.replaceChildren(
      ...config.schedules.map((schedule) => {
        const option = new Option(
          `${schedule.id_short}${runnable.has(schedule.id_short) ? "" : " (not loaded)"}`,
          schedule.id_short
        );
        option.disabled = !runnable.has(schedule.id_short);
        return option;
      })
    );
    const preferred = config.operation_defaults.schedule;
    if (preferred && runnable.has(preferred)) this.el.schedule.value = preferred;
    this.el.schedule.addEventListener("change", () => this.updateScheduleHint());
    this.updateScheduleHint();

    const stop = Number(config.operation_defaults.stopTime);
    if (Number.isFinite(stop) && stop > 0) this.el.stop.placeholder = `AAS default ${stop}`;
    this.el.mode.textContent =
      config.invoke_mode === "aas"
        ? "invoked as an AAS operation"
        : "posted straight to the runner";

    this.renderHandles();
  }

  updateScheduleHint() {
    const schedule = this.config.schedules.find((s) => s.id_short === this.el.schedule.value);
    this.el.scheduleHint.textContent = schedule
      ? [schedule.name, schedule.row_count ? `${schedule.row_count} rows` : null]
          .filter(Boolean)
          .join(" · ")
      : "";
  }

  renderHandles() {
    const faults = this.config.parameters.filter((p) => p.fault_role);
    const others = this.config.parameters.filter((p) => !p.fault_role);
    this.el.faults.replaceChildren(...faults.map((p) => this.handle(p, true)));
    this.el.parameters.replaceChildren(...others.map((p) => this.handle(p, false)));
    this.el.paramCount.textContent = `(${others.length})`;
  }

  /** One row per parameter: boolean -> checkbox, bounded number -> slider + number, else number. */
  handle(parameter, isFault) {
    const row = document.createElement("div");
    row.className = "handle";
    row.dataset.parameter = parameter.id_short;

    const name = document.createElement("div");
    name.className = "name";
    name.textContent = isFault
      ? (FAULT_TITLES[parameter.fault_role] ?? parameter.fault_role)
      : parameter.id_short;
    const role = document.createElement("div");
    role.className = "role";
    role.textContent = [parameter.name, parameter.unit && parameter.unit !== "1" ? parameter.unit : null]
      .filter(Boolean)
      .join(" · ");
    if (parameter.description) row.title = parameter.description;

    const value = document.createElement("div");
    value.className = "value";

    if (typeof parameter.default === "boolean") {
      const toggle = document.createElement("input");
      toggle.type = "checkbox";
      toggle.checked = parameter.default;
      toggle.dataset.kind = "boolean";
      toggle.addEventListener("change", () => this.markChanged(row, parameter, toggle.checked));
      value.append(toggle);
    } else {
      const number = document.createElement("input");
      number.type = "number";
      number.value = String(parameter.default ?? 0);
      number.step = stepFor(parameter);
      if (parameter.minimum !== null) number.min = String(parameter.minimum);
      if (parameter.maximum !== null) number.max = String(parameter.maximum);
      number.dataset.kind = "number";

      let slider = null;
      if (parameter.minimum !== null && parameter.maximum !== null) {
        slider = document.createElement("input");
        slider.type = "range";
        slider.min = String(parameter.minimum);
        slider.max = String(parameter.maximum);
        slider.step = stepFor(parameter);
        slider.value = number.value;
        slider.setAttribute("aria-label", parameter.id_short);
        slider.addEventListener("input", () => {
          number.value = slider.value;
          this.markChanged(row, parameter, Number(slider.value));
        });
        value.append(slider);
      }
      number.addEventListener("input", () => {
        if (slider) slider.value = number.value;
        this.markChanged(row, parameter, Number(number.value));
      });
      value.append(number);
    }

    row.append(name, value, role);
    return row;
  }

  markChanged(row, parameter, value) {
    const isDefault =
      typeof parameter.default === "boolean"
        ? value === parameter.default
        : Math.abs(value - Number(parameter.default ?? 0)) < 1e-12;
    row.classList.toggle("changed", !isDefault);
  }

  /** Only what differs from the AAS default travels — the model keeps its own defaults. */
  overrides() {
    const out = {};
    for (const row of this.el.drawer.querySelectorAll(".handle.changed")) {
      const parameter = this.config.parameters.find((p) => p.id_short === row.dataset.parameter);
      const input = row.querySelector("input[data-kind]");
      out[row.dataset.parameter] =
        input.dataset.kind === "boolean" ? input.checked : Number(input.value);
      if (!parameter) delete out[row.dataset.parameter];
    }
    return out;
  }

  async submit(event) {
    event.preventDefault();
    this.el.error.hidden = true;
    this.el.submit.disabled = true;
    this.el.submit.textContent = "Starting…";
    const payload = {
      model: this.el.model.value || undefined,
      stop_time: Number(this.el.stop.value),
      output_interval: Number(this.el.interval.value),
      schedule: this.el.schedule.value,
      parameter_overrides: this.overrides(),
      label: this.el.label.value.trim() || undefined,
    };
    try {
      const accepted = await api.startSimulation(payload);
      this.watching.set(accepted.run_id, accepted);
      this.renderRuns();
      this.poll();
    } catch (error) {
      this.el.error.textContent = error.message;
      this.el.error.hidden = false;
    } finally {
      this.el.submit.disabled = false;
      this.el.submit.textContent = "Start run";
    }
  }

  async refreshRuns() {
    try {
      const runs = await api.simulations();
      for (const run of runs.slice(-8)) this.watching.set(run.run_id, run);
      this.renderRuns();
      this.poll();
    } catch {
      /* the runner's own status chip already says it is unreachable */
    }
  }

  poll() {
    const pending = [...this.watching.values()].filter(
      (run) => run.status === "queued" || run.status === "running"
    );
    if (!pending.length) {
      clearTimeout(this.timer);
      this.timer = null;
      return;
    }
    this.onStatus?.("sim", "busy", `${pending.length} run(s) in flight`);
    clearTimeout(this.timer);
    this.timer = setTimeout(async () => {
      for (const run of pending) {
        try {
          const updated = await api.simulation(run.run_id);
          const wasPending = run.status === "queued" || run.status === "running";
          this.watching.set(run.run_id, updated);
          if (wasPending && updated.status === "completed") this.onRunFinished?.(updated);
        } catch {
          /* keep the previous state; the next tick retries */
        }
      }
      this.renderRuns();
      this.poll();
    }, 3000);
  }

  renderRuns() {
    const runs = [...this.watching.values()].sort((a, b) =>
      String(b.submitted_at).localeCompare(String(a.submitted_at))
    );
    this.el.runs.replaceChildren(
      ...runs.slice(0, 8).map((run) => {
        const item = document.createElement("li");
        item.className = "sim-run";
        item.dataset.status = run.status;
        const progress = Math.round((run.progress ?? 0) * 100);
        item.innerHTML = `
          <span class="id" title="${run.run_id}">${run.run_id.replace(/^sim_/, "")}</span>
          <span class="state">${run.status}</span>
          <span class="muted small">${run.model ?? ""}${
            run.record_count ? ` · ${run.record_count} records` : ""
          }${run.wall_time_s ? ` · ${formatDuration(run.wall_time_s)} wall` : ""}</span>
          ${
            run.status === "queued" || run.status === "running"
              ? `<span class="bar"><span style="width:${progress}%"></span></span>`
              : ""
          }`;
        if (run.error) {
          const error = document.createElement("span");
          error.className = "err";
          error.textContent = run.error;
          item.append(error);
        }
        if (run.status === "completed") {
          const open = document.createElement("button");
          open.className = "btn ghost small";
          open.type = "button";
          open.textContent = "Show run";
          open.addEventListener("click", () => this.onRunFinished?.(run, { focus: true }));
          item.append(open);
        }
        return item;
      })
    );
    if (!runs.length) {
      const empty = document.createElement("li");
      empty.className = "muted small";
      empty.textContent = "No simulations yet.";
      this.el.runs.append(empty);
    }
  }
}

function stepFor(parameter) {
  const span =
    parameter.minimum !== null && parameter.maximum !== null
      ? parameter.maximum - parameter.minimum
      : Math.abs(Number(parameter.default ?? 1)) || 1;
  if (span <= 1.001) return "0.05";
  if (span <= 10) return "0.1";
  if (span < 0.01) return "0.0001";
  return "0.01";
}

function modelHint(config, selected) {
  const version = config.model_versions.find((v) =>
    selected.toLowerCase().includes(v.version_id.replace(/^mo-/, "").toLowerCase())
  );
  if (!version) return "";
  const notes = version.notes ?? "";
  return notes.length > 190 ? `${notes.slice(0, 190)}…` : notes;
}
