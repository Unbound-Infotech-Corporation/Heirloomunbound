"""Observer audio: separate streams, crosstalk, transcripts, no-signal, dedupe."""
from __future__ import annotations

import math
import struct
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deps import get_current_user
from observer_audio import (
    LABEL_MIC,
    LABEL_SYSTEM,
    accept_companion_chunk,
    audio_iteration,
    correlation,
    drain_chunks,
    is_silence,
    mic_is_crosstalk,
    parse_arecord_listing,
    pick_mic_device,
    pick_system_device,
    sweep_stale,
    whisper_model_name,
)
from observer_capture import signal_verdict
from observer_learn import notes_from_observations, normalize_note_text
from observer_store import ObserverStore
from routers.observer import router

_ARECORD = """**** List of CAPTURE Hardware Devices ****
card 0: PCH [HDA Intel PCH], device 0: ALC1220 Analog [ALC1220 Analog]
  Subdevices: 1/1
card 1: XR1 [EVGA XR1 Lite], device 0: USB Audio [USB Audio]
  Subdevices: 1/1
card 2: C920 [HD Pro Webcam C920], device 0: USB Audio [USB Audio]
  Subdevices: 1/1
"""


def _tone(freq: float, seconds: float = 0.4, *, rate: int = 16000, amp: int = 12000) -> bytes:
    count = int(seconds * rate)
    samples = [int(amp * math.sin(2 * math.pi * freq * i / rate)) for i in range(count)]
    return struct.pack("<" + str(count) + "h", *samples)


def _noise(seconds: float = 0.4, *, rate: int = 16000) -> bytes:
    count = int(seconds * rate)
    samples = [((i * 1103515245 + 12345) % 20001) - 10000 for i in range(count)]
    return struct.pack("<" + str(count) + "h", *samples)


def test_alsa_picks_xr1_for_system_and_c920_for_the_mic():
    devices = parse_arecord_listing(_ARECORD)
    system = pick_system_device(devices)
    mic = pick_mic_device(devices)
    assert system is not None and system["id"] == "XR1"
    assert mic is not None and mic["id"] == "C920"
    assert pick_mic_device([system]) is None
    assert pick_system_device(parse_arecord_listing("card 0: PCH [HDA Intel PCH], device 0: Analog [Analog]\n")) is None


def test_streams_stay_separate_and_crosstalk_drops_the_mic():
    speakers = _tone(440)
    leaked = _tone(440)
    voice = _noise()
    assert correlation(speakers, leaked) > 0.9
    assert mic_is_crosstalk(leaked, speakers) is True
    assert mic_is_crosstalk(voice, b"\x00" * len(voice)) is False
    assert is_silence(b"\x00" * 4000) is True
    seen: list[bytes] = []

    def _hear(pcm: bytes) -> str:
        seen.append(pcm)
        return "from the speakers" if pcm == speakers else "hello from the desk"

    devices = parse_arecord_listing(_ARECORD)
    mixed = audio_iteration(
        devices=devices,
        system_enabled=True,
        mic_enabled=True,
        paused=False,
        local_system=speakers,
        local_mic=leaked,
        transcribe=_hear,
    )
    assert mixed["system"]["source"] == "xr1"
    assert mixed["system"]["status"] == "hearing"
    assert mixed["mic"]["source"] == "c920"
    assert mixed["mic"]["status"] == "suppressed"
    assert seen == [speakers]
    assert mixed["notes"][0]["text"].startswith(LABEL_SYSTEM)
    assert all(not note["text"].startswith(LABEL_MIC) for note in mixed["notes"])

    seen.clear()
    kept = audio_iteration(
        devices=[],
        system_enabled=True,
        mic_enabled=True,
        paused=False,
        companion_system=speakers,
        companion_mic=voice,
        transcribe=_hear,
    )
    assert kept["system"]["source"] == "companion"
    assert kept["mic"]["source"] == "companion"
    assert kept["mic"]["status"] == "hearing"
    assert seen == [speakers, voice]
    labels = [note["text"].split(":", 1)[0] for note in kept["notes"]]
    assert labels == [LABEL_SYSTEM, LABEL_MIC]


