"""Iteration 37 — Photo Restoration + Budget Alerts + Regression.

Covers:
- POST /api/restoration/jobs state machine (blocked/no-provider, blocked/no-companion, queued)
- Foreign photo → 404, invalid kind → 400/422
- GET list/get + fail endpoint
- GET /api/companion/photo-file/{photo_id} with device token
- Budget alert idempotency (single row per user+provider+month+tier)
- Regression: /api/routing/catalog shape, /api/routing/chat, PUT /api/routing/config preserves keys
- Regression: /api/dashboard
"""
import io
import os
import uuid
import time
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Read from frontend/.env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                break

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

SESSION_TOKEN = "test_routing_session"
USER_ID = "test-routing-user"
DEVICE_TOKEN = "device_test_token_abc"


@pytest.fixture(scope="module")
def mdb():
    c = MongoClient(MONGO_URL)
    return c[DB_NAME]


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {SESSION_TOKEN}", "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def device_client():
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {DEVICE_TOKEN}"})
    return s


@pytest.fixture(scope="module")
def seed_photo(mdb):
    """Seed a photo directly: put bytes in storage + insert doc with `path` field.

    We seed directly so the doc has the `path` key that /companion/photo-file expects
    (the /photos/upload endpoint stores `storage_path`, which is a separate field).
    """
    import sys
    sys.path.insert(0, "/app/backend")
    from storage import put_object  # noqa

    photo_id = f"ph_TEST_{uuid.uuid4().hex[:10]}"
    path = f"heirloom/photos/{USER_ID}/{photo_id}.png"
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
        b"\x00\x00\x00\x03\x00\x01\x5b\xd2\xf6\xfb\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    put_object(path, png, "image/png")
    mdb.photos.insert_one({
        "photo_id": photo_id,
        "user_id": USER_ID,
        "path": path,
        "caption": "TEST_iteration37",
        "is_deleted": False,
        "created_at": "2026-08-04T00:00:00+00:00",
    })
    yield photo_id
    mdb.photos.delete_one({"photo_id": photo_id})


# -------------------- Restoration state machine --------------------

