"""Heirloom Desktop — backend endpoints that the PySide6 Windows app calls.

All endpoints here authenticate via the same `device_token` that already
authorises the background companion (`Bearer comp_…`). This means a single
download of the desktop .zip is "logged in forever" — no separate sign-in.

The web app's /twin page and this desktop app share a single conversation
(kind="companion_twin") so chat history is the same everywhere.
"""
from __future__ import annotations

import base64
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from emergentintegrations.llm.chat import LlmChat, UserMessage
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from deps import EMERGENT_LLM_KEY, db
from routers.companion import get_device_user
from routers.live import publish_avatar as live_publish_avatar
from routers.live import publish_turn as live_publish_turn

router = APIRouter(prefix="/desktop", tags=["desktop"])

D_ID_API_KEY = os.environ.get("D_ID_API_KEY", "")
D_ID_BASE = "https://api.d-id.com"
DEFAULT_SOURCE_URL = (
    "https://create-images-results.d-id.com/DefaultPresenters/Emma_f/v1_image.jpeg"
)
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _did_auth(user: dict) -> str:
    key = (user.get("d_id_api_key") or "").strip() or D_ID_API_KEY
    if not key:
        raise HTTPException(
            status_code=500,
            detail="D-ID not configured. Add a personal D-ID key in Settings.",
        )
    return "Basic " + base64.b64encode(key.encode()).decode()


# ---------------- Identity (used by the app for the welcome bar) ----------------
@router.get("/me")
async def desktop_me(ctx: dict = Depends(get_device_user)):
    user = ctx["user"]
    return {
        "user_id": user["user_id"],
        "email": user.get("email", ""),
        "name": user.get("name", ""),
        "picture": user.get("picture", ""),
        "avatar_source_url": user.get("avatar_source_url") or DEFAULT_SOURCE_URL,
        "purchased_lifetime": user.get("purchased_lifetime", False),
        "account_status": user.get("account_status", "active"),
    }


