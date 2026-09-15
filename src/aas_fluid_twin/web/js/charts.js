// The chart layer: one ECharts instance per unit group, all sharing one x axis through
// echarts.connect, so zooming a pressure trace zooms the valve positions underneath it.
//
// Two conventions worth knowing:
//   * binary channels (valves, pumps, level switches) are drawn as steps, never interpolated —
//     a valve is open or shut, it does not pass through 0.5;
//   * an overlaid run is dashed and keeps the same colour as its primary, so measured and
//     simulated versions of the same channel stay visually paired.

import { formatNumber } from "./format.js";

const PALETTE = [
  "#2563eb", "#0f766e", "#b45309", "#7c3aed", "#be123c",
  "#0891b2", "#4d7c0f", "#a16207", "#9333ea", "#c2410c",
];

const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export class ChartBoard {
  /** @param {HTMLElement} container */
  constructor(container) {
    this.container = container;
    this.charts = new Map(); // group id -> { chart, card, holder }
    this.group = "modva";
    this.onZoom = null;
    window.addEventListener("resize", () => this.resize());
  }

  resize() {
    for (const { chart } of this.charts.values()) chart.resize();
  }

  clear() {
    for (const { chart } of this.charts.values()) chart.dispose();
    this.charts.clear();
    this.container.replaceChildren();
  }

  /**
   * @param {Array<{id:string,title:string,unit:string,channels:Array}>} groups
   * @param {{primary: object, overlay: object|null, meta: Map<string, object>, run: object, overlayRun: object|null}} data
   */
  render(groups, data) {
    const wanted = new Set(groups.map((g) => g.id));
    for (const [id, entry] of [...this.charts]) {
      if (!wanted.has(id)) {
        entry.chart.dispose();
        entry.card.remove();
        this.charts.delete(id);
      }
    }

    let colourIndex = 0;
    const colourOf = new Map();
    for (const group of groups) {
      for (const channel of group.channels) {
        colourOf.set(channel.channel, PALETTE[colourIndex++ % PALETTE.length]);
      }
    }

    const base = groups.length <= 1 ? 420 : groups.length === 2 ? 300 : 230;
    // Every chart shares one left margin: stacked charts are only readable if a moment in
    // time sits at the same x in all of them, and lane labels are wider than numbers.
    const left = groups.some((g) => g.id === "actuator" || g.id === "switch") ? 150 : 62;
    groups.forEach((group, index) => {
      const entry = this.ensureCard(group, index === groups.length - 1, base);
      entry.chart.setOption(
        buildOption(group, data, colourOf, {
          showXAxisLabels: index === groups.length - 1,
          showFaultLabel: index === 0,
          left,
        }),
        { notMerge: true }
      );
    });

    // Re-order the cards to match the group order.
    for (const group of groups) this.container.append(this.charts.get(group.id).card);
    echarts.connect(this.group);
    this.resize();
  }

  ensureCard(group, isLast, base = 230) {
    const existing = this.charts.get(group.id);
    const height = group.id === "actuator" || group.id === "switch" ? Math.min(base, 170) : base;
    if (existing) {
      existing.holder.style.height = `${height + (isLast ? 34 : 0)}px`;
      existing.chart.resize();
      return existing;
    }
    const card = document.createElement("section");
    card.className = "chart-card";
    card.innerHTML = `<header><h3>${group.title}</h3><span class="unit">${group.unit}</span></header>`;
    const holder = document.createElement("div");
    holder.className = "chart-holder";
    holder.style.height = `${height + (isLast ? 34 : 0)}px`;
    card.append(holder);
    this.container.append(card);
    const chart = echarts.init(holder, null, { renderer: "canvas" });
    chart.group = this.group;
    chart.on("dataZoom", () => this.onZoom?.());
    const entry = { chart, card, holder };
    this.charts.set(group.id, entry);
    return entry;
  }

  resetZoom() {
    for (const { chart } of this.charts.values()) {
      chart.dispatchAction({ type: "dataZoom", start: 0, end: 100 });
    }
  }

  /** ECharts keeps its own colours; re-render is how a theme change reaches the canvas. */
  refreshTheme(groups, data) {
    this.clear();
    if (groups.length) this.render(groups, data);
  }
}

