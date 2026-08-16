import { useEffect, useState } from "react";
import { Keyboard, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { usePageMeta } from "@/lib/usePageMeta";

function issueKey(issue) {
  return `${issue.kind || ""}:${String(issue.text || "").toLowerCase()}`;
}

export default function Writing() {
  usePageMeta({
    title: "Unbound Keyboard · Heirloom",
    description: "Fix spelling and grammar as you type, in your voice — never a password box.",
  });

  const [text, setText] = useState("");
  const [issues, setIssues] = useState([]);
  const [ignored, setIgnored] = useState(() => new Set());
  const [lastCorrected, setLastCorrected] = useState("");
  const [note, setNote] = useState("Type or paste. I'll catch slips without watching every key on the computer.");
  const [busy, setBusy] = useState(false);
  const [style, setStyle] = useState(null);
  const [house, setHouse] = useState(null);

  useEffect(() => {
    api.get("/writing/style").then(({ data }) => setStyle(data)).catch(() => {});
    api.get("/writing/house-key").then(({ data }) => setHouse(data)).catch(() => {});
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

  const fixSpelling = () => {
    if (!lastCorrected) return;
    setText(lastCorrected);
    setIssues([]);
  };

  const leaveIt = () => {
    setIgnored((prev) => {
      const next = new Set(prev);
      visibleIssues.forEach((issue) => next.add(issueKey(issue)));
      return next;
    });
  };

  const polish = async () => {
    if (!text.trim() || busy) return;
    setBusy(true);
    try {
      const { data } = await api.post("/writing/polish", { text });
      if (data.secret) {
        setNote(data.note);
      } else {
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
      setHouse((h) => ({ ...(h || {}), house_url: data.house_url, active_keys: (h?.active_keys || 0) + 1 }));
      toast.success("House slip copied. Paste it once into Unbound Keyboard on your phone.");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't make a house key.");
    }
  };

  const revokeKeys = async () => {
    if (!window.confirm("This phone key will stop working. You can copy a new one anytime.")) return;
    try {
      const { data } = await api.post("/writing/house-key/revoke");
      setHouse((h) => ({ ...(h || {}), active_keys: 0 }));
      toast.success(data.note || "That phone key will not work anymore.");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't stop that key.");
    }
  };

  return (
    <div className="max-w-3xl mx-auto px-6 py-10" data-testid="writing-root">
      <p className="overline mb-3">Unbound Keyboard</p>
      <h1 className="font-serif text-4xl mb-3" style={{ color: "var(--text-primary)" }}>
        Write like yourself. We'll catch the rest.
      </h1>
      <p className="mb-8" style={{ color: "var(--text-muted)" }}>
        On a phone, choose Unbound Keyboard as the keyboard — it fixes spelling and grammar on the fly,
        and notices when you lean on the same word. On this computer it's a writing helper for the words
        you type or paste here, not a spy on every key. We never read password boxes.
      </p>

      <textarea
        data-testid="writing-editor"
        className="w-full min-h-[220px] p-4 rounded-sm mb-4"
        style={{
          background: "var(--surface-elev)",
          border: "1px solid var(--border-default)",
          color: "var(--text-primary)",
        }}
        placeholder="Type or paste the words you want help with…"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />

      <p className="text-sm mb-4" data-testid="writing-note" style={{ color: "var(--text-muted)" }}>
        {note}
      </p>

      {visibleIssues.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-6" data-testid="writing-issues">
          {visibleIssues.map((issue, i) => (
            <button
              key={`${issue.start}-${i}`}
              type="button"
              onClick={() => applyIssue(issue)}
              className="text-xs px-3 py-1.5 rounded-full border"
              title={issue.note}
              style={{ borderColor: "var(--border-default)", color: "var(--text-primary)" }}
            >
              {issue.text}
              {issue.suggestions?.[0] ? ` → ${issue.suggestions[0]}` : ""}
            </button>
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-3 mb-12">
        <button
          type="button"
          data-testid="writing-fix-spelling"
          onClick={fixSpelling}
          disabled={!lastCorrected || lastCorrected === text}
          className="px-4 py-2 rounded-sm text-sm border"
          style={{ borderColor: "var(--border-default)" }}
        >
          Fix spelling
        </button>
        <button
          type="button"
          data-testid="writing-leave-it"
          onClick={leaveIt}
          disabled={visibleIssues.length === 0}
          className="px-4 py-2 rounded-sm text-sm border"
          style={{ borderColor: "var(--border-default)" }}
        >
          Leave it
        </button>
        <button
          type="button"
          data-testid="writing-polish"
          onClick={polish}
          disabled={busy}
          className="px-4 py-2 rounded-sm text-sm"
          style={{ background: "var(--accent)", color: "var(--bg-base)" }}
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin inline" /> : "Make it sound like me"}
        </button>
      </div>

      {style && (
        <section className="surface p-6 mb-8" data-testid="writing-habits">
          <h2 className="font-serif text-2xl mb-2">Your word habits</h2>
          <p className="text-sm mb-3" style={{ color: "var(--text-muted)" }}>{style.summary}</p>
          <p className="text-xs" style={{ color: "var(--text-muted)" }}>{style.privacy}</p>
        </section>
      )}

      <section className="surface p-6" data-testid="writing-phone">
        <div className="flex items-start gap-3 mb-3">
          <Keyboard className="h-5 w-5 mt-1" style={{ color: "var(--accent)" }} />
          <div>
            <h2 className="font-serif text-2xl mb-2">On your phone</h2>
            <ol className="text-sm space-y-2 list-decimal pl-5" style={{ color: "var(--text-muted)" }}>
              <li>On Android, tap UnboundKeyboard.apk from the try-it zip (or open the Android folder and install). Then Settings → System → Languages &amp; input → On-screen keyboard → Unbound Keyboard.</li>
              <li>When you type, tap 🌐 to switch back to your old keyboard. 123 opens numbers.</li>
              <li>Open Unbound Keyboard settings and paste the house slip once{house?.house_url ? ` (${house.house_url})` : ""}. Copy it below.</li>
              <li>On iPhone, use this Write page in the Heirloom app. Apple does not let us install this keyboard.</li>
            </ol>
            <button
              type="button"
              data-testid="writing-copy-key"
              onClick={copyKey}
              className="mt-4 px-4 py-2 rounded-sm text-sm border"
              style={{ borderColor: "var(--border-default)" }}
            >
              Copy my house key
            </button>
            {(house?.active_keys || 0) > 0 && (
              <button
                type="button"
                data-testid="writing-revoke-key"
                onClick={revokeKeys}
                className="mt-4 ml-3 px-4 py-2 rounded-sm text-sm border"
                style={{ borderColor: "var(--border-default)" }}
              >
                Stop this phone key
              </button>
            )}
            <p className="text-xs mt-3" style={{ color: "var(--text-muted)" }}>
              A house key is a Heirloom token — not a Google, Microsoft, or phone password. We never ask for those.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
