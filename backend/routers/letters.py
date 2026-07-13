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

from emergentintegrations.llm.chat import LlmChat, StreamDone, TextDelta, UserMessage
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deps import EMERGENT_LLM_KEY, db, get_current_user

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


# ----------------------------- Twin-assisted writing -----------------------------
class AssistReq(BaseModel):
    notes: str = Field(min_length=1, max_length=4000)
    recipient_name: Optional[str] = None
    occasion: Optional[str] = None  # e.g. "18th birthday", "wedding day"
    tone: Optional[str] = None      # e.g. "warm", "funny", "solemn"


@router.post("/assist")
async def assist(payload: AssistReq, user: dict = Depends(get_current_user)):
    """Draft a heartfelt letter in the owner's own voice from a few notes.

    Pulls a little of the owner's archive so the voice rings true. Returns a
    suggested title + body for the owner to edit before sealing — never saved
    automatically."""
    # A light voice sample from the owner's own writing.
    voice_docs = await db.entries.find(
        {"user_id": user["user_id"], "content": {"$exists": True, "$ne": ""}}, {"_id": 0, "content": 1}
    ).sort("created_at", -1).limit(4).to_list(length=4)
    voice_blob = "\n---\n".join((d.get("content") or "")[:400] for d in voice_docs) or "(no writing samples yet)"

    recipient = (payload.recipient_name or "the recipient").strip()
    occasion = f" for their {payload.occasion.strip()}" if payload.occasion else ""
    tone = (payload.tone or "warm and sincere").strip()

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"letter_{uuid.uuid4().hex[:8]}",
        system_message=(
            f"You help {user.get('name', 'the writer')} write a deeply personal sealed letter to {recipient}{occasion}, "
            f"to be delivered in the future. Write it in FIRST PERSON as the writer, matching the voice in their "
            f"writing samples below. Tone: {tone}. Draw ONLY on the notes and samples — invent no facts. "
            f"150–300 words, honest and specific, no greeting-card clichés. "
            f'Return STRICT JSON: {{"title": "<short title>", "body": "<the letter>"}}. No markdown, no preamble.\n\n'
            f"=== The writer's voice (samples) ===\n{voice_blob}"
        ),
    ).with_model("anthropic", "claude-sonnet-4-6")

    text = ""
    async for ev in chat.stream_message(UserMessage(text=f"Notes for the letter:\n{payload.notes}")):
        if isinstance(ev, TextDelta):
            text += ev.content
        elif isinstance(ev, StreamDone):
            break
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"): text.rfind("}") + 1]
    import json
    try:
        data = json.loads(text)
        title = str(data.get("title", "")).strip() or "A letter for you"
        body = str(data.get("body", "")).strip()
    except Exception:  # noqa: BLE001
        title, body = "A letter for you", text
    if not body:
        raise HTTPException(status_code=502, detail="Couldn't draft the letter — try again.")
    return {"title": title, "body": body}


# ----------------------------- Auto-delivery scheduler -----------------------------
async def deliver_due_letters(user_id: Optional[str] = None) -> dict:
    """Deliver sealed, date-triggered letters whose date has arrived.

    Emails the letter to the linked heir and marks it delivered. Scoped to one
    user when user_id is given (manual trigger), otherwise scans everyone
    (background scheduler). Letters without a linked heir email are skipped.
    """
    from email_service import send_letter_email

    now_iso = _now_iso()
    query = {
        "sealed": True,
        "delivered": False,
        "trigger": "on_date",
        "delivery_date": {"$lte": now_iso},
    }
    if user_id:
        query["user_id"] = user_id

    due = await db.sealed_letters.find(query, {"_id": 0}).to_list(length=500)
    delivered, skipped = 0, 0
    for lt in due:
        heir = None
        if lt.get("recipient_heir_id"):
            heir = await db.heirs.find_one(
                {"heir_id": lt["recipient_heir_id"], "user_id": lt["user_id"]}, {"_id": 0}
            )
        to_email = (heir or {}).get("email")
        if not to_email:
            skipped += 1
            continue
        owner = await db.users.find_one({"user_id": lt["user_id"]}, {"_id": 0, "name": 1}) or {}
        try:
            res = await send_letter_email(
                to=to_email,
                recipient_name=(heir or {}).get("name") or lt.get("recipient_name") or "",
                owner_name=owner.get("name", ""),
                title=lt.get("title", "A letter for you"),
                body=lt.get("body", ""),
            )
            if res.get("skipped"):  # email service not configured — don't mark delivered
                skipped += 1
                continue
        except Exception:  # noqa: BLE001
            skipped += 1
            continue
        await db.sealed_letters.update_one(
            {"letter_id": lt["letter_id"]},
            {"$set": {"delivered": True, "delivered_at": now_iso, "delivered_to": to_email}},
        )
        delivered += 1
    return {"delivered": delivered, "skipped": skipped, "considered": len(due)}


@router.post("/run-delivery")
async def run_delivery(user: dict = Depends(get_current_user)):
    """Owner-triggered: deliver any of the owner's letters that are due right now."""
    return await deliver_due_letters(user_id=user["user_id"])
