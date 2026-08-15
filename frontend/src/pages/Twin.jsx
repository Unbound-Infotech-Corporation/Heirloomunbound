import { useEffect, useRef, useState } from "react";
import { ArrowRight, BookOpen, Calendar, Clipboard, Cloud, Cpu, Eye, Film, Globe, Keyboard, Link as LinkIcon, Loader2, Mail, Monitor, Music, Palette, Phone, Power, Save, Search, Search as SearchIcon, Sparkles, Terminal, Timer, Video, Volume2, Zap } from "lucide-react";
import { Link } from "react-router-dom";
import { api, streamSSE } from "../lib/api";
import FunctionModelPicker, { modelOverride } from "@/components/FunctionModelPicker";
import { openTwinMiniWindow } from "@/pages/TwinMini";

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
  read_inbox: { label: "reading your mail", icon: Mail },
  search_mail: { label: "searching mail", icon: Mail },
  find_setup_mail: { label: "looking for setup mail", icon: Mail },
  send_email: { label: "sending mail", icon: Mail },
  find_follow_ups: { label: "finding follow-ups", icon: Mail },
  list_reminders: { label: "checking reminders", icon: Timer },
  complete_reminder: { label: "checking off a reminder", icon: Timer },
  whats_on_my_plate: { label: "catching you up", icon: Calendar },
  list_events: { label: "checking your calendar", icon: Calendar },
  create_event: { label: "adding a calendar date", icon: Calendar },
  find_contact: { label: "looking up a person", icon: Phone },
  call_contact: { label: "placing a call", icon: Phone },
  create_artwork: { label: "sketching a picture", icon: Palette },
  edit_video: { label: "starting a video edit", icon: Film },
  make_music: { label: "sketching a song", icon: Music },
  open_studio: { label: "opening your studio", icon: Palette },
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
  const [modelChoice, setModelChoice] = useState(null);
  const [lookHint, setLookHint] = useState("");
  const [lookBusy, setLookBusy] = useState(false);

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
      { conversation_id: conv.conversation_id, message: text, ...modelOverride(modelChoice) },
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
      const local = data.engine === "local";
      // Local Comfy/Pinokio jobs can take several minutes; D-ID is usually < 90s.
      const attempts = local ? 180 : 60;
      for (let i = 0; i < attempts; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        let poll;
        try {
          const r = await api.get(`/avatar/talks/${talkId}`);
          poll = r.data;
        } catch (pollErr) {
          continue;
        }
        if (poll.result_url) {
          setVideos((v) => ({ ...v, [idx]: { state: "ready", url: poll.result_url } }));
          return;
        }
        if (poll.status === "done" && !poll.result_url) {
          setVideos((v) => ({ ...v, [idx]: { state: "opened", err: poll.hint || "Opened EchoMimic / ComfyUI on your PC." } }));
          return;
        }
        if (poll.status === "error" || poll.status === "rejected") {
          setVideos((v) => ({ ...v, [idx]: { state: "error", err: poll.error?.description || poll.error || poll.hint || "That didn't finish. Try Avatar Studio." } }));
          return;
        }
      }
      setVideos((v) => ({ ...v, [idx]: { state: "error", err: local ? "Still working on your computer. Leave Heirloom open and try again in a minute." : "That took too long. Try again." } }));
    } catch (e) {
      const detail = typeof e.response?.data?.detail === "string" ? e.response.data.detail : "";
      setVideos((v) => ({ ...v, [idx]: { state: "error", err: detail || "Couldn't start. Open Avatar Studio — one photo and one button." } }));
    }
  };

  const lookAtMe = async () => {
    if (lookBusy) return;
    setLookBusy(true);
    setLookHint("");
    try {
      const { data } = await api.post("/avatar-studio/jobs", { kind: "look" });
      setLookHint(data.hint || "Look at the computer. When it asks, turn on the webcam.");
    } catch (e) {
      const detail = typeof e.response?.data?.detail === "string" ? e.response.data.detail : "";
      if (/photo|face|camera/i.test(detail)) {
        setLookHint("Add a photo of your face in Avatar Studio first — looking at the camera.");
      } else if (/home|computer|desktop|Heirloom app/i.test(detail)) {
        setLookHint("Open the Heirloom app on the computer at home, then try again.");
      } else {
        setLookHint(detail || "Couldn't start. Open Avatar Studio — one photo and one button.");
      }
    } finally {
      setLookBusy(false);
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
        <div className="flex items-center gap-3 flex-wrap justify-end">
        <FunctionModelPicker functionId="chat" compact onChange={setModelChoice} />
        <button
          type="button"
          onClick={() => openTwinMiniWindow()}
          data-testid="twin-mini-open"
          className="inline-flex items-center gap-2 text-xs px-4 py-2 rounded-sm"
          style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
          title="Open just you and your twin in a small window"
        >
          Talk in a small window
        </button>
        <button
          type="button"
          onClick={lookAtMe}
          disabled={lookBusy}
          data-testid="twin-look-at-me"
          className="inline-flex items-center gap-2 text-xs px-4 py-2 rounded-sm"
          style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
          title="Opens LivePortrait on your home PC so your twin looks back at you"
        >
          {lookBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Eye className="h-3.5 w-3.5" />}
          look at me
        </button>
        <button
          type="button"
          onClick={() => send("Look at my screen and help me with whatever is on it.")}
          disabled={pending || !conv}
          data-testid="twin-look-at-screen"
          className="inline-flex items-center gap-2 text-xs px-4 py-2 rounded-sm disabled:opacity-50"
          style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
          title="The twin looks at your home computer and helps — games, writing, movies. The picture is deleted after."
        >
          <Monitor className="h-3.5 w-3.5" />
          Look at my screen
        </button>
        <Link
          to="/avatar-studio"
          data-testid="twin-avatar-studio"
          className="text-xs px-4 py-2 rounded-sm"
          style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
        >
          avatar studio
        </Link>
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
      {lookHint && (
        <p className="text-xs mb-6 -mt-4" style={{ color: "var(--accent)" }} data-testid="twin-look-hint">
          {lookHint}
        </p>
      )}

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
                "What's on my plate today?",
                "Look at my screen and help me with this.",
                "What did you love most about being a father?",
                "What's a story from your twenties you'd want me to know?",
                "Who in my address book should I call?",
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
                        <Loader2 className="h-3.5 w-3.5 animate-spin" /> rendering on your PC or D-ID…
                      </div>
                    ) : videos[i]?.state === "opened" ? (
                      <div
                        className="inline-flex items-center gap-2 px-3 py-1.5 text-xs rounded-sm"
                        style={{ background: "var(--bg-base)", border: "1px solid var(--accent)", color: "var(--text-secondary)" }}
                      >
                        {videos[i].err}
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
