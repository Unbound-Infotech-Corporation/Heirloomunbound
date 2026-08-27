"""Inbound Twin call turns — greet once, stay in character, hang up cleanly.

No Retell or Mongo here. The WebSocket loop in routers/phone.py applies these
plans: greeting, silence, take-a-message, handoff, goodbye, poor audio, anger.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from phone_policy import (
    DECLINE_SPOKEN,
    HANDOFF_CLOSED,
    HANDOFF_SPOKEN,
    MESSAGE_PROMPT,
    MESSAGE_THANKS,
    PolicyDecision,
    disclosure_line,
    handoff_allowed,
    is_owner_caller,
    match_allowlist,
    normalize_e164,
    wants_handoff,
)

SILENCE_STILL = "I'm still here."
SILENCE_REPEAT = "I didn't catch that. Say it once more if you want."
SILENCE_BYE = "I'll let you go. Call back whenever you like. Goodbye."
UNCLEAR_SPOKEN = "I didn't catch that. Say it once more?"
UNCLEAR_OFFER = "This line isn't coming through. I can keep a message, or you can try again."
ANGRY_CALM = "I hear you. I'm not going to argue. I can take a message, or we can stop here."
ANGRY_AGAIN = "I can keep a message, or we can stop here."
GOODBYE_FAMILY = "Alright. I'm glad you called. Goodbye."
GOODBYE_PLAIN = "Goodbye."
MESSAGE_KEEP = "Go ahead. I'll keep it."
MESSAGE_GOT = "I've got that."
LISTENING = "I'm listening."
MESSAGE_WAIT = "Go ahead whenever you're ready."

MAX_SILENCE_REMINDERS = 3
MAX_UNCLEAR = 2

_GOODBYE_RE = re.compile(
    r"\b(good\s*bye|bye[\s-]*bye|\bbye\b|that's all|that is all|"
    r"i('m| am) done|hang up|end the call|talk later|"
    r"gott?a go|got to go|i('ll| will) let you go|see you later)\b",
    re.IGNORECASE,
)
_MESSAGE_RE = re.compile(
    r"\b(leave (a |them a |him a |her a )?message|take a message|"
    r"tell them i called|give them a message|"
    r"voice\s*mail|leave (a )?voicemail)\b",
    re.IGNORECASE,
)
_FILLER_RE = re.compile(
    r"^(uh+|um+|er+|ah+|hmm+|huh+|what\??|sorry\??|pardon\??|"
    r"\[inaudible\]|\.{2,}|xxx+)$",
    re.IGNORECASE,
)
_ANGRY_RE = re.compile(
    r"\b(shut up|go to hell|screw you|fuck you|idiot|stupid|"
    r"this is (ridiculous|bullshit|bull shit)|speak to (a )?manager|"
    r"hate (this|you)|damn it|dammit)\b",
    re.IGNORECASE,
)
_QUESTION_RE = re.compile(
    r"^(who|what|where|when|why|how|did|do|does|is|are|can|could|would)\b",
    re.IGNORECASE,
)


@dataclass
class InboundSession:
    greeted: bool = False
    reminders: int = 0
    phase: str = "talking"  # talking | taking_message | ending
    last_user: str = ""
    unclear_streak: int = 0
    angry_offered: bool = False
    policy_message: bool = False


@dataclass(frozen=True)
class TurnPlan:
    speak: str = ""
    end_call: bool = False
    transfer_number: str = ""
    need_twin: bool = False
    save_message: str = ""


def caller_name(decision: PolicyDecision) -> str:
    if decision.caller_is_owner:
        return "you"
    entry = decision.allowlist_entry or {}
    return str(entry.get("name") or "").strip()


def greeting(user_name: str, decision: PolicyDecision) -> str:
    name = (user_name or "").strip() or "me"
    who = caller_name(decision)
    if decision.caller_is_owner:
        line = "Hey. It's me."
    elif who and who.lower() != "you":
        line = f"Hey {who}. It's {name}."
    else:
        line = f"Hey, it's {name}."
    if decision.disclose:
        line = f"{line} {disclosure_line(name)}"
    return line


def goodbye_line(decision: PolicyDecision) -> str:
    if decision.known_family:
        return GOODBYE_FAMILY
    return GOODBYE_PLAIN


def wants_goodbye(utterance: str) -> bool:
    return bool(_GOODBYE_RE.search(utterance or ""))


def wants_message(utterance: str) -> bool:
    return bool(_MESSAGE_RE.search(utterance or ""))


def sounds_unclear(utterance: str) -> bool:
    text = (utterance or "").strip()
    if not text:
        return True
    if len(text) <= 1:
        return True
    if _FILLER_RE.fullmatch(text):
        return True
    letters = sum(ch.isalpha() for ch in text)
    return len(text) >= 6 and letters / max(len(text), 1) < 0.35


def sounds_angry(utterance: str) -> bool:
    return bool(_ANGRY_RE.search(utterance or ""))


def looks_like_question(utterance: str) -> bool:
    text = (utterance or "").strip()
    if "?" in text:
        return True
    return bool(_QUESTION_RE.match(text))


def phone_system_addendum(caller: str = "") -> str:
    who = (caller or "").strip()
    address = f" You are speaking with {who}." if who else ""
    return (
        "\n\nPHONE: Live call. First person as them. 2-4 short spoken sentences. "
        "No lists, markdown, or citation numbers. Never say you are an AI, a receptionist, or a helper."
        f"{address} Stay in character. If you don't remember, say so. Never invent. "
        "Do not file this call as a memory. If they ask to leave a message, keep it. "
        "If they want the real person, offer to put them through. "
        "If they say goodbye, say goodbye briefly."
    )


def caller_display(
    from_e164: str,
    settings: dict[str, Any],
    *,
    contact_name: str = "",
) -> str:
    named = (contact_name or "").strip()
    if named:
        return named
    hit = match_allowlist(from_e164, settings)
    if hit and str(hit.get("name") or "").strip():
        return str(hit["name"]).strip()
    if is_owner_caller(from_e164, settings):
        return "You"
    return normalize_e164(from_e164) or "Someone"


def notify_copy(
    *,
    direction: str,
    who: str,
    message_left: str = "",
    status: str = "",
) -> tuple[str, str]:
    title = "Phone"
    name = (who or "").strip() or "Someone"
    if (message_left or "").strip():
        return title, f"{name} left a message. It's in Phone."
    if (direction or "").strip().lower() == "outbound":
        return title, f"Call with {name} ended. Transcript is in Phone."
    if (status or "").strip().lower() in {"decline", "declined"}:
        return title, f"{name} called. This line didn't take it."
    return title, f"{name} called. Transcript is in Phone."


def apply_policy_phase(session: InboundSession, decision: PolicyDecision) -> None:
    """Set the opening phase once, without wiping a live conversation."""
    if session.greeted or session.phase == "ending":
        return
    if decision.action == "message":
        session.phase = "taking_message"
        session.policy_message = True
    elif decision.action == "decline":
        session.phase = "ending"
    else:
        session.phase = "talking"


def plan_turn(
    *,
    interaction: str,
    user_text: str,
    session: InboundSession,
    decision: PolicyDecision,
    settings: Optional[dict[str, Any]] = None,
    user_name: str = "",
) -> TurnPlan:
    """Decide the next spoken line. Mutates session. Twin replies are requested via need_twin."""
    text = (user_text or "").strip()
    reminder = (interaction or "") == "reminder_required"
    settings = settings or {}

    if decision.action == "decline" or session.phase == "ending":
        session.phase = "ending"
        return TurnPlan(speak=decision.spoken or DECLINE_SPOKEN, end_call=True)

    if session.phase == "taking_message":
        return _plan_message(
            text=text,
            reminder=reminder,
            session=session,
            decision=decision,
            settings=settings,
        )

    if reminder:
        if not session.greeted:
            session.greeted = True
            session.reminders = 0
            return TurnPlan(speak=greeting(user_name, decision))
        session.reminders += 1
        if session.reminders >= MAX_SILENCE_REMINDERS:
            session.phase = "ending"
            return TurnPlan(speak=SILENCE_BYE, end_call=True)
        if session.reminders == 1:
            return TurnPlan(speak=SILENCE_STILL)
        return TurnPlan(speak=SILENCE_REPEAT)

    if not text:
        if not session.greeted:
            session.greeted = True
            return TurnPlan(speak=greeting(user_name, decision))
        session.unclear_streak += 1
        if session.unclear_streak >= MAX_UNCLEAR:
            return TurnPlan(speak=UNCLEAR_OFFER)
        return TurnPlan(speak=UNCLEAR_SPOKEN)

    if text == session.last_user:
        return TurnPlan(speak=LISTENING)

    session.last_user = text
    session.reminders = 0

    if wants_goodbye(text):
        session.phase = "ending"
        return TurnPlan(speak=goodbye_line(decision), end_call=True)

    if wants_message(text):
        session.phase = "taking_message"
        session.policy_message = False
        return TurnPlan(speak=MESSAGE_KEEP)

    if wants_handoff(text):
        if handoff_allowed(settings):
            dest = normalize_e164(settings.get("handoff_e164"))
            return TurnPlan(speak=HANDOFF_SPOKEN, transfer_number=dest)
        return TurnPlan(speak=HANDOFF_CLOSED)

    if sounds_unclear(text):
        session.unclear_streak += 1
        if session.unclear_streak >= MAX_UNCLEAR:
            return TurnPlan(speak=UNCLEAR_OFFER)
        return TurnPlan(speak=UNCLEAR_SPOKEN)

    session.unclear_streak = 0

    if sounds_angry(text) and not looks_like_question(text):
        if not session.angry_offered:
            session.angry_offered = True
            return TurnPlan(speak=ANGRY_CALM)
        return TurnPlan(speak=ANGRY_AGAIN)

    session.greeted = True
    return TurnPlan(need_twin=True)


def _plan_message(
    *,
    text: str,
    reminder: bool,
    session: InboundSession,
    decision: PolicyDecision,
    settings: dict[str, Any],
) -> TurnPlan:
    prompt = decision.spoken if decision.action == "message" else MESSAGE_KEEP
    if not session.greeted and not text:
        session.greeted = True
        return TurnPlan(speak=prompt or MESSAGE_PROMPT)

    if reminder:
        session.reminders += 1
        if session.reminders >= MAX_SILENCE_REMINDERS:
            session.phase = "ending"
            if session.policy_message:
                return TurnPlan(speak=MESSAGE_THANKS, end_call=True)
            return TurnPlan(speak=SILENCE_BYE, end_call=True)
        return TurnPlan(speak=MESSAGE_WAIT)

    if not text:
        return TurnPlan(speak=MESSAGE_WAIT)

    if wants_goodbye(text) and len(text.split()) <= 4:
        session.phase = "ending"
        return TurnPlan(speak=goodbye_line(decision), end_call=True)

    if wants_handoff(text):
        session.phase = "talking"
        if handoff_allowed(settings):
            dest = normalize_e164(settings.get("handoff_e164"))
            return TurnPlan(speak=HANDOFF_SPOKEN, transfer_number=dest)
        return TurnPlan(speak=HANDOFF_CLOSED)

    session.last_user = text
    session.reminders = 0
    if session.policy_message:
        session.phase = "ending"
        return TurnPlan(speak=MESSAGE_THANKS, end_call=True, save_message=text[:2000])
    session.phase = "talking"
    return TurnPlan(speak=MESSAGE_GOT, save_message=text[:2000])
