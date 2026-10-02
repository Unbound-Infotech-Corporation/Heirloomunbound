"""Assignments v1 — scoped background jobs the Twin or a Clone reports back on.

Approvals gate anything that would leave Heirloom (send, post, delete, spend).
``autonomy=act`` on a Clone or on the assignment does not bypass that gate.
Connectors are an interface plus an in-memory fake. No real email, calendar,
or Slack.

Pure: no Mongo, no clock, no network. Callers pass ``now`` and a store.
"""
from __future__ import annotations

import json
import re
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Optional, Protocol, Sequence

from assistants import clone_autonomy
from owner_pairing import is_owner_audience

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_NEEDS_APPROVAL = "needs_approval"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

STATUSES = frozenset({
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_NEEDS_APPROVAL,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_CANCELLED,
})

TERMINAL_STATUSES = frozenset({STATUS_DONE, STATUS_FAILED, STATUS_CANCELLED})

# Legal moves. Terminal statuses have nowhere to go.
LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    STATUS_QUEUED: frozenset({STATUS_RUNNING, STATUS_CANCELLED}),
    STATUS_RUNNING: frozenset({
        STATUS_NEEDS_APPROVAL,
        STATUS_DONE,
        STATUS_FAILED,
        STATUS_CANCELLED,
    }),
    STATUS_NEEDS_APPROVAL: frozenset({STATUS_DONE, STATUS_FAILED, STATUS_CANCELLED}),
    STATUS_DONE: frozenset(),
    STATUS_FAILED: frozenset(),
    STATUS_CANCELLED: frozenset(),
}

AUTONOMY_DRAFT = "draft"
AUTONOMY_ACT = "act"
ASSIGNMENT_AUTONOMY = frozenset({AUTONOMY_DRAFT, AUTONOMY_ACT})

APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"
APPROVAL_DECLINED = "declined"
APPROVAL_EXPIRED = "expired"
APPROVAL_STATUSES = frozenset({
    APPROVAL_PENDING,
    APPROVAL_APPROVED,
    APPROVAL_DECLINED,
    APPROVAL_EXPIRED,
})
APPROVAL_FINAL = frozenset({APPROVAL_DECLINED, APPROVAL_EXPIRED})

# Leaves Heirloom or spends as the owner. Never auto-executed.
OUTBOUND_KINDS = frozenset({"send", "post", "delete", "spend"})
# Stays inside the workspace. No approval.
INTERNAL_KINDS = frozenset({"read", "draft", "summarize", "summary", "write", "artifact"})

_KIND_ALIASES = {
    "send_email": "send",
    "send_message": "send",
    "email": "send",
    "message": "send",
    "post_message": "post",
    "spend_money": "spend",
    "purchase": "spend",
    "pay": "spend",
    "remove": "delete",
}

MAX_LOG = 20
MAX_TASKS = 12
MAX_ARTIFACTS = 12
MAX_TITLE = 120
MAX_GOAL = 4000
MAX_SCOPE = 2000
MAX_ARTIFACT_TEXT = 8000
MAX_PAYLOAD_CHARS = 8000

# Conservative. A normal sitting stays in chat.
_ASSIGNMENT_CUE = re.compile(
    r"\bassign\b"
    r"|\bassignment\b"
    r"|\bin the background\b"
    r"|\bwhile I(?:'m| am) away\b",
    re.IGNORECASE,
)

_OUTBOUND_WORD = re.compile(r"\b(send|post|delete|spend)\b", re.IGNORECASE)
_NEGATED_OUTBOUND = re.compile(
    r"\b(?:do not|don't|never|without)\b.{0,48}\b(?:send|post|delete|spend)\b",
    re.IGNORECASE,
)


class IllegalTransition(ValueError):
    """Status move is not in the legal table."""


class ApprovalFinal(ValueError):
    """Declined, expired, or otherwise closed. Never retried."""


class AssignmentError(ValueError):
    """Owner input the API should surface as 400."""


@dataclass
class ProposedAction:
    action_kind: str
    summary: str
    payload: dict[str, Any]


@dataclass
class StepDraft:
    summary: str
    artifact_name: str = "draft.md"
    artifact_kind: str = "draft"
    artifact_text: str = ""
    proposed: Optional[ProposedAction] = None
    note: str = ""


@dataclass(frozen=True)
class ConnectorAction:
    """What a connector would do. v1 has no live email/calendar/Slack."""

    action_kind: str
    summary: str
    payload: dict[str, Any]
    approval_id: str


class Connector(Protocol):
    def execute(self, action: ConnectorAction) -> dict[str, Any]:
        """Perform the action once. Same approval_id must not send twice."""


