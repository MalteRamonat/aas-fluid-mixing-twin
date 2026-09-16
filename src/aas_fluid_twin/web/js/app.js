// Wiring: run list -> selection -> series -> charts, plus the simulation drawer and the
// status chips. State lives in one object; every render reads it and nothing else.

import { api } from "./api.js";
import { ChartBoard } from "./charts.js";
import {
  PRESETS,
  formatDuration,
  formatNumber,
  formatTimestamp,
  groupChannels,
  scenarioLabel,
} from "./format.js";
import { SimulationPanel } from "./simulate.js";

const $ = (id) => document.getElementById(id);

const state = {
  runs: [],
  filtered: [],
  channels: [],
  channelIndex: new Map(),
  selected: null,
  selectedChannels: new Set(),
  runChannels: new Set(),
  overlayId: "",
  series: null,
  overlaySeries: null,
  origin: "",
  scenario: "",
  search: "",
  aas: null,
};

const board = new ChartBoard($("charts"));

// ---------- theme ----------

function applyTheme(theme) {
  const dark =
    theme === "dark" ||
    (theme === "auto" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("modva-theme", theme);
  if (state.series) drawCharts();
}

$("theme-toggle").addEventListener("click", () => {
  const current = localStorage.getItem("modva-theme") ?? "auto";
  applyTheme(current === "dark" ? "light" : current === "light" ? "auto" : "dark");
});
window
  .matchMedia("(prefers-color-scheme: dark)")
  .addEventListener("change", () => applyTheme(localStorage.getItem("modva-theme") ?? "auto"));
applyTheme(localStorage.getItem("modva-theme") ?? "auto");

// ---------- status chips ----------

function setStatus(service, tone, title) {
  const chip = document.querySelector(`.chip[data-service="${service}"]`);
  if (!chip) return;
  chip.dataset.state = tone;
  chip.title = title ?? "";
}

function banner(message, tone = "error") {
  const element = $("banner");
  if (!message) {
    element.hidden = true;
    return;
  }
  element.hidden = false;
  element.dataset.tone = tone;
  element.textContent = message;
}

// ---------- runs ----------

function renderScenarioFilter() {
  const scenarios = [...new Set(state.runs.map((r) => r.scenario))].sort();
  $("scenario-filter").replaceChildren(
    ...scenarios.map((scenario) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `pill${state.scenario === scenario ? " is-active" : ""}`;
      button.textContent = scenarioLabel(scenario);
      button.addEventListener("click", () => {
        state.scenario = state.scenario === scenario ? "" : scenario;
        renderScenarioFilter();
        renderRunList();
      });
      return button;
    })
  );
}

function renderRunList() {
  const needle = state.search.toLowerCase();
  state.filtered = state.runs.filter((run) => {
    if (state.origin && run.origin !== state.origin) return false;
    if (state.scenario && run.scenario !== state.scenario) return false;
    if (!needle) return true;
    return (
      run.run_id.toLowerCase().includes(needle) ||
      run.scenario.toLowerCase().includes(needle) ||
      (run.note ?? "").toLowerCase().includes(needle)
    );
  });

  const list = $("run-list");
  list.replaceChildren(
    ...state.filtered.map((run) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = `run-item${run.usable ? "" : " unusable"}`;
      item.dataset.origin = run.origin;
      item.dataset.runId = run.run_id;
      item.role = "option";
      item.setAttribute("aria-selected", String(run.run_id === state.selected?.run_id));
      item.innerHTML = `
        <span class="rail"></span>
        <span>
          <span class="name">${run.run_id}</span>
          <span class="sub">
            <span class="badge" data-label="${run.anomaly_label}">${scenarioLabel(run.scenario)}</span>
            <span>${formatDuration(run.duration_s)}</span>
            <span>${run.record_count} rec</span>
          </span>
        </span>
        <span class="muted small">${run.origin === "simulated" ? "sim" : ""}</span>`;
      item.addEventListener("click", () => selectRun(run.run_id));
      return item;
    })
  );
  $("run-count").textContent = `${state.filtered.length} of ${state.runs.length} runs`;
  renderOverlayOptions();
}

function renderOverlayOptions() {
  const select = $("overlay-select");
  const current = select.value;
  select.replaceChildren(
    new Option("none", ""),
    ...state.runs
      .filter((run) => run.run_id !== state.selected?.run_id)
      .map((run) => new Option(`${run.run_id} · ${scenarioLabel(run.scenario)}`, run.run_id))
  );
  select.value = state.runs.some((r) => r.run_id === current) ? current : "";
}

// ---------- channels ----------

