"""Personas — switchable "modes" for the same twin.

Use cases:
  - "Family Mode" — warmth high, archive includes all memories, safe-topics = []
  - "Professional Mode" — formal, only career entries, no personal memories
  - "Customer Support Mode" — answers about products only, brand voice
  - "Late-Night Mode" — softer, philosophical

Each persona contributes an additional instruction block to the twin's system
prompt and can scope which archive entry types are visible. At most one persona
is "active" at any time (user.active_persona_id). Default = none = full archive.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deps import db, get_current_user

router = APIRouter(prefix="/personas", tags=["personas"])


VALID_ENTRY_TYPES = {"memory", "story", "value", "advice", "quote", "chapter", "voice", "import"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PersonaCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    description: str = ""
    system_addendum: str = ""  # appended to the twin's system prompt
    archive_types: list[str] = Field(default_factory=list)  # empty = all types
    extra_safe_topics: list[str] = Field(default_factory=list)


class PersonaUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    system_addendum: Optional[str] = None
    archive_types: Optional[list[str]] = None
    extra_safe_topics: Optional[list[str]] = None


def _clean_payload(payload: dict) -> dict:
    cleaned = {}
    for k, v in payload.items():
        if v is None:
            continue
        if k == "archive_types":
            cleaned[k] = [t for t in (v or []) if t in VALID_ENTRY_TYPES][:10]
        elif k == "extra_safe_topics":
            cleaned[k] = [s.strip()[:80] for s in (v or []) if s and s.strip()][:25]
        elif k in ("name", "description", "system_addendum"):
            limit = {"name": 60, "description": 300, "system_addendum": 2000}[k]
            cleaned[k] = str(v).strip()[:limit]
    return cleaned


@router.get("")
async def list_personas(user: dict = Depends(get_current_user)):
    cursor = db.personas.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1)
    items = await cursor.to_list(length=50)
    active_id = user.get("active_persona_id")
    for p in items:
        p["active"] = (p.get("persona_id") == active_id)
    return {"personas": items, "active_persona_id": active_id}


@router.post("")
async def create_persona(payload: PersonaCreate, user: dict = Depends(get_current_user)):
    persona_id = f"per_{uuid.uuid4().hex[:12]}"
    doc = {
        "persona_id": persona_id,
        "user_id": user["user_id"],
        "name": payload.name.strip()[:60],
        "description": (payload.description or "").strip()[:300],
        "system_addendum": (payload.system_addendum or "").strip()[:2000],
        "archive_types": [t for t in (payload.archive_types or []) if t in VALID_ENTRY_TYPES][:10],
        "extra_safe_topics": [s.strip()[:80] for s in (payload.extra_safe_topics or []) if s and s.strip()][:25],
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    await db.personas.insert_one(dict(doc))
    return doc


@router.patch("/{persona_id}")
async def update_persona(
    persona_id: str, payload: PersonaUpdate, user: dict = Depends(get_current_user)
):
    update = _clean_payload(payload.model_dump())
    if not update:
        raise HTTPException(status_code=400, detail="No fields to update")
    update["updated_at"] = _now_iso()
    res = await db.personas.update_one(
        {"persona_id": persona_id, "user_id": user["user_id"]}, {"$set": update}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Persona not found")
    doc = await db.personas.find_one({"persona_id": persona_id}, {"_id": 0})
    return doc


@router.delete("/{persona_id}")
async def delete_persona(persona_id: str, user: dict = Depends(get_current_user)):
    res = await db.personas.delete_one({"persona_id": persona_id, "user_id": user["user_id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Persona not found")
    # If this was the active persona, clear it
    if user.get("active_persona_id") == persona_id:
        await db.users.update_one(
            {"user_id": user["user_id"]}, {"$set": {"active_persona_id": None}}
        )
    return {"ok": True}


@router.post("/{persona_id}/activate")
async def activate_persona(persona_id: str, user: dict = Depends(get_current_user)):
    p = await db.personas.find_one(
        {"persona_id": persona_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    if not p:
        raise HTTPException(status_code=404, detail="Persona not found")
    await db.users.update_one(
        {"user_id": user["user_id"]}, {"$set": {"active_persona_id": persona_id}}
    )
    return {"ok": True, "active_persona_id": persona_id}


@router.post("/deactivate")
async def deactivate(user: dict = Depends(get_current_user)):
    await db.users.update_one(
        {"user_id": user["user_id"]}, {"$set": {"active_persona_id": None}}
    )
    return {"ok": True, "active_persona_id": None}


# ---------------- Helper used by twin.py ----------------
async def get_active_persona(user_id: str, user: dict) -> Optional[dict]:
    active_id = user.get("active_persona_id")
    if not active_id:
        return None
    return await db.personas.find_one(
        {"persona_id": active_id, "user_id": user_id}, {"_id": 0}
    )
