import {
  audioStreamLine,
  canShowObserverControls,
  feedbackLabel,
  observerEnabled,
  watchedSourceLabel,
  WATCHED_SOURCE,
} from "./observer";

describe("observer helpers", () => {
  test("stays off unless health says the box enabled it", () => {
    expect(observerEnabled(null)).toBe(false);
    expect(observerEnabled({})).toBe(false);
    expect(observerEnabled({ observer: { enabled: false } })).toBe(false);
    expect(observerEnabled({ observer: { enabled: true } })).toBe(true);
  });

  test("heirs never see observer controls", () => {
    expect(canShowObserverControls({ enabled: true, audience: "heir" })).toBe(false);
    expect(canShowObserverControls({ enabled: true, audience: "caller" })).toBe(false);
    expect(canShowObserverControls({ enabled: true, audience: "owner", heirSurface: true })).toBe(false);
    expect(canShowObserverControls({ enabled: false, audience: "owner" })).toBe(false);
    expect(canShowObserverControls({ enabled: true, audience: "owner" })).toBe(true);
  });

  test("labels owner feedback and the watched source", () => {
    expect(feedbackLabel("thats_me")).toBe("That's me");
    expect(feedbackLabel("not_me")).toBe("Not me");
    expect(feedbackLabel("never")).toBe("Never learn this");
    expect(feedbackLabel("")).toBe("");
    expect(watchedSourceLabel(`note#1 · ${WATCHED_SOURCE}`)).toBe(WATCHED_SOURCE);
    expect(watchedSourceLabel("vault#4")).toBe("");
  });

  test("labels system audio and the microphone separately", () => {
    expect(audioStreamLine(null, "System audio")).toBe("System audio: off");
    expect(audioStreamLine({ enabled: false, status: "hearing", source: "xr1" }, "System audio")).toBe("System audio: off");
    expect(audioStreamLine({ enabled: true, status: "hearing", source: "xr1", device: "EVGA XR1 Lite" }, "System audio"))
      .toBe("System audio: hearing · EVGA XR1 Lite");
    expect(audioStreamLine({ enabled: true, status: "silent", source: "c920", device: "HD Pro Webcam C920" }, "Microphone"))
      .toBe("Microphone: silent · HD Pro Webcam C920");
    expect(audioStreamLine({ enabled: true, status: "waiting", source: "waiting" }, "Microphone")).toBe("Microphone: waiting");
  });
});
