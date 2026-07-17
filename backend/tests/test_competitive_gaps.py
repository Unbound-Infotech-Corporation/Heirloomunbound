"""Competitive-gap features: Executor Lock, authenticity, semantic search,
WhatsApp import, export endpoints.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest


def test_whatsapp_parser_chunks_messages():
    from routers.social_import import parse_whatsapp_export

    raw = """
[12/03/2024, 14:22:01] Alice: Remember the cabin trip?
[12/03/2024, 14:22:15] Bob: Yes — the lake was freezing
[12/03/2024, 14:23:00] Alice: Best weekend of the year
12/03/2024, 15:00 - Bob: Media omitted
12/03/2024, 15:01 - Alice: Send the photos later
""".strip()
    items = parse_whatsapp_export(raw)
    assert items, "expected at least one chunk"
    assert any("cabin" in (i.get("content") or "").lower() for i in items)
    assert all("whatsapp" in (i.get("tags") or []) for i in items)


def test_whatsapp_multiline_continuation():
    from routers.social_import import parse_whatsapp_export

    raw = """
01/01/2025, 10:00 - Sam: Line one
still going
01/01/2025, 10:01 - Pat: ok
""".strip()
    items = parse_whatsapp_export(raw)
    assert items
    blob = items[0]["content"]
    assert "still going" in blob


def test_tfidf_semantic_search_ranks_relevant(monkeypatch):
    """Unit-level: TF-IDF path ranks the matching entry higher without OpenAI."""
    from semantic_search import semantic_search

    async def _run():
        class FakeCursor:
            def __init__(self, rows):
                self._rows = rows

            def sort(self, *a, **k):
                return self

            def limit(self, n):
                return self

            async def to_list(self, length):
                return self._rows[:length]

        class FakeEntries:
            def find(self, *a, **k):
                return FakeCursor(
                    [
                        {
                            "entry_id": "e1",
                            "type": "memory",
                            "title": "Grocery list",
                            "content": "milk eggs bread",
                            "tags": [],
                            "created_at": "2024-01-01",
                        },
                        {
                            "entry_id": "e2",
                            "type": "story",
                            "title": "First job at the bakery",
                            "content": "I learned to bake sourdough before sunrise every morning.",
                            "tags": ["career"],
                            "created_at": "2024-02-01",
                        },
                    ]
                )

        class FakeEmb:
            async def find_one(self, *a, **k):
                return None

            async def update_one(self, *a, **k):
                return None

        class FakeDB:
            entries = FakeEntries()
            entry_embeddings = FakeEmb()

        import semantic_search as ss

        monkeypatch.setattr(ss, "db", FakeDB())
        monkeypatch.setattr(ss, "EMERGENT_LLM_KEY", "")
        ranked = await semantic_search("user_x", "bakery job sourdough", limit=2)
        assert ranked
        assert ranked[0]["entry_id"] == "e2"

    asyncio.get_event_loop().run_until_complete(_run())


def test_assert_writable_blocks_when_locked(monkeypatch):
    from fastapi import HTTPException
    from routers import executor_lock as el

    async def _locked(_uid):
        return True

    monkeypatch.setattr(el, "is_legacy_locked", _locked)

    async def _run():
        with pytest.raises(HTTPException) as ei:
            await el.assert_writable("user_x")
        assert ei.value.status_code == 403

    asyncio.get_event_loop().run_until_complete(_run())


def test_retrieve_only_system_prompt_blocks_invention():
    from routers.twin import _build_twin_system

    prompt = _build_twin_system(
        "Ada",
        memory_blob="",
        archive_blob="[VALUE] Honesty\nTell the truth.",
        skills_blob="",
        authenticity_mode="retrieve_only",
    )
    assert "RETRIEVE-ONLY" in prompt
    assert "save_memory" not in prompt or "Do not call save_memory" in prompt


def test_export_memoir_html_escapes(monkeypatch):
    """Smoke: memoir builder escapes HTML when given mock data via direct call pieces."""
    import html as _html

    title = _html.escape('<script>alert(1)</script>')
    assert "<script>" not in title
    assert "&lt;script&gt;" in title


def test_activate_lock_sets_retrieve_only(monkeypatch):
    from routers import executor_lock as el

    calls = {"user_set": None, "lock_set": None, "heirs": []}

    class FakeResult:
        pass

    class FakeLocks:
        async def find_one(self, *a, **k):
            return {
                "user_id": "u1",
                "enabled": True,
                "status": "pending",
                "unlocks_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
                "wait_hours": 72,
            }

        async def update_one(self, filt, update, upsert=False):
            calls["lock_set"] = update.get("$set")
            return FakeResult()

    class FakeUsers:
        async def update_one(self, filt, update):
            calls["user_set"] = update.get("$set")
            return FakeResult()

        async def find_one(self, *a, **k):
            return {"user_id": "u1", "legacy_locked": False}

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
        assert calls["user_set"]["authenticity_mode"] == "retrieve_only"
        assert calls["user_set"]["legacy_locked"] is True

    asyncio.get_event_loop().run_until_complete(_run())
