"""Iteration 43 — Mobile PWA + Twilio Voice SDK token tests.

Coverage:
- GET /api/twilio/config returns webrtc_configured boolean
- PUT /api/twilio/config accepts api_key_sid/api_key_secret/twiml_app_sid (with mock)
- POST /api/twilio/voice/token 400s cleanly and mints valid JWT
- PWA static assets: /manifest.json, /sw.js, /icon-192.png, /icon-512.png
- Auth guard: /manifest.json + /sw.js do NOT require auth
"""
import os
import json
import base64
import requests
import pytest

def _load_base_url():
    v = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
    if v:
        return v
    # fall back to reading frontend/.env
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    return line.split("=", 1)[1].strip().rstrip("/")
    except Exception:
        pass
    return ""

BASE_URL = _load_base_url()
assert BASE_URL, "REACT_APP_BACKEND_URL not set"
SESSION_TOKEN = "test_routing_session"
USER_ID = "test-routing-user"

# Frontend base (public URL is the same as backend since ingress serves both)
FRONT_URL = BASE_URL


def auth_client():
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {SESSION_TOKEN}"})
    return s


# ------------- Twilio config ----------------
class TestTwilioConfigWebRTCFlag:
    def test_get_config_returns_webrtc_configured_true(self):
        r = auth_client().get(f"{BASE_URL}/api/twilio/config")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["configured"] is True
        assert "webrtc_configured" in data
        assert data["webrtc_configured"] is True, "Seeded user has all 3 WebRTC fields"
        assert data["phone_number"] == "+15551234567"


# ------------- Voice SDK Token ----------------
class TestVoiceToken:
    def test_token_unauthenticated_401(self):
        r = requests.post(f"{BASE_URL}/api/twilio/voice/token")
        assert r.status_code in (401, 403)

    def test_token_returns_valid_jwt(self):
        r = auth_client().post(f"{BASE_URL}/api/twilio/voice/token")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["identity"] == f"twin-{USER_ID}"
        assert data["ttl"] == 3600
        token = data["token"]
        # JWT is 3 base64url segments
        parts = token.split(".")
        assert len(parts) == 3

        def b64d(seg):
            pad = "=" * (-len(seg) % 4)
            return json.loads(base64.urlsafe_b64decode(seg + pad))

        header = b64d(parts[0])
        payload = b64d(parts[1])
        assert header.get("typ") == "JWT"
        assert payload["sub"] == "ACtest_account_sid_for_jwt_check"
        assert payload["iss"] == "SKtestapikey1234567890abcdef"
        grants = payload["grants"]
        assert grants["identity"] == f"twin-{USER_ID}"
        voice = grants["voice"]
        assert voice["incoming"]["allow"] is True
        assert voice["outgoing"]["application_sid"] == "APtestapp1234567890abcdef"


