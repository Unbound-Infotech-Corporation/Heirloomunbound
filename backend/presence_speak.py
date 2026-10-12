"""Optional greeting audio. Off unless PRESENCE_SPEAK=1. Nothing is uploaded."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Callable, Optional

_ON = frozenset({"1", "true", "yes", "on"})


def speak_enabled(raw: Optional[str] = None) -> bool:
    if raw is None:
        raw = os.environ.get("PRESENCE_SPEAK", "")
    return (raw or "").strip().lower() in _ON


def speak_url(raw: Optional[str] = None) -> str:
    if raw is None:
        raw = os.environ.get("PRESENCE_SPEAK_URL", "http://127.0.0.1:8010/speak")
    return (raw or "").strip() or "http://127.0.0.1:8010/speak"


def _post_json(url: str, text: str) -> dict:
    body = json.dumps({"text": text}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        payload = response.read(4096)
    if not payload:
        return {"status": "ok"}
    try:
        loaded = json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError:
        return {"status": "ok"}
    return loaded if isinstance(loaded, dict) else {"status": "ok"}


def speak_greeting(
    text: str,
    *,
    enabled: Optional[bool] = None,
    poster: Optional[Callable[[str, str], dict]] = None,
    url: Optional[str] = None,
) -> dict:
    """Speak on the box when Chatterbox (or another local sink) is configured."""
    phrase = (text or "").strip()
    if not phrase:
        return {"spoken": False, "reason": "empty"}
    active = speak_enabled() if enabled is None else bool(enabled)
    if not active:
        return {"spoken": False, "reason": "off"}
    target = speak_url(url)
    send = poster or _post_json
    try:
        result = send(target, phrase[:500])
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        return {"spoken": False, "reason": "unreachable", "detail": str(exc)[:160]}
    return {"spoken": True, "reason": "local", "result": result if isinstance(result, dict) else {}}
