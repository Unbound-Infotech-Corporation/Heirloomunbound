"""Local brain strategies. Odysseus is mocked. No cloud model is called."""
from __future__ import annotations

import asyncio
import json

from brain_council import clear_answer_meta, complete_turn, is_simple_chat, needs_research
from brain_route import brain_status, clear_caches
from box_health import health_payload
from odysseus_client import OdysseusDraft


def _completion(text: str, model: str) -> dict:
    return {"model": model, "choices": [{"message": {"content": text}}]}


def _env(monkeypatch, *, strategy: str = "single", odysseus: bool = False) -> None:
    monkeypatch.setenv("HEIRLOOM_BOX", "1")
    monkeypatch.setenv("HEIRLOOM_BRAIN_DISABLE_STORE", "1")
    monkeypatch.setenv("OLLAMA_TWIN_MODEL", "qwen2.5:14b")
    monkeypatch.setenv("HEIRLOOM_BRAIN_STRATEGY", strategy)
    monkeypatch.delenv("HEIRLOOM_BRAIN_URL", raising=False)
    monkeypatch.delenv("HEIRLOOM_BRAIN_TOKEN", raising=False)
    monkeypatch.delenv("HEIRLOOM_ODYSSEUS", raising=False)
    monkeypatch.delenv("HEIRLOOM_ODYSSEUS_URL", raising=False)
    monkeypatch.delenv("HEIRLOOM_ODYSSEUS_TOKEN", raising=False)
    monkeypatch.delenv("HEIRLOOM_ODYSSEUS_TOKEN_FILE", raising=False)
    if odysseus:
        monkeypatch.setenv("HEIRLOOM_ODYSSEUS", "1")
        monkeypatch.setenv("HEIRLOOM_ODYSSEUS_URL", "http://192.168.0.110:7011")
        monkeypatch.setenv("HEIRLOOM_ODYSSEUS_TOKEN", "ody_supersecretvalue")
    clear_caches()
    clear_answer_meta()


def test_simple_chat_and_research_cues():
    assert is_simple_chat("thanks") is True
    assert is_simple_chat("why did we move across the state?") is False
    assert needs_research("what is the latest news") is True
    assert needs_research("thanks") is False


def test_single_is_the_default_and_skips_odysseus(monkeypatch):
    _env(monkeypatch, strategy="single", odysseus=True)
    seen = {"n": 0, "asks": []}

    async def poster(url, body, timeout):
        seen["n"] += 1
        assert "ody_supersecretvalue" not in json.dumps(body)
        return _completion("one model", body["model"])

    async def ask(kind, text, timeout):
        seen["asks"].append((kind, text))
        return OdysseusDraft(text="should not run", ok=True)

    async def _run():
        return await complete_turn(
            [{"role": "user", "content": "what is the latest news"}],
            "what is the latest news",
            audience="owner",
            poster=poster,
            odysseus_ask=ask,
        )

    outcome = asyncio.run(_run())
    assert outcome.text == "one model"
    assert seen["n"] == 1
    assert seen["asks"] == []
    assert outcome.meta["strategy"] == "single"
    assert outcome.meta["path"] == "fast"
    assert outcome.meta["contributors"][0]["name"] == "box"
    assert outcome.meta["latency_ms"] >= 0
    blob = json.dumps(health_payload())
    assert "ody_supersecretvalue" not in blob
    assert health_payload()["brain"]["answer"]["strategy"] == "single"


def test_simple_chat_stays_on_one_model_under_ensemble(monkeypatch):
    _env(monkeypatch, strategy="ensemble_synthesis", odysseus=True)
    seen = {"n": 0}

    async def poster(url, body, timeout):
        seen["n"] += 1
        return _completion("quick", body["model"])

    async def ask(kind, text, timeout):
        raise AssertionError("simple chat must not call Odysseus")

    async def _run():
        return await complete_turn(
            [{"role": "user", "content": "thanks"}],
            "thanks",
            audience="owner",
            poster=poster,
            odysseus_ask=ask,
        )

    outcome = asyncio.run(_run())
    assert outcome.text == "quick"
    assert seen["n"] == 1
    assert outcome.meta["path"] == "fast"
    assert outcome.meta["strategy"] == "ensemble_synthesis"


