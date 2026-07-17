import { useEffect, useState } from "react";
import {
  Download,
  HeartPulse,
  Loader2,
  MonitorSpeaker,
  Shield,
  Users,
} from "lucide-react";
import { api, API_BASE } from "../lib/api";
import { usePageMeta } from "../lib/usePageMeta";

/**
 * Legacy Continuity — the owner's control room for the end goal:
 * a twin close enough to leave to heirs after they pass.
 */
export default function Legacy() {
  usePageMeta({
    title: "Legacy Continuity — Heirloom",
    description:
      "Death-watch, inheritance package export, and readiness for the twin your heirs will speak with.",
  });

  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [inactivity, setInactivity] = useState(30);
  const [toast, setToast] = useState("");

  const load = () =>
    api
      .get("/legacy/status")
      .then(({ data }) => {
        setStatus(data);
        setMessage(data.legacy_message || "");
        setInactivity(data.inactivity_days_default || 30);
      })
      .finally(() => setLoading(false));

  useEffect(() => {
    load();
  }, []);

  const checkIn = async () => {
    setBusy(true);
    try {
      await api.post("/legacy/check-in");
      setToast("Checked in — inactivity clocks reset.");
      await load();
    } catch (e) {
      setToast(e.response?.data?.detail || e.message);
    } finally {
      setBusy(false);
    }
  };

  const saveSettings = async () => {
    setBusy(true);
    try {
      await api.put("/legacy/settings", {
        inactivity_days_default: Number(inactivity),
        legacy_message: message,
      });
      setToast("Legacy settings saved.");
      await load();
    } catch (e) {
      setToast(e.response?.data?.detail || e.message);
    } finally {
      setBusy(false);
    }
  };

  const downloadPackage = () => {
    // Cookie-auth download — open in same origin so session cookie is sent
    window.location.href = `${API_BASE}/legacy/export`;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[40vh]">
        <Loader2 className="h-6 w-6 animate-spin" style={{ color: "var(--accent)" }} />
      </div>
    );
  }

  const r = status?.readiness || {};
  const score = r.score ?? 0;

  return (
    <div className="max-w-3xl mx-auto px-1" data-testid="legacy-page">
      <div className="overline mb-2">legacy continuity</div>
      <h1
        className="font-serif text-4xl lg:text-5xl font-light tracking-tight mb-3"
        style={{ color: "var(--text-primary)" }}
      >
        Leave a twin they can still talk to.
      </h1>
      <p className="text-base mb-10 leading-relaxed" style={{ color: "var(--text-secondary)" }}>
        Heirloom&apos;s end goal is a continuation of you — voice, memories, values —
        that your heirs can sit with after you&apos;re gone. This page is the control
        room for that promise.
      </p>

      {toast ? (
        <div
          className="mb-6 px-4 py-3 text-sm rounded-sm"
          style={{ background: "var(--accent-muted)", color: "var(--text-primary)" }}
          data-testid="legacy-toast"
        >
          {toast}
        </div>
      ) : null}

      {/* Readiness score */}
      <section className="surface p-6 mb-6" data-testid="legacy-readiness">
        <div className="flex items-end justify-between mb-4">
          <div>
            <div className="overline mb-1">twin readiness</div>
            <div className="font-serif text-5xl" style={{ color: "var(--accent)" }}>
              {score}
              <span className="text-lg" style={{ color: "var(--text-muted)" }}>
                /100
              </span>
            </div>
          </div>
          <Shield className="h-8 w-8" style={{ color: "var(--accent)" }} />
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-sm">
          <Stat label="Archive entries" value={r.archive_entries ?? 0} />
          <Stat label="Identity facts" value={r.identity_facts ?? 0} />
          <Stat label="Personality" value={r.personality_profile ? "ready" : "missing"} />
          <Stat label="Voice clone" value={r.voice_clone ? "ready" : "missing"} />
          <Stat label="Heirs" value={r.heirs_designated ?? 0} />
          <Stat label="Desktop twin" value={r.desktop_connected ? "online" : "offline"} />
        </div>
      </section>

      {/* Death watch */}
      <section className="surface p-6 mb-6" data-testid="legacy-death-watch">
        <div className="flex items-center gap-2 mb-3">
          <HeartPulse className="h-4 w-4" style={{ color: "var(--accent)" }} />
          <div className="overline">death watch</div>
        </div>
        <p className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>
          Your Windows companion heartbeats every few minutes. Combined with
          check-ins, this is how inactivity release stays honest — travel won&apos;t
          accidentally unlock your twin for heirs.
        </p>
        <div className="flex flex-wrap gap-4 items-center mb-4 text-sm">
          <div>
            <span style={{ color: "var(--text-muted)" }}>Last presence: </span>
            {status?.last_check_in
              ? new Date(status.last_check_in).toLocaleString()
              : "never"}
          </div>
          <div>
            <span style={{ color: "var(--text-muted)" }}>Days since: </span>
            {status?.days_since_presence ?? "—"}
          </div>
        </div>
        <div className="space-y-2 mb-4">
          {(status?.devices || []).map((d) => (
            <div
              key={d.device_id}
              className="flex items-center gap-3 text-sm"
              data-testid={`legacy-device-${d.device_id}`}
            >
              <MonitorSpeaker className="h-4 w-4" style={{ color: "var(--text-muted)" }} />
              <span>{d.name}</span>
              <span
                className="text-xs px-2 py-0.5 rounded-sm"
                style={{
                  background: d.online ? "var(--accent)" : "var(--bg-base)",
                  color: d.online ? "var(--text-inverse)" : "var(--text-muted)",
                }}
              >
                {d.online ? "online" : "offline"}
              </span>
            </div>
          ))}
          {(status?.devices || []).length === 0 ? (
            <p className="text-sm" style={{ color: "var(--text-muted)" }}>
              No companion PC registered yet — download the Windows app from Local PC.
            </p>
          ) : null}
        </div>
        <button
          onClick={checkIn}
          disabled={busy}
          data-testid="legacy-check-in"
          className="px-5 py-3 text-sm rounded-sm disabled:opacity-50"
          style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin inline" /> : null} I&apos;m here — check in
        </button>
      </section>

      {/* Heirs summary */}
      <section className="surface p-6 mb-6" data-testid="legacy-heirs">
        <div className="flex items-center gap-2 mb-3">
          <Users className="h-4 w-4" style={{ color: "var(--accent)" }} />
          <div className="overline">designated heirs</div>
        </div>
        {(status?.heirs || []).length === 0 ? (
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            No heirs yet. Add them under Heirs so release has somewhere to go.
          </p>
        ) : (
          <ul className="space-y-2">
            {status.heirs.map((h) => (
              <li key={h.heir_id} className="text-sm flex justify-between">
                <span>
                  {h.name}
                  {h.relationship ? ` · ${h.relationship}` : ""}
                </span>
                <span style={{ color: "var(--text-muted)" }}>
                  {h.released
                    ? "released"
                    : h.inactivity_days
                    ? `after ${h.inactivity_days}d silence`
                    : h.release_on || "manual"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Final message + defaults */}
      <section className="surface p-6 mb-6" data-testid="legacy-settings">
        <div className="overline mb-3">defaults & farewell</div>
        <label className="block text-sm mb-2" style={{ color: "var(--text-secondary)" }}>
          Default inactivity days (new heirs inherit this)
        </label>
        <input
          type="number"
          min={7}
          max={3650}
          value={inactivity}
          onChange={(e) => setInactivity(e.target.value)}
          data-testid="legacy-inactivity"
          className="w-32 px-3 py-2 text-sm rounded-sm mb-5"
          style={{
            background: "var(--bg-base)",
            border: "1px solid var(--border-default)",
            color: "var(--text-primary)",
          }}
        />
        <label className="block text-sm mb-2" style={{ color: "var(--text-secondary)" }}>
          A final message baked into every Inheritance Package
        </label>
        <textarea
          rows={4}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          data-testid="legacy-message"
          placeholder="If you're reading this, I'm gone — but I'm still here in the ways that matter…"
          className="w-full px-3 py-3 text-sm rounded-sm mb-4 resize-none"
          style={{
            background: "var(--bg-base)",
            border: "1px solid var(--border-default)",
            color: "var(--text-primary)",
          }}
        />
        <button
          onClick={saveSettings}
          disabled={busy}
          data-testid="legacy-save"
          className="px-5 py-3 text-sm rounded-sm disabled:opacity-50"
          style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
        >
          Save
        </button>
      </section>

      {/* Export */}
      <section className="surface p-6 mb-10" data-testid="legacy-export">
        <div className="flex items-center gap-2 mb-3">
          <Download className="h-4 w-4" style={{ color: "var(--accent)" }} />
          <div className="overline">inheritance package</div>
        </div>
        <p className="text-sm mb-4 leading-relaxed" style={{ color: "var(--text-secondary)" }}>
          Download a portable zip of your archive, personality portrait, identity
          facts, sealed letters, and voice-clone metadata. Store it on a USB drive,
          with your attorney, or give it to heirs alongside their portal link. The
          Windows app can also export this plus your local vault.
        </p>
        <button
          onClick={downloadPackage}
          data-testid="legacy-download"
          className="inline-flex items-center gap-2 px-5 py-3 text-sm rounded-sm"
          style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
        >
          <Download className="h-4 w-4" /> Download Inheritance Package
        </button>
      </section>
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div>
      <div className="overline mb-1">{label}</div>
      <div className="font-serif text-xl" style={{ color: "var(--text-primary)" }}>
        {value}
      </div>
    </div>
  );
}
