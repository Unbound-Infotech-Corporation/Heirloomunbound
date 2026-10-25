"""Owner-controlled living vs posthumous anchor for the twin.

The twin always separates filed memory from what someone is saying now.
Posthumous mode treats the archive as a fixed past and does not pretend
to see the present day.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

LIVING = "living"
POSTHUMOUS = "posthumous"
MODES = frozenset({LIVING, POSTHUMOUS})

DEFAULT_LONG_SESSION_TURNS = 40
DEFAULT_SESSIONS_PER_DAY = 8
DEFAULT_LONG_SESSION_MINUTES = 120

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def default_grief_thresholds() -> dict[str, int]:
    return {
        "long_session_turns": DEFAULT_LONG_SESSION_TURNS,
        "sessions_per_day": DEFAULT_SESSIONS_PER_DAY,
        "long_session_minutes": DEFAULT_LONG_SESSION_MINUTES,
    }


def default_memorial() -> dict[str, Any]:
    return {
        "mode": LIVING,
        "date": "",
        "contact_name": "",
        "contact_email": "",
        "grief": default_grief_thresholds(),
    }


def _clamp_int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, number))


def _clean_date(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    day = raw[:10]
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        return ""
    return day


def contact_email_problem(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if _clean_email(raw):
        return ""
    return "That contact email does not look right."


def _clean_email(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if not _EMAIL.match(raw):
        return ""
    return raw[:200]


def clamp_grief(raw: Any) -> dict[str, int]:
    src = raw if isinstance(raw, dict) else {}
    base = default_grief_thresholds()
    return {
        "long_session_turns": _clamp_int(
            src.get("long_session_turns", base["long_session_turns"]),
            base["long_session_turns"],
            8,
            400,
        ),
        "sessions_per_day": _clamp_int(
            src.get("sessions_per_day", base["sessions_per_day"]),
            base["sessions_per_day"],
            2,
            100,
        ),
        "long_session_minutes": _clamp_int(
            src.get("long_session_minutes", base["long_session_minutes"]),
            base["long_session_minutes"],
            20,
            720,
        ),
    }


def clamp_memorial(raw: Any) -> dict[str, Any]:
    src = raw if isinstance(raw, dict) else {}
    mode = str(src.get("mode") or LIVING).strip().lower()
    if mode not in MODES:
        mode = LIVING
    grief_raw = src.get("grief") if isinstance(src.get("grief"), dict) else {}
    # Flat keys from a settings form land on the same thresholds.
    for key in default_grief_thresholds():
        if key in src and key not in grief_raw:
            grief_raw = {**grief_raw, key: src.get(key)}
    return {
        "mode": mode,
        "date": _clean_date(src.get("date")),
        "contact_name": str(src.get("contact_name") or "").strip()[:120],
        "contact_email": _clean_email(src.get("contact_email")),
        "grief": clamp_grief(grief_raw),
    }


def merge_memorial(current: Any, patch: dict[str, Any]) -> dict[str, Any]:
    """Apply a partial owner update. Missing keys stay as they were."""
    base = clamp_memorial(current)
    if not patch:
        return base
    grief_patch = patch.get("grief") if isinstance(patch.get("grief"), dict) else {}
    flat_grief = {
        key: patch[key]
        for key in default_grief_thresholds()
        if key in patch and patch[key] is not None
    }
    next_raw = {
        "mode": patch["mode"] if patch.get("mode") is not None else base["mode"],
        "date": patch["date"] if "date" in patch and patch.get("date") is not None else base["date"],
        "contact_name": (
            patch["contact_name"]
            if "contact_name" in patch and patch.get("contact_name") is not None
            else base["contact_name"]
        ),
        "contact_email": (
            patch["contact_email"]
            if "contact_email" in patch and patch.get("contact_email") is not None
            else base["contact_email"]
        ),
        "grief": {**base["grief"], **grief_patch, **flat_grief},
    }
    return clamp_memorial(next_raw)


def memorial_from_user(user: Optional[dict]) -> dict[str, Any]:
    raw = None
    if isinstance(user, dict):
        raw = user.get("memorial")
        if raw is None:
            raw = user.get("studio_memorial")
    return clamp_memorial(raw)


def memorial_is_posthumous(settings: Any) -> bool:
    return clamp_memorial(settings)["mode"] == POSTHUMOUS


def memorial_prompt_block(settings: Any = None) -> str:
    """Prompt text for every mode, including the living default."""
    cfg = clamp_memorial(settings)
    separation = (
        'TEMPORAL ANCHOR: Keep two piles separate. '
        '"What I remember" is only what was filed before this conversation. '
        '"What you\'re telling me now" is this conversation, and it is not a memory you lived. '
        "Do not treat their news as something you witnessed, and do not invent a present you did not file."
    )
    if cfg["mode"] == POSTHUMOUS:
        if cfg["date"]:
            dated = (
                f" The life these memories come from ended on {cfg['date']}. "
                "Do not invent a different date."
            )
        else:
            dated = " No date is filed for when that life ended. Do not invent one."
        return (
            separation
            + " MEMORIAL MODE: These memories are a fixed past. Speak of them as memories, gently. "
            "Do not pretend to see current events, the news, or the present day. "
            "If they ask what you are doing today, or about something happening now, "
            "say that your memories stop where they were filed and you do not see the present day. "
            "You are not with them in the present."
            + dated
        )
    return (
        separation
        + " LIVING MODE: The owner is alive. You may speak with them as someone still here, "
        "but you still only know filed memories plus what they tell you in this conversation. "
        "You do not see the wider present day on your own."
    )
