import { useState } from "react";
import { Link } from "react-router-dom";
import { Lock, Mail, Unlock } from "lucide-react";
import {
  FIRST_GIFT,
  FIRST_GIFT_SAMPLE,
  FIRST_GIFT_TAGLINE,
} from "../lib/firstGift";

export default function FirstGift() {
  const [opened, setOpened] = useState(false);

  return (
    <div className="px-4 sm:px-8 lg:px-16 py-12 max-w-3xl" data-testid="first-gift-root">
      <header className="mb-12">
        <div className="overline mb-3">for later</div>
        <h1 className="font-serif text-4xl lg:text-6xl font-light tracking-tight mb-4">
          {FIRST_GIFT_TAGLINE}
        </h1>
        <p className="text-base max-w-xl leading-relaxed" style={{ color: "var(--text-secondary)" }}>
          This is not a setup step. It is a letter you write once, seal, and leave for the people
          you love. The words stay yours.
        </p>
      </header>

      <section
        className="surface p-8 lg:p-10 mb-10"
        data-testid="first-gift-preview"
        style={{ borderColor: opened ? "rgba(212,163,115,0.5)" : "var(--border-default)" }}
      >
        <div className="flex items-center justify-between gap-4 mb-6">
          <div className="overline" style={{ color: "var(--accent)" }}>
            {FIRST_GIFT_SAMPLE.label}
          </div>
          <span
            className="text-xs font-mono tracking-widest uppercase"
            style={{ color: "var(--text-muted)" }}
            data-testid="first-gift-sample-badge"
          >
            {FIRST_GIFT_SAMPLE.label} · not your letter
          </span>
        </div>

        {!opened ? (
          <div className="text-center py-8" data-testid="first-gift-sealed">
            <Lock className="h-8 w-8 mx-auto mb-4" style={{ color: "var(--accent)" }} />
            <p className="font-serif text-3xl font-light mb-3" style={{ color: "var(--text-primary)" }}>
              A sealed letter
            </p>
            <p className="text-sm mb-8" style={{ color: "var(--text-muted)" }}>
              {FIRST_GIFT_SAMPLE.sealedCaption}
            </p>
            <button
              type="button"
              onClick={() => setOpened(true)}
              data-testid="first-gift-open-sample"
              className="inline-flex items-center gap-2 px-6 py-3 text-sm rounded-sm hover:bg-[#E5B98E] transition-colors"
              style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
            >
              <Unlock className="h-4 w-4" /> Open the sample
            </button>
          </div>
        ) : (
          <div data-testid="first-gift-opened">
            <div className="overline mb-3" style={{ color: "var(--text-muted)" }}>
              {FIRST_GIFT_SAMPLE.openCaption}
            </div>
            <p className="text-xs mb-2" style={{ color: "var(--text-muted)" }}>
              to {FIRST_GIFT_SAMPLE.to}
            </p>
            <h2 className="font-serif text-3xl font-light mb-5">{FIRST_GIFT_SAMPLE.title}</h2>
            <p
              className="font-serif text-lg leading-relaxed whitespace-pre-wrap"
              style={{ color: "var(--text-secondary)" }}
            >
              {FIRST_GIFT_SAMPLE.body}
            </p>
          </div>
        )}
      </section>

      <div className="flex flex-wrap items-center gap-3 mb-8">
        <Link
          to={FIRST_GIFT.composePath}
          data-testid="first-gift-write-mine"
          className="inline-flex items-center gap-2 px-6 py-3 text-sm rounded-sm hover:bg-[#E5B98E] transition-colors"
          style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
        >
          <Mail className="h-4 w-4" /> Write mine
        </Link>
        <Link
          to="/twin"
          data-testid="first-gift-back-twin"
          className="inline-flex items-center px-6 py-3 text-sm rounded-sm transition-colors hover:border-[#D4A373] hover:text-[#D4A373]"
          style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
        >
          Back to Twin
        </Link>
      </div>

      <p className="text-xs max-w-xl" style={{ color: "var(--text-muted)" }}>
        Compose uses the sealed letters you already have — to {FIRST_GIFT.recipientName}, delivered
        when an heir is released. Edit the name. The page stays blank until you write.
      </p>
    </div>
  );
}
