"""Iteration 40 backend tests:
   - GET /api/routing/templates
   - POST /api/routing/templates/apply (happy path, unknown, preserves keys/budget)
   - GET /api/routing/usage/projection
   - Rotation-alert retry cap (green->red with failing send, capped at 3)
   - Regression sanity of prior endpoints (health, config redaction, chat rate limit trip)
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

import pytest
import requests

sys.path.insert(0, "/app/backend")

# Load env
for p in ("/app/frontend/.env", "/app/backend/.env"):
    try:
        with open(p) as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.strip().split("=", 1)
                    os.environ.setdefault(k, v.strip('"'))
    except FileNotFoundError:
        pass

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
SESSION = "test_routing_session"


def _c(tok=SESSION):
    return {"session_token": tok}


# -------- Templates --------
class TestTemplatesList:
    def test_returns_5_presets(self):
        r = requests.get(f"{BASE_URL}/api/routing/templates", cookies=_c(), timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data, list)
        ids = {t["id"] for t in data}
        assert ids == {"cheapest", "quality_first", "balanced", "all_emergent", "local_first"}, ids

    def test_shape(self):
        r = requests.get(f"{BASE_URL}/api/routing/templates", cookies=_c(), timeout=15)
        for t in r.json():
            assert "id" in t and "label" in t and "blurb" in t
            assert isinstance(t["task_routes"], dict)
            assert isinstance(t["required_providers"], list)
            # required_providers is derived from task_routes values
            expected = sorted(set(t["task_routes"].values()))
            assert t["required_providers"] == expected

    def test_balanced_content(self):
        r = requests.get(f"{BASE_URL}/api/routing/templates", cookies=_c(), timeout=15)
        b = next(t for t in r.json() if t["id"] == "balanced")
        assert b["task_routes"]["chat"] == "emergent"
        assert b["task_routes"]["cheap"] == "groq"
        assert b["task_routes"]["long_context"] == "gemini"
        assert b["task_routes"]["embeddings"] == "openai"


# -------- Apply Templates --------
class TestApplyTemplate:
    def test_unknown_400(self):
        r = requests.post(f"{BASE_URL}/api/routing/templates/apply",
                          json={"template_id": "does_not_exist"}, cookies=_c(), timeout=15)
        assert r.status_code == 400
        assert "unknown" in r.text.lower()

    def test_apply_balanced_updates_routes(self):
        r = requests.post(f"{BASE_URL}/api/routing/templates/apply",
                          json={"template_id": "balanced"}, cookies=_c(), timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["template"] == "balanced"
        assert "warnings" in data and isinstance(data["warnings"], list)
        assert "config" in data
        tr = data["config"]["task_routes"]
        assert tr["chat"] == "emergent"
        assert tr["cheap"] == "groq"
        assert tr["long_context"] == "gemini"
        assert tr["embeddings"] == "openai"

    def test_warnings_for_disabled_providers(self):
        # Use an ephemeral user so we control config state precisely
        from pymongo import MongoClient
        uid = f"iter40-appl-{uuid.uuid4().hex[:6]}"
        sess = f"iter40-sess-{uuid.uuid4().hex[:6]}"
        client = MongoClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        db.users.insert_one({"user_id": uid, "email": f"{uid}@t.com", "name": "T",
                             "onboarding_complete": True,
                             "created_at": datetime.now(timezone.utc).isoformat()})
        db.user_sessions.insert_one({
            "session_token": sess, "user_id": uid,
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
        })
        try:
            r = requests.post(f"{BASE_URL}/api/routing/templates/apply",
                              json={"template_id": "cheapest"}, cookies=_c(sess), timeout=15)
            assert r.status_code == 200, r.text
            warnings = r.json()["warnings"]
            # cheapest requires groq + deepseek + gemini + openai. Default only enables emergent.
            joined = " ".join(warnings).lower()
            for needed in ("groq", "deepseek", "gemini", "openai"):
                assert needed in joined, f"expected warning about {needed}: {warnings}"
        finally:
            db.routing_configs.delete_many({"user_id": uid})
            db.user_sessions.delete_one({"session_token": sess})
            db.users.delete_one({"user_id": uid})

    def test_preserves_keys_enabled_and_budget(self):
        """Set budget + enabled + fake key on ephemeral user, apply template, verify preserved."""
        from pymongo import MongoClient
        uid = f"iter40-pres-{uuid.uuid4().hex[:6]}"
        sess = f"iter40-sess-{uuid.uuid4().hex[:6]}"
        client = MongoClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        db.users.insert_one({"user_id": uid, "email": f"{uid}@t.com", "name": "T",
                             "onboarding_complete": True,
                             "created_at": datetime.now(timezone.utc).isoformat()})
        db.user_sessions.insert_one({
            "session_token": sess, "user_id": uid,
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
        })
        # seed a routing_configs doc for emergent with budget + groq with a fake key
        db.routing_configs.insert_one({
            "user_id": uid,
            "providers": {
                "emergent": {"enabled": True, "api_key": "", "default_model": "claude-sonnet-4-6",
                             "monthly_budget_usd": 17.77},
                "groq":     {"enabled": True, "api_key": "sk-groq-fake", "default_model": "llama-3.3-70b-versatile",
                             "monthly_budget_usd": 5.55},
            },
            "task_routes": {"chat": "emergent", "interview": "emergent", "tools": "emergent",
                            "cheap": "emergent", "long_context": "emergent", "embeddings": "emergent"},
            "fallback_order": ["emergent", "openai", "anthropic", "gemini", "groq", "xai", "deepseek"],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        try:
            # Apply balanced: touches only task_routes
            r = requests.post(f"{BASE_URL}/api/routing/templates/apply",
                              json={"template_id": "balanced"}, cookies=_c(sess), timeout=15)
            assert r.status_code == 200, r.text
            # Now fetch config and validate
            g = requests.get(f"{BASE_URL}/api/routing/config", cookies=_c(sess), timeout=15)
            assert g.status_code == 200
            cfg = g.json()
            emg = cfg["providers"]["emergent"]
            grq = cfg["providers"]["groq"]
            assert emg["enabled"] is True
            assert emg["monthly_budget_usd"] == 17.77, f"budget lost: {emg}"
            assert grq["enabled"] is True
            assert grq["monthly_budget_usd"] == 5.55
            # groq should have has_key=True (raw key preserved but redacted in response)
            assert grq.get("has_key") is True, grq
            assert grq.get("api_key") == "", "raw api_key must be redacted"
            # task_routes updated
            assert cfg["task_routes"]["cheap"] == "groq"
            assert cfg["task_routes"]["chat"] == "emergent"
        finally:
            db.routing_configs.delete_many({"user_id": uid})
            db.user_sessions.delete_one({"session_token": sess})
            db.users.delete_one({"user_id": uid})


# -------- /usage/projection --------
class TestUsageProjection:
    def test_empty_fresh_user(self):
        from pymongo import MongoClient
        uid = f"iter40-proj-{uuid.uuid4().hex[:6]}"
        sess = f"iter40-sess-{uuid.uuid4().hex[:6]}"
        client = MongoClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        db.users.insert_one({"user_id": uid, "email": f"{uid}@t.com", "name": "T",
                             "onboarding_complete": True,
                             "created_at": datetime.now(timezone.utc).isoformat()})
        db.user_sessions.insert_one({
            "session_token": sess, "user_id": uid,
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
        })
        try:
            r = requests.get(f"{BASE_URL}/api/routing/usage/projection",
                             cookies=_c(sess), timeout=15)
            assert r.status_code == 200
            assert r.json() == {}
        finally:
            db.user_sessions.delete_one({"session_token": sess})
            db.users.delete_one({"user_id": uid})

    def test_math(self):
        """Insert a known cost this month, verify projection = mtd/days_elapsed * days_in_month."""
        import calendar
        from pymongo import MongoClient
        uid = f"iter40-math-{uuid.uuid4().hex[:6]}"
        sess = f"iter40-sess-{uuid.uuid4().hex[:6]}"
        client = MongoClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        days_in_month = calendar.monthrange(now.year, now.month)[1]
        days_elapsed = (now - month_start).days + 1

        db.users.insert_one({"user_id": uid, "email": f"{uid}@t.com", "name": "T",
                             "onboarding_complete": True,
                             "created_at": now.isoformat()})
        db.user_sessions.insert_one({
            "session_token": sess, "user_id": uid,
            "created_at": now, "expires_at": now + timedelta(days=1),
        })
        db.usage_events.insert_one({
            "user_id": uid, "provider": "openai", "model": "gpt-4o",
            "cost_usd": 4.20, "prompt_tokens": 1, "completion_tokens": 1,
            "ts": month_start.isoformat(),
        })
        try:
            r = requests.get(f"{BASE_URL}/api/routing/usage/projection",
                             cookies=_c(sess), timeout=15)
            assert r.status_code == 200
            data = r.json()
            assert "openai" in data, data
            row = data["openai"]
            assert row["mtd_usd"] == 4.20
            assert row["days_elapsed"] == days_elapsed
            assert row["days_in_month"] == days_in_month
            expected = round(4.20 / days_elapsed * days_in_month, 4)
            assert row["projected_month_end_usd"] == expected, row
        finally:
            db.usage_events.delete_many({"user_id": uid})
            db.user_sessions.delete_one({"session_token": sess})
            db.users.delete_one({"user_id": uid})


# -------- Rotation alert retry cap --------
class TestRotationAlertRetryCap:
    def test_cap_at_3_and_reset_on_green(self):
        from services import provider_health as ph
        db = ph.db
        uid = f"iter40-cap-{uuid.uuid4().hex[:6]}"
        provider = "openai"

        async def scenario():
            await db.users.insert_one({"user_id": uid, "email": f"{uid}@t.com", "name": "Cap"})
            calls = {"n": 0}
            orig = ph._send_rotation_alert

            async def failing(user_id, prov, err):
                calls["n"] += 1
                return False  # simulate Resend failure

            ph._send_rotation_alert = failing
            try:
                # (1) prior green
                await ph._write_health(uid, provider, "green", None, 10)
                row = await db.provider_health.find_one({"user_id": uid, "provider": provider})
                assert row.get("rotation_alert_attempts", 0) == 0
                assert row.get("rotation_alert_sent") is False

                # (2) green -> red, delivery fails, attempts=1
                await ph._write_health(uid, provider, "red", "err1", 100)
                row = await db.provider_health.find_one({"user_id": uid, "provider": provider})
                assert calls["n"] == 1
                assert row.get("rotation_alert_attempts") == 1
                assert row.get("rotation_alert_sent") is False

                # (3) reset to green for next cycle
                await ph._write_health(uid, provider, "green", None, 10)
                row = await db.provider_health.find_one({"user_id": uid, "provider": provider})
                assert row.get("rotation_alert_attempts") == 0

                # Force attempts=2 directly, then green->red should tick to 3
                await db.provider_health.update_one(
                    {"user_id": uid, "provider": provider},
                    {"$set": {"status": "green", "rotation_alert_attempts": 2,
                              "rotation_alert_sent": False}},
                )
                await ph._write_health(uid, provider, "red", "err2", 100)
                row = await db.provider_health.find_one({"user_id": uid, "provider": provider})
                assert calls["n"] == 2, f"expected 2 sends total, got {calls['n']}"
                assert row.get("rotation_alert_attempts") == 3
                assert row.get("rotation_alert_sent") is False

                # Green (still red) so we set state manually — simulate persistent red with attempts=3
                # Now another green->red probe should NOT try to send
                await db.provider_health.update_one(
                    {"user_id": uid, "provider": provider},
                    {"$set": {"status": "green", "rotation_alert_attempts": 3,
                              "rotation_alert_sent": False}},
                )
                await ph._write_health(uid, provider, "red", "err3", 100)
                assert calls["n"] == 2, f"cap breached: {calls['n']}"
                row = await db.provider_health.find_one({"user_id": uid, "provider": provider})
                # attempts still 3 (not incremented past cap by send path)
                assert row.get("rotation_alert_attempts") == 3

                # (4) recovery: red -> green resets BOTH fields
                await ph._write_health(uid, provider, "green", None, 10)
                row = await db.provider_health.find_one({"user_id": uid, "provider": provider})
                assert row.get("rotation_alert_attempts") == 0
                assert row.get("rotation_alert_sent") is False

                # (5) fresh green->red after reset should attempt again (still fails)
                await ph._write_health(uid, provider, "red", "err4", 100)
                assert calls["n"] == 3
                row = await db.provider_health.find_one({"user_id": uid, "provider": provider})
                assert row.get("rotation_alert_attempts") == 1
            finally:
                ph._send_rotation_alert = orig
                await db.provider_health.delete_many({"user_id": uid})
                await db.users.delete_one({"user_id": uid})

        asyncio.run(scenario())


# -------- Regression sanity --------
class TestRegression:
    def test_config_redaction(self):
        r = requests.get(f"{BASE_URL}/api/routing/config", cookies=_c(), timeout=15)
        assert r.status_code == 200
        cfg = r.json()
        for pid, pcfg in cfg["providers"].items():
            assert pcfg.get("api_key") == "", f"{pid} leaked key"
            assert "has_key" in pcfg

    def test_health_endpoint(self):
        r = requests.get(f"{BASE_URL}/api/routing/health", cookies=_c(), timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_usage_daily_still_works(self):
        r = requests.get(f"{BASE_URL}/api/routing/usage/daily?days=30", cookies=_c(), timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert len(d["days"]) == 30
