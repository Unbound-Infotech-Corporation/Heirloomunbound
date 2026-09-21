"""Owner-only named Clones under the twin."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from assistants import (
    DEFAULT_ASSISTANTS,
    KNOWN_TOOLS,
    clean_tools,
    public_assistant,
    slugify_name,
    speak_as_for_tools,
)
from deps import db, get_current_user

router = APIRouter(prefix="/clones", tags=["clones"])

MAX_ASSISTANTS = 12


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _owner_gate(user: dict) -> None:
    if user.get("account_status") == "refunded":
        raise HTTPException(status_code=403, detail="account_inactive")


class AssistantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    role: str = ""
    tools_allowlist: list[str] = Field(default_factory=list)
    enabled: bool = True
    speak_as: Optional[str] = None


class AssistantUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=60)
    role: Optional[str] = None
    tools_allowlist: Optional[list[str]] = None
    enabled: Optional[bool] = None
    speak_as: Optional[str] = None


def _doc_from_defaults(user_id: str, spec: dict) -> dict:
    tools = clean_tools(spec.get("tools_allowlist"))
    cid = f"cln_{uuid.uuid4().hex[:12]}"
    return {
        "assistant_id": cid,
        "clone_id": cid,
        "user_id": user_id,
        "slug": spec.get("slug") or slugify_name(spec["name"]),
        "name": spec["name"][:60],
        "role": (spec.get("role") or "")[:400],
        "tools_allowlist": tools,
        "enabled": bool(spec.get("enabled", True)),
        "speak_as": speak_as_for_tools(tools, spec.get("speak_as")),
        "seeded": True,
        "created_at": _now(),
        "updated_at": _now(),
    }


async def list_for_user(user_id: str, *, seed: bool = True) -> list[dict]:
    cursor = db.twin_assistants.find({"user_id": user_id}, {"_id": 0}).sort("created_at", 1)
    items = await cursor.to_list(length=MAX_ASSISTANTS)
    if items or not seed:
        return items
    docs = [_doc_from_defaults(user_id, spec) for spec in DEFAULT_ASSISTANTS]
    if docs:
        await db.twin_assistants.insert_many([dict(d) for d in docs])
    return docs


@router.get("")
async def list_assistants(user: dict = Depends(get_current_user)):
    _owner_gate(user)
    items = await list_for_user(user["user_id"])
    clones = [public_assistant(a) for a in items]
    return {
        "clones": clones,
        "tools": list(KNOWN_TOOLS),
        "max": MAX_ASSISTANTS,
    }


@router.post("")
async def create_assistant(payload: AssistantCreate, user: dict = Depends(get_current_user)):
    _owner_gate(user)
    existing = await db.twin_assistants.count_documents({"user_id": user["user_id"]})
    if existing >= MAX_ASSISTANTS:
        raise HTTPException(status_code=400, detail=f"At most {MAX_ASSISTANTS} clones")
    tools = clean_tools(payload.tools_allowlist)
    cid = f"cln_{uuid.uuid4().hex[:12]}"
    doc = {
        "assistant_id": cid,
        "clone_id": cid,
        "user_id": user["user_id"],
        "slug": slugify_name(payload.name),
        "name": payload.name.strip()[:60],
        "role": (payload.role or "").strip()[:400],
        "tools_allowlist": tools,
        "enabled": bool(payload.enabled),
        "speak_as": speak_as_for_tools(tools, payload.speak_as),
        "seeded": False,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.twin_assistants.insert_one(dict(doc))
    return public_assistant(doc)


def _owned_filter(clone_id: str, user_id: str) -> dict:
    return {
        "user_id": user_id,
        "$or": [{"clone_id": clone_id}, {"assistant_id": clone_id}],
    }


@router.patch("/{clone_id}")
async def update_assistant(
    clone_id: str, payload: AssistantUpdate, user: dict = Depends(get_current_user)
):
    _owner_gate(user)
    update: dict = {}
    if payload.name is not None:
        name = payload.name.strip()[:60]
        if not name:
            raise HTTPException(status_code=400, detail="Name is required")
        update["name"] = name
        update["slug"] = slugify_name(name)
    if payload.role is not None:
        update["role"] = payload.role.strip()[:400]
    if payload.tools_allowlist is not None:
        update["tools_allowlist"] = clean_tools(payload.tools_allowlist)
    if payload.enabled is not None:
        update["enabled"] = bool(payload.enabled)
    owned = _owned_filter(clone_id, user["user_id"])
    if payload.speak_as is not None or "tools_allowlist" in update:
        current = await db.twin_assistants.find_one(owned, {"_id": 0})
        if not current:
            raise HTTPException(status_code=404, detail="Clone not found")
        tools = update.get("tools_allowlist", current.get("tools_allowlist") or [])
        update["speak_as"] = speak_as_for_tools(tools, payload.speak_as or current.get("speak_as"))
    if not update:
        raise HTTPException(status_code=400, detail="No fields to update")
    update["updated_at"] = _now()
    res = await db.twin_assistants.update_one(owned, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Clone not found")
    doc = await db.twin_assistants.find_one(owned, {"_id": 0})
    return public_assistant(doc)


@router.delete("/{clone_id}")
async def delete_assistant(clone_id: str, user: dict = Depends(get_current_user)):
    _owner_gate(user)
    res = await db.twin_assistants.delete_one(_owned_filter(clone_id, user["user_id"]))
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Clone not found")
    return {"ok": True}
