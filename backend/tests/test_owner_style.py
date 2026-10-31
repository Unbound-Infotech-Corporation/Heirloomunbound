"""Owner style profile: incremental local analysis, prompt injection, heir fence."""
from __future__ import annotations

import asyncio
from pathlib import Path

from owner_style import (
    analysis_prompt,
    apply_owner_edit,
    empty_profile,
    fold_pending,
    merge_profile,
    needs_model,
    note_owner_line,
    owner_lines,
    parse_model_json,
    public_profile,
    style_register_block,
)
from twin_pack import TwinPack, TwinPassage, compile_twin_prompt, grounded_miss_applies

ROOT = Path(__file__).resolve().parents[1]


def _pack(audience: str) -> TwinPack:
    return TwinPack(
        passages=[TwinPassage(id="2", kind="interview", tag="home", text="The farm was in Vermont", score=3)],
        grounded=True,
        audience=audience,
    )


def test_owner_grounded_chat_is_natural_and_heirs_stay_strict():
    owner = compile_twin_prompt(_pack("owner"), "Alex")
    heir = compile_twin_prompt(_pack("heir"), "Alex")
    caller = compile_twin_prompt(_pack("caller"), "Alex")
    natural = "Chat naturally about everyday things, the present, and what is on screen."
    assert natural in owner
    assert "Only when asked about your own past" in owner
    assert "Never invent biography, dates, names, or advice they did not file." in owner
    assert natural not in heir
    assert natural not in caller
    assert "A fluent sentence is not a filing." in heir
    assert "A fluent sentence is not a filing." in caller
    assert "Never invent biography, dates, names, or advice they did not file." in heir
    assert grounded_miss_applies("owner", True, False) is False
    assert grounded_miss_applies("heir", True, False) is True
    assert grounded_miss_applies("caller", True, False) is True
    assert grounded_miss_applies("heir", True, True) is False
    runtime = (ROOT / "twin_runtime.py").read_text(encoding="utf-8")
    assert "grounded_miss_applies(audience_key, pack.grounded_miss, pack.watched_relied)" in runtime


def test_style_register_is_owner_only():
    profile = {"word_choice": "short words", "humor": "dry", "topics": "cars"}
    block = style_register_block(profile, audience="owner")
    assert "HOW THIS OWNER TALKS" in block
    assert "short words" in block
    assert "dry" in block
    owner = compile_twin_prompt(_pack("owner"), "Alex", style_profile=profile)
    heir = compile_twin_prompt(_pack("heir"), "Alex", style_profile=profile)
    caller = compile_twin_prompt(_pack("caller"), "Alex", style_profile=profile)
    assert "PERSONA REGISTER:" in owner
    assert owner.index("PERSONA REGISTER:") < owner.index("HOW THIS OWNER TALKS")
    assert "short words" in owner
    assert "short words" not in heir
    assert "short words" not in caller
    assert "HOW THIS OWNER TALKS" not in heir
    assert style_register_block(profile, audience="heir") == ""


def test_incremental_merge_keeps_blank_fields_and_counts_samples():
    previous = empty_profile()
    previous["word_choice"] = "plain"
    previous["sample_count"] = 3
    merged = merge_profile(previous, {"humor": "dry", "word_choice": ""}, added=4)
    assert merged["word_choice"] == "plain"
    assert merged["humor"] == "dry"
    assert merged["sample_count"] == 7
    assert merged["pending"] == []
    parsed = parse_model_json('```json\n{"opens": "hey", "nope": "drop me"}\n```')
    assert parsed == {"opens": "hey"}
    assert parse_model_json("not json") is None
    held = fold_pending(previous, ["one", "two"], "nope")
    assert held["pending"][-2:] == ["one", "two"]
    assert held["word_choice"] == "plain"
    folded = fold_pending(previous, ["yo"], '{"closes": "later"}')
    assert folded["closes"] == "later"
    assert folded["pending"] == []
    assert needs_model(3) is False
    assert needs_model(4) is True
    assert needs_model(1, force=True) is True
    assert needs_model(0, force=True) is False


def test_analysis_prompt_is_local_and_owner_edit_can_clear_a_field():
    system, user = analysis_prompt({"humor": "dry"}, ["yo thats wild"])
    assert "JSON" in system
    assert "do not invent biography" in system.lower() or "Do not invent biography" in system
    assert "yo thats wild" in user
    assert "dry" in user
    edited = apply_owner_edit({"humor": "dry", "sample_count": 2, "pending": ["a"]}, {"humor": "", "topics": "trucks"})
    assert edited["humor"] == ""
    assert edited["topics"] == "trucks"
    assert edited["sample_count"] == 2
    assert edited["pending"] == ["a"]
    public = public_profile(edited)
    assert "pending" not in public
    assert public["pending_count"] == 1
    lines = owner_lines([
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "yo"},
    ])
    assert lines == ["yo"]
    src = (ROOT / "owner_style.py").read_text(encoding="utf-8")
    assert "complete_openai_chat" not in src
    assert "anthropic" not in src.lower()
    assert "ollama_chat" in src
    router = (ROOT / "routers" / "owner_style.py").read_text(encoding="utf-8")
    assert "require_owner" in router
    assert "/reset" in router


def test_note_owner_line_waits_then_folds_with_the_injected_completer():
    store: dict[str, dict] = {}

    async def load(_user_id: str) -> dict:
        return dict(store.get("p") or empty_profile())

    async def save(_user_id: str, profile: dict) -> None:
        store["p"] = dict(profile)

    calls = {"n": 0}

    async def complete(system: str, user: str) -> str:
        calls["n"] += 1
        assert "JSON" in system
        assert "fourth" in user
        return '{"word_choice": "clipped", "humor": "dry"}'

    async def run():
        for line in ("one", "two", "three"):
            await note_owner_line("u", line, load=load, save=save, complete=complete)
        assert calls["n"] == 0
        assert store["p"]["pending"] == ["one", "two", "three"]
        await note_owner_line("u", "fourth", load=load, save=save, complete=complete)
        assert calls["n"] == 1
        assert store["p"]["word_choice"] == "clipped"
        assert store["p"]["humor"] == "dry"
        assert store["p"]["pending"] == []
        assert store["p"]["sample_count"] == 4

    asyncio.run(run())
