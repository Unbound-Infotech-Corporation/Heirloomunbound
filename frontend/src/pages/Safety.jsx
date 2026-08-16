import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { ToyDesk, ToyKnob, ToyLight, ToyPorthole } from "@/components/ToyPlayset";

function parseLights(text) {
  const blob = String(text || "");
  const pick = (patterns) => {
    for (const re of patterns) {
      const m = blob.match(re);
      if (!m) continue;
      const val = (m[1] || "").toLowerCase();
      if (val === "on" || val === "true" || val === "yes") return "on";
      if (val === "off" || val === "false" || val === "no") return "off";
      return "unknown";
    }
    return "unknown";
  };
  return {
    virus: pick([/virus[^:\n]*:\s*(on|off|couldn't|could not)/i]),
    realtime: pick([/real-time[^:\n]*:\s*(on|off|couldn't|could not)/i]),
    firewall: pick([/firewall[^:\n]*:\s*(on|off|couldn't|could not)/i]),
    uac: pick([
      /ask before big changes[^:\n]*:\s*(on|off|couldn't|could not)/i,
      /\bUAC[^:\n]*:\s*(on|off|couldn't|could not)/i,
    ]),
  };
}

export default function Safety() {
  const [devices, setDevices] = useState([]);
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState("");
  const [lights, setLights] = useState({
    virus: "unknown",
    realtime: "unknown",
    firewall: "unknown",
    uac: "unknown",
  });
  const [confirmScan, setConfirmScan] = useState(false);
  const [waitingId, setWaitingId] = useState(null);

  const hasPc = devices.some((d) => !d.revoked);

  useEffect(() => {
    api
      .get("/companion/devices")
      .then(({ data }) => setDevices(Array.isArray(data) ? data : []))
      .catch(() => setDevices([]));
  }, []);

  useEffect(() => {
    if (!waitingId) return undefined;
    let stop = false;
    const tick = async () => {
      try {
        const { data } = await api.get("/companion/commands");
        const rows = Array.isArray(data) ? data : [];
        const hit = rows.find((c) => c.cmd_id === waitingId);
        if (!hit || stop) return;
        if (hit.status === "queued" || hit.status === "dispatched") return;
        const text = String(hit.result || "");
        setReport(text);
        if ((hit.payload?.kind || "") === "status" || /Windows Security on this computer/i.test(text)) {
          setLights(parseLights(text));
        }
        setWaitingId(null);
        setBusy(false);
      } catch {
        /* next poll */
      }
    };
    tick();
    const t = setInterval(tick, 2000);
    return () => {
      stop = true;
      clearInterval(t);
    };
  }, [waitingId]);

  const queueJob = async (kind) => {
    if (busy) return;
    if (!hasPc) {
      setReport("Open the Heirloom app on the home computer.");
      return;
    }
    setBusy(true);
    setReport("");
    try {
      const { data } = await api.post("/companion/queue-command", {
        kind: "security_job",
        payload: { kind },
      });
      setWaitingId(data.cmd_id);
      setReport("Asking the home computer…");
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setReport(
        typeof detail === "string" && detail.trim()
          ? detail
          : "Couldn't reach the home computer. Open the Heirloom app there."
      );
      setBusy(false);
    }
  };

  return (
    <div className="px-4 sm:px-8 lg:px-16 py-12 max-w-4xl" data-testid="safety-root">
      <ToyDesk>
        <div className="toy-playset-row">
          <ToyPorthole status={busy ? "looking…" : "safety"} />
          <div className="min-w-0 flex-1">
            <div className="toy-kicker">windows safety</div>
            <h1 className="toy-title text-4xl sm:text-5xl mb-3">An extra pair of eyes.</h1>
            <p className="toy-copy mb-4">
              We look at Windows Security with you. We never turn protection off. We never ask for your Windows password — even if someone on the phone tells you to say yes.
            </p>
            {!hasPc && (
              <p className="toy-copy mb-4" data-testid="safety-need-pc">
                Open the Heirloom app on the home computer.
              </p>
            )}
          </div>
        </div>

        <div className="toy-plate mt-8 grid sm:grid-cols-2 gap-4" data-testid="safety-lights">
          <ToyLight state={lights.virus} label="Virus & threat protection" testid="safety-light-virus" />
          <ToyLight state={lights.realtime} label="Real-time protection" testid="safety-light-realtime" />
          <ToyLight state={lights.firewall} label="Firewall" testid="safety-light-firewall" />
          <ToyLight state={lights.uac} label="Ask before big changes" testid="safety-light-uac" />
        </div>

        <div className="toy-knob-grid mt-8">
          <ToyKnob
            color="sky"
            testid="safety-look"
            disabled={busy}
            onClick={() => queueJob("status")}
            title="Read whether Windows protection is on"
          >
            {busy ? <Loader2 className="h-5 w-5 animate-spin" /> : null}
            LOOK
          </ToyKnob>
          <ToyKnob
            color="sunflower"
            testid="safety-open"
            disabled={busy}
            onClick={() => queueJob("open")}
            title="Open the same Windows Security app Windows already has"
          >
            OPEN
          </ToyKnob>
          <ToyKnob
            color="tomato"
            testid="safety-scan"
            disabled={busy}
            onClick={() => setConfirmScan(true)}
            title="Ask Windows to start a quick scan"
          >
            SCAN
          </ToyKnob>
        </div>

        {report && (
          <p className="toy-copy mt-6 whitespace-pre-wrap" data-testid="safety-report">
            {report}
          </p>
        )}

        <p className="toy-copy mt-6 text-sm">
          Green means on. Red means off — tap OPEN and turn it back on in Windows. Yellow means we couldn&apos;t read it. We will not turn anything off for anyone.
        </p>
        <Link to="/companion" className="toy-copy mt-3 inline-block underline" style={{ color: "var(--toy-tomato-deep)" }}>
          Need the Heirloom app on that computer?
        </Link>
      </ToyDesk>

      {confirmScan && (
        <div className="toy-modal-scrim" data-testid="safety-scan-confirm">
          <ToyDesk className="max-w-lg w-full">
            <div className="toy-kicker">just checking</div>
            <h2 className="toy-title text-3xl mb-3">Should I ask Windows to look?</h2>
            <p className="toy-copy mb-6">
              This starts a quick scan in Windows Security. I never turn protection off. I never need your Windows password.
            </p>
            <div className="toy-knob-grid">
              <ToyKnob
                color="grass"
                testid="safety-scan-yes"
                onClick={() => {
                  setConfirmScan(false);
                  queueJob("scan");
                }}
              >
                Yes, look
              </ToyKnob>
              <ToyKnob color="cream" testid="safety-scan-no" onClick={() => setConfirmScan(false)}>
                Not now
              </ToyKnob>
            </div>
          </ToyDesk>
        </div>
      )}
    </div>
  );
}
