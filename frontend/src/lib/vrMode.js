/** Owner VR preference. A saved "on" never starts a headset session. */

export function defaultVrPrefs() {
  return { enabled: false, gazeEnabled: false };
}

function asBool(value) {
  if (value === true || value === 1) return true;
  if (value === false || value === 0 || value == null) return false;
  const text = String(value).trim().toLowerCase();
  if (text === "1" || text === "true" || text === "yes" || text === "on") return true;
  if (text === "0" || text === "false" || text === "no" || text === "off") return false;
  return false;
}

export function vrAllowedForAudience(audience, heirSurface = false) {
  if (heirSurface) return false;
  return String(audience || "owner").trim().toLowerCase() === "owner";
}

export function clampVrPrefs(raw) {
  const src = raw && typeof raw === "object" ? raw : {};
  return {
    enabled: asBool(src.enabled),
    gazeEnabled: asBool(src.gazeEnabled ?? src.gaze_enabled),
  };
}

export function persistableVrPrefs(raw) {
  const prefs = clampVrPrefs(raw);
  return { enabled: prefs.enabled, gaze_enabled: prefs.gazeEnabled };
}

export function shouldAutoEnter({ headsetConnected = false, enabled = false } = {}) {
  void headsetConnected;
  void enabled;
  return false;
}

export function launchVrState(raw, { headsetConnected = false } = {}) {
  const prefs = clampVrPrefs(raw);
  return {
    ...prefs,
    sessionActive: false,
    autoEnter: shouldAutoEnter({ headsetConnected, enabled: prefs.enabled }),
  };
}

export function planToggle(prefs, { nextEnabled, gesture = false, surface = "room", sessionActive = false } = {}) {
  const current = clampVrPrefs(prefs);
  if (!gesture) {
    return { prefs: current, startSession: false, endSession: false, reason: "no-gesture" };
  }
  if (!nextEnabled) {
    return {
      prefs: { enabled: false, gazeEnabled: current.gazeEnabled },
      startSession: false,
      endSession: true,
      reason: "toggled-off",
    };
  }
  const next = { enabled: true, gazeEnabled: current.gazeEnabled };
  if (surface !== "room") {
    return { prefs: next, startSession: false, endSession: false, reason: "settings" };
  }
  return {
    prefs: next,
    startSession: !sessionActive,
    endSession: false,
    reason: "user-gesture",
  };
}

export function planEnter({ enabled = false, gesture = false, sessionActive = false } = {}) {
  if (!gesture) return { startSession: false, reason: "no-gesture" };
  if (!enabled) return { startSession: false, reason: "off" };
  if (sessionActive) return { startSession: false, reason: "already" };
  return { startSession: true, reason: "user-gesture" };
}

export function planGaze(prefs, { nextGaze = false, gesture = false } = {}) {
  const current = clampVrPrefs(prefs);
  if (!gesture) return { prefs: current, startSession: false, reason: "no-gesture" };
  return {
    prefs: { enabled: current.enabled, gazeEnabled: Boolean(nextGaze) },
    startSession: false,
    reason: "gaze",
  };
}

export function vrStorageKey(userId) {
  const id = String(userId || "owner").replace(/[^a-zA-Z0-9_-]/g, "");
  return `heirloom.vr.${id || "owner"}`;
}

export function readLocalVr(storage, userId) {
  if (!storage || typeof storage.getItem !== "function") return null;
  try {
    const raw = storage.getItem(vrStorageKey(userId));
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return clampVrPrefs(parsed);
  } catch {
    return null;
  }
}

export function writeLocalVr(storage, userId, prefs) {
  const body = persistableVrPrefs(prefs);
  if (storage && typeof storage.setItem === "function") {
    storage.setItem(vrStorageKey(userId), JSON.stringify(body));
  }
  return body;
}

export const VR_LAUNCH_NOTE =
  "VR is off until you turn it on. Opening this page does not enter the headset.";