function renderChannelPicker() {
  const needle = $("channel-search").value.trim().toLowerCase();
  const visible = state.channels.filter(
    (channel) =>
      !needle ||
      channel.channel.toLowerCase().includes(needle) ||
      channel.title.toLowerCase().includes(needle)
  );
  const groups = groupChannels(visible);

  $("channel-groups").replaceChildren(
    ...groups.map((group) => {
      const section = document.createElement("div");
      section.className = "channel-group";
      const heading = document.createElement("h4");
      heading.textContent = group.unit ? `${group.title} · ${group.unit}` : group.title;
      section.append(heading);
      for (const channel of group.channels) {
        const absent = state.runChannels.size > 0 && !state.runChannels.has(channel.channel);
        const option = document.createElement("label");
        option.className = `channel-option${absent ? " absent" : ""}`;
        option.title = absent
          ? `${channel.channel} — not recorded in this run`
          : [channel.definition, channel.quality_reason].filter(Boolean).join(" ");
        const box = document.createElement("input");
        box.type = "checkbox";
        box.checked = state.selectedChannels.has(channel.channel);
        box.disabled = absent;
        box.addEventListener("change", () => {
          if (box.checked) state.selectedChannels.add(channel.channel);
          else state.selectedChannels.delete(channel.channel);
          persistChannels();
          loadSeries();
        });
        const label = document.createElement("span");
        label.className = "label";
        label.textContent = channel.title;
        option.append(box, label);
        if (channel.quality !== "good") {
          const dot = document.createElement("span");
          dot.className = "dot-warn";
          dot.title = channel.quality_reason ?? `quality: ${channel.quality}`;
          option.append(dot);
        }
        const unit = document.createElement("span");
        unit.className = "u";
        unit.textContent = channel.unit ?? (channel.data_type === "boolean" ? "0/1" : "");
        option.append(unit);
        section.append(option);
      }
      return section;
    })
  );
  updateChannelSummary();
}

function updateChannelSummary() {
  const total = state.channels.length;
  const chosen = state.selectedChannels.size;
  $("channel-summary").textContent = total
    ? `${chosen} of ${total} selected`
    : "AAS metadata unavailable";
}

function renderPresets() {
  $("presets").replaceChildren(
    ...PRESETS.map((preset) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "pill";
      button.textContent = preset.label;
      button.addEventListener("click", () => {
        const wanted = preset.channels(state.channels);
        state.selectedChannels = new Set(
          wanted.filter((name) => state.runChannels.size === 0 || state.runChannels.has(name))
        );
        persistChannels();
        renderChannelPicker();
        loadSeries();
      });
      return button;
    }),
    Object.assign(document.createElement("button"), {
      type: "button",
      className: "pill",
      textContent: "Clear",
      onclick: () => {
        state.selectedChannels.clear();
        persistChannels();
        renderChannelPicker();
        loadSeries();
      },
    })
  );
}

const persistChannels = () =>
  localStorage.setItem("modva-channels", JSON.stringify([...state.selectedChannels]));

// ---------- run detail + series ----------

async function selectRun(runId, { scrollIntoView = false } = {}) {
  const summary = state.runs.find((run) => run.run_id === runId);
  if (!summary) return;
  state.selected = summary;
  for (const item of document.querySelectorAll(".run-item")) {
    item.setAttribute("aria-selected", String(item.dataset.runId === runId));
    if (scrollIntoView && item.dataset.runId === runId) {
      item.scrollIntoView({ block: "nearest" });
    }
  }
  renderOverlayOptions();

  try {
    const [detail, channels] = await Promise.all([api.run(runId), api.runChannels(runId)]);
    state.selected = detail;
    state.runChannels = new Set(channels);
  } catch (error) {
    banner(error.message);
    return;
  }
  renderRunHead();
  if (!state.selectedChannels.size) {
    const volumes = PRESETS[0].channels(state.channels);
    state.selectedChannels = new Set(volumes.filter((name) => state.runChannels.has(name)));
  }
  renderChannelPicker();
  await loadSeries();
}

