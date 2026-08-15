import { useEffect, useRef, useState } from "react";
import { ArrowRight, Loader2, Volume2 } from "lucide-react";
import { Link } from "react-router-dom";
import { api, streamSSE } from "@/lib/api";

const POPUP_FEATURES =
  "popup=yes,width=400,height=680,menubar=no,toolbar=no,location=no,status=no,resizable=yes";

/** Open just-the-twin in its own small browser window. */
export function openTwinMiniWindow() {
  const w = 400;
  const h = 680;
  const left = Math.max(0, (window.screenX || 0) + (window.outerWidth || 800) - w - 24);
  const top = Math.max(0, (window.screenY || 0) + 72);
  const features = `${POPUP_FEATURES},left=${left},top=${top}`;
  const popup = window.open("/twin/mini", "heirloom-twin-mini", features);
  if (popup) {
    try {
      popup.focus();
    } catch (_) {
      /* popup blockers can still return a window that isn't focusable */
    }
  }
  return popup;
}

/**
 * Compact twin talk surface — face, short transcript, tasks.
 * Lives outside AppLayout so it can sit in a small popup.
 */
export default function TwinMini() {
  const [conv, setConv] = useState(null);
  const [streaming, setStreaming] = useState("");
  const [pending, setPending] = useState(false);
  const [input, setInput] = useState("");
  const [portrait, setPortrait] = useState("");
  const [videoUrl, setVideoUrl] = useState("");
  const [faceHint, setFaceHint] = useState("");
  const [speaking, setSpeaking] = useState(false);
  const feedRef = useRef(null);
  const audioRef = useRef(null);
  const autoVideoFor = useRef(null);

  useEffect(() => {
    document.title = "Your twin";
    api.get("/avatar/me")
      .then(({ data }) => setPortrait(data.avatar_source_url || data.default_url || ""))
      .catch(() => {});
    let savedId = null;
    try {
      savedId = localStorage.getItem("twin_conv_id");
    } catch (_) {
      /* noop */
    }
    api.post("/twin/start", savedId ? { conversation_id: savedId } : {})
      .then(({ data }) => {
        setConv(data);
        try {
          localStorage.setItem("twin_conv_id", data.conversation_id);
        } catch (_) {
          /* noop */
        }
      })
      .catch(() => {});
    return () => {
      if (audioRef.current) {
        try {
          audioRef.current.pause();
        } catch (_) {
          /* noop */
        }
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
      } catch (_) {
        /* noop */
      }
      audioRef.current = null;
    }
    setSpeaking(false);
  };

  const speak = async (text) => {
    stopAudio();
    setSpeaking(true);
    try {
      let data;
      try {
        const r = await api.post("/voice-clone/speak", { text });
        data = r.data;
      } catch (_) {
        const r = await api.post("/voice/speak", { text, voice: "onyx" });
        data = r.data;
      }
      const audio = new Audio(`data:${data.mime};base64,${data.audio_base64}`);
      audioRef.current = audio;
      audio.onended = () => {
        if (audioRef.current === audio) audioRef.current = null;
        setSpeaking(false);
      };
      await audio.play();
    } catch (_) {
      setSpeaking(false);
    }
  };

  const playFace = async (idx, text) => {
    if (!text || autoVideoFor.current === idx) return;
    autoVideoFor.current = idx;
    setFaceHint("Getting the face ready…");
    try {
      const { data } = await api.post("/avatar/talk", { text });
      const talkId = data.talk_id;
      const local = data.engine === "local";
      const attempts = local ? 180 : 60;
      for (let i = 0; i < attempts; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        let poll;
        try {
          const r = await api.get(`/avatar/talks/${talkId}`);
          poll = r.data;
        } catch (_) {
          continue;
        }
        if (poll.result_url) {
          setVideoUrl(poll.result_url);
          setFaceHint("");
          return;
        }
        if (poll.status === "done" && !poll.result_url) {
          setFaceHint(poll.hint || "Look at the Heirloom app on your computer.");
          return;
        }
        if (poll.status === "error" || poll.status === "rejected") {
          setFaceHint("Couldn't show the face this time. The twin can still talk.");
          return;
        }
      }
      setFaceHint(local ? "Still working on your computer." : "That took too long. Try again.");
    } catch (_) {
      setFaceHint("Couldn't show the face this time. The twin can still talk.");
    }
  };

  const send = async (text) => {
    if (!text.trim() || !conv || pending) return;
    const myMsg = { role: "user", content: text, ts: new Date().toISOString() };
    setConv((c) => ({ ...c, messages: [...(c.messages || []), myMsg] }));
    setInput("");
    setPending(true);
    setStreaming("");
    setFaceHint("");

    let full = "";
    await streamSSE(
      "/twin/message",
      { conversation_id: conv.conversation_id, message: text },
      (chunk) => {
        full += chunk;
        setStreaming(full);
      },
      () => {
        const newIdx = (conv.messages?.length || 0) + 1;
        setConv((c) => ({
          ...c,
          messages: [
            ...(c.messages || []),
            { role: "assistant", content: full, ts: new Date().toISOString() },
          ],
        }));
        setStreaming("");
        setPending(false);
        if (full) {
          speak(full);
          playFace(newIdx, full);
        }
      },
      () => {
        setStreaming("");
        setPending(false);
      },
    );
  };

  const messages = conv?.messages || [];
  const recent = messages.slice(-8);

  return (
    <div
      className="min-h-screen flex flex-col"
      data-testid="twin-mini-root"
      style={{ background: "var(--bg-base)", color: "var(--text-primary)" }}
    >
      <header
        className="flex items-center justify-between gap-3 px-4 py-3"
        style={{ borderBottom: "1px solid var(--border-default)" }}
      >
        <div>
          <div className="overline">your twin</div>
          <p className="font-serif text-lg leading-tight">Just you and your twin</p>
        </div>
        <Link
          to="/twin"
          data-testid="twin-mini-full"
          className="text-xs px-3 py-1.5 rounded-sm"
          style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
        >
          Full window
        </Link>
      </header>

      <div
        className="relative mx-4 mt-3 overflow-hidden rounded-sm"
        style={{
          height: 220,
          background: "var(--surface-elev, rgba(255,245,230,0.04))",
          border: "1px solid var(--border-default)",
        }}
        data-testid="twin-mini-face"
      >
        {portrait && !videoUrl && (
          <img
            src={portrait}
            alt="Your twin"
            className="absolute inset-0 w-full h-full object-cover"
          />
        )}
        {videoUrl && (
          <video
            key={videoUrl}
            src={videoUrl}
            autoPlay
            playsInline
            className="absolute inset-0 w-full h-full object-cover"
            onEnded={() => setVideoUrl("")}
          />
        )}
        {!portrait && !videoUrl && (
          <div className="absolute inset-0 flex items-center justify-center text-sm" style={{ color: "var(--text-muted)" }}>
            Your twin
          </div>
        )}
        <div
          className="absolute left-3 bottom-3 text-[10px] tracking-widest uppercase"
          style={{ color: "var(--accent)" }}
          data-testid="twin-mini-status"
        >
          {pending ? "thinking…" : speaking ? "speaking" : faceHint || "idle"}
        </div>
      </div>
      {faceHint && (
        <p className="px-4 pt-2 text-xs" style={{ color: "var(--text-muted)" }} data-testid="twin-mini-face-hint">
          {faceHint}
        </p>
      )}

      <div ref={feedRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3" data-testid="twin-mini-feed">
        {recent.length === 0 && !streaming && (
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
            Ask anything. Your twin can still do tasks — mail, calendar, the computer — from this small window.
          </p>
        )}
        {recent.map((m, i) => (
          <div key={`${m.ts || "m"}-${i}`} data-testid={`twin-mini-msg-${i}`}>
            <div className="overline mb-0.5">{m.role === "assistant" ? "twin" : "you"}</div>
            <p
              className="text-sm leading-relaxed"
              style={{ color: m.role === "assistant" ? "var(--text-primary)" : "var(--text-secondary)" }}
            >
              {m.content}
            </p>
          </div>
        ))}
        {streaming && (
          <div>
            <div className="overline mb-0.5">twin</div>
            <p className="text-sm leading-relaxed">
              {streaming}
              <span className="inline-block w-1.5 h-4 ml-1 align-middle animate-pulse" style={{ background: "var(--accent)" }} />
            </p>
          </div>
        )}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
        className="px-4 pb-4 pt-2"
        style={{ borderTop: "1px solid var(--border-default)" }}
      >
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(input);
              }
            }}
            rows={2}
            disabled={pending || !conv}
            placeholder="Tell your twin what to do…"
            data-testid="twin-mini-input"
            className="flex-1 bg-transparent outline-none resize-none text-sm leading-relaxed"
            style={{ color: "var(--text-primary)" }}
          />
          <button
            type="submit"
            disabled={pending || !input.trim()}
            data-testid="twin-mini-send"
            className="inline-flex items-center gap-1 px-3 py-2 text-sm rounded-sm disabled:opacity-50"
            style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
          >
            {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
            Send
          </button>
        </div>
        <p className="mt-2 text-[10px] tracking-widest uppercase flex items-center gap-1" style={{ color: "var(--text-muted)" }}>
          <Volume2 className="h-3 w-3" />
          Replies speak aloud. The live face is strongest in the Heirloom app on your computer.
        </p>
      </form>
    </div>
  );
}
