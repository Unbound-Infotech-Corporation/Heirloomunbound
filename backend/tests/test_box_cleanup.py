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
    FIRST_PERSON,
    as_owner_voice,
    answer_grounded,
    blend_score,
    should_embed,
    approve_fields,
    card_from_model,
    choose_prompt,
    citations_that_ground,
    draft_card,
    embed_mode,
    entry_from_card,
    new_card_doc,
    new_prompt_doc,
    select_cards,
    spoken_reply,
    stored_prompt_status,
    visible_cards,
    waiting_items,
    why_from,
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
    assert payload["model"]["age_s"] == 0
    stale = assess_model_probe(
        {"ok": True, "reply": "pong", "checked_at": (now - timedelta(hours=2)).isoformat()},
        now=now,
    )
    assert stale["ok"] is False
    assert stale["age_s"] >= 7000
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
        assert "don't have that memory yet" in early["reply"]
        late = await answer_grounded("What did Dad teach you at the kitchen table?", [pending, approved], complete)
        assert late["why"][0]["card_id"] == "card_kept"
        assert late["why"][0]["title"] == "The kitchen table"
        assert "kitchen table" in late["why"][0]["story"]
        assert "1978" in late["reply"]

        async def partial_complete(system, user):
            del system, user
            return "I don't remember the year, but we sat at the kitchen table."

        partial = await answer_grounded(
            "What did Dad teach you at the kitchen table?",
            [approved],
            partial_complete,
        )
        assert "kitchen table" in partial["reply"]
        assert partial["why"][0]["card_id"] == "card_kept"

        async def refused(system, user):
            del system, user
            return "I don't remember anything about the kitchen table."

        blank = await answer_grounded(
            "What did Dad teach you at the kitchen table?",
            [approved],
            refused,
        )
        assert blank["why"] == []
        assert "don't have that memory yet" in blank["reply"]

        async def second_person(system, user):
            del system, user
            return "Your first lesson was at that kitchen table."

        owned = await answer_grounded(
            "What did Dad teach you at the kitchen table?",
            [approved],
            second_person,
        )
        assert owned["reply"].startswith("My first lesson")
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
        empty = choose_prompt([], today="2026-11-25", catalog=[])
        assert empty["persist"] is False
        assert empty["prompt"] is None

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

    def find(self, query, projection=None):
        del projection
        from lab_mode import _match_count

        return [row for row in self.rows if _match_count(row, query)]


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


def test_report_waiting_matches_open_nudges_not_just_daily_prompts():
    nudges = [
        {"status": "open", "kind": "weekly_biographer", "action_prompt": f"Tell me about day {i}", "nudge_id": f"n{i}", "created_at": "2026-10-01T00:00:00+00:00"}
        for i in range(8)
    ]
    nudges.append({"status": "open", "kind": "daily", "question": "What did you cook?", "nudge_id": "n8", "created_at": "2026-10-02T00:00:00+00:00"})
    nudges.append({"status": "open", "kind": "reflection", "action_prompt": "A thought from the shop", "nudge_id": "n9", "created_at": "2026-10-03T00:00:00+00:00"})
    nudges.append({"status": "open", "kind": "morning_brief", "action_prompt": "Good morning", "nudge_id": "brief", "created_at": "2026-10-04T00:00:00+00:00"})
    nudges.append({"status": "open", "kind": "note", "action_prompt": "", "question": "", "nudge_id": "empty", "created_at": "2026-10-05T00:00:00+00:00"})
    counts = activity_counts("2026-11-25", _DB({"daily_prompts": [], "nudges": nudges, "entries": []}))
    assert counts["unanswered_prompts"] == 10


