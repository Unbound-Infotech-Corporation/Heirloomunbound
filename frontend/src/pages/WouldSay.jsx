import { useEffect, useState } from "react";
import { api } from "../lib/api";

function scoreLine(run) {
  if (!run) return "";
  const brain = run.brain || "brain";
  const model = run.model ? ` · ${run.model}` : "";
  const style = Number(run.mean_style || 0).toFixed(2);
  const factual = Number(run.mean_factual || 0).toFixed(2);
  return `${brain}${model} · style ${style} · factual ${factual}`;
}

export default function WouldSay() {
  const [cases, setCases] = useState([]);
  const [runs, setRuns] = useState([]);
  const [prompt, setPrompt] = useState("");
  const [reference, setReference] = useState("");
  const [note, setNote] = useState("");
  const [drafts, setDrafts] = useState([]);
  const [busy, setBusy] = useState(false);
  const [closed, setClosed] = useState(false);

  function load() {
    api.get("/would-say/cases")
      .then(({ data }) => {
        setCases(data.cases || []);
        setClosed(false);
      })
      .catch(() => setClosed(true));
    api.get("/would-say/runs")
      .then(({ data }) => setRuns(data.runs || []))
      .catch(() => setRuns([]));
  }

  useEffect(() => { load(); }, []);

  async function addCase(event) {
    event.preventDefault();
    if (!prompt.trim() || !reference.trim()) return;
    setBusy(true);
    setNote("");
    try {
      await api.post("/would-say/cases", { prompt, reference, source: "owner" });
      setPrompt("");
      setReference("");
      load();
    } catch (err) {
      setNote(err?.response?.data?.detail || "Could not save that case.");
    } finally {
      setBusy(false);
    }
  }

  async function suggest() {
    setBusy(true);
    setNote("");
    try {
      const { data } = await api.post("/would-say/suggest");
      const rows = data.cases || [];
      setDrafts(rows);
      setNote(rows.length ? `${rows.length} drafts ready. Keep the ones you want.` : "No owner lines or style notes to draw from yet.");
    } catch (err) {
      setNote(err?.response?.data?.detail || "Could not draft cases.");
    } finally {
      setBusy(false);
    }
  }

  async function keepDrafts() {
    if (!drafts.length) return;
    setBusy(true);
    setNote("");
    try {
      await api.post("/would-say/cases/import", { cases: drafts });
      setNote(`Saved ${drafts.length} from your conversations and style profile.`);
      setDrafts([]);
      load();
    } catch (err) {
      setNote(err?.response?.data?.detail || "Could not save those drafts.");
    } finally {
      setBusy(false);
    }
  }

  async function run(brain) {
    setBusy(true);
    setNote("");
    try {
      const { data } = await api.post("/would-say/run", { brain });
      const fresh = data.runs || [];
      setRuns((prev) => [...fresh, ...prev]);
      if (fresh[0]) setNote(scoreLine(fresh[0]));
    } catch (err) {
      setNote(err?.response?.data?.detail || "The local brain did not finish the run.");
    } finally {
      setBusy(false);
    }
  }

  if (closed) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-8" data-testid="would-say-page">
        <h1 className="font-serif text-3xl">Would C L say that?</h1>
        <p className="text-sm mt-3" data-testid="would-say-closed">This set stays with the owner.</p>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-8" data-testid="would-say-page">
      <div className="overline mb-2">local only</div>
      <h1 className="font-serif text-3xl mb-2" style={{ color: "var(--text-primary)" }}>
        Would C L say that?
      </h1>
      <p className="text-sm mb-6" style={{ color: "var(--text-muted)" }}>
        Cases come from saved owner lines and the style profile. Style uses a local embedding.
        Factual consistency uses the local judge model. Scores are stored on this box, one row per brain.
      </p>

      <form className="surface p-5 mb-6" onSubmit={addCase} data-testid="would-say-form">
        <label className="block text-sm mb-2" htmlFor="would-prompt">Prompt</label>
        <textarea
          id="would-prompt"
          className="w-full mb-3 p-2 text-sm"
          rows={3}
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          data-testid="would-say-prompt"
        />
        <label className="block text-sm mb-2" htmlFor="would-reference">Reference reply</label>
        <textarea
          id="would-reference"
          className="w-full mb-3 p-2 text-sm"
          rows={3}
          value={reference}
          onChange={(event) => setReference(event.target.value)}
          data-testid="would-say-reference"
        />
        <div className="flex flex-wrap gap-2">
          <button type="submit" disabled={busy} data-testid="would-say-add">Add case</button>
          <button type="button" disabled={busy} onClick={suggest} data-testid="would-say-suggest">
            Draft from conversations
          </button>
          <button type="button" disabled={busy || drafts.length === 0} onClick={keepDrafts} data-testid="would-say-keep">
            Keep drafts
          </button>
          <button type="button" disabled={busy} onClick={() => run("local")} data-testid="would-say-run-local">
            Score local
          </button>
          <button type="button" disabled={busy} onClick={() => run("remote")} data-testid="would-say-run-remote">
            Score BIGDEAL
          </button>
          <button type="button" disabled={busy} onClick={() => run("both")} data-testid="would-say-run-both">
            Score both
          </button>
        </div>
        {note ? <p className="text-sm mt-3" data-testid="would-say-note">{note}</p> : null}
        {drafts.map((row, index) => (
          <p key={`draft-${index}`} className="text-sm mt-2" data-testid="would-say-draft" style={{ color: "var(--text-secondary)" }}>
            {row.source} · {row.prompt}
          </p>
        ))}
      </form>

      <section className="surface p-5 mb-6" data-testid="would-say-cases">
        <div className="overline mb-2">{cases.length} cases</div>
        {cases.map((row) => (
          <p key={row.case_id} className="text-sm mb-2" style={{ color: "var(--text-secondary)" }}>
            <span>{row.source || "owner"} · </span>
            {row.prompt}
          </p>
        ))}
      </section>

      <section className="surface p-5" data-testid="would-say-runs">
        <div className="overline mb-2">Scores</div>
        {runs.map((run) => (
          <article key={run.run_id} className="mb-4" data-testid={`would-say-run-${run.brain}`}>
            <p className="font-serif text-lg">{scoreLine(run)}</p>
            {(run.cases || []).slice(0, 3).map((row, index) => (
              <p key={`${run.run_id}-${index}`} className="text-sm" style={{ color: "var(--text-muted)" }}>
                style {Number(row.style || 0).toFixed(2)} · factual {Number(row.factual || 0).toFixed(2)}
                {row.note ? ` · ${row.note}` : ""}
              </p>
            ))}
          </article>
        ))}
      </section>
    </div>
  );
}
