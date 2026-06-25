"""Shared utilities: SSRF guard, regex escape, signed URLs, rate limiting."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import os
import re
import socket
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import HTTPException

from deps import db

# ---------------------------------------------------------------------------
# Regex escape — prevents ReDoS + accidental operator injection
# ---------------------------------------------------------------------------
def escape_regex(value: str) -> str:
    """Escape user input destined for a MongoDB $regex match."""
    return re.escape(value or "")


# ---------------------------------------------------------------------------
# SSRF guard for webhook URLs (Skills + companion action invocations)
# ---------------------------------------------------------------------------
_FORBIDDEN_HOSTS = {"metadata.google.internal", "metadata"}


def _is_blocked_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or str(ip).startswith("169.254.")  # AWS/GCP/Azure metadata
        or str(ip).startswith("fd00:ec2:")  # AWS IMDS IPv6
    )


def validate_outbound_url(url: str) -> None:
    """Raise HTTPException(400) if URL is unsafe to fetch from the server."""
    if not url or not isinstance(url, str):
        raise HTTPException(status_code=400, detail="Missing webhook URL")
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Only http(s) URLs are allowed")
    host = (parsed.hostname or "").lower()
    if not host:
        raise HTTPException(status_code=400, detail="Invalid URL host")
    if host in _FORBIDDEN_HOSTS:
        raise HTTPException(status_code=400, detail="Host blocked")
    # Resolve A/AAAA and reject any private address. Run in thread; socket blocks.
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail=f"DNS resolution failed: {exc}") from exc
    for fam, _, _, _, sockaddr in infos:
        ip_str = sockaddr[0]
        if _is_blocked_ip(ip_str):
            raise HTTPException(status_code=400, detail=f"Blocked target address: {ip_str}")


# ---------------------------------------------------------------------------
# Signed URL for photo viewing — replaces raw session_token in URLs.
# Token format: hex(hmac_sha256(secret, f"{photo_id}:{user_id}:{exp}"))
# ---------------------------------------------------------------------------
_SIGN_SECRET = (
    os.environ.get("PHOTO_SIGN_SECRET")
    or hashlib.sha256(
        (os.environ.get("EMERGENT_LLM_KEY", "")
         + os.environ.get("DB_NAME", "")
         + "heirloom-photo-sign-v1").encode()
    ).hexdigest()
).encode()


def make_photo_signature(photo_id: str, user_id: str, ttl_seconds: int = 300) -> tuple[str, int]:
    exp = int(time.time()) + ttl_seconds
    msg = f"{photo_id}:{user_id}:{exp}".encode()
    sig = hmac.new(_SIGN_SECRET, msg, hashlib.sha256).hexdigest()
    return sig, exp


def verify_photo_signature(photo_id: str, user_id: str, exp: int, sig: str) -> bool:
    if exp < int(time.time()):
        return False
    msg = f"{photo_id}:{user_id}:{exp}".encode()
    expected = hmac.new(_SIGN_SECRET, msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig or "")


# ---------------------------------------------------------------------------
# Lightweight per-user rate limiter (in-memory, sliding window).
# Good enough for a single-pod deployment to prevent runaway costs.
# ---------------------------------------------------------------------------
_rl_lock = asyncio.Lock()
_rl_state: dict[str, list[float]] = {}


async def rate_limit(user_id: str, bucket: str, max_calls: int, per_seconds: int) -> None:
    """Raise 429 if user exceeds max_calls within per_seconds for this bucket."""
    key = f"{bucket}:{user_id}"
    now = time.monotonic()
    cutoff = now - per_seconds
    async with _rl_lock:
        timestamps = _rl_state.get(key, [])
        # drop expired
        timestamps = [t for t in timestamps if t > cutoff]
        if len(timestamps) >= max_calls:
            retry_after = int(per_seconds - (now - timestamps[0])) + 1
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded for {bucket}. Try again in {retry_after}s.",
                headers={"Retry-After": str(retry_after)},
            )
        timestamps.append(now)
        _rl_state[key] = timestamps


# ---------------------------------------------------------------------------
# Image magic-byte validation
# ---------------------------------------------------------------------------
_IMAGE_MAGIC = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
}


def detect_image_mime(head: bytes) -> str | None:
    for magic, mime in _IMAGE_MAGIC.items():
        if head.startswith(magic):
            return mime
    # WebP: RIFF....WEBP
    if len(head) >= 12 and head[0:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    # HEIC/HEIF: starts with ftypheic/heix/mif1 inside box
    if len(head) >= 12 and head[4:8] == b"ftyp" and head[8:12] in (b"heic", b"heix", b"mif1", b"heim", b"heis"):
        return "image/heic"
    return None
