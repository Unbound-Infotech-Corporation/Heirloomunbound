import { useEffect, useRef, useState } from "react";
import { ArrowRight, BookOpen, Clipboard, Cloud, Cpu, Eye, Globe, Keyboard, Link as LinkIcon, Loader2, Monitor, Power, Save, Search, Search as SearchIcon, Sparkles, Terminal, Timer, Video, Volume2, Zap } from "lucide-react";
import { api, streamSSE } from "../lib/api";

const TOOL_META = {
  search_archive: { label: "searching your archive", icon: Search },
  save_memory: { label: "saving to your archive", icon: Save },
  set_reminder: { label: "setting a reminder", icon: Timer },
  list_recent_memories: { label: "reading recent memories", icon: BookOpen },
  get_weather: { label: "checking the weather", icon: Cloud },
  web_search: { label: "searching the web", icon: Globe },
  web_fetch: { label: "reading a page", icon: LinkIcon },
  run_skill: { label: "firing a skill", icon: Zap },
  open_on_pc: { label: "opening on your PC", icon: Monitor },
  control_media: { label: "controlling playback", icon: Volume2 },
  set_volume: { label: "setting volume", icon: Volume2 },
  power_action: { label: "power control", icon: Power },
  notify_on_pc: { label: "notifying your PC", icon: Zap },
  type_text: { label: "typing on your PC", icon: Keyboard },
  clipboard: { label: "using your clipboard", icon: Clipboard },
  see_screen: { label: "looking at your screen", icon: Eye },
  system_status: { label: "checking your rig", icon: Cpu },
  run_command: { label: "running a command", icon: Terminal },
  find_file: { label: "finding a file", icon: SearchIcon },
};

function ToolChip({ tool }) {
  const meta = TOOL_META[tool.name] || { label: tool.name, icon: Sparkles };
  const Icon = meta.icon;
  const done = tool.done;
  const argsPreview = tool.args ? Object.values(tool.args)[0] : "";
  return (
    <div
      className="inline-flex items-center gap-2 px-2.5 py-1 text-xs rounded-sm"
      data-testid={`tool-chip-${tool.name}`}
      style={{
        background: done ? "var(--accent-muted, rgba(212,163,115,0.12))" : "rgba(255,255,255,0.03)",
        border: `1px solid ${done ? "var(--accent)" : "var(--border-default)"}`,
        color: done ? "var(--accent)" : "var(--text-muted)",
      }}
    >
      {done ? <Icon className="h-3 w-3" /> : <Loader2 className="h-3 w-3 animate-spin" />}
      <span>{meta.label}</span>
      {argsPreview && (
        <span className="italic max-w-[220px] truncate" style={{ color: "var(--text-muted)" }}>
          · {String(argsPreview).slice(0, 40)}
        </span>
      )}
    </div>
  );
}

