import { useAuth } from "../lib/auth";

export default function Settings() {
  const { user, logout } = useAuth();

  return (
    <div className="px-10 lg:px-16 py-12 max-w-3xl" data-testid="settings-root">
      <header className="mb-10">
        <div className="overline mb-3">settings</div>
        <h1 className="font-serif text-4xl lg:text-5xl font-light tracking-tight">Your archive.</h1>
      </header>

      <section className="surface p-7 mb-6">
        <div className="overline mb-4">account</div>
        <div className="space-y-3 text-sm">
          <Row label="Name" value={user?.name || "—"} />
          <Row label="Email" value={user?.email || "—"} />
          <Row label="User ID" value={user?.user_id || "—"} mono />
        </div>
      </section>

      <section className="surface p-7 mb-6">
        <div className="overline mb-4">on the roadmap</div>
        <ul className="space-y-3 text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>
          <li>· Local PC companion (Python) — always-on mic + OS control on your 5090.</li>
          <li>· ElevenLabs voice cloning so the twin literally sounds like you.</li>
          <li>· Discord bot for passive personality capture from your text/voice channels.</li>
          <li>· Photo + caption uploads (object storage).</li>
          <li>· Scheduled "release after" workflow for heirs.</li>
        </ul>
      </section>

      <button
        onClick={logout}
        data-testid="settings-logout"
        className="px-5 py-3 text-sm rounded-sm"
        style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
      >
        Sign out
      </button>
    </div>
  );
}

function Row({ label, value, mono }) {
  return (
    <div className="flex justify-between items-baseline gap-4 py-2 border-b last:border-0" style={{ borderColor: "var(--border-default)" }}>
      <div className="overline">{label}</div>
      <div className={mono ? "font-mono text-xs" : ""} style={{ color: "var(--text-primary)" }}>
        {value}
      </div>
    </div>
  );
}
