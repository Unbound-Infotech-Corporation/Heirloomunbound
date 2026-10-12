import {
  clampVrPrefs,
  launchVrState,
  persistableVrPrefs,
  planEnter,
  planGaze,
  planToggle,
  readLocalVr,
  shouldAutoEnter,
  vrAllowedForAudience,
  writeLocalVr,
} from "./vrMode";

describe("VR mode preference", () => {
  test("defaults off and never auto-enters, even with a headset and a saved on", () => {
    const fresh = launchVrState(null, { headsetConnected: true });
    expect(fresh).toMatchObject({ enabled: false, gazeEnabled: false, sessionActive: false, autoEnter: false });
    const saved = launchVrState(
      { enabled: true, gaze_enabled: true, session_active: true, sessionActive: true },
      { headsetConnected: true },
    );
    expect(saved.enabled).toBe(true);
    expect(saved.gazeEnabled).toBe(true);
    expect(saved.sessionActive).toBe(false);
    expect(saved.autoEnter).toBe(false);
    expect(shouldAutoEnter({ headsetConnected: true, enabled: true })).toBe(false);
  });

  test("a room click turns VR on and may start; settings and silent calls do not", () => {
    const off = clampVrPrefs(null);
    expect(planToggle(off, { nextEnabled: true, gesture: false, surface: "room" }).reason).toBe("no-gesture");
    const settings = planToggle(off, { nextEnabled: true, gesture: true, surface: "settings" });
    expect(settings.startSession).toBe(false);
    expect(settings.prefs.enabled).toBe(true);
    const room = planToggle(off, { nextEnabled: true, gesture: true, surface: "room" });
    expect(room.startSession).toBe(true);
    expect(room.reason).toBe("user-gesture");
    const leave = planToggle(room.prefs, { nextEnabled: false, gesture: true, surface: "room", sessionActive: true });
    expect(leave.endSession).toBe(true);
    expect(leave.prefs.enabled).toBe(false);
    expect(leave.startSession).toBe(false);
  });

  test("a saved-on preference still needs a click, and persistence drops the session", () => {
    const launched = launchVrState({ enabled: true, gazeEnabled: false });
    expect(launched.sessionActive).toBe(false);
    expect(planEnter({ enabled: true, gesture: false }).startSession).toBe(false);
    expect(planEnter({ enabled: true, gesture: true, sessionActive: false }).startSession).toBe(true);
    const body = persistableVrPrefs({ enabled: true, gazeEnabled: true, sessionActive: true });
    expect(body).toEqual({ enabled: true, gaze_enabled: true });
    expect(body.sessionActive).toBeUndefined();
    expect(body.session_active).toBeUndefined();
  });

  test("eye tracking is a separate opt-in and does not start VR", () => {
    const gaze = planGaze({ enabled: false, gazeEnabled: false }, { nextGaze: true, gesture: true });
    expect(gaze.startSession).toBe(false);
    expect(gaze.prefs).toEqual({ enabled: false, gazeEnabled: true });
    expect(planGaze({ enabled: true, gazeEnabled: false }, { nextGaze: true, gesture: false }).reason).toBe("no-gesture");
  });

  test("the preference is stored per owner and heirs are refused", () => {
    const storage = new Map();
    const api = {
      getItem: (key) => (storage.has(key) ? storage.get(key) : null),
      setItem: (key, value) => storage.set(key, value),
    };
    writeLocalVr(api, "owner_a", { enabled: true, gazeEnabled: false });
    writeLocalVr(api, "owner_b", { enabled: false, gazeEnabled: true });
    expect(readLocalVr(api, "owner_a")).toEqual({ enabled: true, gazeEnabled: false });
    expect(readLocalVr(api, "owner_b")).toEqual({ enabled: false, gazeEnabled: true });
    expect(launchVrState(readLocalVr(api, "owner_a"), { headsetConnected: true }).sessionActive).toBe(false);
    expect(vrAllowedForAudience("owner")).toBe(true);
    expect(vrAllowedForAudience("heir")).toBe(false);
    expect(vrAllowedForAudience("owner", true)).toBe(false);
    expect(vrAllowedForAudience("caller")).toBe(false);
  });
});
