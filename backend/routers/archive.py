"""Archive (memories / stories / values / advice / quotes / chapters) CRUD."""
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from deps import db, get_current_user

router = APIRouter(prefix="/archive", tags=["archive"])

EntryType = Literal["memory", "story", "value", "advice", "quote", "chapter", "voice", "import"]


class EntryCreate(BaseModel):
    type: EntryType
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)
    audio_url: Optional[str] = None
    source: Optional[str] = None  # e.g. "interviewer", "voice_journal", "manual"


class EntryUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[list[str]] = None


@router.post("")
async def create_entry(payload: EntryCreate, user: dict = Depends(get_current_user)):
    entry_id = f"ent_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "entry_id": entry_id,
        "user_id": user["user_id"],
        "type": payload.type,
        "title": payload.title,
        "content": payload.content,
        "tags": payload.tags,
        "audio_url": payload.audio_url,
        "source": payload.source or "manual",
        "created_at": now,
        "updated_at": now,
    }
    await db.entries.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("")
async def list_entries(
    type: Optional[EntryType] = None,
    q: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    user: dict = Depends(get_current_user),
):
    query: dict = {"user_id": user["user_id"]}
    if type:
        query["type"] = type
    if q:
        query["$or"] = [
            {"title": {"$regex": q, "$options": "i"}},
            {"content": {"$regex": q, "$options": "i"}},
            {"tags": {"$regex": q, "$options": "i"}},
        ]
    cursor = db.entries.find(query, {"_id": 0}).sort("created_at", -1).limit(limit)
    return await cursor.to_list(length=limit)


@router.get("/{entry_id}")
async def get_entry(entry_id: str, user: dict = Depends(get_current_user)):
    doc = await db.entries.find_one(
        {"entry_id": entry_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Entry not found")
    return doc


@router.patch("/{entry_id}")
async def update_entry(entry_id: str, payload: EntryUpdate, user: dict = Depends(get_current_user)):
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="No fields to update")
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    res = await db.entries.update_one(
        {"entry_id": entry_id, "user_id": user["user_id"]}, {"$set": update}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Entry not found")
    doc = await db.entries.find_one({"entry_id": entry_id}, {"_id": 0})
    return doc


@router.delete("/{entry_id}")
async def delete_entry(entry_id: str, user: dict = Depends(get_current_user)):
    res = await db.entries.delete_one({"entry_id": entry_id, "user_id": user["user_id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"ok": True}
