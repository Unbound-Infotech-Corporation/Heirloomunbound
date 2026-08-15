import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowRight,
  Check,
  ChevronRight,
  ExternalLink,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  Mail,
  Music2,
  Phone,
  Server,
  Shield,
  ShieldCheck,
  Sparkles,
  X,
  Zap,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { usePageMeta } from "@/lib/usePageMeta";

// One-line rule: every user-facing choice is a TILE with a clear ACTION.
// No inline forms on the page itself — BYOK keys go through a modal wizard
// so a 40-60 year old skimming the page never sees a wall of text fields.

// ---------- Data ----------
const OAUTH = [
  {
    id: "spotify",
    name: "Spotify",
    tagline: "Import your top tracks + recently played so the twin knows your music soul.",
    connectPath: "/api/oauth/spotify/connect",
    accent: "#1DB954",
    icon: Music2,
  },
  {
    id: "github",
    name: "GitHub",
    tagline: "Your public repos + READMEs feed into the archive — the twin learns what you've built.",
    connectPath: "/api/oauth/github/connect",
    accent: "#8b949e",
    icon: Server,
  },
  {
    id: "google",
    name: "Gmail",
    tagline: "One tap. Google asks you — we never see your password. Mail, calendar, and send-only-after-yes.",
    connectPath: "/api/oauth/google/connect",
    accent: "#EA4335",
    icon: Mail,
  },
  {
    id: "microsoft",
    name: "Outlook",
    tagline: "Same idea for Outlook / Hotmail / Microsoft 365 — mail and calendar. Sign in on Microsoft's page.",
    connectPath: "/api/oauth/microsoft/connect",
    accent: "#0078D4",
    icon: Mail,
  },
];

const BYOK = [
  {
    id: "elevenlabs",
    name: "ElevenLabs",
    tagline: "The twin speaks in your actual voice — clone from 6 minutes of audio.",
    accent: "#f5c264",
    keyEndpoint: "/voice-clone/api-key",
    placeholder: "sk_...",
    dashboard: "https://elevenlabs.io/app/settings/api-keys",
    signup: "https://elevenlabs.io/sign-up",
    steps: [
      "Click Sign up at elevenlabs.io (it's free — 10,000 characters/month).",
      "After signing in, click Profile → API Keys → Create API Key.",
      "Name it Heirloom and click Create. Copy the whole string (starts with sk_).",
      "Paste it below and click Verify. You're done.",
    ],
    freeTier: "Free tier: 10,000 characters/month (~150 short replies).",
  },
  {
    id: "did",
    name: "D-ID",
    tagline: "Paid cloud talking-head. Skip this if you use the free Pinokio/ComfyUI path in Avatar Studio.",
    accent: "#c084fc",
    keyEndpoint: "/avatar/api-key",
    placeholder: "email:secret",
    dashboard: "https://studio.d-id.com/account-settings",
    signup: "https://studio.d-id.com/subscribe",
    steps: [
      "Sign up at studio.d-id.com (free trial = 20 credits — enough to try it).",
      "Go to Account Settings → API Keys.",
      "Click Create new API key and copy the pair shown as email:secret.",
      "Paste the WHOLE thing including the colon.",
    ],
    freeTier: "Free trial: 20 credits (~20 short talking-head videos).",
  },
  {
    id: "fal",
    name: "fal.ai",
    tagline: "Subtle photo touch-ups in Avatar Studio (identity-preserving face restore).",
    accent: "#60a5fa",
    keyEndpoint: "/avatar-studio/api-key",
    placeholder: "key_id:key_secret",
    dashboard: "https://fal.ai/dashboard/keys",
    signup: "https://fal.ai",
    steps: [
      "Open fal.ai and click Sign in (Google or GitHub work).",
      "Head to Dashboard → API Keys → Add key.",
      "Name it Heirloom and copy the whole string (looks like abc:xyz).",
      "Paste below.",
    ],
    freeTier: "First $1 of credit is free — each beautify costs about 1/10th of a cent.",
  },
];

const READ_ONLY = [
  {
    id: "resend",
    name: "Email delivery (Resend)",
    tagline: "Magic-link login + heir-portal invites go through Resend.",
    note: "Provided for you — no setup needed on your side.",
  },
  {
    id: "stripe",
    name: "Payments (Stripe)",
    tagline: "The one-time purchase that unlocks Heirloom + the desktop companion.",
    note: "Provided for you — head to Billing when you're ready to buy.",
  },
];

