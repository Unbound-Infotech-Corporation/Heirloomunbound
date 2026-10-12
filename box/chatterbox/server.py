"""Optional Chatterbox TTS for the Twin Box.

Chatterbox is MIT and may be used commercially. This service does not load
XTTS-v2, F5-TTS, or LivePortrait face models.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Heirloom Chatterbox", version="0.5.1")


class SpeakReq(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "engine": "chatterbox", "license": "MIT"}


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
