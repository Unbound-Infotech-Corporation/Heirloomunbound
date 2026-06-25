"""Voice routes: Whisper STT + OpenAI TTS."""
import base64
import io
import uuid
from datetime import datetime, timezone

from emergentintegrations.llm.openai import OpenAISpeechToText, OpenAITextToSpeech
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from deps import EMERGENT_LLM_KEY, db, get_current_user

router = APIRouter(prefix="/voice", tags=["voice"])


class TTSRequest(BaseModel):
    text: str
    voice: str = "onyx"  # warm, deep, narrator-like — fits the heirloom tone


@router.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    save_to_archive: bool = Form(True),
    title: str = Form(""),
    user: dict = Depends(get_current_user),
):
    if not EMERGENT_LLM_KEY:
        raise HTTPException(status_code=500, detail="EMERGENT_LLM_KEY not configured")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty audio")
    if len(raw) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio over 25MB limit")

    buf = io.BytesIO(raw)
    buf.name = file.filename or "recording.webm"

    stt = OpenAISpeechToText(api_key=EMERGENT_LLM_KEY)
    try:
        result = await stt.transcribe(file=buf, model="whisper-1", response_format="json")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Transcription failed: {exc!s}") from exc

    text = getattr(result, "text", "") or ""
    response: dict = {"text": text}

    if save_to_archive and text.strip():
        entry_id = f"ent_{uuid.uuid4().hex[:12]}"
        doc = {
            "entry_id": entry_id,
            "user_id": user["user_id"],
            "type": "voice",
            "title": title or f"Voice journal — {datetime.now(timezone.utc).strftime('%b %d, %Y · %H:%M')}",
            "content": text,
            "tags": ["voice"],
            "source": "voice_journal",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.entries.insert_one(doc)
        doc.pop("_id", None)
        response["entry"] = doc

    return response


@router.post("/speak")
async def text_to_speech(payload: TTSRequest, user: dict = Depends(get_current_user)):
    if not EMERGENT_LLM_KEY:
        raise HTTPException(status_code=500, detail="EMERGENT_LLM_KEY not configured")
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty text")
    if len(text) > 4000:
        text = text[:4000]

    tts = OpenAITextToSpeech(api_key=EMERGENT_LLM_KEY)
    try:
        audio_bytes = await tts.generate_speech(text=text, model="tts-1", voice=payload.voice)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"TTS failed: {exc!s}") from exc

    return {
        "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
        "mime": "audio/mpeg",
    }