// ---------- Component ----------
export default function SetupKeys() {
  const nav = useNavigate();
  usePageMeta({
    title: "Connect · Heirloom",
    description: "Connect the services that help your twin see, speak, and grow.",
  });

  const [status, setStatus] = useState(null);
  const [openModal, setOpenModal] = useState(null); // svc object or null

  const load = () =>
    api.get("/user-keys/status").then((r) => setStatus(r.data)).catch(() => setStatus({}));

  useEffect(() => { load(); }, []);

  const connectedCount = status
    ? [...OAUTH, ...BYOK].filter((s) => (status[s.id]?.source === "you")).length
    : 0;
  const totalConnectable = OAUTH.length + BYOK.length;

  if (!status) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ color: "var(--text-muted)" }}>
        <Loader2 className="h-5 w-5 animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-screen px-6 sm:px-10 py-14" style={{ background: "var(--bg-base)" }} data-testid="setup-keys-page">
      <div className="max-w-5xl mx-auto">
        {/* Header */}
        <div className="overline mb-3 flex items-center gap-2">
          <KeyRound className="h-3.5 w-3.5" /> connect
        </div>
        <div className="flex items-end justify-between gap-6 flex-wrap mb-3">
          <h1 className="font-serif text-4xl sm:text-5xl font-light">Wire up your twin.</h1>
          <div
            className="text-xs px-3 py-1.5 rounded-full"
            style={{
              background: "var(--accent-muted, rgba(232,169,92,0.14))",
              color: "var(--accent)",
              border: "1px solid var(--accent)",
            }}
            data-testid="setup-progress"
          >
            {connectedCount} of {totalConnectable} connected
          </div>
        </div>
        <p className="text-base mb-8 max-w-2xl" style={{ color: "var(--text-secondary)" }}>
          Every connection makes your twin more like you — its voice, its knowledge, its face.
          Skip any of these for now and come back later. Nothing here is required to start.
        </p>
        <Link
          to="/models"
          data-testid="setup-models-link"
          className="surface p-5 mb-14 flex items-center justify-between gap-4 hover:opacity-90 transition-opacity"
          style={{ border: "1px solid var(--accent)" }}
        >
          <div>
            <div className="overline mb-1" style={{ color: "var(--accent)" }}>click the brain you want</div>
            <p className="text-sm" style={{ color: "var(--text-primary)" }}>
              Connect OpenAI, Claude, Gemini, Groq… or download a model onto your home PC. Then pick which one Twin, Interviewer, and Focus use.
            </p>
            <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
              One key paste or one tap to download. No extra setup screens.
            </p>
          </div>
          <span className="text-2xl" style={{ color: "var(--accent)" }}>→</span>
        </Link>

        {/* SECTION: OAuth 1-clicks */}
        <SectionHeader
          overline="one click, no keys"
          title="Connect with a tap"
          hint="Sign in and you're done. Your data flows in automatically."
        />
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-16">
          {OAUTH.map((s) => (
            <OAuthTile key={s.id} svc={s} status={status[s.id]} />
          ))}
          <ComingSoonTile
            name="Discord"
            tagline="DMs + servers you're active in feed the archive."
            accent="#5865F2"
          />
        </div>

        {/* SECTION: BYOK cards */}
        <SectionHeader
          overline="add a key · takes 2 minutes each"
          title="Unlock voice, video, and photo powers"
          hint="These use your own API key so all usage stays on your account. Each has a free tier."
        />
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-16">
          {BYOK.map((s) => (
            <BYOKTile key={s.id} svc={s} status={status[s.id]} onOpen={() => setOpenModal(s)} />
          ))}
        </div>

        {/* SECTION: Phone */}
        <SectionHeader
          overline="new · phone calling"
          title="Give your twin a phone number"
          hint="Twilio-powered. Someone calls the number, the twin answers in your voice, transcribes both sides into your archive. Also dials outbound."
        />
        <div
          className="rounded-sm p-8 mb-16 flex items-start gap-6 flex-wrap"
          style={{ border: "1px solid var(--accent)", background: "rgba(232,169,92,0.05)" }}
          data-testid="phone-tile"
        >
          <div className="flex-1 min-w-[280px]">
            <div className="flex items-center gap-3 mb-3">
              <Phone className="h-5 w-5" style={{ color: "var(--accent)" }} />
              <div className="text-lg font-medium" style={{ color: "var(--text-primary)" }}>
                Phone (Twilio Programmable Voice)
              </div>
            </div>
            <p className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>
              ~$1/month for a Twilio number + ~$0.014/min for voice. We auto-configure the
              webhook — you just paste your Twilio Account SID, Auth Token, and number.
            </p>
          </div>
          <a
            href="/phone"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-sm text-sm font-medium"
            style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
            data-testid="phone-goto"
          >
            Set up phone <ArrowRight className="h-4 w-4" />
          </a>
        </div>

        {/* SECTION: Local AI */}
        <SectionHeader
          overline="advanced · unlimited & private"
          title="Run AI on your own computer"
          hint="Install Pinokio, Ollama, or LM Studio and route your twin through models on your PC. Nothing leaves the machine."
        />
        <div
          className="rounded-sm p-8 mb-16 flex items-start gap-6 flex-wrap"
          style={{ border: "1px solid var(--border-default)", background: "var(--bg-surface)" }}
          data-testid="local-ai-tile"
        >
          <div className="flex-1 min-w-[280px]">
            <div className="flex items-center gap-3 mb-3">
              <Zap className="h-5 w-5" style={{ color: "var(--accent)" }} />
              <div className="text-lg font-medium" style={{ color: "var(--text-primary)" }}>
                Local AI (Chat · Voice · Transcription · Embeddings · Images)
              </div>
            </div>
            <p className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>
              Configure this from the Heirloom desktop companion — it auto-detects local models
              running on your PC. If you don&apos;t have a local model yet, we recommend Pinokio (a
              friendly launcher) or Ollama (single install + one command per model).
            </p>
            <div className="flex flex-wrap gap-2">
              <a
                href="https://pinokio.co"
                target="_blank"
                rel="noreferrer"
                className="text-xs px-3 py-1.5 rounded-full"
                style={{ border: "1px solid var(--border-default)", color: "var(--text-muted)" }}
              >
                Pinokio <ExternalLink className="inline h-3 w-3 ml-1" />
              </a>
              <a
                href="https://ollama.com"
                target="_blank"
                rel="noreferrer"
                className="text-xs px-3 py-1.5 rounded-full"
                style={{ border: "1px solid var(--border-default)", color: "var(--text-muted)" }}
              >
                Ollama <ExternalLink className="inline h-3 w-3 ml-1" />
              </a>
              <a
                href="https://lmstudio.ai"
                target="_blank"
                rel="noreferrer"
                className="text-xs px-3 py-1.5 rounded-full"
                style={{ border: "1px solid var(--border-default)", color: "var(--text-muted)" }}
              >
                LM Studio <ExternalLink className="inline h-3 w-3 ml-1" />
              </a>
            </div>
          </div>
          <button
            type="button"
            onClick={() => nav("/companion")}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-sm text-sm font-medium"
            style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
            data-testid="local-ai-goto"
          >
            Set up in Heirloom Desktop <ArrowRight className="h-4 w-4" />
          </button>
        </div>

        {/* SECTION: Read-only */}
        <SectionHeader
          overline="provided for you"
          title="Already working under the hood"
          hint="These services are wired at the platform level so you don't have to think about them."
        />
        <div className="grid sm:grid-cols-2 gap-4 mb-16">
          {READ_ONLY.map((s) => (
            <div
              key={s.id}
              className="rounded-sm p-5"
              style={{ border: "1px solid var(--border-default)", background: "var(--bg-surface)" }}
              data-testid={`readonly-tile-${s.id}`}
            >
              <div className="flex items-center gap-2 mb-2">
                <Shield className="h-4 w-4" style={{ color: "var(--text-muted)" }} />
                <div className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                  {s.name}
                </div>
              </div>
              <p className="text-xs mb-2" style={{ color: "var(--text-secondary)" }}>{s.tagline}</p>
              <p className="text-xs italic" style={{ color: "var(--text-muted)" }}>{s.note}</p>
            </div>
          ))}
        </div>

        <button
          type="button"
          onClick={() => nav("/today")}
          className="text-sm inline-flex items-center gap-1.5"
          style={{ color: "var(--text-muted)" }}
          data-testid="setup-keys-back"
        >
          ← Back to Today
        </button>
      </div>

      {/* Modal */}
      {openModal && (
        <BYOKModal
          svc={openModal}
          existingStatus={status[openModal.id]}
          onClose={() => { setOpenModal(null); load(); }}
        />
      )}
    </div>
  );
}

