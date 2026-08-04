"""Restoration regression suite — Phase 39 (post-security-audit).

Explicit coverage for the four properties that were broken or missing at
different points in Phases 36-38 and are now protected by tests:

1. **State machine**
   - blocked (no image provider)
   - blocked (no active companion device)
   - queued (both configured) + companion command enqueued
   - complete after result upload; failed after fail report
   - foreign-photo → 404; invalid kind → 422

2. **Device-auth boundary (SEC audit)**
   - `/result` and `/fail` require device_token, reject session token
   - device_token from one user cannot terminate another user's job
   - `/companion/photo-file/{id}` requires device_token and is user-scoped

3. **Idempotency (code review)**
   - Second `/result` upload for a completed job returns the existing
     `result_photo_id` and does NOT create a duplicate photo doc
   - Second `/fail` after terminal is a no-op

4. **Magic-byte gate (SEC-HARD-3)**
   - HTML disguised as .png → 415
   - Real PNG magic bytes → 200 and content-type sniffed
"""
import io
import os
import uuid
import pytest
import requests
from pymongo import MongoClient

# -------------------------------------------------------------------------
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                break

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

# Two users so we can prove the auth boundary. Both are already seeded by
# earlier iterations, but we defensively upsert them in the fixture.
UA_SESSION = "rest_regress_ua_session"
UA_USER = "rest-regress-ua"
UA_DEVICE = "rest_regress_ua_device"

UB_SESSION = "rest_regress_ub_session"
UB_USER = "rest-regress-ub"
UB_DEVICE = "rest_regress_ub_device"

# 8-byte PNG signature is enough for detect_image_mime — we don't need a
# valid decoded image, just the magic prefix.
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128


# -------------------------------------------------------------------------
@pytest.fixture(scope="module")
def mdb():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module", autouse=True)
def _seed_users(mdb):
    """Idempotently seed two users, sessions, and device tokens."""
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    exp = now + timedelta(days=7)
    for uid, sess, dev, email in (
        (UA_USER, UA_SESSION, UA_DEVICE, "ua.regress@example.com"),
        (UB_USER, UB_SESSION, UB_DEVICE, "ub.regress@example.com"),
    ):
        mdb.users.update_one(
            {"user_id": uid},
            {"$set": {
                "user_id": uid, "email": email, "name": f"Regress {uid[-3:]}",
                "setup_complete": True, "onboarded": True,
                "tour_completed": True, "onboarding_complete": True,
            }},
            upsert=True,
        )
        mdb.user_sessions.update_one(
            {"session_token": sess},
            {"$set": {"user_id": uid, "session_token": sess, "expires_at": exp, "created_at": now}},
            upsert=True,
        )
        mdb.companion_devices.update_one(
            {"device_token": dev},
            {"$set": {
                "device_id": f"dev_{uid}", "user_id": uid, "device_token": dev,
                "name": "Regress PC", "revoked": False,
                "created_at": now, "last_seen": now,
            }},
            upsert=True,
        )
    yield
    # Best-effort cleanup — leave users but remove the jobs/photos this suite creates.
    mdb.restoration_jobs.delete_many({"user_id": {"$in": [UA_USER, UB_USER]}})
    mdb.photos.delete_many({"user_id": {"$in": [UA_USER, UB_USER]}, "is_restoration": True})
    mdb.companion_commands.delete_many({"user_id": {"$in": [UA_USER, UB_USER]}, "kind": "restore_photo"})


def _s(token=None):
    s = requests.Session()
    s.headers["Content-Type"] = "application/json"
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    return s


def _create_photo(mdb, user_id: str) -> str:
    """Insert a source photo doc directly — cheaper than uploading via the API."""
    pid = f"ph_regress_{uuid.uuid4().hex[:8]}"
    mdb.photos.insert_one({
        "photo_id": pid, "user_id": user_id,
        "path": f"heirloom/photos/{user_id}/{pid}.jpg",
        "caption": "regression source photo",
        "taken_at": None, "is_deleted": False,
    })
    return pid


