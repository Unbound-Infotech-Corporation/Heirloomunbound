"""Iteration 21 — Setup/Keys Wizard backend tests.

Covers:
- GET  /api/user-keys/status            (sources: you/admin/none)
- POST /api/user-keys/verify            (fal real-key + bogus + elevenlabs/did fake)
- PUT  /api/avatar-studio/api-key       (saves user fal key)
- DELETE /api/avatar-studio/api-key     (clears it)
- PUT  /api/voice-clone/api-key         (saves user elevenlabs key)
- PUT  /api/avatar/api-key              (saves user did key)
- GET  /api/avatar-studio/me            (fal_configured + fal_using_user_key)
- POST /api/avatar-studio/enhance       (hybrid override path → 404 for bad id)
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

import pymongo
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://voice-clone-hub-20.preview.emergentagent.com").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

VALID_FAL_KEY = "1a3df26f-4808-458c-aef2-56008a1679b0:25a5d3b7f26af0caa3ef6b947b7b53ca"

_client = pymongo.MongoClient(MONGO_URL)
_db = _client[DB_NAME]


def _mk_user():
    uid = f"u_iter21_{int(time.time()*1000)}_{os.urandom(2).hex()}"
    tok = f"sess_iter21_{int(time.time()*1000)}_{os.urandom(3).hex()}"
    _db.users.insert_one({
        "user_id": uid,
        "email": f"{uid}@test.example",
        "name": "Iter21 Tester",
        "picture": "https://via.placeholder.com/150",
        "setup_complete": True,
        "onboarded": True,
        "created_at": datetime.now(timezone.utc),
    })
    _db.user_sessions.insert_one({
        "user_id": uid,
        "session_token": tok,
        "expires_at": datetime.now(timezone.utc) + timedelta(days=7),
        "created_at": datetime.now(timezone.utc),
    })
    return uid, tok


@pytest.fixture(scope="module")
def user_ctx():
    uid, tok = _mk_user()
    yield {"user_id": uid, "token": tok, "headers": {"Authorization": f"Bearer {tok}"}}
    _db.users.delete_many({"user_id": uid})
    _db.user_sessions.delete_many({"user_id": uid})
    _db.avatar_images.delete_many({"user_id": uid})


# ---------------- /user-keys/status ----------------
class TestUserKeysStatus:
    def test_status_baseline(self, user_ctx):
        r = requests.get(f"{BASE_URL}/api/user-keys/status", headers=user_ctx["headers"], timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        for key in ("fal", "elevenlabs", "did", "resend", "stripe", "spotify", "github"):
            assert key in data, f"missing service {key} in status"
            assert "configured" in data[key]
            assert "source" in data[key]
            assert data[key]["source"] in ("you", "admin", "none")

        # admin .env has these set → source should be admin for fresh user
        assert data["fal"]["source"] == "admin", data["fal"]
        assert data["elevenlabs"]["source"] == "admin", data["elevenlabs"]
        assert data["did"]["source"] == "admin", data["did"]
        assert data["resend"]["source"] == "admin", data["resend"]
        assert data["stripe"]["source"] == "admin", data["stripe"]
        # OAuth: none until connected
        assert data["spotify"]["source"] == "none"
        assert data["github"]["source"] == "none"

    def test_status_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/user-keys/status", timeout=20)
        assert r.status_code in (401, 403), r.text


# ---------------- /user-keys/verify ----------------
class TestVerify:
    def test_verify_fal_valid(self, user_ctx):
        r = requests.post(
            f"{BASE_URL}/api/user-keys/verify",
            json={"service": "fal", "api_key": VALID_FAL_KEY},
            headers=user_ctx["headers"], timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True, data
        assert "Valid" in data["detail"]

    def test_verify_fal_bogus(self, user_ctx):
        r = requests.post(
            f"{BASE_URL}/api/user-keys/verify",
            json={"service": "fal", "api_key": "totally:bogus"},
            headers=user_ctx["headers"], timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is False, data
        assert "fal.ai rejected" in data["detail"] or "verification failed" in data["detail"]

    def test_verify_elevenlabs_fake(self, user_ctx):
        r = requests.post(
            f"{BASE_URL}/api/user-keys/verify",
            json={"service": "elevenlabs", "api_key": "definitely-not-a-real-key"},
            headers=user_ctx["headers"], timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is False, data
        assert "ElevenLabs" in data["detail"] or "rejected" in data["detail"].lower()

    def test_verify_did_fake(self, user_ctx):
        r = requests.post(
            f"{BASE_URL}/api/user-keys/verify",
            json={"service": "did", "api_key": "fake:fake"},
            headers=user_ctx["headers"], timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is False, data
        assert "D-ID" in data["detail"] or "rejected" in data["detail"].lower()

    def test_verify_empty_key(self, user_ctx):
        r = requests.post(
            f"{BASE_URL}/api/user-keys/verify",
            json={"service": "fal", "api_key": "  "},
            headers=user_ctx["headers"], timeout=15,
        )
        assert r.status_code == 400

    def test_verify_unknown_service(self, user_ctx):
        r = requests.post(
            f"{BASE_URL}/api/user-keys/verify",
            json={"service": "nope", "api_key": "x"},
            headers=user_ctx["headers"], timeout=15,
        )
        assert r.status_code == 400


# ---------------- PUT/DELETE /api/avatar-studio/api-key ----------------
class TestAvatarStudioApiKey:
    def test_put_get_delete_fal_key(self, user_ctx):
        # PUT
        r = requests.put(
            f"{BASE_URL}/api/avatar-studio/api-key",
            json={"api_key": VALID_FAL_KEY},
            headers=user_ctx["headers"], timeout=20,
        )
        assert r.status_code == 200, r.text
        assert r.json().get("has_user_key") is True

        # GET status reflects user source
        s = requests.get(f"{BASE_URL}/api/user-keys/status", headers=user_ctx["headers"], timeout=20).json()
        assert s["fal"]["source"] == "you", s["fal"]
        assert s["fal"]["configured"] is True

        # avatar-studio/me should show fal_using_user_key true
        me = requests.get(f"{BASE_URL}/api/avatar-studio/me", headers=user_ctx["headers"], timeout=20)
        assert me.status_code == 200, me.text
        me_data = me.json()
        assert me_data["fal_configured"] is True
        assert me_data["fal_using_user_key"] is True

        # DELETE clears it
        d = requests.delete(f"{BASE_URL}/api/avatar-studio/api-key", headers=user_ctx["headers"], timeout=20)
        assert d.status_code == 200, d.text
        assert d.json().get("has_user_key") is False

        s2 = requests.get(f"{BASE_URL}/api/user-keys/status", headers=user_ctx["headers"], timeout=20).json()
        assert s2["fal"]["source"] == "admin", s2["fal"]

        me2 = requests.get(f"{BASE_URL}/api/avatar-studio/me", headers=user_ctx["headers"], timeout=20).json()
        assert me2["fal_using_user_key"] is False
        assert me2["fal_configured"] is True  # admin key still configured


# ---------------- voice-clone & avatar key endpoints ----------------
class TestPerServiceSaveEndpoints:
    def test_voice_clone_key_save_clear(self, user_ctx):
        r = requests.put(
            f"{BASE_URL}/api/voice-clone/api-key",
            json={"api_key": "sk_test_eleven"},
            headers=user_ctx["headers"], timeout=20,
        )
        assert r.status_code == 200, r.text
        s = requests.get(f"{BASE_URL}/api/user-keys/status", headers=user_ctx["headers"], timeout=20).json()
        assert s["elevenlabs"]["source"] == "you", s["elevenlabs"]

        # DELETE
        d = requests.delete(f"{BASE_URL}/api/voice-clone/api-key", headers=user_ctx["headers"], timeout=20)
        assert d.status_code == 200, d.text
        s2 = requests.get(f"{BASE_URL}/api/user-keys/status", headers=user_ctx["headers"], timeout=20).json()
        assert s2["elevenlabs"]["source"] == "admin"

    def test_avatar_did_key_save_clear(self, user_ctx):
        r = requests.put(
            f"{BASE_URL}/api/avatar/api-key",
            json={"api_key": "user@example.com:test"},
            headers=user_ctx["headers"], timeout=20,
        )
        assert r.status_code == 200, r.text
        s = requests.get(f"{BASE_URL}/api/user-keys/status", headers=user_ctx["headers"], timeout=20).json()
        assert s["did"]["source"] == "you", s["did"]

        d = requests.delete(f"{BASE_URL}/api/avatar/api-key", headers=user_ctx["headers"], timeout=20)
        assert d.status_code == 200, d.text
        s2 = requests.get(f"{BASE_URL}/api/user-keys/status", headers=user_ctx["headers"], timeout=20).json()
        assert s2["did"]["source"] == "admin"


# ---------------- /api/avatar-studio/me + enhance hybrid path ----------------
class TestAvatarStudioMe:
    def test_me_baseline(self, user_ctx):
        r = requests.get(f"{BASE_URL}/api/avatar-studio/me", headers=user_ctx["headers"], timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "fal_configured" in data
        assert "fal_using_user_key" in data
        assert isinstance(data["fal_configured"], bool)
        assert isinstance(data["fal_using_user_key"], bool)
        # admin .env has FAL_KEY → configured true
        assert data["fal_configured"] is True


class TestEnhanceHybrid:
    def test_enhance_with_user_key_returns_404_for_bad_image_id(self, user_ctx):
        """Hybrid override wiring proof: when user has a fal key set,
        enhance() must NOT bail with 400 'FAL_KEY missing'; it should
        proceed and 404 on bad image_id."""
        # Set the user fal key first
        r = requests.put(
            f"{BASE_URL}/api/avatar-studio/api-key",
            json={"api_key": VALID_FAL_KEY},
            headers=user_ctx["headers"], timeout=20,
        )
        assert r.status_code == 200

        # Hit enhance with bogus image_id
        e = requests.post(
            f"{BASE_URL}/api/avatar-studio/enhance",
            json={"image_id": "definitely_not_real_xyz", "strength": 0.5},
            headers=user_ctx["headers"], timeout=30,
        )
        assert e.status_code == 404, f"expected 404 (image not found), got {e.status_code} {e.text}"
        # Clean up
        requests.delete(f"{BASE_URL}/api/avatar-studio/api-key", headers=user_ctx["headers"], timeout=20)
