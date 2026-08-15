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

import re
from collections import Counter
from typing import Any, Optional

from services.voice_council import format_portrait_for_prompt

MAX_PROOFREAD_CHARS = 8000
MAX_POLISH_CHARS = 4000
MAX_ISSUES = 20
HABIT_ENTRY_LIMIT = 80
OVERUSE_ARCHIVE_MIN = 8
OVERUSE_CURRENT_MIN = 2
FILLER_CURRENT_MIN = 3

# Whole-word spelling (lowercase keys). Suggestions preserve the typed case.
SPELLING: dict[str, str] = {
    "teh": "the",
    "recieve": "receive",
    "recieved": "received",
    "seperate": "separate",
    "seperated": "separated",
    "definately": "definitely",
    "occured": "occurred",
    "occurence": "occurrence",
    "untill": "until",
    "wich": "which",
    "becuase": "because",
    "becasue": "because",
    "adress": "address",
    "tommorrow": "tomorrow",
    "tmorow": "tomorrow",
    "tomorow": "tomorrow",
    "enviroment": "environment",
    "goverment": "government",
    "goverment's": "government's",
    "accomodate": "accommodate",
    "embarass": "embarrass",
    "existince": "existence",
    "independant": "independent",
    "priviledge": "privilege",
    "neccessary": "necessary",
    "occassion": "occasion",
    "recomend": "recommend",
    "succesful": "successful",
    "untited": "united",
    "usefull": "useful",
    "writting": "writing",
    "begining": "beginning",
    "buisness": "business",
    "calender": "calendar",
    "collegue": "colleague",
    "comming": "coming",
    "completly": "completely",
    "concious": "conscious",
    "curiousity": "curiosity",
    "dissapoint": "disappoint",
    "existance": "existence",
    "familar": "familiar",
    "finaly": "finally",
    "foriegn": "foreign",
    "freind": "friend",
    "goverment": "government",
    "happend": "happened",
    "harrass": "harass",
    "immediatly": "immediately",
    "knowlege": "knowledge",
    "liason": "liaison",
    "maintainance": "maintenance",
    "mispell": "misspell",
    "noticable": "noticeable",
    "occassionally": "occasionally",
    "persue": "pursue",
    "posession": "possession",
    "prefered": "preferred",
    "publically": "publicly",
    "realy": "really",
    "refered": "referred",
    "relavant": "relevant",
    "remeber": "remember",
    "resistence": "resistance",
    "saftey": "safety",
    "seige": "siege",
    "sentance": "sentence",
    "sieze": "seize",
    "similiar": "similar",
    "speach": "speech",
    "sucess": "success",
    "suprise": "surprise",
    "thier": "their",
    "truely": "truly",
    "unfortunatly": "unfortunately",
    "untill": "until",
    "usally": "usually",
    "wether": "whether",
    "whereever": "wherever",
    "wich": "which",
    "alot": "a lot",
    "alright": "all right",
    "couldnt": "couldn't",
    "didnt": "didn't",
    "doesnt": "doesn't",
    "dont": "don't",
    "isnt": "isn't",
    "wasnt": "wasn't",
    "werent": "weren't",
    "wont": "won't",
    "wouldnt": "wouldn't",
    "cant": "can't",
    "havent": "haven't",
    "hasnt": "hasn't",
    "hadnt": "hadn't",
    "youre": "you're",
    "theyre": "they're",
    "thats": "that's",
    "whats": "what's",
    "wheres": "where's",
    "ive": "I've",
    "im": "I'm",
    "weve": "we've",
    "theyve": "they've",
    "shouldve": "should've",
    "wouldve": "would've",
    "couldve": "could've",
}

