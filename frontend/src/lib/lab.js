/** Lab-mode helpers. Heirs never see controls. Off unless the server says so. */

export function labModeFromHealth(health) {
  if (!health || typeof health !== "object") return false;
  return health.lab_mode === true || health.lab_mode === 1 || health.lab_mode === "1";
}

export function canShowLabControls({
  labMode = false,
  audience = "owner",
  heirSurface = false,
} = {}) {
  if (!labMode || heirSurface) return false;
  return String(audience || "owner").trim().toLowerCase() === "owner";
}

export function voteLabel(vote) {
  if (vote === "up") return "Useful";
  if (vote === "down") return "Not useful";
  return "";
}

export function summarizeTurns(turns) {
  const rows = Array.isArray(turns) ? turns : [];
  const summary = {
    turns: rows.length,
    up: 0,
    down: 0,
    errors: 0,
    approvalsCreated: 0,
    approvalsApproved: 0,
    approvalsDeclined: 0,
    byRoute: {},
  };
  rows.forEach((row) => {
    const route = row?.route || "unknown";
    summary.byRoute[route] = (summary.byRoute[route] || 0) + 1;
    const vote = row?.feedback?.vote;
    if (vote === "up") summary.up += 1;
    if (vote === "down") summary.down += 1;
    if (row?.error) summary.errors += 1;
    summary.approvalsCreated += Number(row?.approvals_created || 0);
    summary.approvalsApproved += Number(row?.approvals_approved || 0);
    summary.approvalsDeclined += Number(row?.approvals_declined || 0);
  });
  return summary;
}

export function healthLine(health) {
  if (!health || typeof health !== "object") return "health unavailable";
  const status = health.status || "unknown";
  const provider = health.llm_provider || "emergent";
  const lab = health.lab_mode ? "lab on" : "lab off";
  return `${status} · ${provider} · ${lab}`;
}