function buildOption(group, data, colourOf, { showXAxisLabels, showFaultLabel, left }) {
  const text = cssVar("--text");
  const muted = cssVar("--text-muted");
  const border = cssVar("--border");
  const surface = cssVar("--surface");
  const binary = group.id === "actuator" || group.id === "switch";

  // Binary channels share the range 0…1, so drawing them on one axis makes nine valves into
  // one unreadable band. Each gets its own lane instead — a timing diagram, read top to bottom.
  const lanes = binary ? group.channels.map((c) => c.channel) : [];
  const laneOf = (channel) => lanes.indexOf(channel.channel);

  const series = [];
  for (const channel of group.channels) {
    const colour = colourOf.get(channel.channel);
    const lane = binary ? lanes.length - 1 - laneOf(channel) : 0;
    const primary = seriesFor(channel, data.primary, colour, binary, false, data.run, lane);
    if (primary) series.push(primary);
    if (data.overlay) {
      const overlay = seriesFor(channel, data.overlay, colour, binary, true, data.overlayRun, lane);
      if (overlay) series.push(overlay);
    }
  }

  const markArea = faultAreas(data.run);
  if (series.length && markArea.length) {
    series[0].markArea = {
      silent: true,
      itemStyle: { color: "rgba(180, 35, 31, .10)" },
      label: { show: showFaultLabel, position: "insideTop", color: muted, fontSize: 10 },
      data: markArea,
    };
  }

  return {
    animation: false,
    backgroundColor: "transparent",
    grid: {
      left,
      right: 18,
      top: binary ? 8 : 16,
      bottom: showXAxisLabels ? 46 : 16,
    },
    textStyle: { color: text, fontFamily: getComputedStyle(document.body).fontFamily },
    tooltip: {
      trigger: "axis",
      backgroundColor: surface,
      borderColor: border,
      textStyle: { color: text, fontSize: 12 },
      axisPointer: { type: "line", lineStyle: { color: muted, width: 1, type: "dashed" } },
      formatter: (params) => tooltip(params, group, data),
    },
    legend: {
      // In a lane chart the axis already names every series.
      show: !binary,
      type: "scroll",
      top: 0,
      right: 8,
      itemHeight: 8,
      itemWidth: 14,
      textStyle: { color: muted, fontSize: 11 },
    },
    xAxis: {
      type: "value",
      min: "dataMin",
      max: "dataMax",
      axisLabel: {
        show: showXAxisLabels,
        color: muted,
        fontSize: 11,
        // Sample times are not round numbers; the axis should not pretend otherwise.
        formatter: (value) => `${Number(value).toFixed(Math.abs(value) < 10 ? 1 : 0)} s`,
      },
      axisLine: { lineStyle: { color: border } },
      splitLine: { show: true, lineStyle: { color: border, opacity: .5 } },
    },
    yAxis: binary
      ? {
          type: "value",
          min: 0,
          max: lanes.length,
          interval: 1,
          axisLabel: {
            color: muted,
            fontSize: 11,
            formatter: (value) => {
              const channel = group.channels[lanes.length - 1 - value];
              return channel ? shortName(channel.title) : "";
            },
            align: "right",
            margin: 12,
            verticalAlign: "bottom",
            padding: [0, 0, 6, 0],
          },
          axisTick: { show: false },
          splitLine: { lineStyle: { color: border, opacity: .8 } },
        }
      : {
          type: "value",
          scale: true,
          // Keep zero on the axis for quantities that stay non-negative — a tank showing
          // -1000 ml of head-room reads as an error even when it is only padding. Data that
          // really does go negative keeps ECharts' own rounded bounds: pinning the axis to
          // the raw minimum puts a tick like "-11.996273861" on it.
          min: (value) => (value.min >= -Math.abs(value.max) * 0.02 ? 0 : null),
          axisLabel: { color: muted, fontSize: 11 },
          splitLine: { lineStyle: { color: border, opacity: .6 } },
        },
    dataZoom: [
      { type: "inside", filterMode: "none" },
      ...(showXAxisLabels
        ? [{
            type: "slider",
            height: 18,
            bottom: 8,
            borderColor: border,
            backgroundColor: "transparent",
            fillerColor: "rgba(15, 118, 110, .12)",
            handleStyle: { color: surface, borderColor: muted },
            dataBackground: { lineStyle: { color: muted, opacity: .4 }, areaStyle: { opacity: .1 } },
            textStyle: { color: muted, fontSize: 10 },
            filterMode: "none",
          }]
        : []),
    ],
    series,
  };
}

