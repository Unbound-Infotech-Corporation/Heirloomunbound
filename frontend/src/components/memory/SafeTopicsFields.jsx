import { ShieldOff, X } from "lucide-react";
import { MEMORY_COPY } from "../../lib/memoryStudio";

export default function SafeTopicsFields({
  topics,
  newTopic,
  onNewTopicChange,
  onAdd,
  onRemove,
  id = "safe-topics",
}) {
  return (
    <section className="surface p-7 mb-6" data-testid="safe-topics-section" id={id}>
      <div className="overline mb-2 flex items-center gap-2">
        <ShieldOff className="h-3.5 w-3.5" /> safe-topic fence
      </div>
      <h2 className="font-serif text-2xl mb-2">What your twin won&apos;t talk about</h2>
      <p className="text-sm mb-5" style={{ color: "var(--text-secondary)" }}>
        Add topics your twin should politely decline — politics, religion, business secrets, anything personal. Applied to all chats, including the heir portal.
      </p>
      <div className="flex flex-wrap gap-2 mb-4" data-testid="safe-topics-list">
        {topics.length === 0 && (
          <span className="text-sm italic" style={{ color: "var(--text-muted)" }}>
            {MEMORY_COPY.fenceEmpty}
          </span>
        )}
        {topics.map((t) => (
          <span
            key={t}
            className="inline-flex items-center gap-2 px-3 py-1.5 text-sm rounded-sm"
            style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
            data-testid={`safe-topic-${t}`}
          >
            {t}
            <button type="button" onClick={() => onRemove(t)} className="opacity-60 hover:opacity-100" data-testid={`safe-topic-remove-${t}`}>
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
      </div>
      <div className="flex gap-2">
        <input
          value={newTopic}
          onChange={(e) => onNewTopicChange(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && onAdd()}
          placeholder="Add a topic — e.g. 'politics', 'my divorce', 'work salaries'"
          data-testid="safe-topic-input"
          className="flex-1 px-3 py-2 text-sm rounded-sm"
          style={{ background: "var(--bg-base)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
        />
        <button
          type="button"
          onClick={onAdd}
          disabled={!newTopic.trim()}
          data-testid="safe-topic-add"
          className="px-4 py-2 text-sm rounded-sm disabled:opacity-50"
          style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
        >
          Add
        </button>
      </div>
    </section>
  );
}
