"""Iteration 19 — Cloned-voice TTS playback + PyInstaller .exe build pipeline.

Covers:
- GET /api/desktop/voice/status (configured true/false, missing auth)
- POST /api/desktop/speak (400 when voice not configured, 401 missing auth,
  422 text validation, live ElevenLabs MP3 smoke when key available)
- /api/companion/desktop-package zip now contains heirloom.spec
  and Build-Heirloom-Exe.bat at the zip root.
- heirloom.spec is syntactically valid Python (ast.parse).
"""
from __future__ import annotations

import ast
import base64
import io
import os
import secrets
import subprocess
import sys
import uuid
import zipfile
from datetime import datetime, timezone
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
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")

_MONGO = MongoClient(os.environ.get("MONGO_URL"))
_DB = _MONGO[os.environ.get("DB_NAME")]

_CREATED_USERS: list[str] = []
_CREATED_TOKENS: list[str] = []
_CREATED_SESSIONS: list[str] = []


def _mk_user_and_device(prefix: str = "u_voice", **user_extra) -> tuple[str, str, str]:
    rand = uuid.uuid4().hex[:10]
    user_id = f"{prefix}_{rand}"
    email = f"{prefix}_{rand}@example.com"
    device_token = f"comp_voice_{secrets.token_urlsafe(20)}"
    session_token = f"sess_voice_{secrets.token_urlsafe(20)}"
    now = datetime.now(timezone.utc)
    user_doc = {
        "user_id": user_id,
        "email": email,
        "name": "Voice Test User",
        "picture": "https://placehold.co/150",
        "purchased_lifetime": True,
        "account_status": "active",
        "created_at": now.isoformat(),
    }
    user_doc.update(user_extra)
    _DB.users.insert_one(user_doc)
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


