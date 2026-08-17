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
