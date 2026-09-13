/** Standing Twin routines — owner-only, consent-first, quiet when empty. */

export const ROUTINE_KINDS = [
  [
    "morning_brief",
    "Morning brief",
    "A quiet note in your voice when something is on the plate — due reminders, what you filed yesterday, a letter coming due. Empty mornings stay silent.",
  ],
  [
    "weekly_biographer",
    "Weekly biographer",
    "Once a week, one grounded question about a part of your life that is still thin in the archive. If there is not enough to ask from, it stays quiet.",
  ],
  [
    "sealed_letter_nudge",
    "Sealed letter nudge",
    "A light tap when a draft is still unsealed, or an heir still has no letter. No nag when nothing is waiting.",
  ],
];

export const ROUTINE_COPY = {
  heading: "Standing routines",
  blurb:
    "Your Twin can check in without being asked — only the notes you turn on, only when there is something real to say. Heirs never see these.",
  quiet: "Nothing to report stays quiet. No empty-morning nag.",
  ownerOnly: "Owner sessions only. Heirs keep the gift voice — they never inherit these routines.",
};

const DEFAULT_ROUTINES = {
  morning_brief: false,
  weekly_biographer: false,
  sealed_letter_nudge: false,
};

function _enabled(item) {
  if (item === true || item === false) return item;
  if (item && typeof item === "object") return item.enabled === true;
  return false;
}

export function routinesFromMe(data) {
  const src = data && typeof data === "object" ? data.standing_routines || data : {};
  const out = { ...DEFAULT_ROUTINES };
  for (const [kind] of ROUTINE_KINDS) {
    out[kind] = _enabled(src[kind]);
  }
  return out;
}

export function routinesPayload(routines) {
  const next = routinesFromMe({ standing_routines: routines });
  return {
    morning_brief: !!next.morning_brief,
    weekly_biographer: !!next.weekly_biographer,
    sealed_letter_nudge: !!next.sealed_letter_nudge,
  };
}

export function shouldShowNudge(nudge) {
  return !!(nudge && !nudge.quiet && nudge.title && nudge.status !== "dismissed");
}

export function routineActionHref(nudge) {
  if (!nudge || typeof nudge !== "object") return "/owner";
  if (nudge.kind === "weekly_biographer") {
    const q = nudge.action_prompt || nudge.title || "";
    return `/interviewer?topic=${encodeURIComponent(q)}&key=weekly_biographer`;
  }
  if (nudge.kind === "sealed_letter_nudge") return "/letters";
  if (nudge.action_href) return nudge.action_href;
  if (nudge.kind === "morning_brief") return "/reminders";
  return `/interviewer?topic=${encodeURIComponent(nudge.action_prompt || nudge.title || "")}&key=nudge_${nudge.nudge_id || "today"}`;
}

export function heirPortalMustExcludeRoutines(src) {
  const text = String(src || "");
  return (
    !text.includes("/nudges/routines") &&
    !text.includes("standing_routines") &&
    !text.includes("morning_brief") &&
    !text.includes("weekly_biographer")
  );
}
