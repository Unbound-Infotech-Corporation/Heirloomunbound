"""Owner observer API. Heirs receive 404. Clips are never returned."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deps import get_current_user
from observer_prompt import WATCHED_SOURCE
from observer_store import (
    ObserverStore,
    clips_enabled,
    observer_dir,
    observer_enabled,
    status_public,
)
from owner_pairing import is_owner_audience
from vr_mode import accept_gaze, clamp_vr_prefs

router = APIRouter(prefix="/observer", tags=["observer"])


class FeedbackReq(BaseModel):
    note_id: str = Field(..., min_length=4, max_length=80)
    vote: str = Field(..., min_length=2, max_length=32)


class GazeArea(BaseModel):
    model_config = {"extra": "ignore"}

    area: str = Field(..., min_length=2, max_length=32)
    dwell_ms: int = Field(..., ge=0, le=30 * 60 * 1000)


class GazeReq(BaseModel):
    """Attention summaries only. Extra fields, including a raw stream, are ignored."""

    model_config = {"extra": "ignore"}

    summaries: list[GazeArea] = Field(default_factory=list, max_length=8)


def _gate(user: dict) -> ObserverStore:
    if user.get("heir_surface") or not is_owner_audience(user.get("audience") or "owner"):
        raise HTTPException(status_code=404, detail="Not found")
    return ObserverStore(observer_dir())


@router.get("/status")
async def observer_status(user: dict = Depends(get_current_user)):
    store = _gate(user)
    payload = status_public(store)
    payload["source_label"] = WATCHED_SOURCE
    payload["clips_enabled"] = bool(clips_enabled()) and bool(payload["enabled"])
    return payload


@router.post("/pause")
async def observer_pause(user: dict = Depends(get_current_user)):
    store = _gate(user)
    if not observer_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    state = store.set_paused(True, "web")
    return {"paused": True, "reason": state.get("reason") or "web"}


@router.post("/resume")
async def observer_resume(user: dict = Depends(get_current_user)):
    store = _gate(user)
    if not observer_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    store.set_paused(False, "")
    return {"paused": False}


@router.get("/digest")
async def observer_digest(user: dict = Depends(get_current_user)):
    store = _gate(user)
    if not observer_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    return {
        "day": datetime.now(timezone.utc).date().isoformat(),
        "notes": store.digest_notes(),
        "markdown": store.digest_section(),
    }


@router.post("/vr-gaze")
async def observer_vr_gaze(body: GazeReq, user: dict = Depends(get_current_user)):
    """Owner opt-in attention summary. Heirs get 404. A pause writes nothing."""
    store = _gate(user)
    prefs = clamp_vr_prefs(user.get("studio_vr"))
    paused = bool(store.read_state().get("paused")) if observer_enabled() else False
    decision = accept_gaze(
        [item.model_dump() for item in body.summaries],
        audience=user.get("audience") or "owner",
        heir_surface=bool(user.get("heir_surface")),
        gaze_enabled=bool(prefs["gaze_enabled"]),
        paused=paused,
        observer_on=observer_enabled(),
    )
    if decision.get("status") == 404:
        raise HTTPException(status_code=404, detail="Not found")
    if not decision.get("stored"):
        return {"stored": False, "reason": decision.get("reason") or "skipped"}
    result = store.add_gaze_note(decision.get("note"))
    note = result.get("note")
    return {
        "stored": bool(result.get("stored")),
        "reason": result.get("reason") or decision.get("reason"),
        "note": {"id": note.get("id"), "source": note.get("source"), "text": note.get("text")} if note else None,
    }


@router.post("/feedback")
async def observer_feedback(body: FeedbackReq, user: dict = Depends(get_current_user)):
    store = _gate(user)
    if not observer_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    try:
        result = store.apply_feedback(body.note_id, body.vote)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Not found") from exc
    return {"note": result}
