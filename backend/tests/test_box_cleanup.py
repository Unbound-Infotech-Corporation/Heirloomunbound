"""Observer path and retention, honest health, daily report counts, memory loop."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from box_health import assess_model_probe, health_payload, overall_status, probe_local_chat
from caretaker import observer_opt_actions, parse_systemctl_show
from lab_mode import LabStore, activity_counts, publish_report, render_report, turns_on_day
from memory_cards import (
    answer_grounded,
    approve_fields,
    card_from_model,
    choose_prompt,
    draft_card,
    embed_mode,
    entry_from_card,
    new_card_doc,
    new_prompt_doc,
    select_cards,
    visible_cards,
    waiting_items,
)
from observer_store import read_observer_opt_in
from observer_capture import canonical_ram_dir
from observer_prompt import notes_for_prompt
from observer_store import (
    NOTE_DAILY_CAP,
    ObserverStore,
    honest_signal,
    status_public,
    unit_is_crash_looping,
)


ROOT = Path(__file__).resolve().parents[2]


def test_opt_in_actions_and_unit_snapshot():
    assert observer_opt_actions(wished=False, etc_present=True, env_on=True) == ["disable"]
    assert observer_opt_actions(wished=True, etc_present=False, env_on=False) == ["enable"]
    assert observer_opt_actions(wished=True, etc_present=True, env_on=True) == []
    assert observer_opt_actions(wished=None, etc_present=False, env_on=False) == []
    parsed = parse_systemctl_show("NRestarts=12\nActiveState=activating\nResult=exit-code\n")
    assert parsed["n_restarts"] == 12
    assert parsed["active"] == "activating"


def test_unit_writes_the_real_runtime_directory_not_the_symlink():
    unit = (ROOT / "box/observer/heirloom-observer.service").read_text(encoding="utf-8")
    line = next(row for row in unit.splitlines() if row.startswith("ReadWritePaths="))
    assert "/run/heirloom-observer" not in line
    assert "/run/heirloom" in line
    assert "/var/lib/heirloom/observer" in line
    tmpfiles = (ROOT / "box/observer/heirloom-observer.tmpfiles").read_text(encoding="utf-8")
    assert "L /run/heirloom-observer" in tmpfiles
    assert "d /run/heirloom-observer" not in tmpfiles
    assert canonical_ram_dir("/run/heirloom-observer") == Path("/run/heirloom/observer")
    assert canonical_ram_dir("/run/heirloom-observer/audio") == Path("/run/heirloom/observer/audio")
    assert canonical_ram_dir("/run/heirloom/observer") == Path("/run/heirloom/observer")


def test_retention_and_purge_keep_accepted_notes(tmp_path):
    store = ObserverStore(tmp_path)
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    store.add_observations([
        {"ts": old, "activity": "work", "app": "Terminal", "title": "Terminal", "text": "old caption"},
    ])
    fresh = datetime.now(timezone.utc).isoformat()
    created = store.add_observations([
        {"ts": fresh, "activity": "play", "game": "Hades", "title": "Hades", "text": "you died"},
        {"ts": fresh, "activity": "play", "game": "Hades", "title": "Hades", "text": "retry"},
        {"ts": fresh, "activity": "play", "game": "Hades", "title": "Hades", "text": "you died"},
        {"ts": fresh, "activity": "play", "game": "Hades", "title": "Hades", "text": "retry"},
    ])
    assert created
    kept = created[0]
    store.apply_feedback(kept["id"], "thats_me")
    noise = []
    for index in range(NOTE_DAILY_CAP + 3):
        noise.append({
            "id": f"obs_extra_{index}",
            "kind": "habit",
            "status": "pending",
            "text": f"noise note {index} about a different window",
            "created_at": fresh,
            "fingerprint": f"fp-{index}",
            "tokens": [f"noise{index}"],
        })
    from observer_store import _append_jsonl

    for row in noise:
        _append_jsonl(store.notes_path, row)
    _append_jsonl(store.observations_path, {"ts": fresh, "text": "caption that should go"})
    plan = store.purge_noise(apply=False)
    assert plan["applied"] is False
    assert plan["pending_notes"] >= 1
    assert plan["accepted_notes"] >= 1
    assert store.read_notes()
    applied = store.purge_noise(apply=True)
    assert applied["applied"] is True
    left = store.read_notes()
    assert left
    assert all(note["status"] == "accepted" for note in left)
    assert store.read_notes()
    assert not store.observations_path.is_file() or store.observations_path.read_text(encoding="utf-8").strip() == ""


def test_pending_notes_never_enter_the_prompt():
    notes = [
        {"status": "pending", "confidence": 0.99, "text": "secret pending", "source": "observer"},
        {"status": "accepted", "confidence": 0.2, "text": "filed fact", "source": "observer"},
    ]
    picked = notes_for_prompt(notes, audience="owner")
    assert [note["text"] for note in picked] == ["filed fact"]


def test_stale_status_and_crash_loop_are_not_ok():
    now = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
    fresh_moment = now - timedelta(seconds=30)
    stale_moment = now - timedelta(days=3)
    signal, fresh = honest_signal("ok", enabled=True, moment=fresh_moment, now=now, unit={})
    assert signal == "ok" and fresh is True
    signal, fresh = honest_signal("ok", enabled=True, moment=stale_moment, now=now, unit={})
    assert signal == "stale" and fresh is False
    looping = {
        "n_restarts": 500,
        "active": "activating",
        "result": "exit-code",
        "checked_at": now.isoformat(),
    }
    assert unit_is_crash_looping(looping, now=now) is True
    signal, fresh = honest_signal("ok", enabled=True, moment=fresh_moment, now=now, unit=looping)
    assert signal == "failing" and fresh is False
    signal, fresh = honest_signal("ok", enabled=False, moment=stale_moment, now=now, unit=looping)
    assert signal == "off" and fresh is False
    quiet = overall_status(
        observer={"enabled": False, "signal": "off", "fresh": False, "unit": "failing"},
        model={"ok": True},
        box=True,
    )
    assert quiet == "ok"
    running = {"n_restarts": 500, "active": "active", "checked_at": now.isoformat()}
    assert unit_is_crash_looping(running, now=now) is False
    status = overall_status(observer={"enabled": True, "signal": "stale", "fresh": False, "unit": ""}, model={"ok": True}, box=True)
    assert status == "degraded"
    status = overall_status(observer={"enabled": True, "signal": "failing", "fresh": False, "unit": "failing"}, model={"ok": True}, box=True)
    assert status == "failing"


def test_health_payload_uses_the_probe_and_refuses_a_cloud_host(tmp_path, monkeypatch):
    monkeypatch.setenv("HEIRLOOM_BOX", "1")
    monkeypatch.setenv("HEIRLOOM_OBSERVER", "0")
    monkeypatch.setenv("HEIRLOOM_OBSERVER_DIR", str(tmp_path))
    now = datetime.now(timezone.utc)
    payload = health_payload(
        now=now,
        model_probe=lambda: {"ok": True, "model": "qwen2.5:14b", "reply": "pong", "checked_at": now.isoformat(), "error": ""},
    )
    assert payload["status"] == "ok"
    assert payload["model"]["ok"] is True
    stale = assess_model_probe(
        {"ok": True, "reply": "pong", "checked_at": (now - timedelta(hours=2)).isoformat()},
        now=now,
    )
    assert stale["ok"] is False
    refused = probe_local_chat(base_url="https://api.openai.com/v1", model="gpt-4", now=now)
    assert refused["ok"] is False
    dead = health_payload(
        now=now,
        model_probe=lambda: {"ok": False, "model": "qwen2.5:14b", "reply": "", "checked_at": now.isoformat(), "error": "down"},
    )
    assert dead["status"] == "degraded"


def test_status_file_older_than_a_few_minutes_is_not_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("HEIRLOOM_OBSERVER", "1")
    store = ObserverStore(tmp_path)
    store.write_status({
        "signal": "ok",
        "fps": 2,
        "source": "network",
        "mode": "auto",
        "updated_at": (datetime.now(timezone.utc) - timedelta(days=4)).isoformat(),
    })
    public = status_public(store)
    assert public["signal"] == "stale"
    assert public["fresh"] is False


def test_report_splits_today_from_all_time():
    day = "2026-11-25"
    turns = [
        {"ts": "2026-11-25T01:00:00+00:00", "route": "twin", "error": "Local twin (Ollama) failed"},
        {"ts": "2026-11-20T01:00:00+00:00", "route": "twin", "error": None},
    ]
    assert len(turns_on_day(turns, day)) == 1
    text = render_report(
        turns,
        day=day,
        extras={
            "memories_today": 1,
            "memories_all": 4,
            "conversations_today": 1,
            "conversations_all": 3,
            "observer_cards_today": 2,
            "observer_cards_all": 9,
            "unanswered_prompts": 0,
        },
    )
    today, _, all_time = text.partition("## All-time")
    assert "Failed replies: 1" in today
    assert "New memories: 1" in today
    assert "Observer cards: 2" in today
    assert "Turns: 2" in all_time
    assert "Memories: 4" in all_time
    assert "everything on the box" in all_time


def test_interview_becomes_an_approved_memory_and_grounds_the_answer():
    async def _run():
        seen = {}

        async def complete(system, user):
            seen["system"] = system
            seen["user"] = user
            if "JSON" in system:
                return json.dumps({
                    "title": "The kitchen table",
                    "era": "1978",
                    "people": ["Dad"],
                    "story": "Dad and I sat at the kitchen table in 1978 and he taught me to measure twice.",
                })
            assert "card_kept" in user
            assert "pending secret" not in user
            return "We sat at that kitchen table in 1978. Dad told me to measure twice."

        prompts = []
        choice = choose_prompt(prompts, today="2026-11-25")
        assert choice["create"] is True
        stored = new_prompt_doc("owner", choice["prompt"])
        prompts.append(stored)
        again = choose_prompt(prompts, today="2026-11-25")
        assert again["create"] is False
        assert again["prompt"]["prompt_id"] == stored["prompt_id"]
        piled = waiting_items(prompts + [
            {"prompt_id": "prm_old", "key": "loss", "question": "Tell us about someone you lost", "status": "unanswered", "created_at": "2026-11-01T00:00:00+00:00"},
        ])
        assert piled[0]["prompt_id"] == "prm_old"
        next_choice = choose_prompt(prompts + piled[:1], today="2026-11-25")
        assert next_choice["create"] is False
        assert next_choice["waiting"] >= 1

        draft = await draft_card(
            "Dad and I sat at the kitchen table in 1978 and he taught me to measure twice.",
            stored["question"],
            complete,
        )
        assert draft["status"] == "pending"
        assert "Dad" in draft["people"]
        invented = card_from_model("We had soup.", "A meal?", '{"title":"Paris","era":"1999","people":["a stranger"],"story":"I moved to Paris and bought a boat."}')
        assert invented["story"] == "We had soup."
        assert invented["people"] == []

        pending = new_card_doc("owner", {**draft, "title": "Not yet"}, prompt_id=stored["prompt_id"])
        pending["story"] = "pending secret about the lake"
        pending["title"] = "pending secret"
        approved_src = new_card_doc("owner", draft, prompt_id=stored["prompt_id"])
        approved_src["card_id"] = "card_kept"
        approved = approve_fields(approved_src, {"title": "The kitchen table"})
        early = await answer_grounded("What did Dad teach you at the table?", [pending], complete)
        assert early["why"] == []
        assert "don't have an approved memory" in early["reply"]
        late = await answer_grounded("What did Dad teach you at the kitchen table?", [pending, approved], complete)
        assert late["why"] == [{"card_id": "card_kept", "title": "The kitchen table"}]
        assert "1978" in late["reply"]
        entry = entry_from_card({**approved, "user_id": "owner"})
        assert entry["visibility"] == "owner"
        assert entry["type"] == "memory"
        assert select_cards([pending], "Dad table") == []
        assert embed_mode(listed=[], pull_ok=False, pull_error="missing") == "keyword"
        assert embed_mode(listed=["nomic-embed-text:latest"], pull_ok=False) == "embed"
        private = [{
            "status": "approved",
            "visibility": "owner",
            "card_id": "card_kept",
            "title": "The kitchen table",
            "story": "Dad and I sat at the kitchen table in 1978.",
            "question": stored["question"],
        }]
        assert visible_cards(private, audience="heir") == []
        assert select_cards(visible_cards(private, audience="heir"), "kitchen table") == []
        chosen = choose_prompt(
            prompts,
            today="2026-11-25",
            chosen_key="childhood",
            chosen_question="Describe the home you grew up in.",
        )
        assert chosen["persist"] is False
        assert chosen["prompt"]["prompt_id"] == ""

    asyncio.run(_run())


def test_opt_in_file_overrides_the_container_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HEIRLOOM_OBSERVER_DIR", str(tmp_path))
    monkeypatch.setenv("HEIRLOOM_OBSERVER", "0")
    assert read_observer_opt_in(tmp_path) is None
    from observer_store import observer_enabled

    assert observer_enabled() is False
    (tmp_path / "owner-opt-in.json").write_text('{"enabled": true}\n', encoding="utf-8")
    assert observer_enabled() is True
    (tmp_path / "owner-opt-in.json").write_text('{"enabled": false}\n', encoding="utf-8")
    monkeypatch.setenv("HEIRLOOM_OBSERVER", "1")
    assert observer_enabled() is False


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def count_documents(self, query):
        from lab_mode import _match_count

        return sum(1 for row in self.rows if _match_count(row, query))


class _DB:
    def __init__(self, tables):
        self.tables = tables

    def __getitem__(self, name):
        return _Rows(self.tables.get(name, []))


def test_activity_counts_read_the_day_and_the_pile():
    db = _DB({
        "entries": [
            {"type": "memory", "created_at": "2026-11-25T01:00:00+00:00"},
            {"type": "memory", "created_at": "2026-11-01T01:00:00+00:00"},
            {"type": "story", "created_at": "2026-11-25T01:00:00+00:00"},
        ],
        "conversations": [
            {"created_at": "2026-11-25T02:00:00+00:00"},
            {"created_at": "2026-11-01T02:00:00+00:00"},
        ],
        "daily_prompts": [
            {"status": "unanswered"},
            {"status": "answered"},
        ],
    })
    counts = activity_counts("2026-11-25", db)
    assert counts["memories_today"] == 1
    assert counts["memories_all"] == 2
    assert counts["conversations_today"] == 1
    assert counts["conversations_all"] == 2
    assert counts["unanswered_prompts"] == 1


def test_publish_report_uses_activity_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "lab_mode.activity_counts",
        lambda day: {
            "memories_today": 2,
            "memories_all": 5,
            "conversations_today": 1,
            "conversations_all": 3,
            "unanswered_prompts": 4,
        },
    )
    store = LabStore(tmp_path / "lab")
    store.append({"turn_id": "lab_z", "ts": "2026-11-25T04:00:00+00:00", "route": "twin"})
    path = Path(publish_report(store, tmp_path / "reports", now=datetime(2026, 11, 25, tzinfo=timezone.utc))["path"])
    text = path.read_text(encoding="utf-8")
    assert "New memories: 2" in text
    assert "Memories: 5" in text
    assert "Unanswered prompts: 4" in text
