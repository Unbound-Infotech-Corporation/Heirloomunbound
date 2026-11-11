"""Sealed-letter visibility for the heir portal.

A letter is visible only when it is sealed, its trigger has fired, and it
is linked to this heir. A stored heir id is the link. A recipient name is
a link only when it matches exactly one heir. Anything else stays hidden
and the owner is told it needs a recipient link.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

NEEDS_RECIPIENT_LINK = "needs a recipient link"


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


def normalize_recipient_name(value: Any) -> str:
    """Case-folded full name. Not a first-name or substring match."""
    return " ".join(str(value or "").casefold().split())


def linked_heir_id(letter: dict, heirs: list[dict] | None = None) -> str | None:
    """The one heir this letter may be shown to.

    A stored heir id always wins. A name is used only when exactly one heir
    record has that full name. Zero matches and two matches both stay unlinked.
    """
    stored = str(letter.get("recipient_heir_id") or "").strip()
    if stored:
        return stored
    target = normalize_recipient_name(letter.get("recipient_name"))
    if not target or not heirs:
        return None
    found: list[str] = []
    for row in heirs:
        heir_id = str(row.get("heir_id") or "").strip()
        if heir_id and normalize_recipient_name(row.get("name")) == target:
            found.append(heir_id)
    unique = set(found)
    if len(unique) == 1:
        return found[0]
    return None


def needs_recipient_link(letter: dict, heirs: list[dict] | None = None) -> bool:
    """True when no heir id is stored and the name is missing or not unique.

    An explicit heir id is already a link, even if the roster is not loaded.
    A dangling id (no remaining heir with that id) still needs a link when
    the roster is known.
    """
    stored = str(letter.get("recipient_heir_id") or "").strip()
    if stored:
        if heirs is None:
            return False
        return not any(str(row.get("heir_id") or "").strip() == stored for row in heirs)
    return linked_heir_id(letter, heirs) is None


def letter_unlocked(
    letter: dict,
    heir: dict,
    now: datetime,
    heirs: list[dict] | None = None,
) -> bool:
    """A sealed letter is visible only to the heir it is linked to, after its trigger."""
    if not letter.get("sealed"):
        return False
    linked = linked_heir_id(letter, heirs)
    if not linked or linked != str(heir.get("heir_id") or "").strip():
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
