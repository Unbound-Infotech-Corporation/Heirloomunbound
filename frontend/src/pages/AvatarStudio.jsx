import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Camera, Check, ChevronDown, Download, ExternalLink, Eye, Heart, Loader2, Mail, Monitor, Sparkles, Upload, Video, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { usePageMeta } from "@/lib/usePageMeta";

const ANGLES = [
  { key: "front", label: "Your face", hint: "A clear photo looking at the camera. Glasses on if you wear them every day." },
  { key: "three_quarter", label: "Three-quarter", hint: "Face turned a little. Optional — helps the twin look like you from the side." },
  { key: "left", label: "Left profile", hint: "Optional side view." },
  { key: "right", label: "Right profile", hint: "Optional side view." },
  { key: "full", label: "Full body", hint: "Optional. Standing, head to toe, if you want a body that moves like yours." },
];

const BUILD_LABELS = {
  slim: "Slender",
  average: "Average",
  athletic: "Athletic",
  heavy: "Solid",
};

function setupBusy(job) {
  if (!job) return false;
  return ["queued", "dispatched", "processing"].includes(job.status) && !job.done;
}

function setupReady(data) {
  const last = data?.setup?.last_job;
  return Boolean(data?.setup?.consent_at) && last && (last.ok || last.status === "done");
}

function plainErr(e, fallback) {
  const detail = e?.response?.data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  return fallback;
}

