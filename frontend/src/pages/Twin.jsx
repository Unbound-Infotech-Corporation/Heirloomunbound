import { useEffect, useRef, useState } from "react";
import { ArrowRight, Loader2, Video, Volume2 } from "lucide-react";
import { api, streamSSE } from "../lib/api";

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
  const feedRef = useRef(null);

  useEffect(() => {
    api.post("/twin/start", {}).then(({ data }) => setConv(data));
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
          messages: [...c.messages, { role: "assistant", content: full, ts: new Date().toISOString(), action }],
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
        }
      },
    );
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
      </header>

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
        {streaming && (
          <div className="border-l-2 pl-6" style={{ borderColor: "var(--accent)" }}>
            <div className="overline mb-2">you (the twin)</div>
            <p className="font-serif text-xl lg:text-2xl leading-snug" style={{ color: "var(--text-primary)" }}>
              {streaming}
              <span className="inline-block w-2 h-5 ml-1 align-middle animate-pulse" style={{ background: "var(--accent)" }} />
            </p>
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
