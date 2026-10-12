"""Presence debounce, enrollment, unknown faces, heir fence, thresholds, and pause.

Synthetic embeddings only. No camera, no OpenCV, no GPU.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

from assignments import (
    STATUS_DONE,
    STATUS_RUNNING,
    StepDraft,
    hold_report,
    new_assignment,
    owner_is_present,
    public_assignment,
    run_assignment_step,
    wants_owner_present,
)
from box_health import health_payload
from box_pause import merged_state, read_pause, share_pause, write_pause
from observer_privacy import pause_decision
from presence_access import presence_allowed, require_owner
from presence_cues import cue_for_title, room_cue
from presence_match import SeenFace, best_match, cosine, greeting_text, motion_open, should_greet, step, touch_present
from presence_models import DETECTOR, RECOGNIZER, clamp_fps, select_target
from presence_prompt import presence_prompt_block
from presence_speak import speak_greeting
from presence_store import PresenceStore, presence_enabled, room_for_assignments, status_public

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 12, 16, 0, tzinfo=timezone.utc)
JPEG = b"\xff\xd8\xff" + b"\x00" * 32


def _vec(*values: float, size: int = 32) -> list[float]:
    row = [0.0] * size
    for index, value in enumerate(values):
        row[index] = value
    return row


def _person(person_id: str, embedding: list[float], *, name: str = "Alex", relationship: str = "owner", greeting: str = "") -> dict:
    return {
        "id": person_id,
        "name": name,
        "relationship": relationship,
        "greeting": greeting,
        "embeddings": [embedding],
    }


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def test_presence_defaults_off_and_version_stays(monkeypatch):
    monkeypatch.delenv("HEIRLOOM_PRESENCE", raising=False)
    assert presence_enabled() is False
    payload = health_payload()
    assert payload["version"] == "0.5.1"
    assert payload["presence"]["enabled"] is False
    assert payload["presence"]["enrolled"] == 0
    assert payload["presence"]["present"] == []
    assert room_for_assignments() is None


def test_models_are_permissive_and_gpu_budget_falls_back():
    assert DETECTOR.license == "MIT"
    assert RECOGNIZER.license == "Apache-2.0"
    blob = f"{DETECTOR.url} {RECOGNIZER.url} {DETECTOR.filename} {RECOGNIZER.filename}".lower()
    assert "insightface" not in blob
    assert select_target(None, cuda_available=True) == "cpu"
    assert select_target(200, cuda_available=True, budget_mib=512) == "cpu"
    assert select_target(800, cuda_available=False, budget_mib=512) == "cpu"
    assert select_target(800, cuda_available=True, budget_mib=512) == "cuda"
    assert clamp_fps(1) == 2.0
    assert clamp_fps(9) == 5.0
    assert clamp_fps(3) == 3.0
    assert clamp_fps("nope") == 3.0


def test_threshold_matches_the_same_face_and_rejects_a_near_miss():
    owner = _vec(1.0)
    same = _person("prs_owner", owner, name="Alex")
    other = _person("prs_guest", _vec(0.0, 1.0), name="Sam", relationship="guest")
    assert best_match(owner, [same, other]).person_id == "prs_owner"
    near = _vec(0.35, (1 - 0.35 ** 2) ** 0.5)
    assert cosine(near, owner) < 0.36
    assert best_match(near, [same], threshold=0.36) is None
    assert best_match(_vec(0.0, 1.0), [same]) is None
    tied = [
        _person("prs_b", owner, name="Bee"),
        _person("prs_a", owner, name="Aye"),
    ]
    assert best_match(owner, tied).person_id == "prs_a"


def test_greeting_debounce_and_departure():
    moment = NOW
    assert should_greet(None, moment, 10) is True
    assert should_greet(_iso(moment - timedelta(minutes=1)), moment, 10) is False
    assert should_greet(_iso(moment - timedelta(minutes=11)), moment, 10) is True
    assert should_greet(_iso(moment), moment, 0) is True

    owner = _vec(1.0)
    enrolled = [_person("prs_owner", owner, name="Alex", greeting="Hello Alex.")]
    face = SeenFace(embedding=owner, camera="/dev/video0")
    first = step([face], enrolled, {}, moment, debounce_minutes=10, depart_seconds=30)
    assert first.greetings[0]["text"] == "Hello Alex."
    assert first.events[0]["kind"] == "arrival"
    assert len(enrolled) == 1

    still = step([face], enrolled, first.tracked, moment + timedelta(seconds=5), debounce_minutes=10)
    assert still.greetings == []
    assert still.events == []

    gone = step([], enrolled, still.tracked, moment + timedelta(seconds=40), depart_seconds=30)
    assert gone.events[0]["kind"] == "departure"
    assert any(row.get("present") for row in gone.tracked.values()) is False

    early = step([face], enrolled, gone.tracked, moment + timedelta(minutes=2), debounce_minutes=10)
    assert early.events[0]["kind"] == "arrival"
    assert early.events[0]["greeted"] is False
    assert early.greetings == []

    later = step(
        [],
        enrolled,
        early.tracked,
        moment + timedelta(minutes=20),
        depart_seconds=30,
    )
    again = step([face], enrolled, later.tracked, moment + timedelta(minutes=21), debounce_minutes=10)
    assert again.greetings[0]["text"] == "Hello Alex."
    assert greeting_text("Sam", "") == "Welcome back, Sam."


def test_unknown_face_is_not_enrolled():
    enrolled = [_person("prs_owner", _vec(1.0), name="Alex")]
    before = [dict(person) for person in enrolled]
    stranger = SeenFace(embedding=_vec(0.0, 1.0), thumb=JPEG)
    result = step([stranger], enrolled, {}, NOW, unknown_thumbnails=False)
    assert enrolled == before
    assert result.events == [{"ts": result.events[0]["ts"], "kind": "unrecognized"}]
    assert set(result.events[0]) == {"ts", "kind"}
    assert result.unknown_thumbs == []
    assert result.greetings == []

    saved = step([stranger], enrolled, {}, NOW, unknown_thumbnails=True)
    assert enrolled == before
    assert saved.unknown_thumbs
    assert saved.unknown_thumbs[0][1] == JPEG


def test_calm_frame_does_not_depart_and_motion_gate_skips_the_first_frame():
    tracked = {"prs_owner": {"present": True, "name": "Alex", "last_seen": _iso(NOW - timedelta(seconds=20))}}
    held = touch_present(tracked, NOW)
    assert held["prs_owner"]["present"] is True
    assert held["prs_owner"]["last_seen"] == _iso(NOW)
    assert "prs_stranger" not in held
    opened, _delta = motion_open(b"", b"frame", 0.04)
    assert opened is False
    quiet, delta = motion_open(b"aaaa", b"aaaa", 0.04)
    assert quiet is False
    assert delta == 0.0
    moving, delta = motion_open(b"aaaa", b"bbbb", 0.04)
    assert moving is True
    assert delta == 1.0


def test_enrollment_delete_purges_embeddings_and_forget_wipes_the_box(tmp_path):
    store = PresenceStore(tmp_path)
    with pytest.raises(ValueError, match="Consent"):
        store.create_person(name="Alex", relationship="owner", consent=False)
    person = store.create_person(name="Alex", relationship="owner", greeting="Hello Alex.", consent=True)
    store.add_sample(person["id"], _vec(1.0), JPEG)
    path = tmp_path / "people" / person["id"]
    assert (path / "embeddings.json").is_file()
    assert (path / "thumb.jpg").read_bytes() == JPEG
    store.delete_person(person["id"])
    assert not path.exists()
    assert store.list_people() == []

    again = store.create_person(name="Sam", relationship="guest", consent=True)
    store.add_sample(again["id"], _vec(0.0, 1.0), JPEG)
    store.write_settings({"unknown_thumbnails": True})
    store.save_unknown_thumb(_iso(NOW), JPEG)
    store.forget_everyone(NOW)
    assert store.list_people() == []
    assert not (tmp_path / "people").exists()
    assert list((tmp_path / "unknown").glob("*.jpg")) == [] if (tmp_path / "unknown").exists() else True
    events = store.read_events()
    assert events == [{"ts": _iso(NOW), "kind": "forget", "person_id": "", "name": "", "greeted": False}]


def test_unknown_thumbnails_stay_off_and_expire(tmp_path):
    store = PresenceStore(tmp_path)
    assert store.read_settings()["unknown_thumbnails"] is False
    store.save_unknown_thumb("2026-10-12T16:00:00+00:00", JPEG)
    assert store.list_unknown() == []
    store.write_settings({"unknown_thumbnails": True})
    store.save_unknown_thumb("2026-10-12T16:00:00+00:00", JPEG)
    assert len(store.list_unknown()) == 1
    old = next((tmp_path / "unknown").glob("*.jpg"))
    ancient = (NOW - timedelta(hours=25)).timestamp()
    import os

    os.utime(old, (ancient, ancient))
    assert store.purge_unknown(NOW) == 1
    assert store.list_unknown() == []
    store.append_events([{"ts": _iso(NOW), "kind": "unrecognized", "name": "should-not-stick", "embedding": [1]}])
    assert store.read_events() == [{"ts": _iso(NOW), "kind": "unrecognized"}]


def test_heir_fence_and_prompt_omit_names():
    with pytest.raises(HTTPException) as heir:
        require_owner({"audience": "heir", "heir_surface": False})
    assert heir.value.status_code == 404
    with pytest.raises(HTTPException) as caller:
        require_owner({"audience": "caller"})
    assert caller.value.status_code == 404
    with pytest.raises(HTTPException) as surface:
        require_owner({"audience": "owner", "heir_surface": True})
    assert surface.value.status_code == 404
    require_owner({"audience": "owner", "heir_surface": False})
    assert presence_allowed(None) is False
    status = {"present": [{"name": "Alex", "relationship": "owner"}]}
    assert presence_prompt_block(status, audience="heir") == ""
    assert presence_prompt_block(status, audience="caller") == ""
    assert "Alex" not in presence_prompt_block(status, audience="heir", enabled=True)
    owner_block = presence_prompt_block(status, audience="owner")
    assert "Alex" in owner_block


def test_pause_is_shared_and_quiet_hours_hold(tmp_path, monkeypatch):
    pause_file = tmp_path / "pause.json"
    monkeypatch.setenv("HEIRLOOM_PAUSE_FILE", str(pause_file))
    monkeypatch.delenv("HEIRLOOM_PRESENCE", raising=False)
    monkeypatch.delenv("HEIRLOOM_OBSERVER", raising=False)
    assert read_pause().get("paused") is False
    write_pause(True, "cli", pause_file)
    merged = merged_state({"paused": False, "reason": ""})
    paused, reason = pause_decision(merged, now=NOW, quiet_hours="")
    assert paused is True
    assert reason == "cli"
    write_pause(False, "", pause_file)
    night = datetime(2026, 10, 12, 1, 0, tzinfo=timezone.utc)
    paused, reason = pause_decision({"paused": False}, now=night, quiet_hours="23:00-07:00")
    assert paused is True
    assert reason == "schedule"
    paused, reason = pause_decision({"paused": False}, now=NOW, quiet_hours="23:00-07:00")
    assert paused is False
    share_pause(True, "web", pause_file)
    assert read_pause(pause_file)["reason"] == "web"


def test_status_counts_people_and_who_is_here(tmp_path, monkeypatch):
    monkeypatch.setenv("HEIRLOOM_PRESENCE", "1")
    monkeypatch.setenv("HEIRLOOM_PAUSE_FILE", str(tmp_path / "pause.json"))
    store = PresenceStore(tmp_path / "presence")
    person = store.create_person(name="Alex", relationship="owner", consent=True)
    store.write_tracked({
        person["id"]: {
            "present": True,
            "name": "Alex",
            "relationship": "owner",
            "arrived_at": _iso(NOW),
            "last_seen": _iso(NOW),
        }
    })
    store.write_runtime({"cameras": [{"path": "/dev/video0", "open": True}], "fps": 3, "model": "YuNet+SFace", "backend": "cpu"})
    status = status_public(store)
    assert status["enabled"] is True
    assert status["enrolled"] == 1
    assert status["fps"] == 3
    assert status["present"][0]["name"] == "Alex"
    assert status["owner_names"] == ["Alex"]
    assert "embeddings" not in status
    room = room_for_assignments(store)
    assert room["owner_names"] == ["Alex"]
    assert room["present_names"] == ["Alex"]


def test_assignment_holds_until_the_owner_is_in_the_room():
    assert owner_is_present(["Alex"], ["Alex"]) is True
    assert owner_is_present(["Sam"], ["Alex"]) is False
    assert owner_is_present(["Alex"], []) is False
    waiting = {"deliver_when": "owner_present", "goal": "Write the note.", "scope": ""}
    phrase = {"goal": "Hold the report until the owner is present.", "scope": ""}
    ordinary = {"goal": "Write the note.", "scope": "Heirloom only."}
    assert wants_owner_present(waiting) is True
    assert wants_owner_present(phrase) is True
    assert wants_owner_present(ordinary) is False
    empty_room = {"present_names": [], "owner_names": ["Alex"]}
    assert hold_report(phrase, None) is False
    assert hold_report(phrase, empty_room) is True
    assert hold_report(phrase, {"present_names": ["Alex"], "owner_names": ["Alex"]}) is False
    assert hold_report(ordinary, empty_room) is False

    class _Draft:
        async def draft(self, _assignment):
            return StepDraft(summary="Ready.", artifact_name="note.txt", artifact_text="draft")

    class _Boom:
        async def draft(self, _assignment):
            raise AssertionError("held report must not be drafted again")

    queued = new_assignment(
        user_id="owner-1",
        title="Morning note",
        goal="Hold the report until the owner is present.",
        scope="Write it locally.",
        autonomy="draft",
        clone_id=None,
        now=_iso(NOW),
    )
    held = __import__("asyncio").run(
        run_assignment_step(queued, executor=_Draft(), connector=None, now=_iso(NOW), room=empty_room)
    )
    assert held.assignment["status"] == STATUS_RUNNING
    assert held.assignment["held_for_presence"] is True
    assert any("Holding the report" in row["line"] for row in held.assignment["log"])
    public = public_assignment(held.assignment)
    assert public["held_for_presence"] is True

    released = __import__("asyncio").run(
        run_assignment_step(
            held.assignment,
            executor=_Boom(),
            connector=None,
            now=_iso(NOW + timedelta(minutes=5)),
            room={"present_names": ["Alex"], "owner_names": ["Alex"]},
        )
    )
    assert released.assignment["status"] == STATUS_DONE
    assert released.assignment["held_for_presence"] is False
    assert any("owner is in the room" in row["line"] for row in released.assignment["log"])


def test_observer_cue_names_the_screen_and_speak_stays_off(monkeypatch):
    assert room_cue([]) == "away"
    cue = cue_for_title([{"name": "Alex"}], "BIGDEAL")
    assert cue["presence"] == "at_desk"
    assert cue["presence_note"] == "at desk while BIGDEAL is on screen"
    assert cue["presence_people"] == ["Alex"]
    monkeypatch.delenv("PRESENCE_SPEAK", raising=False)
    assert speak_greeting("Welcome back, Alex.") == {"spoken": False, "reason": "off"}
    calls = []
    spoken = speak_greeting("Welcome back, Alex.", enabled=True, poster=lambda url, text: calls.append((url, text)) or {"ok": True})
    assert spoken["spoken"] is True
    assert calls[0][1] == "Welcome back, Alex."


def test_webcams_skip_hdmi_capture_and_the_observer_device():
    path = str(ROOT / "box" / "presence")
    if path not in sys.path:
        sys.path.insert(0, path)
    import presenced

    devices = [
        {"path": "/dev/video0", "name": "USB2.0 HD UVC WebCam", "index": 0},
        {"path": "/dev/video1", "name": "USB2.0 HD UVC WebCam: USB2.0 HD UVC WebCam", "index": 1},
        {"path": "/dev/video2", "name": "Elgato 4K60 Pro", "index": 2},
        {"path": "/dev/video3", "name": "EVGA XR1 Lite", "index": 3},
    ]
    chosen = presenced.pick_webcams(devices, skip_paths={"/dev/video0"})
    assert [device["path"] for device in chosen] == ["/dev/video1"]
    forced = presenced.pick_webcams(devices, forced=["/dev/video2", "/dev/video1"])
    assert [device["path"] for device in forced] == ["/dev/video1"]
