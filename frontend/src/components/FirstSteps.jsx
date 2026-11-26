import { Link } from "react-router-dom";
import { ArrowRight, Check } from "lucide-react";
import { firstSteps } from "../lib/greeting";

/** A brand-new archive gets four gentle first steps instead of a row of zeros. */
export default function FirstSteps({ stats, testId = "first-steps" }) {
  const steps = firstSteps(stats);
  const done = steps.filter((s) => s.done).length;
  const next = steps.find((s) => !s.done);
  return (
    <section className="surface grain-overlay p-6 sm:p-8 mb-12 relative overflow-hidden" data-testid={testId}>
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -top-24 -right-24 h-64 w-64 rounded-full"
        style={{ background: "radial-gradient(circle, rgba(212,163,115,0.18) 0%, rgba(212,163,115,0) 70%)" }}
      />
      <div className="flex flex-wrap items-end justify-between gap-4 mb-6">
        <div>
          <div className="overline mb-2">first steps</div>
          <h2 className="font-serif text-2xl sm:text-3xl" style={{ color: "var(--text-primary)" }}>
            Your archive is ready for its first story.
          </h2>
        </div>
        <div className="flex items-center gap-3" aria-label={`${done} of ${steps.length} done`}>
          <div className="flex gap-1.5">
            {steps.map((s) => (
              <span
                key={s.key}
                className="h-1.5 w-8 rounded-full"
                style={{ background: s.done ? "var(--accent)" : "var(--border-default)" }}
              />
            ))}
          </div>
          <span className="font-mono text-xs" style={{ color: "var(--text-muted)" }} data-testid={`${testId}-count`}>
            {done} of {steps.length}
          </span>
        </div>
      </div>
      <ol className="grid sm:grid-cols-2 gap-3">
        {steps.map((s, i) => {
          const isNext = next && next.key === s.key;
          return (
            <li key={s.key}>
              <Link
                to={s.to}
                data-testid={`${testId}-${s.key}`}
                className="group flex items-start gap-4 p-4 rounded-sm h-full transition-colors"
                style={{
                  border: `1px solid ${isNext ? "var(--accent)" : "var(--border-default)"}`,
                  background: isNext ? "var(--accent-muted)" : "transparent",
                }}
              >
                <span
                  className="shrink-0 h-7 w-7 rounded-full flex items-center justify-center font-mono text-xs"
                  style={{
                    background: s.done ? "var(--accent)" : "transparent",
                    border: `1px solid ${s.done ? "var(--accent)" : "var(--border-default)"}`,
                    color: s.done ? "var(--text-inverse)" : "var(--text-secondary)",
                  }}
                >
                  {s.done ? <Check className="h-3.5 w-3.5" /> : i + 1}
                </span>
                <span className="flex-1 min-w-0">
                  <span
                    className="block font-serif text-lg leading-snug"
                    style={{ color: s.done ? "var(--text-muted)" : "var(--text-primary)", textDecoration: s.done ? "line-through" : "none" }}
                  >
                    {s.label}
                  </span>
                  <span className="block text-sm mt-0.5" style={{ color: "var(--text-secondary)" }}>
                    {s.desc}
                  </span>
                </span>
                <ArrowRight
                  className="h-4 w-4 mt-1 shrink-0 transition-transform group-hover:translate-x-1"
                  style={{ color: isNext ? "var(--accent)" : "var(--text-muted)" }}
                />
              </Link>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
