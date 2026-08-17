import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { api } from "../lib/api";
import { StudioFieldRow, StudioPanel } from "../components/studio";

const STEPS = [
  { id: "welcome", label: "Welcome" },
  { id: "space", label: "Disk" },
  { id: "email", label: "Email" },
  { id: "keys", label: "Cloud keys" },
  { id: "phone", label: "Phone" },
  { id: "done", label: "Finish" },
];

export default function FirstRunSetup() {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [email, setEmail] = useState("");
  const [keyDrafts, setKeyDrafts] = useState({});
  const [pair, setPair] = useState(null);
  const [phoneFeats, setPhoneFeats] = useState([]);

  const load = useCallback(async () => {
    const { data: body } = await api.get("/studio/first-run");
    setData(body);
    setEmail(body.settings?.vendor_email || "");
    setPhoneFeats(body.settings?.phone_features || ["twin", "capture", "journal", "reminders"]);
    return body;
  }, []);

  useEffect(() => {
    load().catch(() => toast.error("Could not load first-run setup"));
  }, [load]);

  const save = async (patch) => {
    const { data: body } = await api.put("/studio/first-run", patch);
    await load();
    return body;
  };

  const finish = async () => {
    setBusy(true);
    try {
      await save({ vendor_email: email, phone_features: phoneFeats, prefer_local: true });
      const { data: body } = await api.post("/studio/first-run/complete");
      toast.success(body.provision?.hint || "Setup complete");
      navigate("/models");
    } catch (err) {
      toast.error(err?.response?.data?.detail || err.message);
    } finally {
      setBusy(false);
    }
  };

  const startPair = async () => {
    setBusy(true);
    try {
      await save({ phone_features: phoneFeats });
      const { data: body } = await api.post("/studio/first-run/pair");
      setPair(body);
      toast.success("Pairing code ready — open it on your phone");
    } catch (err) {
      toast.error(err?.response?.data?.detail || err.message);
    } finally {
      setBusy(false);
    }
  };

  const verifySaveKey = async (svc) => {
    const draft = (keyDrafts[svc.id] || "").trim();
    if (!draft) {
      toast.error("Paste the key after you finish their sign-up");
      return;
    }
    setBusy(true);
    try {
      await api.post("/user-keys/verify", { service: svc.verify_service, api_key: draft });
      await api.put(svc.save_path, { api_key: draft });
      toast.success(`${svc.label} saved`);
      setKeyDrafts((d) => ({ ...d, [svc.id]: "" }));
      await load();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Key was rejected");
    } finally {
      setBusy(false);
    }
  };

  if (!data) {
    return (
      <div className="px-6 py-10" data-testid="setup-loading">
        Loading first-run setup…
      </div>
    );
  }

  const catalog = data.catalog || {};
  const settings = data.settings || {};
  const profileId = settings.space_profile || "full";
  const gb = catalog.full_power_gb || { min: 20, max: 50 };

  return (
    <div className="px-6 py-6 max-w-3xl" data-testid="first-run-root">
      <p className="overline mb-2">First use · dedicated PC</p>
      <h1 className="font-serif text-3xl mb-2" style={{ color: "var(--text-primary)" }}>
        Set up Heirloom once
      </h1>
      <p className="text-sm mb-6" style={{ color: "var(--text-muted)", lineHeight: 1.5 }}>
        After this, every feature is a dropdown. We prefer local models on this machine for
        security and speed. Full power uses about {gb.min}–{gb.max} GB.
      </p>

      <ol className="studio-setup-steps" data-testid="setup-steps">
        {STEPS.map((s, i) => (
          <li key={s.id} className={i === step ? "is-active" : i < step ? "is-done" : ""}>
            <button type="button" onClick={() => setStep(i)}>
              {i + 1}. {s.label}
            </button>
          </li>
        ))}
      </ol>

      {step === 0 ? (
        <StudioPanel title="What this first run does" defaultOpen>
          <ul className="text-sm space-y-2" style={{ color: "#ccc", lineHeight: 1.45 }}>
            <li>Reserve disk for local Whisper / Ollama / Piper / vault (20–50 GB if you want full power).</li>
            <li>Save the email you will use on vendor sites (ElevenLabs, D-ID, fal).</li>
            <li>
              Open those official sign-up pages. <strong>You</strong> complete any “not a robot”
              checks. Heirloom cannot create those accounts or click captchas for you — vendors
              forbid it, and it would not be secure.
            </li>
            <li>Paste each API key here. We store it and never ask again in a grouped wizard.</li>
            <li>Download local models on this PC, then pair your phone and pick phone features.</li>
          </ul>
        </StudioPanel>
      ) : null}

      {step === 1 ? (
        <StudioPanel title="Space allocation" defaultOpen>
          <p className="text-xs mb-3" style={{ color: "#999" }}>
            Local-first. Pick how much this PC should keep. You can change this later in Settings.
          </p>
          <div className="studio-compute-modes">
            {(catalog.space_profiles || []).map((p) => (
              <label key={p.id} className="studio-compute-mode">
                <input
                  type="radio"
                  name="space"
                  checked={profileId === p.id}
                  onChange={() => save({ space_profile: p.id, prefer_local: true })}
                  data-testid={`setup-space-${p.id}`}
                />
                <span className="studio-compute-mode-label">
                  {p.label} · {p.gb_min}–{p.gb_max} GB
                </span>
                <span className="studio-compute-mode-hint">{p.summary}</span>
              </label>
            ))}
          </div>
        </StudioPanel>
      ) : null}

      {step === 2 ? (
        <StudioPanel title="Vendor email" defaultOpen>
          <p className="text-xs mb-3" style={{ color: "#999", lineHeight: 1.45 }}>
            {catalog.vendor_signup_policy}
          </p>
          <StudioFieldRow label="Email for API accounts">
            <input
              type="email"
              value={email}
              placeholder="you@example.com"
              onChange={(e) => setEmail(e.target.value)}
              onBlur={() => email && save({ vendor_email: email })}
              data-testid="setup-vendor-email"
            />
          </StudioFieldRow>
        </StudioPanel>
      ) : null}

      {step === 3 ? (
        <StudioPanel title="Cloud accounts (optional extras)" defaultOpen>
          <p className="text-xs mb-4" style={{ color: "#999", lineHeight: 1.45 }}>
            Local engines do not need these. For cloned voice or a talking head, open the official
            site with the email above, finish their robot check, then paste the key.
          </p>
          {(catalog.cloud_services || []).map((svc) => {
            const have = data.keys?.[svc.id];
            const signup = email
              ? `${svc.signup_url}${svc.signup_url.includes("?") ? "&" : "?"}email=${encodeURIComponent(email)}`
              : svc.signup_url;
            return (
              <div key={svc.id} className="mb-5 pb-4" style={{ borderBottom: "1px solid #222" }}>
                <div className="flex justify-between gap-3 mb-1">
                  <strong>{svc.label}</strong>
                  <span className="text-xs" style={{ color: have ? "#7da06f" : "#c95a5a" }}>
                    {have ? "saved" : "not set"}
                  </span>
                </div>
                <p className="text-xs mb-2" style={{ color: "#888" }}>
                  {svc.powers}
                </p>
                <div className="flex gap-2 flex-wrap mb-2">
                  <a className="studio-btn" href={signup} target="_blank" rel="noreferrer">
                    Create account
                  </a>
                  <a className="studio-btn" href={svc.dashboard_url} target="_blank" rel="noreferrer">
                    Get API key
                  </a>
                </div>
                <StudioFieldRow label="Paste key">
                  <input
                    type="password"
                    placeholder={svc.placeholder}
                    value={keyDrafts[svc.id] || ""}
                    onChange={(e) => setKeyDrafts((d) => ({ ...d, [svc.id]: e.target.value }))}
                    data-testid={`setup-key-${svc.id}`}
                  />
                </StudioFieldRow>
                <button
                  type="button"
                  className="studio-btn studio-btn-primary mt-2"
                  disabled={busy}
                  onClick={() => verifySaveKey(svc)}
                >
                  Verify & save
                </button>
              </div>
            );
          })}
        </StudioPanel>
      ) : null}

      {step === 4 ? (
        <StudioPanel title="Connect your phone" defaultOpen>
          <p className="text-xs mb-3" style={{ color: "#999", lineHeight: 1.45 }}>
            Same Heirloom login on the phone. Heavy models stay on this PC. Choose what the phone
            is allowed to do.
          </p>
          {(catalog.phone_features || [])
            .filter((f) => !f.pc_only)
            .map((f) => (
              <label key={f.id} className="flex gap-2 items-start mb-2 text-sm">
                <input
                  type="checkbox"
                  checked={phoneFeats.includes(f.id)}
                  onChange={(e) => {
                    const next = e.target.checked
                      ? [...phoneFeats, f.id]
                      : phoneFeats.filter((id) => id !== f.id);
                    setPhoneFeats(next);
                  }}
                  data-testid={`setup-phone-${f.id}`}
                />
                <span>
                  <strong>{f.label}</strong>
                  <span className="block text-xs" style={{ color: "#888" }}>
                    {f.hint}
                  </span>
                </span>
              </label>
            ))}
          <button
            type="button"
            className="studio-btn studio-btn-primary mt-3"
            disabled={busy}
            onClick={startPair}
            data-testid="setup-pair-btn"
          >
            Generate pairing code
          </button>
          {pair ? (
            <div className="mt-4" data-testid="setup-pair-code">
              <p className="text-xs" style={{ color: "#888" }}>
                On your phone, sign in and open
              </p>
              <p className="studio-value break-all">{pair.url}</p>
              <p className="text-4xl font-mono tracking-widest mt-2">{pair.code}</p>
              <p className="text-xs mt-1" style={{ color: "#777" }}>
                Expires {String(pair.expires_at).slice(11, 16)} UTC · same account as this PC
              </p>
            </div>
          ) : null}
          {(data.phones || []).length > 0 ? (
            <p className="text-xs mt-3" style={{ color: "#7da06f" }}>
              Paired: {data.phones.map((p) => p.name).join(", ")}
            </p>
          ) : null}
        </StudioPanel>
      ) : null}

      {step === 5 ? (
        <StudioPanel title="Finish — then pick engines in each window" defaultOpen>
          <p className="text-sm mb-3" style={{ color: "#ccc", lineHeight: 1.5 }}>
            Completing setup queues local model downloads on the dedicated PC (Whisper / Ollama /
            Piper for your disk profile). After that, Models is only dropdowns per feature.
          </p>
          <button
            type="button"
            className="studio-btn studio-btn-primary"
            disabled={busy}
            onClick={finish}
            data-testid="setup-finish"
          >
            {busy ? "Saving…" : "Finish setup & download local models"}
          </button>
        </StudioPanel>
      ) : null}

      <div className="flex justify-between mt-6">
        <button
          type="button"
          className="studio-btn"
          disabled={step === 0}
          onClick={() => setStep((s) => Math.max(0, s - 1))}
        >
          Back
        </button>
        {step < STEPS.length - 1 ? (
          <button type="button" className="studio-btn studio-btn-primary" onClick={() => setStep((s) => s + 1)}>
            Next
          </button>
        ) : null}
      </div>
    </div>
  );
}
