import { useEffect, useState } from "react";
import { Lock, Mail, Plus, Trash2, Unlock } from "lucide-react";
import { toast } from "sonner";
import { api } from "../lib/api";

const TRIGGERS = [
  { key: "on_release", label: "When this heir is released" },
  { key: "on_date", label: "On a specific date" },
  { key: "on_age", label: "When they reach a certain age" },
];

const emptyDraft = {
  title: "",
  body: "",
  recipient_heir_id: "",
  recipient_name: "",
  trigger: "on_release",
  delivery_date: "",
  delivery_age: "",
};

export default function Letters() {
  const [letters, setLetters] = useState([]);
  const [heirs, setHeirs] = useState([]);
  const [draft, setDraft] = useState(emptyDraft);
  const [showNew, setShowNew] = useState(false);
  const [editingId, setEditingId] = useState(null);

  const load = async () => {
    const [{ data: l }, { data: h }] = await Promise.all([
      api.get("/letters"),
      api.get("/heirs"),
    ]);
    setLetters(l);
    setHeirs(h);
  };
  useEffect(() => {
    load();
  }, []);

  const resetForm = () => {
    setDraft(emptyDraft);
    setEditingId(null);
    setShowNew(false);
  };

  const submit = async () => {
    if (!draft.title.trim() || !draft.body.trim()) {
      toast.error("Title and body are required");
      return;
    }
    const payload = {
      title: draft.title.trim(),
      body: draft.body,
      recipient_heir_id: draft.recipient_heir_id || null,
      recipient_name: draft.recipient_name || null,
      trigger: draft.trigger,
      delivery_date: draft.trigger === "on_date" ? draft.delivery_date || null : null,
      delivery_age: draft.trigger === "on_age" ? parseInt(draft.delivery_age, 10) || null : null,
    };
    try {
      if (editingId) {
        await api.patch(`/letters/${editingId}`, payload);
        toast.success("Letter updated");
      } else {
        await api.post("/letters", payload);
        toast.success("Letter saved (draft)");
      }
      resetForm();
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message);
    }
  };

  const seal = async (id) => {
    if (!window.confirm("Sealing locks the letter — you won't be able to edit it. Continue?")) return;
    await api.post(`/letters/${id}/seal`);
    toast.success("Letter sealed");
    load();
  };

  const unseal = async (id) => {
    await api.post(`/letters/${id}/unseal`);
    toast.success("Letter unsealed — you can edit again");
    load();
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this letter? This cannot be undone.")) return;
    try {
      await api.delete(`/letters/${id}`);
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message);
    }
  };

  const startEdit = (l) => {
    setEditingId(l.letter_id);
    setShowNew(true);
    setDraft({
      title: l.title || "",
      body: l.body || "",
      recipient_heir_id: l.recipient_heir_id || "",
      recipient_name: l.recipient_name || "",
      trigger: l.trigger || "on_release",
      delivery_date: l.delivery_date || "",
      delivery_age: l.delivery_age ?? "",
    });
  };

  const triggerLabel = (l) => {
    if (l.trigger === "on_date") return `delivered on ${l.delivery_date}`;
    if (l.trigger === "on_age") return `delivered when they are ${l.delivery_age}`;
    return "delivered when this heir is released";
  };

  return (
    <div className="px-10 lg:px-16 py-12 max-w-4xl" data-testid="letters-root">
      <header className="mb-10 flex justify-between items-end flex-wrap gap-6">
        <div>
          <div className="overline mb-3">sealed letters</div>
          <h1 className="font-serif text-4xl lg:text-5xl font-light tracking-tight">
            Write something only they'll read.
          </h1>
          <p className="mt-3 text-base max-w-2xl" style={{ color: "var(--text-secondary)" }}>
            Compose a letter today. Seal it. It stays private until the trigger you choose — a date, an age, or the day your heir is released.
          </p>
        </div>
        <button
          onClick={() => {
            resetForm();
            setShowNew(true);
          }}
          data-testid="new-letter-toggle"
          className="inline-flex items-center gap-2 px-5 py-3 text-sm rounded-sm"
          style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
        >
          <Plus className="h-4 w-4" /> New letter
        </button>
      </header>

      {showNew && (
        <div className="surface p-6 mb-10 space-y-4" data-testid="letter-form">
          <input
            value={draft.title}
            onChange={(e) => setDraft({ ...draft, title: e.target.value })}
            placeholder="Title — e.g. For your 18th birthday"
            data-testid="letter-title"
            className="w-full px-3 py-2 text-sm rounded-sm"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
          />
          <textarea
            value={draft.body}
            onChange={(e) => setDraft({ ...draft, body: e.target.value })}
            placeholder="The letter itself…"
            rows={10}
            data-testid="letter-body"
            className="w-full px-3 py-2 text-sm rounded-sm leading-relaxed font-serif"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)", fontSize: "16px" }}
          />

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="overline block mb-2">to (heir)</label>
              <select
                value={draft.recipient_heir_id}
                onChange={(e) => setDraft({ ...draft, recipient_heir_id: e.target.value })}
                data-testid="letter-recipient"
                className="w-full px-3 py-2 text-sm rounded-sm"
                style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
              >
                <option value="">— anyone released —</option>
                {heirs.map((h) => (
                  <option key={h.heir_id} value={h.heir_id}>
                    {h.name} {h.relationship ? `(${h.relationship})` : ""}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="overline block mb-2">or, name (free text)</label>
              <input
                value={draft.recipient_name}
                onChange={(e) => setDraft({ ...draft, recipient_name: e.target.value })}
                placeholder="e.g. 'My son, Elias'"
                data-testid="letter-recipient-name"
                className="w-full px-3 py-2 text-sm rounded-sm"
                style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
              />
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="overline block mb-2">deliver</label>
              <select
                value={draft.trigger}
                onChange={(e) => setDraft({ ...draft, trigger: e.target.value })}
                data-testid="letter-trigger"
                className="w-full px-3 py-2 text-sm rounded-sm"
                style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
              >
                {TRIGGERS.map((t) => (
                  <option key={t.key} value={t.key}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>
            {draft.trigger === "on_date" && (
              <div>
                <label className="overline block mb-2">delivery date</label>
                <input
                  type="date"
                  value={draft.delivery_date}
                  onChange={(e) => setDraft({ ...draft, delivery_date: e.target.value })}
                  data-testid="letter-date"
                  className="w-full px-3 py-2 text-sm rounded-sm font-mono"
                  style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
                />
              </div>
            )}
            {draft.trigger === "on_age" && (
              <div>
                <label className="overline block mb-2">deliver when they are</label>
                <input
                  type="number"
                  min="0"
                  max="150"
                  value={draft.delivery_age}
                  onChange={(e) => setDraft({ ...draft, delivery_age: e.target.value })}
                  placeholder="18"
                  data-testid="letter-age"
                  className="w-full px-3 py-2 text-sm rounded-sm font-mono"
                  style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
                />
              </div>
            )}
          </div>

          <div className="flex justify-end gap-3">
            <button
              onClick={resetForm}
              className="px-4 py-2 text-sm rounded-sm"
              style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
            >
              Cancel
            </button>
            <button
              onClick={submit}
              data-testid="letter-submit"
              className="px-4 py-2 text-sm rounded-sm"
              style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
            >
              {editingId ? "Save changes" : "Save as draft"}
            </button>
          </div>
        </div>
      )}

      {letters.length === 0 ? (
        <div className="surface p-12 text-center" data-testid="letters-empty">
          <Mail className="h-8 w-8 mx-auto mb-3" style={{ color: "var(--text-muted)" }} />
          <div className="overline mb-3">nothing sealed yet</div>
          <p className="font-serif text-2xl" style={{ color: "var(--text-secondary)" }}>
            What would you say if you only got one chance?
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {letters.map((l) => {
            const heir = heirs.find((h) => h.heir_id === l.recipient_heir_id);
            return (
              <div
                key={l.letter_id}
                className="surface p-6"
                data-testid={`letter-${l.letter_id}`}
              >
                <div className="flex justify-between items-start gap-4 mb-3">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      {l.sealed ? (
                        <Lock className="h-4 w-4" style={{ color: "var(--accent)" }} />
                      ) : (
                        <Unlock className="h-4 w-4" style={{ color: "var(--text-muted)" }} />
                      )}
                      <span className="overline">
                        {l.sealed ? "sealed" : "draft"}
                        {l.delivered ? " · delivered" : ""}
                      </span>
                    </div>
                    <h3 className="font-serif text-2xl mb-2">{l.title}</h3>
                    <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                      to {heir?.name || l.recipient_name || "any released heir"} · {triggerLabel(l)}
                    </div>
                  </div>
                  {!l.delivered && (
                    <button
                      onClick={() => remove(l.letter_id)}
                      data-testid={`delete-letter-${l.letter_id}`}
                      className="p-2"
                      title="Delete"
                    >
                      <Trash2 className="h-4 w-4" style={{ color: "var(--text-muted)" }} />
                    </button>
                  )}
                </div>
                {!l.sealed && (
                  <p
                    className="font-serif text-base leading-relaxed whitespace-pre-wrap mb-3 line-clamp-5"
                    style={{ color: "var(--text-secondary)" }}
                  >
                    {l.body.slice(0, 400)}
                    {l.body.length > 400 ? "…" : ""}
                  </p>
                )}
                {l.sealed && !l.delivered && (
                  <p className="text-xs italic mb-3" style={{ color: "var(--text-muted)" }}>
                    contents hidden — sealed until {triggerLabel(l)}
                  </p>
                )}
                <div className="flex gap-2">
                  {!l.sealed && (
                    <>
                      <button
                        onClick={() => startEdit(l)}
                        data-testid={`edit-letter-${l.letter_id}`}
                        className="px-3 py-1.5 text-xs rounded-sm"
                        style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => seal(l.letter_id)}
                        data-testid={`seal-letter-${l.letter_id}`}
                        className="px-3 py-1.5 text-xs rounded-sm inline-flex items-center gap-1.5"
                        style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
                      >
                        <Lock className="h-3 w-3" /> Seal
                      </button>
                    </>
                  )}
                  {l.sealed && !l.delivered && (
                    <button
                      onClick={() => unseal(l.letter_id)}
                      data-testid={`unseal-letter-${l.letter_id}`}
                      className="px-3 py-1.5 text-xs rounded-sm inline-flex items-center gap-1.5"
                      style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
                    >
                      <Unlock className="h-3 w-3" /> Unseal to edit
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
