"""Assignments v1 — transitions, approvals, heir fence, router handoff. No Mongo."""
from __future__ import annotations

import asyncio
from pathlib import Path

from assignments import (
    MAX_LOG,
    STATUS_CANCELLED,
    STATUS_DONE,
    STATUS_NEEDS_APPROVAL,
    STATUS_QUEUED,
    STATUS_RUNNING,
    ApprovalFinal,
    ChatAssignmentExecutor,
    IllegalTransition,
    InMemoryConnector,
    MemoryAssignmentStore,
    ProposedAction,
    StepDraft,
    append_log,
    assignments_allowed,
    can_transition,
    cancel_assignment,
    decide_approval,
    effect_needs_approval,
    new_assignment,
    offline_draft,
    open_assignment_for_turn,
    parse_step_output,
    preset_prefill,
    run_assignment_step,
    should_open_assignment,
)
from main_bot import route_main_bot

ROOT = Path(__file__).resolve().parents[2]
NOW = "2026-10-02T12:00:00+00:00"


def _run(coro):
    return asyncio.run(coro)


def _clones():
    return [
        {
            "clone_id": "cln_research",
            "assistant_id": "cln_research",
            "slug": "research",
            "name": "Research",
            "enabled": True,
            "role": "Look things up and summarize.",
            "autonomy": "ask",
            "abilities": ["web"],
            "tools_allowlist": ["web_search"],
        },
        {
            "clone_id": "cln_runner",
            "assistant_id": "cln_runner",
            "slug": "runner",
            "name": "Runner",
            "enabled": True,
            "role": "Do the errand.",
            "autonomy": "act",
            "abilities": ["web"],
            "tools_allowlist": ["web_search"],
        },
    ]


class _Script:
    def __init__(self, draft: StepDraft):
        self.draft_value = draft

    async def draft(self, assignment):
        return self.draft_value


def _queued(**kwargs):
    base = dict(
        user_id="owner-1",
        title="Weekly note",
        goal="Summarize the thread.",
        scope="Heirloom only.",
        autonomy="draft",
        clone_id=None,
        now=NOW,
    )
    base.update(kwargs)
    return new_assignment(**base)


def test_legal_transitions_only():
    assert can_transition("queued", "running")
    assert can_transition("queued", "cancelled")
    assert can_transition("running", "needs_approval")
    assert can_transition("running", "done")
    assert can_transition("running", "failed")
    assert can_transition("needs_approval", "done")
    assert can_transition("needs_approval", "cancelled")
    assert not can_transition("done", "running")
    assert not can_transition("failed", "queued")
    assert not can_transition("cancelled", "done")
    assert not can_transition("queued", "done")
    assert not can_transition("needs_approval", "running")
    doc = _queued()
    try:
        from assignments import transition_assignment

        transition_assignment(doc, "done", now=NOW)
        raised = False
    except IllegalTransition:
        raised = True
    assert raised


def test_log_is_capped():
    doc = _queued()
    for i in range(MAX_LOG + 8):
        append_log(doc, f"line {i}", NOW)
    assert len(doc["log"]) == MAX_LOG
    assert doc["log"][-1]["line"] == f"line {MAX_LOG + 7}"


def test_presets_only_prefill():
    triage = preset_prefill("triage_email")
    assert triage["title"] == "Triage email"
    assert triage["autonomy"] == "draft"
    assert "send" not in triage["goal"].lower() or "do not" in preset_prefill("triage_email")["scope"].lower()
    assert preset_prefill("summarize_thread")["title"] == "Summarize thread"
    blank = preset_prefill("blank")
    assert blank["title"] == "" and blank["goal"] == "" and blank["autonomy"] == "draft"
    drafted = offline_draft({
        "title": triage["title"],
        "goal": triage["goal"],
        "scope": triage["scope"],
        "autonomy": "draft",
    })
    assert drafted.proposed is None