class InMemoryConnector:
    """Test double. Records calls and refuses a second send for the same approval."""

    def __init__(self) -> None:
        self.calls: list[ConnectorAction] = []
        self._done: set[str] = set()

    def execute(self, action: ConnectorAction) -> dict[str, Any]:
        if action.approval_id in self._done:
            return {"ok": True, "idempotent": True, "approval_id": action.approval_id}
        self._done.add(action.approval_id)
        self.calls.append(action)
        return {"ok": True, "idempotent": False, "approval_id": action.approval_id}


class AssignmentExecutor(Protocol):
    async def draft(self, assignment: Mapping[str, Any]) -> StepDraft:
        """Produce a draft/summary. Propose an outbound action instead of doing it."""


class AssignmentStore(Protocol):
    async def insert_assignment(self, doc: dict[str, Any]) -> None: ...
    async def replace_assignment(self, doc: dict[str, Any]) -> None: ...
    async def get_assignment(self, user_id: str, assignment_id: str) -> Optional[dict[str, Any]]: ...
    async def list_assignments(self, user_id: str) -> list[dict[str, Any]]: ...
    async def insert_approval(self, doc: dict[str, Any]) -> None: ...
    async def replace_approval(self, doc: dict[str, Any]) -> None: ...
    async def get_approval(self, user_id: str, approval_id: str) -> Optional[dict[str, Any]]: ...
    async def list_approvals(
        self,
        user_id: str,
        *,
        status: Optional[str] = None,
        assignment_id: Optional[str] = None,
    ) -> list[dict[str, Any]]: ...


@dataclass
class StepOutcome:
    assignment: dict[str, Any]
    approval: Optional[dict[str, Any]] = None


@dataclass
class DecisionOutcome:
    approval: dict[str, Any]
    assignment: dict[str, Any]
    executed: bool
    idempotent: bool


