"""Twin Box client: pause auth, vision fences, owner password, CORS, health."""
from __future__ import annotations

import os
import re
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "heirloom_box_unit")

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from box_cors import origin_regex
from box_desktop import client_chat_mode, resolve_desktop_user
from box_health import health_payload
from box_owner import (
    OWNER_NOT_CONFIGURED,
    owner_configured,
    password_path,
    set_owner_password,
    verify_owner_password,
)
from box_pause import read_pause
from deps import get_current_user
from observer_models import parse_vision_reply
from routers.observer import router


def _client():
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app), app


def test_box_client_chat_stays_twin():
    assert client_chat_mode("assistant", "box-client") == "twin"
    assert client_chat_mode("owner", "box-client") == "twin"
    assert client_chat_mode("twin", "box-client") == "twin"
    assert client_chat_mode("assistant", "dev_pc") == "assistant"


def test_desktop_auth_rejects_a_missing_token():
    app = FastAPI()

    @app.get("/desktop/me")
    async def desktop_me(ctx: dict = Depends(resolve_desktop_user)):
        return ctx

    response = TestClient(app).get("/desktop/me")
    assert response.status_code == 401


def test_pause_rejects_a_missing_token():
    client, _app = _client()
    response = client.post("/api/observer/pause")
    assert response.status_code == 401


def test_pause_hides_from_an_heir():
    client, app = _client()
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "heir", "audience": "heir"}
    try:
        response = client.post("/api/observer/pause")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_pause_and_resume_for_the_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("HEIRLOOM_OBSERVER", "1")
    monkeypatch.setenv("HEIRLOOM_OBSERVER_DIR", str(tmp_path / "observer"))
    monkeypatch.setenv("HEIRLOOM_PRESENCE_DIR", str(tmp_path / "presence"))
    monkeypatch.setenv("HEIRLOOM_PAUSE_FILE", str(tmp_path / "pause.json"))
    monkeypatch.setenv("HEIRLOOM_DATA_ROOT", str(tmp_path))
    client, app = _client()
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "owner", "audience": "owner"}
    try:
        paused = client.post("/api/observer/pause")
        assert paused.status_code == 200
        assert paused.json()["paused"] is True
        resumed = client.post("/api/observer/resume")
        assert resumed.status_code == 200
        assert resumed.json()["paused"] is False
    finally:
        app.dependency_overrides.clear()


def test_pause_file_permission_is_not_paused(tmp_path, monkeypatch):
    target = tmp_path / "pause.json"
    target.write_text('{"paused": true, "reason": "web"}\n', encoding="utf-8")
    real = Path.is_file

    def denied(self):
        if self == target:
            raise PermissionError("denied")
        return real(self)

    monkeypatch.setattr(Path, "is_file", denied)
    assert read_pause(target) == {"paused": False, "reason": ""}


def test_vision_reply_strips_json_fences():
    wrapped = '```json\n{"summary": "kitchen", "people": []}\n```'
    parsed = parse_vision_reply(wrapped)
    assert parsed == {"summary": "kitchen", "people": []}
    assert parse_vision_reply("") is None
    assert parse_vision_reply("not an object") == {"summary": "not an object"}


def test_owner_password_roundtrip(tmp_path):
    path = tmp_path / "owner.pass"
    set_owner_password("ada@example.com", "correct horse", path)
    assert verify_owner_password("Ada@example.com", "correct horse", path)
    assert not verify_owner_password("ada@example.com", "wrong horse", path)
    text = path.read_text(encoding="utf-8")
    assert "correct horse" not in text
    assert "hash=" in text
    assert owner_configured(path)
    assert not owner_configured(tmp_path / "missing.pass")


def test_password_path_is_the_owner_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("HEIRLOOM_OWNER_PASSWORD_FILE", raising=False)
    monkeypatch.setenv("HEIRLOOM_DATA_ROOT", str(tmp_path))
    assert password_path() == tmp_path / "owner" / "owner.pass"
    custom = tmp_path / "custom.pass"
    monkeypatch.setenv("HEIRLOOM_OWNER_PASSWORD_FILE", str(custom))
    assert password_path() == custom


def test_set_owner_updates_the_existing_file_in_place(tmp_path):
    path = tmp_path / "owner.pass"
    path.write_text("placeholder\n", encoding="utf-8")
    inode = path.stat().st_ino
    set_owner_password("ada@example.com", "correct horse", path)
    assert path.stat().st_ino == inode
    assert path.is_file()
    assert verify_owner_password("ada@example.com", "correct horse", path)


def test_set_owner_refuses_a_directory(tmp_path):
    path = tmp_path / "owner.pass"
    path.mkdir()
    try:
        set_owner_password("ada@example.com", "correct horse", path)
    except OSError as exc:
        assert "heirloom-box set-owner" in str(exc)
    else:
        raise AssertionError("a directory password path must fail")


def test_box_login_503_names_set_owner(monkeypatch, tmp_path):
    monkeypatch.setenv("HEIRLOOM_BOX", "1")
    monkeypatch.setenv("HEIRLOOM_OWNER_PASSWORD_FILE", str(tmp_path / "owner" / "owner.pass"))
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.auth import router as auth_router

    app = FastAPI()
    app.include_router(auth_router, prefix="/api")
    response = TestClient(app).post(
        "/api/auth/box-login",
        json={"email": "ada@example.com", "password": "correct horse"},
    )
    assert response.status_code == 503
    assert "heirloom-box set-owner" in response.json()["detail"]
    assert response.json()["detail"] == OWNER_NOT_CONFIGURED

    empty = tmp_path / "owner" / "owner.pass"
    empty.parent.mkdir(parents=True)
    empty.write_text("", encoding="utf-8")
    again = TestClient(app).post(
        "/api/auth/box-login",
        json={"email": "ada@example.com", "password": "correct horse"},
    )
    assert again.status_code == 503
    assert "heirloom-box set-owner" in again.json()["detail"]


def test_cors_stays_closed_until_box_mode():
    cloud = origin_regex(box=False)
    assert re.fullmatch(cloud, "https://preview.emergentagent.com")
    assert re.fullmatch(cloud, "http://localhost:3000")
    assert not re.fullmatch(cloud, "https://evil.example.com")
    assert not re.fullmatch(cloud, "https://192.168.0.111")
    lan = origin_regex(box=True)
    assert re.fullmatch(lan, "https://192.168.0.111")
    assert re.fullmatch(lan, "https://10.1.2.3")
    assert not re.fullmatch(lan, "http://192.168.0.111")
    assert not re.fullmatch(lan, "https://evil.example.com")


def test_health_includes_compute_when_the_box_names_it(monkeypatch):
    monkeypatch.setenv("HEIRLOOM_GPU_NAME", "NVIDIA GeForce RTX 3090")
    monkeypatch.setenv("OLLAMA_TWIN_MODEL", "llama3.1")
    payload = health_payload()
    assert payload["compute"]["gpu"] == "NVIDIA GeForce RTX 3090"
    assert payload["compute"]["model"] == "llama3.1"
    assert payload["version"] == "0.5.1"
