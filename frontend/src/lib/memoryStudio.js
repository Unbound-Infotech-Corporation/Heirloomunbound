/** Memory Studio v1 — owner-only visible memory. No invented biography. */

export const MEMORY_STUDIO_PATH = "/memory";

export const PAIRING_STYLES = [
  ["teammate", "Teammate", "Decide defaults and do the job."],
  ["wait", "Wait", "Propose the next step and wait."],
  ["proactive", "Proactive", "Take the next obvious safe step."],
];

export const PAIRING_TOGGLES = [
  ["act_default", "Act by default", "Do the work unless you asked to wait or Confirm is required."],
  ["close_loop", "Close the loop", "After acting, report in one to three sentences."],
  ["remember_prefs", "Remember this", "Keep this style until you change it."],
];

export const MEMORY_COPY = {
  emptyFacts:
    "Nothing held yet. Facts appear as your archive grows — extracted from what you filed, never invented.",
  factsError: "Couldn't load what the Twin holds. Try again.",
  prefsError: "Couldn't load how we work. Try again.",
  fenceEmpty: "No fenced topics. Your twin will engage freely.",
  ownerOnly: "Owner sessions only. Heirs keep the gift voice — they never see this studio.",
};

const DEFAULT_PAIRING = {
  pairing_style: "teammate",
  act_default: true,
  close_loop: true,
  remember_prefs: true,
};

export function pairingFromMe(data) {
  const src = data && typeof data === "object" ? data : {};
  const style = String(src.pairing_style || DEFAULT_PAIRING.pairing_style).trim().toLowerCase();
  return {
    pairing_style: PAIRING_STYLES.some(([id]) => id === style) ? style : DEFAULT_PAIRING.pairing_style,
    act_default: src.act_default !== false,
    close_loop: src.close_loop !== false,
    remember_prefs: src.remember_prefs !== false,
  };
}

export function pairingPayload(pairing) {
  const next = pairingFromMe(pairing);
  return {
    pairing_style: next.pairing_style,
    act_default: !!next.act_default,
    close_loop: !!next.close_loop,
    remember_prefs: !!next.remember_prefs,
  };
}

export function formatFactProvenance(fact) {
  if (!fact || typeof fact !== "object") {
    return { kind: "other", source: "held without a source entry", when: "" };
  }
  const kind = String(fact.kind || "other").trim() || "other";
  const sourceId = fact.source_entry_id || fact.source_capture_id || "";
  const source = sourceId
    ? `from archive #${String(sourceId).slice(0, 24)}`
    : "held without a source entry";
  const raw = fact.created_at || fact.updated_at || "";
  let when = "";
  if (raw) {
    const d = new Date(raw);
    when = Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString();
  }
  return { kind, source, when };
}

export function nextSafeTopics(topics, topic) {
  const t = String(topic || "").trim();
  if (!t) return Array.isArray(topics) ? topics : [];
  return Array.from(new Set([...(topics || []), t])).slice(0, 25);
}

/** Owner studio routes — never linked from the heir portal. */
export const OWNER_MEMORY_ROUTES = [MEMORY_STUDIO_PATH, "/personality", "/settings", "/owner"];

export function isOwnerMemoryRoute(pathname) {
  const path = String(pathname || "").split("?")[0];
  return path === MEMORY_STUDIO_PATH || path === "/studio/memory";
}

export function heirPortalMustExclude(src) {
  const text = String(src || "");
  return (
    !text.includes(MEMORY_STUDIO_PATH) &&
    !text.includes("/studio/memory") &&
    !text.includes("/auth/me/preferences") &&
    !text.includes("/memory/facts")
  );
}