export default function Twin() {
  const [conv, setConv] = useState(null);
  const [streaming, setStreaming] = useState("");
  const [pending, setPending] = useState(false);
  const [input, setInput] = useState("");
  const [voiceOn, setVoiceOn] = useState(false);
  const [speakingIdx, setSpeakingIdx] = useState(null);
  const audioRef = useRef(null);
  // Avatar video state: { [msgIdx]: { state: 'loading'|'ready'|'error', url?, err? } }
  const [videos, setVideos] = useState({});
  const [liveTools, setLiveTools] = useState([]);
  const [abilities, setAbilities] = useState([]);

  useEffect(() => {
    api.get("/abilities").then(({ data }) => setAbilities(data.abilities || [])).catch(() => {});
  }, []);

  const toggleAbility = async (ab) => {
    // optimistic
    setAbilities((prev) => prev.map((a) => (a.id === ab.id ? { ...a, enabled: !a.enabled } : a)));
    try {
      if (ab.enabled) {
        await api.post(`/abilities/${ab.id}/disable`);
      } else {
        await api.post(`/abilities/${ab.id}/enable`, {
          granted_permissions: (ab.permissions || []).map((p) => p.id),
        });
      }
    } catch (_) {
      // revert on failure
      setAbilities((prev) => prev.map((a) => (a.id === ab.id ? { ...a, enabled: ab.enabled } : a)));
    }
  };
  const feedRef = useRef(null);

  useEffect(() => {
    let savedId = null;
    try { savedId = localStorage.getItem("twin_conv_id"); } catch (_) { /* noop */ }
    api.post("/twin/start", savedId ? { conversation_id: savedId } : {}).then(({ data }) => {
      setConv(data);
      try { localStorage.setItem("twin_conv_id", data.conversation_id); } catch (_) { /* noop */ }
    });
    return () => {
      if (audioRef.current) {
        try { audioRef.current.pause(); } catch (_) { /* noop */ }
        audioRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: "smooth" });
  }, [conv, streaming]);

  const stopAudio = () => {
    if (audioRef.current) {
      try {
        audioRef.current.pause();
        audioRef.current.currentTime = 0;
      } catch (_) { /* noop */ }
      audioRef.current = null;
    }
    setSpeakingIdx(null);
  };

  const speak = async (text, idx) => {
    stopAudio();
    setSpeakingIdx(idx);
    try {
      // Try cloned voice first; fall back to default OpenAI TTS
      let data;
      try {
        const r = await api.post("/voice-clone/speak", { text });
        data = r.data;
      } catch (err) {
        const r = await api.post("/voice/speak", { text, voice: "onyx" });
        data = r.data;
      }
      const audio = new Audio(`data:${data.mime};base64,${data.audio_base64}`);
      audioRef.current = audio;
      audio.onended = () => {
        if (audioRef.current === audio) audioRef.current = null;
        setSpeakingIdx((cur) => (cur === idx ? null : cur));
      };
      audio.play();
    } catch (e) {
      console.error(e);
      setSpeakingIdx(null);
    }
  };

  const send = async (text) => {
    if (!text.trim() || !conv || pending) return;
    const myMsg = { role: "user", content: text, ts: new Date().toISOString() };
    setConv((c) => ({ ...c, messages: [...(c.messages || []), myMsg] }));
    setInput("");
    setPending(true);
    setStreaming("");

    let full = "";
    let action = null;
    const toolTrace = [];
    await streamSSE(
      "/twin/message",
      { conversation_id: conv.conversation_id, message: text },
      (chunk) => {
        full += chunk;
        setStreaming(full);
      },
      async () => {
        const newIdx = (conv.messages?.length || 0) + 1;
        setConv((c) => ({
          ...c,
          messages: [
            ...c.messages,
            {
              role: "assistant",
              content: full,
              ts: new Date().toISOString(),
              action,
              tool_trace: toolTrace.length ? toolTrace : undefined,
            },
          ],
        }));
        setStreaming("");
        setPending(false);
        if (voiceOn && full) speak(full, newIdx);
      },
      (err) => {
        console.error(err);
        setStreaming("");
        setPending(false);
      },
      (eventName, data) => {
        if (eventName === "action") {
          action = data;
        } else if (eventName === "tool") {
          // Merge start + result rows by id so the chip updates in place
          const idx = toolTrace.findIndex((t) => t.id === data.id);
          if (idx === -1) {
            toolTrace.push({ id: data.id, name: data.name, args: data.args, ui: null, done: false });
          } else if (data.phase === "result") {
            toolTrace[idx] = { ...toolTrace[idx], ui: data.ui, done: true };
          }
          // Force a re-render so the chip appears live during streaming
          setLiveTools([...toolTrace]);
        }
      },
    );
    setLiveTools([]);
  };

  const messages = conv?.messages || [];

  const playAsVideo = async (idx, text) => {
    if (videos[idx]?.state === "loading" || videos[idx]?.state === "ready") return;
    setVideos((v) => ({ ...v, [idx]: { state: "loading" } }));
    try {
      const { data } = await api.post("/avatar/talk", { text });
      const talkId = data.talk_id;
      // Poll up to 120s (60 attempts × 2s). D-ID renders take 30-90s depending on text length.
      for (let i = 0; i < 60; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        let poll;
        try {
          const r = await api.get(`/avatar/talks/${talkId}`);
          poll = r.data;
        } catch (pollErr) {
          // Transient network/proxy hiccup — keep polling rather than failing the whole render
          continue;
        }
        if (poll.result_url) {
          setVideos((v) => ({ ...v, [idx]: { state: "ready", url: poll.result_url } }));
          return;
        }
        if (poll.status === "error" || poll.status === "rejected") {
          setVideos((v) => ({ ...v, [idx]: { state: "error", err: poll.error?.description || poll.error || "render failed" } }));
          return;
        }
      }
      setVideos((v) => ({ ...v, [idx]: { state: "error", err: "timed out after 2 min" } }));
    } catch (e) {
      setVideos((v) => ({ ...v, [idx]: { state: "error", err: e.response?.data?.detail || e.message } }));
    }
  };

  return (
    <div className="px-4 sm:px-8 lg:px-16 py-12 max-w-4xl" data-testid="twin-root">
      <header className="mb-10 flex justify-between items-end gap-6">
        <div>
          <div className="overline mb-3">your twin</div>
          <h1 className="font-serif text-4xl lg:text-5xl font-light tracking-tight">
            Sit a while. Ask anything.
          </h1>
          <p className="mt-3 text-base max-w-xl" style={{ color: "var(--text-secondary)" }}>
            Your twin draws from everything you&apos;ve put into the archive. The more you&apos;ve added, the truer it sounds.
          </p>
        </div>
        <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => {
            try { localStorage.removeItem("twin_conv_id"); } catch (_) { /* noop */ }
            stopAudio();
            setConv(null);
            api.post("/twin/start", {}).then(({ data }) => {
              setConv(data);
              try { localStorage.setItem("twin_conv_id", data.conversation_id); } catch (_) { /* noop */ }
            });
          }}
          data-testid="twin-new-conversation"
          className="text-xs px-4 py-2 rounded-sm transition-colors hover:text-[var(--accent)]"
          style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
        >
          new conversation
        </button>
        <label
          className="flex items-center gap-3 text-xs px-4 py-2 rounded-sm cursor-pointer"
          style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
        >
          <input
            type="checkbox"
            checked={voiceOn}
            onChange={(e) => setVoiceOn(e.target.checked)}
            data-testid="twin-voice-toggle"
            className="h-4 w-4"
          />
          <Volume2 className="h-3.5 w-3.5" />
          speak replies aloud
        </label>
        </div>
      </header>

      {abilities.length > 0 && (
        <div className="flex items-center flex-wrap gap-2 mb-8" data-testid="twin-abilities-bar">
          <span className="text-xs mr-1" style={{ color: "var(--text-muted)" }}>abilities:</span>
          {abilities.map((ab) => (
            <button
              key={ab.id}
              type="button"
              onClick={() => toggleAbility(ab)}
              data-testid={`twin-ability-chip-${ab.id}`}
              title={ab.tagline}
              className="text-xs px-3 py-1 rounded-full transition-colors"
              style={{
                border: `1px solid ${ab.enabled ? "var(--accent)" : "var(--border-default)"}`,
                background: ab.enabled ? "var(--accent-muted, rgba(212,163,115,0.12))" : "transparent",
                color: ab.enabled ? "var(--accent)" : "var(--text-muted)",
              }}
            >
              {ab.name}
            </button>
          ))}
        </div>
      )}

      <div ref={feedRef} className="space-y-10 mb-10 max-h-[58vh] overflow-y-auto pr-2" data-testid="twin-feed">
        {messages.length === 0 && !streaming && (
          <div className="surface p-8" data-testid="twin-empty-prompt">
            <div className="overline mb-3">try asking</div>
            <ul className="space-y-3">
              {[
                "What did you love most about being a father?",
                "What's a story from your twenties you'd want me to know?",
                "What scares you most, and what helps?",
              ].map((q) => (
                <li key={q}>
                  <button
                    onClick={() => send(q)}
                    className="font-serif text-lg text-left hover:text-[var(--accent)] transition-colors"
                  >
                    {q}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} data-testid={`twin-msg-${i}`}>
            {m.role === "assistant" ? (
              <div className="border-l-2 pl-6" style={{ borderColor: "var(--accent)" }}>
                <div className="overline mb-2 flex items-center gap-3">
                  <span>you (the twin)</span>
                  <button
                    onClick={() => speak(m.content, i)}
                    disabled={speakingIdx === i}
                    data-testid={`twin-speak-${i}`}
                    className="hover:text-[var(--accent)] transition-colors disabled:opacity-50"
                    style={{ color: "var(--text-muted)" }}
                  >
                    <Volume2 className="h-3.5 w-3.5" />
                  </button>
                </div>
                <p
                  className="font-serif text-xl lg:text-2xl leading-snug"
                  style={{ color: "var(--text-primary)" }}
                >
                  {m.content}
                </p>
                {m.action?.kind === "music" && (
                  <a
                    href={m.action.url}
                    target="_blank"
                    rel="noreferrer"
                    data-testid={`twin-music-${i}`}
                    className="mt-4 inline-flex items-center gap-3 px-4 py-2 text-sm rounded-sm transition-colors"
                    style={{ background: "var(--accent-muted)", border: "1px solid var(--accent)", color: "var(--text-primary)" }}
                  >
                    <span>♪</span>
                    <span>
                      <b>{m.action.query}</b> · {m.action.provider_name}
                      {m.action.queued && (
                        <span className="ml-2 text-xs italic" style={{ color: "var(--text-muted)" }}>
                          queued on your PC
                        </span>
                      )}
                    </span>
                    <span style={{ color: "var(--accent)" }}>↗ open here</span>
                  </a>
                )}
                {m.action?.kind === "skill" && (
                  <div
                    data-testid={`twin-skill-${i}`}
                    className="mt-4 inline-flex items-center gap-3 px-4 py-2 text-sm rounded-sm"
                    style={{
                      background: m.action.ok ? "var(--accent-muted)" : "rgba(220,80,80,0.12)",
                      border: `1px solid ${m.action.ok ? "var(--accent)" : "#c95a5a"}`,
                      color: "var(--text-primary)",
                    }}
                  >
                    <span>⚡</span>
                    <span>
                      <b>{m.action.skill_name}</b>
                      <span className="ml-2 text-xs italic" style={{ color: "var(--text-muted)" }}>
                        {m.action.ok ? `HTTP ${m.action.status}` : `failed (${m.action.status || "error"})`}
                      </span>
                    </span>
                  </div>
                )}
                {/* Per-message tool trace (persisted after the reply finishes) */}
                {m.tool_trace && m.tool_trace.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mt-3" data-testid={`tool-trace-${i}`}>
                    {m.tool_trace.map((t) => (
                      <ToolChip key={t.id} tool={{ ...t, done: true }} />
                    ))}
                  </div>
                )}
                {/* Play-as-video (D-ID talking head) */}
                {!m.action && (
                  <div className="mt-4">
                    {videos[i]?.state === "ready" ? (
                      <video
                        controls
                        autoPlay
                        playsInline
                        src={videos[i].url}
                        data-testid={`twin-video-${i}`}
                        className="rounded-sm max-w-md"
                        style={{ border: "1px solid var(--border-default)" }}
                      />
                    ) : videos[i]?.state === "loading" ? (
                      <div
                        className="inline-flex items-center gap-2 px-3 py-1.5 text-xs rounded-sm"
                        style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-muted)" }}
                      >
                        <Loader2 className="h-3.5 w-3.5 animate-spin" /> rendering your face speaking…
                      </div>
                    ) : videos[i]?.state === "error" ? (
                      <div
                        className="inline-flex items-center gap-2 px-3 py-1.5 text-xs rounded-sm"
                        style={{ background: "rgba(220,80,80,0.08)", border: "1px solid #c95a5a", color: "var(--text-muted)" }}
                      >
                        video failed: {videos[i].err}
                      </div>
                    ) : (
                      <button
                        onClick={() => playAsVideo(i, m.content)}
                        data-testid={`twin-play-video-${i}`}
                        className="inline-flex items-center gap-2 px-3 py-1.5 text-xs rounded-sm transition-colors"
                        style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
                      >
                        <Video className="h-3.5 w-3.5" /> Play as video
                      </button>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <div>
                <div className="overline mb-2">they ask</div>
                <p className="text-base leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                  {m.content}
                </p>
              </div>
            )}
          </div>
        ))}
        {(streaming || liveTools.length > 0) && (
          <div className="border-l-2 pl-6" style={{ borderColor: "var(--accent)" }}>
            <div className="overline mb-2">you (the twin)</div>
            {liveTools.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mb-3" data-testid="tool-live">
                {liveTools.map((t) => (
                  <ToolChip key={t.id} tool={t} />
                ))}
              </div>
            )}
            {streaming && (
              <p className="font-serif text-xl lg:text-2xl leading-snug" style={{ color: "var(--text-primary)" }}>
                {streaming}
                <span className="inline-block w-2 h-5 ml-1 align-middle animate-pulse" style={{ background: "var(--accent)" }} />
              </p>
            )}
          </div>
        )}
      </div>

      <div className="surface p-4 sticky bottom-6">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              send(input);
            }
          }}
          rows={3}
          placeholder="Ask anything. (⌘/Ctrl + Enter to send)"
          data-testid="twin-input"
          className="w-full bg-transparent border-none outline-none resize-none text-base leading-relaxed"
          style={{ color: "var(--text-primary)" }}
        />
        <div className="flex justify-between items-center mt-2 pt-2 border-t" style={{ borderColor: "var(--border-default)" }}>
          <div className="overline">{pending ? "thinking…" : "ask away"}</div>
          <button
            onClick={() => send(input)}
            disabled={pending || !input.trim()}
            data-testid="twin-send"
            className="inline-flex items-center gap-2 px-5 py-2 text-sm font-medium rounded-sm disabled:opacity-50"
            style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
          >
            {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
