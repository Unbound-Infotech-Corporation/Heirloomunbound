import { useEffect, useState } from "react";
import { CheckCircle2, Copy, Download, Loader2, MonitorSpeaker, Power, Trash2 } from "lucide-react";
import { api, API_BASE } from "../lib/api";

export default function Companion() {
  const [devices, setDevices] = useState([]);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("My PC");
  const [issued, setIssued] = useState(null); // { device_id, device_token, name } shown ONCE
  const [commands, setCommands] = useState([]);
  const [cmdDraft, setCmdDraft] = useState({ kind: "shell", text: "" });
  const [busy, setBusy] = useState(false);

  const loadAll = async () => {
    const [d, c] = await Promise.all([api.get("/companion/devices"), api.get("/companion/commands")]);
    setDevices(d.data);
    setCommands(c.data);
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

  return (
    <div className="px-10 lg:px-16 py-12 max-w-5xl" data-testid="companion-root">
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
                onClick={downloadEasyInstaller}
                data-testid="download-easy-installer"
                className="inline-flex items-center gap-2 px-4 py-2 text-xs rounded-sm"
                style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
              >
                <Download className="h-3.5 w-3.5" /> Easy install (Windows, 1 file)
              </button>
              <button
                onClick={downloadWindows}
                data-testid="download-windows"
                className="inline-flex items-center gap-2 px-4 py-2 text-xs rounded-sm"
                style={{ border: "1px solid var(--accent)", color: "var(--text-primary)" }}
              >
                <Download className="h-3.5 w-3.5" /> Windows package (.zip)
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
              <b style={{ color: "var(--accent)" }}>Easy install</b> downloads one tiny <code>.bat</code> file.
              Double-click it on the PC where you want Heirloom to live — it installs Python (silently, if missing),
              sets up the companion at <code>%LOCALAPPDATA%\Heirloom</code>, runs it hidden in the tray, and
              auto-starts on every Windows sign-in. No terminal, no pip, no Python knowledge. ~60 seconds.
            </p>
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

      {/* History */}
      <section>
        <div className="overline mb-4">command history</div>
        {commands.length === 0 ? (
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
            No commands sent yet.
          </p>
        ) : (
          <div className="space-y-3">
            {commands.map((c) => (
              <div key={c.cmd_id} className="surface p-4" data-testid={`cmd-${c.cmd_id}`}>
                <div className="flex justify-between items-baseline mb-1">
                  <div className="font-mono text-xs">
                    <span className="overline mr-2">{c.kind}</span>
                    <span style={{ color: "var(--text-muted)" }}>{c.cmd_id}</span>
                  </div>
                  <div
                    className="overline"
                    style={{
                      color:
                        c.status === "done"
                          ? "var(--accent)"
                          : c.status === "error"
                          ? "var(--danger)"
                          : "var(--text-muted)",
                    }}
                  >
                    {c.status}
                  </div>
                </div>
                <div className="text-sm font-mono break-all" style={{ color: "var(--text-secondary)" }}>
                  {JSON.stringify(c.payload)}
                </div>
                {c.result && (
                  <div
                    className="mt-2 text-xs font-mono p-2 rounded-sm"
                    style={{ background: "var(--bg-base)", color: "var(--text-secondary)" }}
                  >
                    {c.result.slice(0, 400)}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
