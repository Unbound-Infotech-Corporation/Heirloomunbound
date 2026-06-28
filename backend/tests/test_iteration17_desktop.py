"""Iteration 17: Heirloom Desktop (PySide6) backend tests.

Covers:
- /api/desktop/me identity (valid/invalid/missing token)
- /api/desktop/conversation (creates companion_twin conv, returns shared history)
- /api/desktop/chat (text → twin reply, persists pair, source='desktop')
- /api/desktop/capture + /api/desktop/memories/recent (with cross-user isolation)
- /api/desktop/avatar/talk endpoint REGISTRATION ONLY (no live D-ID call)
- build_desktop_app_zip_bytes() shape/contents
- /api/companion/desktop-package?token=... (auth, cross-user, content-disposition)
- Python syntax compile check for every file under companion_desktop/heirloom
"""
from __future__ import annotations

import io
import json
import os
import secrets
import sys
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

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

# Track for cleanup
_CREATED_USERS: list[str] = []
_CREATED_TOKENS: list[str] = []
_CREATED_SESSIONS: list[str] = []


def _mk_user_and_device(prefix: str = "u_desktop") -> tuple[str, str, str]:
    """Insert a user + companion_device + user_session. Returns (user_id, device_token, session_token)."""
    rand = uuid.uuid4().hex[:10]
    user_id = f"{prefix}_{rand}"
    email = f"{prefix}_{rand}@example.com"
    device_token = f"comp_desktop_{secrets.token_urlsafe(24)}"
    session_token = f"sess_desktop_{secrets.token_urlsafe(24)}"
    now = datetime.now(timezone.utc)
    _DB.users.insert_one({
        "user_id": user_id,
        "email": email,
        "name": "Desktop Test User",
        "picture": "https://placehold.co/150",
        "avatar_source_url": "https://example.com/me.jpg",
        "purchased_lifetime": True,
        "account_status": "active",
        "created_at": now.isoformat(),
    })
    _DB.companion_devices.insert_one({
        "device_id": f"dev_{rand}",
        "user_id": user_id,
        "name": "Test PC",
        "device_token": device_token,
        "revoked": False,
        "created_at": now.isoformat(),
        "last_seen": None,
    })
    _DB.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": session_token,
        "expires_at": (now.replace(year=now.year + 1)).isoformat(),
        "created_at": now.isoformat(),
    })
    _CREATED_USERS.append(user_id)
    _CREATED_TOKENS.append(device_token)
    _CREATED_SESSIONS.append(session_token)
    return user_id, device_token, session_token


@pytest.fixture(scope="module")
def user_a():
    return _mk_user_and_device("u_desktop_a")


@pytest.fixture(scope="module")
def user_b():
    return _mk_user_and_device("u_desktop_b")


