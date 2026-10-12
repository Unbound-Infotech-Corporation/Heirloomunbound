import {
  aggregateGaze,
  areaAlongRay,
  createGazeAccumulator,
  droppedRawKeys,
  formatGazeNote,
  gazePayload,
  gazeSupport,
  shouldSendGaze,
} from "./vrGaze";

describe("VR gaze summaries", () => {
  test("aggregates dwell and drops raw rays and short glances", () => {
    const samples = [
      { area: "twin", dwell_ms: 300, origin: [0, 1.6, 0], direction: [0, 0, -1] },
      { area: "twin", dwell_ms: 900 },
      { area: "floor", dwell_ms: 1500, pupil: 0.2 },
      { area: "nope", dwell_ms: 4000 },
    ];
    expect(droppedRawKeys(samples)).toEqual(expect.arrayContaining(["origin", "direction", "pupil"]));
    const summaries = aggregateGaze(samples);
    expect(summaries).toEqual([
      { area: "twin", dwell_ms: 1200 },
      { area: "floor", dwell_ms: 1500 },
    ]);
    expect(gazePayload(samples).summaries).toEqual(summaries);
    expect(JSON.stringify(gazePayload(samples))).not.toMatch(/origin|pupil|direction/);
    expect(formatGazeNote(summaries)).toBe("In VR, looked at the twin for 1 second and the floor for 2 seconds.");
  });

  test("opt-in, pause, missing gaze, and the heir fence block the note", () => {
    const summaries = [{ area: "twin", dwell_ms: 2000 }];
    expect(shouldSendGaze({ gazeEnabled: false, available: true, summaries }).reason).toBe("opt-in-off");
    expect(shouldSendGaze({ gazeEnabled: true, paused: true, available: true, summaries }).reason).toBe("paused");
    expect(shouldSendGaze({ gazeEnabled: true, available: false, summaries }).reason).toBe("unavailable");
    expect(shouldSendGaze({ gazeEnabled: true, available: true, audience: "heir", summaries }).reason).toBe("heir");
    expect(shouldSendGaze({ gazeEnabled: true, available: true, heirSurface: true, summaries }).reason).toBe("heir");
    expect(shouldSendGaze({ gazeEnabled: true, available: true, summaries }).send).toBe(true);
  });

  test("PSVR2 on PC does not pretend eye tracking is available", () => {
    const psvr = gazeSupport({ headsetId: "psvr2", features: [] });
    expect(psvr.available).toBe(false);
    expect(psvr.psvr2PcExposed).toBe(false);
    expect(psvr.extension).toBe("XR_EXT_eye_gaze_interaction");
    expect(psvr.reason.toLowerCase()).toMatch(/not exposed/);
    const browser = gazeSupport({ features: [] });
    expect(browser.available).toBe(false);
    expect(browser.reason).toMatch(/WebXR/);
    expect(gazeSupport({ features: ["eye-tracking"] }).available).toBe(true);
  });

  test("a forward ray lands on the twin, and the accumulator keeps dwell only", () => {
    expect(areaAlongRay([0, 1.2, 0], [0, 0, -1])).toBe("twin");
    expect(areaAlongRay([0, 1.6, 0], [0, -1, 0])).toBe("floor");
    const acc = createGazeAccumulator();
    acc.sample("twin", 0);
    acc.sample("twin", 500);
    acc.sample("room", 2000);
    const summaries = acc.flush(2800);
    expect(summaries).toEqual([
      { area: "twin", dwell_ms: 2000 },
      { area: "room", dwell_ms: 800 },
    ]);
    expect(JSON.stringify(summaries)).not.toMatch(/origin|direction/);
  });
});
