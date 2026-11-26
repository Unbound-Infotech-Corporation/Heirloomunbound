import { useEffect, useState } from "react";
import { Loader2, Link2, Unlink, FolderPlus, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

// Setup for the opt-in local skills: link Google/Microsoft (read and draft only),
// pick folders to index, and see what was drafted. Shown under an enabled ability card.
export default function SkillSetup({ abilityId }) {
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState("");
  const [folder, setFolder] = useState("");

  const load = async () => {
    try {
      const r = await api.get("/local-skills/status");
      setStatus(r.data);
    } catch (e) {
      setStatus({ error: e.response?.data?.detail || "Couldn't load skill setup." });
    }
  };
  useEffect(() => {
    load();
  }, []);

  if (!status) return <Loader2 className="h-4 w-4 animate-spin mt-3" style={{ color: "var(--text-muted)" }} />;
  if (status.error) return <div className="text-xs mt-3" style={{ color: "var(--text-muted)" }}>{status.error}</div>;

  const run = async (key, fn) => {
    setBusy(key);
    try {
      await fn();
      await load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "That didn't work.");
    } finally {
      setBusy("");
    }
  };

  const link = (provider) =>
    run(provider, async () => {
      const r = await api.post(`/local-skills/oauth/${provider}/start`);
      window.location.assign(r.data.url);
    });
  const unlink = (provider) => run(provider, () => api.delete(`/local-skills/oauth/${provider}`));

  const btn = {
    border: "1px solid var(--border-default)",
    color: "var(--text-secondary)",
  };

  if (abilityId === "calendar" || abilityId === "email") {
    return (
      <div className="mt-4 space-y-2" data-testid={`skill-setup-${abilityId}`}>
        {Object.entries(status.providers || {}).map(([id, p]) => (
          <div key={id} className="flex items-center justify-between gap-2 text-xs">
            <span style={{ color: "var(--text-secondary)" }}>
              {p.label}
              {p.connected ? " · linked" : p.configured ? "" : " · not set up on this box"}
            </span>
            {p.connected ? (
              <button type="button" className="px-2 py-1 rounded-sm inline-flex items-center gap-1" style={btn}
                disabled={busy === id} onClick={() => unlink(id)} data-testid={`skill-unlink-${id}`}>
                <Unlink className="h-3 w-3" /> Unlink
              </button>
            ) : (
              <button type="button" className="px-2 py-1 rounded-sm inline-flex items-center gap-1 disabled:opacity-50" style={btn}
                disabled={!p.configured || busy === id} onClick={() => link(id)} data-testid={`skill-link-${id}`}>
                {busy === id ? <Loader2 className="h-3 w-3 animate-spin" /> : <Link2 className="h-3 w-3" />} Link
              </button>
            )}
          </div>
        ))}
        <div className="text-xs" style={{ color: "var(--text-muted)" }}>
          Read and draft only. Heirloom never sends mail or writes your calendar.
          {abilityId === "calendar" && status.calendar_drafts ? ` ${status.calendar_drafts} event draft(s) waiting.` : ""}
        </div>
      </div>
    );
  }

  if (abilityId === "files") {
    const files = status.files || { roots: [], files: 0 };
    return (
      <div className="mt-4 space-y-2" data-testid="skill-setup-files">
        {files.roots.map((root) => (
          <div key={root} className="flex items-center justify-between gap-2 text-xs">
            <span className="truncate" style={{ color: "var(--text-secondary)" }} title={root}>{root}</span>
            <button type="button" className="p-1" style={{ color: "var(--text-muted)" }} aria-label={`Stop indexing ${root}`}
              onClick={() => run("rm" + root, () => api.post("/local-skills/files/roots/remove", { path: root }))}>
              <Trash2 className="h-3 w-3" />
            </button>
          </div>
        ))}
        <div className="flex gap-2">
          <input
            value={folder}
            onChange={(e) => setFolder(e.target.value)}
            placeholder="Folder path on this machine"
            className="flex-1 text-xs px-2 py-1 rounded-sm bg-transparent"
            style={{ border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
            data-testid="skill-files-input"
          />
          <button type="button" className="px-2 py-1 rounded-sm inline-flex items-center gap-1 text-xs" style={btn}
            disabled={!folder.trim() || busy === "add"}
            onClick={() => run("add", async () => {
              const r = await api.post("/local-skills/files/roots", { path: folder.trim() });
              toast.success(`Indexed ${r.data.files} file(s).`);
              setFolder("");
            })}
            data-testid="skill-files-add">
            {busy === "add" ? <Loader2 className="h-3 w-3 animate-spin" /> : <FolderPlus className="h-3 w-3" />} Add
          </button>
          <button type="button" className="px-2 py-1 rounded-sm text-xs" style={btn} aria-label="Re-index"
            disabled={busy === "re"} onClick={() => run("re", () => api.post("/local-skills/files/reindex"))}>
            <RefreshCw className={`h-3 w-3 ${busy === "re" ? "animate-spin" : ""}`} />
          </button>
        </div>
        <div className="text-xs" style={{ color: "var(--text-muted)" }}>
          {files.files} file(s) indexed. The index stays on this machine; keys and password files are skipped.
        </div>
      </div>
    );
  }

  if (abilityId === "web") {
    return (
      <div className="mt-3 text-xs" style={{ color: "var(--text-muted)" }}>
        Owner only. Private names and memories are removed from a search before it leaves the box
        ({status.web_search === "searxng" ? "your own SearXNG" : "DuckDuckGo"}).
      </div>
    );
  }
  return null;
}
