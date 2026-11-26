"""Optional Chatterbox TTS for the Twin Box.

Chatterbox is MIT and may be used commercially. This service does not load
XTTS-v2, F5-TTS, or LivePortrait face models.
"""
from __future__ import annotations

import io
import os
import threading
import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

app = FastAPI(title="Heirloom Chatterbox", version="0.6.0")

WARM_TEXT = "Hello. This is a short warm-up line."
_model = None
_model_lock = threading.Lock()
_warm: dict[str, object] = {"state": "cold", "seconds": None, "error": ""}


class SpeakReq(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "engine": "chatterbox",
        "license": "MIT",
        "warm": _warm.get("state") == "warm",
        "warm_state": _warm.get("state"),
        "warm_seconds": _warm.get("seconds"),
    }


def pick_device(cuda_available: bool) -> str:
    """Use the GPU when the container can see one. Otherwise stay on CPU."""
    return "cuda" if cuda_available else "cpu"


def get_model(loader=None):
    """Load Chatterbox once per process. Every request after that reuses it."""
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is None:
            if loader is None:
                import torch  # type: ignore
                from chatterbox.tts import ChatterboxTTS  # type: ignore

                _model = ChatterboxTTS.from_pretrained(device=pick_device(bool(torch.cuda.is_available())))
            else:
                _model = loader()
    return _model


def warm_up(loader=None, render=None) -> dict[str, object]:
    """Load the weights and render one short line so the first real request is fast."""
    began = time.perf_counter()
    _warm.update({"state": "warming", "error": ""})
    try:
        model = get_model(loader)
        (render or (lambda m: m.generate(WARM_TEXT)))(model)
        _warm.update({"state": "warm", "seconds": round(time.perf_counter() - began, 1)})
    except Exception as exc:  # noqa: BLE001
        _warm.update({"state": "failed", "seconds": round(time.perf_counter() - began, 1), "error": str(exc)[:200]})
    return dict(_warm)


@app.on_event("startup")
def _start_warm_up() -> None:
    if (os.environ.get("CHATTERBOX_WARMUP") or "1").strip().lower() in {"0", "false", "off", "no"}:
        return
    threading.Thread(target=warm_up, name="chatterbox-warmup", daemon=True).start()


def render_wav(text: str) -> bytes:
    """Local Chatterbox only. Missing weights raise; nothing is uploaded."""
    model = get_model()
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
