"""Box owner session renewal. No Mongo, no FastAPI."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import asyncio

from session_renew import (
    ACCESS_TTL,
    HIDDEN,
    KIND_BOX,
    KIND_WEB,
    REFRESH_TTL,
    REJECT,
    ROTATE,
    attach_expiry,
    issue,
    me_expiry,
    refresh_owner_session,
    token_hash,
)


class MemorySessions:
    def __init__(self):
        self.rows = []
        self.users = {}

    async def find_session(self, token: str):
        for row in self.rows:
            if row.get("session_token") == token:
                return dict(row)
        return None

    async def find_refresh(self, refresh_hash: str):
        for row in self.rows:
            if row.get("refresh_hash") == refresh_hash:
                return dict(row)
        return None

    async def find_user(self, user_id: str):
        user = self.users.get(user_id)
        return dict(user) if user else None

    async def replace(self, old, new_doc):
        token = str(old.get("session_token") or "")
        self.rows = [row for row in self.rows if row.get("session_token") != token]
        self.rows.append(dict(new_doc))


def _owner(store: MemorySessions, user_id: str = "user_owner") -> None:
    store.users[user_id] = {"user_id": user_id, "audience": "owner", "email": "ada@example.com"}


def _plant(store: MemorySessions, *, kind: str, access_delta: timedelta, refresh_delta: timedelta | None, user_id: str = "user_owner"):
    now = datetime(2026, 11, 11, 20, 0, tzinfo=timezone.utc)
    issued = issue(now, kind=kind)
    doc = issued.document(user_id, now)
    doc["expires_at"] = (now + access_delta).isoformat()
    if refresh_delta is None:
        doc.pop("refresh_hash", None)
        doc.pop("refresh_expires_at", None)
    else:
        doc["refresh_expires_at"] = (now + refresh_delta).isoformat()
    store.rows.append(doc)
    return issued, now


def test_me_expiry_is_an_iso_timestamp():
    stamped = me_expiry("2026-11-18T20:01:00+00:00")
    assert stamped is not None
    assert stamped.startswith("2026-11-18T20:01:00")
    payload = attach_expiry({"email": "ada@example.com"}, stamped)
    assert payload["expires_at"].startswith("2026-11-18T20:01:00")
    assert "expires_at" not in attach_expiry({"email": "ada@example.com"}, None)


def test_box_issue_hashes_the_refresh_token_and_keeps_seven_day_access():
    now = datetime(2026, 11, 11, 20, 0, tzinfo=timezone.utc)
    issued = issue(now, kind=KIND_BOX)
    doc = issued.document("user_owner", now)
    assert issued.expires_at - now == ACCESS_TTL
    assert issued.refresh_expires_at - now == REFRESH_TTL
    assert doc["refresh_hash"] == token_hash(issued.refresh_token)
    assert issued.refresh_token not in str(doc)
    assert doc["kind"] == KIND_BOX
    web = issue(now, kind=KIND_WEB)
    assert web.refresh_token == ""
    assert "refresh_token" not in web.public()


def test_still_valid_legacy_owner_session_rotates_on_the_box():
    store = MemorySessions()
    _owner(store)
    now = datetime(2026, 11, 11, 20, 0, tzinfo=timezone.utc)
    store.rows.append({
        "user_id": "user_owner",
        "session_token": "legacy-access",
        "expires_at": (now + timedelta(days=6)).isoformat(),
    })

    async def _run():
        return await refresh_owner_session(
            store, bearer="legacy-access", refresh_token="", box_mode=True, now=now,
        )

    outcome, issued = asyncio.run(_run())
    assert outcome == ROTATE
    assert issued is not None
    assert issued.public()["refresh_token"]
    assert asyncio.run(store.find_session("legacy-access")) is None
    saved = asyncio.run(store.find_session(issued.session_token))
    assert saved["kind"] == KIND_BOX
    assert issued.refresh_token not in str(saved)


def test_expired_box_session_renews_with_a_live_refresh_token():
    store = MemorySessions()
    _owner(store)
    issued, now = _plant(
        store,
        kind=KIND_BOX,
        access_delta=timedelta(days=-1),
        refresh_delta=timedelta(days=20),
    )

    async def _run():
        return await refresh_owner_session(
            store,
            bearer=issued.session_token,
            refresh_token=issued.refresh_token,
            box_mode=True,
            now=now,
        )

    outcome, fresh = asyncio.run(_run())
    assert outcome == ROTATE
    assert fresh is not None
    assert fresh.session_token != issued.session_token
    assert asyncio.run(store.find_session(issued.session_token)) is None
    assert asyncio.run(store.find_refresh(token_hash(issued.refresh_token))) is None


def test_expired_session_without_a_live_refresh_token_is_rejected():
    store = MemorySessions()
    _owner(store)
    now = datetime(2026, 11, 11, 20, 0, tzinfo=timezone.utc)
    store.rows.append({
        "user_id": "user_owner",
        "session_token": "dead-access",
        "expires_at": (now - timedelta(hours=1)).isoformat(),
        "kind": KIND_BOX,
    })

    async def _run():
        return await refresh_owner_session(
            store, bearer="dead-access", refresh_token="", box_mode=True, now=now,
        )

    outcome, issued = asyncio.run(_run())
    assert outcome == REJECT
    assert issued is None
    assert asyncio.run(store.find_session("dead-access")) is not None

    issued_dead, _ = _plant(
        store,
        kind=KIND_BOX,
        access_delta=timedelta(days=-2),
        refresh_delta=timedelta(hours=-1),
        user_id="user_owner",
    )
    async def _dead_refresh():
        return await refresh_owner_session(
            store,
            bearer="",
            refresh_token=issued_dead.refresh_token,
            box_mode=True,
            now=now,
        )

    outcome, issued = asyncio.run(_dead_refresh())
    assert outcome == REJECT
    assert issued is None


def test_web_session_is_not_extended_and_heirs_stay_hidden():
    store = MemorySessions()
    _owner(store)
    issued, now = _plant(store, kind=KIND_WEB, access_delta=timedelta(days=3), refresh_delta=None)

    async def _web():
        return await refresh_owner_session(
            store, bearer=issued.session_token, refresh_token="", box_mode=True, now=now,
        )

    outcome, renewed = asyncio.run(_web())
    assert outcome == REJECT
    assert renewed is None
    assert asyncio.run(store.find_session(issued.session_token)) is not None

    store.users["user_heir"] = {"user_id": "user_heir", "audience": "heir"}
    heir, heir_now = _plant(
        store,
        kind=KIND_BOX,
        access_delta=timedelta(days=3),
        refresh_delta=timedelta(days=10),
        user_id="user_heir",
    )

    async def _heir():
        return await refresh_owner_session(
            store,
            bearer=heir.session_token,
            refresh_token=heir.refresh_token,
            box_mode=True,
            now=heir_now,
        )

    outcome, renewed = asyncio.run(_heir())
    assert outcome == HIDDEN
    assert renewed is None

    async def _off_box():
        return await refresh_owner_session(
            store, bearer=issued.session_token, refresh_token="", box_mode=False, now=now,
        )

    off_box, _ = asyncio.run(_off_box())
    assert off_box == HIDDEN
