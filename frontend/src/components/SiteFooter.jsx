import { Link } from "react-router-dom";

/**
 * Site-wide footer with required legal links and brand line.
 * Renders on the public pages and inside the app shell.
 */
export default function SiteFooter() {
  return (
    <footer
      className="px-6 lg:px-12 py-10 border-t mt-20"
      style={{ borderColor: "var(--border-default)", background: "var(--bg-base)" }}
    >
      <div className="max-w-6xl mx-auto flex flex-col md:flex-row md:items-center md:justify-between gap-6">
        <div>
          <div className="font-serif text-lg" style={{ color: "var(--text-primary)" }}>Heirloom</div>
          <div className="text-xs font-mono mt-1" style={{ color: "var(--text-muted)" }}>
            a product of unbound infotech  ·  © 2026  ·  v1.0
          </div>
        </div>
        <nav className="flex flex-wrap gap-x-6 gap-y-2 text-sm" style={{ color: "var(--text-secondary)" }}>
          <Link to="/privacy" data-testid="footer-privacy" className="hover:text-[var(--text-primary)] transition-colors">
            Privacy
          </Link>
          <Link to="/terms" data-testid="footer-terms" className="hover:text-[var(--text-primary)] transition-colors">
            Terms
          </Link>
          <Link to="/refunds" data-testid="footer-refunds" className="hover:text-[var(--text-primary)] transition-colors">
            Refunds
          </Link>
          <Link to="/support" data-testid="footer-support" className="hover:text-[var(--text-primary)] transition-colors">
            Support
          </Link>
          <a
            href="mailto:support@heirloom.app"
            data-testid="footer-mail"
            className="hover:text-[var(--text-primary)] transition-colors"
          >
            support@heirloom.app
          </a>
        </nav>
      </div>
    </footer>
  );
}
