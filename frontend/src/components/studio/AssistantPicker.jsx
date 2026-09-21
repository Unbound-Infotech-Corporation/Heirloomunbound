import { cloneIdOf, speakerOptions } from "../../lib/assistants";

export default function AssistantPicker({
  clones = [],
  assistants,
  selectedId = null,
  onSelect,
  disabled = false,
  testid = "clone-picker",
}) {
  const options = speakerOptions(clones.length ? clones : assistants);
  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid={testid}>
      {options.map((opt) => {
        const id = cloneIdOf(opt);
        const active = (selectedId || null) === id;
        return (
          <button
            key={id || "twin"}
            type="button"
            disabled={disabled}
            onClick={() => onSelect?.(id)}
            data-testid={`clone-chip-${opt.slug || id || "twin"}`}
            title={opt.role || opt.name}
            className="px-2.5 py-1 text-[10px] tracking-wide uppercase rounded-sm disabled:opacity-50"
            style={{
              background: active ? "var(--accent)" : "transparent",
              color: active ? "var(--text-inverse)" : "var(--text-muted)",
              border: active ? "1px solid var(--accent)" : "1px solid var(--border-default)",
            }}
          >
            {opt.name}
          </button>
        );
      })}
    </div>
  );
}
