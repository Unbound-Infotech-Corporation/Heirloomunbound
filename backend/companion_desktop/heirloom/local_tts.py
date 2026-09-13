"""Test-phrase speak path for Heirloom Unbound Voice window."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from . import config
from .models import engine_urls, resolve_tts_backend_local
from .studio_log import error as log_error
from .studio_log import info as log_info


def _post_bytes(url: str, payload: dict, headers: dict | None = None, timeout: float = 20.0) -> tuple[int, bytes]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "audio/mpeg, application/json, */*", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(getattr(resp, "status", 200) or 200), resp.read(2_000_000)
    except urllib.error.HTTPError as exc:
        return int(exc.code), (exc.read() if exc.fp else b"")


def speak_test(
    text: str,
    *,
    model_map: dict | None = None,
    probe: dict | None = None,
    has_voice_clone: bool = False,
) -> dict[str, Any]:
    """Resolve backend, hit local HTTP or /desktop/speak, log latency. Never raises."""
    phrase = (text or "Heirloom Unbound is listening.").strip()[:400]
    backend = resolve_tts_backend_local(model_map, probe, has_voice_clone=has_voice_clone)
    urls = engine_urls()
    started = time.perf_counter()
    result: dict[str, Any] = {"backend": backend, "ok": False, "detail": "", "bytes": 0}
    try:
        if backend == "voicebox":
            status, raw = _post_bytes(
                f"{urls['voicebox_url']}/v1/audio/speech",
                {"model": "voicebox", "input": phrase, "voice": "default"},
            )
            result["ok"] = 200 <= status < 300 and bool(raw)
            result["detail"] = f"Voicebox HTTP {status}"
            result["bytes"] = len(raw)
        elif backend == "qwen3_tts":
            status, raw = _post_bytes(
                f"{urls['qwen3_tts_url']}/v1/audio/speech",
                {"model": "qwen3-tts", "input": phrase, "voice": "default"},
            )
            result["ok"] = 200 <= status < 300 and bool(raw)
            result["detail"] = f"Qwen3-TTS HTTP {status}"
            result["bytes"] = len(raw)
        else:
            import requests

            if not config.DEVICE_TOKEN:
                result["detail"] = "no device token — cannot reach /desktop/speak"
            else:
                r = requests.post(
                    f"{config.BACKEND_URL.rstrip('/')}/api/desktop/speak",
                    headers={"Authorization": f"Bearer {config.DEVICE_TOKEN}"},
                    json={"text": phrase},
                    timeout=45,
                )
                result["ok"] = r.status_code == 200 and bool(r.content)
                result["detail"] = f"/desktop/speak HTTP {r.status_code}"
                result["bytes"] = len(r.content or b"")
    except Exception as exc:  # noqa: BLE001
        result["detail"] = str(exc)[:200]
    result["ms"] = int((time.perf_counter() - started) * 1000)
    line = f"tts {backend} · {result['ms']}ms · {result['detail']}"
    if result["ok"]:
        log_info("tts", line, backend=backend, ms=result["ms"])
    else:
        log_error("tts", line, backend=backend, ms=result["ms"])
    log_info("router", f"resolved tts={backend}", pick=(model_map or {}).get("tts", "auto"))
    return result
