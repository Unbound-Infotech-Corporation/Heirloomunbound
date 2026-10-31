"""Optional Odysseus workspace on the Twin Box LAN.

Odysseus (https://github.com/odysseus-dev/odysseus, compose service
``odysseus``) listens on container port 7000. The host map is
``${APP_PORT:-7011}``. From another container on the ``heirloom-box``
network the address is ``http://odysseus:7000`` once that service is
attached to the network. From the host it is ``http://192.168.0.110:7011``.

Admin-minted integration tokens look like ``ody_...`` and travel as
``Authorization: Bearer``. The secret is read from a file or the
environment and is never logged or returned by the API.

Chat uses ``POST /api/v1/chat`` (chat scope, no tools). Questions that
need current information use Deep Research: ``POST /api/research/start``,
then status and ``POST /api/research/result-peek/{id}`` (SearXNG inside
Odysseus). Odysseus main rejects API tokens on research start
(``require_user``), so a 403 falls back to ``/api/v1/chat``.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Optional
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

SERVICE_HOST = "odysseus"
HOST_PORT = 7011
SERVICE_PORT = 7000
CONNECT_TIMEOUT = 0.8
CHAT_TIMEOUT = 20.0
RESEARCH_TIMEOUT = 45.0
_TOKEN_RE = re.compile(r"ody_[A-Za-z0-9_\-]{6,}")
_SESSION_RE = re.compile(r"^[A-Za-z0-9_\-]{1,80}$")
_RUNNING = frozenset({"", "running", "pending", "started", "queued", "in_progress"})

Transport = Callable[[str, str, Optional[Mapping[str, Any]], float], Awaitable[tuple[int, Any]]]


@dataclass(frozen=True)
class OdysseusSettings:
    enabled: bool = False
    url: str = ""
    token: str = ""

    @property
    def ready(self) -> bool:
        return bool(self.enabled and self.url and self.token)


@dataclass
class OdysseusDraft:
    name: str = "odysseus"
    model: str = ""
    text: str = ""
    ok: bool = False
    via: str = ""
    error: str = ""
    latency_ms: int = 0


def _private_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.is_unspecified or ip.is_multicast or ip.is_reserved:
        return False
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local)


def normalize_odysseus_url(raw: str) -> str:
    """Return scheme://host:port or raise ValueError. No userinfo."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("Odysseus URL is empty")
    parts = urlsplit(text)
    if parts.scheme not in {"http", "https"}:
        raise ValueError("Odysseus URL must be http or https")
    if parts.username or parts.password:
        raise ValueError("Put the Odysseus token in the secret file, not the URL")
    host = parts.hostname
    if not host:
        raise ValueError("Odysseus URL needs a host")
    if host.lower() == SERVICE_HOST:
        port = parts.port or SERVICE_PORT
        if port < 1 or port > 65535:
            raise ValueError("Odysseus URL port is invalid")
        return f"{parts.scheme}://{SERVICE_HOST}:{port}"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("Odysseus URL must be a LAN IP or the odysseus service name") from exc
    if not _private_ip(ip):
        raise ValueError("Odysseus URL must stay on the LAN")
    rendered = str(ip)
    from brain_route import FORBIDDEN_HOSTS

    if rendered in FORBIDDEN_HOSTS:
        raise ValueError("That address is off limits")
    port = parts.port or HOST_PORT
    if port < 1 or port > 65535:
        raise ValueError("Odysseus URL port is invalid")
    shown = f"[{rendered}]" if ip.version == 6 else rendered
    return f"{parts.scheme}://{shown}:{port}"


