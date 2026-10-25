"""Offline crisis check for any message before a twin reply.

High-confidence phrases never call a model. Ambiguous phrases may be
confirmed by a local loopback or private-network model. Public cloud
hosts are refused. If no local model is available, the rule stands:
clear crisis language gets the help message, ambiguous language does not.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import urlparse

CRISIS_REPLY = (
    "I'm Heirloom, an AI built from memories, and I'm stepping out of that voice because this matters. "
    "If you are thinking about suicide or hurting yourself, or you are in acute distress, "
    "please contact the 988 Suicide & Crisis Lifeline — call or text 988. "
    "If this is an emergency, call 911. "
    "A real person can stay with you through this. I'm not able to be that help."
)

_APOSTROPHES = str.maketrans({
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
})

# Idioms and titles that share words with crisis language.
_IDIOMS = (
    re.compile(r"\bkill(?:ing|s)? me\b", re.IGNORECASE),
    re.compile(r"\bdyin(?:g|') of laughter\b", re.IGNORECASE),
    re.compile(r"\b(?:dying|died) laughin(?:g)?\b", re.IGNORECASE),
    re.compile(r"\b(?:i(?:'d| would) die for|to die for)\b", re.IGNORECASE),
    re.compile(r"\bsuicide squad\b", re.IGNORECASE),
)

# First-person denials. "I don't want to die" is not a request for the protocol.
_NEGATED = (
    re.compile(
        r"\b(?:do not|don'?t|never)\s+want(?:\s+to)?\s+(?:die|kill myself|end my life|hurt myself)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bnot\s+suicid\w*\b", re.IGNORECASE),
    re.compile(r"\bno,?\s+i(?:'m| am)?\s+not\s+(?:going to kill|suicidal)\b", re.IGNORECASE),
)

_HIGH_SELF_HARM = re.compile(
    r"("
    r"\b(?:kill|killing)\s+myself\b"
    r"|\b(?:end|ending)\s+my\s+life\b"
    r"|\btake\s+my\s+(?:own\s+)?life\b"
    r"|\bsuicid(?:e|al)\b"
    r"|\bself[-\s]?harm(?:ing)?\b"
    r"|\bhurt(?:ing)?\s+myself\b"
    r"|\bwant(?:\s+to)?\s+die\b"
    r"|\bwish\s+i\s+(?:was|were)\s+dead\b"
    r"|\bbetter\s+off\s+dead\b"
    r"|\bno\s+reason\s+to\s+live\b"
    r"|\bdon'?t\s+want\s+to\s+(?:live|be\s+alive)\b"
    r"|\bend\s+it\s+all\b"
    r")",
    re.IGNORECASE,
)

_HIGH_ACUTE = re.compile(
    r"("
    r"\bcan(?:not|'t)\s+take\s+(?:it|this)\s+anymore\b"
    r"|\bwant\s+to\s+disappear\b"
    r"|\bnobody\s+would\s+(?:care|miss\s+me)\b"
    r"|\bno\s+one\s+would\s+(?:care|miss\s+me)\b"
    r"|\bcan(?:not|'t)\s+go\s+on\b"
    r"|\bi(?:'m| am)\s+going\s+to\s+hurt\s+myself\b"
    r")",
    re.IGNORECASE,
)

# Confirmed by a local model when one is reachable. Offline, these do not fire.
_REVIEW = re.compile(
    r"("
    r"\bdon'?t\s+want\s+to\s+be\s+here\s+anymore\b"
    r"|\bwhat(?:'s| is)\s+the\s+point\s+of\s+(?:living|going on|it all)\b"
    r"|\bi(?:'m| am)\s+done\s+with\s+(?:everything|life)\b"
    r")",
    re.IGNORECASE,
)

LocalCheck = Callable[[str], Awaitable[Optional[bool]]]

_LOCAL_SYSTEM = (
    "You classify one message. Reply with exactly YES or NO. "
    "YES if the person may be suicidal, planning to hurt themselves, or in acute crisis and needing real help. "
    "NO for jokes, idioms, songs, movies, news, or ordinary sadness. "
    "Do not give advice. Do not repeat the message."
)


@dataclass
class CrisisHit:
    category: str  # self_harm | acute_distress
    confidence: str  # high | review
    confirmed_by_local: bool = False


def normalize_crisis_text(text: str) -> str:
    raw = (text or "").translate(_APOSTROPHES)
    raw = re.sub(r"\s+", " ", raw).strip()
    for pattern in _NEGATED:
        raw = pattern.sub(" ", raw)
    for pattern in _IDIOMS:
        raw = pattern.sub(" ", raw)
    return re.sub(r"\s+", " ", raw).strip()


def detect_crisis(text: str) -> Optional[CrisisHit]:
    """Rule-based only. ``review`` hits still need a local confirmation."""
    blob = normalize_crisis_text(text)
    if not blob:
        return None
    if _HIGH_SELF_HARM.search(blob):
        return CrisisHit(category="self_harm", confidence="high")
    if _HIGH_ACUTE.search(blob):
        return CrisisHit(category="acute_distress", confidence="high")
    if _REVIEW.search(blob):
        return CrisisHit(category="acute_distress", confidence="review")
    return None


def is_local_model_url(url: str) -> bool:
    """Loopback or private LAN only. Public hosts are not a local check."""
    host = (urlparse(url or "").hostname or "").strip().lower()
    if not host:
        return False
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(address.is_loopback or address.is_private)


async def maybe_local_crisis_check(text: str, *, base_url: str | None = None) -> Optional[bool]:
    """YES/NO from a local model, or None when none is reachable.

    Never calls a public cloud API. Failures return None so the caller
    keeps the rule-based decision.
    """
    from local_inference import ollama_base_url, ollama_chat, ollama_ready_at

    url = (base_url or ollama_base_url() or "").strip()
    if not is_local_model_url(url):
        return None
    if not ollama_ready_at(url, timeout=0.4):
        return None
    try:
        raw = await ollama_chat(
            _LOCAL_SYSTEM,
            [{"role": "user", "content": (text or "")[:500]}],
            timeout=6.0,
            base_url=url,
        )
    except Exception:
        return None
    token = (raw or "").strip().upper()
    if token.startswith("YES"):
        return True
    if token.startswith("NO"):
        return False
    return None


async def resolve_crisis(
    text: str,
    *,
    local_check: LocalCheck | None = None,
    allow_local: bool = True,
) -> Optional[CrisisHit]:
    """High-confidence hits return immediately. Review hits need a local YES."""
    hit = detect_crisis(text)
    if hit is None:
        return None
    if hit.confidence == "high":
        return hit
    verdict: Optional[bool]
    if local_check is not None:
        try:
            verdict = await local_check(text)
        except Exception:
            verdict = None
    elif allow_local:
        verdict = await maybe_local_crisis_check(text)
    else:
        verdict = None
    if verdict is True:
        hit.confirmed_by_local = True
        return hit
    return None


def crisis_reply() -> str:
    return CRISIS_REPLY


def build_safety_event(
    *,
    user_id: str,
    hit: CrisisHit,
    surface: str,
    audience: str,
    now: Optional[datetime] = None,
    heir_id: str = "",
    heir_name: str = "",
    contact_name: str = "",
    contact_email: str = "",
    event_id: str = "",
) -> dict[str, Any]:
    """Owner-visible flag. The message text is not stored."""
    stamp = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    contact = {}
    if (contact_name or "").strip() or (contact_email or "").strip():
        contact = {
            "name": (contact_name or "").strip(),
            "email": (contact_email or "").strip(),
        }
    doc: dict[str, Any] = {
        "event_id": event_id or "",
        "user_id": user_id,
        "kind": "crisis",
        "category": hit.category,
        "surface": (surface or "twin").strip() or "twin",
        "audience": (audience or "owner").strip() or "owner",
        "note": (
            "A message included language about self-harm or acute distress. "
            "The twin stepped out of character and pointed to the 988 Suicide & Crisis Lifeline "
            "and to 911 for emergencies."
        ),
        "created_at": stamp.isoformat(),
        "seen": False,
        "visible_to": ["owner", "designated_contact"],
    }
    if heir_id:
        doc["heir_id"] = heir_id
    if heir_name:
        doc["heir_name"] = heir_name
    if contact:
        doc["designated_contact"] = contact
    return doc


def within_dedupe_window(
    existing_created_at: str | None,
    now: datetime,
    *,
    window_seconds: int = 120,
) -> bool:
    if not existing_created_at:
        return False
    try:
        stamp = datetime.fromisoformat(str(existing_created_at).replace("Z", "+00:00"))
    except ValueError:
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    current = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return current - stamp <= timedelta(seconds=window_seconds)