def test_stopwords_do_not_cite_an_unrelated_card():
    car = {
        "status": "approved",
        "card_id": "car",
        "title": "First Car",
        "story": "My first car was a Chevy.",
        "people": [],
    }
    dog = {
        "status": "approved",
        "card_id": "dog",
        "title": "Duke",
        "story": "My dog was named Duke.",
        "people": ["Duke"],
    }
    picked = select_cards([car], "What was my dog named?")
    assert picked == []
    picked = select_cards([car, dog], "What was my dog named?")
    assert [card["card_id"] for card in picked] == ["dog"]
    reply = "My dog was named Duke."
    cited = citations_that_ground(reply, why_from([car, dog]))
    assert [card["card_id"] for card in cited] == ["dog"]
    assert citations_that_ground("I don't remember.", why_from([car, dog])) == []
    assert spoken_reply('search_archive("first car")') == ""
    assert as_owner_voice("Your first car was a Chevy.") == "My first car was a Chevy."
    assert as_owner_voice("I looked at your question.") == "I looked at your question."
    assert "I remember" in as_owner_voice("Maybe that's the dog you were thinking of?")
    lab = {
        "status": "approved",
        "card_id": "lab",
        "title": "Duke",
        "story": "A black lab named Duke.",
        "people": ["Duke"],
    }
    # 'dog' is not in the story and 'named' is a stopword, so keywords score 0.
    assert select_cards([lab, car], "What was my dog named?") == []
    assert select_cards([lab, car], "What was my dog called?") == []
    recalled = select_cards(
        [lab, car],
        "What was my dog named?",
        query_vector=[1.0, 0.0],
        vectors={"lab": [0.95, 0.05], "car": [0.0, 1.0]},
    )
    assert [card["card_id"] for card in recalled] == ["lab"]
    assert blend_score(0.0, 0.4) == 0.0
    assert should_embed([lab, car], "What was my dog named?") is True
    assert should_embed([dog], "What was my dog named?") is False
    assert should_embed([car, lab], "What was my first dog named?") is True
    weak = select_cards(
        [lab, car],
        "What was my first dog named?",
        query_vector=[1.0, 0.0],
        vectors={"lab": [0.95, 0.05], "car": [0.0, 1.0]},
    )
    assert weak[0]["card_id"] == "lab"
    assert should_embed([{"status": "pending", "card_id": "x"}], "What was my dog named?") is False
    paraphrase = citations_that_ground("My dog was named Duke.", why_from([car, lab]))
    assert [card["card_id"] for card in paraphrase] == ["lab"]
    assert "first person" in FIRST_PERSON.lower()
    twin = (ROOT / "backend" / "routers" / "twin.py").read_text(encoding="utf-8")
    assert "citations_that_ground" in twin
    assert "FIRST_PERSON" in twin


def test_a_custom_question_is_filed_and_a_stale_prompt_is_not_today():
    stale = [{
        "prompt_id": "prm_oct",
        "key": "old",
        "question": "What were you doing on October 29?",
        "status": "unanswered",
        "created_at": "2026-10-29T00:00:00+00:00",
    }]
    catalog = [{"key": "car", "label": "car", "question": "What was your first car?"}]
    today = choose_prompt(stale, today="2026-11-25", catalog=catalog)
    assert today["create"] is False
    assert today["prompt"]["prompt_id"] == "prm_oct"
    assert today["waiting"] == 1
    nudges = [
        {"nudge_id": f"n{i}", "status": "open", "kind": "weekly_biographer", "action_prompt": f"Question {i}", "created_at": f"2026-10-{i+1:02d}T00:00:00+00:00"}
        for i in range(10)
    ]
    queued = choose_prompt([], nudges, today="2026-11-25", catalog=catalog)
    assert queued["create"] is False
    assert queued["waiting"] == 10
    assert queued["prompt"]["prompt_id"] == "n0"
    custom = choose_prompt(
        stale,
        today="2026-11-25",
        catalog=catalog,
        chosen_key="dog",
        chosen_question="What was my dog named?",
    )
    assert stored_prompt_status(custom) == "draft"
    filed = new_prompt_doc("owner", custom["prompt"])
    filed["status"] = stored_prompt_status(custom)
    assert filed["prompt_id"]
    assert filed["status"] == "draft"
    assert waiting_items([filed]) == []
    answered_today = {
        "prompt_id": "prm_today",
        "key": "car",
        "question": "What was your first car?",
        "status": "answered",
        "created_at": "2026-11-25T08:00:00+00:00",
    }
    again = choose_prompt([answered_today, stale[0]], today="2026-11-25", catalog=catalog)
    assert again["create"] is False
    assert again["prompt"]["prompt_id"] == "prm_oct"
    draft_today = {**filed, "created_at": "2026-11-25T09:00:00+00:00", "status": "draft"}
    after_custom = choose_prompt([draft_today, stale[0]], today="2026-11-25", catalog=catalog)
    assert after_custom["create"] is False
    assert after_custom["prompt"]["prompt_id"] == "prm_oct"
    only_draft = choose_prompt([draft_today], today="2026-11-25", catalog=catalog)
    assert only_draft["create"] is True
    assert only_draft["prompt"]["question"] == "What was your first car?"


