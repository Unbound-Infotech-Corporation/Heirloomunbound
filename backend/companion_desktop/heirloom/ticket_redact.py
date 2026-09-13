"""Redact secrets before a Heirloom Unbound support ticket leaves this PC."""
from __future__ import annotations

import json
import platform
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

_SECRET_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "password",
    "secret",
    "token",
    "device_token",
    "session_token",
    "xi-api-key",
)
_NEVER = ("journal", "memory", "memories", "archive", "wav", "audio", "audio_bytes", "voice_wav", "recording")
_PATTERNS = (
    re.compile(r"sk_[A-Za-z0-9_]{8,}", re.IGNORECASE),
    re.compile(r"(?i)(authorization\s*:\s*)bearer\s+\S+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-+=/]{8,}"),
    re.compile(r"(?i)xi-api-key\s*[:=]\s*\S+"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*[^\s,;]{6,}"),
)


def redact_text(value: str) -> str:
    out = str(value or "")
    for pat in _PATTERNS:
        if pat.groups:
            out = pat.sub(lambda m: (m.group(1) if m.lastindex else "") + "[redacted]", out)
        else:
            out = pat.sub("[redacted]", out)
    return out


def _secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(frag in lowered for frag in _SECRET_FRAGMENTS)


def _forbidden(key: str) -> bool:
    lowered = key.lower()
    return any(frag == lowered or lowered.endswith(frag) for frag in _NEVER)


def redact_value(value: Any, key: str = "") -> Any:
    if _secret_key(key) or _forbidden(key):
        return "[redacted]"
    if isinstance(value, dict):
        return {str(k): redact_value(v, str(k)) for k, v in value.items() if not _forbidden(str(k))}
    if isinstance(value, list):
        return [redact_value(item, key) for item in value[:400]]
    if isinstance(value, str):
        return redact_text(value)
    return value


def sanitize_probe(probe: dict | None) -> dict:
    if not isinstance(probe, dict):
        return {}
    out: dict[str, Any] = {}
    for key, block in probe.items():
        if _secret_key(str(key)) or _forbidden(str(key)):
            continue
        if isinstance(block, dict):
            out[str(key)] = {
                k: redact_value(v, k)
                for k, v in block.items()
                if k in {"ready", "detail", "url", "name", "models", "imported", "cached", "status"}
            }
        elif key in {"detail", "connected", "name"}:
            out[str(key)] = redact_value(block, str(key))
    return out


def build_snapshot(
    *,
    build_id: str,
    companion_version: str,
    probe: dict | None,
    model_map: dict | None,
    compute: dict | None,
    log_lines: list[str],
) -> dict:
    compute_src = compute if isinstance(compute, dict) else {}
    remote = compute_src.get("remote") if isinstance(compute_src.get("remote"), dict) else {}
    return {
        "product": "Heirloom Unbound",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "os": f"{platform.system()} {platform.release()}",
        "build_id": redact_text(build_id),
        "companion_version": redact_text(companion_version),
        "probe": sanitize_probe(probe),
        "model_map": redact_value(model_map if isinstance(model_map, dict) else {}),
        "compute": {
            "mode": compute_src.get("mode") or "local",
            "remote": {
                k: v
                for k, v in remote.items()
                if k in {"label", "ollama_url", "voicebox_url", "qwen3_tts_url", "latentsync_url", "musetalk_url"}
            },
        },
        "log_tail": [redact_text(str(line)) for line in log_lines[-200:]],
    }


def snapshot_json(snapshot: dict) -> str:
    return json.dumps(snapshot, indent=2, default=str)


def mailto_href(ticket_id: str, subject: str, email: str, snapshot: dict) -> str:
    subj = redact_text(subject or f"Heirloom Unbound ticket {ticket_id}")
    body = f"Ticket {ticket_id}\nFrom: {redact_text(email)}\n\n{snapshot_json(snapshot)[:4000]}\n"
    return f"mailto:support@heirloom.app?subject={quote(subj)}&body={quote(body[:1800])}"
