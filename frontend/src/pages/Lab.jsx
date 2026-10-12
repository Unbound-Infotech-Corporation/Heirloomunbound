import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { healthLine, summarizeTurns, voteLabel } from "../lib/lab";
import ObserverPanel from "../components/studio/ObserverPanel";

export default function Lab() {
  const [health, setHealth] = useState(null);
  const [healthError, setHealthError] = useState("");
  const [turns, setTurns] = useState([]);
  const [summary, setSummary] = useState(null);
  const [report, setReport] = useState("");
  const [closed, setClosed] = useState(false);

  useEffect(() => {
    api.get("/health")
      .then(({ data }) => setHealth(data))
      .catch(() => setHealthError("Health is not reachable."));
    api.get("/lab/turns")
      .then(({ data }) => {
        setTurns(data.turns || []);
        setSummary(data.summary || summarizeTurns(data.turns || []));
      })
      .catch(() => setClosed(true));
    api.get("/lab/report")
      .then(({ data }) => setReport(data.markdown || ""))
      .catch(() => setReport(""));
  }, []);

  const counts = summary || summarizeTurns(turns);

  return (
    <div className="max-w-3xl mx-auto px-4 py-8" data-testid="lab-page">
      <div className="overline mb-2">twin box</div>
      <h1 className="font-serif text-3xl mb-2" style={{ color: "var(--text-primary)" }}>
        Lab
      </h1>
      <p className="text-sm mb-6" style={{ color: "var(--text-muted)" }}>
        Usefulness signals stay on this machine. Heirs do not see this page.
      </p>

      <section className="surface p-5 mb-6" data-testid="lab-health">
        <div className="overline mb-2">/api/health</div>
        <p className="font-serif text-xl" data-testid="lab-health-line" style={{ color: "var(--text-primary)" }}>
          {health ? healthLine(health) : (healthError || "Checking…")}
        </p>
        {health ? (
          <pre className="mt-3 text-xs whitespace-pre-wrap" data-testid="lab-health-json" style={{ color: "var(--text-secondary)" }}>
            {JSON.stringify(health, null, 2)}
          </pre>
        ) : null}
      </section>

      {health?.observer?.enabled ? (
        <div className="mb-6" data-testid="lab-observer">
          <ObserverPanel />
        </div>
      ) : null}

      {closed ? (
        <p className="text-sm" data-testid="lab-closed" style={{ color: "var(--text-muted)" }}>
          Lab mode is off on this server.
        </p>
      ) : (
        <>
          <section className="surface p-5 mb-6" data-testid="lab-summary">
            <div className="overline mb-2">this machine</div>
            <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
              {counts.turns} turns · {counts.up} useful · {counts.down} not useful · {counts.errors} errors
            </p>
            <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
              Approvals created {counts.approvals_created ?? counts.approvalsCreated} · approved {counts.approvals_approved ?? counts.approvalsApproved} · declined {counts.approvals_declined ?? counts.approvalsDeclined}
            </p>
          </section>
          <section className="surface p-5 mb-6" data-testid="lab-turns">
            <div className="overline mb-3">turns</div>
            {turns.length === 0 ? (
              <p className="text-sm" style={{ color: "var(--text-muted)" }}>No turns yet.</p>
            ) : (
              <ul className="space-y-3">
                {turns.map((row) => (
                  <li key={row.turn_id} className="text-sm" data-testid={`lab-turn-${row.turn_id}`}>
                    <span style={{ color: "var(--text-primary)" }}>{row.route}</span>
                    <span style={{ color: "var(--text-muted)" }}>
                      {" "}· {row.model || "model unset"} · {row.latency_ms ?? "—"} ms
                      {row.error ? ` · ${row.error}` : ""}
                      {row.feedback?.vote ? ` · ${voteLabel(row.feedback.vote)}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
          {report ? (
            <section className="surface p-5" data-testid="lab-report">
              <div className="overline mb-2">latest report</div>
              <pre className="text-xs whitespace-pre-wrap" style={{ color: "var(--text-secondary)" }}>{report}</pre>
            </section>
          ) : null}
        </>
      )}
    </div>
  );
}
