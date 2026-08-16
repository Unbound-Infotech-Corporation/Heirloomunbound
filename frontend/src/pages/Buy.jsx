import axios from "axios";
import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { ArrowUpRight, ScanLine, ShieldCheck, Smartphone } from "lucide-react";
import { usePageMeta } from "../lib/usePageMeta";
import { isTester } from "../lib/tester";

const BACKEND = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND}/api`;

export default function Buy() {
  usePageMeta({
    title: "$79 Lifetime — Heirloom by Unbound Infotech",
    description:
      "One-time $79 payment, no subscription. Lifetime access to Heirloom — your private AI archive, voice-cloned twin, sealed letters, and Windows companion. Paid securely via Stripe.",
  });

  const [link, setLink] = useState(null);
  const [email, setEmail] = useState("");
  const tester = isTester();

  useEffect(() => {
    axios
      .get(`${API}/billing/payment-link`)
      .then(({ data }) => setLink(data))
      .catch(() => setLink(null));
  }, []);

  // Append prefilled_email so Stripe pre-fills the buyer's email at checkout —
  // makes the post-purchase auto-provision step much more reliable.
  const checkoutUrl = useMemo(() => {
    if (!link?.url) return "";
    if (!email.trim()) return link.url;
    const sep = link.url.includes("?") ? "&" : "?";
    return `${link.url}${sep}prefilled_email=${encodeURIComponent(email.trim())}`;
  }, [link, email]);

  const handleGoogle = () => {
    const redirectUrl = window.location.origin + "/today";
    window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
  };

  // Testers never see the paid funnel — send them to free sign-in instead.
  if (tester) {
    return (
      <div
        className="min-h-screen flex items-center justify-center px-6"
        style={{ background: "var(--bg-base)" }}
        data-testid="buy-tester-panel"
      >
        <div className="w-full max-w-md text-center">
          <div className="overline mb-3">tester access</div>
          <h1 className="font-serif text-4xl font-light tracking-tight mb-4">
            No payment needed.
          </h1>
          <p className="text-base mb-8" style={{ color: "var(--text-secondary)" }}>
            You're testing Heirloom — every feature is unlocked for free. Just sign in
            to start.
          </p>
          <button
            type="button"
            onClick={handleGoogle}
            data-testid="buy-tester-continue"
            className="w-full inline-flex items-center justify-center gap-2 px-6 py-4 rounded-sm text-base font-medium tracking-wide transition-opacity hover:opacity-95"
            style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
          >
            Sign in with Google
          </button>
        </div>
      </div>
    );
  }

  return (
    <div
      className="min-h-screen flex items-center justify-center px-6 py-16"
      style={{ background: "var(--bg-base)" }}
      data-testid="buy-root"
    >
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="w-full max-w-5xl"
      >
        <div className="overline mb-3">heirloom by unbound infotech</div>
        <h1 className="font-serif text-4xl lg:text-5xl font-light tracking-tight mb-3">
          One payment. Your twin, forever.
        </h1>
        <p
          className="text-base max-w-2xl mb-12"
          style={{ color: "var(--text-secondary)" }}
        >
          Pay once via Stripe and we'll email you a magic-link to your private
          archive plus your personalized Windows installer (the device token is
          baked in for you). Lifetime access to every feature — heir release,
          sealed letters, voice clone, the works.
        </p>

        <div className="grid lg:grid-cols-[1.2fr_1fr] gap-8 mb-10">
          {/* PRICE + EMAIL + CTA */}
          <div className="surface p-7" data-testid="buy-price-card">
            <div className="overline mb-2">lifetime</div>
            <h3 className="font-serif text-2xl mb-2">Heirloom Lifetime</h3>
            <div
              className="font-serif text-5xl mb-4"
              style={{ color: "var(--accent)" }}
            >
              ${link?.package?.price ?? "79"}
              <span
                className="text-base ml-1"
                style={{ color: "var(--text-muted)" }}
              >
                USD · one-time
              </span>
            </div>
            <p
              className="text-sm mb-6"
              style={{ color: "var(--text-secondary)" }}
            >
              {link?.package?.description ||
                "Lifetime Heirloom Companion + Cloud Archive. One payment, yours forever."}
            </p>

            <label
              className="overline block mb-2"
              htmlFor="buy-email"
              style={{ color: "var(--text-muted)" }}
            >
              your email (we'll prefill at stripe)
            </label>
            <input
              id="buy-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@domain.com"
              data-testid="buy-email"
              className="w-full px-3 py-3 text-sm rounded-sm mb-5"
              style={{
                background: "var(--bg-base)",
                border: "1px solid var(--border-default)",
                color: "var(--text-primary)",
              }}
            />

            <a
              href={checkoutUrl || "#"}
              target="_blank"
              rel="noopener noreferrer"
              aria-disabled={!checkoutUrl}
              data-testid="buy-checkout"
              onClick={(e) => {
                if (!checkoutUrl) e.preventDefault();
              }}
              className="w-full inline-flex items-center justify-center gap-2 px-6 py-4 rounded-sm text-base font-medium tracking-wide transition-opacity hover:opacity-95"
              style={{
                background: "var(--accent)",
                color: "var(--text-inverse)",
                opacity: checkoutUrl ? 1 : 0.5,
                pointerEvents: checkoutUrl ? "auto" : "none",
              }}
            >
              Pay ${link?.package?.price ?? "79"} with Stripe
              <ArrowUpRight className="h-4 w-4" />
            </a>

            <div
              className="flex items-center gap-2 mt-4 text-xs"
              style={{ color: "var(--text-muted) " }}
            >
              <ShieldCheck className="h-3.5 w-3.5" />
              Secure Stripe checkout. After paying, check your email for the
              magic-link to your archive.
            </div>
          </div>

          {/* QR CODE */}
          <div
            className="surface p-7 flex flex-col items-center text-center"
            data-testid="buy-qr-card"
          >
            <div className="overline mb-2 flex items-center gap-2">
              <Smartphone className="h-3.5 w-3.5" /> on desktop?
            </div>
            <h3 className="font-serif text-xl mb-4">Scan to pay from phone</h3>
            <div
              className="rounded-sm p-3 mb-4 inline-block"
              style={{ background: "white" }}
            >
              <img
                src="/stripe-qr.png"
                alt="Scan this QR code to pay $79 via Stripe"
                width={220}
                height={220}
                className="block"
                data-testid="buy-qr-image"
              />
            </div>
            <p
              className="text-xs max-w-xs"
              style={{ color: "var(--text-muted)" }}
            >
              <ScanLine className="h-3.5 w-3.5 inline-block mr-1" />
              Open your phone camera, point at the code, tap the Stripe link.
              Pay there, come back here — your archive will be waiting in your
              inbox.
            </p>
          </div>
        </div>

        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          By purchasing you agree to Unbound Infotech's{" "}
          <a
            href="/terms"
            className="underline"
            style={{ color: "var(--text-muted)" }}
          >
            terms
          </a>{" "}
          and{" "}
          <a
            href="/refunds"
            className="underline"
            style={{ color: "var(--text-muted)" }}
          >
            refund policy
          </a>
          . Your archive is encrypted at rest. You can export everything or
          delete your account any time.
        </p>
      </motion.div>
    </div>
  );
}
