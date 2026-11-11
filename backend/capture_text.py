"""Verbatim capture text and owner-local due times.

Quick Capture keeps the owner's words as the archive text. An optional
cleanup may only drop or punctuate those words. It must not add any.
Facts and the personality portrait read ``content`` through ``canonical_text``.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_TOKEN = re.compile(r"[a-z0-9']+")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_CLOCK = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)\b",
    re.IGNORECASE,
)
_WEEKDAY = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.IGNORECASE,
)
_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def canonical_text(entry: dict | None) -> str:
    """The owner's words. A cleanup field is never a substitute."""
    if not isinstance(entry, dict):
        return ""
    return str(entry.get("content") or "")


def _words(text: str) -> set[str]:
    return {token for token in _TOKEN.findall((text or "").lower()) if len(token) > 3}


def _novel_words(original: str, candidate: str) -> bool:
    return bool(_words(candidate) - _words(original))


def grounded_cleanup(original: str, cleaned: str | None) -> str | None:
    """Return a cleanup that adds no words, or None."""
    source = (original or "").strip()
    raw = (cleaned or "").strip()
    if not source or not raw or raw == source:
        return None
    kept: list[str] = []
    for sentence in _SENTENCE.split(raw):
        piece = sentence.strip()
        if not piece or _novel_words(source, piece):
            continue
        kept.append(piece)
    if not kept:
        return None
    result = " ".join(kept).strip()
    if not result or result == source:
        return None
    return result


def grounded_title(original: str, title: str | None) -> str:
    fallback = " ".join((original or "").split())[:80]
    label = " ".join(str(title or "").split())
    if not label or _novel_words(original, label):
        return fallback[:120]
    return label[:120]


def grounded_tags(original: str, tags) -> list[str]:
    if not isinstance(tags, list):
        return []
    kept: list[str] = []
    for tag in tags:
        label = str(tag or "").strip()
        if not label or _novel_words(original, label):
            continue
        short = label[:40]
        if short not in kept:
            kept.append(short)
    return kept[:12]


def _valid_zone(name: str) -> str | None:
    text = (name or "").strip()
    if not text:
        return None
    try:
        ZoneInfo(text)
    except ZoneInfoNotFoundError:
        return None
    return text


def owner_timezone(user: dict | None, requested: str | None = None) -> str:
    """The owner's IANA zone. UTC when nothing valid is stored or sent."""
    candidates: list[object] = [requested]
    if isinstance(user, dict):
        candidates.append(user.get("timezone"))
        for key in ("phone_settings", "phone"):
            block = user.get(key)
            if isinstance(block, dict):
                candidates.append(block.get("timezone"))
    candidates.append(os.environ.get("HEIRLOOM_TIMEZONE"))
    for raw in candidates:
        zone = _valid_zone(str(raw or ""))
        if zone:
            return zone
    return "UTC"


def local_clock_line(now: datetime, tz_name: str) -> str:
    """Prompt clock: local wall time first, UTC second."""
    stamp = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    try:
        zone = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        zone = timezone.utc
        tz_name = "UTC"
    local = stamp.astimezone(zone)
    return (
        f"{local.strftime('%A %Y-%m-%d %H:%M')} {tz_name} "
        f"(UTC {stamp.astimezone(timezone.utc).isoformat()})"
    )


def _clock_due(text: str, tz_name: str, now: datetime) -> datetime | None:
    match = _CLOCK.search(text or "")
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    if hour > 12 or minute > 59:
        return None
    meridian = match.group(3).lower().replace(".", "")
    if meridian.startswith("p") and hour < 12:
        hour += 12
    if meridian.startswith("a") and hour == 12:
        hour = 0
    if hour > 23:
        return None
    try:
        zone = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        zone = timezone.utc
    stamp = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    local_now = stamp.astimezone(zone)
    day_match = _WEEKDAY.search(text or "")
    if day_match:
        want = _WEEKDAYS[day_match.group(1).lower()]
        delta = (want - local_now.weekday()) % 7
        if delta == 0 and (hour, minute) <= (local_now.hour, local_now.minute):
            delta = 7
        target = local_now.date() + timedelta(days=delta)
    else:
        target = local_now.date()
        if (hour, minute) <= (local_now.hour, local_now.minute):
            target = target + timedelta(days=1)
    return datetime(target.year, target.month, target.day, hour, minute, tzinfo=zone)


def _parse_iso(raw: str | None) -> datetime | None:
    text = (raw or "").strip()
    if not text or text.lower() == "null":
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def resolve_due_at(
    text: str,
    raw_due: str | None,
    tz_name: str,
    now: datetime,
) -> str | None:
    """A named clock time is the owner's wall clock, not UTC."""
    clock = _clock_due(text, tz_name, now)
    if clock is not None:
        return clock.astimezone(timezone.utc).isoformat()
    parsed = _parse_iso(raw_due)
    if parsed is None:
        return None
    try:
        zone = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        zone = timezone.utc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(timezone.utc).isoformat()
