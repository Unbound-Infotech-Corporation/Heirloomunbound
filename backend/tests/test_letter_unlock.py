"""Sealed-letter heir fence — drafts and not-yet-due letters stay locked."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from letter_unlock import (
    NEEDS_RECIPIENT_LINK,
    add_years,
    letter_unlocked,
    needs_recipient_link,
    on_age_ready,
)

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
    past = {"sealed": True, "trigger": "on_date", "delivery_date": "2020-01-01", "recipient_heir_id": "hr_test"}
    future = {"sealed": True, "trigger": "on_date", "delivery_date": "2099-01-01", "recipient_heir_id": "hr_test"}
    missing = {"sealed": True, "trigger": "on_date", "recipient_heir_id": "hr_test"}
    assert letter_unlocked(past, HEIR, NOW) is True
    assert letter_unlocked(future, HEIR, NOW) is False
    assert letter_unlocked(missing, HEIR, NOW) is False


def test_on_age_does_not_unlock_on_release_alone():
    letter = {"sealed": True, "trigger": "on_age", "delivery_age": 18, "recipient_heir_id": "hr_test"}
    heir = {"heir_id": "hr_test", "released_at": NOW.isoformat()}
    assert letter_unlocked(letter, heir, NOW) is False
    assert on_age_ready(letter, heir, NOW) is False


def test_on_age_uses_birth_date_when_present():
    letter = {"sealed": True, "trigger": "on_age", "delivery_age": 18, "recipient_heir_id": "hr_test"}
    young = {**HEIR, "birth_date": "2015-01-01T00:00:00+00:00"}
    ready = {**HEIR, "birth_date": "2000-01-01T00:00:00+00:00"}
    assert letter_unlocked(letter, young, NOW) is False
    assert letter_unlocked(letter, ready, NOW) is True


def test_on_age_falls_back_to_heir_created_at():
    letter = {"sealed": True, "trigger": "on_age", "delivery_age": 18, "recipient_heir_id": "hr_test"}
    recent = {**HEIR, "created_at": "2020-01-01T00:00:00+00:00"}
    old = {**HEIR, "created_at": "2000-01-01T00:00:00+00:00"}
    assert letter_unlocked(letter, recent, NOW) is False
    assert letter_unlocked(letter, old, NOW) is True


def test_on_age_missing_age_stays_locked():
    letter = {"sealed": True, "trigger": "on_age", "recipient_heir_id": "hr_test"}
    assert letter_unlocked(letter, HEIR, NOW) is False


def test_add_years_handles_leap_day():
    leap = datetime(2020, 2, 29, tzinfo=timezone.utc)
    assert add_years(leap, 1) == datetime(2021, 2, 28, tzinfo=timezone.utc)


FAMILY = [
    {"heir_id": "hr_test", "name": "Elena"},
    {"heir_id": "hr_other", "name": "Sam"},
]


def test_name_only_letter_is_hidden_until_it_is_linked():
    letter = {"sealed": True, "trigger": "on_release", "recipient_name": "Elena"}
    assert letter_unlocked(letter, HEIR, NOW) is False
    assert letter_unlocked(letter, {**HEIR, "name": "Elena"}, NOW) is False
    assert letter_unlocked(letter, {"heir_id": "hr_other", "name": "Sam"}, NOW, FAMILY) is False
    assert needs_recipient_link(letter, []) is True


def test_unique_full_name_links_exactly_one_heir():
    letter = {"sealed": True, "trigger": "on_release", "recipient_name": "  elena "}
    assert letter_unlocked(letter, HEIR, NOW, FAMILY) is True
    assert letter_unlocked(letter, {"heir_id": "hr_other", "name": "Sam"}, NOW, FAMILY) is False
    assert needs_recipient_link(letter, FAMILY) is False
    partial = {**letter, "recipient_name": "Ele"}
    assert letter_unlocked(partial, HEIR, NOW, FAMILY) is False
    assert needs_recipient_link(partial, FAMILY) is True


def test_shared_or_missing_name_needs_a_recipient_link():
    twins = [*FAMILY, {"heir_id": "hr_two", "name": "Elena"}]
    shared = {"sealed": True, "trigger": "on_release", "recipient_name": "Elena"}
    assert letter_unlocked(shared, HEIR, NOW, twins) is False
    assert letter_unlocked(shared, {"heir_id": "hr_two", "name": "Elena"}, NOW, twins) is False
    assert needs_recipient_link(shared, twins) is True
    unnamed = {"sealed": True, "trigger": "on_release"}
    assert letter_unlocked(unnamed, HEIR, NOW, FAMILY) is False
    assert needs_recipient_link(unnamed, FAMILY) is True
    assert NEEDS_RECIPIENT_LINK == "needs a recipient link"
    explicit = {"sealed": True, "trigger": "on_release", "recipient_heir_id": "hr_test", "recipient_name": "Sam"}
    assert letter_unlocked(explicit, HEIR, NOW, FAMILY) is True
    assert letter_unlocked(explicit, {"heir_id": "hr_other", "name": "Sam"}, NOW, FAMILY) is False


def test_portal_uses_shared_unlock_helper():
    src = (
        Path(__file__).resolve().parents[1] / "routers" / "heir_portal.py"
    ).read_text(encoding="utf-8")
    assert "from letter_unlock import letter_unlocked" in src
    assert "letter_unlocked(letter, heir, now, heirs)" in src
    assert "letter_unlocked(l, heir, now, family)" in src
    assert '"sealed": True' in src
    assert "if trig == \"on_age\"" not in src
