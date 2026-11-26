"""Pair a phone with the owner's box: a short one-time code (shown as text and a QR) becomes a
phone device token. The phone then talks to the box directly; speech, the model and memory stay
on the box.

Flow
  1. Owner, signed in on the box (web or desktop): POST /api/mobile/pair/start -> code + QR payload.
  2. Phone scans the QR (or types the code): POST /api/mobile/pair/claim -> device token.
  3. Phone uses the token as `Authorization: Bearer ...` for chat, voice and speak.
  4. Owner can see and revoke phones (GET/DELETE /api/mobile/devices).

Codes: 8 characters from an alphabet without look-alikes (XXXX-XXXX), valid 10 minutes, single use,
stored only as a SHA-256 hash. Wrong codes count against a per-address limit.
"""
from __future__ import annotations

import hashlib
import secrets
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional, Protocol

ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"  # no 0/O, 1/I/L, U
CODE_LEN = 8
CODE_TTL = timedelta(minutes=10)
MAX_OPEN_CODES = 3
MAX_FAILS_PER_WINDOW = 10
FAIL_WINDOW_S = 600
PLATFORMS = {"android", "ios"}
TOKEN_PREFIX = "mob_"
SCHEME = "heirloom://pair"


class PairingError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))


def normalize_code(raw: str) -> str:
    """What the owner typed: any case, with spaces or a dash."""
    return "".join(ch for ch in (raw or "").upper() if ch.isalnum())


def code_hash(code: str) -> str:
    return hashlib.sha256(("heirloom-pair:" + code).encode()).hexdigest()


def display(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


def qr_payload(box_url: str, code: str, pin: str = "") -> str:
    query = {"box": box_url.rstrip("/"), "code": code}
    if pin:
        query["pin"] = pin
    return SCHEME + "?" + urllib.parse.urlencode(query)


def parse_qr(text: str) -> dict:
    """The phone side: heirloom://pair?box=...&code=...&pin=... -> fields (empty dict if not ours)."""
    raw = (text or "").strip()
    if not raw.startswith(SCHEME):
        return {}
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(raw).query)
    box = (query.get("box") or [""])[0]
    code = (query.get("code") or [""])[0]
    if not box.startswith(("https://", "http://")) or len(code) != CODE_LEN:
        return {}
    return {"box": box, "code": code, "pin": (query.get("pin") or [""])[0]}


class PairStore(Protocol):
    async def open_codes(self, user_id: str, now: datetime) -> int: ...
    async def save_code(self, doc: dict) -> None: ...
    async def take_code(self, hashed: str, now: datetime) -> Optional[dict]: ...  # atomically marks used
    async def save_device(self, doc: dict) -> None: ...


@dataclass
class FailLimiter:
    """Wrong codes per client address. In memory: a restart resets it, which is fine for 10-minute codes."""
    window_s: int = FAIL_WINDOW_S
    limit: int = MAX_FAILS_PER_WINDOW
    hits: dict[str, list[float]] = field(default_factory=dict)

    def blocked(self, key: str, now: Optional[float] = None) -> bool:
        now = time.monotonic() if now is None else now
        rows = [t for t in self.hits.get(key, []) if now - t < self.window_s]
        self.hits[key] = rows
        return len(rows) >= self.limit

    def fail(self, key: str, now: Optional[float] = None) -> None:
        self.hits.setdefault(key, []).append(time.monotonic() if now is None else now)


async def start(store: PairStore, user_id: str, box_url: str, *, pin: str = "",
                now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if await store.open_codes(user_id, now) >= MAX_OPEN_CODES:
        raise PairingError(429, "Too many open pairing codes. Use one or wait 10 minutes.")
    code = new_code()
    expires = now + CODE_TTL
    await store.save_code({"code_hash": code_hash(code), "user_id": user_id, "created_at": now.isoformat(),
                           "expires_at": expires.isoformat(), "used": False})
    return {"code": display(code), "expires_at": expires.isoformat(), "qr": qr_payload(box_url, code, pin),
            "box": box_url.rstrip("/"), "pin": pin}


async def claim(store: PairStore, code: str, *, device_name: str, platform: str, client: str,
                limiter: FailLimiter, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if limiter.blocked(client):
        raise PairingError(429, "Too many wrong codes. Wait a few minutes and try again.")
    plat = (platform or "").strip().lower()
    if plat not in PLATFORMS:
        raise PairingError(400, "platform must be android or ios")
    row = await store.take_code(code_hash(normalize_code(code)), now)
    if not row:
        limiter.fail(client)
        raise PairingError(404, "That code is wrong, used or expired. Make a new one on the box.")
    device_id = "phone_" + secrets.token_hex(6)
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    name = (device_name or "").strip()[:60] or ("iPhone" if plat == "ios" else "Android phone")
    await store.save_device({"device_id": device_id, "user_id": row["user_id"], "name": name, "kind": "phone",
                             "platform": plat, "device_token": token, "revoked": False,
                             "created_at": now.isoformat(), "last_seen": None, "paired_by": "code"})
    return {"device_id": device_id, "device_token": token, "name": name}


class MemoryStore:
    """For tests and the mock mode."""

    def __init__(self) -> None:
        self.codes: list[dict] = []
        self.devices: list[dict] = []

    async def open_codes(self, user_id: str, now: datetime) -> int:
        return sum(1 for c in self.codes if c["user_id"] == user_id and not c["used"]
                   and c["expires_at"] > now.isoformat())

    async def save_code(self, doc: dict) -> None:
        self.codes.append(dict(doc))

    async def take_code(self, hashed: str, now: datetime) -> Optional[dict]:
        for c in self.codes:
            if c["code_hash"] == hashed and not c["used"] and c["expires_at"] > now.isoformat():
                c["used"] = True
                return dict(c)
        return None

    async def save_device(self, doc: dict) -> None:
        self.devices.append(dict(doc))
