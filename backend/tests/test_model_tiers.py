"""Hardware tiers: detection parsing, the pick per card, overrides, and thinking flags."""
import asyncio
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

import model_tiers
from model_tiers import TIERS, Hardware, choose, parse_nvidia_smi, parse_rocm_smi, think_value, tier_for

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _no_override(monkeypatch):
    monkeypatch.delenv("HEIRLOOM_MODEL_OVERRIDE", raising=False)
    model_tiers._CAPS.clear()


def test_tiers_are_ordered_and_local():
    floors = [tier.min_vram_mib for tier in TIERS]
    assert floors == sorted(floors, reverse=True)
    assert TIERS[-1].name == "cpu" and TIERS[-1].min_vram_mib == 0
    for tier in TIERS:
        assert not model_tiers.is_cloud_tag(tier.model)
        assert not model_tiers.is_cloud_tag(tier.fallback)
        assert tier.license


@pytest.mark.parametrize("mib, expected", [
    (32607, "xl"),     # RTX 5090
    (24576, "large"),  # RTX 3090 / 4090
    (16376, "medium"),  # RTX 4080 / 4060 Ti 16G
    (12288, "small"),  # RTX 3060 12G
    (8192, "compact"),  # RTX 4060
    (6144, "cpu"),     # too small for any GPU tier
])
def test_common_cards_land_in_their_tier(mib, expected):
    tier, model = tier_for(mib, ram_mib=32768, vendor="nvidia")
    assert tier.name == expected
    assert model in {tier.model, tier.fallback}


def test_measured_size_plus_voice_must_fit_or_fallback():
    for tier in TIERS[:-1]:
        if not tier.loaded_mib:
            continue
        voice = model_tiers.VOICE_RESERVE_MIB if tier.voice_on_gpu else 0
        need = tier.loaded_mib + model_tiers.BASE_RESERVE_MIB + voice
        assert need <= tier.min_vram_mib or tier_for(tier.min_vram_mib, vendor="nvidia")[1] == tier.fallback


def test_amd_counts_and_unknown_vendor_is_cpu():
    assert tier_for(24576, vendor="amd")[0].name == "large"
    assert tier_for(24576, vendor="intel")[0].name == "cpu"
    assert tier_for(0, vendor="none", ram_mib=8192)[1] == TIERS[-1].fallback
    assert tier_for(0, vendor="none", ram_mib=65536)[1] == TIERS[-1].model


def test_override_wins_but_never_a_cloud_tag(monkeypatch):
    hw = Hardware(vendor="nvidia", gpu="RTX 3090", vram_mib=24576, ram_mib=65536)
    monkeypatch.setenv("HEIRLOOM_MODEL_OVERRIDE", "qwen2.5:14b")
    picked = choose(hw)
    assert picked.model == "qwen2.5:14b" and picked.override
    monkeypatch.setenv("HEIRLOOM_MODEL_OVERRIDE", "gpt-4o")
    picked = choose(hw)
    assert picked.model != "gpt-4o" and not picked.override


def test_parsers():
    assert parse_nvidia_smi("NVIDIA GeForce RTX 3090, 24576\nNVIDIA GeForce GTX 1650, 4096\n") == ("NVIDIA GeForce RTX 3090", 24576)
    assert parse_nvidia_smi("") == ("", 0)
    rocm = json.dumps({"card0": {"VRAM Total Memory (B)": str(24 * 1024 ** 3), "VRAM Total Used Memory (B)": "1"}})
    assert parse_rocm_smi(rocm)[1] == 24576
    assert parse_rocm_smi("not json") == ("", 0)
    assert model_tiers.vendor_from_name("AMD Radeon RX 7900 XTX") == "amd"
    assert model_tiers.vendor_from_name("NVIDIA GeForce RTX 4060") == "nvidia"


def test_cli_choose_json():
    done = subprocess.run(
        ["python3", str(ROOT / "backend" / "model_tiers.py"), "choose", "--vram-mib", "24576", "--ram-mib", "65536", "--json"],
        capture_output=True, text=True, check=True,
    )
    picked = json.loads(done.stdout)
    assert picked["tier"] == "large"


@pytest.mark.skipif(os.name == "nt", reason="box/lib/models.sh is for the Linux box")
def test_shell_table_matches_python():
    """box/lib/models.sh carries the same picks for a box without python3."""
    for tier in TIERS[:-1]:
        script = f'source "{ROOT}/box/lib/models.sh"; HEIRLOOM_TIERS_PY=/nonexistent heirloom_model_for_vram_mib {tier.min_vram_mib}'
        out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True).stdout.strip()
        assert out == tier_for(tier.min_vram_mib, vendor="nvidia")[1], tier.name
    script = f'source "{ROOT}/box/lib/models.sh"; HEIRLOOM_TIERS_PY=/nonexistent heirloom_model_for_vram_mib 0'
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True).stdout.strip()
    assert out == TIERS[-1].model


