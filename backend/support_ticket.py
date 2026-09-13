"""Redacted support-ticket snapshots for Heirloom Unbound Terminal."""
from __future__ import annotations

import json
import platform
import re
import secrets
from datetime import datetime, timezone
from typing import Any

TICKET_PREFIX = "HU-"

_SECRET_KEY_FRAGMENTS = (
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
    "elevenlabs_api_key",
    "d_id_api_key",
    "fal_api_key",
    "emergent_llm_key",
    "resend_api_key",
    "openai_api_key",
)

_NEVER_ATTACH_KEYS = (
    "journal",
    "memory",
    "memories",
    "archive",
    "wav",
    "audio",
    "audio_bytes",
    "voice_wav",
    "recording",
    "transcript_audio",
)

_REDACT_PATTERNS = (
    re.compile(r"sk_[A-Za-z0-9_]{8,}", re.IGNORECASE),
    re.compile(r"(?i)(authorization\s*:\s*)bearer\s+\S+", re.IGNORECASE),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-+=/]{8,}"),
    re.compile(r"(?i)xi-api-key\s*[:=]\s*\S+"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*[^\s,;]{6,}"),
)


def new_ticket_id() -> str:
    return f"{TICKET_PREFIX}{secrets.token_hex(4).upper()}"


def redact_text(value: str) -> str:
    """Strip API keys, bearer tokens, and Authorization headers from free text."""
    if not value:
        return ""
    out = str(value)
    for pat in _REDACT_PATTERNS:
        if pat.groups:
            out = pat.sub(lambda m: (m.group(1) if m.lastindex else "") + "[redacted]", out)
        else:
            out = pat.sub("[redacted]", out)
    return out


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(frag in lowered for frag in _SECRET_KEY_FRAGMENTS)


def _is_forbidden_key(key: str) -> bool:
    lowered = key.lower()
    return any(frag == lowered or lowered.endswith(frag) for frag in _NEVER_ATTACH_KEYS)


def redact_value(value: Any, key: str = "") -> Any:
    if _is_secret_key(key) or _is_forbidden_key(key):
        return "[redacted]"
    if isinstance(value, dict):
        return {str(k): redact_value(v, str(k)) for k, v in value.items() if not _is_forbidden_key(str(k))}
    if isinstance(value, list):
        return [redact_value(item, key) for item in value[:400]]
    if isinstance(value, str):
        return redact_text(value)
    return value


def sanitize_probe(probe: dict | None) -> dict:
    """Keep ready/detail/url; drop credentials and media."""
    if not isinstance(probe, dict):
        return {}
    out: dict[str, Any] = {}
    for key, block in probe.items():
        if _is_secret_key(key) or _is_forbidden_key(key):
            continue
        if isinstance(block, dict):
            slim = {
                k: redact_value(v, k)
                for k, v in block.items()
                if k in {"ready", "detail", "url", "name", "models", "imported", "cached", "status"}
            }
            out[str(key)] = slim
        elif key in {"detail", "connected", "name"}:
            out[str(key)] = redact_value(block, key)
    return out


def build_ticket_snapshot(
    *,
    os_name: str | None = None,
    build_id: str | None = None,
    companion_version: str | None = None,
    probe: dict | None = None,
    model_map: dict | None = None,
    compute: dict | None = None,
    log_lines: list[str] | None = None,
    log_limit: int = 200,
) -> dict:
    """Archive snapshot safe to email. URLs stay; secrets and vault text do not."""
    compute_src = compute if isinstance(compute, dict) else {}
    remote = compute_src.get("remote") if isinstance(compute_src.get("remote"), dict) else {}
    slim_compute = {
        "mode": compute_src.get("mode") or "local",
        "device_id": None,  # device ids are fine; omit token-bearing fields
        "remote": {
            k: v
            for k, v in remote.items()
            if k in {"label", "ollama_url", "voicebox_url", "qwen3_tts_url", "latentsync_url", "musetalk_url"}
        },
    }
    lines = [redact_text(str(line)) for line in (log_lines or [])][-max(1, int(log_limit)) :]
    return {
        "product": "Heirloom Unbound",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "os": redact_text(os_name or f"{platform.system()} {platform.release()}"),
        "build_id": redact_text(build_id or ""),
        "companion_version": redact_text(companion_version or ""),
        "probe": sanitize_probe(probe),
        "model_map": redact_value(model_map if isinstance(model_map, dict) else {}),
        "compute": slim_compute,
        "log_tail": lines,
    }


def snapshot_json(snapshot: dict) -> str:
    return json.dumps(snapshot, indent=2, default=str)


def mailto_href(*, ticket_id: str, subject: str, email: str, snapshot: dict) -> str:
    from urllib.parse import quote

    subj = redact_text(subject or f"Heirloom Unbound ticket {ticket_id}")
    body = (
        f"Ticket {ticket_id}\nFrom: {redact_text(email)}\n\n"
        f"{snapshot_json(snapshot)[:4000]}\n"
    )
    return (
        f"mailto:support@heirloom.app"
        f"?subject={quote(subj)}"
        f"&body={quote(body[:1800])}"
    )
