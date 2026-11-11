"""Twin Box owner sessions.

Access tokens stay at seven days. On a Twin Box (``HEIRLOOM_BOX``) a still-valid
owner session, or a box refresh token, can be rotated into a new pair. Web and
magic-link sessions (``kind=web``) are not extended. An expired access token
with no live refresh token stays expired. Heirs are not owners and get the
same not-found answer as other owner routes.

The refresh token is stored only as a SHA-256 hash. The raw value is returned
once to the client that just signed in or rotated.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional, Protocol

ACCESS_TTL = timedelta(days=7)
REFRESH_TTL = timedelta(days=45)
KIND_BOX = "box"
KIND_WEB = "web"

HIDDEN = "hidden"
REJECT = "reject"
ROTATE = "rotate"


def _now(now: Optional[datetime] = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current


def parse_expiry(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def token_hash(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def hashes_match(stored: str, presented: str) -> bool:
    if not stored or not presented:
        return False
    return hmac.compare_digest(stored, token_hash(presented))


def me_expiry(expires_at: Any) -> Optional[str]:
    parsed = parse_expiry(expires_at)
    return parsed.isoformat() if parsed else None


def attach_expiry(payload: dict, expires_at: Any) -> dict:
    stamped = me_expiry(expires_at)
    if stamped:
        payload["expires_at"] = stamped
    return payload


@dataclass(frozen=True)
class IssuedSession:
    session_token: str
    refresh_token: str
    expires_at: datetime
    refresh_expires_at: datetime
    kind: str

    def document(self, user_id: str, now: datetime) -> dict:
        return {
            "user_id": user_id,
            "session_token": self.session_token,
            "refresh_hash": token_hash(self.refresh_token),
            "expires_at": self.expires_at.isoformat(),
            "refresh_expires_at": self.refresh_expires_at.isoformat(),
            "kind": self.kind,
            "created_at": _now(now).isoformat(),
        }

    def public(self) -> dict:
        body = {
            "session_token": self.session_token,
            "expires_at": self.expires_at.isoformat(),
        }
        if self.kind == KIND_BOX:
            body["refresh_token"] = self.refresh_token
            body["refresh_expires_at"] = self.refresh_expires_at.isoformat()
        return body


def issue(now: Optional[datetime] = None, *, kind: str = KIND_BOX) -> IssuedSession:
    current = _now(now)
    stamped = kind if kind in {KIND_BOX, KIND_WEB} else KIND_WEB
    return IssuedSession(
        session_token=secrets.token_urlsafe(32),
        refresh_token=secrets.token_urlsafe(32) if stamped == KIND_BOX else "",
        expires_at=current + ACCESS_TTL,
        refresh_expires_at=current + REFRESH_TTL,
        kind=stamped,
    )


def _is_heir(user: Optional[Mapping[str, Any]]) -> bool:
    if not user:
        return False
    if user.get("heir_surface"):
        return True
    return str(user.get("audience") or "").strip().lower() == "heir"


def _is_owner(user: Optional[Mapping[str, Any]]) -> bool:
    if not user or _is_heir(user):
        return False
    audience = str(user.get("audience") or "owner").strip().lower()
    return audience in {"", "owner"}


def _access_usable(row: Optional[Mapping[str, Any]], now: datetime) -> bool:
    if not row:
        return False
    if str(row.get("kind") or "") == KIND_WEB:
        return False
    if str(row.get("kind") or "") not in {KIND_BOX, ""}:
        return False
    expires = parse_expiry(row.get("expires_at"))
    return expires is not None and expires >= now


def _refresh_usable(row: Optional[Mapping[str, Any]], now: datetime) -> bool:
    if not row or str(row.get("kind") or "") != KIND_BOX:
        return False
    expires = parse_expiry(row.get("refresh_expires_at"))
    return expires is not None and expires >= now


class SessionStore(Protocol):
    async def find_session(self, token: str) -> Optional[dict]: ...

    async def find_refresh(self, refresh_hash: str) -> Optional[dict]: ...

    async def find_user(self, user_id: str) -> Optional[dict]: ...

    async def replace(self, old: Mapping[str, Any], new_doc: dict) -> bool: ...


async def refresh_owner_session(
    store: SessionStore,
    *,
    bearer: str,
    refresh_token: str,
    box_mode: bool,
    now: Optional[datetime] = None,
) -> tuple[str, Optional[IssuedSession]]:
    """Rotate a box owner session, or refuse.

    Returns ``(HIDDEN, None)`` for a non-box process or an heir,
    ``(REJECT, None)`` when the session cannot be renewed, or
    ``(ROTATE, issued)`` after the previous row has been replaced.
    """
    if not box_mode:
        return HIDDEN, None
    current = _now(now)
    presented = (refresh_token or "").strip()
    refresh_row = None
    if presented:
        found = await store.find_refresh(token_hash(presented))
        if found and hashes_match(str(found.get("refresh_hash") or ""), presented):
            refresh_row = found
    session = None
    if (bearer or "").strip():
        session = await store.find_session(bearer.strip())

    candidate = None
    if _refresh_usable(refresh_row, current):
        candidate = refresh_row
    elif _access_usable(session, current):
        candidate = session
    else:
        row = refresh_row or session
        if row:
            user = await store.find_user(str(row.get("user_id") or ""))
            if _is_heir(user):
                return HIDDEN, None
        return REJECT, None

    user = await store.find_user(str(candidate.get("user_id") or ""))
    if _is_heir(user):
        return HIDDEN, None
    if not _is_owner(user):
        return REJECT, None
    issued = issue(current, kind=KIND_BOX)
    swapped = await store.replace(candidate, issued.document(str(candidate.get("user_id") or ""), current))
    if not swapped:
        return REJECT, None
    return ROTATE, issued


class MongoSessionStore:
    async def find_session(self, token: str) -> Optional[dict]:
        from deps import db

        row = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
        return row if isinstance(row, dict) else None

    async def find_refresh(self, refresh_hash: str) -> Optional[dict]:
        from deps import db

        row = await db.user_sessions.find_one({"refresh_hash": refresh_hash}, {"_id": 0})
        return row if isinstance(row, dict) else None

    async def find_user(self, user_id: str) -> Optional[dict]:
        from deps import db

        row = await db.users.find_one({"user_id": user_id}, {"_id": 0})
        return row if isinstance(row, dict) else None

    async def replace(self, old: Mapping[str, Any], new_doc: dict) -> bool:
        """Swap one session row in place. A second rotator of the same token loses."""
        from deps import db

        token = str(old.get("session_token") or "")
        doc = {key: value for key, value in dict(new_doc).items() if key != "_id"}
        if not token:
            await db.user_sessions.insert_one(doc)
            return True
        updated = await db.user_sessions.find_one_and_update(
            {"session_token": token},
            {"$set": doc},
        )
        return updated is not None
