// Three ways to decide what the plant's actuators do, and one editor behind all of them:
//
//   * the model's own embedded schedule, or the benchmark's matrix;
//   * the commands a recorded run was driven with (copied from the store);
//   * whatever you draw or type here.
//
// The grid is the point: one row per actuator, time across, click or drag to switch a span on.
// Everything writes the same array of {time, V201…P202} rows, which is what the runner takes.

import { api } from "./api.js";

const ACTUATORS = ["V201", "V202", "V203", "V206", "V205", "V204", "V209", "P201", "P202"];
const LABELS = {
  V201: "V201 · drains B201",
  V202: "V202 · drains B202",
  V203: "V203 · drains B203",
  V204: "V204 · fills B201",
  V205: "V205 · fills B202",
  V206: "V206 · fills B203",
  V209: "V209 · to drain X202",
  P201: "P201 · dosing pump",
  P202: "P202 · discharge pump",
};

export class ScheduleEditor {
  /**
   * @param {HTMLElement} root
   * @param {{onChange?: (rows: object[]) => void}} options
   */
  constructor(root, { onChange } = {}) {
    this.root = root;
    this.onChange = onChange;
    this.rows = [];
    this.horizon = 120;
    this.step = 5;
    this.name = "EmbeddedDefault";
    this.notes = [];
    this.dragging = null;
    this.root.addEventListener("pointerup", () => (this.dragging = null));
    this.root.addEventListener("pointerleave", () => (this.dragging = null));
  }

  /** @param {object[]} rows @param {{name?: string, notes?: string[], horizon?: number}} meta */
  load(rows, { name, notes = [], horizon } = {}) {
    this.rows = rows.map((row) => ({
      time: Number(row.time) || 0,
      ...Object.fromEntries(ACTUATORS.map((a) => [a, Number(row[a]) ? 1 : 0])),
    }));
    this.rows.sort((a, b) => a.time - b.time);
    if (name) this.name = name;
    this.notes = notes;
    if (horizon) this.horizon = Math.max(10, Math.ceil(horizon));
    this.render();
    this.onChange?.(this.rows);
  }

  /** The state of every actuator at a moment, which is what a cell shows. */
  stateAt(time) {
    let state = Object.fromEntries(ACTUATORS.map((a) => [a, 0]));
    for (const row of this.rows) {
      if (row.time > time + 1e-9) break;
      state = { ...state, ...Object.fromEntries(ACTUATORS.map((a) => [a, row[a] ?? 0])) };
    }
    return state;
  }

  /** Set one actuator over one grid cell, then fold away rows that changed nothing. */
  set(actuator, time, value) {
    const at = this.rows.find((row) => Math.abs(row.time - time) < 1e-9);
    if (at) {
      at[actuator] = value;
    } else {
      this.rows.push({ ...this.stateAt(time), time, [actuator]: value });
      this.rows.sort((a, b) => a.time - b.time);
    }
    this.compress();
    this.render();
    this.onChange?.(this.rows);
  }

  /** A row that repeats its predecessor is noise; the first row always stays. */
  compress() {
    const kept = [];
    let previous = null;
    for (const row of this.rows) {
      const state = ACTUATORS.map((a) => row[a] ?? 0).join("");
      if (previous !== state || kept.length === 0) kept.push(row);
      previous = state;
    }
    this.rows = kept;
  }

  clear() {
    this.rows = [{ time: 0, ...Object.fromEntries(ACTUATORS.map((a) => [a, 0])) }];
    this.name = "custom";
    this.notes = [];
    this.render();
    this.onChange?.(this.rows);
  }

  toJSON() {
    return this.rows.map((row) => ({ ...row }));
  }

  render() {
    const times = [];
    for (let t = 0; t <= this.horizon; t += this.step) times.push(Number(t.toFixed(3)));

    const grid = document.createElement("div");
    grid.className = "sched-grid";
    grid.style.setProperty("--cols", String(times.length));

    const corner = document.createElement("div");
    corner.className = "sched-corner";
    corner.textContent = "s";
    grid.append(corner);

    for (const time of times) {
      const head = document.createElement("div");
      head.className = "sched-time";
      // Label every other column, so the header stays readable when the step is small.
      head.textContent = times.indexOf(time) % 2 === 0 ? String(Math.round(time)) : "";
      grid.append(head);
    }

    for (const actuator of ACTUATORS) {
      const label = document.createElement("div");
      label.className = "sched-label";
      label.title = LABELS[actuator] ?? actuator;
      label.textContent = actuator;
      grid.append(label);

      for (const time of times) {
        const on = this.stateAt(time)[actuator] >= 0.5;
        const cell = document.createElement("button");
        cell.type = "button";
        cell.className = `sched-cell${on ? " on" : ""}`;
        cell.dataset.actuator = actuator;
        cell.dataset.time = String(time);
        cell.setAttribute("aria-pressed", String(on));
        cell.setAttribute("aria-label", `${actuator} at ${time} s: ${on ? "on" : "off"}`);
        cell.addEventListener("pointerdown", (event) => {
          event.preventDefault();
          this.dragging = on ? 0 : 1;
          this.set(actuator, time, this.dragging);
        });
        cell.addEventListener("pointerenter", () => {
          if (this.dragging !== null) this.set(actuator, time, this.dragging);
        });
        grid.append(cell);
      }
    }

    const summary = document.createElement("p");
    summary.className = "muted small";
    // A replay's first note already counts its switching points; do not say it twice.
    const count = `${this.rows.length} switching point${this.rows.length === 1 ? "" : "s"}`;
    const notes = this.notes.filter((note) => !note.startsWith(count));
    summary.textContent = count + (notes.length ? ` — ${notes.join("; ")}` : "");

    this.root.replaceChildren(grid, summary);
  }
}

/** The run picker for "copy the actuators of a recorded run". */
export async function pickRecordedRun(runs, onPick) {
  const measured = runs.filter((run) => run.origin === "measured");
  const select = document.createElement("select");
  select.append(
    new Option("— choose a recorded run —", ""),
    ...measured.map(
      (run) => new Option(`${run.run_id} · ${run.scenario.replaceAll("_", " ")}`, run.run_id)
    )
  );
  select.addEventListener("change", async () => {
    if (!select.value) return;
    onPick(await api.scheduleOfRun(select.value), select.value);
  });
  return select;
}
