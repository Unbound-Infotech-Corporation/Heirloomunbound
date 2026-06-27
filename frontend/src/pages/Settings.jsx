import { useEffect, useState } from "react";
import { CheckCircle2, Loader2, ShieldOff, Sparkles, Trash2, Upload, X } from "lucide-react";
import { api, API_BASE } from "../lib/api";
import { useAuth } from "../lib/auth";

const WIDGETS = [
  { key: "reflection", label: "Daily reflection prompt" },
  { key: "reminders", label: "Reminders on your plate" },
  { key: "on_this_day", label: "On this day (past years)" },
  { key: "suggested_topics", label: "Suggested capture topics" },
  { key: "recent_journals", label: "Recent voice journals" },
  { key: "last_twin_chat", label: "Last conversation with the Twin" },
];

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
  const [widgets, setWidgets] = useState({});
  const [safeTopics, setSafeTopics] = useState([]);
  const [newTopic, setNewTopic] = useState("");

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
  const loadWidgets = async () => {
    const { data } = await api.get("/onboarding/state");
    setWidgets(data.dashboard_widgets || {});
  };
  const loadPrefs = async () => {
    const { data } = await api.get("/auth/me");
    setSafeTopics(data.safe_topics || []);
  };

  useEffect(() => {
    loadSettings().then(() => loadVoices());
    loadWidgets();
    loadPrefs();
  }, []);

  const addTopic = async () => {
    const t = newTopic.trim();
    if (!t) return;
    const next = Array.from(new Set([...safeTopics, t])).slice(0, 25);
    setSafeTopics(next);
    setNewTopic("");
    await api.put("/auth/me/preferences", { safe_topics: next });
  };
  const removeTopic = async (t) => {
    const next = safeTopics.filter((x) => x !== t);
    setSafeTopics(next);
    await api.put("/auth/me/preferences", { safe_topics: next });
  };

  const toggleWidget = async (key) => {
    const next = { ...widgets, [key]: !widgets[key] };
    setWidgets(next);
    await api.put("/onboarding/widgets", { widgets: next });
  };

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
      if (!res.ok) throw new Error(await res.text());
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

      {/* Dashboard widget toggles */}
      <section className="surface p-7 mb-6" data-testid="widgets-section">
        <div className="overline mb-4">today dashboard</div>
        <h2 className="font-serif text-2xl mb-2">What shows up on your Today page</h2>
        <p className="text-sm mb-5" style={{ color: "var(--text-secondary)" }}>
          Pick what you want to see. Quick Capture and the stat strip always show.
        </p>
        <div className="space-y-3">
          {WIDGETS.map((w) => (
            <label
              key={w.key}
              className="flex items-center justify-between px-4 py-3 rounded-sm cursor-pointer"
              style={{ border: "1px solid var(--border-default)" }}
              data-testid={`widget-row-${w.key}`}
            >
              <span className="text-sm" style={{ color: "var(--text-primary)" }}>{w.label}</span>
              <input
                type="checkbox"
                checked={!!widgets[w.key]}
                onChange={() => toggleWidget(w.key)}
                data-testid={`widget-toggle-${w.key}`}
                className="h-4 w-4"
              />
            </label>
          ))}
        </div>
      </section>

      {/* Safe Topics — twin won't engage on these */}
      <section className="surface p-7 mb-6" data-testid="safe-topics-section">
        <div className="overline mb-2 flex items-center gap-2">
          <ShieldOff className="h-3.5 w-3.5" /> safe-topic fence
        </div>
        <h2 className="font-serif text-2xl mb-2">What your twin won't talk about</h2>
        <p className="text-sm mb-5" style={{ color: "var(--text-secondary)" }}>
          Add topics your twin should politely decline — politics, religion, business secrets, anything personal. Applied to all chats, including the heir portal.
        </p>
        <div className="flex flex-wrap gap-2 mb-4" data-testid="safe-topics-list">
          {safeTopics.length === 0 && (
            <span className="text-sm italic" style={{ color: "var(--text-muted)" }}>
              No fenced topics. Your twin will engage freely.
            </span>
          )}
          {safeTopics.map((t) => (
            <span
              key={t}
              className="inline-flex items-center gap-2 px-3 py-1.5 text-sm rounded-sm"
              style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
              data-testid={`safe-topic-${t}`}
            >
              {t}
              <button onClick={() => removeTopic(t)} className="opacity-60 hover:opacity-100">
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
        <div className="flex gap-2">
          <input
            value={newTopic}
            onChange={(e) => setNewTopic(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addTopic()}
            placeholder="Add a topic — e.g. 'politics', 'my divorce', 'work salaries'"
            data-testid="safe-topic-input"
            className="flex-1 px-3 py-2 text-sm rounded-sm"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
          />
          <button
            onClick={addTopic}
            disabled={!newTopic.trim()}
            data-testid="safe-topic-add"
            className="px-4 py-2 text-sm rounded-sm disabled:opacity-50"
            style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
          >
            Add
          </button>
        </div>
      </section>

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
          <li>· Wake-word ("Hey Twin") on the companion.</li>
          <li>· OAuth Gmail + Drive (post Google verification).</li>
          <li>· Sealed letters auto-delivered to heirs on a date you set.</li>
          <li>· Heir release workflow.</li>
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
