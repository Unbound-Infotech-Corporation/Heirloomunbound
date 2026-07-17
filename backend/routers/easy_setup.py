"""Easy Setup — plain-language, one-question-at-a-time legacy setup.

Designed so someone who is not technical can finish the essential steps:
name a loved one, name a trusted person, choose how the twin should speak
after they're gone, and optionally practice the forever version.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from deps import db, get_current_user

router = APIRouter(prefix="/easy-setup", tags=["easy-setup"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _build_status(user: dict) -> dict:
    uid = user["user_id"]
    heirs = await db.heirs.count_documents({"user_id": uid})
    entries = await db.entries.count_documents({"user_id": uid})
    lock = await db.executor_locks.find_one({"user_id": uid}, {"_id": 0}) or {}
    has_executor = bool(lock.get("enabled") and lock.get("executor_email"))
    operating = user.get("twin_operating_mode") or "living"
    if user.get("legacy_locked"):
        operating = "death_governance"
    authenticity = user.get("authenticity_mode") or "balanced"
    if operating == "death_governance" or user.get("legacy_locked"):
        authenticity = "retrieve_only"

    steps = [
        {
            "id": "heir",
            "title": "Name someone who should get this someday",
            "done": heirs > 0,
            "hint": "A child, spouse, or close friend.",
        },
        {
            "id": "executor",
            "title": "Name a trusted person who can unlock it",
            "done": has_executor,
            "hint": "Someone who can confirm if something happens to you.",
        },
        {
            "id": "style",
            "title": "Choose how your twin should talk later",
            "done": bool(user.get("easy_setup_style_chosen") or user.get("legacy_locked")),
            "hint": "Only what you wrote — or warm but careful.",
        },
        {
            "id": "memory",
            "title": "Save at least one memory",
            "done": entries > 0,
            "hint": "A story, a belief, or something you want them to know.",
        },
    ]
    done_n = sum(1 for s in steps if s["done"])
    return {
        "steps": steps,
        "done_count": done_n,
        "total": len(steps),
        "complete": done_n >= 3,  # memory can lag; 3 of 4 is "ready enough"
        "all_done": done_n == len(steps),
        "easy_setup_completed": bool(user.get("easy_setup_completed")),
        "heirs_count": heirs,
        "entries_count": entries,
        "has_executor": has_executor,
        "executor_name": lock.get("executor_name") or "",
        "twin_operating_mode": operating,
        "authenticity_mode": authenticity,
        "preferred_name": user.get("preferred_name") or user.get("name") or "",
    }


@router.get("/status")
async def easy_status(user: dict = Depends(get_current_user)):
    return await _build_status(user)


class EasyHeir(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    email: EmailStr
    relationship: str = Field("loved one", max_length=80)
    note: str = Field("", max_length=2000)


@router.post("/heir")
async def easy_add_heir(payload: EasyHeir, user: dict = Depends(get_current_user)):
    """Add one heir with safe defaults (release after 365 days of no check-in)."""
    from routers.executor_lock import assert_writable

    await assert_writable(user["user_id"])
    # Upsert-ish: if same email exists, update name/relationship
    existing = await db.heirs.find_one(
        {"user_id": user["user_id"], "email": str(payload.email).lower()},
        {"_id": 0},
    )
    if existing:
        await db.heirs.update_one(
            {"heir_id": existing["heir_id"]},
            {"$set": {
                "name": payload.name.strip(),
                "relationship": (payload.relationship or "loved one").strip(),
                "note": (payload.note or "").strip(),
            }},
        )
        return await _build_status(user)

    heir_id = f"hr_{uuid.uuid4().hex[:10]}"
    doc = {
        "heir_id": heir_id,
        "user_id": user["user_id"],
        "name": payload.name.strip(),
        "email": str(payload.email).lower(),
        "relationship": (payload.relationship or "loved one").strip(),
        "note": (payload.note or "").strip(),
        "release_on": None,
        "inactivity_days": 365,
        "released": False,
        "released_at": None,
        "release_token": None,
        "last_check_in": _now_iso(),
        "created_at": _now_iso(),
        "source": "easy_setup",
    }
    await db.heirs.insert_one(doc)
    return await _build_status(
        await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0}) or user
    )


class EasyExecutor(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    email: EmailStr
    same_as_heir: bool = False


@router.post("/executor")
async def easy_set_executor(payload: EasyExecutor, user: dict = Depends(get_current_user)):
    from routers.executor_lock import assert_writable, get_lock

    await assert_writable(user["user_id"])
    existing = await db.executor_locks.find_one({"user_id": user["user_id"]}, {"_id": 0}) or {}
    if existing.get("status") == "locked":
        raise HTTPException(status_code=409, detail="Already locked — cannot change.")

    attest_token = existing.get("attest_token") or ("ex_tok_" + secrets.token_urlsafe(24))
    doc = {
        "user_id": user["user_id"],
        "enabled": True,
        "status": "armed" if existing.get("status") != "pending" else "pending",
        "executor_name": payload.name.strip(),
        "executor_email": str(payload.email).lower(),
        "wait_hours": 72,
        "post_death_mode": "read_only",
        "notes": "Set up with Easy Setup",
        "attest_token": attest_token,
        "updated_at": _now_iso(),
        "created_at": existing.get("created_at") or _now_iso(),
    }
    for k in ("attested_at", "locked_at", "attestation_note", "document_reference", "unlocks_at"):
        if existing.get(k):
            doc[k] = existing[k]
    if existing.get("status") == "pending":
        doc["status"] = "pending"

    await db.executor_locks.update_one(
        {"user_id": user["user_id"]}, {"$set": doc}, upsert=True
    )
    refreshed = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0}) or user
    return await _build_status(refreshed)


class EasyStyle(BaseModel):
    """
    only_written  → retrieve_only authenticity, living mode (preview careful answers)
    warm_careful  → balanced authenticity, living mode
    practice_forever → death_governance + retrieve_only (full stewardship practice)
    """
    style: str


@router.post("/style")
async def easy_set_style(payload: EasyStyle, user: dict = Depends(get_current_user)):
    from routers.executor_lock import is_legacy_locked
    import death_governance as dg

    style = (payload.style or "").strip().lower()
    if style not in ("only_written", "warm_careful", "practice_forever"):
        raise HTTPException(status_code=400, detail="Pick only_written, warm_careful, or practice_forever")

    if await is_legacy_locked(user["user_id"]):
        # Locked archives stay in death governance
        await db.users.update_one(
            {"user_id": user["user_id"]},
            {"$set": {"easy_setup_style_chosen": True, "easy_setup_style": style}},
        )
        refreshed = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})
        return await _build_status(refreshed)

    update: dict = {"easy_setup_style_chosen": True, "easy_setup_style": style}
    if style == "only_written":
        update["authenticity_mode"] = "retrieve_only"
        update["twin_operating_mode"] = dg.MODE_LIVING
    elif style == "warm_careful":
        update["authenticity_mode"] = "balanced"
        update["twin_operating_mode"] = dg.MODE_LIVING
    else:  # practice_forever
        update["authenticity_mode"] = "retrieve_only"
        update["twin_operating_mode"] = dg.MODE_DEATH_GOVERNANCE
        update["death_governance_policy"] = dg.normalize_policy({
            "disclose_nature": True,
            "grief_aware": True,
            "refuse_invented_wishes": True,
            "guide_to_letters": True,
            "no_legal_medical_advice": True,
            "heir_first_person": True,
        })

    await db.users.update_one({"user_id": user["user_id"]}, {"$set": update})
    refreshed = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})
    return await _build_status(refreshed)


class EasyMemory(BaseModel):
    text: str = Field(..., min_length=3, max_length=8000)
    title: str = Field("", max_length=120)


@router.post("/memory")
async def easy_add_memory(payload: EasyMemory, user: dict = Depends(get_current_user)):
    from routers.executor_lock import assert_writable

    await assert_writable(user["user_id"])
    text = payload.text.strip()
    title = (payload.title or "").strip() or (text.split("\n", 1)[0][:60] or "Something I want remembered")
    now = _now_iso()
    entry_id = f"ent_{uuid.uuid4().hex[:12]}"
    doc = {
        "entry_id": entry_id,
        "user_id": user["user_id"],
        "type": "memory",
        "title": title,
        "content": text,
        "tags": ["easy-setup", "memory"],
        "source": "easy_setup",
        "created_at": now,
        "updated_at": now,
    }
    await db.entries.insert_one(doc)
    refreshed = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0}) or user
    return await _build_status(refreshed)


@router.post("/finish")
async def easy_finish(user: dict = Depends(get_current_user)):
    status = await _build_status(user)
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {
            "easy_setup_completed": True,
            "easy_setup_completed_at": _now_iso(),
        }},
    )
    status["easy_setup_completed"] = True
    return status
