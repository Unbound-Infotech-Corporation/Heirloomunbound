import { Brain, X } from "lucide-react";
import { formatFactProvenance, MEMORY_COPY } from "../../lib/memoryStudio";

export default function HeldFactsList({ facts, onRemove, loading = false, error = "" }) {
  return (
    <section className="mb-10" data-testid="memory-facts-section">
      <div className="overline mb-4 flex items-center gap-2">
        <Brain className="h-3.5 w-3.5" /> what i hold onto
      </div>
      <h2 className="font-serif text-2xl mb-2">My long-term memory.</h2>
      <p className="text-sm mb-5" style={{ color: "var(--text-secondary)" }}>
        Stable facts the Twin keeps in mind. Each one shows where it came from. Remove a wrong one — the Twin stops using it immediately. Nothing here is invented.
      </p>
      {loading ? (
        <p className="text-sm" style={{ color: "var(--text-muted)" }} data-testid="memory-facts-loading">
          Reading what is held…
        </p>
      ) : error ? (
        <div className="surface p-6" data-testid="memory-facts-error">
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>{error}</p>
        </div>
      ) : facts.length === 0 ? (
        <div className="surface p-8" data-testid="memory-facts-empty">
          <p className="font-serif text-xl mb-2" style={{ color: "var(--text-secondary)" }}>
            Quiet so far.
          </p>
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
            {MEMORY_COPY.emptyFacts}
          </p>
        </div>
      ) : (
        <div className="space-y-2" data-testid="memory-facts-list">
          {facts.map((f) => {
            const prov = formatFactProvenance(f);
            return (
              <div
                key={f.fact_id}
                className="surface p-4 flex justify-between items-start gap-3"
                data-testid={`fact-${f.fact_id}`}
              >
                <div className="flex-1">
                  <div className="overline mb-1">{prov.kind}</div>
                  <div className="text-base" style={{ color: "var(--text-primary)" }}>
                    {f.fact}
                  </div>
                  <div className="font-mono text-xs mt-2" style={{ color: "var(--text-muted)" }} data-testid={`fact-provenance-${f.fact_id}`}>
                    {prov.source}
                    {prov.when ? ` · ${prov.when}` : ""}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => onRemove(f.fact_id)}
                  data-testid={`remove-fact-${f.fact_id}`}
                  title="Remove this fact"
                  className="p-2"
                >
                  <X className="h-4 w-4" style={{ color: "var(--text-muted)" }} />
                </button>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