def safe_odysseus_url(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    try:
        return normalize_odysseus_url(text)
    except ValueError:
        logger.error("HEIRLOOM_ODYSSEUS_URL is not a local address; ignoring it")
        return ""


def redact(text: str, token: str = "") -> str:
    """Drop token material before anything is logged or returned."""
    cleaned = text or ""
    secret = (token or "").strip()
    if secret:
        cleaned = cleaned.replace(secret, "ody_…")
    return _TOKEN_RE.sub("ody_…", cleaned)


def _read_token_file(path: str) -> str:
    file_path = (path or "").strip()
    if not file_path:
        return ""
    try:
        raw = Path(file_path).read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in raw.splitlines():
        token = line.strip()
        if token and not token.startswith("#"):
            return token
    return ""


def resolve_token(saved: Optional[Mapping[str, Any]] = None) -> str:
    """File, then env, then an owner-saved copy. Never log the value."""
    file_token = _read_token_file(os.environ.get("HEIRLOOM_ODYSSEUS_TOKEN_FILE") or "")
    if file_token:
        return file_token
    env_token = (os.environ.get("HEIRLOOM_ODYSSEUS_TOKEN") or "").strip()
    if env_token:
        return env_token
    if isinstance(saved, Mapping):
        return str(saved.get("odysseus_token") or "").strip()
    return ""


def _env_enabled() -> bool:
    return (os.environ.get("HEIRLOOM_ODYSSEUS") or "").strip().lower() in {"1", "true", "yes", "on"}


def odysseus_from_env() -> OdysseusSettings:
    url = safe_odysseus_url(os.environ.get("HEIRLOOM_ODYSSEUS_URL") or "")
    return OdysseusSettings(enabled=_env_enabled() and bool(url), url=url, token=resolve_token(None))


async def current_odysseus() -> OdysseusSettings:
    from brain_route import load_saved_settings

    saved = await load_saved_settings()
    return merge_odysseus(odysseus_from_env(), saved if isinstance(saved, Mapping) else None)


def merge_odysseus(base: OdysseusSettings, saved: Optional[Mapping[str, Any]]) -> OdysseusSettings:
    if not isinstance(saved, Mapping):
        return base
    if "odysseus_enabled" in saved:
        enabled = bool(saved.get("odysseus_enabled"))
    else:
        enabled = base.enabled
    if "odysseus_url" in saved:
        url = safe_odysseus_url(str(saved.get("odysseus_url") or ""))
    else:
        url = base.url
    return OdysseusSettings(enabled=enabled, url=url, token=resolve_token(saved))


def public_odysseus(settings: OdysseusSettings) -> dict[str, Any]:
    host = ""
    if settings.url:
        host = urlsplit(settings.url).hostname or ""
    return {
        "enabled": bool(settings.enabled),
        "ready": bool(settings.ready),
        "url": settings.url,
        "host": host,
        "token_set": bool(settings.token),
    }


def merge_owner_extras(doc: dict, body: Mapping[str, Any], current: Optional[Mapping[str, Any]]) -> dict:
    """Fold strategy and Odysseus fields into the owner brain document."""
    from brain_council import normalize_strategy

    prior = current if isinstance(current, Mapping) else {}
    out = dict(doc)
    if body.get("strategy") is not None:
        out["strategy"] = normalize_strategy(str(body.get("strategy") or ""), strict=True)
    elif str(prior.get("strategy") or "").strip():
        out["strategy"] = normalize_strategy(str(prior.get("strategy") or ""), strict=False)

    if body.get("odysseus_enabled") is not None:
        out["odysseus_enabled"] = bool(body.get("odysseus_enabled"))
    elif "odysseus_enabled" in prior:
        out["odysseus_enabled"] = bool(prior.get("odysseus_enabled"))

    if body.get("odysseus_url") is not None:
        raw_url = str(body.get("odysseus_url") or "").strip()
        out["odysseus_url"] = normalize_odysseus_url(raw_url) if raw_url else ""
    elif "odysseus_url" in prior:
        out["odysseus_url"] = str(prior.get("odysseus_url") or "")

    if body.get("clear_odysseus_token"):
        out["odysseus_token"] = ""
    elif str(body.get("odysseus_token") or "").strip():
        token = str(body.get("odysseus_token") or "").strip()
        if len(token) > 512:
            raise ValueError("Odysseus token is too long")
        out["odysseus_token"] = token
    elif str(prior.get("odysseus_token") or ""):
        out["odysseus_token"] = str(prior.get("odysseus_token") or "")
    return out


def context_for_odysseus(question: str, *, audience: str, memory_text: str = "") -> str:
    """The only text Odysseus may see: the question, never vault memories.

    Heir and caller turns drop ``memory_text`` the same way owner turns do.
    The argument exists so a caller cannot accidentally forward a pack.
    """
    del audience, memory_text
    return " ".join((question or "").split())[:4000]


def _timeout_seconds() -> float:
    raw = (os.environ.get("HEIRLOOM_ODYSSEUS_TIMEOUT") or "").strip()
    try:
        value = float(raw) if raw else RESEARCH_TIMEOUT
    except ValueError:
        value = RESEARCH_TIMEOUT
    return max(5.0, min(value, 120.0))


class OdysseusClient:
    def __init__(
        self,
        settings: OdysseusSettings,
        *,
        transport: Optional[Transport] = None,
        poll_interval: float = 0.4,
    ) -> None:
        self.settings = settings
        self._transport = transport
        self.poll_interval = poll_interval

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.token}",
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        body: Optional[Mapping[str, Any]],
        timeout: float,
    ) -> tuple[int, Any]:
        if self._transport is not None:
            return await self._transport(method, path, body, timeout)
        import httpx

        url = f"{self.settings.url.rstrip('/')}{path}"
        connect = min(CONNECT_TIMEOUT, timeout)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=connect)) as client:
                response = await client.request(method, url, json=None if body is None else dict(body), headers=self._headers())
        except Exception as exc:
            raise RuntimeError(type(exc).__name__) from exc
        payload: Any = None
        if response.content:
            try:
                payload = response.json()
            except Exception:
                payload = {"text": redact(response.text[:180], self.settings.token)}
        return response.status_code, payload

    async def chat(self, question: str, *, timeout: float = CHAT_TIMEOUT) -> OdysseusDraft:
        import time

        text = context_for_odysseus(question, audience="owner")
        if not self.settings.ready or not text:
            return OdysseusDraft(error="not_ready")
        started = time.perf_counter()
        try:
            status, payload = await self._request(
                "POST",
                "/api/v1/chat",
                {"message": text},
                timeout,
            )
        except Exception as exc:
            logger.warning("odysseus chat failed: %s", type(exc).__name__)
            return OdysseusDraft(error="unavailable", via="chat")
        if status >= 400 or not isinstance(payload, dict):
            logger.warning("odysseus chat HTTP %s", status)
            return OdysseusDraft(error=f"http_{status}", via="chat")
        reply = str(payload.get("response") or "").strip()
        model = str(payload.get("model") or "odysseus").strip() or "odysseus"
        elapsed = int((time.perf_counter() - started) * 1000)
        if not reply:
            return OdysseusDraft(model=model, error="empty", via="chat", latency_ms=max(0, elapsed))
        return OdysseusDraft(model=model, text=reply, ok=True, via="chat", latency_ms=max(0, elapsed))

    async def research(self, question: str, *, timeout: Optional[float] = None) -> OdysseusDraft:
        """Deep Research, with a chat fallback when the token cannot start it."""
        import asyncio
        import time

        budget = _timeout_seconds() if timeout is None else timeout
        text = context_for_odysseus(question, audience="owner")
        if not self.settings.ready or not text:
            return OdysseusDraft(error="not_ready")
        started = time.perf_counter()
        try:
            status, payload = await self._request(
                "POST",
                "/api/research/start",
                {"query": text, "max_rounds": 2, "max_time": 60},
                min(8.0, budget),
            )
        except Exception as exc:
            logger.warning("odysseus research failed: %s", type(exc).__name__)
            return OdysseusDraft(error="unavailable", via="research")
        if status in {401, 403}:
            logger.warning("odysseus research refused the API token; using chat")
            draft = await self.chat(text, timeout=budget)
            draft.via = "chat"
            return draft
        if status >= 400 or not isinstance(payload, dict):
            logger.warning("odysseus research HTTP %s", status)
            return OdysseusDraft(error=f"http_{status}", via="research")
        session_id = str(payload.get("session_id") or "").strip()
        if not _SESSION_RE.match(session_id):
            return OdysseusDraft(error="bad_session", via="research")
        deadline = time.perf_counter() + budget
        state = str(payload.get("status") or "running")
        while state.lower() in _RUNNING and time.perf_counter() < deadline:
            if self.poll_interval:
                await asyncio.sleep(self.poll_interval)
            try:
                peek_status, view = await self._request(
                    "GET",
                    f"/api/research/status/{session_id}",
                    None,
                    5.0,
                )
            except Exception as exc:
                logger.warning("odysseus research status failed: %s", type(exc).__name__)
                break
            if peek_status >= 400 or not isinstance(view, dict):
                break
            state = str(view.get("status") or "completed")
        try:
            result_status, result = await self._request(
                "POST",
                f"/api/research/result-peek/{session_id}",
                {},
                8.0,
            )
        except Exception as exc:
            logger.warning("odysseus research result failed: %s", type(exc).__name__)
            return OdysseusDraft(error="unavailable", via="research")
        if result_status >= 400 or not isinstance(result, dict):
            return OdysseusDraft(error=f"http_{result_status}", via="research")
        reply = ""
        for key in ("result", "response", "report", "text"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                reply = value.strip()
                break
        elapsed = int((time.perf_counter() - started) * 1000)
        if not reply:
            return OdysseusDraft(error="empty", via="research", latency_ms=elapsed)
        return OdysseusDraft(
            model="deep-research",
            text=reply[:4000],
            ok=True,
            via="research",
            latency_ms=max(0, elapsed),
        )
