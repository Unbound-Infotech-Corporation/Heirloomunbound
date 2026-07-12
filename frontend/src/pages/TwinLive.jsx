import axios from "axios";
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { Eye, Radio } from "lucide-react";
import { usePageMeta } from "../lib/usePageMeta";
import { isTester } from "../lib/tester";

const BACKEND = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND}/api`;

/* ---------- Public live-stream twin page ----------
   URL:    /twin/live/:handle
   Modes:  default (full chrome), ?obs=1 (avatar-only, transparent, OBS-ready)
   Stream: SSE from /api/live/:handle/stream — pushes new turns + avatar URLs
*/

const MAX_TURNS = 15;

function PortraitAvatar({ avatarUrl, videoUrl, speaking, onVideoEnded }) {
  const videoRef = useRef(null);
  useEffect(() => {
    if (!videoUrl || !videoRef.current) return;
    videoRef.current.src = videoUrl;
    videoRef.current.play().catch(() => {});
  }, [videoUrl]);

  return (
    <div
      className="relative w-full h-full overflow-hidden rounded-md"
      style={{ background: "transparent" }}
      data-testid="live-avatar"
    >
      {!speaking && avatarUrl && (
        <img
          src={avatarUrl}
          alt="twin portrait"
          className="absolute inset-0 w-full h-full object-cover"
          style={{ filter: "saturate(0.95)" }}
        />
      )}
      <video
        ref={videoRef}
        className={`absolute inset-0 w-full h-full object-cover transition-opacity duration-300 ${
          speaking ? "opacity-100" : "opacity-0"
        }`}
        autoPlay
        playsInline
        onEnded={onVideoEnded}
      />
    </div>
  );
}

export default function TwinLive() {
  const { handle } = useParams();
  const [params] = useSearchParams();
  const obsMode = params.get("obs") === "1";

  const [profile, setProfile] = useState(null);
  const [error, setError] = useState(null);
  const [turns, setTurns] = useState([]);
  const [videoUrl, setVideoUrl] = useState(null);
  const [speaking, setSpeaking] = useState(false);
  const [live, setLive] = useState(false);
  const esRef = useRef(null);

  usePageMeta({
    title: profile ? `${profile.name} · live with their twin` : "Heirloom live twin",
    description: "Watch a digital twin in real time — Heirloom by Unbound Infotech.",
  });

  // Initial profile + history
  useEffect(() => {
    if (!handle) return;
    let cancelled = false;
    Promise.all([
      axios.get(`${API}/live/${handle}/profile`),
      axios.get(`${API}/live/${handle}/recent?limit=${MAX_TURNS}`),
    ])
      .then(([p, r]) => {
        if (cancelled) return;
        setProfile(p.data);
        setTurns((r.data?.messages || []).slice(-MAX_TURNS));
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err.response?.data?.detail || err.message || "Couldn't load this twin.");
      });
    return () => {
      cancelled = true;
    };
  }, [handle]);

  // SSE subscription
  useEffect(() => {
    if (!handle || !profile) return;
    const url = `${API}/live/${handle}/stream`;
    const es = new EventSource(url);
    esRef.current = es;

    es.addEventListener("hello", () => setLive(true));
    es.addEventListener("turn", (e) => {
      try {
        const data = JSON.parse(e.data);
        setTurns((prev) => {
          const next = [
            ...prev,
            { role: data.role, content: data.content, ts: data.ts },
          ];
          return next.slice(-MAX_TURNS);
        });
      } catch {
        /* ignore parse errors */
      }
    });
    es.addEventListener("avatar", (e) => {
      try {
        const data = JSON.parse(e.data);
        if (!data.video_url) return;
        setSpeaking(true);
        setVideoUrl(data.video_url);
      } catch {
        /* ignore */
      }
    });
    es.onerror = () => setLive(false);

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [handle, profile]);

  const recent = useMemo(() => turns.slice(-MAX_TURNS), [turns]);

  if (error) {
    return (
      <div
        className="min-h-screen flex items-center justify-center px-6"
        style={{ background: "var(--bg-base)" }}
      >
        <div className="max-w-md text-center" data-testid="live-error">
          <div className="overline mb-3" style={{ color: "var(--text-muted)" }}>
            heirloom · live
          </div>
          <h1 className="font-serif text-3xl mb-3">Nobody home.</h1>
          <p style={{ color: "var(--text-secondary)" }}>{error}</p>
          <a
            href="/"
            className="inline-block mt-6 text-sm underline"
            style={{ color: "var(--accent)" }}
          >
            Go to Heirloom →
          </a>
        </div>
      </div>
    );
  }

  if (!profile) {
    return (
      <div
        className="min-h-screen flex items-center justify-center"
        style={{ background: "var(--bg-base)", color: "var(--text-muted)" }}
        data-testid="live-loading"
      >
        Loading…
      </div>
    );
  }

  // ---------- OBS MODE ----------
  if (obsMode) {
    return (
      <div
        className="w-screen h-screen overflow-hidden"
        style={{ background: "transparent" }}
        data-testid="live-obs"
      >
        <PortraitAvatar
          avatarUrl={profile.avatar_url}
          videoUrl={videoUrl}
          speaking={speaking}
          onVideoEnded={() => setSpeaking(false)}
        />
      </div>
    );
  }

  // ---------- DEFAULT VIEWER ----------
  return (
    <div
      className="min-h-screen"
      style={{ background: "var(--bg-base)" }}
      data-testid="live-root"
    >
      {/* header */}
      <header
        className="px-6 sm:px-10 py-5 flex items-center justify-between"
        style={{ borderBottom: "1px solid var(--border-default)" }}
      >
        <div>
          <div className="overline" style={{ color: "var(--text-muted)" }}>
            heirloom · live
          </div>
          <h1
            className="font-serif text-2xl sm:text-3xl mt-1"
            style={{ color: "var(--text-primary)" }}
            data-testid="live-name"
          >
            {profile.name}
          </h1>
          {profile.tagline && (
            <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>
              {profile.tagline}
            </p>
          )}
        </div>
        <div className="flex items-center gap-4">
          <div
            className="inline-flex items-center gap-2 text-xs px-3 py-1 rounded-full"
            style={{
              background: live ? "rgba(125,160,111,0.16)" : "rgba(126,116,104,0.16)",
              color: live ? "var(--ok)" : "var(--text-muted)",
              border: `1px solid ${live ? "var(--ok)" : "var(--border-default)"}`,
            }}
            data-testid="live-status-pill"
          >
            <Radio className="h-3 w-3" />
            {live ? "live" : "connecting…"}
          </div>
          <div
            className="inline-flex items-center gap-1 text-xs"
            style={{ color: "var(--text-muted)" }}
            data-testid="live-viewer-count"
          >
            <Eye className="h-3 w-3" />
            watching now
          </div>
        </div>
      </header>

      <main className="px-6 sm:px-10 py-8 grid lg:grid-cols-[1.1fr_1fr] gap-8 max-w-6xl mx-auto">
        {/* Avatar */}
        <div
          className="rounded-md overflow-hidden aspect-square w-full"
          style={{ background: "var(--bg-surface)", border: "1px solid var(--border-default)" }}
        >
          <PortraitAvatar
            avatarUrl={profile.avatar_url}
            videoUrl={videoUrl}
            speaking={speaking}
            onVideoEnded={() => setSpeaking(false)}
          />
        </div>

        {/* Transcript */}
        <div className="flex flex-col">
          <div
            className="overline mb-3"
            style={{ color: "var(--text-muted)" }}
          >
            LIVE TRANSCRIPT
          </div>
          <div
            className="flex-1 overflow-y-auto space-y-4 pr-2"
            style={{ maxHeight: "70vh" }}
            data-testid="live-transcript"
          >
            {recent.length === 0 ? (
              <p
                className="text-sm italic"
                style={{ color: "var(--text-muted)" }}
              >
                Quiet right now. Waiting for the next exchange…
              </p>
            ) : (
              recent.map((m, i) => (
                <div
                  key={`${m.ts || "noTs"}-${i}`}
                  className={`text-sm ${m.role === "user" ? "" : "pl-4"}`}
                  data-testid={`live-turn-${m.role}`}
                >
                  <div
                    className="overline mb-1"
                    style={{
                      color: m.role === "user" ? "var(--accent)" : "var(--text-muted)",
                    }}
                  >
                    {m.role === "user" ? profile.name.toUpperCase() : "TWIN"}
                  </div>
                  <div style={{ color: "var(--text-primary)" }}>{m.content}</div>
                </div>
              ))
            )}
          </div>
        </div>
      </main>

      <footer
        className="px-6 sm:px-10 py-6 text-xs mt-12"
        style={{
          color: "var(--text-muted)",
          borderTop: "1px solid var(--border-default)",
        }}
      >
        Built with{" "}
        <a
          href="/"
          className="underline"
          style={{ color: "var(--accent)" }}
        >
          Heirloom
        </a>{" "}
        by Unbound Infotech.{" "}
        {!isTester() && (
          <>
            Want your own twin you can stream?{" "}
            <a
              href="/buy"
              className="underline"
              style={{ color: "var(--accent)" }}
            >
              $79, lifetime
            </a>
            .{" "}
          </>
        )}
        Streamers: use{" "}
        <code style={{ color: "var(--text-secondary)" }}>
          /twin/live/{profile.handle}?obs=1
        </code>{" "}
        as a Browser Source in OBS.
      </footer>
    </div>
  );
}
