import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Camera, Check, Download, ExternalLink, Eye, Loader2, Monitor, Sparkles, Upload, Video, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { usePageMeta } from "@/lib/usePageMeta";

const ANGLES = [
  { key: "front", label: "Front", hint: "Straight on, eyes level. This is the face LivePortrait and D-ID drive." },
  { key: "three_quarter", label: "Three-quarter", hint: "Face turned ~45°. Helps InstantID lock your bone structure." },
  { key: "left", label: "Left profile", hint: "Side view of the left half of your face." },
  { key: "right", label: "Right profile", hint: "Side view of the right half. Symmetry helps." },
  { key: "full", label: "Full body", hint: "Standing, head to toe, even light. Needed for a body that moves like yours." },
];

export default function AvatarStudio() {
  const nav = useNavigate();
  usePageMeta({
    title: "Avatar Studio · Heirloom",
    description: "Upload your face, give your measurements, and run a local Pinokio/ComfyUI twin that looks back at you.",
  });

  const [data, setData] = useState(null);
  const [uploading, setUploading] = useState(null); // angle string while in flight
  const [enhanceState, setEnhanceState] = useState({ open: false, strength: 35, previewUrl: null, previewId: null, originalUrl: null, originalId: null });
  const [body, setBody] = useState({ height_cm: "", weight_kg: "", build: "average", presentation: "unspecified", notes: "" });
  const [engine, setEngine] = useState("auto");
  const [busy, setBusy] = useState("");
  const [jobHint, setJobHint] = useState("");

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
      toast.success("Body sheet saved — InstantID will use this.");
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
      setJobHint(r.data.hint || r.data.howto || "Queued on your home PC.");
      toast.success(kind === "look" ? "Opening LivePortrait on your PC…" : "Queued on your home PC.");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't start that on your PC.");
    } finally {
      setBusy("");
    }
  };

  const installPinokio = async (url) => {
    if (!url) return;
    setBusy(`pinokio:${url}`);
    try {
      await api.post("/companion/queue-command", { kind: "open_url", payload: { url } });
      toast.success("Opening Pinokio on your home computer.");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't reach your PC. Open the Heirloom desktop app.");
    } finally {
      setBusy("");
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
        <div className="overline mb-3">your twin&apos;s body</div>
        <h1 className="font-serif text-4xl mb-3">Avatar Studio</h1>
        <p className="text-sm mb-6 max-w-2xl" style={{ color: "var(--text-secondary)" }}>
          Upload a few photos of <em>your</em> face, add height and build, then run free local models on the home PC.
          LivePortrait looks back at you. EchoMimic / Sonic speak in the cloned voice. InstantID builds the full-body still those animators start from.
          D-ID stays as a paid cloud fallback. This is your likeness, on your machine — don&apos;t upload anyone else.
        </p>
        {data.home && (
          <p className="text-xs mb-8" style={{ color: data.home.online ? "var(--ok, #7da06f)" : "var(--text-muted)" }} data-testid="avatar-home-status">
            <Monitor className="inline h-3.5 w-3.5 mr-1" />
            {data.home.connected
              ? (data.home.online ? `${data.home.name || "Home PC"} is awake — local jobs run there.` : `${data.home.name || "Home PC"} is paired but asleep. Open the desktop app.`)
              : "Pair the Heirloom desktop app first. Pinokio and ComfyUI cannot run in the cloud."}
          </p>
        )}

        {/* upload tiles */}
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-6 mb-12">
          {ANGLES.map((a) => (
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
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
            <label className="text-xs" style={{ color: "var(--text-muted)" }}>
              Height (cm)
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
              Build
              <select
                value={body.build}
                onChange={(e) => setBody((b) => ({ ...b, build: e.target.value }))}
                data-testid="avatar-build"
                className="mt-1 w-full px-3 py-2 text-sm rounded-sm"
                style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
              >
                {(data.catalog?.builds || ["slim", "average", "athletic", "heavy"]).map((b) => (
                  <option key={b} value={b}>{b}</option>
                ))}
              </select>
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
