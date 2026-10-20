"""Assist task router: classify, fallback, second opinion, install tiers."""
from __future__ import annotations

import pytest

from assist_router import (
    AssistRouteError,
    Inventory,
    answer_assist,
    classify_assist_task,
    model_matches,
    preview_assist,
    wants_second_opinion,
)
from studio_defaults import ASSIST_TIER_MODELS, clamp_assist_settings
from studio_setup import provision_features, provision_manifest, space_profile


class Scripted:
    def __init__(self, replies: dict):
        self.replies = replies
        self.calls: list[tuple[str, str]] = []

    async def complete(self, *, backend, model, messages, timeout):
        self.calls.append((backend, model))
        value = self.replies[(backend, model)]
        if isinstance(value, Exception):
            raise value
        return value


def _inv(**kwargs) -> Inventory:
    base = dict(
        ollama_ready=True,
        ollama_models=["qwen2.5-coder:32b", "qwen2.5-coder:7b", "qwen2.5:3b", "deepseek-r1:14b", "llava:7b"],
        llamacpp_ready=False,
    )
    base.update(kwargs)
    return Inventory(**base)


def test_classify_routes_code_research_reasoning_chat_and_vision():
    assert classify_assist_task("hi") == "chat"
    assert classify_assist_task("refactor the auth middleware") == "code"
    assert classify_assist_task("plan the archive layout") == "reasoning"
    assert classify_assist_task("what is the latest on local whisper") == "research"
    assert classify_assist_task("look at this screenshot") == "vision"
    assert classify_assist_task("hello", has_image=True) == "vision"
    assert classify_assist_task("plan a refactor of the parser") == "code"


def test_model_match_is_exact_or_tag_not_a_sibling_family():
    assert model_matches("qwen2.5-coder", "qwen2.5-coder:32b")
    assert model_matches("qwen2.5-coder:7b", "qwen2.5-coder:7b")
    assert not model_matches("qwen3", "qwen3-coder:30b")
    assert not model_matches("qwen2.5:3b", "qwen2.5:7b")
    assert not model_matches("deepseek-coder", "deepseek-coder-v2")


def test_risky_code_requests_a_second_opinion_only_in_auto():
    assert wants_second_opinion("delete the auth middleware and refactor it", "code", "auto")
    assert not wants_second_opinion("rename this function", "code", "auto")
    assert wants_second_opinion("rename this function", "code", "always")
    assert not wants_second_opinion("delete the auth middleware", "code", "off")
    assert not wants_second_opinion("delete the file on the desktop", "chat", "always")


@pytest.mark.asyncio
async def test_auto_names_the_preferred_installed_model():
    transport = Scripted({("ollama", "qwen3-coder:30b"): "preferred"})
    inv = _inv(ollama_models=["qwen3-coder:30b", "qwen2.5-coder:7b", "llama3.1:8b"])
    answer = await answer_assist(
        "refactor parse()",
        system="sys",
        settings={"picker": "auto", "second_opinion": "off"},
        inventory=inv,
        transport=transport,
    )
    assert answer.model == "qwen3-coder:30b"
    assert answer.backend == "ollama"
    assert "qwen3-coder:30b" in answer.badge
    assert "fallback" not in answer.badge
    assert answer.degraded is False
    assert transport.calls == [("ollama", "qwen3-coder:30b")]


@pytest.mark.asyncio
async def test_unsized_spec_prefers_the_larger_installed_tag():
    transport = Scripted({("ollama", "qwen2.5-coder:32b"): "larger"})
    settings = {
        "picker": "auto",
        "second_opinion": "off",
        "routes": {"code": [{"backend": "ollama", "model": "qwen2.5-coder"}]},
    }
    answer = await answer_assist(
        "refactor parse()",
        system="sys",
        settings=settings,
        inventory=_inv(),
        transport=transport,
    )
    assert answer.model == "qwen2.5-coder:32b"
    assert answer.degraded is False


@pytest.mark.asyncio
async def test_missing_preferred_model_falls_back_loudly():
    transport = Scripted({("ollama", "qwen2.5-coder:7b"): "smaller coder"})
    inv = _inv(ollama_models=["qwen2.5-coder:7b"])
    answer = await answer_assist(
        "refactor parse()",
        system="sys",
        settings={"picker": "auto", "second_opinion": "off"},
        inventory=inv,
        transport=transport,
    )
    assert answer.model == "qwen2.5-coder:7b"
    assert answer.degraded is True
    assert "fallback" in answer.badge
    assert "qwen3-coder" in answer.badge
    assert "not installed" in answer.badge


