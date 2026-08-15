"""Emergent-managed Google Auth routes plus desktop email sign-in."""
import os
import re
import secrets
import time
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


@router.delete("/me")
async def delete_account(
    request: Request,
    response: Response,
    confirm: str = "",
    user: dict = Depends(get_current_user),
):
    """Hard delete this user and every artifact they own.

    GDPR/CCPA "right to be forgotten". Requires a `confirm=DELETE` query param
    so accidental DELETE calls (mistyped curls etc.) don't blow up data.

    Wipes: archive entries, conversations, photos, companion devices, skills,
    heirs, letters, memories, identity facts, personas, reminders, nudges,
    imports, sources, voice clone settings, avatar talks, magic links, the
    user document itself, and the active session cookie. Stripe records are
    retained per Stripe's own policies (we only stored session ids).
    """
    if confirm != "DELETE":
        raise HTTPException(
            status_code=400,
            detail="Pass confirm=DELETE to confirm permanent account deletion.",
        )

    uid = user["user_id"]
    collections = [
        "entries", "conversations", "photos", "companion_devices",
        "companion_commands", "skills", "heirs", "letters", "memories",
        "identity_facts", "personas", "reminders", "nudges", "imports",
        "sources", "elevenlabs_settings", "avatar_talks", "magic_links",
        "checkout_sessions", "user_sessions",
    ]
    counts = {}
    for c in collections:
        res = await db[c].delete_many({"user_id": uid})
        if res.deleted_count:
            counts[c] = res.deleted_count

    user_res = await db.users.delete_one({"user_id": uid})
    counts["users"] = user_res.deleted_count

    # Log the deletion anonymously for fraud/tax records (12 months per privacy policy)
    await db.deletion_log.insert_one({
        "event_id": f"del_{uid}_{int(time.time())}",
        "deleted_at": datetime.now(timezone.utc).isoformat(),
        "counts": counts,
    })

    response.delete_cookie("session_token", path="/", samesite="none", secure=True)
    return {"deleted": True, "counts": counts}


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ML_RE = re.compile(r"ml_[A-Za-z0-9_-]+")


class DesktopLoginReq(BaseModel):
    email: str


class DesktopFinishReq(BaseModel):
    code: str


def _public_house_url() -> str:
    return (os.environ.get("PUBLIC_BACKEND_URL") or os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")


@router.post("/desktop-login")
async def request_desktop_login(payload: DesktopLoginReq):
    """Email a paste-in slip for the Heirloom app. Not a third-party password."""
    email = (payload.email or "").strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="That doesn't look like an email address.")

    now = datetime.now(timezone.utc)
    recent = await db.magic_links.find_one(
        {"email": email, "issued_via": "desktop", "created_at": {"$gt": (now - timedelta(seconds=45)).isoformat()}},
        {"_id": 0},
    )
    if recent:
        return {
            "ok": True,
            "note": "Check your mail. Paste the slip into Unbound Keyboard on this computer.",
        }

    user = await db.users.find_one({"email": {"$regex": f"^{re.escape(email)}$", "$options": "i"}}, {"_id": 0})
    if not user:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        user = {
            "user_id": user_id,
            "email": email,
            "name": email.split("@", 1)[0],
            "picture": "",
            "created_at": now.isoformat(),
            "last_login": now.isoformat(),
            "tour_completed": True,
        }
        await db.users.insert_one(user)
    else:
        user_id = user["user_id"]

    magic_token = "ml_" + secrets.token_urlsafe(32)
    await db.magic_links.insert_one({
        "magic_token": magic_token,
        "user_id": user_id,
        "email": email,
        "consumed": False,
        "issued_via": "desktop",
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "created_at": now.isoformat(),
    })

    from email_service import send_desktop_sign_in_email

    sent = await send_desktop_sign_in_email(to=email, code=magic_token)
    if sent.get("error") or sent.get("skipped"):
        raise HTTPException(
            status_code=503,
            detail="Couldn't send the note. Try again in a minute.",
        )
    return {
        "ok": True,
        "note": "Check your mail. Paste the slip into Unbound Keyboard on this computer.",
    }


@router.post("/desktop-login/finish")
async def finish_desktop_login(payload: DesktopFinishReq):
    """Paste the email slip in the app. Pairs this computer. No website needed."""
    found = _ML_RE.search(payload.code or "")
    if not found:
        raise HTTPException(
            status_code=400,
            detail="Paste the whole slip from your mail. It starts with ml_.",
        )
    from routers.fulfillment import redeem_magic_link

    user, session_token = await redeem_magic_link(found.group(0))
    device_id = f"dev_{uuid.uuid4().hex[:10]}"
    device_token = "comp_" + secrets.token_urlsafe(32)
    await db.companion_devices.insert_one({
        "device_id": device_id,
        "user_id": user["user_id"],
        "name": "This computer",
        "device_token": device_token,
        "revoked": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_seen": None,
        "paired_via": "desktop_login",
    })
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"last_login": datetime.now(timezone.utc).isoformat()}},
    )
    return {
        "session_token": session_token,
        "device_token": device_token,
        "house_url": _public_house_url(),
        "user": {
            "user_id": user["user_id"],
            "email": user.get("email") or "",
            "name": user.get("name") or "",
        },
        "note": "This computer is signed in. Spelling still never reads a password box.",
    }
