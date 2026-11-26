import { useEffect, useState } from "react";
import { Plus, X } from "lucide-react";
import { cleanNames } from "../../lib/cardSharing";

const btn = { border: "1px solid var(--border-default)", color: "var(--text-primary)" };
const primary = { background: "var(--accent)", color: "var(--text-inverse)" };

// "Sam calls June Grandma." Names only: they help the Twin understand a question and are never
// treated as something that happened.
export default function FamilyNamesFields({ heirs, onSave }) {
  const [rows, setRows] = useState({});
  const [saved, setSaved] = useState("");
  useEffect(() => {
    setRows(Object.fromEntries(heirs.map((h) => [h.heir_id, (h.names || []).map((n) => ({ ...n }))])));
  }, [heirs]);

  if (!heirs.length) return null;
  const edit = (id, i, key, value) =>
    setRows({ ...rows, [id]: rows[id].map((r, j) => (j === i ? { ...r, [key]: value } : r)) });

  return (
    <section className="mt-10" data-testid="family-names">
      <div className="overline mb-3">family names</div>
      <h2 className="font-serif text-2xl mb-2">What each heir calls people.</h2>
      <p className="text-sm mb-4" style={{ color: "var(--text-secondary)" }}>
        If Sam calls June “Grandma”, add it here so the Twin knows who Sam means. These are names only; they are never used as memories.
      </p>
      <div className="grid gap-3">
        {heirs.map((h) => (
          <div key={h.heir_id} className="surface p-4" data-testid={`names-${h.heir_id}`}>
            <div className="text-base mb-2">{h.name}</div>
            {(rows[h.heir_id] || []).map((r, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2 mb-2" data-testid={`names-row-${h.heir_id}-${i}`}>
                <span className="text-sm" style={{ color: "var(--text-muted)" }}>{h.name} calls</span>
                <input className="p-2 min-h-[44px] flex-1 min-w-[7rem]" placeholder="June" aria-label="Person" value={r.person}
                  onChange={(e) => edit(h.heir_id, i, "person", e.target.value)} />
                <span className="text-sm" style={{ color: "var(--text-muted)" }}>“</span>
                <input className="p-2 min-h-[44px] flex-1 min-w-[7rem]" placeholder="Grandma" aria-label="Called" value={r.called}
                  onChange={(e) => edit(h.heir_id, i, "called", e.target.value)} />
                <button type="button" className="p-2 min-h-[44px]" aria-label="Remove name"
                  onClick={() => setRows({ ...rows, [h.heir_id]: rows[h.heir_id].filter((_, j) => j !== i) })}>
                  <X className="h-4 w-4" style={{ color: "var(--text-muted)" }} />
                </button>
              </div>
            ))}
            <div className="flex flex-wrap gap-2">
              <button type="button" className="px-3 py-2 min-h-[44px] text-sm rounded-sm inline-flex items-center gap-1" style={btn}
                onClick={() => setRows({ ...rows, [h.heir_id]: [...(rows[h.heir_id] || []), { person: "", called: "" }] })}
                data-testid={`names-add-${h.heir_id}`}>
                <Plus className="h-3.5 w-3.5" /> Add a name
              </button>
              <button type="button" className="px-4 py-2 min-h-[44px] text-sm rounded-sm" style={primary}
                onClick={async () => { await onSave(h.heir_id, cleanNames(rows[h.heir_id])); setSaved(h.heir_id); }}
                data-testid={`names-save-${h.heir_id}`}>
                Save names
              </button>
              {saved === h.heir_id ? <span className="text-sm self-center" style={{ color: "var(--accent)" }}>Saved</span> : null}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
