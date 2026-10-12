import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowRight, Loader2 } from "lucide-react";
import RoomViewer3D from "../components/studio/RoomViewer3D";
import VrModeControls from "../components/studio/VrModeControls";
import AssistantPicker from "../components/studio/AssistantPicker";
import { api, API_BASE, streamSSE } from "../lib/api";
import { speakerLabel } from "../lib/assistants";
import { useAuth } from "../lib/auth";
import { createGazeAccumulator, gazePayload, shouldSendGaze } from "../lib/vrGaze";
import { VR_LAUNCH_NOTE, vrAllowedForAudience } from "../lib/vrMode";
import { applyRoomGaze, applyRoomVrEnter, applyRoomVrToggle, loadOwnerVr, saveOwnerVr } from "../lib/vrRoom";
import { enterRoomVr } from "../lib/vrRuntime";
import { playAtSeat, runVrTurn, TWIN_SEAT } from "../lib/vrTalk";

export default function RoomSit() {
  const { roomId } = useParams();
  const { user } = useAuth();
  const heirSurface = Boolean(user?.heir_surface) || user?.audience === "heir";
  const audience = heirSurface ? "heir" : "owner";
  const allowed = vrAllowedForAudience(audience, heirSurface);
  const userId = user?.user_id || "owner";

  const [room, setRoom] = useState(null);
  const [gltf, setGltf] = useState(null);
  const [error, setError] = useState("");
  const [vrNote, setVrNote] = useState(allowed ? VR_LAUNCH_NOTE : "");
  const [vr, setVr] = useState({ enabled: false, gazeEnabled: false });
  const [sessionActive, setSessionActive] = useState(false);
  const [assistants, setAssistants] = useState([]);
  const [selectedAssistant, setSelectedAssistant] = useState(null);
  const [conv, setConv] = useState(null);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [streaming, setStreaming] = useState("");

  const prefsRef = useRef(vr);
  const sessionRef = useRef(null);
  const mediaRef = useRef(null);
  const recorderRef = useRef(null);
  const chunksRef = useRef([]);
  const gazeRef = useRef(null);
  const convRef = useRef(null);
  const selectedRef = useRef(null);
  const sendLock = useRef(false);
  const sendRef = useRef(async () => "");

  useEffect(() => {
    prefsRef.current = vr;
  }, [vr]);
  useEffect(() => {
    convRef.current = conv;
  }, [conv]);
  useEffect(() => {
    selectedRef.current = selectedAssistant;
  }, [selectedAssistant]);

  useEffect(() => {
    api.get(`/rooms/${roomId}`).then(({ data }) => setRoom(data)).catch(() => setError("Room not found."));
    api.get(`/rooms/${roomId}/scene`).then(({ data }) => setGltf(data)).catch(() => setGltf(null));
    api.get("/clones").then(({ data }) => setAssistants(data.clones || [])).catch(() => {});
    api.post("/twin/start", {}).then(({ data }) => setConv(data)).catch(() => {});
  }, [roomId]);

  useEffect(() => {
    if (!allowed) return undefined;
    let cancelled = false;
    loadOwnerVr(api, userId, window.localStorage).then((launched) => {
      if (cancelled) return;
      setVr({ enabled: Boolean(launched.enabled), gazeEnabled: Boolean(launched.gazeEnabled) });
      setSessionActive(false);
    });
    return () => {
      cancelled = true;
    };
  }, [allowed, userId]);

  useEffect(() => () => {
    try {
      sessionRef.current?.end?.();
    } catch {
      /* The page is already leaving. */
    }
    mediaRef.current?.getTracks?.().forEach((track) => track.stop());
  }, []);

  const send = useCallback(async (text) => {
    const sitting = convRef.current;
    if (!String(text || "").trim() || !sitting || sendLock.current) return "";
    sendLock.current = true;
    const myMsg = { role: "user", content: text, ts: new Date().toISOString() };
    setConv((c) => {
      const base = c || sitting;
      return { ...base, messages: [...(base.messages || []), myMsg] };
    });
    setInput("");
    setPending(true);
    setStreaming("");
    let full = "";
    let specialistName = "";
    try {
      await streamSSE(
        "/twin/message",
        {
          conversation_id: sitting.conversation_id,
          message: text,
          clone_id: selectedRef.current || undefined,
          room_id: roomId,
        },
        (chunk) => {
          full += chunk;
          setStreaming(full);
        },
        () => {
          setConv((c) => {
            const base = c || sitting;
            return {
              ...base,
              messages: [
                ...(base.messages || []),
                {
                  role: "assistant",
                  content: full,
                  ts: new Date().toISOString(),
                  specialist_name: specialistName || undefined,
                  specialist_id: selectedRef.current || undefined,
                },
              ],
            };
          });
          setStreaming("");
          setPending(false);
        },
        () => {
          setStreaming("");
          setPending(false);
        },
        (eventName, data) => {
          if (eventName === "specialist" && data?.name) specialistName = data.name;
        },
      );
    } finally {
      sendLock.current = false;
    }
    return full;
  }, [roomId]);

  useEffect(() => {
    sendRef.current = send;
  }, [send]);

  const transcribeBlob = useCallback(async (blob) => {
    const body = new FormData();
    body.append("file", blob, "vr-talk.webm");
    body.append("save_to_archive", "false");
    const res = await fetch(`${API_BASE}/voice/transcribe`, {
      method: "POST",
      credentials: "include",
      body,
    });
    if (!res.ok) return "";
    const data = await res.json().catch(() => ({}));
    return data.text || "";
  }, []);

  const speakReply = useCallback(async (text) => {
    const { data } = await api.post("/voice/speak", { text });
    const audio = data?.audio_base64 || "";
    if (audio) await playAtSeat(audio, TWIN_SEAT, window);
    return audio;
  }, []);

  const flushGaze = useCallback(async (available) => {
    const acc = gazeRef.current;
    gazeRef.current = null;
    if (!acc) return;
    const summaries = acc.flush(typeof performance !== "undefined" ? performance.now() : 0);
    const decision = shouldSendGaze({
      gazeEnabled: prefsRef.current.gazeEnabled,
      audience,
      heirSurface,
      available,
      summaries,
    });
    if (!decision.send) return;
    try {
      await api.post("/observer/vr-gaze", gazePayload(summaries));
    } catch {
      /* Pause, heir fence, or Observer off. The sitting still ends. */
    }
  }, [audience, heirSurface]);

  const stopCapture = useCallback(() => {
    const recorder = recorderRef.current;
    recorderRef.current = null;
    if (recorder && recorder.state !== "inactive") recorder.stop();
  }, []);

  const startCapture = useCallback(async () => {
    if (!allowed || recorderRef.current) return;
    try {
      if (!mediaRef.current) {
        mediaRef.current = await navigator.mediaDevices.getUserMedia({ audio: true });
      }
      const mime = window.MediaRecorder?.isTypeSupported?.("audio/webm") ? "audio/webm" : "";
      const recorder = mime
        ? new MediaRecorder(mediaRef.current, { mimeType: mime })
        : new MediaRecorder(mediaRef.current);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        chunksRef.current = [];
        runVrTurn({
          blob,
          audience,
          heirSurface,
          transcribe: transcribeBlob,
          chat: (text) => sendRef.current(text),
          speak: speakReply,
        }).catch(() => {});
      };
      recorderRef.current = recorder;
      recorder.start();
    } catch {
      setVrNote("The microphone did not start. You can still type.");
    }
  }, [allowed, audience, heirSurface, speakReply, transcribeBlob]);

  const startSession = useCallback(async ({ gesture, gaze }) => {
    if (!allowed) return { ok: false, reason: "heir" };
    if (sessionRef.current) return sessionRef.current;
    gazeRef.current = gaze ? createGazeAccumulator() : null;
    const result = await enterRoomVr({
      gesture,
      gaze,
      onPtt: ({ phase }) => {
        if (phase === "down") startCapture();
        else stopCapture();
      },
      onAttention: ({ area, time }) => {
        if (!prefsRef.current.gazeEnabled) return;
        gazeRef.current?.sample(area, time);
      },
      onEnd: ({ gazeAvailable } = {}) => {
        sessionRef.current = null;
        setSessionActive(false);
        stopCapture();
        flushGaze(Boolean(gazeAvailable));
      },
    });
    if (result?.ok) {
      sessionRef.current = result;
      setSessionActive(true);
      setVrNote("In the headset. Trigger or Space talks. The twin is across the table.");
    } else {
      gazeRef.current = null;
      setSessionActive(false);
      setVrNote(result?.reason || "The headset did not start. The Room stays on this screen.");
    }
    return result;
  }, [allowed, flushGaze, startCapture, stopCapture]);

  const endSession = useCallback(async () => {
    const handle = sessionRef.current;
    if (handle?.end) {
      try {
        handle.end();
      } catch {
        sessionRef.current = null;
        setSessionActive(false);
      }
      return;
    }
    sessionRef.current = null;
    setSessionActive(false);
  }, []);

  const save = useCallback(
    (prefs) => saveOwnerVr(api, userId, window.localStorage, prefs),
    [userId],
  );

  const onToggleVr = async (nextEnabled) => {
    const result = await applyRoomVrToggle({
      prefs: prefsRef.current,
      nextEnabled,
      gesture: true,
      surface: "room",
      sessionActive: Boolean(sessionRef.current),
      enter: startSession,
      endSession,
      save,
    });
    setVr(result.prefs);
    if (!nextEnabled) setVrNote("Back on the normal screen.");
  };

  const onToggleGaze = async (nextGaze) => {
    const result = await applyRoomGaze({
      prefs: prefsRef.current,
      nextGaze,
      gesture: true,
      save,
    });
    setVr(result.prefs);
    if (!nextGaze) {
      gazeRef.current = null;
      return;
    }
    const live = sessionRef.current;
    if (live && !live.gazeAvailable) {
      setVrNote("This visit started without eye tracking. Leave and enter again to ask the runtime for gaze.");
      return;
    }
    if (live && !gazeRef.current) gazeRef.current = createGazeAccumulator();
  };

  const onEnter = async () => {
    const result = await applyRoomVrEnter({
      prefs: prefsRef.current,
      gesture: true,
      sessionActive: Boolean(sessionRef.current),
      enter: startSession,
    });
    if (result.started && !result.started.ok) {
      setVrNote(result.started.reason || "The headset did not start.");
    }
  };

  const messages = conv?.messages || [];

  return (
    <div className="px-4 sm:px-6 lg:px-10 py-8 max-w-6xl" data-testid="room-sit">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 text-xs" style={{ color: "var(--text-muted)" }}>
        <Link to={`/rooms/${roomId}`} className="hover:text-[var(--accent)]" data-testid="room-sit-back">
          ← {room?.name || "room"}
        </Link>
        <Link to={`/twin?room=${encodeURIComponent(roomId)}`} className="hover:text-[var(--accent)]" data-testid="room-sit-twin">
          Open full Twin sitting →
        </Link>
      </div>

      <div className="grid lg:grid-cols-5 gap-4">
        <div className="lg:col-span-3 surface overflow-hidden" style={{ minHeight: 360 }}>
          <div className="h-[52vh] min-h-[320px]" data-testid="room-sit-stage">
            {gltf ? (
              <RoomViewer3D gltf={gltf} title={room?.name} />
            ) : (
              <div className="h-full flex items-center justify-center text-sm" style={{ color: "var(--text-muted)" }}>
                {error || "Loading the stand-in scene…"}
              </div>
            )}
          </div>
          <div className="px-4 py-3" style={{ borderTop: "1px solid var(--border-default)" }}>
            {allowed ? (
              <VrModeControls
                testid="room-sit-vr"
                enabled={vr.enabled}
                gazeEnabled={vr.gazeEnabled}
                sessionActive={sessionActive}
                onToggleVr={onToggleVr}
                onToggleGaze={onToggleGaze}
                onEnter={onEnter}
                onLeave={endSession}
                note={vrNote}
              />
            ) : (
              <p className="text-xs" data-testid="room-sit-vr-heir" style={{ color: "var(--text-muted)" }}>
                VR is an owner sitting. This screen stays flat.
              </p>
            )}
          </div>
        </div>

        <div className="lg:col-span-2 surface p-4 flex flex-col" style={{ minHeight: 360 }} data-testid="room-sit-chat">
          <div className="overline mb-2">twin in this place</div>
          <AssistantPicker
            clones={assistants}
            selectedId={selectedAssistant}
            onSelect={setSelectedAssistant}
            testid="room-sit-clones"
          />
          <div className="flex-1 overflow-y-auto mt-4 space-y-4 max-h-[40vh]" data-testid="room-sit-feed">
            {messages.map((m, i) => (
              <div key={`${m.ts}-${i}`}>
                <div className="overline mb-1">
                  {m.role === "assistant" ? speakerLabel(m, assistants) : "you"}
                </div>
                <p className="text-sm leading-relaxed" style={{ color: "var(--text-primary)" }}>
                  {m.content}
                </p>
              </div>
            ))}
            {streaming ? (
              <p className="font-serif text-lg" style={{ color: "var(--text-primary)" }}>{streaming}</p>
            ) : null}
          </div>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            rows={3}
            placeholder="Talk here. @Research or pick a clone."
            data-testid="room-sit-input"
            className="mt-3 w-full bg-transparent outline-none resize-none text-sm"
            style={{ color: "var(--text-primary)" }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                send(input);
              }
            }}
          />
          <button
            type="button"
            onClick={() => send(input)}
            disabled={pending || !input.trim()}
            data-testid="room-sit-send"
            className="mt-2 inline-flex items-center justify-center gap-2 px-4 py-2 text-sm rounded-sm disabled:opacity-50"
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
