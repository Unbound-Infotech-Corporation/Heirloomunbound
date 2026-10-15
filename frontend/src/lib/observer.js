/** Observer controls. Off unless the box health flag says so. Heirs never see them. */

export const WATCHED_SOURCE = "from what I've watched";

export function observerEnabled(health) {
  const observer = health && health.observer;
  if (!observer || typeof observer !== "object") return false;
  return observer.enabled === true || observer.enabled === 1 || observer.enabled === "1";
}

export function canShowObserverControls({
  enabled = false,
  audience = "owner",
  heirSurface = false,
} = {}) {
  if (!enabled || heirSurface) return false;
  return String(audience || "owner").trim().toLowerCase() === "owner";
}

export function feedbackLabel(vote) {
  if (vote === "thats_me") return "That's me";
  if (vote === "not_me") return "Not me";
  if (vote === "never") return "Never learn this";
  return "";
}

export function audioStreamLine(stream, label) {
  if (!stream || typeof stream !== "object" || stream.enabled === false || stream.status === "off") {
    return `${label}: off`;
  }
  const status = stream.status || "waiting";
  const where = stream.device || (stream.source && stream.source !== "off" && stream.source !== "waiting" ? stream.source : "");
  return where ? `${label}: ${status} · ${where}` : `${label}: ${status}`;
}

export function watchedSourceLabel(label) {
  if (!label) return "";
  return String(label).includes(WATCHED_SOURCE) ? WATCHED_SOURCE : "";
}
