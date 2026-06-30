"""Iteration 20: Live-stream twin (/api/live/*) + desktop zip path migration tests.

Coverage:
- Handle validation (reserved/length/charset/auto-lowercase)
- POST /api/live/handle: auth, idempotent, 409 cross-user collision
- PATCH /api/live/settings: enabled/private_mode toggles + edge cases
- GET /api/live/{handle}/profile (public, 404 if not enabled)
- GET /api/live/{handle}/recent (public, with seeded conversation)
- GET /api/live/{handle}/stream (SSE) + publish_turn helper
- publish_turn respects enabled / private_mode flags
- Cross-user isolation of pub/sub bus
- build_desktop_app_zip_bytes works with new /app/backend/companion_desktop path
"""
from __future__ import annotations

import asyncio
import io
import os
import secrets
import sys
import time
import uuid
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).parent.parent / ".env")
load_dotenv(Path(__file__).parent.parent.parent / "frontend" / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent))

BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or os.environ.get("PUBLIC_BACKEND_URL")
    or ""
).rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL not set"
API = f"{BASE_URL}/api"

_MONGO = MongoClient(os.environ.get("MONGO_URL"))
_DB = _MONGO[os.environ.get("DB_NAME")]


def _reset_motor_for_current_loop():
    """Motor binds to the loop it's first used on. Each pytest-asyncio test gets a
    fresh loop, so we rebuild the motor client + rebind routers.live.db before
    calling publish_turn() in-process. Safe — only the in-test reference is
    swapped; the running backend has its own process + client.
    """
    from motor.motor_asyncio import AsyncIOMotorClient
    import routers.live as live_mod
    fresh_client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    live_mod.db = fresh_client[os.environ["DB_NAME"]]
    return fresh_client

_CREATED_USERS: list[str] = []
_CREATED_SESSIONS: list[str] = []
_CREATED_HANDLES: list[str] = []


def _mk_user(prefix: str = "u_live") -> tuple[str, str]:
    """Insert a user + session. Returns (user_id, session_token)."""
    rand = uuid.uuid4().hex[:10]
    user_id = f"{prefix}_{rand}"
    session_token = f"sess_live_{secrets.token_urlsafe(24)}"
    now = datetime.now(timezone.utc)
    _DB.users.insert_one({
        "user_id": user_id,
        "email": f"{prefix}_{rand}@example.com",
        "name": "Live Test User",
        "picture": "https://placehold.co/150",
        "avatar_source_url": "https://example.com/me.jpg",
        "tagline": "Hello from the test suite",
        "account_status": "active",
        "created_at": now.isoformat(),
    })
    _DB.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": session_token,
        "expires_at": (now + timedelta(days=365)).isoformat(),
        "created_at": now.isoformat(),
    })
    _CREATED_USERS.append(user_id)
    _CREATED_SESSIONS.append(session_token)
    return user_id, session_token


