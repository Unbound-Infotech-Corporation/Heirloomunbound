"""Optional Chatterbox TTS for the Twin Box.

Chatterbox is MIT and may be used commercially. This service does not load
XTTS-v2, F5-TTS, or LivePortrait face models.
"""
from __future__ import annotations

import io

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

app = FastAPI(title="Heirloom Chatterbox", version="0.5.1")


class SpeakReq(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "engine": "chatterbox", "license": "MIT"}


def render_wav(text: str) -> bytes:
    """Local Chatterbox only. Missing weights raise; nothing is uploaded."""
    from chatterbox.tts import ChatterboxTTS  # type: ignore

    model = ChatterboxTTS.from_pretrained(device="cuda")
    wav = model.generate(text)
    import torchaudio  # type: ignore

    buffer = io.BytesIO()
    tensor = wav.unsqueeze(0) if getattr(wav, "dim", lambda: 1)() == 1 else wav
    torchaudio.save(buffer, tensor.cpu(), model.sr, format="wav")
    return buffer.getvalue()


@app.post("/speak")
def speak(body: SpeakReq) -> dict[str, str]:
    try:
        from chatterbox.tts import ChatterboxTTS  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Chatterbox is not ready: {exc}") from exc
    _ = ChatterboxTTS
    return {
        "status": "ready",
        "engine": "chatterbox",
        "license": "MIT",
        "chars": str(len(body.text)),
    }


@app.post("/speak.wav")
def speak_wav(body: SpeakReq) -> Response:
    try:
        payload = render_wav(body.text)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Chatterbox is not ready: {exc}") from exc
    if not payload.startswith(b"RIFF"):
        raise HTTPException(status_code=503, detail="Chatterbox did not return audio")
    return Response(content=payload, media_type="audio/wav")
