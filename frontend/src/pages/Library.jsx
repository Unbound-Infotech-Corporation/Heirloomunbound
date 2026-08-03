import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import { Plus, Search, Sparkles, Trash2, Zap } from "lucide-react";
import { toast } from "sonner";
import { api } from "../lib/api";

const TYPES = ["all", "memory", "story", "value", "advice", "quote", "chapter", "voice", "import"];

export default function Library() {
  const [entries, setEntries] = useState([]);
  const [type, setType] = useState("all");
  const [q, setQ] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [draft, setDraft] = useState({ type: "memory", title: "", content: "", tags: "" });
  const [askMode, setAskMode] = useState(false);
  const [asking, setAsking] = useState(false);
  const [askResult, setAskResult] = useState(null);
  const [searchMode, setSearchMode] = useState(null); // 'semantic' | 'keyword' | null
  const [semStatus, setSemStatus] = useState(null); // {has_provider, embedded, total_entries, ...}
  const [indexing, setIndexing] = useState(false);

  const loadSemStatus = useCallback(() => {
    api.get("/memory/search/status")
      .then(({ data }) => setSemStatus(data))
      .catch(() => setSemStatus(null));
  }, []);

  const load = () => {
    const params = {};
    if (type !== "all") params.type = type;
    if (q) params.q = q;
    api.get("/archive", { params }).then(({ data }) => {
      setEntries(data);
      setSearchMode(null);
    });
  };

  // Semantic search — try /memory/search first, fall back to /archive?q= inside the backend.
  const semanticSearch = () => {
    const query = q.trim();
    if (!query) { load(); return; }
    api.post("/memory/search", { query, limit: 25 })
      .then(({ data }) => {
        setEntries(data.results || []);
        setSearchMode(data.mode || "keyword");
      })
      .catch(() => load());
  };

  const rebuildIndex = () => {
    setIndexing(true);
    api.post("/memory/search/embed/sync", { force: false })
      .then(({ data }) => {
        toast.success(`Indexed ${data.embedded ?? 0} memories.`);
        loadSemStatus();
      })
      .catch((err) => toast.error(err.response?.data?.detail || "Couldn't rebuild the index."))
      .finally(() => setIndexing(false));
  };

  useEffect(() => {
    load();
    loadSemStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [type]);

  const submit = async () => {
    if (!draft.title.trim() || !draft.content.trim()) return;
    const payload = {
      type: draft.type,
      title: draft.title,
      content: draft.content,
      tags: draft.tags ? draft.tags.split(",").map((t) => t.trim()).filter(Boolean) : [],
    };
    await api.post("/archive", payload);
    setShowNew(false);
    setDraft({ type: "memory", title: "", content: "", tags: "" });
    load();
  };

  const remove = async (id) => {
    if (!window.confirm("Remove this entry?")) return;
    await api.delete(`/archive/${id}`);
    load();
  };

  return (
    <div className="px-4 sm:px-8 lg:px-16 py-12 max-w-6xl" data-testid="library-root">
      <header className="mb-10 flex justify-between items-end flex-wrap gap-6">
        <div>
          <div className="overline mb-3">the library</div>
          <h1 className="font-serif text-4xl lg:text-5xl font-light tracking-tight">
            Every piece, gathered.
          </h1>
        </div>
        <button
          onClick={() => setShowNew((s) => !s)}
          data-testid="new-entry-toggle"
          className="inline-flex items-center gap-2 px-5 py-3 text-sm rounded-sm"
          style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
        >
          <Plus className="h-4 w-4" /> New entry
        </button>
      </header>

      {showNew && (
        <div className="surface p-6 mb-10 space-y-4">
          <div className="flex gap-3 flex-wrap">
            <select
              value={draft.type}
              onChange={(e) => setDraft({ ...draft, type: e.target.value })}
              data-testid="new-entry-type"
              className="px-3 py-2 text-sm rounded-sm"
              style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
            >
              {TYPES.filter((t) => t !== "all" && t !== "voice" && t !== "import").map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
            <input
              value={draft.title}
              onChange={(e) => setDraft({ ...draft, title: e.target.value })}
              placeholder="Title"
              data-testid="new-entry-title"
              className="flex-1 px-3 py-2 text-sm rounded-sm"
              style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
            />
          </div>
          <textarea
            value={draft.content}
            onChange={(e) => setDraft({ ...draft, content: e.target.value })}
            placeholder="The story, the memory, the lesson…"
            rows={6}
            data-testid="new-entry-content"
            className="w-full px-3 py-2 text-sm rounded-sm leading-relaxed"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
          />
          <input
            value={draft.tags}
            onChange={(e) => setDraft({ ...draft, tags: e.target.value })}
            placeholder="tags, comma, separated"
            data-testid="new-entry-tags"
            className="w-full px-3 py-2 text-sm rounded-sm"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
          />
          <div className="flex justify-end gap-3">
            <button
              onClick={() => setShowNew(false)}
              className="px-4 py-2 text-sm rounded-sm"
              style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
            >
              Cancel
            </button>
            <button
              onClick={submit}
              data-testid="new-entry-submit"
              className="px-4 py-2 text-sm rounded-sm"
              style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
            >
              Save entry
            </button>
          </div>
        </div>
      )}

      <div className="flex gap-3 flex-wrap mb-6">
        {TYPES.map((t) => (
          <button
            key={t}
            onClick={() => setType(t)}
            data-testid={`filter-${t}`}
            className="px-3 py-1.5 text-xs rounded-sm tracking-wide transition-colors"
            style={{
              border: "1px solid var(--border-default)",
              background: type === t ? "var(--accent)" : "transparent",
              color: type === t ? "var(--text-inverse)" : "var(--text-secondary)",
            }}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="relative mb-2">
        <Search
          className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4"
          style={{ color: "var(--text-muted)" }}
        />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key !== "Enter") return;
            if (askMode) {
              if (!q.trim()) return;
              setAsking(true);
              setAskResult(null);
              api
                .post("/archive/ask", { question: q })
                .then(({ data }) => setAskResult(data))
                .catch((err) => toast.error(err.response?.data?.detail || err.message))
                .finally(() => setAsking(false));
            } else {
              semanticSearch();
            }
          }}
          placeholder={askMode ? "Ask anything: 'What did I think about my first job?'" : "Search by meaning or keyword — try 'my dad&apos;s temper'"}
          data-testid="library-search"
          className="w-full pl-10 pr-3 py-3 text-sm rounded-sm"
          style={{ background: "var(--bg-surface)", border: askMode ? "1px solid var(--accent)" : "1px solid var(--border-default)", color: "var(--text-primary)" }}
        />
      </div>

      {/* Semantic search status ribbon */}
      {!askMode && (
        <div
          className="flex items-center justify-between gap-3 mb-4 flex-wrap text-xs"
          data-testid="semantic-status"
        >
          <div className="flex items-center gap-2" style={{ color: "var(--text-muted)" }}>
            <Zap className="h-3 w-3" style={{ color: semStatus?.has_provider ? "var(--accent)" : "var(--text-muted)" }} />
            {semStatus?.has_provider ? (
              <span>
                semantic search on ·{" "}
                <b style={{ color: "var(--text-secondary)" }}>{semStatus.embedded}</b>
                <span> / {semStatus.total_entries} memories indexed</span>
                {semStatus.pending > 0 && <span> · {semStatus.pending} pending</span>}
                {searchMode === "semantic" && <span style={{ color: "var(--accent)" }}> · ranked by meaning</span>}
                {searchMode === "keyword" && <span> · falling back to keyword</span>}
              </span>
            ) : (
              <span>
                semantic search off ·{" "}
                <Link to="/settings" className="underline" style={{ color: "var(--accent)" }}>
                  set up a local embeddings provider
                </Link>{" "}
                (Ollama, OpenAI, LM Studio) to search by meaning
              </span>
            )}
          </div>
          {semStatus?.has_provider && (
            <button
              type="button"
              onClick={rebuildIndex}
              disabled={indexing}
              data-testid="rebuild-index"
              className="px-3 py-1 rounded-sm disabled:opacity-50"
              style={{ border: "1px solid var(--border-default)", color: "var(--text-muted)" }}
            >
              {indexing ? "indexing…" : "rebuild index"}
            </button>
          )}
        </div>
      )}

      <div className="flex justify-between items-center mb-8">
        <button
          onClick={() => {
            setAskMode((m) => !m);
            setAskResult(null);
          }}
          data-testid="library-ask-toggle"
          className="inline-flex items-center gap-2 px-3 py-1.5 text-xs rounded-sm"
          style={{
            background: askMode ? "var(--accent)" : "transparent",
            color: askMode ? "var(--text-inverse)" : "var(--accent)",
            border: "1px solid var(--accent)",
          }}
        >
          <Sparkles className="h-3.5 w-3.5" />
          {askMode ? "Search mode" : "Ask the archive"}
        </button>
        {askMode && (
          <span className="text-xs italic" style={{ color: "var(--text-muted)" }}>
            press Enter to ask
          </span>
        )}
      </div>

      {askMode && (asking || askResult) && (
        <section className="surface p-6 mb-8" data-testid="library-ask-result">
          {asking ? (
            <div className="flex items-center gap-3 text-sm" style={{ color: "var(--text-muted)" }} data-testid="ask-loading">
              <span
                className="inline-block w-2 h-2 rounded-full animate-pulse"
                style={{ background: "var(--accent)" }}
              />
              Reading your archive — Claude is composing the answer…
            </div>
          ) : (
            <>
              <div className="overline mb-3">the twin&apos;s answer</div>
              <p
                className="font-serif text-lg leading-relaxed mb-6 whitespace-pre-wrap"
                style={{ color: "var(--text-primary)" }}
                data-testid="ask-answer"
              >
                {askResult.answer}
              </p>
              {askResult.citations?.length > 0 && (
                <div>
                  <div className="overline mb-2">drawn from</div>
                  <div className="space-y-2">
                    {askResult.citations.slice(0, 6).map((c) => (
                      <div
                        key={c.entry_id}
                        className="text-sm px-3 py-2 rounded-sm"
                        style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)" }}
                      >
                        <div className="overline mb-0.5">{c.type}</div>
                        <div className="font-serif text-base mb-1">{c.title}</div>
                        <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                          {c.snippet}…
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </section>
      )}

      {!askMode && entries.length === 0 ? (
        <div className="surface p-12 text-center" data-testid="library-empty">
          <div className="overline mb-3">the shelves are bare</div>
          <p className="font-serif text-2xl" style={{ color: "var(--text-secondary)" }}>
            Begin with a single story.
          </p>
        </div>
      ) : !askMode ? (
        <div className="grid md:grid-cols-2 gap-4">
          {entries.map((e) => (
            <div key={e.entry_id} className="surface p-6 group" data-testid={`library-card-${e.entry_id}`}>
              <div className="flex justify-between items-start mb-2">
                <div className="overline">{e.type}</div>
                <button
                  onClick={() => remove(e.entry_id)}
                  data-testid={`delete-${e.entry_id}`}
                  className="opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  <Trash2 className="h-4 w-4" style={{ color: "var(--text-muted)" }} />
                </button>
              </div>
              <h3 className="font-serif text-xl mb-3">{e.title}</h3>
              <p className="text-sm leading-relaxed mb-3" style={{ color: "var(--text-secondary)" }}>
                {e.content.slice(0, 240)}{e.content.length > 240 ? "…" : ""}
              </p>
              <div className="flex justify-between items-center text-xs font-mono" style={{ color: "var(--text-muted)" }}>
                <span>{new Date(e.created_at).toLocaleDateString()}</span>
                {e.tags?.length > 0 && <span>{e.tags.slice(0, 3).join(" · ")}</span>}
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
