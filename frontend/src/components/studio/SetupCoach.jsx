import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { X } from "lucide-react";
import { api } from "../../lib/api";
import { TWIN_SETUP_CHANGED, coachShouldShow } from "../../lib/twinSetup";
import { SetupExampleArt } from "./SetupIllustrations";

/**
 * Persistent but dismissible Twin setup reminder. Top-right of the studio
 * shell. Does not block the rest of the app. Reopen from Help.
 */
export default function SetupCoach({ reopenSignal = 0 }) {
  const navigate = useNavigate();
  const [progress, setProgress] = useState(null);
  const [youreSet, setYoureSet] = useState(false);
  const [forceOpen, setForceOpen] = useState(false);
  const sawIncomplete = useRef(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/studio/first-run/progress");
      setProgress(data);
      if (data?.all_critical_done && sawIncomplete.current) {
        setYoureSet(true);
        setForceOpen(false);
        window.setTimeout(() => setYoureSet(false), 4200);
      }
      sawIncomplete.current = Boolean(data && !data.all_critical_done);
      return data;
    } catch {
      return null;
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const onChange = () => load();
    window.addEventListener(TWIN_SETUP_CHANGED, onChange);
    window.addEventListener("focus", onChange);
    return () => {
      window.removeEventListener(TWIN_SETUP_CHANGED, onChange);
      window.removeEventListener("focus", onChange);
    };
  }, [load]);

  useEffect(() => {
    if (!reopenSignal) return;
    setForceOpen(true);
    api.put("/studio/first-run", { coach_dismissed: false }).then(load).catch(() => load());
  }, [reopenSignal, load]);

  const dismiss = async () => {
    setForceOpen(false);
    if (progress?.all_critical_done) {
      setYoureSet(false);
      return;
    }
    setProgress((p) => (p ? { ...p, coach_dismissed: true, visible: false } : p));
    try {
      await api.put("/studio/first-run", { coach_dismissed: true });
    } catch {
      /* local hide still stands */
    }
  };

  const remaining = (progress?.steps || []).filter((s) => s.critical && !s.done);
  const showSet = youreSet && progress?.all_critical_done;
  const showList = forceOpen || coachShouldShow(progress, { dismissedOverride: forceOpen ? false : undefined });

  if (!showSet && !showList) return null;

  return (
    <aside className="setup-coach" data-testid="setup-coach" aria-label="Twin setup remaining">
      <header className="setup-coach-titlebar">
        <div>
          <p className="setup-coach-overline">Twin setup</p>
          <h2>{showSet ? "You’re set" : "Still to do"}</h2>
        </div>
        <button
          type="button"
          className="setup-coach-close"
          aria-label="Close setup reminder"
          data-testid="setup-coach-close"
          onClick={dismiss}
        >
          <X className="h-4 w-4" />
        </button>
      </header>
      {showSet ? (
        <p className="setup-coach-body">
          Voice and likeness are on file. The Twin can sound and look like you — live sit, video,
          and a room sit.
        </p>
      ) : (
        <ul className="setup-coach-list">
          {remaining.map((step) => {
            const ex = (step.examples || [])[0];
            return (
              <li key={step.id} data-testid={`setup-coach-step-${step.id}`}>
                <button type="button" className="setup-coach-step" onClick={() => navigate(step.href)}>
                  {ex ? <SetupExampleArt exampleId={ex.id} /> : null}
                  <div>
                    <strong>{step.label}</strong>
                    <span>
                      {step.id === "likeness"
                        ? `${step.have} of ${step.needed} photos`
                        : step.benefit}
                    </span>
                    <em>{step.cta}</em>
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {!showSet ? (
        <p className="setup-coach-hint">Help → Remaining setup if you close this.</p>
      ) : null}
    </aside>
  );
}