def _bearer(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


# ---------------------------------------------------------------- voice/status
class TestVoiceStatus:
    def test_status_no_voice_configured(self):
        # User without elevenlabs_voice_id
        _, tok, _ = _mk_user_and_device("u_voice_noid")
        r = requests.get(f"{API}/desktop/voice/status", headers=_bearer(tok), timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["configured"] is False
        assert data["voice_id"] == ""
        assert data["voice_name"] == ""

    def test_status_voice_configured_with_user_key(self):
        # User with BOTH api key + voice id → configured: true regardless of env
        _, tok, _ = _mk_user_and_device(
            "u_voice_full",
            elevenlabs_api_key="sk_user_dummy_xyz",
            elevenlabs_voice_id="vid_test_xyz",
            elevenlabs_voice_name="My Clone",
        )
        r = requests.get(f"{API}/desktop/voice/status", headers=_bearer(tok), timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["configured"] is True
        assert data["voice_id"] == "vid_test_xyz"
        assert data["voice_name"] == "My Clone"

    def test_status_missing_auth_returns_401(self):
        r = requests.get(f"{API}/desktop/voice/status", timeout=10)
        assert r.status_code == 401

    def test_status_configured_via_env_only(self):
        """If ENV ELEVENLABS_API_KEY is set AND user has voice_id (no user key),
        configured must still be true. Server env has ELEVENLABS_API_KEY set,
        so this validates the env-fallback branch.

        NOTE: The complementary "no env key & no user key & only voice_id => false"
        case would require unsetting the env at server import time, which can't be
        done from the test side without restarting the server. Covered by code-review.
        """
        _, tok, _ = _mk_user_and_device(
            "u_voice_envonly",
            elevenlabs_voice_id="vid_env_xyz",
            elevenlabs_voice_name="Env Clone",
        )
        r = requests.get(f"{API}/desktop/voice/status", headers=_bearer(tok), timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        if ELEVENLABS_API_KEY:
            assert data["configured"] is True, "env key present but configured=false"
        else:
            assert data["configured"] is False
        assert data["voice_id"] == "vid_env_xyz"
        assert data["voice_name"] == "Env Clone"


# ---------------------------------------------------------------- desktop/speak (negatives)
class TestSpeakNegatives:
    def test_speak_missing_auth_401(self):
        r = requests.post(f"{API}/desktop/speak", json={"text": "hi"}, timeout=10)
        assert r.status_code == 401

    def test_speak_no_voice_returns_400(self):
        # Need a user with NO voice_id AND no user-key. (env key set, but user
        # voice_id missing → still 400 because voice_id check fails)
        _, tok, _ = _mk_user_and_device("u_voice_400")
        r = requests.post(
            f"{API}/desktop/speak", json={"text": "hello"},
            headers=_bearer(tok), timeout=15,
        )
        assert r.status_code == 400, r.text
        assert "Voice clone not configured" in r.text

    def test_speak_empty_text_422(self):
        _, tok, _ = _mk_user_and_device("u_voice_empty")
        r = requests.post(
            f"{API}/desktop/speak", json={"text": ""},
            headers=_bearer(tok), timeout=10,
        )
        assert r.status_code == 422, r.text

    def test_speak_text_too_long_422(self):
        _, tok, _ = _mk_user_and_device("u_voice_long")
        long_text = "a" * 4001
        r = requests.post(
            f"{API}/desktop/speak", json={"text": long_text},
            headers=_bearer(tok), timeout=10,
        )
        assert r.status_code == 422, r.text


# ---------------------------------------------------------------- desktop/speak (live)
class TestSpeakLive:
    def test_speak_live_elevenlabs(self):
        if not ELEVENLABS_API_KEY:
            pytest.skip("No ELEVENLABS_API_KEY in env — skipping live MP3 smoke test")

        # Fetch a real voice_id from the ElevenLabs account
        try:
            with httpx.Client(timeout=15.0) as c:
                vr = c.get(
                    "https://api.elevenlabs.io/v1/voices",
                    headers={"xi-api-key": ELEVENLABS_API_KEY},
                )
        except Exception as exc:
            pytest.skip(f"ElevenLabs /voices fetch failed: {exc}")
        if vr.status_code != 200:
            pytest.skip(f"ElevenLabs /voices returned {vr.status_code}: {vr.text[:200]}")
        voices = vr.json().get("voices") or []
        if not voices:
            pytest.skip("No voices in ElevenLabs account — skipping live test")
        voice_id = voices[0]["voice_id"]
        voice_name = voices[0].get("name", "Test")

        _, tok, _ = _mk_user_and_device(
            "u_voice_live",
            elevenlabs_api_key=ELEVENLABS_API_KEY,
            elevenlabs_voice_id=voice_id,
            elevenlabs_voice_name=voice_name,
        )
        r = requests.post(
            f"{API}/desktop/speak",
            json={"text": "this is a test"},
            headers=_bearer(tok), timeout=60,
        )
        assert r.status_code == 200, f"got {r.status_code}: {r.text[:300]}"
        assert r.headers.get("content-type", "").startswith("audio/mpeg"), \
            f"content-type={r.headers.get('content-type')}"
        assert len(r.content) > 1024, f"audio too small: {len(r.content)} bytes"
        assert r.headers.get("X-Voice-Id") == voice_id


# ---------------------------------------------------------------- .exe pipeline in zip
class TestDesktopZipExePipeline:
    def test_zip_contains_spec_and_bat_at_root(self):
        code = (
            "import sys, base64; sys.path.insert(0, '/app/backend');"
            "from routers.companion import build_desktop_app_zip_bytes;"
            "data = build_desktop_app_zip_bytes('comp_iter19_test');"
            "sys.stdout.buffer.write(base64.b64encode(data))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr.decode()
        zip_bytes = base64.b64decode(result.stdout)
        z = zipfile.ZipFile(io.BytesIO(zip_bytes))
        names = set(z.namelist())
        assert "heirloom.spec" in names, f"heirloom.spec missing from zip. names={sorted(names)}"
        assert "Build-Heirloom-Exe.bat" in names, \
            f"Build-Heirloom-Exe.bat missing from zip. names={sorted(names)}"

    def test_heirloom_spec_is_valid_python(self):
        spec_path = Path("/app/backend/companion_desktop/heirloom.spec")
        if not spec_path.is_file():
            spec_path = Path("/app/companion_desktop/heirloom.spec")
        assert spec_path.is_file(), f"missing {spec_path}"
        src = spec_path.read_text(encoding="utf-8")
        # ast.parse will raise SyntaxError on bad spec
        ast.parse(src)


# ---------------------------------------------------------------- cleanup
def teardown_module(module):  # noqa: D401
    if _CREATED_USERS:
        _DB.users.delete_many({"user_id": {"$in": _CREATED_USERS}})
        _DB.companion_devices.delete_many({"user_id": {"$in": _CREATED_USERS}})
        _DB.user_sessions.delete_many({"user_id": {"$in": _CREATED_USERS}})
