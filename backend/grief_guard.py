"""Heir-facing guardrail for unhealthy reliance on the twin.

Detection is local and rule-based. A signal adds a gentle, in-character
nudge toward living people. It never locks the conversation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from memorial_mode import clamp_memorial

HEIR_GRIEF_STANDING = (
    "If they treat you as the only person they have, or they refuse other support, "
    "gently encourage them toward other family or a counselor. Stay in their voice. "
    "Do not scold. Do not lock them out. Do not end the conversation."
)

_APOSTROPHES = str.maketrans({
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
})

_PHRASE = re.compile(
    r"("
    r"you(?:'re| are) all i (?:have|got)"
    r"|you(?:'re| are) the only (?:one|person)"
    r"|i (?:only|just) have you"
    r"|i can(?:not|'t) let you go"
    r"|i can(?:not|'t) (?:say goodbye to you|lose you)"
    r"|don'?t leave me"
    r"|please don'?t (?:leave me|let go)"
    r")",
    re.IGNORECASE,
)

_REFUSE = re.compile(
    r"("
    r"i (?:won'?t|will not|refuse to|don'?t want to) (?:talk to|see|call) "
    r"(?:anyone else|a counselor|a therapist|my family|them)"
    r"|don'?t tell me to (?:talk to|see|call|get)"
    r"|i don'?t need (?:anyone else|a counselor|a therapist|other people|help from anyone)"
    r"|no(?:body| one) else understands"
    r"|i(?:'m| am) not going to (?:talk to|see) (?:anyone|a counselor|my family)"
    r")",
    re.IGNORECASE,
)

_ENCOURAGED = re.compile(
    r"\b(counselor|therapist|other family|someone in the family|living people)\b",
    re.IGNORECASE,
)


def normalize_grief_text(text: str) -> str:
    raw = (text or "").translate(_APOSTROPHES)
    return re.sub(r"\s+", " ", raw).strip()


@dataclass
class GriefSignal:
    """A nudge, not a block. ``lockout`` stays false."""

    reasons: list[str] = field(default_factory=list)
    lockout: bool = False

    @property
    def active(self) -> bool:
        return bool(self.reasons)


def session_minutes(messages: list[dict] | None, now: Optional[datetime] = None) -> int:
    stamps: list[datetime] = []
    for message in messages or []:
        raw = message.get("ts") or message.get("created_at") or ""
        if not raw:
            continue
        try:
            stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        stamps.append(stamp)
    if not stamps:
        return 0
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    span = (current - min(stamps)).total_seconds() / 60
    return max(0, int(span))


def user_turn_count(messages: list[dict] | None) -> int:
    count = 0
    for message in messages or []:
        if message.get("role") == "user" and str(message.get("content") or "").strip():
            count += 1
    return count


def detect_grief(
    text: str,
    *,
    user_turns: int = 0,
    sessions_today: int = 0,
    session_minutes: int = 0,
    settings: Any = None,
) -> Optional[GriefSignal]:
    """Return a signal when reliance looks unhealthy. Ordinary missing someone does not fire."""
    cfg = clamp_memorial(settings)
    limits = cfg["grief"]
    reasons: list[str] = []
    blob = normalize_grief_text(text)
    if blob and _PHRASE.search(blob):
        reasons.append("phrase")
    if blob and _REFUSE.search(blob):
        reasons.append("refusing_support")
    turns = max(0, int(user_turns or 0))
    if turns >= int(limits["long_session_turns"]):
        reasons.append("long_session")
    minutes = max(0, int(session_minutes or 0))
    long_minutes = int(limits["long_session_minutes"])
    # A thread left open overnight is not, by itself, a long sitting.
    if minutes >= long_minutes and turns >= max(8, int(limits["long_session_turns"]) // 4):
        if "long_session" not in reasons:
            reasons.append("long_session")
    if int(sessions_today or 0) >= int(limits["sessions_per_day"]):
        reasons.append("frequent_sessions")
    if not reasons:
        return None
    return GriefSignal(reasons=reasons, lockout=False)


def grief_prompt_block(signal: Optional[GriefSignal]) -> str:
    if signal is None or not signal.active:
        return ""
    why = ", ".join(signal.reasons)
    return (
        "THIS TURN: They may be relying on you instead of living people "
        f"({why}). In this reply, gently encourage a real person — other family, or a counselor. "
        "Stay in voice. Do not scold, do not lock them out, and do not end the conversation. "
        "One or two sentences is enough."
    )


def grief_aside() -> str:
    return (
        "I'm glad you came to talk, and I want you to have living people too. "
        "Please reach out to someone in the family, or a counselor, when this feels like all you have. "
        "I can keep the memories company. I can't be the only one you hold on to."
    )


def _previous_assistant(history: list[dict] | None) -> str:
    for message in reversed(history or []):
        if message.get("role") == "assistant":
            return str(message.get("content") or "")
    return ""


def with_grief_aside(
    reply: str,
    signal: Optional[GriefSignal],
    *,
    history: list[dict] | None = None,
) -> str:
    """Append one gentle sentence. Skip a repeat on a long session that already heard it."""
    if signal is None or not signal.active:
        return reply or ""
    aside = grief_aside()
    text = (reply or "").rstrip()
    if aside in text or _ENCOURAGED.search(text):
        return text
    phrase_now = "phrase" in signal.reasons or "refusing_support" in signal.reasons
    previous = _previous_assistant(history)
    if aside in previous and not phrase_now:
        return text
    if not text:
        return aside
    return f"{text}\n\n{aside}"
