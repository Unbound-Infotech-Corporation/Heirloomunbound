// Who may hear an approved memory. Cards start owner-only; the owner shares them with heirs.
// visibility owner/private = only the owner's Twin. family/heir = heirs after release;
// heir_ids empty = every heir, a list = only those heirs.

export const SHARE_COPY = {
  only: "Only me",
  all: "All heirs",
  none: "Nobody yet",
  note: "Heirs hear a shared memory only after you release their access. Your private notes and letters are never shared by this.",
  defaultLabel: "Share new approved cards with all heirs",
  defaultHelp: "Off by default. Applies to cards you approve from now on. Cards already approved keep the way you shared them.",
};

const HEIR_LEVELS = new Set(["family", "heir"]);

export function isShared(card) {
  return HEIR_LEVELS.has(String(card?.visibility || "owner"));
}

export function whoHears(card, heirs = []) {
  if (!isShared(card)) return { kind: "only-me", label: SHARE_COPY.only, names: [] };
  const ids = Array.isArray(card.heir_ids) ? card.heir_ids : [];
  if (!ids.length) {
    const n = heirs.length;
    return { kind: "all", label: n ? `${SHARE_COPY.all} (${n})` : SHARE_COPY.all, names: heirs.map((h) => h.name) };
  }
  const byId = new Map(heirs.map((h) => [h.heir_id, h.name]));
  const names = ids.map((id) => byId.get(id)).filter(Boolean);
  if (!names.length) return { kind: "nobody", label: "Nobody (those heirs were removed)", names: [] };
  return { kind: "some", label: names.join(", "), names };
}

// mode: "none" (stop sharing) | "all" | "some"
export function sharePayload(mode, heirIds = []) {
  if (mode === "none") return { visibility: "owner", heir_ids: [] };
  if (mode === "all") return { visibility: "family", heir_ids: [] };
  const ids = [...new Set((heirIds || []).filter(Boolean))];
  if (!ids.length) throw new Error("Pick at least one heir");
  return { visibility: "family", heir_ids: ids };
}

export function bulkSharePayload(cardIds, mode, heirIds = []) {
  return { card_ids: [...new Set(cardIds || [])], ...sharePayload(mode, heirIds) };
}

export function pickedIds(map) {
  return Object.keys(map || {}).filter((k) => map[k]);
}

export function cardMode(card) {
  if (!isShared(card)) return "none";
  return Array.isArray(card.heir_ids) && card.heir_ids.length ? "some" : "all";
}

export function sharedCount(cards) {
  return (cards || []).filter(isShared).length;
}

// Family names: how an heir names people, e.g. Sam calls June "Grandma". Names only, never facts.
export function cleanNames(rows) {
  const seen = new Set();
  const out = [];
  for (const r of rows || []) {
    const person = String(r?.person || "").trim().replace(/\s+/g, " ").slice(0, 60);
    const called = String(r?.called || "").trim().replace(/\s+/g, " ").slice(0, 40);
    const key = `${person.toLowerCase()}|${called.toLowerCase()}`;
    if (person && called && person.toLowerCase() !== called.toLowerCase() && !seen.has(key)) {
      seen.add(key);
      out.push({ person, called });
    }
  }
  return out.slice(0, 20);
}