def test_pause_privacy_and_empty_windows_store_no_pcm(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OBSERVER_AUDIO_SPOOL", str(tmp_path / "spool"))
    monkeypatch.setenv("HEIRLOOM_OBSERVER", "1")
    monkeypatch.setenv("OBSERVER_AUDIO", "1")
    paused = audio_iteration(
        devices=[],
        system_enabled=True,
        mic_enabled=True,
        paused=True,
        companion_system=_tone(220),
        companion_mic=_tone(330),
        transcribe=lambda _pcm: "should not run",
    )
    assert paused["notes"] == []
    assert paused["system"]["status"] == "paused"
    assert paused["mic"]["status"] == "paused"

    from observer_audio import consider_transcript

    secret = consider_transcript("Your verification code is 019283", channel="mic")
    assert secret["dropped"] is True and secret["text"] == ""
    said = consider_transcript("ship the box tonight", channel="mic")
    assert said["text"] == "User said: ship the box tonight"
    heard = consider_transcript("the match is on", channel="system")
    assert heard["text"].startswith("Watching/heard:")

    pcm = _tone(180, 0.05)
    refused = accept_companion_chunk(source="mic", pcm=pcm, paused=True, enabled=True, spool=tmp_path / "spool")
    assert refused["accepted"] is False
    assert list((tmp_path / "spool").rglob("*.pcm")) == []
    accepted = accept_companion_chunk(source="system", pcm=pcm, paused=False, enabled=True, spool=tmp_path / "spool")
    assert accepted["accepted"] is True
    drained = drain_chunks(tmp_path / "spool", "system")
    assert drained == pcm
    assert list((tmp_path / "spool").rglob("*.pcm")) == []
    stale = tmp_path / "spool" / "mic" / "old.pcm"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_bytes(pcm)
    import os

    os.utime(stale, (time_old := __import__("time").time() - 120, time_old))
    assert sweep_stale(tmp_path / "spool", now=__import__("time").time()) == 1
    assert not stale.exists()


def test_transcripts_join_the_timeline_and_identical_notes_collapse(tmp_path: Path):
    store = ObserverStore(tmp_path)
    first = store.add_transcript(
        {
            "channel": "mic",
            "text": "User said: one more run",
            "ts": "2026-10-12T15:00:00+00:00",
        }
    )
    again = store.add_transcript(
        {
            "channel": "mic",
            "text": "User said: one more run",
            "ts": "2026-10-12T15:00:04+00:00",
        }
    )
    heard = store.add_transcript(
        {
            "channel": "system",
            "text": "Watching/heard: the boss fight started",
            "ts": "2026-10-12T15:00:05+00:00",
        }
    )
    assert first["stored"] is True and first["note"]["kind"] == "speech"
    assert again["reason"] == "duplicate"
    assert heard["note"]["kind"] == "heard"
    notes = store.read_notes()
    assert len(notes) == 2
    assert {note["kind"] for note in notes} == {"speech", "heard"}
    timeline = store.read_observations() if hasattr(store, "read_observations") else None
    rows = __import__("json").loads("null")
    del rows
    from observer_store import _read_jsonl

    observations = _read_jsonl(store.observations_path)
    assert [row["channel"] for row in observations] == ["mic", "system"]
    assert all("pcm" not in row for row in observations)

    vision = "A terminal and a browser are open on the desk."
    created = store.add_observations(
        [
            {"ts": "2026-10-12T15:10:00+00:00", "activity": "work", "app": "Terminal", "title": "Terminal", "text": vision},
            {"ts": "2026-10-12T15:10:15+00:00", "activity": "work", "app": "Terminal", "title": "Terminal", "text": vision},
            {"ts": "2026-10-12T15:10:30+00:00", "activity": "work", "app": "VS Code", "title": "VS Code", "text": "Editing the installer."},
            {"ts": "2026-10-12T15:10:45+00:00", "activity": "work", "app": "Browser", "title": "Browser", "text": "Reading the capture notes."},
        ]
    )
    texts = [row["text"] for row in _read_jsonl(store.observations_path) if row.get("activity") == "work"]
    assert texts.count(vision) == 1
    assert normalize_note_text(vision) == normalize_note_text(vision.upper() + "!")
    drafts = notes_from_observations(
        [
            {"ts": "2026-10-12T15:10:00+00:00", "activity": "work", "app": "Terminal", "title": "Terminal", "text": vision},
            {"ts": "2026-10-12T15:10:20+00:00", "activity": "work", "app": "VS Code", "title": "VS Code", "text": "Editing."},
            {"ts": "2026-10-12T15:10:40+00:00", "activity": "work", "app": "Browser", "title": "Browser", "text": "Reading."},
            {"ts": "2026-10-12T15:11:00+00:00", "activity": "speech", "channel": "mic", "text": "User said: one more run"},
        ]
    )
    assert all(note["kind"] != "speech" for note in drafts)
    assert any(note["kind"] == "workflow" for note in created)


def test_no_signal_uses_size_content_and_timing():
    varied = bytes([index % 256 for index in range(400)])
    flat = bytes([29]) * 400
    assert signal_verdict(gray=varied, width=1280, height=720, gap_s=0.4) == (True, "signal")
    assert signal_verdict(gray=varied, width=720, height=480)[0] is False
    assert signal_verdict(gray=flat, width=1280, height=720)[0] is False
    assert signal_verdict(gray=b"", width=1280, height=720, grab_error="timeout")[0] is False
    assert signal_verdict(gray=varied, width=1280, height=720, gap_s=8.0, repeated=True)[0] is False
    assert signal_verdict(gray=varied, width=1280, height=720, gap_s=8.0, repeated=False)[0] is True
    assert signal_verdict(gray=varied, stderr="Stream #0: 720x480 yuyv422")[0] is False


def test_whisper_model_follows_vram():
    assert whisper_model_name(24576) == "medium"
    assert whisper_model_name(8192) == "small"


def test_audio_routes_require_the_owner_and_keep_streams_apart(tmp_path, monkeypatch):
    monkeypatch.setenv("HEIRLOOM_OBSERVER", "1")
    monkeypatch.setenv("HEIRLOOM_OBSERVER_DIR", str(tmp_path / "observer"))
    monkeypatch.setenv("OBSERVER_AUDIO", "1")
    monkeypatch.setenv("OBSERVER_AUDIO_SPOOL", str(tmp_path / "spool"))
    monkeypatch.setenv("HEIRLOOM_PAUSE_FILE", str(tmp_path / "pause.json"))
    monkeypatch.setenv("HEIRLOOM_DATA_ROOT", str(tmp_path))
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "owner", "audience": "owner"}
    client = TestClient(app)
    missing = client.post("/api/observer/audio/room", content=_tone(200, 0.05))
    assert missing.status_code == 404
    posted = client.post("/api/observer/audio/mic", content=_tone(200, 0.05))
    assert posted.status_code == 200
    assert posted.json()["source"] == "mic"
    assert list((tmp_path / "spool" / "mic").glob("*.pcm"))
    assert list((tmp_path / "spool" / "system").glob("*.pcm")) == []
    toggled = client.put("/api/observer/audio", json={"mic": False})
    assert toggled.status_code == 200
    assert toggled.json()["audio"]["mic"]["enabled"] is False
    blocked = client.post("/api/observer/audio/mic", content=_tone(200, 0.05))
    assert blocked.status_code == 409
    huge = b"\x01\x00" * (16000 * 5)
    too_big = client.post("/api/observer/audio/system", content=huge)
    assert too_big.status_code == 413
    status = client.get("/api/observer/status")
    assert status.json()["audio"]["transcripts_only"] is True
    assert status.json()["audio"]["mic"]["enabled"] is False
    assert status.json()["audio"]["system"]["enabled"] is True


