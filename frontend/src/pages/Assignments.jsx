import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Loader2 } from "lucide-react";
import ApprovalCard from "../components/studio/ApprovalCard";
import { api } from "../lib/api";
import {
  PRESETS,
  assignmentHref,
  nextStatusLabels,
  presetPrefill,
  statusIsOpen,
  statusLabel,
} from "../lib/assignments";
import { connectorNotice } from "../lib/connectors";

export default function Assignments() {
  const { assignmentId } = useParams();
  if (assignmentId) return <AssignmentDetail assignmentId={assignmentId} />;
  return <AssignmentList />;
}

function AssignmentList() {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const { data } = await api.get("/assignments");
      setRows(data.assignments || []);
    } catch (err) {
      setError(err.response?.data?.detail || "Couldn't load assignments.");
      setRows([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="px-4 sm:px-8 lg:px-16 py-12 max-w-4xl" data-testid="assignments-root">
      <header className="mb-10 flex justify-between items-end gap-6">
        <div>
          <div className="overline mb-3">workspace</div>
          <h1 className="font-serif text-4xl lg:text-5xl font-light tracking-tight">
            Assignments
          </h1>
          <p className="mt-3 text-base max-w-xl" style={{ color: "var(--text-secondary)" }}>
            The twin takes a scoped job — or hands it to a clone — and reports back.
            Anything that would send, post, delete, or spend waits for you.
          </p>
        </div>
        <Link
          to="/assignments/new"
          data-testid="assignments-new-link"
          className="text-sm"
          style={{ color: "var(--accent)" }}
        >
          New assignment
        </Link>
      </header>
      {loading ? (
        <p className="inline-flex items-center gap-2 text-sm" style={{ color: "var(--text-muted)" }}>
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading
        </p>
      ) : null}
      {error ? <p className="text-sm" style={{ color: "var(--danger)" }}>{error}</p> : null}
      {!loading && !rows.length ? (
        <div className="surface p-8" data-testid="assignments-empty">
          <p className="font-serif text-xl">Nothing assigned yet.</p>
          <button
            type="button"
            className="mt-4 text-sm"
            style={{ color: "var(--accent)" }}
            onClick={() => navigate("/assignments/new")}
          >
            Start from a preset
          </button>
        </div>
      ) : null}
      <ul className="space-y-3">
        {rows.map((row) => (
          <li key={row.assignment_id}>
            <Link
              to={assignmentHref(row)}
              className="surface block p-5"
              data-testid={`assignment-row-${row.assignment_id}`}
            >
              <div className="flex justify-between gap-4">
                <span className="font-serif text-xl">{row.title || "Untitled"}</span>
                <span className="text-xs uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
                  {statusLabel(row.status)}
                </span>
              </div>
              {row.goal ? (
                <p className="mt-2 text-sm" style={{ color: "var(--text-secondary)" }}>
                  {row.goal}
                </p>
              ) : null}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function AssignmentNew() {
  const [preset, setPreset] = useState("blank");
  const [title, setTitle] = useState("");
  const [goal, setGoal] = useState("");
  const [scope, setScope] = useState("");
  const [autonomy, setAutonomy] = useState("draft");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [connectorStatus, setConnectorStatus] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    let cancelled = false;
    api.get("/connectors/status")
      .then(({ data }) => {
        if (!cancelled) setConnectorStatus(data);
      })
      .catch(() => {
        if (!cancelled) setConnectorStatus({ connectors: [] });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const applyPreset = (id) => {
    const filled = presetPrefill(id);
    setPreset(filled.preset);
    setTitle(filled.title);
    setGoal(filled.goal);
    setScope(filled.scope);
    setAutonomy(filled.autonomy);
  };

  const create = async () => {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const { data } = await api.post("/assignments", {
        preset: preset === "blank" ? undefined : preset,
        title,
        goal,
        scope,
        autonomy,
      });
      const id = data.assignment?.assignment_id;
      navigate(id ? assignmentHref(id) : "/assignments");
    } catch (err) {
      setError(err.response?.data?.detail || "Couldn't create the assignment.");
    } finally {
      setBusy(false);
    }
  };

  const mailbox = connectorNotice(preset, connectorStatus);

  return (
    <div className="px-4 sm:px-8 lg:px-16 py-12 max-w-4xl" data-testid="assignment-new">
      <header className="mb-8">
        <Link to="/assignments" className="text-xs" style={{ color: "var(--text-muted)" }}>
          Assignments
        </Link>
        <h1 className="font-serif text-4xl font-light mt-3">New assignment</h1>
      </header>
      <div className="flex flex-wrap gap-2 mb-6" data-testid="assignment-presets">
        {PRESETS.map((row) => (
          <button
            key={row.id}
            type="button"
            data-testid={`preset-${row.id}`}
            onClick={() => applyPreset(row.id)}
            className="px-3 py-1.5 text-sm rounded-sm"
            style={{
              border: "1px solid var(--border-default)",
              color: preset === row.id ? "var(--text-inverse)" : "var(--text-secondary)",
              background: preset === row.id ? "var(--accent)" : "transparent",
            }}
          >
            {row.label}
          </button>
        ))}
      </div>
      {mailbox.message ? (
        <p className="mb-4 text-sm" data-testid="assignment-connector-state" style={{ color: "var(--text-secondary)" }}>
          {mailbox.message}
        </p>
      ) : null}
      <div className="surface p-6 space-y-4">
        <Field label="Title" value={title} onChange={setTitle} testid="assignment-title" />
        <Field label="Goal" value={goal} onChange={setGoal} testid="assignment-goal" multiline />
        <Field label="Scope" value={scope} onChange={setScope} testid="assignment-scope" multiline />
        <label className="block text-sm">
          <span className="overline">Autonomy</span>
          <select
            value={autonomy}
            onChange={(e) => setAutonomy(e.target.value)}
            data-testid="assignment-autonomy"
            className="mt-2 block bg-transparent border px-2 py-1"
            style={{ borderColor: "var(--border-default)", color: "var(--text-primary)" }}
          >
            <option value="draft">Draft</option>
            <option value="act">Act</option>
          </select>
        </label>
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          Act still asks before it sends, posts, deletes, or spends.
        </p>
        {error ? <p className="text-sm" style={{ color: "var(--danger)" }}>{error}</p> : null}
        <button
          type="button"
          disabled={busy || (!title.trim() && !goal.trim())}
          onClick={create}
          data-testid="assignment-create"
          className="px-4 py-2 text-sm font-medium rounded-sm disabled:opacity-50"
          style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
        >
          {busy ? "Creating…" : "Create"}
        </button>
      </div>
    </div>
  );
}

function AssignmentDetail({ assignmentId }) {
  const [assignment, setAssignment] = useState(null);
  const [approvals, setApprovals] = useState([]);
  const [taskText, setTaskText] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setError("");
    try {
      const [{ data: detail }, { data: pending }] = await Promise.all([
        api.get(`/assignments/${assignmentId}`),
        api.get("/approvals", { params: { assignment_id: assignmentId, status: "all" } }),
      ]);
      setAssignment(detail.assignment);
      setApprovals(pending.approvals || []);
    } catch (err) {
      setError(err.response?.data?.detail || "Couldn't open that assignment.");
    }
  }, [assignmentId]);

  useEffect(() => {
    load();
  }, [load]);

  const decide = async (approval, path) => {
    setBusy(true);
    try {
      await api.post(`/approvals/${approval.approval_id}/${path}`);
      await load();
    } catch (err) {
      setError(err.response?.data?.detail || "Couldn't record that decision.");
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    setBusy(true);
    try {
      await api.post(`/assignments/${assignmentId}/cancel`);
      await load();
    } catch (err) {
      setError(err.response?.data?.detail || "Couldn't cancel.");
    } finally {
      setBusy(false);
    }
  };

  const addTask = async () => {
    const text = taskText.trim();
    if (!text) return;
    setBusy(true);
    try {
      await api.post(`/assignments/${assignmentId}/tasks`, { text });
      setTaskText("");
      await load();
    } catch (err) {
      setError(err.response?.data?.detail || "Couldn't add the task.");
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (taskId) => {
    setBusy(true);
    try {
      await api.post(`/assignments/${assignmentId}/tasks/${taskId}/toggle`);
      await load();
    } catch (err) {
      setError(err.response?.data?.detail || "Couldn't update the task.");
    } finally {
      setBusy(false);
    }
  };

  if (!assignment && !error) {
    return (
      <div className="px-4 sm:px-8 lg:px-16 py-12" data-testid="assignment-detail">
        <Loader2 className="h-4 w-4 animate-spin" />
      </div>
    );
  }

  return (
    <div className="px-4 sm:px-8 lg:px-16 py-12 max-w-4xl" data-testid="assignment-detail">
      <Link to="/assignments" className="text-xs" style={{ color: "var(--text-muted)" }}>
        Assignments
      </Link>
      {error ? <p className="mt-4 text-sm" style={{ color: "var(--danger)" }}>{error}</p> : null}
      {assignment ? (
        <>
          <header className="mt-3 mb-8">
            <div className="overline mb-2" data-testid="assignment-status">
              {statusLabel(assignment.status)}
            </div>
            <h1 className="font-serif text-4xl font-light">{assignment.title || "Untitled"}</h1>
            <p className="mt-3 text-base" style={{ color: "var(--text-secondary)" }}>
              {assignment.goal}
            </p>
            {assignment.scope ? (
              <p className="mt-2 text-sm" style={{ color: "var(--text-muted)" }}>
                Scope: {assignment.scope}
              </p>
            ) : null}
            <p className="mt-2 text-xs" style={{ color: "var(--text-muted)" }} data-testid="assignment-next">
              {nextStatusLabels(assignment.status).length
                ? `Can move to ${nextStatusLabels(assignment.status).join(", ")}`
                : "Closed"}
              {assignment.clone_id ? ` · Clone ${assignment.clone_id}` : " · Twin"}
              {` · ${assignment.autonomy || "draft"}`}
            </p>
            {statusIsOpen(assignment.status) ? (
              <button
                type="button"
                onClick={cancel}
                disabled={busy}
                data-testid="assignment-cancel"
                className="mt-4 text-sm"
                style={{ color: "var(--text-secondary)" }}
              >
                Cancel
              </button>
            ) : null}
          </header>

          <div className="space-y-4 mb-10">
            {approvals.filter((row) => row.status === "pending").map((row) => (
              <ApprovalCard
                key={row.approval_id}
                approval={row}
                busy={busy}
                testid={`approval-${row.approval_id}`}
                onApprove={(item) => decide(item, "approve")}
                onDecline={(item) => decide(item, "decline")}
              />
            ))}
          </div>

          <section className="mb-10" data-testid="assignment-tasks">
            <div className="overline mb-3">Tasks</div>
            {(assignment.tasks || []).length ? (
              <ul className="space-y-2">
                {assignment.tasks.map((task) => (
                  <li key={task.task_id}>
                    <button
                      type="button"
                      onClick={() => toggle(task.task_id)}
                      data-testid={`task-${task.task_id}`}
                      className="text-left text-sm"
                      style={{ color: task.done ? "var(--text-muted)" : "var(--text-primary)" }}
                    >
                      {task.done ? "Done · " : "Open · "}
                      {task.text}
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm" style={{ color: "var(--text-muted)" }}>No checklist yet.</p>
            )}
            {assignment.status !== "cancelled" ? (
              <div className="mt-3 flex gap-2">
                <input
                  value={taskText}
                  onChange={(e) => setTaskText(e.target.value)}
                  data-testid="task-input"
                  className="flex-1 bg-transparent border px-2 py-1 text-sm"
                  style={{ borderColor: "var(--border-default)", color: "var(--text-primary)" }}
                  placeholder="Add a step"
                />
                <button type="button" onClick={addTask} data-testid="task-add" className="text-sm" style={{ color: "var(--accent)" }}>
                  Add
                </button>
              </div>
            ) : null}
          </section>

          <section className="mb-10" data-testid="assignment-artifacts">
            <div className="overline mb-3">Artifacts</div>
            {(assignment.artifacts || []).length ? (
              assignment.artifacts.map((artifact, index) => (
                <article key={`${artifact.name}-${index}`} className="surface p-4 mb-3">
                  <div className="text-xs uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
                    {artifact.kind} · {artifact.name}
                  </div>
                  {artifact.text ? (
                    <pre className="mt-2 whitespace-pre-wrap text-sm font-sans" style={{ color: "var(--text-secondary)" }}>
                      {artifact.text}
                    </pre>
                  ) : null}
                  {artifact.ref ? (
                    <p className="mt-2 text-xs" style={{ color: "var(--text-muted)" }}>{artifact.ref}</p>
                  ) : null}
                </article>
              ))
            ) : (
              <p className="text-sm" style={{ color: "var(--text-muted)" }}>No artifacts yet.</p>
            )}
          </section>

          <section data-testid="assignment-log">
            <div className="overline mb-3">Log</div>
            <ul className="space-y-2">
              {(assignment.log || []).map((line, index) => (
                <li key={`${line.ts}-${index}`} className="text-sm" style={{ color: "var(--text-secondary)" }}>
                  <span style={{ color: "var(--text-muted)" }}>{line.ts} </span>
                  {line.line}
                </li>
              ))}
            </ul>
          </section>
        </>
      ) : null}
    </div>
  );
}

function Field({ label, value, onChange, testid, multiline = false }) {
  const shared = {
    value,
    onChange: (e) => onChange(e.target.value),
    "data-testid": testid,
    className: "mt-2 w-full bg-transparent border px-2 py-1 text-sm",
    style: { borderColor: "var(--border-default)", color: "var(--text-primary)" },
  };
  return (
    <label className="block text-sm">
      <span className="overline">{label}</span>
      {multiline ? <textarea rows={3} {...shared} /> : <input {...shared} />}
    </label>
  );
}
