import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

/**
 * Phone writing helper — same brain as Unbound Keyboard.
 * The real Android IME lives in android/unbound-keyboard; this page lets
 * someone try proofreading before they sideload the keyboard.
 */
function issueKey(issue) {
  return `${issue.kind || ""}:${String(issue.text || "").toLowerCase()}`;
}

export default function MobileKeyboard() {
  const [text, setText] = useState("");
  const [issues, setIssues] = useState([]);
  const [ignored, setIgnored] = useState(() => new Set());
  const [lastCorrected, setLastCorrected] = useState("");
  const [note, setNote] = useState("Type here. Unbound Keyboard will catch slips — never in a password box.");
  const [busy, setBusy] = useState(false);
  const [style, setStyle] = useState(null);

  useEffect(() => {
    api.get("/writing/style").then(({ data }) => setStyle(data)).catch(() => {});
  }, []);

  useEffect(() => {
    if (!text.trim()) {
      setIgnored(new Set());
      return undefined;
    }
    const t = setTimeout(() => {
      api.post("/writing/proofread", { text }).then(({ data }) => {
        if (data.secret) {
          setNote(data.style_note);
          setIssues([]);
          setLastCorrected("");
          return;
        }
        setNote(data.style_note || "");
        setIssues(data.issues || []);
        setLastCorrected(data.corrected || "");
      }).catch(() => {});
    }, 700);
    return () => clearTimeout(t);
  }, [text]);

  const visibleIssues = issues.filter((issue) => !ignored.has(issueKey(issue)));

  const applyIssue = (issue) => {
    const next = issue.suggestions?.[0];
    if (next == null) return;
    setText((cur) => cur.slice(0, issue.start) + next + cur.slice(issue.end));
  };

  const polish = async () => {
    if (!text.trim() || busy) return;
    setBusy(true);
    try {
      const { data } = await api.post("/writing/polish", { text });
      if (data.secret) setNote(data.note);
      else {
        if (data.polished) setText(data.polished);
        setNote(data.note || "");
        setIssues(data.issues || []);
        setLastCorrected(data.polished || lastCorrected);
      }
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't polish that.");
    } finally {
      setBusy(false);
    }
  };

  const copyKey = async () => {
    try {
      const { data } = await api.post("/writing/house-key");
      const blob = data.blob || `HOUSE\n${data.house_url || ""}\n${data.token}\n`;
      await navigator.clipboard.writeText(blob);
      toast.success("House slip copied. Paste it once in Unbound Keyboard settings.");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't make a house key.");
    }
  };

  return (
    <div className="px-4 py-5" data-testid="mobile-keyboard-root">
      <p className="text-xs uppercase tracking-widest mb-2" style={{ color: "var(--text-muted)" }}>
        Unbound Keyboard
      </p>
      <h1 className="text-2xl font-semibold mb-2">Write. We'll catch the slips.</h1>
      <p className="text-sm mb-4" style={{ color: "var(--text-muted)" }}>
        Choose Unbound Keyboard as your Android keyboard to fix spelling in any app.
        This page is the same helper. We never read password boxes. On iPhone, stay here.
      </p>
      <textarea
        data-testid="mobile-keyboard-editor"
        className="w-full min-h-[160px] p-3 rounded-md mb-3 text-base"
        style={{
          background: "var(--surface-elev)",
          border: "1px solid var(--border-default)",
          color: "var(--text-primary)",
        }}
        placeholder="Type here…"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <p className="text-sm mb-3" data-testid="mobile-keyboard-note">{note}</p>
      {visibleIssues.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-4">
          {visibleIssues.map((issue, i) => (
            <button
              key={`${issue.start}-${i}`}
              type="button"
              onClick={() => applyIssue(issue)}
              className="text-xs px-3 py-2 rounded-full border"
              title={issue.note}
            >
              {issue.text}
              {issue.suggestions?.[0] ? ` → ${issue.suggestions[0]}` : ""}
            </button>
          ))}
        </div>
      )}
      <button
        type="button"
        data-testid="mobile-keyboard-fix-spelling"
        onClick={() => lastCorrected && setText(lastCorrected)}
        disabled={!lastCorrected || lastCorrected === text}
        className="w-full py-3 rounded-md mb-2 border text-sm"
      >
        Fix spelling
      </button>
      <button
        type="button"
        data-testid="mobile-keyboard-leave-it"
        onClick={() => {
          setIgnored((prev) => {
            const next = new Set(prev);
            visibleIssues.forEach((issue) => next.add(issueKey(issue)));
            return next;
          });
        }}
        disabled={visibleIssues.length === 0}
        className="w-full py-3 rounded-md mb-2 border text-sm"
      >
        Leave it
      </button>
      <button
        type="button"
        data-testid="mobile-keyboard-polish"
        onClick={polish}
        disabled={busy}
        className="w-full py-3 rounded-md mb-3"
        style={{ background: "var(--accent)", color: "var(--bg-base)" }}
      >
        {busy ? <Loader2 className="h-4 w-4 animate-spin inline" /> : "Make it sound like me"}
      </button>
      <button
        type="button"
        data-testid="mobile-keyboard-copy-key"
        onClick={copyKey}
        className="w-full py-3 rounded-md border text-sm mb-4"
      >
        Copy my house key
      </button>
      {style && (
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          {style.summary} {style.privacy}
        </p>
      )}
    </div>
  );
}
