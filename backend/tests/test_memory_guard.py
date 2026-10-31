"""Heir and caller memory stays out of the prompt because the query filters it."""
from __future__ import annotations

import os

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "heirloom_test")

import asyncio

import pytest

from memory_guard import (
    embed_local,
    hybrid_rerank,
    matches_document,
    mongo_query,
    cosine_unit,
)
from routers.memory import build_memory_pack, format_memory_pack_for_prompt
from twin_pack import format_passages
from twin_runtime import archive_passages, build_brain_pack
from twin_tools import exec_search_archive


PRIVATE = "OWNER_PRIVATE_VAULT_CODE"
GIFT = "We fished at Lake Erie"
CALLER = "The shop on Main Street opens at nine"


def _docs():
    return [
        {
            "entry_id": "priv",
            "user_id": "u",
            "title": "vault",
            "content": PRIVATE,
            "visibility": "owner",
            "tags": ["secret"],
            "type": "memory",
            "created_at": "2026-02-02",
        },
        {
            "entry_id": "gift",
            "user_id": "u",
            "title": "lake",
            "content": GIFT,
            "visibility": "heir",
            "tags": ["family"],
            "type": "story",
            "created_at": "2026-02-01",
        },
        {
            "entry_id": "public",
            "user_id": "u",
            "title": "shop",
            "content": CALLER,
            "visibility": "caller",
            "tags": [],
            "type": "memory",
            "created_at": "2026-01-01",
        },
        {
            "entry_id": "legacy",
            "user_id": "u",
            "title": "porch",
            "content": "The porch light stays on",
            "tags": [],
            "type": "memory",
            "created_at": "2025-12-01",
        },
    ]


class FakeCursor:
    def __init__(self, docs):
        self.docs = list(docs)

    def sort(self, key, direction=-1):
        self.docs.sort(key=lambda row: row.get(key) or "", reverse=int(direction) < 0)
        return self

    def limit(self, count):
        self.docs = self.docs[: int(count)]
        return self

    async def to_list(self, length=None):
        if length is None:
            return list(self.docs)
        return list(self.docs[:length])


class FakeColl:
    def __init__(self, docs):
        self.docs = list(docs)
        self.queries: list[dict] = []

    def find(self, query, projection=None):
        self.queries.append(query)
        matched = [row for row in self.docs if matches_document(query, row)]
        return FakeCursor(matched)


class FakeDb:
    def __init__(self, entries, facts, episodes):
        self.entries = FakeColl(entries)
        self.memory_facts = FakeColl(facts)
        self.memory_episodes = FakeColl(episodes)


def _facts():
    return [
        {"user_id": "u", "fact": PRIVATE, "visibility": "owner", "source_entry_id": "priv"},
        {"user_id": "u", "fact": "Grew up near the lake", "visibility": "heir", "source_entry_id": "gift"},
    ]


def _episodes():
    return [
        {"user_id": "u", "summary": PRIVATE, "visibility": "owner", "created_at": "2026-02-02"},
        {"user_id": "u", "summary": "Talked about the lake", "visibility": "heir", "created_at": "2026-02-01"},
        {"user_id": "u", "summary": "Unmarked owner chat", "created_at": "2026-01-15"},
    ]


def test_visibility_is_inside_the_query():
    heir = mongo_query("u", "heir", kind="entry")
    assert "visibility" in str(heir)
    assert matches_document(heir, {"user_id": "u", "visibility": "heir", "content": GIFT})
    assert matches_document(heir, {"user_id": "u", "content": "legacy gift"})
    assert not matches_document(heir, {"user_id": "u", "visibility": "owner", "content": PRIVATE})
    episode = mongo_query("u", "heir", kind="episode")
    assert not matches_document(episode, {"user_id": "u", "summary": "unmarked"})
    assert matches_document(episode, {"user_id": "u", "visibility": "heir", "summary": "ok"})
    caller = mongo_query("u", "caller", kind="entry")
    assert matches_document(caller, {"user_id": "u", "visibility": "caller"})
    assert not matches_document(caller, {"user_id": "u", "visibility": "heir"})
    owner = mongo_query("u", "owner", kind="entry", extra={"$or": [{"title": "x"}]})
    assert "$nin" not in str(owner)
    assert owner["user_id"] == "u"


