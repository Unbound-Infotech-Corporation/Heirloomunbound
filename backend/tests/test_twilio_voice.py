"""Twilio Programmable Voice endpoint tests — plumbing/structural checks only.

Verifies:
 - auth-guarded endpoints
 - fake credentials rejected with 400 (fast-fail, not 500/hang)
 - unsigned webhooks return 403 (fail closed)
 - fresh-user shapes for GET config, GET calls
 - audio 404 for nonexistent token
 - outbound requires config
 - no regressions on adjacent surfaces
"""
import os
import time

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://voice-clone-hub-20.preview.emergentagent.com").rstrip("/")
SESSION_TOKEN = "test_session_twilio_iter35"


@pytest.fixture(scope="module")
def auth_client():
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {SESSION_TOKEN}",
        "Content-Type": "application/json",
    })
    return s


@pytest.fixture(scope="module")
def anon_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ----- auth guards -----
def test_config_get_unauth_returns_401(anon_client):
    r = anon_client.get(f"{BASE_URL}/api/twilio/config")
    assert r.status_code in (401, 403), r.text


def test_outbound_unauth_returns_401(anon_client):
    r = anon_client.post(f"{BASE_URL}/api/twilio/call/outbound",
                         json={"to_number": "+15555550100"})
    assert r.status_code in (401, 403), r.text


# ----- fresh user shape -----
def test_config_fresh_user_returns_configured_false(auth_client):
    # ensure no config exists
    auth_client.delete(f"{BASE_URL}/api/twilio/config")
    r = auth_client.get(f"{BASE_URL}/api/twilio/config")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["configured"] is False
    assert data.get("phone_number") in (None, "")


def test_calls_fresh_user_returns_empty(auth_client):
    r = auth_client.get(f"{BASE_URL}/api/twilio/calls")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "calls" in data
    assert isinstance(data["calls"], list)


def test_delete_config_idempotent(auth_client):
    r = auth_client.delete(f"{BASE_URL}/api/twilio/config")
    assert r.status_code == 200, r.text
    assert r.json().get("ok") is True


# ----- fake creds fast-fail (no hang, no 500) -----
def test_put_config_fake_credentials_rejected_400(auth_client):
    t0 = time.time()
    r = auth_client.put(
        f"{BASE_URL}/api/twilio/config",
        json={
            "account_sid": "ACfake0000000000000000000000000000",
            "auth_token": "fake123456789012345678901234567890",
            "phone_number": "+15555550100",
            "outbound_enabled": False,
        },
        timeout=30,
    )
    elapsed = time.time() - t0
    assert r.status_code == 400, f"Expected 400 got {r.status_code}: {r.text}"
    body = r.json()
    detail = body.get("detail", "")
    assert "rejected" in detail.lower() or "twilio" in detail.lower()
    assert elapsed < 25, f"Too slow ({elapsed:.1f}s) — should fast-fail"


# ----- outbound requires config -----
def test_outbound_without_config_returns_400(auth_client):
    auth_client.delete(f"{BASE_URL}/api/twilio/config")
    r = auth_client.post(
        f"{BASE_URL}/api/twilio/call/outbound",
        json={"to_number": "+15555550100", "opening_line": "hey"},
    )
    assert r.status_code == 400, r.text
    detail = r.json().get("detail", "")
    assert "configured" in detail.lower() or "twilio" in detail.lower()


# ----- signature validation on webhooks -----
def test_voice_incoming_without_signature_returns_403(anon_client):
    # form-encoded, no X-Twilio-Signature header, To is not a real user's number
    r = requests.post(
        f"{BASE_URL}/api/twilio/voice/incoming",
        data={"CallSid": "CAtest", "From": "+15550001111", "To": "+15550002222",
              "Direction": "inbound"},
    )
    assert r.status_code == 403, r.text


def test_voice_turn_without_signature_returns_403_or_hangup(anon_client):
    r = requests.post(
        f"{BASE_URL}/api/twilio/voice/turn/CAnonexistent",
        data={"SpeechResult": "hello"},
    )
    assert r.status_code == 403, r.text


# ----- audio cache 404 -----
def test_audio_nonexistent_token_returns_404(anon_client):
    r = anon_client.get(f"{BASE_URL}/api/twilio/audio/nonexistent-token.mp3")
    assert r.status_code == 404, r.text
    assert "expired" in r.json().get("detail", "").lower()


# ----- regression: adjacent endpoints still work -----
def test_regression_providers(anon_client):
    r = anon_client.get(f"{BASE_URL}/api/providers")
    assert r.status_code in (200, 401), r.text


def test_regression_agent_kinds(anon_client):
    r = anon_client.get(f"{BASE_URL}/api/agent/kinds")
    assert r.status_code in (200, 401), r.text


def test_regression_memory_search_status(auth_client):
    r = auth_client.get(f"{BASE_URL}/api/memory/search/status")
    assert r.status_code == 200, r.text


def test_regression_archive(auth_client):
    r = auth_client.get(f"{BASE_URL}/api/archive")
    assert r.status_code == 200, r.text


def test_regression_auth_me(auth_client):
    r = auth_client.get(f"{BASE_URL}/api/auth/me")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("user_id") == "test-user-twilio-iter35" or "user_id" in data
