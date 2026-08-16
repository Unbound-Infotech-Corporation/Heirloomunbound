import { useEffect, useRef, useState } from "react";
import { ArrowRight, Loader2, Volume2 } from "lucide-react";
import { Link } from "react-router-dom";
import { api, streamSSE } from "@/lib/api";
import { ToyDesk, ToyKnob, ToyPorthole } from "@/components/ToyPlayset";

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
      className="min-h-screen flex flex-col p-3"
      data-testid="twin-mini-root"
      style={{ background: "var(--bg-base)", color: "var(--text-primary)" }}
    >
      <ToyDesk className="flex-1 flex flex-col min-h-0">
      <header className="flex items-center justify-between gap-3 pb-3">
        <div>
          <div className="toy-kicker">your twin</div>
          <p className="toy-title text-xl leading-tight">Just you and your twin</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap justify-end">
          <ToyKnob
            color="sunflower"
            testid="twin-mini-look-screen"
            disabled={pending || !conv}
            onClick={() => send("Look at my screen and help me with whatever is on it.")}
            title="Looks at your home computer. The picture is deleted after."
          >
            Look at my screen
          </ToyKnob>
          <Link
            to="/twin"
            data-testid="twin-mini-full"
            className="toy-bead toy-knob-cream"
          >
            Full window
          </Link>
        </div>
      </header>

      <div className="flex justify-center my-2" data-testid="twin-mini-face">
        <ToyPorthole
          src={portrait}
          videoSrc={videoUrl}
          status={pending ? "thinking…" : speaking ? "speaking" : faceHint || "idle"}
          onVideoEnded={() => setVideoUrl("")}
        />
      </div>
      {faceHint && (
        <p className="pt-2 text-sm toy-copy" data-testid="twin-mini-face-hint">
          {faceHint}
        </p>
      )}

      <div ref={feedRef} className="flex-1 overflow-y-auto py-3 space-y-3 min-h-0" data-testid="twin-mini-feed">
        {recent.length === 0 && !streaming && (
          <p className="toy-copy">
            Ask anything. Your twin can still do tasks — mail, calendar, the computer — from this small window.
          </p>
        )}
        {recent.map((m, i) => (
          <div key={`${m.ts || "m"}-${i}`} data-testid={`twin-mini-msg-${i}`}>
            <div className="toy-kicker mb-0.5">{m.role === "assistant" ? "twin" : "you"}</div>
            <p className="toy-copy">
              {m.content}
            </p>
          </div>
        ))}
        {streaming && (
          <div>
            <div className="toy-kicker mb-0.5">twin</div>
            <p className="toy-copy">
              {streaming}
              <span className="inline-block w-1.5 h-4 ml-1 align-middle animate-pulse" style={{ background: "var(--toy-tomato)" }} />
            </p>
          </div>
        )}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
        className="pt-2"
      >
        <div className="toy-composer">
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
          />
          <ToyKnob
            color="tomato"
            className="toy-send"
            type="submit"
            disabled={pending || !input.trim()}
            testid="twin-mini-send"
          >
            {pending ? <Loader2 className="h-6 w-6 animate-spin" /> : <ArrowRight className="h-6 w-6" />}
          </ToyKnob>
        </div>
        <p className="mt-3 toy-kicker flex items-center gap-1">
          <Volume2 className="h-3 w-3" />
          Replies speak aloud. The live face is strongest in the Heirloom app on your computer.
        </p>
      </form>
      </ToyDesk>
    </div>
  );
}
