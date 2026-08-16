import { useEffect, useRef, useState } from "react";
import { ArrowRight, BookOpen, Calendar, Clipboard, Cloud, Cpu, Eye, Film, Globe, Keyboard, Link as LinkIcon, Loader2, Mail, Monitor, Music, Palette, Phone, Power, Save, Search, Search as SearchIcon, ShieldCheck, Sparkles, Terminal, Timer, Video, Volume2, Zap } from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { api, streamSSE } from "../lib/api";
import FunctionModelPicker, { modelOverride } from "@/components/FunctionModelPicker";
import { openTwinMiniWindow } from "@/pages/TwinMini";
import { ToyDesk, ToyKnob, ToyPorthole } from "@/components/ToyPlayset";

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
  check_pc_safety: { label: "checking Windows Security", icon: ShieldCheck },
  open_windows_security: { label: "opening Windows Security", icon: ShieldCheck },
  scan_pc: { label: "starting a Windows scan", icon: ShieldCheck },
  proofread_text: { label: "checking your writing", icon: Keyboard },
  polish_wording: { label: "making it sound like you", icon: Keyboard },
  word_habits: { label: "noticing word habits", icon: Keyboard },
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
  const [portrait, setPortrait] = useState("");
  const location = useLocation();
  const navigate = useNavigate();
  const starterSent = useRef(false);

  useEffect(() => {
    api.get("/abilities").then(({ data }) => setAbilities(data.abilities || [])).catch(() => {});
    api.get("/avatar/me")
      .then(({ data }) => setPortrait(data.avatar_source_url || data.default_url || ""))
      .catch(() => {});
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

  useEffect(() => {
    const starter = location.state?.starter;
    if (!starter || !conv || pending || starterSent.current) return;
    starterSent.current = true;
    navigate(location.pathname, { replace: true, state: {} });
    send(starter);
    // send is stable enough for a one-shot starter from the play desk
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conv, pending, location.state, location.pathname, navigate]);

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
      <ToyDesk className="mb-10">
        <div className="toy-playset-row">
          <ToyPorthole src={portrait} status={pending ? "thinking…" : "listening"} />
          <div className="min-w-0 flex-1">
            <div className="toy-kicker">your twin</div>
            <h1 className="toy-title text-4xl lg:text-5xl mb-2">Sit a while. Ask anything.</h1>
            <p className="toy-copy mb-4">
              Press a knob. Your twin still draws from everything you&apos;ve put in the archive — this is just easier to pick up.
            </p>
            <div className="toy-knob-grid">
              <ToyKnob
                color="sunflower"
                data-testid="twin-mini-open"
                onClick={() => openTwinMiniWindow()}
                title="Open just you and your twin in a small window"
              >
                Talk in a small window
              </ToyKnob>
              <ToyKnob
                color="sky"
                data-testid="twin-look-at-screen"
                disabled={pending || !conv}
                onClick={() => send("Look at my screen and help me with whatever is on it.")}
                title="The twin looks at your home computer and helps — games, writing, movies. The picture is deleted after."
              >
                <Monitor className="h-5 w-5" />
                Look at my screen
              </ToyKnob>
              <ToyKnob
                color="grape"
                data-testid="twin-look-at-me"
                disabled={lookBusy}
                onClick={lookAtMe}
                title="Opens LivePortrait on your home PC so your twin looks back at you"
              >
                {lookBusy ? <Loader2 className="h-5 w-5 animate-spin" /> : <Eye className="h-5 w-5" />}
                look at me
              </ToyKnob>
            </div>
            <div className="flex items-center gap-2 flex-wrap mt-4">
              <FunctionModelPicker functionId="chat" compact onChange={setModelChoice} />
              <Link
                to="/avatar-studio"
                data-testid="twin-avatar-studio"
                className="toy-bead toy-knob-cream"
              >
                avatar studio
              </Link>
              <button
                type="button"
                onClick={() => {
                  try { localStorage.removeItem("twin_conv_id"); } catch (_) { /* noop */ }
                  stopAudio();
                  setConv(null);
                  starterSent.current = false;
                  api.post("/twin/start", {}).then(({ data }) => {
                    setConv(data);
                    try { localStorage.setItem("twin_conv_id", data.conversation_id); } catch (_) { /* noop */ }
                  });
                }}
                data-testid="twin-new-conversation"
                className="toy-bead toy-knob-cream"
              >
                new conversation
              </button>
              <label className="toy-bead toy-knob-cream cursor-pointer">
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
          </div>
        </div>
      </ToyDesk>
      {lookHint && (
        <p className="text-xs mb-6 -mt-4" style={{ color: "var(--accent)" }} data-testid="twin-look-hint">
          {lookHint}
        </p>
      )}

      {abilities.length > 0 && (
        <div className="flex items-center flex-wrap gap-2 mb-8" data-testid="twin-abilities-bar">
          <span className="toy-kicker mr-1" style={{ color: "var(--text-muted)" }}>abilities</span>
          {abilities.map((ab) => (
            <button
              key={ab.id}
              type="button"
              onClick={() => toggleAbility(ab)}
              data-testid={`twin-ability-chip-${ab.id}`}
              title={ab.tagline}
              className="toy-bead"
              style={{
                background: ab.enabled ? "var(--toy-sunflower)" : "#fff6dc",
                color: "var(--toy-ink)",
              }}
            >
              {ab.name}
            </button>
          ))}
        </div>
      )}

      <div ref={feedRef} className="space-y-10 mb-10 max-h-[58vh] overflow-y-auto pr-2" data-testid="twin-feed">
        {messages.length === 0 && !streaming && (
          <ToyDesk className="mb-6" testid="twin-empty-prompt">
            <div className="toy-kicker mb-3">try asking</div>
            <div className="toy-knob-grid">
              {[
                "What's on my plate today?",
                "Look at my screen and help me with this.",
                "Sketch a picture of a sunny kitchen, then open Photoshop.",
              ].map((q, i) => (
                <ToyKnob
                  key={q}
                  color={["tomato", "sunflower", "grape"][i] || "cream"}
                  onClick={() => send(q)}
                >
                  {q}
                </ToyKnob>
              ))}
            </div>
          </ToyDesk>
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

      <ToyDesk className="sticky bottom-6">
        <div className="toy-composer">
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
          />
          <ToyKnob
            color="tomato"
            className="toy-send"
            onClick={() => send(input)}
            disabled={pending || !input.trim()}
            testid="twin-send"
          >
            {pending ? <Loader2 className="h-6 w-6 animate-spin" /> : <ArrowRight className="h-6 w-6" />}
          </ToyKnob>
        </div>
        <div className="toy-kicker mt-3">{pending ? "thinking…" : "ask away"}</div>
      </ToyDesk>
    </div>
  );
}
