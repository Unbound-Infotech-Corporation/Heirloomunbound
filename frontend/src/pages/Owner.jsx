import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Loader2 } from "lucide-react";
import AssistReceipt from "../components/studio/AssistReceipt";
import AssistantPicker from "../components/studio/AssistantPicker";
import { shouldShowReceipt, splitOwnerLegs } from "../lib/assistReceipt";
import { speakerLabel } from "../lib/assistants";
import { api } from "../lib/api";

const CHIP = {
  Do: { label: "Do", hint: "Assist on this PC" },
  "As you": { label: "As you", hint: "Twin from the vault" },
  "Do + As you": { label: "Do + As you", hint: "Both legs this turn" },
};

function RailChip({ chip, testid }) {
  const meta = CHIP[chip] || { label: chip || "As you", hint: "" };
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2 py-0.5 text-[10px] tracking-wide uppercase rounded-sm"
      data-testid={testid}
      title={meta.hint}
      style={{
        border: "1px solid var(--border-default)",
        color: "var(--text-muted)",
        background: "transparent",
      }}
    >
      {meta.label}
    </span>
  );
}

export default function Owner() {
  const [conv, setConv] = useState(null);
  const [pending, setPending] = useState(false);
  const [input, setInput] = useState("");
  const [lastChip, setLastChip] = useState("");
  const [assistants, setAssistants] = useState([]);
  const [selectedAssistant, setSelectedAssistant] = useState(null);
  const feedRef = useRef(null);

  useEffect(() => {
    api.get("/owner/conversation").then(({ data }) => setConv(data)).catch(() => {
      setConv({ conversation_id: "", messages: [] });
    });
    api.get("/clones").then(({ data }) => setAssistants(data.clones || data.assistants || [])).catch(() => {});
  }, []);

  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: "smooth" });
  }, [conv, pending]);

  const send = async (text) => {
    if (!text.trim() || pending) return;
    const myMsg = { role: "user", content: text, ts: new Date().toISOString() };
    setConv((c) => ({ ...(c || {}), messages: [...(c?.messages || []), myMsg] }));
    setInput("");
    setPending(true);
    try {
      const { data } = await api.post("/owner/chat", { text, clone_id: selectedAssistant || undefined });
      setLastChip(data.rail_chip || "");
      setConv((c) => ({
        ...(c || {}),
        conversation_id: data.conversation_id || c?.conversation_id,
        messages: [
          ...(c?.messages || []),
          {
            role: "assistant",
            content: data.reply,
            ts: data.ts || new Date().toISOString(),
            rail: data.rail,
            rail_chip: data.rail_chip,
            rail_legs: data.rail_legs,
            tool_trace: data.tool_trace,
            action: data.action,
            receipt: data.receipt,
            twin_reply: data.twin_reply,
            assist_reply: data.assist_reply,
            specialist_id: data.specialist_id,
            specialist_name: data.specialist_name,
          },
        ],
      }));
    } catch (err) {
      setConv((c) => ({
        ...(c || {}),
        messages: [
          ...(c?.messages || []),
          {
            role: "assistant",
            content: err.response?.data?.detail || "I couldn't take that turn just now.",
            ts: new Date().toISOString(),
            rail_chip: "",
          },
        ],
      }));
    } finally {
      setPending(false);
    }
  };

  const messages = conv?.messages || [];

  return (
    <div className="px-4 sm:px-8 lg:px-16 py-12 max-w-4xl" data-testid="owner-root">
      <header className="mb-10 flex justify-between items-end gap-6">
        <div>
          <div className="overline mb-3">sit</div>
          <h1 className="font-serif text-4xl lg:text-5xl font-light tracking-tight">
            One teammate.
          </h1>
          <p className="mt-3 text-base max-w-xl" style={{ color: "var(--text-secondary)" }}>
            Ask or do — we route it. Quiet chips, no mode picker. Twin stays the gift voice;
            Assist still confirms the destructive work in the document.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {lastChip ? <RailChip chip={lastChip} testid="owner-last-chip" /> : null}
        </div>
      </header>

      <div className="flex flex-wrap gap-3 mb-8 text-xs" style={{ color: "var(--text-muted)" }}>
        <Link to="/twin" className="hover:text-[var(--accent)]" data-testid="owner-link-twin">
          Twin sitting →
        </Link>
        <Link to="/memory" className="hover:text-[var(--accent)]" data-testid="owner-link-memory">
          Memory Studio →
        </Link>
        <Link to="/companion" className="hover:text-[var(--accent)]" data-testid="owner-link-companion">
          Work on this PC →
        </Link>
        <Link to="/rooms" className="hover:text-[var(--accent)]" data-testid="owner-link-rooms">
          Rooms →
        </Link>
        <Link to="/settings" className="hover:text-[var(--accent)]" data-testid="owner-link-clones">
          Clones →
        </Link>
      </div>

      <div ref={feedRef} className="space-y-10 mb-10 max-h-[58vh] overflow-y-auto pr-2" data-testid="owner-feed">
        {messages.length === 0 && !pending && (
          <div className="surface p-8" data-testid="owner-empty-prompt">
            <div className="overline mb-3">try saying</div>
            <ul className="space-y-3">
              {[
                "What did you love most about being a father?",
                "Open the browser and go to YouTube",
                "Remember the dentist Thursday and open my calendar",
              ].map((q) => (
                <li key={q}>
                  <button
                    type="button"
                    onClick={() => send(q)}
                    className="font-serif text-lg text-left hover:text-[var(--accent)] transition-colors"
                    data-testid="owner-prompt"
                  >
                    {q}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={`${m.ts || i}-${i}`} data-testid={`owner-msg-${i}`}>
            {m.role === "assistant" ? (
              <div className="border-l-2 pl-6" style={{ borderColor: "var(--accent)" }}>
                <div className="overline mb-2 flex items-center gap-3">
                  <span>{speakerLabel(m, assistants) === "you (the twin)" ? "teammate" : speakerLabel(m, assistants)}</span>
                  {m.rail_chip ? <RailChip chip={m.rail_chip} testid={`owner-chip-${i}`} /> : null}
                </div>
                <OwnerAssistantBody message={m} index={i} />
              </div>
            ) : (
              <div>
                <div className="overline mb-2">you</div>
                <p className="text-base leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                  {m.content}
                </p>
              </div>
            )}
          </div>
        ))}
        {pending && (
          <div className="border-l-2 pl-6" style={{ borderColor: "var(--accent)" }}>
            <div className="overline mb-2">teammate</div>
            <p className="inline-flex items-center gap-2 text-sm" style={{ color: "var(--text-muted)" }}>
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> routing…
            </p>
          </div>
        )}
      </div>

      <div className="surface p-4 sticky bottom-6">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              send(input);
            }
          }}
          rows={3}
          placeholder="Ask or do. (⌘/Ctrl + Enter to send)"
          data-testid="owner-input"
          className="w-full bg-transparent border-none outline-none resize-none text-base leading-relaxed"
          style={{ color: "var(--text-primary)" }}
        />
        <div className="flex flex-wrap justify-between items-center gap-3 mt-2 pt-2 border-t" style={{ borderColor: "var(--border-default)" }}>
          <AssistantPicker
            assistants={assistants}
            selectedId={selectedAssistant}
            onSelect={setSelectedAssistant}
            disabled={pending}
            testid="owner-clone-picker"
          />
          <button
            type="button"
            onClick={() => send(input)}
            disabled={pending || !input.trim()}
            data-testid="owner-send"
            className="inline-flex items-center gap-2 px-5 py-2 text-sm font-medium rounded-sm disabled:opacity-50"
            style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
          >
            {pending ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
            Send
          </button>
        </div>
      </div>
    </div>
  );
}

