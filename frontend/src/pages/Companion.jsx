import { useEffect, useState } from "react";
import { Ban, Bell, CheckCircle2, Clipboard, Copy, Cpu, Download, Eye, Globe, Keyboard, Loader2, MessageCircle, Monitor, MonitorSpeaker, Power, Search, Terminal, Trash2, Volume2 } from "lucide-react";
import { api, API_BASE } from "../lib/api";

const KIND_ICONS = {
  open_url: Globe, open_app: Monitor, say: MessageCircle, set_volume: Volume2,
  media_key: Volume2, power: Power, notify: Bell, type_text: Keyboard,
  clipboard_get: Clipboard, clipboard_set: Clipboard, system_status: Cpu,
  find_file: Search, screenshot: Eye, shell: Terminal,
  pull_model: Download, list_models: Cpu, llm_chat: Cpu,
};

const STATUS_META = {
  done: { label: "done", color: "var(--accent)" },
  error: { label: "failed", color: "var(--danger)" },
  cancelled: { label: "cancelled", color: "var(--text-muted)" },
  queued: { label: "queued", color: "var(--text-muted)" },
  dispatched: { label: "running", color: "var(--accent)" },
};

function timeAgo(iso) {
  if (!iso) return "";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export default function Companion() {
  const [devices, setDevices] = useState([]);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("My PC");
  const [issued, setIssued] = useState(null); // { device_id, device_token, name } shown ONCE
  const [activity, setActivity] = useState([]);
  const [cmdDraft, setCmdDraft] = useState({ kind: "shell", text: "" });
  const [busy, setBusy] = useState(false);

  const loadAll = async () => {
    const [d, a] = await Promise.all([
      api.get("/companion/devices"),
      api.get("/companion/activity"),
    ]);
    setDevices(d.data);
    setActivity(a.data.items || []);
  };
  useEffect(() => {
    loadAll();
    const t = setInterval(loadAll, 5000);
    return () => clearInterval(t);
  }, []);

  const createDevice = async () => {
    setCreating(true);
    try {
      const { data } = await api.post("/companion/register", { name: newName });
      setIssued(data);
      setNewName("My PC");
      loadAll();
    } finally {
      setCreating(false);
    }
  };

  const downloadScript = () => {
    if (!issued) return;
    const url = `${API_BASE}/companion/script?token=${encodeURIComponent(issued.device_token)}`;
    // open in new tab — cookie auth is sent automatically
    window.open(url, "_blank");
  };

  const downloadWindows = () => {
    if (!issued) return;
    const url = `${API_BASE}/companion/windows-package?token=${encodeURIComponent(issued.device_token)}`;
    window.open(url, "_blank");
  };

  const downloadEasyInstaller = () => {
    if (!issued) return;
    const url = `${API_BASE}/companion/easy-installer?token=${encodeURIComponent(issued.device_token)}`;
    window.open(url, "_blank");
  };

  const downloadDesktopApp = () => {
    if (!issued) return;
    const url = `${API_BASE}/companion/desktop-package?token=${encodeURIComponent(issued.device_token)}`;
    window.open(url, "_blank");
  };

  const revoke = async (id) => {
    if (!window.confirm("Revoke this device?")) return;
    await api.delete(`/companion/devices/${id}`);
    loadAll();
  };

  const queueCommand = async () => {
    if (!cmdDraft.text.trim()) return;
    setBusy(true);
    try {
      let payload = {};
      if (cmdDraft.kind === "shell") payload = { command: cmdDraft.text };
      else if (cmdDraft.kind === "open_url") payload = { url: cmdDraft.text };
      else if (cmdDraft.kind === "open_app") payload = { name: cmdDraft.text };
      else if (cmdDraft.kind === "say") payload = { text: cmdDraft.text };
      await api.post("/companion/queue-command", { kind: cmdDraft.kind, payload });
      setCmdDraft({ ...cmdDraft, text: "" });
      loadAll();
    } finally {
      setBusy(false);
    }
  };

  const cancelCmd = async (cmdId) => {
    // optimistic
    setActivity((prev) => prev.map((it) => (it.cmd_id === cmdId ? { ...it, status: "cancelled", cancellable: false } : it)));
    try {
      await api.post(`/companion/activity/${cmdId}/cancel`);
    } catch (_) {
      /* refresh will correct state */
    }
    loadAll();
  };

  return (
    <div className="px-4 sm:px-8 lg:px-16 py-12 max-w-5xl" data-testid="companion-root">
      <header className="mb-10">
        <div className="overline mb-3">the local companion</div>
        <h1 className="font-serif text-4xl lg:text-5xl font-light tracking-tight">
          Your hands on the machine.
        </h1>
        <p className="mt-3 text-base max-w-2xl" style={{ color: "var(--text-secondary)" }}>
          A small Python program that runs on your 5090 PC. It listens for your push-to-talk, talks to your Twin in the cloud, and quietly carries out the things you ask it to do.
        </p>
      </header>

      {/* Setup */}
      <section className="surface p-7 mb-10">
        <div className="overline mb-3">setup — two steps</div>
        <ol className="space-y-3 text-sm leading-relaxed mb-6" style={{ color: "var(--text-secondary)" }}>
          <li>1. Name this device, then click <b style={{ color: "var(--text-primary)" }}>Issue token</b>.</li>
          <li>2. On your PC, <b style={{ color: "var(--text-primary)" }}>download the Easy install <code className="font-mono" style={{ color: "var(--accent)" }}>.bat</code> and double-click it</b>. It installs Python silently (if missing), drops the companion in <code className="font-mono">%LOCALAPPDATA%\Heirloom</code>, runs it hidden in the tray, and auto-starts on every sign-in. That&apos;s it.</li>
        </ol>
        <p className="text-xs mb-6" style={{ color: "var(--text-muted)" }}>
          Works on Windows 10 (≥ 1809) and Windows 11. No terminal, no pip, no Python knowledge needed.
          Prefer the manual route? The <b>Windows package (.zip)</b> ships the same script as separate files
          you can inspect and run yourself.
        </p>

        <div className="flex gap-3">
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Device name (e.g. Studio PC)"
            data-testid="companion-name"
            className="flex-1 px-3 py-2 text-sm rounded-sm"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
          />
          <button
            onClick={createDevice}
            disabled={creating || !newName.trim()}
            data-testid="companion-register"
            className="inline-flex items-center gap-2 px-5 py-2 text-sm rounded-sm disabled:opacity-50"
            style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
          >
            {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Power className="h-4 w-4" />}
            Issue token
          </button>
        </div>

        {issued && (
          <div className="mt-6 p-5 rounded-sm" style={{ border: "1px dashed var(--accent)", background: "var(--accent-muted)" }}>
            <div className="flex items-center gap-2 mb-3">
              <CheckCircle2 className="h-4 w-4" style={{ color: "var(--accent)" }} />
              <div className="overline">token issued — copy or download now</div>
            </div>
            <div className="font-mono text-xs break-all mb-3" data-testid="issued-token" style={{ color: "var(--text-primary)" }}>
              {issued.device_token}
            </div>
            <div className="flex gap-3 flex-wrap">
              <button
                onClick={downloadDesktopApp}
                data-testid="download-desktop-app"
                className="inline-flex items-center gap-2 px-4 py-2 text-xs rounded-sm"
                style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
              >
                <Download className="h-3.5 w-3.5" /> Heirloom Desktop (full app)
              </button>
              <button
                onClick={downloadEasyInstaller}
                data-testid="download-easy-installer"
                className="inline-flex items-center gap-2 px-4 py-2 text-xs rounded-sm"
                style={{ border: "1px solid var(--accent)", color: "var(--text-primary)" }}
              >
                <Download className="h-3.5 w-3.5" /> Background companion (.bat)
              </button>
              <button
                onClick={downloadWindows}
                data-testid="download-windows"
                className="inline-flex items-center gap-2 px-4 py-2 text-xs rounded-sm"
                style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
              >
                <Download className="h-3.5 w-3.5" /> Companion .zip
              </button>
              <button
                onClick={downloadScript}
                data-testid="download-script"
                className="inline-flex items-center gap-2 px-4 py-2 text-xs rounded-sm"
                style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
              >
                <Download className="h-3.5 w-3.5" /> .py only (Mac/Linux)
              </button>
              <button
                onClick={() => {
                  navigator.clipboard.writeText(issued.device_token);
                }}
                className="inline-flex items-center gap-2 px-4 py-2 text-xs rounded-sm"
                style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
                data-testid="copy-token"
              >
                <Copy className="h-3.5 w-3.5" /> Copy token
              </button>
            </div>
            <p className="text-xs mt-4 leading-relaxed" style={{ color: "var(--text-muted)" }}>
              <b style={{ color: "var(--accent)" }}>Heirloom Desktop</b> is the full Windows app — a resizable
              window with your twin&apos;s talking-head avatar, full chat thread, push-to-talk, quick-capture journal,
              and a pop-out avatar mode for OBS streaming. The background companion <code>.bat</code> is the lightweight
              option — runs hidden in the tray, listens for Ctrl+Space, no GUI. Both share the same token.</p>
          </div>
        )}
      </section>

      {/* Devices */}
      <section className="mb-12">
        <div className="overline mb-4">your devices</div>
        {devices.length === 0 ? (
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
            None yet.
          </p>
        ) : (
          <div className="space-y-3">
            {devices.map((d) => (
              <div key={d.device_id} className="surface p-5 flex justify-between items-center gap-3" data-testid={`device-${d.device_id}`}>
                <div className="flex items-center gap-4">
                  <MonitorSpeaker className="h-5 w-5" style={{ color: "var(--accent)" }} />
                  <div>
                    <div className="font-serif text-lg">{d.name}</div>
                    <div className="font-mono text-xs" style={{ color: "var(--text-muted)" }}>
                      {d.revoked ? "revoked" : d.last_seen ? `seen ${new Date(d.last_seen).toLocaleString()}` : "never connected"}
                    </div>
                  </div>
                </div>
                {!d.revoked && (
                  <button onClick={() => revoke(d.device_id)} data-testid={`revoke-${d.device_id}`} className="p-2">
                    <Trash2 className="h-4 w-4" style={{ color: "var(--text-muted)" }} />
                  </button>
                )}
              </div>
            ))}
            <p className="text-xs mt-3" style={{ color: "var(--text-muted)" }}>
              Lost a download? Tokens can't be retrieved after they're issued — revoke the device above and click <b>Issue token</b> again to get a fresh package.
            </p>
          </div>
        )}
      </section>

      {/* Queue command */}
      <section className="surface p-7 mb-10">
        <div className="overline mb-4">send a command</div>
        <div className="flex gap-3 mb-3 flex-wrap">
          <select
            value={cmdDraft.kind}
            onChange={(e) => setCmdDraft({ ...cmdDraft, kind: e.target.value, text: "" })}
            data-testid="cmd-kind"
            className="px-3 py-2 text-sm rounded-sm"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
          >
            <option value="shell">shell command</option>
            <option value="open_url">open URL</option>
            <option value="open_app">open app</option>
            <option value="say">say (TTS on PC)</option>
          </select>
          <input
            value={cmdDraft.text}
            onChange={(e) => setCmdDraft({ ...cmdDraft, text: e.target.value })}
            onKeyDown={(e) => e.key === "Enter" && queueCommand()}
            placeholder={
              cmdDraft.kind === "shell"
                ? "echo hello world"
                : cmdDraft.kind === "open_url"
                ? "https://news.ycombinator.com"
                : cmdDraft.kind === "open_app"
                ? "Spotify"
                : "Welcome home"
            }
            data-testid="cmd-text"
            className="flex-1 px-3 py-2 text-sm rounded-sm font-mono"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
          />
          <button
            onClick={queueCommand}
            disabled={busy || !cmdDraft.text.trim()}
            data-testid="cmd-queue"
            className="px-5 py-2 text-sm rounded-sm disabled:opacity-50"
            style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
          >
            Queue
          </button>
        </div>
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          Commands are queued and picked up by the companion on its next poll (every 3s).
        </p>
      </section>

      {/* Activity log — what your twin did on this machine */}
      <section data-testid="activity-log">
        <div className="flex items-baseline justify-between mb-4">
          <div className="overline">activity — what your twin did</div>
          <div className="text-xs" style={{ color: "var(--text-muted)" }}>auto-refreshes</div>
        </div>
        {activity.length === 0 ? (
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
            Nothing yet. When your twin opens an app, checks your screen, or runs a command, it shows up here.
          </p>
        ) : (
          <div className="space-y-2">
            {activity.map((it) => {
              const Icon = KIND_ICONS[it.kind] || Terminal;
              const meta = STATUS_META[it.status] || STATUS_META.queued;
              return (
                <div
                  key={it.cmd_id}
                  className="surface p-4 flex items-center gap-4"
                  data-testid={`activity-${it.cmd_id}`}
                >
                  <div
                    className="h-9 w-9 rounded-sm flex items-center justify-center shrink-0"
                    style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
                  >
                    <Icon className="h-4 w-4" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm" style={{ color: "var(--text-primary)" }}>
                      {it.label}
                      {it.summary && (
                        <span style={{ color: "var(--text-muted)" }}> · {it.summary}</span>
                      )}
                    </div>
                    <div className="text-xs mt-0.5 flex items-center gap-2" style={{ color: "var(--text-muted)" }}>
                      <span style={{ color: meta.color }}>{meta.label}</span>
                      <span>·</span>
                      <span>{timeAgo(it.completed_at || it.created_at)}</span>
                      {it.result_snippet && (
                        <span className="truncate" style={{ color: "var(--danger)" }}>· {it.result_snippet}</span>
                      )}
                    </div>
                  </div>
                  {it.cancellable && (
                    <button
                      type="button"
                      onClick={() => cancelCmd(it.cmd_id)}
                      data-testid={`activity-cancel-${it.cmd_id}`}
                      title="Cancel this action"
                      className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-sm shrink-0 transition-colors hover:border-[var(--danger)]"
                      style={{ border: "1px solid var(--border-default)", color: "var(--danger)" }}
                    >
                      <Ban className="h-3.5 w-3.5" /> Stop
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
