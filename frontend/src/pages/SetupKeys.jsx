import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Check, ExternalLink, Eye, EyeOff, KeyRound, Loader2, ShieldCheck, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { usePageMeta } from "@/lib/usePageMeta";

// Each service entry is a self-contained recipe: how to get the key, what
// the wizard sends it to, and where to test it. Keeping the data here (vs.
// in the backend) keeps the wizard 100% static-renderable and easy to edit.
const SERVICES = [
  {
    id: "fal",
    name: "fal.ai",
    powers: "Subtle Beautify in Avatar Studio (identity-preserving face restorer).",
    dashboard: "https://fal.ai/dashboard/keys",
    keyEndpoint: "/avatar-studio/api-key",
    placeholder: "key_id:key_secret",
    docs: "https://docs.fal.ai/authentication/key-based",
    steps: [
      "Open fal.ai/dashboard/keys (sign in with Google or GitHub).",
      "Click '+ Add key' and give it a name like 'Heirloom'.",
      "Copy the WHOLE string — it looks like 'abc123…:xyz789…' (two halves joined by a colon).",
      "Paste below and click Verify. The first $1 of credit is free; beautify costs ~$0.001 per image.",
    ],
  },
  {
    id: "elevenlabs",
    name: "ElevenLabs",
    powers: "Cloned-voice TTS so your twin speaks in your actual voice.",
    dashboard: "https://elevenlabs.io/app/settings/api-keys",
    keyEndpoint: "/voice-clone/api-key",
    placeholder: "sk_...",
    docs: "https://elevenlabs.io/docs/api-reference/authentication",
    steps: [
      "Sign in at elevenlabs.io, then go to Profile → API Keys.",
      "Click 'Create API Key', name it 'Heirloom', accept all permissions.",
      "Copy the key (starts with sk_). It's only shown once — save it now.",
      "Paste below. Free tier gives 10,000 chars/month — enough for ~150 short twin replies.",
    ],
  },
  {
    id: "did",
    name: "D-ID",
    powers: "Talking-head video — your face speaking your twin's replies.",
    dashboard: "https://studio.d-id.com/account-settings",
    keyEndpoint: "/avatar/api-key",
    placeholder: "email:secret (Basic auth pair)",
    docs: "https://docs.d-id.com/reference/get-started",
    steps: [
      "Create an account at studio.d-id.com (free trial = 20 credits).",
      "Go to Account Settings → API Keys.",
      "Click 'Create new API key' and copy the pair shown as 'email:secret'.",
      "Paste the WHOLE thing including the colon. Each talking-head clip ≈ 1 credit.",
    ],
  },
];

// Read-only badges (status only, no input)
const READ_ONLY = [
  {
    id: "resend",
    name: "Resend",
    powers: "Magic-link login emails + heir-portal invites.",
    note: "App-wide service. Admin manages this — your account is good to go if the badge below is green.",
  },
  {
    id: "stripe",
    name: "Stripe",
    powers: "One-time purchase that unlocks Heirloom + the desktop companion.",
    note: "Powered by a Stripe Payment Link. To purchase or re-subscribe, head to the Billing page.",
  },
];

// OAuth services — authorize URL is fetched from the API (not a static href)
const OAUTH = [
  {
    id: "spotify",
    name: "Spotify",
    powers: "One click — imports your top tracks so your twin knows your taste.",
  },
  {
    id: "github",
    name: "GitHub",
    powers: "One click — imports public repos so your twin knows what you've built.",
  },
];

const INCLUDED = [
  {
    id: "llm",
    name: "Heirloom AI",
    powers: "The brain behind your twin, interviewer, and archive search.",
    note: "Included with Heirloom — no key to paste. If this badge is green, you're ready to talk.",
  },
  ...READ_ONLY,
];

