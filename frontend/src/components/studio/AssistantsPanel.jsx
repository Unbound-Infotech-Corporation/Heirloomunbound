import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api } from "../../lib/api";

const EMPTY = { name: "", role: "", tools_allowlist: [] };

export default function AssistantsPanel({ testid = "assistants-panel" }) {
  const [assistants, setAssistants] = useState([]);
  const [tools, setTools] = useState([]);
  const [draft, setDraft] = useState(EMPTY);

  const load = async () => {
    const { data } = await api.get("/assistants");
    setAssistants(data.assistants || []);
    setTools(data.tools || []);
  };

  useEffect(() => {
    load().catch(() => {});
  }, []);

  const create = async () => {
    if (!draft.name.trim()) return;
    try {
      await api.post("/assistants", {
        name: draft.name.trim(),
        role: draft.role,
        tools_allowlist: draft.tools_allowlist,
        enabled: true,
      });
      setDraft(EMPTY);
      toast.success("Assistant added");
      await load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Couldn't add that assistant.");
    }
  };

  const patch = async (id, body) => {
    try {
      await api.patch(`/assistants/${id}`, body);
      await load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Couldn't update.");
    }
  };

  const remove = async (id) => {
    try {
      await api.delete(`/assistants/${id}`);
      toast.success("Assistant removed");
      await load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Couldn't remove.");
    }
  };

  const toggleTool = (id) => {
    setDraft((d) => {
      const has = d.tools_allowlist.includes(id);
      return {
        ...d,
        tools_allowlist: has ? d.tools_allowlist.filter((t) => t !== id) : [...d.tools_allowlist, id],
      };
    });
  };

  return (
    <section className="surface p-7 mb-6" data-testid={testid}>
      <div className="overline mb-2">assistants under the twin</div>
      <h2 className="font-serif text-2xl mb-2">Specialists, not a second person</h2>
      <p className="text-sm mb-5" style={{ color: "var(--text-secondary)" }}>
        The twin stays the person. Assistants are named teammates you can pick or @mention —
        research, letters, archive, PC. PC tools still belong to Assist. Heirs never see this list.
      </p>

      <div className="space-y-3 mb-6" data-testid="assistants-list">
        {assistants.map((a) => (
          <div
            key={a.assistant_id}
            className="p-4 rounded-sm"
            data-testid={`assistant-row-${a.slug || a.assistant_id}`}
            style={{ border: "1px solid var(--border-default)" }}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="font-serif text-lg">{a.name}</div>
                <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                  @{a.slug} · {a.speak_as === "assist" ? "Assist / PC" : "specialist"} ·{" "}
                  {(a.tools_allowlist || []).join(", ") || "no extra tools"}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  data-testid={`assistant-toggle-${a.slug}`}
                  onClick={() => patch(a.assistant_id, { enabled: !a.enabled })}
                  className="px-3 py-1 text-xs rounded-sm"
                  style={{ border: "1px solid var(--border-default)" }}
                >
                  {a.enabled ? "Disable" : "Enable"}
                </button>
                <button
                  type="button"
                  data-testid={`assistant-delete-${a.slug}`}
                  onClick={() => remove(a.assistant_id)}
                  className="px-3 py-1 text-xs rounded-sm"
                  style={{ color: "var(--text-muted)" }}
                >
                  Remove
                </button>
              </div>
            </div>
            {a.role ? (
              <p className="text-sm mt-2" style={{ color: "var(--text-secondary)" }}>
                {a.role}
              </p>
            ) : null}
            <input
              defaultValue={a.name}
              aria-label={`Rename ${a.name}`}
              data-testid={`assistant-rename-${a.slug}`}
              className="mt-3 w-full px-3 py-1.5 text-sm rounded-sm"
              style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
              onBlur={(e) => {
                const next = e.target.value.trim();
                if (next && next !== a.name) patch(a.assistant_id, { name: next });
              }}
            />
          </div>
        ))}
      </div>

      <div className="space-y-2" data-testid="assistants-create">
        <input
          value={draft.name}
          onChange={(e) => setDraft({ ...draft, name: e.target.value })}
          placeholder="Name — e.g. Research, Letters"
          data-testid="assistant-new-name"
          className="w-full px-3 py-2 text-sm rounded-sm"
          style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
        />
        <textarea
          value={draft.role}
          onChange={(e) => setDraft({ ...draft, role: e.target.value })}
          placeholder="What this specialist does. Never first-person as you."
          rows={2}
          data-testid="assistant-new-role"
          className="w-full px-3 py-2 text-sm rounded-sm"
          style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
        />
        <div className="flex flex-wrap gap-1.5" data-testid="assistant-new-tools">
          {tools.map((t) => {
            const on = draft.tools_allowlist.includes(t.id);
            return (
              <button
                key={t.id}
                type="button"
                onClick={() => toggleTool(t.id)}
                className="px-2 py-1 text-[10px] uppercase tracking-wide rounded-sm"
                style={{
                  border: "1px solid var(--border-default)",
                  background: on ? "var(--accent-muted)" : "transparent",
                  color: on ? "var(--accent)" : "var(--text-muted)",
                }}
              >
                {t.label}
              </button>
            );
          })}
        </div>
        <button
          type="button"
          onClick={create}
          disabled={!draft.name.trim()}
          data-testid="assistant-create"
          className="px-4 py-2 text-sm rounded-sm disabled:opacity-50"
          style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
        >
          Add assistant
        </button>
      </div>
    </section>
  );
}
