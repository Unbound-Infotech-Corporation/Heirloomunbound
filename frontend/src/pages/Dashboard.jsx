import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, BookText, Feather, MessageCircleHeart, Mic, Sparkles, Users } from "lucide-react";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";

const QUICK_LINKS = [
  { to: "/interviewer", label: "Continue interview", desc: "Pick up where you left off", icon: MessageCircleHeart, tid: "quick-interview" },
  { to: "/journal", label: "Voice journal", desc: "Speak freely. Get transcribed.", icon: Feather, tid: "quick-journal" },
  { to: "/import", label: "Import a memory", desc: "Paste Facebook, tweets, blogs", icon: BookText, tid: "quick-import" },
  { to: "/twin", label: "Sit with your twin", desc: "Talk to the version of you", icon: Sparkles, tid: "quick-twin" },
];

export default function Dashboard() {
  const { user } = useAuth();
  const [stats, setStats] = useState(null);

  useEffect(() => {
    api.get("/dashboard").then(({ data }) => setStats(data)).catch(() => setStats(null));
  }, []);

  return (
    <div className="px-4 sm:px-8 lg:px-16 py-12 lg:py-16 max-w-7xl" data-testid="dashboard-root">
      <header className="mb-14">
        <div className="overline mb-3">your archive</div>
        <h1
          className="font-serif text-4xl lg:text-5xl font-light tracking-tight"
          style={{ color: "var(--text-primary)" }}
          data-testid="dashboard-greeting"
        >
          Hello, {user?.name?.split(" ")[0] || "friend"}.
        </h1>
        <p className="mt-3 text-base max-w-xl" style={{ color: "var(--text-secondary)" }}>
          A little more of you is here today than yesterday. Keep going.
        </p>
      </header>

      <section className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-14">
        <Stat label="entries" value={stats?.total_entries ?? 0} testid="stat-entries" />
        <Stat label="words" value={stats?.total_words ?? 0} testid="stat-words" />
        <Stat label="interviews" value={stats?.interview_conversations ?? 0} testid="stat-interviews" />
        <Stat label="heirs" value={stats?.heirs ?? 0} testid="stat-heirs" />
      </section>

      <section className="surface p-8 lg:p-10 mb-14 grain-overlay">
        <div className="flex justify-between items-baseline mb-6">
          <div>
            <div className="overline mb-2">a life unfolding</div>
            <h2 className="font-serif text-3xl">{stats?.completeness ?? 0}% captured</h2>
          </div>
          <div className="font-mono text-xs" style={{ color: "var(--text-muted)" }}>
            target · 80 entries · 8,000 words
          </div>
        </div>
        <div
          className="w-full h-px relative"
          style={{ background: "var(--border-default)" }}
        >
          <div
            className="absolute top-0 left-0 h-px transition-all duration-700"
            style={{
              width: `${stats?.completeness ?? 0}%`,
              background: "var(--accent)",
              boxShadow: "0 0 10px rgba(212,163,115,0.4)",
            }}
            data-testid="completeness-bar"
          />
        </div>
      </section>

      <section className="grid lg:grid-cols-2 gap-4 mb-14">
        {QUICK_LINKS.map((q) => {
          const Icon = q.icon;
          return (
            <Link
              key={q.to}
              to={q.to}
              data-testid={q.tid}
              className="surface p-7 flex justify-between items-start group transition-all duration-300 hover:-translate-y-1"
              style={{ borderColor: "var(--border-default)" }}
            >
              <div>
                <Icon className="h-5 w-5 mb-4" style={{ color: "var(--accent)" }} />
                <div className="font-serif text-2xl mb-1">{q.label}</div>
                <div className="text-sm" style={{ color: "var(--text-secondary)" }}>
                  {q.desc}
                </div>
              </div>
              <ArrowRight
                className="h-5 w-5 mt-1 transition-transform group-hover:translate-x-1"
                style={{ color: "var(--text-muted)" }}
              />
            </Link>
          );
        })}
      </section>

      {stats?.suggested_topics?.length > 0 && (
        <section className="mb-10">
          <div className="overline mb-4">suggested next</div>
          <h2 className="font-serif text-2xl mb-6">Stories you haven't told yet</h2>
          <div className="grid md:grid-cols-2 gap-4">
            {stats.suggested_topics.map((t) => (
              <Link
                key={t.key}
                to={`/interviewer?topic=${encodeURIComponent(t.question)}&key=${t.key}`}
                data-testid={`suggested-${t.key}`}
                className="surface p-6 hover:border-[var(--accent)] transition-colors"
              >
                <div className="overline mb-2">{t.label}</div>
                <div className="font-serif text-lg leading-snug">{t.question}</div>
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function Stat({ label, value, testid }) {
  return (
    <div className="surface p-6" data-testid={testid}>
      <div className="overline mb-2">{label}</div>
      <div className="font-mono text-4xl font-light" style={{ color: "var(--text-primary)" }}>
        {Number(value).toLocaleString()}
      </div>
    </div>
  );
}
