import { useState } from "react";
import { Link } from "react-router-dom";
import { FIRST_GIFT, FIRST_GIFT_TAGLINE } from "../lib/firstGift";

const DISMISS_KEY = "heirloom_first_gift_dismissed";

export default function FirstGiftInvite({ compact = false }) {
  const [hidden, setHidden] = useState(() => {
    try {
      return window.localStorage.getItem(DISMISS_KEY) === "1";
    } catch {
      return false;
    }
  });

  if (hidden) return null;

  const dismiss = () => {
    try {
      window.localStorage.setItem(DISMISS_KEY, "1");
    } catch {
      /* ignore */
    }
    setHidden(true);
  };

  return (
    <section
      className={`relative ${compact ? "surface p-6" : "surface p-7 lg:p-8"}`}
      data-testid="first-gift-invite"
      style={{ borderColor: "var(--border-default)" }}
    >
      <button
        type="button"
        onClick={dismiss}
        data-testid="first-gift-dismiss"
        className="absolute top-4 right-4 text-xs hover:text-[#F2EFE9] transition-colors"
        style={{ color: "var(--text-muted)" }}
        aria-label="Dismiss first gift"
      >
        Later
      </button>
      <div className="overline mb-3" style={{ color: "var(--accent)" }}>
        the first gift
      </div>
      <p
        className="font-serif font-light tracking-tight mb-2"
        style={{
          color: "var(--text-primary)",
          fontSize: compact ? "1.65rem" : "2rem",
          lineHeight: 1.15,
        }}
        data-testid="first-gift-tagline"
      >
        {FIRST_GIFT_TAGLINE}
      </p>
      <p className="text-sm mb-6 max-w-xl" style={{ color: "var(--text-secondary)" }}>
        Write something only they will read. Seal it. It opens later — a date, an age, or the day
        you release an heir.
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <Link
          to={FIRST_GIFT.momentPath}
          data-testid="first-gift-write"
          className="inline-flex items-center px-6 py-3 text-sm rounded-sm hover:bg-[#E5B98E] transition-colors"
          style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
        >
          Write the first gift
        </Link>
        <Link
          to={FIRST_GIFT.composePath}
          data-testid="first-gift-seal-later"
          className="inline-flex items-center px-6 py-3 text-sm rounded-sm transition-colors hover:border-[#D4A373] hover:text-[#D4A373]"
          style={{ border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
        >
          Seal a letter for later
        </Link>
      </div>
    </section>
  );
}