def test_install_reloads_ssh_safely():
    script = Path(__file__).resolve().parents[2] / "box" / "install.sh"
    text = script.read_text(encoding="utf-8")
    assert "systemctl try-reload-or-restart ssh" in text
    assert "systemctl reload ssh" not in text
    assert "--observer-audio" in text
    assert "nvidia-cublas-cu12" in text
    assert "nvidia-cudnn-cu12>=9,<10" in text
    assert "LD_LIBRARY_PATH" in text
    assert "systemctl restart heirloom-observer.service" in text
    assert "systemctl enable --now heirloom-observer.service" not in text
    main = text.split("main() {", 1)[1]
    assert main.index('write_env "') < main.index("install_observer")


def test_duplicate_note_text_is_not_rewritten(tmp_path: Path):
    store = ObserverStore(tmp_path)
    moment = datetime(2026, 10, 12, 16, 0, tzinfo=timezone.utc).isoformat()
    store.add_observations(
        [
            {"ts": moment, "activity": "media", "app": "VLC", "title": "VLC", "text": "Watching the match."},
            {"ts": moment, "activity": "media", "app": "VLC", "title": "VLC", "text": "Watching the match!"},
        ]
    )
    media = [row for row in store.read_notes() if "match" in row["text"].lower()]
    assert len({normalize_note_text(row["text"]) for row in media}) == len(media)


