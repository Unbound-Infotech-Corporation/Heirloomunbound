import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, ArrowRight, CheckCircle2, Heart, Loader2, Shield } from "lucide-react";
import { toast } from "sonner";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";

/**
 * Grandmother-friendly setup: one big question per screen, plain words,
 * large tap targets, no jargon.
 */
export default function EasySetup() {
  const navigate = useNavigate();
  const { refresh } = useAuth();
  const [status, setStatus] = useState(null);
  const [step, setStep] = useState(0); // 0 welcome, 1 heir, 2 executor, 3 style, 4 memory, 5 done
  const [busy, setBusy] = useState(false);

  const [heir, setHeir] = useState({ name: "", email: "", relationship: "child", note: "" });
  const [executor, setExecutor] = useState({ name: "", email: "", same_as_heir: false });
  const [memory, setMemory] = useState("");

  const load = async () => {
    const { data } = await api.get("/easy-setup/status");
    setStatus(data);
    return data;
  };

  useEffect(() => {
    load().catch((e) => toast.error(e.response?.data?.detail || e.message));
  }, []);

  const goNext = () => setStep((s) => Math.min(s + 1, 5));
  const goBack = () => setStep((s) => Math.max(s - 1, 0));

  const saveHeir = async () => {
    if (!heir.name.trim() || !heir.email.trim()) {
      toast.error("Please fill in their name and email.");
      return;
    }
    setBusy(true);
    try {
      const { data } = await api.post("/easy-setup/heir", heir);
      setStatus(data);
      if (!executor.name && !executor.email) {
        setExecutor({ name: heir.name, email: heir.email, same_as_heir: true });
      }
      toast.success("Saved. They'll be able to reach your twin someday.");
      goNext();
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message);
    } finally {
      setBusy(false);
    }
  };

  const saveExecutor = async () => {
    const name = executor.same_as_heir ? heir.name : executor.name;
    const email = executor.same_as_heir ? heir.email : executor.email;
    if (!name?.trim() || !email?.trim()) {
      toast.error("Please name a trusted person and their email.");
      return;
    }
    setBusy(true);
    try {
      const { data } = await api.post("/easy-setup/executor", { name, email });
      setStatus(data);
      toast.success("Trusted person saved.");
      goNext();
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message);
    } finally {
      setBusy(false);
    }
  };

  const saveStyle = async (style) => {
    setBusy(true);
    try {
      const { data } = await api.post("/easy-setup/style", { style });
      setStatus(data);
      toast.success("Got it — that's how your twin will behave.");
      goNext();
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message);
    } finally {
      setBusy(false);
    }
  };

  const saveMemory = async () => {
    if (memory.trim().length < 3) {
      toast.error("Write a little something — even one sentence helps.");
      return;
    }
    setBusy(true);
    try {
      const { data } = await api.post("/easy-setup/memory", { text: memory });
      setStatus(data);
      toast.success("Memory saved.");
      await finish(data);
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message);
    } finally {
      setBusy(false);
    }
  };

  const skipMemory = async () => {
    await finish(status);
  };

  const finish = async (st) => {
    setBusy(true);
    try {
      const { data } = await api.post("/easy-setup/finish");
      setStatus(data || st);
      await refresh?.();
      setStep(5);
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message);
    } finally {
      setBusy(false);
    }
  };

  if (!status) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center" data-testid="easy-setup-loading">
        <Loader2 className="h-7 w-7 animate-spin" style={{ color: "var(--accent)" }} />
      </div>
    );
  }

  const progress = Math.min(step, 5);

  return (
    <div
      className="px-4 sm:px-8 lg:px-16 py-10 max-w-2xl mx-auto"
      style={{ paddingBottom: "max(3rem, env(safe-area-inset-bottom))" }}
      data-testid="easy-setup-root"
    >
      <header className="mb-8">
        <div className="overline mb-2">simple setup</div>
        <h1 className="font-serif text-3xl sm:text-4xl font-light tracking-tight leading-tight">
          A few easy questions.
        </h1>
        <p className="mt-3 text-base sm:text-lg" style={{ color: "var(--text-secondary)" }}>
          No tech talk. You can change anything later.
        </p>
        <div className="flex gap-2 mt-6" aria-hidden>
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <div
              key={i}
              className="h-1.5 flex-1 rounded-sm"
              style={{ background: i <= progress ? "var(--accent)" : "var(--border-default)" }}
            />
          ))}
        </div>
      </header>

      {step === 0 && (
        <section className="space-y-6" data-testid="easy-step-welcome">
          <p className="font-serif text-2xl sm:text-3xl leading-snug">
            Heirloom keeps your stories so your family can still hear from you someday.
          </p>
          <ul className="space-y-4 text-base sm:text-lg" style={{ color: "var(--text-secondary)" }}>
            <li className="flex gap-3"><Heart className="h-5 w-5 mt-1 shrink-0" style={{ color: "var(--accent)" }} /> Who should receive this later</li>
            <li className="flex gap-3"><Shield className="h-5 w-5 mt-1 shrink-0" style={{ color: "var(--accent)" }} /> Who you trust to unlock it</li>
            <li className="flex gap-3"><CheckCircle2 className="h-5 w-5 mt-1 shrink-0" style={{ color: "var(--accent)" }} /> How careful your twin should be</li>
          </ul>
          <BigButton onClick={goNext} testId="easy-start">
            Let&apos;s begin
          </BigButton>
          <button
            type="button"
            onClick={() => navigate("/settings")}
            className="text-sm underline"
            style={{ color: "var(--text-muted)" }}
          >
            I&apos;ll use the regular settings instead
          </button>
        </section>
      )}

      {step === 1 && (
        <section className="space-y-5" data-testid="easy-step-heir">
          <h2 className="font-serif text-2xl sm:text-3xl font-light">Who should get this someday?</h2>
          <p className="text-base" style={{ color: "var(--text-secondary)" }}>
            Usually a child, spouse, or close friend. Just one person for now — you can add more later.
          </p>
          <Field label="Their first name" value={heir.name} onChange={(v) => setHeir({ ...heir, name: v })} testId="easy-heir-name" autoFocus />
          <Field label="Their email" value={heir.email} onChange={(v) => setHeir({ ...heir, email: v })} testId="easy-heir-email" type="email" />
          <label className="block text-base">
            <span className="mb-2 block" style={{ color: "var(--text-secondary)" }}>They are my…</span>
            <select
              value={heir.relationship}
              onChange={(e) => setHeir({ ...heir, relationship: e.target.value })}
              data-testid="easy-heir-relationship"
              className="w-full px-4 py-3 text-lg rounded-sm"
              style={inputStyle}
            >
              {["child", "spouse", "partner", "grandchild", "sibling", "friend", "loved one"].map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </label>
          <Field
            label="A short note for them (optional)"
            value={heir.note}
            onChange={(v) => setHeir({ ...heir, note: v })}
            testId="easy-heir-note"
            multiline
            placeholder="I love you. This is for you when you need it."
          />
          <NavRow onBack={goBack} onNext={saveHeir} nextLabel={busy ? "Saving…" : "Save & continue"} busy={busy} nextTestId="easy-heir-save" />
          {status.heirs_count > 0 && (
            <button type="button" onClick={goNext} className="text-sm underline" style={{ color: "var(--text-muted)" }} data-testid="easy-heir-skip">
              Already have someone saved — skip
            </button>
          )}
        </section>
      )}

      {step === 2 && (
        <section className="space-y-5" data-testid="easy-step-executor">
          <h2 className="font-serif text-2xl sm:text-3xl font-light">Who can unlock it if something happens to you?</h2>
          <p className="text-base" style={{ color: "var(--text-secondary)" }}>
            This trusted person confirms that it&apos;s time. Nothing opens right away — there&apos;s a waiting period so mistakes can be fixed.
          </p>
          <label className="flex items-start gap-3 text-base cursor-pointer p-4 rounded-sm" style={{ border: "1px solid var(--border-default)" }}>
            <input
              type="checkbox"
              className="mt-1 h-5 w-5"
              checked={executor.same_as_heir}
              onChange={(e) => setExecutor({ ...executor, same_as_heir: e.target.checked })}
              data-testid="easy-executor-same"
            />
            <span>Same person I just named</span>
          </label>
          {!executor.same_as_heir && (
            <>
              <Field label="Their name" value={executor.name} onChange={(v) => setExecutor({ ...executor, name: v })} testId="easy-executor-name" />
              <Field label="Their email" value={executor.email} onChange={(v) => setExecutor({ ...executor, email: v })} testId="easy-executor-email" type="email" />
            </>
          )}
          <NavRow onBack={goBack} onNext={saveExecutor} nextLabel={busy ? "Saving…" : "Save & continue"} busy={busy} nextTestId="easy-executor-save" />
          {status.has_executor && (
            <button type="button" onClick={goNext} className="text-sm underline" style={{ color: "var(--text-muted)" }}>
              Already set — skip
            </button>
          )}
        </section>
      )}

      {step === 3 && (
        <section className="space-y-5" data-testid="easy-step-style">
          <h2 className="font-serif text-2xl sm:text-3xl font-light">How should your twin talk later?</h2>
          <p className="text-base" style={{ color: "var(--text-secondary)" }}>
            Pick the one that feels right. You can change this anytime.
          </p>
          <ChoiceCard
            title="Only say what I wrote down"
            body="Safest. If you didn't record it, the twin won't invent it."
            onClick={() => saveStyle("only_written")}
            testId="easy-style-only"
            disabled={busy}
          />
          <ChoiceCard
            title="Warm and careful"
            body="Sounds more like everyday you, but still won't make up important facts."
            onClick={() => saveStyle("warm_careful")}
            testId="easy-style-warm"
            disabled={busy}
          />
          <ChoiceCard
            title="Practice the forever version now"
            body="Turns on Death Governance today — the careful, grief-aware mode your family would get later."
            onClick={() => saveStyle("practice_forever")}
            testId="easy-style-practice"
            disabled={busy}
          />
          <button type="button" onClick={goBack} className="inline-flex items-center gap-2 text-sm" style={{ color: "var(--text-muted)" }}>
            <ArrowLeft className="h-4 w-4" /> Back
          </button>
        </section>
      )}

      {step === 4 && (
        <section className="space-y-5" data-testid="easy-step-memory">
          <h2 className="font-serif text-2xl sm:text-3xl font-light">What&apos;s one thing you want them to know?</h2>
          <p className="text-base" style={{ color: "var(--text-secondary)" }}>
            A story, a belief, or a sentence you hope they never forget. One is enough to start.
          </p>
          <textarea
            value={memory}
            onChange={(e) => setMemory(e.target.value)}
            rows={6}
            data-testid="easy-memory-text"
            placeholder="Example: I always wanted you to know how proud I am of your kindness…"
            className="w-full px-4 py-3 text-lg rounded-sm leading-relaxed"
            style={inputStyle}
          />
          <NavRow
            onBack={goBack}
            onNext={saveMemory}
            nextLabel={busy ? "Saving…" : "Save memory"}
            busy={busy}
            nextTestId="easy-memory-save"
          />
          <button type="button" onClick={skipMemory} className="text-sm underline" style={{ color: "var(--text-muted)" }} data-testid="easy-memory-skip">
            I&apos;ll add a memory later
          </button>
        </section>
      )}

      {step === 5 && (
        <section className="space-y-6" data-testid="easy-step-done">
          <div className="flex items-center gap-3">
            <CheckCircle2 className="h-8 w-8" style={{ color: "var(--accent)" }} />
            <h2 className="font-serif text-2xl sm:text-3xl font-light">You&apos;re set.</h2>
          </div>
          <p className="text-lg" style={{ color: "var(--text-secondary)" }}>
            The important pieces are in place. Come back anytime to add stories — that&apos;s what makes the twin sound like you.
          </p>
          <ul className="space-y-3">
            {(status.steps || []).map((s) => (
              <li key={s.id} className="flex items-center gap-3 text-base">
                <CheckCircle2
                  className="h-5 w-5 shrink-0"
                  style={{ color: s.done ? "var(--accent)" : "var(--border-default)" }}
                />
                <span style={{ color: s.done ? "var(--text-primary)" : "var(--text-muted)" }}>{s.title}</span>
              </li>
            ))}
          </ul>
          <BigButton onClick={() => navigate("/twin")} testId="easy-go-twin">
            Talk to your twin
          </BigButton>
          <BigButton onClick={() => navigate("/today")} testId="easy-go-today" secondary>
            Go to Today
          </BigButton>
        </section>
      )}
    </div>
  );
}