@dataclass
class MemoryAssignmentStore:
    """In-process store for tests and the handoff unit path."""

    assignments: dict[str, dict[str, Any]] = field(default_factory=dict)
    approvals: dict[str, dict[str, Any]] = field(default_factory=dict)

    async def insert_assignment(self, doc: dict[str, Any]) -> None:
        self.assignments[doc["assignment_id"]] = doc

    async def replace_assignment(self, doc: dict[str, Any]) -> None:
        if doc["assignment_id"] not in self.assignments:
            raise KeyError(doc["assignment_id"])
        self.assignments[doc["assignment_id"]] = doc

    async def get_assignment(self, user_id: str, assignment_id: str) -> Optional[dict[str, Any]]:
        doc = self.assignments.get(assignment_id)
        if not doc or doc.get("user_id") != user_id:
            return None
        return doc

    async def list_assignments(self, user_id: str) -> list[dict[str, Any]]:
        rows = [a for a in self.assignments.values() if a.get("user_id") == user_id]
        rows.sort(key=lambda a: a.get("updated_at") or "", reverse=True)
        return rows

    async def insert_approval(self, doc: dict[str, Any]) -> None:
        self.approvals[doc["approval_id"]] = doc

    async def replace_approval(self, doc: dict[str, Any]) -> None:
        if doc["approval_id"] not in self.approvals:
            raise KeyError(doc["approval_id"])
        self.approvals[doc["approval_id"]] = doc

    async def get_approval(self, user_id: str, approval_id: str) -> Optional[dict[str, Any]]:
        doc = self.approvals.get(approval_id)
        if not doc or doc.get("user_id") != user_id:
            return None
        return doc

    async def list_approvals(
        self,
        user_id: str,
        *,
        status: Optional[str] = None,
        assignment_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for doc in self.approvals.values():
            if doc.get("user_id") != user_id:
                continue
            if status and doc.get("status") != status:
                continue
            if assignment_id and doc.get("assignment_id") != assignment_id:
                continue
            rows.append(doc)
        rows.sort(key=lambda a: a.get("created_at") or "")
        return rows


PRESETS: dict[str, dict[str, str]] = {
    "triage_email": {
        "id": "triage_email",
        "label": "Triage email",
        "title": "Triage email",
        "goal": (
            "Read what the owner pointed at and draft a short triage: "
            "what needs a reply, what can wait, and what to leave alone."
        ),
        "scope": "Heirloom only. Draft replies. Do not send email.",
        "autonomy": AUTONOMY_DRAFT,
    },
    "summarize_thread": {
        "id": "summarize_thread",
        "label": "Summarize thread",
        "title": "Summarize thread",
        "goal": "Summarize the thread into a short note the owner can act on.",
        "scope": "Read the thread. Write a summary artifact. Do not reply, post, or send.",
        "autonomy": AUTONOMY_DRAFT,
    },
    "blank": {
        "id": "blank",
        "label": "Blank",
        "title": "",
        "goal": "",
        "scope": "",
        "autonomy": AUTONOMY_DRAFT,
    },
}


def assignments_allowed(*, audience: Optional[str], heir_surface: bool = False) -> bool:
    """Heirs and callers never see assignments or approvals."""
    if heir_surface:
        return False
    return is_owner_audience(audience)


def can_transition(src: str, dst: str) -> bool:
    return dst in LEGAL_TRANSITIONS.get(src or "", frozenset())


def assert_transition(src: str, dst: str) -> None:
    if dst not in STATUSES:
        raise IllegalTransition(f"Unknown status {dst}")
    if not can_transition(src, dst):
        raise IllegalTransition(f"Cannot move an assignment from {src} to {dst}")


def clean_assignment_autonomy(raw: Optional[str]) -> str:
    key = str(raw or "").strip().lower()
    if key == AUTONOMY_ACT:
        return AUTONOMY_ACT
    return AUTONOMY_DRAFT


def normalize_action_kind(kind: str) -> str:
    key = str(kind or "").strip().lower().replace("-", "_").replace(" ", "_")
    return _KIND_ALIASES.get(key, key)


def effect_needs_approval(action_kind: str, *, clone_autonomy_value: str = "ask") -> bool:
    """Outbound send/post/delete/spend always needs an approval.

    Clone ``ask`` (default) requires an approval for every external effect.
    Clone ``act`` may read, draft, summarize, and write artifacts without
    asking. ``act`` does not bypass send, post, delete, or spend. Other
    external effects still pause in this slice so nothing leaves Heirloom
    unapproved.
    """
    kind = normalize_action_kind(action_kind)
    autonomy = "act" if str(clone_autonomy_value or "").strip().lower() == "act" else "ask"
    if kind in INTERNAL_KINDS:
        return False
    if kind in OUTBOUND_KINDS:
        return True
    # Unknown / other external. ``autonomy`` is read so ask and act stay
    # explicit: neither one executes outside Heirloom in this slice.
    return autonomy in {"ask", "act"}


def preset_prefill(preset_id: Optional[str]) -> dict[str, str]:
    key = str(preset_id or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "triage": "triage_email",
        "email": "triage_email",
        "summarize": "summarize_thread",
        "summary": "summarize_thread",
        "thread": "summarize_thread",
    }
    key = aliases.get(key, key)
    spec = PRESETS.get(key) or PRESETS["blank"]
    return {
        "preset": spec["id"],
        "title": spec["title"],
        "goal": spec["goal"],
        "scope": spec["scope"],
        "autonomy": spec["autonomy"],
    }


def should_open_assignment(
    text: str,
    *,
    fenced: bool = False,
    handler: str = "twin",
    message: str = "",
) -> bool:
    """True only for an explicit background/assign phrase.

    A Clone handoff counts when the turn (or the remainder handed to the
    Clone) asks for it. The default sitting stays answer-in-chat. Heir
    fences never open an assignment.
    """
    if fenced:
        return False
    # A Clone handoff counts only when that handoff asks for background work.
    if handler == "clone" and _ASSIGNMENT_CUE.search(message or text or ""):
        return True
    return bool(_ASSIGNMENT_CUE.search(text or ""))


def title_from_request(text: str) -> str:
    cleaned = _ASSIGNMENT_CUE.sub(" ", text or "")
    cleaned = re.sub(r"^@\S+\s*", "", cleaned.strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .:-")
    if not cleaned:
        return "Background assignment"
    return cleaned[:MAX_TITLE]


def receipt_line(assignment: Mapping[str, Any]) -> str:
    title = (assignment.get("title") or "Untitled assignment").strip() or "Untitled assignment"
    aid = assignment.get("assignment_id") or ""
    return f"Assigned “{title}” — {aid}. I'll report back on /assignments/{aid}."


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def append_log(assignment: dict[str, Any], line: str, now: str) -> None:
    text = re.sub(r"\s+", " ", (line or "").strip())[:240]
    if not text:
        return
    log = list(assignment.get("log") or [])
    log.append({"ts": now, "line": text})
    if len(log) > MAX_LOG:
        log = log[-MAX_LOG:]
    assignment["log"] = log
    assignment["updated_at"] = now


def add_artifact(
    assignment: dict[str, Any],
    *,
    name: str,
    kind: str,
    text: str = "",
    ref: str = "",
    now: str,
) -> None:
    artifacts = list(assignment.get("artifacts") or [])
    artifacts.append({
        "name": (name or "note").strip()[:80] or "note",
        "kind": (kind or "draft").strip()[:40] or "draft",
        "text": (text or "")[:MAX_ARTIFACT_TEXT],
        "ref": (ref or "")[:500],
    })
    if len(artifacts) > MAX_ARTIFACTS:
        artifacts = artifacts[-MAX_ARTIFACTS:]
    assignment["artifacts"] = artifacts
    assignment["updated_at"] = now


def clean_payload(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        return {"text": str(payload)[:4000]}
    try:
        raw = json.dumps(payload, default=str)
    except (TypeError, ValueError):
        return {"text": str(payload)[:4000]}
    if len(raw) > MAX_PAYLOAD_CHARS:
        return {"text": raw[:MAX_PAYLOAD_CHARS]}
    loaded = json.loads(raw)
    return loaded if isinstance(loaded, dict) else {"text": raw[:4000]}


def new_assignment(
    *,
    user_id: str,
    title: str,
    goal: str,
    scope: str,
    autonomy: str,
    clone_id: Optional[str],
    now: str,
    tasks: Optional[Sequence[str]] = None,
    assignment_id: Optional[str] = None,
) -> dict[str, Any]:
    if not (user_id or "").strip():
        raise AssignmentError("Owner is required")
    cid = (clone_id or "").strip() or None
    task_rows: list[dict[str, Any]] = []
    for raw in list(tasks or [])[:MAX_TASKS]:
        text = str(raw or "").strip()[:200]
        if not text:
            continue
        task_rows.append({"task_id": _new_id("tsk"), "text": text, "done": False})
    doc = {
        "assignment_id": assignment_id or _new_id("asn"),
        "user_id": user_id,
        "title": (title or "").strip()[:MAX_TITLE],
        "goal": (goal or "").strip()[:MAX_GOAL],
        "status": STATUS_QUEUED,
        "autonomy": clean_assignment_autonomy(autonomy),
        "clone_id": cid,
        "scope": (scope or "").strip()[:MAX_SCOPE],
        "artifacts": [],
        "log": [],
        "tasks": task_rows,
        "created_at": now,
        "updated_at": now,
    }
    append_log(doc, "Queued.", now)
    return doc


def public_assignment(doc: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "assignment_id": doc.get("assignment_id"),
        "user_id": doc.get("user_id"),
        "title": doc.get("title") or "",
        "goal": doc.get("goal") or "",
        "status": doc.get("status"),
        "autonomy": clean_assignment_autonomy(str(doc.get("autonomy") or "")),
        "clone_id": doc.get("clone_id"),
        "scope": doc.get("scope") or "",
        "artifacts": list(doc.get("artifacts") or []),
        "log": list(doc.get("log") or []),
        "tasks": list(doc.get("tasks") or []),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


def public_approval(doc: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "approval_id": doc.get("approval_id"),
        "assignment_id": doc.get("assignment_id"),
        "user_id": doc.get("user_id"),
        "action_kind": doc.get("action_kind"),
        "summary": doc.get("summary") or "",
        "payload": doc.get("payload") or {},
        "status": doc.get("status"),
        "decided_at": doc.get("decided_at"),
        "executed": bool(doc.get("executed")),
        "created_at": doc.get("created_at"),
    }


def transition_assignment(assignment: Mapping[str, Any], dst: str, *, now: str) -> dict[str, Any]:
    nxt = deepcopy(dict(assignment))
    assert_transition(str(nxt.get("status") or ""), dst)
    nxt["status"] = dst
    nxt["updated_at"] = now
    return nxt


def apply_field_update(assignment: Mapping[str, Any], patch: Mapping[str, Any], *, now: str) -> dict[str, Any]:
    nxt = deepcopy(dict(assignment))
    if nxt.get("status") in TERMINAL_STATUSES:
        raise AssignmentError("This assignment is closed")
    if "title" in patch and patch["title"] is not None:
        nxt["title"] = str(patch["title"]).strip()[:MAX_TITLE]
    if "goal" in patch and patch["goal"] is not None:
        nxt["goal"] = str(patch["goal"]).strip()[:MAX_GOAL]
    if "scope" in patch and patch["scope"] is not None:
        nxt["scope"] = str(patch["scope"]).strip()[:MAX_SCOPE]
    if "autonomy" in patch and patch["autonomy"] is not None:
        nxt["autonomy"] = clean_assignment_autonomy(str(patch["autonomy"]))
    if "clone_id" in patch:
        cid = patch.get("clone_id")
        nxt["clone_id"] = (str(cid).strip() if cid else None) or None
    nxt["updated_at"] = now
    return nxt


def add_task(assignment: Mapping[str, Any], text: str, *, now: str) -> dict[str, Any]:
    nxt = deepcopy(dict(assignment))
    if nxt.get("status") == STATUS_CANCELLED:
        raise AssignmentError("This assignment is cancelled")
    body = (text or "").strip()[:200]
    if not body:
        raise AssignmentError("Task text is required")
    tasks = list(nxt.get("tasks") or [])
    if len(tasks) >= MAX_TASKS:
        raise AssignmentError(f"At most {MAX_TASKS} tasks")
    tasks.append({"task_id": _new_id("tsk"), "text": body, "done": False})
    nxt["tasks"] = tasks
    nxt["updated_at"] = now
    append_log(nxt, f"Task added: {body}", now)
    return nxt


def toggle_task(assignment: Mapping[str, Any], task_id: str, *, now: str) -> dict[str, Any]:
    nxt = deepcopy(dict(assignment))
    if nxt.get("status") == STATUS_CANCELLED:
        raise AssignmentError("This assignment is cancelled")
    found = False
    tasks = []
    for task in list(nxt.get("tasks") or []):
        row = dict(task)
        if row.get("task_id") == task_id:
            row["done"] = not bool(row.get("done"))
            found = True
        tasks.append(row)
    if not found:
        raise AssignmentError("Task not found")
    nxt["tasks"] = tasks
    nxt["updated_at"] = now
    return nxt


def new_approval(
    *,
    assignment: Mapping[str, Any],
    action_kind: str,
    summary: str,
    payload: Any,
    now: str,
) -> dict[str, Any]:
    kind = normalize_action_kind(action_kind)
    return {
        "approval_id": _new_id("apr"),
        "assignment_id": assignment["assignment_id"],
        "user_id": assignment["user_id"],
        "action_kind": kind,
        "summary": (summary or f"Approve {kind}").strip()[:400],
        "payload": clean_payload(payload),
        "status": APPROVAL_PENDING,
        "decided_at": None,
        "executed": False,
        "created_at": now,
    }


def outbound_kind_in_text(text: str) -> Optional[str]:
    """First non-negated send/post/delete/spend. 'Do not send' does not count."""
    for chunk in re.split(r"[\n.]+", text or ""):
        line = chunk.strip()
        if not line or _NEGATED_OUTBOUND.search(line):
            continue
        match = _OUTBOUND_WORD.search(line)
        if match:
            return match.group(1).lower()
    return None


def offline_draft(assignment: Mapping[str, Any]) -> StepDraft:
    """Deterministic draft when no model is injected. Still proposes outbound work."""
    title = (assignment.get("title") or "Assignment").strip() or "Assignment"
    goal = (assignment.get("goal") or "").strip()
    scope = (assignment.get("scope") or "").strip()
    kind = "summary" if assignment.get("autonomy") == AUTONOMY_ACT else "draft"
    body = f"# {title}\n\n{goal or '(no goal yet)'}\n"
    if scope:
        body += f"\nScope: {scope}\n"
    proposed = None
    outbound = outbound_kind_in_text(f"{title}\n{goal}")
    if outbound:
        proposed = ProposedAction(
            action_kind=outbound,
            summary=f"Would {outbound}: {goal[:180] or title}",
            payload={"text": goal or title, "kind": outbound},
        )
    summary = f"Drafted “{title}”."
    if proposed:
        summary = f"Drafted “{title}” and held {proposed.action_kind} for approval."
    return StepDraft(
        summary=summary,
        artifact_name="summary.md" if kind == "summary" else "draft.md",
        artifact_kind=kind,
        artifact_text=body.strip(),
        proposed=proposed,
    )


def build_executor_prompt(assignment: Mapping[str, Any]) -> str:
    return "\n".join([
        "You are drafting inside Heirloom. You cannot send, post, delete, or spend.",
        "Reply in this shape:",
        "SUMMARY: one line",
        "ARTIFACT_NAME: draft.md",
        "ARTIFACT_KIND: draft",
        "ARTIFACT:",
        "<the draft or summary>",
        "ACTION: none|send|post|delete|spend",
        "ACTION_SUMMARY: one line, or empty",
        "PAYLOAD: {json object of exactly what would be sent or changed}",
        "",
        f"Title: {assignment.get('title') or ''}",
        f"Goal: {assignment.get('goal') or ''}",
        f"Scope: {assignment.get('scope') or ''}",
        f"Autonomy: {assignment.get('autonomy') or AUTONOMY_DRAFT}",
    ])


def parse_step_output(raw: str, assignment: Mapping[str, Any]) -> StepDraft:
    text = (raw or "").strip()
    if not text:
        return offline_draft(assignment)
    fenced = re.search(r"\{[\s\S]*\}", text)
    if fenced and "SUMMARY:" not in text.upper():
        try:
            data = json.loads(fenced.group(0))
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            return _draft_from_json(data, assignment)
    summary = _field(text, "SUMMARY") or "Draft ready."
    name = _field(text, "ARTIFACT_NAME") or "draft.md"
    kind = (_field(text, "ARTIFACT_KIND") or "draft").lower()
    artifact = _block(text, "ARTIFACT")
    action = (_field(text, "ACTION") or "none").strip().lower()
    action_summary = _field(text, "ACTION_SUMMARY")
    payload_raw = _field(text, "PAYLOAD")
    proposed = None
    if action and action not in {"none", "null", "-"}:
        payload: Any = {}
        if payload_raw:
            try:
                payload = json.loads(payload_raw)
            except json.JSONDecodeError:
                payload = {"text": payload_raw}
        if not payload and artifact:
            payload = {"text": artifact[:4000]}
        proposed = ProposedAction(
            action_kind=normalize_action_kind(action),
            summary=action_summary or summary,
            payload=clean_payload(payload),
        )
    if not artifact:
        artifact = text[:MAX_ARTIFACT_TEXT]
    return StepDraft(
        summary=summary[:240],
        artifact_name=name[:80] or "draft.md",
        artifact_kind=kind[:40] or "draft",
        artifact_text=artifact[:MAX_ARTIFACT_TEXT],
        proposed=proposed,
    )


def _draft_from_json(data: Mapping[str, Any], assignment: Mapping[str, Any]) -> StepDraft:
    action = data.get("action")
    proposed = None
    if isinstance(action, dict):
        kind = str(action.get("kind") or action.get("action_kind") or "").strip()
        if kind and kind.lower() not in {"none", "null"}:
            proposed = ProposedAction(
                action_kind=normalize_action_kind(kind),
                summary=str(action.get("summary") or data.get("summary") or "")[:400],
                payload=clean_payload(action.get("payload")),
            )
    elif isinstance(action, str) and action.strip().lower() not in {"", "none", "null"}:
        proposed = ProposedAction(
            action_kind=normalize_action_kind(action),
            summary=str(data.get("summary") or "")[:400],
            payload=clean_payload(data.get("payload")),
        )
    artifact = str(data.get("artifact") or data.get("text") or "")
    if not artifact and not proposed:
        return offline_draft(assignment)
    return StepDraft(
        summary=str(data.get("summary") or "Draft ready.")[:240],
        artifact_name=str(data.get("artifact_name") or "draft.md")[:80],
        artifact_kind=str(data.get("artifact_kind") or "draft")[:40],
        artifact_text=artifact[:MAX_ARTIFACT_TEXT],
        proposed=proposed,
    )


def _field(text: str, name: str) -> str:
    match = re.search(rf"^{name}:\s*(.*)$", text, re.IGNORECASE | re.MULTILINE)
    if not match:
        return ""
    return match.group(1).strip()


def _block(text: str, name: str) -> str:
    match = re.search(
        rf"^{name}:\s*\n(.*?)(?:\nACTION:|\nPAYLOAD:|\Z)",
        text,
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    if not match:
        return ""
    return match.group(1).strip()


class ChatAssignmentExecutor:
    """v1 executor. ``complete`` is the existing chat plumbing (injected).

    When it is missing or fails, the step still returns a local draft and,
    if the goal proposes an outbound action, an approval — never a send.
    """

    def __init__(self, complete: Optional[Callable[[str], Awaitable[str]]] = None) -> None:
        self.complete = complete

    async def draft(self, assignment: Mapping[str, Any]) -> StepDraft:
        if self.complete is None:
            return offline_draft(assignment)
        try:
            raw = await self.complete(build_executor_prompt(assignment))
        except Exception as exc:  # noqa: BLE001 — model outages stay a local draft
            drafted = offline_draft(assignment)
            drafted.note = f"Model unavailable ({type(exc).__name__}). Local draft only."
            return drafted
        try:
            return parse_step_output(str(raw or ""), assignment)
        except Exception:  # noqa: BLE001
            return offline_draft(assignment)


async def run_assignment_step(
    assignment: Mapping[str, Any],
    *,
    executor: AssignmentExecutor,
    connector: Connector,
    now: str,
    clone_autonomy_value: str = "ask",
) -> StepOutcome:
    """One step. Outbound proposals become an Approval. The connector is not called."""
    status = str(assignment.get("status") or "")
    if status == STATUS_QUEUED:
        current = transition_assignment(assignment, STATUS_RUNNING, now=now)
        append_log(current, "Running.", now)
    elif status == STATUS_RUNNING:
        current = deepcopy(dict(assignment))
    else:
        raise IllegalTransition(f"Cannot run a step from {status}")

    try:
        drafted = await executor.draft(current)
    except Exception as exc:  # noqa: BLE001
        failed = transition_assignment(current, STATUS_FAILED, now=now)
        append_log(failed, f"Step failed: {exc}", now)
        return StepOutcome(assignment=failed, approval=None)

    if drafted.note:
        append_log(current, drafted.note, now)
    if drafted.summary:
        append_log(current, drafted.summary, now)
    if drafted.artifact_text or drafted.artifact_name:
        add_artifact(
            current,
            name=drafted.artifact_name,
            kind=drafted.artifact_kind,
            text=drafted.artifact_text,
            now=now,
        )

    proposed = drafted.proposed
    if proposed and effect_needs_approval(
        proposed.action_kind, clone_autonomy_value=clone_autonomy_value
    ):
        approval = new_approval(
            assignment=current,
            action_kind=proposed.action_kind,
            summary=proposed.summary,
            payload=proposed.payload,
            now=now,
        )
        current = transition_assignment(current, STATUS_NEEDS_APPROVAL, now=now)
        held = (
            f"Waiting for approval before {approval['action_kind']}."
        )
        if str(clone_autonomy_value).strip().lower() == "act" or current.get("autonomy") == AUTONOMY_ACT:
            held = f"Waiting for approval before {approval['action_kind']}. Act does not send on its own."
        append_log(current, held, now)
        # Connector stays idle until the owner approves.
        _ = connector
        return StepOutcome(assignment=current, approval=approval)

    done = transition_assignment(current, STATUS_DONE, now=now)
    append_log(done, "Done.", now)
    return StepOutcome(assignment=done, approval=None)


def decide_approval(
    approval: Mapping[str, Any],
    assignment: Mapping[str, Any],
    decision: str,
    *,
    now: str,
    connector: Connector,
) -> DecisionOutcome:
    """Approve executes once. Decline and expire are final and are not retried."""
    choice = (decision or "").strip().lower()
    if choice not in {"approve", "decline", "expire"}:
        raise AssignmentError("Decision must be approve, decline, or expire")
    status = str(approval.get("status") or "")
    current_approval = deepcopy(dict(approval))
    current_assignment = deepcopy(dict(assignment))

    if choice == "approve":
        if status == APPROVAL_APPROVED:
            return DecisionOutcome(
                approval=current_approval,
                assignment=current_assignment,
                executed=False,
                idempotent=True,
            )
        if status in APPROVAL_FINAL:
            raise ApprovalFinal(f"Approval is {status} and cannot be retried")
        if status != APPROVAL_PENDING:
            raise ApprovalFinal(f"Approval is {status or 'closed'} and cannot be retried")
        action = ConnectorAction(
            action_kind=str(current_approval.get("action_kind") or ""),
            summary=str(current_approval.get("summary") or ""),
            payload=dict(current_approval.get("payload") or {}),
            approval_id=str(current_approval.get("approval_id") or ""),
        )
        connector.execute(action)
        current_approval["status"] = APPROVAL_APPROVED
        current_approval["decided_at"] = now
        current_approval["executed"] = True
        moved = transition_assignment(current_assignment, STATUS_DONE, now=now)
        append_log(moved, f"Approved {action.action_kind}. Executed once.", now)
        return DecisionOutcome(approval=current_approval, assignment=moved, executed=True, idempotent=False)

    if status == APPROVAL_DECLINED and choice == "decline":
        return DecisionOutcome(
            approval=current_approval,
            assignment=current_assignment,
            executed=False,
            idempotent=True,
        )
    if status == APPROVAL_EXPIRED and choice == "expire":
        return DecisionOutcome(
            approval=current_approval,
            assignment=current_assignment,
            executed=False,
            idempotent=True,
        )
    if status != APPROVAL_PENDING:
        raise ApprovalFinal(f"Approval is {status or 'closed'} and cannot be retried")

    if choice == "decline":
        current_approval["status"] = APPROVAL_DECLINED
        line = "Declined. This will not be retried."
    else:
        current_approval["status"] = APPROVAL_EXPIRED
        line = "Expired. This will not be retried."
    current_approval["decided_at"] = now
    current_approval["executed"] = False
    if current_assignment.get("status") == STATUS_NEEDS_APPROVAL:
        current_assignment = transition_assignment(current_assignment, STATUS_CANCELLED, now=now)
    append_log(current_assignment, line, now)
    return DecisionOutcome(
        approval=current_approval,
        assignment=current_assignment,
        executed=False,
        idempotent=False,
    )


def cancel_assignment(
    assignment: Mapping[str, Any],
    approvals: Sequence[Mapping[str, Any]],
    *,
    now: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    moved = transition_assignment(assignment, STATUS_CANCELLED, now=now)
    append_log(moved, "Cancelled.", now)
    closed: list[dict[str, Any]] = []
    for row in approvals:
        nxt = deepcopy(dict(row))
        if nxt.get("status") == APPROVAL_PENDING:
            nxt["status"] = APPROVAL_EXPIRED
            nxt["decided_at"] = now
            nxt["executed"] = False
        closed.append(nxt)
    return moved, closed


def resolve_create_fields(
    *,
    preset: Optional[str],
    title: str,
    goal: str,
    scope: str,
    autonomy: Optional[str],
) -> dict[str, str]:
    filled = preset_prefill(preset) if preset else {
        "preset": "",
        "title": "",
        "goal": "",
        "scope": "",
        "autonomy": AUTONOMY_DRAFT,
    }
    if (title or "").strip():
        filled["title"] = title.strip()[:MAX_TITLE]
    if (goal or "").strip():
        filled["goal"] = goal.strip()[:MAX_GOAL]
    if (scope or "").strip():
        filled["scope"] = scope.strip()[:MAX_SCOPE]
    if autonomy:
        filled["autonomy"] = clean_assignment_autonomy(autonomy)
    if not filled["title"] and not filled["goal"]:
        raise AssignmentError("Add a title or a goal")
    if not filled["title"]:
        filled["title"] = title_from_request(filled["goal"])
    return filled


def autonomy_for_clone(clones: Optional[Sequence[Mapping[str, Any]]], clone_id: Optional[str]) -> str:
    if not clone_id:
        return "ask"
    for clone in clones or []:
        cid = clone.get("clone_id") or clone.get("assistant_id")
        if cid == clone_id:
            return clone_autonomy(dict(clone))
    return "ask"


async def create_and_run(
    store: AssignmentStore,
    *,
    user_id: str,
    title: str,
    goal: str,
    scope: str,
    autonomy: str,
    clone_id: Optional[str],
    tasks: Optional[Sequence[str]],
    now: str,
    executor: AssignmentExecutor,
    connector: Connector,
    clone_autonomy_value: str = "ask",
) -> dict[str, Any]:
    doc = new_assignment(
        user_id=user_id,
        title=title,
        goal=goal,
        scope=scope,
        autonomy=autonomy,
        clone_id=clone_id,
        now=now,
        tasks=tasks,
    )
    await store.insert_assignment(doc)
    outcome = await run_assignment_step(
        doc,
        executor=executor,
        connector=connector,
        now=now,
        clone_autonomy_value=clone_autonomy_value,
    )
    await store.replace_assignment(outcome.assignment)
    if outcome.approval:
        await store.insert_approval(outcome.approval)
    return {
        "assignment": public_assignment(outcome.assignment),
        "approval": public_approval(outcome.approval) if outcome.approval else None,
        "receipt": receipt_line(outcome.assignment),
    }


async def open_assignment_for_turn(
    text: str,
    *,
    user_id: str,
    now: str,
    fenced: bool = False,
    handler: str = "twin",
    message: str = "",
    clone_id: Optional[str] = None,
    clones: Optional[Sequence[Mapping[str, Any]]] = None,
    store: Optional[AssignmentStore] = None,
    executor: Optional[AssignmentExecutor] = None,
    connector: Optional[Connector] = None,
) -> Optional[dict[str, Any]]:
    """Router handoff. Returns a receipt payload, or None to stay in chat."""
    if not should_open_assignment(text, fenced=fenced, handler=handler, message=message):
        return None
    active = store
    if active is None:
        from assignment_store import MongoAssignmentStore

        active = MongoAssignmentStore()
    goal = (message or text or "").strip()[:MAX_GOAL]
    fields = resolve_create_fields(
        preset=None,
        title=title_from_request(text),
        goal=goal,
        scope="Heirloom workspace. Do not send, post, delete, or spend without approval.",
        autonomy=AUTONOMY_DRAFT,
    )
    return await create_and_run(
        active,
        user_id=user_id,
        title=fields["title"],
        goal=fields["goal"],
        scope=fields["scope"],
        autonomy=fields["autonomy"],
        clone_id=clone_id,
        tasks=None,
        now=now,
        executor=executor or production_executor(),
        connector=connector or InMemoryConnector(),
        clone_autonomy_value=autonomy_for_clone(clones, clone_id),
    )


def production_executor() -> ChatAssignmentExecutor:
    """Wire the existing LlmChat path. Failures fall back inside ``draft``."""

    async def _complete(prompt: str) -> str:
        from assignment_chat import complete_assignment_prompt

        return await complete_assignment_prompt(prompt)

    return ChatAssignmentExecutor(complete=_complete)
