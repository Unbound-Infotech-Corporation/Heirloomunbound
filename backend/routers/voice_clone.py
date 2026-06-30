"""ElevenLabs voice cloning + TTS."""
import base64
import io
import os
from typing import Optional

from elevenlabs.client import AsyncElevenLabs
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from deps import db, get_current_user

router = APIRouter(prefix="/voice-clone", tags=["voice-clone"])

DEFAULT_KEY = os.environ.get("ELEVENLABS_API_KEY", "")


def _resolve_key(user: dict) -> str:
    return user.get("elevenlabs_api_key") or DEFAULT_KEY


def _resolve_voice_id(user: dict) -> Optional[str]:
    return user.get("elevenlabs_voice_id") or None


class SettingsPayload(BaseModel):
    api_key: Optional[str] = None
    voice_id: Optional[str] = None
    clear: bool = False


class TTSReq(BaseModel):
    text: str
    language: Optional[str] = None  # ISO 639-1 (en, es, fr, ...). 'auto' or None = let model detect.


@router.get("/settings")
async def get_settings(user: dict = Depends(get_current_user)):
    key = user.get("elevenlabs_api_key") or ""
    return {
        "has_user_key": bool(user.get("elevenlabs_api_key")),
        "has_default_key": bool(DEFAULT_KEY),
        "api_key_preview": (key[:6] + "…" + key[-4:]) if key else "",
        "voice_id": user.get("elevenlabs_voice_id") or "",
        "voice_name": user.get("elevenlabs_voice_name") or "",
    }


@router.put("/settings")
async def set_settings(payload: SettingsPayload, user: dict = Depends(get_current_user)):
    update: dict = {}
    if payload.clear:
        update["elevenlabs_api_key"] = ""
        update["elevenlabs_voice_id"] = ""
        update["elevenlabs_voice_name"] = ""
    else:
        if payload.api_key is not None:
            update["elevenlabs_api_key"] = payload.api_key.strip()
        if payload.voice_id is not None:
            update["elevenlabs_voice_id"] = payload.voice_id.strip()
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    await db.users.update_one({"user_id": user["user_id"]}, {"$set": update})
    return {"ok": True}


class ApiKeyOnly(BaseModel):
    api_key: str


@router.put("/api-key")
async def set_api_key(payload: ApiKeyOnly, user: dict = Depends(get_current_user)):
    """Alias for /settings with just the api_key — mirrors /avatar/api-key
    and /avatar-studio/api-key so the Setup/Keys wizard can use a uniform
    REST shape across all three providers."""
    key = (payload.api_key or "").strip()
    if not key:
        await db.users.update_one(
            {"user_id": user["user_id"]}, {"$unset": {"elevenlabs_api_key": ""}}
        )
        return {"has_user_key": False}
    await db.users.update_one(
        {"user_id": user["user_id"]}, {"$set": {"elevenlabs_api_key": key}}
    )
    return {"has_user_key": True}


@router.delete("/api-key")
async def clear_api_key(user: dict = Depends(get_current_user)):
    await db.users.update_one(
        {"user_id": user["user_id"]}, {"$unset": {"elevenlabs_api_key": ""}}
    )
    return {"has_user_key": False}


@router.get("/voices")
async def list_voices(user: dict = Depends(get_current_user)):
    key = _resolve_key(user)
    if not key:
        raise HTTPException(status_code=400, detail="No ElevenLabs API key configured")
    client = AsyncElevenLabs(api_key=key)
    try:
        resp = await client.voices.get_all()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"ElevenLabs error: {exc!s}") from exc

    voices = []
    for v in getattr(resp, "voices", []) or []:
        voices.append(
            {
                "voice_id": getattr(v, "voice_id", None),
                "name": getattr(v, "name", ""),
                "category": getattr(v, "category", ""),
                "preview_url": getattr(v, "preview_url", None),
            }
        )
    return {"voices": voices}


@router.post("/speak")
async def speak(payload: TTSReq, user: dict = Depends(get_current_user)):
    key = _resolve_key(user)
    voice_id = _resolve_voice_id(user)
    if not key or not voice_id:
        raise HTTPException(status_code=400, detail="Voice clone not configured")
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty text")
    if len(text) > 5000:
        text = text[:5000]

    client = AsyncElevenLabs(api_key=key)
    # Language: explicit param → user preference → model autodetect
    lang_pref = (payload.language or user.get("tts_language") or "auto").strip().lower()
    convert_kwargs = dict(
        voice_id=voice_id,
        text=text,
        model_id="eleven_multilingual_v2",
        output_format="mp3_44100_128",
    )
    if lang_pref and lang_pref != "auto" and len(lang_pref) <= 8:
        convert_kwargs["language_code"] = lang_pref
    try:
        stream = client.text_to_speech.convert(**convert_kwargs)
        audio = b""
        async for chunk in stream:
            if chunk:
                audio += chunk
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"ElevenLabs TTS failed: {exc!s}") from exc

    return {
        "audio_base64": base64.b64encode(audio).decode("ascii"),
        "mime": "audio/mpeg",
    }


@router.post("/clone")
async def clone_voice(
    name: str = Form(...),
    description: str = Form(""),
    files: list[UploadFile] = File(...),
    user: dict = Depends(get_current_user),
):
    key = _resolve_key(user)
    if not key:
        raise HTTPException(status_code=400, detail="No ElevenLabs API key configured")
    if not files:
        raise HTTPException(status_code=400, detail="Upload at least one audio sample")

    client = AsyncElevenLabs(api_key=key)
    samples = []
    for f in files:
        raw = await f.read()
        if not raw:
            continue
        buf = io.BytesIO(raw)
        buf.name = f.filename or "sample.mp3"
        samples.append(buf)
    if not samples:
        raise HTTPException(status_code=400, detail="No usable audio in upload")

    try:
        result = await client.voices.ivc.create(
            name=name,
            description=description or None,
            files=samples,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"ElevenLabs clone failed: {exc!s}") from exc

    voice_id = getattr(result, "voice_id", None) or (
        result.get("voice_id") if isinstance(result, dict) else None
    )
    if not voice_id:
        raise HTTPException(status_code=502, detail="ElevenLabs did not return a voice_id")

    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"elevenlabs_voice_id": voice_id, "elevenlabs_voice_name": name}},
    )
    return {"voice_id": voice_id, "name": name}
