"""One interview answer becomes a memory card the twin can use after approval.

Local models only. Pending cards and observer notes are not answers.
Owner-private cards stay on the box; this module does not call Odysseus.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import OrderedDict
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from standing_routines import GAP_PROMPTS

EMBED_MODEL = "nomic-embed-text"
EMBED_FLOOR = 0.60
EMBED_MARGIN = 0.05
NO_MEMORY_YET = "I don't have that memory yet. Record it, and I'll keep it."
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
    "Stay close to the card's facts and wording. "
    "Do not add traits, feelings, places, names, dates, or events that are not written on the card. "
    "Answer in one to three short sentences. No padding, no closing questions, no offers. "
    "If they do not answer the question, say you don't remember. Do not invent a life."
)

FIRST_PERSON = (
    "You are the owner. Speak in the first person: I, my, me. "
    "Never say 'your first car' or 'you' about this life. "
    "Do not print tool calls. The archive is already in this prompt.\n"
    "HARD RULE: You know nothing about this life except what is written in the approved memories and the owner's own "
    "messages above. Never state a name, relative, place, date, job, pet, event, habit, taste, or feeling from this life "
    "unless it is written there. If asked about something that is not written there, say: "
    "\"I don't have that memory yet. Record it, and I'll keep it.\" "
    "You cannot set reminders or do anything later from this chat, so never promise to."
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


def embed_query(text: str) -> str:
    """nomic-embed-text query prefix. The document prefix is the other half of the pair."""
    body = " ".join((text or "").split())
    return f"search_query: {body}" if body else ""


def embed_document(text: str) -> str:
    body = " ".join((text or "").split())
    return f"search_document: {body}" if body else ""


_LIFE = (
    r"car|cars|dog|dad|father|mom|mother|childhood|grew up|grow up|named|"
    r"drive|drove|driven|family|brother|sister|wife|husband|son|daughter|born|"
    r"wedding|hometown|job"
)
# "we" only counts beside a past-life word. "Can we drive" is a request.
_PAST = r"childhood|grew up|grow up|born|wedding|hometown|first job|drove|driven"
_PERSONAL_MEMORY = re.compile(
    rf"(?i)\b(?:my|our|i)\b[\s\S]{{0,64}}\b(?:{_LIFE})\b"
    rf"|\b(?:{_LIFE})\b[\s\S]{{0,64}}\b(?:my|our|i)\b"
    rf"|\bwe\b[\s\S]{{0,64}}\b(?:{_PAST})\b"
    rf"|\b(?:{_PAST})\b[\s\S]{{0,64}}\bwe\b"
)


# A task keeps its verb after an optional "can you". A recall question does not.
_TASK = re.compile(
    r"(?i)^(?:please\s+)?(?:(?:can|could|would)\s+you\s+(?:please\s+)?)?"
    r"(?:remind me to|remember to|recall to|set a reminder|"
    r"help me(?!\s+(?:remember|recall))|plan my)\b"
)
_HOWTO = re.compile(
    r"(?i)^(?:please\s+)?(?:(?:can|could|would)\s+you\s+(?:please\s+)?)?"
    r"how\s+(?:do|can|should|would|could)\b"
    r"(?!\s+(?:i|we)\s+(?:remember|recall)(?!\s+to)\b)"
)
_OBLIGATION = re.compile(
    r"(?i)^(?:please\s+)?(?:(?:can|could|would)\s+you\s+(?:please\s+)?)?"
    r"(?:remember|recall)\b.*\b(?:needs|need to|has to|have to|gotta|must|should)\b"
)
_RECALL = re.compile(
    r"(?i)^(?:please\s+)?"
    r"(?:(?:can|could|would)\s+you\s+(?:please\s+)?)?"
    r"(?:help me\s+(?:remember|recall)\b|remember|recall|"
    r"what|who|where|when|which|how|did|was|were|do|does|is|are|"
    r"tell me|describe|do you|remind me (?:about|what|who|of))\b"
)


def asks_for_personal_memory(text: str) -> bool:
    """A recall question about the owner's own life.

    "Tell me about my first car", "did I have a dog", and "can you tell me
    about my first car?" count, with or without a question mark.
    "Remind me to feed my dog" and "can you help me with my car?" do not.
    """
    raw = " ".join((text or "").split())
    if not raw or _TASK.match(raw) or _HOWTO.match(raw) or _OBLIGATION.match(raw):
        return False
    if not _RECALL.match(raw):
        return False
    return bool(_PERSONAL_MEMORY.search(raw))


def history_without_invented_claims(messages: list[dict]) -> list[dict]:
    """Keep the owner's lines. An assistant line counts only with a card citation."""
    kept: list[dict] = []
    for message in messages or []:
        role = message.get("role")
        content = message.get("content")
        if role not in {"user", "assistant"} or not content:
            continue
        if role == "assistant" and not message.get("why"):
            continue
        kept.append({"role": role, "content": content})
    return kept


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


