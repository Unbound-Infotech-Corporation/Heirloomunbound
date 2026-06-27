import { Link } from "react-router-dom";
import { usePageMeta } from "../lib/usePageMeta";

export default function Terms() {
  usePageMeta({
    title: "Terms of Service — Heirloom",
    description: "Terms governing your use of Heirloom by Unbound Infotech — a lifetime AI archive and digital-twin product.",
  });
  return (
    <div className="min-h-screen px-6 lg:px-12 py-16" style={{ background: "var(--bg-base)" }}>
      <div className="max-w-3xl mx-auto">
        <Link to="/" className="text-xs font-mono uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
          ← back to Heirloom
        </Link>
        <h1 className="font-serif text-5xl font-light tracking-tight mt-6 mb-3" style={{ color: "var(--text-primary)" }}>
          Terms of Service
        </h1>
        <p className="text-sm font-mono mb-12" style={{ color: "var(--text-muted)" }}>Last updated: February 27, 2026</p>

        <div className="space-y-7 text-base leading-relaxed" style={{ color: "var(--text-secondary)" }}>
          <Section title="Agreement">
            By signing in to Heirloom or purchasing a license, you agree to these terms. If you do not agree, do not use the product.
            Heirloom is operated by <b style={{ color: "var(--text-primary)" }}>Unbound Infotech</b>.
          </Section>

          <Section title="What you are buying">
            One <b>lifetime license</b> per Google account, currently priced at <b>$79 USD</b>, paid once via Stripe. The license includes:
            <ul className="list-disc ml-6 space-y-1.5 mt-2">
              <li>Unlimited personal archive entries, photos, and interviews.</li>
              <li>Unlimited Twin conversations.</li>
              <li>Voice cloning via ElevenLabs (subject to your own ElevenLabs key or our fair-use cap).</li>
              <li>Talking-head video avatars via D-ID (subject to your own D-ID key or our fair-use cap).</li>
              <li>The local Windows companion software.</li>
              <li>Up to ten (10) heirs and unlimited sealed letters.</li>
              <li>Software updates and new features as they ship.</li>
            </ul>
            We may, at our discretion, introduce fair-use caps on third-party services we pay for on your behalf (currently: Claude
            requests, D-ID renders, and ElevenLabs character usage). When a cap applies, the Settings page will show your remaining
            allowance and let you connect your own API key to lift it.
          </Section>

          <Section title="Your archive belongs to you">
            Everything you put into Heirloom — text, voice, photos, letters — remains your property. You grant us a limited, revocable
            license to store and process it solely to provide the service. The moment you delete your account, that license ends.
          </Section>

          <Section title="Acceptable use">
            Don&apos;t use Heirloom to:
            <ul className="list-disc ml-6 space-y-1.5 mt-2">
              <li>Impersonate a real person without their explicit consent (this includes voice cloning).</li>
              <li>Generate content that defames, harasses, or sexualizes a third party.</li>
              <li>Resell or sublicense the product without written permission.</li>
              <li>Probe, scan, or attempt to compromise the service or other users&apos; data.</li>
            </ul>
            We may suspend your access for clear violations and will refund the unused portion of the license fee on a pro-rated
            basis (see Refunds).
          </Section>

          <Section title="Third-party services">
            Heirloom integrates Anthropic Claude, ElevenLabs, D-ID, Stripe, and Google sign-in. Your use of those services is also
            subject to their own terms. We are not responsible for outages or policy changes at those providers, but we will tell
            you when a meaningful provider change affects your account.
          </Section>

          <Section title="The Twin is software, not a person">
            The AI Twin is a generative model grounded in your archive. It can hallucinate, misremember, or invent. Don&apos;t use its
            output for medical, legal, financial, or other consequential decisions without verifying with a qualified human.
            The Twin&apos;s output is provided &quot;as is&quot;.
          </Section>

          <Section title="Limitation of liability">
            To the maximum extent allowed by law, our total liability under these terms is capped at the amount you have paid us
            in the 12 months prior to the event giving rise to the claim. We are not liable for indirect, incidental, or consequential
            damages, or for any loss of profits or data caused by force majeure.
          </Section>

          <Section title="Termination">
            You may delete your account at any time from Settings. We may terminate accounts that breach these terms. Surviving
            obligations (intellectual property, limitation of liability, dispute resolution) outlast termination.
          </Section>

          <Section title="Governing law">
            These terms are governed by the laws of the jurisdiction where Unbound Infotech is registered. Disputes are first
            attempted to be resolved by good-faith email, then by binding arbitration in that jurisdiction.
          </Section>

          <Section title="Contact">
            Write to <a href="mailto:support@heirloom.app" style={{ color: "var(--accent)" }}>support@heirloom.app</a> for any
            question about these terms.
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
