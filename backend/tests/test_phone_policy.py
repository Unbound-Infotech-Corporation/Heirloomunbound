"""Unit tests for Twin phone-line policy. No Retell, no Mongo."""
from __future__ import annotations

from datetime import datetime, timezone

from phone_policy import (
    DECLINE_SPOKEN,
    MESSAGE_PROMPT,
    OFF_SPOKEN,
    clamp_settings,
    decide_inbound,
    default_settings,
    handoff_allowed,
    in_hours,
    normalize_e164,
    outbound_allowed,
    should_disclose,
    wants_handoff,
)


def test_normalize_e164_us_and_plus():
    assert normalize_e164("555-123-4567") == "+15551234567"
    assert normalize_e164("(555) 123-4567") == "+15551234567"
    assert normalize_e164("15551234567") == "+15551234567"
    assert normalize_e164("+44 20 7946 0958") == "+442079460958"
    assert normalize_e164("") == ""
    assert normalize_e164("abc") == ""


def test_clamp_settings_drops_junk_and_dedupes():
    out = clamp_settings({
        "who_can_call": "robots",
        "unknown_policy": "yell",
        "disclosure": "maybe",
        "timezone": "Not/AZone",
        "allowlist": [
            {"e164": "5551234567", "name": "Sam"},
            {"e164": "+1 555 123 4567", "name": "Duplicate"},
            {"name": "no number"},
        ],
        "hours_windows": [{"days": [0, 9, 1], "start": "9:00", "end": "17:00"}],
    })
    assert out["who_can_call"] == "allowlist"
    assert out["unknown_policy"] == "decline"
    assert out["disclosure"] == "unknown"
    assert out["timezone"] == "America/Los_Angeles"
    assert len(out["allowlist"]) == 1
    assert out["allowlist"][0]["name"] == "Sam"
    assert out["hours_windows"][0]["days"] == [0, 1]
    assert out["hours_windows"][0]["start"] == "09:00"


def _family(**kwargs):
    base = default_settings()
    base["answering"] = True
    base["allowlist"] = [{"e164": "+15551230000", "name": "Sam", "heir_id": "heir_1"}]
    base["owner_e164"] = "+15559990000"
    base.update(kwargs)
    return clamp_settings(base)


def test_unknown_declines_by_default():
    decision = decide_inbound("+15550001111", _family())
    assert decision.action == "decline"
    assert decision.spoken == DECLINE_SPOKEN
    assert not decision.allow


def test_unknown_can_take_a_message():
    decision = decide_inbound("+15550001111", _family(unknown_policy="message"))
    assert decision.action == "message"
    assert decision.spoken == MESSAGE_PROMPT


def test_allowlisted_heir_answers_without_disclosure():
    decision = decide_inbound("555-123-0000", _family())
    assert decision.action == "answer"
    assert decision.audience == "heir"
    assert decision.known_family is True
    assert decision.disclose is False
    assert decision.allowlist_entry["name"] == "Sam"


def test_owner_cell_is_owner_audience():
    decision = decide_inbound("+1 (555) 999-0000", _family())
    assert decision.caller_is_owner is True
    assert decision.audience == "owner"
    assert decision.action == "answer"


def test_anyone_answers_unknown_with_disclosure():
    decision = decide_inbound("+15550001111", _family(who_can_call="anyone"))
    assert decision.action == "answer"
    assert decision.audience == "caller"
    assert decision.disclose is True


def test_answering_off_declines_even_family():
    decision = decide_inbound("+15551230000", _family(answering=False))
    assert decision.action == "decline"
    assert decision.spoken == OFF_SPOKEN


def test_hours_do_not_silence_the_twin():
    settings = _family(
        hours_enabled=True,
        timezone="America/Los_Angeles",
        hours_windows=[{"days": [0], "start": "09:00", "end": "17:00"}],
    )
    sunday_night = datetime(2026, 8, 16, 4, 0, tzinfo=timezone.utc)  # Sunday 21:00 PT
    decision = decide_inbound("+15551230000", settings, now=sunday_night)
    assert decision.action == "answer"
    assert in_hours(settings, sunday_night) is False


def test_handoff_respects_hours():
    settings = _family(
        handoff_enabled=True,
        handoff_e164="+15557770000",
        hours_enabled=True,
        timezone="America/Los_Angeles",
        hours_windows=[{"days": [0, 1, 2, 3, 4], "start": "09:00", "end": "17:00"}],
    )
    monday_morning = datetime(2026, 8, 17, 17, 0, tzinfo=timezone.utc)  # 10:00 PT
    monday_evening = datetime(2026, 8, 18, 3, 0, tzinfo=timezone.utc)  # 20:00 PT Monday
    assert handoff_allowed(settings, monday_morning) is True
    assert handoff_allowed(settings, monday_evening) is False
    assert handoff_allowed({**settings, "handoff_enabled": False}, monday_morning) is False


def test_overnight_window():
    settings = clamp_settings({
        "hours_enabled": True,
        "timezone": "UTC",
        "hours_windows": [{"days": [4], "start": "22:00", "end": "06:00"}],
    })
    late = datetime(2026, 8, 21, 23, 0, tzinfo=timezone.utc)  # Friday
    early = datetime(2026, 8, 22, 5, 0, tzinfo=timezone.utc)  # Saturday 05:00, still Friday's window
    midday = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    assert in_hours(settings, late) is True
    assert in_hours(settings, early) is True
    assert in_hours(settings, midday) is False


def test_outbound_allowlist_only():
    settings = _family()
    assert outbound_allowed("555-123-0000", settings) is True
    assert outbound_allowed("555-999-0000", settings) is True  # owner cell
    assert outbound_allowed("555-000-1111", settings) is False


def test_disclosure_modes():
    always = _family(disclosure="always")
    never = _family(disclosure="never")
    unknown = _family(disclosure="unknown")
    assert should_disclose(always, known_family=True) is True
    assert should_disclose(never, known_family=False) is False
    assert should_disclose(unknown, known_family=True) is False
    assert should_disclose(unknown, known_family=False) is True


def test_wants_handoff_phrases():
    assert wants_handoff("can you put me through")
    assert wants_handoff("I need to speak to you in person")
    assert wants_handoff("please transfer me")
    assert not wants_handoff("how was the farm")
    assert not wants_handoff("I couldn't reach you last week")