def test_ensemble_synthesizes_and_hides_memories_from_odysseus(monkeypatch):
    _env(monkeypatch, strategy="ensemble_synthesis", odysseus=True)
    monkeypatch.setenv("HEIRLOOM_BRAIN_URL", "http://192.168.0.50:11434")
    monkeypatch.setenv("HEIRLOOM_BRAIN_MODEL", "llama3.3:70b")
    monkeypatch.setenv("HEIRLOOM_BRAIN_TOKEN", "brain-secret-token")
    clear_caches()

    async def probe_remote(url, headers, timeout):
        assert "brain-secret-token" not in url
        return True

    monkeypatch.setattr("brain_route.probe_remote", probe_remote)
    asked = []

    async def poster(url, body, timeout):
        blob = json.dumps(body)
        if "Untrusted local drafts" in blob:
            return _completion("synthesized", body["model"])
        if "192.168.0.50" in url:
            return _completion("from bigdeal", "llama3.3:70b")
        return _completion("from box", "qwen2.5:14b")

    async def ask(kind, text, timeout):
        asked.append((kind, text))
        return OdysseusDraft(text="ody draft", ok=True, model="qwen", via="chat")

    question = "why did the family move across the state when I was young?"
    messages = [
        {"role": "system", "content": "SECRET VAULT FACT about the owner"},
        {"role": "user", "content": question},
    ]

    async def _run():
        return await complete_turn(
            messages,
            question,
            audience="owner",
            poster=poster,
            odysseus_ask=ask,
        )

    outcome = asyncio.run(_run())
    assert outcome.text == "synthesized"
    assert asked == [("chat", question)]
    assert "SECRET VAULT FACT" not in asked[0][1]
    names = [item["name"] for item in outcome.meta["contributors"]]
    assert names == ["bigdeal", "box", "odysseus"]
    assert outcome.meta["path"] == "ensemble"
    assert outcome.meta["latency_ms"] >= 0
    blob = json.dumps(outcome.meta) + json.dumps(brain_status())
    assert "ody_supersecretvalue" not in blob
    assert "brain-secret-token" not in blob


def test_judge_returns_the_picked_draft(monkeypatch):
    _env(monkeypatch, strategy="judge_pick_best", odysseus=True)
    monkeypatch.setenv("HEIRLOOM_BRAIN_URL", "http://192.168.0.50:11434")
    clear_caches()

    async def probe_remote(url, headers, timeout):
        return True

    monkeypatch.setattr("brain_route.probe_remote", probe_remote)

    async def poster(url, body, timeout):
        system = body["messages"][0]["content"]
        if "You pick the best" in system:
            return _completion("PICK: odysseus", body["model"])
        if "192.168.0.50" in url:
            return _completion("from bigdeal", "llama3.3:70b")
        return _completion("from box", "qwen2.5:14b")

    async def ask(kind, text, timeout):
        return OdysseusDraft(text="from odysseus", ok=True, model="qwen", via="chat")

    question = "explain how the north field drains after a week of rain in the spring"

    async def _run():
        return await complete_turn(
            [{"role": "system", "content": "SECRET VAULT FACT"}, {"role": "user", "content": question}],
            question,
            audience="heir",
            poster=poster,
            odysseus_ask=ask,
        )

    outcome = asyncio.run(_run())
    assert outcome.text == "from odysseus"
    assert outcome.meta["picked"] == "odysseus"
    assert outcome.meta["path"] == "judge"
    assert "PICK:" not in outcome.text


def test_odysseus_down_still_answers(monkeypatch):
    _env(monkeypatch, strategy="ensemble_synthesis", odysseus=True)
    monkeypatch.setenv("HEIRLOOM_BRAIN_URL", "http://192.168.0.50:11434")
    clear_caches()

    async def probe_remote(url, headers, timeout):
        return False

    monkeypatch.setattr("brain_route.probe_remote", probe_remote)

    async def poster(url, body, timeout):
        if "Untrusted local drafts" in json.dumps(body):
            return _completion("box only", body["model"])
        return _completion("from box", "qwen2.5:14b")

    async def ask(kind, text, timeout):
        return OdysseusDraft(ok=False, error="unavailable")

    async def _run():
        return await complete_turn(
            [{"role": "user", "content": "why did we move across the state last spring?"}],
            "why did we move across the state last spring?",
            audience="owner",
            poster=poster,
            odysseus_ask=ask,
        )

    outcome = asyncio.run(_run())
    assert outcome.text
    assert "odysseus" in outcome.meta["skipped"]
    assert "bigdeal" in outcome.meta["skipped"]
    assert all(item["name"] != "odysseus" for item in outcome.meta["contributors"])


def test_research_strategy_adds_odysseus_notes_without_memories(monkeypatch):
    _env(monkeypatch, strategy="single+odysseus_research", odysseus=True)
    seen = {"bodies": [], "asks": []}

    async def poster(url, body, timeout):
        seen["bodies"].append(json.dumps(body))
        return _completion("with research", body["model"])

    async def ask(kind, text, timeout):
        seen["asks"].append((kind, text))
        return OdysseusDraft(text="searxng notes", ok=True, model="deep-research", via="research")

    question = "what is the latest news about the river road"
    messages = [
        {"role": "system", "content": "SECRET VAULT FACT"},
        {"role": "user", "content": question},
    ]

    async def _run():
        return await complete_turn(
            messages,
            question,
            audience="heir",
            poster=poster,
            odysseus_ask=ask,
        )

    outcome = asyncio.run(_run())
    assert outcome.text == "with research"
    assert seen["asks"] == [("research", question)]
    assert "SECRET VAULT FACT" not in seen["asks"][0][1]
    assert "searxng notes" in seen["bodies"][0]
    assert "SECRET VAULT FACT" in seen["bodies"][0]
    names = [item["name"] for item in outcome.meta["contributors"]]
    assert "odysseus" in names
    assert outcome.meta["path"] == "research"