function renderRunHead() {
  const run = state.selected;
  if (!run) return;
  $("run-title").innerHTML = `${run.run_id}
    <span class="badge" data-label="${run.anomaly_label}">${scenarioLabel(run.scenario)}</span>
    ${run.usable ? "" : '<span class="badge quality">unusable</span>'}`;
  $("run-subtitle").textContent =
    run.note ?? (run.origin === "simulated" ? "Simulated run." : "Recorded on the plant.");

  const windows = run.fault_windows ?? [];
  const meta = [
    ["Origin", run.origin],
    ["Started", formatTimestamp(run.started_at)],
    ["Duration", formatDuration(run.duration_s)],
    ["Records", `${run.record_count}`],
    ["Schema", run.schema_variant],
  ];
  if (windows.length) {
    meta.push([
      windows.length === 1 ? "Fault window" : "Fault windows",
      windows
        .map((w) =>
          w.end_s === null || w.end_s === undefined
            ? `from ${w.onset_s} s`
            : `${w.onset_s}–${w.end_s} s`
        )
        .join(", "),
    ]);
  }
  if (run.params?.runner) {
    meta.push(["Runner", `${run.params.runner} · ${run.params.solver ?? ""}`]);
    if (run.params.model) meta.push(["Model", String(run.params.model)]);
    const overrides = run.params.parameter_overrides ?? {};
    if (Object.keys(overrides).length) {
      meta.push([
        "Overrides",
        Object.entries(overrides)
          .map(([key, value]) => `${key}=${value}`)
          .join(", "),
      ]);
    }
  }
  if (state.aas?.web_ui) {
    const submodel =
      run.origin === "simulated"
        ? state.aas.submodels.simulation_time_series
        : state.aas.submodels.plant_time_series;
    const href = `${state.aas.web_ui}/submodels/${btoa(submodel)
      .replaceAll("+", "-")
      .replaceAll("/", "_")
      .replace(/=+$/, "")}`;
    meta.push(["In the AAS", `<a href="${href}" target="_blank" rel="noopener">TimeSeries ↗</a>`]);
  }

  $("run-meta").replaceChildren(
    ...meta.map(([term, value]) => {
      const block = document.createElement("dl");
      block.className = "meta";
      block.innerHTML = `<dt>${term}</dt><dd>${value}</dd>`;
      return block;
    })
  );
}

async function loadSeries() {
  const run = state.selected;
  const channels = [...state.selectedChannels];
  $("chart-toolbar").hidden = !run;
  if (!run || !channels.length) {
    board.clear();
    $("empty-state").hidden = false;
    $("empty-state").querySelector("p").textContent = run
      ? "No channels selected — pick some above."
      : "Pick a run on the left to plot it.";
    return;
  }
  $("empty-state").hidden = true;
  try {
    state.series = await api.timeseries(run.run_id, channels);
    state.overlaySeries = state.overlayId
      ? await api.timeseries(state.overlayId, channels).catch(() => null)
      : null;
  } catch (error) {
    banner(`Could not load ${run.run_id}: ${error.message}`);
    return;
  }
  banner(null);
  drawCharts();
}

function drawCharts() {
  const channels = [...state.selectedChannels]
    .map((name) => state.channelIndex.get(name))
    .filter(Boolean);
  const groups = groupChannels(channels);
  board.render(groups, {
    primary: state.series,
    overlay: state.overlaySeries,
    run: state.selected,
    overlayRun: state.runs.find((r) => r.run_id === state.overlayId) ?? null,
  });
}

// ---------- toolbar ----------

$("overlay-select").addEventListener("change", (event) => {
  state.overlayId = event.target.value;
  loadSeries();
});
$("reset-zoom").addEventListener("click", () => board.resetZoom());
$("copy-link").addEventListener("click", async (event) => {
  if (!state.selected) return;
  const url = new URL(
    api.timeseriesUrl(state.selected.run_id, [...state.selectedChannels]),
    location.origin
  ).toString();
  try {
    await navigator.clipboard.writeText(url);
    flash(event.target, "Copied");
  } catch {
    flash(event.target, url);
  }
});
$("download-csv").addEventListener("click", () => downloadCsv());

function flash(button, text) {
  const original = button.textContent;
  button.textContent = text;
  setTimeout(() => (button.textContent = original), 1400);
}

function downloadCsv() {
  if (!state.series) return;
  const names = Object.keys(state.series.channels);
  const header = ["t_rel_s", "timestamp", "label", ...names];
  const lines = [header.join(",")];
  state.series.t_rel_s.forEach((t, index) => {
    const row = [
      t,
      state.series.timestamps[index],
      state.series.labels[index],
      ...names.map((name) => {
        const value = state.series.channels[name][index];
        return value === null || value === undefined ? "" : value;
      }),
    ];
    lines.push(row.join(","));
  });
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${state.selected.run_id}.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
}

// ---------- filters, panel, keyboard ----------

for (const button of document.querySelectorAll(".pill[data-origin]")) {
  button.addEventListener("click", () => {
    state.origin = button.dataset.origin;
    for (const other of document.querySelectorAll(".pill[data-origin]")) {
      other.classList.toggle("is-active", other === button);
    }
    renderRunList();
  });
}

$("run-search").addEventListener("input", (event) => {
  state.search = event.target.value;
  renderRunList();
});
$("channel-search").addEventListener("input", () => renderChannelPicker());

