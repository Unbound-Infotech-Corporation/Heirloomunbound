"""Death Governance mode — stewardship profile for the AI twin."""
from __future__ import annotations

import asyncio

import pytest


def test_normalize_mode_and_policy():
    import death_governance as dg

    assert dg.normalize_mode("death_governance") == dg.MODE_DEATH_GOVERNANCE
    assert dg.normalize_mode("weird") == dg.MODE_LIVING
    p = dg.normalize_policy({"disclose_nature": False, "extra": 1})
    assert p["disclose_nature"] is False
    assert p["grief_aware"] is True
    assert "extra" not in p


def test_death_governance_prompt_contains_stewardship_rules():
    import death_governance as dg

    section = dg.build_death_governance_section(
        "Ada",
        policy={"disclose_nature": True, "refuse_invented_wishes": True},
        governance_pack="Heirs: Sam (child, released).",
        for_heir=True,
    )
    assert "DEATH GOVERNANCE MODE" in section
    assert "invent" in section.lower() or "Never invent" in section
    assert "Sam" in section
    assert "heir" in section.lower() or "released" in section.lower()


def test_filter_tools_blocks_writes():
    import death_governance as dg

    schemas = [
        {"function": {"name": "search_archive"}},
        {"function": {"name": "save_memory"}},
        {"function": {"name": "set_reminder"}},
        {"function": {"name": "list_recent_memories"}},
    ]
    out = dg.filter_tools_for_mode(schemas, dg.MODE_DEATH_GOVERNANCE)
    names = {s["function"]["name"] for s in out}
    assert names == {"search_archive", "list_recent_memories"}
    assert dg.filter_tools_for_mode(schemas, dg.MODE_LIVING) == schemas


def test_twin_system_includes_governance_section():
    from routers.twin import _build_twin_system
    import death_governance as dg

    section = dg.build_death_governance_section("Ada", governance_pack="pack-here")
    prompt = _build_twin_system(
        "Ada",
        memory_blob="",
        archive_blob="[VALUE] Kindness\nBe kind.",
        skills_blob="do-laundry",
        authenticity_mode="retrieve_only",
        death_governance_section=section,
    )
    assert "DEATH GOVERNANCE MODE" in prompt
    assert "pack-here" in prompt
    assert "skills paused" in prompt
    assert "posthumous steward" in prompt


def test_resolve_mode_forced_when_locked(monkeypatch):
    import death_governance as dg

    async def _locked(_uid):
        return True

    monkeypatch.setattr("routers.executor_lock.is_legacy_locked", _locked)

    async def _run():
        mode = await dg.resolve_operating_mode({"user_id": "u1", "twin_operating_mode": "living"})
        assert mode == dg.MODE_DEATH_GOVERNANCE
        auth = await dg.effective_authenticity({"user_id": "u1", "authenticity_mode": "balanced"}, mode)
        assert auth == "retrieve_only"

    asyncio.get_event_loop().run_until_complete(_run())


def test_activate_lock_sets_death_governance(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from routers import executor_lock as el

    calls = {"user_set": None}

    class FakeResult:
        pass

    class FakeLocks:
        async def find_one(self, *a, **k):
            return {
                "user_id": "u1",
                "enabled": True,
                "status": "pending",
                "unlocks_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            }

        async def update_one(self, filt, update, upsert=False):
            return FakeResult()

    class FakeUsers:
        async def update_one(self, filt, update):
            calls["user_set"] = update.get("$set")
            return FakeResult()

        async def find_one(self, *a, **k):
            return {"user_id": "u1"}

    class FakeHeirsCursor:
        async def to_list(self, length):
            return []

    class FakeHeirs:
        def find(self, *a, **k):
            return FakeHeirsCursor()

    class FakeDB:
        executor_locks = FakeLocks()
        users = FakeUsers()
        heirs = FakeHeirs()

    monkeypatch.setattr(el, "db", FakeDB())

    async def _run():
        out = await el.activate_lock_if_due("u1")
        assert out["status"] == "locked"
        assert calls["user_set"]["twin_operating_mode"] == "death_governance"
        assert calls["user_set"]["authenticity_mode"] == "retrieve_only"

    asyncio.get_event_loop().run_until_complete(_run())
