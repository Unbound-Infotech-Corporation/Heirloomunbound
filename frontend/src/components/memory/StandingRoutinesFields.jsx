import { Sunrise } from "lucide-react";
import { ROUTINE_COPY, ROUTINE_KINDS } from "../../lib/standingRoutines";

export default function StandingRoutinesFields({ routines, onChange, id = "standing-routines" }) {
  return (
    <section className="surface p-7 mb-6" data-testid="standing-routines-section" id={id}>
      <div className="overline mb-2 flex items-center gap-2">
        <Sunrise className="h-3.5 w-3.5" /> {ROUTINE_COPY.heading.toLowerCase()}
      </div>
      <h2 className="font-serif text-2xl mb-2">Quiet check-ins in your voice</h2>
      <p className="text-sm mb-2" style={{ color: "var(--text-secondary)" }}>
        {ROUTINE_COPY.blurb}
      </p>
      <p className="text-xs mb-5" style={{ color: "var(--text-muted)" }}>
        {ROUTINE_COPY.quiet} {ROUTINE_COPY.ownerOnly}
      </p>
      <div className="space-y-3">
        {ROUTINE_KINDS.map(([key, label, hint]) => (
          <label
            key={key}
            className="flex items-center justify-between px-4 py-3 rounded-sm cursor-pointer"
            style={{ border: "1px solid var(--border-default)" }}
            data-testid={`routine-toggle-${key}`}
          >
            <span>
              <span className="text-sm block" style={{ color: "var(--text-primary)" }}>{label}</span>
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>{hint}</span>
            </span>
            <input
              type="checkbox"
              checked={!!routines[key]}
              onChange={() => onChange({ ...routines, [key]: !routines[key] })}
              data-testid={`routine-checkbox-${key}`}
              className="h-4 w-4"
            />
          </label>
        ))}
      </div>
    </section>
  );
}