@pytest.mark.asyncio
async def test_http_failure_tries_the_next_model_and_records_it():
    transport = Scripted(
        {
            ("ollama", "qwen2.5-coder:32b"): RuntimeError("connection reset"),
            ("ollama", "qwen2.5-coder:7b"): "recovered",
        }
    )
    answer = await answer_assist(
        "refactor parse()",
        system="sys",
        settings={"picker": "auto", "second_opinion": "off"},
        inventory=_inv(),
        transport=transport,
    )
    assert answer.reply == "recovered"
    assert answer.model == "qwen2.5-coder:7b"
    assert any(row["status"] == "failed" and row["model"] == "qwen2.5-coder:32b" for row in answer.attempts)
    assert "connection reset" in answer.badge


@pytest.mark.asyncio
async def test_exhausted_chain_raises_and_does_not_substitute():
    transport = Scripted({})
    with pytest.raises(AssistRouteError) as caught:
        await answer_assist(
            "refactor parse()",
            system="sys",
            settings={"picker": "auto", "second_opinion": "off"},
            inventory=_inv(ollama_ready=False, ollama_models=[], ollama_reason="Ollama is not running."),
            transport=transport,
        )
    text = str(caught.value)
    assert "Nothing else was substituted." in text
    assert "did not run" in text
    assert transport.calls == []


@pytest.mark.asyncio
async def test_manual_override_does_not_fall_back():
    transport = Scripted({("ollama", "qwen2.5-coder:7b"): "nope"})
    with pytest.raises(AssistRouteError) as caught:
        await answer_assist(
            "refactor parse()",
            system="sys",
            settings={
                "picker": "manual",
                "manual_backend": "ollama",
                "manual_model": "missing-coder",
                "second_opinion": "off",
            },
            inventory=_inv(),
            transport=transport,
        )
    assert "missing-coder" in str(caught.value)
    assert transport.calls == []


@pytest.mark.asyncio
async def test_cloud_slot_is_skipped_until_opt_in_and_key():
    settings = clamp_assist_settings(
        {
            "picker": "auto",
            "second_opinion": "off",
            "routes": {
                "code": [
                    {"backend": "cloud", "model": "cloud-coder"},
                    {"backend": "ollama", "model": "qwen2.5-coder:7b"},
                ]
            },
            "cloud": {"enabled": False, "base_url": "https://example.invalid/v1", "model": "cloud-coder"},
        }
    )
    transport = Scripted({("ollama", "qwen2.5-coder:7b"): "local"})
    answer = await answer_assist(
        "refactor parse()",
        system="sys",
        settings=settings,
        inventory=_inv(ollama_models=["qwen2.5-coder:7b"], cloud_enabled=False),
        transport=transport,
        cloud_key="",
    )
    assert answer.backend == "ollama"
    assert "Cloud opt-in is off." in answer.badge
    assert all(call[0] != "cloud" for call in transport.calls)

    cloud_inv = _inv(
        ollama_ready=False,
        ollama_models=[],
        cloud_enabled=True,
        cloud_has_key=True,
        cloud_base_url="https://example.invalid/v1",
        cloud_model="cloud-coder",
    )
    cloud = Scripted({("cloud", "cloud-coder"): "from the cloud"})
    cloud_settings = dict(settings)
    cloud_settings["cloud"] = {"enabled": True, "base_url": "https://example.invalid/v1", "model": "cloud-coder"}
    cloud_settings["routes"] = {"code": [{"backend": "cloud", "model": "cloud-coder"}]}
    answer = await answer_assist(
        "refactor parse()",
        system="sys",
        settings=cloud_settings,
        inventory=cloud_inv,
        transport=cloud,
        cloud_key="sk-test",
    )
    assert answer.reply == "from the cloud"
    assert answer.backend == "cloud"
    assert cloud.calls == [("cloud", "cloud-coder")]


@pytest.mark.asyncio
async def test_second_opinion_runs_two_models_and_a_judge():
    transport = Scripted(
        {
            ("ollama", "qwen2.5-coder:32b"): "draft A",
            ("ollama", "qwen2.5-coder:7b"): "draft B",
            ("ollama", "deepseek-r1:14b"): "merged safely",
        }
    )
    answer = await answer_assist(
        "refactor and delete the auth check",
        system="sys",
        settings={"picker": "auto", "second_opinion": "auto"},
        inventory=_inv(),
        transport=transport,
    )
    assert answer.second_opinion is True
    assert answer.reply == "merged safely"
    assert answer.drafts["primary"]["text"] == "draft A"
    assert answer.drafts["second"]["text"] == "draft B"
    assert "judge" in answer.badge
    assert "deepseek-r1:14b" in answer.badge
    assert [call[1] for call in transport.calls] == [
        "qwen2.5-coder:32b",
        "qwen2.5-coder:7b",
        "deepseek-r1:14b",
    ]


