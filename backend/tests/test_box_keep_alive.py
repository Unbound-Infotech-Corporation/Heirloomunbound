"""The box keeps its own chat model loaded; a LAN brain is never held."""
import os

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "heirloom")

import llm_provider  # noqa: E402


def _observer(monkeypatch, on):
    import sys
    import types

    module = types.ModuleType("observer_store")
    module.observer_enabled = lambda: on
    monkeypatch.setitem(sys.modules, "observer_store", module)


def test_box_model_stays_loaded_while_the_observer_is_off(monkeypatch):
    monkeypatch.delenv("HEIRLOOM_BOX_KEEP_ALIVE", raising=False)
    _observer(monkeypatch, False)
    assert llm_provider.box_keep_alive() == "24h"


def test_observer_on_keeps_the_short_swap_window(monkeypatch):
    monkeypatch.delenv("HEIRLOOM_BOX_KEEP_ALIVE", raising=False)
    _observer(monkeypatch, True)
    assert llm_provider.box_keep_alive() == llm_provider.BRAIN_KEEP_ALIVE == "30m"


def test_the_owner_can_set_it(monkeypatch):
    monkeypatch.setenv("HEIRLOOM_BOX_KEEP_ALIVE", "2h")
    _observer(monkeypatch, False)
    assert llm_provider.box_keep_alive() == "2h"


def _capture(monkeypatch, url):
    seen = {}

    async def poster(target, body, timeout):
        seen["url"] = target
        seen["body"] = body
        return {"model": body["model"], "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}

    monkeypatch.setenv("HEIRLOOM_BOX", "1")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
    monkeypatch.delenv("HEIRLOOM_BOX_KEEP_ALIVE", raising=False)
    _observer(monkeypatch, False)
    return seen, poster


def test_box_completions_ask_for_the_long_keep_alive_and_bigdeal_does_not(monkeypatch):
    import asyncio

    seen, poster = _capture(monkeypatch, "")
    asyncio.run(llm_provider.complete_openai_chat(
        [{"role": "user", "content": "hi"}], base_url="http://ollama:11434", pin_host=True,
        poster=poster, keep_alive=llm_provider.BRAIN_KEEP_ALIVE,
    ))
    assert seen["body"]["keep_alive"] == "24h"
    asyncio.run(llm_provider.complete_openai_chat(
        [{"role": "user", "content": "hi"}], base_url="http://192.168.0.50:11434", pin_host=True,
        poster=poster, keep_alive=llm_provider.BRAIN_KEEP_ALIVE,
    ))
    assert seen["body"]["keep_alive"] == "30m"
