"""Phase 4 tests:
- SEC-001 CORS allowlist
- SEC-002 Photo signed-URL + magic bytes
- SEC-003 SSRF guard for skills
- SEC-004 Rate limiting
- ReDoS guard in archive search
- Live Assistant: capture (reminder/memory/question), reminders CRUD, dashboard streak, twin retrieval
- Companion poll delivers reminders
- Regression: auth/me, archive, heirs, skills, photos list
"""
import io
import os
import time
import struct
import zlib

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or \
           "https://voice-clone-hub-20.preview.emergentagent.com"
API = f"{BASE_URL}/api"

# Seeded fresh in mongosh
TOKEN = "p4_sess_1782377069570"
USER_ID = "p4-user-1782377069570"
DEVICE_TOKEN = "comp_p4_1782377069570"
H = {"Authorization": f"Bearer {TOKEN}"}


# ---------------- helpers ----------------
def _real_png_bytes(width: int = 1, height: int = 1) -> bytes:
    """Build a minimal valid PNG (1x1 red pixel)."""
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"\x00\xff\x00\x00" * width
    idat = zlib.compress(b"".join([b"\x00" + raw] * height))
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _real_jpg_bytes() -> bytes:
    # Smallest valid JPEG marker sequence (will not actually decode but magic check is what we test)
    return b"\xff\xd8\xff\xe0" + b"\x00" * 16 + b"\xff\xd9"


# ============================================================
# SEC-001 CORS
# ============================================================
class TestCORS:
    """NOTE: Tests against direct backend (localhost:8001) to bypass the preview
    ingress, which overrides CORS headers in this environment. The FastAPI-level
    allowlist (SEC-001) is verified here. See test report for the ingress caveat."""
    DIRECT = "http://localhost:8001/api"

    def test_evil_origin_not_echoed(self):
        r = requests.get(f"{self.DIRECT}/auth/me",
                         headers={"Origin": "https://evil.example.com", **H}, timeout=10)
        acao = r.headers.get("Access-Control-Allow-Origin", "")
        assert acao not in ("https://evil.example.com", "*"), f"CORS leaked: ACAO={acao}"

    def test_allowed_emergent_origin(self):
        origin = BASE_URL
        r = requests.get(f"{self.DIRECT}/auth/me",
                         headers={"Origin": origin, **H}, timeout=10)
        acao = r.headers.get("Access-Control-Allow-Origin", "")
        assert acao == origin, f"expected ACAO={origin}, got {acao!r}"

    def test_unknown_origin_rejected(self):
        r = requests.get(f"{self.DIRECT}/auth/me",
                         headers={"Origin": "https://attacker.test", **H}, timeout=10)
        acao = r.headers.get("Access-Control-Allow-Origin", "")
        assert acao != "https://attacker.test"
        assert acao != "*"


