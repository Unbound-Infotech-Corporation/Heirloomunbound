import { useState } from "react";
import { api } from "../../lib/api";
import { voteLabel } from "../../lib/lab";

export default function LabVote({ turnId, enabled }) {
  const [vote, setVote] = useState("");
  const [note, setNote] = useState("");
  const [saved, setSaved] = useState("");
  if (!enabled || !turnId) return null;

  const send = async (next) => {
    setVote(next);
    try {
      await api.post("/lab/feedback", { turn_id: turnId, vote: next, note });
      setSaved(voteLabel(next));
    } catch {
      setSaved("Couldn't save");
    }
  };

  return (
    <div className="mt-3 flex flex-wrap items-center gap-2" data-testid="lab-vote">
      <span className="overline">useful?</span>
      <button
        type="button"
        onClick={() => send("up")}
        data-testid="lab-vote-up"
        className="px-2 py-1 text-xs rounded-sm"
        style={{
          border: "1px solid var(--border-default)",
          color: vote === "up" ? "var(--text-inverse)" : "var(--text-secondary)",
          background: vote === "up" ? "var(--accent)" : "transparent",
        }}
      >
        Useful
      </button>
      <button
        type="button"
        onClick={() => send("down")}
        data-testid="lab-vote-down"
        className="px-2 py-1 text-xs rounded-sm"
        style={{
          border: "1px solid var(--border-default)",
          color: vote === "down" ? "var(--text-inverse)" : "var(--text-secondary)",
          background: vote === "down" ? "var(--accent)" : "transparent",
        }}
      >
        Not useful
      </button>
      <input
        value={note}
        onChange={(event) => setNote(event.target.value)}
        placeholder="Optional note"
        maxLength={500}
        data-testid="lab-vote-note"
        className="px-2 py-1 text-xs rounded-sm bg-transparent"
        style={{ border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
      />
      {saved ? (
        <span className="text-xs" data-testid="lab-vote-saved" style={{ color: "var(--text-muted)" }}>
          {saved}
        </span>
      ) : null}
    </div>
  );
}
