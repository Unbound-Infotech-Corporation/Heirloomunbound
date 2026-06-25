"""Skills: webhook-based commands the Twin can invoke (lights, scripts, etc)."""
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deps import db, get_current_user
from utils import validate_outbound_url

router = APIRouter(prefix="/skills", tags=["skills"])


class SkillCreate(BaseModel):
    name: str
    description: str = ""
    webhook_url: str
    method: str = "POST"
    headers: dict = Field(default_factory=dict)
    body_template: str = ""
    enabled: bool = True


class SkillUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    webhook_url: Optional[str] = None
    method: Optional[str] = None
    headers: Optional[dict] = None
    body_template: Optional[str] = None
    enabled: Optional[bool] = None


@router.post("")
async def create_skill(payload: SkillCreate, user: dict = Depends(get_current_user)):
    skill_id = f"sk_{uuid.uuid4().hex[:10]}"
    doc = {
        "skill_id": skill_id,
        "user_id": user["user_id"],
        **payload.model_dump(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.skills.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("")
async def list_skills(user: dict = Depends(get_current_user)):
    cursor = db.skills.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1)
    return await cursor.to_list(length=100)


@router.patch("/{skill_id}")
async def update_skill(skill_id: str, payload: SkillUpdate, user: dict = Depends(get_current_user)):
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="No fields to update")
    res = await db.skills.update_one(
        {"skill_id": skill_id, "user_id": user["user_id"]}, {"$set": update}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Skill not found")
    doc = await db.skills.find_one({"skill_id": skill_id}, {"_id": 0})
    return doc


@router.delete("/{skill_id}")
async def delete_skill(skill_id: str, user: dict = Depends(get_current_user)):
    res = await db.skills.delete_one({"skill_id": skill_id, "user_id": user["user_id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"ok": True}


@router.post("/{skill_id}/invoke")
async def invoke_skill(skill_id: str, user: dict = Depends(get_current_user)):
    skill = await db.skills.find_one(
        {"skill_id": skill_id, "user_id": user["user_id"], "enabled": True}, {"_id": 0}
    )
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found or disabled")
    # Security (SEC-003): block SSRF — only public http(s) destinations
    validate_outbound_url(skill["webhook_url"])
    try:
        # follow_redirects=False prevents bouncing to internal targets via 30x
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            r = await client.request(
                skill.get("method", "POST"),
                skill["webhook_url"],
                headers=skill.get("headers") or {},
                content=skill.get("body_template") or None,
            )
        return {
            "ok": 200 <= r.status_code < 300,
            "status": r.status_code,
            "body": r.text[:2000],
        }
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": 0, "error": str(exc)}
