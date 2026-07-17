"""Iteration 15 - Pre-sale hardening tests.

Covers:
- Backend: DELETE /api/auth/me account deletion with confirm guard, cascade
  delete across collections, deletion_log entry, session invalidated.
- Backend: GET /api/avatar/me + PUT/DELETE /api/avatar/api-key (BYO D-ID key).
- Backend: GET /api/companion/poll returns script_version.
- Backend: GET /api/companion/public-script contains SCRIPT_VERSION constant.
"""
import os
import time
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://voice-clone-hub-20.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

# Mongo for direct seeding/verification
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
client = MongoClient(MONGO_URL)
db = client[DB_NAME]


def _seed_user(label: str):
    """Create a fresh user + session. Returns (user_id, session_token)."""
    t = int(time.time() * 1000)
    uid = f"iter15-{label}-{t}"
    tok = f"iter15_{label}_{t}"
    db.users.insert_one({
        "user_id": uid,
        "email": f"iter15.{label}.{t}@example.com",
        "name": f"Iter15 {label}",
        "picture": "",
        "onboarded": True,
        "onboarding_complete": True,
        "created_at": "2026-01-01T00:00:00+00:00",
    })
    db.user_sessions.insert_one({
        "user_id": uid,
        "session_token": tok,
        "expires_at": "2099-01-01T00:00:00+00:00",
        "created_at": "2026-01-01T00:00:00+00:00",
    })
    return uid, tok


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


