"""Iteration-12 tests — Stripe checkout + fulfillment + auto-skill triggers.

Run with REACT_APP_BACKEND_URL in env. Seeds its own users + sessions directly
into MongoDB (test_database) so we don't depend on Emergent Google auth.
"""
import io
import os
import time
import uuid
import zipfile
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

mc = MongoClient(MONGO)
db = mc[DB_NAME]


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


# ----------------------- Fixtures -----------------------
@pytest.fixture(scope="session")
def user_a():
    uid = f"test-user-A-{int(time.time() * 1000)}"
    tok = f"tk_A_{int(time.time() * 1000)}"
    db.users.insert_one({
        "user_id": uid,
        "email": f"a.it12.{uid}@example.com",
        "name": "User A",
        "picture": "",
        "created_at": _iso(_now()),
        "setup_complete": True,
    })
    db.user_sessions.insert_one({
        "user_id": uid,
        "session_token": tok,
        "expires_at": _iso(_now() + timedelta(days=7)),
        "created_at": _iso(_now()),
    })
    yield {"user_id": uid, "token": tok}


@pytest.fixture(scope="session")
def user_b():
    uid = f"test-user-B-{int(time.time() * 1000)}"
    tok = f"tk_B_{int(time.time() * 1000)}"
    db.users.insert_one({
        "user_id": uid,
        "email": f"b.it12.{uid}@example.com",
        "name": "User B",
        "picture": "",
        "created_at": _iso(_now()),
        "setup_complete": True,
    })
    db.user_sessions.insert_one({
        "user_id": uid,
        "session_token": tok,
        "expires_at": _iso(_now() + timedelta(days=7)),
        "created_at": _iso(_now()),
    })
    yield {"user_id": uid, "token": tok}


def H(token):
    return {"Authorization": f"Bearer {token}"}


