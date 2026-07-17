import axios from "axios";
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { motion } from "framer-motion";
import { BookOpen, Loader2, Mail, MessageCircle, Send, Sparkles } from "lucide-react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const PORTAL_BASE = `${BACKEND_URL}/api/heir-portal`;

const tabs = [
  { key: "welcome", label: "Welcome", icon: Sparkles },
  { key: "letters", label: "Letters", icon: Mail },
  { key: "entries", label: "Archive", icon: BookOpen },
  { key: "twin", label: "Talk to them", icon: MessageCircle },
];

export default function HeirPortal() {
  const { token } = useParams();
  const [tab, setTab] = useState("welcome");
  const [summary, setSummary] = useState(null);
  const [letters, setLetters] = useState(null);
  const [entries, setEntries] = useState(null);
  const [chat, setChat] = useState([]);
  const [chatInput, setChatInput] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    axios
      .get(`${PORTAL_BASE}/${token}`)
      .then(({ data }) => setSummary(data))
      .catch((e) =>
        setError(
          e.response?.data?.detail ||
            "This link is invalid or has been revoked."
        )
      )
      .finally(() => setLoading(false));
  }, [token]);

  useEffect(() => {
    if (tab === "letters" && !letters) {
      axios
        .get(`${PORTAL_BASE}/${token}/letters`)
        .then(({ data }) => setLetters(data.letters))
        .catch(() => setLetters([]));
    }
    if (tab === "entries" && !entries) {
      axios
        .get(`${PORTAL_BASE}/${token}/entries`)
        .then(({ data }) => setEntries(data.entries))
        .catch(() => setEntries([]));
    }
  }, [tab, token, letters, entries]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chat]);

  const send = async () => {
    const text = chatInput.trim();
    if (!text || chatBusy) return;
    setChat((c) => [...c, { role: "user", content: text }]);
    setChatInput("");
    setChatBusy(true);
    try {
      const { data } = await axios.post(`${PORTAL_BASE}/${token}/twin/chat`, {
        message: text,
        session_id: sessionId,
      });
      setSessionId(data.session_id);
      setChat((c) => [...c, { role: "assistant", content: data.reply }]);
    } catch (e) {
      setChat((c) => [
        ...c,
        {
          role: "system",
          content:
            e.response?.data?.detail || "Their twin couldn't reply just now.",
        },
      ]);
    } finally {
      setChatBusy(false);
    }
  };

  if (loading) {
    return (
      <div
        className="min-h-screen flex items-center justify-center"
        style={{ background: "var(--bg-base)" }}
      >
        <Loader2 className="h-6 w-6 animate-spin" style={{ color: "var(--accent)" }} />
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="min-h-screen flex items-center justify-center px-6"
        style={{ background: "var(--bg-base)" }}
        data-testid="heir-portal-error"
      >
        <div className="max-w-md text-center">
          <div className="overline mb-3">heir portal</div>
          <h1 className="font-serif text-3xl mb-3">This link no longer works.</h1>
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            {error}
          </p>
        </div>
      </div>
    );
  }

  const ownerName = summary?.owner?.name || "their";

  return (
    <div
      className="min-h-screen pb-safe"
      style={{
        background: "var(--bg-base)",
        paddingBottom: "env(safe-area-inset-bottom)",
      }}
      data-testid="heir-portal"
    >
      <header
        className="px-6 lg:px-16 py-8 border-b"
        style={{ borderColor: "var(--border-default)", background: "var(--bg-surface)" }}
      >
        <div className="max-w-5xl mx-auto flex items-center gap-4">
          {summary?.owner?.picture ? (
            <img
              src={summary.owner.picture}
              alt=""
              className="h-12 w-12 rounded-full object-cover"
              style={{ border: "1px solid var(--border-default)" }}
            />
          ) : null}
          <div>
            <div className="overline">heirloom · a continuation of</div>
            <h1 className="font-serif text-3xl lg:text-4xl tracking-tight">
              {ownerName}
            </h1>
            <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
              released to you {summary?.heir?.released_at?.slice(0, 10) || ""}
            </p>
          </div>
        </div>
      </header>

      <nav
        className="px-6 lg:px-16 border-b sticky top-0 z-10 backdrop-blur"
        style={{ borderColor: "var(--border-default)", background: "rgba(18,17,16,0.85)" }}
      >
        <div className="max-w-5xl mx-auto flex gap-2 overflow-x-auto py-3">
          {tabs.map((t) => {
            const Icon = t.icon;
            return (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                data-testid={`portal-tab-${t.key}`}
                className="px-4 py-2 text-sm rounded-sm inline-flex items-center gap-2 whitespace-nowrap"
                style={{
                  background: tab === t.key ? "var(--accent)" : "transparent",
                  color: tab === t.key ? "var(--text-inverse)" : "var(--text-secondary)",
                  border:
                    tab === t.key
                      ? "1px solid var(--accent)"
                      : "1px solid var(--border-default)",
                }}
              >
                <Icon className="h-4 w-4" /> {t.label}
              </button>
            );
          })}
        </div>
      </nav>

      <main className="px-6 lg:px-16 py-10 max-w-3xl mx-auto">
        {tab === "welcome" && (
          <motion.section
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
            data-testid="portal-welcome"
          >
            <div className="overline mb-3">a note from them</div>
            <h2 className="font-serif text-3xl lg:text-4xl font-light mb-6">
              {summary?.heir?.name}, this is for you.
            </h2>
            {summary?.heir?.note ? (
              <blockquote
                className="font-serif text-2xl leading-relaxed border-l-2 pl-6 py-2 mb-10"
                style={{
                  borderColor: "var(--accent)",
                  color: "var(--text-primary)",
                }}
              >
                "{summary.heir.note}"
              </blockquote>
            ) : null}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="surface p-5">
                <div className="overline mb-2">letters waiting</div>
                <div className="font-serif text-3xl">
                  {summary?.letters_available ?? 0}
                </div>
              </div>
              <div className="surface p-5">
                <div className="overline mb-2">archive entries</div>
                <div className="font-serif text-3xl">
                  {summary?.entries_available ?? 0}
                </div>
              </div>
              <div className="surface p-5">
                <div className="overline mb-2">talk to their twin</div>
                <button
                  onClick={() => setTab("twin")}
                  className="text-sm mt-2"
                  style={{ color: "var(--accent)" }}
                >
                  Begin →
                </button>
              </div>
            </div>
          </motion.section>
        )}

        {tab === "letters" && (
          <section data-testid="portal-letters">
            <div className="overline mb-3">letters sealed for you</div>
            <h2 className="font-serif text-3xl lg:text-4xl font-light mb-8">
              Read in their own hand.
            </h2>
            {letters === null ? (
              <Loader2 className="h-5 w-5 animate-spin" style={{ color: "var(--accent)" }} />
            ) : letters.length === 0 ? (
              <p className="font-serif text-xl" style={{ color: "var(--text-secondary)" }}>
                No letters have been unlocked yet.
              </p>
            ) : (
              <div className="space-y-6">
                {letters.map((l) => (
                  <article
                    key={l.letter_id}
                    className="surface p-7"
                    data-testid={`portal-letter-${l.letter_id}`}
                  >
                    <div className="overline mb-2">
                      {l.recipient_name || "for you"}
                    </div>
                    <h3 className="font-serif text-2xl mb-4">{l.title}</h3>
                    <p
                      className="font-serif text-base leading-relaxed whitespace-pre-wrap"
                      style={{ color: "var(--text-primary)" }}
                    >
                      {l.body}
                    </p>
                    <div
                      className="text-xs mt-5 font-mono"
                      style={{ color: "var(--text-muted)" }}
                    >
                      written {l.created_at?.slice(0, 10)}
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
        )}

        {tab === "entries" && (
          <section data-testid="portal-entries">
            <div className="overline mb-3">their archive</div>
            <h2 className="font-serif text-3xl lg:text-4xl font-light mb-8">
              Memories, stories, advice.
            </h2>
            {entries === null ? (
              <Loader2 className="h-5 w-5 animate-spin" style={{ color: "var(--accent)" }} />
            ) : entries.length === 0 ? (
              <p className="font-serif text-xl" style={{ color: "var(--text-secondary)" }}>
                The archive is empty.
              </p>
            ) : (
              <div className="space-y-4">
                {entries.map((e, i) => (
                  <article
                    key={e.entry_id || i}
                    className="surface p-6"
                    data-testid={`portal-entry-${e.entry_id || i}`}
                  >
                    <div className="overline mb-2">{e.type}</div>
                    <h4 className="font-serif text-xl mb-3">{e.title}</h4>
                    <p
                      className="text-sm leading-relaxed whitespace-pre-wrap"
                      style={{ color: "var(--text-secondary)" }}
                    >
                      {e.content}
                    </p>
                  </article>
                ))}
              </div>
            )}
          </section>
        )}

        {tab === "twin" && (
          <section data-testid="portal-twin" className="pb-24 sm:pb-0">
            <div className="overline mb-3">talk to {ownerName}</div>
            <h2 className="font-serif text-3xl lg:text-4xl font-light mb-8">
              Ask them anything.
            </h2>
            <div
              className="surface p-4 sm:p-6 mb-4 min-h-[240px] max-h-[50vh] sm:max-h-[60vh] overflow-y-auto"
            >
              {chat.length === 0 && (
                <p
                  className="font-serif text-lg italic"
                  style={{ color: "var(--text-muted)" }}
                >
                  Begin a conversation. Their twin will reply as best it can,
                  grounded in everything they archived.
                </p>
              )}
              {chat.map((m, i) => (
                <div
                  key={i}
                  className="mb-4"
                  data-testid={`portal-msg-${m.role}-${i}`}
                >
                  <div className="overline mb-1">
                    {m.role === "user"
                      ? "you"
                      : m.role === "system"
                      ? "system"
                      : ownerName}
                  </div>
                  <p
                    className="font-serif text-base leading-relaxed whitespace-pre-wrap"
                    style={{
                      color:
                        m.role === "system"
                          ? "var(--text-muted)"
                          : "var(--text-primary)",
                    }}
                  >
                    {m.content}
                  </p>
                </div>
              ))}
              <div ref={messagesEndRef} />
            </div>
            <div
              className="flex gap-2 fixed sm:static left-0 right-0 bottom-0 sm:bottom-auto p-3 sm:p-0 z-20"
              style={{
                background: "rgba(18,17,16,0.96)",
                borderTop: "1px solid var(--border-default)",
                paddingBottom: "max(0.75rem, env(safe-area-inset-bottom))",
              }}
            >
              <input
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
                placeholder="Type a message…"
                disabled={chatBusy}
                data-testid="portal-twin-input"
                className="flex-1 px-3 py-3 text-base sm:text-sm rounded-sm"
                style={{
                  background: "var(--bg-surface)",
                  border: "1px solid var(--border-default)",
                  color: "var(--text-primary)",
                  fontSize: "16px", // prevent iOS zoom
                }}
              />
              <button
                onClick={send}
                disabled={chatBusy || !chatInput.trim()}
                data-testid="portal-twin-send"
                className="px-5 py-3 text-sm rounded-sm inline-flex items-center gap-2 disabled:opacity-50"
                style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
              >
                {chatBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                Send
              </button>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
