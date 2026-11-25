"""One interview answer becomes a memory card the twin can use after approval.

Local models only. Pending cards and observer notes are not answers.
Owner-private cards stay on the box; this module does not call Odysseus.
"""
from __future__ import annotations

import json
import math
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from standing_routines import GAP_PROMPTS

EMBED_MODEL = "nomic-embed-text"
Complete = Callable[[str, str], Awaitable[str]]

DAILY_REFLECTIONS: tuple[tuple[str, str], ...] = (
    ("joy", "What's one small joy from yesterday worth keeping?"),
    ("call", "Who do you wish you'd called this week?"),
    ("son", "Name one thing your family should know about today."),
    ("surprise", "What surprised you in the last day?"),
    ("learn", "What did you learn that you don't want to forget?"),
    ("thought", "What's a thought you've been turning over?"),
    ("thanks", "What did you do today that your future self will thank you for?"),
)

CARD_SYSTEM = """Turn the owner's spoken or typed answer into a memory card.
Return ONLY a JSON object with keys title, era, people, story.
title: a short name for the memory.
era: a year, decade, or life stage they actually named. Empty string if they did not.
people: a JSON array of names they actually named. Empty array if they named nobody.
story: the memory in their words. Do not add facts they did not say.
"""

ANSWER_SYSTEM = (
    "You are the owner, speaking in the first person. Say I, my, and me. "
    "Never say 'your' about this life. Use only the approved memories. "
    "If they do not answer the question, say you don't remember. Do not invent a life."
)

FIRST_PERSON = (
    "You are the owner. Speak in the first person: I, my, me. "
    "Never say 'your first car' or 'you' about this life. "
    "Do not print tool calls. The archive is already in this prompt."
)


def _now(now: Optional[datetime] = None) -> datetime:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def prompt_catalog() -> list[dict[str, str]]:
    rows = [
        {"key": gap["key"], "label": gap["label"], "question": gap["question"]}
        for gap in GAP_PROMPTS
    ]
    for key, question in DAILY_REFLECTIONS:
        rows.append({"key": key, "label": question[:48], "question": question})
    return rows


_STOP = frozenset({
    "the", "a", "an", "of", "in", "on", "to", "for", "was", "is", "are",
    "what", "where", "when", "who", "why", "how", "my", "me", "i", "did",
    "do", "does", "that", "this", "at", "with", "and", "you", "your", "named",
    "name", "about", "from", "have", "had", "been", "were", "his", "her",
    "their", "our", "it", "its",
})


def _tokens(text: str) -> set[str]:
    """Content words only. 'was' must not cite an unrelated card."""
    return {
        part
        for part in re.split(r"\W+", (text or "").lower())
        if len(part) > 2 and part not in _STOP
    }


def waiting_items(prompts: list[dict], nudges: list[dict] | None = None) -> list[dict]:
    """Unanswered interview prompts, oldest first. Open biographer nudges count too."""
    rows: list[dict] = []
    for prompt in prompts or []:
        if str(prompt.get("status") or "") != "unanswered":
            continue
        rows.append(dict(prompt))
    for nudge in nudges or []:
        if str(nudge.get("status") or "open") not in {"open", "unanswered"}:
            continue
        kind = str(nudge.get("kind") or "")
        if kind in {"morning_brief", "sealed_letter_nudge"}:
            continue
        question = str(nudge.get("action_prompt") or nudge.get("question") or "").strip()
        if not question:
            continue
        rows.append({
            "prompt_id": str(nudge.get("nudge_id") or ""),
            "key": kind or "nudge",
            "question": question,
            "status": "unanswered",
            "source": "nudge",
            "created_at": str(nudge.get("created_at") or ""),
        })
    rows.sort(key=lambda row: (str(row.get("created_at") or ""), str(row.get("prompt_id") or "")))
    return rows


