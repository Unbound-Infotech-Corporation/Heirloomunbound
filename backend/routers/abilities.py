"""Abilities API — browse the catalog and toggle each ability per user."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import abilities as ab
from deps import db, get_current_user

router = APIRouter(prefix="/abilities", tags=["abilities"])


async def _companion_connected(user_id: str) -> bool:
    dev = await db.companion_devices.find_one({"user_id": user_id, "revoked": False}, {"_id": 0})
    return dev is not None


@router.get("")
async def list_abilities(user: dict = Depends(get_current_user)):
    """Catalog merged with the user's enabled state + permission grants."""
    states = await ab.get_states(user["user_id"])
    companion = await _companion_connected(user["user_id"])
    items = []
    for a in ab.ABILITIES:
        s = states[a["id"]]
        items.append({
            "id": a["id"],
            "name": a["name"],
            "tagline": a["tagline"],
            "icon": a["icon"],
            "category": a["category"],
            "requires_companion": a["requires_companion"],
            "permissions": a["permissions"],
            "tool_count": len(a["tools"]),
            "enabled": s["enabled"],
            "granted_permissions": s["granted_permissions"],
        })
    return {"abilities": items, "companion_connected": companion}


class ToggleReq(BaseModel):
    granted_permissions: list[str] | None = None


@router.post("/{ability_id}/enable")
async def enable_ability(ability_id: str, payload: ToggleReq, user: dict = Depends(get_current_user)):
    a = ab.ABILITY_BY_ID.get(ability_id)
    if not a:
        raise HTTPException(status_code=404, detail="Unknown ability")
    required = {p["id"] for p in a["permissions"]}
    granted = set(payload.granted_permissions or [])
    if not required.issubset(granted):
        missing = sorted(required - granted)
        raise HTTPException(status_code=400, detail=f"Missing permission grant: {', '.join(missing)}")
    return await ab.set_state(user["user_id"], ability_id, True, sorted(required))


@router.post("/{ability_id}/disable")
async def disable_ability(ability_id: str, user: dict = Depends(get_current_user)):
    if ability_id not in ab.ABILITY_BY_ID:
        raise HTTPException(status_code=404, detail="Unknown ability")
    return await ab.set_state(user["user_id"], ability_id, False, [])