export default function AvatarStudio() {
  const nav = useNavigate();
  usePageMeta({
    title: "Your twin · Heirloom",
    description: "One photo and one tap. We install the free tools on your home computer. No extra accounts.",
  });

  const [data, setData] = useState(null);
  const [uploading, setUploading] = useState(null); // angle string while in flight
  const [enhanceState, setEnhanceState] = useState({ open: false, strength: 35, previewUrl: null, previewId: null, originalUrl: null, originalId: null });
  const [body, setBody] = useState({ height_cm: "", weight_kg: "", build: "average", presentation: "unspecified", notes: "" });
  const [engine, setEngine] = useState("auto");
  const [busy, setBusy] = useState("");
  const [jobHint, setJobHint] = useState("");
  const [consent, setConsent] = useState(false);
  const [showExtras, setShowExtras] = useState(false);
  const [setupJob, setSetupJob] = useState(null);

  const load = async () => {
    try {
      const r = await api.get("/avatar-studio/me");
      setData(r.data);
      const b = r.data.body || {};
      setBody({
        height_cm: b.height_cm ?? "",
        weight_kg: b.weight_kg ?? "",
        build: b.build || "average",
        presentation: b.presentation || "unspecified",
        notes: b.notes || "",
      });
      setEngine(r.data.engine || "auto");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't load avatars.");
    }
  };
  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    const last = data?.setup?.last_job;
    if (!last || last.done) {
      setSetupJob(last || null);
      return undefined;
    }
    setSetupJob(last);
    const id = last.job_id;
    const timer = setInterval(async () => {
      try {
        const r = await api.get(`/avatar-studio/jobs/${id}`);
        setSetupJob(r.data);
        if (r.data.done) {
          clearInterval(timer);
          load();
        }
      } catch {
        /* keep waiting — the home PC may still be installing */
      }
    }, 2500);
    return () => clearInterval(timer);
  }, [data?.setup?.last_job?.job_id, data?.setup?.last_job?.status]);

  const handleUpload = async (angle, file) => {
    if (!file) return;
    setUploading(angle);
    try {
      const fd = new FormData();
      fd.append("angle", angle);
      fd.append("file", file);
      await api.post("/avatar-studio/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success(`${angle} uploaded.`);
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Upload failed.");
    } finally {
      setUploading(null);
    }
  };

  const setActiveImage = async (image_id) => {
    try {
      await api.post("/avatar-studio/use", { image_id });
      toast.success("Set as your twin's face.");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't save.");
    }
  };

  const openEnhance = (img) => {
    if (!data?.fal_configured) {
      toast.error("Beautify needs a fal.ai key — add yours in Setup → Keys & Integrations.");
      return;
    }
    setEnhanceState({
      open: true,
      strength: 35,
      previewUrl: null,
      previewId: null,
      originalUrl: img.serve_url,
      originalId: img.image_id,
    });
  };

  const runEnhance = async () => {
    const strength = enhanceState.strength / 100;
    try {
      const r = await api.post("/avatar-studio/enhance", {
        image_id: enhanceState.originalId,
        strength,
      });
      setEnhanceState((s) => ({ ...s, previewUrl: r.data.serve_url, previewId: r.data.image_id }));
      toast.success("Enhanced — preview ready.");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Enhance failed.");
    }
  };

  const commitEnhanced = async () => {
    if (!enhanceState.previewId) return;
    await setActiveImage(enhanceState.previewId);
    setEnhanceState({ open: false, strength: 35, previewUrl: null, previewId: null, originalUrl: null, originalId: null });
  };

  const saveBody = async () => {
    setBusy("body");
    try {
      const payload = {
        height_cm: body.height_cm === "" ? null : Number(body.height_cm),
        weight_kg: body.weight_kg === "" ? null : Number(body.weight_kg),
        build: body.build,
        presentation: body.presentation,
        notes: body.notes,
      };
      const r = await api.put("/avatar-studio/body", payload);
      setBody({
        height_cm: r.data.body.height_cm ?? "",
        weight_kg: r.data.body.weight_kg ?? "",
        build: r.data.body.build,
        presentation: r.data.body.presentation,
        notes: r.data.body.notes || "",
      });
      toast.success("Saved.");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't save measurements.");
    } finally {
      setBusy("");
    }
  };

  const saveEngine = async (next) => {
    setEngine(next);
    try {
      await api.put("/avatar-studio/engine", { engine: next });
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't save engine.");
    }
  };

  const runJob = async (kind, recipeId) => {
    setBusy(`${kind}:${recipeId || ""}`);
    setJobHint("");
    try {
      const r = await api.post("/avatar-studio/jobs", {
        kind,
        recipe_id: recipeId || "",
        text: "",
        body: {
          height_cm: body.height_cm === "" ? null : Number(body.height_cm),
          weight_kg: body.weight_kg === "" ? null : Number(body.weight_kg),
          build: body.build,
          presentation: body.presentation,
          notes: body.notes,
        },
      });
      setJobHint(r.data.hint || r.data.howto || "Your home computer is working on it.");
      toast.success(kind === "look" ? "Look at the computer — your twin is opening." : "Your home computer is working on it.");
      load();
    } catch (e) {
      toast.error(plainErr(e, "Couldn't start that. Is the Heirloom app open on the home computer?"));
    } finally {
      setBusy("");
    }
  };

  const installPinokio = async (url) => {
    if (!url) return;
    setBusy(`pinokio:${url}`);
    try {
      await api.post("/companion/queue-command", { kind: "open_url", payload: { url } });
      toast.success("Opening the install page on your home computer.");
    } catch (e) {
      toast.error(plainErr(e, "Open the Heirloom app on the computer at home first."));
    } finally {
      setBusy("");
    }
  };

  const runEasySetup = async () => {
    if (!data?.home?.connected) {
      toast.error("Open the Heirloom app on the computer at home first.");
      return;
    }
    const already = Boolean(data.setup?.consent_at);
    if (!already && !consent) {
      toast.error("Tick the box so we know you want this on your computer.");
      return;
    }
    setBusy("setup");
    setJobHint("");
    try {
      await api.put("/avatar-studio/body", {
        height_cm: body.height_cm === "" ? null : Number(body.height_cm),
        weight_kg: body.weight_kg === "" ? null : Number(body.weight_kg),
        build: body.build,
        presentation: body.presentation,
        notes: body.notes,
      });
      const r = await api.post("/avatar-studio/setup", { consent: true });
      setJobHint(r.data.hint || "We're installing the free tools on your computer.");
      toast.success("Hang tight — your computer is doing the rest.");
      load();
    } catch (e) {
      toast.error(plainErr(e, "Couldn't start. Is the Heirloom app open on the home computer?"));
    } finally {
      setBusy("");
    }
  };

  const primaryAction = async () => {
    if (setupBusy(setupJob)) return;
    if (setupReady(data) && data.front) {
      return runJob("look", "liveportrait");
    }
    if (setupReady(data) && !data.front) {
      toast.error("Add a photo of your face first — looking at the camera.");
      return;
    }
    return runEasySetup();
  };

  const connectMail = async (provider) => {
    try {
      const { data: d } = await api.get(`/oauth/${provider}/connect`);
      if (d?.authorize_url) {
        window.location.href = d.authorize_url;
        return;
      }
      toast.error("Couldn't start email sign-in.");
    } catch (e) {
      toast.error(plainErr(e, "Couldn't start email sign-in."));
    }
  };

  if (!data) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ color: "var(--text-muted)" }}>
        Loading…
      </div>
    );
  }

  return (
    <div className="min-h-screen px-6 sm:px-10 py-10" style={{ background: "var(--bg-base)" }} data-testid="avatar-studio">
      <div className="max-w-5xl mx-auto">
        <div className="overline mb-3">your twin</div>
        <h1 className="font-serif text-4xl mb-3">Look like you. Talk like you.</h1>
        <p className="text-sm mb-6 max-w-2xl" style={{ color: "var(--text-secondary)" }}>
          {(data.setup?.blurb) || (data.catalog?.setup?.blurb) || "Three taps. We install the free tools on your home computer. No extra accounts, no passwords."}
          {" "}Use a photo of <em>you</em> — never someone else.
        </p>
        {data.home && (
          <p className="text-xs mb-8" style={{ color: data.home.online ? "var(--ok, #7da06f)" : "var(--text-muted)" }} data-testid="avatar-home-status">
            <Monitor className="inline h-3.5 w-3.5 mr-1" />
            {data.home.connected
              ? (data.home.online
                ? `${data.home.name || "Your computer"} is ready.`
                : `Open the Heirloom app on ${data.home.name || "the computer at home"}.`)
              : "First, open the Heirloom app on the computer at home. We install the tools there."}
          </p>
        )}

        <section className="surface p-6 mb-8" data-testid="avatar-easy-setup">
          <ol className="text-sm mb-6 space-y-2" style={{ color: "var(--text-secondary)" }}>
            {((data.setup?.steps) || (data.catalog?.setup?.steps) || []).map((step, i) => (
              <li key={step}><span className="font-serif mr-2">{i + 1}.</span>{step}</li>
            ))}
          </ol>
          <div className="max-w-md mb-6">
            <UploadTile
              angle={ANGLES[0]}
              img={data.front || data.by_angle?.front}
              uploading={uploading === "front"}
              activeUrl={data.active_source_url}
              onUpload={(file) => handleUpload("front", file)}
              onUse={setActiveImage}
              onEnhance={openEnhance}
              falConfigured={data.fal_configured}
            />
          </div>
          <div className="grid sm:grid-cols-2 gap-4 mb-6 max-w-lg">
            <label className="text-xs" style={{ color: "var(--text-muted)" }}>
              About how tall are you? (cm, optional)
              <input
                type="number"
                min="90"
                max="230"
                value={body.height_cm}
                onChange={(e) => setBody((b) => ({ ...b, height_cm: e.target.value }))}
                data-testid="avatar-height"
                className="mt-1 w-full px-3 py-2 text-sm rounded-sm"
                style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
              />
            </label>
            <label className="text-xs" style={{ color: "var(--text-muted)" }}>
              How would you describe your build?
              <select
                value={body.build}
                onChange={(e) => setBody((b) => ({ ...b, build: e.target.value }))}
                data-testid="avatar-build"
                className="mt-1 w-full px-3 py-2 text-sm rounded-sm"
                style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
              >
                {(data.catalog?.builds || ["slim", "average", "athletic", "heavy"]).map((b) => (
                  <option key={b} value={b}>{BUILD_LABELS[b] || b}</option>
                ))}
              </select>
            </label>
          </div>
          {data.setup?.consent_at ? (
            <p className="text-xs mb-4" style={{ color: "var(--text-muted)" }}>
              You already said yes. We never ask for a Pinokio or ComfyUI password — those programs do not need an account.
            </p>
          ) : (
            <label className="flex items-start gap-3 mb-4 text-sm" style={{ color: "var(--text-secondary)" }} data-testid="avatar-consent">
              <input
                type="checkbox"
                checked={consent}
                onChange={(e) => setConsent(e.target.checked)}
                className="mt-1 h-4 w-4"
                data-testid="avatar-consent-box"
              />
              <span>{(data.setup?.consent) || (data.catalog?.setup?.consent)}</span>
            </label>
          )}
          <p className="text-xs mb-4" style={{ color: "var(--text-muted)" }}>
            {(data.setup?.windows_note) || (data.catalog?.setup?.windows_note)}
          </p>
          <button
            type="button"
            onClick={primaryAction}
            disabled={!!busy || setupBusy(setupJob)}
            data-testid="avatar-setup-go"
            className="inline-flex items-center gap-2 px-5 py-3 text-sm rounded-sm"
            style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
          >
            {(busy === "setup" || setupBusy(setupJob)) ? <Loader2 className="h-4 w-4 animate-spin" /> : setupReady(data) ? <Eye className="h-4 w-4" /> : <Heart className="h-4 w-4" />}
            {setupBusy(setupJob) || busy === "setup"
              ? "Working on your computer…"
              : setupReady(data)
                ? "Look at me"
                : "Set up my twin"}
          </button>
          {(setupJob || jobHint) && (
            <p className="text-xs mt-4" style={{ color: "var(--accent)" }} data-testid="avatar-setup-progress">
              {setupJob?.result_text || jobHint || (setupBusy(setupJob) ? "Downloading the free installer…" : "")}
            </p>
          )}
          <div className="mt-6 pt-5" style={{ borderTop: "1px solid var(--border-default)" }} data-testid="avatar-mail-cta">
            {data.mail?.connected ? (
              <>
                <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                  <Mail className="inline h-3.5 w-3.5 mr-1" />
                  Watching {data.mail.email || data.mail.label}. Ask your twin: &ldquo;what&apos;s on my plate?&rdquo; or &ldquo;check my setup emails.&rdquo;
                </p>
                {data.mail.calendar === false && (
                  <p className="text-xs mt-2" style={{ color: "var(--text-muted)" }}>
                    Tap Connect Gmail again so we can also see your calendar. We still never see your password.
                  </p>
                )}
              </>
            ) : (
              <>
                <p className="text-sm mb-3" style={{ color: "var(--text-secondary)" }}>
                  Want me to watch your inbox and calendar? Connect Gmail — Google asks, we never see your password.
                </p>
                <div className="flex flex-wrap gap-2">
                  {data.mail?.google_ready !== false && (
                    <button
                      type="button"
                      onClick={() => connectMail("google")}
                      data-testid="avatar-connect-gmail"
                      className="inline-flex items-center gap-2 px-3 py-2 text-xs rounded-sm"
                      style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
                    >
                      <Mail className="h-3.5 w-3.5" /> Connect Gmail
                    </button>
                  )}
                  {data.mail?.microsoft_ready && (
                    <button
                      type="button"
                      onClick={() => connectMail("microsoft")}
                      data-testid="avatar-connect-outlook"
                      className="inline-flex items-center gap-2 px-3 py-2 text-xs rounded-sm"
                      style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
                    >
                      Connect Outlook
                    </button>
                  )}
                </div>
                {data.mail?.google_ready === false && !data.mail?.microsoft_ready && (
                  <p className="text-xs mt-2 italic" style={{ color: "var(--text-muted)" }}>
                    Ask the person who set up Heirloom to add Google. We never ask for your email password.
                  </p>
                )}
              </>
            )}
          </div>
        </section>

        <button
          type="button"
          onClick={() => setShowExtras((v) => !v)}
          data-testid="avatar-show-extras"
          className="inline-flex items-center gap-2 text-xs mb-8"
          style={{ color: "var(--text-muted)" }}
        >
          <ChevronDown className={`h-4 w-4 transition-transform ${showExtras ? "rotate-180" : ""}`} />
          I&apos;m comfortable with extra settings
        </button>

        {showExtras && (
          <>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-6 mb-12">
          {ANGLES.filter((a) => a.key !== "front").map((a) => (
            <UploadTile
              key={a.key}
              angle={a}
              img={data[a.key] || data.by_angle?.[a.key]}
              uploading={uploading === a.key}
              activeUrl={data.active_source_url}
              onUpload={(file) => handleUpload(a.key, file)}
              onUse={setActiveImage}
              onEnhance={openEnhance}
              falConfigured={data.fal_configured}
            />
          ))}
        </div>

        {/* Body sheet */}
        <section className="surface p-6 mb-8" data-testid="avatar-body-sheet">
          <div className="overline mb-2">body sheet</div>
          <h2 className="font-serif text-2xl mb-2">How you&apos;re built</h2>
          <p className="text-xs mb-5" style={{ color: "var(--text-muted)" }}>
            InstantID and WAN read this as a prompt with your photos. Honest numbers look more like you than flattering ones.
          </p>
          <div className="grid sm:grid-cols-2 gap-4 mb-4">
            <label className="text-xs" style={{ color: "var(--text-muted)" }}>
              Weight (kg, optional)
              <input
                type="number"
                min="30"
                max="250"
                value={body.weight_kg}
                onChange={(e) => setBody((b) => ({ ...b, weight_kg: e.target.value }))}
                data-testid="avatar-weight"
                className="mt-1 w-full px-3 py-2 text-sm rounded-sm"
                style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
              />
            </label>
            <label className="text-xs" style={{ color: "var(--text-muted)" }}>
              Presentation
              <select
                value={body.presentation}
                onChange={(e) => setBody((b) => ({ ...b, presentation: e.target.value }))}
                data-testid="avatar-presentation"
                className="mt-1 w-full px-3 py-2 text-sm rounded-sm"
                style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
              >
                {(data.catalog?.presentations || ["unspecified"]).map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </label>
          </div>
          <textarea
            value={body.notes}
            onChange={(e) => setBody((b) => ({ ...b, notes: e.target.value }))}
            placeholder="Hair, glasses, posture, clothing you always wear…"
            data-testid="avatar-notes"
            rows={2}
            className="w-full px-3 py-2 text-sm rounded-sm mb-4"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
          />
          <button
            type="button"
            onClick={saveBody}
            disabled={busy === "body"}
            data-testid="avatar-save-body"
            className="px-4 py-2 text-sm rounded-sm"
            style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
          >
            {busy === "body" ? "Saving…" : "Save measurements"}
          </button>
        </section>

        {/* Engine */}
        <section className="surface p-6 mb-8" data-testid="avatar-engine">
          <div className="overline mb-2">when the twin speaks</div>
          <h2 className="font-serif text-2xl mb-3">Video engine</h2>
          <div className="flex flex-wrap gap-2">
            {[
              { id: "auto", label: "Auto", hint: "D-ID if a key is connected, otherwise local Pinokio" },
              { id: "local", label: "Local (free)", hint: "Always queue EchoMimic / LivePortrait on the home PC" },
              { id: "did", label: "D-ID (paid)", hint: "Cloud talking-head — needs a D-ID key" },
            ].map((opt) => (
              <button
                key={opt.id}
                type="button"
                onClick={() => saveEngine(opt.id)}
                data-testid={`avatar-engine-${opt.id}`}
                title={opt.hint}
                className="px-3 py-2 text-xs rounded-sm"
                style={{
                  background: engine === opt.id ? "var(--accent)" : "transparent",
                  color: engine === opt.id ? "var(--text-inverse)" : "var(--text-secondary)",
                  border: `1px solid ${engine === opt.id ? "var(--accent)" : "var(--border-default)"}`,
                }}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </section>

        {/* Recipes */}
        <section className="mb-10" data-testid="avatar-recipes">
          <div className="overline mb-2">pinokio · comfyui</div>
          <h2 className="font-serif text-2xl mb-2">Free models on your PC</h2>
          <p className="text-xs mb-5 max-w-2xl" style={{ color: "var(--text-muted)" }}>
            {data.catalog?.honest}
          </p>
          <div className="grid md:grid-cols-2 gap-4">
            {(data.catalog?.recipes || []).map((r) => (
              <div key={r.id} className="surface p-5" data-testid={`avatar-recipe-${r.id}`}>
                <div className="flex items-start justify-between gap-3 mb-2">
                  <h3 className="font-serif text-xl">{r.label}</h3>
                  <span className="text-xs px-2 py-1 rounded-sm" style={{ border: "1px solid var(--border-default)", color: "var(--text-muted)" }}>
                    ~{r.vram_gb} GB VRAM
                  </span>
                </div>
                <p className="text-xs mb-3" style={{ color: "var(--text-secondary)" }}>{r.blurb}</p>
                {r.license_note && (
                  <p className="text-xs mb-3" style={{ color: "var(--text-muted)" }}>{r.license_note}</p>
                )}
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => runJob(r.kind, r.id)}
                    disabled={!!busy}
                    data-testid={`avatar-run-${r.id}`}
                    className="inline-flex items-center gap-1 text-xs px-3 py-2 rounded-sm"
                    style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
                  >
                    {busy === `${r.kind}:${r.id}` ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : r.kind === "look" ? <Eye className="h-3.5 w-3.5" /> : <Video className="h-3.5 w-3.5" />}
                    {r.kind === "look" ? "Look at me" : r.kind === "talk" ? "Prepare talk clip" : "Build still"}
                  </button>
                  {r.pinokio_url && (
                    <button
                      type="button"
                      onClick={() => installPinokio(r.pinokio_url)}
                      data-testid={`avatar-pinokio-${r.id}`}
                      className="inline-flex items-center gap-1 text-xs px-3 py-2 rounded-sm"
                      style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
                    >
                      <Download className="h-3.5 w-3.5" /> Install in Pinokio
                    </button>
                  )}
                  {r.github && (
                    <a
                      href={r.github}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-xs px-3 py-2"
                      style={{ color: "var(--text-muted)" }}
                    >
                      <ExternalLink className="h-3.5 w-3.5" /> nodes
                    </a>
                  )}
                </div>
              </div>
            ))}
          </div>
          {jobHint && (
            <p className="text-xs mt-4" style={{ color: "var(--accent)" }} data-testid="avatar-job-hint">{jobHint}</p>
          )}
        </section>
          </>
        )}

        {(data.jobs || []).length > 0 && (
          <section className="mb-10" data-testid="avatar-jobs">
            <div className="overline mb-3">recent local jobs</div>
            <ul className="space-y-2">
              {data.jobs.map((j) => (
                <li key={j.job_id} className="text-xs flex justify-between gap-3" style={{ color: "var(--text-muted)" }}>
                  <span>{j.kind} · {j.recipe_id} · {j.status}</span>
                  {j.result_url && (
                    <a href={j.result_url} target="_blank" rel="noreferrer" style={{ color: "var(--accent)" }}>open result</a>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}
        {enhanceState.open && (
          <EnhanceDialog
            state={enhanceState}
            setStrength={(strength) => setEnhanceState((s) => ({ ...s, strength }))}
            onRun={runEnhance}
            onCommit={commitEnhanced}
            onClose={() => setEnhanceState({ open: false, strength: 35, previewUrl: null, previewId: null, originalUrl: null, originalId: null })}
          />
        )}

        <button
          type="button"
          onClick={() => nav("/settings")}
          className="text-sm underline"
          style={{ color: "var(--text-muted)" }}
          data-testid="avatar-studio-back"
        >
          ← Back to Settings
        </button>
      </div>
    </div>
  );
}

function UploadTile({ angle, img, uploading, activeUrl, onUpload, onUse, onEnhance, falConfigured }) {
  const fileInput = useRef(null);
  const [dragOver, setDragOver] = useState(false);
  const isActive = img && activeUrl === img.serve_url;
  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer?.files?.[0];
    if (file) onUpload(file);
  };
  return (
    <div
      className="surface p-5"
      data-testid={`avatar-tile-${angle.key}`}
      style={{ border: `1px solid ${isActive ? "var(--accent)" : "var(--border-default)"}` }}
    >
      <div className="overline mb-2">{angle.label.toUpperCase()}</div>
      <div
        className={`${angle.key === "full" ? "aspect-[3/4]" : "aspect-square"} rounded-sm mb-3 overflow-hidden flex items-center justify-center cursor-pointer transition-colors`}
        style={{
          background: dragOver ? "var(--accent-muted, rgba(212,163,115,0.12))" : "var(--bg-base)",
          border: `1px dashed ${dragOver ? "var(--accent)" : "var(--border-default)"}`,
        }}
        onClick={() => fileInput.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        data-testid={`avatar-dropzone-${angle.key}`}
      >
        {img?.serve_url ? (
          <img src={img.serve_url} alt={angle.label} className="w-full h-full object-cover" />
        ) : (
          <div className="flex flex-col items-center gap-2" style={{ color: "var(--text-muted)" }}>
            <Camera className="h-8 w-8" />
            <span className="text-xs">click or drop a photo</span>
          </div>
        )}
      </div>
      <p className="text-xs mb-4" style={{ color: "var(--text-muted)" }}>
        {angle.hint}
      </p>
      <input
        ref={fileInput}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        className="hidden"
        onChange={(e) => onUpload(e.target.files?.[0])}
        data-testid={`avatar-input-${angle.key}`}
      />
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => fileInput.current?.click()}
          disabled={uploading}
          data-testid={`avatar-upload-${angle.key}`}
          className="inline-flex items-center gap-1 text-xs px-3 py-2 rounded-sm"
          style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
        >
          <Upload className="h-3.5 w-3.5" /> {uploading ? "Uploading…" : img ? "Replace" : "Upload"}
        </button>
        {img && angle.key === "front" && (
          <>
            <button
              type="button"
              onClick={() => onUse(img.image_id)}
              data-testid={`avatar-use-${angle.key}`}
              disabled={isActive}
              className="inline-flex items-center gap-1 text-xs px-3 py-2 rounded-sm"
              style={{
                background: isActive ? "var(--ok)" : "transparent",
                color: isActive ? "var(--text-inverse)" : "var(--text-primary)",
                border: `1px solid ${isActive ? "var(--ok)" : "var(--border-default)"}`,
              }}
            >
              {isActive ? <><Check className="h-3.5 w-3.5" /> Active</> : "Use as twin"}
            </button>
            <button
              type="button"
              onClick={() => onEnhance(img)}
              data-testid={`avatar-enhance-${angle.key}`}
              disabled={!falConfigured}
              className="inline-flex items-center gap-1 text-xs px-3 py-2 rounded-sm"
              style={{ border: "1px solid var(--accent)", color: "var(--accent)", opacity: falConfigured ? 1 : 0.5 }}
              title={falConfigured ? "Subtle enhance" : "Beautify needs a fal.ai key — add yours in Setup → Keys & Integrations"}
            >
              <Sparkles className="h-3.5 w-3.5" /> Beautify
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function EnhanceDialog({ state, setStrength, onRun, onCommit, onClose }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-6"
      style={{ background: "rgba(0,0,0,0.7)" }}
      data-testid="enhance-dialog"
    >
      <div className="surface w-full max-w-3xl p-8" style={{ background: "var(--bg-surface)" }}>
        <div className="flex items-start justify-between mb-4">
          <div>
            <div className="overline mb-1">subtle enhance</div>
            <h2 className="font-serif text-2xl">Beautify (preview before saving)</h2>
          </div>
          <button onClick={onClose} data-testid="enhance-close" className="p-1" style={{ color: "var(--text-muted)" }}>
            <X className="h-5 w-5" />
          </button>
        </div>

        <p className="text-xs mb-6" style={{ color: "var(--text-secondary)" }}>
          We use an identity-preserving model. It cleans skin, sharpens, and gently corrects symmetry up to your
          chosen strength. It will never change your eye color, jaw shape, skin tone, or weight.
        </p>

        <div className="grid sm:grid-cols-2 gap-6 mb-6">
          <div>
            <div className="overline mb-2">ORIGINAL</div>
            <img
              src={state.originalUrl}
              alt="original"
              className="w-full aspect-square object-cover rounded-sm"
              style={{ border: "1px solid var(--border-default)" }}
            />
          </div>
          <div>
            <div className="overline mb-2">ENHANCED</div>
            {state.previewUrl ? (
              <img
                src={state.previewUrl}
                alt="enhanced preview"
                className="w-full aspect-square object-cover rounded-sm"
                style={{ border: "1px solid var(--accent)" }}
                data-testid="enhance-preview-image"
              />
            ) : (
              <div
                className="w-full aspect-square rounded-sm flex items-center justify-center"
                style={{ border: "1px dashed var(--border-default)", color: "var(--text-muted)" }}
              >
                <Sparkles className="h-8 w-8" />
              </div>
            )}
          </div>
        </div>

        <div className="mb-6">
          <div className="flex justify-between text-xs mb-2" style={{ color: "var(--text-muted)" }}>
            <span>STRENGTH</span>
            <span>{state.strength}%</span>
          </div>
          <input
            type="range"
            min="0"
            max="85"
            step="5"
            value={state.strength}
            onChange={(e) => setStrength(parseInt(e.target.value, 10))}
            data-testid="enhance-strength"
            className="w-full"
            style={{ accentColor: "var(--accent)" }}
          />
        </div>

        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={onRun}
            data-testid="enhance-run"
            className="px-5 py-2 text-sm rounded-sm"
            style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
          >
            {state.previewUrl ? "Re-run at this strength" : "Generate preview"}
          </button>
          <button
            type="button"
            onClick={onCommit}
            data-testid="enhance-commit"
            disabled={!state.previewUrl}
            className="px-5 py-2 text-sm rounded-sm"
            style={{
              background: state.previewUrl ? "var(--ok)" : "transparent",
              color: state.previewUrl ? "var(--text-inverse)" : "var(--text-muted)",
              border: `1px solid ${state.previewUrl ? "var(--ok)" : "var(--border-default)"}`,
            }}
          >
            Use this as my twin
          </button>
        </div>
      </div>
    </div>
  );
}
