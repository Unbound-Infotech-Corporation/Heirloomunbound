"""Observer privacy, sessions, notes, heir fence, and storage caps."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from box_health import health_payload
from observer_capture import (
    IdleClock,
    assert_ram_dir,
    ffmpeg_clip_command,
    ffmpeg_grab_command,
    ffmpeg_gray_command,
    is_no_signal,
    pick_capture_device,
    ram_budget_bytes,
    ring_slot_count,
    sample_interval_s,
    scene_delta,
    trim_ram_dir,
)
from observer_learn import (
    count_switches,
    fingerprint,
    notes_from_observations,
    segment_sessions,
    suppressed,
    tokenize,
)
from observer_models import (
    REFERENCE_VRAM_MIB,
    keep_alive_payload,
    models_fit,
    observer_pair_for_vram_mib,
    residency_for,
    same_model,
    vision_model_for_vram_mib,
    vision_model_license,
)
from observer_pipeline import consider_frame
from observer_privacy import pause_decision, screen_is_sensitive
from observer_prompt import (
    PROMPT_BLOCK_CHARS,
    PROMPT_NOTE_CHARS,
    PROMPT_NOTE_LIMIT,
    WATCHED_SOURCE,
    apply_source_label,
    attach_observer_context,
    block_grounded_miss,
    observer_prompt_block,
    select_for_prompt,
)
from observer_store import (
    HEARD_TEXT_CAP,
    NOTE_HOURLY_CAP,
    ObserverStore,
    observer_enabled,
)


def _ts(minutes: int) -> str:
    base = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)
    return (base + timedelta(minutes=minutes)).isoformat()


def test_observer_defaults_off(monkeypatch):
    monkeypatch.delenv("HEIRLOOM_OBSERVER", raising=False)
    assert observer_enabled() is False
    payload = health_payload()
    assert payload["observer"]["enabled"] is False
    assert payload["observer"]["audio"]["transcripts_only"] is True
    assert payload["observer"]["audio"]["system"]["status"] == "off"
    assert payload["version"] == "0.5.1"


def test_privacy_drops_sensitive_screens_before_the_model():
    calls = {"n": 0}

    def _model(_payload):
        calls["n"] += 1
        raise AssertionError("model saw a sensitive frame")

    samples = [
        ("Password:\n••••••••", "", "password_field"),
        ("Sign in\nEmail\nPassword", "", "password_field"),
        ("1Password — Vault", "1Password", "password_manager"),
        ("Bitwarden", "", "password_manager"),
        ("Your verification code is 019283", "", "otp"),
        ("Authenticator\n482913", "", "otp"),
        ("PayPal Checkout\nCard number\nCVV", "", "banking"),
        ("Chase Bank\nAvailable balance\nRouting number 021000021", "", "banking"),
        ("Slack — Dana: are you free tonight?", "Slack", "chat"),
        ("WhatsApp", "", "chat"),
        ("Discord — private message from Sam", "", "chat"),
    ]
    for text, app, reason in samples:
        decision = screen_is_sensitive(text, app)
        assert decision.drop is True, text
        assert decision.reason == reason
        result = consider_frame(ocr=text, app=app, model=_model)
        assert result["model_called"] is False
        assert result["store_text"] is False
        assert result["text"] == ""
        assert result["reason"] == reason
    assert calls["n"] == 0


def test_privacy_allows_ordinary_work():
    text = "VS Code — observer.py\nconst password = hash(secret)"
    decision = screen_is_sensitive(text, "Visual Studio Code")
    assert decision.drop is False
    assert screen_is_sensitive("HDMI capture\nno signal", "").drop is False

    def _model(_payload):
        return {"activity": "work", "summary": "Editing observer.py"}

    result = consider_frame(ocr=text, app="Visual Studio Code", title="observer.py", model=_model)
    assert result["dropped"] is False
    assert result["model_called"] is True
    assert result["activity"] == "work"
    assert "password" not in result["reason"]


def test_sessions_focus_and_switches():
    rows = [
        {"ts": _ts(0), "activity": "work", "title": "Terminal"},
        {"ts": _ts(5), "activity": "work", "title": "VS Code"},
        {"ts": _ts(10), "activity": "work", "title": "Browser docs"},
        {"ts": _ts(12), "activity": "play", "title": "Hades", "game": "Hades"},
        {"ts": _ts(40), "activity": "play", "title": "Hades", "game": "Hades"},
    ]
    sessions = segment_sessions(rows)
    assert [item["activity"] for item in sessions] == ["work", "play", "play"]
    assert sessions[0]["focus_seconds"] == 10 * 60
    assert count_switches(sessions) == 1
    assert len(sessions[0]["titles"]) == 3


def test_notes_from_fake_observations_are_tagged_observer():
    rows = [
        {"ts": _ts(0), "activity": "work", "app": "VS Code", "title": "Terminal"},
        {"ts": _ts(4), "activity": "work", "app": "VS Code", "title": "VS Code — server.py"},
        {"ts": _ts(8), "activity": "work", "app": "VS Code", "title": "Browser — API docs"},
        {"ts": _ts(12), "activity": "work", "app": "VS Code", "title": "Terminal"},
        {
            "ts": _ts(20),
            "activity": "play",
            "app": "Steam",
            "title": "Hades",
            "game": "Hades",
            "text": "you died",
        },
        {
            "ts": _ts(21),
            "activity": "play",
            "app": "Steam",
            "title": "Hades",
            "game": "Hades",
            "text": "retry",
        },
        {
            "ts": _ts(22),
            "activity": "play",
            "app": "Steam",
            "title": "Hades",
            "game": "Hades",
            "text": "you died",
            "owner_phrases": ["one more run"],
        },
        {
            "ts": _ts(23),
            "activity": "play",
            "app": "Steam",
            "title": "Hades",
            "game": "Hades",
            "text": "retry",
            "owner_phrases": ["one more run"],
        },
    ]
    notes = notes_from_observations(rows)
    kinds = {note["kind"] for note in notes}
    assert "workflow" in kinds
    assert "decision_style" in kinds
    assert "vocabulary" in kinds
    assert "habit" in kinds
    for note in notes:
        assert note["source"] == "observer"
        assert 0 < note["confidence"] <= 0.99
        assert note["status"] == "pending"
    decision = next(note for note in notes if note["kind"] == "decision_style")
    assert "Hades" in decision["text"]
    assert "retries" in decision["text"].lower()
    workflow = next(note for note in notes if note["kind"] == "workflow")
    assert "1. Terminal" in workflow["text"]
    assert "2. VS Code" in workflow["text"]


def test_reject_and_never_suppress_similar_notes(tmp_path):
    store = ObserverStore(tmp_path)
    rows = [
        {"ts": _ts(20), "activity": "play", "game": "Hades", "title": "Hades", "text": "you died"},
        {"ts": _ts(21), "activity": "play", "game": "Hades", "title": "Hades", "text": "retry"},
        {"ts": _ts(22), "activity": "play", "game": "Hades", "title": "Hades", "text": "you died"},
        {"ts": _ts(23), "activity": "play", "game": "Hades", "title": "Hades", "text": "retry"},
    ]
    created = store.add_observations(rows)
    decision = next(note for note in created if note["kind"] == "decision_style")
    store.apply_feedback(decision["id"], "not_me")
    assert all(note["id"] != decision["id"] for note in store.read_notes())
    again = store.add_observations(rows)
    assert all(note["fingerprint"] != decision["fingerprint"] for note in again)
    similar = {
        "kind": "decision_style",
        "text": "After a loss in Hades he retries quickly instead of stopping.",
        "fingerprint": fingerprint("After a loss in Hades he retries quickly instead of stopping."),
        "tokens": tokenize("After a loss in Hades he retries quickly instead of stopping."),
        "topics": ["hades"],
    }
    assert suppressed(similar, store.read_suppressions()) is True

    other = store.add_observations(
        [
            {
                "ts": _ts(0),
                "activity": "work",
                "app": "Terminal",
                "title": "Terminal",
                "owner_phrases": ["ship the box"],
            },
            {
                "ts": _ts(3),
                "activity": "work",
                "app": "Terminal",
                "title": "Editor",
                "owner_phrases": ["ship the box"],
            },
            {
                "ts": _ts(6),
                "activity": "work",
                "app": "Terminal",
                "title": "Browser",
            },
            {
                "ts": _ts(9),
                "activity": "work",
                "app": "Terminal",
                "title": "Editor",
            },
        ]
    )
    vocab = next(note for note in other if note["kind"] == "vocabulary")
    store.apply_feedback(vocab["id"], "never")
    broader = {
        "kind": "vocabulary",
        "text": "Phrasing he types: ship the box.",
        "fingerprint": fingerprint("different"),
        "tokens": tokenize("phrasing he types ship the box"),
        "topics": ["ship the box"],
    }
    assert store.would_suppress(broader) is True


def test_heir_fence_hides_pending_notes_and_clips(tmp_path):
    store = ObserverStore(tmp_path)
    created = store.add_observations(
        [
            {"ts": _ts(20), "activity": "play", "game": "Hades", "title": "Hades", "text": "you died"},
            {"ts": _ts(21), "activity": "play", "game": "Hades", "title": "Hades", "text": "retry"},
            {"ts": _ts(22), "activity": "play", "game": "Hades", "title": "Hades", "text": "you died"},
            {"ts": _ts(23), "activity": "play", "game": "Hades", "title": "Hades", "text": "retry"},
        ]
    )
    accepted = created[0]
    store.apply_feedback(accepted["id"], "thats_me")
    store.record_clip(name="moment.mkv", seconds=8, now=datetime(2026, 10, 12, tzinfo=timezone.utc))
    heir = store.export_for_audience(audience="heir")
    assert heir["clips"] == []
    assert heir["notes"]
    assert all(note["status"] == "accepted" for note in heir["notes"])
    owner = store.export_for_audience(audience="owner")
    assert any(note["status"] == "pending" for note in owner["notes"])
    assert owner["clips"]


def test_storage_prunes_clips_and_keeps_notes(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSERVER_CLIPS", "0")
    store = ObserverStore(tmp_path)
    store.add_observations(
        [
            {"ts": _ts(20), "activity": "play", "game": "Hades", "title": "Hades", "text": "you died"},
            {"ts": _ts(21), "activity": "play", "game": "Hades", "title": "Hades", "text": "retry"},
        ]
    )
    assert store.read_notes()
    store.clips_dir.mkdir(parents=True)
    blob = store.clips_dir / "old.mkv"
    blob.write_bytes(b"x" * 4096)
    store.record_clip(
        name="old.mkv",
        seconds=30,
        now=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    fresh = store.clips_dir / "fresh.mkv"
    fresh.write_bytes(b"y" * 4096)
    store.record_clip(
        name="fresh.mkv",
        seconds=8,
        now=datetime(2026, 10, 12, tzinfo=timezone.utc),
    )
    expired = store.prune(now=datetime(2026, 10, 12, tzinfo=timezone.utc), cap_bytes=10**9, ttl_days=7)
    assert "old.mkv" in expired["removed"]
    assert not blob.exists()
    assert fresh.exists()
    assert store.read_notes()
    tight = store.prune(now=datetime(2026, 10, 12, tzinfo=timezone.utc), cap_bytes=500, ttl_days=7)
    assert "fresh.mkv" in tight["removed"]
    assert not fresh.exists()
    assert store.read_notes()
    assert store.admit_clip(privacy_dropped=True, duration_s=5, enabled=True) is False
    assert store.admit_clip(privacy_dropped=False, duration_s=5, enabled=False) is False
    monkeypatch.setenv("OBSERVER_CLIP_MAX_MINUTES_PER_DAY", "1")
    moment = datetime(2026, 10, 12, tzinfo=timezone.utc)
    assert store.admit_clip(privacy_dropped=False, duration_s=30, enabled=True, now=moment) is True
    store.record_clip(name="budget.mkv", seconds=30, now=moment)
    assert store.admit_clip(privacy_dropped=False, duration_s=50, enabled=True, now=moment) is False


def test_pause_hotkey_and_schedule():
    evening = datetime(2026, 10, 12, 23, 30)
    morning = datetime(2026, 10, 12, 9, 0)
    paused, reason = pause_decision({}, now=evening, quiet_hours="23:00-07:00")
    assert paused is True and reason == "schedule"
    paused, reason = pause_decision({}, now=morning, quiet_hours="23:00-07:00")
    assert paused is False
    paused, reason = pause_decision(
        {},
        now=morning,
        screen_text="HEIRLOOM PAUSE — look away",
        hotkey_phrase="HEIRLOOM PAUSE",
    )
    assert paused is True and reason == "hotkey"
    paused, reason = pause_decision({"paused": True, "reason": "cli"}, now=morning)
    assert paused is True and reason == "cli"


def test_capture_rate_ring_and_device_pick():
    assert sample_interval_s(0.0) == pytest.approx(0.5)
    assert sample_interval_s(0.9) == pytest.approx(0.125)
    assert scene_delta(b"aaa", b"aaa") == 0
    assert is_no_signal(b"\x00" * 20) is True
    assert is_no_signal(b"\xff" * 20) is False
    ram = assert_ram_dir("/run/heirloom-observer")
    assert str(ram).startswith("/run/")
    with pytest.raises(ValueError):
        assert_ram_dir("/var/lib/heirloom/observer")
    command = ffmpeg_grab_command("/dev/video0", Path("/run/heirloom-observer/frame.jpg"))
    assert "v4l2" in command
    assert "1280x720" in command
    assert "yuyv422" in command
    assert "1920x1080" not in command
    gray = ffmpeg_gray_command("/dev/video0")
    assert "1280x720" in gray
    assert "yuyv422" in gray
    clip = ffmpeg_clip_command("/dev/video0", Path("/run/heirloom-observer/highlight.mkv"), seconds=8)
    assert "-an" in clip
    assert "8" in clip
    with pytest.raises(ValueError):
        ffmpeg_clip_command("/dev/video0", Path("/var/lib/heirloom/observer/highlight.mkv"))
    picked = pick_capture_device(
        [
            {"path": "/dev/video1", "name": "UVC metadata", "index": 1},
            {"path": "/dev/video2", "name": "Webcam", "index": 2},
            {"path": "/dev/video0", "name": "EVGA XR1", "index": 0},
        ]
    )
    assert picked["path"] == "/dev/video0"
    clock = IdleClock()
    assert clock.update(True, 10) is None
    assert clock.update(False, 25) == pytest.approx(15)


def test_rtx_3090_pair_fits_and_a_32b_chat_model_does_not():
    assert REFERENCE_VRAM_MIB == 24576
    plan = observer_pair_for_vram_mib(24576)
    assert plan.twin == "qwen2.5:14b"
    assert plan.vision == "qwen2.5vl:7b"
    assert plan.fits is True
    assert plan.mode == "shared"
    assert plan.max_loaded == 2
    assert plan.vision_keep_alive == "45s"
    assert plan.expected_mib == 19456
    assert vision_model_license(plan.twin) == "Apache-2.0"
    assert vision_model_license(plan.vision) == "Apache-2.0"
    assert models_fit("qwen2.5:32b", "qwen2.5vl:7b", 24576) is False
    crowded = residency_for("qwen2.5:32b", "qwen2.5vl:7b", 24576)
    assert crowded.fits is False
    assert crowded.mode == "exclusive"
    assert crowded.max_loaded == 1
    assert keep_alive_payload(crowded.vision_keep_alive) == 0
    assert same_model("qwen2.5:14b:latest", "qwen2.5:14b") is True
    small = observer_pair_for_vram_mib(8192)
    assert small.twin == "qwen2.5:3b"
    assert small.vision == "moondream"
    assert small.fits is True
    assert ring_slot_count(4) == 4
    assert ring_slot_count(99) == 8
    assert ram_budget_bytes(64 * 1024 * 1024) == 64 * 1024 * 1024
    assert ram_budget_bytes(1024 * 1024 * 1024) == 256 * 1024 * 1024


def test_ram_ring_stays_inside_its_budget(tmp_path: Path):
    for index in range(6):
        path = tmp_path / f"ring-{index}.gray"
        path.write_bytes(b"x" * 100)
    removed = trim_ram_dir(tmp_path, 250)
    assert removed == 4
    assert sum(path.stat().st_size for path in tmp_path.iterdir()) <= 250


def test_vision_table_is_commercially_licensed():
    assert vision_model_for_vram_mib(0) == ""
    assert vision_model_for_vram_mib("none") == ""
    assert vision_model_for_vram_mib(4096) == "moondream"
    assert vision_model_for_vram_mib(8192) == "qwen2.5vl:3b"
    assert vision_model_for_vram_mib(12288) == "qwen2.5vl:7b"
    assert vision_model_license("moondream") == "Apache-2.0"
    assert vision_model_license("qwen2.5vl:7b") == "Apache-2.0"
    assert vision_model_license("") == "none"


def test_prompt_uses_watched_label_and_skips_heirs_pending():
    notes = [
        {
            "kind": "habit",
            "status": "accepted",
            "confidence": 0.9,
            "text": "Often in VS Code during work.",
            "tokens": tokenize("Often in VS Code during work."),
        },
        {
            "kind": "habit",
            "status": "pending",
            "confidence": 0.9,
            "text": "Stayed with play for 40 minutes before switching.",
            "tokens": tokenize("Stayed with play for 40 minutes before switching."),
        },
        {
            "kind": "habit",
            "status": "pending",
            "confidence": 0.4,
            "text": "Often in Terminal during work.",
            "tokens": tokenize("Often in Terminal during work."),
        },
    ]
    owner = attach_observer_context(
        "note#1",
        "How long do I stay with play?",
        audience="owner",
        notes=notes,
        enabled=True,
    )
    assert owner.relied is True
    assert owner.citation.endswith(WATCHED_SOURCE)
    assert "lower priority" in owner.block
    assert "VS Code" in owner.block
    assert "Terminal" not in owner.block
    heir = attach_observer_context(
        "",
        "How long do I stay with play?",
        audience="heir",
        notes=[note for note in notes if note["status"] == "accepted"],
        enabled=True,
    )
    assert heir.relied is False
    assert heir.citation == ""
    assert block_grounded_miss(True, False) is True
    assert block_grounded_miss(True, True) is False
    assert apply_source_label("vault#4", False) == "vault#4"
    off = attach_observer_context("vault#4", "play", notes=notes, enabled=False)
    assert off.block == ""
    assert off.citation == "vault#4"


def test_prompt_keeps_a_relevant_handful_and_caps_the_block():
    river = {
        "kind": "habit",
        "status": "pending",
        "confidence": 0.8,
        "created_at": "2026-10-01T00:00:00+00:00",
        "text": "The river road floods after spring rain.",
    }
    hades = {
        "kind": "habit",
        "status": "accepted",
        "confidence": 0.99,
        "created_at": "2026-11-01T00:00:00+00:00",
        "text": "Often in Hades during play.",
    }
    ranked = select_for_prompt([hades, river], "how is the river road")
    assert ranked[0]["text"].startswith("The river road")

    accepted = {
        "kind": "habit",
        "status": "accepted",
        "confidence": 0.2,
        "created_at": "2020-01-01T00:00:00+00:00",
        "text": "Often in the pottery shed on weekends.",
    }
    pending = {
        "kind": "habit",
        "status": "pending",
        "confidence": 0.99,
        "created_at": "2026-11-01T00:00:00+00:00",
        "text": "Often in the garage on weekends.",
    }
    tied = select_for_prompt([pending, accepted], "zzzz unique")
    assert tied[0]["status"] == "accepted"

    base = "Often near the river road after the spring rain"
    longer = {
        "kind": "heard",
        "status": "pending",
        "confidence": 0.9,
        "created_at": "2026-11-02T00:00:00+00:00",
        "text": base + " and the fields drain slowly",
    }
    shorter = {
        "kind": "heard",
        "status": "accepted",
        "confidence": 0.4,
        "created_at": "2026-10-02T00:00:00+00:00",
        "text": base,
    }
    deduped = select_for_prompt([longer, shorter], "river road")
    assert len(deduped) == 1
    assert deduped[0]["status"] == "accepted"

    long_text = "river " * 200
    clipped = select_for_prompt(
        [{"kind": "habit", "status": "accepted", "confidence": 0.9, "text": long_text, "created_at": "2026-11-02T00:00:00+00:00"}],
        "river",
    )
    assert len(clipped[0]["text"]) <= PROMPT_NOTE_CHARS

    many = []
    for index in range(40):
        many.append(
            {
                "kind": "habit",
                "status": "accepted",
                "confidence": 0.9,
                "created_at": f"2026-11-02T00:{index:02d}:00+00:00",
                "text": (f"unique{index} " * 70).strip(),
            }
        )
    secret = {
        "kind": "habit",
        "status": "pending",
        "confidence": 0.99,
        "created_at": "2026-11-02T03:00:00+00:00",
        "text": "The 60/40 money split stays with the owner.",
    }
    chosen = select_for_prompt(many, "unique0")
    block = observer_prompt_block(chosen)
    assert len(chosen) <= PROMPT_NOTE_LIMIT
    assert len(block) <= PROMPT_BLOCK_CHARS
    assert all(len(note["text"]) <= PROMPT_NOTE_CHARS for note in chosen)
    attached = attach_observer_context(
        "",
        "unique0",
        audience="owner",
        notes=many + [secret],
        enabled=True,
    )
    assert len(attached.block) <= PROMPT_BLOCK_CHARS
    assert attached.block.count("\n- ") <= PROMPT_NOTE_LIMIT
    heir = attach_observer_context(
        "",
        "money split",
        audience="heir",
        notes=many + [secret],
        enabled=True,
    )
    assert "60/40" not in heir.block
    assert "money split" not in heir.block


def _note_row(note_id: str, **overrides) -> dict:
    row = {
        "id": note_id,
        "source": "observer",
        "kind": "habit",
        "text": note_id,
        "confidence": 0.8,
        "created_at": "2026-01-01T00:00:00+00:00",
        "status": "pending",
        "fingerprint": note_id,
        "tokens": [],
        "topics": [],
    }
    row.update(overrides)
    return row


def test_heard_notes_merge_and_new_notes_are_rate_limited(tmp_path: Path):
    store = ObserverStore(tmp_path)
    moment = datetime.now(timezone.utc)
    short = "Watching/heard: the boss fight started in the north hall beside the river"
    first = store.add_transcript(
        {"channel": "system", "text": short, "ts": moment.isoformat()}
    )
    store.apply_feedback(first["note"]["id"], "thats_me")
    longer = short + " and then the gate opened slowly"
    merged = store.add_transcript(
        {
            "channel": "system",
            "text": longer,
            "ts": (moment + timedelta(seconds=2)).isoformat(),
        }
    )
    heard = [note for note in store.read_notes() if note["kind"] == "heard"]
    assert merged["reason"] == "merged"
    assert len(heard) == 1
    assert heard[0]["id"] == first["note"]["id"]
    assert heard[0]["status"] == "accepted"
    assert "gate opened" in heard[0]["text"]

    growing = ObserverStore(tmp_path / "growing")
    seed = growing.add_transcript(
        {"channel": "system", "text": short, "ts": moment.isoformat()}
    )
    assert seed["note"]["kind"] == "heard"
    extended = short + " and the music swelled as the gate opened"
    growing.add_transcript(
        {
            "channel": "system",
            "text": extended,
            "ts": (moment + timedelta(seconds=3)).isoformat(),
        }
    )
    huge = extended + (" more" * 4000)
    growing.add_transcript(
        {
            "channel": "system",
            "text": huge,
            "ts": (moment + timedelta(seconds=4)).isoformat(),
        }
    )
    lines = [note for note in growing.read_notes() if note["kind"] == "heard"]
    assert len(lines) == 1
    assert len(lines[0]["text"]) <= HEARD_TEXT_CAP
    assert lines[0]["text"].endswith("…")

    burst = ObserverStore(tmp_path / "burst")
    for index in range(NOTE_HOURLY_CAP + 5):
        burst.add_transcript(
            {
                "channel": "mic",
                "text": f"User said: alpha{index} remembers the maple kiln beside the river",
                "ts": (moment + timedelta(seconds=index)).isoformat(),
            }
        )
    assert len(burst.read_notes()) == NOTE_HOURLY_CAP


def test_compact_backs_up_then_keeps_accepted_notes(tmp_path: Path, monkeypatch, capsys):
    store = ObserverStore(tmp_path)
    heard = "Watching/heard: the boss fight started in the north hall and the gate opened"
    rows = [
        _note_row(
            "obs_accepted",
            status="accepted",
            text="Often in the pottery shed.",
            created_at="2020-01-01T00:00:00+00:00",
        ),
        _note_row(
            "obs_secret",
            text="The 60/40 money split stays with the owner.",
            created_at="2026-01-02T00:00:00+00:00",
        ),
    ]
    for extra_id, extra in (
        ("obs_heard_a", ""),
        ("obs_heard_b", " and the music swelled"),
        ("obs_heard_c", " and the music swelled as the rain began"),
    ):
        rows.append(
            _note_row(
                extra_id,
                kind="heard",
                text=heard + extra,
                created_at="2026-11-01T12:00:00+00:00",
            )
        )
    for index in range(30):
        rows.append(
            _note_row(
                f"obs_old_{index}",
                text=f"Pending fact number {index} about maple syrup and winter roads",
                created_at="2026-01-01T00:00:00+00:00",
            )
        )
    for index in range(4):
        rows.append(
            _note_row(
                f"obs_new_{index}",
                text=f"Recent kiln note {index} about the glaze",
                created_at="2026-11-01T08:00:00+00:00",
            )
        )
    store.notes_path.parent.mkdir(parents=True, exist_ok=True)
    store.notes_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    moment = datetime(2026, 11, 2, tzinfo=timezone.utc)
    first = store.compact_notes(now=moment)
    assert first["changed"] is True
    assert first["before"] == len(rows)
    assert Path(first["backup"]).is_file()
    backup_lines = [line for line in Path(first["backup"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(backup_lines) == len(rows)
    kept = store.read_notes()
    assert any(note["id"] == "obs_accepted" and note["status"] == "accepted" for note in kept)
    assert all(note["id"] != "obs_secret" for note in kept)
    assert sum(1 for note in kept if note["kind"] == "heard") == 1
    heard_note = next(note for note in kept if note["kind"] == "heard")
    assert "rain began" in heard_note["text"]
    assert any(note["id"] == "obs_new_0" for note in kept)
    assert all(not str(note["id"]).startswith("obs_old_") for note in kept)
    heir = store.export_for_audience(audience="heir")
    assert [note["id"] for note in heir["notes"]] == ["obs_accepted"]
    assert "60/40" not in json.dumps(heir)

    second = store.compact_notes(now=moment)
    assert second["changed"] is False
    assert second["backup"] == ""
    assert store.read_notes() == kept
    assert len(list(tmp_path.glob("notes.jsonl.*.bak"))) == 1

    monkeypatch.setenv("HEIRLOOM_OBSERVER_DIR", str(tmp_path))
    from observer_cli import main

    assert main(["compact"]) == 0
    assert "unchanged" in capsys.readouterr().out
    script = Path(__file__).resolve().parents[2] / "box" / "heirloom-box"
    text = script.read_text(encoding="utf-8")
    assert "observer compact" in text
    assert "status|pause|resume|digest|compact" in text
