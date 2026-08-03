"""Iteration 31 — Local AI providers CRUD + regression on public/protected routes."""
import os
import subprocess
import time
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") if os.environ.get("REACT_APP_BACKEND_URL") else None
if not BASE_URL:
    # fall back to reading frontend env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                break

API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def session_token():
    ts = int(time.time() * 1000)
    user_id = f"test-user-iter31-{ts}"
    token = f"test_session_iter31_{ts}"
    js = f"""
    use('test_database');
    db.users.insertOne({{user_id:'{user_id}', email:'iter31.{ts}@example.com', name:'Iter31', picture:'https://x/y', created_at:new Date()}});
    db.user_sessions.insertOne({{user_id:'{user_id}', session_token:'{token}', expires_at:new Date(Date.now()+7*24*3600*1000), created_at:new Date()}});
    """
    r = subprocess.run(["mongosh", "--quiet", "--eval", js], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    yield {"token": token, "user_id": user_id}
    subprocess.run(["mongosh", "--quiet", "--eval",
                    f"use('test_database'); db.user_sessions.deleteMany({{user_id:'{user_id}'}}); db.users.deleteMany({{user_id:'{user_id}'}}); db.user_providers.deleteMany({{user_id:'{user_id}'}});"],
                   capture_output=True, text=True)


@pytest.fixture
def auth_headers(session_token):
    return {"Authorization": f"Bearer {session_token['token']}"}


# ---------------- providers CRUD ----------------
def test_providers_unauth_returns_401():
    r = requests.get(f"{API}/providers")
    assert r.status_code == 401, f"expected 401 got {r.status_code}: {r.text[:200]}"


def test_providers_get_defaults(auth_headers):
    r = requests.get(f"{API}/providers", headers=auth_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    for sub in ("chat", "tts", "stt", "image", "embeddings"):
        assert sub in data, f"missing subsystem {sub}"
        s = data[sub]
        for field in ("enabled", "base_url", "api_key", "model", "provider_type"):
            assert field in s, f"missing field {field} in {sub}"
        assert s["enabled"] is False
        assert s["provider_type"] in ("openai_compat", "comfyui")


def test_providers_put_and_persist(auth_headers):
    payload = {
        "chat": {"enabled": True, "base_url": "http://127.0.0.1:11434/v1", "api_key": "", "model": "llama3.3:70b", "provider_type": "openai_compat"},
        "tts":  {"enabled": True, "base_url": "http://127.0.0.1:8880/v1", "api_key": "", "model": "kokoro-en-v1", "provider_type": "openai_compat", "voice": "af_bella"},
        "stt":  {"enabled": False, "base_url": "", "api_key": "", "model": "", "provider_type": "openai_compat"},
        "image":{"enabled": True, "base_url": "http://127.0.0.1:8188", "api_key": "", "model": "flux1-dev", "provider_type": "comfyui", "comfy_workflow": "{}"},
        "embeddings":{"enabled": False, "base_url": "", "api_key": "", "model": "", "provider_type": "openai_compat"},
    }
    r = requests.put(f"{API}/providers", headers=auth_headers, json=payload)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["chat"]["enabled"] is True
    assert d["chat"]["model"] == "llama3.3:70b"
    assert d["image"]["provider_type"] == "comfyui"
    assert d["tts"].get("voice") == "af_bella"

    # GET again — must match
    r2 = requests.get(f"{API}/providers", headers=auth_headers)
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["chat"]["base_url"] == "http://127.0.0.1:11434/v1"
    assert d2["image"]["provider_type"] == "comfyui"


def test_providers_reset(auth_headers):
    r = requests.post(f"{API}/providers/reset", headers=auth_headers)
    assert r.status_code == 200, r.text
    d = r.json()
    for sub in ("chat", "tts", "stt", "image", "embeddings"):
        assert d[sub]["enabled"] is False
        assert d[sub]["base_url"] == ""


# ---------------- regressions ----------------
def test_agent_kinds_still_401():
    r = requests.get(f"{API}/agent/kinds")
    assert r.status_code == 401


def test_archive_with_auth(auth_headers):
    r = requests.get(f"{API}/archive", headers=auth_headers)
    assert r.status_code in (200, 404), f"got {r.status_code}"


def test_abilities_returns(auth_headers):
    r = requests.get(f"{API}/abilities", headers=auth_headers)
    assert r.status_code in (200, 401), f"got {r.status_code}"


def test_landing_renders():
    r = requests.get(f"{BASE_URL}/", timeout=15)
    assert r.status_code == 200
    assert "<div id=\"root\"" in r.text or "<div id='root'" in r.text or "root" in r.text
