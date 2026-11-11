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
_MONTHS = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sept": 9, "sep": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}
_MONTH_DAY = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december|"
    r"jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec)\.?\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)
_ISO_DAY = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_RELATIVE_SPAN = re.compile(r"\bin\s+(\d+)\s+(day|days|week|weeks)\b", re.IGNORECASE)
_OTHER_DATE = re.compile(
    r"\b(today|tomorrow|tonight|next\s+week|in\s+\d+\s+(?:day|days|week|weeks|month|months)|"
    r"january|february|march|april|june|july|august|september|october|november|december)\b|"
    r"\d{4}-\d{2}-\d{2}",
    re.IGNORECASE,
)


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


def _zone(tz_name: str):
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return timezone.utc


def _spoken_clock(text: str) -> tuple[int, int] | None:
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
    return hour, minute


def _safe_date(year: int, month: int, day: int):
    try:
        return datetime(year, month, day).date()
    except ValueError:
        return None


def _year_beside(text: str, start: int, end: int) -> int | None:
    """A year counts only when it sits against the month-day, not elsewhere in the note."""
    after = re.match(r"\s*,?\s*((?:19|20)\d{2})\b", text[end:end + 16])
    if after:
        return int(after.group(1))
    before = re.search(r"\b((?:19|20)\d{2})\s*,?\s*$", text[max(0, start - 12):start])
    if before:
        return int(before.group(1))
    return None


def _named_date(text: str, local_now: datetime, hour: int, minute: int):
    """The date cue closest to the clock. A story date farther away does not win."""
    raw = text or ""
    clock = _CLOCK.search(raw)
    anchor = clock.start() if clock else 0
    found: list[tuple[int, int, object]] = []

    def keep(match: re.Match, rank: int, day) -> None:
        if day is not None:
            found.append((abs(match.start() - anchor), rank, day))

    for match in re.finditer(r"\b(tomorrow|today|tonight)\b", raw, flags=re.IGNORECASE):
        word = match.group(1).lower()
        day = local_now.date() + (timedelta(days=1) if word == "tomorrow" else timedelta())
        keep(match, 0, day)
    for match in _RELATIVE_SPAN.finditer(raw):
        count = int(match.group(1))
        days = count * 7 if match.group(2).lower().startswith("week") else count
        keep(match, 1, local_now.date() + timedelta(days=days))
    for match in _WEEKDAY.finditer(raw):
        want = _WEEKDAYS[match.group(1).lower()]
        delta = (want - local_now.weekday()) % 7
        if delta == 0 and (hour, minute) <= (local_now.hour, local_now.minute):
            delta = 7
        keep(match, 2, local_now.date() + timedelta(days=delta))
    for match in _MONTH_DAY.finditer(raw):
        month = _MONTHS[match.group(1).lower().rstrip(".")]
        day_num = int(match.group(2))
        beside = _year_beside(raw, match.start(), match.end())
        year = beside if beside is not None else local_now.year
        target = _safe_date(year, month, day_num)
        if target is not None and beside is None:
            due = datetime(year, month, day_num, hour, minute, tzinfo=local_now.tzinfo)
            if due <= local_now:
                target = _safe_date(year + 1, month, day_num) or _safe_date(year + 1, month, 28)
        keep(match, 3, target)
    for match in _ISO_DAY.finditer(raw):
        keep(match, 4, _safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3))))
    if not found:
        return None
    found.sort(key=lambda item: (item[0], item[1]))
    return found[0][2]


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
    """A named clock time is the owner's wall clock, on the day they named."""
    zone = _zone(tz_name)
    stamp = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    local_now = stamp.astimezone(zone)
    clock = _spoken_clock(text)
    if clock is not None:
        hour, minute = clock
        target = _named_date(text, local_now, hour, minute)
        if target is None and _OTHER_DATE.search(text or ""):
            parsed = _parse_iso(raw_due)
            if parsed is None:
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=zone)
            target = parsed.astimezone(zone).date()
        if target is None:
            target = local_now.date()
            if (hour, minute) <= (local_now.hour, local_now.minute):
                target = target + timedelta(days=1)
        due = datetime(target.year, target.month, target.day, hour, minute, tzinfo=zone)
        return due.astimezone(timezone.utc).isoformat()
    parsed = _parse_iso(raw_due)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(timezone.utc).isoformat()
