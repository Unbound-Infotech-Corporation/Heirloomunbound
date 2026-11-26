/** Who we greet, and what a brand-new archive should do first. */

function firstWord(value) {
  return String(value || "").trim().split(/\s+/)[0] || "";
}

function looksLikeHandle(name, email) {
  const n = String(name || "").trim();
  if (!n || /\s/.test(n)) return false;
  const local = String(email || "").split("@")[0].toLowerCase().replace(/[^a-z0-9]/g, "");
  const flat = n.toLowerCase().replace(/[^a-z0-9]/g, "");
  if (local && flat === local) return true;
  // An all-lowercase single word with digits reads like an account name, not a person.
  return n === n.toLowerCase() && /\d/.test(n);
}

/** The owner's preferred first name, or "" when all we have is an account handle. */
export function greetingName(user) {
  if (!user) return "";
  const preferred = firstWord(user.preferred_name);
  if (preferred) return preferred;
  if (looksLikeHandle(user.name, user.email)) return "";
  return firstWord(user.name);
}

/** "Good evening, Chris." or "Good evening." */
export function greetingLine(salutation, user) {
  const name = greetingName(user);
  return name ? `${salutation}, ${name}.` : `${salutation}.`;
}

export const FIRST_STEPS = [
  { key: "record", label: "Record your first memory", desc: "One story, a few lines. The twin learns from it.", to: "/record" },
  { key: "interview", label: "Sit with the interviewer", desc: "Ten gentle questions about your life.", to: "/interviewer" },
  { key: "twin", label: "Say hello to your twin", desc: "Hear how it sounds with what it holds so far.", to: "/twin" },
  { key: "heir", label: "Name an heir", desc: "Choose who will one day sit with your twin.", to: "/heirs" },
];

/** The four first steps with done flags, from /api/dashboard stats. */
export function firstSteps(stats) {
  const s = stats || {};
  const done = {
    record: (s.total_entries || 0) > 0,
    interview: (s.interview_conversations || 0) > 0,
    twin: (s.twin_conversations || 0) > 0,
    heir: (s.heirs || 0) > 0,
  };
  return FIRST_STEPS.map((step) => ({ ...step, done: done[step.key] }));
}

/** Show first steps instead of a row of zeros until the archive holds something. */
export function isFreshArchive(stats) {
  if (!stats) return false;
  return (stats.total_entries || 0) === 0 && (stats.streak_days || 0) === 0;
}
