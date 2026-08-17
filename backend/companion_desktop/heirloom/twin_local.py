"""Local Ollama twin inference on the dedicated PC."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Optional

from .models import probe_ollama

OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "llama3.1"


def ollama_ready() -> bool:
    return bool(probe_ollama().get("ready"))


def should_use_local_twin(model_map: dict | None) -> bool:
    if not ollama_ready():
        return False
    pick = (model_map or {}).get("twin", "auto")
    if pick == "cloud_claude":
        return False
    return pick in ("auto", "ollama")


def generate_reply(
    system: str,
    history: list[dict],
    user_text: str,
    *,
    model: str | None = None,
    timeout: float = 120.0,
) -> str:
    messages = [{"role": "system", "content": system}]
    for turn in history:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_text.strip()})

    body = json.dumps(
        {
            "model": model or DEFAULT_MODEL,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.65, "num_predict": 512},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_URL.rstrip('/')}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"Ollama HTTP {exc.code}: {detail}") from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Ollama unreachable: {exc!s}") from exc

    msg = data.get("message") or {}
    text = (msg.get("content") or "").strip()
    if not text:
        raise RuntimeError("Ollama returned empty reply")
    return text
