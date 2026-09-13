"""Sealed-letter visibility for the heir portal.

A letter is visible only when it is sealed AND its trigger has fired.
Heirs must never see drafts or on_age / on_date letters that are not due.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


def parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_years(dt: datetime, years: int) -> datetime:
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        # Feb 29 → Feb 28 in a non-leap target year
        return dt.replace(year=dt.year + years, day=28)


def on_age_ready(letter: dict, heir: dict, now: datetime) -> bool:
    """Unlock only when delivery_age years have passed from a real date.

    Prefer the heir's birth date. Without one, wait delivery_age years from
    when the heir record was created (or released). Missing age or date
    stays locked — never unlock on release alone.
    """
    raw_age = letter.get("delivery_age")
    try:
        age = int(raw_age)
    except (TypeError, ValueError):
        return False
    if age < 0 or age > 150:
        return False
    anchor = (
        parse_iso(heir.get("birth_date") or heir.get("date_of_birth"))
        or parse_iso(heir.get("created_at"))
        or parse_iso(heir.get("released_at"))
    )
    if not anchor:
        return False
    return now >= add_years(anchor, age)


def letter_unlocked(letter: dict, heir: dict, now: datetime) -> bool:
    """A sealed letter is visible to the heir iff it's been sealed AND its
    trigger has fired."""
    if not letter.get("sealed"):
        return False
    rid = letter.get("recipient_heir_id")
    if rid and rid != heir.get("heir_id"):
        return False

    trig = letter.get("trigger", "on_release")
    if trig == "on_release":
        return True
    if trig == "on_date":
        target = parse_iso(letter.get("delivery_date"))
        if not target:
            return False
        return now >= target
    if trig == "on_age":
        return on_age_ready(letter, heir, now)
    return False
