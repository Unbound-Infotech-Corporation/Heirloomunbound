import { useEffect, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { api } from "../lib/api";

const empty = { name: "", email: "", relationship: "", note: "", release_on: "" };

export default function Heirs() {
  const [heirs, setHeirs] = useState([]);
  const [showNew, setShowNew] = useState(false);
  const [draft, setDraft] = useState(empty);

  const load = () => api.get("/heirs").then(({ data }) => setHeirs(data));
  useEffect(() => {
    load();
  }, []);

  const submit = async () => {
    if (!draft.name.trim() || !draft.email.trim()) return;
    try {
      await api.post("/heirs", { ...draft, release_on: draft.release_on || null });
      setShowNew(false);
      setDraft(empty);
      load();
    } catch (e) {
      alert(e.response?.data?.detail || e.message);
    }
  };

  const remove = async (id) => {
    if (!window.confirm("Remove this heir?")) return;
    await api.delete(`/heirs/${id}`);
    load();
  };

  return (
    <div className="px-10 lg:px-16 py-12 max-w-4xl" data-testid="heirs-root">
      <header className="mb-10 flex justify-between items-end flex-wrap gap-6">
        <div>
          <div className="overline mb-3">the keepers</div>
          <h1 className="font-serif text-4xl lg:text-5xl font-light tracking-tight">
            Who do you trust with this?
          </h1>
          <p className="mt-3 text-base max-w-2xl" style={{ color: "var(--text-secondary)" }}>
            Name the people who should be able to sit with your twin one day. They'll be notified when their access opens.
          </p>
        </div>
        <button
          onClick={() => setShowNew((s) => !s)}
          data-testid="new-heir-toggle"
          className="inline-flex items-center gap-2 px-5 py-3 text-sm rounded-sm"
          style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
        >
          <Plus className="h-4 w-4" /> Add heir
        </button>
      </header>

      {showNew && (
        <div className="surface p-6 mb-10 space-y-4">
          <input
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            placeholder="Name (e.g. Elias — my son)"
            data-testid="heir-name"
            className="w-full px-3 py-2 text-sm rounded-sm"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
          />
          <input
            value={draft.email}
            onChange={(e) => setDraft({ ...draft, email: e.target.value })}
            placeholder="Email"
            type="email"
            data-testid="heir-email"
            className="w-full px-3 py-2 text-sm rounded-sm"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
          />
          <input
            value={draft.relationship}
            onChange={(e) => setDraft({ ...draft, relationship: e.target.value })}
            placeholder="Relationship (son, partner, friend…)"
            data-testid="heir-rel"
            className="w-full px-3 py-2 text-sm rounded-sm"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
          />
          <textarea
            value={draft.note}
            onChange={(e) => setDraft({ ...draft, note: e.target.value })}
            placeholder="A private note to them (read only after release)"
            rows={4}
            data-testid="heir-note"
            className="w-full px-3 py-2 text-sm rounded-sm leading-relaxed"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
          />
          <div className="flex gap-3 items-center">
            <label className="overline">release date (optional)</label>
            <input
              type="date"
              value={draft.release_on}
              onChange={(e) => setDraft({ ...draft, release_on: e.target.value })}
              data-testid="heir-release"
              className="px-3 py-2 text-sm rounded-sm font-mono"
              style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
            />
          </div>
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
              data-testid="heir-submit"
              className="px-4 py-2 text-sm rounded-sm"
              style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
            >
              Add heir
            </button>
          </div>
        </div>
      )}

      {heirs.length === 0 ? (
        <div className="surface p-12 text-center" data-testid="heirs-empty">
          <div className="overline mb-3">no heirs yet</div>
          <p className="font-serif text-2xl" style={{ color: "var(--text-secondary)" }}>
            Begin with one person.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {heirs.map((h) => (
            <div key={h.heir_id} className="surface p-6" data-testid={`heir-${h.heir_id}`}>
              <div className="flex justify-between items-start gap-4">
                <div>
                  <div className="overline mb-1">{h.relationship || "trusted"}</div>
                  <h3 className="font-serif text-2xl mb-1">{h.name}</h3>
                  <div className="text-sm font-mono" style={{ color: "var(--text-muted)" }}>
                    {h.email}
                  </div>
                  {h.note && (
                    <p className="text-sm mt-3 leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                      "{h.note}"
                    </p>
                  )}
                  {h.release_on && (
                    <div className="overline mt-3">
                      release: <span style={{ color: "var(--text-secondary)" }}>{h.release_on}</span>
                    </div>
                  )}
                </div>
                <button
                  onClick={() => remove(h.heir_id)}
                  data-testid={`delete-heir-${h.heir_id}`}
                  className="p-2"
                >
                  <Trash2 className="h-4 w-4" style={{ color: "var(--text-muted)" }} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
