"""Privacy gate for the Twin Box Observer.

A frame is dropped before any vision model sees it and before any text from
it is stored. Password managers, login fields, banking, one-time codes, and
chat apps (other people's messages) never become notes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time
from typing import Optional

_PASSWORD_MANAGERS = (
    "1password",
    "bitwarden",
    "lastpass",
    "keepass",
    "dashlane",
    "nordpass",
    "roboform",
    "enpass",
)
_PASSWORD_FIELD = re.compile(
    r"(?is)(?:\b(?:password|passphrase|passwd)\b\s*:|"
    r"\b(?:enter|current|new|confirm|master)\s+(?:your\s+)?(?:password|passphrase)\b|"
    r"\b(?:sign[\s-]?in|log[\s-]?in|login)\b.{0,120}\b(?:password|passphrase)\b|"
    r"\b(?:password|passphrase)\b.{0,80}\b(?:sign[\s-]?in|log[\s-]?in|username)\b)"
)
_OTP = re.compile(
    r"(?is)(\b(?:one[-\s]?time(?:\s+password)?|otp|2fa|two-factor|verification code|"
    r"authenticator|security code|passcode)\b|"
    r"\b(?:otp|passcode|verification)\b.{0,40}\b\d{6}\b|"
    r"\b\d{6}\b.{0,40}\b(?:otp|passcode|verification)\b)"
)
_BANK_NAMED = re.compile(
    r"(?i)\b(?:paypal|venmo|wellsfargo|wells fargo|bank of america|capital one|"
    r"citibank|american express|stripe checkout|add payment method)\b"
)
_BANK_FIELDS = re.compile(
    r"(?i)\b(?:routing|account|card)\s+number\b|\b(?:cvv|cvc|iban)\b|\bwire transfer\b"
)
_CHASE = re.compile(r"(?i)\bchase\b")
_CHASE_CTX = re.compile(r"(?i)\b(?:bank|balance|checking|savings|routing|debit|credit)\b")
_CHAT = re.compile(
    r"(?i)\b(?:slack|discord|whatsapp|imessage|telegram|snapchat|messenger)\b|"
    r"\bmicrosoft teams\b|\bgoogle chat\b|\bdirect messages?\b|\binstagram direct\b"
)
_SIGNAL_APP = re.compile(r"(?i)(?<!\bno )\bsignal\b(?!\s+(?:strength|lost))")
_NO_SIGNAL = re.compile(r"(?i)\bno signal\b")


@dataclass(frozen=True)
class PrivacyDecision:
    drop: bool
    reason: str = ""


def screen_is_sensitive(text: str, app_hint: str = "") -> PrivacyDecision:
    """Return a drop decision. ``reason`` is a stable code, never the screen text."""
    blob = f"{app_hint or ''}\n{text or ''}"
    folded = blob.lower()
    for name in _PASSWORD_MANAGERS:
        if name in folded:
            return PrivacyDecision(True, "password_manager")
    if _PASSWORD_FIELD.search(blob):
        return PrivacyDecision(True, "password_field")
    if _BANK_NAMED.search(blob) or _BANK_FIELDS.search(blob):
        return PrivacyDecision(True, "banking")
    if _CHASE.search(blob) and _CHASE_CTX.search(blob):
        return PrivacyDecision(True, "banking")
    if _OTP.search(blob):
        return PrivacyDecision(True, "otp")
    chat_blob = _NO_SIGNAL.sub(" ", blob)
    if _CHAT.search(chat_blob) or _SIGNAL_APP.search(chat_blob):
        return PrivacyDecision(True, "chat")
    return PrivacyDecision(False, "")


def redact_stored_text(text: str, *, limit: int = 400) -> str:
    """Last-pass redaction for excerpts that already passed the drop gate."""
    cleaned = text or ""
    cleaned = re.sub(r"\b\d{6,}\b", "[redacted]", cleaned)
    cleaned = re.sub(r"\b(?:\d[ -]?){13,19}\b", "[redacted]", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:limit]


def hotkey_detected(text: str, phrase: str) -> bool:
    needle = (phrase or "").strip().lower()
    if len(needle) < 4:
        return False
    return needle in (text or "").lower()


def _parse_hhmm(value: str) -> Optional[time]:
    raw = (value or "").strip()
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", raw)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return time(hour, minute)


def parse_quiet_hours(raw: str) -> list[tuple[time, time]]:
    """``23:00-07:00`` or several spans separated by commas. Empty means none."""
    spans: list[tuple[time, time]] = []
    for part in (raw or "").split(","):
        piece = part.strip()
        if not piece:
            continue
        if "-" not in piece:
            continue
        start_raw, end_raw = piece.split("-", 1)
        start = _parse_hhmm(start_raw)
        end = _parse_hhmm(end_raw)
        if start is None or end is None or start == end:
            continue
        spans.append((start, end))
    return spans


def in_quiet_hours(now: datetime, spans: list[tuple[time, time]]) -> bool:
    if not spans:
        return False
    moment = now.time()
    for start, end in spans:
        if start < end:
            if start <= moment < end:
                return True
        elif moment >= start or moment < end:
            return True
    return False


def pause_decision(
    state: dict | None,
    *,
    now: datetime,
    screen_text: str = "",
    hotkey_phrase: str = "",
    quiet_hours: str = "",
) -> tuple[bool, str]:
    """Manual and latched hotkey pauses win. Quiet hours pause only inside the span.

    Hotkey detection is reported so the caller can latch it. The screen text
    itself is not returned.
    """
    current = state or {}
    if current.get("paused") and str(current.get("reason") or "") in {"cli", "web", "hotkey"}:
        return True, str(current.get("reason") or "manual")
    phrase = hotkey_phrase or str(current.get("hotkey_phrase") or "")
    if hotkey_detected(screen_text, phrase):
        return True, "hotkey"
    schedule = current.get("schedule")
    if isinstance(schedule, str) and schedule.strip():
        spans = parse_quiet_hours(schedule)
    elif isinstance(schedule, list):
        spans = []
        for item in schedule:
            if isinstance(item, str):
                spans.extend(parse_quiet_hours(item))
            elif isinstance(item, dict):
                start = str(item.get("start") or "")
                end = str(item.get("end") or "")
                parsed = parse_quiet_hours(f"{start}-{end}")
                spans.extend(parsed)
    else:
        spans = parse_quiet_hours(quiet_hours)
    if in_quiet_hours(now, spans):
        return True, "schedule"
    return False, ""
