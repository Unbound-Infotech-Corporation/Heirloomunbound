"""Emergent-managed Google Auth routes."""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from deps import db, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])

EMERGENT_SESSION_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"


@router.post("/session")
async def create_session(request: Request, response: Response):
    """Exchange Emergent session_id for a persistent session_token + httpOnly cookie."""
    body = await request.json()
    session_id = body.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing session_id")

    async with httpx.AsyncClient(timeout=15.0) as http:
        r = await http.get(EMERGENT_SESSION_URL, headers={"X-Session-ID": session_id})
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid Emergent session_id")
    data = r.json()

    email = data["email"]
    name = data.get("name", "")
    picture = data.get("picture", "")
    session_token = data["session_token"]

    # Upsert user (custom user_id, never expose _id)
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        user_id = existing["user_id"]
        await db.users.update_one(
            {"user_id": user_id},
            {"$set": {"name": name, "picture": picture, "last_login": datetime.now(timezone.utc).isoformat()}},
        )
    else:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        await db.users.insert_one({
            "user_id": user_id,
            "email": email,
            "name": name,
            "picture": picture,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_login": datetime.now(timezone.utc).isoformat(),
        })

    # Persist session
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    await db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": session_token,
        "expires_at": expires_at.isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    response.set_cookie(
        key="session_token",
        value=session_token,
        max_age=7 * 24 * 60 * 60,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
    )
    return {
        "user_id": user_id,
        "email": email,
        "name": name,
        "picture": picture,
    }


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "name": user.get("name", ""),
        "picture": user.get("picture", ""),
        "safe_topics": user.get("safe_topics") or [],
        "tts_language": user.get("tts_language") or "auto",
        "music_provider": user.get("music_provider") or "youtube_music",
        "brand_name": user.get("brand_name") or "",
        "brand_tagline": user.get("brand_tagline") or "",
        "brand_signoff": user.get("brand_signoff") or "",
        "active_persona_id": user.get("active_persona_id") or None,
        "tour_completed": bool(user.get("tour_completed", False)),
    }


@router.post("/me/tour-complete")
async def complete_tour(user: dict = Depends(get_current_user)):
    """Mark the first-run welcome tour as seen. Idempotent."""
    await db.users.update_one(
        {"user_id": user["user_id"]}, {"$set": {"tour_completed": True}}
    )
    return {"tour_completed": True}


class PreferencesUpdate(BaseModel):
    safe_topics: Optional[list[str]] = None
    tts_language: Optional[str] = None  # 'auto', 'en', 'es', 'fr', etc.
    music_provider: Optional[str] = None  # 'youtube_music' | 'spotify' | ...
    brand_name: Optional[str] = None
    brand_tagline: Optional[str] = None
    brand_signoff: Optional[str] = None  # e.g. "— Aaron, Unbound Infotech"


@router.put("/me/preferences")
async def update_preferences(payload: PreferencesUpdate, user: dict = Depends(get_current_user)):
    update: dict = {}
    if payload.safe_topics is not None:
        cleaned = [s.strip()[:80] for s in payload.safe_topics if s and s.strip()][:25]
        update["safe_topics"] = cleaned
    if payload.tts_language is not None:
        lang = payload.tts_language.strip().lower()[:8]
        if lang and lang not in {"auto","en","es","fr","de","it","pt","pl","hi","ja","ko","zh","nl","sv","no","da","fi","cs","tr","ru","ar"}:
            raise HTTPException(status_code=400, detail="Unsupported language code")
        update["tts_language"] = lang or "auto"
    if payload.music_provider is not None:
        from routers.music import PROVIDERS, DEFAULT_PROVIDER
        prov = payload.music_provider.strip().lower()
        if prov and prov not in PROVIDERS:
            raise HTTPException(status_code=400, detail=f"Unknown music provider. Choose from {list(PROVIDERS)}")
        update["music_provider"] = prov or DEFAULT_PROVIDER
    if payload.brand_name is not None:
        update["brand_name"] = payload.brand_name.strip()[:80]
    if payload.brand_tagline is not None:
        update["brand_tagline"] = payload.brand_tagline.strip()[:200]
    if payload.brand_signoff is not None:
        update["brand_signoff"] = payload.brand_signoff.strip()[:160]
    if not update:
        raise HTTPException(status_code=400, detail="No preferences provided")
    await db.users.update_one({"user_id": user["user_id"]}, {"$set": update})
    refreshed = await db.users.find_one({"user_id": user["user_id"]}, {"_id": 0})
    return {
        "safe_topics": refreshed.get("safe_topics") or [],
        "tts_language": refreshed.get("tts_language") or "auto",
        "music_provider": refreshed.get("music_provider") or "youtube_music",
        "brand_name": refreshed.get("brand_name") or "",
        "brand_tagline": refreshed.get("brand_tagline") or "",
        "brand_signoff": refreshed.get("brand_signoff") or "",
    }


@router.post("/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("session_token")
    if token:
        await db.user_sessions.delete_one({"session_token": token})
    response.delete_cookie("session_token", path="/", samesite="none", secure=True)
    return {"ok": True}