# ---------------- Chat (text → twin reply, shared with web) ----------------
class ChatReq(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


async def _ensure_companion_conv(user_id: str) -> dict:
    conv = await db.conversations.find_one(
        {"user_id": user_id, "kind": "companion_twin"}, {"_id": 0}
    )
    if conv:
        return conv
    conv = {
        "conversation_id": f"comp_{uuid.uuid4().hex[:12]}",
        "user_id": user_id,
        "kind": "companion_twin",
        "messages": [],
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    await db.conversations.insert_one(dict(conv))
    return conv


@router.get("/conversation")
async def get_conversation(ctx: dict = Depends(get_device_user), limit: int = 80):
    """Return the most-recent N turns of the shared companion conversation."""
    user = ctx["user"]
    conv = await _ensure_companion_conv(user["user_id"])
    msgs = conv.get("messages", [])
    if limit and len(msgs) > limit:
        msgs = msgs[-limit:]
    return {
        "conversation_id": conv["conversation_id"],
        "messages": msgs,
    }


@router.post("/chat")
async def desktop_chat(body: ChatReq, ctx: dict = Depends(get_device_user)):
    """Send a text message as the user; persist + return the twin's reply."""
    user = ctx["user"]
    conv = await _ensure_companion_conv(user["user_id"])

    cursor = db.entries.find({"user_id": user["user_id"]}, {"_id": 0}).sort(
        "created_at", -1
    ).limit(120)
    entries = await cursor.to_list(length=120)
    archive = "\n".join(
        f"[{e.get('type','note').upper()}] {e.get('title','')}\n{e.get('content','')}\n"
        for e in entries
    )

    system = (
        f"You are {user.get('name','the user')}'s digital twin running in their "
        f"desktop app. You ARE them — speak first-person, briefly (1-3 sentences), "
        f"never narrate. Don't sign off. Don't add caveats.\n\n"
        f"Your personality archive (most recent first):\n{archive[:18000] or '(empty)'}"
    )

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=conv["conversation_id"],
        system_message=system,
        initial_messages=(
            [{"role": "system", "content": system}]
            + [
                {"role": m["role"], "content": m["content"]}
                for m in conv.get("messages", [])
                if m.get("role") in ("user", "assistant") and m.get("content")
            ]
        ),
    ).with_model("anthropic", "claude-sonnet-4-6")

    try:
        reply = await chat.send_message(UserMessage(text=body.text))
        reply_text = reply if isinstance(reply, str) else getattr(reply, "content", str(reply))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM failed: {exc!s}") from exc

    now = _now_iso()
    await db.conversations.update_one(
        {"conversation_id": conv["conversation_id"], "user_id": user["user_id"]},
        {
            "$push": {
                "messages": {
                    "$each": [
                        {"role": "user", "content": body.text, "ts": now, "source": "desktop"},
                        {"role": "assistant", "content": reply_text, "ts": now, "source": "desktop"},
                    ]
                }
            },
            "$set": {"updated_at": now},
        },
    )

    # Fan out to any live-stream viewers (no-op if owner hasn't enabled it)
    await live_publish_turn(user["user_id"], "user", body.text, source="desktop")
    await live_publish_turn(user["user_id"], "assistant", reply_text, source="desktop")

    return {"reply": reply_text, "ts": now}


# ---------------- Avatar (D-ID talking-head) ----------------
class TalkReq(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


@router.post("/avatar/talk")
async def desktop_avatar_talk(payload: TalkReq, ctx: dict = Depends(get_device_user)):
    """Kick off a D-ID talking-head render for `text`. Same shape as
    `/avatar/talk` but device-token authed."""
    user = ctx["user"]
    source_url = user.get("avatar_source_url") or DEFAULT_SOURCE_URL

    eleven_settings = (
        await db.elevenlabs_settings.find_one({"user_id": user["user_id"]}, {"_id": 0})
        or {}
    )
    voice_id = eleven_settings.get("voice_id")
    if voice_id:
        provider = {"type": "elevenlabs", "voice_id": voice_id}
    else:
        provider = {"type": "microsoft", "voice_id": "en-US-JennyNeural"}

    body = {
        "source_url": source_url,
        "script": {"type": "text", "input": payload.text[:1000], "provider": provider},
        "config": {"stitch": True, "fluent": True},
    }
    headers = {
        "Authorization": _did_auth(user),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(f"{D_ID_BASE}/talks", headers=headers, json=body)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"D-ID upstream: {exc!s}") from exc
    if r.status_code >= 400:
        raise HTTPException(
            status_code=502, detail=f"D-ID error {r.status_code}: {r.text[:300]}"
        )

    data = r.json()
    talk_id = data.get("id")
    if not talk_id:
        raise HTTPException(status_code=502, detail="D-ID returned no talk id")

    await db.avatar_talks.insert_one(
        {
            "talk_id": talk_id,
            "user_id": user["user_id"],
            "text": payload.text,
            "source_url": source_url,
            "voice_provider": provider["type"],
            "status": data.get("status", "created"),
            "created_at": _now_iso(),
            "source": "desktop",
        }
    )
    return {"talk_id": talk_id, "status": data.get("status", "created")}


@router.get("/avatar/talk/{talk_id}")
async def desktop_avatar_poll(talk_id: str, ctx: dict = Depends(get_device_user)):
    user = ctx["user"]
    rec = await db.avatar_talks.find_one(
        {"talk_id": talk_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    if not rec:
        raise HTTPException(status_code=404, detail="Talk not found")

    headers = {"Authorization": _did_auth(user), "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(f"{D_ID_BASE}/talks/{talk_id}", headers=headers)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"D-ID poll: {exc!s}") from exc
    if r.status_code >= 400:
        raise HTTPException(
            status_code=502, detail=f"D-ID {r.status_code}: {r.text[:300]}"
        )
    data = r.json()
    status = data.get("status", "created")
    result_url = data.get("result_url")
    update = {"status": status, "updated_at": _now_iso()}
    if result_url:
        update["result_url"] = result_url
    await db.avatar_talks.update_one(
        {"talk_id": talk_id, "user_id": user["user_id"]}, {"$set": update}
    )
    # When the render is finished, fan out to live viewers so they see the
    # talking head play in sync with the owner.
    if status == "done" and result_url:
        await live_publish_avatar(user["user_id"], result_url)
    return {
        "talk_id": talk_id,
        "status": status,
        "result_url": result_url,
        "error": data.get("error"),
    }


# ---------------- Quick capture (journal) ----------------
class CaptureReq(BaseModel):
    title: Optional[str] = None
    content: str = Field(..., min_length=1, max_length=8000)
    type: str = "note"  # note | memory | belief | story
    tags: list[str] = Field(default_factory=list)


@router.post("/capture")
async def desktop_capture(body: CaptureReq, ctx: dict = Depends(get_device_user)):
    user = ctx["user"]
    entry = {
        "entry_id": f"ent_{uuid.uuid4().hex[:12]}",
        "user_id": user["user_id"],
        "type": body.type,
        "title": (body.title or body.content[:80]).strip(),
        "content": body.content,
        "tags": list({*body.tags, "desktop"}),
        "source": "desktop",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    await db.entries.insert_one(dict(entry))
    return entry


# ---------------- Recent memories sidebar ----------------
@router.get("/memories/recent")
async def desktop_memories(ctx: dict = Depends(get_device_user), limit: int = 20):
    user = ctx["user"]
    cursor = (
        db.entries.find(
            {"user_id": user["user_id"]},
            {"_id": 0, "entry_id": 1, "type": 1, "title": 1, "content": 1, "created_at": 1, "tags": 1},
        )
        .sort("created_at", -1)
        .limit(max(1, min(limit, 100)))
    )
    items = await cursor.to_list(length=limit)
    return {"items": items}


# ---------------- Cloned-voice TTS (used by Waveform avatar mode) ----------------
class SpeakReq(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    language: Optional[str] = None


@router.post("/speak")
async def desktop_speak(payload: SpeakReq, ctx: dict = Depends(get_device_user)):
    """Synthesize `text` through the user's cloned ElevenLabs voice and stream
    back the MP3 bytes. Returns 400 if the user hasn't configured a voice
    (the desktop app falls back to silent waveform animation in that case).

    Returns audio/mpeg directly — no base64 wrapper — because the desktop
    QMediaPlayer plays from raw bytes and we want to avoid the ~33% size
    inflation."""
    user = ctx["user"]
    key = (user.get("elevenlabs_api_key") or "").strip() or ELEVENLABS_API_KEY
    voice_id = (user.get("elevenlabs_voice_id") or "").strip()
    if not key or not voice_id:
        raise HTTPException(
            status_code=400,
            detail="Voice clone not configured — open the web Settings to clone your voice or set an ElevenLabs voice_id.",
        )

    text = payload.text.strip()[:4000]
    lang_pref = (payload.language or user.get("tts_language") or "auto").strip().lower()

    # Call ElevenLabs directly via REST so we don't have to import the heavy
    # AsyncElevenLabs client just for streaming bytes — keeps cold-start fast.
    headers = {
        "xi-api-key": key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    body: dict = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "output_format": "mp3_44100_128",
    }
    if lang_pref and lang_pref != "auto" and len(lang_pref) <= 8:
        body["language_code"] = lang_pref

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers=headers,
                json=body,
            )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"ElevenLabs upstream: {exc!s}") from exc

    if r.status_code >= 400:
        # Map common errors to clearer messages
        snippet = r.text[:300]
        if r.status_code == 401:
            raise HTTPException(status_code=400, detail="ElevenLabs key invalid or revoked.")
        if r.status_code == 404:
            raise HTTPException(status_code=400, detail=f"Voice id not found in your ElevenLabs account ({voice_id}).")
        raise HTTPException(status_code=502, detail=f"ElevenLabs {r.status_code}: {snippet}")

    audio = r.content
    if not audio:
        raise HTTPException(status_code=502, detail="ElevenLabs returned empty audio.")

    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": 'inline; filename="twin.mp3"',
            "Cache-Control": "no-store",
            "X-Voice-Id": voice_id,
        },
    )


@router.get("/voice/status")
async def desktop_voice_status(ctx: dict = Depends(get_device_user)):
    """Cheap pre-flight check the desktop app calls at boot — lets the avatar
    panel decide whether Waveform mode should attempt TTS or stay silent."""
    user = ctx["user"]
    return {
        "configured": bool(
            (user.get("elevenlabs_api_key") or ELEVENLABS_API_KEY)
            and user.get("elevenlabs_voice_id")
        ),
        "voice_name": user.get("elevenlabs_voice_name") or "",
        "voice_id": user.get("elevenlabs_voice_id") or "",
    }
