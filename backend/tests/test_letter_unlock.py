"""Sealed-letter heir fence — drafts and not-yet-due letters stay locked."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from letter_unlock import add_years, letter_unlocked, on_age_ready

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
HEIR = {
    "heir_id": "hr_test",
    "created_at": "2024-01-01T00:00:00+00:00",
    "released_at": "2026-01-01T00:00:00+00:00",
}


def test_unsealed_letter_never_unlocks():
    letter = {"sealed": False, "trigger": "on_release", "recipient_heir_id": "hr_test"}
    assert letter_unlocked(letter, HEIR, NOW) is False


def test_on_release_sealed_unlocks_for_that_heir():
    letter = {"sealed": True, "trigger": "on_release", "recipient_heir_id": "hr_test"}
    assert letter_unlocked(letter, HEIR, NOW) is True
    other = {**letter, "recipient_heir_id": "hr_other"}
    assert letter_unlocked(other, HEIR, NOW) is False


def test_on_date_respects_delivery_date():
    past = {"sealed": True, "trigger": "on_date", "delivery_date": "2020-01-01"}
    future = {"sealed": True, "trigger": "on_date", "delivery_date": "2099-01-01"}
    missing = {"sealed": True, "trigger": "on_date"}
    assert letter_unlocked(past, HEIR, NOW) is True
    assert letter_unlocked(future, HEIR, NOW) is False
    assert letter_unlocked(missing, HEIR, NOW) is False


def test_on_age_does_not_unlock_on_release_alone():
    letter = {"sealed": True, "trigger": "on_age", "delivery_age": 18}
    heir = {"heir_id": "hr_test", "released_at": NOW.isoformat()}
    assert letter_unlocked(letter, heir, NOW) is False
    assert on_age_ready(letter, heir, NOW) is False


def test_on_age_uses_birth_date_when_present():
    letter = {"sealed": True, "trigger": "on_age", "delivery_age": 18}
    young = {**HEIR, "birth_date": "2015-01-01T00:00:00+00:00"}
    ready = {**HEIR, "birth_date": "2000-01-01T00:00:00+00:00"}
    assert letter_unlocked(letter, young, NOW) is False
    assert letter_unlocked(letter, ready, NOW) is True


def test_on_age_falls_back_to_heir_created_at():
    letter = {"sealed": True, "trigger": "on_age", "delivery_age": 18}
    recent = {**HEIR, "created_at": "2020-01-01T00:00:00+00:00"}
    old = {**HEIR, "created_at": "2000-01-01T00:00:00+00:00"}
    assert letter_unlocked(letter, recent, NOW) is False
    assert letter_unlocked(letter, old, NOW) is True


def test_on_age_missing_age_stays_locked():
    letter = {"sealed": True, "trigger": "on_age"}
    assert letter_unlocked(letter, HEIR, NOW) is False


def test_add_years_handles_leap_day():
    leap = datetime(2020, 2, 29, tzinfo=timezone.utc)
    assert add_years(leap, 1) == datetime(2021, 2, 28, tzinfo=timezone.utc)


def test_portal_uses_shared_unlock_helper():
    src = (
        Path(__file__).resolve().parents[1] / "routers" / "heir_portal.py"
    ).read_text(encoding="utf-8")
    assert "from letter_unlock import letter_unlocked" in src
    assert "letter_unlocked(letter, heir, now)" in src
    assert '"sealed": True' in src
    assert "if trig == \"on_age\"" not in src