def choose_prompt(
    prompts: list[dict],
    nudges: list[dict] | None = None,
    *,
    today: str,
    catalog: list[dict] | None = None,
    chosen_key: str = "",
    chosen_question: str = "",
) -> dict[str, Any]:
    """The next question. An open prompt or nudge is shown as-is. Nothing new is added while any are waiting."""
    book = catalog if catalog is not None else prompt_catalog()
    waiting = waiting_items(prompts, nudges)
    key = (chosen_key or "").strip()
    question = (chosen_question or "").strip()
    if key or question:
        for row in waiting:
            if key and str(row.get("key") or "") == key:
                return {"prompt": row, "create": False, "persist": False, "waiting": len(waiting)}
            if question and str(row.get("question") or "") == question:
                return {"prompt": row, "create": False, "persist": False, "waiting": len(waiting)}
        match = next((item for item in book if item["key"] == key or item["question"] == question), None)
        shown = {
            "prompt_id": "",
            "key": key or (match["key"] if match else "chosen"),
            "question": question or (match["question"] if match else ""),
            "status": "unanswered",
            "created_at": "",
        }
        # A suggested topic can be answered now. It must not become a second
        # unanswered row while older questions are still waiting.
        return {
            "prompt": shown,
            "create": not waiting,
            "persist": not waiting,
            "waiting": len(waiting),
        }
    # Open prompts and nudges are the queue. Do not add another while any are waiting.
    if waiting:
        today_open = [
            row for row in waiting
            if str(row.get("created_at") or "")[:10] == today and row.get("source") != "nudge"
        ]
        return {
            "prompt": today_open[-1] if today_open else waiting[0],
            "create": False,
            "persist": False,
            "waiting": len(waiting),
        }
    if not book:
        return {"prompt": None, "create": False, "persist": False, "waiting": 0}
    try:
        index = datetime.fromisoformat(today).toordinal()
    except ValueError:
        index = 0
    item = book[index % len(book)]
    return {
        "prompt": {
            "prompt_id": "",
            "key": item["key"],
            "question": item["question"],
            "status": "unanswered",
            "created_at": "",
        },
        "create": True,
        "persist": True,
        "waiting": len(waiting),
    }


def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        loaded = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _story_stays_in_their_words(story: str, transcript: str) -> bool:
    told = _tokens(story)
    source = _tokens(transcript)
    if not told:
        return False
    if not source:
        return False
    shared = told & source
    return len(shared) * 2 >= len(told)


def card_from_model(transcript: str, question: str, model_text: str) -> dict[str, Any]:
    """A card the owner can edit. The story falls back to their words if the model invents."""
    parsed = _extract_json(model_text or "") or {}
    words = " ".join((transcript or "").split())
    story = " ".join(str(parsed.get("story") or "").split())
    if not story or not _story_stays_in_their_words(story, words):
        story = words
    title = " ".join(str(parsed.get("title") or "").split())
    if not title:
        title = words.split(".")[0][:80].strip() or "A memory"
    era = " ".join(str(parsed.get("era") or "").split())[:80]
    people_raw = parsed.get("people")
    people: list[str] = []
    if isinstance(people_raw, list):
        for name in people_raw:
            cleaned = " ".join(str(name).split())
            if cleaned and cleaned.lower() in words.lower():
                people.append(cleaned[:80])
    return {
        "title": title[:120],
        "era": era,
        "people": people[:8],
        "story": story[:4000],
        "transcript": words[:8000],
        "question": (question or "")[:500],
        "status": "pending",
    }


def embed_mode(*, listed: list[str], pull_ok: bool = False, pull_error: str = "") -> str:
    """Use local embeddings when the model is present or the pull worked. Otherwise keywords."""
    names = {str(name).split(":", 1)[0] for name in listed or []}
    if EMBED_MODEL in names or any(str(name).startswith(EMBED_MODEL) for name in listed or []):
        return "embed"
    if pull_ok:
        return "embed"
    if pull_error:
        return "keyword"
    return "pull"


def card_embed_text(card: dict) -> str:
    people = ", ".join(card.get("people") or [])
    return " ".join(
        part for part in (
            str(card.get("title") or ""),
            str(card.get("era") or ""),
            people,
            str(card.get("story") or ""),
        ) if part
    )


def _cosine(left: list[float] | None, right: list[float] | None) -> float | None:
    if not left or not right or len(left) != len(right):
        return None
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left)) or 1.0
    right_norm = math.sqrt(sum(b * b for b in right)) or 1.0
    return dot / (left_norm * right_norm)


def should_embed(cards: list[dict], keyword_hits: list[dict]) -> bool:
    """Ask Ollama only when keywords missed and an approved card could be a paraphrase."""
    if keyword_hits:
        return False
    return any(str(card.get("status") or "") == "approved" for card in cards or [])


def blend_score(keyword: float, cosine: float | None) -> float:
    """Keywords stay in charge of exact words. A strong local embedding can recall a paraphrase.

    A weak embedding does not invent a match, so an unrelated card still scores 0.
    """
    if cosine is None or cosine < 0.72:
        return keyword
    return max(keyword, cosine)


