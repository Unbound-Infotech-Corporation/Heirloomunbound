import { useEffect, useRef, useState } from "react";
import { Camera, Loader2, Mic, Square, Upload } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

/**
 * Mobile Quick Capture — two paths, both explicitly mobile-first:
 *
 *   1. **Voice memo** — MediaRecorder captures a WebM/Opus blob, uploaded to
 *      `/api/entries/voice` (existing voice-journal endpoint). One tap starts,
 *      another tap stops + uploads.
 *
 *   2. **Photo** — <input type="file" accept="image/*" capture="environment">
 *      opens the phone's rear-camera directly. Uploaded to `/api/photos`.
 *
 * The Capture flow is deliberately dead-simple — big buttons, no forms.
 * If the user is offline, the service-worker returns a 503 stub and we show
 * a queue notice; upload can be retried once online.
 */
export default function MobileCapture() {
  const [recording, setRecording] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [lastResult, setLastResult] = useState(null);
  const recorderRef = useRef(null);
  const chunksRef = useRef([]);
  const streamRef = useRef(null);
  const timerRef = useRef(null);

  useEffect(() => () => {
    if (timerRef.current) clearInterval(timerRef.current);
    if (streamRef.current) streamRef.current.getTracks().forEach((t) => t.stop());
  }, []);

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const rec = new MediaRecorder(stream, { mimeType: "audio/webm;codecs=opus" });
      chunksRef.current = [];
      rec.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      rec.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        streamRef.current.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
        await uploadVoice(blob);
      };
      rec.start();
      recorderRef.current = rec;
      setRecording(true);
      setElapsed(0);
      timerRef.current = setInterval(() => setElapsed((n) => n + 1), 1000);
    } catch (e) {
      toast.error(e.message || "Microphone permission denied");
    }
  };

  const stopRecording = () => {
    if (recorderRef.current && recorderRef.current.state !== "inactive") {
      recorderRef.current.stop();
    }
    if (timerRef.current) clearInterval(timerRef.current);
    setRecording(false);
  };

  const uploadVoice = async (blob) => {
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", blob, `memo-${Date.now()}.webm`);
      // The voice-journal endpoint transcribes + saves as an archive entry.
      const { data } = await api.post("/entries/voice", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setLastResult({ kind: "voice", ...data });
      toast.success("Memo captured");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const uploadPhoto = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("caption", "");
      const { data } = await api.post("/photos", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setLastResult({ kind: "photo", ...data });
      toast.success("Photo captured");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Upload failed");
    } finally {
      setUploading(false);
      event.target.value = ""; // let the same file be picked again
    }
  };

  const mmSs = (sec) => `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;

  return (
    <div className="max-w-md mx-auto space-y-6" data-testid="mobile-capture">
      <div className="text-center pt-2">
        <div className="overline mb-2">Quick Capture</div>
        <h1 className="font-serif text-4xl" style={{ color: "var(--text-primary)" }}>
          Drop a memory
        </h1>
        <p className="text-sm mt-2" style={{ color: "var(--text-muted)" }}>
          Voice notes get transcribed. Photos go straight into your archive.
        </p>
      </div>

      {/* Voice recorder */}
      <div
        className="rounded-md border p-6 text-center"
        style={{ background: "var(--surface)", borderColor: "var(--border-default)" }}
        data-testid="capture-voice-card"
      >
        {recording ? (
          <>
            <div className="overline mb-2" style={{ color: "#c25b3f" }}>recording</div>
            <div className="font-serif text-4xl mb-4" style={{ color: "var(--text-primary)" }} data-testid="capture-timer">
              {mmSs(elapsed)}
            </div>
            <button
              onClick={stopRecording}
              data-testid="capture-stop-btn"
              className="w-20 h-20 rounded-full flex items-center justify-center mx-auto"
              style={{ background: "#c25b3f", color: "white" }}
            >
              <Square className="w-7 h-7" />
            </button>
          </>
        ) : (
          <>
            <div className="font-medium mb-3" style={{ color: "var(--text-primary)" }}>
              Voice memo
            </div>
            <button
              onClick={startRecording}
              disabled={uploading}
              data-testid="capture-record-btn"
              className="w-20 h-20 rounded-full flex items-center justify-center mx-auto"
              style={{ background: "var(--accent)", color: "var(--surface)" }}
            >
              {uploading ? <Loader2 className="w-7 h-7 animate-spin" /> : <Mic className="w-7 h-7" />}
            </button>
            <p className="text-xs mt-4" style={{ color: "var(--text-muted)" }}>
              Tap to record. Tap Stop to save + transcribe.
            </p>
          </>
        )}
      </div>

      {/* Photo capture */}
      <label
        htmlFor="mobile-photo-input"
        className="block rounded-md border p-6 cursor-pointer"
        style={{ background: "var(--surface)", borderColor: "var(--border-default)" }}
        data-testid="capture-photo-card"
      >
        <div className="flex items-center gap-4">
          <div
            className="w-14 h-14 rounded-full flex items-center justify-center"
            style={{ background: "var(--surface-elev)", color: "var(--accent)" }}
          >
            <Camera className="w-6 h-6" />
          </div>
          <div>
            <div className="font-medium" style={{ color: "var(--text-primary)" }}>Take a photo</div>
            <div className="text-xs" style={{ color: "var(--text-muted)" }}>Rear camera opens automatically</div>
          </div>
        </div>
        <input
          id="mobile-photo-input"
          type="file"
          accept="image/*"
          capture="environment"
          onChange={uploadPhoto}
          disabled={uploading || recording}
          className="hidden"
          data-testid="capture-photo-input"
        />
      </label>

      {lastResult && (
        <div
          className="rounded-md p-4 text-sm flex items-start gap-3"
          style={{ background: "var(--surface-elev)", color: "var(--text-secondary)" }}
          data-testid="capture-last-result"
        >
          <Upload className="w-4 h-4 mt-0.5" style={{ color: "var(--accent)" }} />
          <div>
            <div style={{ color: "var(--text-primary)" }}>
              {lastResult.kind === "voice" ? "Voice memo saved" : "Photo saved"}
            </div>
            {lastResult.kind === "voice" && lastResult.entry?.content && (
              <div className="text-xs mt-1 italic" style={{ color: "var(--text-muted)" }}>
                &ldquo;{String(lastResult.entry.content).slice(0, 100)}…&rdquo;
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
