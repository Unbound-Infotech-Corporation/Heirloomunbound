"""Network screen: source choice, pause, the shared note pipeline, health."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deps import get_current_user
from observer_screen import (
    CAPTURE_DEVICE,
    MAX_JPEG_BYTES,
    NetworkInbox,
    accept_frame,
    choose_source,
    commit_frame,
    configured_source,
    latest_frame,
    status_fields,
)
from observer_store import ObserverStore, status_public
from routers.observer import router

JPEG = b"\xff\xd8\xff\xd9"


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("HEIRLOOM_OBSERVER", "1")
    monkeypatch.setenv("HEIRLOOM_OBSERVER_DIR", str(tmp_path / "observer"))
    monkeypatch.setenv("OBSERVER_SCREEN_SPOOL", str(tmp_path / "screen"))
    monkeypatch.setenv("HEIRLOOM_PAUSE_FILE", str(tmp_path / "pause.json"))
    monkeypatch.setenv("HEIRLOOM_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("OBSERVER_QUIET_HOURS", "")
    monkeypatch.setenv("OBSERVER_SOURCE", "auto")
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "owner", "audience": "owner"}
    return app


def test_auto_uses_a_fresh_network_frame_and_falls_back_to_video0():
    assert configured_source("hdmi") == "auto"
    assert configured_source("network") == "network"
    fresh = choose_source(mode="auto", network_age_s=0.4, fresh_s=3)
    assert fresh["source"] == "network"
    assert fresh["signal"] == "ok"
    assert fresh["mode"] == "auto"
    fields = status_fields(fresh, fps=2, device="network")
    assert fields["signal"] == "ok"
    assert fields["source"] == "network"
    assert fields["fps"] == 2

    inbox = NetworkInbox()
    inbox.push(JPEG, received_at=100.0)
    assert abs((inbox.age(100.4, 3) or 0) - 0.4) < 1e-6
    still = choose_source(mode="auto", network_age_s=inbox.age(100.4, 3), fresh_s=3)
    assert still["signal"] == "ok"
    assert inbox.age(104.0, 3) is None
    stale = choose_source(mode="auto", network_age_s=None, fresh_s=3)
    assert stale["source"] == "capture"
    assert stale["device"] == CAPTURE_DEVICE == "/dev/video0"
    assert status_fields(stale, fps=2, device="/dev/video0", capture_signal="signal")["signal"] == "signal"

    only_network = choose_source(mode="network", network_age_s=None, fresh_s=3)
    assert only_network["source"] == "network"
    assert only_network["signal"] == "no-signal"
    assert only_network["device"] == ""

    capture = choose_source(mode="capture", network_age_s=0.1, fresh_s=3)
    assert capture["source"] == "capture"
    assert capture["device"] == ""


def test_paused_and_bad_frames_are_refused(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    client = TestClient(app)
    spool = tmp_path / "screen"
    missing = client.post("/api/observer/screen", content=b"not-a-jpeg")
    assert missing.status_code == 400
    assert list(spool.glob("*.jpg")) == []
    posted = client.post("/api/observer/screen", content=JPEG)
    assert posted.status_code == 200
    assert posted.json()["source"] == "network"
    assert list(spool.glob("*.jpg"))
    frame = latest_frame(spool, fresh_s=3)
    assert frame is not None
    assert frame[0] == JPEG
    assert list(spool.glob("*.jpg")) == []

    store = ObserverStore(tmp_path / "observer")
    store.set_paused(True, "web")
    blocked = client.post("/api/observer/screen", content=JPEG)
    assert blocked.status_code == 409
    assert list(spool.glob("*.jpg")) == []

    huge = b"\xff\xd8" + (b"\x00" * (MAX_JPEG_BYTES + 8)) + b"\xff\xd9"
    store.set_paused(False, "")
    too_big = client.post("/api/observer/screen", content=huge)
    assert too_big.status_code == 413

    heir = FastAPI()
    heir.include_router(router, prefix="/api")
    heir.dependency_overrides[get_current_user] = lambda: {"user_id": "heir", "audience": "heir", "heir_surface": True}
    assert TestClient(heir).post("/api/observer/screen", content=JPEG).status_code == 404


def test_health_reports_ok_when_the_network_picture_is_fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("HEIRLOOM_OBSERVER", "1")
    monkeypatch.setenv("HEIRLOOM_OBSERVER_DIR", str(tmp_path))
    monkeypatch.setenv("OBSERVER_SOURCE", "auto")
    store = ObserverStore(tmp_path)
    choice = choose_source(mode="auto", network_age_s=0.2, fresh_s=3)
    store.write_status(status_fields(choice, fps=2, device="network"))
    health = status_public(store)
    assert health["source"] == "network"
    assert health["mode"] == "auto"
    assert health["signal"] == "ok"
    assert health["fps"] == 2
    assert health["device"] == "network"


def test_network_frame_uses_the_capture_pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("HEIRLOOM_OBSERVER", "1")
    monkeypatch.setenv("OBSERVER_CLIPS", "1")
    store = ObserverStore(tmp_path)
    store.root.mkdir(parents=True, exist_ok=True)
    seen: dict[str, str] = {}

    def model(payload):
        seen["ocr"] = payload["ocr"]
        return {"activity": "work", "summary": "Editing a letter", "game": ""}

    clip = store.clips_dir / "highlight-1.mkv"
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(b"x" * 8000)
    store.record_clip(name="highlight-1.mkv", seconds=2)
    result = commit_frame(
        store,
        ocr="a letter to my daughter",
        app="",
        model=model,
        hotkey_phrase="HEIRLOOM PAUSE",
        now_iso="2026-10-28T12:00:00+00:00",
        delta=0.1,
        clips=True,
        cap_bytes=1000,
    )
    assert result["model_called"] is True
    assert result["dropped"] is False
    assert seen["ocr"] == "a letter to my daughter"
    assert "Editing a letter" in store.observations_path.read_text(encoding="utf-8")
    assert not clip.exists()

    def boom(_payload):
        raise AssertionError("model must stay uncalled")

    dropped = commit_frame(
        store,
        ocr="1Password vault is open",
        app="1Password",
        model=boom,
        hotkey_phrase="HEIRLOOM PAUSE",
        now_iso="2026-10-28T12:00:01+00:00",
        delta=0.2,
        clips=False,
    )
    assert dropped["dropped"] is True
    assert dropped["reason"] == "password_manager"
    assert dropped["model_called"] is False
    raw = store.observations_path.read_text(encoding="utf-8")
    assert "1Password" not in raw
    assert "password_manager" in raw

    latched = commit_frame(
        store,
        ocr="HEIRLOOM PAUSE",
        model=boom,
        hotkey_phrase="HEIRLOOM PAUSE",
        now_iso="2026-10-28T12:00:02+00:00",
        delta=0.0,
    )
    assert latched["latch_pause"] is True
    assert store.read_state()["paused"] is True


def test_daemon_shares_one_pipeline_and_install_writes_the_source(monkeypatch):
    monkeypatch.setenv("OLLAMA_OBSERVER_MODEL", "qwen2.5vl:7b")
    root = Path(__file__).resolve().parents[2]
    daemon = (root / "box" / "observer" / "observerd.py").read_text(encoding="utf-8")
    assert daemon.count("commit_frame(") == 1
    assert daemon.count("_consume_picture(") == 3
    assert "consider_frame(" not in daemon
    assert "ollama_see(" in daemon
    assert "status_fields(" in daemon
    assert "CAPTURE_DEVICE" in daemon
    install = (root / "box" / "install.sh").read_text(encoding="utf-8")
    assert 'upsert_env OBSERVER_SOURCE "auto"' in install
    assert 'upsert_env OBSERVER_NETWORK_FRESH_S "3"' in install
    assert 'upsert_env OBSERVER_SCREEN_SPOOL "/run/heirloom-observer/screen"' in install
    env = (root / "box" / "env.example").read_text(encoding="utf-8")
    assert "OBSERVER_SOURCE=auto" in env
    readme = (root / "box" / "README.md").read_text(encoding="utf-8")
    assert "OBSERVER_SOURCE" in readme
    assert "/dev/video0" in readme
    assert "qwen2.5vl:7b" in readme
    guide = (root / "box" / "OBSERVER.md").read_text(encoding="utf-8")
    assert "POST /api/observer/screen" in guide
    assert "signal" in guide and "`ok`" in guide

    import importlib.util

    spec = importlib.util.spec_from_file_location("heirloom_observerd", root / "box" / "observer" / "observerd.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.vision_model_name() == "qwen2.5vl:7b"


def test_accept_frame_refuses_a_pause_without_writing(tmp_path):
    spool = tmp_path / "screen"
    refused = accept_frame(jpeg=JPEG, paused=True, enabled=True, spool=spool)
    assert refused["accepted"] is False
    assert refused["reason"] == "paused"
    assert list(spool.glob("*.jpg")) == []
