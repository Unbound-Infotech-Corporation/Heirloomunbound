"""Heir management — designate people who will inherit access to the Twin."""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from deps import db, get_current_user

router = APIRouter(prefix="/heirs", tags=["heirs"])


class HeirCreate(BaseModel):
    name: str
    email: EmailStr
    relationship: str = ""
    note: str = ""
    release_on: Optional[str] = None  # ISO date, optional


class HeirUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    relationship: Optional[str] = None
    note: Optional[str] = None
    release_on: Optional[str] = None
    released: Optional[bool] = None


@router.post("")
async def add_heir(payload: HeirCreate, user: dict = Depends(get_current_user)):
    heir_id = f"hr_{uuid.uuid4().hex[:10]}"
    doc = {
        "heir_id": heir_id,
        "user_id": user["user_id"],
        "name": payload.name,
        "email": payload.email,
        "relationship": payload.relationship,
        "note": payload.note,
        "release_on": payload.release_on,
        "released": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.heirs.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("")
async def list_heirs(user: dict = Depends(get_current_user)):
    cursor = db.heirs.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1)
    return await cursor.to_list(length=100)


@router.patch("/{heir_id}")
async def update_heir(heir_id: str, payload: HeirUpdate, user: dict = Depends(get_current_user)):
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="No fields to update")
    res = await db.heirs.update_one(
        {"heir_id": heir_id, "user_id": user["user_id"]}, {"$set": update}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Heir not found")
    doc = await db.heirs.find_one({"heir_id": heir_id}, {"_id": 0})
    return doc


@router.delete("/{heir_id}")
async def delete_heir(heir_id: str, user: dict = Depends(get_current_user)):
    res = await db.heirs.delete_one({"heir_id": heir_id, "user_id": user["user_id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Heir not found")
    return {"ok": True}
