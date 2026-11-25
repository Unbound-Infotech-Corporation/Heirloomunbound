"""Streamed twin chat must not raise UnboundLocalError on why_cards."""
from __future__ import annotations

import ast
import json
import os
import sys
import types
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "heirloom")
os.environ["HEIRLOOM_LLM_PROVIDER"] = "ollama"

ROOT = Path(__file__).resolve().parents[1]


def _stub_emergent() -> None:
    if "emergentintegrations.llm.chat" in sys.modules:
        return
    package = types.ModuleType("emergentintegrations")
    llm = types.ModuleType("emergentintegrations.llm")
    chat = types.ModuleType("emergentintegrations.llm.chat")

    class LlmChat:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        def with_model(self, *args, **kwargs):
            del args, kwargs
            return self

        def with_tools(self, *args, **kwargs):
            del args, kwargs
            return self

    class UserMessage:
        def __init__(self, text: str = ""):
            self.text = text

    class StreamDone:
        pass

    class TextDelta:
        def __init__(self, text: str = ""):
            self.text = text

    chat.LlmChat = LlmChat
    chat.UserMessage = UserMessage
    chat.StreamDone = StreamDone
    chat.TextDelta = TextDelta
    package.llm = llm
    llm.chat = chat
    sys.modules["emergentintegrations"] = package
    sys.modules["emergentintegrations.llm"] = llm
    sys.modules["emergentintegrations.llm.chat"] = chat


_stub_emergent()


def _names_bound(fn: ast.AST) -> set[str]:
    found: set[str] = set()

    def walk(node: ast.AST, top: bool = False) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not top:
            return
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            found.add(node.target.id)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            found.add(node.target.id)
        for child in ast.iter_child_nodes(node):
            walk(child, False)

    walk(fn, True)
    return found


