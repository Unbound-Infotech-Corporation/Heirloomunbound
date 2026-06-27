"""D-ID talking-head avatar — your twin with your face.

Flow:
1. User uploads a reference photo at /avatar/source (or pastes a URL).
2. When Twin replies, the user clicks "Play as video" on a message:
     POST /avatar/talk {text} → returns {talk_id, status}
     GET  /avatar/talks/{talk_id} polled until status=done → result_url is the .mp4
3. Frontend embeds the .mp4 inline (or downloads).

Voice: D-ID can drive lip-sync with several voice providers. We pass
provider=elevenlabs when the user has a cloned voice; otherwise Microsoft.
"""
from __future__ import annotations

import base64
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel, Field

from deps import db, get_current_user

router = APIRouter(prefix="/avatar", tags=["avatar"])

D_ID_API_KEY = os.environ.get("D_ID_API_KEY", "")
D_ID_BASE = "https://api.d-id.com"


async def _user_d_id_key(user: dict) -> str:
    """Return the D-ID API key for this user. Prefer their personal key
    (Settings → BYO key) if present, else fall back to the platform default.

    Letting customers BYO their key means D-ID render costs come out of their
    account, not ours — which is essential for the $79 lifetime price to work
    at scale."""
    personal = (user.get("d_id_api_key") or "").strip()
    if personal:
        return personal
    if not D_ID_API_KEY:
        raise HTTPException(
            status_code=500,
            detail=(
                "D-ID not configured. Add your personal D-ID API key in "
                "Settings → Avatar to enable video generation."
            ),
        )
    return D_ID_API_KEY


def _auth_header_from_key(key: str) -> str:
    return "Basic " + base64.b64encode(key.encode()).decode()

# A safe public default portrait until the user uploads their own. D-ID hosts
# a small library of free demo presenters; this is the "amy-Aq6OmGZnMt" image.
DEFAULT_SOURCE_URL = "https://create-images-results.d-id.com/DefaultPresenters/Emma_f/v1_image.jpeg"


def _auth_header() -> str:
    if not D_ID_API_KEY:
        raise HTTPException(status_code=500, detail="D-ID not configured (D_ID_API_KEY missing)")
    return "Basic " + base64.b64encode(D_ID_API_KEY.encode()).decode()


class ApiKeyReq(BaseModel):
    api_key: str = Field(..., min_length=10, max_length=500)


class ApiKeyResp(BaseModel):
    has_personal_key: bool
    masked: str = ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TalkReq(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    voice: Optional[str] = None  # ElevenLabs voice id (overrides user pref)


class SourceUrlReq(BaseModel):
    url: str


@router.post("/talk")
async def create_talk(payload: TalkReq, user: dict = Depends(get_current_user)):
    """Kicks off a D-ID talking-head render. Returns immediately with a
    talk_id; client polls GET /avatar/talks/{talk_id}."""
    source_url = user.get("avatar_source_url") or DEFAULT_SOURCE_URL

    # Voice — prefer the user's cloned ElevenLabs voice; fall back to Microsoft.
    eleven_settings = await db.elevenlabs_settings.find_one(
        {"user_id": user["user_id"]}, {"_id": 0}
    ) or {}
    voice_id = payload.voice or eleven_settings.get("voice_id")
    if voice_id:
        provider = {"type": "elevenlabs", "voice_id": voice_id}
    else:
        provider = {"type": "microsoft", "voice_id": "en-US-JennyNeural"}

    body = {
        "source_url": source_url,
        "script": {
            "type": "text",
            "input": payload.text,
            "provider": provider,
        },
        "config": {"stitch": True, "fluent": True},
    }
    headers = {
        "Authorization": _auth_header_from_key(await _user_d_id_key(user)),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(f"{D_ID_BASE}/talks", headers=headers, json=body)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"D-ID upstream error: {exc!s}") from exc

    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"D-ID error {r.status_code}: {r.text[:400]}")

    data = r.json()
    talk_id = data.get("id")
    if not talk_id:
        raise HTTPException(status_code=502, detail="D-ID returned no talk id")

    await db.avatar_talks.insert_one({
        "talk_id": talk_id,
        "user_id": user["user_id"],
        "text": payload.text,
        "source_url": source_url,
        "voice_provider": provider["type"],
        "status": data.get("status", "created"),
        "created_at": _now_iso(),
    })
    return {
        "talk_id": talk_id,
        "status": data.get("status", "created"),
        "poll": f"/api/avatar/talks/{talk_id}",
    }