def should_embed(cards: list[dict], query: str) -> bool:
    """Ask Ollama when no approved card already contains every content word.

    A single shared word is not enough to skip paraphrase search.
    """
    approved = [card for card in cards or [] if str(card.get("status") or "") == "approved"]
    if not approved:
        return False
    best = max(_score_card(card, query) for card in approved)
    return best < 1.0


def blend_score(keyword: float, cosine: float | None, *, best_cosine: float | None = None) -> float:
    """Keywords stay in charge of exact words.

    An embedding counts when it clears the floor and stays within a small margin of the
    best card. A weak score, such as a car card beside a dog question, stays at the keyword score.
    """
    if cosine is None or best_cosine is None:
        return keyword
    if cosine < EMBED_FLOOR or cosine < best_cosine - EMBED_MARGIN:
        return keyword
    return max(keyword, cosine)


# Words that say nothing about which memory is meant. "first job" must not match "first car".
_GENERIC = frozenset({
    "first", "last", "favorite", "favourite", "remember", "recall", "tell", "ever", "used", "like",
    "really", "thing", "things", "something", "time", "times", "back", "still", "also", "can", "could",
    "would", "should", "will", "just", "more", "most", "much", "very", "some", "any", "all", "one",
    "got", "get", "know", "think", "mine", "yours", "life", "day", "days", "please", "describe",
})


def _content_tokens(text: str) -> set[str]:
    return {token for token in _tokens(text) if token not in _GENERIC}


def _score_card(card: dict, query: str) -> float:
    hay = " ".join([
        str(card.get("title") or ""),
        str(card.get("era") or ""),
        " ".join(card.get("people") or []),
        str(card.get("story") or ""),
        str(card.get("question") or ""),
    ])
    query_tokens = _content_tokens(query)
    if not query_tokens:
        return 0.0
    hay_tokens = _content_tokens(hay)
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
    pending: list[tuple[float, float | None, dict]] = []
    known = vectors or {}
    for card in cards or []:
        if str(card.get("status") or "") != "approved":
            continue
        keyword = _score_card(card, query)
        cosine = _cosine(query_vector, known.get(str(card.get("card_id") or "")))
        pending.append((keyword, cosine, card))
    cosines = [cosine for _keyword, cosine, _card in pending if cosine is not None]
    best_cosine = max(cosines) if cosines else None
    ranked: list[tuple[float, dict]] = []
    for keyword, cosine, card in pending:
        score = blend_score(keyword, cosine, best_cosine=best_cosine)
        if score <= 0:
            continue
        ranked.append((score, card))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [card for _score, card in ranked[:limit]]


_DECLINE = (
    "don't remember",
    "do not remember",
    "don't have an approved memory",
    "don't have that memory yet",
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

    spoken = re.sub(r"(^|[.!?]\s+)([Yy]our)\b", _own, raw)
    spoken = re.sub(r"\byou were thinking of\b", "I remember", spoken, flags=re.IGNORECASE)
    spoken = re.sub(r"\byou're thinking of\b", "I remember", spoken, flags=re.IGNORECASE)
    spoken = re.sub(r"\bwere you\b", "was I", spoken, flags=re.IGNORECASE)
    return spoken


def cards_reached_through_archive(archive: str, cards: list[dict], question: str = "") -> list[dict]:
    """Approved cards whose vault copy is in the archive and matches this question.

    A recent card that merely sits in the archive blob is not grounding.
    """
    text = archive or ""
    folded = text.lower()
    found: list[dict] = []
    for card in cards or []:
        if str(card.get("status") or "") != "approved":
            continue
        if not question or _score_card(card, question) <= 0:
            continue
        card_id = str(card.get("card_id") or "")
        title = str(card.get("title") or "").strip()
        story = str(card.get("story") or "").strip()
        if card_id and f"card={card_id}" in text:
            found.append(card)
            continue
        if title and len(title) > 2 and title.lower() in folded:
            found.append(card)
            continue
        if story and len(story) > 24 and story[:80].lower() in folded:
            found.append(card)
    return found


def merge_cards(primary: list[dict], extra: list[dict]) -> list[dict]:
    seen: set[str] = set()
    rows: list[dict] = []
    for card in [*(primary or []), *(extra or [])]:
        card_id = str(card.get("card_id") or "")
        if card_id and card_id in seen:
            continue
        if card_id:
            seen.add(card_id)
        rows.append(card)
    return rows


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
            "era": str(card.get("era") or ""),
            "people": [str(name) for name in (card.get("people") or [])][:8],
        })
    return rows