class TestRestorationStateMachine:
    def _clear_provider_and_companion(self, mdb):
        mdb.user_providers.delete_one({"user_id": USER_ID})

    def test_blocked_when_no_image_provider(self, mdb, client, seed_photo):
        mdb.user_providers.delete_one({"user_id": USER_ID})
        r = client.post(f"{BASE_URL}/api/restoration/jobs", json={"photo_id": seed_photo, "kind": "restore"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "blocked"
        assert "image provider" in (data.get("reason") or "").lower()
        mdb.restoration_jobs.delete_one({"job_id": data["job_id"]})

    def test_blocked_when_no_companion(self, mdb, client, seed_photo):
        # Enable image provider but revoke all companions
        mdb.user_providers.replace_one(
            {"user_id": USER_ID},
            {"user_id": USER_ID, "image": {"enabled": True, "base_url": "http://127.0.0.1:8188",
                                            "api_key": "", "model": "", "provider_type": "comfyui"}},
            upsert=True,
        )
        mdb.companion_devices.update_many({"user_id": USER_ID}, {"$set": {"revoked": True}})
        r = client.post(f"{BASE_URL}/api/restoration/jobs", json={"photo_id": seed_photo, "kind": "restore"})
        # restore companion for later tests
        mdb.companion_devices.update_many({"user_id": USER_ID}, {"$set": {"revoked": False}})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "blocked"
        assert "desktop companion" in (data.get("reason") or "").lower()
        mdb.restoration_jobs.delete_one({"job_id": data["job_id"]})

    def test_queued_when_both_ready_and_enqueues_command(self, mdb, client, device_client, seed_photo):
        # Ensure device is active
        mdb.companion_devices.update_many({"user_id": USER_ID}, {"$set": {"revoked": False}})
        # Ensure image provider enabled
        mdb.user_providers.replace_one(
            {"user_id": USER_ID},
            {"user_id": USER_ID, "image": {"enabled": True, "base_url": "http://127.0.0.1:8188",
                                            "api_key": "", "model": "", "provider_type": "comfyui"}},
            upsert=True,
        )
        r = client.post(f"{BASE_URL}/api/restoration/jobs", json={"photo_id": seed_photo, "kind": "colorize"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "queued", data
        assert data["reason"] is None
        job_id = data["job_id"]

        # Companion poll should return a restore_photo command
        poll = device_client.get(f"{BASE_URL}/api/companion/poll")
        assert poll.status_code == 200, poll.text
        cmds = poll.json().get("commands", [])
        found = [c for c in cmds if c.get("kind") == "restore_photo" and c.get("payload", {}).get("job_id") == job_id]
        assert found, f"restore_photo command with job_id={job_id} not found in poll: {cmds}"
        assert found[0]["payload"]["photo_id"] == seed_photo
        assert found[0]["payload"]["kind"] == "colorize"

        # Cleanup
        mdb.restoration_jobs.delete_one({"job_id": job_id})
        mdb.companion_commands.delete_many({"payload.job_id": job_id})

    def test_foreign_photo_404(self, client):
        r = client.post(f"{BASE_URL}/api/restoration/jobs", json={"photo_id": "ph_nonexistent", "kind": "restore"})
        assert r.status_code == 404

    def test_invalid_kind_returns_400_or_422(self, client, seed_photo):
        r = client.post(f"{BASE_URL}/api/restoration/jobs", json={"photo_id": seed_photo, "kind": "sharpen"})
        # Pydantic Literal rejects with 422 before app-level 400; either is acceptable rejection.
        assert r.status_code in (400, 422), r.text


# -------------------- List / Get / Fail --------------------

class TestRestorationJobsIO:
    def test_list_sorted_desc_and_scoped(self, mdb, client, seed_photo):
        # Create two jobs (they will be blocked since provider likely cleared by earlier test, but that's fine)
        mdb.user_providers.delete_one({"user_id": USER_ID})
        a = client.post(f"{BASE_URL}/api/restoration/jobs",
                        json={"photo_id": seed_photo, "kind": "restore"}).json()
        time.sleep(0.05)
        b = client.post(f"{BASE_URL}/api/restoration/jobs",
                        json={"photo_id": seed_photo, "kind": "upscale"}).json()

        r = client.get(f"{BASE_URL}/api/restoration/jobs")
        assert r.status_code == 200
        jobs = r.json()
        assert isinstance(jobs, list) and len(jobs) >= 2
        # Descending created_at
        created = [j["created_at"] for j in jobs]
        assert created == sorted(created, reverse=True)
        # All belong to caller
        for j in jobs:
            assert j["user_id"] == USER_ID

        # Cleanup
        mdb.restoration_jobs.delete_many({"job_id": {"$in": [a["job_id"], b["job_id"]]}})

    def test_get_own_job_and_foreign_404(self, mdb, client, seed_photo):
        mdb.user_providers.delete_one({"user_id": USER_ID})
        job = client.post(f"{BASE_URL}/api/restoration/jobs",
                          json={"photo_id": seed_photo, "kind": "restore"}).json()
        job_id = job["job_id"]
        r = client.get(f"{BASE_URL}/api/restoration/jobs/{job_id}")
        assert r.status_code == 200
        assert r.json()["job_id"] == job_id

        r2 = client.get(f"{BASE_URL}/api/restoration/jobs/rst_nope_foreign")
        assert r2.status_code == 404

        mdb.restoration_jobs.delete_one({"job_id": job_id})

    def test_fail_sets_status_and_reason(self, mdb, client, seed_photo):
        mdb.user_providers.delete_one({"user_id": USER_ID})
        job = client.post(f"{BASE_URL}/api/restoration/jobs",
                          json={"photo_id": seed_photo, "kind": "restore"}).json()
        job_id = job["job_id"]

        r = client.post(f"{BASE_URL}/api/restoration/jobs/{job_id}/fail",
                        json={"reason": "comfy timeout xyz"})
        assert r.status_code == 200, r.text

        got = client.get(f"{BASE_URL}/api/restoration/jobs/{job_id}").json()
        assert got["status"] == "failed"
        assert got["reason"] == "comfy timeout xyz"

        mdb.restoration_jobs.delete_one({"job_id": job_id})

    def test_fail_foreign_job_404(self, client):
        r = client.post(f"{BASE_URL}/api/restoration/jobs/rst_nope_foreign/fail",
                        json={"reason": "x"})
        assert r.status_code == 404


# -------------------- Companion photo-file --------------------

class TestCompanionPhotoFile:
    def test_returns_bytes_with_device_token(self, device_client, seed_photo):
        r = device_client.get(f"{BASE_URL}/api/companion/photo-file/{seed_photo}")
        assert r.status_code == 200, r.text
        assert r.content and len(r.content) > 20
        assert r.headers.get("content-type", "").startswith("image/")

    def test_401_without_device_token(self, seed_photo):
        r = requests.get(f"{BASE_URL}/api/companion/photo-file/{seed_photo}")
        assert r.status_code == 401

    def test_404_for_foreign_photo(self, device_client):
        r = device_client.get(f"{BASE_URL}/api/companion/photo-file/ph_nonexistent")
        assert r.status_code == 404


# -------------------- Budget alert idempotency --------------------

class TestBudgetAlertIdempotency:
    def test_alert_row_inserted_once_and_chat_still_ok(self, mdb, client):
        # Set an absurdly tiny budget cap on emergent so the very first chat call trips 100%.
        cfg_doc = mdb.routing_configs.find_one({"user_id": USER_ID}) or {}
        providers = cfg_doc.get("providers") or {}
        # Disable every non-emergent provider so this test isn't polluted by leftover BYOK keys
        # from earlier tests (which would sit ahead of emergent in the fallback chain).
        for pid in ("openai", "anthropic", "gemini", "groq", "xai", "deepseek"):
            pcfg = providers.get(pid) or {}
            pcfg["enabled"] = False
            providers[pid] = pcfg
        emergent_cfg = providers.get("emergent") or {"enabled": True, "api_key": "", "default_model": "claude-sonnet-4-6"}
        emergent_cfg["monthly_budget_usd"] = 0.00001
        emergent_cfg["enabled"] = True
        providers["emergent"] = emergent_cfg
        mdb.routing_configs.update_one(
            {"user_id": USER_ID},
            {"$set": {"user_id": USER_ID, "providers": providers}},
            upsert=True,
        )

        # Clear any prior budget_alerts for this month/user/emergent so we test fresh idempotency
        from datetime import datetime, timezone as _tz
        now = datetime.now(_tz.utc)
        month = f"{now.year:04d}-{now.month:02d}"
        mdb.budget_alerts.delete_many({"user_id": USER_ID, "provider": "emergent", "month": month})

        # Chat twice
        for _ in range(2):
            r = client.post(f"{BASE_URL}/api/routing/chat",
                            json={"task": "chat", "messages": [{"role": "user", "content": "hi"}]})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body.get("ok") is True, body

        # Exactly one budget_alerts row for (user, emergent, this-month) — could be tier 80 or 100
        rows = list(mdb.budget_alerts.find({"user_id": USER_ID, "provider": "emergent", "month": month}))
        assert len(rows) == 1, f"expected exactly 1 alert row, got {len(rows)}: {rows}"

        # Reset the cap back to 0 so we don't leak state
        providers["emergent"]["monthly_budget_usd"] = 0.0
        mdb.routing_configs.update_one({"user_id": USER_ID}, {"$set": {"providers": providers}})
        mdb.budget_alerts.delete_many({"user_id": USER_ID, "provider": "emergent", "month": month})


# -------------------- Regression: routing catalog + chat + config --------------------

class TestRoutingRegression:
    def test_catalog_shape(self, client):
        r = client.get(f"{BASE_URL}/api/routing/catalog")
        assert r.status_code == 200
        cat = r.json()
        assert len(cat.get("providers", [])) == 7
        assert len(cat.get("tasks", [])) == 6
        assert len(cat.get("pricing", [])) == 28

    def test_chat_normal_task_succeeds_and_logs(self, mdb, client):
        # Make sure budget is not blocking
        cfg = mdb.routing_configs.find_one({"user_id": USER_ID}) or {}
        providers = cfg.get("providers") or {}
        if "emergent" in providers:
            providers["emergent"]["monthly_budget_usd"] = 0.0
            mdb.routing_configs.update_one({"user_id": USER_ID}, {"$set": {"providers": providers}})

        before = mdb.usage_events.count_documents({"user_id": USER_ID})
        r = client.post(f"{BASE_URL}/api/routing/chat",
                        json={"task": "chat", "messages": [{"role": "user", "content": "say hi in 3 words"}]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["provider"]
        after = mdb.usage_events.count_documents({"user_id": USER_ID})
        assert after >= before + 1

    def test_config_put_empty_api_key_preserves_stored(self, mdb, client):
        # Seed a fake key first
        cfg = mdb.routing_configs.find_one({"user_id": USER_ID}) or {"user_id": USER_ID, "providers": {}}
        providers = cfg.get("providers") or {}
        providers["openai"] = {**providers.get("openai", {}), "enabled": True,
                               "api_key": "sk-preserve-me-abc", "default_model": "gpt-4o-mini",
                               "monthly_budget_usd": 0.0}
        mdb.routing_configs.update_one({"user_id": USER_ID}, {"$set": {"providers": providers}}, upsert=True)

        # PUT config with empty api_key for openai
        get_r = client.get(f"{BASE_URL}/api/routing/config")
        assert get_r.status_code == 200
        current = get_r.json()
        # Zero out the openai key in payload
        current["providers"]["openai"]["api_key"] = ""
        put_r = client.put(f"{BASE_URL}/api/routing/config", json=current)
        assert put_r.status_code == 200, put_r.text

        # Verify stored key is still the original
        stored = mdb.routing_configs.find_one({"user_id": USER_ID})
        assert stored["providers"]["openai"]["api_key"] == "sk-preserve-me-abc"


# -------------------- Regression: dashboard --------------------

class TestDashboardRegression:
    def test_dashboard_200(self, client):
        r = client.get(f"{BASE_URL}/api/dashboard")
        assert r.status_code == 200, r.text
        body = r.json()
        # Field name is total_words (word_count semantic) — verify a few dashboard fields exist.
        assert "total_words" in body or "word_count" in body
        assert "total_entries" in body
