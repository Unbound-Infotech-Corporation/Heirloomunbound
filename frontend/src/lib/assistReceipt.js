/** Assist action receipts — rendering helpers for Sit / Do turns.

 * Twin-only messages do not show a receipt. Assist and owner-rail Do
 * legs show Plan (optional) → Did / Failed / Waiting for Confirm.
 */

export const RECEIPT_STATUS_LABEL = {
  did: "Did",
  failed: "Failed",
  waiting_confirm: "Waiting for Confirm",
  planned: "Plan",
};

export function receiptStatusLabel(status) {
  const key = String(status || "").trim();
  return RECEIPT_STATUS_LABEL[key] || RECEIPT_STATUS_LABEL.did;
}

function asStep(row) {
  if (!row || typeof row !== "object") return null;
  const name = String(row.name || "").trim();
  if (!name) return null;
  return {
    id: String(row.id || name),
    name,
    label: String(row.label || name),
    ok: Boolean(row.ok),
    needs_confirm: Boolean(row.needs_confirm),
    summary: String(row.summary || "").trim(),
  };
}

export function normalizeReceipt(raw) {
  if (!raw || typeof raw !== "object") return null;
  const steps = Array.isArray(raw.steps) ? raw.steps.map(asStep).filter(Boolean) : [];
  const plan = Array.isArray(raw.plan)
    ? raw.plan.map((item) => String(item || "").trim()).filter(Boolean)
    : [];
  const statusKey = String(raw.status || "").trim();
  const status = RECEIPT_STATUS_LABEL[statusKey] ? statusKey : "did";
  const summary = String(raw.summary || "").trim();
  if (!summary && !steps.length && !plan.length) return null;
  return {
    status,
    summary,
    steps,
    plan: plan.length ? plan : null,
  };
}

/** Sit / Assist Do only. Twin-only turns never show a receipt. */
export function shouldShowReceipt(message) {
  const receipt = normalizeReceipt(message?.receipt);
  if (!receipt) return false;
  const rail = String(message?.rail || "").trim().toLowerCase();
  if (rail === "twin") return false;
  return true;
}

export function splitOwnerLegs(message) {
  const twinStored = String(message?.twin_reply || "").trim();
  const assistStored = String(message?.assist_reply || "").trim();
  if (twinStored || assistStored) {
    return { twinReply: twinStored, assistReply: assistStored };
  }
  const rail = String(message?.rail || "").trim().toLowerCase();
  const content = String(message?.content || message?.reply || "").trim();
  if (rail === "assist") {
    return { twinReply: "", assistReply: content };
  }
  if (rail === "both") {
    const parts = content.split(/\n\n+/);
    if (parts.length >= 2) {
      return { twinReply: parts[0].trim(), assistReply: parts.slice(1).join("\n\n").trim() };
    }
    return { twinReply: content, assistReply: "" };
  }
  return { twinReply: content, assistReply: "" };
}

export function receiptConfirmCopy(receipt) {
  const normalized = normalizeReceipt(receipt);
  if (!normalized || normalized.status !== "waiting_confirm") return "";
  return "Confirm in this document. Reply Confirm to run it; cancel leaves it unrun.";
}
