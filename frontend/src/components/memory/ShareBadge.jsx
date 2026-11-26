import { Lock, Users } from "lucide-react";
import { whoHears } from "../../lib/cardSharing";

// A small gold/grey pill: who can hear this memory.
export default function ShareBadge({ card, heirs, testId }) {
  const who = whoHears(card, heirs);
  const shared = who.kind !== "only-me";
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-0.5 text-xs rounded-sm max-w-full"
      style={{
        border: `1px solid ${shared ? "var(--accent)" : "var(--border-default)"}`,
        background: shared ? "var(--accent-muted)" : "transparent",
        color: shared ? "var(--accent)" : "var(--text-muted)",
      }}
      data-testid={testId || `share-badge-${card.card_id}`}
      data-kind={who.kind}
      title={shared ? `Heirs who can hear this: ${who.label}` : "Only you and your Twin can hear this"}
    >
      {shared ? <Users className="h-3 w-3 shrink-0" aria-hidden /> : <Lock className="h-3 w-3 shrink-0" aria-hidden />}
      <span className="truncate">{shared ? `Heard by: ${who.label}` : who.label}</span>
    </span>
  );
}
