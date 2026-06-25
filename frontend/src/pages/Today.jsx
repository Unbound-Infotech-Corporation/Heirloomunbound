import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlarmClock, ArrowRight, CheckCircle2, Circle, Clock, Flame, Sparkles } from "lucide-react";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";

const GREETINGS = ["Good morning", "Good afternoon", "Good evening"];
const REFLECTIONS = [
  "What's one small joy from yesterday worth keeping?",
  "Who do you wish you'd called this week?",
  "Name one thing your son should know about today.",
  "What surprised you in the last 24 hours?",
  "What did you learn that you don't want to forget?",
  "What's a thought you've been turning over?",
];

function pickGreeting() {
  const h = new Date().getHours();
  if (h < 12) return GREETINGS[0];
  if (h < 18) return GREETINGS[1];
  return GREETINGS[2];
}

function pickReflection() {
  const seed = new Date().getDate();
  return REFLECTIONS[seed % REFLECTIONS.length];
}

export default function Today() {
  const { user } = useAuth();
  const [data, setData] = useState({ overdue: [], today: [], no_date: [] });
  const [stats, setStats] = useState(null);

  const load = async () => {
    const [t, s] = await Promise.all([api.get("/reminders/today"), api.get("/dashboard")]);
    setData(t.data);
    setStats(s.data);
  };

  useEffect(() => {
    load();
  }, []);

  const complete = async (id) => {
    await api.post(`/reminders/${id}/complete`);
    load();
  };

  const reflection = pickReflection();
  const total = (data.overdue?.length || 0) + (data.today?.length || 0);

  return (
    <div className="px-10 lg:px-16 py-12 max-w-5xl" data-testid="today-root">
      <header className="mb-12">
        <div className="overline mb-3">today, {new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}</div>
        <h1
          className="font-serif text-4xl lg:text-5xl font-light tracking-tight"
          data-testid="today-greeting"
        >
          {pickGreeting()}, {user?.name?.split(" ")[0] || "friend"}.
        </h1>
      </header>

      {/* Stats strip */}
      <section className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-12">
        <StatPill icon={Flame} label="streak" value={`${stats?.streak_days ?? 0} ${stats?.streak_days === 1 ? "day" : "days"}`} tid="today-streak" />
        <StatPill icon={AlarmClock} label="open" value={stats?.reminders_open ?? 0} tid="today-open" />
        <StatPill icon={Clock} label="due today" value={total} tid="today-due" />
        <StatPill icon={Sparkles} label="captured" value={stats?.total_entries ?? 0} tid="today-entries" />
      </section>

      {/* Reflection prompt */}
      <section className="surface p-7 mb-12 grain-overlay" data-testid="today-reflection">
        <div className="overline mb-3">today's reflection</div>
        <p
          className="font-serif text-2xl lg:text-3xl leading-snug max-w-3xl mb-5"
          style={{ color: "var(--text-primary)" }}
        >
          {reflection}
        </p>
        <Link
          to={`/interviewer?topic=${encodeURIComponent(reflection)}&key=daily`}
          data-testid="today-reflect-button"
          className="inline-flex items-center gap-2 text-sm hover:text-[var(--accent)] transition-colors"
          style={{ color: "var(--text-secondary)" }}
        >
          sit with this question <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </section>

      {/* Reminders */}
      <section className="mb-12">
        <div className="flex justify-between items-end mb-5">
          <div>
            <div className="overline mb-2">reminders</div>
            <h2 className="font-serif text-2xl">On your plate</h2>
          </div>
          <Link to="/reminders" data-testid="today-all-reminders" className="text-sm hover:text-[var(--accent)]" style={{ color: "var(--text-secondary)" }}>
            see all →
          </Link>
        </div>

        {total === 0 && (data.no_date?.length || 0) === 0 ? (
          <div className="surface p-10 text-center" data-testid="today-empty">
            <p className="font-serif text-xl" style={{ color: "var(--text-secondary)" }}>
              Nothing on your plate. Use the capture bar to jot something down.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {data.overdue?.map((r) => (
              <ReminderRow key={r.reminder_id} r={r} onComplete={complete} variant="overdue" />
            ))}
            {data.today?.map((r) => (
              <ReminderRow key={r.reminder_id} r={r} onComplete={complete} variant="today" />
            ))}
            {data.no_date?.map((r) => (
              <ReminderRow key={r.reminder_id} r={r} onComplete={complete} variant="someday" />
            ))}
          </div>
        )}
      </section>

      {/* Suggested capture */}
      {stats?.suggested_topics?.length > 0 && (
        <section>
          <div className="overline mb-4">suggested capture</div>
          <h2 className="font-serif text-2xl mb-6">A story you haven't told</h2>
          <div className="grid md:grid-cols-2 gap-4">
            {stats.suggested_topics.slice(0, 4).map((t) => (
              <Link
                key={t.key}
                to={`/interviewer?topic=${encodeURIComponent(t.question)}&key=${t.key}`}
                data-testid={`today-suggest-${t.key}`}
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

function StatPill({ icon: Icon, label, value, tid }) {
  return (
    <div className="surface p-5" data-testid={tid}>
      <div className="flex items-center gap-2 overline mb-2">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <div className="font-mono text-2xl font-light" style={{ color: "var(--text-primary)" }}>
        {value}
      </div>
    </div>
  );
}

function ReminderRow({ r, onComplete, variant }) {
  const color =
    variant === "overdue"
      ? "var(--danger)"
      : variant === "today"
      ? "var(--accent)"
      : "var(--text-muted)";
  return (
    <div
      className="surface px-5 py-4 flex items-center gap-4 group"
      data-testid={`reminder-${r.reminder_id}`}
    >
      <button
        onClick={() => onComplete(r.reminder_id)}
        data-testid={`complete-${r.reminder_id}`}
        className="shrink-0"
        title="Mark done"
      >
        <Circle className="h-5 w-5 group-hover:hidden" style={{ color }} />
        <CheckCircle2 className="h-5 w-5 hidden group-hover:block" style={{ color: "var(--accent)" }} />
      </button>
      <div className="flex-1">
        <div className="text-sm" style={{ color: "var(--text-primary)" }}>{r.text}</div>
        {r.due_at && (
          <div className="font-mono text-xs mt-1" style={{ color }}>
            {variant === "overdue" ? "overdue · " : ""}
            {new Date(r.due_at).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}
          </div>
        )}
      </div>
      <div className="overline" style={{ color }}>{variant}</div>
    </div>
  );
}
