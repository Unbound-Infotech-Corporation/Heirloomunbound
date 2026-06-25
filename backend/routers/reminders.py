"""Reminders & to-dos for the Live Assistant layer."""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from deps import db, get_current_user

router = APIRouter(prefix="/reminders", tags=["reminders"])


class ReminderCreate(BaseModel):
    text: str
    due_at: Optional[str] = None  # ISO datetime
    notes: Optional[str] = None


class ReminderUpdate(BaseModel):
    text: Optional[str] = None
    due_at: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None  # open | done | snoozed
    snooze_until: Optional[str] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("")
async def create_reminder(payload: ReminderCreate, user: dict = Depends(get_current_user)):
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="Reminder text is required")
    rid = f"rem_{uuid.uuid4().hex[:12]}"
    doc = {
        "reminder_id": rid,
        "user_id": user["user_id"],
        "text": payload.text.strip(),
        "notes": (payload.notes or "").strip() or None,
        "due_at": payload.due_at,
        "status": "open",
        "snooze_until": None,
        "completed_at": None,
        "delivered_at": None,
        "created_at": _now_iso(),
    }
    await db.reminders.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("")
async def list_reminders(
    status: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    query: dict = {"user_id": user["user_id"]}
    if status:
        query["status"] = status
    cursor = db.reminders.find(query, {"_id": 0}).sort([("due_at", 1), ("created_at", -1)]).limit(500)
    return await cursor.to_list(length=500)


@router.get("/today")
async def today(user: dict = Depends(get_current_user)):
    """Reminders due before end of today (in UTC for simplicity) or already overdue."""
    now = datetime.now(timezone.utc)
    end_of_day = now.replace(hour=23, minute=59, second=59).isoformat()
    cursor = db.reminders.find(
        {
            "user_id": user["user_id"],
            "status": "open",
            "$or": [{"due_at": None}, {"due_at": {"$lte": end_of_day}}],
        },
        {"_id": 0},
    ).sort([("due_at", 1)])
    items = await cursor.to_list(length=200)
    overdue = [i for i in items if i.get("due_at") and i["due_at"] < now.isoformat()]
    today_due = [i for i in items if i.get("due_at") and now.isoformat() <= i["due_at"] <= end_of_day]
    no_date = [i for i in items if not i.get("due_at")]
    return {"overdue": overdue, "today": today_due, "no_date": no_date}


@router.patch("/{reminder_id}")
async def update_reminder(reminder_id: str, payload: ReminderUpdate, user: dict = Depends(get_current_user)):
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="No fields to update")
    if update.get("status") == "done" and "completed_at" not in update:
        update["completed_at"] = _now_iso()
    res = await db.reminders.update_one(
        {"reminder_id": reminder_id, "user_id": user["user_id"]}, {"$set": update}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Reminder not found")
    doc = await db.reminders.find_one({"reminder_id": reminder_id}, {"_id": 0})
    return doc


@router.post("/{reminder_id}/complete")
async def complete_reminder(reminder_id: str, user: dict = Depends(get_current_user)):
    res = await db.reminders.update_one(
        {"reminder_id": reminder_id, "user_id": user["user_id"]},
        {"$set": {"status": "done", "completed_at": _now_iso()}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Reminder not found")
    return {"ok": True}


@router.delete("/{reminder_id}")
async def delete_reminder(reminder_id: str, user: dict = Depends(get_current_user)):
    res = await db.reminders.delete_one(
        {"reminder_id": reminder_id, "user_id": user["user_id"]}
    )
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Reminder not found")
    return {"ok": True}