def test_fact_extraction_never_reads_private_entries(monkeypatch):
    fake = FakeDb(_docs(), [], [])
    from routers import memory as mem

    monkeypatch.setattr(mem, "db", fake)

    async def _run():
        return await mem._gather_corpus("u")

    text, count = asyncio.run(_run())
    assert PRIVATE not in text
    assert "Lake Erie" in text
    assert count == 3
    assert "visibility" in str(fake.entries.queries[0])


def test_hybrid_rerank_prefers_a_paraphrase():
    docs = [
        {"id": "far", "text": "quarterly revenue forecast increased sharply"},
        {"id": "near", "text": "yeah I reckon we head out early"},
    ]
    ranked = hybrid_rerank(docs, "yeah I reckon we leave early", text_of=lambda row: row["text"])
    assert ranked[0]["id"] == "near"
    near = embed_local("yeah I reckon we head out early")
    far = embed_local("quarterly revenue forecast increased sharply")
    query = embed_local("yeah I reckon we leave early")
    assert cosine_unit(query, near) > cosine_unit(query, far)


def test_heir_prompt_never_receives_private_memory(monkeypatch):
    fake = FakeDb(_docs(), _facts(), _episodes())
    import twin_runtime as tr
    from routers import memory as mem

    monkeypatch.setattr(tr, "db", fake)
    monkeypatch.setattr(mem, "db", fake)

    async def _run():
        pack = await build_memory_pack("u", "lake", audience="heir")
        passages = await archive_passages("u", "lake", audience="heir")
        prompt = format_memory_pack_for_prompt(pack) + "\n" + format_passages(passages)
        caller_passages = await archive_passages("u", "shop", audience="caller")
        caller_prompt = format_passages(caller_passages)
        search = await exec_search_archive("u", {"query": "vault"}, audience="heir")
        return prompt, caller_prompt, search

    import twin_tools
    monkeypatch.setattr(twin_tools, "db", fake)
    prompt, caller_prompt, search = asyncio.run(_run())
    assert PRIVATE not in prompt
    assert "Lake Erie" in prompt
    assert "Grew up near the lake" in prompt
    assert "Talked about the lake" in prompt
    assert "Unmarked owner chat" not in prompt
    assert PRIVATE not in caller_prompt
    assert "Lake Erie" not in caller_prompt
    assert "Main Street" in caller_prompt
    assert PRIVATE not in search["summary"]
    assert fake.entries.queries
    assert all("visibility" in str(query) for query in fake.entries.queries)
    assert all("visibility" in str(query) for query in fake.memory_facts.queries)
    assert all("visibility" in str(query) for query in fake.memory_episodes.queries)


def test_client_pack_cannot_smuggle_private_text(monkeypatch):
    fake = FakeDb(_docs(), _facts(), _episodes())
    import abilities as ab
    import twin_runtime as tr
    from routers import memory as mem

    monkeypatch.setattr(tr, "db", fake)
    monkeypatch.setattr(mem, "db", fake)

    async def fake_enabled(_uid):
        return set()

    async def fake_skills(_uid):
        return ""

    async def fake_persona(_uid, _user):
        return None

    async def fake_sessions(*_args, **_kwargs):
        return 0

    monkeypatch.setattr(ab, "enabled_ability_ids", fake_enabled)
    monkeypatch.setattr(tr, "skills_blob", fake_skills)
    monkeypatch.setattr(tr, "get_active_persona", fake_persona)
    monkeypatch.setattr("twin_safety.sessions_today_count", fake_sessions)

    user = {"user_id": "u", "name": "C L", "studio_models": {"twin": "ollama"}}
    conv = {"conversation_id": "c1", "messages": []}
    packed = {
        "passages": [{"id": "smuggle", "text": PRIVATE, "kind": "memory"}],
        "facts": [{"fact": PRIVATE, "source_capture_id": "priv"}],
        "audience": "heir",
        "grounded": True,
    }

    async def _run():
        return await build_brain_pack(
            user,
            "tell me about the lake",
            conversation=conv,
            audience="heir",
            twin_pack=packed,
        )

    pack = asyncio.run(_run())
    assert PRIVATE not in pack.system
    assert "Lake Erie" in pack.system
