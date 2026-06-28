import { useEffect, useState } from "react";
import { CheckCircle2, Languages, Loader2, Music, Palette, ShieldOff, Sparkles, Trash2, Upload, User, Video, X } from "lucide-react";
import { toast } from "sonner";
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
  const [musicProvider, setMusicProvider] = useState("youtube_music");
  const [musicProviders, setMusicProviders] = useState([]);
  const [brand, setBrand] = useState({ brand_name: "", brand_tagline: "", brand_signoff: "" });
  const [ttsLang, setTtsLang] = useState("auto");
  const [personas, setPersonas] = useState([]);
  const [activePersonaId, setActivePersonaId] = useState(null);
  const [newPersona, setNewPersona] = useState({ name: "", description: "", system_addendum: "" });
  const [avatarUrl, setAvatarUrl] = useState("");
  const [avatarDefault, setAvatarDefault] = useState("");
  const [avatarConfigured, setAvatarConfigured] = useState(false);

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
    setMusicProvider(data.music_provider || "youtube_music");
    setBrand({
      brand_name: data.brand_name || "",
      brand_tagline: data.brand_tagline || "",
      brand_signoff: data.brand_signoff || "",
    });
    setTtsLang(data.tts_language || "auto");
    setActivePersonaId(data.active_persona_id || null);
  };
  const loadPersonas = async () => {
    try {
      const { data } = await api.get("/personas");
      setPersonas(data.personas || []);
      setActivePersonaId(data.active_persona_id || null);
    } catch { /* noop */ }
  };
  const loadAvatar = async () => {
    try {
      const { data } = await api.get("/avatar/me");
      setAvatarUrl(data.avatar_source_url || "");
      setAvatarDefault(data.default_url || "");
      setAvatarConfigured(!!data.configured);
    } catch { /* noop */ }
  };
  const loadMusicProviders = async () => {
    try {
      const { data } = await api.get("/music/providers");
      setMusicProviders(data.providers || []);
    } catch {
      // public endpoint — should always work, but degrade silently
    }
  };

  useEffect(() => {
    loadSettings().then(() => loadVoices());
    loadWidgets();
    loadPrefs();
    loadMusicProviders();
    loadPersonas();
    loadAvatar();
  }, []);

  const saveAvatarUrl = async () => {
    try {
      await api.put("/avatar/source-url", { url: avatarUrl.trim() });
      toast.success("Avatar photo saved");
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message);
    }
  };

  const saveBrand = async () => {
    try {
      await api.put("/auth/me/preferences", brand);
      toast.success("Brand kit saved");
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message);
    }
  };

  const saveLang = async (lang) => {
    setTtsLang(lang);
    try {
      await api.put("/auth/me/preferences", { tts_language: lang });
      toast.success("Voice language updated");
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message);
    }
  };

  const activatePersona = async (id) => {
    if (!id) {
      await api.post("/personas/deactivate");
      setActivePersonaId(null);
      toast.success("Persona cleared");
      return;
    }
    await api.post(`/personas/${id}/activate`);
    setActivePersonaId(id);
    toast.success("Persona activated");
  };

  const createPersona = async () => {
    if (!newPersona.name.trim()) return;
    try {
      await api.post("/personas", newPersona);
      setNewPersona({ name: "", description: "", system_addendum: "" });
      loadPersonas();
      toast.success("Persona created");
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message);
    }
  };

  const deletePersona = async (id) => {
    if (!window.confirm("Delete this persona?")) return;
    await api.delete(`/personas/${id}`);
    loadPersonas();
  };

  const updateMusicProvider = async (val) => {
    setMusicProvider(val);
    try {
      await api.put("/auth/me/preferences", { music_provider: val });
      toast.success("Music provider updated");
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message);
    }
  };

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
    <div className="px-4 sm:px-8 lg:px-16 py-12 max-w-3xl" data-testid="settings-root">
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

      {/* Talking-head avatar — D-ID */}
      <section className="surface p-7 mb-6" data-testid="avatar-section">
        <div className="overline mb-2 flex items-center gap-2">
          <Video className="h-3.5 w-3.5" /> talking-head avatar
        </div>
        <h2 className="font-serif text-2xl mb-2">Your face, speaking.</h2>
        <p className="text-sm mb-5" style={{ color: "var(--text-secondary)" }}>
          Paste a public URL to a photo of you (imgur, your social, etc.). When you click <i>Play as video</i> on a twin reply, D-ID renders a short clip of your face speaking the text in your cloned voice.
          {!avatarConfigured && (
            <span className="block mt-2 text-xs" style={{ color: "#c95a5a" }}>
              D-ID API not configured — contact the operator.
            </span>
          )}
        </p>
        <div className="flex gap-3 items-start mb-4">
          {(avatarUrl || avatarDefault) && (
            <img
              src={avatarUrl || avatarDefault}
              alt="avatar source"
              className="w-24 h-24 rounded-sm object-cover"
              data-testid="avatar-preview"
              style={{ border: "1px solid var(--border-default)" }}
              onError={(e) => { e.currentTarget.style.opacity = 0.3; }}
            />
          )}
          <div className="flex-1 space-y-3">
            <input
              value={avatarUrl}
              onChange={(e) => setAvatarUrl(e.target.value)}
              placeholder={`Photo URL (leave blank to use the default presenter)`}
              data-testid="avatar-url-input"
              className="w-full px-3 py-2 text-sm rounded-sm font-mono"
              style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
            />
            <button
              onClick={saveAvatarUrl}
              data-testid="avatar-save"
              className="px-4 py-2 text-sm rounded-sm"
              style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
            >
              Save photo
            </button>
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>
              Best: front-facing, neutral expression, ~1024×1024. D-ID requires the URL to be publicly fetchable.
            </p>
          </div>
        </div>
      </section>

      {/* Personas — switchable twin modes */}
      <section className="surface p-7 mb-6" data-testid="personas-section">
        <div className="overline mb-2 flex items-center gap-2">
          <User className="h-3.5 w-3.5" /> personas
        </div>
        <h2 className="font-serif text-2xl mb-2">Your twin&apos;s modes</h2>
        <p className="text-sm mb-5" style={{ color: "var(--text-secondary)" }}>
          Switchable personalities for the same archive. Family mode for evenings, Professional mode for work — the underlying memory stays the same, only the tone shifts.
        </p>

        <div className="flex flex-wrap gap-2 mb-5">
          <button
            onClick={() => activatePersona(null)}
            data-testid="persona-none"
            className="px-4 py-2 text-sm rounded-sm"
            style={{
              background: !activePersonaId ? "var(--accent)" : "var(--bg-base)",
              color: !activePersonaId ? "var(--text-inverse)" : "var(--text-primary)",
              border: !activePersonaId ? "1px solid var(--accent)" : "1px solid var(--border-default)",
            }}
          >
            Default
          </button>
          {personas.map((p) => (
            <button
              key={p.persona_id}
              onClick={() => activatePersona(p.persona_id)}
              data-testid={`persona-${p.persona_id}`}
              className="px-4 py-2 text-sm rounded-sm group inline-flex items-center gap-2"
              style={{
                background: p.persona_id === activePersonaId ? "var(--accent)" : "var(--bg-base)",
                color: p.persona_id === activePersonaId ? "var(--text-inverse)" : "var(--text-primary)",
                border: p.persona_id === activePersonaId ? "1px solid var(--accent)" : "1px solid var(--border-default)",
              }}
            >
              {p.name}
              <span
                onClick={(e) => { e.stopPropagation(); deletePersona(p.persona_id); }}
                className="opacity-50 hover:opacity-100 transition-opacity"
                title="Delete"
              >
                <X className="h-3 w-3" />
              </span>
            </button>
          ))}
        </div>

        <div className="space-y-2 mb-3">
          <input
            value={newPersona.name}
            onChange={(e) => setNewPersona({ ...newPersona, name: e.target.value })}
            placeholder="Name — e.g. 'Professional', 'Customer Support'"
            data-testid="persona-new-name"
            className="w-full px-3 py-2 text-sm rounded-sm"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
          />
          <textarea
            value={newPersona.system_addendum}
            onChange={(e) => setNewPersona({ ...newPersona, system_addendum: e.target.value })}
            placeholder="Instructions added to the twin in this mode. e.g. 'Be formal. Don't mention family. Focus on Unbound Infotech work and product positioning.'"
            rows={3}
            data-testid="persona-new-addendum"
            className="w-full px-3 py-2 text-sm rounded-sm"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
          />
          <button
            onClick={createPersona}
            disabled={!newPersona.name.trim()}
            data-testid="persona-create"
            className="px-4 py-2 text-sm rounded-sm disabled:opacity-50"
            style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
          >
            Create persona
          </button>
        </div>
      </section>

      {/* Brand Kit — injected into the twin's system prompt */}
      <section className="surface p-7 mb-6" data-testid="brand-section">
        <div className="overline mb-2 flex items-center gap-2">
          <Palette className="h-3.5 w-3.5" /> brand kit
        </div>
        <h2 className="font-serif text-2xl mb-2">Your voice across everything</h2>
        <p className="text-sm mb-5" style={{ color: "var(--text-secondary)" }}>
          Optional — applied to all twin replies so it stays consistent across personal chats, the heir portal, and any business persona.
        </p>
        <input
          value={brand.brand_name}
          onChange={(e) => setBrand({ ...brand, brand_name: e.target.value })}
          placeholder="Brand or company name (e.g. Unbound Infotech)"
          data-testid="brand-name"
          className="w-full px-3 py-2 text-sm rounded-sm mb-3"
          style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
        />
        <input
          value={brand.brand_tagline}
          onChange={(e) => setBrand({ ...brand, brand_tagline: e.target.value })}
          placeholder="One-line tagline (optional)"
          data-testid="brand-tagline"
          className="w-full px-3 py-2 text-sm rounded-sm mb-3"
          style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
        />
        <input
          value={brand.brand_signoff}
          onChange={(e) => setBrand({ ...brand, brand_signoff: e.target.value })}
          placeholder="Sign-off the twin uses on longer replies (e.g. '— Aaron, Unbound')"
          data-testid="brand-signoff"
          className="w-full px-3 py-2 text-sm rounded-sm mb-4"
          style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
        />
        <button
          onClick={saveBrand}
          data-testid="brand-save"
          className="px-4 py-2 text-sm rounded-sm"
          style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
        >
          Save brand
        </button>
      </section>

      {/* Voice language — ElevenLabs Multilingual v2 */}
      <section className="surface p-7 mb-6" data-testid="language-section">
        <div className="overline mb-2 flex items-center gap-2">
          <Languages className="h-3.5 w-3.5" /> spoken language
        </div>
        <h2 className="font-serif text-2xl mb-2">Speak your language</h2>
        <p className="text-sm mb-5" style={{ color: "var(--text-secondary)" }}>
          When the twin replies in audio, it&apos;ll use your cloned voice — in the language you pick. ElevenLabs Multilingual v2 preserves your timbre across all of these.
        </p>
        <select
          value={ttsLang}
          onChange={(e) => saveLang(e.target.value)}
          data-testid="lang-select"
          className="w-full px-3 py-2 text-sm rounded-sm"
          style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
        >
          {[
            ["auto","Auto-detect from text"],
            ["en","English"],["es","Español"],["fr","Français"],["de","Deutsch"],
            ["it","Italiano"],["pt","Português"],["nl","Nederlands"],["pl","Polski"],
            ["sv","Svenska"],["no","Norsk"],["da","Dansk"],["fi","Suomi"],
            ["cs","Čeština"],["tr","Türkçe"],["ru","Русский"],["ar","العربية"],
            ["hi","हिन्दी"],["ja","日本語"],["ko","한국어"],["zh","中文"],
          ].map(([k, label]) => (
            <option key={k} value={k}>{label}</option>
          ))}
        </select>
      </section>

      {/* Music — default service the twin opens when you say "play X" */}
      <section className="surface p-7 mb-6" data-testid="music-section">
        <div className="overline mb-2 flex items-center gap-2">
          <Music className="h-3.5 w-3.5" /> music
        </div>
        <h2 className="font-serif text-2xl mb-2">Where should &ldquo;play X&rdquo; go?</h2>
        <p className="text-sm mb-5" style={{ color: "var(--text-secondary)" }}>
          When you say things like <i>&ldquo;play me some Pink Floyd&rdquo;</i> to the twin, it queues an open-URL command on your companion PC for this service. You can override per-request later.
        </p>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
          {musicProviders.map((p) => (
            <button
              key={p.id}
              onClick={() => updateMusicProvider(p.id)}
              data-testid={`music-provider-${p.id}`}
              className="px-4 py-3 text-sm rounded-sm text-left transition-colors"
              style={{
                background: musicProvider === p.id ? "var(--accent)" : "var(--bg-base)",
                color: musicProvider === p.id ? "var(--text-inverse)" : "var(--text-primary)",
                border: musicProvider === p.id ? "1px solid var(--accent)" : "1px solid var(--border-default)",
              }}
            >
              {p.name}
            </button>
          ))}
        </div>
      </section>

      {/* Safe Topics — twin won't engage on these */}
      <section className="surface p-7 mb-6" data-testid="safe-topics-section">
        <div className="overline mb-2 flex items-center gap-2">
          <ShieldOff className="h-3.5 w-3.5" /> safe-topic fence
        </div>
        <h2 className="font-serif text-2xl mb-2">What your twin won&apos;t talk about</h2>
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
          <li>· Wake-word (&ldquo;Hey Twin&rdquo;) on the companion.</li>
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

      <DIdKeySection />
      <EmailSection />
      <ConnectedAccountsSection />
      <DangerZone />
    </div>
  );
}

