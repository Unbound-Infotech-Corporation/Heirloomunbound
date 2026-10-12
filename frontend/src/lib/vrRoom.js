/** Room sit wiring. Hydrate never starts a session. */

import { launchVrState, planEnter, planGaze, planToggle, readLocalVr, writeLocalVr } from "./vrMode";

export async function loadOwnerVr(api, userId, storage) {
  const local = readLocalVr(storage, userId);
  try {
    const response = await api.get("/studio/vr");
    const data = response?.data || response || {};
    const launched = launchVrState(data.settings || data);
    writeLocalVr(storage, userId, launched);
    return launched;
  } catch {
    return launchVrState(local);
  }
}

export async function saveOwnerVr(api, userId, storage, prefs) {
  const body = writeLocalVr(storage, userId, prefs);
  try {
    if (api?.put) await api.put("/studio/vr", body);
  } catch {
    /* The browser copy is enough until the account is reachable. */
  }
  return launchVrState(body);
}

export async function applyRoomVrToggle({
  prefs,
  nextEnabled,
  gesture = false,
  surface = "room",
  sessionActive = false,
  headsetConnected = false,
  enter,
  endSession,
  save,
}) {
  const decision = planToggle(prefs, { nextEnabled, gesture, surface, sessionActive });
  const launched = save ? await save(decision.prefs) : launchVrState(decision.prefs, { headsetConnected });
  if (decision.endSession && endSession) await endSession();
  let started = null;
  if (decision.startSession && enter) {
    started = await enter({ gesture: true, gaze: decision.prefs.gazeEnabled });
  }
  return { decision, prefs: { enabled: launched.enabled, gazeEnabled: launched.gazeEnabled }, started };
}

export async function applyRoomVrEnter({ prefs, gesture = false, sessionActive = false, enter }) {
  const decision = planEnter({ enabled: prefs?.enabled, gesture, sessionActive });
  if (!decision.startSession || !enter) return { decision, started: null };
  const started = await enter({ gesture: true, gaze: Boolean(prefs?.gazeEnabled) });
  return { decision, started };
}

export async function applyRoomGaze({ prefs, nextGaze, gesture = false, save }) {
  const decision = planGaze(prefs, { nextGaze, gesture });
  const launched = save ? await save(decision.prefs) : launchVrState(decision.prefs);
  return { decision, prefs: { enabled: launched.enabled, gazeEnabled: launched.gazeEnabled } };
}
