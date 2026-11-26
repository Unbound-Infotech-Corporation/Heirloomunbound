/** One layer of studio chrome: page menus fold into the app menubar. */

const SEP = { sep: true };

/**
 * Merge per-page menus into the app menubar.
 * Same label: the page items join the app menu after a separator (duplicates dropped).
 * New label (e.g. "Today"): inserted right after "File".
 */
export function mergeMenus(appMenus = [], pageMenus = []) {
  const merged = appMenus.map((m) => ({ ...m, items: [...(m.items || [])] }));
  const extra = [];
  for (const page of pageMenus) {
    const target = merged.find((m) => m.label === page.label);
    if (!target) {
      extra.push({ ...page, items: [...(page.items || [])] });
      continue;
    }
    const seen = new Set(target.items.filter((i) => !i.sep).map((i) => i.label));
    const fresh = (page.items || []).filter((i) => !i.sep && !seen.has(i.label));
    if (fresh.length) target.items.push(SEP, ...fresh);
  }
  const fileAt = merged.findIndex((m) => m.label === "File");
  merged.splice(fileAt + 1, 0, ...extra);
  return merged;
}

export const NAV_GROUPS = [
  { key: "daily", label: "Daily" },
  { key: "archive", label: "Archive" },
  { key: "twin", label: "Twin" },
  { key: "studio", label: "Studio" },
];

/** Split nav items into labelled groups, keeping order; ungrouped items go to Studio. */
export function groupNav(items = []) {
  return NAV_GROUPS.map((g) => ({
    ...g,
    items: items.filter((i) => (i.group || "studio") === g.key),
  })).filter((g) => g.items.length > 0);
}
