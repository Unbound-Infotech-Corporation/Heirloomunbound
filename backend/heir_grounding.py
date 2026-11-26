"""Grounding for the Heir Portal chat. Same rules as the owner Twin (grounding.py).

An heir may only hear what the owner wrote down and shared:

* approved memory cards the heir may see (owner-only and private cards never load),
* archive entries the heir may see (the memory_guard fence is in the Mongo query),
* sealed letters already unlocked for this heir (locked letters never load),

and, when a row lists ``heir_ids``, only those heirs. The heir's own messages are
never evidence about the owner's life: an heir can't plant a fact by asking about it.

A life question is answered from the relevant rows only and then fact-checked
(grounding.answer_personal). Any other reply (a greeting, comfort, small talk) is
fact-checked too (grounding.verify_reply), so an invented memory is removed either
way. With nothing to stand on the Twin says HEIR_NO_MEMORY.
"""
from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, Optional

from grounding import HEIR_NO_MEMORY, AskModel, answer_personal, classify_turn, strip_false_promises, verify_reply

Loader = Callable[[], Awaitable[list[dict]]]

# "How did you and Grandma meet?" — the heir's "you" is the owner. These are
# recall questions even though the owner-side keyword gate looks for "my".
_HEIR_RECALL = re.compile(
    r"\b(how|when|where|why) (did|were|was) you\b"
    r"|\bdid you (ever|have|meet|grow|go|live|work|serve|marry|play|keep|own|build|teach|learn)\b"
    r"|\b(what|who|which) (was|were|is) your\b"
    r"|\btell me (about|more about) (your|you and|when you|the time|how you)\b"
    r"|\bdo you remember\b|\bremember when\b"
    r"|\bwhat did you (do|call|name|love|like|teach|tell|say|drive|study|want|write|mean|leave|hope)\b"
    r"|\byour letter\b|\byou wrote\b|\byou left me\b|\bwant(ed)? me to (know|have|keep)\b"
    r"|\bhow old were you\b|\bwhat happened (when|to|with)\b"
    r"|\b(your|grandma'?s?|grandpa'?s?|grandmother'?s?|grandfather'?s?) (wedding|childhood|first|parents|mom|mother|dad|father|job|house|dog|car|war|army|navy)\b",
    re.IGNORECASE,
)

HEIR_CLASSIFY_NOTE = (
    "\n\nThe sender is a family member (an heir) talking to the twin. When they say "
    "\"you\" or \"your\" they mean the owner, so \"How did you and Grandma meet?\" or "
    "\"What was your first job?\" is personal=true."
)


def heir_asks_for_memory(text: str) -> bool:
    return bool(_HEIR_RECALL.search(" ".join((text or "").split())))


def per_heir_clause(heir_id: str) -> dict:
    """Rows without heir_ids are for every heir; a list limits them to those heirs."""
    return {"$or": [{"heir_ids": {"$exists": False}}, {"heir_ids": None}, {"heir_ids": []}, {"heir_ids": heir_id}]}


def shared_with(row: dict, heir_id: str) -> bool:
    ids = row.get("heir_ids")
    if not ids:
        return True
    return heir_id in [str(x) for x in ids]


def heir_cards(cards: list[dict], heir_id: str) -> list[dict]:
    """Approved, heir-visible, shared with this heir."""
    from memory_cards import visible_cards

    approved = [c for c in cards or [] if str(c.get("status") or "") == "approved"]
    return [c for c in visible_cards(approved, audience="heir", heir_surface=True) if shared_with(c, heir_id)]


def entry_as_card(entry: dict) -> dict:
    tags = entry.get("tags") or []
    return {
        "card_id": str(entry.get("entry_id") or ""),
        "title": str(entry.get("title") or "A memory"),
        "story": " ".join(str(entry.get("content") or "").split())[:4000],
        "era": "",
        "people": [str(t) for t in tags if isinstance(t, str)][:8] if entry.get("type") == "person" else [],
        "status": "approved",
        "kind": "entry",
    }


def letter_as_card(letter: dict) -> dict:
    return {
        "card_id": str(letter.get("letter_id") or ""),
        "title": str(letter.get("title") or "A letter"),
        "story": " ".join(str(letter.get("body") or "").split())[:4000],
        "era": "",
        "people": [str(letter.get("recipient_name"))] if letter.get("recipient_name") else [],
        "status": "approved",
        "kind": "letter",
    }


def heir_context_line(heir: dict, owner: dict) -> str:
    """What the twin may say about who it is talking to. Comes from the heir record, not the chat."""
    name = str(heir.get("name") or "").strip()
    rel = str(heir.get("relationship") or "").strip()
    if not name:
        return ""
    return f"I am talking with {name}" + (f", my {rel}" if rel else "") + "."


def citations(cards: list[dict]) -> list[dict[str, str]]:
    return [{"id": str(c.get("card_id") or ""), "title": str(c.get("title") or "A memory"),
             "kind": str(c.get("kind") or "card")} for c in cards]


async def select_evidence(question: str, rows: list[dict]) -> list[dict]:
    from memory_cards import recall_cards

    try:
        return await recall_cards(question, rows)
    except Exception:  # noqa: BLE001
        from memory_cards import select_cards

        return select_cards(rows, question)


