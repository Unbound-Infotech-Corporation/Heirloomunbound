"""Unbound Keyboard — proofread, polish, and word-habit APIs.

Accepts a Heirloom session, a companion device token, or a house key from
the Writing page so the Android keyboard and Windows helper can share one
brain. Never stores the typed buffer.
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from deps import _extract_token, db, get_current_user
from services.writing_coach import (
    MAX_POLISH_CHARS,
    MAX_PROOFREAD_CHARS,
    apply_suggestion,
    polish_for_user,
    proofread_for_user,
    style_for_user,
)

router = APIRouter(prefix="/writing", tags=["writing"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public_house_url() -> str:
    return (os.environ.get("PUBLIC_BACKEND_URL") or os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")


async def get_writing_owner(request: Request) -> dict:
    """Session cookie/Bearer, companion device token, or Unbound Keyboard house key."""
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if session:
        expires_at = session.get("expires_at")
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at)
        if expires_at is not None:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at < datetime.now(timezone.utc):
                raise HTTPException(status_code=401, detail="Session expired")
        user = await db.users.find_one({"user_id": session["user_id"]}, {"_id": 0})
        if user:
            return user

    device = await db.companion_devices.find_one({"device_token": token, "revoked": False}, {"_id": 0})
    if device:
        user = await db.users.find_one({"user_id": device["user_id"]}, {"_id": 0})
        if user:
            return user

    house = await db.keyboard_tokens.find_one({"token": token, "revoked": False}, {"_id": 0})
    if house:
        user = await db.users.find_one({"user_id": house["user_id"]}, {"_id": 0})
        if user:
            await db.keyboard_tokens.update_one(
                {"token": token},
                {"$set": {"last_seen": _now_iso()}},
            )
            return user

    raise HTTPException(status_code=401, detail="Invalid session")


class ProofreadReq(BaseModel):
    text: str = Field(..., max_length=MAX_PROOFREAD_CHARS)
    habits: Optional[dict[str, Any]] = None


class PolishReq(BaseModel):
    text: str = Field(..., max_length=MAX_POLISH_CHARS)
    instruction: str = Field("", max_length=400)


class ApplyReq(BaseModel):
    text: str = Field(..., max_length=MAX_PROOFREAD_CHARS)
    start: int
    end: int
    replacement: str = Field(..., max_length=200)


@router.post("/proofread")
async def proofread(payload: ProofreadReq, user: dict = Depends(get_writing_owner)):
    return await proofread_for_user(user["user_id"], payload.text, payload.habits)


@router.post("/polish")
async def polish(payload: PolishReq, user: dict = Depends(get_writing_owner)):
    return await polish_for_user(user["user_id"], payload.text, payload.instruction)


@router.get("/style")
async def style(user: dict = Depends(get_writing_owner)):
    return await style_for_user(user["user_id"])


@router.post("/apply")
async def apply(payload: ApplyReq, user: dict = Depends(get_writing_owner)):
    del user  # auth only — no storage
    return {"text": apply_suggestion(payload.text, payload.start, payload.end, payload.replacement)}


@router.post("/house-key")
async def make_house_key(user: dict = Depends(get_current_user)):
    """Long-lived key for the Android keyboard. Not a third-party password."""
    token = "kb_" + secrets.token_urlsafe(32)
    doc = {
        "token": token,
        "user_id": user["user_id"],
        "revoked": False,
        "created_at": _now_iso(),
        "last_seen": None,
    }
    await db.keyboard_tokens.insert_one(doc)
    return {
        "token": token,
        "house_url": _public_house_url(),
        "note": (
            "Paste this into Unbound Keyboard on your phone. It is a Heirloom house key — "
            "not a Google, Microsoft, or phone password. We never ask for those."
        ),
    }


@router.get("/house-key")
async def house_key_status(user: dict = Depends(get_current_user)):
    count = await db.keyboard_tokens.count_documents({"user_id": user["user_id"], "revoked": False})
    return {"active_keys": int(count), "house_url": _public_house_url()}