def _bearer(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _unique_handle(stem: str = "h") -> str:
    h = f"{stem}{uuid.uuid4().hex[:8]}"
    _CREATED_HANDLES.append(h)
    return h


# =========================================================
# Owner endpoints — POST /api/live/handle
# =========================================================
class TestClaimHandle:
    def test_no_auth_returns_401(self):
        r = requests.post(f"{API}/live/handle", json={"handle": "doesnotmatter"})
        assert r.status_code == 401

    def test_reserved_handle_admin(self):
        _, tok = _mk_user("u_live_res_a")
        r = requests.post(f"{API}/live/handle", json={"handle": "admin"}, headers=_bearer(tok))
        assert r.status_code == 400
        assert "reserved" in r.json().get("detail", "").lower()

    @pytest.mark.parametrize("handle", ["api", "www", "twin", "support", "mail", "live"])
    def test_reserved_handles(self, handle):
        _, tok = _mk_user("u_live_res")
        r = requests.post(f"{API}/live/handle", json={"handle": handle}, headers=_bearer(tok))
        assert r.status_code == 400
        assert "reserved" in r.json().get("detail", "").lower()

    def test_too_short_handle(self):
        _, tok = _mk_user("u_live_short")
        # 'XX' = 2 chars → Pydantic min_length=3 rejects at 422 OR validator at 400
        r = requests.post(f"{API}/live/handle", json={"handle": "XX"}, headers=_bearer(tok))
        assert r.status_code in (400, 422)

    @pytest.mark.parametrize("handle", ["-foo", "foo-", "a", "foo bar"])
    def test_invalid_chars(self, handle):
        _, tok = _mk_user("u_live_inv")
        r = requests.post(f"{API}/live/handle", json={"handle": handle}, headers=_bearer(tok))
        assert r.status_code in (400, 422), f"handle {handle!r} expected 400/422 got {r.status_code}"

    def test_uppercase_auto_lowercased(self):
        user_id, tok = _mk_user("u_live_upper")
        # use a unique prefix to avoid collision
        h = _unique_handle("fooup")
        upper = h.upper()
        r = requests.post(f"{API}/live/handle", json={"handle": upper}, headers=_bearer(tok))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["handle"] == h  # lowercased
        assert body["url"] == f"/twin/live/{h}"
        # verify stored handle in db is lowercase
        prof = _DB.live_profiles.find_one({"user_id": user_id})
        assert prof and prof["handle"] == h
        assert prof.get("enabled") is False  # broadcasting off by default

    def test_good_handle_returns_url_and_persists(self):
        user_id, tok = _mk_user("u_live_good")
        h = _unique_handle("good-h")
        r = requests.post(f"{API}/live/handle", json={"handle": h}, headers=_bearer(tok))
        assert r.status_code == 200
        body = r.json()
        assert body == {"handle": h, "url": f"/twin/live/{h}"}
        prof = _DB.live_profiles.find_one({"user_id": user_id})
        assert prof and prof["handle"] == h and prof["enabled"] is False

    def test_idempotent_same_user(self):
        _, tok = _mk_user("u_live_idem")
        h = _unique_handle("idem")
        r1 = requests.post(f"{API}/live/handle", json={"handle": h}, headers=_bearer(tok))
        r2 = requests.post(f"{API}/live/handle", json={"handle": h}, headers=_bearer(tok))
        assert r1.status_code == 200
        assert r2.status_code == 200

    def test_collision_returns_409(self):
        _, tok_a = _mk_user("u_live_a")
        _, tok_b = _mk_user("u_live_b")
        h = _unique_handle("dup")
        r_a = requests.post(f"{API}/live/handle", json={"handle": h}, headers=_bearer(tok_a))
        assert r_a.status_code == 200
        r_b = requests.post(f"{API}/live/handle", json={"handle": h}, headers=_bearer(tok_b))
        assert r_b.status_code == 409


# =========================================================
# PATCH /api/live/settings + GET /api/live/me
# =========================================================
class TestSettings:
    def test_patch_requires_handle_first(self):
        _, tok = _mk_user("u_live_nohandle")
        r = requests.patch(f"{API}/live/settings", json={"enabled": True}, headers=_bearer(tok))
        assert r.status_code == 400
        assert "claim a handle first" in r.json().get("detail", "").lower()

    def test_patch_empty_body_returns_400(self):
        _, tok = _mk_user("u_live_empty")
        h = _unique_handle("e")
        requests.post(f"{API}/live/handle", json={"handle": h}, headers=_bearer(tok))
        r = requests.patch(f"{API}/live/settings", json={}, headers=_bearer(tok))
        assert r.status_code == 400
        assert "nothing to update" in r.json().get("detail", "").lower()

    def test_enable_then_private_mode_then_me(self):
        user_id, tok = _mk_user("u_live_flow")
        h = _unique_handle("flow")
        requests.post(f"{API}/live/handle", json={"handle": h}, headers=_bearer(tok))

        # enable
        r1 = requests.patch(f"{API}/live/settings", json={"enabled": True}, headers=_bearer(tok))
        assert r1.status_code == 200
        me = requests.get(f"{API}/live/me", headers=_bearer(tok)).json()
        assert me["handle"] == h and me["enabled"] is True and me["private_mode"] is False

        # private mode on; enabled stays true
        r2 = requests.patch(
            f"{API}/live/settings", json={"private_mode": True}, headers=_bearer(tok)
        )
        assert r2.status_code == 200
        me2 = requests.get(f"{API}/live/me", headers=_bearer(tok)).json()
        assert me2["enabled"] is True and me2["private_mode"] is True


# =========================================================
# PUBLIC endpoints — /api/live/{handle}/profile + /recent
# =========================================================
class TestPublicEndpoints:
    def test_profile_nonexistent_handle_404(self):
        r = requests.get(f"{API}/live/this-handle-does-not-exist-xyz/profile")
        assert r.status_code == 404
        assert r.json().get("detail") == "No twin at that handle."

    def test_profile_when_disabled_returns_404(self):
        """Privacy: handle claimed but enabled=false → invisible."""
        user_id, _ = _mk_user("u_live_priv")
        h = _unique_handle("priv")
        now = datetime.now(timezone.utc).isoformat()
        _DB.live_profiles.insert_one({
            "user_id": user_id, "handle": h, "enabled": False,
            "private_mode": False, "created_at": now, "updated_at": now,
        })
        r = requests.get(f"{API}/live/{h}/profile")
        assert r.status_code == 404

    def test_profile_when_enabled_returns_data(self):
        user_id, tok = _mk_user("u_live_enabled")
        h = _unique_handle("en")
        requests.post(f"{API}/live/handle", json={"handle": h}, headers=_bearer(tok))
        requests.patch(f"{API}/live/settings", json={"enabled": True}, headers=_bearer(tok))
        r = requests.get(f"{API}/live/{h}/profile")
        assert r.status_code == 200
        body = r.json()
        assert body["handle"] == h
        assert body["name"]
        assert body["private_mode"] is False
        assert body["viewer_count"] == 0
        assert "avatar_url" in body
        assert "tagline" in body

    def test_recent_empty_when_no_conversation(self):
        user_id, tok = _mk_user("u_live_rec_empty")
        h = _unique_handle("recE")
        requests.post(f"{API}/live/handle", json={"handle": h}, headers=_bearer(tok))
        requests.patch(f"{API}/live/settings", json={"enabled": True}, headers=_bearer(tok))
        r = requests.get(f"{API}/live/{h}/recent")
        assert r.status_code == 200
        assert r.json() == {"messages": []}

    def test_recent_returns_seeded_messages_in_order(self):
        user_id, tok = _mk_user("u_live_rec_seed")
        h = _unique_handle("recS")
        requests.post(f"{API}/live/handle", json={"handle": h}, headers=_bearer(tok))
        requests.patch(f"{API}/live/settings", json={"enabled": True}, headers=_bearer(tok))

        now = datetime.now(timezone.utc).isoformat()
        msgs = [
            {"role": "user", "content": "msg1", "ts": now},
            {"role": "assistant", "content": "reply1", "ts": now},
            {"role": "user", "content": "msg2", "ts": now},
            {"role": "assistant", "content": "reply2", "ts": now},
            {"role": "user", "content": "msg3", "ts": now},
            {"role": "assistant", "content": "reply3", "ts": now},
        ]
        _DB.conversations.insert_one({
            "user_id": user_id, "kind": "companion_twin",
            "messages": msgs, "created_at": now, "updated_at": now,
        })
        r = requests.get(f"{API}/live/{h}/recent")
        assert r.status_code == 200
        got = r.json()["messages"]
        assert len(got) == 6
        # In order — first should be msg1
        assert got[0]["content"] == "msg1"
        assert got[-1]["content"] == "reply3"


# =========================================================
# SSE stream + publish_turn
# =========================================================
class TestSSEStream:
    @pytest.mark.asyncio
    async def test_sse_hello_received(self):
        """Connect to /stream, expect 'hello' SSE event within 5s.

        NOTE: We can't validate publish_turn → SSE end-to-end here because the
        in-process BUS in this test process is distinct from the running server's
        BUS (separate processes). The publish→subscribe roundtrip is covered in
        the unit tests below by subscribing to our local BUS directly.
        """
        user_id, tok = _mk_user("u_live_sse")
        h = _unique_handle("sse")
        requests.post(f"{API}/live/handle", json={"handle": h}, headers=_bearer(tok))
        requests.patch(f"{API}/live/settings", json={"enabled": True}, headers=_bearer(tok))

        url = f"{API}/live/{h}/stream"
        got_hello = False

        async def _read_stream():
            nonlocal got_hello
            async with httpx.AsyncClient(timeout=10.0) as client:
                async with client.stream("GET", url) as resp:
                    assert resp.status_code == 200
                    buf = ""
                    start = time.time()
                    async for chunk in resp.aiter_text():
                        buf += chunk
                        if "event: hello" in buf:
                            got_hello = True
                            return
                        if time.time() - start > 5:
                            return

        await asyncio.wait_for(_read_stream(), timeout=8)
        assert got_hello, "Did not receive SSE 'hello' event within 5s"

    @pytest.mark.asyncio
    async def test_publish_turn_respects_disabled(self):
        """When enabled=false, publish_turn delivers no event."""
        _reset_motor_for_current_loop()
        from routers.live import publish_turn, BUS

        user_id, _ = _mk_user("u_live_disabled")
        h = _unique_handle("dis")
        now = datetime.now(timezone.utc).isoformat()
        _DB.live_profiles.insert_one({
            "user_id": user_id, "handle": h, "enabled": False,
            "private_mode": False, "created_at": now, "updated_at": now,
        })
        q = BUS.subscribe(user_id)
        try:
            await publish_turn(user_id, "user", "should not arrive", source="test")
            await asyncio.sleep(0.2)
            assert q.empty(), "Event leaked when broadcasting disabled"
        finally:
            BUS.unsubscribe(user_id, q)

    @pytest.mark.asyncio
    async def test_publish_turn_respects_private_mode(self):
        _reset_motor_for_current_loop()
        from routers.live import publish_turn, BUS

        user_id, _ = _mk_user("u_live_priv2")
        h = _unique_handle("priv2")
        now = datetime.now(timezone.utc).isoformat()
        _DB.live_profiles.insert_one({
            "user_id": user_id, "handle": h, "enabled": True,
            "private_mode": True, "created_at": now, "updated_at": now,
        })
        q = BUS.subscribe(user_id)
        try:
            await publish_turn(user_id, "user", "no leak", source="test")
            await asyncio.sleep(0.2)
            assert q.empty()
        finally:
            BUS.unsubscribe(user_id, q)

    @pytest.mark.asyncio
    async def test_publish_turn_flows_when_enabled_not_private(self):
        _reset_motor_for_current_loop()
        from routers.live import publish_turn, BUS

        user_id, _ = _mk_user("u_live_flow2")
        h = _unique_handle("flow2")
        now = datetime.now(timezone.utc).isoformat()
        _DB.live_profiles.insert_one({
            "user_id": user_id, "handle": h, "enabled": True,
            "private_mode": False, "created_at": now, "updated_at": now,
        })
        q = BUS.subscribe(user_id)
        try:
            await publish_turn(user_id, "user", "hello world", source="test")
            ev = await asyncio.wait_for(q.get(), timeout=2.0)
            assert ev["type"] == "turn"
            assert ev["content"] == "hello world"
            assert ev["role"] == "user"
            assert ev["source"] == "test"
        finally:
            BUS.unsubscribe(user_id, q)

    @pytest.mark.asyncio
    async def test_cross_user_isolation(self):
        """publish_turn for user A must NOT reach user B's subscribers."""
        _reset_motor_for_current_loop()
        from routers.live import publish_turn, BUS

        ua, _ = _mk_user("u_live_aaa")
        ub, _ = _mk_user("u_live_bbb")
        ha = _unique_handle("aaaalpha")
        hb = _unique_handle("bbbbeta")
        now = datetime.now(timezone.utc).isoformat()
        _DB.live_profiles.insert_one({
            "user_id": ua, "handle": ha, "enabled": True,
            "private_mode": False, "created_at": now, "updated_at": now,
        })
        _DB.live_profiles.insert_one({
            "user_id": ub, "handle": hb, "enabled": True,
            "private_mode": False, "created_at": now, "updated_at": now,
        })
        qa = BUS.subscribe(ua)
        qb = BUS.subscribe(ub)
        try:
            await publish_turn(ua, "user", "only A", source="test")
            ev = await asyncio.wait_for(qa.get(), timeout=2.0)
            assert ev["content"] == "only A"
            await asyncio.sleep(0.2)
            assert qb.empty(), "Event leaked across users"
        finally:
            BUS.unsubscribe(ua, qa)
            BUS.unsubscribe(ub, qb)


# =========================================================
# Desktop zip migration
# =========================================================
class TestDesktopZipPathMigration:
    def test_zip_built_from_new_location(self):
        from routers.companion import build_desktop_app_zip_bytes

        tok = f"testtok_{secrets.token_urlsafe(12)}"
        zb = build_desktop_app_zip_bytes(tok)
        assert isinstance(zb, (bytes, bytearray)) and len(zb) > 1000

        zf = zipfile.ZipFile(io.BytesIO(zb))
        names = zf.namelist()

        # Expected files from new /app/backend/companion_desktop path
        expected = ["heirloom/vault.py", "heirloom.spec", "Build-Heirloom-Exe.bat"]
        for fname in expected:
            assert any(n.endswith(fname) for n in names), (
                f"Missing {fname} in zip. Got: {sorted(names)[:20]}"
            )

    def test_token_bake_in(self):
        from routers.companion import build_desktop_app_zip_bytes

        tok = f"baketok_{secrets.token_urlsafe(16)}"
        zb = build_desktop_app_zip_bytes(tok)
        zf = zipfile.ZipFile(io.BytesIO(zb))
        # Look for the device token bound in any file
        found = False
        for name in zf.namelist():
            try:
                content = zf.read(name).decode("utf-8", errors="ignore")
            except Exception:
                continue
            if tok in content:
                found = True
                break
        assert found, "device token not baked into any file"

    def test_companion_desktop_source_under_backend(self):
        p = Path(__file__).parent.parent / "companion_desktop"
        assert p.exists() and p.is_dir(), f"{p} missing — migration incomplete"
        assert (p / "heirloom" / "vault.py").exists()
        assert (p / "heirloom.spec").exists()
        assert (p / "Build-Heirloom-Exe.bat").exists()


# =========================================================
# Cleanup
# =========================================================
def teardown_module(module):
    if _CREATED_USERS:
        _DB.users.delete_many({"user_id": {"$in": _CREATED_USERS}})
        _DB.user_sessions.delete_many({"user_id": {"$in": _CREATED_USERS}})
        _DB.live_profiles.delete_many({"user_id": {"$in": _CREATED_USERS}})
        _DB.conversations.delete_many({"user_id": {"$in": _CREATED_USERS}})
    if _CREATED_HANDLES:
        _DB.live_profiles.delete_many({"handle": {"$in": _CREATED_HANDLES}})
