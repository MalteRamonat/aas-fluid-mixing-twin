// The only place that talks to the API. Every call returns parsed JSON or throws an Error
// whose message is the API's own `detail` — the banner shows that text verbatim, because a
// 503 from the AAS repository is information, not noise to be swallowed.

/** @param {string} path @param {RequestInit} [init] */
async function request(path, init) {
  let response;
  try {
    response = await fetch(path, init);
  } catch (cause) {
    throw new Error(`${path} is unreachable`, { cause });
  }
  if (response.status === 204) return null;
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body && (body.detail ?? body.error);
    throw Object.assign(new Error(detail ? String(detail) : `${response.status} on ${path}`), {
      status: response.status,
    });
  }
  return body;
}

const query = (params) => {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
};

export const api = {
  health: () => request("/api/health"),
  aas: () => request("/api/aas"),
  channels: () => request("/api/channels"),
  runs: (origin) => request(`/api/runs${query({ origin })}`),
  run: (runId) => request(`/api/runs/${encodeURIComponent(runId)}`),
  runChannels: (runId) => request(`/api/runs/${encodeURIComponent(runId)}/channels`),
  /** The LinkedSegment query, exactly as the AAS spells it. */
  timeseriesUrl: (runId, channels) =>
    `/api/timeseries${query({ run_id: runId, channels: channels.join(",") })}`,
  timeseries: (runId, channels) => request(api.timeseriesUrl(runId, channels)),
  simulationConfig: () => request("/api/simulation/config"),
  simulations: () => request("/api/simulations"),
  simulation: (runId) => request(`/api/simulations/${encodeURIComponent(runId)}`),
  startSimulation: (payload) =>
    request("/api/simulations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
};
