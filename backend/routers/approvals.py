"""Owner-only approvals. Nothing outbound runs until the owner approves."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from assignment_store import MongoAssignmentStore
from assignments import (
    ApprovalFinal,
    AssignmentError,
    IllegalTransition,
    InMemoryConnector,
    assignments_allowed,
    decide_approval,
    public_approval,
    public_assignment,
)
from deps import get_current_user

router = APIRouter(prefix="/approvals", tags=["approvals"])


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


async def _decide(user: dict, approval_id: str, decision: str) -> dict:
    _owner_gate(user)
    store = _store()
    approval = await store.get_approval(user["user_id"], approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    assignment = await store.get_assignment(user["user_id"], approval["assignment_id"])
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    try:
        outcome = decide_approval(
            approval,
            assignment,
            decision,
            now=_now(),
            connector=InMemoryConnector(),
        )
    except ApprovalFinal as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (AssignmentError, IllegalTransition) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not outcome.idempotent:
        await store.replace_approval(outcome.approval)
        await store.replace_assignment(outcome.assignment)
    return {
        "approval": public_approval(outcome.approval),
        "assignment": public_assignment(outcome.assignment),
        "idempotent": outcome.idempotent,
        "executed": outcome.executed,
    }


@router.get("")
async def list_approvals(
    user: dict = Depends(get_current_user),
    status: str = "pending",
    assignment_id: str | None = None,
):
    _owner_gate(user)
    status_filter = None if status == "all" else status
    rows = await _store().list_approvals(
        user["user_id"],
        status=status_filter,
        assignment_id=assignment_id,
    )
    return {"approvals": [public_approval(row) for row in rows]}


@router.post("/{approval_id}/approve")
async def approve(approval_id: str, user: dict = Depends(get_current_user)):
    return await _decide(user, approval_id, "approve")


@router.post("/{approval_id}/decline")
async def decline(approval_id: str, user: dict = Depends(get_current_user)):
    return await _decide(user, approval_id, "decline")
