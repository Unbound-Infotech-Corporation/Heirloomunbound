/** Named Clones under the twin. Twin stays the person. */

export const TWIN_SPEAKER = {
  clone_id: null,
  assistant_id: null,
  name: "Twin",
  slug: "twin",
  role: "The person. First-person from the vault.",
  speak_as: "twin",
  enabled: true,
};

export const MENTION_RE = /^@([A-Za-z0-9][\w-]{0,47})\b[:,]?\s*/;

export function cloneIdOf(item) {
  if (!item) return null;
  return item.clone_id || item.assistant_id || null;
}

export function parseAssistantMention(text) {
  const src = String(text || "");
  const m = src.match(MENTION_RE);
  if (!m) return { mention: null, remainder: src };
  return { mention: m[1], remainder: src.slice(m[0].length) };
}

export function slugifyAssistant(name) {
  const raw = String(name || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  return raw.slice(0, 32) || "clone";
}

export function matchAssistant(clones, { assistantId, cloneId, mention } = {}) {
  const enabled = (clones || []).filter((a) => a && a.enabled !== false);
  const id = cloneId || assistantId;
  if (id) {
    return enabled.find((a) => cloneIdOf(a) === id) || null;
  }
  const key = String(mention || "").trim().toLowerCase();
  if (!key) return null;
  return (
    enabled.find((a) => {
      const slug = String(a.slug || slugifyAssistant(a.name)).toLowerCase();
      const name = String(a.name || "").trim().toLowerCase();
      const cid = String(cloneIdOf(a) || "").toLowerCase();
      return slug === key || name === key || cid === key || cid.endsWith(key);
    }) || null
  );
}

export function speakerOptions(clones) {
  const enabled = (clones || []).filter((a) => a && a.enabled !== false);
  return [
    { clone_id: null, assistant_id: null, name: "Twin", slug: "twin", speak_as: "twin", role: TWIN_SPEAKER.role },
    ...enabled,
  ];
}

export function speakerLabel(message, clones) {
  if (message?.specialist_name) return message.specialist_name;
  const sid = message?.clone_id || message?.specialist_id || message?.assistant_id;
  if (sid) {
    const found = (clones || []).find((a) => cloneIdOf(a) === sid);
    if (found) return found.name;
  }
  return "you (the twin)";
}

export function isPcSpecialist(clone) {
  if (!clone) return false;
  if (String(clone.speak_as || "").toLowerCase() === "assist") return true;
  const tools = clone.tools_allowlist || [];
  return tools.some((t) =>
    ["open_on_pc", "see_screen", "run_command", "type_text", "power_action"].includes(t)
  );
}