def test_think_flag_by_family_without_ollama():
    assert think_value("qwen3.5:9b") is False
    assert think_value("gemma4:26b") is False
    assert think_value("gpt-oss:20b") == "low"
    assert think_value("qwen2.5:14b") is None
    assert think_value("mistral-small3.2:24b") is None


def test_think_flag_uses_ollama_capabilities(monkeypatch):
    monkeypatch.setitem(model_tiers._CAPS, ("http://lan:11434", "custom:1b"), ("completion", "thinking"))
    monkeypatch.setitem(model_tiers._CAPS, ("http://lan:11434", "qwen3.5:9b"), ("completion", "tools"))
    assert think_value("custom:1b", "http://lan:11434") is False
    assert think_value("qwen3.5:9b", "http://lan:11434") is None


def test_v1_body_turns_thinking_off_with_reasoning_effort():
    from llm_provider import complete_openai_chat, reasoning_effort

    assert reasoning_effort(False) == "none"
    assert reasoning_effort("low") == "low"
    assert reasoning_effort(None) == ""
    seen = {}

    async def poster(url, body, timeout):
        seen["body"] = dict(body)
        return {"model": body["model"], "choices": [{"message": {"content": "ready"}}]}

    async def _run(model):
        return await complete_openai_chat([{"role": "user", "content": "Hi"}], model=model,
                                          base_url="http://192.168.0.50:11434", pin_host=True, poster=poster)

    asyncio.run(_run("qwen3.5:9b"))
    assert seen["body"]["reasoning_effort"] == "none"
    asyncio.run(_run("gemma4:26b"))
    assert seen["body"]["reasoning_effort"] == "none"
    asyncio.run(_run("gpt-oss:20b"))
    assert seen["body"]["reasoning_effort"] == "low"
    asyncio.run(_run("qwen2.5:14b"))
    assert "reasoning_effort" not in seen["body"] and "think" not in seen["body"]


def test_grounding_calls_send_think_off(monkeypatch):
    import grounding

    sent = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"message": {"content": '{"personal": false}'}}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json):
            sent.update(json)
            return _Resp()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    monkeypatch.setenv("OLLAMA_TWIN_MODEL", "qwen3.5:9b")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:9")
    model_tiers._CAPS[("http://127.0.0.1:9", "qwen3.5:9b")] = ("completion", "thinking", "tools")
    asyncio.run(grounding.ask_box_model("s", "u", json_mode=True))
    assert sent["think"] is False
    model_tiers._CAPS[("http://127.0.0.1:9", "qwen2.5:14b")] = ("completion", "tools")
    monkeypatch.setenv("OLLAMA_TWIN_MODEL", "qwen2.5:14b")
    sent.clear()
    asyncio.run(grounding.ask_box_model("s", "u", json_mode=True))
    assert "think" not in sent


def test_bench_score_is_the_weighted_sum():
    from model_bench import score

    perfect = {"right": 1, "of": 1}
    none = {"right": 0, "of": 1}
    grounded = {"grounding": {k: perfect for k in ("classifier", "verifier", "recall", "decline")},
                "chat": none, "tools": none, "json": none}
    chatty = {"grounding": {k: none for k in ("classifier", "verifier", "recall", "decline")},
              "chat": perfect, "tools": none, "json": perfect}
    assert score(grounded)["quality"] == 40.0
    assert score(chatty)["quality"] == 42.0
    assert score({**grounded, "chat": perfect, "tools": perfect, "json": perfect})["quality"] == 100.0


@pytest.mark.skipif(os.name == "nt", reason="box/lib/models.sh is for the Linux box")
def test_shell_context_matches_python():
    for tier in TIERS[:-1]:
        script = f'source "{ROOT}/box/lib/models.sh"; heirloom_ctx_for_vram_mib {tier.min_vram_mib}'
        out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True).stdout.strip()
        assert int(out) == tier.num_ctx, tier.name


def test_upgrade_never_rewrites_the_context():
    text = (ROOT / "box" / "install.sh").read_text()
    assert '[[ "${UPGRADE}" -eq 0 ]] && ! grep -q \'^OLLAMA_CONTEXT_LENGTH=\'' in text
