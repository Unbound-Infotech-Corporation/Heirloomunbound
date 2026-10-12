import {
  cameraSummary,
  canShowPresenceControls,
  consentText,
  presenceEnabled,
  presentLabel,
  samplesStillNeeded,
  CONSENT_TEXT,
  SAMPLE_GOAL,
} from "./presence";

describe("presence helpers", () => {
  test("stays off unless health says the box enabled it", () => {
    expect(presenceEnabled(null)).toBe(false);
    expect(presenceEnabled({})).toBe(false);
    expect(presenceEnabled({ presence: { enabled: false } })).toBe(false);
    expect(presenceEnabled({ presence: { enabled: true } })).toBe(true);
  });

  test("heirs never see presence controls", () => {
    expect(canShowPresenceControls({ enabled: true, audience: "heir" })).toBe(false);
    expect(canShowPresenceControls({ enabled: true, audience: "caller" })).toBe(false);
    expect(canShowPresenceControls({ enabled: true, audience: "owner", heirSurface: true })).toBe(false);
    expect(canShowPresenceControls({ enabled: false, audience: "owner" })).toBe(false);
    expect(canShowPresenceControls({ enabled: true, audience: "owner" })).toBe(true);
  });

  test("labels who is here and how many samples are left", () => {
    expect(presentLabel([])).toBe("Nobody enrolled is here");
    expect(presentLabel([{ name: "Alex" }, { name: "Sam" }])).toBe("Alex, Sam");
    expect(cameraSummary([], 0)).toBe("no camera · 0 fps");
    expect(cameraSummary([{ open: true }, { open: false }], 3)).toBe("1/2 cameras · 3 fps");
    expect(samplesStillNeeded(2)).toBe(3);
    expect(samplesStillNeeded(SAMPLE_GOAL)).toBe(0);
    expect(consentText()).toBe(CONSENT_TEXT);
  });
});
