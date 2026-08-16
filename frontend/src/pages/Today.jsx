import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AlarmClock, ArrowRight, BookmarkPlus, Calendar, CheckCircle2, Circle, Clock, Feather, Flame, MessageCircle, Sparkles, X } from "lucide-react";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { ToyDesk, ToyKnob, ToyPorthole } from "@/components/ToyPlayset";

const LOOK_AT_SCREEN = "Look at my screen and help me with whatever is on it.";

const GREETINGS = ["Good morning", "Good afternoon", "Good evening"];
const REFLECTIONS = [
  "What's one small joy from yesterday worth keeping?",
  "Who do you wish you'd called this week?",
  "Name one thing your son should know about today.",
  "What surprised you in the last 24 hours?",
  "What did you learn that you don't want to forget?",
  "What's a thought you've been turning over?",
  "What did you do today that future-you will thank you for?",
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
  const navigate = useNavigate();
  const [portrait, setPortrait] = useState("");
  const [data, setData] = useState({ overdue: [], today: [], no_date: [] });
  const [stats, setStats] = useState(null);
  const [onthisday, setOnThisDay] = useState(null);
  const [journals, setJournals] = useState([]);
  const [lastTwin, setLastTwin] = useState(null);
  const [nudge, setNudge] = useState(null);
  const [widgets, setWidgets] = useState({
    reflection: true,
    reminders: true,
    on_this_day: true,
    suggested_topics: true,
    recent_journals: false,
    last_twin_chat: false,
  });

  const load = async () => {
    const [t, s, ob] = await Promise.all([
      api.get("/reminders/today"),
      api.get("/dashboard"),
      api.get("/onboarding/state"),
    ]);
    setData(t.data);
    setStats(s.data);
    if (ob.data?.dashboard_widgets) setWidgets((w) => ({ ...w, ...ob.data.dashboard_widgets }));
  };

  useEffect(() => {
    load();
    api.get("/nudges/today").then(({ data }) => setNudge(data)).catch(() => {});
    api.get("/avatar/me")
      .then(({ data }) => setPortrait(data.avatar_source_url || data.default_url || ""))
      .catch(() => {});
  }, []);

  const dismissNudge = async () => {
    if (!nudge?.nudge_id) return;
    await api.patch(`/nudges/${nudge.nudge_id}`, { status: "dismissed" });
    setNudge(null);
  };
  const actOnNudge = async () => {
    if (!nudge?.nudge_id) return;
    await api.patch(`/nudges/${nudge.nudge_id}`, { status: "acted" });
  };

  useEffect(() => {
    if (widgets.on_this_day) {
      api.get("/dashboard/on-this-day").then(({ data }) => setOnThisDay(data)).catch(() => {});
    }
    if (widgets.recent_journals) {
      api.get("/dashboard/recent-journals").then(({ data }) => setJournals(data.entries || [])).catch(() => {});
    }
    if (widgets.last_twin_chat) {
      api.get("/dashboard/last-twin-chat").then(({ data }) => setLastTwin(data)).catch(() => {});
    }
  }, [widgets.on_this_day, widgets.recent_journals, widgets.last_twin_chat]);

  const complete = async (id) => {
    await api.post(`/reminders/${id}/complete`);
    load();
  };

  const reflection = pickReflection();
  const total = (data.overdue?.length || 0) + (data.today?.length || 0);

  return (
    <div className="px-4 sm:px-8 lg:px-16 py-12 max-w-5xl" data-testid="today-root">
      <header className="mb-12">
        <div className="overline mb-3">today, {new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })}</div>
        <h1
          className="font-serif text-4xl lg:text-5xl font-light tracking-tight"
          data-testid="today-greeting"
        >
          {pickGreeting()}, {user?.name?.split(" ")[0] || "friend"}.
        </h1>
      </header>

      <ToyDesk className="mb-12" testid="today-playset">
        <div className="toy-playset-row">
          <ToyPorthole src={portrait} status="ready" />
          <div className="min-w-0 flex-1">
            <div className="toy-kicker">the play desk</div>
            <h2 className="toy-title text-4xl sm:text-5xl mb-3">Press a button.</h2>
            <p className="toy-copy">
              That&apos;s the whole trick. A face in a round window — not another inbox to live in.
            </p>
            <div className="toy-knob-grid">
              <ToyKnob color="tomato" to="/twin" testid="playset-knob-talk">
                Talk
              </ToyKnob>
              <ToyKnob
                color="sunflower"
                testid="playset-knob-look"
                onClick={() => navigate("/twin", { state: { starter: LOOK_AT_SCREEN } })}
                title="The twin looks at the home computer. The picture is deleted after."
              >
                Look
              </ToyKnob>
              <ToyKnob
                color="sky"
                testid="playset-knob-mail"
                onClick={() => navigate("/twin", { state: { starter: "What's on my plate today?" } })}
              >
                Mail
              </ToyKnob>
              <ToyKnob color="grass" to="/safety" testid="playset-knob-safety">
                Safety
              </ToyKnob>
              <ToyKnob color="sky" to="/writing" testid="playset-knob-write">
                Write
              </ToyKnob>
              <ToyKnob
                color="grape"
                testid="playset-knob-make"
                onClick={() =>
                  navigate("/twin", {
                    state: { starter: "Sketch a picture of a sunny kitchen, then open Photoshop." },
                  })
                }
              >
                Make
              </ToyKnob>
              <ToyKnob color="cream" to="/companion" testid="playset-knob-pc">
                PC
              </ToyKnob>
            </div>
          </div>
        </div>
      </ToyDesk>

      {/* Always-on stat strip */}
      <section className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-12">
        <StatPill icon={Flame} label="streak" value={`${stats?.streak_days ?? 0} ${stats?.streak_days === 1 ? "day" : "days"}`} tid="today-streak" />
        <StatPill icon={AlarmClock} label="open" value={stats?.reminders_open ?? 0} tid="today-open" />
        <StatPill icon={Clock} label="due today" value={total} tid="today-due" />
        <StatPill icon={Sparkles} label="captured" value={stats?.total_entries ?? 0} tid="today-entries" />
      </section>

      {/* From your twin — daily nudge */}
      {nudge && nudge.status !== "dismissed" && (
        <section
          className="surface p-7 mb-12 relative"
          style={{ borderLeft: "3px solid var(--accent)" }}
          data-testid="today-nudge"
        >
          <button
            onClick={dismissNudge}
            data-testid="nudge-dismiss"
            className="absolute top-4 right-4 p-1"
            title="Dismiss"
          >
            <X className="h-4 w-4" style={{ color: "var(--text-muted)" }} />
          </button>
          <div className="overline mb-2 flex items-center gap-2">
            <Sparkles className="h-3.5 w-3.5" style={{ color: "var(--accent)" }} /> from your twin
          </div>
          <h2
            className="font-serif text-2xl lg:text-3xl mb-3"
            style={{ color: "var(--text-primary)" }}
            data-testid="nudge-title"
          >
            {nudge.title}
          </h2>
          <p
            className="font-serif text-lg leading-relaxed mb-5 max-w-3xl"
            style={{ color: "var(--text-secondary)" }}
            data-testid="nudge-body"
          >
            {nudge.body}
          </p>
          <Link
            to={`/interviewer?topic=${encodeURIComponent(nudge.action_prompt || nudge.title)}&key=nudge_${nudge.nudge_id}`}
            onClick={actOnNudge}
            data-testid="nudge-act"
            className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded-sm"
            style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
          >
            Answer this <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </section>
      )}

      {/* Reflection */}
      {widgets.reflection && (
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
      )}

      {/* Reminders */}
      {widgets.reminders && (
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
      )}

      {/* On this day */}
      {widgets.on_this_day && onthisday?.entries?.length > 0 && (
        <section className="mb-12" data-testid="today-onthisday">
          <div className="overline mb-2 flex items-center gap-2"><Calendar className="h-3.5 w-3.5" /> on this day</div>
          <h2 className="font-serif text-2xl mb-6">A year ago, two years ago, you wrote this:</h2>
          <div className="space-y-3">
            {onthisday.entries.slice(0, 4).map((e) => (
              <div key={e.entry_id} className="surface px-6 py-5" data-testid={`onthisday-${e.entry_id}`}>
                <div className="flex justify-between items-baseline mb-1">
                  <div className="overline">{e.type}</div>
                  <div className="font-mono text-xs" style={{ color: "var(--text-muted)" }}>
                    {new Date(e.created_at).getFullYear()}
                  </div>
                </div>
                <div className="font-serif text-lg mb-1" style={{ color: "var(--text-primary)" }}>
                  {e.title}
                </div>
                <p className="text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                  {e.content.slice(0, 240)}{e.content.length > 240 ? "…" : ""}
                </p>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Last twin chat tail */}
      {widgets.last_twin_chat && lastTwin?.tail?.length > 0 && (
        <section className="mb-12" data-testid="today-lasttwin">
          <div className="overline mb-2 flex items-center gap-2"><MessageCircle className="h-3.5 w-3.5" /> last conversation with the twin</div>
          <h2 className="font-serif text-2xl mb-6">Where you left off</h2>
          <div className="surface p-6 space-y-4">
            {lastTwin.tail.map((m, i) => (
              <div key={i}>
                <div className="overline mb-1">{m.role === "user" ? "you" : "the twin"}</div>
                <p className="text-sm leading-relaxed" style={{ color: m.role === "user" ? "var(--text-secondary)" : "var(--text-primary)" }}>
                  {m.content.slice(0, 280)}{m.content.length > 280 ? "…" : ""}
                </p>
              </div>
            ))}
            <Link to="/twin" className="inline-flex items-center gap-2 text-sm hover:text-[var(--accent)]" style={{ color: "var(--accent)" }}>
              continue <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </section>
      )}

      {/* Recent voice journals */}
      {widgets.recent_journals && journals.length > 0 && (
        <section className="mb-12" data-testid="today-journals">
          <div className="overline mb-2 flex items-center gap-2"><Feather className="h-3.5 w-3.5" /> recent voice journals</div>
          <h2 className="font-serif text-2xl mb-6">Your voice, lately</h2>
          <div className="space-y-3">
            {journals.map((j) => (
              <div key={j.entry_id} className="surface px-5 py-4" data-testid={`journal-${j.entry_id}`}>
                <div className="flex justify-between items-baseline mb-1">
                  <div className="font-serif text-base">{j.title}</div>
                  <div className="font-mono text-xs" style={{ color: "var(--text-muted)" }}>
                    {new Date(j.created_at).toLocaleDateString()}
                  </div>
                </div>
                <p className="text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                  {j.content.slice(0, 200)}{j.content.length > 200 ? "…" : ""}
                </p>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Suggested capture */}
      {widgets.suggested_topics && stats?.suggested_topics?.length > 0 && (
        <section data-testid="today-suggest">
          <div className="overline mb-4 flex items-center gap-2"><BookmarkPlus className="h-3.5 w-3.5" /> suggested capture</div>
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