const inputStyle = {
  background: "var(--bg-base)",
  border: "1px solid var(--border-default)",
  color: "var(--text-primary)",
  fontSize: "18px", // avoid iOS zoom; easier to read
};

function Field({ label, value, onChange, testId, type = "text", multiline, placeholder, autoFocus }) {
  const shared = {
    value,
    onChange: (e) => onChange(e.target.value),
    "data-testid": testId,
    placeholder,
    autoFocus,
    className: "w-full px-4 py-3 text-lg rounded-sm",
    style: inputStyle,
  };
  return (
    <label className="block text-base">
      <span className="mb-2 block" style={{ color: "var(--text-secondary)" }}>{label}</span>
      {multiline ? <textarea rows={3} {...shared} /> : <input type={type} {...shared} />}
    </label>
  );
}

function BigButton({ children, onClick, testId, secondary, disabled }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      data-testid={testId}
      className="w-full px-5 py-4 text-lg rounded-sm disabled:opacity-50 inline-flex items-center justify-center gap-2"
      style={
        secondary
          ? { border: "1px solid var(--border-default)", color: "var(--text-primary)" }
          : { background: "var(--accent)", color: "var(--text-inverse)" }
      }
    >
      {children}
      {!secondary && <ArrowRight className="h-5 w-5" />}
    </button>
  );
}

