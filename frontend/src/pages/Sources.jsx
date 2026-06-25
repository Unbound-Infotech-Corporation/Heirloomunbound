import { useEffect, useRef, useState } from "react";
import { Cloud, FolderOpen, HardDrive, Inbox, Loader2, Plus, RefreshCw, Trash2, Upload } from "lucide-react";
import { api, API_BASE } from "../lib/api";

const KINDS = [
  {
    key: "local_folder",
    label: "Local folder",
    icon: FolderOpen,
    desc: "Point at any folder on your PC — your companion will sync it.",
    needs: "path",
  },
  {
    key: "gmail_takeout",
    label: "Gmail (Takeout)",
    icon: Inbox,
    desc: "Upload a Google Takeout .mbox file. Best signal of your voice.",
    needs: "upload",
  },
  {
    key: "drive_takeout",
    label: "Google Drive",
    icon: Cloud,
    desc: "Download a folder as .zip from Drive, then upload it here.",
    needs: "upload",
  },
  {
    key: "generic_upload",
    label: "Any text / docs",
    icon: HardDrive,
    desc: "Drop in any .txt / .md / .json / .zip of writing you've done.",
    needs: "upload",
  },
];

export default function Sources() {
  const [sources, setSources] = useState([]);
  const [showNew, setShowNew] = useState(false);
  const [draft, setDraft] = useState({ kind: "local_folder", label: "", path: "" });
  const [uploadingFor, setUploadingFor] = useState(null);
  const [uploadResult, setUploadResult] = useState({});

  const load = () => api.get("/sources").then(({ data }) => setSources(data));
  useEffect(() => {
    load();
  }, []);

  const submit = async () => {
    const meta = KINDS.find((k) => k.key === draft.kind);
    if (!meta) return;
    const config = draft.kind === "local_folder" ? { path: draft.path } : {};
    if (draft.kind === "local_folder" && !draft.path.trim()) {
      return alert("Please enter a folder path.");
    }
    await api.post("/sources", { kind: draft.kind, label: draft.label || meta.label, config });
    setDraft({ kind: "local_folder", label: "", path: "" });
    setShowNew(false);
    load();
  };

  const triggerLocalSync = async (src) => {
    try {
      await api.post(`/sources/${src.source_id}/sync-local`);
      load();
      setUploadResult((r) => ({ ...r, [src.source_id]: { ok: true, note: "Queued — your companion will pick this up within a few seconds." } }));
    } catch (e) {
      setUploadResult((r) => ({ ...r, [src.source_id]: { ok: false, note: e.response?.data?.detail || e.message } }));
    }
  };

  const upload = async (src, file) => {
    setUploadingFor(src.source_id);
    const fd = new FormData();
    fd.append("file", file);
    try {
      const res = await fetch(`${API_BASE}/sources/${src.source_id}/upload`, {
        method: "POST",
        credentials: "include",
        body: fd,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Upload failed");
      setUploadResult((r) => ({ ...r, [src.source_id]: { ok: true, note: `${data.extracted} memories extracted.` } }));
      load();
    } catch (e) {
      setUploadResult((r) => ({ ...r, [src.source_id]: { ok: false, note: e.message } }));
    } finally {
      setUploadingFor(null);
    }
  };

  const remove = async (id) => {
    if (!window.confirm("Remove this source? (Imported entries stay in your archive.)")) return;
    await api.delete(`/sources/${id}`);
    load();
  };

  return (
    <div className="px-10 lg:px-16 py-12 max-w-5xl" data-testid="sources-root">
      <header className="mb-10 flex justify-between items-end flex-wrap gap-6">
        <div>
          <div className="overline mb-3">the wider self</div>
          <h1 className="font-serif text-4xl lg:text-5xl font-light tracking-tight">
            Bring in your scattered selves.
          </h1>
          <p className="mt-3 text-base max-w-2xl" style={{ color: "var(--text-secondary)" }}>
            Local journals on your PC, years of sent email, blog posts, doc archives — connect any of it and your Twin draws from all of it.
          </p>
        </div>
        <button
          onClick={() => setShowNew((s) => !s)}
          data-testid="new-source-toggle"
          className="inline-flex items-center gap-2 px-5 py-3 text-sm rounded-sm"
          style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
        >
          <Plus className="h-4 w-4" /> Add source
        </button>
      </header>

      {showNew && (
        <div className="surface p-6 mb-10 space-y-5">
          <div>
            <div className="overline mb-3">choose a kind</div>
            <div className="grid sm:grid-cols-2 gap-3">
              {KINDS.map((k) => {
                const Icon = k.icon;
                return (
                  <button
                    key={k.key}
                    onClick={() => setDraft({ ...draft, kind: k.key })}
                    data-testid={`source-kind-${k.key}`}
                    className="text-left px-4 py-4 rounded-sm transition-colors"
                    style={{
                      border: draft.kind === k.key ? "1px solid var(--accent)" : "1px solid var(--border-default)",
                      background: draft.kind === k.key ? "var(--accent-muted)" : "transparent",
                    }}
                  >
                    <Icon className="h-4 w-4 mb-2" style={{ color: "var(--accent)" }} />
                    <div className="font-serif text-base mb-1" style={{ color: "var(--text-primary)" }}>{k.label}</div>
                    <div className="text-xs" style={{ color: "var(--text-secondary)" }}>{k.desc}</div>
                  </button>
                );
              })}
            </div>
          </div>

          <input
            value={draft.label}
            onChange={(e) => setDraft({ ...draft, label: e.target.value })}
            placeholder="Label (e.g. 'My journals folder')"
            data-testid="source-label"
            className="w-full px-3 py-2 text-sm rounded-sm"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
          />
          {draft.kind === "local_folder" && (
            <input
              value={draft.path}
              onChange={(e) => setDraft({ ...draft, path: e.target.value })}
              placeholder="Absolute folder path (e.g. C:\\Users\\you\\Documents\\Journal)"
              data-testid="source-path"
              className="w-full px-3 py-2 text-sm font-mono rounded-sm"
              style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
            />
          )}

          <div className="flex justify-end gap-3">
            <button
              onClick={() => setShowNew(false)}
              className="px-4 py-2 text-sm rounded-sm"
              style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
            >
              Cancel
            </button>
            <button
              onClick={submit}
              data-testid="source-submit"
              className="px-4 py-2 text-sm rounded-sm"
              style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
            >
              Add source
            </button>
          </div>
        </div>
      )}

      {sources.length === 0 ? (
        <div className="surface p-12 text-center" data-testid="sources-empty">
          <div className="overline mb-3">no sources yet</div>
          <p className="font-serif text-2xl" style={{ color: "var(--text-secondary)" }}>
            Connect your first source above.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {sources.map((s) => {
            const meta = KINDS.find((k) => k.key === s.kind) || {};
            const Icon = meta.icon || HardDrive;
            const result = uploadResult[s.source_id];
            const uploading = uploadingFor === s.source_id;
            return (
              <div key={s.source_id} className="surface p-6" data-testid={`source-${s.source_id}`}>
                <div className="flex justify-between items-start gap-4">
                  <div className="flex items-start gap-3 min-w-0 flex-1">
                    <Icon className="h-5 w-5 mt-1 shrink-0" style={{ color: "var(--accent)" }} />
                    <div className="min-w-0 flex-1">
                      <div className="overline mb-1">{meta.label || s.kind}</div>
                      <div className="font-serif text-xl mb-1">{s.label}</div>
                      {s.config?.path && (
                        <div className="font-mono text-xs mb-2 break-all" style={{ color: "var(--text-muted)" }}>
                          {s.config.path}
                        </div>
                      )}
                      <div className="flex gap-4 text-xs font-mono" style={{ color: "var(--text-muted)" }}>
                        <span>{s.imported_count} imported</span>
                        {s.last_synced_at && <span>last sync {new Date(s.last_synced_at).toLocaleString()}</span>}
                        <span style={{ color: s.status === "syncing" ? "var(--accent)" : "var(--text-muted)" }}>{s.status}</span>
                      </div>
                    </div>
                  </div>
                  <div className="flex gap-2 shrink-0">
                    {s.kind === "local_folder" ? (
                      <button
                        onClick={() => triggerLocalSync(s)}
                        data-testid={`sync-${s.source_id}`}
                        className="inline-flex items-center gap-2 px-3 py-2 text-xs rounded-sm"
                        style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
                      >
                        <RefreshCw className="h-3.5 w-3.5" /> Sync now
                      </button>
                    ) : (
                      <label
                        className="inline-flex items-center gap-2 px-3 py-2 text-xs rounded-sm cursor-pointer"
                        style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
                      >
                        {uploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
                        {uploading ? "Reading…" : "Upload"}
                        <input
                          type="file"
                          accept=".mbox,.zip,.txt,.md,.json,.html,.csv"
                          onChange={(e) => e.target.files?.[0] && upload(s, e.target.files[0])}
                          className="hidden"
                          data-testid={`upload-${s.source_id}`}
                        />
                      </label>
                    )}
                    <button
                      onClick={() => remove(s.source_id)}
                      data-testid={`delete-source-${s.source_id}`}
                      className="p-2"
                    >
                      <Trash2 className="h-4 w-4" style={{ color: "var(--text-muted)" }} />
                    </button>
                  </div>
                </div>
                {result && (
                  <div
                    className="mt-4 px-4 py-3 rounded-sm text-xs"
                    style={{
                      border: "1px solid var(--border-default)",
                      background: "var(--bg-base)",
                      color: result.ok ? "var(--accent)" : "var(--danger)",
                    }}
                  >
                    {result.note}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <section
        className="surface p-7 mt-12 text-sm leading-relaxed"
        style={{ color: "var(--text-secondary)" }}
      >
        <div className="overline mb-3">how to grab your Gmail or Drive data</div>
        <ol className="space-y-2 list-decimal list-inside">
          <li>Visit <span className="font-mono" style={{ color: "var(--accent)" }}>takeout.google.com</span> while signed in to Google.</li>
          <li>For Gmail: deselect everything, then check just <em>Mail</em>. Click "All Mail data included" and check only your <em>Sent</em> label. (Sent items are the truest signal of your voice.)</li>
          <li>For Drive: check <em>Drive</em>, click "All Drive data included" and pick a folder if you want.</li>
          <li>Export, wait for the email link, download the .zip / .mbox.</li>
          <li>Come back here and Upload it to the matching source above.</li>
        </ol>
      </section>
    </div>
  );
}
