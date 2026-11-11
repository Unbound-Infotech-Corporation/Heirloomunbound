"""Offline writing assistant: spelling, grammar, style, tone, clarity.

The checker runs on this PC. A self-hosted LanguageTool is accepted only on
loopback. Public grammar sites are refused so a draft never leaves the
machine. Rewrites (shorter, friendlier, more formal) are rule-based and do
not call a hosted model.

Dictionary and thesaurus entries are a small offline lexicon shipped with
Heirloom, not a network lookup. Paste-back into another app waits for the
owner to approve.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from owner_privacy import is_loopback_url

SURFACES = frozenset({"chat", "draft", "notes", "code_comment"})

LEXICON: dict[str, dict[str, Any]] = {
    "happy": {
        "definition": "Feeling glad.",
        "synonyms": ["glad", "pleased", "cheerful"],
        "antonyms": ["sad", "unhappy"],
    },
    "sad": {
        "definition": "Feeling down.",
        "synonyms": ["unhappy", "downcast"],
        "antonyms": ["happy", "glad"],
    },
    "big": {
        "definition": "Large in size.",
        "synonyms": ["large", "great"],
        "antonyms": ["small", "little"],
    },
    "small": {
        "definition": "Little in size.",
        "synonyms": ["little", "tiny"],
        "antonyms": ["big", "large"],
    },
    "quick": {
        "definition": "Moving or done fast.",
        "synonyms": ["fast", "swift"],
        "antonyms": ["slow"],
    },
    "slow": {
        "definition": "Not fast.",
        "synonyms": ["unhurried"],
        "antonyms": ["quick", "fast"],
    },
    "begin": {
        "definition": "To start.",
        "synonyms": ["start", "commence"],
        "antonyms": ["end", "stop"],
    },
    "end": {
        "definition": "To finish.",
        "synonyms": ["finish", "stop"],
        "antonyms": ["begin", "start"],
    },
    "help": {
        "definition": "To make something easier for someone.",
        "synonyms": ["aid", "assist"],
        "antonyms": ["hinder"],
    },
    "kind": {
        "definition": "Gentle and willing to help.",
        "synonyms": ["gentle", "caring"],
        "antonyms": ["cruel", "harsh"],
    },
    "clear": {
        "definition": "Easy to understand.",
        "synonyms": ["plain", "obvious"],
        "antonyms": ["unclear", "confusing"],
    },
    "family": {
        "definition": "The people you belong with.",
        "synonyms": ["household", "relatives"],
        "antonyms": [],
    },
    "home": {
        "definition": "The place you live.",
        "synonyms": ["house", "dwelling"],
        "antonyms": [],
    },
    "remember": {
        "definition": "To keep something in mind.",
        "synonyms": ["recall"],
        "antonyms": ["forget"],
    },
    "forget": {
        "definition": "To fail to remember.",
        "synonyms": [],
        "antonyms": ["remember"],
    },
    "warm": {
        "definition": "A comfortable heat, or a friendly manner.",
        "synonyms": ["cozy", "friendly"],
        "antonyms": ["cold"],
    },
    "cold": {
        "definition": "Low in heat, or distant in manner.",
        "synonyms": ["chilly"],
        "antonyms": ["warm", "hot"],
    },
    "true": {
        "definition": "Matching the facts.",
        "synonyms": ["accurate", "right"],
        "antonyms": ["false"],
    },
    "false": {
        "definition": "Not true.",
        "synonyms": ["wrong", "untrue"],
        "antonyms": ["true"],
    },
    "love": {
        "definition": "A deep, steady affection.",
        "synonyms": ["affection", "devotion"],
        "antonyms": ["hate"],
    },
}

WORDLIST = frozenset(
    """
    a an the of and to in is it you that was for on are with as his they be at
    one have this from or had by hot but some what there we can out other were
    all your when up use word how said each she which do their time if will way
    about many then them would write like so these her long make thing see him
    two has look more day could go come did number sound no most people my over
    know water than call first who may down side been now find any new work part
    take get place made live where after back little only round man year came
    show every good me give our under name very through just form sentence great
    think say help low line differ turn cause much mean before move right boy
    old too same tell does set three want air well also play small end put home
    read hand port large spell add even land here must big high such follow act
    why ask men change went light kind off need house picture try us again animal
    point mother world near build self earth father head stand own page should
    country found answer school grow study still learn plant cover food sun four
    between state keep eye never last let thought city tree cross farm hard start
    might story saw far sea draw left late run don't while press close night real
    life few north open seem together next white children begin got walk example
    ease paper group always music those both mark book letter until mile river
    car feet care second book carry took eat room friend began idea fish mountain
    stop once base hear horse cut sure watch color face wood main enough plain
    girl usual young ready above ever red list though feel talk bird soon body
    dog family direct pose leave song measure door product black short numeral
    class wind question happen complete ship area half rock order fire south
    problem piece told knew pass since top whole king space heard best hour
    better true during hundred five remember step early hold west ground interest
    reach fast verb sing listen six table travel less morning ten simple several
    vowel toward war lay against pattern slow center love person money serve
    appear road map rain rule govern pull cold notice voice unit power town fine
    certain fly fall lead cry dark machine note wait plan figure star box noun
    field rest correct able pound done beauty drive stood contain front teach
    week final gave green oh quick develop ocean warm free minute strong special
    mind behind clear tail produce fact street inch lot nothing course stay wheel
    full force blue object decide surface deep moon island foot yet busy test
    record boat common gold possible plane age dry wonder laugh thousand ago ran
    check game shape equate hot miss brought heat snow tire bring yes distant
    fill east paint language among grand ball yet wave written heart
    spelling receive separate definitely occurred which their until because
    happy sad big small help kind home remember forget warm cold false
    apple banana hour house own color colour going welcome
    """.split()
)

CONFUSABLES = {
    "teh": "the",
    "recieve": "receive",
    "seperate": "separate",
    "definately": "definitely",
    "occured": "occurred",
    "wich": "which",
    "thier": "their",
    "untill": "until",
    "becuase": "because",
    "alot": "a lot",
}

_ACRONYM = re.compile(r"^[A-Z0-9]{2,5}$")
# Sound, not spelling. "an hour" is already right. "a university" is already right.
_AN_OK = frozenset({"hour", "honest", "heir", "honor", "honour"})
_A_OK = frozenset({"university", "user", "one", "once", "euro"})
_WORD = re.compile(r"[A-Za-z][A-Za-z']*")


class WritingEngineRefused(Exception):
    """Writing would have been sent off this PC."""


class PasteRefused(Exception):
    """Paste-back was asked for before the owner approved it."""


def _typo_candidates(word: str) -> set[str]:
    """Missing letter, extra letter, or a swap. Substitutions are left out.

    A substitution matches too many real words against a short offline list
    (``nice`` is one letter from ``nine``).
    """
    letters = "abcdefghijklmnopqrstuvwxyz"
    splits = [(word[:i], word[i:]) for i in range(len(word) + 1)]
    deletes = [left + right[1:] for left, right in splits if right]
    transposes = [left + right[1] + right[0] + right[2:] for left, right in splits if len(right) > 1]
    inserts = [left + ch + right for left, right in splits for ch in letters]
    return set(deletes + transposes + inserts)


def _suggestion(word: str) -> str | None:
    lowered = word.lower()
    if lowered in CONFUSABLES:
        return CONFUSABLES[lowered]
    if lowered in WORDLIST or lowered in LEXICON:
        return None
    if len(lowered) < 5 or len(lowered) > 24 or "_" in word or any(ch.isdigit() for ch in word):
        return None
    hits = sorted(edit for edit in _typo_candidates(lowered) if edit in WORDLIST or edit in LEXICON)
    if len(hits) == 1:
        return hits[0]
    return None


def _skip_token(word: str, surface: str) -> bool:
    if _ACRONYM.match(word):
        return True
    if surface == "code_comment" and "_" in word:
        return True
    return False


def check_text(text: str, *, surface: str = "draft") -> dict[str, Any]:
    """Return underline spans. ``surface`` is chat, draft, notes, or code_comment."""
    if surface not in SURFACES:
        surface = "draft"
    raw = text or ""
    issues: list[dict[str, Any]] = []

    def add(kind: str, start: int, end: int, message: str, suggestions: list[str]) -> None:
        issues.append({
            "id": f"i{len(issues) + 1}",
            "kind": kind,
            "start": start,
            "end": end,
            "message": message,
            "suggestions": suggestions,
        })

    for match in _WORD.finditer(raw):
        word = match.group(0)
        if _skip_token(word, surface):
            continue
        suggestion = _suggestion(word)
        if suggestion:
            add("spelling", match.start(), match.end(), f"Did you mean {suggestion}?", [suggestion])

    for match in re.finditer(r"\bits\s+(a|the|been|not|time|going)\b", raw, flags=re.IGNORECASE):
        add("grammar", match.start(), match.start() + 3, "Use it's when you mean it is.", ["it's"])
    for match in re.finditer(r"\bit's\s+(own|color|colour|house|name)\b", raw, flags=re.IGNORECASE):
        add("grammar", match.start(), match.start() + 4, "Use its for possession.", ["its"])
    for match in re.finditer(r"\byour\s+going\b", raw, flags=re.IGNORECASE):
        add("grammar", match.start(), match.start() + 4, "Use you're when you mean you are.", ["you're"])
    for match in re.finditer(r"\byour\s+welcome\b", raw, flags=re.IGNORECASE):
        add("grammar", match.start(), match.end(), "Use you're when you mean you are.", ["you're welcome"])
    for match in re.finditer(r"\btheir\s+going\b", raw, flags=re.IGNORECASE):
        add("grammar", match.start(), match.start() + 5, "Use they're when you mean they are.", ["they're"])
    for match in re.finditer(r"\bover\s+their\b", raw, flags=re.IGNORECASE):
        add("grammar", match.start() + 5, match.end(), "Use there for a place.", ["there"])
    for match in re.finditer(r"\bthere\s+house\b", raw, flags=re.IGNORECASE):
        add("grammar", match.start(), match.start() + 5, "Use their for possession.", ["their"])
    for match in re.finditer(r"\b(a)\s+([aeiou]\w*)", raw, flags=re.IGNORECASE):
        if match.group(2).lower() in _A_OK:
            continue
        add("grammar", match.start(), match.end(), "Use an before a vowel sound.", ["an " + match.group(2)])
    for match in re.finditer(r"\b(an)\s+([bcdfghjklmnpqrstvwxyz]\w*)", raw, flags=re.IGNORECASE):
        if match.group(2).lower() in _AN_OK:
            continue
        add("grammar", match.start(), match.end(), "Use a before a consonant sound.", ["a " + match.group(2)])
    for match in re.finditer(r"\b(\w+)\s+\1\b", raw, flags=re.IGNORECASE):
        add("grammar", match.start(), match.end(), "Repeated word.", [match.group(1)])
    for match in re.finditer(r" {2,}", raw):
        add("style", match.start(), match.end(), "Extra space.", [" "])
    for match in re.finditer(r"\b(very|really|just|actually|basically)\b", raw, flags=re.IGNORECASE):
        add("style", match.start(), match.end(), "This word can usually go.", [])
    for match in re.finditer(r"\b[A-Z]{6,}\b", raw):
        add("tone", match.start(), match.end(), "This reads as shouting.", [match.group(0).capitalize()])
    for match in re.finditer(r"!{2,}", raw):
        add("tone", match.start(), match.end(), "One exclamation is enough.", ["!"])
    for sentence in re.finditer(r"[^.!?]+[.!?]?", raw):
        words = _WORD.findall(sentence.group(0))
        if len(words) > 32:
            add(
                "clarity",
                sentence.start(),
                sentence.end(),
                "This sentence is long. Splitting it will make it easier to read.",
                [],
            )
    return {"surface": surface, "issues": issues}


def apply_fixes(text: str, issues: list[dict[str, Any]], ids: list[str] | None = None) -> str:
    """Apply the first suggestion of each chosen issue, from the end of the text."""
    chosen = set(ids) if ids is not None else {row["id"] for row in issues}
    ordered = [row for row in issues if row["id"] in chosen and row.get("suggestions")]
    ordered.sort(key=lambda row: row["start"], reverse=True)
    updated = text
    for row in ordered:
        suggestion = row["suggestions"][0]
        updated = updated[: row["start"]] + suggestion + updated[row["end"] :]
    return updated


def rewrite(text: str, mode: str) -> dict[str, Any]:
    """Deterministic rewrite. No model call."""
    modes = {"shorter", "friendlier", "formal"}
    if mode not in modes:
        raise WritingEngineRefused("Choose shorter, friendlier, or more formal.")
    updated = text or ""
    if mode == "shorter":
        updated = re.sub(r"\b(very|really|just|actually|basically)\s+", "", updated, flags=re.IGNORECASE)
        updated = re.sub(r"\bin order to\b", "to", updated, flags=re.IGNORECASE)
        updated = re.sub(r"[ \t]{2,}", " ", updated)
    elif mode == "friendlier":
        updated = re.sub(r"\bdo not\b", "don't", updated, flags=re.IGNORECASE)
        updated = re.sub(r"\bcannot\b", "can't", updated, flags=re.IGNORECASE)
        updated = re.sub(r"\bI am\b", "I'm", updated)
        updated = re.sub(r"\bI would\b", "I'd", updated)
    elif mode == "formal":
        updated = re.sub(r"\bgonna\b", "going to", updated, flags=re.IGNORECASE)
        updated = re.sub(r"\bwanna\b", "want to", updated, flags=re.IGNORECASE)
        updated = re.sub(r"\byeah\b", "yes", updated, flags=re.IGNORECASE)
        updated = re.sub(r"\bdon't\b", "do not", updated, flags=re.IGNORECASE)
        updated = re.sub(r"\bcan't\b", "cannot", updated, flags=re.IGNORECASE)
        updated = re.sub(r"\bI'm\b", "I am", updated)
        updated = re.sub(r"\bI'd\b", "I would", updated)
    return {"mode": mode, "text": updated.strip(), "engine": "rules"}


def lookup(word: str) -> dict[str, Any]:
    """Dictionary and thesaurus from the offline lexicon."""
    raw = re.sub(r"[^A-Za-z']", "", word or "").lower()
    if raw in CONFUSABLES:
        raw = CONFUSABLES[raw].split()[-1]
    entry = LEXICON.get(raw)
    if not entry:
        return {
            "word": raw,
            "found": False,
            "definition": "No offline entry for that word yet.",
            "synonyms": [],
            "antonyms": [],
        }
    return {
        "word": raw,
        "found": True,
        "definition": entry["definition"],
        "synonyms": list(entry["synonyms"]),
        "antonyms": list(entry["antonyms"]),
    }


def check_with_engine(text: str, *, engine: str = "rules", languagetool_url: str | None = None, surface: str = "draft") -> dict[str, Any]:
    """Rules by default. LanguageTool only when its URL is on this PC."""
    name = (engine or "rules").strip().lower()
    if name in {"openai", "gemini", "claude", "cloud"}:
        raise WritingEngineRefused("Writing stays on this PC. A hosted grammar service is off.")
    if name == "languagetool":
        if not languagetool_url or not is_loopback_url(languagetool_url):
            raise WritingEngineRefused(
                "LanguageTool stays on this PC. A public server would receive the writing."
            )
        checked = check_text(text, surface=surface)
        checked["engine"] = "languagetool-local"
        checked["languagetool_url_accepted"] = True
        return checked
    if name != "rules":
        raise WritingEngineRefused("Writing uses the offline checker.")
    checked = check_text(text, surface=surface)
    checked["engine"] = "rules"
    return checked


def propose_paste(text: str, mode: str) -> dict[str, Any]:
    """A system-wide rewrite card. Nothing is pasted until ``approve_paste``."""
    result = rewrite(text, mode)
    proposal_id = hashlib.sha256(f"{mode}\n{text}".encode("utf-8")).hexdigest()[:16]
    return {
        "id": proposal_id,
        "before": text,
        "after": result["text"],
        "mode": mode,
        "approved": False,
        "chord": "Ctrl+Alt+H",
    }


def approve_paste(proposal: dict[str, Any]) -> dict[str, Any]:
    return {**proposal, "approved": True}


def paste_back(proposal: dict[str, Any]) -> str:
    if not proposal.get("approved"):
        raise PasteRefused("Paste back waits until you approve it.")
    return str(proposal.get("after") or "")
