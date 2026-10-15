import { useCallback, useEffect, useState } from "react";
import { api } from "../../lib/api";
import { audioStreamLine, feedbackLabel } from "../../lib/observer";

const VOTES = [
  ["thats_me", "That's me"],
  ["not_me", "Not me"],
  ["never", "Never learn this"],
];

export default function ObserverPanel({ showIntro = false }) {
  const [status, setStatus] = useState(null);
  const [notes, setNotes] = useState([]);
  const [markdown, setMarkdown] = useState("");
  const [closed, setClosed] = useState(false);
  const [busy, setBusy] = useState("");

  const load = useCallback(() => {
    api.get("/observer/status")
      .then(({ data }) => {
        setStatus(data);
        if (!data?.enabled) {
          setClosed(true);
          return;
        }
        setClosed(false);
        return api.get("/observer/digest").then(({ data: digest }) => {
          setNotes(digest.notes || []);
          setMarkdown(digest.markdown || "");
        });
      })
      .catch(() => setClosed(true));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const setPaused = (paused) => {
    setBusy(paused ? "pause" : "resume");
    api.post(paused ? "/observer/pause" : "/observer/resume")
      .then(() => load())
      .finally(() => setBusy(""));
  };

  const setAudio = (key, enabled) => {
    setBusy(key);
    api.put("/observer/audio", { [key]: enabled })
      .then(() => load())
      .finally(() => setBusy(""));
  };

  const vote = (noteId, choice) => {
    setBusy(noteId);
    api.post("/observer/feedback", { note_id: noteId, vote: choice })
      .then(() => load())
      .finally(() => setBusy(""));
  };

  if (closed) {
    return (
      <p className="text-sm" data-testid="observer-closed" style={{ color: "var(--text-muted)" }}>
        Observer is off on this server.
      </p>
    );
  }

  return (
    <div data-testid="observer-panel">
      {showIntro ? (
        <p className="text-sm mb-6" style={{ color: "var(--text-muted)" }}>
          The box watches the capture card and keeps notes, not footage. Heirs never see clips.
        </p>
      ) : null}
      <section className="surface p-5 mb-6" data-testid="observer-status">
        <div className="overline mb-2">capture</div>
        <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
          {status
            ? `${status.device || "no device"} · ${status.signal || "unknown"} · ${status.fps || 0} fps · ${status.model || "ocr"} · ${status.paused ? "paused" : "watching"}`
            : "Checking…"}
        </p>
        <div className="mt-3 flex gap-2">
          <button
            type="button"
            className="text-sm px-3 py-1.5 rounded-sm"
            style={{ border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
            data-testid="observer-pause"
            disabled={busy === "pause" || status?.paused}
            onClick={() => setPaused(true)}
          >
            Pause
          </button>
          <button
            type="button"
            className="text-sm px-3 py-1.5 rounded-sm"
            style={{ border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
            data-testid="observer-resume"
            disabled={busy === "resume" || !status?.paused}
            onClick={() => setPaused(false)}
          >
            Resume
          </button>
        </div>
        {status?.audio ? (
          <div className="mt-4" data-testid="observer-audio">
            <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
              {audioStreamLine(status.audio.system, "System audio")}
            </p>
            <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
              {audioStreamLine(status.audio.mic, "Microphone")}
            </p>
            <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
              Transcripts only. The two streams stay separate.
            </p>
            <div className="mt-3 flex gap-4">
              <label className="text-sm" style={{ color: "var(--text-primary)" }}>
                <input
                  type="checkbox"
                  className="mr-2"
                  data-testid="observer-audio-system"
                  checked={!!status.audio.system?.enabled}
                  disabled={busy === "system"}
                  onChange={(event) => setAudio("system", event.target.checked)}
                />
                System audio
              </label>
              <label className="text-sm" style={{ color: "var(--text-primary)" }}>
                <input
                  type="checkbox"
                  className="mr-2"
                  data-testid="observer-audio-mic"
                  checked={!!status.audio.mic?.enabled}
                  disabled={busy === "mic"}
                  onChange={(event) => setAudio("mic", event.target.checked)}
                />
                Microphone
              </label>
            </div>
          </div>
        ) : null}
      </section>
      <section className="surface p-5" data-testid="observer-digest">
        <div className="overline mb-2">What I learned about you</div>
        {notes.length === 0 ? (
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>Nothing new.</p>
        ) : (
          <ul className="space-y-4">
            {notes.map((note) => (
              <li key={note.id} data-testid={`observer-note-${note.id}`}>
                <p className="text-sm" style={{ color: "var(--text-primary)" }}>{note.text}</p>
                <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                  {note.kind} · {note.status} · {Number(note.confidence || 0).toFixed(2)}
                </p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {VOTES.map(([choice, label]) => (
                    <button
                      key={choice}
                      type="button"
                      className="text-xs px-2 py-1 rounded-sm"
                      style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
                      data-testid={`observer-${choice}-${note.id}`}
                      disabled={busy === note.id}
                      onClick={() => vote(note.id, choice)}
                    >
                      {label || feedbackLabel(choice)}
                    </button>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        )}
        {markdown ? (
          <pre className="mt-4 text-xs whitespace-pre-wrap" data-testid="observer-digest-markdown" style={{ color: "var(--text-secondary)" }}>
            {markdown}
          </pre>
        ) : null}
      </section>
    </div>
  );
}