def grounding_block(cards: list[dict]) -> str:
    if not cards:
        return ""
    lines = [
        "APPROVED MEMORIES. Stay close to these facts and this wording. "
        "Do not add traits, feelings, places, or events that are not written on the card. "
        "If these cards do not answer the question, say you don't remember.",
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


_VECTORS: "OrderedDict[str, list[float]]" = OrderedDict()
_VECTOR_CAP = 4000


def _vector_key(doc: str) -> str:
    return hashlib.sha1(f"{EMBED_MODEL}\n{doc}".encode("utf-8")).hexdigest()


def _remember_vector(doc: str, vector: list[float]) -> None:
    key = _vector_key(doc)
    _VECTORS[key] = vector
    _VECTORS.move_to_end(key)
    while len(_VECTORS) > _VECTOR_CAP:
        _VECTORS.popitem(last=False)


async def recall_cards(question: str, cards: list[dict]) -> list[dict]:
    """Keyword hits, then local embeddings when the keyword match is incomplete."""
    keyword_hits = select_cards(cards, question)
    if not should_embed(cards, question):
        return keyword_hits
    try:
        from local_inference import embed_timeout, ollama_embed_many
    except Exception:
        return keyword_hits
    approved = [card for card in cards or [] if str(card.get("status") or "") == "approved"]
    docs = [embed_document(card_embed_text(card)) for card in approved]
    vectors: dict[str, list[float]] = {}
    missing: list[int] = []
    for i, (card, doc) in enumerate(zip(approved, docs)):
        cached = _VECTORS.get(_vector_key(doc))
        if cached is not None:
            vectors[str(card.get("card_id") or "")] = cached
        else:
            missing.append(i)
    # A life-story interview makes a hundred cards; only new or edited ones are embedded again.
    embedded = await ollama_embed_many([embed_query(question), *[docs[i] for i in missing]], timeout=embed_timeout())
    if not embedded:
        return keyword_hits
    for i, vector in zip(missing, embedded[1:]):
        _remember_vector(docs[i], vector)
        vectors[str(approved[i].get("card_id") or "")] = vector
    return select_cards(cards, question, vectors=vectors, query_vector=embedded[0])


async def answer_grounded(
    question: str,
    cards: list[dict],
    complete: Complete,
    *,
    verify: Optional[Callable[..., Awaitable[Any]]] = None,
) -> dict[str, Any]:
    """The Ask page. Relevant approved cards only, then every claim is checked when ``verify`` is given."""
    used = await recall_cards(question, cards)
    if not used:
        return {"reply": NO_MEMORY_YET, "why": []}
    block = grounding_block(used)
    try:
        reply = as_owner_voice(await complete(ANSWER_SYSTEM, f"{block}\n\nQuestion: {question}") or "")
    except Exception:
        reply = ""
    if not reply or _declines(reply):
        return {"reply": NO_MEMORY_YET, "why": []}
    if verify is not None:
        verdict = await verify(reply, cards=used, owner_messages=[question])
        if getattr(verdict, "source", "") == "fail-closed":
            story = " ".join(str(used[0].get("story") or "").split())
            reply = f"Here's what I have written down: {story}" if story else ""
        else:
            reply = getattr(verdict, "text", "") or ""
        if not reply or _declines(reply):
            return {"reply": NO_MEMORY_YET, "why": []}
    grounded = citations_that_ground(reply, used)
    if not grounded:
        return {"reply": NO_MEMORY_YET, "why": []}
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


def approve_fields(card: dict, edits: dict | None = None, *, now: Optional[datetime] = None,
                   share_new: bool = False) -> dict[str, Any]:
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
    if str(card.get("status") or "") == "approved":
        # Editing or re-approving a memory never changes who can hear it.
        updated["visibility"] = card.get("visibility") or "owner"
        updated["heir_ids"] = list(card.get("heir_ids") or [])
    elif share_new:
        # The owner's "share new approved cards with all heirs" setting (off by default).
        updated["visibility"], updated["heir_ids"] = "family", []
    else:
        updated["visibility"], updated["heir_ids"] = "owner", []
    updated["status"] = "approved"
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
