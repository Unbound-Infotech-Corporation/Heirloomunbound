"""When the twin should look at the owner's screen and how to coach from it.

The screenshot is captured on the home PC, analysed, then deleted. We never
keep the picture. This is for sitting-next-to-you help: games, grammar,
movies, errors — not surveillance.
"""
from __future__ import annotations

import re

# Exact phrase the "Look at my screen" buttons send.
LOOK_AT_SCREEN_PHRASE = "Look at my screen and help me with whatever is on it."

VISION_SYSTEM = (
    "You are sitting next to the owner, looking at their computer screen so you can help. "
    "Identify what is on screen (a game, a document, a movie or show, a browser, an error, or something else). "
    "Then answer their request as a practical coach:\n"
    "- Games: name the game if you can, say what is happening, and give one or two clear next-step tips. "
    "Do not spoil later story unless they asked.\n"
    "- Writing and grammar: transcribe the readable text, then list specific spelling, grammar, and clarity edits.\n"
    "- Movies and TV: identify the title and scene if you can. Answer their question. "
    "Do not spoil later plot unless they asked.\n"
    "- Anything else: describe what you see and give useful advice.\n"
    "Be concrete. If the picture is too blurry to read, say so. "
    "Do not mention that you are an AI looking at an image."
)

_LOOK_RE = re.compile(
    r"("
    r"look at (my |the )?screen"
    r"|see (my |the )?screen"
    r"|what(?:'s| is) on (my |the )?screen"
    r"|watch (this|the (screen|game|movie|show)) with me"
    r"|help me (with|on) (this |the )?(game|level|boss|puzzle|raid|mission)"
    r"|check (my |this )?(grammar|spelling|writing|essay|email|draft)"
    r"|proofread"
    r"|what (movie|show|film|series) is this"
    r"|who(?:'s| is) (this|that) (actor|character)"
    r"|read (this|the) (error|message|page|document)"
    r"|look at (this|that)\b"
    r")",
    re.IGNORECASE,
)

_GAME_HINTS = ("game", "level", "boss", "raid", "puzzle", "mission", "quest", "hp")
_WRITE_HINTS = ("grammar", "spelling", "proofread", "essay", "writing", "draft")
_MEDIA_HINTS = ("movie", "film", "show", "series", "actor", "scene", "netflix", "watching")


def should_look_at_screen(message: str) -> bool:
    """True when the owner is asking about what is in front of them.

    Long pasted text is treated as the content itself — we do not screenshot.
    """
    text = (message or "").strip()
    if not text:
        return False
    if len(text) > 500:
        return False
    return bool(_LOOK_RE.search(text))


def coach_question_for(message: str) -> str:
    """Vision prompt tailored to games, writing, movies, or a general look."""
    text = (message or "").strip() or LOOK_AT_SCREEN_PHRASE
    lower = text.lower()
    if any(word in lower for word in _WRITE_HINTS):
        return (
            "This is a writing and grammar request. Transcribe the readable text on screen "
            "as faithfully as you can, then list specific grammar, spelling, and clarity edits."
        )
    if any(word in lower for word in _GAME_HINTS):
        return (
            "This is a video-game coaching request. Identify the game and what is happening. "
            "Give one or two clear next-step tips. Do not spoil later story unless they asked."
        )
    if any(word in lower for word in _MEDIA_HINTS):
        return (
            "This is a movie or TV request. Identify the title and scene if you can. "
            "Answer their question. Do not spoil later plot unless they asked."
        )
    return (
        f"The owner said: {text}\n"
        "Identify what is on the screen, then help them with it — a game, writing, a movie, "
        "an error, or whatever you see."
    )


def format_screen_context(user_message: str, look: dict) -> str:
    """Fold a screen look into the LLM user turn so the twin can coach from it."""
    summary = (look or {}).get("summary") or "Couldn't see the screen."
    ok = bool(((look or {}).get("ui") or {}).get("ok"))
    if not ok:
        return (
            f"{user_message}\n\n"
            f"(You tried to look at their computer screen but couldn't: {summary} "
            "If the Heirloom app isn't open on the home computer, tell them to open it. "
            "Never ask them to type a password.)"
        )
    return (
        f"{user_message}\n\n"
        f"(You are looking at their screen right now. Do not call see_screen again. {summary})"
    )
