"""Voice council + personality portrait wiring (no Mongo)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from services.voice_council import (
    VOICE_COUNCIL_AFTER_MESSAGES,
    VOICE_COUNCIL_SYSTEM,
    build_council_user_payload,
    format_portrait_for_prompt,
    merge_signature_phrases,
    parse_council_reply,
    plan_voice_updates,
    render_twin_voice_section,
    should_run_council,
)
from services.model_catalog import FUNCTIONS


PROFILE = {
    "summary": "You are a dry Vermonter who leads with the weather.",
    "top_values": ["family", "plain talk", "the land"],
    "voice_tone": {
        "description": "Short sentences. A little wry. Never flowery.",
        "signature_phrases": ["well now", "that's about the size of it"],
    },
    "bigfive": {"openness": {"score": 40, "reason": "likes the known path"}},
}


def test_portrait_formats_voice_values_summary_not_bigfive():
    blob = format_portrait_for_prompt(PROFILE)
    assert "Short sentences" in blob
    assert '"well now"' in blob
    assert "family" in blob
    assert "dry Vermonter" in blob
    assert "40" not in blob
    assert format_portrait_for_prompt(None) == ""
    assert format_portrait_for_prompt({}) == ""
    assert format_portrait_for_prompt({"voice_tone": "oops"}) == ""


def test_voice_section_only_when_portrait_exists():
    assert render_twin_voice_section("") == ""
    section = render_twin_voice_section(format_portrait_for_prompt(PROFILE))
    assert "=== HOW YOU SOUND ===" in section
    assert "Stay in this voice" in section
    assert "newer fact wins" in section


def test_parse_council_reply_from_fenced_json():
    raw = """Sure.
```json
{
  "phrases": ["well now", "that's about the size of it", "well now"],
  "beliefs": ["Family comes first."],
  "corrections": ["Don't call me honey."]
}
```
"""
    notes = parse_council_reply(raw)
    assert notes["phrases"] == ["well now", "that's about the size of it"]
    assert notes["beliefs"] == ["Family comes first."]
    assert notes["corrections"] == ["Don't call me honey."]
    empty = parse_council_reply("no json here")
    assert empty == {"phrases": [], "beliefs": [], "corrections": []}


def test_merge_phrases_prefers_fresh_then_caps():
    merged = merge_signature_phrases(
        ["old one", "well now"],
        ["Well now", "new phrase"],
    )
    assert merged == ["Well now", "new phrase", "old one"]
    capped = merge_signature_phrases(
        ["keep me"],
        ["a", "b", "c", "d", "e", "f", "g", "h", "i"],
        cap=8,
    )
    assert capped == ["a", "b", "c", "d", "e", "f", "g", "h"]
    assert "i" not in capped
    assert "keep me" not in capped


def test_should_run_skips_local_and_thin_talk():
    assert should_run_council(
        cheap_kind="cloud",
        new_message_count=VOICE_COUNCIL_AFTER_MESSAGES,
        user_turn_count=2,
    )
    assert should_run_council(
        cheap_kind="local",
        new_message_count=20,
        user_turn_count=10,
    ) is False
    assert should_run_council(
        cheap_kind="cloud",
        new_message_count=4,
        user_turn_count=2,
    ) is False
    assert should_run_council(
        cheap_kind="compat",
        new_message_count=8,
        user_turn_count=1,
    ) is False


def test_plan_skips_duplicate_facts_and_tags_kinds():
    notes = {
        "phrases": ["well now"],
        "beliefs": ["Family comes first."],
        "corrections": ["Don't call me honey."],
    }
    existing = [{"fact": 'They often say: "well now"'}]
    plan = plan_voice_updates(
        notes,
        existing_facts=existing,
        existing_phrases=["that's about the size of it"],
    )
    kinds = {f["kind"] for f in plan["facts"]}
    texts = [f["fact"] for f in plan["facts"]]
    assert "phrase" not in kinds  # duplicate phrase skipped
    assert "belief" in kinds
    assert any("Family comes first" in t for t in texts)
    assert any("honey" in t.lower() for t in texts)
    assert plan["phrases"][0] == "well now"


def test_council_payload_labels_user_vs_twin():
    payload = build_council_user_payload(
        [
            {"role": "user", "content": "well now, that's a storm"},
            {"role": "assistant", "content": "It surely is."},
        ],
        ["well now"],
    )
    assert "Phrases already captured" in payload
    assert "USER: well now, that's a storm" in payload
    assert "ASSISTANT: It surely is." in payload
    assert "extract from USER" in payload
    assert "committee" not in VOICE_COUNCIL_SYSTEM.lower()
    assert "ensemble" not in VOICE_COUNCIL_SYSTEM.lower()


def test_twin_injects_cached_portrait_and_runs_council():
    twin = (ROOT / "routers" / "twin.py").read_text(encoding="utf-8")
    assert "voice_blob" in twin
    assert "render_twin_voice_section" in twin
    assert "format_portrait_for_prompt" in twin
    assert "_after_twin_turn" in twin
    assert "maybe_run_voice_council" in twin
    assert "personality_profiles" in twin
    # Must not regenerate the portrait on a chat turn.
    assert "_generate_profile" not in twin
    assert "personality/refresh" not in twin


def test_memory_refresh_keeps_voice_council_facts():
    memory = (ROOT / "routers" / "memory.py").read_text(encoding="utf-8")
    assert '"$nin": ["voice_council"]' in memory
    assert '"source": "archive"' in memory
    assert memory.count("$nin") >= 2  # refresh + rebuild


def test_catalog_blurbs_explain_jobs_without_new_function():
    tasks = {f["task"] for f in FUNCTIONS}
    assert tasks == {"chat", "interview", "tools", "cheap", "long_context", "embeddings"}
    by_id = {f["id"]: f for f in FUNCTIONS}
    assert "portrait" in by_id["chat"]["blurb"].lower()
    assert "archive" in by_id["interview"]["blurb"].lower()
    assert "sounds like you" in by_id["cheap"]["blurb"].lower()
    router_src = (ROOT / "services" / "llm_router.py").read_text(encoding="utf-8")
    assert '"ollama"' not in router_src.split("PROVIDERS", 1)[1].split("TASKS", 1)[0]


def test_models_and_personality_copy_is_grandmother_simple():
    models = (REPO / "frontend" / "src" / "pages" / "Models.jsx").read_text(encoding="utf-8")
    personality = (REPO / "frontend" / "src" / "pages" / "Personality.jsx").read_text(encoding="utf-8")
    assert "work together" in models
    assert "keeps the voice honest" in models
    assert "ensemble" not in models.lower()
    assert "committee" not in models.lower()
    assert "This portrait is what the twin uses when it talks as you" in personality
    assert 'to="/models"' in personality
    assert 'to="/twin"' in personality
    assert 'to="/interviewer"' in personality


def test_phone_twin_uses_cached_portrait():
    twilio = (ROOT / "routers" / "twilio_voice.py").read_text(encoding="utf-8")
    assert "format_portrait_for_prompt" in twilio
    assert "How you sound" in twilio