function ConnectedAccountsSection() {
  const [data, setData] = useState(null);
  const load = async () => {
    try {
      const r = await api.get("/oauth/connections");
      setData(r.data);
    } catch { /* noop */ }
  };
  useEffect(() => { load(); }, []);

  // After Spotify callback we land at /settings?spotify=connected (or error:...)
  useEffect(() => {
    const u = new URL(window.location.href);
    const p = u.searchParams.get("spotify");
    if (!p) return;
    if (p === "connected") toast.success("Spotify connected. Your listening history is now in your archive.");
    else toast.error(`Spotify connection failed (${p.replace("error:", "")})`);
    // Clean URL
    u.searchParams.delete("spotify");
    window.history.replaceState({}, "", u.toString());
    load();
  }, []);

  const connectSpotify = async () => {
    try {
      const { data: d } = await api.get("/oauth/spotify/connect");
      window.location.href = d.authorize_url;
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to start Spotify OAuth");
    }
  };
  const disconnect = async (provider) => {
    if (!confirm(`Disconnect ${provider}? Your previously imported data stays in the archive.`)) return;
    await api.delete(`/oauth/${provider}`);
    toast.success(`${provider} disconnected`);
    load();
  };

  if (!data) return null;
  return (
    <section className="surface p-8 mt-10" data-testid="settings-oauth-section">
      <div className="overline mb-2">connected accounts</div>
      <h2 className="font-serif text-2xl font-light mb-3" style={{ color: "var(--text-primary)" }}>
        Bring your accounts in
      </h2>
      <p className="text-sm mb-6 leading-relaxed" style={{ color: "var(--text-secondary)" }}>
        Connect the apps you already live in. Heirloom quietly pulls a small personality signal from each — what you listen to, what you read, what you make — and weaves it into your archive without you having to type a single word.
      </p>
      <div className="space-y-3">
        {data.connections.map((c) => (
          <div
            key={c.provider}
            className="p-5 rounded-sm flex items-start gap-4"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)" }}
            data-testid={`oauth-card-${c.provider}`}
          >
            <div
              className="h-11 w-11 flex-shrink-0 flex items-center justify-center rounded-sm"
              style={{
                background: c.connected ? "var(--accent-muted)" : "var(--bg-elevated)",
                border: `1px solid ${c.connected ? "var(--accent)" : "var(--border-default)"}`,
              }}
            >
              <Music className="h-5 w-5" style={{ color: c.connected ? "var(--accent)" : "var(--text-muted)" }} />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-baseline justify-between gap-3">
                <div className="font-serif text-lg" style={{ color: "var(--text-primary)" }}>{c.label}</div>
                {c.connected && c.profile?.display_name && (
                  <div className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>
                    signed in as <b style={{ color: "var(--accent)" }}>{c.profile.display_name}</b>
                  </div>
                )}
              </div>
              <p className="text-xs mt-1 mb-4 leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                {c.description}
              </p>
              {!c.configured ? (
                <div className="text-xs italic" style={{ color: "var(--text-muted)" }}>
                  Not configured on the server. Set the {c.provider.toUpperCase()}_CLIENT_ID and _CLIENT_SECRET env vars.
                </div>
              ) : c.connected ? (
                <button
                  onClick={() => disconnect(c.provider)}
                  data-testid={`oauth-disconnect-${c.provider}`}
                  className="px-3 py-1.5 text-xs rounded-sm"
                  style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
                >
                  Disconnect
                </button>
              ) : (
                <button
                  onClick={() => c.provider === "spotify" ? connectSpotify() : null}
                  data-testid={`oauth-connect-${c.provider}`}
                  className="px-3 py-1.5 text-xs rounded-sm"
                  style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
                >
                  Connect {c.label}
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function EmailSection() {
  const [info, setInfo] = useState(null);
  const [to, setTo] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get("/email/status");
        setInfo(data);
      } catch { /* noop */ }
    })();
  }, []);
  const sendTest = async () => {
    if (!to.includes("@")) {
      toast.error("Enter a real email address first");
      return;
    }
    setBusy(true);
    try {
      const { data } = await api.post("/email/test", { to });
      toast.success(`Email sent (id ${data.id?.slice(0, 8) || "—"}). Check your inbox.`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Send failed");
    } finally {
      setBusy(false);
    }
  };
  if (!info) return null;
  return (
    <section className="surface p-8 mt-10" data-testid="settings-email-section">
      <div className="overline mb-2">delivery · resend</div>
      <h2 className="font-serif text-2xl font-light mb-3" style={{ color: "var(--text-primary)" }}>
        Transactional email
      </h2>
      <p className="text-sm mb-4 leading-relaxed" style={{ color: "var(--text-secondary)" }}>
        Sent automatically after Stripe checkout (welcome + magic link) and when an heir is released.
        Status:{" "}
        {info.configured
          ? <span style={{ color: "var(--accent)" }}>connected</span>
          : <span style={{ color: "#c95a5a" }}>not configured</span>}
        {info.configured && (
          <> · from <code className="font-mono">{info.sender_email}</code></>
        )}
      </p>
      {info.test_mode && (
        <p className="text-xs mb-4 leading-relaxed p-3 rounded-sm" style={{
          background: "rgba(212,163,115,0.06)", border: "1px solid var(--accent-muted)", color: "var(--text-muted)",
        }}>
          <b style={{ color: "var(--accent)" }}>Test mode</b> — using Resend&apos;s shared{" "}
          <code className="font-mono">onboarding@resend.dev</code> sender. In this mode emails only deliver to the
          inbox that owns your Resend account. To send to real customers, verify a domain at{" "}
          <a href="https://resend.com/domains" target="_blank" rel="noreferrer" style={{ color: "var(--accent)" }}>
            resend.com/domains
          </a>{" "}
          and update <code className="font-mono">SENDER_EMAIL</code> in your backend env.
        </p>
      )}
      {info.configured && (
        <div className="flex flex-wrap gap-3 items-center">
          <input
            type="email"
            value={to}
            onChange={(e) => setTo(e.target.value)}
            placeholder="recipient@example.com"
            data-testid="email-test-input"
            className="flex-1 min-w-[260px] px-3 py-2 text-sm rounded-sm"
            style={{
              background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)",
            }}
          />
          <button
            onClick={sendTest}
            disabled={busy || !to}
            data-testid="email-test-send"
            className="px-4 py-2 text-sm rounded-sm disabled:opacity-50"
            style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
          >
            {busy ? "Sending…" : "Send a test welcome email"}
          </button>
        </div>
      )}
    </section>
  );
}

function DIdKeySection() {
  const [info, setInfo] = useState(null);
  const [key, setKey] = useState("");
  const [saving, setSaving] = useState(false);
  const load = async () => {
    try {
      const { data } = await api.get("/avatar/me");
      setInfo(data);
    } catch { /* noop */ }
  };
  useEffect(() => { load(); }, []);
  const save = async () => {
    if (key.length < 10) {
      toast.error("That key looks too short");
      return;
    }
    setSaving(true);
    try {
      await api.put("/avatar/api-key", { api_key: key });
      toast.success("D-ID key saved. Renders now bill to your account.");
      setKey("");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    } finally {
      setSaving(false);
    }
  };
  const clear = async () => {
    if (!confirm("Remove your personal D-ID key? Renders will fall back to the platform key.")) return;
    await api.delete("/avatar/api-key");
    toast.success("Key removed");
    load();
  };
  return (
    <section className="surface p-8 mt-10" data-testid="settings-d-id-section">
      <div className="overline mb-2">your face · d-id integration</div>
      <h2 className="font-serif text-2xl font-light mb-3" style={{ color: "var(--text-primary)" }}>
        Bring your own D-ID key
      </h2>
      <p className="text-sm mb-6 leading-relaxed" style={{ color: "var(--text-secondary)" }}>
        Every &ldquo;Play as video&rdquo; click on the Twin renders through D-ID. If you connect your personal D-ID key,
        renders are billed to your account (much higher monthly cap, no shared platform throttle). Get a key at{" "}
        <a href="https://www.d-id.com/api/" target="_blank" rel="noreferrer" style={{ color: "var(--accent)" }}>
          d-id.com/api
        </a>.
      </p>
      {info?.has_personal_key ? (
        <div className="flex flex-wrap gap-3 items-center">
          <div className="font-mono text-xs px-3 py-2 rounded-sm" style={{
            background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)",
          }} data-testid="d-id-key-masked">
            {info.masked_key || "•••••• connected"}
          </div>
          <button
            onClick={clear}
            data-testid="d-id-key-clear"
            className="px-4 py-2 text-xs rounded-sm"
            style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
          >
            Remove key
          </button>
        </div>
      ) : (
        <div className="flex flex-wrap gap-3 items-center">
          <input
            type="password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="paste your D-ID API key (Basic auth string)"
            data-testid="d-id-key-input"
            className="flex-1 min-w-[300px] px-3 py-2 text-sm rounded-sm font-mono"
            style={{
              background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)",
            }}
          />
          <button
            onClick={save}
            disabled={saving || !key}
            data-testid="d-id-key-save"
            className="px-4 py-2 text-sm rounded-sm disabled:opacity-50"
            style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
          >
            {saving ? "Saving…" : "Connect"}
          </button>
        </div>
      )}
    </section>
  );
}

