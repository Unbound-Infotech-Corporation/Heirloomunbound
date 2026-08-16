"""Unbound Keyboard — live spelling, grammar, and word-habit help.

Fast path is local (no LLM): common misspellings, its/it's-style mixups,
repeated words, and filler / overused-word flags. The slower polish path
asks the twin's usual chat model to rewrite in the owner's voice.

Privacy:
- Do not store the buffer. Callers must not persist raw keyboard text.
- Secret-looking text (cards, SSN, password fields) is refused.
- Habits come from the owner's archive + cached personality portrait —
  never from regenerating the portrait on each keystroke.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Optional

from services.voice_council import format_portrait_for_prompt
from services.writing_local import (
    ALTERNATIVES,
    FILLERS,
    HABIT_STOPWORDS,
    OVERUSE_ARCHIVE_MIN,
    WORD_RE,
    apply_suggestion,
    looks_secret,
    proofread_local,
)

MAX_POLISH_CHARS = 4000
HABIT_ENTRY_LIMIT = 80

# Re-export so existing tests and twin tools keep importing from writing_coach.
__all__ = (
    "apply_suggestion",
    "build_habit_profile",
    "load_habits",
    "looks_secret",
    "polish_for_user",
    "proofread_for_user",
    "proofread_local",
    "style_for_user",
)


def build_habit_profile(texts: list[str], portrait: Optional[dict] = None) -> dict[str, Any]:
    """Count characteristic words from archive writing + the cached portrait."""
    blob = "\n".join(t for t in texts if t)
    words = [w.group(0).lower() for w in WORD_RE.finditer(blob)]
    counts = Counter(w for w in words if len(w) > 3 and w not in HABIT_STOPWORDS and "'" not in w)
    overused = [
        {"word": word, "count": n, "suggestions": ALTERNATIVES.get(word, FILLERS.get(word, []))}
        for word, n in counts.most_common(12)
        if n >= OVERUSE_ARCHIVE_MIN
    ]
    voice = format_portrait_for_prompt(portrait) if portrait else ""
    phrases: list[str] = []
    tone = portrait.get("voice_tone") if isinstance(portrait, dict) else None
    if isinstance(tone, dict):
        phrases = [str(p).strip() for p in (tone.get("signature_phrases") or []) if str(p).strip()][:8]
    return {
        "overused": overused,
        "voice_note": voice,
        "signature_phrases": phrases,
        "sample_words": len(words),
    }


async def load_habits(user_id: str) -> dict[str, Any]:
    from deps import db

    cursor = db.entries.find({"user_id": user_id}, {"content": 1, "title": 1, "_id": 0}).sort(
        "created_at", -1
    )
    rows = await cursor.to_list(length=HABIT_ENTRY_LIMIT)
    texts = [f"{r.get('title') or ''} {r.get('content') or ''}" for r in rows]
    portrait = await db.personality_profiles.find_one({"user_id": user_id}, {"_id": 0})
    return build_habit_profile(texts, portrait)


async def proofread_for_user(
    user_id: str,
    text: str,
    habits: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    profile = habits if isinstance(habits, dict) and ("overused" in habits or "voice_note" in habits) else await load_habits(user_id)
    result = proofread_local(text, profile)
    result["habits"] = {
        "overused": profile.get("overused") or [],
        "signature_phrases": profile.get("signature_phrases") or [],
    }
    return result


async def polish_for_user(user_id: str, text: str, instruction: str = "") -> dict[str, Any]:
    """Rewrite in the owner's voice. Falls back to local proofread if models are down."""
    original = (text or "")[:MAX_POLISH_CHARS]
    if looks_secret(original):
        return {
            "secret": True,
            "original": original,
            "polished": original,
            "note": "That looks private. I will not rewrite it.",
        }
    local = await proofread_for_user(user_id, original)
    if not original.strip():
        return {"secret": False, "original": original, "polished": original, "note": "Nothing to polish yet."}

    from services.llm_router import chat_once

    habits = await load_habits(user_id)
    voice = str(habits.get("voice_note") or "").strip()
    over = ", ".join(str(r.get("word")) for r in (habits.get("overused") or [])[:8] if r.get("word"))
    extra = (instruction or "").strip()[:400]
    system = (
        "You help this person write in their own voice. Fix spelling and grammar. "
        "If they lean on the same word, swap a few for closer cousins — do not make them sound like a magazine. "
        "Keep their meaning. Do not add facts. Do not mention that you are an AI. "
        "Return ONLY the rewritten text."
    )
    if voice:
        system += f"\nTheir voice:\n{voice}"
    if over:
        system += f"\nWords they overuse: {over}"
    if extra:
        system += f"\nExtra ask: {extra}"
    try:
        out = await chat_once(
            user_id,
            "chat",
            [
                {"role": "system", "content": system},
                {"role": "user", "content": original},
            ],
        )
    except Exception:  # noqa: BLE001
        out = {"ok": False}
    polished = ""
    if isinstance(out, dict) and out.get("ok"):
        polished = str(out.get("text") or "").strip()
    if not polished:
        polished = str(local.get("corrected") or original)
        note = "I cleaned spelling here. Connect a writing model in Settings if you want a fuller rewrite in your voice."
    else:
        note = "Rewritten so it still sounds like you — not like a generic editor."
    return {
        "secret": False,
        "original": original,
        "polished": polished,
        "note": note,
        "issues": local.get("issues") or [],
    }


async def style_for_user(user_id: str) -> dict[str, Any]:
    habits = await load_habits(user_id)
    over = habits.get("overused") or []
    if over:
        words = ", ".join(str(r.get("word")) for r in over[:6] if r.get("word"))
        summary = f"In your archive you reach for {words} more than most words."
    else:
        summary = "I have not seen a strong word habit yet. Keep writing — I'll notice gently."
    return {
        "summary": summary,
        "overused": over,
        "signature_phrases": habits.get("signature_phrases") or [],
        "voice_note": habits.get("voice_note") or "",
        "sample_words": int(habits.get("sample_words") or 0),
        "privacy": (
            "Unbound Keyboard only sees the field you are typing in — never password boxes. "
            "We do not keep other people's documents or the raw keyboard buffer."
        ),
    }