async def heir_reply(
    text: str,
    *,
    owner: dict,
    heir: dict,
    rows: list[dict],
    draft: Callable[[list[dict]], Awaitable[str]],
    ask: Optional[AskModel] = None,
    observer: Optional[dict] = None,
) -> dict[str, Any]:
    """One heir turn. ``rows`` are already fenced for this heir. ``draft`` writes a free reply
    (greetings, comfort) from the selected rows; it is fact-checked before anyone sees it."""
    used = await select_evidence(text, rows)
    if observer:
        used = used + [observer]
    context = heir_context_line(heir, owner)
    said = [context] if context else []

    if heir_asks_for_memory(text):
        personal, source = True, "heir-keyword"
    else:
        turn = await classify_turn(text, ask=_heir_ask(ask))
        personal, source = turn.personal, turn.source
        if personal and source == "model" and not _is_question(text):
            # "I miss you so much." is not a request for a memory; the free reply is still checked.
            personal, source = False, "model-statement"
    meta: dict[str, Any] = {"personal": personal, "classifier": source, "evidence": len(used)}

    if personal:
        answered = await answer_personal(text, cards=used, owner_messages=said,
                                         name=str(owner.get("name") or ""), ask=ask)
        meta.update(answered.get("trace") or {})
        cited = answered.get("cited") or []
        if not cited:
            return {"reply": HEIR_NO_MEMORY, "cited": [], "grounded": False, "meta": meta}
        return {"reply": answered["reply"], "cited": citations(cited), "grounded": True, "meta": meta}

    raw = strip_false_promises(await draft(used) or "")
    verdict = await verify_reply(raw, cards=used, owner_messages=said, ask=ask)
    meta.update({"verify": verdict.source, "removed": len(verdict.removed)})
    final = names_only_from_evidence(verdict.text, used, said)
    if not final:
        reply = HEIR_NO_MEMORY if _is_question(text) else here_line(heir)
        return {"reply": reply, "cited": [], "grounded": False, "meta": meta}
    from memory_cards import citations_that_ground

    return {"reply": final, "cited": citations(citations_that_ground(final, used)), "grounded": True, "meta": meta}


def _is_question(text: str) -> bool:
    raw = " ".join((text or "").split()).lower()
    return raw.endswith("?") or bool(re.match(r"^(who|what|when|where|why|how|did|do|does|was|were|is|are|can|could|tell me|remember)\b", raw))


def here_line(heir: dict) -> str:
    name = str(heir.get("name") or "").strip()
    return f"I'm glad you're here, {name}." if name else "I'm glad you're here."


def names_only_from_evidence(text: str, used: list[dict], said: list[str]) -> str:
    """Drop any sentence that names a person, place or number the evidence never mentions
    (an invented "Aunt Sarah"), even when the checker model let it through."""
    from grounding import evidence_text, is_harmless, split_sentences, unseen_details

    evidence = evidence_text(used, said)
    low_evidence = evidence.lower()
    kept, dropped_last = [], False
    for line in split_sentences(text or ""):
        kin = {w.lower() for w in _KIN.findall(line)}
        words = {w.lower() for w in re.findall(r"[A-Za-z']{5,}", line)}
        new_words = {w for w in words if w not in low_evidence and w not in _WARM}
        ok = (not any(w not in low_evidence for w in kin)  # "ask my sister" when no memory mentions a sister
              and not new_words                          # "the church picnic" that no memory mentions
              and (is_harmless(line, evidence) or not unseen_details(line, evidence))
              and not (dropped_last and _LEANS_BACK.match(line)))  # "They could share..." after a dropped line
        if ok:
            kept.append(line)
        dropped_last = not ok
    return " ".join(kept).strip()


_LEANS_BACK = re.compile(r"^\s*(they|them|he|she|it|that|those|this|these|there)\b", re.IGNORECASE)
# Small talk a free heir reply may use without a memory behind it; any other word must come from the evidence.
_WARM = frozenset("""
hello there great happy glad wonderful lovely really means thank thanks always forever proud
today talking talked again right still every everything anything something someone nothing
being would could should might maybe think thinking feeling feels heart loved loves lucky
hear hearing visit visiting moment sweet dear honey darling about where which while whenever
here's there's that's you're we're i've you've it's what's let's don't can't won't didn't
grateful blessed missed missing mean meant world means asking share chat little favorite
please sorry yourself myself together whatever care careful because doing going coming
""".split())


_KIN = re.compile(
    r"\b(sisters?|brothers?|aunts?|uncles?|cousins?|nieces?|nephews?|mother|mom|father|dad|sons?|daughters?|"
    r"wife|husband|grandma|grandpa|grandmother|grandfather|parents|siblings|relatives|family members?)\b",
    re.IGNORECASE,
)


def _heir_ask(ask: Optional[AskModel]) -> AskModel:
    from grounding import CLASSIFY_SYSTEM, ask_box_model

    caller = ask or ask_box_model

    async def classify(system: str, prompt: str, **kw: Any) -> str:
        if system == CLASSIFY_SYSTEM:
            system = CLASSIFY_SYSTEM + HEIR_CLASSIFY_NOTE
        return await caller(system, prompt, **kw)

    return classify
