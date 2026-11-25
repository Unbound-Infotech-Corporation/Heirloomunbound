"""Public health payload for the Twin Box and ``GET /api/health``.

No secrets. The product version string matches the existing 0.5.1 titlebar.
A Twin Box does not report ok from a stale file, a crash-looping unit, or a
chat model that will not answer.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from ai_disclosure import disclosure_enabled
from lab_mode import box_mode_enabled, lab_mode_enabled
from llm_provider import resolve_llm_provider
from product_info import PRODUCT_VERSION
from observer_store import status_public
from presence_store import status_public as presence_status_public

MODEL_FRESH_S = 180
_PROBE_CACHE: dict[str, Any] = {"at": 0.0, "probe": None}


def _compute() -> dict[str, str]:
    """GPU name and twin model when the installer wrote them. Empty when unset."""
    gpu = (os.environ.get("HEIRLOOM_GPU_NAME") or "").strip()
    model = (os.environ.get("OLLAMA_TWIN_MODEL") or "").strip()
    found: dict[str, str] = {}
    if gpu:
        found["gpu"] = gpu
    if model:
        found["model"] = model
    return found


def assess_model_probe(probe: Optional[dict], *, now: Optional[datetime] = None, fresh_s: int = MODEL_FRESH_S) -> dict[str, Any]:
    """A tiny local reply counts only while the check itself is fresh."""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    body = probe if isinstance(probe, dict) else {}
    reply = str(body.get("reply") or "").strip()
    checked = _parse_iso(str(body.get("checked_at") or ""))
    age_s = int((moment - checked).total_seconds()) if checked is not None else None
    age_ok = age_s is not None and age_s <= fresh_s
    ok = bool(body.get("ok")) and bool(reply) and age_ok
    reason = ""
    if not body.get("ok") or not reply:
        reason = str(body.get("error") or "the chat model did not answer")
    elif not age_ok:
        reason = "the model check is stale"
    return {
        "ok": ok,
        "model": str(body.get("model") or ""),
        "reply": reply[:80],
        "checked_at": str(body.get("checked_at") or ""),
        "age_s": age_s,
        "error": "" if ok else reason[:200],
    }


def overall_status(*, observer: dict, model: Optional[dict], box: bool) -> str:
    """No false green. Observer off is fine. A stale signal or a dead model is not."""
    if observer.get("enabled") and (
        str(observer.get("signal") or "") == "failing" or str(observer.get("unit") or "") == "failing"
    ):
        return "failing"
    if observer.get("enabled") and not observer.get("fresh"):
        return "degraded"
    if box:
        if not model or not model.get("ok"):
            return "degraded"
    return "ok"


def probe_local_chat(
    *,
    base_url: str,
    model: str,
    opener: Optional[Callable[..., Any]] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Ask the configured local model for one word. Empty, error, and cloud hosts are not ok."""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    host = (base_url or "").strip().rstrip("/")
    name = (model or "").strip()
    if not host or not name:
        return {"ok": False, "model": name, "reply": "", "checked_at": moment.isoformat(), "error": "chat model is not configured"}
    lowered = host.lower()
    if any(name in lowered for name in ("openai.com", "anthropic.com", "googleapis.com", "generativelanguage")):
        return {"ok": False, "model": name, "reply": "", "checked_at": moment.isoformat(), "error": "refusing a cloud model host"}
    payload = json.dumps({
        "model": name,
        "messages": [{"role": "user", "content": "Reply with the single word pong."}],
        "stream": False,
        "options": {"temperature": 0, "num_predict": 8},
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{host}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    send = opener or urllib.request.urlopen
    try:
        with send(request, timeout=12) as response:
            raw = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "model": name, "reply": "", "checked_at": moment.isoformat(), "error": str(exc)[:200]}
    try:
        loaded = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeError, json.JSONDecodeError):
        loaded = {}
    message = loaded.get("message") if isinstance(loaded, dict) else None
    reply = ""
    if isinstance(message, dict):
        reply = str(message.get("content") or "").strip()
    return {
        "ok": bool(reply),
        "model": name,
        "reply": reply[:80],
        "checked_at": moment.isoformat(),
        "error": "" if reply else "the chat model returned nothing",
    }


def _cached_probe(box: bool, probe: Optional[Callable[[], dict]]) -> Optional[dict]:
    if probe is not None:
        return probe()
    if not box:
        return None
    now_s = time.monotonic()
    cached = _PROBE_CACHE.get("probe")
    if isinstance(cached, dict) and now_s - float(_PROBE_CACHE.get("at") or 0) < 60:
        return cached
    from llm_provider import ollama_base_url, ollama_model

    fresh = probe_local_chat(base_url=ollama_base_url(), model=ollama_model())
    _PROBE_CACHE["at"] = now_s
    _PROBE_CACHE["probe"] = fresh
    return fresh


def _parse_iso(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def health_payload(
    *,
    now: Optional[datetime] = None,
    model_probe: Optional[Callable[[], dict]] = None,
) -> dict[str, object]:
    box = box_mode_enabled()
    observer = status_public(now=now)
    model = assess_model_probe(_cached_probe(box, model_probe), now=now) if box else None
    payload: dict[str, object] = {
        "status": overall_status(observer=observer, model=model, box=box),
        "app": "digital-heirloom",
        "version": PRODUCT_VERSION,
        "llm_provider": resolve_llm_provider(),
        "lab_mode": lab_mode_enabled(),
        "box": box,
        "ai_disclosure": disclosure_enabled(),
        "observer": observer,
        "presence": presence_status_public(),
    }
    if model is not None:
        payload["model"] = model
    compute = _compute()
    if compute:
        payload["compute"] = compute
    try:
        from brain_route import brain_status

        payload["brain"] = brain_status()
    except Exception:
        payload["brain"] = {"answered": "local", "remote_configured": False}
    return payload
