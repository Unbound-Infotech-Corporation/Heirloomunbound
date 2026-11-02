"""Owner controls for the LAN brain. Heirs receive 404."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from brain_council import configured_strategy, note_health
from brain_route import (
    brain_status,
    clear_caches,
    current_settings,
    load_saved_settings,
    prepare_owner_update,
    public_settings,
)
from odysseus_client import current_odysseus, deep_research_enabled, merge_owner_extras, public_odysseus
from deps import db, get_current_user
from presence_access import require_owner

router = APIRouter(prefix="/brain", tags=["brain"])


class BrainBody(BaseModel):
    url: str = ""
    model: str = ""
    token: Optional[str] = None
    clear_token: bool = False
    strategy: Optional[str] = None
    odysseus_enabled: Optional[bool] = None
    odysseus_url: Optional[str] = None
    odysseus_token: Optional[str] = None
    odysseus_deep_research: Optional[bool] = None
    clear_odysseus_token: bool = False


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
    odysseus = await current_odysseus()
    strategy = await configured_strategy()
    odysseus_view = public_odysseus(odysseus)
    saved = await load_saved_settings()
    odysseus_view["deep_research"] = deep_research_enabled(saved if isinstance(saved, dict) else None)
    view["strategy"] = strategy
    view["odysseus"] = odysseus_view
    answer = dict(status.get("answer") or {})
    answer["strategy"] = strategy
    view["answer"] = answer
    note_health(strategy, odysseus_view, answer)
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
        doc = merge_owner_extras(doc, payload, current)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.brain_settings.replace_one({"_id": "box"}, doc, upsert=True)
    clear_caches()
    return await read_brain(user)
