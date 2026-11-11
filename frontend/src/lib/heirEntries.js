/** Heir archive rows. Owner-only and private entries never render. */

const HIDDEN = new Set(["private", "owner"]);

export function heirVisibleEntries(entries) {
  if (!Array.isArray(entries)) return [];
  return entries.filter((entry) => {
    const visibility = String(entry?.visibility || "").trim().toLowerCase();
    return !HIDDEN.has(visibility);
  });
}
