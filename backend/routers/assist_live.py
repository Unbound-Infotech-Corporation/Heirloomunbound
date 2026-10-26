"""Owner Assist-live API. Heirs and family receive 404.

The microphone, the screen summary, and PC tools stay with the owner.
Pause is the existing Observer switch.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from assist_live import load_state, mic_transcript, reduce_mute, reduce_ptt, reduce_settings, save_state
from deps import get_current_user
from observer_store import observer_dir, observer_enabled
from owner_pairing import is_owner_audience

router = APIRouter(prefix="/assist/live", tags=["assist-live"])


class SettingsReq(BaseModel):
    wake_phrase: str | None = Field(default=None, max_length=80)
    twin_name: str | None = Field(default=None, max_length=80)
    proactive: bool | None = None


class PttReq(BaseModel):
    held: bool = True


class MuteReq(BaseModel):
    muted: bool = True


class ConfirmReq(BaseModel):
    id: str = Field(default="", max_length=80)


def _owner(user: dict) -> None:
    if user.get("heir_surface") or not is_owner_audience(user.get("audience") or "owner"):
        raise HTTPException(status_code=404, detail="Not found")


@router.get("")
async def assist_live_poll(user: dict = Depends(get_current_user)):
    _owner(user)
    if not observer_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    from assist_live_runner import advance_for_user

    return await advance_for_user(user)


@router.put("/settings")
async def assist_live_settings(body: SettingsReq, user: dict = Depends(get_current_user)):
    _owner(user)
    if not observer_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    root = observer_dir()
    state = reduce_settings(load_state(root), body.model_dump())
    save_state(state, root)
    from assist_live import public_view

    return public_view(state)


@router.post("/ptt")
async def assist_live_ptt(body: PttReq, user: dict = Depends(get_current_user)):
    _owner(user)
    if not observer_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    from time import time

    root = observer_dir()
    state = reduce_ptt(load_state(root), now=time(), held=body.held)
    save_state(state, root)
    return {"ptt": bool(state.get("ptt_until"))}


@router.post("/mute")
async def assist_live_mute(body: MuteReq, user: dict = Depends(get_current_user)):
    _owner(user)
    if not observer_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    root = observer_dir()
    state = reduce_mute(load_state(root), body.muted)
    save_state(state, root)
    return {"muted": bool(state.get("muted"))}


@router.get("/mic")
async def assist_live_mic(user: dict = Depends(get_current_user)):
    """Owner microphone words already stored by Observer. Nothing new is written."""
    _owner(user)
    if not observer_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    from box_pause import merged_state
    from observer_store import ObserverStore

    root = observer_dir()
    paused = bool(merged_state(ObserverStore(root).read_state()).get("paused"))
    return mic_transcript(root, paused=paused)


@router.post("/confirm")
async def assist_live_confirm(body: ConfirmReq, user: dict = Depends(get_current_user)):
    _owner(user)
    if not observer_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    from assist_live_runner import advance_for_user

    return await advance_for_user(user, clicked_id=body.id)


@router.post("/decline")
async def assist_live_decline(body: ConfirmReq, user: dict = Depends(get_current_user)):
    _owner(user)
    if not observer_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    from assist_live_runner import advance_for_user

    return await advance_for_user(user, declined_id=body.id)


@router.get("/audio/{audio_id}")
async def assist_live_audio(audio_id: str, user: dict = Depends(get_current_user)):
    _owner(user)
    if not observer_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    from assist_live_runner import take_wav

    wav = take_wav(observer_dir(), audio_id)
    if not wav:
        raise HTTPException(status_code=404, detail="Not found")
    return Response(content=wav, media_type="audio/wav")
