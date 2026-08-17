"""Studio mixer + automated model provision."""
from __future__ import annotations

import os
import secrets
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent))

from studio_defaults import clamp_audio, clamp_model_map, clamp_compute, default_model_map
from studio_setup import clamp_setup, inbox_for_email, vendor_handoff
from studio_coach_vision import (
    next_step_for_scene,
    observe_result,
    parse_scene_payload,
    sanitize_hint,
)

BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or os.environ.get("PUBLIC_BACKEND_URL")
    or ""
).rstrip("/")
API = f"{BASE_URL}/api" if BASE_URL else ""

_MONGO = MongoClient(os.environ.get("MONGO_URL"))
_DB = _MONGO[os.environ.get("DB_NAME")]
_CREATED = []


def _mk(prefix: str = "u_studio"):
    rand = uuid.uuid4().hex[:10]
    user_id = f"{prefix}_{rand}"
    session = f"sess_studio_{secrets.token_urlsafe(16)}"
    now = datetime.now(timezone.utc)
    _DB.users.insert_one(
        {
            "user_id": user_id,
            "email": f"{user_id}@example.com",
            "name": "Studio Tester",
            "purchased_lifetime": True,
            "account_status": "active",
            "created_at": now.isoformat(),
        }
    )
    _DB.user_sessions.insert_one(
        {
            "user_id": user_id,
            "session_token": session,
            "expires_at": now + timedelta(days=7),
            "created_at": now.isoformat(),
        }
    )
    _CREATED.append(user_id)
    return user_id, session


@pytest.fixture
def studio_user():
    user_id, token = _mk()
    yield user_id, token
    _DB.users.delete_many({"user_id": user_id})
    _DB.user_sessions.delete_many({"user_id": user_id})
    _DB.companion_devices.delete_many({"user_id": user_id})
    _DB.companion_commands.delete_many({"user_id": user_id})
    _DB.pairing_codes.delete_many({"user_id": user_id})


def test_clamp_audio_bounds():
    out = clamp_audio({"output_volume": 999, "input_gain": -4, "sample_rate": 123, "noise_gate_db": 12})
    assert out["output_volume"] == 100
    assert out["input_gain"] == 0
    assert out["sample_rate"] == 48000
    assert out["noise_gate_db"] == 0
    assert out["input_device_id"] == "default"


def test_clamp_model_map_rejects_unknown():
    out = clamp_model_map({"stt": "local_whisper", "twin": "nope", "zzz": "auto"})
    assert out["stt"] == "local_whisper"
    assert out["twin"] == default_model_map()["twin"]
    assert "zzz" not in out


def test_clamp_compute_modes():
    out = clamp_compute({"mode": "network", "device_id": "dev_abc"})
    assert out["mode"] == "network"
    assert out["device_id"] == "dev_abc"
    server = clamp_compute(
        {
            "mode": "server",
            "remote": {"label": "Lab", "ollama_url": "http://10.0.0.5:11434"},
        }
    )
    assert server["mode"] == "server"
    assert server["device_id"] is None
    assert server["remote"]["ollama_url"] == "http://10.0.0.5:11434"
    bad = clamp_compute({"remote": {"ollama_url": "ftp://nope"}})
    assert bad["remote"]["ollama_url"].startswith("http://127.0.0.1")


def test_clamp_setup_space_and_email():
    out = clamp_setup({"space_profile": "max", "vendor_email": "YOU@Example.COM", "phone_features": ["twin", "live_listen"]})
    assert out["space_profile"] == "max"
    assert out["vendor_email"] == "you@example.com"
    assert "live_listen" not in out["phone_features"]
    assert "twin" in out["phone_features"]
    junk = clamp_setup({"space_profile": "huge", "vendor_email": "not-an-email"})
    assert junk["space_profile"] == "full"
    assert junk["vendor_email"] == ""


@pytest.mark.skipif(not BASE_URL, reason="backend URL not configured")
def test_studio_compute_roundtrip(studio_user):
    import requests

    _uid, token = studio_user
    h = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{API}/studio/compute", headers=h, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["settings"]["mode"] == "local"

    r = requests.put(
        f"{API}/studio/compute",
        headers=h,
        json={
            "mode": "server",
            "remote": {"label": "Test box", "ollama_url": "http://127.0.0.1:11434"},
        },
        timeout=15,
    )
    assert r.status_code == 200, r.text
    assert r.json()["settings"]["mode"] == "server"

    r = requests.post(f"{API}/studio/compute/test-ollama", headers=h, timeout=15)
    assert r.status_code == 200, r.text
    assert "ok" in r.json()


