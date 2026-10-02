/** Assignments v1 — display helpers. The server owns legal transitions. */

export const ASSIGNMENT_STATUSES = [
  "queued",
  "running",
  "needs_approval",
  "done",
  "failed",
  "cancelled",
];

export const STATUS_LABELS = {
  queued: "Queued",
  running: "Running",
  needs_approval: "Needs approval",
  done: "Done",
  failed: "Failed",
  cancelled: "Cancelled",
};

/** Mirrors the server table so the page can show where a status can go. */
export const LEGAL_TRANSITIONS = {
  queued: ["running", "cancelled"],
  running: ["needs_approval", "done", "failed", "cancelled"],
  needs_approval: ["done", "cancelled", "failed"],
  done: [],
  failed: [],
  cancelled: [],
};

export const PRESETS = [
  {
    id: "triage_email",
    label: "Triage email",
    title: "Triage email",
    goal: "Read what the owner pointed at and draft a short triage: what needs a reply, what can wait, and what to leave alone.",
    scope: "Heirloom only. Draft replies. Do not send email.",
    autonomy: "draft",
  },
  {
    id: "summarize_thread",
    label: "Summarize thread",
    title: "Summarize thread",
    goal: "Summarize the thread into a short note the owner can act on.",
    scope: "Read the thread. Write a summary artifact. Do not reply, post, or send.",
    autonomy: "draft",
  },
  {
    id: "blank",
    label: "Blank",
    title: "",
    goal: "",
    scope: "",
    autonomy: "draft",
  },
];

const PRESET_ALIASES = {
  triage: "triage_email",
  email: "triage_email",
  summarize: "summarize_thread",
  summary: "summarize_thread",
  thread: "summarize_thread",
};

export function statusLabel(status) {
  return STATUS_LABELS[String(status || "").trim().toLowerCase()] || "Unknown";
}

export function canTransition(src, dst) {
  const from = String(src || "").trim().toLowerCase();
  const to = String(dst || "").trim().toLowerCase();
  return (LEGAL_TRANSITIONS[from] || []).includes(to);
}

export function nextStatusLabels(status) {
  const from = String(status || "").trim().toLowerCase();
  return (LEGAL_TRANSITIONS[from] || []).map(statusLabel);
}

export function transitionLabel(src, dst) {
  if (!canTransition(src, dst)) return "";
  return `${statusLabel(src)} → ${statusLabel(dst)}`;
}

export function statusIsOpen(status) {
  const key = String(status || "").trim().toLowerCase();
  return key === "queued" || key === "running" || key === "needs_approval";
}

export function presetPrefill(presetId) {
  const raw = String(presetId || "").trim().toLowerCase().replace(/[\s-]+/g, "_");
  const id = PRESET_ALIASES[raw] || raw;
  const spec = PRESETS.find((row) => row.id === id) || PRESETS[PRESETS.length - 1];
  return {
    preset: spec.id,
    label: spec.label,
    title: spec.title,
    goal: spec.goal,
    scope: spec.scope,
    autonomy: spec.autonomy,
  };
}

export function payloadLines(payload) {
  if (payload == null || payload === "") return [];
  if (typeof payload !== "object") return [["text", String(payload)]];
  return Object.entries(payload).map(([key, value]) => [
    key,
    typeof value === "string" ? value : JSON.stringify(value),
  ]);
}

export function assignmentHref(assignmentOrId) {
  const id = typeof assignmentOrId === "string"
    ? assignmentOrId
    : assignmentOrId?.assignment_id;
  if (!id) return "/assignments";
  return `/assignments/${id}`;
}
