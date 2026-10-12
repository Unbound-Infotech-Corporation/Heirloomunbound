/** Presence controls. Off unless the box health flag says so. Heirs never see them. */

export const CONSENT_TEXT = "This person agreed to be recognized by Heirloom on this box.";
export const SAMPLE_GOAL = 5;

export function presenceEnabled(health) {
  const presence = health && health.presence;
  if (!presence || typeof presence !== "object") return false;
  return presence.enabled === true || presence.enabled === 1 || presence.enabled === "1";
}

export function canShowPresenceControls({
  enabled = false,
  audience = "owner",
  heirSurface = false,
} = {}) {
  if (!enabled || heirSurface) return false;
  return String(audience || "owner").trim().toLowerCase() === "owner";
}

export function presentLabel(present) {
  const names = (Array.isArray(present) ? present : [])
    .map((person) => (person && person.name ? String(person.name).trim() : ""))
    .filter(Boolean);
  if (!names.length) return "Nobody enrolled is here";
  return names.join(", ");
}

export function cameraSummary(cameras, fps) {
  const list = Array.isArray(cameras) ? cameras : [];
  const open = list.filter((camera) => camera && camera.open).length;
  const count = list.length;
  const rate = Number(fps) || 0;
  if (!count) return `no camera · ${rate} fps`;
  const noun = count === 1 ? "camera" : "cameras";
  return `${open}/${count} ${noun} · ${rate} fps`;
}

export function samplesStillNeeded(count, goal = SAMPLE_GOAL) {
  const have = Number(count) || 0;
  return Math.max(0, goal - have);
}

export function consentText() {
  return CONSENT_TEXT;
}