@pytest.mark.skipif(not BASE_URL, reason="backend URL not configured")
def test_studio_audio_roundtrip(studio_user):
    import requests

    _uid, token = studio_user
    h = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{API}/studio/audio", headers=h, timeout=15)
    assert r.status_code == 200, r.text
    settings = r.json()["settings"]
    assert settings["output_volume"] == 80
    r = requests.put(
        f"{API}/studio/audio",
        headers=h,
        json={
            "output_volume": 42,
            "input_gain": 130,
            "live_listen": True,
            "sample_rate": 44100,
            "input_device_id": "mic-1",
            "output_device_id": "spk-1",
        },
        timeout=15,
    )
    assert r.status_code == 200, r.text
    saved = r.json()["settings"]
    assert saved["output_volume"] == 42
    assert saved["input_gain"] == 130
    assert saved["live_listen"] is True
    assert saved["sample_rate"] == 44100
    assert saved["input_device_id"] == "mic-1"


@pytest.mark.skipif(not BASE_URL, reason="backend URL not configured")
def test_studio_models_catalog_and_provision(studio_user):
    import requests

    user_id, token = studio_user
    h = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{API}/studio/models", headers=h, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {f["id"] for f in body["features"]}
    assert {"stt", "tts", "twin", "vision", "avatar"} <= ids
    assert body["companion"]["connected"] is False
    assert "status" in body["features"][0]
    assert "effective" in body

    r = requests.patch(f"{API}/studio/models/stt", headers=h, json={"backend": "local_whisper"}, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["backend"] == "local_whisper"
    r = requests.get(f"{API}/studio/models", headers=h, timeout=15)
    assert r.json()["map"]["stt"] == "local_whisper"
    assert r.json()["map"]["twin"] == default_model_map()["twin"]

    r = requests.post(f"{API}/studio/models/tts/test", headers=h, timeout=15)
    assert r.status_code == 200, r.text
    assert "ok" in r.json()

    r = requests.post(f"{API}/studio/models/provision", headers=h, json={}, timeout=15)
    assert r.status_code == 409, r.text

    device_token = "comp_studio_" + secrets.token_urlsafe(12)
    _DB.companion_devices.insert_one(
        {
            "device_id": f"dev_{uuid.uuid4().hex[:8]}",
            "user_id": user_id,
            "name": "5090 box",
            "device_token": device_token,
            "revoked": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_seen": datetime.now(timezone.utc).isoformat(),
        }
    )
    r = requests.post(f"{API}/studio/models/provision", headers=h, json={"features": ["stt", "twin"]}, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["queued"] is True
    cmd = _DB.companion_commands.find_one({"cmd_id": r.json()["cmd_id"]})
    assert cmd["kind"] == "provision_models"
    assert "stt" in cmd["payload"]["features"]

    dh = {"Authorization": f"Bearer {device_token}"}
    r = requests.post(
        f"{API}/companion/runtime",
        headers=dh,
        json={
            "gpu": {"ready": True, "detail": "RTX 5090"},
            "whisper": {"ready": True, "detail": "faster-whisper"},
            "detail": "RTX 5090 · Whisper ready",
        },
        timeout=15,
    )
    assert r.status_code == 200, r.text
    r = requests.get(f"{API}/studio/models", headers=h, timeout=15)
    assert r.json()["companion"]["connected"] is True
    assert r.json()["companion"]["gpu"]["ready"] is True

    r = requests.get(f"{API}/companion/poll", headers=dh, timeout=15)
    assert r.status_code == 200, r.text
    poll = r.json()
    assert "audio_settings" in poll
    assert "model_map" in poll
    kinds = {c["kind"] for c in poll.get("commands") or []}
    assert "provision_models" in kinds


@pytest.mark.skipif(not BASE_URL, reason="backend URL not configured")
def test_device_token_can_put_audio(studio_user):
    import requests

    user_id, _token = studio_user
    device_token = "comp_studio_" + secrets.token_urlsafe(12)
    _DB.companion_devices.insert_one(
        {
            "device_id": f"dev_{uuid.uuid4().hex[:8]}",
            "user_id": user_id,
            "name": "PC",
            "device_token": device_token,
            "revoked": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    dh = {"Authorization": f"Bearer {device_token}"}
    r = requests.put(f"{API}/studio/audio", headers=dh, json={"output_volume": 17}, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["settings"]["output_volume"] == 17


def test_vendor_handoff_copies_email_into_official_url():
    assert vendor_handoff("nope") is None
    h = vendor_handoff("elevenlabs", "Fam+test@Example.COM")
    assert h["email"] == "fam+test@example.com"
    assert h["signup_url"].startswith("https://elevenlabs.io/app/sign-up")
    assert "email=fam%2Btest%40example.com" in h["signup_url"]
    assert h["dashboard_url"].endswith("/api-keys")
    assert h["save_path"] == "/voice-clone/api-key"
    assert h["inbox"]["label"] == "your email inbox"
    assert h["inbox"]["url"] is None
    ids = [s["id"] for s in h["coach_steps"]]
    assert ids == ["create_account", "verify_email", "find_key", "paste_key"]
    assert h["coach_steps"][0]["auto_open"] is True
    assert h["coach_steps"][0]["open_url"].startswith("https://elevenlabs.io/")
    assert h["coach_steps"][-1]["kind"] == "paste"
    assert any("robot" in line.lower() for line in h["you_do"])
    assert "clipboard" in " ".join(h["we_do"]).lower()
    bare = vendor_handoff("did", "")
    assert bare["signup_url"] == "https://studio.d-id.com/"
    assert "email=" not in bare["signup_url"]


def test_inbox_for_known_email_providers():
    gmail = inbox_for_email("you@Gmail.COM")
    assert gmail["label"] == "Gmail"
    assert "mail.google.com" in gmail["url"]
    guided = vendor_handoff("elevenlabs", "you@gmail.com")
    assert guided["inbox"]["url"].startswith("https://mail.google.com")
    assert guided["coach_steps"][1]["open_url"] == guided["inbox"]["url"]
    assert guided["coach_steps"][1]["auto_open"] is True
    unknown = inbox_for_email("owner@family-archive.test")
    assert unknown["url"] is None
    assert unknown["label"] == "your email inbox"


def test_coach_observe_advances_forward_only():
    assert next_step_for_scene("create_account", "email_inbox") == "verify_email"
    assert next_step_for_scene("create_account", "api_keys_page") == "find_key"
    assert next_step_for_scene("create_account", "captcha") is None
    assert next_step_for_scene("verify_email", "api_keys_page") == "find_key"
    assert next_step_for_scene("find_key", "api_keys_page") == "paste_key"
    assert next_step_for_scene("find_key", "api_key_visible") == "paste_key"
    assert next_step_for_scene("paste_key", "api_key_visible") is None
    assert next_step_for_scene("paste_key", "signup_form") is None
    out = observe_result(current_step="create_account", scene="email_inbox")
    assert out["advance_to_step"] == "verify_email"
    assert out["scene"] == "email_inbox"
    parsed = parse_scene_payload('```json\n{"scene":"captcha","hint":"click the box"}\n```')
    assert parsed["scene"] == "captcha"
    assert "sk_live_abcdefghij" not in sanitize_hint("here is sk_live_abcdefghij")
    assert "paste" in sanitize_hint("here is sk_live_abcdefghij").lower()


@pytest.mark.skipif(not BASE_URL, reason="backend URL not configured")
def test_first_run_and_phone_pair(studio_user):
    import requests

    user_id, token = studio_user
    h = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{API}/studio/first-run", headers=h, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["settings"]["complete"] is False
    assert body["catalog"]["full_power_gb"]["min"] == 20
    assert "vendor_signup_policy" in body["catalog"]
    assert "watch" in body["catalog"]["vendor_signup_policy"].lower()
    assert "handoffs" in body
    assert body["handoffs"]["elevenlabs"]["signup_url"].startswith("https://elevenlabs.io/")

    r = requests.put(
        f"{API}/studio/first-run",
        headers=h,
        json={"space_profile": "lite", "vendor_email": "setup@example.com", "prefer_local": True},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    assert r.json()["settings"]["space_profile"] == "lite"
    assert r.json()["settings"]["vendor_email"] == "setup@example.com"

    r = requests.get(f"{API}/studio/first-run/handoff/elevenlabs", headers=h, timeout=15)
    assert r.status_code == 200, r.text
    handoff = r.json()
    assert "email=setup%40example.com" in handoff["signup_url"]
    assert handoff["inbox"]["label"] == "your email inbox"
    assert len(handoff["coach_steps"]) == 4
    r = requests.get(f"{API}/studio/first-run/handoff/nope", headers=h, timeout=15)
    assert r.status_code == 404

    r = requests.post(
        f"{API}/studio/first-run/coach/observe",
        headers=h,
        json={"service_id": "elevenlabs", "current_step": "create_account"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    observed = r.json()
    assert observed["scene"] == "unknown"
    assert observed["watching"] is False
    assert observed["advance_to_step"] is None
    assert "sk_" not in (observed.get("hint") or "")

    r = requests.post(f"{API}/studio/first-run/complete", headers=h, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["settings"]["complete"] is True
    assert r.json()["provision"]["queued"] is False

    r = requests.post(f"{API}/studio/first-run/pair", headers=h, timeout=15)
    assert r.status_code == 200, r.text
    code = r.json()["code"]
    assert len(code) == 6
    r = requests.post(
        f"{API}/studio/first-run/pair/claim",
        headers=h,
        json={"code": code, "name": "Pixel test", "phone_features": ["twin", "reminders"]},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert r.json()["name"] == "Pixel test"
    phone = _DB.companion_devices.find_one({"user_id": user_id, "kind": "phone"})
    assert phone is not None
    assert phone["phone_features"] == ["twin", "reminders"]