# ============================================================
# Regression: auth/me
# ============================================================
class TestAuthMe:
    def test_auth_me(self):
        r = requests.get(f"{API}/auth/me", headers=H, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["user_id"] == USER_ID


# ============================================================
# SEC-002 — Photo signed URL + magic bytes
# ============================================================
class TestPhotos:
    photo_id: str | None = None

    def test_upload_fake_image_rejected(self):
        files = {"file": ("fake.png", b"not an image at all", "image/png")}
        r = requests.post(f"{API}/photos/upload", headers=H, files=files, timeout=20)
        assert r.status_code == 400, r.text
        assert "real image" in r.text.lower()

    def test_upload_real_png_ok(self):
        png = _real_png_bytes()
        files = {"file": ("ok.png", png, "image/png")}
        r = requests.post(f"{API}/photos/upload", headers=H, files=files, timeout=30)
        assert r.status_code == 200, r.text
        TestPhotos.photo_id = r.json()["photo_id"]

    def test_upload_real_jpg_ok(self):
        files = {"file": ("ok.jpg", _real_jpg_bytes(), "image/jpeg")}
        r = requests.post(f"{API}/photos/upload", headers=H, files=files, timeout=30)
        assert r.status_code == 200, r.text

    def test_file_bearer_auth_works(self):
        assert TestPhotos.photo_id, "need photo from prior test"
        r = requests.get(
            f"{API}/photos/{TestPhotos.photo_id}/file", headers=H, timeout=15
        )
        assert r.status_code == 200, r.text
        assert len(r.content) > 0

    def test_signed_url_flow(self):
        assert TestPhotos.photo_id
        r = requests.post(
            f"{API}/photos/{TestPhotos.photo_id}/signed-url", headers=H, timeout=10
        )
        assert r.status_code == 200, r.text
        d = r.json()
        sig, exp, uid = d["sig"], d["exp"], d.get("user_id") or d.get("uid")
        # GET with sig works without Bearer
        r2 = requests.get(
            f"{API}/photos/{TestPhotos.photo_id}/file",
            params={"sig": sig, "exp": exp, "uid": uid}, timeout=15,
        )
        assert r2.status_code == 200, r2.text

    def test_tampered_sig_unauthorized(self):
        assert TestPhotos.photo_id
        r = requests.post(f"{API}/photos/{TestPhotos.photo_id}/signed-url", headers=H, timeout=10)
        d = r.json()
        bad_sig = "0" * len(d["sig"])
        r2 = requests.get(
            f"{API}/photos/{TestPhotos.photo_id}/file",
            params={"sig": bad_sig, "exp": d["exp"], "uid": d.get("user_id") or d.get("uid")}, timeout=15,
        )
        assert r2.status_code == 401, r2.text

    def test_expired_sig_unauthorized(self):
        assert TestPhotos.photo_id
        r = requests.post(f"{API}/photos/{TestPhotos.photo_id}/signed-url", headers=H, timeout=10)
        d = r.json()
        r2 = requests.get(
            f"{API}/photos/{TestPhotos.photo_id}/file",
            params={"sig": d["sig"], "exp": 1, "uid": d.get("user_id") or d.get("uid")}, timeout=15,
        )
        assert r2.status_code == 401, r2.text

    def test_no_auth_no_sig_unauthorized(self):
        assert TestPhotos.photo_id
        r = requests.get(f"{API}/photos/{TestPhotos.photo_id}/file", timeout=15)
        assert r.status_code == 401, r.text

    def test_session_token_query_no_longer_works(self):
        """SEC-002: ?auth=session_token must NOT bypass auth anymore."""
        assert TestPhotos.photo_id
        r = requests.get(
            f"{API}/photos/{TestPhotos.photo_id}/file",
            params={"auth": TOKEN}, timeout=15,
        )
        assert r.status_code == 401, r.text


# ============================================================
# SEC-003 — SSRF in skills
# ============================================================
class TestSSRF:
    @pytest.mark.parametrize("bad_url", [
        "http://169.254.169.254/latest/meta-data/",
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://192.168.1.1/",
        "ftp://example.com/file",
    ])
    def test_invoke_blocks_internal_or_bad_scheme(self, bad_url):
        # Create skill
        r = requests.post(f"{API}/skills", headers=H, json={
            "name": f"ssrf-{bad_url[:20]}",
            "description": "test",
            "webhook_url": bad_url,
            "enabled": True,
        }, timeout=10)
        assert r.status_code == 200, r.text
        sid = r.json()["skill_id"]
        # Invoke
        r2 = requests.post(f"{API}/skills/{sid}/invoke", headers=H, json={"input": "x"}, timeout=15)
        assert r2.status_code == 400, f"expected 400 for {bad_url}, got {r2.status_code}: {r2.text}"
        # Cleanup
        requests.delete(f"{API}/skills/{sid}", headers=H, timeout=10)

    def test_invoke_public_url_ok(self):
        r = requests.post(f"{API}/skills", headers=H, json={
            "name": "public-skill",
            "description": "test",
            "webhook_url": "https://httpbin.org/anything",
            "enabled": True,
        }, timeout=10)
        assert r.status_code == 200
        sid = r.json()["skill_id"]
        r2 = requests.post(f"{API}/skills/{sid}/invoke", headers=H, json={"input": "hello"}, timeout=30)
        # Should reach the public host and return 200 (or at most 5xx from httpbin, but not 400 SSRF block)
        assert r2.status_code != 400, f"public URL wrongly blocked: {r2.text}"
        requests.delete(f"{API}/skills/{sid}", headers=H, timeout=10)


# ============================================================
# ReDoS guard
# ============================================================
class TestRedos:
    def test_regex_bomb_safe(self):
        r = requests.get(f"{API}/archive", headers=H, params={"q": "(a+)+"}, timeout=15)
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_open_bracket_safe(self):
        r = requests.get(f"{API}/archive", headers=H, params={"q": "["}, timeout=15)
        assert r.status_code == 200, r.text


# ============================================================
# Live Assistant: capture
# ============================================================
class TestCapture:
    memory_inserted = False

    def test_capture_reminder(self):
        r = requests.post(f"{API}/capture", headers=H, json={
            "text": "Remind me to call mom tomorrow at 3pm"
        }, timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["kind"] == "reminder", f"expected reminder, got {d}"
        assert d.get("reminder_id"), f"no reminder_id: {d}"
        assert d.get("due_at"), f"no due_at: {d}"

    def test_capture_memory(self):
        r = requests.post(f"{API}/capture", headers=H, json={
            "text": "Best memory: my dad teaching me to fish at Lake Tenkiller in 1979 — sunrise, no other boats."
        }, timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["kind"] in ("memory", "value", "advice", "quote", "note"), f"got kind={d.get('kind')}"
        assert d.get("entry"), f"no entry returned: {d}"
        TestCapture.memory_inserted = True
        # Verify in /archive
        r2 = requests.get(f"{API}/archive", headers=H, timeout=15)
        assert r2.status_code == 200
        titles = [e["title"].lower() for e in r2.json()]
        assert any("fish" in t or "fishing" in t or "lake" in t or "dad" in t for t in titles), \
            f"memory not found in archive: {titles}"

    def test_capture_question(self):
        # Ensure the memory exists first
        if not TestCapture.memory_inserted:
            self.test_capture_memory()
        time.sleep(1)
        r = requests.post(f"{API}/capture", headers=H, json={
            "text": "Where did dad teach me to fish?"
        }, timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["kind"] == "question", f"got {d}"
        assert d.get("answer"), f"no answer: {d}"
        assert isinstance(d.get("sources"), list)
        assert len(d["sources"]) > 0, f"empty sources: {d}"


# ============================================================
# Reminders CRUD
# ============================================================
class TestReminders:
    rid: str | None = None

    def test_create(self):
        r = requests.post(f"{API}/reminders", headers=H, json={
            "text": "TEST_buy milk", "due_at": "2099-01-01T12:00:00+00:00",
        }, timeout=10)
        assert r.status_code == 200, r.text
        TestReminders.rid = r.json()["reminder_id"]

    def test_list_open(self):
        r = requests.get(f"{API}/reminders", headers=H, params={"status": "open"}, timeout=10)
        assert r.status_code == 200
        assert any(x["reminder_id"] == TestReminders.rid for x in r.json())

    def test_today(self):
        r = requests.get(f"{API}/reminders/today", headers=H, timeout=10)
        assert r.status_code == 200
        d = r.json()
        for k in ("overdue", "today", "no_date"):
            assert k in d

    def test_patch(self):
        r = requests.patch(f"{API}/reminders/{TestReminders.rid}", headers=H, json={
            "text": "TEST_buy almond milk"
        }, timeout=10)
        assert r.status_code == 200, r.text
        assert r.json()["text"] == "TEST_buy almond milk"

    def test_complete(self):
        r = requests.post(f"{API}/reminders/{TestReminders.rid}/complete", headers=H, timeout=10)
        assert r.status_code == 200, r.text

    def test_delete(self):
        r = requests.delete(f"{API}/reminders/{TestReminders.rid}", headers=H, timeout=10)
        assert r.status_code == 200


# ============================================================
# Dashboard
# ============================================================
class TestDashboard:
    def test_dashboard_fields(self):
        r = requests.get(f"{API}/dashboard", headers=H, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("streak_days", "reminders_open", "reminders_today", "reminders_overdue"):
            assert k in d, f"missing key {k}: {d.keys()}"
        # We've inserted at least 1 entry via capture above
        assert d["streak_days"] >= 1, f"streak_days={d['streak_days']}"


# ============================================================
# Twin retrieval (no archive dump)
# ============================================================
class TestTwinRetrieval:
    def test_twin_streams_with_retrieval(self):
        import httpx
        # Start convo
        r = requests.post(f"{API}/twin/start", headers=H, json={}, timeout=15)
        assert r.status_code == 200
        cid = r.json()["conversation_id"]

        full = ""
        done = False
        with httpx.stream(
            "POST", f"{API}/twin/message",
            headers={**H, "Content-Type": "application/json"},
            json={"conversation_id": cid, "message": "What did I say about fishing?"},
            timeout=90,
        ) as resp:
            assert resp.status_code == 200, resp.read().decode()
            buf = ""
            for chunk in resp.iter_text():
                buf += chunk
                while "\n\n" in buf:
                    evt, buf = buf.split("\n\n", 1)
                    if "event: done" in evt:
                        done = True
                        continue
                    for line in evt.split("\n"):
                        if line.startswith("data:"):
                            import json as _json
                            try:
                                full += _json.loads(line[5:].strip()).get("text", "")
                            except Exception:
                                pass
        assert done, "no done event"
        assert len(full) > 5, f"empty reply: {full!r}"


# ============================================================
# Companion poll delivers reminders
# ============================================================
class TestCompanionPoll:
    def test_due_reminder_delivered_once(self):
        # Create a reminder due NOW
        r = requests.post(f"{API}/reminders", headers=H, json={
            "text": "TEST_companion_due",
            "due_at": "2000-01-01T00:00:00+00:00",
        }, timeout=10)
        assert r.status_code == 200
        rid = r.json()["reminder_id"]

        dh = {"Authorization": f"Bearer {DEVICE_TOKEN}"}
        r1 = requests.get(f"{API}/companion/poll", headers=dh, timeout=10)
        assert r1.status_code == 200, r1.text
        cmds = r1.json().get("commands", [])
        say_cmds = [c for c in cmds if c.get("kind") == "say" and "Reminder:" in c.get("payload", {}).get("text", "")]
        assert any(rid in c.get("reminder_id", "") or "TEST_companion_due" in c["payload"]["text"]
                   for c in say_cmds), f"reminder not delivered: {cmds}"

        # Second poll should NOT re-deliver
        r2 = requests.get(f"{API}/companion/poll", headers=dh, timeout=10)
        cmds2 = r2.json().get("commands", [])
        say_cmds2 = [c for c in cmds2 if c.get("kind") == "say"
                     and "TEST_companion_due" in c.get("payload", {}).get("text", "")]
        assert not say_cmds2, f"reminder re-delivered: {cmds2}"

        # Cleanup
        requests.delete(f"{API}/reminders/{rid}", headers=H, timeout=10)


# ============================================================
# SEC-004 — Rate limiting (capture)
# ============================================================
class TestRateLimit:
    def test_capture_429(self):
        """Cap=30/min. Use a cheap endpoint (reminders) to confirm rate-limiter middleware semantics
        — but capture is what the request asks for. Parallelize so 35 reqs finish in <60s window."""
        import concurrent.futures as cf
        def fire(i):
            try:
                r = requests.post(f"{API}/capture", headers=H, json={"text": f"rlx_{i}"}, timeout=30)
                return r.status_code, r.headers.get("Retry-After")
            except Exception as e:
                return 0, str(e)
        with cf.ThreadPoolExecutor(max_workers=10) as ex:
            results = list(ex.map(fire, range(35)))
        codes = [c for c, _ in results]
        retry_afters = [ra for c, ra in results if c == 429]
        assert 429 in codes, f"never got 429 in {codes}"
        assert any(retry_afters), f"missing Retry-After header in 429 responses"


# ============================================================
# Regression smoke
# ============================================================
class TestRegression:
    def test_archive_list(self):
        r = requests.get(f"{API}/archive", headers=H, timeout=10)
        assert r.status_code == 200

    def test_archive_create_get_delete(self):
        r = requests.post(f"{API}/archive", headers=H, json={
            "type": "memory", "title": "TEST_reg", "content": "reg test", "tags": ["x"]
        }, timeout=10)
        assert r.status_code == 200, r.text
        eid = r.json()["entry_id"]
        r2 = requests.delete(f"{API}/archive/{eid}", headers=H, timeout=10)
        assert r2.status_code == 200

    def test_heirs_list(self):
        r = requests.get(f"{API}/heirs", headers=H, timeout=10)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_voice_clone_settings(self):
        r = requests.get(f"{API}/voice-clone/settings", headers=H, timeout=10)
        assert r.status_code == 200

    def test_photos_list(self):
        r = requests.get(f"{API}/photos", headers=H, timeout=10)
        assert r.status_code == 200
