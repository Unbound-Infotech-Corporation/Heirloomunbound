"""On-device speech-to-text for the dedicated PC (faster-whisper)."""
from __future__ import annotations

import io
import tempfile
from typing import Optional

from .models import probe_gpu, probe_whisper


_whisper_model = None


def _model():
    global _whisper_model  # noqa: PLW0603
    if _whisper_model is not None:
        return _whisper_model
    from faster_whisper import WhisperModel

    device = "cuda" if probe_gpu().get("ready") else "cpu"
    compute = "float16" if device == "cuda" else "int8"
    _whisper_model = WhisperModel("base", device=device, compute_type=compute)
    return _whisper_model


def whisper_ready() -> bool:
    return bool(probe_whisper().get("imported"))


def should_use_local_stt(model_map: dict | None) -> bool:
    if not whisper_ready():
        return False
    pick = (model_map or {}).get("stt", "auto")
    if pick == "cloud_whisper":
        return False
    return pick in ("auto", "local_whisper")


def transcribe_wav(wav_bytes: bytes) -> str:
    if not wav_bytes:
        return ""
    if not whisper_ready():
        raise RuntimeError("faster-whisper not installed")
    model = _model()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
        tmp.write(wav_bytes)
        tmp.flush()
        segments, _info = model.transcribe(tmp.name, beam_size=1, vad_filter=True)
        parts = [seg.text.strip() for seg in segments if seg.text.strip()]
    return " ".join(parts).strip()
