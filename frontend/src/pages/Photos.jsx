import { useEffect, useRef, useState } from "react";
import { Image as ImageIcon, Loader2, Sparkles, Trash2, Upload as UploadIcon, Wand2 } from "lucide-react";
import { toast } from "sonner";
import { api, API_BASE } from "../lib/api";

function PhotoCard({ p, onRemove, onRestored }) {
  const [src, setSrc] = useState(null);
  const [restoring, setRestoring] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  useEffect(() => {
    let cancelled = false;
    let createdUrl = null;
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/photos/${p.photo_id}/file`, { credentials: "include" });
        const blob = await res.blob();
        if (cancelled) return;
        createdUrl = URL.createObjectURL(blob);
        setSrc(createdUrl);
      } catch (e) {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
  }, [p.photo_id]);

  const startRestore = async (kind) => {
    setMenuOpen(false);
    setRestoring(true);
    try {
      const { data } = await api.post("/restoration/jobs", { photo_id: p.photo_id, kind });
      if (data.status === "blocked") {
        toast.error(data.reason || "Restoration blocked");
        setRestoring(false);
        return;
      }
      toast.success(`${kind[0].toUpperCase()+kind.slice(1)} queued — your desktop is on it`);
      // Poll every 4s until complete/failed
      const poll = async () => {
        try {
          const { data: job } = await api.get(`/restoration/jobs/${data.job_id}`);
          if (job.status === "complete") {
            toast.success("Restoration complete");
            setRestoring(false);
            onRestored && onRestored();
            return;
          }
          if (job.status === "failed") {
            toast.error(`Restoration failed: ${job.reason || "unknown"}`);
            setRestoring(false);
            return;
          }
          setTimeout(poll, 4000);
        } catch {
          setRestoring(false);
        }
      };
      setTimeout(poll, 4000);
    } catch (e) {
      toast.error("Couldn't queue restoration");
      setRestoring(false);
    }
  };

  return (
    <div className="surface overflow-hidden group relative" data-testid={`photo-${p.photo_id}`}>
      <div className="aspect-[4/3] relative" style={{ background: "var(--bg-base)" }}>
        {src ? (
          <img src={src} alt={p.caption} className="w-full h-full object-cover" />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center">
            <ImageIcon className="h-6 w-6" style={{ color: "var(--text-muted)" }} />
          </div>
        )}
        {p.is_restoration && (
          <div className="absolute top-2 left-2 px-2 py-0.5 rounded-full text-xs flex items-center gap-1"
               style={{ background: "rgba(212,163,115,0.16)", color: "var(--accent)" }}
               data-testid={`restored-badge-${p.photo_id}`}>
            <Sparkles className="h-3 w-3" /> {p.restoration_kind || "restored"}
          </div>
        )}
        <div className="absolute top-2 right-2 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          {!p.is_restoration && (
            <div className="relative">
              <button
                onClick={() => setMenuOpen((v) => !v)}
                disabled={restoring}
                data-testid={`restore-photo-${p.photo_id}`}
                className="p-1.5 rounded-sm flex items-center gap-1"
                style={{ background: "rgba(18,17,16,0.7)" }}
                title="Restore with local ComfyUI"
              >
                {restoring ? <Loader2 className="h-4 w-4 animate-spin" style={{ color: "var(--accent)" }} /> :
                             <Wand2 className="h-4 w-4" style={{ color: "var(--accent)" }} />}
              </button>
              {menuOpen && (
                <div className="absolute right-0 top-8 rounded-sm py-1 z-10 min-w-[160px]"
                     style={{ background: "var(--surface-elev)", border: "1px solid var(--border-default)" }}
                     data-testid={`restore-menu-${p.photo_id}`}>
                  {["restore", "colorize", "upscale"].map((k) => (
                    <button key={k}
                      onClick={() => startRestore(k)}
                      data-testid={`restore-${k}-${p.photo_id}`}
                      className="w-full text-left px-3 py-1.5 text-xs hover:bg-black/10 capitalize"
                      style={{ color: "var(--text-primary)" }}
                    >
                      {k}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          <button
            onClick={() => onRemove(p.photo_id)}
            data-testid={`delete-photo-${p.photo_id}`}
            className="p-1.5 rounded-sm"
            style={{ background: "rgba(18,17,16,0.7)" }}
          >
            <Trash2 className="h-4 w-4" style={{ color: "var(--text-primary)" }} />
          </button>
        </div>
      </div>
      <div className="p-4">
        <div className="font-serif text-base leading-snug mb-1" style={{ color: "var(--text-primary)" }}>
          {p.caption || "Untitled"}
        </div>
        <div className="font-mono text-xs" style={{ color: "var(--text-muted)" }}>
          {p.taken_at || new Date(p.created_at).toLocaleDateString()}
        </div>
      </div>
    </div>
  );
}

export default function Photos() {
  const [photos, setPhotos] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [pending, setPending] = useState(null); // {file, preview}
  const [caption, setCaption] = useState("");
  const [takenAt, setTakenAt] = useState("");
  const fileInputRef = useRef(null);

  const load = async () => {
    const { data } = await api.get("/photos");
    setPhotos(data);
  };
  useEffect(() => {
    load();
  }, []);

  const onPick = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setPending({ file: f, preview: URL.createObjectURL(f) });
    setCaption("");
    setTakenAt("");
  };

  const upload = async () => {
    if (!pending) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", pending.file);
      fd.append("caption", caption);
      fd.append("taken_at", takenAt);
      const res = await fetch(`${API_BASE}/photos/upload`, {
        method: "POST",
        credentials: "include",
        body: fd,
      });
      if (!res.ok) throw new Error(await res.text());
      URL.revokeObjectURL(pending.preview);
      setPending(null);
      setCaption("");
      setTakenAt("");
      if (fileInputRef.current) fileInputRef.current.value = "";
      load();
    } catch (e) {
      alert("Upload failed: " + e.message);
    } finally {
      setUploading(false);
    }
  };

  const remove = async (id) => {
    if (!window.confirm("Remove this photo?")) return;
    await api.delete(`/photos/${id}`);
    load();
  };

  return (
    <div className="px-4 sm:px-8 lg:px-16 py-12 max-w-6xl" data-testid="photos-root">
      <header className="mb-10">
        <div className="overline mb-3">the photographs</div>
        <h1 className="font-serif text-4xl lg:text-5xl font-light tracking-tight">A picture, then a story.</h1>
        <p className="mt-3 text-base max-w-xl" style={{ color: "var(--text-secondary)" }}>
          Upload an image and write the story behind it. The Twin reads the captions.
        </p>
      </header>

      <div className="surface p-6 mb-10">
        {!pending ? (
          <label
            className="block py-12 text-center cursor-pointer rounded-sm"
            style={{ border: "1px dashed var(--border-default)" }}
            data-testid="photo-dropzone"
          >
            <UploadIcon className="h-7 w-7 mx-auto mb-3" style={{ color: "var(--accent)" }} />
            <div className="font-serif text-xl mb-1">Choose a photograph</div>
            <div className="text-xs" style={{ color: "var(--text-muted)" }}>
              JPG · PNG · WebP · HEIC · up to 12MB
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={onPick}
              data-testid="photo-file-input"
            />
          </label>
        ) : (
          <div className="grid md:grid-cols-2 gap-6">
            <div className="aspect-[4/3] overflow-hidden rounded-sm" style={{ border: "1px solid var(--border-default)" }}>
              <img src={pending.preview} alt="preview" className="w-full h-full object-cover" />
            </div>
            <div className="space-y-4">
              <textarea
                value={caption}
                onChange={(e) => setCaption(e.target.value)}
                placeholder="Tell the story behind this photo…"
                rows={5}
                data-testid="photo-caption"
                className="w-full px-3 py-2 text-sm rounded-sm leading-relaxed"
                style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
              />
              <input
                value={takenAt}
                onChange={(e) => setTakenAt(e.target.value)}
                placeholder="When was this? (e.g. 'Summer 1987' or 2024-06-15)"
                data-testid="photo-taken"
                className="w-full px-3 py-2 text-sm rounded-sm"
                style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
              />
              <div className="flex gap-3 justify-end">
                <button
                  onClick={() => {
                    URL.revokeObjectURL(pending.preview);
                    setPending(null);
                  }}
                  className="px-4 py-2 text-sm rounded-sm"
                  style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
                >
                  Cancel
                </button>
                <button
                  onClick={upload}
                  disabled={uploading}
                  data-testid="photo-upload-submit"
                  className="inline-flex items-center gap-2 px-5 py-2 text-sm rounded-sm disabled:opacity-50"
                  style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
                >
                  {uploading && <Loader2 className="h-4 w-4 animate-spin" />}
                  {uploading ? "Saving…" : "Save photo"}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {photos.length === 0 ? (
        <div className="surface p-12 text-center" data-testid="photos-empty">
          <div className="overline mb-3">no photos yet</div>
          <p className="font-serif text-2xl" style={{ color: "var(--text-secondary)" }}>
            One image is worth a thousand entries.
          </p>
        </div>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {photos.map((p) => (
            <PhotoCard key={p.photo_id} p={p} onRemove={remove} onRestored={load} />
          ))}
        </div>
      )}
    </div>
  );
}
