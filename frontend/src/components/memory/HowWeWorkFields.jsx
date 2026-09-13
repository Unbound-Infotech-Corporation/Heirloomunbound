import { Handshake } from "lucide-react";
import { MEMORY_COPY, PAIRING_STYLES, PAIRING_TOGGLES } from "../../lib/memoryStudio";

export default function HowWeWorkFields({ pairing, onChange, id = "how-we-work" }) {
  return (
    <section className="surface p-7 mb-6" data-testid="how-we-work-section" id={id}>
      <div className="overline mb-2 flex items-center gap-2">
        <Handshake className="h-3.5 w-3.5" /> how we work
      </div>
      <h2 className="font-serif text-2xl mb-2">Pairing style for Assist and your Twin</h2>
      <p className="text-sm mb-5" style={{ color: "var(--text-secondary)" }}>
        {MEMORY_COPY.ownerOnly}
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mb-5">
        {PAIRING_STYLES.map(([styleId, label, hint]) => (
          <button
            key={styleId}
            type="button"
            onClick={() => onChange({ ...pairing, pairing_style: styleId })}
            data-testid={`pairing-style-${styleId}`}
            className="px-4 py-3 text-sm rounded-sm text-left transition-colors"
            style={{
              background: pairing.pairing_style === styleId ? "var(--accent)" : "var(--bg-base)",
              color: pairing.pairing_style === styleId ? "var(--text-inverse)" : "var(--text-primary)",
              border: pairing.pairing_style === styleId ? "1px solid var(--accent)" : "1px solid var(--border-default)",
            }}
          >
            <div>{label}</div>
            <div className="text-xs mt-1" style={{ opacity: 0.8 }}>{hint}</div>
          </button>
        ))}
      </div>
      <div className="space-y-3">
        {PAIRING_TOGGLES.map(([key, label, hint]) => (
          <label
            key={key}
            className="flex items-center justify-between px-4 py-3 rounded-sm cursor-pointer"
            style={{ border: "1px solid var(--border-default)" }}
            data-testid={`pairing-toggle-${key}`}
          >
            <span>
              <span className="text-sm block" style={{ color: "var(--text-primary)" }}>{label}</span>
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>{hint}</span>
            </span>
            <input
              type="checkbox"
              checked={!!pairing[key]}
              onChange={() => onChange({ ...pairing, [key]: !pairing[key] })}
              className="h-4 w-4"
            />
          </label>
        ))}
      </div>
    </section>
  );
}