def _score_card(card: dict, query: str) -> float:
    hay = " ".join([
        str(card.get("title") or ""),
        str(card.get("era") or ""),
        " ".join(card.get("people") or []),
        str(card.get("story") or ""),
        str(card.get("question") or ""),
    ])
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0
    hay_tokens = _tokens(hay)
    if not hay_tokens:
        return 0.0
    return len(query_tokens & hay_tokens) / len(query_tokens)


def visible_cards(
    cards: list[dict],
    *,
    audience: str = "owner",
    heir_surface: bool = False,
) -> list[dict]:
    """Owner-private cards stay out of heir and caller prompts."""
    heir = heir_surface or (audience or "").strip().lower() in {"heir", "caller"}
    if not heir:
        return list(cards or [])
    hidden = {"owner", "private"}
    return [card for card in cards or [] if str(card.get("visibility") or "owner") not in hidden]


def select_cards(
    cards: list[dict],
    query: str,
    *,
    limit: int = 3,
    vectors: dict[str, list[float]] | None = None,
    query_vector: list[float] | None = None,
) -> list[dict]:
    """Approved cards only. Pending cards cannot ground an answer.

    ``vectors`` are local embeddings (nomic-embed-text). Missing vectors fall
    back to keywords, which still ignore stopwords.
    """
    ranked: list[tuple[float, dict]] = []
    known = vectors or {}
    for card in cards or []:
        if str(card.get("status") or "") != "approved":
            continue
        keyword = _score_card(card, query)
        cosine = _cosine(query_vector, known.get(str(card.get("card_id") or "")))
        score = blend_score(keyword, cosine)
        if score <= 0:
            continue
        ranked.append((score, card))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [card for _score, card in ranked[:limit]]


_DECLINE = (
    "don't remember",
    "do not remember",
    "don't have an approved memory",
    "do not have an approved memory",
    "nothing filed",
)


def reply_is_only_a_tool_call(text: str) -> bool:
    raw = (text or "").strip().strip("`")
    return bool(re.fullmatch(
        r"(?is)(?:search_archive|list_recent_memories|set_reminder|run_skill)\s*\([^)]*\)",
        raw,
    ))


def spoken_reply(text: str) -> str:
    """Drop a reply that is only a tool call the local model printed as text."""
    raw = (text or "").strip()
    if reply_is_only_a_tool_call(raw):
        return ""
    kept = [line for line in raw.splitlines() if not reply_is_only_a_tool_call(line.strip())]
    return "\n".join(kept).strip()


def as_owner_voice(text: str) -> str:
    """The twin is the owner. A sentence that starts with 'Your' is 'My'.

    Mid-sentence 'your' stays, so 'your question' is left alone.
    """
    raw = spoken_reply(text)
    if not raw:
        return ""

    def _own(match: re.Match) -> str:
        return match.group(1) + ("My" if match.group(2)[:1].isupper() else "my")

    return re.sub(r"(^|[.!?]\s+)([Yy]our)\b", _own, raw)


def _declines(reply: str) -> bool:
    """A refusal. A memory that continues after but/though is kept."""
    folded = " ".join((reply or "").lower().split())
    hit = next((phrase for phrase in _DECLINE if phrase in folded), "")
    if not hit:
        return False
    after = folded.split(hit, 1)[1]
    if re.search(r"\b(but|except|though|however)\b", after):
        return len(_tokens(after)) < 3
    return True


def citations_that_ground(reply: str, cards: list[dict]) -> list[dict]:
    """Keep a card only when the reply actually uses it."""
    if _declines(reply):
        return []
    reply_tokens = _tokens(reply)
    if not reply_tokens:
        return []
    kept: list[dict] = []
    for card in cards or []:
        hay = " ".join([
            str(card.get("title") or ""),
            str(card.get("story") or ""),
            " ".join(card.get("people") or []),
        ])
        if _tokens(hay) & reply_tokens:
            kept.append(card)
    return kept


def stored_prompt_status(choice: dict) -> Optional[str]:
    """How to file a new prompt. Draft is linked to the card and is not 'waiting'."""
    prompt = choice.get("prompt") or {}
    if not isinstance(prompt, dict):
        return None
    if str(prompt.get("prompt_id") or "").strip():
        return None
    if not str(prompt.get("question") or "").strip():
        return None
    if choice.get("persist", True):
        return "unanswered"
    return "draft"


def why_from(cards: list[dict]) -> list[dict[str, str]]:
    rows = []
    for card in cards:
        rows.append({
            "card_id": str(card.get("card_id") or ""),
            "title": str(card.get("title") or "A memory"),
            "story": str(card.get("story") or ""),
        })
    return rows


