// Shared vocabulary: scenario names, channel grouping, number and duration formatting.
// Channel *metadata* always comes from the AAS; what is here is presentation only.

export const SCENARIOS = {
  normal_behaviour: { label: "normal", code: 0 },
  leakage: { label: "leakage", code: 1 },
  clogging: { label: "clogging", code: 2 },
  leakage_and_clogging: { label: "leakage + clogging", code: 3 },
  changed_initial_state: { label: "changed initial state", code: 4 },
  reconfiguration: { label: "reconfiguration", code: 5 },
  sensor_errors: { label: "sensor errors", code: 6 },
  stirring_error: { label: "stirring error", code: 7 },
  manual_mode: { label: "manual mode", code: 8 },
};

export const scenarioLabel = (scenario) =>
  SCENARIOS[scenario]?.label ?? String(scenario ?? "").replaceAll("_", " ");

/** Chart groups. One chart per group, because one chart per unit is what an axis can honestly show. */
const GROUPS = [
  { id: "volume", title: "Tank volumes", unit: "ml", match: (c) => c.unit === "ml" },
  { id: "level_mm", title: "Levels (ultrasonic)", unit: "mm", match: (c) => c.unit === "mm" },
  { id: "level", title: "Levels (derived)", unit: "cm", match: (c) => c.unit === "cm" },
  { id: "pressure", title: "Pressures", unit: "kPa", match: (c) => c.unit === "kPa" },
  { id: "flow", title: "Flows", unit: "l/min", match: (c) => c.unit === "l/min" },
  { id: "temperature", title: "Temperatures", unit: "°C", match: (c) => c.unit === "°C" },
  {
    id: "actuator",
    title: "Actuators",
    unit: "open / on",
    match: (c) => c.role === "actuator",
  },
  {
    id: "switch",
    title: "Level switches",
    unit: "active",
    match: (c) => c.data_type === "boolean",
  },
  { id: "other", title: "Other", unit: "", match: () => true },
];

export function groupOf(channel) {
  // Actuators and switches first: they are binary and belong on their own step-plotted axis.
  if (channel.role === "actuator") return GROUPS.find((g) => g.id === "actuator");
  if (channel.data_type === "boolean") return GROUPS.find((g) => g.id === "switch");
  return GROUPS.find((g) => g.match(channel)) ?? GROUPS.at(-1);
}

export const GROUP_ORDER = GROUPS.map((g) => g.id);

export function groupChannels(channels) {
  const groups = new Map();
  for (const channel of channels) {
    const group = groupOf(channel);
    if (!groups.has(group.id)) groups.set(group.id, { ...group, channels: [] });
    groups.get(group.id).channels.push(channel);
  }
  return [...groups.values()].sort(
    (a, b) => GROUP_ORDER.indexOf(a.id) - GROUP_ORDER.indexOf(b.id)
  );
}

export function formatNumber(value, unit) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const magnitude = Math.abs(value);
  let digits = 2;
  if (magnitude >= 1000) digits = 0;
  else if (magnitude >= 100) digits = 1;
  else if (magnitude < 0.01 && magnitude > 0) digits = 4;
  const text = value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  return unit ? `${text} ${unit}` : text;
}

export function formatDuration(seconds) {
  if (!Number.isFinite(seconds)) return "—";
  if (seconds < 90) return `${seconds.toFixed(0)} s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return rest ? `${minutes} min ${rest} s` : `${minutes} min`;
}

export function formatTimestamp(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return String(iso);
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Presets are named by what a reader wants to see, not by what the channels are called. */
export const PRESETS = [
  { id: "volumes", label: "Tank volumes", channels: (all) => pick(all, /_Volume$/) },
  {
    id: "levels",
    label: "Tank levels",
    // The ultrasonic sensors' own reading (millimetres — deviation D10). The levels derived
    // from the volume and from the pressures stay selectable in the channel list.
    channels: (all) => pick(all, /^Tank_B20[1-4]_level_calculated_via_LI21[1-4]$/),
  },
  {
    id: "cycle",
    label: "Dosing cycle",
    channels: (all) => [
      ...pick(all, /^Tank_B20[14]_Volume$/),
      ...pick(all, /^Valve_V20[1-6]_opening$/),
      ...pick(all, /^Pump_P20[12]_active$/),
    ],
  },
  {
    id: "leak",
    label: "Leak signature",
    channels: (all) => [
      ...pick(all, /^Flow_after_Pump_P201$/),
      ...pick(all, /^Tank_B204_Volume$/),
      ...pick(all, /^Tank_B201_Volume$/),
    ],
  },
  { id: "pressures", label: "Pressures", channels: (all) => pick(all, /^Pressure_below_/) },
  {
    id: "temperature",
    label: "Temperatures",
    channels: (all) => pick(all, /^(Tempreature|Temperature)_/),
  },
];

const pick = (channels, pattern) =>
  channels.filter((c) => pattern.test(c.channel)).map((c) => c.channel);