// ---------- Section header ----------
function SectionHeader({ overline, title, hint }) {
  return (
    <div className="mb-6">
      <div className="overline mb-2">{overline}</div>
      <h2 className="font-serif text-2xl sm:text-3xl font-light mb-2" style={{ color: "var(--text-primary)" }}>
        {title}
      </h2>
      <p className="text-sm max-w-2xl" style={{ color: "var(--text-muted)" }}>{hint}</p>
    </div>
  );
}

// ---------- OAuth tile ----------
function OAuthTile({ svc, status }) {
  const connected = status?.source === "you";
  const serverReady = status?.server_ready !== false;
  const [busy, setBusy] = useState(false);
  const Icon = svc.icon;

  const connect = async () => {
    setBusy(true);
    try {
      const { data } = await api.get(`/oauth/${svc.id}/connect`);
      if (data?.authorize_url) {
        window.location.href = data.authorize_url;
        return;
      }
      toast.error("Couldn't start sign-in.");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't start sign-in.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="rounded-sm p-6 flex flex-col justify-between transition-all"
      style={{
        border: `1px solid ${connected ? svc.accent : "var(--border-default)"}`,
        background: connected ? `${svc.accent}0d` : "var(--bg-surface)",
      }}
      data-testid={`oauth-tile-${svc.id}`}
    >
      <div>
        <div className="flex items-center justify-between mb-3">
          <Icon className="h-6 w-6" style={{ color: svc.accent }} />
          {connected && (
            <span className="text-xs px-2 py-0.5 rounded-full flex items-center gap-1" style={{ color: svc.accent, border: `1px solid ${svc.accent}` }}>
              <Check className="h-3 w-3" /> connected
            </span>
          )}
        </div>
        <div className="text-lg font-medium mb-1" style={{ color: "var(--text-primary)" }}>
          {svc.name}
        </div>
        <p className="text-sm mb-6" style={{ color: "var(--text-secondary)" }}>{svc.tagline}</p>
      </div>
      {!serverReady ? (
        <p className="text-xs italic" style={{ color: "var(--text-muted)" }}>
          Ask the person who set up Heirloom to add {svc.name}. We never ask for your password.
        </p>
      ) : (
        <button
          type="button"
          onClick={connect}
          disabled={busy}
          data-testid={`oauth-tile-btn-${svc.id}`}
          className="inline-flex items-center justify-center gap-2 w-full px-4 py-2.5 rounded-sm text-sm font-medium disabled:opacity-60"
          style={{
            background: connected ? "transparent" : svc.accent,
            color: connected ? svc.accent : "#ffffff",
            border: `1px solid ${svc.accent}`,
          }}
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          {connected ? "Reconnect" : `Connect ${svc.name}`}
          <ChevronRight className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}

// ---------- BYOK tile ----------
function BYOKTile({ svc, status, onOpen }) {
  const connected = status?.source === "you";
  return (
    <div
      className="rounded-sm p-6 flex flex-col justify-between transition-all cursor-pointer hover:border-opacity-100"
      style={{
        border: `1px solid ${connected ? svc.accent : "var(--border-default)"}`,
        background: connected ? `${svc.accent}0d` : "var(--bg-surface)",
      }}
      onClick={onOpen}
      data-testid={`byok-tile-${svc.id}`}
    >
      <div>
        <div className="flex items-center justify-between mb-3">
          <Sparkles className="h-5 w-5" style={{ color: svc.accent }} />
          {connected ? (
            <span className="text-xs px-2 py-0.5 rounded-full flex items-center gap-1" style={{ color: svc.accent, border: `1px solid ${svc.accent}` }}>
              <Check className="h-3 w-3" /> key saved
            </span>
          ) : (
            <span className="text-xs px-2 py-0.5 rounded-full" style={{ color: "var(--text-muted)", border: "1px solid var(--border-default)" }}>
              2 min setup
            </span>
          )}
        </div>
        <div className="text-lg font-medium mb-1" style={{ color: "var(--text-primary)" }}>
          {svc.name}
        </div>
        <p className="text-sm mb-6" style={{ color: "var(--text-secondary)" }}>{svc.tagline}</p>
      </div>
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); onOpen(); }}
        data-testid={`byok-tile-btn-${svc.id}`}
        className="inline-flex items-center justify-center gap-2 w-full px-4 py-2.5 rounded-sm text-sm font-medium"
        style={{
          background: connected ? "transparent" : svc.accent,
          color: connected ? svc.accent : "#111",
          border: `1px solid ${svc.accent}`,
        }}
      >
        {connected ? "Manage key" : `Set up ${svc.name}`}
        <ChevronRight className="h-4 w-4" />
      </button>
    </div>
  );
}

function ComingSoonTile({ name, tagline, accent }) {
  return (
    <div
      className="rounded-sm p-6 opacity-70"
      style={{ border: "1px dashed var(--border-default)", background: "var(--bg-surface)" }}
      data-testid={`oauth-coming-${name.toLowerCase()}`}
    >
      <div className="flex items-center justify-between mb-3">
        <div className="h-6 w-6 rounded-sm" style={{ background: accent }} />
        <span className="text-xs px-2 py-0.5 rounded-full" style={{ color: "var(--text-muted)", border: "1px solid var(--border-default)" }}>
          coming soon
        </span>
      </div>
      <div className="text-lg font-medium mb-1" style={{ color: "var(--text-primary)" }}>{name}</div>
      <p className="text-sm" style={{ color: "var(--text-secondary)" }}>{tagline}</p>
    </div>
  );
}

// ---------- BYOK Modal Wizard ----------
function BYOKModal({ svc, existingStatus, onClose }) {
  const [step, setStep] = useState(0);
  const [key, setKey] = useState("");
  const [reveal, setReveal] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [verified, setVerified] = useState(null);
  const [saving, setSaving] = useState(false);
  const [clearing, setClearing] = useState(false);
  const connected = existingStatus?.source === "you";

  const verify = async () => {
    const trimmed = key.trim();
    if (!trimmed) { toast.error("Paste your key first."); return; }
    setVerifying(true); setVerified(null);
    try {
      const r = await api.post("/user-keys/verify", { service: svc.id, api_key: trimmed });
      setVerified(r.data);
      if (r.data.ok) toast.success("Verified!");
      else toast.error(r.data.detail || "Couldn't verify.");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Verify failed.");
    } finally { setVerifying(false); }
  };

  const save = async () => {
    const trimmed = key.trim();
    if (!trimmed) { toast.error("Paste your key first."); return; }
    setSaving(true);
    try {
      await api.put(svc.keyEndpoint, { api_key: trimmed });
      toast.success(`${svc.name} connected!`);
      onClose();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Save failed.");
    } finally { setSaving(false); }
  };

  const removeKey = async () => {
    if (!window.confirm(`Remove ${svc.name} key?`)) return;
    setClearing(true);
    try {
      await api.delete(svc.keyEndpoint);
      toast.success(`${svc.name} key removed.`);
      onClose();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't remove key.");
    } finally { setClearing(false); }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,0.6)" }}
      onClick={onClose}
      data-testid="byok-modal"
    >
      <div
        className="rounded-sm max-w-lg w-full max-h-[90vh] overflow-y-auto"
        style={{ background: "var(--bg-surface)", border: `1px solid ${svc.accent}` }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal header */}
        <div
          className="px-6 py-5 flex items-center justify-between"
          style={{ borderBottom: "1px solid var(--border-default)" }}
        >
          <div className="flex items-center gap-3">
            <Sparkles className="h-5 w-5" style={{ color: svc.accent }} />
            <div>
              <div className="text-lg font-medium" style={{ color: "var(--text-primary)" }}>
                Set up {svc.name}
              </div>
              <p className="text-xs" style={{ color: "var(--text-muted)" }}>{svc.freeTier}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            data-testid="byok-modal-close"
            className="p-1 rounded-sm"
            style={{ color: "var(--text-muted)" }}
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Step tabs */}
        <div
          className="px-6 py-3 flex items-center gap-4 text-xs"
          style={{ borderBottom: "1px solid var(--border-default)", color: "var(--text-muted)" }}
        >
          {["Get the key", "Paste & verify"].map((label, i) => (
            <button
              key={label}
              type="button"
              onClick={() => setStep(i)}
              className="flex items-center gap-2"
              style={{ color: step === i ? svc.accent : "var(--text-muted)" }}
              data-testid={`byok-modal-tab-${i}`}
            >
              <span
                className="w-5 h-5 rounded-full flex items-center justify-center text-[10px]"
                style={{
                  background: step === i ? svc.accent : "transparent",
                  color: step === i ? "#111" : "var(--text-muted)",
                  border: `1px solid ${step === i ? svc.accent : "var(--border-default)"}`,
                }}
              >
                {i + 1}
              </span>
              {label}
            </button>
          ))}
        </div>

        {/* Modal body */}
        <div className="p-6">
          {step === 0 && (
            <div data-testid="byok-modal-step-1">
              <p className="text-sm mb-4" style={{ color: "var(--text-primary)" }}>
                Follow these steps in a new tab, then come back:
              </p>
              <ol className="space-y-3 mb-6 text-sm" style={{ color: "var(--text-secondary)" }}>
                {svc.steps.map((s, i) => (
                  <li key={i} className="flex gap-3">
                    <span
                      className="shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium"
                      style={{ background: `${svc.accent}22`, color: svc.accent }}
                    >
                      {i + 1}
                    </span>
                    <span>{s}</span>
                  </li>
                ))}
              </ol>
              <div className="flex flex-wrap gap-3">
                <a
                  href={svc.signup}
                  target="_blank"
                  rel="noreferrer"
                  data-testid="byok-modal-signup"
                  className="inline-flex items-center gap-2 px-4 py-2.5 rounded-sm text-sm font-medium"
                  style={{ background: svc.accent, color: "#111" }}
                >
                  Open {svc.name} in a new tab <ExternalLink className="h-4 w-4" />
                </a>
                <button
                  type="button"
                  onClick={() => setStep(1)}
                  className="inline-flex items-center gap-2 px-4 py-2.5 rounded-sm text-sm"
                  style={{ border: `1px solid ${svc.accent}`, color: svc.accent }}
                  data-testid="byok-modal-next"
                >
                  I have the key <ArrowRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          )}

          {step === 1 && (
            <div data-testid="byok-modal-step-2">
              <label
                className="text-xs block mb-2 tracking-widest uppercase"
                style={{ color: "var(--text-muted)" }}
              >
                Your {svc.name} key
              </label>
              <div className="relative mb-3">
                <input
                  type={reveal ? "text" : "password"}
                  value={key}
                  onChange={(e) => { setKey(e.target.value); setVerified(null); }}
                  placeholder={svc.placeholder}
                  data-testid="byok-modal-input"
                  className="w-full px-3 py-3 pr-10 text-sm font-mono rounded-sm"
                  style={{
                    background: "var(--bg-base)",
                    border: "1px solid var(--border-default)",
                    color: "var(--text-primary)",
                  }}
                  autoFocus
                />
                <button
                  type="button"
                  onClick={() => setReveal((r) => !r)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1"
                  style={{ color: "var(--text-muted)" }}
                  title={reveal ? "Hide" : "Reveal"}
                >
                  {reveal ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>

              {verified && (
                <div
                  className="mb-4 text-xs px-3 py-2 rounded-sm flex items-start gap-2"
                  data-testid="byok-modal-verify-result"
                  style={{
                    background: verified.ok ? "rgba(80, 160, 120, 0.14)" : "rgba(200, 90, 90, 0.14)",
                    color: verified.ok ? "var(--ok, #4d9b76)" : "#c95a5a",
                    border: `1px solid ${verified.ok ? "var(--ok, #4d9b76)" : "#c95a5a"}`,
                  }}
                >
                  {verified.ok ? <Check className="h-4 w-4 shrink-0 mt-0.5" /> : <X className="h-4 w-4 shrink-0 mt-0.5" />}
                  <span>{verified.detail}</span>
                </div>
              )}

              <div className="flex flex-wrap gap-2 items-stretch">
                <button
                  type="button"
                  onClick={verify}
                  disabled={!key || verifying}
                  data-testid="byok-modal-verify"
                  className="inline-flex items-center gap-1.5 px-4 py-2.5 rounded-sm text-sm disabled:opacity-50"
                  style={{ border: `1px solid ${svc.accent}`, color: svc.accent }}
                >
                  {verifying ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
                  Verify
                </button>
                <button
                  type="button"
                  onClick={save}
                  disabled={!key || saving}
                  data-testid="byok-modal-save"
                  className="inline-flex items-center gap-1.5 px-4 py-2.5 rounded-sm text-sm font-medium disabled:opacity-50 flex-1 justify-center"
                  style={{ background: svc.accent, color: "#111" }}
                >
                  {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                  Save &amp; connect
                </button>
              </div>

              {connected && (
                <button
                  type="button"
                  onClick={removeKey}
                  disabled={clearing}
                  data-testid="byok-modal-remove"
                  className="mt-6 text-xs inline-flex items-center gap-1.5"
                  style={{ color: "var(--text-muted)" }}
                >
                  {clearing ? <Loader2 className="h-3 w-3 animate-spin" /> : <X className="h-3 w-3" />}
                  Remove existing {svc.name} key
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
