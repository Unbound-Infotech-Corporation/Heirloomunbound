import { describeEnterFailure, ENTER_CODES, enterRoomVr, openXrSelfCheck, probeBrowserXr } from "./vrRuntime";

describe("VR runtime probe", () => {
  test("insecure context is explained", () => {
    const fail = describeEnterFailure({ secure: false, hasXr: true, immersiveVr: true });
    expect(fail.ok).toBe(false);
    expect(fail.code).toBe(ENTER_CODES.insecure);
    expect(fail.coachPath).toContain("/rooms/vr");
  });

  test("missing WebXR points at the coach", () => {
    const fail = describeEnterFailure({ secure: true, hasXr: false, immersiveVr: false });
    expect(fail.code).toBe(ENTER_CODES.no_webxr);
  });

  test("headset missing still guides install", () => {
    const fail = describeEnterFailure({ secure: true, hasXr: true, immersiveVr: false });
    expect(fail.code).toBe(ENTER_CODES.no_headset);
    expect(fail.reason.toLowerCase()).toMatch(/runtime|headset|coach/);
  });

  test("probeBrowserXr reads navigator.xr", async () => {
    const xr = { isSessionSupported: jest.fn().mockResolvedValue(true) };
    const probe = await probeBrowserXr(
      { xr, userAgent: "OculusBrowser Quest 3" },
      { isSecureContext: true },
    );
    expect(probe.hasXr).toBe(true);
    expect(probe.immersiveVr).toBe(true);
    expect(probe.headsetHint.id).toBe("quest");
  });

  test("openXr self-check mixes browser + server probe", () => {
    const items = openXrSelfCheck(
      { secure: true, hasXr: true, immersiveVr: false },
      { openxr: { found: true, runtime_name: "SteamVR", runtime_path: "C:\\\\openxr\\\\active_runtime.json" } },
    );
    expect(items.find((i) => i.id === "https").ok).toBe(true);
    expect(items.find((i) => i.id === "immersive_vr").ok).toBe(false);
    expect(items.find((i) => i.id === "runtime_json").ok).toBe(true);
  });

  test("enterRoomVr refuses without WebXR", async () => {
    const result = await enterRoomVr({
      xr: undefined,
      win: { isSecureContext: true, document: { createElement: () => ({ getContext: () => null }) } },
    });
    expect(result.ok).toBe(false);
    expect([ENTER_CODES.no_webxr, ENTER_CODES.no_headset]).toContain(result.code);
  });
});
