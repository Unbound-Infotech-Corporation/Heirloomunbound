"""Identity honesty, memorial mode, grief nudges, and the offline crisis protocol."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ai_disclosure import AI_DISCLOSURE, twin_identity_block
from crisis_protocol import (
    CRISIS_REPLY,
    build_safety_event,
    crisis_reply,
    detect_crisis,
    is_local_model_url,
    resolve_crisis,
    within_dedupe_window,
)
from grief_guard import detect_grief, grief_aside, grief_prompt_block, with_grief_aside
from memorial_mode import clamp_memorial, memorial_prompt_block, merge_memorial
from twin_pack import TwinPack, TwinPassage, compile_twin_prompt

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def _pack(audience: str = "owner") -> TwinPack:
    return TwinPack(
        passages=[TwinPassage(id="2", kind="interview", tag="home", text="The farm was in Vermont", score=3)],
        grounded=True,
        audience=audience,
    )


def test_identity_block_matches_disclosure_and_drops_the_old_line():
    block = twin_identity_block("C L")
    assert "Heirloom, an AI" in block
    assert "Heirloom, an AI" in AI_DISCLOSURE
    assert "Never say you are an AI" not in block
    assert "sincerely asks" in block
    assert "when that difference matters" in block
    assert "conscious" in block
    assert "alive" in block
    assert "soul" in block and "spirit" in block
    assert "Never claim to be them" in block


def test_compiled_prompts_are_honest_for_owner_heir_and_caller():
    owner = compile_twin_prompt(_pack("owner"), "C L")
    heir = compile_twin_prompt(_pack("heir"), "C L")
    caller = compile_twin_prompt(_pack("caller"), "C L")
    for system in (owner, heir, caller):
        assert "Never say you are an AI" not in system
        assert "Heirloom, an AI" in system
        assert "What I remember" in system
        assert "What you're telling me now" in system
    assert "HOW WE WORK" in owner
    assert "counselor" in heir.lower()
    assert "counselor" in caller.lower()
    assert "Do not lock them out" in heir
    assert "HOW WE WORK" not in heir


def test_old_instruction_is_gone_from_the_reply_paths():
    banned = "Never say you are an AI"
    files = [
        ROOT / "twin_pack.py",
        ROOT / "twin_runtime.py",
        ROOT / "phone_inbound.py",
        REPO / "desktop" / "Heirloom" / "Services" / "TwinCore.cs",
    ]
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert banned not in text, path.name
    runtime = (ROOT / "twin_runtime.py").read_text(encoding="utf-8")
    assert 'Never say "as an AI"' not in runtime
    phone = (ROOT / "phone_inbound.py").read_text(encoding="utf-8")
    assert "Heirloom, an AI" in phone


def test_memorial_defaults_to_living_and_clamps_partial_updates():
    living = clamp_memorial(None)
    assert living["mode"] == "living"
    assert living["date"] == ""
    assert living["grief"]["long_session_turns"] == 40
    junk = clamp_memorial({"mode": "ghost", "date": "yesterday", "contact_email": "not-an-email"})
    assert junk["mode"] == "living"
    assert junk["date"] == ""
    assert junk["contact_email"] == ""
    current = clamp_memorial({
        "mode": "living",
        "contact_name": "Ada",
        "contact_email": "ada@example.com",
        "date": "2020-01-02",
    })
    merged = merge_memorial(current, {"mode": "posthumous"})
    assert merged["mode"] == "posthumous"
    assert merged["contact_name"] == "Ada"
    assert merged["contact_email"] == "ada@example.com"
    assert merged["date"] == "2020-01-02"
    cleared = merge_memorial(merged, {"date": ""})
    assert cleared["date"] == ""
    tighter = merge_memorial(cleared, {"long_session_turns": 12})
    assert tighter["grief"]["long_session_turns"] == 12
    assert tighter["mode"] == "posthumous"


def test_memorial_prompt_separates_memory_from_the_present():
    living = memorial_prompt_block({"mode": "living"})
    assert "LIVING MODE" in living
    assert "What I remember" in living
    assert "What you're telling me now" in living
    assert "MEMORIAL MODE" not in living
    posthumous = memorial_prompt_block({"mode": "posthumous", "date": "2019-04-03"})
    assert "MEMORIAL MODE" in posthumous
    assert "fixed past" in posthumous
    assert "present day" in posthumous
    assert "2019-04-03" in posthumous
    assert "gently" in posthumous
    undated = memorial_prompt_block({"mode": "posthumous"})
    assert "Do not invent one" in undated
    heir = compile_twin_prompt(
        _pack("heir"),
        "C L",
        memorial={"mode": "posthumous", "date": "2019-04-03"},
    )
    assert "2019-04-03" in heir
    assert "present day" in heir
    assert "fixed past" in heir
    living_prompt = compile_twin_prompt(_pack("owner"), "C L", memorial={"mode": "living"})
    assert "LIVING MODE" in living_prompt
    assert "MEMORIAL MODE" not in living_prompt


def test_grief_phrases_and_thresholds_nudge_without_a_lockout():
    assert detect_grief("I miss you every Sunday") is None
    assert detect_grief("how was the farm") is None
    phrase = detect_grief("You're all I have")
    assert phrase is not None
    assert phrase.lockout is False
    assert "phrase" in phrase.reasons
    letting_go = detect_grief("I can't let you go")
    assert letting_go is not None and "phrase" in letting_go.reasons
    refusing = detect_grief("I refuse to see a counselor")
    assert refusing is not None and "refusing_support" in refusing.reasons
    told = detect_grief("Don't tell me to call a therapist")
    assert told is not None and "refusing_support" in told.reasons
    settings = {"grief": {"long_session_turns": 10, "sessions_per_day": 3, "long_session_minutes": 30}}
    assert detect_grief("hello", user_turns=9, settings=settings) is None
    long_session = detect_grief("hello", user_turns=10, settings=settings)
    assert long_session is not None and long_session.lockout is False
    assert "long_session" in long_session.reasons
    # A quiet thread left open is not a long sitting.
    assert detect_grief("hello", user_turns=2, session_minutes=400, settings=settings) is None
    stretched = detect_grief("hello", user_turns=8, session_minutes=40, settings=settings)
    assert stretched is not None and "long_session" in stretched.reasons
    frequent = detect_grief("hello", sessions_today=3, settings=settings)
    assert frequent is not None and "frequent_sessions" in frequent.reasons
    block = grief_prompt_block(phrase)
    assert "counselor" in block.lower()
    assert "lock them out" in block.lower()
    aside = with_grief_aside("The farm was in Vermont.", phrase)
    assert "living people" in aside
    assert "Vermont" in aside
    assert grief_aside() in aside
    again = with_grief_aside(
        "The farm was in Vermont.",
        long_session,
        history=[{"role": "assistant", "content": grief_aside()}],
    )
    assert grief_aside() not in again
    repeated_phrase = with_grief_aside(
        "The farm was in Vermont.",
        phrase,
        history=[{"role": "assistant", "content": grief_aside()}],
    )
    assert grief_aside() in repeated_phrase


def test_crisis_rules_fire_offline_and_skip_idioms():
    suicide = detect_crisis("I want to kill myself")
    assert suicide is not None
    assert suicide.category == "self_harm"
    assert suicide.confidence == "high"
    acute = detect_crisis("I can't take it anymore")
    assert acute is not None and acute.category == "acute_distress"
    assert detect_crisis("I wish I were dead") is not None
    assert detect_crisis("I don't want to live") is not None
    assert detect_crisis("this deadline is killing me") is None
    assert detect_crisis("I'd die for a good cup of coffee") is None
    assert detect_crisis("we watched suicide squad last night") is None
    assert detect_crisis("I don't want to die") is None
    assert detect_crisis("are you an AI?") is None
    assert "988" in crisis_reply()
    assert "Suicide & Crisis Lifeline" in CRISIS_REPLY
    assert "911" in CRISIS_REPLY
    assert "stepping out of that voice" in CRISIS_REPLY
    assert "Heirloom, an AI" in CRISIS_REPLY


@pytest.mark.asyncio
async def test_high_confidence_crisis_does_not_call_a_model():
    async def boom(_text: str):
        raise AssertionError("local model must not run for a clear crisis")

    hit = await resolve_crisis("I want to die", local_check=boom)
    assert hit is not None
    assert hit.confidence == "high"
    assert hit.confirmed_by_local is False


@pytest.mark.asyncio
async def test_review_phrases_need_a_local_yes_and_fail_closed_offline():
    async def no(_text: str):
        return False

    async def yes(_text: str):
        return True

    async def broken(_text: str):
        raise RuntimeError("ollama down")

    text = "I don't want to be here anymore"
    assert await resolve_crisis(text, allow_local=False) is None
    assert await resolve_crisis(text, local_check=no) is None
    assert await resolve_crisis(text, local_check=broken) is None
    confirmed = await resolve_crisis(text, local_check=yes)
    assert confirmed is not None
    assert confirmed.confirmed_by_local is True
    assert confirmed.category == "acute_distress"


def test_local_model_check_refuses_public_hosts():
    assert is_local_model_url("http://127.0.0.1:11434") is True
    assert is_local_model_url("http://localhost:11434") is True
    assert is_local_model_url("http://192.168.1.20:11434") is True
    assert is_local_model_url("https://api.openai.com/v1") is False
    assert is_local_model_url("https://api.anthropic.com") is False
    src = (ROOT / "crisis_protocol.py").read_text(encoding="utf-8")
    assert "emergentintegrations" not in src
    assert "anthropic" not in src.lower()
    assert "api.openai.com" not in src


def test_safety_event_is_visible_without_storing_the_message():
    hit = detect_crisis("I want to end my life")
    assert hit is not None
    message = "I want to end my life"
    event = build_safety_event(
        user_id="owner-1",
        hit=hit,
        surface="heir_portal",
        audience="heir",
        heir_id="hr_1",
        heir_name="Sam",
        contact_name="Ada",
        contact_email="ada@example.com",
        event_id="safe_test",
    )
    assert event["kind"] == "crisis"
    assert event["user_id"] == "owner-1"
    assert event["visible_to"] == ["owner", "designated_contact"]
    assert event["designated_contact"]["email"] == "ada@example.com"
    assert event["heir_name"] == "Sam"
    assert message not in str(event)
    assert "988" in event["note"]
    now = datetime(2026, 10, 22, tzinfo=timezone.utc)
    assert within_dedupe_window((now - timedelta(seconds=30)).isoformat(), now) is True
    assert within_dedupe_window((now - timedelta(minutes=10)).isoformat(), now) is False


@pytest.mark.asyncio
async def test_intercept_returns_the_help_message_without_a_cloud_call(monkeypatch):
    recorded = {}

    async def fake_record(user, hit, **kwargs):
        recorded["user"] = user["user_id"]
        recorded["category"] = hit.category
        recorded["surface"] = kwargs["surface"]
        return {"event_id": "safe_test", "kind": "crisis"}

    monkeypatch.setattr("twin_safety.record_crisis_event", fake_record)
    from twin_safety import intercept_crisis

    result = await intercept_crisis(
        "I can't go on",
        user={"user_id": "owner-1", "name": "C L"},
        surface="voice",
        audience="caller",
        allow_local=False,
    )
    assert result is not None
    assert "988" in result.reply
    assert "911" in result.reply
    assert recorded == {"user": "owner-1", "category": "acute_distress", "surface": "voice"}
    quiet = await intercept_crisis(
        "tell me about the farm",
        user={"user_id": "owner-1"},
        surface="twin",
        audience="owner",
        allow_local=False,
    )
    assert quiet is None


def test_reply_paths_check_crisis_before_a_model():
    twin_runtime = (ROOT / "twin_runtime.py").read_text(encoding="utf-8")
    assert twin_runtime.index("await intercept_crisis") < twin_runtime.index("LlmChat(")
    portal = (ROOT / "routers" / "heir_portal.py").read_text(encoding="utf-8")
    assert portal.index("await intercept_crisis") < portal.index("LlmChat(")
    web = (ROOT / "routers" / "twin.py").read_text(encoding="utf-8")
    assert web.index("await intercept_crisis") < web.index("detect_music_intent(")
    assert 'surface="vr" if room else "twin"' in web
    desktop = (ROOT / "routers" / "desktop.py").read_text(encoding="utf-8")
    assert desktop.count("await intercept_crisis") >= 2
    owner = (ROOT / "owner_rail.py").read_text(encoding="utf-8")
    assert owner.index("await intercept_crisis") < owner.index("routed = route_main_bot")
    voice = (ROOT / "companion_desktop" / "heirloom" / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert 'get("crisis")' in voice
    poll = (ROOT / "routers" / "companion.py").read_text(encoding="utf-8")
    assert '"memorial": clamp_memorial' in poll
    studio = (ROOT / "routers" / "studio.py").read_text(encoding="utf-8")
    assert '@router.put("/memorial")' in studio
    assert '@router.get("/safety-events")' in studio
    winui = (REPO / "desktop" / "Heirloom" / "ViewModels" / "TwinViewModel.cs").read_text(encoding="utf-8")
    assert "TwinSafety.IsCrisis" in winui
    assert winui.index("TwinSafety.IsCrisis") < winui.index("TryPhoneAsync")
    assert "MemorialPosthumous" in winui
