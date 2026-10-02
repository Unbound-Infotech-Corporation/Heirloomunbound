"""Owner phrases that open an email assignment.

Mail content is never an intent. Only the owner's own turn is read here.
"""
from __future__ import annotations

import re

TRIAGE_EMAIL = "triage_email"
SUMMARIZE_THREAD = "summarize_thread"
DRAFT_REPLY = "draft_reply"

EMAIL_PRESETS = frozenset({TRIAGE_EMAIL, SUMMARIZE_THREAD, DRAFT_REPLY})

NOT_CONNECTED_REPLY = (
    "No email is connected. Connect one in Settings > Connectors."
)

_TRIAGE = re.compile(
    r"\b(?:check|triage|read|look at|go through)\s+(?:my\s+)?(?:e-?mail|inbox)\b",
    re.IGNORECASE,
)
_SUMMARIZE = re.compile(
    r"\bsummarize\s+(?:this\s+|the\s+|my\s+)?(?:e-?mail\s+)?thread\b"
    r"|\bsummarize\s+(?:the\s+|my\s+)?(?:e-?mail|inbox)\b",
    re.IGNORECASE,
)
_DRAFT = re.compile(
    r"\bdraft\s+(?:a\s+)?repl(?:y|ies)\b",
    re.IGNORECASE,
)


def email_assignment_intent(text: str) -> str | None:
    """Triage, summarize, or draft. None keeps the turn in chat."""
    raw = text or ""
    if _DRAFT.search(raw):
        return DRAFT_REPLY
    if _SUMMARIZE.search(raw):
        return SUMMARIZE_THREAD
    if _TRIAGE.search(raw):
        return TRIAGE_EMAIL
    return None