# Phrase-level grammar (applied before word scan). Replacement is the full match fix.
PHRASE_FIXES: tuple[tuple[str, str, str], ...] = (
    (r"\bshould of\b", "should have", "Use 'should have', not 'should of'."),
    (r"\bcould of\b", "could have", "Use 'could have', not 'could of'."),
    (r"\bwould of\b", "would have", "Use 'would have', not 'would of'."),
    (r"\bmight of\b", "might have", "Use 'might have', not 'might of'."),
    (r"\bmust of\b", "must have", "Use 'must have', not 'must of'."),
    (r"\bits a\b", "it's a", "'It's' means it is."),
    (r"\bits an\b", "it's an", "'It's' means it is."),
    (r"\bits the\b", "it's the", "'It's' means it is."),
    (r"\bit's own\b", "its own", "'Its' is the possessive — no apostrophe."),
    (r"\bit's way\b", "its way", "'Its' is the possessive — no apostrophe."),
    (r"\byour welcome\b", "you're welcome", "'You're' means you are."),
    (r"\byour right\b", "you're right", "'You're' means you are — unless you mean belonging to you."),
    (r"\btheir is\b", "there is", "'There is' points to a place or fact."),
    (r"\btheir are\b", "there are", "'There are' points to a place or fact."),
    (r"\bthere going\b", "they're going", "'They're' means they are."),
    (r"\bthey're house\b", "their house", "'Their' is the possessive."),
    (r"\bthey're car\b", "their car", "'Their' is the possessive."),
    (r"\bto to\b", "to", "That word was typed twice."),
    (r"\bthe the\b", "the", "That word was typed twice."),
    (r"\ba a\b", "a", "That word was typed twice."),
    (r"\band and\b", "and", "That word was typed twice."),
)

FILLERS: dict[str, list[str]] = {
    "just": ["simply", "only", ""],
    "really": ["truly", "genuinely", ""],
    "very": ["especially", "rather", ""],
    "actually": ["in fact", ""],
    "literally": [""],
    "basically": ["simply", ""],
    "honestly": ["frankly", ""],
    "maybe": ["perhaps", "possibly"],
    "stuff": ["the details", "what happened"],
    "things": ["the details", "what happened"],
    "amazing": ["wonderful", "striking", "kind"],
    "great": ["good", "fine", "glad"],
    "nice": ["kind", "warm", "pleasant"],
    "important": ["needed", "pressing"],
    "utilize": ["use"],
    "leverage": ["use"],
}

STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "from", "have", "has", "had",
    "were", "was", "are", "been", "being", "they", "them", "their", "there",
    "then", "than", "what", "when", "where", "which", "while", "will", "would",
    "could", "should", "about", "into", "over", "after", "before", "because",
    "your", "you", "she", "him", "her", "his", "our", "ours", "who", "whom",
    "not", "but", "all", "any", "can", "out", "how", "now", "new", "one",
    "two", "also", "just", "like", "some", "more", "most", "other", "only",
    "own", "same", "such", "too", "very", "here", "it's", "its", "i'm",
}

ALTERNATIVES: dict[str, list[str]] = {
    "good": ["fine", "solid", "kind"],
    "bad": ["rough", "unkind", "poor"],
    "said": ["told", "asked", "wrote"],
    "went": ["walked", "headed", "left"],
    "got": ["received", "picked up", "found"],
    "make": ["build", "write", "put together"],
    "help": ["lend a hand", "walk through", "look after"],
    "need": ["want", "ask for", "could use"],
    "think": ["believe", "figure", "wonder"],
    "know": ["remember", "understand", "see"],
    "love": ["care for", "am fond of", "hold dear"],
    "hate": ["cannot stand", "dread"],
    "always": ["often", "most days"],
    "never": ["rarely", "hardly"],
    "people": ["folks", "family", "the ones I love"],
}

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z']*")
_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_PASSWORD_RE = re.compile(
    r"(?i)\b(?:password|passwd|passcode|pin|ssn|social security|cvv|cvc|routing number)\b\s*[:=]"
)
_SECRETISH_RE = re.compile(
    r"(?i)\b(?:sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b"
)