def test_streamed_generators_do_not_rebind_closed_over_names():
    """An assignment inside the generator makes the name local and the read fails."""
    tree = ast.parse((ROOT / "routers" / "twin.py").read_text(encoding="utf-8"))
    offenders: list[str] = []
    for outer in ast.walk(tree):
        if not isinstance(outer, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        outer_bound = _names_bound(outer)
        for child in ast.walk(outer):
            if child is outer or not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if child.name not in {"gen_local", "gen", "music_stream", "skill_stream", "crisis_stream"}:
                continue
            rebound = _names_bound(child) & outer_bound
            # gen() has its own `result` from execute_tool. That name is assigned before it is read.
            rebound.discard("result")
            if rebound:
                offenders.append(f"{outer.name}/{child.name}:{sorted(rebound)}")
    assert offenders == []


def test_streamed_twin_message_returns_text(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from brain_council import TurnOutcome
    from deps import get_current_user
    import abilities as ab
    import routers.twin as twin

    class Cursor:
        def sort(self, *args, **kwargs):
            del args, kwargs
            return self

        def limit(self, *args, **kwargs):
            del args, kwargs
            return self

        async def to_list(self, length=0):
            del length
            return []

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class Conversations:
        def __init__(self):
            self.rows = {}

        async def find_one(self, query, projection=None):
            del projection
            return self.rows.get(query.get("conversation_id"))

        async def insert_one(self, doc):
            self.rows[doc["conversation_id"]] = {k: v for k, v in doc.items() if k != "_id"}

        async def update_one(self, query, update):
            row = self.rows[query["conversation_id"]]
            each = ((update.get("$push") or {}).get("messages") or {}).get("$each") or []
            row.setdefault("messages", []).extend(each)

    class Collection:
        def find(self, *args, **kwargs):
            del args, kwargs
            return Cursor()

    class Database:
        def __init__(self):
            self.conversations = Conversations()
            self.entries = Collection()
            self.skills = Collection()

        def __getattr__(self, name):
            return Collection()

    fake = Database()
    monkeypatch.setattr(twin, "db", fake)
    monkeypatch.setattr(twin.ab, "enabled_ability_ids", lambda user_id: _async([]))

    async def _async(value):
        return value

    monkeypatch.setattr(ab, "enabled_ability_ids", lambda user_id: _async([]))

    async def no_specialist(*args, **kwargs):
        del args, kwargs
        return {}

    async def no_crisis(*args, **kwargs):
        del args, kwargs
        return None

    calls = []

    async def complete(*args, **kwargs):
        calls.append(args)
        text = str(args[1] if len(args) > 1 else args[0]).lower()
        if "wedding" in text:
            reply = "I remember we danced to At Last by Etta James."
        elif "grow up" in text:
            reply = "I grew up in Longview, Texas."
        elif "job" in text:
            reply = "My first job was at a local grocery store."
        else:
            reply = "My first car was a rusty old Ford Escort."
        return TurnOutcome(text=reply, meta={"model": "qwen2.5:14b"}, label="local")

    import twin_runtime
    import twin_safety
    import brain_council

    monkeypatch.setattr(twin_runtime, "load_specialist_turn", no_specialist)
    monkeypatch.setattr(twin_safety, "intercept_crisis", no_crisis)
    monkeypatch.setattr(brain_council, "complete_turn", complete)

    async def grounding(user_id, question, **kwargs):
        del user_id, kwargs
        if "dog" not in (question or "").lower():
            return "", []
        from memory_cards import grounding_block, why_from

        card = {
            "card_id": "duke",
            "title": "Duke",
            "story": "a black lab named Duke",
            "people": ["Duke"],
            "status": "approved",
        }
        return grounding_block([card]), why_from([card])

    import routers.memory_loop as memory_loop

    monkeypatch.setattr(memory_loop, "grounding_for_turn", grounding)

    async def quiet(*args, **kwargs):
        del args, kwargs
        return {}

    monkeypatch.setattr(twin, "rate_limit", quiet)
    monkeypatch.setattr(twin, "build_memory_pack", quiet)
    monkeypatch.setattr(twin, "get_active_persona", quiet)
    monkeypatch.setattr(twin, "maybe_summarise_episode", quiet)
    monkeypatch.setattr(twin, "live_publish_turn", quiet)

    async def user():
        return {"user_id": "owner", "audience": "owner", "name": "Pat", "safe_topics": []}

    app = FastAPI()
    app.include_router(twin.router, prefix="/api")
    app.dependency_overrides[get_current_user] = user
    client = TestClient(app)
    started = client.post("/api/twin/start", json={})
    assert started.status_code == 200
    conversation_id = started.json()["conversation_id"]
    response = client.post(
        "/api/twin/message",
        json={"conversation_id": conversation_id, "message": "Hello there"},
    )
    assert response.status_code == 200
    body = response.text
    assert "event: error" not in body
    assert "cannot access local variable" not in body
    assert "Ford Escort" in body
    assert "event: done" in body
    ungrounded = client.post(
        "/api/twin/message",
        json={"conversation_id": conversation_id, "message": "What was my first car?"},
    )
    assert ungrounded.status_code == 200
    denied = ungrounded.text
    assert "don't have that memory yet" in denied
    assert "Ford" not in denied
    assert "event: error" not in denied
    for question, invented in (
        ("What song did we dance to at my wedding?", "Etta"),
        ("Where did I grow up?", "Longview"),
        ("What was my first job?", "grocery"),
    ):
        later = client.post(
            "/api/twin/message",
            json={"conversation_id": conversation_id, "message": question},
        )
        assert later.status_code == 200
        body = later.text
        assert "don't have that memory yet" in body
        assert invented not in body
        assert "event: error" not in body
    assert len(calls) == 1
    dog = client.post(
        "/api/twin/message",
        json={"conversation_id": conversation_id, "message": "What was my dog named?"},
    )
    assert dog.status_code == 200
    assert "event: error" not in dog.text
    assert len(calls) == 2
    prompt = json.dumps(calls[1][0])
    assert "Ford Escort" not in prompt
    assert "Etta" not in prompt
    assert "Do not add traits" in prompt
