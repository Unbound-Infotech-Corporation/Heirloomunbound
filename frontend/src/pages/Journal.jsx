import { useEffect, useRef, useState } from "react";
import { Loader2, Mic, Square } from "lucide-react";
import { api, API_BASE } from "../lib/api";

export default function Journal() {
  const [recording, setRecording] = useState(false);
  const [audioBlob, setAudioBlob] = useState(null);
  const [audioUrl, setAudioUrl] = useState(null);
  const [title, setTitle] = useState("");
  const [transcript, setTranscript] = useState("");
  const [transcribing, setTranscribing] = useState(false);
  const [savedEntry, setSavedEntry] = useState(null);
  const [elapsed, setElapsed] = useState(0);
  const [recent, setRecent] = useState([]);
  const [inputDeviceId, setInputDeviceId] = useState("default");
  const recorderRef = useRef(null);
  const chunksRef = useRef([]);
  const timerRef = useRef(null);

  const loadRecent = () =>
    api
      .get("/archive", { params: { type: "voice", limit: 8 } })
      .then(({ data }) => setRecent(data))
      .catch(() => setRecent([]));

  useEffect(() => {
    loadRecent();
    api
      .get("/studio/audio")
      .then(({ data }) => setInputDeviceId(data?.settings?.input_device_id || "default"))
      .catch(() => {});
  }, []);

  const start = async () => {
    try {
      const audio =
        inputDeviceId && inputDeviceId !== "default"
          ? { deviceId: { exact: inputDeviceId } }
          : true;
      const stream = await navigator.mediaDevices.getUserMedia({ audio });
      const mr = new MediaRecorder(stream, { mimeType: "audio/webm" });
      chunksRef.current = [];
      mr.ondataavailable = (e) => chunksRef.current.push(e.data);
      mr.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        setAudioBlob(blob);
        setAudioUrl(URL.createObjectURL(blob));
        stream.getTracks().forEach((t) => t.stop());
      };
      mr.start();
      recorderRef.current = mr;
      setRecording(true);
      setElapsed(0);
      setSavedEntry(null);
      setTranscript("");
      timerRef.current = setInterval(() => setElapsed((e) => e + 1), 1000);
    } catch (err) {
      alert("Microphone permission denied or unsupported browser.");
    }
  };

  const stop = () => {
    recorderRef.current?.stop();
    clearInterval(timerRef.current);
    setRecording(false);
  };

  const transcribe = async () => {
    if (!audioBlob) return;
    setTranscribing(true);
    const fd = new FormData();
    fd.append("file", audioBlob, "journal.webm");
    fd.append("save_to_archive", "true");
    if (title) fd.append("title", title);
    try {
      const res = await fetch(`${API_BASE}/voice/transcribe`, {
        method: "POST",
        credentials: "include",
        body: fd,
      });
      const data = await res.json();
      setTranscript(data.text || "");
      setSavedEntry(data.entry || null);
      loadRecent();
    } catch (e) {
      console.error(e);
    } finally {
      setTranscribing(false);
    }
  };

  const reset = () => {
    setAudioBlob(null);
    setAudioUrl(null);
    setTranscript("");
    setSavedEntry(null);
    setTitle("");
    setElapsed(0);
  };

  const mmss = (s) => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

  return (
    <div className="px-4 sm:px-8 lg:px-16 py-12 max-w-4xl" data-testid="journal-root">
      <header className="mb-12">
        <div className="overline mb-3">voice journal</div>
        <h1 className="font-serif text-4xl lg:text-5xl font-light tracking-tight">
          Speak. We'll listen.
        </h1>
        <p className="mt-3 text-base max-w-xl" style={{ color: "var(--text-secondary)" }}>
          Press record, talk for as long as feels right, then we transcribe and tuck it into your archive.
        </p>
      </header>

      <div className="surface p-12 lg:p-16 flex flex-col items-center text-center mb-12 grain-overlay">
        <div className="relative h-32 w-32 flex items-center justify-center mb-8">
          {recording && (
            <span
              className="absolute inset-0 rounded-full record-ring"
              style={{ background: "var(--accent-muted)" }}
            />
          )}
          <button
            onClick={recording ? stop : start}
            disabled={transcribing}
            data-testid="record-button"
            className="relative h-24 w-24 rounded-full flex items-center justify-center transition-colors"
            style={{
              background: recording ? "var(--danger)" : "var(--accent)",
              color: "var(--text-inverse)",
            }}
          >
            {recording ? <Square className="h-7 w-7" /> : <Mic className="h-8 w-8" />}
          </button>
        </div>
        <div className="font-mono text-2xl mb-2" data-testid="record-timer" style={{ color: "var(--text-primary)" }}>
          {mmss(elapsed)}
        </div>
        <div className="overline">{recording ? "recording" : audioBlob ? "ready" : "press to begin"}</div>

        {audioUrl && !recording && (
          <div className="mt-8 w-full max-w-md space-y-5">
            <audio src={audioUrl} controls className="w-full" data-testid="record-playback" />
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Give this journal a quiet title (optional)"
              data-testid="journal-title-input"
              className="w-full px-4 py-3 text-sm bg-transparent rounded-sm"
              style={{
                border: "1px solid var(--border-default)",
                color: "var(--text-primary)",
              }}
            />
            <div className="flex gap-3 justify-center">
              <button
                onClick={transcribe}
                disabled={transcribing}
                data-testid="transcribe-button"
                className="inline-flex items-center gap-2 px-6 py-3 text-sm font-medium rounded-sm"
                style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
              >
                {transcribing && <Loader2 className="h-4 w-4 animate-spin" />}
                {transcribing ? "Transcribing…" : "Transcribe & save"}
              </button>
              <button
                onClick={reset}
                data-testid="reset-record"
                className="px-6 py-3 text-sm rounded-sm"
                style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
              >
                Discard
              </button>
            </div>
          </div>
        )}
      </div>

      {transcript && (
        <div className="surface p-8 mb-12">
          <div className="overline mb-3">transcript</div>
          <p className="text-base leading-relaxed whitespace-pre-wrap" style={{ color: "var(--text-primary)" }} data-testid="transcript-text">
            {transcript}
          </p>
          {savedEntry && (
            <div className="mt-4 text-xs font-mono" style={{ color: "var(--text-muted)" }}>
              saved as: {savedEntry.entry_id}
            </div>
          )}
        </div>
      )}

      <section>
        <div className="overline mb-4">recent voice entries</div>
        {recent.length === 0 ? (
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
            No voice entries yet. Press record above.
          </p>
        ) : (
          <div className="space-y-4">
            {recent.map((e) => (
              <div key={e.entry_id} className="surface p-5" data-testid={`recent-${e.entry_id}`}>
                <div className="flex justify-between items-baseline mb-2">
                  <div className="font-serif text-lg">{e.title}</div>
                  <div className="font-mono text-xs" style={{ color: "var(--text-muted)" }}>
                    {new Date(e.created_at).toLocaleString()}
                  </div>
                </div>
                <p className="text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                  {e.content.slice(0, 280)}{e.content.length > 280 ? "…" : ""}
                </p>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