@pytest.mark.asyncio
async def test_second_opinion_fails_loudly_when_only_one_code_model_exists():
    transport = Scripted({("ollama", "qwen2.5-coder:7b"): "only one"})
    with pytest.raises(AssistRouteError) as caught:
        await answer_assist(
            "migrate the auth table",
            system="sys",
            settings={"picker": "auto", "second_opinion": "always"},
            inventory=_inv(ollama_models=["qwen2.5-coder:7b"]),
            transport=transport,
        )
    assert "two different code models" in str(caught.value)
    assert transport.calls == []


@pytest.mark.asyncio
async def test_judge_failure_still_shows_both_drafts():
    transport = Scripted(
        {
            ("ollama", "qwen2.5-coder:32b"): "draft A",
            ("ollama", "qwen2.5-coder:7b"): "draft B",
            ("ollama", "deepseek-r1:14b"): RuntimeError("judge down"),
        }
    )
    answer = await answer_assist(
        "rewrite the payment check",
        system="sys",
        settings={"picker": "auto", "second_opinion": "always"},
        inventory=_inv(),
        transport=transport,
    )
    assert answer.error
    assert "draft A" in answer.reply
    assert "draft B" in answer.reply
    assert "judge failed" in answer.badge
    assert answer.drafts["primary"]["model"] == "qwen2.5-coder:32b"


def test_preview_names_the_model_without_calling_it():
    probe = {"ollama": {"ready": True, "models": ["qwen2.5:3b"]}}
    preview = preview_assist("hello there", settings={"picker": "auto"}, probe=probe, has_key=False)
    assert preview["ok"] is True
    assert preview["category"] == "chat"
    assert preview["model"] == "qwen2.5:3b"
    assert "qwen2.5:3b" in preview["badge"]


def test_clamp_drops_unknown_slots_and_keeps_cloud_off():
    clamped = clamp_assist_settings(
        {
            "routes": {"code": [{"backend": "pinokio", "model": "nope"}, {"backend": "ollama", "model": "qwen3-coder"}]},
            "cloud": {"enabled": True, "base_url": "ftp://nope", "model": "x"},
        }
    )
    assert clamped["routes"]["code"] == [{"backend": "ollama", "model": "qwen3-coder"}]
    assert clamped["cloud"]["enabled"] is True
    assert clamped["cloud"]["base_url"] == ""
    assert clamped["routes"]["chat"][0]["model"] == "qwen2.5:3b"


def test_companion_catalog_matches_studio_dev_models():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "companion_desktop" / "heirloom" / "space_profiles.py"
    spec = importlib.util.spec_from_file_location("companion_space_profiles", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for profile_id, tags in ASSIST_TIER_MODELS.items():
        companion = next(row for row in module.SPACE_PROFILES if row["id"] == profile_id)
        assert list(companion["dev_models"]) == list(tags)
        assert list(space_profile(profile_id)["dev_models"]) == list(tags)


def test_install_tiers_map_to_assist_dev_models():
    assert space_profile("small")["dev_models"] == ()
    assert "assist" not in provision_features("small")
    assert list(space_profile("medium")["dev_models"]) == ["qwen2.5-coder:7b", "qwen2.5:3b"]
    assert "assist" in provision_features("medium")
    large = list(ASSIST_TIER_MODELS["large"])
    assert list(space_profile("large")["dev_models"]) == large
    assert "qwen2.5-coder:32b" in large and "deepseek-r1:14b" in large
    dedicated = list(space_profile("dedicated")["dev_models"])
    assert "qwen3-coder" in dedicated
    assert "deepseek-coder-v2" in dedicated
    assert set(large) <= set(dedicated)
    small_ids = {a["id"] for a in provision_manifest("small")["artifacts"]}
    assert "ollama-qwen25-coder-7b" not in small_ids
    medium_ids = {a["id"] for a in provision_manifest("medium")["artifacts"]}
    assert "ollama-qwen25-coder-7b" in medium_ids
    assert "ollama-qwen3-coder" not in medium_ids
    ded_ids = {a["id"] for a in provision_manifest("dedicated")["artifacts"]}
    assert "ollama-deepseek-coder-v2" in ded_ids
    assert provision_manifest("large")["dev_models"] == large
