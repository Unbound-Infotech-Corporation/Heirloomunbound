"""HTTP probes for standalone local voice / lipsync engines.

Copied beside the companion so the baked zip does not import FastAPI.
Timeouts are short; every helper returns a dict and never raises.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

VOICEBOX_DEFAULT = "http://127.0.0.1:17493"
QWEN3_TTS_DEFAULT = "http://127.0.0.1:8001"
LATENTSYNC_DEFAULT = "http://127.0.0.1:7860"
MUSETALK_DEFAULT = "http://127.0.0.1:7861"
PROBE_TIMEOUT_SEC = 1.4


def _clean_url(url: str | None, default: str) -> str:
    raw = (url or default or "").strip().rstrip("/")
    if not raw.startswith(("http://", "https://")):
        raw = default.rstrip("/")
    return raw[:512]


def probe_http_get(url: str, path: str = "", *, timeout: float = PROBE_TIMEOUT_SEC) -> dict[str, Any]:
    target = _clean_url(url, url or "http://127.0.0.1")
    if path:
        if not path.startswith("/"):
            path = "/" + path
        target = f"{target}{path}"
    try:
        req = urllib.request.Request(
            target,
            method="GET",
            headers={"Accept": "application/json, text/plain, */*"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(8000)
            status = int(getattr(resp, "status", 200) or 200)
            ready = 200 <= status < 300
            detail = f"HTTP {status}"
            snippet = body.decode("utf-8", errors="replace").strip()
            if snippet:
                detail = f"{detail} · {snippet[:160]}"
            return {"ready": ready, "detail": detail, "url": _clean_url(url, url or target), "status": status, "body": snippet}
    except urllib.error.HTTPError as exc:
        return {
            "ready": False,
            "detail": f"HTTP {exc.code}",
            "url": _clean_url(url, url or target),
            "status": int(exc.code),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ready": False,
            "detail": str(exc)[:200] or "unreachable",
            "url": _clean_url(url, url or target),
        }


def probe_voicebox(url: str | None = None, *, timeout: float = PROBE_TIMEOUT_SEC) -> dict[str, Any]:
    base = _clean_url(url, VOICEBOX_DEFAULT)
    health = probe_http_get(base, "/health", timeout=timeout)
    if health.get("ready"):
        return {"ready": True, "detail": health.get("detail") or "Voicebox listening", "url": base}
    root = probe_http_get(base, "/", timeout=timeout)
    if root.get("ready"):
        return {"ready": True, "detail": root.get("detail") or "Voicebox listening", "url": base}
    return {"ready": False, "detail": health.get("detail") or root.get("detail") or "Voicebox not listening", "url": base}


def probe_qwen3_tts(url: str | None = None, *, timeout: float = PROBE_TIMEOUT_SEC) -> dict[str, Any]:
    base = _clean_url(url, QWEN3_TTS_DEFAULT)
    result = probe_http_get(base, "/v1/models", timeout=timeout)
    out: dict[str, Any] = {"ready": bool(result.get("ready")), "detail": result.get("detail") or "Qwen3-TTS not listening", "url": base}
    if result.get("ready"):
        raw = result.get("body") or ""
        try:
            payload = json.loads(raw) if raw.startswith("{") else {}
            models = payload.get("data") if isinstance(payload, dict) else None
            if isinstance(models, list):
                names = [str(m.get("id") or "") for m in models if isinstance(m, dict) and m.get("id")]
                if names:
                    out["detail"] = f"{len(names)} model(s): {', '.join(names[:4])}"
                    out["models"] = names
        except Exception:
            out["detail"] = result.get("detail") or "Qwen3-TTS /v1/models ok"
    return out


def probe_latentsync(url: str | None = None, *, timeout: float = PROBE_TIMEOUT_SEC) -> dict[str, Any]:
    base = _clean_url(url, LATENTSYNC_DEFAULT)
    result = probe_http_get(base, "/", timeout=timeout)
    if not result.get("ready"):
        health = probe_http_get(base, "/health", timeout=timeout)
        if health.get("ready"):
            result = health
    return {
        "ready": bool(result.get("ready")),
        "detail": result.get("detail") or "LatentSync not listening (optional)",
        "url": base,
    }


def probe_musetalk(url: str | None = None, *, timeout: float = PROBE_TIMEOUT_SEC) -> dict[str, Any]:
    base = _clean_url(url, MUSETALK_DEFAULT)
    result = probe_http_get(base, "/", timeout=timeout)
    return {
        "ready": bool(result.get("ready")),
        "detail": result.get("detail") or "MuseTalk not listening (optional)",
        "url": base,
    }
