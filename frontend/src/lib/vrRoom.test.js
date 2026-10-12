import { applyRoomGaze, applyRoomVrEnter, applyRoomVrToggle, loadOwnerVr } from "./vrRoom";

describe("Room VR wiring", () => {
  test("loading a saved-on account with a headset does not enter", async () => {
    const enter = jest.fn();
    const api = {
      get: jest.fn().mockResolvedValue({
        data: { settings: { enabled: true, gaze_enabled: true }, session_active: true },
      }),
    };
    const storage = { getItem: () => null, setItem: jest.fn() };
    const state = await loadOwnerVr(api, "owner_1", storage);
    expect(state.enabled).toBe(true);
    expect(state.sessionActive).toBe(false);
    expect(state.autoEnter).toBe(false);
    expect(enter).not.toHaveBeenCalled();
  });

  test("turning the room switch on is the gesture that enters, and off ends it", async () => {
    const enter = jest.fn().mockResolvedValue({ ok: true, session: { id: "s" } });
    const endSession = jest.fn().mockResolvedValue(undefined);
    const save = jest.fn(async (prefs) => ({ ...prefs, sessionActive: false, autoEnter: false }));
    const on = await applyRoomVrToggle({
      prefs: { enabled: false, gazeEnabled: false },
      nextEnabled: true,
      gesture: true,
      surface: "room",
      enter,
      save,
    });
    expect(enter).toHaveBeenCalledWith({ gesture: true, gaze: false });
    expect(on.started.ok).toBe(true);
    const off = await applyRoomVrToggle({
      prefs: on.prefs,
      nextEnabled: false,
      gesture: true,
      surface: "room",
      sessionActive: true,
      enter,
      endSession,
      save,
    });
    expect(endSession).toHaveBeenCalled();
    expect(off.prefs.enabled).toBe(false);
    expect(enter).toHaveBeenCalledTimes(1);
  });

  test("settings and a missing gesture never call enter", async () => {
    const enter = jest.fn();
    await applyRoomVrToggle({
      prefs: { enabled: false, gazeEnabled: false },
      nextEnabled: true,
      gesture: true,
      surface: "settings",
      enter,
      save: async (prefs) => prefs,
    });
    await applyRoomVrToggle({
      prefs: { enabled: false, gazeEnabled: false },
      nextEnabled: true,
      gesture: false,
      surface: "room",
      enter,
    });
    expect(enter).not.toHaveBeenCalled();
  });

  test("a saved-on room still needs the enter click, and gaze does not start VR", async () => {
    const enter = jest.fn().mockResolvedValue({ ok: true });
    const blocked = await applyRoomVrEnter({
      prefs: { enabled: true, gazeEnabled: false },
      gesture: false,
      enter,
    });
    expect(blocked.decision.startSession).toBe(false);
    expect(enter).not.toHaveBeenCalled();
    await applyRoomVrEnter({
      prefs: { enabled: true, gazeEnabled: true },
      gesture: true,
      enter,
    });
    expect(enter).toHaveBeenCalledWith({ gesture: true, gaze: true });
    const gaze = await applyRoomGaze({
      prefs: { enabled: false, gazeEnabled: false },
      nextGaze: true,
      gesture: true,
      save: async (prefs) => prefs,
    });
    expect(gaze.decision.startSession).toBe(false);
    expect(gaze.prefs.gazeEnabled).toBe(true);
    expect(enter).toHaveBeenCalledTimes(1);
  });
});
