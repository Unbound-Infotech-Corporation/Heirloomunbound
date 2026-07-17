import { useEffect, useState } from "react";
import { Loader2, Upload as UploadIcon } from "lucide-react";
import { api } from "../lib/api";

const SOURCES = [
  { key: "facebook", label: "Facebook export / posts" },
  { key: "twitter", label: "Twitter / X" },
  { key: "reddit", label: "Reddit comments" },
  { key: "blog", label: "Blog / website" },
  { key: "discord", label: "Discord chat log" },
  { key: "whatsapp", label: "WhatsApp chat export" },
  { key: "sms", label: "SMS / text dump" },
  { key: "other", label: "Other text" },
];

export default function Import() {
  const [source, setSource] = useState("facebook");
  const [raw, setRaw] = useState("");
  const [autoExtract, setAutoExtract] = useState(true);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);

  const loadHistory = () => api.get("/import").then(({ data }) => setHistory(data));
  useEffect(() => {
    loadHistory();
  }, []);

  const submit = async () => {
    if (!raw.trim()) return;
    setBusy(true);
    setResult(null);
    try {
      const { data } = await api.post("/import", { source, raw_text: raw, auto_extract: autoExtract });
      setResult(data);
      setRaw("");
      loadHistory();
    } catch (e) {
      alert(e.message);
    } finally {
      setBusy(false);
    }
  };

  const handleFile = (file) => {
    const reader = new FileReader();
    reader.onload = (e) => setRaw(String(e.target.result || ""));
    reader.readAsText(file);
  };

  return (
    <div className="px-4 sm:px-8 lg:px-16 py-12 max-w-5xl" data-testid="import-root">
      <header className="mb-10">
        <div className="overline mb-3">seed from elsewhere</div>
        <h1 className="font-serif text-4xl lg:text-5xl font-light tracking-tight">
          Bring the past in.
        </h1>
        <p className="mt-3 text-base max-w-2xl" style={{ color: "var(--text-secondary)" }}>
          Paste posts, blog excerpts, chats, anything written in your voice. WhatsApp and SMS dumps
          are parsed into conversation chunks automatically; other sources use AI extraction.
        </p>
      </header>

      <div className="surface p-7 mb-6">
        <div className="flex gap-3 flex-wrap mb-5">
          {SOURCES.map((s) => (
            <button
              key={s.key}
              onClick={() => setSource(s.key)}
              data-testid={`source-${s.key}`}
              className="px-3 py-1.5 text-xs rounded-sm tracking-wide transition-colors"
              style={{
                border: "1px solid var(--border-default)",
                background: source === s.key ? "var(--accent)" : "transparent",
                color: source === s.key ? "var(--text-inverse)" : "var(--text-secondary)",
              }}
            >
              {s.label}
            </button>
          ))}
        </div>

        <textarea
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          placeholder={
            source === "whatsapp"
              ? "Paste a WhatsApp chat export (.txt) — lines like [12/03/2024, 14:22:01] Name: message"
              : source === "sms"
              ? "Paste SMS Backup XML or From:/Date: text blocks…"
              : "Paste raw text here — Facebook export, tweets, chat logs, blog posts…"
          }
          rows={12}
          data-testid="import-textarea"
          className="w-full px-4 py-3 text-sm rounded-sm leading-relaxed font-mono"
          style={{
            background: "var(--bg-base)",
            border: "1px solid var(--border-default)",
            color: "var(--text-primary)",
          }}
        />

        <div className="flex flex-wrap items-center justify-between gap-4 mt-4">
          <label className="flex items-center gap-3 text-sm cursor-pointer" style={{ color: "var(--text-secondary)" }}>
            <input
              type="checkbox"
              checked={autoExtract}
              onChange={(e) => setAutoExtract(e.target.checked)}
              data-testid="import-auto-extract"
              className="h-4 w-4"
            />
            Let the AI extract structured memories
          </label>

          <div className="flex gap-3">
            <label
              className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded-sm cursor-pointer"
              style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
            >
              <UploadIcon className="h-4 w-4" />
              Load .txt / .json
              <input
                type="file"
                accept=".txt,.json,.md,.csv,.html"
                onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
                className="hidden"
                data-testid="import-file"
              />
            </label>
            <button
              onClick={submit}
              disabled={busy || !raw.trim()}
              data-testid="import-submit"
              className="inline-flex items-center gap-2 px-5 py-2 text-sm font-medium rounded-sm disabled:opacity-50"
              style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
            >
              {busy && <Loader2 className="h-4 w-4 animate-spin" />}
              {busy ? "Reading…" : "Import"}
            </button>
          </div>
        </div>
      </div>

      {result && (
        <div className="surface p-6 mb-10" data-testid="import-result">
          <div className="overline mb-3">extracted</div>
          <p className="font-serif text-2xl mb-4">
            {result.count} {result.count === 1 ? "memory" : "memories"} added to your archive
          </p>
          <ul className="space-y-3">
            {(result.extracted || []).map((e) => (
              <li key={e.entry_id} className="text-sm" style={{ color: "var(--text-secondary)" }}>
                <span className="overline mr-2">{e.type}</span>
                <span className="text-[var(--text-primary)] font-serif text-base">{e.title}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <section>
        <div className="overline mb-4">previous imports</div>
        {history.length === 0 ? (
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
            None yet.
          </p>
        ) : (
          <div className="space-y-3">
            {history.map((h) => (
              <div
                key={h.import_id}
                className="surface px-5 py-4 flex justify-between text-sm"
                data-testid={`import-history-${h.import_id}`}
              >
                <div>
                  <div className="overline mb-1">{h.source}</div>
                  <div style={{ color: "var(--text-secondary)" }}>
                    {h.extracted_count} extracted
                  </div>
                </div>
                <div className="font-mono text-xs" style={{ color: "var(--text-muted)" }}>
                  {new Date(h.created_at).toLocaleString()}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