function NavRow({ onBack, onNext, nextLabel, busy, nextTestId }) {
  return (
    <div className="flex flex-col sm:flex-row gap-3 pt-2">
      <button
        type="button"
        onClick={onBack}
        className="px-5 py-4 text-lg rounded-sm inline-flex items-center justify-center gap-2"
        style={{ border: "1px solid var(--border-default)", color: "var(--text-secondary)" }}
      >
        <ArrowLeft className="h-5 w-5" /> Back
      </button>
      <button
        type="button"
        onClick={onNext}
        disabled={busy}
        data-testid={nextTestId}
        className="flex-1 px-5 py-4 text-lg rounded-sm disabled:opacity-50 inline-flex items-center justify-center gap-2"
        style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
      >
        {busy ? <Loader2 className="h-5 w-5 animate-spin" /> : null}
        {nextLabel}
      </button>
    </div>
  );
}

function ChoiceCard({ title, body, onClick, testId, disabled }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      data-testid={testId}
      className="w-full text-left p-5 rounded-sm disabled:opacity-50 transition-opacity hover:opacity-90"
      style={{ border: "1px solid var(--border-default)", background: "var(--bg-surface)" }}
    >
      <div className="font-serif text-xl mb-2">{title}</div>
      <p className="text-base" style={{ color: "var(--text-secondary)" }}>{body}</p>
    </button>
  );
}
