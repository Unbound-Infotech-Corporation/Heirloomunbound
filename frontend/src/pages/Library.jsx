import { useEffect, useState } from "react";
import { Plus, Search, Trash2 } from "lucide-react";
import { api } from "../lib/api";

const TYPES = ["all", "memory", "story", "value", "advice", "quote", "chapter", "voice", "import"];

export default function Library() {
  const [entries, setEntries] = useState([]);
  const [type, setType] = useState("all");
  const [q, setQ] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [draft, setDraft] = useState({ type: "memory", title: "", content: "", tags: "" });

  const load = () => {
    const params = {};
    if (type !== "all") params.type = type;
    if (q) params.q = q;
    api.get("/archive", { params }).then(({ data }) => setEntries(data));
  };

  useEffect(() => {
    load();
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
    <div className="px-10 lg:px-16 py-12 max-w-6xl" data-testid="library-root">
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

      <div className="relative mb-8">
        <Search
          className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4"
          style={{ color: "var(--text-muted)" }}
        />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load()}
          placeholder="Search title, content, tags…"
          data-testid="library-search"
          className="w-full pl-10 pr-3 py-3 text-sm rounded-sm"
          style={{ background: "var(--bg-surface)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
        />
      </div>

      {entries.length === 0 ? (
        <div className="surface p-12 text-center" data-testid="library-empty">
          <div className="overline mb-3">the shelves are bare</div>
          <p className="font-serif text-2xl" style={{ color: "var(--text-secondary)" }}>
            Begin with a single story.
          </p>
        </div>
      ) : (
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
      )}
    </div>
  );
}