def test_dry_run_purge_does_not_need_the_lock(tmp_path):
    root = tmp_path / "observer"
    root.mkdir()
    (root / "notes.jsonl").write_text(
        json.dumps({
            "note_id": "n1",
            "status": "pending",
            "text": "noise",
            "created_at": "2026-11-01T00:00:00+00:00",
        }) + "\n",
        encoding="utf-8",
    )
    lock = root / ".store.lock"
    lock.write_text("")
    lock.chmod(0o444)
    root.chmod(0o555)
    store = ObserverStore(root)
    try:
        plan = store.purge_noise(apply=False)
        assert plan["applied"] is False
        assert plan["pending_notes"] == 1
        try:
            store.purge_noise(apply=True)
        except PermissionError as exc:
            assert "sudo heirloom-box observer purge --apply" in str(exc)
        else:
            raise AssertionError("apply should need a writable lock")
    finally:
        root.chmod(0o755)
        lock.chmod(0o644)


def test_upgrade_preserves_env_and_does_not_touch_drivers(tmp_path):
    install = (ROOT / "box" / "install.sh").read_text(encoding="utf-8")
    box = (ROOT / "box" / "heirloom-box").read_text(encoding="utf-8")
    assert "--upgrade" in install
    assert "Upgrade does not install or change the NVIDIA driver" in install
    assert "Upgrade keeps OLLAMA_TWIN_MODEL" in install
    assert "Upgrade keeps the chatterbox compose profile" in install
    wish = install.find("Upgrade keeps Observer on")
    model_pick = install.find('mib="$(vram_mib)"')
    assert 0 < wish < model_pick
    assert 'upsert_env HEIRLOOM_OBSERVER "1"' in install
    assert "cmd_upgrade" in box
    env = tmp_path / "box.env"
    env.write_text("OLLAMA_TWIN_MODEL=qwen2.5:14b\nHEIRLOOM_LLM_PROVIDER=ollama\n", encoding="utf-8")
    env.chmod(0o640)
    script = f"""
set -euo pipefail
UPGRADE=1
eval "$(sed -n '/^upsert_env()/,/^}}/p' '{ROOT / "box" / "install.sh"}')"
upsert_env OLLAMA_TWIN_MODEL qwen2.5:32b '{env}'
upsert_env WHISPER_MODEL base '{env}'
"""
    import subprocess
    subprocess.run(["bash", "-c", script], check=True)
    text = env.read_text(encoding="utf-8")
    assert "OLLAMA_TWIN_MODEL=qwen2.5:14b" in text
    assert "qwen2.5:32b" not in text
    assert "WHISPER_MODEL=base" in text
    assert oct(env.stat().st_mode & 0o777) == oct(0o640)


