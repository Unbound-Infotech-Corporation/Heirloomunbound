"""Retell AI HTTP + custom-LLM protocol helpers for Twin phone.

Heirloom owns the Twin brain. Retell owns PSTN, turn-taking, and TTS.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse

import httpx

RETELL_API_BASE = os.environ.get("RETELL_API_BASE", "https://api.retellai.com").rstrip("/")
DEFAULT_STOCK_VOICE = os.environ.get("RETELL_DEFAULT_VOICE_ID", "11labs-Adrian")


def retell_api_key() -> str:
    return (os.environ.get("RETELL_API_KEY") or "").strip()


def webhook_secret() -> str:
    return (os.environ.get("RETELL_WEBHOOK_SECRET") or retell_api_key()).strip()


def configured() -> bool:
    return bool(retell_api_key())


def public_http_base() -> str:
    return (
        os.environ.get("PUBLIC_BACKEND_URL")
        or os.environ.get("REACT_APP_BACKEND_URL")
        or ""
    ).rstrip("/")


def public_ws_base() -> str:
    http = public_http_base()
    parsed = urlparse(http)
    if parsed.scheme == "https":
        parsed = parsed._replace(scheme="wss")
    elif parsed.scheme == "http":
        parsed = parsed._replace(scheme="ws")
    else:
        return ""
    return urlunparse(parsed).rstrip("/")


def llm_websocket_url() -> str:
    base = public_ws_base()
    if not base:
        return ""
    return f"{base}/api/phone/retell/llm"


def webhook_url() -> str:
    base = public_http_base()
    if not base:
        return ""
    return f"{base}/api/phone/retell/webhook"


def verify_webhook_signature(raw_body: bytes, signature: str, *, secret: str = "") -> bool:
    key = (secret or webhook_secret()).encode("utf-8")
    if not key or not signature:
        return False
    digest = hmac.new(key, raw_body, hashlib.sha256).hexdigest()
    offered = signature.strip()
    if offered.lower().startswith("sha256="):
        offered = offered.split("=", 1)[1].strip()
    return hmac.compare_digest(digest, offered)


def event_key(event: str, call_id: str) -> str:
    return f"{(event or '').strip()}:{(call_id or '').strip()}"


def latest_user_text(transcript: Any) -> str:
    if not isinstance(transcript, list):
        return ""
    for turn in reversed(transcript):
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role") or "").strip().lower()
        if role in {"user", "human"}:
            return str(turn.get("content") or "").strip()
    return ""


def format_transcript(transcript: Any, *, caller_name: str = "") -> str:
    """Plain spoken log for Phone. Accepts Retell's list or a finished string."""
    if isinstance(transcript, str):
        return transcript.strip()
    if not isinstance(transcript, list):
        return ""
    them = (caller_name or "Them").strip() or "Them"
    lines: list[str] = []
    for turn in transcript:
        if not isinstance(turn, dict):
            continue
        content = str(turn.get("content") or "").strip()
        if not content:
            continue
        role = str(turn.get("role") or "").strip().lower()
        who = them if role in {"user", "human"} else "Twin"
        lines.append(f"{who}: {content}")
    return "\n".join(lines)


def agent_has_spoken(transcript: Any) -> bool:
    if not isinstance(transcript, list):
        return False
    for turn in transcript:
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role") or "").strip().lower()
        if role in {"agent", "assistant"} and str(turn.get("content") or "").strip():
            return True
    return False


def spoken_reply(
    content: str,
    *,
    response_id: int,
    complete: bool = True,
    end_call: bool = False,
    transfer_number: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "response_type": "response",
        "response_id": response_id,
        "content": content,
        "content_complete": complete,
    }
    if end_call:
        payload["end_call"] = True
    if transfer_number:
        payload["transfer_number"] = transfer_number
    return payload


def config_hello() -> dict[str, Any]:
    return {
        "response_type": "config",
        "config": {"auto_reconnect": True, "call_details": True},
    }


def ping_pong(timestamp: Any) -> dict[str, Any]:
    return {"response_type": "ping_pong", "timestamp": timestamp}