def looks_secret(text: str) -> bool:
    """True when the buffer looks like a secret, not ordinary writing."""
    blob = text or ""
    if not blob.strip():
        return False
    if _PASSWORD_RE.search(blob):
        return True
    if _SSN_RE.search(blob):
        return True
    if _SECRETISH_RE.search(blob):
        return True
    digits = re.sub(r"[^\d]", "", blob)
    if len(digits) >= 13 and _CARD_RE.search(blob):
        return True
    return False


def _match_case(src: str, repl: str) -> str:
    if not src or not repl:
        return repl
    if src.isupper():
        return repl.upper()
    if src[0].isupper():
        return repl[0].upper() + repl[1:]
    return repl


def _issue(
    start: int,
    end: int,
    kind: str,
    text: str,
    suggestions: list[str],
    note: str,
    auto: bool = False,
) -> dict[str, Any]:
    clean = [s for s in suggestions if s is not None]
    return {
        "start": start,
        "end": end,
        "kind": kind,
        "text": text,
        "suggestions": clean[:4],
        "note": note,
        "auto": auto,
    }


def _apply_autos(text: str, issues: list[dict[str, Any]]) -> str:
    """Apply auto spelling/grammar suggestions from the end so offsets stay valid."""
    out = text
    autos = [i for i in issues if i.get("auto") and i.get("suggestions")]
    autos.sort(key=lambda i: int(i["start"]), reverse=True)
    used: set[tuple[int, int]] = set()
    for item in autos:
        start, end = int(item["start"]), int(item["end"])
        if any(not (end <= a or start >= b) for a, b in used):
            continue
        repl = str(item["suggestions"][0])
        if start < 0 or end > len(out) or start >= end:
            continue
        out = out[:start] + repl + out[end:]
        used.add((start, end))
    return out


def build_habit_profile(texts: list[str], portrait: Optional[dict] = None) -> dict[str, Any]:
    """Count characteristic words from archive writing + the cached portrait."""
    blob = "\n".join(t for t in texts if t)
    words = [w.group(0).lower() for w in _WORD_RE.finditer(blob)]
    counts = Counter(w for w in words if len(w) > 3 and w not in STOPWORDS and "'" not in w)
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