def test_voice_is_local_and_chatterbox_can_see_a_gpu(monkeypatch):
    from local_inference import whisper_runtime

    monkeypatch.setenv("WHISPER_MODEL", "base")
    monkeypatch.setenv("WHISPER_DEVICE", "cpu")
    assert whisper_runtime() == ("base", "cpu", "int8")
    monkeypatch.setenv("WHISPER_DEVICE", "cuda")
    assert whisper_runtime() == ("base", "cuda", "float16")
    api = (ROOT / "box" / "Dockerfile.api").read_text(encoding="utf-8")
    assert "faster-whisper==1.1.1" in api
    assert "av==15.1.0" in api
    assert "nvidia-cublas-cu12" in api
    compose = (ROOT / "box" / "docker-compose.yml").read_text(encoding="utf-8")
    assert "/whisper:/var/lib/heirloom/whisper" in compose
    gpu = (ROOT / "box" / "docker-compose.gpu.yml").read_text(encoding="utf-8")
    assert "api:" in gpu
    chatter = (ROOT / "box" / "chatterbox" / "Dockerfile").read_text(encoding="utf-8")
    assert "chatterbox-tts==" in chatter
    assert "cu124" in chatter
    import importlib.util
    path = ROOT / "box" / "chatterbox" / "server.py"
    spec = importlib.util.spec_from_file_location("heirloom_chatterbox_server", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.pick_device(True) == "cuda"
    assert module.pick_device(False) == "cpu"


def test_owner_words_are_the_only_memory_and_ungrounded_questions_decline():
    from routers.memory import owner_episode_text, sourced_facts
    from memory_cards import NO_MEMORY_YET, asks_for_personal_memory, cards_reached_through_archive
    from box_selftest import judge

    assert asks_for_personal_memory("What was my first car?") is True
    assert asks_for_personal_memory("Hello there") is False
    said = owner_episode_text([
        {"role": "user", "content": "I had soup."},
        {"role": "assistant", "content": "My first car was a rusty old Ford Escort."},
    ])
    assert "soup" in said
    assert "Ford" not in said
    kept = sourced_facts(
        [
            {"fact": "Has a blue Chevy", "source_entry_id": "ent_real"},
            {"fact": "Had a Ford Escort", "source_entry_id": "ent_invented"},
            {"fact": "No source"},
        ],
        {"ent_real"},
    )
    assert [row["fact"] for row in kept] == ["Has a blue Chevy"]
    car = {"status": "approved", "card_id": "car", "title": "First Car", "story": "My first car was a blue Chevy."}
    archive = "[MEMORY card=car] First Car\nMy first car was a blue Chevy.\n"
    assert cards_reached_through_archive(archive, [car])[0]["card_id"] == "car"
    rows = judge(
        "My first car was a blue Chevy.",
        "I drove a blue Chevy when I was young.",
        "My first car was a blue Chevy.",
        "A blue Chevy.",
        NO_MEMORY_YET,
        True,
    )
    assert all(ok for _name, ok in rows)

    import local_inference

    original = local_inference.ollama_embed_many

    async def embedded(texts, timeout=None, keep_alive="30m"):
        del timeout, keep_alive
        assert texts[0].startswith("search_query:")
        assert texts[1].startswith("search_document:")
        return [[1.0, 0.0], [0.66, 0.2], [0.1, 0.9]]

    async def _ask():
        young = {
            "status": "approved",
            "card_id": "car",
            "title": "First Car",
            "story": "My first car was a blue Chevy.",
            "people": [],
        }
        other = {
            "status": "approved",
            "card_id": "dog",
            "title": "Duke",
            "story": "A black lab named Duke.",
            "people": ["Duke"],
        }

        async def complete(system, user):
            del system, user
            return "I drove a blue Chevy when I was young."

        from memory_cards import answer_grounded

        return await answer_grounded("What did I drive when I was young?", [young, other], complete)

    local_inference.ollama_embed_many = embedded
    local_inference._embed_warm = True
    try:
        result = asyncio.run(_ask())
    finally:
        local_inference.ollama_embed_many = original
    assert "Chevy" in result["reply"]
    assert result["why"][0]["card_id"] == "car"


def test_upgrade_skips_installed_apt_and_replaces_a_real_observer_dir(tmp_path):
    install = ROOT / "box" / "install.sh"
    text = install.read_text(encoding="utf-8")
    assert "apt_install python3-opencv v4l-utils ffmpeg" in text
    assert "link_observer_spool" in text
    link = tmp_path / "heirloom-observer"
    target = tmp_path / "observer"
    link.mkdir()
    (link / "stale.txt").write_text("old spool\n", encoding="utf-8")
    script = f"""
set -euo pipefail
UPGRADE=1
log() {{ printf '%s\\n' "$*"; }}
eval "$(sed -n '/^apt_install()/,/^}}/p' '{install}')"
eval "$(sed -n '/^link_observer_spool()/,/^}}/p' '{install}')"
called=0
dpkg() {{ return 0; }}
apt-get() {{ echo apt-ran; exit 1; }}
apt_install python3-opencv v4l-utils ffmpeg
link_observer_spool '{link}' '{target}'
test -L '{link}'
test -f '{target}/stale.txt'
"""
    import subprocess
    subprocess.run(["bash", "-c", script], check=True)
    assert link.is_symlink()
    assert (target / "stale.txt").read_text(encoding="utf-8") == "old spool\n"
    empty = tmp_path / "empty-observer"
    empty.mkdir()
    empty_target = tmp_path / "empty-target"
    script_empty = f"""
set -euo pipefail
eval "$(sed -n '/^link_observer_spool()/,/^}}/p' '{install}')"
link_observer_spool '{empty}' '{empty_target}'
test -L '{empty}'
"""
    subprocess.run(["bash", "-c", script_empty], check=True)
    assert empty.is_symlink()
    kept = tmp_path / "mongo"
    kept.mkdir()
    kept.chmod(0o755)
    script_keep = f"""
set -euo pipefail
log() {{ :; }}
run() {{ "$@"; }}
eval "$(sed -n '/^ensure_data_dir()/,/^}}/p' '{install}')"
ensure_data_dir '{kept}'
"""
    subprocess.run(["bash", "-c", script_keep], check=True)
    assert oct(kept.stat().st_mode & 0o777) == oct(0o755)
    paused = subprocess.run(
        ["bash", "-c", f"""
systemctl() {{ printf '%s\\n' "$*"; }}
log() {{ :; }}
UPGRADE=1
DRY_RUN=0
eval "$(sed -n '/^pause_caretaker_for_upgrade()/,/^}}/p' '{install}')"
pause_caretaker_for_upgrade
exit 1
"""],
        capture_output=True,
        text=True,
    )
    assert "stop heirloom-caretaker.timer" in paused.stdout
    assert "start heirloom-caretaker.timer" in paused.stdout
