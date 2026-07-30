"""Iteration 30: Magic-link login regression + cookie-only auth verification.

Context: MagicLink.jsx no longer mirrors session_token into localStorage.
This test confirms the httpOnly cookie set by POST /api/auth/magic/{token}
is sufficient for subsequent authenticated API calls.
"""
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient

def _load_backend_url():
    from pathlib import Path
    url = os.environ.get("REACT_APP_BACKEND_URL")
    if url:
        return url.rstrip("/")
    env = Path("/app/frontend/.env").read_text()
    for line in env.splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            return line.split("=", 1)[1].strip().strip('"').rstrip("/")
    raise RuntimeError("REACT_APP_BACKEND_URL not set")

BASE_URL = _load_backend_url()
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


@pytest.fixture(scope="module")
def mongo():
    # Try backend .env for accurate DB_NAME
    from pathlib import Path
    env = Path("/app/backend/.env").read_text()
    mongo_url = MONGO_URL
    db_name = DB_NAME
    for line in env.splitlines():
        if line.startswith("MONGO_URL="):
            mongo_url = line.split("=", 1)[1].strip().strip('"')
        if line.startswith("DB_NAME="):
            db_name = line.split("=", 1)[1].strip().strip('"')
    client = MongoClient(mongo_url)
    yield client[db_name]
    client.close()


@pytest.fixture
def seeded_magic_link(mongo):
    """Insert a fresh test user + magic_link doc; clean up after."""
    uid = f"test-user-ml-{uuid.uuid4().hex[:8]}"
    email = f"test.ml.{int(time.time())}@example.com"
    mongo.users.insert_one({
        "user_id": uid,
        "email": email,
        "name": "ML Test User",
        "picture": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tour_completed": True,
    })
    token = f"ml_TEST_{uuid.uuid4().hex}"
    mongo.magic_links.insert_one({
        "magic_token": token,
        "user_id": uid,
        "consumed": False,
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    yield {"user_id": uid, "email": email, "magic_token": token}
    # cleanup
    mongo.users.delete_one({"user_id": uid})
    mongo.magic_links.delete_many({"user_id": uid})
    mongo.user_sessions.delete_many({"user_id": uid})


class TestMagicLinkFlow:
    def test_consume_magic_link_returns_user_and_sets_cookie(self, seeded_magic_link):
        s = requests.Session()
        r = s.post(f"{BASE_URL}/api/auth/magic/{seeded_magic_link['magic_token']}")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "session_token" in data and isinstance(data["session_token"], str) and len(data["session_token"]) > 10
        assert "user" in data
        assert data["user"]["user_id"] == seeded_magic_link["user_id"]
        assert data["user"]["email"] == seeded_magic_link["email"]
        # httpOnly cookie must be set on the session
        assert "session_token" in s.cookies, f"Cookie missing. Got: {dict(s.cookies)}"

    def test_cookie_alone_authenticates_me(self, seeded_magic_link):
        s = requests.Session()
        s.post(f"{BASE_URL}/api/auth/magic/{seeded_magic_link['magic_token']}")
        # Now hit /auth/me with only the cookie
        r = s.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 200, r.text
        me = r.json()
        assert me["user_id"] == seeded_magic_link["user_id"]
        assert me["email"] == seeded_magic_link["email"]

    def test_cookie_alone_hits_protected_endpoints(self, seeded_magic_link):
        s = requests.Session()
        s.post(f"{BASE_URL}/api/auth/magic/{seeded_magic_link['magic_token']}")
        results = {}
        for path in ("/api/archive", "/api/abilities", "/api/agent/kinds"):
            r = s.get(f"{BASE_URL}{path}")
            results[path] = r.status_code
        # All must be 200 with cookie alone
        for p, code in results.items():
            assert code == 200, f"{p} returned {code}, expected 200. All: {results}"

    def test_magic_link_cannot_be_reused(self, seeded_magic_link):
        s = requests.Session()
        r1 = s.post(f"{BASE_URL}/api/auth/magic/{seeded_magic_link['magic_token']}")
        assert r1.status_code == 200
        r2 = requests.post(f"{BASE_URL}/api/auth/magic/{seeded_magic_link['magic_token']}")
        assert r2.status_code == 410, f"Expected 410 on reuse, got {r2.status_code}: {r2.text}"

    def test_invalid_magic_token(self):
        r = requests.post(f"{BASE_URL}/api/auth/magic/ml_TEST_does_not_exist_zzz")
        assert r.status_code == 404

    def test_malformed_magic_token(self):
        r = requests.post(f"{BASE_URL}/api/auth/magic/not-a-real-token")
        assert r.status_code == 400


class TestAuthMeRegression:
    def test_me_unauthenticated_returns_401(self):
        r = requests.get(f"{BASE_URL}/api/auth/me")
        assert r.status_code == 401, f"Expected 401 for unauth /me, got {r.status_code}"

    def test_protected_endpoints_unauth_401(self):
        for path in ("/api/archive", "/api/abilities", "/api/agent/kinds"):
            r = requests.get(f"{BASE_URL}{path}")
            assert r.status_code == 401, f"{path} returned {r.status_code}, expected 401"
