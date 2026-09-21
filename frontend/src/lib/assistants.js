/** Named specialists under the twin. Twin stays the person. */

export const TWIN_SPEAKER = {
  assistant_id: null,
  name: "Twin",
  slug: "twin",
  role: "The person. First-person from the vault.",
  speak_as: "twin",
  enabled: true,
};

export const MENTION_RE = /^@([A-Za-z0-9][\w-]{0,47})\b[:,]?\s*/;

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
  return raw.slice(0, 32) || "assistant";
}

export function matchAssistant(assistants, { assistantId, mention } = {}) {
  const enabled = (assistants || []).filter((a) => a && a.enabled !== false);
  if (assistantId) {
    return enabled.find((a) => a.assistant_id === assistantId) || null;
  }
  const key = String(mention || "").trim().toLowerCase();
  if (!key) return null;
  return (
    enabled.find((a) => {
      const slug = String(a.slug || slugifyAssistant(a.name)).toLowerCase();
      const name = String(a.name || "").trim().toLowerCase();
      const id = String(a.assistant_id || "").toLowerCase();
      return slug === key || name === key || id === key || id.endsWith(key);
    }) || null
  );
}

export function speakerOptions(assistants) {
  const enabled = (assistants || []).filter((a) => a && a.enabled !== false);
  return [
    { assistant_id: null, name: "Twin", slug: "twin", speak_as: "twin", role: TWIN_SPEAKER.role },
    ...enabled,
  ];
}

export function speakerLabel(message, assistants) {
  if (message?.specialist_name) return message.specialist_name;
  if (message?.specialist_id) {
    const found = (assistants || []).find((a) => a.assistant_id === message.specialist_id);
    if (found) return found.name;
  }
  return "you (the twin)";
}

export function isPcSpecialist(assistant) {
  if (!assistant) return false;
  if (String(assistant.speak_as || "").toLowerCase() === "assist") return true;
  const tools = assistant.tools_allowlist || [];
  return tools.some((t) =>
    ["open_on_pc", "see_screen", "run_command", "type_text", "power_action"].includes(t)
  );
}
