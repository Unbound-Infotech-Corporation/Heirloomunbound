import { useEffect, useState } from "react";
import { CheckCircle2, Loader2, Sparkles, Trash2, Upload } from "lucide-react";
import { api, API_BASE } from "../lib/api";
import { useAuth } from "../lib/auth";

export default function Settings() {
  const { user, logout } = useAuth();
  const [elSettings, setElSettings] = useState(null);
  const [voices, setVoices] = useState([]);
  const [voicesLoading, setVoicesLoading] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [voiceId, setVoiceId] = useState("");
  const [saving, setSaving] = useState(false);
  const [cloneOpen, setCloneOpen] = useState(false);
  const [cloneName, setCloneName] = useState("");
  const [cloneDesc, setCloneDesc] = useState("");
  const [cloneFiles, setCloneFiles] = useState([]);
  const [cloning, setCloning] = useState(false);

  const loadSettings = async () => {
    const { data } = await api.get("/voice-clone/settings");
    setElSettings(data);
    setVoiceId(data.voice_id || "");
  };
  const loadVoices = async () => {
    setVoicesLoading(true);
    try {
      const { data } = await api.get("/voice-clone/voices");
      setVoices(data.voices || []);
    } catch (e) {
      setVoices([]);
    } finally {
      setVoicesLoading(false);
    }
  };

  useEffect(() => {
    loadSettings().then(() => loadVoices());
  }, []);

  const saveKey = async () => {
    setSaving(true);
    try {
      await api.put("/voice-clone/settings", { api_key: apiKey });
      setApiKey("");
      await loadSettings();
      await loadVoices();
    } finally {
      setSaving(false);
    }
  };

  const saveVoice = async (id) => {
    setVoiceId(id);
    await api.put("/voice-clone/settings", { voice_id: id });
    await loadSettings();
  };

  const clearAll = async () => {
    if (!window.confirm("Clear ElevenLabs key and voice ID?")) return;
    await api.put("/voice-clone/settings", { clear: true });
    setVoices([]);
    await loadSettings();
  };

  const submitClone = async () => {
    if (!cloneName.trim() || cloneFiles.length === 0) return;
    setCloning(true);
    try {
      const fd = new FormData();
      fd.append("name", cloneName);
      fd.append("description", cloneDesc);
      for (const f of cloneFiles) fd.append("files", f);
      const res = await fetch(`${API_BASE}/voice-clone/clone`, {
        method: "POST",
        credentials: "include",
        body: fd,
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t);
      }
      const data = await res.json();
      setCloneOpen(false);
      setCloneName("");
      setCloneDesc("");
      setCloneFiles([]);
      await loadSettings();
      await loadVoices();
      alert(`Voice "${data.name}" created and set as your Twin voice.`);
    } catch (e) {
      alert("Clone failed: " + e.message);
    } finally {
      setCloning(false);
    }
  };

  return (
    <div className="px-10 lg:px-16 py-12 max-w-3xl" data-testid="settings-root">
      <header className="mb-10">
        <div className="overline mb-3">settings</div>
        <h1 className="font-serif text-4xl lg:text-5xl font-light tracking-tight">Your archive.</h1>
      </header>

      <section className="surface p-7 mb-6">
        <div className="overline mb-4">account</div>
        <div className="space-y-3 text-sm">
          <Row label="Name" value={user?.name || "—"} />
          <Row label="Email" value={user?.email || "—"} />
          <Row label="User ID" value={user?.user_id || "—"} mono />
        </div>
      </section>

      {/* ElevenLabs voice */}
      <section className="surface p-7 mb-6" data-testid="elevenlabs-section">
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="overline mb-1">your voice</div>
            <h2 className="font-serif text-2xl">ElevenLabs voice clone</h2>
            <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
              When you set a voice, the Twin will literally sound like it when it speaks aloud.
            </p>
          </div>
          {elSettings?.voice_id && (
            <CheckCircle2 className="h-6 w-6" style={{ color: "var(--accent)" }} />
          )}
        </div>

        <div className="mb-6 text-sm space-y-2" style={{ color: "var(--text-secondary)" }}>
          <div className="flex justify-between">
            <span className="overline">api key</span>
            <span className="font-mono">
              {elSettings?.has_user_key
                ? elSettings.api_key_preview
                : elSettings?.has_default_key
                ? "app default in use"
                : "not set"}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="overline">selected voice</span>
            <span className="font-mono">
              {elSettings?.voice_name || elSettings?.voice_id || "—"}
            </span>
          </div>
        </div>

        <div className="space-y-3 mb-6">
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="Paste your ElevenLabs API key (overrides default)"
            data-testid="elevenlabs-key"
            className="w-full px-3 py-2 text-sm rounded-sm font-mono"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
          />
          <div className="flex gap-3">
            <button
              onClick={saveKey}
              disabled={saving || !apiKey.trim()}
              data-testid="elevenlabs-save-key"
              className="px-4 py-2 text-sm rounded-sm disabled:opacity-50"
              style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
            >
              {saving ? "Saving…" : "Save key"}
            </button>
            {(elSettings?.has_user_key || elSettings?.voice_id) && (
              <button
                onClick={clearAll}
                data-testid="elevenlabs-clear"
                className="px-4 py-2 text-sm rounded-sm"
                style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
              >
                Clear
              </button>
            )}
          </div>
        </div>

        {/* Voices */}
        <div className="mb-4">
          <div className="flex items-center justify-between mb-3">
            <div className="overline">available voices</div>
            <button
              onClick={loadVoices}
              data-testid="elevenlabs-refresh"
              className="text-xs hover:text-[var(--accent)]"
              style={{ color: "var(--text-muted)" }}
            >
              refresh
            </button>
          </div>
          {voicesLoading ? (
            <div className="text-sm flex items-center gap-2" style={{ color: "var(--text-muted)" }}>
              <Loader2 className="h-4 w-4 animate-spin" /> loading voices…
            </div>
          ) : voices.length === 0 ? (
            <p className="text-sm" style={{ color: "var(--text-muted)" }}>
              No voices found. Add an API key or clone a voice below.
            </p>
          ) : (
            <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
              {voices.map((v) => (
                <label
                  key={v.voice_id}
                  className="flex items-center justify-between px-3 py-2 rounded-sm cursor-pointer transition-colors"
                  style={{
                    border: "1px solid var(--border-default)",
                    background: voiceId === v.voice_id ? "var(--accent-muted)" : "transparent",
                  }}
                  data-testid={`voice-row-${v.voice_id}`}
                >
                  <div className="flex items-center gap-3">
                    <input
                      type="radio"
                      name="voice"
                      checked={voiceId === v.voice_id}
                      onChange={() => saveVoice(v.voice_id)}
                      data-testid={`voice-radio-${v.voice_id}`}
                    />
                    <div>
                      <div className="text-sm" style={{ color: "var(--text-primary)" }}>
                        {v.name}
                      </div>
                      <div className="font-mono text-xs" style={{ color: "var(--text-muted)" }}>
                        {v.category} · {v.voice_id?.slice(0, 8)}
                      </div>
                    </div>
                  </div>
                </label>
              ))}
            </div>
          )}
        </div>

        {!cloneOpen ? (
          <button
            onClick={() => setCloneOpen(true)}
            data-testid="open-clone"
            className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded-sm"
            style={{ border: "1px solid var(--accent)", color: "var(--accent)" }}
          >
            <Sparkles className="h-4 w-4" /> Clone your own voice
          </button>
        ) : (
          <div className="space-y-3 mt-4 pt-4 border-t" style={{ borderColor: "var(--border-default)" }}>
            <div className="overline">instant voice clone</div>
            <input
              value={cloneName}
              onChange={(e) => setCloneName(e.target.value)}
              placeholder="Voice name (e.g. 'My voice')"
              data-testid="clone-name"
              className="w-full px-3 py-2 text-sm rounded-sm"
              style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
            />
            <input
              value={cloneDesc}
              onChange={(e) => setCloneDesc(e.target.value)}
              placeholder="Description (optional)"
              data-testid="clone-desc"
              className="w-full px-3 py-2 text-sm rounded-sm"
              style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
            />
            <label
              className="block px-4 py-6 text-center cursor-pointer rounded-sm"
              style={{ border: "1px dashed var(--border-default)" }}
              data-testid="clone-dropzone"
            >
              <Upload className="h-5 w-5 mx-auto mb-2" style={{ color: "var(--accent)" }} />
              <div className="text-sm">
                {cloneFiles.length > 0
                  ? `${cloneFiles.length} file(s) selected`
                  : "Choose 1–3 audio samples (≥30s of clear speech each)"}
              </div>
              <input
                type="file"
                multiple
                accept="audio/*"
                onChange={(e) => setCloneFiles(Array.from(e.target.files || []))}
                className="hidden"
                data-testid="clone-files"
              />
            </label>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => {
                  setCloneOpen(false);
                  setCloneFiles([]);
                  setCloneName("");
                  setCloneDesc("");
                }}
                className="px-4 py-2 text-sm rounded-sm"
                style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
              >
                Cancel
              </button>
              <button
                onClick={submitClone}
                disabled={cloning || !cloneName.trim() || cloneFiles.length === 0}
                data-testid="clone-submit"
                className="inline-flex items-center gap-2 px-5 py-2 text-sm rounded-sm disabled:opacity-50"
                style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
              >
                {cloning && <Loader2 className="h-4 w-4 animate-spin" />}
                {cloning ? "Cloning…" : "Create voice"}
              </button>
            </div>
          </div>
        )}
      </section>

      <section className="surface p-7 mb-6">
        <div className="overline mb-4">on the roadmap</div>
        <ul className="space-y-3 text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>
          <li>· Wake-word ("Hey Twin") on the local companion.</li>
          <li>· Discord text-channel bot for passive personality capture.</li>
          <li>· Scheduled "release after" workflow for heirs.</li>
          <li>· Sealed letters auto-delivered to heirs on a future date.</li>
        </ul>
      </section>

      <button
        onClick={logout}
        data-testid="settings-logout"
        className="px-5 py-3 text-sm rounded-sm"
        style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
      >
        Sign out
      </button>
    </div>
  );
}

function Row({ label, value, mono }) {
  return (
    <div className="flex justify-between items-baseline gap-4 py-2 border-b last:border-0" style={{ borderColor: "var(--border-default)" }}>
      <div className="overline">{label}</div>
      <div className={mono ? "font-mono text-xs" : ""} style={{ color: "var(--text-primary)" }}>
        {value}
      </div>
    </div>
  );
}