# ----------------------- Billing -----------------------
class TestBilling:
    def test_packages(self):
        r = requests.get(f"{BASE}/api/billing/packages", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert "packages" in data
        assert "lifetime" in data["packages"]
        pkg = data["packages"]["lifetime"]
        assert pkg["name"]
        assert pkg["price"] == 79.00
        assert pkg["currency"] == "usd"
        assert pkg["description"]

    def test_checkout_creates_session_and_txn(self):
        payload = {
            "package_id": "lifetime",
            "origin_url": "https://example.com",
            "email": f"TEST_buyer_{uuid.uuid4().hex[:8]}@example.com",
            "name": "Buyer One",
        }
        r = requests.post(f"{BASE}/api/billing/checkout", json=payload, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["url"].startswith("https://checkout.stripe.com/")
        assert data["session_id"].startswith("cs_")

        txn = db.payment_transactions.find_one({"session_id": data["session_id"]})
        assert txn is not None
        assert txn["status"] == "open"
        assert txn["provisioned"] is False
        assert txn["email"] == payload["email"]

    def test_checkout_invalid_package(self):
        r = requests.post(f"{BASE}/api/billing/checkout", json={
            "package_id": "nope",
            "origin_url": "https://example.com",
            "email": "x@example.com",
        }, timeout=10)
        assert r.status_code == 400

    def test_checkout_bad_email(self):
        r = requests.post(f"{BASE}/api/billing/checkout", json={
            "package_id": "lifetime",
            "origin_url": "https://example.com",
            "email": "not-an-email",
        }, timeout=10)
        assert r.status_code == 422

    def test_status_unpaid(self):
        # create a session
        payload = {
            "package_id": "lifetime",
            "origin_url": "https://example.com",
            "email": f"TEST_unpaid_{uuid.uuid4().hex[:8]}@example.com",
        }
        r = requests.post(f"{BASE}/api/billing/checkout", json=payload, timeout=20)
        sid = r.json()["session_id"]
        s = requests.get(f"{BASE}/api/billing/status/{sid}", timeout=15)
        assert s.status_code == 200
        d = s.json()
        assert d["paid"] is False
        assert d["payment_status"] in ("unpaid", "no_payment_required")
        assert d["status"] in ("open", "complete", "expired")


# ----------------------- Fulfillment (seeded paid txn) -----------------------
class TestFulfillment:
    def _seed_paid(self, email):
        """Seed a payment txn + a user + download_token + magic_link directly,
        bypassing real Stripe payment."""
        sid = f"cs_test_seeded_{uuid.uuid4().hex[:16]}"
        user_id = f"u_seed_{uuid.uuid4().hex[:10]}"
        device_token = "comp_" + uuid.uuid4().hex
        download_token = "dl_" + uuid.uuid4().hex + uuid.uuid4().hex
        magic_token = "ml_" + uuid.uuid4().hex + uuid.uuid4().hex
        db.users.insert_one({
            "user_id": user_id, "email": email, "name": "Seeded",
            "picture": "", "created_at": _iso(_now()), "setup_complete": False,
            "purchased_lifetime": True,
        })
        db.companion_devices.insert_one({
            "device_id": f"dev_{uuid.uuid4().hex[:12]}",
            "user_id": user_id, "name": "My PC",
            "device_token": device_token, "revoked": False,
            "created_at": _iso(_now()), "last_seen": None,
        })
        db.download_tokens.insert_one({
            "download_token": download_token, "user_id": user_id,
            "device_token": device_token, "uses": 0, "max_uses": 5,
            "expires_at": _iso(_now() + timedelta(days=14)),
            "created_at": _iso(_now()),
        })
        db.magic_links.insert_one({
            "magic_token": magic_token, "user_id": user_id,
            "consumed": False, "expires_at": _iso(_now() + timedelta(hours=24)),
            "created_at": _iso(_now()),
        })
        db.payment_transactions.insert_one({
            "session_id": sid, "package_id": "lifetime", "amount": 79.00,
            "currency": "usd", "email": email, "name": "Seeded",
            "status": "complete", "payment_status": "paid",
            "metadata": {}, "provisioned": True, "user_id": user_id,
            "download_url": f"/api/download/{download_token}",
            "login_url": f"/auth/magic/{magic_token}",
            "created_at": _iso(_now()), "updated_at": _iso(_now()),
        })
        return {
            "session_id": sid, "user_id": user_id, "email": email,
            "download_token": download_token, "magic_token": magic_token,
            "device_token": device_token,
        }

    def test_download_returns_personalized_zip(self):
        seed = self._seed_paid(f"TEST_dl_{uuid.uuid4().hex[:6]}@example.com")
        r = requests.get(f"{BASE}/api/download/{seed['download_token']}", timeout=30)
        assert r.status_code == 200, r.text
        assert r.headers.get("content-type", "").startswith("application/zip")
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        names = set(zf.namelist())
        expected = {
            "Double-click me - Install Heirloom.bat",
            "Update Heirloom.bat",
            "Read me first.txt",
        }
        assert expected.issubset(names), f"missing: {expected - names}"
        bat = zf.read("Double-click me - Install Heirloom.bat").decode("utf-8", errors="ignore")
        assert seed["device_token"] in bat, "device token not baked into installer"
        assert "public-script" in bat, "installer must fetch newest script from server"

    def test_download_invalid_token(self):
        r = requests.get(f"{BASE}/api/download/not-a-token", timeout=10)
        assert r.status_code == 404
        r2 = requests.get(f"{BASE}/api/download/dl_nonexistent", timeout=10)
        assert r2.status_code == 404

    def test_download_expired(self):
        seed = self._seed_paid(f"TEST_exp_{uuid.uuid4().hex[:6]}@example.com")
        db.download_tokens.update_one(
            {"download_token": seed["download_token"]},
            {"$set": {"expires_at": _iso(_now() - timedelta(hours=1))}},
        )
        r = requests.get(f"{BASE}/api/download/{seed['download_token']}", timeout=10)
        assert r.status_code == 410

    def test_download_exhausted_after_5_uses(self):
        seed = self._seed_paid(f"TEST_ex5_{uuid.uuid4().hex[:6]}@example.com")
        for _ in range(5):
            r = requests.get(f"{BASE}/api/download/{seed['download_token']}", timeout=30)
            assert r.status_code == 200
        r6 = requests.get(f"{BASE}/api/download/{seed['download_token']}", timeout=10)
        assert r6.status_code == 410

    def test_magic_link_consume_and_burn(self):
        seed = self._seed_paid(f"TEST_ml_{uuid.uuid4().hex[:6]}@example.com")
        r = requests.post(f"{BASE}/api/auth/magic/{seed['magic_token']}", timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "session_token" in d
        assert d["user"]["user_id"] == seed["user_id"]
        assert d["user"]["email"] == seed["email"]
        # cookie set
        assert "session_token" in r.cookies or any(
            "session_token" in (h.lower()) for h in r.headers.get("set-cookie", "").lower().split(";")
        ) or "session_token" in r.headers.get("set-cookie", "")
        # session persisted
        sess = db.user_sessions.find_one({"session_token": d["session_token"]})
        assert sess is not None
        # second call → 410
        r2 = requests.post(f"{BASE}/api/auth/magic/{seed['magic_token']}", timeout=10)
        assert r2.status_code == 410

    def test_magic_link_invalid_format(self):
        r = requests.post(f"{BASE}/api/auth/magic/garbage", timeout=10)
        assert r.status_code == 400

    def test_magic_link_unknown(self):
        r = requests.post(f"{BASE}/api/auth/magic/ml_doesnotexist", timeout=10)
        assert r.status_code == 404


# ----------------------- Skills (triggers field) -----------------------
class TestSkills:
    def test_create_skill_with_triggers(self, user_a):
        body = {
            "name": "TEST_Notify_webhook",
            "description": "auto",
            "webhook_url": "https://httpbin.org/post",
            "method": "POST",
            "headers": {},
            "body_template": '{"ok":true}',
            "triggers": ["ping me", "notify me"],
            "enabled": True,
        }
        r = requests.post(f"{BASE}/api/skills", json=body, headers=H(user_a["token"]), timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["triggers"] == ["ping me", "notify me"]
        assert "skill_id" in d

        # GET reflects triggers
        g = requests.get(f"{BASE}/api/skills", headers=H(user_a["token"]), timeout=10)
        assert g.status_code == 200
        match = next((s for s in g.json() if s["skill_id"] == d["skill_id"]), None)
        assert match and match["triggers"] == ["ping me", "notify me"]

        # PATCH updates triggers
        p = requests.patch(
            f"{BASE}/api/skills/{d['skill_id']}",
            json={"triggers": ["beep"]},
            headers=H(user_a["token"]),
            timeout=10,
        )
        assert p.status_code == 200
        assert p.json()["triggers"] == ["beep"]


# ----------------------- Twin auto-skill short-circuit -----------------------
class TestTwinAutoSkill:
    def _create_skill(self, token, triggers, name="TEST_AutoSkill", enabled=True, url="https://httpbin.org/post"):
        r = requests.post(f"{BASE}/api/skills", json={
            "name": name, "description": "", "webhook_url": url,
            "method": "POST", "headers": {}, "body_template": "{}",
            "triggers": triggers, "enabled": enabled,
        }, headers=H(token), timeout=10)
        assert r.status_code == 200, r.text
        return r.json()

    def _start_conv(self, token):
        r = requests.post(f"{BASE}/api/twin/start", json={}, headers=H(token), timeout=10)
        assert r.status_code == 200, r.text
        return r.json()["conversation_id"]

    def _send_twin(self, token, text, conv_id=None):
        """Hit /twin/message SSE and collect raw chunks until [DONE] or timeout."""
        if conv_id is None:
            conv_id = self._start_conv(token)
        t0 = time.time()
        r = requests.post(
            f"{BASE}/api/twin/message",
            json={"conversation_id": conv_id, "message": text},
            headers=H(token),
            stream=True,
            timeout=20,
        )
        chunks = []
        for line in r.iter_lines(decode_unicode=True):
            if line is None:
                continue
            chunks.append(line)
            if "[DONE]" in line or (time.time() - t0) > 15:
                break
        return time.time() - t0, "\n".join(chunks)

    def test_auto_skill_fires_short_circuit(self, user_a):
        skill = self._create_skill(user_a["token"], ["ping me", "notify me"], name="TEST_PingSkill")
        conv_id = self._start_conv(user_a["token"])
        elapsed, body = self._send_twin(user_a["token"], "hey twin, ping me please", conv_id=conv_id)
        assert elapsed < 8.0, f"expected fast short-circuit, took {elapsed}s"
        assert "event: action" in body or "\"kind\":" in body or "skill" in body.lower()
        # Should contain skill name (or at least an indication)
        # Check db.conversations has assistant message with action.kind='skill'
        time.sleep(0.5)
        conv = db.conversations.find_one({"conversation_id": conv_id})
        # find an assistant message with action.kind=skill
        found = False
        if conv:
            for m in (conv.get("messages") or [])[-6:]:
                if (m.get("action") or {}).get("kind") == "skill":
                    found = True
                    break
        assert found, "no assistant message with action.kind=skill found in last conversation"

    def test_case_insensitive_substring(self, user_a):
        # Reuse previous skill or create a fresh one with 'notify me'
        self._create_skill(user_a["token"], ["notify me"], name="TEST_NotifyMe2")
        elapsed, body = self._send_twin(user_a["token"], "Please Notify Me!")
        assert elapsed < 8.0
        assert "skill" in body.lower()

    def test_short_triggers_ignored(self, user_a):
        """Triggers <3 chars should NOT match — so this should fall through to LLM
        (we don't wait for LLM, just assert no skill action in the SSE)."""
        self._create_skill(user_a["token"], ["hi"], name="TEST_Hi_short")
        conv_id = self._start_conv(user_a["token"])
        # Quick check — only read first ~3s of stream
        t0 = time.time()
        r = requests.post(
            f"{BASE}/api/twin/message",
            json={"conversation_id": conv_id, "message": "hi there"},
            headers=H(user_a["token"]),
            stream=True,
            timeout=10,
        )
        early = []
        for line in r.iter_lines(decode_unicode=True):
            early.append(line or "")
            if (time.time() - t0) > 3:
                break
        r.close()
        joined = "\n".join(early)
        # Should NOT have skill action chip in first 3s (LLM is slower)
        assert "\"kind\": \"skill\"" not in joined and "\"kind\":\"skill\"" not in joined

    def test_disabled_skill_not_invoked(self, user_a):
        skill = self._create_skill(
            user_a["token"], ["zzz_disabled_trigger"], name="TEST_Disabled", enabled=False
        )
        conv_id = self._start_conv(user_a["token"])
        t0 = time.time()
        r = requests.post(
            f"{BASE}/api/twin/message",
            json={"conversation_id": conv_id, "message": "zzz_disabled_trigger now"},
            headers=H(user_a["token"]),
            stream=True,
            timeout=10,
        )
        out = []
        for line in r.iter_lines(decode_unicode=True):
            out.append(line or "")
            if (time.time() - t0) > 3:
                break
        r.close()
        joined = "\n".join(out)
        assert "\"kind\": \"skill\"" not in joined and "\"kind\":\"skill\"" not in joined

    def test_music_intent_wins_over_skill(self, user_a):
        # Trigger that overlaps with music verbiage
        self._create_skill(user_a["token"], ["play me"], name="TEST_PlaySkill")
        elapsed, body = self._send_twin(user_a["token"], "play me Pink Floyd")
        assert elapsed < 8.0
        # Music short-circuit emits a music chip not a skill chip
        assert "\"kind\": \"skill\"" not in body and "\"kind\":\"skill\"" not in body
        assert "music" in body.lower() or "provider" in body.lower() or "queue" in body.lower()

    def test_multi_user_isolation(self, user_a, user_b):
        # user A has 'ping me' from earlier test. send same text as user B → no skill
        conv_id = self._start_conv(user_b["token"])
        t0 = time.time()
        r = requests.post(
            f"{BASE}/api/twin/message",
            json={"conversation_id": conv_id, "message": "ping me please"},
            headers=H(user_b["token"]),
            stream=True,
            timeout=10,
        )
        out = []
        for line in r.iter_lines(decode_unicode=True):
            out.append(line or "")
            if (time.time() - t0) > 3:
                break
        r.close()
        joined = "\n".join(out)
        assert "\"kind\": \"skill\"" not in joined and "\"kind\":\"skill\"" not in joined
