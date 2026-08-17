import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { api } from "../../lib/api";

/**
 * Stay-on-top coach: Heirloom opens official pages and pauses with copy/paste
 * hints. Humans click Create account / I'm not a robot / Verify. We never
 * drive vendor DOM or solve captchas.
 */
function signupUrlWithEmail(url, email, param) {
  if (!url || !email || !param) return url;
  try {
    const next = new URL(url);
    next.searchParams.set(param, email);
    return next.toString();
  } catch {
    return url;
  }
}

async function copyText(value) {
  if (!value) return;
  try {
    await navigator.clipboard.writeText(value);
    toast.success(`Copied ${value}`);
  } catch {
    toast.message("Copy the email yourself if paste is blocked");
  }
}

export default function VendorCoach({
  services,
  email,
  onSaved,
  onPersistEmail,
  onDone,
}) {
  const [queue] = useState(() => (services || []).filter((svc) => svc && !svc.alreadySaved));
  const [svcIdx, setSvcIdx] = useState(0);
  const [stepIdx, setStepIdx] = useState(0);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const openedKey = useRef("");
  const persistRef = useRef(onPersistEmail);
  persistRef.current = onPersistEmail;

  const svc = queue[svcIdx];
  const steps = svc?.coach_steps || [];
  const step = steps[stepIdx];

  useEffect(() => {
    if (!svc || !step) return;
    const key = `${svc.id}:${step.id}`;
    if (openedKey.current === key) return;
    openedKey.current = key;
    const run = async () => {
      await persistRef.current?.();
      if (step.copy) await copyText(step.copy);
      const url =
        step.id === "create_account"
          ? signupUrlWithEmail(step.open_url || svc.signup_url, email, svc.email_query_param || "email")
          : step.open_url;
      if (step.auto_open && url) {
        window.open(url, "_blank", "noopener,noreferrer");
      }
    };
    run();
  }, [svc, step, email]);

  if (!queue.length) {
    return (
      <aside className="studio-coach" data-testid="vendor-coach">
        <p className="studio-coach-overline">Cloud keys</p>
        <h2>All vendor keys are saved</h2>
        <p className="studio-coach-body">Local Whisper and Ollama do not need these.</p>
        <button type="button" className="studio-btn studio-btn-primary" onClick={onDone}>
          Close guide
        </button>
      </aside>
    );
  }

  if (!svc || !step) return null;

  const advance = () => {
    setDraft("");
    if (stepIdx + 1 < steps.length) {
      setStepIdx(stepIdx + 1);
      return;
    }
    const nextSvc = svcIdx + 1;
    if (nextSvc < queue.length) {
      setSvcIdx(nextSvc);
      setStepIdx(0);
      openedKey.current = "";
      return;
    }
    onDone?.();
  };

  const verifySave = async () => {
    const key = draft.trim();
    if (!key) {
      toast.error("Paste the API key from their dashboard");
      return;
    }
    setBusy(true);
    try {
      await api.post("/user-keys/verify", { service: svc.verify_service, api_key: key });
      await api.put(svc.save_path, { api_key: key });
      toast.success(`${svc.label} saved`);
      setDraft("");
      onSaved?.();
      const nextSvc = svcIdx + 1;
      if (nextSvc < queue.length) {
        setSvcIdx(nextSvc);
        setStepIdx(0);
        openedKey.current = "";
      } else {
        onDone?.();
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Key was rejected");
    } finally {
      setBusy(false);
    }
  };

  const reopen = () => {
    const url =
      step.id === "create_account"
        ? signupUrlWithEmail(step.open_url || svc.signup_url, email, svc.email_query_param || "email")
        : step.open_url;
    if (url) window.open(url, "_blank", "noopener,noreferrer");
  };

  return (
    <aside className="studio-coach" data-testid="vendor-coach">
      <div className="studio-coach-titlebar">
        <p className="studio-coach-overline">
          {svc.label} · {svcIdx + 1} of {queue.length} · step {stepIdx + 1} of {steps.length}
        </p>
        <button type="button" className="studio-coach-x" onClick={onDone} aria-label="Close guide">
          ×
        </button>
      </div>
      <h2 data-testid="vendor-coach-title">{step.title}</h2>
      <p className="studio-coach-body">{step.body}</p>
      {step.bullets?.length ? (
        <ol className="studio-coach-bullets">
          {step.bullets.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ol>
      ) : null}

      {step.kind === "paste" ? (
        <>
          <input
            type="password"
            className="studio-coach-input"
            placeholder={step.placeholder || svc.placeholder}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            data-testid={`setup-key-${svc.id}`}
          />
          <button
            type="button"
            className="studio-btn studio-btn-primary"
            disabled={busy}
            onClick={verifySave}
            data-testid="vendor-coach-save"
          >
            {busy ? "Saving…" : step.cta || "Verify & save"}
          </button>
        </>
      ) : (
        <button
          type="button"
          className="studio-btn studio-btn-primary"
          onClick={advance}
          data-testid="vendor-coach-continue"
        >
          {step.cta || "Continue"}
        </button>
      )}

      <div className="studio-coach-actions">
        {step.open_url ? (
          <button type="button" className="studio-btn" onClick={reopen}>
            Re-open page
          </button>
        ) : null}
        {step.skip_cta ? (
          <button type="button" className="studio-btn" onClick={advance}>
            {step.skip_cta}
          </button>
        ) : null}
      </div>
    </aside>
  );
}
