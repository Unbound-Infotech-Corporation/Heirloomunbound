import { createPortal } from "react-dom";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { api } from "../../lib/api";

/**
 * Stay-on-top coach: Heirloom opens official pages from a click (popup-safe)
 * and pauses with copy/paste hints. On the dedicated PC, after models install,
 * the desktop guide watches the screen. Humans click Create account / I'm not
 * a robot / Verify. We never drive vendor DOM, solve captchas, or scrape keys.
 */
export function signupUrlWithEmail(url, email, param) {
  if (!url || !email || !param) return url;
  try {
    const next = new URL(url);
    next.searchParams.set(param, email);
    return next.toString();
  } catch {
    return url;
  }
}

function copyText(value) {
  if (!value) return;
  navigator.clipboard.writeText(value).then(
    () => toast.success(`Copied ${value}`),
    () => toast.message("Copy the email yourself if paste is blocked")
  );
}

export function stepOpenUrl(svc, step, email) {
  if (!step) return "";
  if (step.id === "create_account") {
    return signupUrlWithEmail(
      step.open_url || svc?.signup_url,
      email,
      svc?.email_query_param || "email"
    );
  }
  return step.open_url || "";
}

export function openCoachStep(svc, step, email) {
  try {
    if (step?.copy) copyText(step.copy);
    const url = stepOpenUrl(svc, step, email);
    if (step?.auto_open && url) {
      window.open(url, "_blank", "noopener,noreferrer");
    }
    return url;
  } catch {
    return "";
  }
}

function fallbackSteps(svc, email) {
  const inboxHost =
    (email || "").includes("@gmail.") || (email || "").includes("@googlemail.")
      ? { label: "Gmail", url: "https://mail.google.com/mail/u/0/#inbox" }
      : { label: "your email inbox", url: "" };
  return [
    {
      id: "create_account",
      kind: "pause",
      title: `Create your ${svc.label} account`,
      body: "Their official sign-up page is open. Click Create account, paste your email if the box is empty, then click I'm not a robot.",
      bullets: svc.create_account_bullets || svc.you_do || [],
      copy: email,
      open_url: svc.signup_url,
      auto_open: true,
      cta: "I signed up (and clicked I'm not a robot)",
    },
    {
      id: "verify_email",
      kind: "pause",
      title: `Verify in ${inboxHost.label}`,
      body: inboxHost.url
        ? `We opened ${inboxHost.label}. Find the message from ${svc.label} and click Verify.`
        : `Open the inbox for ${email || "your email"} and click the verify link.`,
      bullets: [email ? `Look for mail to ${email}.` : "Use the same email you just typed."],
      open_url: inboxHost.url,
      auto_open: Boolean(inboxHost.url),
      cta: "I verified the email",
      skip_cta: "Skip — already verified",
    },
    {
      id: "find_key",
      kind: "pause",
      title: `Get the ${svc.label} API key`,
      body: svc.key_where || "Open their API keys page and copy a key.",
      bullets: [svc.key_what || "Copy the secret, then continue."],
      open_url: svc.dashboard_url,
      auto_open: true,
      cta: "I'm on the API keys page",
    },
    {
      id: "paste_key",
      kind: "paste",
      title: "Paste the key into Heirloom",
      body: "This box stays in Heirloom. After it saves, the guide moves to the next vendor.",
      bullets: [svc.key_what || "Paste the secret you copied."],
      placeholder: svc.placeholder,
      cta: "Verify & save",
    },
  ];
}

function CoachCard({ children }) {
  if (typeof document === "undefined") return children;
  return createPortal(children, document.body);
}

export default function VendorCoach({
  services,
  email,
  onSaved,
  onPersistEmail,
  onDone,
}) {
  const [queue] = useState(() =>
    (services || [])
      .filter((svc) => svc && !svc.alreadySaved)
      .map((svc) => ({
        ...svc,
        coach_steps: svc.coach_steps?.length ? svc.coach_steps : fallbackSteps(svc, email),
      }))
  );
  const [svcIdx, setSvcIdx] = useState(0);
  const [stepIdx, setStepIdx] = useState(0);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const persistRef = useRef(onPersistEmail);
  persistRef.current = onPersistEmail;

  const svc = queue[svcIdx];
  const steps = svc?.coach_steps || [];
  const step = steps[stepIdx];

  if (!queue.length) {
    return (
      <CoachCard>
        <aside className="studio-coach" data-testid="vendor-coach">
          <p className="studio-coach-overline">Cloud keys</p>
          <h2>All vendor keys are saved</h2>
          <p className="studio-coach-body">Local Whisper and Ollama do not need these.</p>
          <button type="button" className="studio-btn studio-btn-primary" onClick={onDone}>
            Close guide
          </button>
        </aside>
      </CoachCard>
    );
  }

  if (!svc || !step) return null;

  const peekNext = () => {
    if (stepIdx + 1 < steps.length) {
      return { nextSvc: svc, nextStep: steps[stepIdx + 1], nextSvcIdx: svcIdx, nextStepIdx: stepIdx + 1 };
    }
    if (svcIdx + 1 < queue.length) {
      const nextSvc = queue[svcIdx + 1];
      return {
        nextSvc,
        nextStep: (nextSvc.coach_steps || [])[0],
        nextSvcIdx: svcIdx + 1,
        nextStepIdx: 0,
      };
    }
    return null;
  };

  const go = (next) => {
    setDraft("");
    if (!next) {
      onDone?.();
      return;
    }
    setSvcIdx(next.nextSvcIdx);
    setStepIdx(next.nextStepIdx);
  };

  const continueNow = () => {
    persistRef.current?.();
    const next = peekNext();
    if (next?.nextStep) openCoachStep(next.nextSvc, next.nextStep, email);
    go(next);
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
      const next = peekNext();
      go(next);
      if (next?.nextSvc) {
        toast.message(`Next: ${next.nextSvc.label} — click Re-open page`);
      }
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Key was rejected");
    } finally {
      setBusy(false);
    }
  };

  const reopen = () => {
    openCoachStep(svc, step, email);
  };

  return (
    <CoachCard>
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
            onClick={continueNow}
            data-testid="vendor-coach-continue"
          >
            {step.cta || "Continue"}
          </button>
        )}

        <p className="studio-coach-watch">
          {step.kind === "paste"
            ? "Paste the key here. Heirloom never copies it from a screenshot."
            : "Screen watch runs in the dedicated PC app after models install. Continue still works here."}
        </p>

        <div className="studio-coach-actions">
          {stepOpenUrl(svc, step, email) ? (
            <button type="button" className="studio-btn" onClick={reopen} data-testid="vendor-coach-reopen">
              Re-open page
            </button>
          ) : null}
          {step.skip_cta ? (
            <button type="button" className="studio-btn" onClick={continueNow}>
              {step.skip_cta}
            </button>
          ) : null}
        </div>
      </aside>
    </CoachCard>
  );
}
