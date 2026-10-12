import {
  canShowLabControls,
  healthLine,
  labModeFromHealth,
  summarizeTurns,
  voteLabel,
} from "./lab";

describe("lab helpers", () => {
  test("heirs never see lab controls", () => {
    expect(canShowLabControls({ labMode: true, audience: "heir" })).toBe(false);
    expect(canShowLabControls({ labMode: true, audience: "caller" })).toBe(false);
    expect(canShowLabControls({ labMode: true, audience: "owner", heirSurface: true })).toBe(false);
    expect(canShowLabControls({ labMode: false, audience: "owner" })).toBe(false);
    expect(canShowLabControls({ labMode: true, audience: "owner" })).toBe(true);
  });

  test("reads lab mode only from an explicit health flag", () => {
    expect(labModeFromHealth(null)).toBe(false);
    expect(labModeFromHealth({ lab_mode: false })).toBe(false);
    expect(labModeFromHealth({ lab_mode: true })).toBe(true);
    expect(labModeFromHealth({ lab_mode: "1" })).toBe(true);
  });

  test("labels votes and summarizes local turns", () => {
    expect(voteLabel("up")).toBe("Useful");
    expect(voteLabel("down")).toBe("Not useful");
    expect(voteLabel("")).toBe("");
    const summary = summarizeTurns([
      { route: "twin", feedback: { vote: "up" }, approvals_created: 1 },
      { route: "assist", error: "timeout", approvals_declined: 2 },
      { route: "clone", feedback: { vote: "down", note: "vague" } },
    ]);
    expect(summary.turns).toBe(3);
    expect(summary.up).toBe(1);
    expect(summary.down).toBe(1);
    expect(summary.errors).toBe(1);
    expect(summary.approvalsCreated).toBe(1);
    expect(summary.approvalsDeclined).toBe(2);
    expect(summary.byRoute).toEqual({ twin: 1, assist: 1, clone: 1 });
  });

  test("health line names status, provider, and lab", () => {
    expect(healthLine(null)).toBe("health unavailable");
    expect(healthLine({ status: "ok", llm_provider: "ollama", lab_mode: true })).toBe(
      "ok · ollama · lab on",
    );
    expect(healthLine({ status: "ok" })).toBe("ok · emergent · lab off");
  });
});