function DangerZone() {
  const [busy, setBusy] = useState(false);
  const remove = async () => {
    const phrase = prompt(
      "This is permanent. Your archive, voice clone, photos, heirs, letters, and account will be erased within 7 days. " +
      "Type DELETE to confirm:"
    );
    if (phrase !== "DELETE") {
      toast.message("Cancelled — your account is safe.");
      return;
    }
    setBusy(true);
    try {
      await api.delete("/auth/me?confirm=DELETE");
      toast.success("Account deleted. Goodbye.");
      setTimeout(() => { window.location.href = "/"; }, 1200);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Delete failed");
      setBusy(false);
    }
  };
  return (
    <section
      className="p-8 mt-10 rounded-sm"
      style={{ border: "1px solid #6b1f1f", background: "rgba(107, 31, 31, 0.06)" }}
      data-testid="settings-danger-zone"
    >
      <div className="overline mb-2" style={{ color: "#ff8a8a" }}>danger zone</div>
      <h2 className="font-serif text-2xl font-light mb-3" style={{ color: "var(--text-primary)" }}>
        Delete my account
      </h2>
      <p className="text-sm mb-6 leading-relaxed" style={{ color: "var(--text-secondary)" }}>
        Permanently delete your archive, voice clone, photos, heirs, letters, and every other artifact tied to your
        account. This cannot be undone. Stripe records are retained per Stripe&apos;s policies (we only kept your
        checkout session id, never your card). For a refund, write to{" "}
        <a href="mailto:support@heirloom.app" style={{ color: "var(--accent)" }}>support@heirloom.app</a> first
        — see our <a href="/refunds" target="_blank" rel="noreferrer" style={{ color: "var(--accent)" }}>refund policy</a>.
      </p>
      <button
        onClick={remove}
        disabled={busy}
        data-testid="settings-delete-account"
        className="px-5 py-3 text-sm rounded-sm transition-colors disabled:opacity-50"
        style={{ border: "1px solid #6b1f1f", color: "#ff8a8a", background: "transparent" }}
      >
        {busy ? "Deleting…" : "Delete my account permanently"}
      </button>
    </section>
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
