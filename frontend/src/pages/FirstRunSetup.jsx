import { useCallback, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { api, API_BASE } from "../lib/api";
import { notifyTwinSetupChanged, stepById } from "../lib/twinSetup";
import { StudioFieldRow, StudioPanel, VendorCoach } from "../components/studio";
import { openCoachStep } from "../components/studio/VendorHandoff";
import { SetupExampleRow } from "../components/studio/SetupIllustrations";

const STEPS = [
  { id: "welcome", label: "Welcome" },
  { id: "space", label: "Disk" },
  { id: "email", label: "Email" },
  { id: "voice", label: "Voice" },
  { id: "likeness", label: "Photos" },
  { id: "phone", label: "Phone" },
  { id: "done", label: "Install" },
  { id: "keys", label: "Cloud keys" },
];

const LIKENESS_ANGLES = [
  { id: "front", exampleId: "front", label: "Straight on" },
  { id: "left", exampleId: "three_quarter", label: "Three-quarter" },
  { id: "right", exampleId: "profile", label: "Profile" },
];

function stepIndexFromHash(hash) {
  const id = (hash || "").replace("#", "");
  const i = STEPS.findIndex((s) => s.id === id);
  return i >= 0 ? i : 0;
}

export default function FirstRunSetup() {
  const navigate = useNavigate();
  const location = useLocation();
  const [data, setData] = useState(null);
  const [step, setStep] = useState(() => stepIndexFromHash(window.location.hash));
  const [busy, setBusy] = useState(false);
  const [email, setEmail] = useState("");
  const [pair, setPair] = useState(null);
  const [phoneFeats, setPhoneFeats] = useState([]);
  const [coachOn, setCoachOn] = useState(false);
  const [voiceName, setVoiceName] = useState("My Twin voice");
  const [voiceFiles, setVoiceFiles] = useState([]);
  const [likenessBusy, setLikenessBusy] = useState("");

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

  useEffect(() => {
    const i = stepIndexFromHash(location.hash);
    if (i) setStep(i);
  }, [location.hash]);

  const save = async (patch) => {
    const { data: body } = await api.put("/studio/first-run", patch);
    await load();
    return body;
  };

  const startCoach = (serviceId) => {
    setCoachOn(true);
    try {
      if (email) save({ vendor_email: email });
      const pending = (data?.catalog?.cloud_services || [])
        .map((svc) => ({
          ...svc,
          ...(data.handoffs || {})[svc.id],
          alreadySaved: Boolean(data.keys?.[svc.id]),
        }))
        .filter((svc) => !svc.alreadySaved);
      const first = (serviceId && pending.find((s) => s.id === serviceId)) || pending[0];
      if (first) {
        const steps = first.coach_steps?.length ? first.coach_steps : null;
        openCoachStep(
          first,
          steps ? steps[0] : { id: "create_account", copy: email, open_url: first.signup_url, auto_open: true },
          email
        );
      }
    } catch {
      /* coach still opens */
    }
  };

  const downloadModels = async () => {
    setBusy(true);
    try {
      await save({ vendor_email: email, phone_features: phoneFeats, prefer_local: true });
      const { data: body } = await api.post("/studio/first-run/complete");
      toast.success(body.provision?.hint || "Local models queued on the dedicated PC");
      setStep(STEPS.length - 1);
      startCoach();
    } catch (err) {
      toast.error(err?.response?.data?.detail || err.message);
    } finally {
      setBusy(false);
    }
  };

  const enterStudio = async () => {
    setBusy(true);
    try {
      await save({ complete: true, vendor_email: email, phone_features: phoneFeats });
      notifyTwinSetupChanged();
      navigate("/twin");
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

  const cloneVoice = async () => {
    if (!voiceFiles.length) {
      toast.error("Add at least one recording of you speaking.");
      return;
    }
    if (!data?.keys?.elevenlabs) {
      toast.message("Save an ElevenLabs key first — the guide will open.");
      startCoach("elevenlabs");
      return;
    }
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("name", voiceName.trim() || "My Twin voice");
      fd.append("description", "First-run Twin voice");
      for (const f of voiceFiles) fd.append("files", f);
      const res = await fetch(`${API_BASE}/voice-clone/clone`, {
        method: "POST",
        credentials: "include",
        body: fd,
      });
      const text = await res.text();
      if (!res.ok) throw new Error(text || "Clone failed");
      toast.success("Voice cloned. The Twin can sound like you.");
      await load();
      notifyTwinSetupChanged();
    } catch (err) {
      toast.error(err.message || "Could not clone the voice");
    } finally {
      setBusy(false);
    }
  };

  const uploadLikeness = async (angle, file) => {
    if (!file) return;
    setLikenessBusy(angle);
    try {
      const fd = new FormData();
      fd.append("angle", angle);
      fd.append("file", file);
      await api.post("/avatar-studio/upload", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      toast.success(`${angle} photo saved`);
      await load();
      notifyTwinSetupChanged();
    } catch (err) {
      toast.error(err?.response?.data?.detail || err.message);
    } finally {
      setLikenessBusy("");
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
  const progress = data.progress || {};
  const profileId = settings.space_profile || "medium";
  const gb = catalog.full_power_gb || { min: 100, max: 160 };
  const gbLabel = (p) => (p.gb_max ? `${p.gb_min}–${p.gb_max} GB` : `${p.gb_min} GB+`);
  const voiceStep = stepById(progress, "voice") || catalog.twin_setup_steps?.[0];
  const likenessStep = stepById(progress, "likeness") || catalog.twin_setup_steps?.[1];
  const voiceDone = Boolean(progress.voice_ready);
  const likenessDone = Boolean(progress.likeness_ready);

  const go = (i) => {
    setStep(i);
    const id = STEPS[i]?.id;
    if (id) navigate(`/setup#${id}`, { replace: true });
  };

  return (
    <div className="px-6 py-6 max-w-3xl" data-testid="first-run-root">
      <p className="overline mb-2">Heirloom Unbound · first use</p>
      <h1 className="font-serif text-3xl mb-2" style={{ color: "var(--text-primary)" }}>
        Make a Twin that sounds and looks like you
      </h1>
      <p className="text-sm mb-6" style={{ color: "var(--text-muted)", lineHeight: 1.5 }}>
        Two things unlock the live Twin: a cloned voice, and three likeness photos. After that you
        can sit, make talking video, and enter a Heirloom Room. Local models stay on this PC. Large
        is about {gb.min}–{gb.max} GB.
      </p>

      <ol className="studio-setup-steps" data-testid="setup-steps">
        {STEPS.map((s, i) => (
          <li
            key={s.id}
            className={
              i === step
                ? "is-active"
                : i < step || (s.id === "voice" && voiceDone) || (s.id === "likeness" && likenessDone)
                  ? "is-done"
                  : ""
            }
          >
            <button type="button" onClick={() => go(i)}>
              {i + 1}. {s.label}
            </button>
          </li>
        ))}
      </ol>

      {step === 0 ? (
        <StudioPanel title="What this first run unlocks" defaultOpen>
          <ul className="text-sm space-y-2" style={{ color: "#ccc", lineHeight: 1.45 }}>
            <li>
              <strong>Clone your voice</strong> so the Twin greets people as you — not a stock speaker.
            </li>
            <li>
              <strong>Take three photos</strong> (front, three-quarter, profile) to build the lifelike
              talking picture.
            </li>
            <li>That pair unlocks live sit, talking video, and sitting in a captured room.</li>
            <li>Reserve disk, pair a phone, then download local models on this PC.</li>
            <li>
              A stay-on-top guide can open official vendor pages.
              <strong> You</strong> click Create account, I’m not a robot, and Verify — Heirloom cannot
              drive those sites or read keys off a screenshot.
            </li>
            <li>If you leave voice or photos for later, a reminder stays in the top-right. You can close it.</li>
          </ul>
        </StudioPanel>
      ) : null}

      {step === 1 ? (
        <StudioPanel title="Install size" defaultOpen>
          <p className="text-xs mb-3" style={{ color: "#999" }}>
            Heirloom Unbound. Pick how much this PC should keep. You can change this later in Models.
          </p>
          <div className="studio-compute-modes">
            {(catalog.space_profiles || []).map((p) => (
              <label key={p.id} className="studio-compute-mode">
                <input
                  type="radio"
                  name="space"
                  checked={profileId === p.id}
                  onChange={() =>
                    save({
                      space_profile: p.id,
                      install_profile: p.id,
                      prefer_local: true,
                      dedicated_consent: p.id === "dedicated",
                    })
                  }
                  data-testid={`setup-space-${p.id}`}
                />
                <span className="studio-compute-mode-label">
                  {p.label} · {gbLabel(p)}
                </span>
                <span className="studio-compute-mode-hint">{p.summary}</span>
              </label>
            ))}
          </div>
          {profileId === "dedicated" ? (
            <p className="text-xs mt-3" style={{ color: "#c9b8a4" }} data-testid="setup-dedicated-consent">
              Dedicated PC: this computer exists for Heirloom Unbound. Prefer a second vault
              disk, start with Windows, and warm local engines. High-performance power plan
              needs explicit consent on the Windows app — we do not silently fight IT policy.
            </p>
          ) : null}
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
        <StudioPanel title="Clone your voice" defaultOpen testId="setup-voice-panel">
          <p className="text-sm mb-3" style={{ color: "#ccc", lineHeight: 1.5 }}>
            {voiceStep?.benefit} This is required for the Twin to speak as you. You can skip and a
            reminder will stay in the corner.
          </p>
          <ul className="text-xs mb-3 space-y-1" style={{ color: "#9a9a9a" }}>
            {(voiceStep?.unlocks || []).map((u) => (
              <li key={u}>Unlocks: {u}</li>
            ))}
          </ul>
          <SetupExampleRow examples={voiceStep?.examples} done={voiceDone} />
          {voiceDone ? (
            <p className="text-sm mt-3" style={{ color: "#7da06f" }} data-testid="setup-voice-done">
              Voice ready{progress.voice_name ? ` — ${progress.voice_name}` : ""}.
            </p>
          ) : (
            <>
              <StudioFieldRow label="Name this voice">
                <input
                  value={voiceName}
                  onChange={(e) => setVoiceName(e.target.value)}
                  data-testid="setup-voice-name"
                />
              </StudioFieldRow>
              <StudioFieldRow label="Recordings of you">
                <input
                  type="file"
                  accept="audio/*"
                  multiple
                  onChange={(e) => setVoiceFiles(Array.from(e.target.files || []))}
                  data-testid="setup-voice-files"
                />
              </StudioFieldRow>
              <p className="text-xs mb-3" style={{ color: "#888" }}>
                One clip of about 30 seconds is enough. Speak as you would to family.
              </p>
              {!data.keys?.elevenlabs ? (
                <button
                  type="button"
                  className="studio-btn studio-btn-primary mb-2"
                  onClick={() => startCoach("elevenlabs")}
                  data-testid="setup-voice-key-guide"
                >
                  Open the voice-key guide
                </button>
              ) : null}
              <button
                type="button"
                className="studio-btn studio-btn-primary"
                disabled={busy}
                onClick={cloneVoice}
                data-testid="setup-voice-clone"
              >
                {busy ? "Cloning…" : "Clone this voice"}
              </button>
            </>
          )}
        </StudioPanel>
      ) : null}

      {step === 4 ? (
        <StudioPanel title="Take likeness photos" defaultOpen testId="setup-likeness-panel">
          <p className="text-sm mb-3" style={{ color: "#ccc", lineHeight: 1.5 }}>
            {likenessStep?.benefit} Three photos. Same clothes, even light, you alone in the frame.
          </p>
          <ul className="text-xs mb-3 space-y-1" style={{ color: "#9a9a9a" }}>
            {(likenessStep?.unlocks || []).map((u) => (
              <li key={u}>Unlocks: {u}</li>
            ))}
          </ul>
          <SetupExampleRow examples={likenessStep?.examples} done={likenessDone} />
          <p className="text-xs mt-2 mb-3" style={{ color: progress.likeness_ready ? "#7da06f" : "#c9b8a4" }}>
            {progress.likeness_have || 0} of {progress.likeness_needed || 3} photos on file
          </p>
          <div className="setup-likeness-uploads">
            {LIKENESS_ANGLES.map((ang) => (
              <label key={ang.id} className="setup-likeness-upload">
                <span>{ang.label}</span>
                <input
                  type="file"
                  accept="image/*"
                  capture="user"
                  disabled={Boolean(likenessBusy)}
                  data-testid={`setup-likeness-${ang.id}`}
                  onChange={(e) => uploadLikeness(ang.id, e.target.files?.[0])}
                />
                {likenessBusy === ang.id ? <em>Saving…</em> : null}
              </label>
            ))}
          </div>
          <button
            type="button"
            className="studio-btn mt-3"
            onClick={() => navigate("/avatar-studio")}
            data-testid="setup-open-avatar-studio"
          >
            Open Avatar Studio
          </button>
        </StudioPanel>
      ) : null}

      {step === 5 ? (
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

      {step === 6 ? (
        <StudioPanel title="Install local models first" defaultOpen>
          <p className="text-sm mb-3" style={{ color: "#ccc", lineHeight: 1.5 }}>
            Completing this step queues Whisper / Ollama / Piper on the dedicated PC. The vendor
            guide comes next so screen vision is already there on first open.
          </p>
          <button
            type="button"
            className="studio-btn studio-btn-primary"
            disabled={busy}
            onClick={downloadModels}
            data-testid="setup-finish"
          >
            {busy ? "Saving…" : "Download local models"}
          </button>
        </StudioPanel>
      ) : null}

      {step === 7 ? (
        <StudioPanel title="Cloud accounts — after install" defaultOpen>
          <p className="text-xs mb-4" style={{ color: "#999", lineHeight: 1.45 }}>
            {catalog.vendor_signup_policy} Local Whisper/Ollama do not need these keys. Screen
            watch is in the dedicated PC app; this browser guide still opens official pages from
            your click.
          </p>
          <button
            type="button"
            className="studio-btn studio-btn-primary mb-4"
            onClick={() => startCoach()}
            data-testid="setup-start-coach"
          >
            Pop out the guide
          </button>
          {(catalog.cloud_services || []).map((svc) => (
            <div key={svc.id} className="studio-handoff">
              <div className="flex justify-between gap-3">
                <strong>{svc.label}</strong>
                <span className="text-xs" style={{ color: data.keys?.[svc.id] ? "#7da06f" : "#c95a5a" }}>
                  {data.keys?.[svc.id] ? "saved" : "not set"}
                </span>
              </div>
              <p className="text-xs" style={{ color: "#888" }}>
                {svc.powers}
              </p>
            </div>
          ))}
          <button
            type="button"
            className="studio-btn mt-4"
            disabled={busy}
            onClick={enterStudio}
            data-testid="setup-enter-studio"
          >
            Enter studio
          </button>
          <button
            type="button"
            className="studio-btn studio-btn-primary mt-3"
            disabled={busy}
            onClick={() => navigate("/first-gift")}
            data-testid="setup-first-gift"
          >
            Write the first gift
          </button>
          <p className="text-xs mt-3" style={{ color: "#888" }}>
            Not a chatbot. A gift. A sealed letter for later — after you sit with your Twin.
          </p>
        </StudioPanel>
      ) : null}

      {coachOn ? (
        <VendorCoach
          email={email}
          onSaved={() => load()}
          onPersistEmail={() => email && save({ vendor_email: email })}
          onDone={() => {
            setCoachOn(false);
            load();
          }}
          services={(catalog.cloud_services || []).map((svc) => {
            const handoff = (data.handoffs || {})[svc.id] || {};
            return {
              ...svc,
              ...handoff,
              alreadySaved: Boolean(data.keys?.[svc.id]),
            };
          })}
        />
      ) : null}

      <div className="flex justify-between mt-6">
        <button type="button" className="studio-btn" disabled={step === 0} onClick={() => go(Math.max(0, step - 1))}>
          Back
        </button>
        {step < STEPS.length - 1 ? (
          <button
            type="button"
            className="studio-btn studio-btn-primary"
            data-testid="setup-next"
            onClick={async () => {
              if (step === 2 && email) {
                await save({ vendor_email: email });
              }
              if ((step === 3 && !voiceDone) || (step === 4 && !likenessDone)) {
                toast.message("A reminder will sit in the top-right until this is done.");
              }
              go(step + 1);
            }}
          >
            {(step === 3 && !voiceDone) || (step === 4 && !likenessDone) ? "Skip for now" : "Next"}
          </button>
        ) : null}
      </div>
    </div>
  );
}
