"""Sealed Letters — locked messages/letters the user writes today for delivery
later (on a specific date, when an heir reaches a target age, or at release).

A sealed letter cannot be edited after sealing. It becomes visible to the
designated heir only after the heir-release flow has unlocked it (or, for
date-triggered letters, after the delivery date has passed AND the heir was
released).
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deps import db, get_current_user

router = APIRouter(prefix="/letters", tags=["letters"])

ALLOWED_TRIGGERS = {"on_release", "on_date", "on_age"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LetterCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=50000)
    recipient_heir_id: Optional[str] = None
    recipient_name: Optional[str] = None
    trigger: str = "on_release"  # on_release | on_date | on_age
    delivery_date: Optional[str] = None   # ISO date when trigger=on_date
    delivery_age: Optional[int] = None    # int years when trigger=on_age


class LetterUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    recipient_heir_id: Optional[str] = None
    recipient_name: Optional[str] = None
    trigger: Optional[str] = None
    delivery_date: Optional[str] = None
    delivery_age: Optional[int] = None


def _validate_trigger(payload_trigger: str, delivery_date, delivery_age) -> None:
    if payload_trigger not in ALLOWED_TRIGGERS:
        raise HTTPException(status_code=400, detail=f"Invalid trigger; use one of {sorted(ALLOWED_TRIGGERS)}")
    if payload_trigger == "on_date" and not delivery_date:
        raise HTTPException(status_code=400, detail="delivery_date is required when trigger=on_date")
    if payload_trigger == "on_age":
        if delivery_age is None or delivery_age < 0 or delivery_age > 150:
            raise HTTPException(status_code=400, detail="delivery_age must be between 0 and 150 when trigger=on_age")


@router.post("")
async def create_letter(payload: LetterCreate, user: dict = Depends(get_current_user)):
    _validate_trigger(payload.trigger, payload.delivery_date, payload.delivery_age)

    if payload.recipient_heir_id:
        heir = await db.heirs.find_one(
            {"heir_id": payload.recipient_heir_id, "user_id": user["user_id"]}, {"_id": 0}
        )
        if not heir:
            raise HTTPException(status_code=404, detail="Recipient heir not found")

    letter_id = f"lt_{uuid.uuid4().hex[:12]}"
    doc = {
        "letter_id": letter_id,
        "user_id": user["user_id"],
        "title": payload.title.strip(),
        "body": payload.body,
        "recipient_heir_id": payload.recipient_heir_id,
        "recipient_name": (payload.recipient_name or "").strip() or None,
        "trigger": payload.trigger,
        "delivery_date": payload.delivery_date,
        "delivery_age": payload.delivery_age,
        "sealed": False,
        "delivered": False,
        "delivered_at": None,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    await db.sealed_letters.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("")
async def list_letters(user: dict = Depends(get_current_user)):
    cursor = db.sealed_letters.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1)
    return await cursor.to_list(length=500)


@router.get("/{letter_id}")
async def get_letter(letter_id: str, user: dict = Depends(get_current_user)):
    doc = await db.sealed_letters.find_one(
        {"letter_id": letter_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Letter not found")
    return doc


@router.patch("/{letter_id}")
async def update_letter(
    letter_id: str, payload: LetterUpdate, user: dict = Depends(get_current_user)
):
    existing = await db.sealed_letters.find_one(
        {"letter_id": letter_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Letter not found")
    if existing.get("sealed"):
        raise HTTPException(status_code=400, detail="Letter is sealed; unseal first to edit")

    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="No fields to update")

    merged_trigger = update.get("trigger", existing.get("trigger"))
    merged_date = update.get("delivery_date", existing.get("delivery_date"))
    merged_age = update.get("delivery_age", existing.get("delivery_age"))
    _validate_trigger(merged_trigger, merged_date, merged_age)

    if "recipient_heir_id" in update and update["recipient_heir_id"]:
        heir = await db.heirs.find_one(
            {"heir_id": update["recipient_heir_id"], "user_id": user["user_id"]}, {"_id": 0}
        )
        if not heir:
            raise HTTPException(status_code=404, detail="Recipient heir not found")

    update["updated_at"] = _now_iso()
    await db.sealed_letters.update_one(
        {"letter_id": letter_id, "user_id": user["user_id"]}, {"$set": update}
    )
    doc = await db.sealed_letters.find_one(
        {"letter_id": letter_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    return doc


@router.post("/{letter_id}/seal")
async def seal_letter(letter_id: str, user: dict = Depends(get_current_user)):
    res = await db.sealed_letters.update_one(
        {"letter_id": letter_id, "user_id": user["user_id"], "sealed": False},
        {"$set": {"sealed": True, "updated_at": _now_iso()}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Letter not found or already sealed")
    doc = await db.sealed_letters.find_one(
        {"letter_id": letter_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    return doc


@router.post("/{letter_id}/unseal")
async def unseal_letter(letter_id: str, user: dict = Depends(get_current_user)):
    existing = await db.sealed_letters.find_one(
        {"letter_id": letter_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Letter not found")
    if existing.get("delivered"):
        raise HTTPException(status_code=400, detail="Letter has already been delivered; cannot unseal")
    await db.sealed_letters.update_one(
        {"letter_id": letter_id, "user_id": user["user_id"]},
        {"$set": {"sealed": False, "updated_at": _now_iso()}},
    )
    doc = await db.sealed_letters.find_one(
        {"letter_id": letter_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    return doc


@router.delete("/{letter_id}")
async def delete_letter(letter_id: str, user: dict = Depends(get_current_user)):
    existing = await db.sealed_letters.find_one(
        {"letter_id": letter_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Letter not found")
    if existing.get("delivered"):
        raise HTTPException(status_code=400, detail="Cannot delete a delivered letter")
    await db.sealed_letters.delete_one(
        {"letter_id": letter_id, "user_id": user["user_id"]}
    )
    return {"ok": True}
