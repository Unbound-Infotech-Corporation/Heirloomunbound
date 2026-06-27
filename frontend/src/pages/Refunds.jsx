import { Link } from "react-router-dom";
import { usePageMeta } from "../lib/usePageMeta";

export default function Refunds() {
  usePageMeta({
    title: "Refund Policy — Heirloom",
    description: "30-day no-questions-asked refund policy for Heirloom by Unbound Infotech.",
  });
  return (
    <div className="min-h-screen px-6 lg:px-12 py-16" style={{ background: "var(--bg-base)" }}>
      <div className="max-w-3xl mx-auto">
        <Link to="/" className="text-xs font-mono uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
          ← back to Heirloom
        </Link>
        <h1 className="font-serif text-5xl font-light tracking-tight mt-6 mb-3" style={{ color: "var(--text-primary)" }}>
          Refund Policy
        </h1>
        <p className="text-sm font-mono mb-12" style={{ color: "var(--text-muted)" }}>Last updated: February 27, 2026</p>

        <div className="space-y-7 text-base leading-relaxed" style={{ color: "var(--text-secondary)" }}>
          <Section title="30 days, no questions">
            If Heirloom is not what you hoped, write to{" "}
            <a href="mailto:support@heirloom.app" style={{ color: "var(--accent)" }}>support@heirloom.app</a> within
            <b style={{ color: "var(--text-primary)" }}> 30 days </b>
            of your purchase and we will refund the full $79. No questions, no friction.
            We will also delete your archive at the same time unless you ask us not to.
          </Section>

          <Section title="After 30 days">
            Heirloom is a lifetime license, so we do not pro-rate refunds after 30 days. If you stop using the product, your
            archive remains intact and can be picked up again at any time. You can also delete it permanently from Settings
            at any point.
          </Section>

          <Section title="Service outages">
            If a third-party provider we depend on (Claude, ElevenLabs, D-ID) suffers a multi-day outage that prevents you
            from using Heirloom in any meaningful way, write to us. We will issue a goodwill credit or a partial refund
            depending on the impact.
          </Section>

          <Section title="Chargebacks">
            Please email us before filing a chargeback. We have never refused a reasonable refund. A chargeback locks the
            account and is an irreversible process that often costs more than the original payment.
          </Section>

          <Section title="How to request">
            One sentence is enough: <i>&quot;Please refund my Heirloom purchase&quot;</i> sent from the email tied to your account.
            We aim to process within 2 business days; Stripe usually returns the funds in another 3–5.
          </Section>
        </div>

        <div className="mt-16 pt-8 border-t" style={{ borderColor: "var(--border-default)" }}>
          <Link to="/" className="text-sm" style={{ color: "var(--accent)" }}>
            ← Heirloom home
          </Link>
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <section>
      <h2 className="font-serif text-2xl font-light mb-3" style={{ color: "var(--text-primary)" }}>{title}</h2>
      <div>{children}</div>
    </section>
  );
}