def test_internal_work_does_not_ask():
    assert effect_needs_approval("summarize", clone_autonomy_value="ask") is False
    assert effect_needs_approval("read", clone_autonomy_value="act") is False
    assert effect_needs_approval("write", clone_autonomy_value="ask") is False
    connector = InMemoryConnector()
    doc = _queued(autonomy="act", clone_id="cln_runner", goal="Summarize the thread.")
    outcome = _run(run_assignment_step(
        doc,
        executor=_Script(StepDraft(summary="Summary ready.", artifact_text="Short note.", artifact_kind="summary")),
        connector=connector,
        now=NOW,
        clone_autonomy_value="act",
    ))
    assert outcome.approval is None
    assert outcome.assignment["status"] == STATUS_DONE
    assert connector.calls == []
    assert outcome.assignment["artifacts"]


def test_act_does_not_bypass_outbound_approval():
    assert effect_needs_approval("send", clone_autonomy_value="act") is True
    assert effect_needs_approval("post", clone_autonomy_value="act") is True
    assert effect_needs_approval("delete", clone_autonomy_value="ask") is True
    assert effect_needs_approval("spend", clone_autonomy_value="act") is True
    connector = InMemoryConnector()
    doc = _queued(autonomy="act", clone_id="cln_runner", goal="Send the weekly note to Ada.")
    outcome = _run(run_assignment_step(
        doc,
        executor=_Script(StepDraft(
            summary="Held the send.",
            artifact_text="Hello Ada",
            proposed=ProposedAction(
                "send",
                "Send the weekly note to Ada",
                {"to": "ada@example.com", "body": "Hello Ada"},
            ),
        )),
        connector=connector,
        now=NOW,
        clone_autonomy_value="act",
    ))
    assert outcome.assignment["status"] == STATUS_NEEDS_APPROVAL
    assert outcome.approval["status"] == "pending"
    assert outcome.approval["action_kind"] == "send"
    assert outcome.approval["payload"]["to"] == "ada@example.com"
    assert outcome.approval["payload"]["body"] == "Hello Ada"
    assert connector.calls == []
    assert any("does not send" in row["line"].lower() for row in outcome.assignment["log"])


def test_approve_is_idempotent_and_decline_is_final():
    connector = InMemoryConnector()
    doc = _queued(goal="Send the weekly note to Ada.")
    outcome = _run(run_assignment_step(
        doc,
        executor=_Script(StepDraft(
            summary="Held the send.",
            artifact_text="Hello",
            proposed=ProposedAction("send_email", "Send it", {"to": "ada@example.com", "body": "Hello"}),
        )),
        connector=connector,
        now=NOW,
        clone_autonomy_value="ask",
    ))
    assert outcome.approval["action_kind"] == "send"
    first = decide_approval(outcome.approval, outcome.assignment, "approve", now=NOW, connector=connector)
    assert first.executed is True
    assert first.idempotent is False
    assert first.assignment["status"] == STATUS_DONE
    assert len(connector.calls) == 1
    assert connector.calls[0].payload["body"] == "Hello"
    second = decide_approval(first.approval, first.assignment, "approve", now=NOW, connector=connector)
    assert second.idempotent is True
    assert second.executed is False
    assert len(connector.calls) == 1

    declined_step = _run(run_assignment_step(
        _queued(goal="Post the note."),
        executor=_Script(StepDraft(
            summary="Held the post.",
            artifact_text="Note",
            proposed=ProposedAction("post", "Post the note", {"text": "Note"}),
        )),
        connector=InMemoryConnector(),
        now=NOW,
    ))
    declined = decide_approval(
        declined_step.approval,
        declined_step.assignment,
        "decline",
        now=NOW,
        connector=connector,
    )
    assert declined.approval["status"] == "declined"
    assert declined.assignment["status"] == STATUS_CANCELLED
    assert declined.executed is False
    again = decide_approval(declined.approval, declined.assignment, "decline", now=NOW, connector=connector)
    assert again.idempotent is True
    try:
        decide_approval(declined.approval, declined.assignment, "approve", now=NOW, connector=connector)
        retried = False
    except ApprovalFinal:
        retried = True
    assert retried
    assert len(connector.calls) == 1


