/** Aggregated VR attention. Areas and dwell only — never a raw gaze stream. */

import { vrAllowedForAudience } from "./vrMode";

export const GAZE_AREAS = ["twin", "seat", "room", "floor", "elsewhere"];
export const MIN_DWELL_MS = 400;
export const GAZE_EXTENSION = "XR_EXT_eye_gaze_interaction";

const RAW_KEYS = new Set([
  "origin",
  "direction",
  "ray",
  "quaternion",
  "pupil",
  "gaze",
  "gaze_x",
  "gaze_y",
  "gaze_z",
  "x",
  "y",
  "z",
  "raw",
  "samples_raw",
  "stream",
  "matrix",
]);

const AREA_LABELS = {
  twin: "the twin",
  seat: "the twin's seat",
  room: "the room",
  floor: "the floor",
  elsewhere: "elsewhere in the room",
};

/** Coarse targets in the Room, meters, local-floor. The twin sits across. */
export const ROOM_TARGETS = [
  { area: "twin", min: [-0.28, 0.7, -1.95], max: [0.28, 1.5, -1.25] },
  { area: "seat", min: [-0.4, 0.35, -2.05], max: [0.4, 0.7, -1.15] },
  { area: "floor", min: [-2, -0.2, -2], max: [2, 0.2, 2] },
  { area: "room", min: [-2.2, 0, -2.2], max: [2.2, 2.6, 2.2] },
];

export function sanitizeGazeSamples(samples) {
  if (!Array.isArray(samples)) return [];
  const cleaned = [];
  samples.forEach((item) => {
    if (!item || typeof item !== "object") return;
    const area = String(item.area || "").trim().toLowerCase();
    if (!GAZE_AREAS.includes(area)) return;
    const dwell = Number(item.dwell_ms ?? item.dwellMs);
    if (!Number.isFinite(dwell) || dwell <= 0) return;
    cleaned.push({ area, dwell_ms: Math.min(Math.round(dwell), 30 * 60 * 1000) });
  });
  return cleaned;
}

export function aggregateGaze(samples) {
  const totals = new Map();
  const order = [];
  sanitizeGazeSamples(samples).forEach((row) => {
    if (!totals.has(row.area)) {
      order.push(row.area);
      totals.set(row.area, 0);
    }
    totals.set(row.area, totals.get(row.area) + row.dwell_ms);
  });
  return order
    .map((area) => ({ area, dwell_ms: totals.get(area) }))
    .filter((row) => row.dwell_ms >= MIN_DWELL_MS);
}

export function formatGazeNote(summaries) {
  const parts = (summaries || [])
    .map((row) => {
      const label = AREA_LABELS[row.area];
      if (!label) return "";
      const seconds = Math.max(1, Math.round(Number(row.dwell_ms || 0) / 1000));
      const unit = seconds === 1 ? "second" : "seconds";
      return `${label} for ${seconds} ${unit}`;
    })
    .filter(Boolean);
  if (!parts.length) return "";
  const body = parts.length === 1 ? parts[0] : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
  return `In VR, looked at ${body}.`;
}

export function gazePayload(summaries) {
  return {
    summaries: aggregateGaze(summaries).map((row) => ({ area: row.area, dwell_ms: row.dwell_ms })),
  };
}

export function droppedRawKeys(samples) {
  if (!Array.isArray(samples)) return [];
  const found = new Set();
  samples.forEach((item) => {
    if (!item || typeof item !== "object") return;
    Object.keys(item).forEach((key) => {
      if (RAW_KEYS.has(key)) found.add(key);
    });
  });
  return Array.from(found);
}

export function shouldSendGaze({
  gazeEnabled = false,
  paused = false,
  audience = "owner",
  heirSurface = false,
  available = false,
  summaries = [],
} = {}) {
  if (!vrAllowedForAudience(audience, heirSurface)) return { send: false, reason: "heir" };
  if (!gazeEnabled) return { send: false, reason: "opt-in-off" };
  if (paused) return { send: false, reason: "paused" };
  if (!available) return { send: false, reason: "unavailable" };
  if (!aggregateGaze(summaries).length) return { send: false, reason: "empty" };
  return { send: true, reason: "ok" };
}

/**
 * PSVR2 eye cameras work on a PlayStation 5. Sony's PC adapter and the
 * PlayStation VR2 App do not document eye tracking as a PC feature, and
 * SteamVR does not currently expose it for this headset. WebXR in Chrome
 * and Edge also does not surface XR_EXT_eye_gaze_interaction to the page.
 * If a runtime advertises a gaze feature anyway, we can use it.
 */
export function gazeSupport({ features = [], headsetId = "" } = {}) {
  const advertised = (features || []).some((feature) => /gaze|eye-tracking|eye_gaze/i.test(String(feature || "")));
  if (advertised) {
    return {
      available: true,
      extension: GAZE_EXTENSION,
      psvr2PcExposed: false,
      reason: "",
    };
  }
  if (headsetId === "psvr2") {
    return {
      available: false,
      extension: GAZE_EXTENSION,
      psvr2PcExposed: false,
      reason:
        "PSVR2 eye tracking is not exposed to PC apps through Sony's adapter and SteamVR. The Room continues without it.",
    };
  }
  return {
    available: false,
    extension: GAZE_EXTENSION,
    psvr2PcExposed: false,
    reason:
      "This runtime did not expose eye gaze. WebXR in Chrome and Edge does not surface XR_EXT_eye_gaze_interaction, so nothing is sent.",
  };
}

export function rayHitAabb(origin, direction, min, max) {
  let tmin = 0;
  let tmax = 40;
  for (let axis = 0; axis < 3; axis += 1) {
    const originAxis = origin[axis];
    const directionAxis = direction[axis];
    if (Math.abs(directionAxis) < 1e-8) {
      if (originAxis < min[axis] || originAxis > max[axis]) return null;
      continue;
    }
    let enter = (min[axis] - originAxis) / directionAxis;
    let exit = (max[axis] - originAxis) / directionAxis;
    if (enter > exit) {
      const swap = enter;
      enter = exit;
      exit = swap;
    }
    tmin = Math.max(tmin, enter);
    tmax = Math.min(tmax, exit);
    if (tmin > tmax) return null;
  }
  if (tmax < 0) return null;
  return tmin >= 0 ? tmin : tmax;
}

export function areaAlongRay(origin, direction) {
  if (!origin || !direction || origin.length < 3 || direction.length < 3) return null;
  let best = null;
  let bestT = Infinity;
  ROOM_TARGETS.forEach((target) => {
    const distance = rayHitAabb(origin, direction, target.min, target.max);
    if (distance != null && distance < bestT) {
      bestT = distance;
      best = target.area;
    }
  });
  return best || "elsewhere";
}

export function createGazeAccumulator() {
  let current = null;
  const closed = [];
  return {
    sample(area, timeMs) {
      if (!area || typeof timeMs !== "number") return;
      if (!current) {
        current = { area, start: timeMs };
        return;
      }
      if (current.area === area) return;
      closed.push({ area: current.area, dwell_ms: Math.max(0, timeMs - current.start) });
      current = { area, start: timeMs };
    },
    flush(timeMs) {
      if (current && typeof timeMs === "number") {
        closed.push({ area: current.area, dwell_ms: Math.max(0, timeMs - current.start) });
        current = null;
      }
      const rows = closed.splice(0, closed.length);
      return aggregateGaze(rows);
    },
  };
}