export default function SetupKeys() {
  const nav = useNavigate();
  usePageMeta({
    title: "Keys & Integrations · Heirloom",
    description: "Connect your own API keys so your twin can speak, see, and grow.",
  });

  const [status, setStatus] = useState(null);
  const [drafts, setDrafts] = useState({}); // {fal: "...", elevenlabs: "..."}
  const [reveal, setReveal] = useState({}); // {fal: true}
  const [busy, setBusy] = useState({}); // {fal: "verifying" | "saving"}
  const [verified, setVerified] = useState({}); // {fal: {ok, detail}}

  const load = async () => {
    try {
      const r = await api.get("/user-keys/status");
      setStatus(r.data);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't load key status.");
    }
  };
  useEffect(() => { load(); }, []);

  const setDraft = (id, v) => {
    setDrafts((d) => ({ ...d, [id]: v }));
    setVerified((v0) => ({ ...v0, [id]: null })); // editing invalidates prior verify
  };

  const verify = async (svc) => {
    const key = (drafts[svc.id] || "").trim();
    if (!key) {
      toast.error("Paste a key first.");
      return;
    }
    setBusy((b) => ({ ...b, [svc.id]: "verifying" }));
    try {
      const r = await api.post("/user-keys/verify", { service: svc.id, api_key: key });
      setVerified((v) => ({ ...v, [svc.id]: r.data }));
      if (r.data.ok) toast.success(`${svc.name}: ${r.data.detail}`);
      else toast.error(`${svc.name}: ${r.data.detail}`);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Verify failed.");
    } finally {
      setBusy((b) => ({ ...b, [svc.id]: null }));
    }
  };

  const save = async (svc) => {
    const key = (drafts[svc.id] || "").trim();
    if (!key) {
      toast.error("Paste a key first.");
      return;
    }
    setBusy((b) => ({ ...b, [svc.id]: "saving" }));
    try {
      await api.put(svc.keyEndpoint, { api_key: key });
      toast.success(`${svc.name} key saved.`);
      setDrafts((d) => ({ ...d, [svc.id]: "" }));
      setVerified((v) => ({ ...v, [svc.id]: null }));
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Save failed.");
    } finally {
      setBusy((b) => ({ ...b, [svc.id]: null }));
    }
  };

  const clear = async (svc) => {
    setBusy((b) => ({ ...b, [svc.id]: "saving" }));
    try {
      await api.delete(svc.keyEndpoint);
      toast.success(`${svc.name} key removed — falling back to default.`);
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't remove key.");
    } finally {
      setBusy((b) => ({ ...b, [svc.id]: null }));
    }
  };

  const connectOAuth = async (provider) => {
    try {
      const { data } = await api.get(`/oauth/${provider}/connect`);
      if (!data?.authorize_url) throw new Error("No authorize URL returned");
      window.location.href = data.authorize_url;
    } catch (e) {
      toast.error(e.response?.data?.detail || `Couldn't start ${provider} connection.`);
    }
  };

  const disconnectOAuth = async (provider) => {
    if (!window.confirm(`Disconnect ${provider}? Imported memories stay in your archive.`)) return;
    try {
      await api.delete(`/oauth/${provider}`);
      toast.success(`${provider} disconnected`);
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't disconnect.");
    }
  };

  if (!status) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ color: "var(--text-muted)" }}>
        Loading…
      </div>
    );
  }

  return (
    <div className="min-h-screen px-6 sm:px-10 py-10" style={{ background: "var(--bg-base)" }} data-testid="setup-keys-page">
      <div className="max-w-3xl mx-auto">
        <div className="overline mb-3 flex items-center gap-2">
          <KeyRound className="h-3.5 w-3.5" /> bring your own keys
        </div>
        <h1 className="font-serif text-4xl mb-3">Connect extras</h1>
        <p className="text-base mb-4 max-w-2xl" style={{ color: "var(--text-secondary)" }}>
          Heirloom already includes the AI that powers your twin. Optional keys below unlock
          <strong> your voice</strong>, <strong> talking video</strong>, and <strong> photo polish</strong>
          under your own accounts — with higher limits. Most people start with voice.
        </p>
        <div className="flex flex-wrap gap-3 mb-10 text-sm">
          <button
            type="button"
            onClick={() => nav("/setup/easy")}
            className="px-4 py-2 rounded-sm"
            style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
          >
            ← Simple Setup
          </button>
          <button
            type="button"
            onClick={() => nav("/abilities")}
            className="px-4 py-2 rounded-sm"
            style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
            data-testid="setup-keys-abilities-link"
          >
            What your twin can do →
          </button>
        </div>

        {/* Included AI first — reassurance */}
        <div className="overline mb-3">ALREADY INCLUDED</div>
        <div className="space-y-3 mb-10">
          {INCLUDED.map((svc) => {
            const st = status[svc.id] || { source: "none" };
            return (
              <section
                key={svc.id}
                className="surface p-5"
                data-testid={`included-card-${svc.id}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="overline mb-1">{svc.name.toUpperCase()}</div>
                    <p className="text-sm mb-1" style={{ color: "var(--text-primary)" }}>{svc.powers}</p>
                    <p className="text-xs" style={{ color: "var(--text-muted)" }}>{svc.note}</p>
                  </div>
                  <StatusBadge source={st.source} />
                </div>
              </section>
            );
          })}
        </div>

        <div className="overline mb-3">OPTIONAL — YOUR OWN KEYS</div>
        <p className="text-sm mb-4" style={{ color: "var(--text-muted)" }}>
          Paste a key, tap Verify, then Save. We never show the full key again after saving.
        </p>
        <div className="space-y-6 mb-12">
          {SERVICES.map((svc) => {
            const st = status[svc.id] || { source: "none" };
            const draft = drafts[svc.id] || "";
            const v = verified[svc.id];
            const busyState = busy[svc.id];
            return (
              <section
                key={svc.id}
                className="surface p-6"
                data-testid={`key-card-${svc.id}`}
                style={{ border: `1px solid ${st.source === "you" ? "var(--ok)" : "var(--border-default)"}` }}
              >
                <div className="flex items-start justify-between gap-4 mb-3">
                  <div>
                    <div className="overline mb-1">{svc.name.toUpperCase()}</div>
                    <p className="text-sm" style={{ color: "var(--text-primary)" }}>{svc.powers}</p>
                  </div>
                  <StatusBadge source={st.source} />
                </div>

                <ol className="text-xs mb-4 space-y-1.5 list-decimal pl-5" style={{ color: "var(--text-secondary)" }}>
                  {svc.steps.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ol>

                <div className="flex flex-wrap gap-3 mb-4 text-xs">
                  <a
                    href={svc.dashboard}
                    target="_blank"
                    rel="noreferrer"
                    data-testid={`key-dashboard-${svc.id}`}
                    className="inline-flex items-center gap-1.5 underline"
                    style={{ color: "var(--accent)" }}
                  >
                    Open {svc.name} dashboard <ExternalLink className="h-3 w-3" />
                  </a>
                  <a
                    href={svc.docs}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1.5 underline"
                    style={{ color: "var(--text-muted)" }}
                  >
                    API docs <ExternalLink className="h-3 w-3" />
                  </a>
                </div>

                <div className="flex flex-wrap gap-2 items-stretch">
                  <div className="relative flex-1 min-w-[240px]">
                    <input
                      type={reveal[svc.id] ? "text" : "password"}
                      value={draft}
                      onChange={(e) => setDraft(svc.id, e.target.value)}
                      placeholder={svc.placeholder}
                      data-testid={`key-input-${svc.id}`}
                      className="w-full px-3 py-2 pr-10 text-sm font-mono rounded-sm"
                      style={{
                        background: "var(--bg-base)",
                        border: "1px solid var(--border-default)",
                        color: "var(--text-primary)",
                      }}
                    />
                    <button
                      type="button"
                      onClick={() => setReveal((r) => ({ ...r, [svc.id]: !r[svc.id] }))}
                      data-testid={`key-reveal-${svc.id}`}
                      className="absolute right-2 top-1/2 -translate-y-1/2"
                      style={{ color: "var(--text-muted)" }}
                      title={reveal[svc.id] ? "Hide" : "Reveal"}
                    >
                      {reveal[svc.id] ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                  <button
                    type="button"
                    onClick={() => verify(svc)}
                    disabled={!draft || busyState === "verifying"}
                    data-testid={`key-verify-${svc.id}`}
                    className="inline-flex items-center gap-1.5 text-xs px-4 py-2 rounded-sm"
                    style={{
                      border: "1px solid var(--accent)",
                      color: "var(--accent)",
                      opacity: !draft ? 0.5 : 1,
                    }}
                  >
                    {busyState === "verifying" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ShieldCheck className="h-3.5 w-3.5" />}
                    Verify
                  </button>
                  <button
                    type="button"
                    onClick={() => save(svc)}
                    disabled={!draft || busyState === "saving"}
                    data-testid={`key-save-${svc.id}`}
                    className="inline-flex items-center gap-1.5 text-xs px-4 py-2 rounded-sm"
                    style={{
                      background: "var(--accent)",
                      color: "var(--text-inverse)",
                      opacity: !draft ? 0.5 : 1,
                    }}
                  >
                    {busyState === "saving" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                    Save key
                  </button>
                  {st.source === "you" && (
                    <button
                      type="button"
                      onClick={() => clear(svc)}
                      data-testid={`key-clear-${svc.id}`}
                      className="inline-flex items-center gap-1.5 text-xs px-3 py-2 rounded-sm"
                      style={{ border: "1px solid var(--border-default)", color: "var(--text-muted)" }}
                    >
                      <X className="h-3.5 w-3.5" /> Remove
                    </button>
                  )}
                </div>

                {v && (
                  <div
                    className="mt-3 text-xs px-3 py-2 rounded-sm"
                    data-testid={`key-verify-result-${svc.id}`}
                    style={{
                      background: v.ok ? "rgba(80, 160, 120, 0.12)" : "rgba(200, 90, 90, 0.12)",
                      color: v.ok ? "var(--ok, #4d9b76)" : "#c95a5a",
                      border: `1px solid ${v.ok ? "var(--ok, #4d9b76)" : "#c95a5a"}`,
                    }}
                  >
                    {v.ok ? "✓ " : "✗ "}{v.detail}
                  </div>
                )}
              </section>
            );
          })}
        </div>

        {/* OAuth section */}
        <div className="overline mb-3">ONE-CLICK CONNECTIONS</div>
        <p className="text-sm mb-4" style={{ color: "var(--text-muted)" }}>
          No passwords to copy — just sign in and approve.
        </p>
        <div className="grid sm:grid-cols-2 gap-4 mb-12">
          {OAUTH.map((svc) => {
            const st = status[svc.id] || { source: "none" };
            const connected = st.source === "you";
            return (
              <section
                key={svc.id}
                className="surface p-5"
                data-testid={`oauth-card-${svc.id}`}
                style={{ border: `1px solid ${connected ? "var(--ok)" : "var(--border-default)"}` }}
              >
                <div className="flex items-start justify-between mb-2">
                  <div className="overline">{svc.name.toUpperCase()}</div>
                  <StatusBadge source={st.source} oauth />
                </div>
                <p className="text-xs mb-4" style={{ color: "var(--text-secondary)" }}>{svc.powers}</p>
                {connected ? (
                  <button
                    type="button"
                    onClick={() => disconnectOAuth(svc.id)}
                    data-testid={`oauth-disconnect-${svc.id}`}
                    className="inline-flex items-center gap-1.5 text-xs px-4 py-2 rounded-sm"
                    style={{ border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
                  >
                    Disconnect
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => connectOAuth(svc.id)}
                    data-testid={`oauth-connect-${svc.id}`}
                    className="inline-flex items-center gap-1.5 text-xs px-4 py-2 rounded-sm"
                    style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
                  >
                    Connect {svc.name}
                  </button>
                )}
              </section>
            );
          })}
        </div>

        <button
          type="button"
          onClick={() => nav("/settings")}
          className="text-sm underline"
          style={{ color: "var(--text-muted)" }}
          data-testid="setup-keys-back"
        >
          ← Back to Settings
        </button>
      </div>
    </div>
  );
}

function StatusBadge({ source, oauth }) {
  let label;
  let color;
  let bg;
  if (source === "you") {
    label = oauth ? "Connected" : "Using your key";
    color = "var(--ok, #4d9b76)";
    bg = "rgba(80, 160, 120, 0.12)";
  } else if (source === "admin") {
    label = "Using shared default";
    color = "var(--text-muted)";
    bg = "var(--bg-base)";
  } else {
    label = oauth ? "Not connected" : "Missing";
    color = "#c95a5a";
    bg = "rgba(200, 90, 90, 0.12)";
  }
  return (
    <span
      className="text-xs px-2 py-1 rounded-sm whitespace-nowrap"
      style={{ background: bg, color, border: `1px solid ${color}` }}
      data-testid={`status-badge-${source}`}
    >
      {label}
    </span>
  );
}