def grounding_block(cards: list[dict]) -> str:
    if not cards:
        return ""
    lines = [
        "APPROVED MEMORIES. Use only these. If they do not answer, say you don't remember.",
    ]
    for card in cards:
        people = ", ".join(card.get("people") or []) or "none named"
        era = card.get("era") or "undated"
        lines.append(
            f"- [{card.get('card_id')}] {card.get('title')} ({era}). People: {people}. {card.get('story')}"
        )
    return "\n".join(lines)


async def draft_card(transcript: str, question: str, complete: Complete) -> dict[str, Any]:
    words = " ".join((transcript or "").split())
    if not words:
        raise ValueError("The answer is empty")
    model_text = ""
    try:
        model_text = await complete(
            CARD_SYSTEM,
            f"Question: {question}\n\nAnswer:\n{words}",
        )
    except Exception:
        model_text = ""
    return card_from_model(words, question, model_text)


async def answer_grounded(question: str, cards: list[dict], complete: Complete) -> dict[str, Any]:
    used = select_cards(cards, question)
    if not used:
        return {
            "reply": "I don't have an approved memory about that.",
            "why": [],
        }
    block = grounding_block(used)
    try:
        reply = as_owner_voice(await complete(ANSWER_SYSTEM, f"{block}\n\nQuestion: {question}") or "")
    except Exception:
        reply = ""
    if not reply or _declines(reply):
        return {
            "reply": "I don't have an approved memory about that.",
            "why": [],
        }
    grounded = citations_that_ground(reply, used)
    if not grounded:
        return {
            "reply": "I don't have an approved memory about that.",
            "why": [],
        }
    return {"reply": reply, "why": why_from(grounded)}


def new_prompt_doc(user_id: str, prompt: dict, *, now: Optional[datetime] = None) -> dict[str, Any]:
    moment = _now(now)
    return {
        "prompt_id": prompt.get("prompt_id") or f"prm_{uuid.uuid4().hex[:12]}",
        "user_id": user_id,
        "key": prompt.get("key") or "daily",
        "question": prompt.get("question") or "",
        "status": "unanswered",
        "source": prompt.get("source") or "daily",
        "created_at": moment.isoformat(),
        "answered_at": "",
        "card_id": "",
    }


def new_card_doc(user_id: str, draft: dict, *, prompt_id: str = "", now: Optional[datetime] = None) -> dict[str, Any]:
    moment = _now(now)
    return {
        "card_id": f"card_{uuid.uuid4().hex[:12]}",
        "user_id": user_id,
        "prompt_id": prompt_id,
        "status": "pending",
        "visibility": "owner",
        "title": draft.get("title") or "A memory",
        "era": draft.get("era") or "",
        "people": list(draft.get("people") or []),
        "story": draft.get("story") or "",
        "transcript": draft.get("transcript") or "",
        "question": draft.get("question") or "",
        "created_at": moment.isoformat(),
        "updated_at": moment.isoformat(),
        "approved_at": "",
    }


def approve_fields(card: dict, edits: dict | None = None, *, now: Optional[datetime] = None) -> dict[str, Any]:
    moment = _now(now)
    updated = dict(card)
    for key in ("title", "era", "story", "question"):
        if edits and edits.get(key) is not None:
            updated[key] = " ".join(str(edits.get(key) or "").split())[:4000]
    if edits and edits.get("people") is not None:
        people = edits.get("people")
        if isinstance(people, str):
            people = [part.strip() for part in people.split(",") if part.strip()]
        updated["people"] = [str(name)[:80] for name in (people or [])][:8]
    updated["status"] = "approved"
    updated["visibility"] = "owner"
    updated["approved_at"] = moment.isoformat()
    updated["updated_at"] = moment.isoformat()
    return updated


def entry_from_card(card: dict) -> dict[str, Any]:
    """An approved card is a vault memory. Visibility stays owner-private."""
    people = ", ".join(card.get("people") or [])
    content = str(card.get("story") or "")
    if card.get("era"):
        content = f"{card.get('era')}. {content}"
    if people:
        content = f"People: {people}. {content}"
    return {
        "entry_id": f"ent_{uuid.uuid4().hex[:12]}",
        "user_id": card.get("user_id") or "",
        "type": "memory",
        "title": card.get("title") or "A memory",
        "content": content,
        "tags": ["memory-card", str(card.get("card_id") or "")],
        "source": "memory-card",
        "visibility": "owner",
        "card_id": card.get("card_id") or "",
        "transcript": card.get("transcript") or "",
        "created_at": card.get("approved_at") or card.get("created_at") or "",
        "updated_at": card.get("updated_at") or "",
    }
