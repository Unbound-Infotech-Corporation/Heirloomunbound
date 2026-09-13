import {
  normalizeReceipt,
  receiptConfirmCopy,
  receiptStatusLabel,
  shouldShowReceipt,
  splitOwnerLegs,
} from "./assistReceipt";

describe("assistReceipt helpers", () => {
  test("status labels cover the Sit chip set", () => {
    expect(receiptStatusLabel("did")).toBe("Did");
    expect(receiptStatusLabel("failed")).toBe("Failed");
    expect(receiptStatusLabel("waiting_confirm")).toBe("Waiting for Confirm");
    expect(receiptStatusLabel("planned")).toBe("Plan");
    expect(receiptStatusLabel("")).toBe("Did");
  });

  test("normalizeReceipt drops empty payloads and keeps steps", () => {
    expect(normalizeReceipt(null)).toBeNull();
    expect(normalizeReceipt({})).toBeNull();
    const rec = normalizeReceipt({
      status: "did",
      summary: "Opened Chrome",
      steps: [{ id: "1", name: "open_on_pc", label: "Open on this PC", ok: true }],
      plan: ["Open on this PC", ""],
    });
    expect(rec.status).toBe("did");
    expect(rec.steps).toHaveLength(1);
    expect(rec.plan).toEqual(["Open on this PC"]);
  });

  test("shouldShowReceipt is Assist / Do only", () => {
    const receipt = { status: "did", summary: "Opened Chrome", steps: [] };
    expect(shouldShowReceipt({ rail: "assist", receipt })).toBe(true);
    expect(shouldShowReceipt({ rail: "both", receipt })).toBe(true);
    expect(shouldShowReceipt({ receipt })).toBe(true);
    expect(shouldShowReceipt({ rail: "twin", receipt })).toBe(false);
    expect(shouldShowReceipt({ rail: "assist" })).toBe(false);
    expect(shouldShowReceipt({ rail: "twin" })).toBe(false);
  });

  test("splitOwnerLegs keeps both-leg replies separate", () => {
    expect(
      splitOwnerLegs({
        rail: "both",
        twin_reply: "I remember the lake.",
        assist_reply: "Opened the calendar.",
        content: "merged",
      })
    ).toEqual({ twinReply: "I remember the lake.", assistReply: "Opened the calendar." });

    expect(splitOwnerLegs({ rail: "assist", content: "Opened Chrome." })).toEqual({
      twinReply: "",
      assistReply: "Opened Chrome.",
    });

    expect(splitOwnerLegs({ rail: "twin", content: "A story from the vault." })).toEqual({
      twinReply: "A story from the vault.",
      assistReply: "",
    });

    expect(
      splitOwnerLegs({
        rail: "both",
        content: "Filed the dentist.\n\nOpened the calendar.",
      })
    ).toEqual({
      twinReply: "Filed the dentist.",
      assistReply: "Opened the calendar.",
    });
  });

  test("confirm copy is in-document only", () => {
    expect(receiptConfirmCopy({ status: "did", summary: "Done", steps: [] })).toBe("");
    expect(receiptConfirmCopy({ status: "waiting_confirm", summary: "Wait", steps: [] })).toMatch(
      /Confirm in this document/
    );
    expect(receiptConfirmCopy({ status: "waiting_confirm", summary: "Wait", steps: [] })).not.toMatch(
      /MessageBox|dialog/
    );
  });
});