$("channels-toggle").addEventListener("click", () => {
  const expanded = $("channels-toggle").getAttribute("aria-expanded") === "true";
  $("channels-toggle").setAttribute("aria-expanded", String(!expanded));
  $("channel-body").hidden = expanded;
});

$("run-list").addEventListener("keydown", (event) => {
  if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
  event.preventDefault();
  const index = state.filtered.findIndex((run) => run.run_id === state.selected?.run_id);
  const next = event.key === "ArrowDown" ? index + 1 : index - 1;
  const run = state.filtered[Math.max(0, Math.min(state.filtered.length - 1, next))];
  if (run) selectRun(run.run_id, { scrollIntoView: true });
});

document.addEventListener("keydown", (event) => {
  if (event.target.matches("input, select, textarea")) return;
  if (event.key === "/") {
    event.preventDefault();
    $("run-search").focus();
  }
  if (event.key.toLowerCase() === "s" && !event.metaKey && !event.ctrlKey) {
    event.preventDefault();
    simulation.open();
  }
});

// ---------- simulation ----------

const simulation = new SimulationPanel(
  {
    drawer: $("simulate-drawer"),
    scrim: $("drawer-scrim"),
    open: $("open-simulate"),
    close: $("close-simulate"),
    form: $("simulate-form"),
    model: $("sim-model"),
    modelHint: $("sim-model-hint"),
    schedule: $("sim-schedule"),
    scheduleHint: $("sim-schedule-hint"),
    stop: $("sim-stop"),
    interval: $("sim-interval"),
    label: $("sim-label"),
    faults: $("fault-handles"),
    parameters: $("model-parameters"),
    paramCount: $("param-count"),
    submit: $("submit-simulation"),
    error: $("sim-error"),
    mode: $("sim-mode"),
    runs: $("sim-runs"),
    editor: $("schedule-editor"),
    editorField: $("editor-field"),
    rules: $("rule-builder"),
    replayField: $("replay-field"),
    replayPicker: $("replay-picker"),
    replayHint: $("replay-hint"),
    replayInitial: $("replay-initial"),
    horizon: $("editor-horizon"),
    stepSize: $("editor-step"),
    clearSchedule: $("editor-clear"),
  },
  {
    onStatus: setStatus,
    runsProvider: () => state.runs,
    onRunFinished: async (job, options = {}) => {
      await refreshRuns();
      if (options.focus || !state.selected || state.selected.origin === "simulated") {
        await selectRun(job.run_id, { scrollIntoView: true });
      }
      setStatus("sim", "up", `${job.run_id} completed`);
    },
  }
);

// ---------- boot ----------

async function refreshRuns() {
  state.runs = await api.runs();
  state.runs.sort((a, b) => String(b.started_at).localeCompare(String(a.started_at)));
  renderScenarioFilter();
  renderRunList();
}

async function pollHealth() {
  try {
    const health = await api.health();
    const samples = health.store?.samples;
    setStatus(
      "store",
      health.status === "UP" ? "up" : "down",
      samples ? `${formatNumber(samples, "samples")}` : health.store ?? ""
    );
  } catch (error) {
    setStatus("store", "down", error.message);
  }
}

async function boot() {
  const restored = JSON.parse(localStorage.getItem("modva-channels") ?? "[]");
  state.selectedChannels = new Set(restored);

  await pollHealth();
  setInterval(pollHealth, 30_000);

  try {
    state.aas = await api.aas();
    const link = $("aas-link");
    if (state.aas.web_ui) {
      link.href = state.aas.web_ui;
      link.hidden = false;
    }
  } catch {
    /* the chip below carries the failure */
  }

  try {
    state.channels = await api.channels();
    state.channelIndex = new Map(state.channels.map((channel) => [channel.channel, channel]));
    setStatus("aas", "up", `${state.channels.length} channels described`);
  } catch (error) {
    setStatus("aas", "down", error.message);
    banner(
      `Channel metadata comes from the AAS repository, which is not answering: ${error.message}`,
      "warn"
    );
  }
  renderPresets();
  renderChannelPicker();

  try {
    await refreshRuns();
  } catch (error) {
    banner(`No runs: ${error.message}`);
  }

  await simulation.load();

  // Open on a recorded run: that is the plant, and it has fault windows to show. A ?run=
  // parameter wins, so a link to a specific run stays a link to that run.
  const initial =
    new URLSearchParams(location.search).get("run") ??
    state.filtered.find((run) => run.origin === "measured")?.run_id ??
    state.filtered[0]?.run_id;
  if (initial) selectRun(initial, { scrollIntoView: true });
}

boot();