@router.get("/talks/{talk_id}")
async def poll_talk(talk_id: str, user: dict = Depends(get_current_user)):
    rec = await db.avatar_talks.find_one(
        {"talk_id": talk_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    if not rec:
        raise HTTPException(status_code=404, detail="Talk not found")

    headers = {"Authorization": _auth_header_from_key(await _user_d_id_key(user)), "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(f"{D_ID_BASE}/talks/{talk_id}", headers=headers)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"D-ID poll failed: {exc!s}") from exc

    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"D-ID {r.status_code}: {r.text[:300]}")

    data = r.json()
    status = data.get("status", "created")
    result_url = data.get("result_url")

    update = {"status": status, "updated_at": _now_iso()}
    if result_url:
        update["result_url"] = result_url
    await db.avatar_talks.update_one(
        {"talk_id": talk_id, "user_id": user["user_id"]}, {"$set": update}
    )

    return {
        "talk_id": talk_id,
        "status": status,
        "result_url": result_url,
        "duration": data.get("duration"),
        "error": data.get("error"),
    }


# ---------------- Source photo ----------------
@router.put("/source-url")
async def set_source_url(payload: SourceUrlReq, user: dict = Depends(get_current_user)):
    url = payload.url.strip()
    if url and not (url.startswith("https://") or url.startswith("http://")):
        raise HTTPException(status_code=400, detail="URL must be http(s)")
    await db.users.update_one(
        {"user_id": user["user_id"]}, {"$set": {"avatar_source_url": url}}
    )
    return {"avatar_source_url": url}


@router.post("/source-upload")
async def upload_source(
    file: UploadFile = File(...), user: dict = Depends(get_current_user)
):
    """Photo upload via Heirloom's storage is currently blocked behind Bearer
    auth, which D-ID's render servers can't speak. For now, host your photo
    on a public URL (imgur, your social media, etc.) and use PUT /source-url.

    This endpoint stays as a stub so the frontend doesn't 404 — returns 501
    with a helpful pointer. We'll wire a presigned-public bucket in a later pass.
    """
    raise HTTPException(
        status_code=501,
        detail=(
            "Direct upload isn't wired yet — D-ID needs a public URL. Please host "
            "your photo somewhere (imgur.com, your social media, an S3 bucket) and "
            "paste the URL via the 'Use this URL' option in Settings."
        ),
    )


@router.get("/me")
async def my_avatar(user: dict = Depends(get_current_user)):
    personal_key = (user.get("d_id_api_key") or "").strip()
    return {
        "avatar_source_url": user.get("avatar_source_url") or "",
        "default_url": DEFAULT_SOURCE_URL,
        "configured": bool(personal_key or D_ID_API_KEY),
        "has_personal_key": bool(personal_key),
        "masked_key": (personal_key[:6] + "…" + personal_key[-4:]) if personal_key else "",
    }


@router.put("/api-key")
async def set_api_key(payload: ApiKeyReq, user: dict = Depends(get_current_user)):
    """User stores their personal D-ID key. We never log or return it in full."""
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"d_id_api_key": payload.api_key.strip()}},
    )
    return {"has_personal_key": True, "masked": payload.api_key[:6] + "…" + payload.api_key[-4:]}


@router.delete("/api-key")
async def clear_api_key(user: dict = Depends(get_current_user)):
    await db.users.update_one(
        {"user_id": user["user_id"]}, {"$unset": {"d_id_api_key": ""}}
    )
    return {"has_personal_key": False}
