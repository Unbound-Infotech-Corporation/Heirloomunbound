export const TWIN_SETUP_CHANGED = "heirloom:twin-setup-changed";

export function notifyTwinSetupChanged() {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(TWIN_SETUP_CHANGED));
}

export function remainingCritical(progress) {
  if (!progress) return 2;
  if (typeof progress.remaining_critical === "number") return progress.remaining_critical;
  return (progress.steps || []).filter((s) => s.critical && !s.done).length;
}

export function coachShouldShow(progress, { dismissedOverride } = {}) {
  if (!progress) return false;
  if (progress.youre_set || progress.all_critical_done) return false;
  const dismissed = dismissedOverride ?? progress.coach_dismissed;
  if (dismissed) return false;
  return remainingCritical(progress) > 0;
}

export function stepById(progress, id) {
  return (progress?.steps || []).find((s) => s.id === id) || null;
}
