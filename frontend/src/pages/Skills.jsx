import { useEffect, useState } from "react";
import { Play, Plus, Trash2 } from "lucide-react";
import { api } from "../lib/api";

const empty = {
  name: "",
  description: "",
  webhook_url: "",
  method: "POST",
  headers: "",
  body_template: "",
  triggers: "",
  enabled: true,
};

export default function Skills() {
  const [skills, setSkills] = useState([]);
  const [showNew, setShowNew] = useState(false);
  const [draft, setDraft] = useState(empty);
  const [invokeResults, setInvokeResults] = useState({});

  const load = () => api.get("/skills").then(({ data }) => setSkills(data));
  useEffect(() => {
    load();
  }, []);

  const submit = async () => {
    if (!draft.name.trim() || !draft.webhook_url.trim()) return;
    let headers = {};
    if (draft.headers) {
      try {
        headers = JSON.parse(draft.headers);
      } catch {
        return alert("Headers must be valid JSON, e.g. {\"Authorization\":\"Bearer …\"}");
      }
    }
    await api.post("/skills", {
      ...draft,
      headers,
      triggers: draft.triggers
        ? draft.triggers.split(/\r?\n|,/).map((s) => s.trim()).filter(Boolean)
        : [],
    });
    setShowNew(false);
    setDraft(empty);
    load();
  };

  const invoke = async (id) => {
    setInvokeResults((r) => ({ ...r, [id]: { loading: true } }));
    const { data } = await api.post(`/skills/${id}/invoke`);
    setInvokeResults((r) => ({ ...r, [id]: data }));
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this skill?")) return;
    await api.delete(`/skills/${id}`);
    load();
  };

  return (
    <div className="px-10 lg:px-16 py-12 max-w-5xl" data-testid="skills-root">
      <header className="mb-10 flex justify-between items-end flex-wrap gap-6">
        <div>
          <div className="overline mb-3">your hands in the world</div>
          <h1 className="font-serif text-4xl lg:text-5xl font-light tracking-tight">
            Skills the twin can perform.
          </h1>
          <p className="mt-3 text-base max-w-2xl" style={{ color: "var(--text-secondary)" }}>
            Each skill is a webhook. Wire it to Home Assistant, IFTTT, a script on your PC, or any URL that does
            something useful — turning on the porch light, sending a text, triggering an OBS scene.
          </p>
        </div>
        <button
          onClick={() => setShowNew((s) => !s)}
          data-testid="new-skill-toggle"
          className="inline-flex items-center gap-2 px-5 py-3 text-sm rounded-sm"
          style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
        >
          <Plus className="h-4 w-4" /> New skill
        </button>
      </header>

      {showNew && (
        <div className="surface p-6 mb-10 space-y-4">
          <input
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            placeholder="Skill name (e.g. Turn on office lights)"
            data-testid="skill-name"
            className="w-full px-3 py-2 text-sm rounded-sm"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
          />
          <input
            value={draft.description}
            onChange={(e) => setDraft({ ...draft, description: e.target.value })}
            placeholder="Short description for the twin to understand when to use this"
            data-testid="skill-desc"
            className="w-full px-3 py-2 text-sm rounded-sm"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
          />
          <div className="flex gap-3">
            <select
              value={draft.method}
              onChange={(e) => setDraft({ ...draft, method: e.target.value })}
              data-testid="skill-method"
              className="px-3 py-2 text-sm rounded-sm"
              style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
            >
              {["GET", "POST", "PUT", "PATCH", "DELETE"].map((m) => (
                <option key={m}>{m}</option>
              ))}
            </select>
            <input
              value={draft.webhook_url}
              onChange={(e) => setDraft({ ...draft, webhook_url: e.target.value })}
              placeholder="https://your-home-assistant.local/api/services/..."
              data-testid="skill-url"
              className="flex-1 px-3 py-2 text-sm rounded-sm font-mono"
              style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
            />
          </div>
          <textarea
            value={draft.headers}
            onChange={(e) => setDraft({ ...draft, headers: e.target.value })}
            placeholder='Headers as JSON, optional. e.g. {"Authorization":"Bearer …"}'
            rows={2}
            data-testid="skill-headers"
            className="w-full px-3 py-2 text-sm rounded-sm font-mono"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
          />
          <textarea
            value={draft.body_template}
            onChange={(e) => setDraft({ ...draft, body_template: e.target.value })}
            placeholder='Body, optional. e.g. {"entity_id":"light.office"}'
            rows={3}
            data-testid="skill-body"
            className="w-full px-3 py-2 text-sm rounded-sm font-mono"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
          />
          <div>
            <label className="overline block mb-2">trigger phrases (auto-invoke)</label>
            <textarea
              value={draft.triggers}
              onChange={(e) => setDraft({ ...draft, triggers: e.target.value })}
              placeholder={'One per line (or comma-separated). When the twin sees any of these in chat,\nit runs this skill automatically without asking. e.g.\nturn on the office lights\noffice lights on'}
              rows={3}
              data-testid="skill-triggers"
              className="w-full px-3 py-2 text-sm rounded-sm"
              style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
            />
            <p className="text-xs mt-2" style={{ color: "var(--text-muted)" }}>
              Match is case-insensitive substring across the user's message. Leave blank to keep this skill manual-only.
            </p>
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
              data-testid="skill-submit"
              className="px-4 py-2 text-sm rounded-sm"
              style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
            >
              Save skill
            </button>
          </div>
        </div>
      )}

      {skills.length === 0 ? (
        <div className="surface p-12 text-center" data-testid="skills-empty">
          <div className="overline mb-3">no skills yet</div>
          <p className="font-serif text-2xl" style={{ color: "var(--text-secondary)" }}>
            Give your twin its first hand in the world.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {skills.map((s) => {
            const r = invokeResults[s.skill_id];
            return (
              <div key={s.skill_id} className="surface p-6" data-testid={`skill-${s.skill_id}`}>
                <div className="flex justify-between items-start mb-3 gap-4">
                  <div className="min-w-0">
                    <div className="overline mb-1">{s.method}</div>
                    <h3 className="font-serif text-2xl mb-1">{s.name}</h3>
                    {s.description && (
                      <p className="text-sm mb-2" style={{ color: "var(--text-secondary)" }}>
                        {s.description}
                      </p>
                    )}
                    <div className="font-mono text-xs truncate" style={{ color: "var(--text-muted)" }}>
                      {s.webhook_url}
                    </div>
                    {(s.triggers || []).length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {s.triggers.slice(0, 6).map((t, i) => (
                          <span
                            key={i}
                            className="text-xs px-2 py-0.5 rounded-sm"
                            style={{ background: "var(--accent-muted)", color: "var(--text-primary)", border: "1px solid var(--accent)" }}
                          >
                            "{t}"
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="flex gap-2 shrink-0">
                    <button
                      onClick={() => invoke(s.skill_id)}
                      data-testid={`invoke-${s.skill_id}`}
                      className="inline-flex items-center gap-2 px-3 py-2 text-xs rounded-sm"
                      style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
                    >
                      <Play className="h-3.5 w-3.5" /> Test
                    </button>
                    <button
                      onClick={() => remove(s.skill_id)}
                      data-testid={`delete-skill-${s.skill_id}`}
                      className="p-2"
                    >
                      <Trash2 className="h-4 w-4" style={{ color: "var(--text-muted)" }} />
                    </button>
                  </div>
                </div>
                {r && !r.loading && (
                  <div
                    className="mt-3 text-xs font-mono p-3 rounded-sm"
                    data-testid={`invoke-result-${s.skill_id}`}
                    style={{
                      background: "var(--bg-base)",
                      border: "1px solid var(--border-default)",
                      color: r.ok ? "var(--accent)" : "var(--danger)",
                    }}
                  >
                    {r.ok ? `✓ ${r.status}` : `✗ ${r.status || ""} ${r.error || ""}`}
                    {r.body && (
                      <div className="mt-1 break-all" style={{ color: "var(--text-secondary)" }}>
                        {r.body.slice(0, 200)}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <div
        className="surface p-6 mt-12 text-sm"
        style={{ borderColor: "var(--border-default)", color: "var(--text-secondary)" }}
      >
        <div className="overline mb-2">a note on local control</div>
        <p className="leading-relaxed">
          To control your home from this cloud app, point each skill at a publicly reachable endpoint — your Home Assistant
          Nabu Casa URL, an ngrok tunnel into your 5090 PC, an IFTTT webhook, or a tiny FastAPI you run locally. A native
          local-companion app is on the roadmap.
        </p>
      </div>
    </div>
  );
}
