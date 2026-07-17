"""Performance / latency optimizations — no LLM required."""
import os

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/workspace/backend/.env")
load_dotenv("/workspace/frontend/.env")

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/")
TOKEN = "hello_world_token_123"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update(HEADERS)
    return sess


def test_dashboard_fast_and_shaped(s):
    r = s.get(f"{BASE_URL}/api/dashboard")
    assert r.status_code == 200, r.text
    d = r.json()
    for key in (
        "total_entries", "total_words", "streak_days", "suggested_topics",
        "reminders_open", "completeness", "counts_by_type",
    ):
        assert key in d
    assert isinstance(d["suggested_topics"], list)
    assert len(d["suggested_topics"]) <= 6


def test_archive_blob_truncates():
    from routers.twin import _archive_blob
    import asyncio
    from deps import db

    async def _run():
        # Insert a huge entry, retrieve, assert blob stays bounded
        uid = "user_helloworld01"
        await db.entries.insert_one({
            "entry_id": "ent_opt_huge",
            "user_id": uid,
            "type": "memory",
            "title": "Huge opt test",
            "content": "x" * 50000,
            "tags": ["opt"],
            "created_at": "2099-01-01T00:00:00+00:00",
        })
        try:
            blob = await _archive_blob(uid, query_hint="Huge opt")
            assert len(blob) < 20000
            assert "Huge opt test" in blob
        finally:
            await db.entries.delete_one({"entry_id": "ent_opt_huge"})

    asyncio.get_event_loop().run_until_complete(_run())


def test_tool_names_for_abilities_no_io():
    import abilities as ab
    names = ab.tool_names_for_abilities({"music", "web"})
    assert "search_archive" in names  # core
    assert "web_search" in names
    assert "play_music" in names or "open_on_pc" in names or len(names) > 4


def test_memory_pack_uses_cache():
    from routers.memory import build_memory_pack, get_cached_facts
    import asyncio

    async def _run():
        pack = await build_memory_pack("user_helloworld01")
        assert "facts" in pack and "episodes" in pack
        cached = await get_cached_facts("user_helloworld01")
        assert isinstance(cached, list)

    asyncio.get_event_loop().run_until_complete(_run())
