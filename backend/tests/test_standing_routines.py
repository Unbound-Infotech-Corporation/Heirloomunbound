"""Standing Twin routines — skip-when-empty, owner-only, no invented biography."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from standing_routines import (
    apply_enabled_updates,
    compose_morning_brief,
    compose_routine,
    compose_sealed_letter_nudge,
    compose_weekly_biographer,
    due_kinds,
    morning_has_signal,
    normalize_routines,
    period_key,
    pick_archive_gap,
    routines_allowed,
    routines_from_user,
    routines_public,
    skip_reason,
)

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


def test_defaults_are_off_consent():
    state = normalize_routines(None)
    assert state["morning_brief"]["enabled"] is False
    assert state["weekly_biographer"]["enabled"] is False
    assert state["sealed_letter_nudge"]["enabled"] is False
    assert routines_from_user({})["morning_brief"]["enabled"] is False


def test_normalize_accepts_bool_or_object():
    state = normalize_routines({"morning_brief": True, "weekly_biographer": {"enabled": "yes", "last_run": "2026-W36"}})
    assert state["morning_brief"]["enabled"] is True
    assert state["weekly_biographer"]["enabled"] is True
    assert state["weekly_biographer"]["last_run"] == "2026-W36"
    assert state["sealed_letter_nudge"]["enabled"] is False


def test_due_kinds_respects_period_and_enabled():
    day = period_key("morning_brief", NOW)
    week = period_key("weekly_biographer", NOW)
    state = {
        "morning_brief": {"enabled": True, "last_run": None},
        "weekly_biographer": {"enabled": True, "last_run": week},
        "sealed_letter_nudge": {"enabled": False, "last_run": None},
    }
    assert due_kinds(state, NOW) == ["morning_brief"]
    state["morning_brief"]["last_run"] = day
    assert due_kinds(state, NOW) == []


def test_morning_skip_when_empty():
    assert morning_has_signal({}) is False
    assert morning_has_signal({"overdue": [], "due_today": [], "recent_titles": []}) is False
    assert compose_morning_brief({}) is None
    assert compose_routine("morning_brief", {}) is None
    assert skip_reason("morning_brief", {}) == "empty"


def test_morning_fires_from_reminders_only_and_stays_grounded():
    snap = {
        "overdue": [{"text": "Call the dentist"}],
        "due_today": [{"text": "Pack the lake bag"}],
    }
    brief = compose_morning_brief(snap)
    assert brief is not None
    assert brief["kind"] == "morning_brief"
    assert "Call the dentist" in brief["body"]
    assert "Pack the lake bag" in brief["body"]
    assert "Vermont" not in brief["body"]
    assert "Elias" not in brief["body"]
    assert brief["action_href"] == "/reminders"


def test_morning_mentions_only_filed_titles():
    brief = compose_morning_brief({"recent_titles": [{"title": "The lake house"}]})
    assert brief is not None
    assert "The lake house" in brief["body"]
    assert "son named" not in brief["body"].lower()


def test_weekly_skips_empty_archive():
    assert compose_weekly_biographer({"entry_count": 0, "fact_kinds": []}) is None
    assert skip_reason("weekly_biographer", {"entry_count": 0}) == "empty_archive"


def test_weekly_asks_a_real_gap_without_inventing():
    snap = {
        "entry_count": 3,
        "entry_titles": [{"title": "Work at the mill", "tags": ["work"]}],
        "entry_tags": [["work"]],
        "fact_kinds": ["work"],
    }
    gap = pick_archive_gap(snap)
    assert gap is not None
    assert gap["key"] != "work"
    prompt = compose_weekly_biographer(snap)
    assert prompt is not None
    assert gap["label"].lower() in prompt["body"].lower()
    assert "will not invent" in prompt["body"]
    assert "Elias" not in prompt["body"]


def test_weekly_skips_when_gaps_are_covered():
    titles = [{"title": g["label"]} for g in (
        {"label": "Childhood home"},
        {"label": "First love"},
        {"label": "Fatherhood / parenting"},
        {"label": "Your work / craft"},
        {"label": "Faith / meaning"},
        {"label": "A friendship"},
        {"label": "A loss"},
    )]
    snap = {"entry_count": 20, "entry_titles": titles, "entry_tags": [], "fact_kinds": []}
    assert pick_archive_gap(snap) is None
    assert compose_weekly_biographer(snap) is None
    assert skip_reason("weekly_biographer", snap) == "no_gap"


def test_sealed_letter_skips_when_nothing_waiting():
    assert compose_sealed_letter_nudge({}) is None
    assert skip_reason("sealed_letter_nudge", {}) == "nothing_waiting"


def test_sealed_letter_nudge_uses_draft_title_only():
    nudge = compose_sealed_letter_nudge({"draft_letters": [{"title": "For Sam"}]})
    assert nudge is not None
    assert "For Sam" in nudge["body"]
    assert nudge["action_href"] == "/letters"
    assert "invent" not in nudge["body"] or "will not finish" in nudge["body"]


def test_sealed_letter_nudge_names_heir_without_a_letter():
    nudge = compose_sealed_letter_nudge({"heirs_without_letter": [{"name": "Maya"}]})
    assert nudge is not None
    assert "Maya" in nudge["body"]
    assert "will not invent" in nudge["body"]


def test_owner_only_fence():
    assert routines_allowed(audience="owner") is True
    assert routines_allowed(audience="heir") is False
    assert routines_allowed(audience="caller") is False
    assert routines_allowed(audience="owner", heir_surface=True) is False
    assert routines_allowed(audience=None, heir_surface=False) is True


def test_apply_enabled_updates_preserves_last_run():
    current = normalize_routines({"morning_brief": {"enabled": False, "last_run": "2026-09-12"}})
    nxt = apply_enabled_updates(current, {"morning_brief": True})
    assert nxt["morning_brief"]["enabled"] is True
    assert nxt["morning_brief"]["last_run"] == "2026-09-12"


def test_routines_public_is_owner_marked():
    pub = routines_public({"standing_routines": {"morning_brief": True}})
    assert pub["routines_owner_only"] is True
    assert pub["standing_routines"]["morning_brief"]["enabled"] is True
    assert "Empty mornings stay silent" in pub["standing_routines"]["morning_brief"]["description"]


def test_heir_portal_has_no_standing_routines():
    portal = (ROOT / "frontend" / "src" / "pages" / "HeirPortal.jsx").read_text(encoding="utf-8")
    heir_router = (ROOT / "backend" / "routers" / "heir_portal.py").read_text(encoding="utf-8")
    for src in (portal, heir_router):
        assert "/nudges/routines" not in src
        assert "standing_routines" not in src
        assert "morning_brief" not in src
        assert "weekly_biographer" not in src
        assert "run_due_routines" not in src


def test_memory_and_settings_expose_toggles():
    memory = (ROOT / "frontend" / "src" / "pages" / "Memory.jsx").read_text(encoding="utf-8")
    settings = (ROOT / "frontend" / "src" / "pages" / "Settings.jsx").read_text(encoding="utf-8")
    assert "StandingRoutinesFields" in memory
    assert "StandingRoutinesFields" in settings
    assert 'api.put("/nudges/routines"' in memory
    assert 'api.put("/nudges/routines"' in settings


def test_today_stays_quiet_on_empty_morning():
    today = (ROOT / "frontend" / "src" / "pages" / "Today.jsx").read_text(encoding="utf-8")
    assert "shouldShowNudge" in today
    assert "quiet" in today


def test_run_due_routines_empty_morning_writes_no_nudge(monkeypatch):
    import asyncio

    import routers.nudges as nudges

    inserted: list[dict] = []
    updates: list[tuple] = []

    async def fake_gather(_db, _user_id, _now):
        return {}

    class _Users:
        async def update_one(self, query, update):
            updates.append((query, update))

    class _Nudges:
        async def find_one(self, _q, _p=None):
            return None

        async def insert_one(self, doc):
            inserted.append(doc)

        def find(self, _q, _p=None):
            class _C:
                async def to_list(self, length=None):
                    return []

            return _C()

    class _DB:
        users = _Users()
        nudges = _Nudges()

    monkeypatch.setattr(nudges, "gather_routine_snapshot", fake_gather)
    monkeypatch.setattr(nudges, "db", _DB())

    user = {
        "user_id": "owner_1",
        "name": "Ada",
        "standing_routines": {"morning_brief": {"enabled": True, "last_run": None}},
    }
    result = asyncio.run(nudges.run_due_routines(user, now=NOW, audience="owner"))
    assert result["quiet"] is True
    assert result["fired"] == []
    assert result["skipped"] == [{"kind": "morning_brief", "reason": "empty"}]
    assert inserted == []
    assert updates  # last_run still recorded so we do not nag again today


def test_run_due_routines_heir_fence_is_silent(monkeypatch):
    import asyncio

    import routers.nudges as nudges

    called = {"gather": False}

    async def fake_gather(_db, _user_id, _now):
        called["gather"] = True
        return {"overdue": [{"text": "secret"}]}

    monkeypatch.setattr(nudges, "gather_routine_snapshot", fake_gather)
    user = {
        "user_id": "owner_1",
        "standing_routines": {"morning_brief": {"enabled": True}},
    }
    result = asyncio.run(nudges.run_due_routines(user, now=NOW, audience="heir"))
    assert result["quiet"] is True
    assert result["skipped"][0]["reason"] == "heir_fence"
    assert called["gather"] is False

    portal = asyncio.run(nudges.run_due_routines(user, now=NOW, heir_surface=True))
    assert portal["skipped"][0]["reason"] == "heir_fence"


def test_run_due_routines_fires_grounded_morning(monkeypatch):
    import asyncio

    import routers.nudges as nudges

    inserted: list[dict] = []

    async def fake_gather(_db, _user_id, _now):
        return {"overdue": [{"text": "Call the dentist"}]}

    class _Users:
        async def update_one(self, _q, _u):
            return None

    class _Nudges:
        async def find_one(self, _q, _p=None):
            return None

        async def insert_one(self, doc):
            inserted.append(doc)

        def find(self, _q, _p=None):
            class _C:
                async def to_list(self, length=None):
                    return []

            return _C()

    class _DB:
        users = _Users()
        nudges = _Nudges()

    monkeypatch.setattr(nudges, "gather_routine_snapshot", fake_gather)
    monkeypatch.setattr(nudges, "db", _DB())

    user = {
        "user_id": "owner_1",
        "standing_routines": {"morning_brief": {"enabled": True}},
    }
    result = asyncio.run(nudges.run_due_routines(user, now=NOW))
    assert result["quiet"] is False
    assert len(result["fired"]) == 1
    assert result["fired"][0]["kind"] == "morning_brief"
    assert "Call the dentist" in result["fired"][0]["body"]
    assert inserted[0]["source"] == "routine"


def test_nudges_router_reuses_collection_not_a_new_platform():
    src = (ROOT / "backend" / "routers" / "nudges.py").read_text(encoding="utf-8")
    assert "run_due_routines" in src
    assert '"/routines/check"' in src
    assert "source\": \"routine\"" in src or 'source": "routine"' in src
    assert "heir_fence" in src