def test_expired_is_final_and_cancel_expires_pending():
    connector = InMemoryConnector()
    step = _run(run_assignment_step(
        _queued(goal="Delete the draft outside Heirloom."),
        executor=_Script(StepDraft(
            summary="Held the delete.",
            artifact_text="draft",
            proposed=ProposedAction("delete", "Delete the draft", {"ref": "draft-1"}),
        )),
        connector=connector,
        now=NOW,
    ))
    expired = decide_approval(step.approval, step.assignment, "expire", now=NOW, connector=connector)
    assert expired.approval["status"] == "expired"
    assert expired.assignment["status"] == STATUS_CANCELLED
    try:
        decide_approval(expired.approval, expired.assignment, "approve", now=NOW, connector=connector)
        retried = False
    except ApprovalFinal:
        retried = True
    assert retried
    assert connector.calls == []

    fresh = _run(run_assignment_step(
        _queued(goal="Spend $12 on stamps."),
        executor=_Script(StepDraft(
            summary="Held the spend.",
            artifact_text="$12",
            proposed=ProposedAction("spend", "Buy stamps", {"amount": "12", "payee": "post"}),
        )),
        connector=InMemoryConnector(),
        now=NOW,
    ))
    cancelled, closed = cancel_assignment(fresh.assignment, [fresh.approval], now=NOW)
    assert cancelled["status"] == STATUS_CANCELLED
    assert closed[0]["status"] == "expired"
    try:
        decide_approval(closed[0], cancelled, "approve", now=NOW, connector=connector)
        retried = False
    except ApprovalFinal:
        retried = True
    assert retried


def test_parser_proposes_action_instead_of_doing_it():
    raw = "\n".join([
        "SUMMARY: Drafted the note",
        "ARTIFACT_NAME: draft.md",
        "ARTIFACT_KIND: draft",
        "ARTIFACT:",
        "Hello Ada",
        "ACTION: send",
        "ACTION_SUMMARY: Send the note to Ada",
        'PAYLOAD: {"to":"ada@example.com","body":"Hello Ada"}',
    ])
    drafted = parse_step_output(raw, {"title": "Note", "goal": "Send it", "autonomy": "draft"})
    assert drafted.proposed is not None
    assert drafted.proposed.action_kind == "send"
    assert drafted.proposed.payload["body"] == "Hello Ada"
    assert "Hello Ada" in drafted.artifact_text
    plain = parse_step_output("Just a summary of the thread.", {
        "title": "Thread",
        "goal": "Summarize the thread. Do not send.",
        "autonomy": "draft",
        "scope": "",
    })
    assert plain.artifact_text


def test_default_chat_does_not_open_an_assignment():
    text = "What did I love most about being a father?"
    decision = route_main_bot(text, _clones())
    assert should_open_assignment(
        text, fenced=decision.fenced, handler=decision.handler, message=decision.message
    ) is False
    store = MemoryAssignmentStore()
    opened = _run(open_assignment_for_turn(
        text,
        user_id="owner-1",
        now=NOW,
        fenced=decision.fenced,
        handler=decision.handler,
        message=decision.message,
        store=store,
        executor=ChatAssignmentExecutor(complete=None),
        connector=InMemoryConnector(),
    ))
    assert opened is None
    assert store.assignments == {}


