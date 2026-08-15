import { useEffect, useRef, useState } from "react";
import { Device } from "@twilio/voice-sdk";
import {
  AlertCircle, Bell, BellOff, Mic, MicOff, Phone, PhoneCall,
  PhoneOff, Settings,
} from "lucide-react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { api, API_BASE } from "@/lib/api";
import ContactsPanel from "@/pages/mobile/ContactsPanel";
import { ensurePushSubscription, getPushPermission, unsubscribeFromPush, pushSupported } from "@/lib/push";

/**
 * Mobile Call tab — two ways to talk to the twin:
 *
 *   1. **PSTN card** — tap the twin's phone number to launch the OS dialer.
 *   2. **In-app dialer (WebRTC)** — Twilio Voice SDK negotiates a WebRTC
 *      session with Twilio.
 *   3. **Contacts book** — tap a saved contact to place a Twin-initiated
 *      outbound call (uses `/api/twilio/call/contact`).
 *
 * Extras:
 *   - Push notification toggle — enrolls the browser for Web Push so an
 *     inbound call wakes the PWA even when it isn't open.
 *   - Live transcript panel — during an active WebRTC call, an SSE stream
 *     shows each caller / twin turn as it happens.
 */
export default function MobileCall() {
  const [cfg, setCfg] = useState(null);
  const [state, setState] = useState("idle");
  const [error, setError] = useState(null);
  const [muted, setMuted] = useState(false);
  const [durationSec, setDurationSec] = useState(0);
  const [activeCallSid, setActiveCallSid] = useState(null);
  const [pushState, setPushState] = useState("unknown"); // unsupported|default|granted|denied
  const [transcript, setTranscript] = useState([]); // {role,text,at}
  const deviceRef = useRef(null);
  const callRef = useRef(null);
  const timerRef = useRef(null);
  const sseRef = useRef(null);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get("/twilio/config");
        setCfg(data);
      } catch { /* ignore */ }
      if (await pushSupported()) setPushState(await getPushPermission());
      else setPushState("unsupported");
    })();

    // If a notification click deep-linked us here with ?join=<sid>, auto-attach.
    const params = new URLSearchParams(window.location.search);
    const join = params.get("join");
    if (join) {
      setActiveCallSid(join);
      startTranscript(join);
    }

    // SW postMessage from notificationclick — join a live call transcript.
    const onMsg = (evt) => {
      if (evt?.data?.type === "notification-click" && evt.data?.data?.call_sid) {
        setActiveCallSid(evt.data.data.call_sid);
        startTranscript(evt.data.data.call_sid);
      }
    };
    navigator.serviceWorker?.addEventListener("message", onMsg);

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      if (callRef.current) callRef.current.disconnect();
      if (deviceRef.current) deviceRef.current.destroy();
      if (sseRef.current) sseRef.current.close();
      navigator.serviceWorker?.removeEventListener("message", onMsg);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---------- Push notifications ----------
  const togglePush = async () => {
    try {
      if (pushState === "granted") {
        await unsubscribeFromPush();
        setPushState("default");
        toast.success("Notifications off");
      } else {
        await ensurePushSubscription();
        setPushState("granted");
        toast.success("You'll hear about incoming calls");
      }
    } catch (e) {
      toast.error(e.message || "Couldn't set notifications");
    }
  };

  // ---------- Live transcript SSE ----------
  const startTranscript = (callSid) => {
    if (!callSid) return;
    if (sseRef.current) sseRef.current.close();
    setTranscript([]);
    const es = new EventSource(
      `${API_BASE}/twilio/calls/${callSid}/transcript/stream`,
      { withCredentials: true },
    );
    es.addEventListener("history", (evt) => {
      try {
        const parsed = JSON.parse(evt.data);
        setTranscript(parsed.turns || []);
      } catch { /* ignore */ }
    });
    es.onmessage = (evt) => {
      try {
        const parsed = JSON.parse(evt.data);
        if (parsed.event === "end") { es.close(); return; }
        setTranscript((prev) => [...prev, parsed]);
      } catch { /* ignore */ }
    };
    es.onerror = () => { /* auto-reconnects */ };
    sseRef.current = es;
  };

  const stopTranscript = () => {
    if (sseRef.current) { sseRef.current.close(); sseRef.current = null; }
    setActiveCallSid(null);
    setTranscript([]);
  };

  // ---------- WebRTC device init ----------
  const initDevice = async () => {
    if (deviceRef.current) return deviceRef.current;
    const { data } = await api.post("/twilio/voice/token");
    const device = new Device(data.token, {
      logLevel: 1,
      codecPreferences: ["opus", "pcmu"],
    });
    device.on("error", (err) => {
      setError(err.message || String(err));
      setState("ended");
    });
    device.on("incoming", (call) => {
      call.accept();
      wireCall(call);
      setState("in-call");
    });
    await device.register();
    deviceRef.current = device;
    return device;
  };

  const wireCall = (call) => {
    callRef.current = call;
    call.on("accept", () => {
      setState("in-call");
      const start = Date.now();
      timerRef.current = setInterval(() => {
        setDurationSec(Math.floor((Date.now() - start) / 1000));
      }, 1000);
      // Twilio Voice SDK Call → parameters.CallSid (server-side) is what we
      // need for the SSE transcript subscription. Try common access paths.
      const sid = call.parameters?.CallSid || call.customParameters?.get?.("CallSid");
      if (sid) { setActiveCallSid(sid); startTranscript(sid); }
    });
    call.on("ringing", () => setState("ringing"));
    call.on("disconnect", () => {
      setState("ended");
      if (timerRef.current) clearInterval(timerRef.current);
      if (sseRef.current) { sseRef.current.close(); sseRef.current = null; }
    });
    call.on("error", (err) => {
      setError(err.message || String(err));
      setState("ended");
    });
  };

  const startInAppCall = async () => {
    setError(null);
    setState("connecting");
    setDurationSec(0);
    try {
      const device = await initDevice();
      const call = await device.connect({ params: { To: "twin" } });
      wireCall(call);
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "Couldn't start call");
      setState("ended");
      toast.error("Call failed");
    }
  };

  const dialContact = async (contact) => {
    try {
      const { data } = await api.post("/twilio/call/contact", { contact_id: contact.contact_id });
      toast.success(`Calling ${contact.name}…`);
      if (data?.call_sid) { setActiveCallSid(data.call_sid); startTranscript(data.call_sid); }
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Couldn't place call");
    }
  };

  const hangUp = () => {
    if (callRef.current) callRef.current.disconnect();
  };

  const toggleMute = () => {
    if (!callRef.current) return;
    const next = !muted;
    callRef.current.mute(next);
    setMuted(next);
  };

  const mmSs = (sec) => `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
  const twinNumber = cfg?.phone_number || "";
  const webrtcReady = cfg?.webrtc_configured;
  const twilioConfigured = cfg?.configured;

  // ---------- render ----------
  if (!twilioConfigured) {
    return (
      <div className="max-w-md mx-auto text-center py-16" data-testid="mobile-call-empty">
        <Phone className="w-10 h-10 mx-auto mb-4" style={{ color: "var(--text-muted)" }} />
        <h1 className="font-serif text-3xl mb-3" style={{ color: "var(--text-primary)" }}>
          The twin has no number yet
        </h1>
        <p className="text-sm mb-6" style={{ color: "var(--text-muted)" }}>
          Set up Twilio in your phone settings to give the twin a number people can call.
        </p>
        <Link
          to="/phone"
          data-testid="mobile-call-setup-link"
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-sm text-sm font-medium"
          style={{ background: "var(--accent)", color: "var(--surface)" }}
        >
          <Settings className="w-4 h-4" /> Configure Twilio
        </Link>
      </div>
    );
  }

  // Active call view
  if (state !== "idle") {
    const stateLabels = {
      connecting: "connecting…",
      ringing: "ringing…",
      "in-call": mmSs(durationSec),
      ended: "call ended",
    };
    return (
      <div className="max-w-md mx-auto py-4 space-y-6" data-testid="mobile-call-active">
        <div className="text-center">
          <div className="overline mb-3">
            {state === "in-call" ? "on call · twin" : state}
          </div>
          <div className="font-serif text-5xl mb-6" style={{ color: "var(--text-primary)" }} data-testid="call-timer">
            {stateLabels[state] || state}
          </div>
          {error && (
            <div className="mb-4 text-xs font-mono" style={{ color: "#c25b3f" }} data-testid="call-error">
              {error}
            </div>
          )}
          <div className="flex items-center justify-center gap-6 mt-6">
            {state === "in-call" && (
              <button
                onClick={toggleMute}
                data-testid="call-mute-btn"
                className="w-14 h-14 rounded-full flex items-center justify-center border"
                style={{
                  background: muted ? "var(--accent-muted)" : "var(--surface-elev)",
                  borderColor: "var(--border-default)",
                  color: muted ? "var(--accent)" : "var(--text-primary)",
                }}
              >
                {muted ? <MicOff className="w-5 h-5" /> : <Mic className="w-5 h-5" />}
              </button>
            )}
            {state === "ended" ? (
              <button
                onClick={() => { setState("idle"); setError(null); setDurationSec(0); stopTranscript(); }}
                data-testid="call-reset-btn"
                className="px-6 py-3 rounded-full text-sm font-medium"
                style={{ background: "var(--accent)", color: "var(--surface)" }}
              >
                Done
              </button>
            ) : (
              <button
                onClick={hangUp}
                data-testid="call-hangup-btn"
                className="w-16 h-16 rounded-full flex items-center justify-center"
                style={{ background: "#c25b3f", color: "white" }}
              >
                <PhoneOff className="w-6 h-6" />
              </button>
            )}
          </div>
        </div>

        <LiveTranscript turns={transcript} />
      </div>
    );
  }

  // Idle — the choice screen
  return (
    <div className="max-w-md mx-auto space-y-6" data-testid="mobile-call-idle">
      <div className="text-center pt-2">
        <div className="overline mb-2">Twin · {twinNumber}</div>
        <h1 className="font-serif text-4xl" style={{ color: "var(--text-primary)" }}>
          Talk to your twin
        </h1>
      </div>

      {/* Push notifications toggle */}
      {pushState !== "unsupported" && (
        <button
          onClick={togglePush}
          data-testid="push-toggle-btn"
          className="w-full rounded-md border p-4 flex items-center gap-3 text-left"
          style={{
            background: pushState === "granted" ? "var(--surface-elev)" : "var(--surface)",
            borderColor: pushState === "granted" ? "var(--accent)" : "var(--border-default)",
          }}
        >
          <div
            className="w-10 h-10 rounded-full flex items-center justify-center"
            style={{ background: pushState === "granted" ? "var(--accent)" : "var(--surface-elev)", color: pushState === "granted" ? "var(--surface)" : "var(--text-muted)" }}
          >
            {pushState === "granted" ? <Bell className="w-5 h-5" /> : <BellOff className="w-5 h-5" />}
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
              {pushState === "granted" ? "Notifications on" : "Turn on call alerts"}
            </div>
            <div className="text-xs" style={{ color: "var(--text-muted)" }}>
              {pushState === "denied"
                ? "Blocked in browser settings — enable there first"
                : "We'll ping you when someone calls the twin"}
            </div>
          </div>
        </button>
      )}

      {/* In-app WebRTC dialer */}
      {webrtcReady ? (
        <button
          onClick={startInAppCall}
          data-testid="in-app-call-btn"
          className="w-full rounded-md border p-6 text-left flex items-center gap-4"
          style={{ background: "var(--surface)", borderColor: "var(--accent)" }}
        >
          <div className="w-14 h-14 rounded-full flex items-center justify-center"
               style={{ background: "var(--accent)", color: "var(--surface)" }}>
            <PhoneCall className="w-6 h-6" />
          </div>
          <div>
            <div className="font-medium" style={{ color: "var(--text-primary)" }}>Call in-app</div>
            <div className="text-xs" style={{ color: "var(--text-muted)" }}>
              WebRTC — no cellular minutes used
            </div>
          </div>
        </button>
      ) : (
        <div
          className="rounded-md border p-5 text-sm"
          style={{ background: "var(--surface)", borderColor: "var(--border-default)", color: "var(--text-secondary)" }}
          data-testid="in-app-call-disabled"
        >
          <div className="flex items-start gap-3">
            <AlertCircle className="w-4 h-4 mt-0.5" style={{ color: "var(--text-muted)" }} />
            <div>
              <div className="font-medium mb-1" style={{ color: "var(--text-primary)" }}>
                In-app calling isn&rsquo;t set up yet
              </div>
              <p className="text-xs mb-3" style={{ color: "var(--text-muted)" }}>
                Create a Twilio API Key + TwiML App and paste the SIDs in Phone settings to talk to the twin over WebRTC without using cellular minutes.
              </p>
              <Link to="/phone" data-testid="webrtc-setup-link" className="text-xs font-medium" style={{ color: "var(--accent)" }}>
                Open Phone settings →
              </Link>
            </div>
          </div>
        </div>
      )}

      {/* PSTN fallback */}
      <a
        href={`tel:${twinNumber}`}
        data-testid="pstn-call-link"
        className="w-full rounded-md border p-6 flex items-center gap-4"
        style={{ background: "var(--surface)", borderColor: "var(--border-default)", color: "var(--text-primary)" }}
      >
        <div className="w-14 h-14 rounded-full flex items-center justify-center border"
             style={{ borderColor: "var(--border-default)" }}>
          <Phone className="w-6 h-6" style={{ color: "var(--text-primary)" }} />
        </div>
        <div>
          <div className="font-medium">Call via carrier</div>
          <div className="text-xs" style={{ color: "var(--text-muted)" }}>{twinNumber}</div>
        </div>
      </a>

      {/* Contacts book */}
      <ContactsPanel onDial={dialContact} />

      {/* Live transcript of any external call the user is spectating on */}
      {activeCallSid && transcript.length > 0 && (
        <LiveTranscript turns={transcript} />
      )}
    </div>
  );
}

function LiveTranscript({ turns }) {
  const scrollRef = useRef(null);
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [turns.length]);

  return (
    <div
      className="rounded-md border p-4"
      style={{ background: "var(--surface)", borderColor: "var(--border-default)" }}
      data-testid="live-transcript"
    >
      <div className="overline mb-2">Live transcript</div>
      {turns.length === 0 ? (
        <div className="text-xs italic" style={{ color: "var(--text-muted)" }}>
          Listening…
        </div>
      ) : (
        <div ref={scrollRef} className="space-y-2 max-h-72 overflow-y-auto text-sm">
          {turns.map((t, i) => (
            <div key={i} data-testid={`transcript-turn-${i}`}>
              <span
                className="uppercase tracking-wide text-[10px] mr-2"
                style={{ color: t.role === "twin" ? "var(--accent)" : "var(--text-muted)" }}
              >
                {t.role === "twin" ? "Twin" : t.role === "caller" ? "Caller" : t.role || "…"}
              </span>
              <span style={{ color: "var(--text-primary)" }}>{t.text}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
