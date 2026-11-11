/** Menu and page title for the owner's style check. */

export function wouldSayLabel(name) {
  const cleaned = String(name || "").replace(/\s+/g, " ").trim();
  if (!cleaned) return "Would you say that?";
  return `Would ${cleaned} say that?`;
}