def test_router_handoff_creates_an_assignment():
    text = "@Research assign the thread summary in the background"
    decision = route_main_bot(text, _clones())
    assert decision.handler == "clone"
    assert decision.clone_id == "cln_research"
    assert should_open_assignment(
        text, fenced=decision.fenced, handler=decision.handler, message=decision.message
    ) is True
    store = MemoryAssignmentStore()
    opened = _run(open_assignment_for_turn(
        text,
        user_id="owner-1",
        now=NOW,
        fenced=decision.fenced,
        handler=decision.handler,
        message=decision.message,
        clone_id=decision.clone_id,
        clones=_clones(),
        store=store,
        executor=ChatAssignmentExecutor(complete=None),
        connector=InMemoryConnector(),
    ))
    assert opened is not None
    assignment = opened["assignment"]
    assert assignment["assignment_id"] in store.assignments
    assert assignment["user_id"] == "owner-1"
    assert assignment["clone_id"] == "cln_research"
    assert assignment["status"] in {STATUS_DONE, STATUS_NEEDS_APPROVAL, STATUS_QUEUED, STATUS_RUNNING}
    assert assignment["status"] == STATUS_DONE
    assert "I'll report back" in opened["receipt"]
    assert "/assignments/" in opened["receipt"]
    hidden = _run(store.get_assignment("someone-else", assignment["assignment_id"]))
    assert hidden is None
    own = _run(store.get_assignment("owner-1", assignment["assignment_id"]))
    assert own["title"]


def test_clone_handoff_without_a_cue_stays_in_chat():
    text = "@Research look up the weather in Austin"
    decision = route_main_bot(text, _clones())
    assert decision.handler == "clone"
    assert should_open_assignment(
        text, fenced=False, handler="clone", message=decision.message
    ) is False


def test_while_away_phrase_opens_for_the_twin():
    text = "While I'm away, summarize the inbox"
    decision = route_main_bot(text, [])
    assert decision.fenced is False
    assert should_open_assignment(text, fenced=False, handler=decision.handler, message=decision.message)


def test_heir_fence_blocks_assignments():
    assert assignments_allowed(audience="owner") is True
    assert assignments_allowed(audience="heir") is False
    assert assignments_allowed(audience="caller") is False
    assert assignments_allowed(audience="owner", heir_surface=True) is False
    text = "Assign the inbox triage in the background"
    decision = route_main_bot(text, _clones(), audience="heir", heir_surface=True)
    assert decision.fenced is True
    assert should_open_assignment(
        text, fenced=decision.fenced, handler=decision.handler, message=decision.message
    ) is False
    store = MemoryAssignmentStore()
    opened = _run(open_assignment_for_turn(
        text,
        user_id="heir-1",
        now=NOW,
        fenced=True,
        handler=decision.handler,
        message=text,
        store=store,
        executor=ChatAssignmentExecutor(complete=None),
    ))
    assert opened is None
    assert store.assignments == {}


def test_owner_routers_are_session_scoped_and_heir_portal_is_dark():
    assignments_src = (ROOT / "backend" / "routers" / "assignments.py").read_text(encoding="utf-8")
    approvals_src = (ROOT / "backend" / "routers" / "approvals.py").read_text(encoding="utf-8")
    for src in (assignments_src, approvals_src):
        assert "Depends(get_current_user)" in src
        assert 'user["user_id"]' in src
        assert "assignments_allowed" in src
        assert "release_token" not in src
    server = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    assert "assignments.router" in server
    assert "approvals.router" in server
    owner = (ROOT / "backend" / "owner_rail.py").read_text(encoding="utf-8")
    assert "should_open_assignment" in owner
    assert "open_assignment_for_turn" in owner
    portal = (ROOT / "frontend" / "src" / "pages" / "HeirPortal.jsx").read_text(encoding="utf-8")
    assert "/assignments" not in portal
    assert "/approvals" not in portal
    assert "ApprovalCard" not in portal
    page = (ROOT / "frontend" / "src" / "pages" / "Assignments.jsx").read_text(encoding="utf-8")
    assert "triage_email" in page or "PRESETS" in page
    assert "ApprovalCard" in page
    app = (ROOT / "frontend" / "src" / "App.js").read_text(encoding="utf-8")
    assert 'path="/assignments"' in app
    heir_idx = app.index('path="/heir/:token"')
    layout_idx = app.index("<AppLayout />")
    assignments_idx = app.index('path="/assignments"')
    assert heir_idx < layout_idx < assignments_idx
