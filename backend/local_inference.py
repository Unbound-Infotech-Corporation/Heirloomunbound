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

    headers: dict[str, str] = {}
    from brain_route import maybe_route

    routed = await maybe_route()
    if routed is not None:
        base_url = routed.url
        model = routed.model
        headers = dict(routed.headers)
    body = {
        "model": model or OLLAMA_MODEL,
        "messages": payload_messages,
        "stream": False,
        "options": {"temperature": 0.65, "num_predict": 512},
    }
    url = f"{(base_url or ollama_base_url()).rstrip('/')}/api/chat"
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, json=body, headers=headers)
    if r.status_code >= 400:
        raise RuntimeError(f"Ollama HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    msg = data.get("message") or {}
    text = (msg.get("content") or "").strip()
    if not text:
        raise RuntimeError("Ollama returned empty content")
    from brain_route import remember_answer

    if routed is None:
        remember_answer(
            name="local",
            model=str(body["model"]),
            url=(base_url or ollama_base_url()),
        )
    return text


_whisper_model = None
_whisper_key = ""


def whisper_runtime() -> tuple[str, str, str]:
    """Model size, device, compute. CUDA when the process can see a GPU, else CPU int8."""
    model = (os.environ.get("WHISPER_MODEL") or os.environ.get("OBSERVER_WHISPER_MODEL") or "base").strip() or "base"
    device = "cpu"
    compute = "int8"
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            device = "cuda"
            compute = "float16"
    except Exception:
        device = "cpu"
        compute = "int8"
    forced = (os.environ.get("WHISPER_DEVICE") or "").strip().lower()
    if forced in {"cpu", "cuda"}:
        device = forced
        compute = "float16" if forced == "cuda" else "int8"
    return model, device, compute


def transcribe_whisper_bytes(
    raw: bytes,
    *,
    filename: str = "audio.wav",
    model_size: str = "",
) -> str:
    """Transcribe WAV/PCM bytes with faster-whisper if installed. Fully local."""
    if not raw:
        return ""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("faster-whisper not installed on this host") from exc

    global _whisper_model, _whisper_key
    size, device, compute = whisper_runtime()
    if model_size:
        size = model_size
    cache = (os.environ.get("WHISPER_CACHE") or "/var/lib/heirloom/whisper").strip() or "/var/lib/heirloom/whisper"
    try:
        os.makedirs(cache, exist_ok=True)
    except OSError:
        cache = ""
    key = f"{size}:{device}:{compute}:{cache}"
    if _whisper_model is None or _whisper_key != key:
        kwargs = {"device": device, "compute_type": compute}
        if cache:
            kwargs["download_root"] = cache
        try:
            _whisper_model = WhisperModel(size, **kwargs)
        except Exception:
            if device != "cpu":
                fallback = {"device": "cpu", "compute_type": "int8"}
                if cache:
                    fallback["download_root"] = cache
                _whisper_model = WhisperModel(size, **fallback)
                device = "cpu"
            else:
                raise
        _whisper_key = key
    model = _whisper_model
    suffix = ".wav" if filename.lower().endswith(".wav") else ".bin"
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(raw)
        tmp.flush()
        segments, _info = model.transcribe(tmp.name, beam_size=1, vad_filter=True)
        parts = [seg.text.strip() for seg in segments if seg.text.strip()]
    return " ".join(parts).strip()


def embed_model() -> str:
    return (os.environ.get("OLLAMA_EMBED_MODEL") or "nomic-embed-text").strip() or "nomic-embed-text"


async def ollama_embed_many(texts: list[str], *, timeout: float = 2.0) -> list[list[float]] | None:
    """Local embeddings from the box Ollama. None when the model is absent."""
    rows = [text for text in texts if (text or "").strip()]
    if not rows or len(rows) != len(texts):
        return None
    url = f"{ollama_base_url().rstrip('/')}/api/embed"
    body = {"model": embed_model(), "input": rows}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=body)
        if response.status_code >= 400:
            return None
        payload = response.json()
    except Exception:
        return None
    vectors = payload.get("embeddings") if isinstance(payload, dict) else None
    if not isinstance(vectors, list) or len(vectors) != len(rows):
        return None
    cleaned: list[list[float]] = []
    for vector in vectors:
        if not isinstance(vector, list) or not vector:
            return None
        cleaned.append([float(item) for item in vector])
    return cleaned


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