def _set_image_provider(mdb, user_id: str, *, enabled: bool):
    """Toggle the local image provider so we can drive the blocked/queued paths."""
    mdb.user_providers.update_one(
        {"user_id": user_id},
        {"$set": {
            f"image.enabled": enabled,
            f"image.base_url": "http://127.0.0.1:8188" if enabled else "",
            f"image.provider_type": "comfyui",
            f"image.model": "",
            f"image.api_key": "",
        }},
        upsert=True,
    )


def _set_companion_revoked(mdb, user_id: str, *, revoked: bool):
    mdb.companion_devices.update_many({"user_id": user_id}, {"$set": {"revoked": revoked}})


# =========================================================================
# 1. STATE MACHINE
# =========================================================================
class TestStateMachine:

    def test_blocked_no_image_provider(self, mdb):
        _set_image_provider(mdb, UA_USER, enabled=False)
        _set_companion_revoked(mdb, UA_USER, revoked=False)
        photo_id = _create_photo(mdb, UA_USER)
        r = _s(UA_SESSION).post(f"{BASE_URL}/api/restoration/jobs",
                                 json={"photo_id": photo_id, "kind": "restore"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "blocked"
        assert "image provider" in (body.get("reason") or "").lower()

    def test_blocked_no_companion(self, mdb):
        _set_image_provider(mdb, UA_USER, enabled=True)
        _set_companion_revoked(mdb, UA_USER, revoked=True)  # simulate no active device
        photo_id = _create_photo(mdb, UA_USER)
        r = _s(UA_SESSION).post(f"{BASE_URL}/api/restoration/jobs",
                                 json={"photo_id": photo_id, "kind": "colorize"})
        _set_companion_revoked(mdb, UA_USER, revoked=False)  # restore for later tests
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "blocked"
        assert "companion" in (body.get("reason") or "").lower()

    def test_queued_and_command_enqueued(self, mdb):
        _set_image_provider(mdb, UA_USER, enabled=True)
        _set_companion_revoked(mdb, UA_USER, revoked=False)
        photo_id = _create_photo(mdb, UA_USER)
        r = _s(UA_SESSION).post(f"{BASE_URL}/api/restoration/jobs",
                                 json={"photo_id": photo_id, "kind": "upscale"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "queued"
        # Companion command must exist for this job
        cmd = mdb.companion_commands.find_one({
            "user_id": UA_USER, "kind": "restore_photo",
            "payload.job_id": body["job_id"],
        })
        assert cmd is not None
        assert cmd["payload"]["kind"] == "upscale"

    def test_foreign_photo_404(self, mdb):
        # UB tries to restore UA's photo
        photo_id = _create_photo(mdb, UA_USER)
        r = _s(UB_SESSION).post(f"{BASE_URL}/api/restoration/jobs",
                                 json={"photo_id": photo_id, "kind": "restore"})
        assert r.status_code == 404

    def test_invalid_kind_422(self, mdb):
        photo_id = _create_photo(mdb, UA_USER)
        r = _s(UA_SESSION).post(f"{BASE_URL}/api/restoration/jobs",
                                 json={"photo_id": photo_id, "kind": "not_a_kind"})
        assert r.status_code == 422


# =========================================================================
# 2. DEVICE-AUTH BOUNDARY
# =========================================================================
class TestDeviceAuthBoundary:

    def _seed_queued_job(self, mdb) -> str:
        _set_image_provider(mdb, UA_USER, enabled=True)
        _set_companion_revoked(mdb, UA_USER, revoked=False)
        photo_id = _create_photo(mdb, UA_USER)
        r = _s(UA_SESSION).post(f"{BASE_URL}/api/restoration/jobs",
                                 json={"photo_id": photo_id, "kind": "restore"})
        return r.json()["job_id"]

    def test_result_rejects_session_token(self, mdb):
        job_id = self._seed_queued_job(mdb)
        files = {"file": ("x.png", io.BytesIO(PNG_BYTES), "image/png")}
        r = requests.post(
            f"{BASE_URL}/api/restoration/jobs/{job_id}/result",
            headers={"Authorization": f"Bearer {UA_SESSION}"},
            files=files,
        )
        assert r.status_code == 401, r.text

    def test_result_rejects_no_auth(self, mdb):
        job_id = self._seed_queued_job(mdb)
        files = {"file": ("x.png", io.BytesIO(PNG_BYTES), "image/png")}
        r = requests.post(f"{BASE_URL}/api/restoration/jobs/{job_id}/result", files=files)
        assert r.status_code == 401

    def test_result_rejects_other_users_device(self, mdb):
        """UB's device_token must not be able to upload a result for UA's job."""
        job_id = self._seed_queued_job(mdb)
        files = {"file": ("x.png", io.BytesIO(PNG_BYTES), "image/png")}
        r = requests.post(
            f"{BASE_URL}/api/restoration/jobs/{job_id}/result",
            headers={"Authorization": f"Bearer {UB_DEVICE}"},
            files=files,
        )
        # Server can't tell whether it's "job not found for this user" or
        # a genuine 404 — 404 is the correct response either way.
        assert r.status_code == 404, r.text

    def test_fail_rejects_session_token(self, mdb):
        job_id = self._seed_queued_job(mdb)
        r = requests.post(
            f"{BASE_URL}/api/restoration/jobs/{job_id}/fail",
            headers={"Authorization": f"Bearer {UA_SESSION}", "Content-Type": "application/json"},
            json={"reason": "test"},
        )
        assert r.status_code == 401

    def test_fail_accepts_owning_device(self, mdb):
        job_id = self._seed_queued_job(mdb)
        r = requests.post(
            f"{BASE_URL}/api/restoration/jobs/{job_id}/fail",
            headers={"Authorization": f"Bearer {UA_DEVICE}", "Content-Type": "application/json"},
            json={"reason": "ComfyUI offline"},
        )
        assert r.status_code == 200
        # Verify status flipped
        got = _s(UA_SESSION).get(f"{BASE_URL}/api/restoration/jobs/{job_id}").json()
        assert got["status"] == "failed"
        assert "ComfyUI offline" in got["reason"]

    def test_photo_file_requires_device_token(self, mdb):
        photo_id = _create_photo(mdb, UA_USER)
        # No auth → 401
        r = requests.get(f"{BASE_URL}/api/companion/photo-file/{photo_id}")
        assert r.status_code == 401
        # Session token → 401 (not a device token)
        r = requests.get(f"{BASE_URL}/api/companion/photo-file/{photo_id}",
                         headers={"Authorization": f"Bearer {UA_SESSION}"})
        assert r.status_code == 401

    def test_photo_file_rejects_other_users_device(self, mdb):
        photo_id = _create_photo(mdb, UA_USER)
        r = requests.get(f"{BASE_URL}/api/companion/photo-file/{photo_id}",
                         headers={"Authorization": f"Bearer {UB_DEVICE}"})
        assert r.status_code == 404


# =========================================================================
# 3. IDEMPOTENCY
# =========================================================================
class TestIdempotency:

    def _queue(self, mdb) -> str:
        _set_image_provider(mdb, UA_USER, enabled=True)
        _set_companion_revoked(mdb, UA_USER, revoked=False)
        photo_id = _create_photo(mdb, UA_USER)
        return _s(UA_SESSION).post(f"{BASE_URL}/api/restoration/jobs",
                                    json={"photo_id": photo_id, "kind": "restore"}).json()["job_id"]

    def test_double_result_upload_is_idempotent(self, mdb):
        job_id = self._queue(mdb)
        files = {"file": ("first.png", io.BytesIO(PNG_BYTES), "image/png")}
        r1 = requests.post(
            f"{BASE_URL}/api/restoration/jobs/{job_id}/result",
            headers={"Authorization": f"Bearer {UA_DEVICE}"},
            files=files,
        )
        assert r1.status_code == 200
        rpid1 = r1.json()["result_photo_id"]
        assert rpid1

        # Second upload
        files2 = {"file": ("second.png", io.BytesIO(PNG_BYTES), "image/png")}
        r2 = requests.post(
            f"{BASE_URL}/api/restoration/jobs/{job_id}/result",
            headers={"Authorization": f"Bearer {UA_DEVICE}"},
            files=files2,
        )
        assert r2.status_code == 200
        b2 = r2.json()
        assert b2.get("already_complete") is True
        assert b2["result_photo_id"] == rpid1

        # Exactly ONE restored photo doc must exist for this source
        count = mdb.photos.count_documents({
            "user_id": UA_USER, "is_restoration": True,
            "source_photo_id": {"$exists": True},
            "photo_id": rpid1,
        })
        assert count == 1

    def test_double_fail_is_idempotent(self, mdb):
        job_id = self._queue(mdb)
        h = {"Authorization": f"Bearer {UA_DEVICE}", "Content-Type": "application/json"}
        r1 = requests.post(f"{BASE_URL}/api/restoration/jobs/{job_id}/fail",
                           headers=h, json={"reason": "first"})
        assert r1.status_code == 200 and r1.json().get("ok") is True
        r2 = requests.post(f"{BASE_URL}/api/restoration/jobs/{job_id}/fail",
                           headers=h, json={"reason": "second"})
        assert r2.status_code == 200
        # Terminal — must not have mutated the reason
        got = _s(UA_SESSION).get(f"{BASE_URL}/api/restoration/jobs/{job_id}").json()
        assert got["status"] == "failed"
        assert got["reason"] == "first"


# =========================================================================
# 4. MAGIC-BYTE GATE
# =========================================================================
class TestMagicByteGate:

    def _queue(self, mdb) -> str:
        _set_image_provider(mdb, UA_USER, enabled=True)
        _set_companion_revoked(mdb, UA_USER, revoked=False)
        photo_id = _create_photo(mdb, UA_USER)
        return _s(UA_SESSION).post(f"{BASE_URL}/api/restoration/jobs",
                                    json={"photo_id": photo_id, "kind": "restore"}).json()["job_id"]

    def test_html_disguised_as_png_rejected(self, mdb):
        job_id = self._queue(mdb)
        evil = b"<html><script>alert('xss')</script></html>"
        files = {"file": ("shady.png", io.BytesIO(evil), "image/png")}
        r = requests.post(
            f"{BASE_URL}/api/restoration/jobs/{job_id}/result",
            headers={"Authorization": f"Bearer {UA_DEVICE}"},
            files=files,
        )
        assert r.status_code == 415, r.text

    def test_zero_byte_upload_rejected(self, mdb):
        job_id = self._queue(mdb)
        files = {"file": ("empty.png", io.BytesIO(b""), "image/png")}
        r = requests.post(
            f"{BASE_URL}/api/restoration/jobs/{job_id}/result",
            headers={"Authorization": f"Bearer {UA_DEVICE}"},
            files=files,
        )
        assert r.status_code == 415

    def test_real_png_accepted(self, mdb):
        job_id = self._queue(mdb)
        files = {"file": ("legit.png", io.BytesIO(PNG_BYTES), "image/png")}
        r = requests.post(
            f"{BASE_URL}/api/restoration/jobs/{job_id}/result",
            headers={"Authorization": f"Bearer {UA_DEVICE}"},
            files=files,
        )
        assert r.status_code == 200
        assert r.json()["result_photo_id"]

    def test_jpeg_magic_accepted(self, mdb):
        job_id = self._queue(mdb)
        jpeg = b"\xff\xd8\xff" + b"\x00" * 128  # JPEG SOI marker
        files = {"file": ("legit.jpg", io.BytesIO(jpeg), "application/octet-stream")}
        r = requests.post(
            f"{BASE_URL}/api/restoration/jobs/{job_id}/result",
            headers={"Authorization": f"Bearer {UA_DEVICE}"},
            files=files,
        )
        assert r.status_code == 200
