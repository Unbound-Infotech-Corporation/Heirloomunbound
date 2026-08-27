"""Twin phone-line policy — allowlist, hours (handoff only), unknown callers.

No Retell imports here. Hours never silence the Twin; they only gate Reach-me
transfer. Outbound as the Twin is an owner-studio concern, not this module.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

WHO_CAN_CALL = frozenset({"allowlist", "anyone"})
UNKNOWN_POLICIES = frozenset({"decline", "message"})
DISCLOSURE = frozenset({"never", "unknown", "always"})
WEEKDAYS = range(7)  # Monday = 0, matching datetime.weekday()

DECLINE_SPOKEN = "This line is for family. I can't take this call."
OFF_SPOKEN = "This line is not taking calls right now."
MESSAGE_PROMPT = (
    "This line is for family. Please leave a short message after I finish, and I'll keep it."
)
MESSAGE_THANKS = "I've got that. Thank you. Goodbye."
HANDOFF_SPOKEN = "I'll put you through now."
HANDOFF_CLOSED = "I can't put you through right now. I can still talk."

_DIGIT_RE = re.compile(r"\D+")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def normalize_e164(raw: Any, *, default_region: str = "1") -> str:
    """Best-effort E.164. US/CA 10-digit numbers become +1XXXXXXXXXX."""
    text = str(raw or "").strip()
    if not text:
        return ""
    if text.startswith("+"):
        digits = re.sub(r"\D", "", text)
        return f"+{digits}" if len(digits) >= 8 else ""
    digits = re.sub(r"\D", "", text)
    if not digits:
        return ""
    if len(digits) == 10 and default_region:
        return f"+{default_region}{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if len(digits) >= 8:
        return f"+{digits}"
    return ""


def e164_equal(a: Any, b: Any) -> bool:
    left, right = normalize_e164(a), normalize_e164(b)
    return bool(left) and left == right


def default_settings() -> dict[str, Any]:
    return {
        "answering": False,
        "who_can_call": "allowlist",
        "allowlist": [],
        "unknown_policy": "decline",
        "owner_e164": "",
        "hours_enabled": False,
        "timezone": "America/Los_Angeles",
        "hours_windows": [
            {"days": [0, 1, 2, 3, 4], "start": "09:00", "end": "17:00"},
        ],
        "handoff_enabled": False,
        "handoff_e164": "",
        "disclosure": "unknown",
        "record": True,
    }


def _clamp_hhmm(raw: Any, fallback: str) -> str:
    text = str(raw or "").strip()
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", text)
    if not m:
        return fallback
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _clamp_window(raw: Any) -> Optional[dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    days: list[int] = []
    for item in raw.get("days") or []:
        try:
            day = int(item)
        except (TypeError, ValueError):
            continue
        if day in WEEKDAYS and day not in days:
            days.append(day)
    if not days:
        return None
    return {
        "days": days,
        "start": _clamp_hhmm(raw.get("start"), "09:00"),
        "end": _clamp_hhmm(raw.get("end"), "17:00"),
    }


def _clamp_allow_entry(raw: Any) -> Optional[dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    e164 = normalize_e164(raw.get("e164") or raw.get("phone") or raw.get("number"))
    if not e164:
        return None
    name = str(raw.get("name") or "").strip()[:80]
    heir_id = str(raw.get("heir_id") or "").strip()[:64]
    entry: dict[str, Any] = {"e164": e164, "name": name}
    if heir_id:
        entry["heir_id"] = heir_id
    return entry


def clamp_settings(raw: Any) -> dict[str, Any]:
    src = default_settings()
    if not isinstance(raw, dict):
        return src
    src["answering"] = bool(raw.get("answering", src["answering"]))
    who = str(raw.get("who_can_call") or src["who_can_call"]).strip().lower()
    src["who_can_call"] = who if who in WHO_CAN_CALL else "allowlist"
    unknown = str(raw.get("unknown_policy") or src["unknown_policy"]).strip().lower()
    src["unknown_policy"] = unknown if unknown in UNKNOWN_POLICIES else "decline"
    disc = str(raw.get("disclosure") or src["disclosure"]).strip().lower()
    src["disclosure"] = disc if disc in DISCLOSURE else "unknown"
    src["owner_e164"] = normalize_e164(raw.get("owner_e164"))
    src["handoff_enabled"] = bool(raw.get("handoff_enabled", False))
    src["handoff_e164"] = normalize_e164(raw.get("handoff_e164"))
    src["hours_enabled"] = bool(raw.get("hours_enabled", False))
    tz = str(raw.get("timezone") or src["timezone"]).strip() or src["timezone"]
    try:
        ZoneInfo(tz)
        src["timezone"] = tz
    except ZoneInfoNotFoundError:
        src["timezone"] = "America/Los_Angeles"
    windows: list[dict[str, Any]] = []
    for item in raw.get("hours_windows") or []:
        clamped = _clamp_window(item)
        if clamped:
            windows.append(clamped)
    if windows:
        src["hours_windows"] = windows
    allow: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw.get("allowlist") or []:
        entry = _clamp_allow_entry(item)
        if not entry or entry["e164"] in seen:
            continue
        seen.add(entry["e164"])
        allow.append(entry)
    src["allowlist"] = allow[:80]
    src["record"] = bool(raw.get("record", True))
    return src


def match_allowlist(from_e164: str, settings: dict[str, Any]) -> Optional[dict[str, Any]]:
    needle = normalize_e164(from_e164)
    if not needle:
        return None
    for entry in settings.get("allowlist") or []:
        if e164_equal(entry.get("e164"), needle):
            return entry
    return None


def is_owner_caller(from_e164: str, settings: dict[str, Any]) -> bool:
    owner = normalize_e164(settings.get("owner_e164"))
    return bool(owner) and e164_equal(from_e164, owner)


def local_now(settings: dict[str, Any], now: Optional[datetime] = None) -> datetime:
    stamp = now or _now_utc()
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    name = str(settings.get("timezone") or "UTC").strip() or "UTC"
    if name.upper() in {"UTC", "GMT", "Z"}:
        return stamp.astimezone(timezone.utc)
    try:
        zone = ZoneInfo(name)
    except ZoneInfoNotFoundError:
        zone = timezone.utc
    return stamp.astimezone(zone)


def _minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def in_hours(settings: dict[str, Any], now: Optional[datetime] = None) -> bool:
    """True when Reach-me transfer is allowed. Twin answering ignores this."""
    if not settings.get("hours_enabled"):
        return True
    local = local_now(settings, now)
    weekday = local.weekday()
    current = local.hour * 60 + local.minute
    for window in settings.get("hours_windows") or []:
        days = window.get("days") or []
        start = _minutes(str(window.get("start") or "00:00"))
        end = _minutes(str(window.get("end") or "23:59"))
        if start <= end:
            if weekday in days and start <= current < end:
                return True
            continue
        # Overnight window, e.g. Friday 22:00–06:00 continues into Saturday morning.
        if weekday in days and current >= start:
            return True
        yesterday = (weekday - 1) % 7
        if yesterday in days and current < end:
            return True
    return False


def handoff_allowed(settings: dict[str, Any], now: Optional[datetime] = None) -> bool:
    if not settings.get("handoff_enabled"):
        return False
    if not normalize_e164(settings.get("handoff_e164")):
        return False
    return in_hours(settings, now)


def should_disclose(settings: dict[str, Any], *, known_family: bool) -> bool:
    mode = str(settings.get("disclosure") or "unknown")
    if mode == "always":
        return True
    if mode == "never":
        return False
    return not known_family


def disclosure_line(name: str) -> str:
    who = (name or "").strip() or "this person"
    return f"This is {who}'s Heirloom Twin."


def outbound_allowed(to_e164: str, settings: dict[str, Any]) -> bool:
    """Owner studio may dial allowlisted numbers (or the owner's own cell)."""
    dest = normalize_e164(to_e164)
    if not dest:
        return False
    if is_owner_caller(dest, settings):
        return True
    return match_allowlist(dest, settings) is not None


@dataclass(frozen=True)
class PolicyDecision:
    action: str  # answer | decline | message
    audience: str  # owner | heir | caller
    caller_is_owner: bool
    known_family: bool
    disclose: bool
    allowlist_entry: Optional[dict[str, Any]]
    spoken: str

    @property
    def allow(self) -> bool:
        return self.action == "answer"


def decide_inbound(
    from_e164: str,
    settings: dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> PolicyDecision:
    """Who may talk to the Twin on this inbound call.

    `now` is accepted so hours can be tested, but inbound answering does not
    consult hours — only handoff_allowed does.
    """
    _ = now  # hours do not gate answering
    clamped = clamp_settings(settings)
    if not clamped.get("answering"):
        return PolicyDecision(
            action="decline",
            audience="caller",
            caller_is_owner=False,
            known_family=False,
            disclose=False,
            allowlist_entry=None,
            spoken=OFF_SPOKEN,
        )

    if is_owner_caller(from_e164, clamped):
        return PolicyDecision(
            action="answer",
            audience="owner",
            caller_is_owner=True,
            known_family=True,
            disclose=should_disclose(clamped, known_family=True),
            allowlist_entry=None,
            spoken="",
        )

    hit = match_allowlist(from_e164, clamped)
    if hit is not None:
        heir = bool(hit.get("heir_id"))
        return PolicyDecision(
            action="answer",
            audience="heir" if heir else "caller",
            caller_is_owner=False,
            known_family=True,
            disclose=should_disclose(clamped, known_family=True),
            allowlist_entry=hit,
            spoken="",
        )

    if clamped.get("who_can_call") == "anyone":
        return PolicyDecision(
            action="answer",
            audience="caller",
            caller_is_owner=False,
            known_family=False,
            disclose=should_disclose(clamped, known_family=False),
            allowlist_entry=None,
            spoken="",
        )

    if clamped.get("unknown_policy") == "message":
        return PolicyDecision(
            action="message",
            audience="caller",
            caller_is_owner=False,
            known_family=False,
            disclose=False,
            allowlist_entry=None,
            spoken=MESSAGE_PROMPT,
        )

    return PolicyDecision(
        action="decline",
        audience="caller",
        caller_is_owner=False,
        known_family=False,
        disclose=False,
        allowlist_entry=None,
        spoken=DECLINE_SPOKEN,
    )


_HANDOFF_RE = re.compile(
    r"\b(speak to (you|them|him|her) in person|the real (you|person)|"
    r"transfer( me)?|put me through|talk to a human|"
    r"get (them|him|her|you) on the (phone|line)|connect me|"
    r"hand ?off)\b",
    re.IGNORECASE,
)


def wants_handoff(utterance: str) -> bool:
    return bool(_HANDOFF_RE.search(utterance or ""))