function seriesFor(channel, payload, colour, binary, dashed, run, lane = 0) {
  const values = payload?.channels?.[channel.channel];
  if (!values) return null;
  const time = payload.t_rel_s;
  // In a lane chart the plotted y is the lane baseline plus the state; the raw value rides
  // along as a third element so the tooltip can still report on/off.
  const points = values.map((value, index) =>
    binary
      ? [time[index], value === null ? null : lane + 0.12 + Math.min(1, Math.max(0, value)) * 0.7, value]
      : [time[index], value]
  );
  const present = points.some((point) => point[1] !== null && point[1] !== undefined);
  if (!present) return null;
  return {
    name: dashed ? `${channel.title} · ${run?.run_id ?? "overlay"}` : channel.title,
    type: "line",
    step: binary ? "end" : false,
    showSymbol: false,
    connectNulls: false,
    sampling: "lttb",
    lineStyle: { width: dashed ? 1.4 : 1.8, type: dashed ? "dashed" : "solid", color: colour },
    itemStyle: { color: colour },
    emphasis: { focus: "series" },
    data: points,
    channel: channel.channel,
    unit: channel.unit,
  };
}

function faultAreas(run) {
  if (!run?.fault_windows?.length) return [];
  return run.fault_windows
    .filter((window) => window.onset_s !== null && window.onset_s !== undefined)
    .map((window) => [
      { xAxis: window.onset_s, name: window.end_s === null ? "fault from here" : "fault" },
      { xAxis: window.end_s ?? Number.MAX_SAFE_INTEGER },
    ]);
}

function tooltip(params, group, data) {
  if (!params.length) return "";
  const t = params[0].value[0];
  const rows = params
    .map((point) => {
      const unit = point.seriesModel?.option?.unit ?? "";
      const value = point.value.length > 2 ? point.value[2] : point.value[1];
      const shown =
        group.id === "actuator" || group.id === "switch"
          ? value === null
            ? "—"
            : value >= 0.5
              ? "on"
              : "off"
          : formatNumber(value, unit);
      return `<tr><td style="padding-right:10px">${point.marker} ${point.seriesName}</td>
              <td style="text-align:right;font-variant-numeric:tabular-nums">${shown}</td></tr>`;
    })
    .join("");
  const label = labelAt(data.run, t);
  return `<div style="font-size:11px;color:var(--text-muted);margin-bottom:4px">
            t = ${t.toFixed(2)} s${label ? ` · <b>${label}</b>` : ""}
          </div><table style="font-size:12px">${rows}</table>`;
}

function labelAt(run, t) {
  if (!run?.fault_windows?.length) return "";
  for (const window of run.fault_windows) {
    const from = window.onset_s ?? -Infinity;
    const to = window.end_s ?? Infinity;
    if (t >= from && t <= to) return "fault window";
  }
  return "";
}


/** "Valve V201 opening" -> "V201 opening"; the lane axis has ~130 px to work with. */
function shortName(title) {
  const trimmed = title.replace(/^(Valve|Pump|Mixer|Tank)\s+/i, "");
  return trimmed.length > 22 ? `${trimmed.slice(0, 21)}…` : trimmed;
}
