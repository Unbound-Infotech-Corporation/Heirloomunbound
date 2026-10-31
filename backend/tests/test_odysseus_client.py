"""Odysseus URL, token handling, and the mocked HTTP client."""
from __future__ import annotations

import asyncio
import json
import logging

import pytest

from odysseus_client import (
    OdysseusClient,
    OdysseusSettings,
    context_for_odysseus,
    merge_owner_extras,
    normalize_odysseus_url,
    public_odysseus,
    redact,
    resolve_token,
    safe_odysseus_url,
)


def test_urls_stay_on_the_lan_or_the_service_name():
    assert normalize_odysseus_url("http://192.168.0.110:7011") == "http://192.168.0.110:7011"
    assert normalize_odysseus_url("http://192.168.0.110") == "http://192.168.0.110:7011"
    assert normalize_odysseus_url("http://odysseus:7000") == "http://odysseus:7000"
    assert normalize_odysseus_url("http://odysseus") == "http://odysseus:7000"
    assert safe_odysseus_url("http://8.8.8.8:7011") == ""
    with pytest.raises(ValueError):
        normalize_odysseus_url("http://example.com:7011")
    with pytest.raises(ValueError):
        normalize_odysseus_url("http://user:ody_secret@192.168.0.110:7011")
    with pytest.raises(ValueError):
        normalize_odysseus_url("http://192.168.0.16:7011")


def test_token_file_wins_and_is_not_logged(tmp_path, monkeypatch, caplog):
    path = tmp_path / "odysseus.token"
    path.write_text("# owner copy\nody_fromfile\n", encoding="utf-8")
    monkeypatch.setenv("HEIRLOOM_ODYSSEUS_TOKEN_FILE", str(path))
    monkeypatch.setenv("HEIRLOOM_ODYSSEUS_TOKEN", "ody_fromenv")
    token = resolve_token({"odysseus_token": "ody_saved"})
    assert token == "ody_fromfile"
    caplog.set_level(logging.DEBUG)
    logging.getLogger("odysseus_client").info("token file loaded")
    assert "ody_fromfile" not in caplog.text
    assert redact("Authorization Bearer ody_fromfile", token) == "Authorization Bearer ody_…"


def test_context_drops_memories_for_every_audience():
    question = "what is the latest news"
    for audience in ("owner", "heir", "caller"):
        sent = context_for_odysseus(question, audience=audience, memory_text="SECRET VAULT FACT")
        assert sent == question
        assert "SECRET" not in sent


def test_owner_save_hides_the_token():
    doc = merge_owner_extras(
        {"_id": "box", "url": "", "model": "llama3.3:70b", "token": ""},
        {
            "strategy": "judge",
            "odysseus_enabled": True,
            "odysseus_url": "http://odysseus:7000",
            "odysseus_token": "ody_supersecretvalue",
        },
        None,
    )
    assert doc["strategy"] == "judge_pick_best"
    assert doc["odysseus_url"] == "http://odysseus:7000"
    view = public_odysseus(OdysseusSettings(
        enabled=True,
        url=doc["odysseus_url"],
        token=doc["odysseus_token"],
    ))
    assert view["token_set"] is True
    assert view["ready"] is True
    assert "ody_supersecretvalue" not in json.dumps(view)
    with pytest.raises(ValueError):
        merge_owner_extras({}, {"strategy": "cloud", "odysseus_url": ""}, None)


def test_research_polls_and_chat_fallback_on_403():
    settings = OdysseusSettings(enabled=True, url="http://odysseus:7000", token="ody_supersecretvalue")

    async def research_transport(method, path, body, timeout):
        if path == "/api/research/start":
            assert body["query"] == "latest news"
            return 200, {"session_id": "rp-abc", "status": "running"}
        if path == "/api/research/status/rp-abc":
            return 200, {"status": "completed"}
        if path == "/api/research/result-peek/rp-abc":
            return 200, {"result": "found it"}
        return 404, {}

    async def chat_transport(method, path, body, timeout):
        if path == "/api/research/start":
            return 403, {"error": "API tokens must use a scope-aware API route"}
        if path == "/api/v1/chat":
            assert body == {"message": "latest news"}
            return 200, {"response": "chat fallback", "model": "qwen", "session_id": "s"}
        return 500, {}

    async def _run():
        researched = await OdysseusClient(settings, transport=research_transport, poll_interval=0).research("latest news")
        fallback = await OdysseusClient(settings, transport=chat_transport, poll_interval=0).research("latest news")
        return researched, fallback

    researched, fallback = asyncio.run(_run())
    assert researched.ok is True
    assert researched.text == "found it"
    assert researched.via == "research"
    assert fallback.ok is True
    assert fallback.text == "chat fallback"
    assert fallback.via == "chat"


def test_fast_search_uses_the_search_endpoint_before_chat():
    settings = OdysseusSettings(enabled=True, url="http://odysseus:7000", token="ody_supersecretvalue")
    calls = []

    async def transport(method, path, body, timeout):
        calls.append(path)
        assert body["query"] == "river road news"
        assert "SECRET" not in json.dumps(body)
        assert timeout <= 10
        return 200, {"context": "The road is closed.", "sources": [{"title": "Local paper", "snippet": "since Tuesday"}]}

    async def _run():
        return await OdysseusClient(settings, transport=transport).web_search("river road news", timeout=8)

    draft = asyncio.run(_run())
    assert calls == ["/api/search"]
    assert draft.ok is True
    assert draft.via == "search"
    assert "The road is closed." in draft.text
    assert "Local paper" in draft.text


def test_search_falls_back_to_v1_chat_with_web():
    settings = OdysseusSettings(enabled=True, url="http://192.168.0.110:7011", token="ody_supersecretvalue")

    async def transport(method, path, body, timeout):
        if path == "/api/search":
            return 404, {"error": "missing"}
        assert path == "/api/v1/chat"
        assert body["use_web"] is True
        assert body["message"] == "river road news"
        return 200, {"response": "from web chat", "model": "qwen"}

    async def _run():
        return await OdysseusClient(settings, transport=transport).web_search("river road news")

    draft = asyncio.run(_run())
    assert draft.ok is True
    assert draft.via == "chat"
    assert draft.text == "from web chat"


def test_deep_research_start_does_not_poll():
    settings = OdysseusSettings(enabled=True, url="http://odysseus:7000", token="ody_supersecretvalue")
    calls = []

    async def transport(method, path, body, timeout):
        calls.append(path)
        return 200, {"session_id": "rp-bg", "status": "running"}

    async def _run():
        return await OdysseusClient(settings, transport=transport).start_research("latest news")

    draft = asyncio.run(_run())
    assert calls == ["/api/research/start"]
    assert draft.ok is True
    assert draft.via == "deep_research"
    assert draft.text == "rp-bg"


def test_down_client_returns_a_failed_draft(caplog):
    settings = OdysseusSettings(enabled=True, url="http://192.168.0.110:7011", token="ody_supersecretvalue")

    async def transport(method, path, body, timeout):
        raise RuntimeError("boom ody_supersecretvalue")

    caplog.set_level(logging.WARNING)

    async def _run():
        return await OdysseusClient(settings, transport=transport).chat("hello")

    draft = asyncio.run(_run())
    assert draft.ok is False
    assert "ody_supersecretvalue" not in caplog.text
