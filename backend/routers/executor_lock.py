"""Executor Lock — consent-first posthumous governance.

Owner configures an executor while alive. After a death attestation
(with waiting period), the lock activates: heirs are released, and the
owner's archive / twin become read-only for stewardship (not rewriting).
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from deps import db, get_current_user

router = APIRouter(prefix="/executor-lock", tags=["executor-lock"])

DEFAULT_WAIT_HOURS = 72


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


class LockConfig(BaseModel):
    enabled: bool = True
    executor_name: str = Field(..., min_length=1, max_length=120)
    executor_email: EmailStr
    wait_hours: int = Field(DEFAULT_WAIT_HOURS, ge=24, le=720)
    post_death_mode: str = "read_only"  # read_only | freeze_twin
    notes: str = ""


class AttestReq(BaseModel):
    """Executor (or owner testing) submits a death attestation."""
    attestation_note: str = Field(..., min_length=10, max_length=2000)
    confirmation: str = Field(..., description='Must equal CONFIRM DEATH')
    document_reference: str = ""  # e.g. certificate number / attorney file #


class CancelAttestReq(BaseModel):
    reason: str = ""


async def get_lock_doc(user_id: str) -> dict:
    doc = await db.executor_locks.find_one({"user_id": user_id}, {"_id": 0})
    return doc or {
        "user_id": user_id,
        "enabled": False,
        "status": "inactive",  # inactive | armed | pending | locked
        "executor_name": "",
        "executor_email": "",
        "wait_hours": DEFAULT_WAIT_HOURS,
        "post_death_mode": "read_only",
        "notes": "",
        "attest_token": None,
        "attested_at": None,
        "locked_at": None,
        "attestation_note": "",
        "document_reference": "",
    }


@router.get("")
async def get_lock(user: dict = Depends(get_current_user)):
    # Auto-finalize if waiting period elapsed
    doc = await get_lock_doc(user["user_id"])
    if doc.get("status") == "pending":
        await activate_lock_if_due(user["user_id"])
        doc = await get_lock_doc(user["user_id"])
    # Never expose attest_token in owner GET — they use a separate share link
    out = dict(doc)
    token = out.pop("attest_token", None)
    out["has_attest_token"] = bool(token)
    out["attest_path"] = f"/executor/{token}" if token else None
    return out


@router.put("")
async def configure_lock(payload: LockConfig, user: dict = Depends(get_current_user)):
    if payload.post_death_mode not in ("read_only", "freeze_twin"):
        raise HTTPException(status_code=400, detail="post_death_mode must be read_only or freeze_twin")

    existing = await db.executor_locks.find_one({"user_id": user["user_id"]}, {"_id": 0}) or {}
    if existing.get("status") == "locked":
        raise HTTPException(status_code=409, detail="Lock already activated — cannot reconfigure.")

    attest_token = existing.get("attest_token") or ("ex_tok_" + secrets.token_urlsafe(24))
    doc = {
        "user_id": user["user_id"],
        "enabled": payload.enabled,
        "status": "armed" if payload.enabled else "inactive",
        "executor_name": payload.executor_name.strip(),
        "executor_email": str(payload.executor_email).lower(),
        "wait_hours": int(payload.wait_hours),
        "post_death_mode": payload.post_death_mode,
        "notes": (payload.notes or "")[:2000],
        "attest_token": attest_token,
        "updated_at": _now_iso(),
        "created_at": existing.get("created_at") or _now_iso(),
    }
    # Preserve pending attestation fields if any
    for k in ("attested_at", "locked_at", "attestation_note", "document_reference", "status"):
        if k == "status":
            continue
        if existing.get(k):
            doc[k] = existing[k]
    if existing.get("status") == "pending":
        doc["status"] = "pending"

    await db.executor_locks.update_one(
        {"user_id": user["user_id"]}, {"$set": doc}, upsert=True
    )
    return await get_lock(user)


@router.post("/attest")
async def owner_attest(payload: AttestReq, user: dict = Depends(get_current_user)):
    """Owner can simulate/start attestation (also used in tests). Prefer public token path."""
    return await _start_attestation(user["user_id"], payload, actor="owner")


@router.post("/public/{token}/attest")
async def public_attest(token: str, payload: AttestReq):
    """Executor submits death attestation via shared token (no login)."""
    doc = await db.executor_locks.find_one({"attest_token": token, "enabled": True}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Invalid or inactive executor link.")
    return await _start_attestation(doc["user_id"], payload, actor="executor")


@router.get("/public/{token}")
async def public_lock_info(token: str):
    doc = await db.executor_locks.find_one({"attest_token": token}, {"_id": 0})
    if not doc or not doc.get("enabled"):
        raise HTTPException(status_code=404, detail="Invalid or inactive executor link.")
    owner = await db.users.find_one({"user_id": doc["user_id"]}, {"_id": 0, "name": 1})
    return {
        "owner_name": (owner or {}).get("name") or "the owner",
        "executor_name": doc.get("executor_name"),
        "status": doc.get("status"),
        "wait_hours": doc.get("wait_hours", DEFAULT_WAIT_HOURS),
        "attested_at": doc.get("attested_at"),
        "locked_at": doc.get("locked_at"),
    }


async def _start_attestation(user_id: str, payload: AttestReq, *, actor: str) -> dict:
    if payload.confirmation.strip().upper() != "CONFIRM DEATH":
        raise HTTPException(status_code=400, detail='Type CONFIRM DEATH exactly to proceed.')
    doc = await get_lock_doc(user_id)
    if not doc.get("enabled"):
        raise HTTPException(status_code=400, detail="Executor Lock is not enabled.")
    if doc.get("status") == "locked":
        return {"status": "locked", "locked_at": doc.get("locked_at"), "message": "Already locked."}
    if doc.get("status") == "pending":
        return {
            "status": "pending",
            "attested_at": doc.get("attested_at"),
            "unlocks_at": doc.get("unlocks_at"),
            "message": "Waiting period already in progress.",
        }

    wait = int(doc.get("wait_hours") or DEFAULT_WAIT_HOURS)
    attested_at = _now()
    unlocks_at = attested_at + timedelta(hours=wait)
    await db.executor_locks.update_one(
        {"user_id": user_id},
        {"$set": {
            "status": "pending",
            "attested_at": attested_at.isoformat(),
            "unlocks_at": unlocks_at.isoformat(),
            "attestation_note": payload.attestation_note.strip()[:2000],
            "document_reference": (payload.document_reference or "").strip()[:200],
            "attested_by": actor,
            "updated_at": _now_iso(),
        }},
        upsert=True,
    )
    return {
        "status": "pending",
        "attested_at": attested_at.isoformat(),
        "unlocks_at": unlocks_at.isoformat(),
        "wait_hours": wait,
        "message": f"Waiting period started ({wait}h). Lock activates after that unless cancelled.",
    }


@router.post("/cancel-attestation")
async def cancel_attestation(payload: CancelAttestReq, user: dict = Depends(get_current_user)):
    """Owner cancels a pending attestation during the waiting period (anti-fraud)."""
    doc = await get_lock_doc(user["user_id"])
    if doc.get("status") != "pending":
        raise HTTPException(status_code=400, detail="No pending attestation to cancel.")
    await db.executor_locks.update_one(
        {"user_id": user["user_id"]},
        {"$set": {
            "status": "armed",
            "attested_at": None,
            "unlocks_at": None,
            "attestation_note": "",
            "document_reference": "",
            "cancel_reason": (payload.reason or "")[:500],
            "cancelled_at": _now_iso(),
            "updated_at": _now_iso(),
        }},
    )
    return {"status": "armed", "message": "Attestation cancelled. Lock re-armed."}


@router.post("/finalize")
async def finalize_lock(user: dict = Depends(get_current_user)):
    """Activate lock if waiting period elapsed; also releases all heirs."""
    return await activate_lock_if_due(user["user_id"])


async def activate_lock_if_due(user_id: str) -> dict:
    doc = await get_lock_doc(user_id)
    if doc.get("status") == "locked":
        return {"status": "locked", "locked_at": doc.get("locked_at")}
    if doc.get("status") != "pending":
        return {"status": doc.get("status") or "inactive", "message": "Nothing to finalize."}

    unlocks = doc.get("unlocks_at")
    if unlocks:
        try:
            u = datetime.fromisoformat(unlocks)
            if u.tzinfo is None:
                u = u.replace(tzinfo=timezone.utc)
            if _now() < u:
                return {
                    "status": "pending",
                    "unlocks_at": unlocks,
                    "message": "Waiting period not finished yet.",
                }
        except Exception:
            pass

    locked_at = _now_iso()
    await db.executor_locks.update_one(
        {"user_id": user_id},
        {"$set": {
            "status": "locked",
            "locked_at": locked_at,
            "updated_at": locked_at,
        }},
    )
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {
            "legacy_locked": True,
            "legacy_locked_at": locked_at,
            "authenticity_mode": "retrieve_only",  # hard authenticity after death
        }},
    )

    # Release all unreleased heirs
    from routers.heirs import _do_release
    cursor = db.heirs.find({"user_id": user_id, "released": False}, {"_id": 0})
    heirs = await cursor.to_list(length=200)
    released = []
    for h in heirs:
        token = await _do_release(h)
        released.append({"heir_id": h["heir_id"], "name": h.get("name"), "portal_path": f"/heir/{token}"})

    return {
        "status": "locked",
        "locked_at": locked_at,
        "heirs_released": released,
        "message": "Executor Lock activated. Archive is read-only; heirs released.",
    }


async def is_legacy_locked(user_id: str) -> bool:
    user = await db.users.find_one({"user_id": user_id}, {"_id": 0, "legacy_locked": 1})
    if user and user.get("legacy_locked"):
        return True
    doc = await db.executor_locks.find_one({"user_id": user_id}, {"_id": 0, "status": 1})
    return bool(doc and doc.get("status") == "locked")


async def assert_writable(user_id: str) -> None:
    if await is_legacy_locked(user_id):
        raise HTTPException(
            status_code=403,
            detail="Executor Lock is active — this archive is read-only for stewardship.",
        )
