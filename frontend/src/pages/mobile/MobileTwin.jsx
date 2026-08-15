import { useEffect, useRef, useState } from "react";
import { Loader2, Sparkles } from "lucide-react";
import { api, streamSSE } from "@/lib/api";
import FunctionModelPicker, { modelOverride } from "@/components/FunctionModelPicker";

/**
 * Phone twin chat — same archive as the home computer, same model picker.
 * Kept lean: no avatar video, no desktop-only ability chips.
 */
export default function MobileTwin() {
  const [conv, setConv] = useState(null);
  const [streaming, setStreaming] = useState("");
  const [pending, setPending] = useState(false);
  const [input, setInput] = useState("");
  const [modelChoice, setModelChoice] = useState(null);
  const feedRef = useRef(null);

  useEffect(() => {
    let savedId = null;
    try { savedId = localStorage.getItem("twin_conv_id"); } catch (_) { /* noop */ }
    api.post("/twin/start", savedId ? { conversation_id: savedId } : {}).then(({ data }) => {
      setConv(data);
      try { localStorage.setItem("twin_conv_id", data.conversation_id); } catch (_) { /* noop */ }
    }).catch(() => {});
  }, []);

  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: "smooth" });
  }, [conv, streaming]);

  const send = async (text) => {
    if (!text.trim() || !conv || pending) return;
    const myMsg = { role: "user", content: text, ts: new Date().toISOString() };
    setConv((c) => ({ ...c, messages: [...(c.messages || []), myMsg] }));
    setInput("");
    setPending(true);
    setStreaming("");

    let full = "";
    await streamSSE(
      "/twin/message",
      { conversation_id: conv.conversation_id, message: text, ...modelOverride(modelChoice) },
      (chunk) => {
        full += chunk;
        setStreaming(full);
      },
      () => {
        setConv((c) => ({
          ...c,
          messages: [
            ...(c.messages || []),
            { role: "assistant", content: full, ts: new Date().toISOString() },
          ],
        }));
        setStreaming("");
        setPending(false);
      },
      () => {
        setStreaming("");
        setPending(false);
      },
    );
  };

  const messages = conv?.messages || [];

  return (
    <div className="max-w-md mx-auto flex flex-col h-full" data-testid="mobile-twin">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <div className="overline mb-1">your twin</div>
          <h1 className="font-serif text-3xl" style={{ color: "var(--text-primary)" }}>Talk.</h1>
        </div>
        <FunctionModelPicker functionId="chat" compact onChange={setModelChoice} />
      </div>

      <div ref={feedRef} className="flex-1 space-y-5 overflow-y-auto mb-4 max-h-[52vh]" data-testid="mobile-twin-feed">
        {messages.length === 0 && !streaming && (
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
            Same archive as your home computer. Ask anything. The lifelike video twin runs on that PC — open Avatar Studio there, not on the phone.
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} data-testid={`mobile-twin-msg-${i}`}>
            <div className="overline mb-1">{m.role === "assistant" ? "twin" : "you"}</div>
            <p className="text-sm leading-relaxed" style={{ color: m.role === "assistant" ? "var(--text-primary)" : "var(--text-secondary)" }}>
              {m.content}
            </p>
          </div>
        ))}
        {streaming && (
          <div>
            <div className="overline mb-1">twin</div>
            <p className="text-sm leading-relaxed" style={{ color: "var(--text-primary)" }}>
              {streaming}
              <span className="inline-block w-1.5 h-4 ml-1 align-middle animate-pulse" style={{ background: "var(--accent)" }} />
            </p>
          </div>
        )}
      </div>

      <form
        onSubmit={(e) => { e.preventDefault(); send(input); }}
        className="flex items-center gap-2"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={pending || !conv}
          placeholder="Say something…"
          data-testid="mobile-twin-input"
          className="flex-1 px-3 py-2 text-sm rounded-sm"
          style={{
            background: "var(--surface-elev)",
            border: "1px solid var(--border-default)",
            color: "var(--text-primary)",
          }}
        />
        <button
          type="submit"
          disabled={pending || !input.trim()}
          data-testid="mobile-twin-send"
          className="px-3 py-2 rounded-sm"
          style={{ background: "var(--accent)", color: "var(--surface)" }}
        >
          {pending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
        </button>
      </form>
    </div>
  );
}