def test_transcription_failure_stays_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("HEIRLOOM_OBSERVER", "1")
    monkeypatch.setenv("HEIRLOOM_OBSERVER_DIR", str(tmp_path))

    def boom(_pcm: bytes) -> str:
        raise RuntimeError("Library libcublas.so.12 is not found or cannot be loaded")

    tone = _tone(440, 0.2)
    failed = audio_iteration(
        devices=[],
        system_enabled=True,
        mic_enabled=True,
        paused=False,
        companion_system=tone,
        companion_mic=b"\x00" * 4000,
        transcribe=boom,
    )
    assert failed["system"]["status"] == "error"
    assert failed["system"]["status"] != "silent"
    assert "libcublas.so.12" in failed["system"]["error"]
    assert failed["mic"]["status"] == "silent"
    quiet = audio_iteration(
        devices=[],
        system_enabled=True,
        mic_enabled=False,
        paused=False,
        companion_system=b"\x00" * 4000,
        transcribe=boom,
        prior_faults=failed["faults"],
    )
    assert quiet["system"]["status"] == "error"
    assert "libcublas.so.12" in quiet["system"]["error"]

    store = ObserverStore(tmp_path)
    store.write_status(
        {
            "audio": {
                "installed": True,
                "model": "medium",
                "system": failed["system"],
                "mic": {"enabled": True, "source": "c920", "status": "silent", "device": "C920", "error": ""},
            }
        }
    )
    from observer_store import status_public

    health = status_public(store)
    assert health["audio"]["system"]["status"] == "error"
    assert "libcublas.so.12" in health["audio"]["system"]["error"]


def test_capture_card_name_is_not_a_repeating_habit(tmp_path: Path):
    from observer_learn import habit_identity, is_capture_device_label, notes_from_observations

    assert is_capture_device_label("EVGA XR1 Lite Capture Box Video") is True
    assert is_capture_device_label("Terminal") is False
    assert habit_identity("Often in Terminal during work (6 samples this stretch).") == habit_identity(
        "Often in Terminal during work."
    )
    card_rows = [
        {
            "ts": f"2026-10-12T15:{index:02d}:00+00:00",
            "activity": "work",
            "app": "EVGA XR1 Lite Capture Box Video",
            "title": "EVGA XR1 Lite Capture Box Video",
            "text": f"desktop {index}",
        }
        for index in range(8)
    ]
    assert all("xr1" not in note["text"].lower() for note in notes_from_observations(card_rows))

    store = ObserverStore(tmp_path)
    store.root.mkdir(parents=True, exist_ok=True)
    store.notes_path.write_text(
        '{"id":"obs_oldhabit","source":"observer","kind":"habit","text":"Often in Terminal during work (4 samples this stretch).",'
        '"confidence":0.7,"created_at":"2026-10-12T16:00:00+00:00","status":"pending","fingerprint":"old","tokens":[],"topics":["terminal","work"]}\n',
        encoding="utf-8",
    )
    store.add_observations(
        [
            {
                "ts": f"2026-10-12T16:{index:02d}:00+00:00",
                "activity": "work",
                "app": "Terminal",
                "title": f"edit {index}",
                "text": f"line {index}",
            }
            for index in range(1, 6)
        ]
    )
    habits = [note for note in store.read_notes() if note["kind"] == "habit" and "Terminal" in note["text"]]
    assert len(habits) == 1
