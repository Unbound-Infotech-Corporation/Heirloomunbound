import { Link } from "react-router-dom";
import { Mail, MessageSquare, ShieldCheck } from "lucide-react";
import { usePageMeta } from "../lib/usePageMeta";

export default function Support() {
  usePageMeta({
    title: "Support — Heirloom",
    description: "Reach the humans behind Heirloom. We answer every email personally.",
  });
  return (
    <div className="min-h-screen px-6 lg:px-12 py-16" style={{ background: "var(--bg-base)" }}>
      <div className="max-w-2xl mx-auto">
        <Link to="/" className="text-xs font-mono uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
          ← back to Heirloom
        </Link>
        <h1 className="font-serif text-5xl font-light tracking-tight mt-6 mb-6" style={{ color: "var(--text-primary)" }}>
          We answer every email.
        </h1>
        <p className="text-base mb-12 leading-relaxed" style={{ color: "var(--text-secondary)" }}>
          Heirloom is a small product made by a small team. Real humans read each message; we usually respond within a
          working day. Whether you are stuck on setup, have a feature request, or want a refund, we want to hear from you.
        </p>

        <div className="grid md:grid-cols-1 gap-5">
          <a
            href="mailto:support@heirloom.app"
            className="surface p-7 flex items-start gap-4 hover:opacity-90 transition-opacity"
            data-testid="support-email-link"
          >
            <div className="h-12 w-12 flex items-center justify-center rounded-sm flex-shrink-0"
              style={{ background: "var(--accent-muted)", border: "1px solid var(--accent)" }}>
              <Mail className="h-5 w-5" style={{ color: "var(--accent)" }} />
            </div>
            <div>
              <div className="overline mb-1">email</div>
              <div className="font-serif text-xl mb-1" style={{ color: "var(--text-primary)" }}>support@heirloom.app</div>
              <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                For everything. Setup help, refund requests, GDPR/account deletion, feature ideas, press.
              </p>
            </div>
          </a>

          <div className="surface p-7 flex items-start gap-4">
            <div className="h-12 w-12 flex items-center justify-center rounded-sm flex-shrink-0"
              style={{ background: "var(--accent-muted)", border: "1px solid var(--accent)" }}>
              <ShieldCheck className="h-5 w-5" style={{ color: "var(--accent)" }} />
            </div>
            <div>
              <div className="overline mb-1">security disclosure</div>
              <div className="font-serif text-xl mb-1" style={{ color: "var(--text-primary)" }}>security@heirloom.app</div>
              <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                Found a bug that could affect another user&apos;s privacy? Email us privately first; we will respond within 24 hours
                and credit you in the fix log if you wish.
              </p>
            </div>
          </div>

          <div className="surface p-7 flex items-start gap-4">
            <div className="h-12 w-12 flex items-center justify-center rounded-sm flex-shrink-0"
              style={{ background: "var(--accent-muted)", border: "1px solid var(--accent)" }}>
              <MessageSquare className="h-5 w-5" style={{ color: "var(--accent)" }} />
            </div>
            <div>
              <div className="overline mb-1">before you write</div>
              <div className="font-serif text-xl mb-1" style={{ color: "var(--text-primary)" }}>FAQs</div>
              <p className="text-sm mb-2" style={{ color: "var(--text-secondary)" }}>
                The quickest answers are usually:
              </p>
              <ul className="text-sm list-disc ml-5 space-y-1" style={{ color: "var(--text-secondary)" }}>
                <li>Windows companion not appearing in the tray? — see <Link to="/companion" style={{ color: "var(--accent)" }}>Companion setup</Link>.</li>
                <li>Refund request? — see <Link to="/refunds" style={{ color: "var(--accent)" }}>Refund policy</Link>.</li>
                <li>Want to delete your account? — Settings → Danger Zone.</li>
                <li>How is my data protected? — <Link to="/privacy" style={{ color: "var(--accent)" }}>Privacy policy</Link>.</li>
              </ul>
            </div>
          </div>
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
