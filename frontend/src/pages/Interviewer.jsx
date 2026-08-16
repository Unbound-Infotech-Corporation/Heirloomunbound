import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Bookmark, Loader2, Sparkles, ArrowRight } from "lucide-react";
import { api, streamSSE } from "../lib/api";
import FunctionModelPicker, { modelOverride } from "@/components/FunctionModelPicker";

export default function Interviewer() {
  const [searchParams] = useSearchParams();
  const [conversation, setConversation] = useState(null);
  const [seedQuestions, setSeedQuestions] = useState([]);
  const [pending, setPending] = useState(false);
  const [streaming, setStreaming] = useState("");
  const [input, setInput] = useState("");
  const [savedIds, setSavedIds] = useState(new Set());
  const [modelChoice, setModelChoice] = useState(null);
  const scrollRef = useRef(null);

  useEffect(() => {
    api.get("/interviewer/seed-questions").then(({ data }) => setSeedQuestions(data.questions));
    api.post("/interviewer/start", {}).then(({ data }) => {
      // If empty conversation and a topic is passed, seed the first AI message
      const topic = searchParams.get("topic");
      if (topic && (data.messages || []).length === 0) {
        setConversation({
          ...data,
          messages: [{ role: "assistant", content: topic, ts: new Date().toISOString(), _seed: true }],
        });
      } else {
        setConversation(data);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [conversation, streaming]);

  const send = async (text) => {
    if (!text.trim() || !conversation || pending) return;
    const myMsg = { role: "user", content: text, ts: new Date().toISOString() };
    setConversation((c) => ({ ...c, messages: [...(c.messages || []), myMsg] }));
    setInput("");
    setPending(true);
    setStreaming("");

    let fullText = "";
    await streamSSE(
      "/interviewer/message",
      { conversation_id: conversation.conversation_id, message: text, ...modelOverride(modelChoice) },
      (chunk) => {
        fullText += chunk;
        setStreaming(fullText);
      },
      () => {
        setConversation((c) => ({
          ...c,
          messages: [
            ...c.messages,
            { role: "assistant", content: fullText, ts: new Date().toISOString() },
          ],
        }));
        setStreaming("");
        setPending(false);
      },
      (err) => {
        console.error(err);
        setStreaming("");
        setPending(false);
      },
    );
  };

  const saveAsEntry = async (msg, idx) => {
    // pair: previous assistant question + this user answer
    const messages = conversation.messages;
    const prev = messages[idx - 1];
    const payload = {
      question: prev?.role === "assistant" ? prev.content : "",
      answer: msg.content,
      title: msg.content.split(/[.!?]/)[0].slice(0, 80),
      type: "memory",
    };
    const { data } = await api.post("/interviewer/save-turn", payload);
    setSavedIds((s) => new Set(s).add(idx));
    return data;
  };

  const messages = conversation?.messages || [];

  return (
    <div className="px-4 sm:px-8 lg:px-16 py-12 max-w-4xl" data-testid="interviewer-root">
      <header className="mb-10">
        <div className="overline mb-3 flex items-center justify-between gap-3 flex-wrap">
          <span>the interviewer</span>
          <FunctionModelPicker functionId="interview" compact onChange={setModelChoice} />
        </div>
        <h1 className="font-serif text-4xl lg:text-5xl font-light tracking-tight">A patient question, then another.</h1>
        <p className="mt-3 text-base max-w-xl" style={{ color: "var(--text-secondary)" }}>
          Answer in your own time. Each meaningful turn can be saved into your archive.
        </p>
      </header>

      {messages.length === 0 && (
        <div className="surface p-8 mb-10">
          <div className="overline mb-4">begin with one of these</div>
          <div className="space-y-3">
            {seedQuestions.slice(0, 5).map((q, i) => (
              <button
                key={i}
                onClick={() => send(q)}
                data-testid={`seed-question-${i}`}
                className="block text-left w-full font-serif text-lg leading-snug py-3 hover:text-[var(--accent)] transition-colors border-b"
                style={{ borderColor: "var(--border-default)", color: "var(--text-primary)" }}
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}

      <div ref={scrollRef} className="space-y-10 mb-10 max-h-[55vh] overflow-y-auto pr-2" data-testid="interviewer-feed">
        {messages.map((m, i) => (
          <div key={i} data-testid={`interview-msg-${i}`}>
            {m.role === "assistant" ? (
              <div>
                <div className="overline mb-2">{m._seed ? "today's topic" : "asks"}</div>
                <p
                  className="font-serif text-2xl lg:text-3xl leading-snug"
                  style={{ color: "var(--text-primary)" }}
                >
                  {m.content}
                </p>
              </div>
            ) : (
              <div className="border-l-2 pl-6" style={{ borderColor: "var(--accent)" }}>
                <div className="overline mb-2">you say</div>
                <p className="text-base leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                  {m.content}
                </p>
                <button
                  onClick={() => saveAsEntry(m, i)}
                  disabled={savedIds.has(i)}
                  data-testid={`save-entry-${i}`}
                  className="mt-3 inline-flex items-center gap-2 text-xs hover:text-[var(--accent)] disabled:opacity-60"
                  style={{ color: "var(--text-muted)" }}
                >
                  <Bookmark className="h-3.5 w-3.5" />
                  {savedIds.has(i) ? "Saved to archive" : "Save this answer to the archive"}
                </button>
              </div>
            )}
          </div>
        ))}
        {streaming && (
          <div>
            <div className="overline mb-2">asks</div>
            <p className="font-serif text-2xl lg:text-3xl leading-snug" style={{ color: "var(--text-primary)" }}>
              {streaming}
              <span className="inline-block w-2 h-6 ml-1 align-middle animate-pulse" style={{ background: "var(--accent)" }} />
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
          placeholder="Answer here. Take your time. (⌘/Ctrl + Enter to send)"
          data-testid="interviewer-input"
          className="w-full bg-transparent border-none outline-none resize-none text-base leading-relaxed"
          style={{ color: "var(--text-primary)" }}
        />
        <div className="flex justify-between items-center mt-2 pt-2 border-t" style={{ borderColor: "var(--border-default)" }}>
          <div className="overline">
            {pending ? "listening…" : streaming ? "writing…" : "your turn"}
          </div>
          <button
            onClick={() => send(input)}
            disabled={pending || !input.trim()}
            data-testid="interviewer-send"
            className="inline-flex items-center gap-2 px-5 py-2 text-sm font-medium rounded-sm disabled:opacity-50 transition-colors"
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
