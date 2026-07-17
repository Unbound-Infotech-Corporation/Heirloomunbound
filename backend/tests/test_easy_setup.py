"""Easy Setup — grandmother-friendly status helpers."""
from __future__ import annotations

import asyncio


def test_easy_status_counts_steps(monkeypatch):
    from routers import easy_setup as es

    class FakeCursor:
        def __init__(self, n):
            self.n = n

        async def to_list(self, length):
            return []

    class FakeDB:
        class heirs:
            @staticmethod
            async def count_documents(*a, **k):
                return 1

        class entries:
            @staticmethod
            async def count_documents(*a, **k):
                return 2

        class executor_locks:
            @staticmethod
            async def find_one(*a, **k):
                return {
                    "enabled": True,
                    "executor_email": "trusted@example.com",
                    "executor_name": "Pat",
                }

    monkeypatch.setattr(es, "db", FakeDB())

    async def _run():
        status = await es._build_status({
            "user_id": "u1",
            "name": "Ada",
            "easy_setup_style_chosen": True,
            "twin_operating_mode": "living",
            "authenticity_mode": "retrieve_only",
        })
        assert status["done_count"] == 4
        assert status["all_done"] is True
        assert status["has_executor"] is True

    asyncio.get_event_loop().run_until_complete(_run())


def test_easy_style_maps_practice_forever(monkeypatch):
    from routers import easy_setup as es
    from fastapi import HTTPException

    captured = {}

    class FakeUsers:
        async def update_one(self, filt, update):
            captured["set"] = update["$set"]

        async def find_one(self, *a, **k):
            return {
                "user_id": "u1",
                "easy_setup_style_chosen": True,
                "twin_operating_mode": "death_governance",
                "authenticity_mode": "retrieve_only",
            }

    class FakeDB:
        users = FakeUsers()

        class heirs:
            @staticmethod
            async def count_documents(*a, **k):
                return 0

        class entries:
            @staticmethod
            async def count_documents(*a, **k):
                return 0

        class executor_locks:
            @staticmethod
            async def find_one(*a, **k):
                return {}

    async def _unlocked(_):
        return False

    monkeypatch.setattr(es, "db", FakeDB())
    monkeypatch.setattr("routers.executor_lock.is_legacy_locked", _unlocked)

    async def _run():
        from routers.easy_setup import EasyStyle, easy_set_style
        # Call underlying logic via the style endpoint body mapping
        # by invoking the route function with a fake user dependency isn't trivial;
        # exercise the update mapping by replaying the branch.
        style = "practice_forever"
        import death_governance as dg
        update = {"easy_setup_style_chosen": True, "easy_setup_style": style}
        update["authenticity_mode"] = "retrieve_only"
        update["twin_operating_mode"] = dg.MODE_DEATH_GOVERNANCE
        assert update["twin_operating_mode"] == "death_governance"

        # Invalid style should 400
        try:
            await easy_set_style(EasyStyle(style="nope"), {"user_id": "u1"})
            assert False, "expected HTTPException"
        except HTTPException as e:
            assert e.status_code == 400

        out = await easy_set_style(EasyStyle(style="practice_forever"), {"user_id": "u1"})
        assert captured["set"]["twin_operating_mode"] == "death_governance"
        assert out["authenticity_mode"] == "retrieve_only"

    asyncio.get_event_loop().run_until_complete(_run())
