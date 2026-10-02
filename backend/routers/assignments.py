"""Owner-only assignments. Heirs use the portal and never reach this router."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from assignment_store import MongoAssignmentStore
from assignments import (
    AssignmentError,
    IllegalTransition,
    InMemoryConnector,
    PRESETS,
    add_task,
    apply_field_update,
    assignments_allowed,
    autonomy_for_clone,
    cancel_assignment,
    create_and_run,
    preset_prefill,
    public_approval,
    public_assignment,
    resolve_create_fields,
    run_assignment_step,
    toggle_task,
)
from deps import get_current_user
from routers.assistants import list_for_user

router = APIRouter(prefix="/assignments", tags=["assignments"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _owner_gate(user: dict) -> None:
    if user.get("account_status") == "refunded":
        raise HTTPException(status_code=403, detail="account_inactive")
    if not assignments_allowed(
        audience=user.get("audience") or "owner",
        heir_surface=bool(user.get("heir_surface")),
    ):
        raise HTTPException(status_code=403, detail="owner_only")


def _store() -> MongoAssignmentStore:
    return MongoAssignmentStore()


async def _executor_for(user_id: str, preset: Optional[str]):
    from email_intent import EMAIL_PRESETS

    if (preset or "") in EMAIL_PRESETS:
        from connector_runtime import provider_for_user
        from mail_provider import EmailAssignmentExecutor

        return EmailAssignmentExecutor(await provider_for_user(user_id))
    from assignments import production_executor

    return production_executor()


class AssignmentCreate(BaseModel):
    title: str = ""
    goal: str = ""
    scope: str = ""
    autonomy: Optional[str] = None
    clone_id: Optional[str] = Field(None, max_length=40)
    preset: Optional[str] = Field(None, max_length=40)
    tasks: list[str] = Field(default_factory=list)


class AssignmentUpdate(BaseModel):
    title: Optional[str] = None
    goal: Optional[str] = None
    scope: Optional[str] = None
    autonomy: Optional[str] = None
    clone_id: Optional[str] = Field(None, max_length=40)


class TaskCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=200)


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (AssignmentError, IllegalTransition, ApprovalFinal)):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=400, detail="Could not update the assignment")


@router.get("")
async def list_assignments(user: dict = Depends(get_current_user)):
    _owner_gate(user)
    rows = await _store().list_assignments(user["user_id"])
    return {
        "assignments": [public_assignment(row) for row in rows],
        "presets": [preset_prefill(key) | {"label": spec["label"]} for key, spec in PRESETS.items()],
    }


@router.post("")
async def create_assignment(payload: AssignmentCreate, user: dict = Depends(get_current_user)):
    _owner_gate(user)
    try:
        fields = resolve_create_fields(
            preset=payload.preset,
            title=payload.title,
            goal=payload.goal,
            scope=payload.scope,
            autonomy=payload.autonomy,
        )
    except AssignmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    clone_id = (payload.clone_id or "").strip() or None
    clones: list[dict] = []
    if clone_id:
        clones = await list_for_user(user["user_id"], seed=False)
        if not any((c.get("clone_id") or c.get("assistant_id")) == clone_id for c in clones):
            raise HTTPException(status_code=400, detail="Clone not found")
    try:
        result = await create_and_run(
            _store(),
            user_id=user["user_id"],
            title=fields["title"],
            goal=fields["goal"],
            scope=fields["scope"],
            autonomy=fields["autonomy"],
            clone_id=clone_id,
            tasks=payload.tasks,
            now=_now(),
            executor=await _executor_for(user["user_id"], fields.get("preset")),
            connector=InMemoryConnector(),
            preset=fields.get("preset") or "",
            clone_autonomy_value=autonomy_for_clone(clones, clone_id),
        )
    except (AssignmentError, IllegalTransition) as exc:
        raise _map_error(exc) from exc
    return result


@router.get("/{assignment_id}")
async def get_assignment(assignment_id: str, user: dict = Depends(get_current_user)):
    _owner_gate(user)
    doc = await _store().get_assignment(user["user_id"], assignment_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Assignment not found")
    return {"assignment": public_assignment(doc)}


@router.patch("/{assignment_id}")
async def update_assignment(
    assignment_id: str,
    payload: AssignmentUpdate,
    user: dict = Depends(get_current_user),
):
    _owner_gate(user)
    store = _store()
    doc = await store.get_assignment(user["user_id"], assignment_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Assignment not found")
    patch = payload.model_dump(exclude_unset=True)
    if "clone_id" in patch and patch["clone_id"]:
        clones = await list_for_user(user["user_id"], seed=False)
        if not any((c.get("clone_id") or c.get("assistant_id")) == patch["clone_id"] for c in clones):
            raise HTTPException(status_code=400, detail="Clone not found")
    try:
        updated = apply_field_update(doc, patch, now=_now())
    except (AssignmentError, IllegalTransition) as exc:
        raise _map_error(exc) from exc
    await store.replace_assignment(updated)
    return {"assignment": public_assignment(updated)}


@router.post("/{assignment_id}/cancel")
async def cancel(assignment_id: str, user: dict = Depends(get_current_user)):
    _owner_gate(user)
    store = _store()
    doc = await store.get_assignment(user["user_id"], assignment_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Assignment not found")
    pending = await store.list_approvals(
        user["user_id"], status="pending", assignment_id=assignment_id
    )
    try:
        updated, closed = cancel_assignment(doc, pending, now=_now())
    except IllegalTransition as exc:
        raise _map_error(exc) from exc
    await store.replace_assignment(updated)
    for row in closed:
        if row.get("approval_id"):
            await store.replace_approval(row)
    return {"assignment": public_assignment(updated)}


@router.post("/{assignment_id}/tasks")
async def create_task(
    assignment_id: str,
    payload: TaskCreate,
    user: dict = Depends(get_current_user),
):
    _owner_gate(user)
    store = _store()
    doc = await store.get_assignment(user["user_id"], assignment_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Assignment not found")
    try:
        updated = add_task(doc, payload.text, now=_now())
    except AssignmentError as exc:
        raise _map_error(exc) from exc
    await store.replace_assignment(updated)
    return {"assignment": public_assignment(updated)}


@router.post("/{assignment_id}/tasks/{task_id}/toggle")
async def toggle(
    assignment_id: str,
    task_id: str,
    user: dict = Depends(get_current_user),
):
    _owner_gate(user)
    store = _store()
    doc = await store.get_assignment(user["user_id"], assignment_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Assignment not found")
    try:
        updated = toggle_task(doc, task_id, now=_now())
    except AssignmentError as exc:
        raise _map_error(exc) from exc
    await store.replace_assignment(updated)
    return {"assignment": public_assignment(updated)}


@router.post("/{assignment_id}/step")
async def step(assignment_id: str, user: dict = Depends(get_current_user)):
    """Run one more step when the assignment is still queued or running."""
    _owner_gate(user)
    store = _store()
    doc = await store.get_assignment(user["user_id"], assignment_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Assignment not found")
    clones = await list_for_user(user["user_id"], seed=False)
    try:
        outcome = await run_assignment_step(
            doc,
            executor=await _executor_for(user["user_id"], doc.get("preset")),
            connector=InMemoryConnector(),
            now=_now(),
            clone_autonomy_value=autonomy_for_clone(clones, doc.get("clone_id")),
        )
    except (IllegalTransition, AssignmentError) as exc:
        raise _map_error(exc) from exc
    await store.replace_assignment(outcome.assignment)
    if outcome.approval:
        await store.insert_approval(outcome.approval)
    return {
        "assignment": public_assignment(outcome.assignment),
        "approval": public_approval(outcome.approval) if outcome.approval else None,
    }
