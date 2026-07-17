import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  Bell,
  Check,
  ChevronRight,
  CircleDot,
  Loader2,
  Monitor,
  Play,
  Sparkles,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { usePageMeta } from "@/lib/usePageMeta";

// Focus Mode — the user states a goal, the twin plans steps, they approve,
// the companion executes. This is the front door for autonomous multi-step
// actions across the owner's Abilities.

const STATUS_COLORS = {
  pending_approval: "var(--warning, #d69663)",
  running: "var(--accent)",
  completed: "var(--success, #4c9a6a)",
  failed: "var(--danger, #b6543f)",
  cancelled: "var(--text-muted)",
};

const STATUS_LABELS = {
  pending_approval: "waiting for you",
  running: "running",
  completed: "done",
  failed: "failed",
  cancelled: "cancelled",
};

const STEP_ICON = {
  pending: CircleDot,
  approved: CircleDot,
  running: Loader2,
  done: Check,
  failed: X,
  rejected: X,
  skipped: X,
};

function relativeTime(iso) {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  const s = Math.max(1, Math.round((Date.now() - t) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

function StepRow({ step, onReject, disabled }) {
  const Icon = STEP_ICON[step.status] || CircleDot;
  const spinning = step.status === "running";
  const dim = step.status === "rejected" || step.status === "skipped";
  const failed = step.status === "failed";
  return (
    <div
      className="flex items-start gap-3 py-3"
      data-testid={`agent-step-${step.order}`}
      style={{ borderTop: "1px solid var(--border-default)", opacity: dim ? 0.55 : 1 }}
    >
      <div className="mt-0.5">
        <Icon
          className={`h-4 w-4 ${spinning ? "animate-spin" : ""}`}
          style={{
            color:
              step.status === "done"
                ? "var(--success, #4c9a6a)"
                : failed
                  ? "var(--danger, #b6543f)"
                  : step.status === "running"
                    ? "var(--accent)"
                    : "var(--text-muted)",
          }}
        />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm" style={{ color: "var(--text-primary)" }}>
            {step.description}
          </span>
          {step.kind === "companion" && (
            <span
              className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded-sm inline-flex items-center gap-1"
              style={{
                color: "var(--text-muted)",
                border: "1px solid var(--border-default)",
              }}
            >
              <Monitor className="h-3 w-3" />
              {step.companion_kind}
            </span>
          )}
          {step.kind === "notify" && (
            <span
              className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded-sm inline-flex items-center gap-1"
              style={{ color: "var(--text-muted)", border: "1px solid var(--border-default)" }}
            >
              <Bell className="h-3 w-3" />
              note
            </span>
          )}
        </div>
        {step.result && (step.status === "done" || failed) && (
          <div
            className="text-xs mt-1 font-mono whitespace-pre-wrap"
            style={{ color: failed ? "var(--danger, #b6543f)" : "var(--text-muted)" }}
          >
            {step.result}
          </div>
        )}
        {step.kind === "notify" && step.message && step.status !== "done" && (
          <div className="text-xs italic mt-1" style={{ color: "var(--text-muted)" }}>
            “{step.message}”
          </div>
        )}
      </div>
      {(step.status === "pending" || step.status === "approved") && !disabled && (
        <button
          type="button"
          onClick={() => onReject(step.step_id)}
          data-testid={`agent-step-reject-${step.order}`}
          className="text-xs px-2 py-1 rounded-sm"
          style={{ color: "var(--text-muted)", border: "1px solid var(--border-default)" }}
          title="Skip this step"
        >
          skip
        </button>
      )}
    </div>
  );
}

function RunCard({ run, onApprove, onCancel, onReject, isActive }) {
  const pendingCount = run.steps.filter((s) => s.status === "pending").length;
  const doneCount = run.steps.filter((s) => s.status === "done").length;
  const busy = run.status === "running";
  const canApprove = run.status === "pending_approval" && pendingCount > 0;

  return (
    <div className="surface p-6" data-testid={`agent-run-${run.run_id}`}>
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          <div className="overline mb-1">
            {STATUS_LABELS[run.status] || run.status} · {relativeTime(run.created_at)}
          </div>
          <h3 className="font-serif text-2xl leading-tight" style={{ color: "var(--text-primary)" }}>
            {run.goal}
          </h3>
        </div>
        <span
          className="text-[10px] uppercase tracking-widest px-2 py-1 rounded-sm shrink-0"
          style={{
            color: STATUS_COLORS[run.status] || "var(--text-muted)",
            border: `1px solid ${STATUS_COLORS[run.status] || "var(--border-default)"}`,
          }}
        >
          {doneCount}/{run.steps.length}
        </span>
      </div>

      <div className="mt-4">
        {run.steps.map((s) => (
          <StepRow key={s.step_id} step={s} onReject={onReject} disabled={!isActive || busy} />
        ))}
      </div>

      {isActive && (canApprove || busy || run.status === "pending_approval") && (
        <div className="mt-5 flex flex-wrap gap-3">
          {canApprove && (
            <button
              type="button"
              onClick={onApprove}
              data-testid="agent-approve"
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-sm text-sm font-medium"
              style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
            >
              <Play className="h-4 w-4" /> Approve & run ({pendingCount})
            </button>
          )}
          {(canApprove || busy) && (
            <button
              type="button"
              onClick={onCancel}
              data-testid="agent-cancel"
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-sm text-sm"
              style={{ color: "var(--text-muted)", border: "1px solid var(--border-default)" }}
            >
              <X className="h-4 w-4" /> Cancel
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default function Agent() {
  usePageMeta({
    title: "Focus Mode · Heirloom",
    description: "Give your twin a goal — it makes a plan, you approve, it does the work.",
  });

  const [goal, setGoal] = useState("");
  const [planning, setPlanning] = useState(false);
  const [activeRun, setActiveRun] = useState(null);
  const [runs, setRuns] = useState([]);
  const [companionInfo, setCompanionInfo] = useState({ companion_connected: false });
  const pollRef = useRef(null);

  const loadRuns = useCallback(async () => {
    try {
      const { data } = await api.get("/agent/runs");
      setRuns(data.runs || []);
      if (!activeRun && data.runs?.length) {
        const first = data.runs[0];
        if (["running", "pending_approval"].includes(first.status)) {
          setActiveRun(first);
        }
      }
    } catch (e) {
      // silent — page still usable
    }
  }, [activeRun]);

  useEffect(() => {
    api.get("/agent/kinds").then(({ data }) => setCompanionInfo(data)).catch(() => {});
    loadRuns();
  }, [loadRuns]);

  // Poll the active run while it's live
  useEffect(() => {
    if (!activeRun) return undefined;
    if (!["running", "pending_approval"].includes(activeRun.status)) return undefined;
    const tick = async () => {
      try {
        const { data } = await api.get(`/agent/runs/${activeRun.run_id}`);
        setActiveRun(data);
        if (!["running", "pending_approval"].includes(data.status)) {
          loadRuns();
        }
      } catch (e) {
        // ignore transient
      }
    };
    pollRef.current = setInterval(tick, activeRun.status === "running" ? 1500 : 4000);
    return () => clearInterval(pollRef.current);
  }, [activeRun, loadRuns]);

  const plan = async () => {
    const g = goal.trim();
    if (g.length < 3) {
      toast.error("Give it a bit more detail.");
      return;
    }
    setPlanning(true);
    try {
      const { data } = await api.post("/agent/runs", { goal: g });
      setActiveRun(data);
      setGoal("");
      loadRuns();
      toast.success("Plan is ready — review and approve.");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't plan that. Try rephrasing.");
    } finally {
      setPlanning(false);
    }
  };

  const approve = async () => {
    if (!activeRun) return;
    try {
      const { data } = await api.post(`/agent/runs/${activeRun.run_id}/approve`, {});
      setActiveRun(data);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't approve.");
    }
  };

  const cancel = async () => {
    if (!activeRun) return;
    try {
      await api.post(`/agent/runs/${activeRun.run_id}/cancel`, {});
      const { data } = await api.get(`/agent/runs/${activeRun.run_id}`);
      setActiveRun(data);
      loadRuns();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't cancel.");
    }
  };

  const reject = async (stepId) => {
    if (!activeRun) return;
    try {
      const { data } = await api.post(`/agent/runs/${activeRun.run_id}/steps/${stepId}/reject`, {});
      setActiveRun(data);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't skip that step.");
    }
  };

  const suggestions = [
    "Wind down for the night — dim it, play something calm, set a 7am reminder.",
    "Open Spotify and cue up my focus playlist.",
    "Take a screenshot of my desktop and tell me what's on it.",
    "Lock my PC and speak “heading out” aloud.",
  ];

  const hasHistory = runs.length > 0;
  const showActive = activeRun && (["running", "pending_approval"].includes(activeRun.status) || activeRun.status === "completed");

  return (
    <div className="px-4 sm:px-8 lg:px-16 py-12 max-w-4xl" data-testid="agent-root">
      <header className="mb-10">
        <div className="overline mb-3 flex items-center gap-2">
          <Sparkles className="h-3 w-3" /> focus mode
        </div>
        <h1 className="font-serif text-4xl lg:text-5xl font-light tracking-tight">
          One goal, many steps.
        </h1>
        <p className="mt-3 text-base max-w-2xl" style={{ color: "var(--text-secondary)" }}>
          Tell your twin what you&apos;re trying to do. It&apos;ll break it into a plan, you approve
          the whole thing at a glance, and it does the work through your PC companion.
        </p>
      </header>

      {!companionInfo.companion_connected && (
        <div
          className="rounded-sm p-4 mb-8 flex items-start gap-3"
          style={{ background: "rgba(214,150,99,0.08)", border: "1px solid rgba(214,150,99,0.3)" }}
          data-testid="agent-companion-warning"
        >
          <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" style={{ color: "var(--warning, #d69663)" }} />
          <div className="text-sm">
            <span style={{ color: "var(--text-primary)" }}>No PC companion connected.</span>{" "}
            <span style={{ color: "var(--text-secondary)" }}>
              Focus Mode can still plan and take notes, but it can&apos;t touch your computer yet.{" "}
            </span>
            <Link to="/companion" className="underline" style={{ color: "var(--accent)" }}>
              Set it up →
            </Link>
          </div>
        </div>
      )}

      <div className="surface p-6 mb-10">
        <label
          htmlFor="agent-goal"
          className="text-sm block mb-2"
          style={{ color: "var(--text-primary)" }}
        >
          What would you like your twin to do?
        </label>
        <textarea
          id="agent-goal"
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          rows={3}
          data-testid="agent-goal-input"
          disabled={planning}
          className="w-full px-3 py-2 text-sm rounded-sm resize-none"
          style={{
            background: "var(--bg-base)",
            border: "1px solid var(--border-default)",
            color: "var(--text-primary)",
          }}
          placeholder="e.g. 'Wind me down for the night — dim it, queue something calm, remind me to journal in the morning.'"
        />
        <div className="flex items-center justify-between gap-3 mt-3 flex-wrap">
          <div className="flex flex-wrap gap-2">
            {suggestions.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setGoal(s)}
                disabled={planning}
                className="text-xs px-2.5 py-1 rounded-sm"
                style={{ color: "var(--text-muted)", border: "1px solid var(--border-default)" }}
                data-testid="agent-suggestion"
              >
                {s.split(" — ")[0]}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={plan}
            disabled={planning || goal.trim().length < 3}
            data-testid="agent-plan-button"
            className="inline-flex items-center gap-2 px-6 py-2.5 rounded-sm text-sm font-medium disabled:opacity-50"
            style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
          >
            {planning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            {planning ? "planning…" : "Plan it"}
          </button>
        </div>
      </div>

      {showActive && (
        <div className="mb-10" data-testid="agent-active-run">
          <div className="overline mb-3">current plan</div>
          <RunCard
            run={activeRun}
            onApprove={approve}
            onCancel={cancel}
            onReject={reject}
            isActive
          />
        </div>
      )}

      {hasHistory && (
        <div>
          <div className="overline mb-4">recent</div>
          <div className="space-y-3">
            {runs
              .filter((r) => !activeRun || r.run_id !== activeRun.run_id)
              .slice(0, 8)
              .map((r) => (
                <button
                  key={r.run_id}
                  type="button"
                  onClick={() => setActiveRun(r)}
                  data-testid={`agent-history-${r.run_id}`}
                  className="w-full text-left p-4 rounded-sm flex items-start justify-between gap-3 transition-colors hover:bg-[var(--bg-surface)]"
                  style={{ border: "1px solid var(--border-default)" }}
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-sm truncate" style={{ color: "var(--text-primary)" }}>
                      {r.goal}
                    </div>
                    <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                      {STATUS_LABELS[r.status] || r.status} · {r.steps.length} step{r.steps.length === 1 ? "" : "s"} ·{" "}
                      {relativeTime(r.created_at)}
                    </div>
                  </div>
                  <ChevronRight className="h-4 w-4 shrink-0 mt-1" style={{ color: "var(--text-muted)" }} />
                </button>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}
