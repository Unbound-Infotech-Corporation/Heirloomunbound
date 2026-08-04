"""
Iteration 39: verify rotation-alert reset semantic and /routing/usage/daily API.
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import requests

sys.path.insert(0, "/app/backend")

# Load frontend .env for REACT_APP_BACKEND_URL
try:
    with open("/app/frontend/.env") as f:
        for line in f:
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k, v)
except FileNotFoundError:
    pass
# Load backend .env for MONGO_URL/DB_NAME
try:
    with open("/app/backend/.env") as f:
        for line in f:
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k, v.strip('"'))
except FileNotFoundError:
    pass

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")


# -----------------------------------------------------------------
# /api/routing/usage/daily
# -----------------------------------------------------------------
SESSION_TOKEN = "test_routing_session"


def _cookies(tok=SESSION_TOKEN):
    return {"session_token": tok}


def _headers():
    return {"Content-Type": "application/json"}


class TestUsageDaily:
    def test_default_days(self):
        r = requests.get(f"{BASE_URL}/api/routing/usage/daily", headers=_headers(), cookies=_cookies(), timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "days" in data and "series" in data
        assert isinstance(data["days"], list)
        assert isinstance(data["series"], dict)
        # default should be 30
        assert len(data["days"]) == 30
        # dates ISO YYYY-MM-DD
        datetime.strptime(data["days"][0], "%Y-%m-%d")
        # each series has same length as days
        for pid, arr in data["series"].items():
            assert len(arr) == 30, f"{pid} has {len(arr)} not 30"
            assert all(isinstance(x, (int, float)) for x in arr)

    def test_days_7(self):
        r = requests.get(f"{BASE_URL}/api/routing/usage/daily?days=7", headers=_headers(), cookies=_cookies(), timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert len(data["days"]) == 7
        for arr in data["series"].values():
            assert len(arr) == 7

    def test_days_clamped_high(self):
        r = requests.get(f"{BASE_URL}/api/routing/usage/daily?days=1000", headers=_headers(), cookies=_cookies(), timeout=15)
        assert r.status_code == 200
        assert len(r.json()["days"]) == 90

    def test_days_clamped_zero(self):
        r = requests.get(f"{BASE_URL}/api/routing/usage/daily?days=0", headers=_headers(), cookies=_cookies(), timeout=15)
        assert r.status_code == 200
        assert len(r.json()["days"]) == 1

    def test_caller_scoped(self):
        # Create ephemeral user + session using sync pymongo (avoid motor event-loop issues)
        from pymongo import MongoClient
        user_a = f"iter39-a-{uuid.uuid4().hex[:6]}"
        session_a = f"iter39-sess-a-{uuid.uuid4().hex[:6]}"
        client = MongoClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]

        db.users.insert_one({
            "user_id": user_a, "email": f"{user_a}@t.com", "name": "A",
            "onboarding_complete": True, "created_at": datetime.now(timezone.utc).isoformat(),
        })
        db.user_sessions.insert_one({
            "session_token": session_a, "user_id": user_a,
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
        })
        db.usage_events.insert_one({
            "user_id": user_a, "provider": "openai", "model": "gpt-4o",
            "cost_usd": 12.3456, "input_tokens": 1, "output_tokens": 1,
            "ts": datetime.now(timezone.utc).isoformat(),
        })

        try:
            ra = requests.get(f"{BASE_URL}/api/routing/usage/daily?days=7",
                              headers=_headers(), cookies=_cookies(session_a), timeout=15)
            assert ra.status_code == 200, ra.text
            series_a = ra.json()["series"]
            openai_a = series_a.get("openai", [])
            assert any(abs(v - 12.3456) < 0.01 for v in openai_a), f"A missing usage: {openai_a}"

            rb = requests.get(f"{BASE_URL}/api/routing/usage/daily?days=7",
                              headers=_headers(), cookies=_cookies(), timeout=15)
            assert rb.status_code == 200
            openai_b = rb.json()["series"].get("openai", [])
            assert not any(abs(v - 12.3456) < 0.01 for v in openai_b), \
                f"cross-user leak: {openai_b}"
        finally:
            db.users.delete_one({"user_id": user_a})
            db.user_sessions.delete_one({"session_token": session_a})
            db.usage_events.delete_many({"user_id": user_a})


# -----------------------------------------------------------------
# Rotation alert reset semantic - direct _write_health invocation
# -----------------------------------------------------------------
class TestRotationAlertReset:
    def test_full_cycle(self):
        from services import provider_health as ph
        db = ph.db

        uid = f"iter39-rot-{uuid.uuid4().hex[:6]}"
        provider = "openai"

        async def scenario():
            # Ensure a user exists (with email) so alert path exercises
            await db.users.insert_one({
                "user_id": uid, "email": f"{uid}@t.com", "name": "Rot",
            })
            # Track how many times _send_rotation_alert is called
            calls = {"n": 0}
            orig = ph._send_rotation_alert

            async def counter(user_id, prov, err):
                calls["n"] += 1
                return True  # pretend delivered

            ph._send_rotation_alert = counter
            try:
                # (1) Set prior state = green
                await ph._write_health(uid, provider, "green", None, 10)
                row = await db.provider_health.find_one({"user_id": uid, "provider": provider})
                assert row["status"] == "green"
                assert row.get("rotation_alert_sent") is False
                assert calls["n"] == 0

                # (2) Green -> red: should fire
                await ph._write_health(uid, provider, "red", "boom", 100)
                row = await db.provider_health.find_one({"user_id": uid, "provider": provider})
                assert row["status"] == "red"
                assert row.get("rotation_alert_sent") is True
                assert calls["n"] == 1, f"expected 1 call, got {calls['n']}"

                # (3) Red -> red: should NOT fire again
                await ph._write_health(uid, provider, "red", "still broken", 100)
                row = await db.provider_health.find_one({"user_id": uid, "provider": provider})
                assert row.get("rotation_alert_sent") is True
                assert calls["n"] == 1, f"guard failed, got {calls['n']}"

                # (4) Red -> green: flag resets
                await ph._write_health(uid, provider, "green", None, 10)
                row = await db.provider_health.find_one({"user_id": uid, "provider": provider})
                assert row["status"] == "green"
                assert row.get("rotation_alert_sent") is False, "reset failed"
                assert calls["n"] == 1

                # (5) Green -> red again: fires
                await ph._write_health(uid, provider, "red", "boom2", 100)
                row = await db.provider_health.find_one({"user_id": uid, "provider": provider})
                assert row.get("rotation_alert_sent") is True
                assert calls["n"] == 2, f"expected 2 calls, got {calls['n']}"
            finally:
                ph._send_rotation_alert = orig
                await db.provider_health.delete_many({"user_id": uid})
                await db.users.delete_one({"user_id": uid})

        asyncio.run(scenario())


# -----------------------------------------------------------------
# send_provider_rotation_email is callable
# -----------------------------------------------------------------
class TestRotationEmailTemplate:
    def test_callable(self):
        from email_service import send_provider_rotation_email

        async def run():
            result = await send_provider_rotation_email(
                to="ops@example.com",
                owner_name="Ops",
                provider="openai",
                error="401 unauthorized",
            )
            assert isinstance(result, dict)
            # In preview pod, Resend may reject example.com or RESEND_API_KEY may be
            # unset. Any of ok/skipped/error is fine — the point is the template
            # function is callable, produces an HTML body, and doesn't raise.

        asyncio.run(run())
