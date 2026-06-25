import { useEffect, useState } from "react";
import { CheckCircle2, Circle, Plus, Trash2 } from "lucide-react";
import { api } from "../lib/api";

const FILTERS = [
  { key: "open", label: "Open" },
  { key: "done", label: "Done" },
  { key: "all", label: "All" },
];

export default function Reminders() {
  const [status, setStatus] = useState("open");
  const [items, setItems] = useState([]);
  const [showNew, setShowNew] = useState(false);
  const [draft, setDraft] = useState({ text: "", due_at: "", notes: "" });

  const load = () => {
    const params = status === "all" ? {} : { status };
    api.get("/reminders", { params }).then(({ data }) => setItems(data));
  };
  useEffect(() => {
    load();
    // eslint-disable-next-line
  }, [status]);

  const submit = async () => {
    if (!draft.text.trim()) return;
    await api.post("/reminders", {
      text: draft.text,
      due_at: draft.due_at ? new Date(draft.due_at).toISOString() : null,
      notes: draft.notes || null,
    });
    setDraft({ text: "", due_at: "", notes: "" });
    setShowNew(false);
    load();
  };

  const complete = async (id) => {
    await api.post(`/reminders/${id}/complete`);
    load();
  };

  const reopen = async (id) => {
    await api.patch(`/reminders/${id}`, { status: "open" });
    load();
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this reminder?")) return;
    await api.delete(`/reminders/${id}`);
    load();
  };

  return (
    <div className="px-10 lg:px-16 py-12 max-w-4xl" data-testid="reminders-root">
      <header className="mb-10 flex justify-between items-end flex-wrap gap-6">
        <div>
          <div className="overline mb-3">your reminders</div>
          <h1 className="font-serif text-4xl lg:text-5xl font-light tracking-tight">
            Things to remember.
          </h1>
        </div>
        <button
          onClick={() => setShowNew((s) => !s)}
          data-testid="new-reminder-toggle"
          className="inline-flex items-center gap-2 px-5 py-3 text-sm rounded-sm"
          style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
        >
          <Plus className="h-4 w-4" /> New reminder
        </button>
      </header>

      {showNew && (
        <div className="surface p-6 mb-10 space-y-4">
          <input
            value={draft.text}
            onChange={(e) => setDraft({ ...draft, text: e.target.value })}
            placeholder="What do you want to remember?"
            data-testid="reminder-text"
            className="w-full px-3 py-2 text-sm rounded-sm"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
          />
          <div className="flex gap-3 items-center">
            <label className="overline">when</label>
            <input
              type="datetime-local"
              value={draft.due_at}
              onChange={(e) => setDraft({ ...draft, due_at: e.target.value })}
              data-testid="reminder-due"
              className="px-3 py-2 text-sm rounded-sm font-mono"
              style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
            />
          </div>
          <textarea
            value={draft.notes}
            onChange={(e) => setDraft({ ...draft, notes: e.target.value })}
            placeholder="Notes (optional)"
            rows={3}
            data-testid="reminder-notes"
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
              data-testid="reminder-submit"
              className="px-4 py-2 text-sm rounded-sm"
              style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
            >
              Save reminder
            </button>
          </div>
        </div>
      )}

      <div className="flex gap-3 flex-wrap mb-6">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setStatus(f.key)}
            data-testid={`reminder-filter-${f.key}`}
            className="px-3 py-1.5 text-xs rounded-sm tracking-wide transition-colors"
            style={{
              border: "1px solid var(--border-default)",
              background: status === f.key ? "var(--accent)" : "transparent",
              color: status === f.key ? "var(--text-inverse)" : "var(--text-secondary)",
            }}
          >
            {f.label}
          </button>
        ))}
      </div>

      {items.length === 0 ? (
        <div className="surface p-12 text-center" data-testid="reminders-empty">
          <p className="font-serif text-2xl" style={{ color: "var(--text-secondary)" }}>
            Nothing here.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {items.map((r) => {
            const done = r.status === "done";
            return (
              <div
                key={r.reminder_id}
                className="surface px-5 py-4 flex items-center gap-4 group"
                data-testid={`row-${r.reminder_id}`}
              >
                <button
                  onClick={() => (done ? reopen(r.reminder_id) : complete(r.reminder_id))}
                  data-testid={`toggle-${r.reminder_id}`}
                >
                  {done ? (
                    <CheckCircle2 className="h-5 w-5" style={{ color: "var(--accent)" }} />
                  ) : (
                    <Circle className="h-5 w-5" style={{ color: "var(--text-muted)" }} />
                  )}
                </button>
                <div className="flex-1">
                  <div
                    className="text-sm"
                    style={{
                      color: done ? "var(--text-muted)" : "var(--text-primary)",
                      textDecoration: done ? "line-through" : "none",
                    }}
                  >
                    {r.text}
                  </div>
                  <div className="flex gap-3 mt-1 font-mono text-xs" style={{ color: "var(--text-muted)" }}>
                    {r.due_at && <span>due {new Date(r.due_at).toLocaleString()}</span>}
                    {r.completed_at && <span>completed {new Date(r.completed_at).toLocaleString()}</span>}
                  </div>
                  {r.notes && (
                    <div className="text-xs mt-2" style={{ color: "var(--text-secondary)" }}>
                      {r.notes}
                    </div>
                  )}
                </div>
                <button
                  onClick={() => remove(r.reminder_id)}
                  data-testid={`delete-${r.reminder_id}`}
                  className="opacity-0 group-hover:opacity-100 transition-opacity"
                >
                  <Trash2 className="h-4 w-4" style={{ color: "var(--text-muted)" }} />
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
