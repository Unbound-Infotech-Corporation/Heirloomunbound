"""Optional local inference helpers (Ollama + faster-whisper on the runtime host).

On the dedicated PC the companion process runs Whisper/Ollama locally. When the
backend itself is co-located (dev) or has faster-whisper installed, these same
helpers power /companion/voice STT and cloud-side Ollama twin turns.
"""
from __future__ import annotations

import io
import json
import os
import urllib.error
import urllib.request
from typing import Any, Optional

import httpx

OLLAMA_DEFAULT = "http://127.0.0.1:11434"
OLLAMA_MODEL = os.environ.get("OLLAMA_TWIN_MODEL", "llama3.1")


def ollama_base_url() -> str:
    return (os.environ.get("OLLAMA_BASE_URL") or os.environ.get("OLLAMA_URL") or OLLAMA_DEFAULT).rstrip("/")


def ollama_ready_at(base_url: str, timeout: float = 2.0) -> bool:
    url = (base_url or "").strip().rstrip("/")
    if not url:
        return False
    try:
        req = urllib.request.Request(f"{url}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def ollama_ready(timeout: float = 2.0) -> bool:
    return ollama_ready_at(ollama_base_url(), timeout=timeout)


async def ollama_chat(
    system: str,
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    timeout: float = 120.0,
    base_url: str | None = None,
) -> str:
    """Single-shot chat completion via Ollama /api/chat (non-streaming)."""
    payload_messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    for m in messages:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            payload_messages.append({"role": role, "content": content})

    body = {
        "model": model or OLLAMA_MODEL,
        "messages": payload_messages,
        "stream": False,
        "options": {"temperature": 0.65, "num_predict": 512},
    }
    url = f"{(base_url or ollama_base_url()).rstrip('/')}/api/chat"
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, json=body)
    if r.status_code >= 400:
        raise RuntimeError(f"Ollama HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    msg = data.get("message") or {}
    text = (msg.get("content") or "").strip()
    if not text:
        raise RuntimeError("Ollama returned empty content")
    return text


def transcribe_whisper_bytes(
    raw: bytes,
    *,
    filename: str = "audio.wav",
    model_size: str = "base",
) -> str:
    """Transcribe WAV/PCM bytes with faster-whisper if installed."""
    if not raw:
        return ""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("faster-whisper not installed on this host") from exc

    device = "cuda"
    compute = "float16"
    try:
        import torch  # noqa: F401

        if not __import__("torch").cuda.is_available():
            device = "cpu"
            compute = "int8"
    except Exception:
        device = "cpu"
        compute = "int8"

    model = WhisperModel(model_size, device=device, compute_type=compute)
    suffix = ".wav" if filename.lower().endswith(".wav") else ".bin"
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(raw)
        tmp.flush()
        segments, _info = model.transcribe(tmp.name, beam_size=1, vad_filter=True)
        parts = [seg.text.strip() for seg in segments if seg.text.strip()]
    return " ".join(parts).strip()


async def probe_ollama_models() -> dict[str, Any]:
    if not ollama_ready():
        return {"ready": False, "detail": "Ollama not reachable", "models": []}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{ollama_base_url()}/api/tags")
        data = r.json()
        models = [m.get("name") for m in (data.get("models") or []) if m.get("name")]
        return {"ready": True, "detail": f"{len(models)} model(s)", "models": models}
    except Exception as exc:
        return {"ready": False, "detail": str(exc)[:120], "models": []}
