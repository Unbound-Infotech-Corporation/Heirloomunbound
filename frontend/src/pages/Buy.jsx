import axios from "axios";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { CheckCircle2, Loader2, ShieldCheck } from "lucide-react";
import { usePageMeta } from "../lib/usePageMeta";

const BACKEND = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND}/api`;

export default function Buy() {
  usePageMeta({
    title: "$79 Lifetime — Heirloom by Unbound Infotech",
    description:
      "One-time $79 payment, no subscription. Lifetime access to Heirloom — your private AI archive, voice-cloned twin, sealed letters, and Windows companion. Paid securely via Stripe.",
  });
  const nav = useNavigate();
  const [packages, setPackages] = useState({});
  const [selected, setSelected] = useState("lifetime");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    axios.get(`${API}/billing/packages`).then(({ data }) => setPackages(data.packages || {}));
  }, []);

  const pkg = packages[selected];

  const checkout = async () => {
    setErr("");
    if (!email.trim()) {
      setErr("Email is required so we can deliver your install.");
      return;
    }
    setBusy(true);
    try {
      const { data } = await axios.post(`${API}/billing/checkout`, {
        package_id: selected,
        origin_url: window.location.origin,
        email: email.trim(),
        name: name.trim() || undefined,
      });
      window.location.href = data.url;
    } catch (e) {
      setErr(e.response?.data?.detail || e.message);
      setBusy(false);
    }
  };

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
        className="w-full max-w-3xl"
      >
        <div className="overline mb-3">heirloom by unbound infotech</div>
        <h1 className="font-serif text-4xl lg:text-5xl font-light tracking-tight mb-3">
          One payment. Your twin, forever.
        </h1>
        <p
          className="text-base max-w-2xl mb-12"
          style={{ color: "var(--text-secondary)" }}
        >
          You'll get a personalized Windows installer (the device token is baked in at checkout), a magic-link to your private archive, and lifetime access to every feature we've built — heir release, sealed letters, voice clone, the works.
        </p>

        <div className="grid md:grid-cols-2 gap-5 mb-10">
          {Object.entries(packages).map(([id, p]) => (
            <button
              key={id}
              onClick={() => setSelected(id)}
              data-testid={`pkg-${id}`}
              className="text-left p-6 rounded-sm transition-colors"
              style={{
                background: selected === id ? "var(--accent-muted)" : "var(--bg-surface)",
                border: selected === id ? "2px solid var(--accent)" : "1px solid var(--border-default)",
              }}
            >
              <div className="overline mb-2">{id}</div>
              <h3 className="font-serif text-2xl mb-2">{p.name}</h3>
              <div className="font-serif text-4xl mb-3" style={{ color: "var(--accent)" }}>
                ${p.price}
                <span className="text-base ml-1" style={{ color: "var(--text-muted)" }}>
                  USD
                </span>
              </div>
              <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                {p.description}
              </p>
            </button>
          ))}
        </div>

        <div className="surface p-7 mb-6">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Email — where to send your install link"
            data-testid="buy-email"
            className="w-full px-3 py-3 text-sm rounded-sm mb-4"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
          />
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Your name (optional — shown to your heirs)"
            data-testid="buy-name"
            className="w-full px-3 py-3 text-sm rounded-sm mb-5"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
          />
          {err && (
            <div className="text-sm mb-4" style={{ color: "var(--error)" }} data-testid="buy-error">
              {err}
            </div>
          )}
          <button
            onClick={checkout}
            disabled={busy || !pkg || !email.trim()}
            data-testid="buy-checkout"
            className="w-full inline-flex items-center justify-center gap-2 px-6 py-4 rounded-sm disabled:opacity-50 text-base"
            style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
          >
            {busy ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" /> Redirecting to Stripe…
              </>
            ) : (
              <>
                Pay ${pkg?.price || "—"} with Stripe →
              </>
            )}
          </button>
          <div className="flex items-center gap-2 mt-4 text-xs" style={{ color: "var(--text-muted)" }}>
            <ShieldCheck className="h-3.5 w-3.5" />
            Test-mode keys — no real charges. Use card 4242 4242 4242 4242, any future expiry, any CVC.
          </div>
        </div>

        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          By purchasing you agree to Unbound Infotech's terms. Your archive is encrypted at rest. You can export everything or delete your account any time.
        </p>
      </motion.div>
    </div>
  );
}