def _bearer(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _cookies(sess: str) -> dict:
    return {"session_token": sess}


# ============== /api/desktop/me ==============
class TestDesktopMe:
    def test_me_valid_token(self, user_a):
        uid, tok, _ = user_a
        r = requests.get(f"{API}/desktop/me", headers=_bearer(tok), timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["user_id"] == uid
        assert data["email"].startswith("u_desktop_a")
        assert data["avatar_source_url"]  # set above
        assert data["purchased_lifetime"] is True
        assert data["account_status"] == "active"

    def test_me_invalid_token(self):
        r = requests.get(f"{API}/desktop/me",
                         headers=_bearer("comp_invalid_xxx"), timeout=10)
        assert r.status_code == 401

    def test_me_missing_auth(self):
        r = requests.get(f"{API}/desktop/me", timeout=10)
        assert r.status_code == 401


# ============== /api/desktop/conversation ==============
class TestDesktopConversation:
    def test_conversation_first_call_creates_empty(self, user_a):
        uid, tok, _ = user_a
        # Pre-clean any existing companion_twin conv for this user
        _DB.conversations.delete_many({"user_id": uid, "kind": "companion_twin"})
        r = requests.get(f"{API}/desktop/conversation", headers=_bearer(tok), timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["conversation_id"].startswith("comp_")
        assert data["messages"] == []


# ============== /api/desktop/chat (live LLM, ONE call) ==============
class TestDesktopChat:
    def test_chat_persists_pair_and_shares_conversation(self, user_a):
        uid, tok, _ = user_a
        # Ensure conv exists first (and capture id)
        r1 = requests.get(f"{API}/desktop/conversation", headers=_bearer(tok), timeout=10)
        conv_id_before = r1.json()["conversation_id"]

        r = requests.post(
            f"{API}/desktop/chat",
            json={"text": "hello twin"},
            headers=_bearer(tok),
            timeout=60,
        )
        if r.status_code == 502:
            # Acceptable per spec when LLM upstream fails
            assert "LLM" in r.text or "llm" in r.text.lower()
            pytest.skip(f"LLM upstream returned 502 — auth path verified. body={r.text[:200]}")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("reply"), "empty reply"
        assert isinstance(data["reply"], str)
        assert data.get("ts")

        # Same conv surfaces via /desktop/conversation with user+assistant turns
        r2 = requests.get(f"{API}/desktop/conversation", headers=_bearer(tok), timeout=10)
        d2 = r2.json()
        assert d2["conversation_id"] == conv_id_before
        msgs = d2["messages"]
        assert len(msgs) >= 2
        # Last two should be user(hello twin), assistant(...)
        last_user = next((m for m in reversed(msgs) if m.get("role") == "user"), None)
        last_assistant = next((m for m in reversed(msgs) if m.get("role") == "assistant"), None)
        assert last_user and last_user["content"] == "hello twin"
        assert last_assistant and last_assistant.get("source") == "desktop"


# ============== /api/desktop/capture + /memories/recent ==============
class TestDesktopCaptureAndMemories:
    def test_capture_and_recent_isolation(self, user_a, user_b):
        uid_a, tok_a, _ = user_a
        uid_b, tok_b, _ = user_b

        # Create one entry for user B
        rb = requests.post(
            f"{API}/desktop/capture",
            json={"content": "USER_B SECRET memory", "type": "memory",
                  "title": "user b entry", "tags": ["b"]},
            headers=_bearer(tok_b), timeout=10,
        )
        assert rb.status_code == 200, rb.text
        entry_b_id = rb.json()["entry_id"]

        # Create one entry for user A
        ra = requests.post(
            f"{API}/desktop/capture",
            json={"content": "a memory from the desktop app", "type": "memory",
                  "title": "desktop test entry", "tags": ["t"]},
            headers=_bearer(tok_a), timeout=10,
        )
        assert ra.status_code == 200, ra.text
        a_entry = ra.json()
        assert a_entry["source"] == "desktop"
        assert "desktop" in a_entry["tags"]
        assert "t" in a_entry["tags"]
        assert a_entry["title"] == "desktop test entry"
        assert a_entry["type"] == "memory"

        # /memories/recent returns A's entry first AND no B leak
        r = requests.get(f"{API}/desktop/memories/recent?limit=5",
                         headers=_bearer(tok_a), timeout=10)
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert len(items) >= 1
        assert items[0]["entry_id"] == a_entry["entry_id"]
        # Cross-user isolation: B's entry must NOT appear
        for it in items:
            assert it["entry_id"] != entry_b_id, "cross-user leak!"


# ============== /api/desktop/avatar/talk REGISTRATION ONLY ==============
class TestDesktopAvatarTalkRegistration:
    def test_openapi_has_avatar_talk_endpoints(self):
        # openapi.json is served at root which the public ingress hides; hit backend directly
        r = requests.get("http://localhost:8001/openapi.json", timeout=10)
        assert r.status_code == 200, r.text[:200]
        spec = r.json()
        paths = spec.get("paths", {})
        assert "/api/desktop/avatar/talk" in paths, "missing /api/desktop/avatar/talk"
        assert "post" in paths["/api/desktop/avatar/talk"], "POST not registered"
        assert "/api/desktop/avatar/talk/{talk_id}" in paths
        assert "get" in paths["/api/desktop/avatar/talk/{talk_id}"]


# ============== build_desktop_app_zip_bytes() unit ==============
class TestBuildDesktopZip:
    EXPECTED_FILES = {
        "Heirloom.bat",
        "README.txt",
        "requirements.txt",
        "heirloom/__init__.py",
        "heirloom/__main__.py",
        "heirloom/api.py",
        "heirloom/audio.py",
        "heirloom/config.py",
        "heirloom/ui/__init__.py",
        "heirloom/ui/avatar_panel.py",
        "heirloom/ui/conversation.py",
        "heirloom/ui/main_window.py",
        "heirloom/ui/panels.py",
    }

    def test_zip_structure_and_token_injection(self):
        # Run in subprocess so we don't poison the test's asyncio loop with motor
        import subprocess
        code = (
            "import sys, base64; sys.path.insert(0, '/app/backend');"
            "from routers.companion import build_desktop_app_zip_bytes;"
            "data = build_desktop_app_zip_bytes('comp_zipbuild_test');"
            "sys.stdout.buffer.write(base64.b64encode(data))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr.decode()
        import base64
        zip_bytes = base64.b64decode(result.stdout)

        z = zipfile.ZipFile(io.BytesIO(zip_bytes))
        names = set(z.namelist())
        # No __pycache__
        for n in names:
            assert "__pycache__" not in n, f"pycache leaked: {n}"
        # Exactly the expected files
        assert names == self.EXPECTED_FILES, (
            f"unexpected file set:\nMISSING: {self.EXPECTED_FILES - names}\n"
            f"EXTRA: {names - self.EXPECTED_FILES}"
        )
        # config.py contains injected token + https BACKEND_URL
        cfg = z.read("heirloom/config.py").decode("utf-8")
        assert "comp_zipbuild_test" in cfg, "device token not injected"
        # BACKEND_URL line should be present with https
        # config.py uses `BACKEND_URL = "..."`
        import re
        m = re.search(r'BACKEND_URL\s*=\s*"([^"]+)"', cfg)
        assert m, "BACKEND_URL constant not found in config.py"
        assert m.group(1).startswith("https://"), \
            f"BACKEND_URL not https://: {m.group(1)}"


# ============== /api/companion/desktop-package (cookie auth) ==============
class TestDesktopPackageEndpoint:
    def test_unauth_returns_401(self, user_a):
        _, tok, _ = user_a
        r = requests.get(f"{API}/companion/desktop-package?token={tok}", timeout=15,
                         allow_redirects=False)
        # No session cookie => 401 from get_current_user
        assert r.status_code == 401, f"got {r.status_code}: {r.text[:200]}"

    def test_auth_owner_returns_zip(self, user_a):
        uid, tok, sess = user_a
        r = requests.get(
            f"{API}/companion/desktop-package?token={tok}",
            cookies=_cookies(sess), timeout=30,
        )
        assert r.status_code == 200, r.text[:300]
        assert r.headers.get("content-type", "").startswith("application/zip")
        cd = r.headers.get("content-disposition", "")
        assert "HeirloomDesktop.zip" in cd, cd
        # Valid zip
        z = zipfile.ZipFile(io.BytesIO(r.content))
        assert "heirloom/config.py" in z.namelist()

    def test_cross_user_token_returns_404(self, user_a, user_b):
        # user_a session asks for user_b's device_token → 404
        _, tok_b, _ = user_b
        _, _, sess_a = user_a
        r = requests.get(
            f"{API}/companion/desktop-package?token={tok_b}",
            cookies=_cookies(sess_a), timeout=15,
        )
        assert r.status_code == 404, f"expected 404 cross-user, got {r.status_code}"


# ============== Python syntax compile check ==============
class TestDesktopAppSyntax:
    def test_all_python_files_compile(self):
        pkg = Path("/app/companion_desktop/heirloom")
        py_files = list(pkg.rglob("*.py"))
        assert py_files, "no python files under heirloom/"
        errors = []
        for f in py_files:
            src = f.read_text(encoding="utf-8")
            try:
                compile(src, str(f), "exec")
            except SyntaxError as exc:
                errors.append(f"{f}: {exc}")
        assert not errors, "Syntax errors:\n" + "\n".join(errors)


# ============== Cleanup at the very end ==============
def teardown_module(module):  # noqa: D401
    """Best-effort cleanup of all fixtures we minted."""
    if _CREATED_USERS:
        _DB.users.delete_many({"user_id": {"$in": _CREATED_USERS}})
        _DB.companion_devices.delete_many({"user_id": {"$in": _CREATED_USERS}})
        _DB.user_sessions.delete_many({"user_id": {"$in": _CREATED_USERS}})
        _DB.entries.delete_many({"user_id": {"$in": _CREATED_USERS}})
        _DB.conversations.delete_many({"user_id": {"$in": _CREATED_USERS}})
        _DB.avatar_talks.delete_many({"user_id": {"$in": _CREATED_USERS}})
