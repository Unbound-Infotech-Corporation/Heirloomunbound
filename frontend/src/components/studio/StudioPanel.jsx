import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

/**
 * Premiere / Audition-style collapsible inspector section.
 */
export default function StudioPanel({
  title,
  children,
  defaultOpen = true,
  testId,
  actions,
  className = "",
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <section
      className={`studio-panel ${open ? "is-open" : "is-collapsed"} ${className}`}
      data-testid={testId}
    >
      <header className="studio-panel-header">
        <button
          type="button"
          className="studio-panel-toggle"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
        >
          {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          <span>{title}</span>
        </button>
        {actions ? <div className="studio-panel-actions">{actions}</div> : null}
      </header>
      {open ? <div className="studio-panel-body">{children}</div> : null}
    </section>
  );
}
