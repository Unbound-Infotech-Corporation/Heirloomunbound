"""Owner lab dashboard API. Heirs receive 404. Off unless lab mode is on."""
from __future__ import annotations

import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deps import get_current_user
from lab_mode import (
    LabStore,
    default_store,
    lab_allowed,
    publish_report,
    record_chat_turn,
    report_dir,
    summarize_turns,
)

router = APIRouter(prefix="/lab", tags=["lab"])


class FeedbackReq(BaseModel):
    turn_id: str = Field(..., min_length=4, max_length=80)
    vote: str = Field(..., min_length=2, max_length=8)
    note: Optional[str] = Field(None, max_length=500)


def _gate(user: dict) -> LabStore:
    if not lab_allowed(
        audience=user.get("audience") or "owner",
        heir_surface=bool(user.get("heir_surface")),
    ):
        raise HTTPException(status_code=404, detail="Not found")
    return default_store()


@router.get("/status")
async def lab_status(user: dict = Depends(get_current_user)):
    _gate(user)
    return {"enabled": True, "storage": "local"}


@router.get("/turns")
async def lab_turns(user: dict = Depends(get_current_user), limit: int = 50):
    store = _gate(user)
    rows = store.read_all()
    cap = 20 if limit < 1 else min(limit, 200)
    page = rows[-cap:]
    return {"turns": page, "summary": summarize_turns(rows)}


@router.post("/feedback")
async def lab_feedback(body: FeedbackReq, user: dict = Depends(get_current_user)):
    store = _gate(user)
    try:
        row = store.set_feedback(body.turn_id, body.vote, body.note or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    return {"turn": row}


@router.post("/report")
async def lab_report_now(user: dict = Depends(get_current_user)):
    store = _gate(user)
    result = publish_report(store, report_dir())
    return {
        "path": result["path"],
        "day": result["day"],
        "github": result["github"],
    }


@router.get("/report")
async def lab_report_latest(user: dict = Depends(get_current_user)):
    _gate(user)
    folder = report_dir()
    files = sorted(folder.glob("lab-report-*.md")) if folder.is_dir() else []
    if not files:
        return {"path": "", "markdown": ""}
    latest = files[-1]
    return {"path": str(latest), "markdown": latest.read_text(encoding="utf-8")}


def note_chat_reply(
    user: dict,
    *,
    route: str,
    started: float,
    approval: Any = None,
    error: Optional[str] = None,
    audience: Optional[str] = None,
    model: str = "",
) -> Optional[str]:
    """One local row for a Twin, Clone, or Assist reply. Never raises."""
    try:
        from llm_provider import take_usage

        usage = take_usage()
        created = 0
        if isinstance(approval, dict) and approval.get("status") == "pending":
            created = 1
        return record_chat_turn(
            route=route,
            latency_ms=max(0, int((time.perf_counter() - started) * 1000)),
            model=str(usage.get("model") or model or ""),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            approvals_created=created,
            error=error,
            audience=audience if audience is not None else (user.get("audience") or "owner"),
            heir_surface=bool(user.get("heir_surface")),
            user_id=str(user.get("user_id") or ""),
        )
    except Exception:  # noqa: BLE001
        return None


def note_approval_decision(
    user: dict,
    decision: str,
    *,
    executed: bool,
    idempotent: bool,
) -> None:
    """Local counter for an approve or decline. Heirs never reach this router."""
    if idempotent:
        return
    approved = 1 if decision == "approve" and executed else 0
    declined = 1 if decision == "decline" else 0
    if not approved and not declined:
        return
    record_chat_turn(
        route="approval",
        latency_ms=0,
        approvals_approved=approved,
        approvals_declined=declined,
        audience=user.get("audience") or "owner",
        heir_surface=bool(user.get("heir_surface")),
        user_id=str(user.get("user_id") or ""),
    )
