import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  ExternalLink,
  Eye,
  EyeOff,
  Loader2,
  Phone,
  PhoneCall,
  PhoneIncoming,
  PhoneOutgoing,
  Shield,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { usePageMeta } from "@/lib/usePageMeta";

// The Twin's phone number — Twilio Programmable Voice
// Setup: paste Account SID + Auth Token + Phone Number → we verify + auto-set
// the voice webhook on the number. Then inbound calls Just Work.

export default function PhonePage() {
  usePageMeta({
    title: "Phone · Heirloom",
    description: "Give your twin a phone number. It answers in your voice.",
  });

  const [status, setStatus] = useState(null);
  const [calls, setCalls] = useState([]);
  const [loading, setLoading] = useState(true);

  const [sid, setSid] = useState("");
  const [token, setToken] = useState("");
  const [number, setNumber] = useState("");
  const [outboundEnabled, setOutboundEnabled] = useState(false);
  const [revealToken, setRevealToken] = useState(false);
  const [saving, setSaving] = useState(false);

  const [dialing, setDialing] = useState(false);
  const [outNum, setOutNum] = useState("");
  const [outOpener, setOutOpener] = useState("Hey, this is the twin — got a minute?");

  const load = useCallback(async () => {
    try {
      const [s, c] = await Promise.all([
        api.get("/twilio/config"),
        api.get("/twilio/calls?limit=20").catch(() => ({ data: { calls: [] } })),
      ]);
      setStatus(s.data);
      setCalls(c.data?.calls || []);
      if (s.data?.configured) {
        setOutboundEnabled(!!s.data.outbound_enabled);
      }
    } catch (e) {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    if (!sid.trim() || !token.trim() || !number.trim()) {
      toast.error("All three fields required.");
      return;
    }
    setSaving(true);
    try {
      const { data } = await api.put("/twilio/config", {
        account_sid: sid.trim(),
        auth_token: token.trim(),
        phone_number: number.trim(),
        outbound_enabled: outboundEnabled,
      });
      toast.success(
        data.webhook_configured
          ? "Twilio connected — number will start answering calls immediately."
          : "Twilio saved. Couldn't auto-set the webhook — see docs at the bottom."
      );
      setSid(""); setToken(""); setNumber("");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't save.");
    } finally { setSaving(false); }
  };

  const disconnect = async () => {
    if (!window.confirm("Disconnect Twilio? Your number will stop answering.")) return;
    try {
      await api.delete("/twilio/config");
      toast.success("Disconnected.");
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't disconnect.");
    }
  };

  const dial = async () => {
    if (!outNum.trim()) { toast.error("Enter a number to dial."); return; }
    setDialing(true);
    try {
      const { data } = await api.post("/twilio/call/outbound", {
        to_number: outNum.trim(),
        opening_line: outOpener.trim() || "Hi, this is the digital twin.",
      });
      toast.success(`Dialing... call SID ${data.call_sid.slice(0, 10)}…`);
      setOutNum("");
      setTimeout(load, 2000);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't place the call.");
    } finally { setDialing(false); }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ color: "var(--text-muted)" }}>
        <Loader2 className="h-5 w-5 animate-spin" />
      </div>
    );
  }

  const configured = !!status?.configured;
  const verified = !!status?.verified;
  const webhookOk = !!status?.webhook_configured;

  return (
    <div className="min-h-screen px-6 sm:px-10 py-12" style={{ background: "var(--bg-base)" }} data-testid="phone-page">
      <div className="max-w-3xl mx-auto">
        <Link
          to="/setup/keys"
          className="inline-flex items-center gap-2 text-sm mb-8"
          style={{ color: "var(--text-muted)" }}
          data-testid="phone-back"
        >
          <ArrowLeft className="h-4 w-4" /> Back to Connect
        </Link>

        <div className="overline mb-3 flex items-center gap-2">
          <Phone className="h-3.5 w-3.5" /> phone
        </div>
        <h1 className="font-serif text-4xl sm:text-5xl font-light mb-3">
          Your twin&apos;s phone number.
        </h1>
        <p className="text-base mb-10 max-w-2xl" style={{ color: "var(--text-secondary)" }}>
          Give the twin a real phone number through Twilio. People call it — it answers
          in your voice, has a real conversation, transcribes both sides into your archive.
          You can also have the twin dial outbound.
        </p>

        {/* Status card */}
        {configured ? (
          <div
            className="rounded-sm p-6 mb-10 flex items-start gap-4 flex-wrap"
            style={{ border: `1px solid ${verified ? "var(--accent)" : "#c95a5a"}`, background: verified ? "rgba(232,169,92,0.06)" : "rgba(200,90,90,0.06)" }}
            data-testid="phone-status"
          >
            <div className="flex-1 min-w-[240px]">
              <div className="flex items-center gap-2 mb-2">
                {verified ? <Check className="h-4 w-4" style={{ color: "var(--accent)" }} /> : <AlertTriangle className="h-4 w-4" style={{ color: "#c95a5a" }} />}
                <div className="text-sm" style={{ color: "var(--text-primary)" }}>
                  {verified ? "Connected · answering calls" : "Not verified"}
                </div>
              </div>
              <div className="font-mono text-xl mb-1" style={{ color: "var(--text-primary)" }}>
                {status.phone_number}
              </div>
              <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                Outbound calls: {status.outbound_enabled ? "enabled" : "off"} · Webhook: {webhookOk ? "auto-configured" : "manual setup needed"}
              </div>
              {!webhookOk && (
                <p className="text-xs mt-3" style={{ color: "#c95a5a" }}>
                  We couldn&apos;t auto-configure the voice webhook. In the Twilio console → Phone Numbers → your number →
                  Voice Configuration, set A CALL COMES IN to <code>Webhook</code> pointing to
                  <code className="ml-1 font-mono">/api/twilio/voice/incoming</code> on this backend, POST method.
                </p>
              )}
            </div>
            <button
              type="button"
              onClick={disconnect}
              data-testid="phone-disconnect"
              className="inline-flex items-center gap-2 text-xs px-3 py-2 rounded-sm"
              style={{ border: "1px solid var(--border-default)", color: "var(--text-muted)" }}
            >
              <Trash2 className="h-3 w-3" /> Disconnect
            </button>
          </div>
        ) : null}

        {/* Setup form — always visible so users can replace credentials */}
        <div
          className="rounded-sm p-6 mb-10"
          style={{ border: "1px solid var(--border-default)", background: "var(--bg-surface)" }}
          data-testid="phone-setup"
        >
          <div className="overline mb-3">{configured ? "replace credentials" : "setup"}</div>
          <ol className="text-sm space-y-2 mb-5" style={{ color: "var(--text-secondary)" }}>
            <li>1. Sign up at <a href="https://www.twilio.com/try-twilio" target="_blank" rel="noreferrer" className="underline" style={{ color: "var(--accent)" }}>twilio.com/try-twilio <ExternalLink className="inline h-3 w-3" /></a>. Free trial credit.</li>
            <li>2. Buy a phone number: Console → Phone Numbers → Buy a Number (~$1/mo).</li>
            <li>3. Copy your Account SID + Auth Token from the top of the console dashboard.</li>
            <li>4. Paste all three below — we auto-configure the voice webhook.</li>
          </ol>

          <div className="grid sm:grid-cols-2 gap-4 mb-4">
            <div>
              <label className="text-xs block mb-1 tracking-widest uppercase" style={{ color: "var(--text-muted)" }}>Account SID</label>
              <input
                type="text"
                value={sid}
                onChange={(e) => setSid(e.target.value)}
                placeholder="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
                data-testid="phone-input-sid"
                className="w-full px-3 py-2.5 text-sm font-mono rounded-sm"
                style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
              />
            </div>
            <div>
              <label className="text-xs block mb-1 tracking-widest uppercase" style={{ color: "var(--text-muted)" }}>Auth Token</label>
              <div className="relative">
                <input
                  type={revealToken ? "text" : "password"}
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  placeholder="32-char token"
                  data-testid="phone-input-token"
                  className="w-full px-3 py-2.5 pr-9 text-sm font-mono rounded-sm"
                  style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
                />
                <button
                  type="button"
                  onClick={() => setRevealToken((r) => !r)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1"
                  style={{ color: "var(--text-muted)" }}
                >
                  {revealToken ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>
            <div className="sm:col-span-2">
              <label className="text-xs block mb-1 tracking-widest uppercase" style={{ color: "var(--text-muted)" }}>Phone Number (E.164)</label>
              <input
                type="tel"
                value={number}
                onChange={(e) => setNumber(e.target.value)}
                placeholder="+15555551234"
                data-testid="phone-input-number"
                className="w-full px-3 py-2.5 text-sm font-mono rounded-sm"
                style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
              />
            </div>
          </div>

          <label className="flex items-center gap-2 text-sm mb-5" style={{ color: "var(--text-secondary)" }}>
            <input
              type="checkbox"
              checked={outboundEnabled}
              onChange={(e) => setOutboundEnabled(e.target.checked)}
              data-testid="phone-outbound-toggle"
            />
            Also allow outbound calls (the twin can dial numbers you approve)
          </label>

          <button
            type="button"
            onClick={save}
            disabled={saving || !sid.trim() || !token.trim() || !number.trim()}
            data-testid="phone-save"
            className="inline-flex items-center gap-2 px-6 py-2.5 rounded-sm text-sm font-medium disabled:opacity-50"
            style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Shield className="h-4 w-4" />}
            {configured ? "Update & verify" : "Connect Twilio"}
          </button>
        </div>

        {/* Outbound dialer — only when configured + outbound enabled */}
        {configured && verified && status.outbound_enabled && (
          <div
            className="rounded-sm p-6 mb-10"
            style={{ border: "1px solid var(--border-default)", background: "var(--bg-surface)" }}
            data-testid="phone-dialer"
          >
            <div className="overline mb-3 flex items-center gap-2">
              <PhoneOutgoing className="h-3 w-3" style={{ color: "var(--accent)" }} />
              have the twin call someone
            </div>
            <div className="grid sm:grid-cols-2 gap-3 mb-3">
              <input
                type="tel"
                value={outNum}
                onChange={(e) => setOutNum(e.target.value)}
                placeholder="+15555551234"
                data-testid="phone-dialer-number"
                className="px-3 py-2.5 text-sm font-mono rounded-sm"
                style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
              />
              <button
                type="button"
                onClick={dial}
                disabled={dialing || !outNum.trim()}
                data-testid="phone-dialer-call"
                className="inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-sm text-sm font-medium disabled:opacity-50"
                style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
              >
                {dialing ? <Loader2 className="h-4 w-4 animate-spin" /> : <PhoneCall className="h-4 w-4" />}
                Dial now
              </button>
            </div>
            <textarea
              value={outOpener}
              onChange={(e) => setOutOpener(e.target.value)}
              placeholder="What should the twin open with?"
              rows={2}
              data-testid="phone-dialer-opener"
              className="w-full px-3 py-2 text-sm rounded-sm"
              style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
            />
          </div>
        )}

        {/* Call history */}
        {calls.length > 0 && (
          <div>
            <div className="overline mb-4">recent calls</div>
            <ul className="space-y-3">
              {calls.map((c, i) => (
                <li
                  key={c.call_sid || i}
                  className="rounded-sm p-4"
                  style={{ border: "1px solid var(--border-default)" }}
                  data-testid={`phone-call-${i}`}
                >
                  <div className="flex items-start justify-between mb-2 gap-3">
                    <div className="flex items-center gap-2 text-sm" style={{ color: "var(--text-primary)" }}>
                      {c.direction === "outbound" ? (
                        <PhoneOutgoing className="h-4 w-4" style={{ color: "var(--accent)" }} />
                      ) : (
                        <PhoneIncoming className="h-4 w-4" style={{ color: "var(--accent)" }} />
                      )}
                      <span className="font-mono">{c.direction === "outbound" ? c.to_number : c.from_number}</span>
                    </div>
                    <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                      {c.status} · {c.turns?.length || 0} turns
                    </div>
                  </div>
                  {c.turns?.slice(-2).map((t, ti) => (
                    <div key={ti} className="text-xs mt-1" style={{ color: t.role === "twin" ? "var(--accent)" : "var(--text-secondary)" }}>
                      <b>{t.role}:</b> {t.text}
                    </div>
                  ))}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
