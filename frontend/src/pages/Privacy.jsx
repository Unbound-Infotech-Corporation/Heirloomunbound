import { Link } from "react-router-dom";
import { usePageMeta } from "../lib/usePageMeta";

export default function Privacy() {
  usePageMeta({
    title: "Privacy Policy — Heirloom",
    description: "How Heirloom by Unbound Infotech collects, stores, and protects your private archive, voice samples, photos, and family data.",
  });
  return (
    <div className="min-h-screen px-6 lg:px-12 py-16" style={{ background: "var(--bg-base)" }}>
      <div className="max-w-3xl mx-auto">
        <Link to="/" className="text-xs font-mono uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
          ← back to Heirloom
        </Link>
        <h1 className="font-serif text-5xl font-light tracking-tight mt-6 mb-3" style={{ color: "var(--text-primary)" }}>
          Privacy Policy
        </h1>
        <p className="text-sm font-mono mb-12" style={{ color: "var(--text-muted)" }}>Last updated: February 27, 2026</p>

        <div className="space-y-7 text-base leading-relaxed" style={{ color: "var(--text-secondary)" }}>
          <Section title="The short version">
            Heirloom holds intimate things — your voice, your stories, your photos, your last words to your family. We treat them
            accordingly. Your archive is yours. We do not sell it, train external models on it, or share it with anyone you have
            not personally named as an heir.
          </Section>

          <Section title="Who is responsible">
            Heirloom is a product of <b style={{ color: "var(--text-primary)" }}>Unbound Infotech</b> (the &quot;Company&quot;, &quot;we&quot;, &quot;our&quot;).
            For privacy questions, write to <a href="mailto:support@heirloom.app" style={{ color: "var(--accent)" }}>support@heirloom.app</a>.
          </Section>

          <Section title="What we collect">
            <ul className="list-disc ml-6 space-y-1.5 mt-2">
              <li><b>Account info</b> — email, name, profile photo from Google when you sign in.</li>
              <li><b>Archive content</b> — text entries, voice recordings, photos, social-media imports, and the answers you give to the AI biographer.</li>
              <li><b>Derived data</b> — long-term identity facts and episodic summaries the system extracts from your archive to help the Twin remember you.</li>
              <li><b>Heirs and letters</b> — the names, emails, and release conditions for the people you designate.</li>
              <li><b>Companion telemetry</b> — your local PC companion sends only a heartbeat and the commands you issue. It never streams the contents of your screen, microphone, or other applications.</li>
              <li><b>Billing</b> — Stripe handles your card; we receive only a checkout session id and your email address.</li>
            </ul>
          </Section>

          <Section title="What we do NOT do">
            <ul className="list-disc ml-6 space-y-1.5 mt-2">
              <li>We do not sell your data.</li>
              <li>We do not use your archive to train external models — not OpenAI, not Anthropic, not Google.</li>
              <li>We do not allow any other Heirloom user to read your archive.</li>
              <li>We do not surveil your microphone or your screen.</li>
            </ul>
          </Section>

          <Section title="Third-party processors">
            To make the product work, certain pieces of your data are sent to specialized services. Each of them is contractually bound to
            process the data only on our behalf:
            <ul className="list-disc ml-6 space-y-1.5 mt-2">
              <li><b>Anthropic (Claude)</b> — the model that powers the Twin chat and the biographer. Your archive entries are sent at chat time.</li>
              <li><b>ElevenLabs</b> — your voice samples and generated TTS audio.</li>
              <li><b>D-ID</b> — text + your portrait photo URL when you render a talking-head video.</li>
              <li><b>Stripe</b> — payment processing.</li>
              <li><b>Google</b> — sign-in via OAuth (we receive only your email, name, and avatar).</li>
              <li><b>MongoDB Atlas</b> — encrypted storage for your archive.</li>
            </ul>
          </Section>

          <Section title="Heirs and release">
            An heir gains read access to your archive <i>only</i> when you have explicitly released it — manually, on a date you set, on a future age,
            or after a period of inactivity that you chose. Until then no human at Unbound Infotech can read your archive in plaintext;
            we use it only to power the AI services you have signed up for.
          </Section>

          <Section title="Retention and deletion">
            You can delete your account and every artifact tied to it from the Settings page (&quot;Delete my account&quot;). The deletion is hard —
            your archive, your voice clone, your heirs, your letters, and your billing history are wiped within 7 days. We keep an
            anonymized audit log of the deletion event for 12 months for fraud and tax reasons.
          </Section>

          <Section title="Your rights (GDPR / CCPA)">
            You have the right to <b>export</b> your archive (write to support), to <b>correct</b> any inaccuracies (do it from the Library),
            and to <b>delete</b> everything (Settings → Danger Zone). EU residents may also lodge a complaint with their local data
            protection authority.
          </Section>

          <Section title="Children">
            Heirloom is not intended for users under 18 without a parent or guardian operating the account.
          </Section>

          <Section title="Changes">
            If we change this policy materially, we will send you an email and update the &quot;Last updated&quot; date above. Continued use
            after a change means you accept the new policy.
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
