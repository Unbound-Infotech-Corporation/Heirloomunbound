import { useState } from "react";
import { ArrowRight, BookmarkCheck, Brain, Clock, Loader2, Sparkles } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";

const PLACEHOLDERS = [
  "Call mom on Saturday at 2pm…",
  "I learned today that…",
  "Where did dad teach me to fish?",
  "Always tell my son: tell people you love them, out loud, often.",
  "Pick up dry cleaning tomorrow morning…",
];

export default function QuickCapture({ onCaptured }) {
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState(null);
  const [placeholder] = useState(() => PLACEHOLDERS[Math.floor(Math.random() * PLACEHOLDERS.length)]);

  const submit = async () => {
    if (!text.trim() || busy) return;
    setBusy(true);
    setLast(null);
    try {
      const { data } = await api.post("/capture", { text });
      setLast(data);
      setText("");
      if (onCaptured) onCaptured(data);
    } catch (e) {
      setLast({ kind: "error", error: e.response?.data?.detail || e.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="w-full" data-testid="quick-capture">
      <div
        className="flex items-center gap-3 px-4 py-2.5 rounded-sm"
        style={{ background: "var(--bg-surface)", border: "1px solid var(--border-default)" }}
      >
        <Brain className="h-4 w-4 shrink-0" style={{ color: "var(--accent)" }} />
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder={placeholder}
          data-testid="quick-capture-input"
          className="flex-1 bg-transparent border-none outline-none text-sm"
          style={{ color: "var(--text-primary)" }}
        />
        <button
          onClick={submit}
          disabled={busy || !text.trim()}
          data-testid="quick-capture-submit"
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-sm disabled:opacity-40"
          style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ArrowRight className="h-3.5 w-3.5" />}
          Capture
        </button>
      </div>

      {last && (
        <div
          className="mt-3 px-4 py-3 rounded-sm text-sm"
          data-testid="quick-capture-result"
          style={{
            background: "var(--bg-surface)",
            border: "1px solid var(--accent)",
          }}
        >
          {last.kind === "reminder" && (
            <ResultRow icon={<Clock className="h-4 w-4" />} testid="result-reminder">
              <span className="overline mr-2">reminder</span>
              <span style={{ color: "var(--text-primary)" }}>{last.text}</span>
              {last.due_at && (
                <span className="ml-2 font-mono text-xs" style={{ color: "var(--text-muted)" }}>
                  · due {new Date(last.due_at).toLocaleString()}
                </span>
              )}
              <button
                onClick={() => navigate("/today")}
                className="ml-3 text-xs underline"
                style={{ color: "var(--accent)" }}
              >
                view
              </button>
            </ResultRow>
          )}
          {last.kind === "question" && (
            <ResultRow icon={<Sparkles className="h-4 w-4" />} testid="result-question">
              <div>
                <div className="overline mb-1">answer</div>
                <div style={{ color: "var(--text-primary)" }}>{last.answer}</div>
                {last.sources?.length > 0 && (
                  <div className="mt-2 text-xs" style={{ color: "var(--text-muted)" }}>
                    sources: {last.sources.map((s) => s.title).join(" · ")}
                  </div>
                )}
              </div>
            </ResultRow>
          )}
          {last.entry && (
            <ResultRow icon={<BookmarkCheck className="h-4 w-4" />} testid="result-entry">
              <span className="overline mr-2">{last.entry.type}</span>
              <span style={{ color: "var(--text-primary)" }}>{last.entry.title}</span>
              <button
                onClick={() => navigate("/library")}
                className="ml-3 text-xs underline"
                style={{ color: "var(--accent)" }}
              >
                view
              </button>
            </ResultRow>
          )}
          {last.kind === "error" && (
            <span style={{ color: "var(--danger)" }}>Couldn't capture: {last.error}</span>
          )}
        </div>
      )}
    </div>
  );
}

function ResultRow({ icon, children, testid }) {
  return (
    <div className="flex items-start gap-3" data-testid={testid}>
      <span style={{ color: "var(--accent)" }} className="mt-0.5">
        {icon}
      </span>
      <div className="flex-1 leading-snug">{children}</div>
    </div>
  );
}