# ---------------- Companion script_version ----------------
class TestCompanionScriptVersion:
    def test_poll_returns_script_version(self):
        uid, tok = _seed_user("comp")
        # Register a device for this user
        r = requests.post(f"{API}/companion/register", headers=_auth(tok), json={"name": "TEST_PC"}, timeout=15)
        assert r.status_code == 200, r.text
        dev = r.json()
        device_token = dev["device_token"]

        # Poll using the device token
        r = requests.get(f"{API}/companion/poll", headers=_auth(device_token), timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "script_version" in data, "poll response missing script_version"
        assert data["script_version"] == "2026.02.27.1", f"unexpected version {data['script_version']}"
        assert "commands" in data
        assert "server_time" in data

        # cleanup
        db.companion_devices.delete_many({"user_id": uid})
        db.user_sessions.delete_many({"user_id": uid})
        db.users.delete_one({"user_id": uid})

    def test_public_script_contains_version_constant(self):
        uid, tok = _seed_user("script")
        r = requests.post(f"{API}/companion/register", headers=_auth(tok), json={"name": "TEST_PC2"}, timeout=15)
        assert r.status_code == 200
        device_token = r.json()["device_token"]

        r = requests.get(f"{API}/companion/public-script", params={"token": device_token}, timeout=20)
        assert r.status_code == 200, r.text
        body = r.text
        assert 'SCRIPT_VERSION = "2026.02.27.1"' in body, "version constant not baked into script"
        assert device_token in body, "device token should be embedded in script"

        # public-script must reject invalid/revoked tokens
        r2 = requests.get(f"{API}/companion/public-script", params={"token": "bogus_token_doesnt_exist"}, timeout=15)
        assert r2.status_code == 404

        db.companion_devices.delete_many({"user_id": uid})
        db.user_sessions.delete_many({"user_id": uid})
        db.users.delete_one({"user_id": uid})


# ---------------- D-ID BYO key ----------------
class TestAvatarApiKey:
    def test_get_me_initially_no_personal_key(self):
        uid, tok = _seed_user("didA")
        r = requests.get(f"{API}/avatar/me", headers=_auth(tok), timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "has_personal_key" in data and data["has_personal_key"] is False
        assert "masked_key" in data and data["masked_key"] == ""
        db.user_sessions.delete_many({"user_id": uid})
        db.users.delete_one({"user_id": uid})

    def test_put_then_get_then_delete_api_key(self):
        uid, tok = _seed_user("didB")
        # PUT key
        r = requests.put(f"{API}/avatar/api-key", headers=_auth(tok),
                         json={"api_key": "test-key-1234567890"}, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["has_personal_key"] is True
        assert data["masked"] == "test-k…7890", f"masked got {data['masked']!r}"

        # GET /me reflects it
        r = requests.get(f"{API}/avatar/me", headers=_auth(tok), timeout=15)
        assert r.status_code == 200
        me = r.json()
        assert me["has_personal_key"] is True
        assert me["masked_key"] == "test-k…7890"
        assert me["configured"] is True

        # Verify persisted in DB
        u = db.users.find_one({"user_id": uid}, {"_id": 0})
        assert u.get("d_id_api_key") == "test-key-1234567890"

        # DELETE clears it
        r = requests.delete(f"{API}/avatar/api-key", headers=_auth(tok), timeout=15)
        assert r.status_code == 200
        assert r.json()["has_personal_key"] is False

        # GET /me reflects deletion
        r = requests.get(f"{API}/avatar/me", headers=_auth(tok), timeout=15)
        assert r.json()["has_personal_key"] is False
        assert r.json()["masked_key"] == ""

        u = db.users.find_one({"user_id": uid}, {"_id": 0})
        assert "d_id_api_key" not in u or not u.get("d_id_api_key")

        db.user_sessions.delete_many({"user_id": uid})
        db.users.delete_one({"user_id": uid})

    def test_put_api_key_validates_length(self):
        uid, tok = _seed_user("didC")
        r = requests.put(f"{API}/avatar/api-key", headers=_auth(tok), json={"api_key": "short"}, timeout=15)
        assert r.status_code in (400, 422), f"expected validation error, got {r.status_code}"
        db.user_sessions.delete_many({"user_id": uid})
        db.users.delete_one({"user_id": uid})


# ---------------- DELETE /api/auth/me ----------------
class TestAccountDeletion:
    def test_delete_without_confirm_returns_400(self):
        uid, tok = _seed_user("delA")
        r = requests.delete(f"{API}/auth/me", headers=_auth(tok), timeout=15)
        assert r.status_code == 400, r.text
        # session still works
        r = requests.get(f"{API}/auth/me", headers=_auth(tok), timeout=15)
        assert r.status_code == 200
        # cleanup
        db.user_sessions.delete_many({"user_id": uid})
        db.users.delete_one({"user_id": uid})

    def test_delete_with_confirm_cascades_and_invalidates_session(self):
        uid, tok = _seed_user("delB")

        # Seed artifacts across several collections to verify cascade
        db.entries.insert_one({"entry_id": "TEST_e1", "user_id": uid, "title": "x", "type": "note", "content": "y", "created_at": "2026-01-01"})
        db.heirs.insert_one({"heir_id": "TEST_h1", "user_id": uid, "name": "Heir1"})
        db.letters.insert_one({"letter_id": "TEST_l1", "user_id": uid, "title": "L"})
        db.companion_devices.insert_one({"device_id": "TEST_d1", "user_id": uid, "device_token": "TEST_devtok", "revoked": False})
        db.personas.insert_one({"persona_id": "TEST_p1", "user_id": uid, "name": "P"})

        # Sanity: data exists
        assert db.entries.count_documents({"user_id": uid}) == 1
        assert db.heirs.count_documents({"user_id": uid}) == 1
        assert db.users.count_documents({"user_id": uid}) == 1

        # Note current deletion_log size for delta verification
        before = db.deletion_log.count_documents({})

        # DELETE with confirm=DELETE
        r = requests.delete(f"{API}/auth/me?confirm=DELETE", headers=_auth(tok), timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("deleted") is True
        assert isinstance(data.get("counts"), dict)
        # At least these collections should report deletions
        for c in ("entries", "heirs", "letters", "companion_devices", "personas", "user_sessions", "users"):
            assert data["counts"].get(c, 0) >= 1, f"{c} not deleted (counts={data['counts']})"

        # User document gone
        assert db.users.find_one({"user_id": uid}) is None
        # Cascaded collections cleared
        assert db.entries.count_documents({"user_id": uid}) == 0
        assert db.heirs.count_documents({"user_id": uid}) == 0
        assert db.letters.count_documents({"user_id": uid}) == 0
        assert db.companion_devices.count_documents({"user_id": uid}) == 0
        assert db.personas.count_documents({"user_id": uid}) == 0
        assert db.user_sessions.count_documents({"user_id": uid}) == 0

        # deletion_log has a new entry
        after = db.deletion_log.count_documents({})
        assert after == before + 1, f"deletion_log should grow by 1 (before={before}, after={after})"
        log = db.deletion_log.find_one({"event_id": {"$regex": f"^del_{uid}_"}})
        assert log is not None, "deletion_log entry missing for deleted user"

        # Session token no longer authenticates
        r = requests.get(f"{API}/auth/me", headers=_auth(tok), timeout=15)
        assert r.status_code == 401, f"expected 401 after deletion, got {r.status_code}"

    def test_second_user_unaffected_by_first_deletion(self):
        uidA, tokA = _seed_user("delC1")
        uidB, tokB = _seed_user("delC2")
        db.entries.insert_one({"entry_id": "TEST_eA", "user_id": uidA, "title": "A", "type": "note", "content": "a", "created_at": "2026-01-01"})
        db.entries.insert_one({"entry_id": "TEST_eB", "user_id": uidB, "title": "B", "type": "note", "content": "b", "created_at": "2026-01-01"})

        r = requests.delete(f"{API}/auth/me?confirm=DELETE", headers=_auth(tokA), timeout=20)
        assert r.status_code == 200

        # B intact
        assert db.users.find_one({"user_id": uidB}) is not None
        assert db.entries.count_documents({"user_id": uidB}) == 1
        r = requests.get(f"{API}/auth/me", headers=_auth(tokB), timeout=15)
        assert r.status_code == 200

        # cleanup
        db.entries.delete_many({"user_id": uidB})
        db.user_sessions.delete_many({"user_id": uidB})
        db.users.delete_one({"user_id": uidB})


# ---------------- Regression: existing endpoints still work ----------------
class TestRegression:
    def test_auth_me_and_logout(self):
        uid, tok = _seed_user("reg")
        r = requests.get(f"{API}/auth/me", headers=_auth(tok), timeout=15)
        assert r.status_code == 200
        assert r.json()["user_id"] == uid
        db.user_sessions.delete_many({"user_id": uid})
        db.users.delete_one({"user_id": uid})

    def test_companion_easy_installer_still_works(self):
        uid, tok = _seed_user("ezi")
        r = requests.post(f"{API}/companion/register", headers=_auth(tok), json={"name": "TEST_PC_EZ"}, timeout=15)
        assert r.status_code == 200
        device_token = r.json()["device_token"]
        r = requests.get(f"{API}/companion/easy-installer",
                         params={"token": device_token},
                         headers=_auth(tok), timeout=20)
        assert r.status_code == 200, r.text
        disp = r.headers.get("content-disposition", "")
        assert (
            "Install-Heirloom" in disp
            or "HeirloomInstall" in disp
            or b"Heirloom" in r.content
        )
        db.companion_devices.delete_many({"user_id": uid})
        db.user_sessions.delete_many({"user_id": uid})
        db.users.delete_one({"user_id": uid})


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
