"""Owner privacy fence for Setup, Assist, Code, Smart Home, and Writing.

Heirs and callers stay Twin-only: owner routes answer 404, not 403, so the
route does not advertise itself. Owner-private memories are stripped before
anything is handed to Odysseus, web research, a smart-home vendor, a writing
engine, or an MCP connector.

This module does not choose a chat model. Twin routing stays in
``model_router.py`` and ``llm_provider.py`` (local Ollama only).
"""
from __future__ import annotations

import ipaddress
import re
from typing import Any, Mapping
from urllib.parse import urlparse

class OwnerHidden(Exception):
    """The caller is not the owner. Map this to HTTP 404."""


class PrivacyError(Exception):
    """A private memory would have left the machine."""


# Paths and filenames that are never useful in an external payload.
PRIVATE_MARKERS = (
    "/var/lib/heirloom/vault",
    "/var/lib/heirloom/owner",
    "/var/lib/heirloom/observer",
    "odysseus.token",
    "owner.pass",
)

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})


def require_owner(user: Mapping[str, Any] | None) -> None:
    """Raise ``OwnerHidden`` unless this is the owner, off the heir portal."""
    if not isinstance(user, Mapping):
        raise OwnerHidden("Not found")
    if user.get("heir_surface"):
        raise OwnerHidden("Not found")
    audience = (user.get("audience") or "owner").strip().lower()
    if audience != "owner":
        raise OwnerHidden("Not found")


def redact_private(text: str, private_texts: list[str] | tuple[str, ...] | None) -> str:
    """Replace owner-private snippets and known secret paths."""
    cleaned = text or ""
    for secret in private_texts or ():
        snippet = (secret or "").strip()
        if len(snippet) < 3:
            continue
        if snippet in cleaned:
            cleaned = cleaned.replace(snippet, "[private]")
    for marker in PRIVATE_MARKERS:
        if marker in cleaned:
            cleaned = cleaned.replace(marker, "[private]")
    return cleaned


def contains_private(text: str, private_texts: list[str] | tuple[str, ...] | None) -> bool:
    raw = text or ""
    for secret in private_texts or ():
        snippet = (secret or "").strip()
        if len(snippet) >= 4 and snippet in raw:
            return True
    return False


def prepare_external_payload(
    kind: str,
    payload: str,
    private_texts: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Payload that is safe to hand to a service outside the vault.

    ``kind`` is one of odysseus, web_research, smart_home, writing, mcp.
    The cleaned text is what may leave. The original private lines are not.
    """
    allowed = {"odysseus", "web_research", "smart_home", "writing", "mcp"}
    if kind not in allowed:
        raise PrivacyError(f"Unknown external hop: {kind}")
    cleaned = redact_private(payload or "", private_texts)
    if contains_private(cleaned, private_texts):
        raise PrivacyError("A private memory is still in the outgoing text.")
    return {"kind": kind, "payload": cleaned, "sent_private": False}


def is_loopback_url(url: str) -> bool:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    return host in _LOOPBACK_HOSTS


def is_private_http_url(url: str) -> bool:
    """True for loopback, .local, or a private/link-local IP. Public hosts are false."""
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return False
    if host in _LOOPBACK_HOSTS or host.endswith(".local") or host.endswith(".lan"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local)


def mask_secret(value: str) -> str:
    raw = (value or "").strip()
    if len(raw) < 8:
        return "••••"
    return "••••" + raw[-4:]


def secret_for_log(_value: str) -> str:
    """Log helper. The secret is never returned."""
    return "[redacted]"


def json_hides_secret(document: Any, secret: str) -> bool:
    """True when the full secret string is absent from a JSON-ish value."""
    raw = (secret or "").strip()
    if len(raw) < 8:
        return True
    blob = _flatten(document)
    return raw not in blob


def _flatten(document: Any) -> str:
    if isinstance(document, str):
        return document
    if isinstance(document, Mapping):
        return " ".join(_flatten(v) for v in document.values())
    if isinstance(document, (list, tuple)):
        return " ".join(_flatten(v) for v in document)
    if document is None:
        return ""
    return str(document)


_CLOUD_KEY_FLOWS = frozenset({
    "openai",
    "anthropic",
    "claude",
    "gemini",
    "google",
    "google_ai",
    "elevenlabs",
    "groq",
    "mistral",
    "openrouter",
    "azure_openai",
})


def cloud_model_key_flow(flow_id: str) -> bool:
    key = re.sub(r"[^a-z0-9_]+", "", (flow_id or "").strip().lower())
    return key in _CLOUD_KEY_FLOWS