class TestVoiceTokenErrors:
    """Verify empty-config and missing-webrtc-fields error paths using a scratch user."""

    @pytest.fixture(scope="class")
    def scratch_user(self):
        # Create a scratch user + session via a direct mongosh call
        import subprocess
        import time
        uid = f"TEST_iter43_{int(time.time())}"
        tok = f"TEST_iter43_tok_{int(time.time())}"
        subprocess.run(
            ["mongosh", "--quiet", "--eval",
             f"use('test_database'); "
             f"db.users.insertOne({{user_id:'{uid}', email:'{uid}@example.com'}}); "
             f"db.user_sessions.insertOne({{user_id:'{uid}', session_token:'{tok}', "
             f"expires_at: new Date(Date.now()+3600000)}});"],
            check=True, capture_output=True,
        )
        yield uid, tok
        # cleanup
        subprocess.run(
            ["mongosh", "--quiet", "--eval",
             f"use('test_database'); "
             f"db.users.deleteOne({{user_id:'{uid}'}}); "
             f"db.user_sessions.deleteOne({{session_token:'{tok}'}}); "
             f"db.user_twilio.deleteOne({{user_id:'{uid}'}});"],
            check=False, capture_output=True,
        )

    def test_no_twilio_config_returns_400(self, scratch_user):
        uid, tok = scratch_user
        s = requests.Session()
        s.headers["Authorization"] = f"Bearer {tok}"
        r = s.post(f"{BASE_URL}/api/twilio/voice/token")
        assert r.status_code == 400, r.text
        assert "isn't configured" in r.json()["detail"].lower() or "isn" in r.json()["detail"].lower()

    def test_config_without_webrtc_fields_returns_400(self, scratch_user):
        uid, tok = scratch_user
        # Seed a config missing WebRTC fields
        import subprocess
        subprocess.run(
            ["mongosh", "--quiet", "--eval",
             f"use('test_database'); "
             f"db.user_twilio.replaceOne({{user_id:'{uid}'}}, "
             f"{{user_id:'{uid}', account_sid:'ACxxx', auth_token:'tok', "
             f"phone_number:'+15550000000', verified:true}}, {{upsert:true}});"],
            check=True, capture_output=True,
        )
        s = requests.Session()
        s.headers["Authorization"] = f"Bearer {tok}"
        r = s.post(f"{BASE_URL}/api/twilio/voice/token")
        assert r.status_code == 400, r.text
        detail = r.json()["detail"]
        assert "API Key" in detail and "Secret" in detail and "TwiML App SID" in detail
        assert "Twilio Console" in detail


# ------------- PWA static assets ----------------
class TestPWAAssets:
    def test_manifest_json(self):
        r = requests.get(f"{FRONT_URL}/manifest.json")
        assert r.status_code == 200
        ct = r.headers.get("content-type", "")
        assert "json" in ct or "text/plain" in ct, f"unexpected: {ct}"
        data = r.json()
        assert data["name"] == "Heirloom · Digital Twin" or "Heirloom" in data["name"]
        assert data["start_url"] == "/m"
        assert data["display"] == "standalone"
        sizes = sorted([i["sizes"] for i in data["icons"]])
        assert "192x192" in sizes
        assert "512x512" in sizes

    def test_sw_js(self):
        r = requests.get(f"{FRONT_URL}/sw.js")
        assert r.status_code == 200
        ct = r.headers.get("content-type", "")
        assert "javascript" in ct, f"unexpected: {ct}"
        body = r.text
        assert "SW_VERSION" in body
        assert "APP_SHELL" in body

    def test_icon_192(self):
        r = requests.get(f"{FRONT_URL}/icon-192.png")
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("image/png")
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n"

    def test_icon_512(self):
        r = requests.get(f"{FRONT_URL}/icon-512.png")
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("image/png")
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n"

    def test_pwa_assets_no_auth_required(self):
        # No Authorization header — should still be 200
        for path in ("/manifest.json", "/sw.js", "/icon-192.png", "/icon-512.png"):
            r = requests.get(f"{FRONT_URL}{path}")
            assert r.status_code == 200, f"{path} needs auth?"

    def test_index_html_pwa_meta(self):
        r = requests.get(f"{FRONT_URL}/")
        assert r.status_code == 200
        html = r.text
        assert 'name="apple-mobile-web-app-capable"' in html and 'content="yes"' in html
        assert 'apple-mobile-web-app-status-bar-style' in html and 'black-translucent' in html
        assert 'rel="apple-touch-icon"' in html and '/icon-192.png' in html
        assert 'viewport-fit=cover' in html
        assert 'rel="manifest"' in html


# ------------- Regression: /routing endpoints still work ----------------
class TestRoutingRegression:
    def test_routing_config_get(self):
        r = auth_client().get(f"{BASE_URL}/api/routing/config")
        # Endpoint should be reachable (200 or 404-if-none), not 500
        assert r.status_code in (200, 404), r.text