def proofread_local(text: str, habits: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Instant spelling + grammar + habit flags. No network, no storage."""
    original = text or ""
    if looks_secret(original):
        return {
            "secret": True,
            "original": original,
            "corrected": original,
            "issues": [],
            "style_note": "That looks private — a password, a card, or a number that should stay with you. I will not read it.",
        }
    clipped = original[:MAX_PROOFREAD_CHARS]
    issues: list[dict[str, Any]] = []

    for pattern, repl, note in PHRASE_FIXES:
        for m in re.finditer(pattern, clipped, flags=re.IGNORECASE):
            issues.append(
                _issue(
                    m.start(),
                    m.end(),
                    "grammar",
                    m.group(0),
                    [_match_case(m.group(0), repl)],
                    note,
                    auto=True,
                )
            )
            if len(issues) >= MAX_ISSUES:
                break
        if len(issues) >= MAX_ISSUES:
            break

    covered = {(i["start"], i["end"]) for i in issues}

    def _overlaps(a: int, b: int) -> bool:
        return any(not (b <= s or a >= e) for s, e in covered)

    filler_hits: Counter[str] = Counter()
    for m in _WORD_RE.finditer(clipped):
        raw = m.group(0)
        key = raw.lower()
        if key in FILLERS:
            filler_hits[key] += 1

    for m in _WORD_RE.finditer(clipped):
        if len(issues) >= MAX_ISSUES:
            break
        start, end, raw = m.start(), m.end(), m.group(0)
        if _overlaps(start, end):
            continue
        key = raw.lower()
        if key in SPELLING and SPELLING[key].lower() != key:
            fix = _match_case(raw, SPELLING[key])
            if fix != raw:
                issues.append(
                    _issue(start, end, "spelling", raw, [fix], f"Did you mean '{fix}'?", auto=True)
                )
                covered.add((start, end))

    for m in re.finditer(r"\b([A-Za-z']+)\s+\1\b", clipped, flags=re.IGNORECASE):
        if len(issues) >= MAX_ISSUES:
            break
        if _overlaps(m.start(), m.end()):
            continue
        word = m.group(1)
        issues.append(
            _issue(m.start(), m.end(), "grammar", m.group(0), [word], "That word was typed twice.", auto=True)
        )
        covered.add((m.start(), m.end()))

    # Lone "i" as a pronoun.
    for m in re.finditer(r"(?:^|[.!?]\s+)(i)(?=\s)", clipped):
        if len(issues) >= MAX_ISSUES:
            break
        start = m.start(1)
        end = m.end(1)
        if _overlaps(start, end):
            continue
        issues.append(_issue(start, end, "grammar", "i", ["I"], "Capital I when you mean yourself.", auto=True))
        covered.add((start, end))

    for word, n in filler_hits.items():
        if n < FILLER_CURRENT_MIN or len(issues) >= MAX_ISSUES:
            continue
        alts = [a for a in FILLERS.get(word, []) if a]
        note = f"You used '{word}' {n} times here. A different word (or none) often sounds more like you."
        # Flag the last occurrence so the strip has somewhere to land.
        last = None
        for m in _WORD_RE.finditer(clipped):
            if m.group(0).lower() == word:
                last = m
        if last is None:
            continue
        issues.append(
            _issue(last.start(), last.end(), "style", last.group(0), alts, note, auto=False)
        )

    habit_words = []
    if isinstance(habits, dict):
        habit_words = habits.get("overused") or []
    for row in habit_words:
        if len(issues) >= MAX_ISSUES:
            break
        word = str(row.get("word") or "").lower()
        if not word or word in FILLERS:
            continue
        hits = [m for m in _WORD_RE.finditer(clipped) if m.group(0).lower() == word]
        if len(hits) < OVERUSE_CURRENT_MIN:
            continue
        last = hits[-1]
        alts = [str(s) for s in (row.get("suggestions") or ALTERNATIVES.get(word, [])) if s]
        issues.append(
            _issue(
                last.start(),
                last.end(),
                "habit",
                last.group(0),
                alts,
                (
                    f"You reach for '{word}' a lot in your archive"
                    + (f" ({row.get('count')} times in recent writing)" if row.get("count") else "")
                    + ". Want a different word that still sounds like you?"
                ),
                auto=False,
            )
        )

    issues.sort(key=lambda i: int(i["start"]))
    issues = issues[:MAX_ISSUES]
    corrected = _apply_autos(clipped, issues)
    style_bits: list[str] = []
    habit_flags = [i for i in issues if i["kind"] in ("style", "habit")]
    spelling_flags = [i for i in issues if i["kind"] in ("spelling", "grammar")]
    if spelling_flags:
        style_bits.append("I marked spelling and little grammar slips.")
    if habit_flags:
        style_bits.append("A few words you lean on are highlighted — tap one for a swap that still sounds like you.")
    if not style_bits:
        style_bits.append("Looks clean. Keep going.")
    voice = ""
    if isinstance(habits, dict):
        voice = str(habits.get("voice_note") or "").strip()
    if voice:
        style_bits.append("I'll keep your usual voice — not a generic editor's.")
    return {
        "secret": False,
        "original": original,
        "corrected": corrected,
        "issues": [{k: v for k, v in i.items() if k != "auto"} | {"auto": bool(i.get("auto"))} for i in issues],
        "style_note": " ".join(style_bits),
    }


def apply_suggestion(text: str, start: int, end: int, replacement: str) -> str:
    """Replace one span. Used when the person taps a candidate."""
    blob = text or ""
    if start < 0 or end > len(blob) or start > end:
        return blob
    return blob[:start] + (replacement or "") + blob[end:]


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

    portrait = local.get("habits") or {}
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
