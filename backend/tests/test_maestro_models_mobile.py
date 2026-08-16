"""Maestro model catalog + phone integration packs (no Mongo required)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "companion_desktop"))

from heirloom.local_ai import parse_tags
from services.model_catalog import (
    CLOUD_SERVICES,
    FUNCTIONS,
    LOCAL_MODELS,
    assignment_for,
    llm_family_for,
    option_id,
    parse_option_id,
    ready_options,
    tag_is_installed,
    installed_set,
)
from services.phone_packs import phone_enabled_ids, visible_integrations


def test_option_id_round_trip_cloud_and_local_colon_tags():
    assert option_id("openai", "gpt-4o") == "openai:gpt-4o"
    assert parse_option_id("openai:gpt-4o") == ("openai", "gpt-4o")
    assert parse_option_id("local:llama3.2:3b") == ("local", "llama3.2:3b")
    assert option_id("local", "llama3.2:3b") == "local:llama3.2:3b"


def test_parse_option_id_rejects_junk():
    for raw in ("", "local:", "openai", ":"):
        try:
            parse_option_id(raw)
            assert False, raw
        except ValueError:
            pass


def test_catalog_covers_router_providers_and_tasks():
    assert {s["id"] for s in CLOUD_SERVICES} == {
        "emergent", "openai", "anthropic", "gemini", "groq", "xai", "deepseek",
    }
    assert {f["task"] for f in FUNCTIONS} == {
        "chat", "interview", "tools", "cheap", "long_context", "embeddings",
    }
    assert any(m["id"] == "llama3.2:3b" for m in LOCAL_MODELS)
    assert any(m["recommended"] for m in LOCAL_MODELS)


def test_llm_family_for_tool_capable_vs_compat():
    assert llm_family_for("openai", "gpt-4o") == ("openai", "gpt-4o")
    assert llm_family_for("anthropic", "claude-sonnet-4-6")[0] == "anthropic"
    assert llm_family_for("emergent", "gpt-5.4") == ("openai", "gpt-5.4")
    assert llm_family_for("emergent", "gemini-3-flash-preview")[0] == "gemini"
    assert llm_family_for("emergent", "")[0] == "anthropic"
    assert llm_family_for("groq", "llama-3.3-70b-versatile") is None
    assert llm_family_for("xai", "grok-2") is None
    assert llm_family_for("deepseek", "deepseek-chat") is None
    assert llm_family_for("local", "llama3.2:3b") is None


def test_tag_is_installed_does_not_confuse_size_variants():
    installed = installed_set(["llama3.2:1b", "phi3:latest"])
    assert tag_is_installed("llama3.2:1b", installed)
    assert not tag_is_installed("llama3.2:3b", installed)
    assert tag_is_installed("phi3:mini", installed) is False
    assert tag_is_installed("phi3:latest", installed)
    assert tag_is_installed("phi3", installed)


def test_ready_options_only_lists_connected_and_installed():
    cfg = {
        "providers": {
            "emergent": {"enabled": True, "api_key": ""},
            "openai": {"enabled": True, "api_key": "sk-test", "default_model": "gpt-4o"},
            "groq": {"enabled": True, "api_key": ""},  # BYOK without a key → hidden
        }
    }
    opts = ready_options(cfg, ["llama3.2:3b", "my-finetune:q4"])
    ids = {o["id"] for o in opts}
    assert "emergent:claude-sonnet-4-6" in ids
    assert "openai:gpt-4o" in ids
    assert "groq:llama-3.3-70b-versatile" not in ids
    assert "local:llama3.2:3b" in ids
    assert "local:my-finetune:q4" in ids
    assert "local:llama3.2:1b" not in ids


def test_assignment_for_prefers_local_then_task_model():
    chat_fn = next(f for f in FUNCTIONS if f["id"] == "chat")
    local = assignment_for(chat_fn, {"local_task_routes": {"chat": "phi3:mini"}})
    assert local["provider"] == "local"
    assert local["option_id"] == "local:phi3:mini"
    cloud = assignment_for(chat_fn, {
        "task_routes": {"chat": "openai"},
        "task_models": {"chat": "gpt-4o-mini"},
        "providers": {"openai": {"enabled": True}},
    })
    assert cloud["provider"] == "openai"
    assert cloud["model"] == "gpt-4o-mini"


def test_phone_calls_default_on_and_desktop_off_hidden():
    abilities = [
        {"id": "web", "name": "Web", "tagline": "t", "icon": "globe", "category": "knowledge", "requires_companion": False},
        {"id": "music", "name": "Music", "tagline": "t", "icon": "music", "category": "companion", "requires_companion": False},
    ]
    desktop = {"web": {"enabled": True}, "music": {"enabled": False}}
    items = visible_integrations(abilities, desktop, {})
    ids = [i["id"] for i in items]
    assert ids[0] == "phone_calls"
    assert items[0]["phone_enabled"] is True
    assert "web" in ids
    assert "music" not in ids

    off = visible_integrations(abilities, desktop, {"explicit_off": ["phone_calls"]})
    phone = next(i for i in off if i["id"] == "phone_calls")
    assert phone["phone_enabled"] is False
    assert phone_enabled_ids({"explicit_off": ["phone_calls"]}) == set()


def test_parse_tags_skips_header_and_empty():
    out = parse_tags("NAME\tID\nllama3.2:3b\t123\n(none installed)\n")
    assert out == ["llama3.2:3b"]
