import { useEffect, useRef, useState } from "react";
import { Camera, CloudOff, Loader2, Mic, RefreshCw, Square, Upload } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { count as queueCount, enqueue, flush } from "@/lib/offlineQueue";

/**
 * Mobile Quick Capture — voice memos + photos.
 *
 * When the browser is offline (or an upload fails), the blob is queued in
 * IndexedDB and auto-flushed the next time we detect `online`. A small
 * pending-count row lets the user manually retry too.
 */
export default function MobileCapture() {
  const [recording, setRecording] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [lastResult, setLastResult] = useState(null);
  const [online, setOnline] = useState(navigator.onLine);
  const [pending, setPending] = useState(0);
  const [flushing, setFlushing] = useState(false);
  const recorderRef = useRef(null);
  const chunksRef = useRef([]);
  const streamRef = useRef(null);
  const timerRef = useRef(null);

  // Track online status + auto-flush queue on reconnect.
  useEffect(() => {
    const refresh = async () => setPending(await queueCount());
    refresh();
    const onOnline = async () => {
      setOnline(true);
      const p = await queueCount();
      if (p > 0) doFlush();
    };
    const onOffline = () => setOnline(false);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => () => {
    if (timerRef.current) clearInterval(timerRef.current);
    if (streamRef.current) streamRef.current.getTracks().forEach((t) => t.stop());
  }, []);

  const doFlush = async () => {
    setFlushing(true);
    try {
      const { succeeded, failed } = await flush(api);
      setPending(await queueCount());
      if (succeeded > 0) toast.success(`${succeeded} queued item${succeeded === 1 ? "" : "s"} uploaded`);
      if (failed > 0 && succeeded === 0) toast.error("Still can't reach the server");
    } finally {
      setFlushing(false);
    }
  };

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
        await handleVoice(blob);
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

  const handleVoice = async (blob) => {
    if (!navigator.onLine) {
      try {
        await enqueue({ kind: "voice", blob, filename: `memo-${Date.now()}.webm` });
        setPending(await queueCount());
        toast.success("Saved offline — will upload when you're back online");
      } catch (e) { toast.error(e.message || "Couldn't queue offline"); }
      return;
    }
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", blob, `memo-${Date.now()}.webm`);
      const { data } = await api.post("/entries/voice", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setLastResult({ kind: "voice", ...data });
      toast.success("Memo captured");
    } catch (e) {
      // Any failure while marked online → queue it and keep going.
      try {
        await enqueue({ kind: "voice", blob, filename: `memo-${Date.now()}.webm` });
        setPending(await queueCount());
        toast.success("Upload failed — saved for retry");
      } catch { toast.error(e?.response?.data?.detail || "Upload failed"); }
    } finally {
      setUploading(false);
    }
  };

  const handlePhoto = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (!navigator.onLine) {
      try {
        await enqueue({ kind: "photo", blob: file, filename: file.name });
        setPending(await queueCount());
        toast.success("Saved offline — will upload when you're back online");
      } catch (e) { toast.error(e.message || "Couldn't queue offline"); }
      event.target.value = "";
      return;
    }
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
      try {
        await enqueue({ kind: "photo", blob: file, filename: file.name });
        setPending(await queueCount());
        toast.success("Upload failed — saved for retry");
      } catch { toast.error(e?.response?.data?.detail || "Upload failed"); }
    } finally {
      setUploading(false);
      event.target.value = "";
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

      {/* Offline / queue status */}
      {(!online || pending > 0) && (
        <div
          className="rounded-md border p-3 flex items-center gap-3 text-sm"
          style={{
            background: "var(--surface-elev)",
            borderColor: online ? "var(--border-default)" : "#c25b3f",
            color: "var(--text-secondary)",
          }}
          data-testid="offline-banner"
        >
          <CloudOff className="w-4 h-4" style={{ color: online ? "var(--text-muted)" : "#c25b3f" }} />
          <div className="flex-1 min-w-0">
            {online ? (
              <>
                <span data-testid="offline-queue-count">{pending} item{pending === 1 ? "" : "s"}</span> waiting to upload.
              </>
            ) : (
              <>
                You&rsquo;re offline.
                {pending > 0 && (<> <span data-testid="offline-queue-count">{pending}</span> queued.</>)}
              </>
            )}
          </div>
          {online && pending > 0 && (
            <button
              onClick={doFlush}
              disabled={flushing}
              data-testid="offline-retry-btn"
              className="text-xs px-2.5 py-1 rounded-sm border inline-flex items-center gap-1"
              style={{ borderColor: "var(--border-default)", color: "var(--accent)" }}
            >
              {flushing ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
              Retry
            </button>
          )}
        </div>
      )}

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
          onChange={handlePhoto}
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