def for_speech(text: str) -> str:
    """Strip citation chips and markdown so Retell can speak the line."""
    raw = (text or "").strip()
    raw = re.sub(r"\[#[^\]]+\]", "", raw)
    raw = re.sub(r"[*_`#]+", "", raw)
    raw = re.sub(r"\n{2,}", "\n", raw)
    return " ".join(raw.split()).strip()


class RetellError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _headers() -> dict[str, str]:
    key = retell_api_key()
    if not key:
        raise RetellError(503, "Retell is not configured. Add RETELL_API_KEY.")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


async def _request(method: str, path: str, *, json: Any = None, timeout: float = 30.0) -> dict[str, Any]:
    url = f"{RETELL_API_BASE}{path}"
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.request(method, url, headers=_headers(), json=json)
    if response.status_code >= 400:
        detail = response.text[:400] or f"HTTP {response.status_code}"
        raise RetellError(response.status_code, detail)
    if not response.content:
        return {}
    data = response.json()
    return data if isinstance(data, dict) else {"data": data}


async def create_agent(
    *,
    name: str,
    voice_id: str,
    webhook: str,
    llm_ws: str,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "agent_name": name[:80] or "Heirloom Twin",
        "response_engine": {
            "type": "custom-llm",
            "llm_websocket_url": llm_ws,
        },
        "voice_id": voice_id or DEFAULT_STOCK_VOICE,
        "language": "en-US",
        "webhook_url": webhook,
        "webhook_events": ["call_started", "call_ended", "call_analyzed"],
        "max_call_duration_ms": 20 * 60 * 1000,
        "end_call_after_silence_ms": 45 * 1000,
        "enable_backchannel": True,
    }
    return await _request("POST", "/create-agent", json=body)


async def update_agent(agent_id: str, **fields: Any) -> dict[str, Any]:
    body = {"agent_id": agent_id, **fields}
    return await _request("PATCH", "/update-agent", json=body)


async def delete_agent(agent_id: str) -> None:
    if not agent_id:
        return
    try:
        await _request("DELETE", f"/delete-agent/{agent_id}")
    except RetellError:
        await _request("POST", "/delete-agent", json={"agent_id": agent_id})


async def create_phone_number(*, inbound_agent_id: str, outbound_agent_id: str) -> dict[str, Any]:
    return await _request(
        "POST",
        "/create-phone-number",
        json={
            "inbound_agent_id": inbound_agent_id,
            "outbound_agent_id": outbound_agent_id,
        },
    )


async def delete_phone_number(e164: str) -> None:
    if not e164:
        return
    try:
        await _request("DELETE", f"/delete-phone-number/{e164}")
    except RetellError:
        await _request("POST", "/delete-phone-number", json={"phone_number": e164})


async def create_phone_call(
    *,
    from_number: str,
    to_number: str,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "from_number": from_number,
        "to_number": to_number,
    }
    if metadata:
        body["metadata"] = metadata
    try:
        return await _request("POST", "/v2/create-phone-call", json=body)
    except RetellError as exc:
        if exc.status != 404:
            raise
        return await _request("POST", "/create-phone-call", json=body)


async def get_call(call_id: str) -> dict[str, Any]:
    try:
        return await _request("GET", f"/v2/get-call/{call_id}")
    except RetellError as exc:
        if exc.status != 404:
            raise
        return await _request("GET", f"/get-call/{call_id}")


async def import_elevenlabs_voice(*, voice_id: str, name: str, api_key: str) -> Optional[str]:
    """Best-effort import of an existing ElevenLabs clone into Retell.

    Returns a Retell voice_id, or None if the vendor does not accept the import
    (dashboard-only voices still work via stock fallback).
    """
    if not voice_id:
        return None
    payloads = [
        {
            "voice_name": (name or "Heirloom Twin")[:80],
            "voice_provider": "elevenlabs",
            "voice_id": voice_id,
            "elevenlabs_api_key": api_key,
        },
        {
            "voice_name": (name or "Heirloom Twin")[:80],
            "provider": "11labs",
            "provider_voice_id": voice_id,
        },
    ]
    for body in payloads:
        try:
            data = await _request("POST", "/create-custom-voice", json=body)
        except RetellError:
            try:
                data = await _request("POST", "/create-voice", json=body)
            except RetellError:
                continue
        for key in ("voice_id", "custom_voice_id", "id"):
            value = str(data.get(key) or "").strip()
            if value:
                return value
    return None
