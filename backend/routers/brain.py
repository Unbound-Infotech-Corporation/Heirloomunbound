"""Owner controls for the LAN brain. Heirs receive 404."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from brain_route import (
    brain_status,
    clear_caches,
    current_settings,
    load_saved_settings,
    prepare_owner_update,
    public_settings,
)
from deps import db, get_current_user
from presence_access import require_owner

router = APIRouter(prefix="/brain", tags=["brain"])


class BrainBody(BaseModel):
    url: str = ""
    model: str = ""
    token: Optional[str] = None
    clear_token: bool = False


@router.get("")
async def read_brain(user: dict = Depends(get_current_user)):
    require_owner(user)
    settings = await current_settings()
    status = brain_status()
    view = public_settings(
        settings,
        answered=str(status.get("answered") or ""),
        local_gpu=str(status.get("local_gpu") or "unknown"),
    )
    view["model_in_use"] = status.get("model_in_use") or view["model"]
    if status.get("answered_host"):
        view["answered_host"] = status["answered_host"]
    return view


@router.put("")
async def write_brain(body: BrainBody, user: dict = Depends(get_current_user)):
    require_owner(user)
    current = await load_saved_settings()
    payload = body.model_dump()
    if body.token is None:
        payload.pop("token", None)
    try:
        doc = prepare_owner_update(payload, current)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.brain_settings.replace_one({"_id": "box"}, doc, upsert=True)
    clear_caches()
    settings = await current_settings()
    return public_settings(settings)
