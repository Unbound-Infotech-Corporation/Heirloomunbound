import { useEffect, useState } from "react";
import { ArrowLeft, ArrowRight, CheckCircle2, Loader2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";

const VALUES = [
  "kindness",
  "honesty",
  "curiosity",
  "discipline",
  "faith",
  "loyalty",
  "humor",
  "freedom",
  "family",
  "craft",
  "patience",
  "grit",
];

const CHAPTERS = [
  "Parent of young kids",
  "Parent of teens",
  "Parent of grown kids",
  "Building a career",
  "Mid-career, settled",
  "Retired",
  "Starting over",
  "Caregiver",
  "Solo & figuring it out",
];

const STEPS = [
  { key: "name", label: "your name" },
  { key: "chapter", label: "your chapter" },
  { key: "people", label: "your people" },
  { key: "values", label: "what you live by" },
  { key: "saying", label: "your saying" },
  { key: "remember", label: "to be remembered" },
  { key: "review", label: "review" },
];

export default function Onboarding() {
  const navigate = useNavigate();
  const { user, refresh } = useAuth();
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [a, setA] = useState({
    preferred_name: "",
    chapter: "",
    key_people: "",
    guiding_values: [],
    favorite_saying: "",
    one_thing_to_remember: "",
    daily_routine: "",
  });

  useEffect(() => {
    api.get("/onboarding/state").then(({ data }) => {
      if (data.onboarded) {
        navigate("/today", { replace: true });
        return;
      }
      setA((prev) => ({ ...prev, preferred_name: data.preferred_name || prev.preferred_name }));
    });
  }, [navigate]);

  const toggleValue = (v) => {
    setA((s) => ({
      ...s,
      guiding_values: s.guiding_values.includes(v)
        ? s.guiding_values.filter((x) => x !== v)
        : [...s.guiding_values, v].slice(0, 5),
    }));
  };

  const next = () => setStep((s) => Math.min(s + 1, STEPS.length - 1));
  const prev = () => setStep((s) => Math.max(s - 1, 0));

  const finish = async () => {
    setBusy(true);
    try {
      await api.post("/onboarding/complete", a);
      await refresh();
      navigate("/today", { replace: true });
    } catch (e) {
      alert("Couldn't save: " + e.message);
    } finally {
      setBusy(false);
    }
  };

  const stepValid = () => {
    if (step === 0) return a.preferred_name.trim().length > 0;
    if (step === 1) return a.chapter.trim().length > 0;
    if (step === 2) return a.key_people.trim().length > 0;
    if (step === 3) return a.guiding_values.length > 0;
    if (step === 5) return a.one_thing_to_remember.trim().length > 0;
    return true;
  };

  return (
    <div className="min-h-screen flex flex-col" style={{ background: "var(--bg-base)" }} data-testid="onboarding-root">
      <header className="px-5 sm:px-10 lg:px-20 py-8 flex items-center justify-between">
        <div>
          <div className="overline mb-1">step {step + 1} of {STEPS.length}</div>
          <div className="font-serif text-2xl" style={{ color: "var(--text-primary)" }}>
            Heirloom
          </div>
        </div>
        <div className="flex gap-1.5">
          {STEPS.map((_, i) => (
            <div
              key={i}
              className="h-1 w-8 transition-colors"
              style={{
                background: i <= step ? "var(--accent)" : "var(--border-default)",
              }}
            />
          ))}
        </div>
      </header>

      <main className="flex-1 flex flex-col justify-center px-5 sm:px-10 lg:px-20 max-w-3xl pb-20">
        {step === 0 && (
          <Step title="What should the Twin call you?" subtitle="Pick the name you'd want a grandchild to hear.">
            <input
              autoFocus
              value={a.preferred_name}
              onChange={(e) => setA({ ...a, preferred_name: e.target.value })}
              onKeyDown={(e) => e.key === "Enter" && stepValid() && next()}
              data-testid="ob-name"
              placeholder={user?.name || "Your name"}
              className="w-full font-serif text-3xl bg-transparent border-b py-3 outline-none"
              style={{ borderColor: "var(--border-default)", color: "var(--text-primary)" }}
            />
          </Step>
        )}

        {step === 1 && (
          <Step title={`What chapter are you in, ${a.preferred_name.split(" ")[0]}?`} subtitle="Roughly. You can refine it later.">
            <div className="grid sm:grid-cols-2 gap-3">
              {CHAPTERS.map((c) => (
                <button
                  key={c}
                  onClick={() => setA({ ...a, chapter: c })}
                  data-testid={`ob-chapter-${c.toLowerCase().replace(/[^a-z]+/g, "-")}`}
                  className="px-4 py-3 text-left text-sm rounded-sm transition-colors"
                  style={{
                    border: a.chapter === c ? "1px solid var(--accent)" : "1px solid var(--border-default)",
                    background: a.chapter === c ? "var(--accent-muted)" : "transparent",
                    color: a.chapter === c ? "var(--text-primary)" : "var(--text-secondary)",
                  }}
                >
                  {c}
                </button>
              ))}
            </div>
            <input
              value={CHAPTERS.includes(a.chapter) ? "" : a.chapter}
              onChange={(e) => setA({ ...a, chapter: e.target.value })}
              data-testid="ob-chapter-custom"
              placeholder="or describe it in your own words…"
              className="mt-4 w-full px-4 py-2 text-sm rounded-sm"
              style={{ background: "var(--bg-surface)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
            />
          </Step>
        )}

        {step === 2 && (
          <Step title="Who matters most to you right now?" subtitle="The names. Why. One paragraph is plenty.">
            <textarea
              autoFocus
              rows={6}
              value={a.key_people}
              onChange={(e) => setA({ ...a, key_people: e.target.value })}
              data-testid="ob-people"
              placeholder="My son Elias, who's six now and still believes I can fix anything…"
              className="w-full bg-transparent border-b py-3 outline-none text-lg leading-relaxed resize-none"
              style={{ borderColor: "var(--border-default)", color: "var(--text-primary)" }}
            />
          </Step>
        )}

        {step === 3 && (
          <Step title="What do you try to live by?" subtitle="Pick up to 5 — or write your own.">
            <div className="flex flex-wrap gap-2 mb-4">
              {VALUES.map((v) => (
                <button
                  key={v}
                  onClick={() => toggleValue(v)}
                  data-testid={`ob-value-${v}`}
                  className="px-4 py-2 text-sm rounded-full transition-colors"
                  style={{
                    border: a.guiding_values.includes(v) ? "1px solid var(--accent)" : "1px solid var(--border-default)",
                    background: a.guiding_values.includes(v) ? "var(--accent)" : "transparent",
                    color: a.guiding_values.includes(v) ? "var(--text-inverse)" : "var(--text-secondary)",
                  }}
                >
                  {v}
                </button>
              ))}
            </div>
            <input
              placeholder="add your own (press Enter)"
              data-testid="ob-value-custom"
              onKeyDown={(e) => {
                if (e.key === "Enter" && e.target.value.trim()) {
                  toggleValue(e.target.value.trim().toLowerCase());
                  e.target.value = "";
                }
              }}
              className="w-full px-4 py-2 text-sm rounded-sm"
              style={{ background: "var(--bg-surface)", border: "1px solid var(--border-default)", color: "var(--text-primary)" }}
            />
          </Step>
        )}

        {step === 4 && (
          <Step title="What do you find yourself saying?" subtitle="A phrase that comes out of your mouth more than you realize. Optional.">
            <input
              autoFocus
              value={a.favorite_saying}
              onChange={(e) => setA({ ...a, favorite_saying: e.target.value })}
              data-testid="ob-saying"
              placeholder={'"It is what it is, but it doesn\u2019t have to stay that way."'}
              className="w-full font-serif text-2xl italic bg-transparent border-b py-3 outline-none"
              style={{ borderColor: "var(--border-default)", color: "var(--text-primary)" }}
            />
          </Step>
        )}

        {step === 5 && (
          <Step title="One thing you want them to remember about you." subtitle="When everything else fades. The most you can put into a single sentence.">
            <textarea
              autoFocus
              rows={4}
              value={a.one_thing_to_remember}
              onChange={(e) => setA({ ...a, one_thing_to_remember: e.target.value })}
              data-testid="ob-remember"
              placeholder="That I showed up. Even when it was inconvenient. Especially then."
              className="w-full font-serif text-xl bg-transparent border-b py-3 outline-none leading-relaxed resize-none"
              style={{ borderColor: "var(--border-default)", color: "var(--text-primary)" }}
            />
          </Step>
        )}

        {step === 6 && (
          <Step title="Here's what we'll plant in your archive." subtitle="You can edit any of these later in the Library.">
            <div className="space-y-3" data-testid="ob-review">
              <ReviewRow label="Name" value={a.preferred_name} />
              <ReviewRow label="Chapter" value={a.chapter} />
              <ReviewRow label="Key people" value={a.key_people} />
              <ReviewRow label="Values" value={a.guiding_values.join(" · ")} />
              {a.favorite_saying && <ReviewRow label="Saying" value={a.favorite_saying} />}
              <ReviewRow label="To remember" value={a.one_thing_to_remember} />
            </div>
          </Step>
        )}
      </main>

      <footer
        className="pl-10 lg:pl-20 py-6 pr-44 sm:pr-56 lg:pr-60 flex justify-between items-center border-t"
        style={{ borderColor: "var(--border-default)" }}
      >
        <button
          onClick={prev}
          disabled={step === 0 || busy}
          data-testid="ob-prev"
          className="inline-flex items-center gap-2 text-sm disabled:opacity-30"
          style={{ color: "var(--text-secondary)" }}
        >
          <ArrowLeft className="h-4 w-4" /> back
        </button>
        {step < STEPS.length - 1 ? (
          <button
            onClick={next}
            disabled={!stepValid() || busy}
            data-testid="ob-next"
            className="inline-flex items-center gap-2 px-6 py-3 text-sm rounded-sm disabled:opacity-50"
            style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
          >
            continue <ArrowRight className="h-4 w-4" />
          </button>
        ) : (
          <button
            onClick={finish}
            disabled={busy}
            data-testid="ob-finish"
            className="inline-flex items-center gap-2 px-6 py-3 text-sm rounded-sm disabled:opacity-50"
            style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
            begin the archive
          </button>
        )}
      </footer>
    </div>
  );
}

function Step({ title, subtitle, children }) {
  return (
    <div>
      <h1 className="font-serif text-4xl lg:text-5xl font-light leading-tight mb-3" style={{ color: "var(--text-primary)" }}>
        {title}
      </h1>
      <p className="mb-10 text-base" style={{ color: "var(--text-secondary)" }}>
        {subtitle}
      </p>
      <div>{children}</div>
    </div>
  );
}

function ReviewRow({ label, value }) {
  return (
    <div className="flex gap-6 py-3 border-b" style={{ borderColor: "var(--border-default)" }}>
      <div className="overline w-32 shrink-0">{label}</div>
      <div className="flex-1 text-sm" style={{ color: "var(--text-primary)" }}>{value || "—"}</div>
    </div>
  );
}
