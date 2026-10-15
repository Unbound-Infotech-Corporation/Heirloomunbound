"""Owner observer API. Heirs receive 404. Clips and raw audio are never returned."""
from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
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


class AudioToggleReq(BaseModel):
    """Turn one stream off without touching the other. Omitted fields stay as they are."""

    system: bool | None = None
    mic: bool | None = None


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


@router.put("/audio")
async def observer_audio_toggles(body: AudioToggleReq, user: dict = Depends(get_current_user)):
    """Separate on/off switches for system audio and the microphone."""
    store = _gate(user)
    if not observer_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    store.set_audio_toggles(system=body.system, mic=body.mic)
    return status_public(store)


@router.post("/audio/{source}")
async def observer_audio_chunk(source: str, request: Request, user: dict = Depends(get_current_user)):
    """Companion PCM for one stream. The body is deleted after the daemon reads it."""
    store = _gate(user)
    if not observer_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    if source not in {"system", "mic"}:
        raise HTTPException(status_code=404, detail="Not found")
    from box_pause import merged_state
    from observer_audio import accept_companion_chunk, spool_dir
    from observer_privacy import pause_decision

    paused, _reason = pause_decision(
        merged_state(store.read_state()),
        now=datetime.now().astimezone(),
        quiet_hours=os.environ.get("OBSERVER_QUIET_HOURS", ""),
        hotkey_phrase=os.environ.get("OBSERVER_HOTKEY_PHRASE", "HEIRLOOM PAUSE"),
    )
    enabled = store.audio_toggle("audio_system" if source == "system" else "audio_mic")
    body = await request.body()
    result = accept_companion_chunk(
        source=source,
        pcm=body,
        paused=paused,
        enabled=enabled,
        spool=spool_dir(),
    )
    if result["reason"] == "too-large":
        raise HTTPException(status_code=413, detail="Audio window is too long")
    if result["reason"] in {"empty", "alignment"}:
        raise HTTPException(status_code=400, detail="PCM must be 16-bit little-endian mono")
    if not result["accepted"]:
        raise HTTPException(status_code=409, detail=result["reason"])
    return {"accepted": True, "source": source, "bytes": result["bytes"]}


@router.post("/pause")
async def observer_pause(user: dict = Depends(get_current_user)):
    store = _gate(user)
    if not observer_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    from box_pause import share_pause

    share_pause(True, "web")
    state = store.set_paused(True, "web")
    return {"paused": True, "reason": state.get("reason") or "web"}


@router.post("/resume")
async def observer_resume(user: dict = Depends(get_current_user)):
    store = _gate(user)
    if not observer_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    from box_pause import share_pause

    share_pause(False, "")
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
