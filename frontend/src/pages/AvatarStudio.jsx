import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Camera, Check, Sparkles, Upload, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { usePageMeta } from "@/lib/usePageMeta";

const ANGLES = [
  { key: "front", label: "Front", hint: "Straight on, eyes level with camera. The one your twin uses today." },
  { key: "left", label: "Left profile", hint: "Side view of the left half of your face. For future 3D avatar." },
  { key: "right", label: "Right profile", hint: "Side view of the right half. Symmetry helps." },
];

export default function AvatarStudio() {
  const nav = useNavigate();
  usePageMeta({
    title: "Avatar Studio · Heirloom",
    description: "Upload three angles of your face and tune your twin's likeness.",
  });

  const [data, setData] = useState(null);
  const [uploading, setUploading] = useState(null); // angle string while in flight
  const [enhanceState, setEnhanceState] = useState({ open: false, strength: 35, previewUrl: null, previewId: null, originalUrl: null, originalId: null });

  const load = async () => {
    try {
      const r = await api.get("/avatar-studio/me");
      setData(r.data);
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
      const r = await api.post("/avatar-studio/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
      if (r.data?.activated_as_twin) {
        toast.success("Front photo set as your twin's face — ready for live / OBS.");
      } else {
        toast.success(`${angle} uploaded.`);
      }
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
        <div className="overline mb-3">your twin&apos;s face</div>
        <h1 className="font-serif text-4xl mb-3">Avatar Studio</h1>
        <p className="text-sm mb-10 max-w-2xl" style={{ color: "var(--text-secondary)" }}>
          Drop a front-facing photo — it becomes your twin&apos;s face automatically for talking-head video,
          live stream, and OBS. Left/right angles are optional (saved for a future 3D upgrade). Optional
          Beautify cleans lighting without changing who you are.
        </p>
        {data.active_source_url ? (
          <div
            className="mb-8 p-4 rounded-sm flex flex-wrap items-center gap-4"
            style={{ border: "1px solid var(--border-default)", background: "var(--bg-surface)" }}
            data-testid="avatar-studio-active"
          >
            <img
              src={data.active_source_url}
              alt="Active twin face"
              className="w-16 h-16 rounded-sm object-cover"
              style={{ border: "1px solid var(--border-default)" }}
            />
            <div className="flex-1 min-w-[12rem]">
              <div className="overline mb-1" style={{ color: "var(--ok)" }}>active twin face</div>
              <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                This is what D-ID, live viewers, and OBS will show.
              </p>
            </div>
            <a
              href="/settings"
              className="text-xs underline"
              style={{ color: "var(--accent)" }}
            >
              Live broadcast setup →
            </a>
          </div>
        ) : null}

        {/* 3 upload tiles */}
        <div className="grid sm:grid-cols-3 gap-6 mb-10">
          {ANGLES.map((a) => (
            <UploadTile
              key={a.key}
              angle={a}
              img={data[a.key]}
              uploading={uploading === a.key}
              activeUrl={data.active_source_url}
              onUpload={(file) => handleUpload(a.key, file)}
              onUse={setActiveImage}
              onEnhance={openEnhance}
              falConfigured={data.fal_configured}
            />
          ))}
        </div>

        {/* Enhancement dialog */}
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
        className="aspect-square rounded-sm mb-3 overflow-hidden flex items-center justify-center cursor-pointer transition-colors"
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
