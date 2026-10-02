import {
  canTransition,
  nextStatusLabels,
  payloadLines,
  presetPrefill,
  statusLabel,
  transitionLabel,
} from "./assignments";

describe("assignment status display", () => {
  test("labels the six statuses", () => {
    expect(statusLabel("queued")).toBe("Queued");
    expect(statusLabel("running")).toBe("Running");
    expect(statusLabel("needs_approval")).toBe("Needs approval");
    expect(statusLabel("done")).toBe("Done");
    expect(statusLabel("failed")).toBe("Failed");
    expect(statusLabel("cancelled")).toBe("Cancelled");
    expect(statusLabel("nope")).toBe("Unknown");
  });

  test("shows only legal next statuses", () => {
    expect(nextStatusLabels("queued")).toEqual(["Running", "Cancelled"]);
    expect(nextStatusLabels("running")).toEqual([
      "Needs approval",
      "Done",
      "Failed",
      "Cancelled",
    ]);
    expect(nextStatusLabels("needs_approval")).toEqual(["Done", "Cancelled", "Failed"]);
    expect(nextStatusLabels("done")).toEqual([]);
    expect(nextStatusLabels("failed")).toEqual([]);
    expect(nextStatusLabels("cancelled")).toEqual([]);
  });

  test("transition copy is empty when the move is illegal", () => {
    expect(canTransition("done", "running")).toBe(false);
    expect(transitionLabel("done", "running")).toBe("");
    expect(transitionLabel("queued", "cancelled")).toBe("Queued → Cancelled");
    expect(transitionLabel("needs_approval", "done")).toBe("Needs approval → Done");
  });
});

describe("assignment presets", () => {
  test("prefill title, goal, scope, and draft autonomy", () => {
    const triage = presetPrefill("triage_email");
    expect(triage.title).toBe("Triage email");
    expect(triage.goal).toMatch(/triage/i);
    expect(triage.scope).toMatch(/do not send/i);
    expect(triage.autonomy).toBe("draft");

    const thread = presetPrefill("summarize");
    expect(thread.preset).toBe("summarize_thread");
    expect(thread.title).toBe("Summarize thread");
    expect(thread.goal).toMatch(/summarize/i);
    expect(thread.autonomy).toBe("draft");

    const blank = presetPrefill("blank");
    expect(blank.title).toBe("");
    expect(blank.goal).toBe("");
    expect(blank.scope).toBe("");
    expect(blank.autonomy).toBe("draft");
  });

  test("unknown preset falls back to blank", () => {
    expect(presetPrefill("nope").preset).toBe("blank");
    expect(presetPrefill("").title).toBe("");
  });
});

describe("approval payload display", () => {
  test("shows exactly the fields that would be sent", () => {
    expect(payloadLines({ to: "ada@example.com", body: "Hello" })).toEqual([
      ["to", "ada@example.com"],
      ["body", "Hello"],
    ]);
    expect(payloadLines({ items: ["a"] })).toEqual([["items", "[\"a\"]"]]);
    expect(payloadLines(null)).toEqual([]);
  });
});