function OwnerAssistantBody({ message, index }) {
  const rail = String(message.rail || "").toLowerCase();
  const { twinReply, assistReply } = splitOwnerLegs(message);
  const showReceipt = shouldShowReceipt(message);
  const both = rail === "both" || (twinReply && (assistReply || showReceipt));

  if (both) {
    return (
      <div className="space-y-6" data-testid={`owner-both-${index}`}>
        {twinReply ? (
          <div data-testid={`owner-twin-leg-${index}`}>
            <div className="overline mb-2">as you</div>
            <p className="font-serif text-xl lg:text-2xl leading-snug" style={{ color: "var(--text-primary)" }}>
              {twinReply}
            </p>
          </div>
        ) : null}
        <div data-testid={`owner-assist-leg-${index}`}>
          <div className="overline mb-2">do</div>
          {assistReply ? (
            <p className="font-serif text-xl lg:text-2xl leading-snug" style={{ color: "var(--text-primary)" }}>
              {assistReply}
            </p>
          ) : null}
          {showReceipt ? <AssistReceipt receipt={message.receipt} testid={`assist-receipt-${index}`} /> : null}
        </div>
      </div>
    );
  }

  return (
    <>
      <p className="font-serif text-xl lg:text-2xl leading-snug" style={{ color: "var(--text-primary)" }}>
        {message.content}
      </p>
      {showReceipt ? <AssistReceipt receipt={message.receipt} testid={`assist-receipt-${index}`} /> : null}
    </>
  );
}
