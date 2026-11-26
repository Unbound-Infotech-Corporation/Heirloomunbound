"""Keep the twin from inventing the owner's life.

Three checks, all on the box's own Ollama model:

1. ``classify_turn`` decides whether a message asks about the owner's own life.
   The keyword gate in memory_cards stays as a fallback. When the model errors,
   the turn is treated as personal unless it is clearly a task or a greeting.
2. Personal answers are written only from approved cards that match the question
   (``answer_personal``), never from the whole archive or earlier twin replies.
3. ``verify_reply`` checks every personal claim in a draft reply against those
   cards and the owner's own messages. Unsupported sentences are removed. When the
   check itself fails, a heuristic removes anything that looks like a life claim.

Nothing here calls Odysseus, the web, or a cloud model.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

AskModel = Callable[..., Awaitable[str]]

CLASSIFY_TIMEOUT = float(os.environ.get("HEIRLOOM_GROUNDING_CLASSIFY_TIMEOUT", "20") or 20)
VERIFY_TIMEOUT = float(os.environ.get("HEIRLOOM_GROUNDING_VERIFY_TIMEOUT", "30") or 30)
ANSWER_TIMEOUT = float(os.environ.get("HEIRLOOM_GROUNDING_ANSWER_TIMEOUT", "60") or 60)

CLASSIFY_SYSTEM = """You sort one message sent to a memory twin. The twin speaks as its owner.

personal=true when the message asks the twin to state, recall, confirm, or describe anything about the owner's own life:
their past, childhood, parents, grandparents, children, spouse, siblings, relatives, friends, pets, homes, streets, towns,
schools, teachers, jobs, bosses, military service, wedding, honeymoon, trips, holidays, cars, habits, tastes, favorites,
beliefs, health, hardships, lessons someone taught them, or how they felt about events in their life.
Examples that are personal: "What was my mom's name?", "What did Dad teach me?", "Tell me about grandpa.",
"What's my favorite food?", "Do you remember our trip to the lake?", "How did I meet my wife?", "Who was my best friend?",
"What was the hardest year of my life?", "What did we name the dog?".

personal=false for greetings, small talk, general knowledge, advice, how-to, math, planning, writing or drafting help,
reminders, to-dos, or requests to do something, even when they mention family.
Examples that are not personal: "Hi, how are you?", "Help me write a birthday note for my sister.", "How do I cook trout?",
"Plan my week.", "Remind me to call Mom tomorrow.", "My printer won't connect, what should I try?".

Return only JSON: {"personal": true} or {"personal": false}."""

VERIFY_SYSTEM = """You fact-check a reply written by a memory twin. The twin speaks as its owner, so "I", "my", "we", and "our" mean the owner.

EVIDENCE is everything known about the owner's life: approved memory cards and the owner's own messages.
Earlier twin replies are not evidence. General knowledge is not evidence about the owner's life.

For EACH numbered sentence of the REPLY decide two things.
personal_claim: true when the sentence states something about the owner's own life or family: a person, a name, a relative,
a relationship, a pet, a place, a home, a school, a job, a date, an age, a possession, an event, a habit, a taste, a feeling about
something that happened, or a lesson someone taught them. Also true when it names or describes a relative or friend.
personal_claim: false for greetings, thanks, how the twin is feeling right now, offers to help, advice, instructions,
general facts, jokes, questions back to the owner, and sentences saying the twin does not remember or has no memory.
supported: true only when the EVIDENCE states every detail of that sentence. One added name, place, date, number, trait, feeling,
person, or event that the EVIDENCE does not state makes it false. A detail the owner's own message states is supported:
when the owner asks for a note to their sister, greeting or addressing that sister is supported.

Return only JSON in this shape, one entry per sentence:
{"sentences": [{"n": 1, "personal_claim": true, "supported": false}]}"""

PERSONAL_SYSTEM = """You are the digital twin of {name}, an AI built from their approved memories. Speak as them, in the first person (I, my, me).

STRICT MEMORY RULES:
- The APPROVED MEMORIES below are the only facts you know about this life. Nothing else is true for you.
- Answer only with facts written on those cards, in their own wording where you can.
- Do not add names, places, dates, numbers, traits, feelings, reasons, or events that are not written on a card.
- If the cards do not answer the question, say exactly: "{no_memory}"
- Never guess, never fill gaps, never describe what "probably" happened.
- Keep it to one to three short sentences. No padding, no closing questions, no offers.
- Do not promise to remind, save, or do anything later."""

FALSE_PROMISE = re.compile(
    r"(?i)\b(?:i'?ll|i will|i'm going to|let me|i can)\s+(?:make sure to\s+|be sure to\s+|go ahead and\s+)?"
    r"(?:remind you|set (?:a|that|the|up a) reminder|add (?:a|that|it as a) reminder|ping you|nudge you|follow up with you)\b"
    r"|\b(?:i'?ve|i have)\s+(?:set|added|created|scheduled)\s+(?:a|the|that|your)\s+reminder\b"
    r"|\breminder (?:is )?(?:set|added|created|scheduled)\b"
)

_REMINDER = re.compile(
    r"(?i)^\s*(?:hey[, ]+)?(?:please\s+)?(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?)?"
    r"(?:remind me (?:to|about|that)|set (?:a|me a) reminder (?:to|for|about)|add a reminder (?:to|for|about))\s+(?P<rest>.+?)\s*[.!?]*\s*$"
)
_WHEN = re.compile(
    r"(?i)\s*\b(?P<when>(?:tomorrow|tonight|today|this (?:morning|afternoon|evening|weekend)|next \w+|"
    r"on (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|in \d+ (?:minutes?|hours?|days?|weeks?)|"
    r"at \d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?|by \d{1,2}(?::\d{2})?\s*(?:am|pm)?|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w* \d{1,2})"
    r"(?:\s+(?:at|by|around)\s+\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?|\s+(?:morning|afternoon|evening|night))?)\s*$"
)

# Candidate life claims. A sentence without any of these words never needs the model.
_CLAIM_WORDS = re.compile(
    r"(?i)\b(?:i|i'm|i've|i'd|i was|my|me|we|we're|we've|our|us|mom|mother|dad|father|grand\w*|grandpa|grandma|"
    r"wife|husband|son|daughter|brother|sister|aunt|uncle|cousin|family|wedding|married|born|grew|childhood)\b"
)
# Used only when the verifier model fails. Specific life claims, not "I can help".
_STRONG_CLAIM = re.compile(
    r"(?i)\b(?:my|our)\s+(?:\w+\s+){0,3}?(?:mom|mother|mama|dad|father|papa|pop|grand\w*|wife|husband|son|daughter|"
    r"brother|sister|aunt|uncle|cousin|kids?|children|family|friend|dog|cat|pet|house|home|street|town|school|"
    r"teacher|job|boss|wedding|honeymoon|car|truck|trip|name|favorite|childhood|army|navy|unit)\b"
    r"|\b(?:i|we)\s+(?:grew up|was born|were born|used to|met|married|moved|lived|worked|served|went|danced|"
    r"bought|learned|taught|remember|loved|had|spent|played|fished|drove)\b"
    r"|\b(?:mom|dad|mother|father|grandpa|grandma|grandfather|grandmother)\s+(?:was|were|taught|used|loved|had|always|would|said)\b"
    r"|\bnamed\s+[A-Z][a-z]+"
)


@dataclass
class TurnClass:
    personal: bool
    source: str  # model | keyword | fail-closed | task
    ms: int = 0
    error: str = ""


@dataclass
class Verdict:
    text: str
    removed: list[str] = field(default_factory=list)
    source: str = "skip"  # model | skip | fail-closed
    ms: int = 0
    error: str = ""

    @property
    def changed(self) -> bool:
        return bool(self.removed)


async def ask_box_model(
    system: str,
    user: str,
    *,
    json_mode: bool = False,
    num_predict: int = 64,
    temperature: float = 0.0,
    timeout: float = 20.0,
) -> str:
    """One call to the box's own Ollama. Not routed to Odysseus or any other host."""
    import httpx

    from llm_provider import box_keep_alive, ollama_base_url, ollama_model, refuse_cloud

    model = ollama_model(None)
    refuse_cloud("ollama", model, caller="grounding")
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "keep_alive": box_keep_alive(),
        "options": {"temperature": temperature, "num_predict": num_predict},
    }
    if json_mode:
        body["format"] = "json"
    from model_tiers import think_value

    think = think_value(model, ollama_base_url(None))
    if think is not None:
        # A thinking model spends a 16-token budget on its trace and returns nothing.
        body["think"] = think
    url = ollama_base_url(None) + "/api/chat"
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=body)
    if response.status_code >= 400:
        raise RuntimeError(f"Ollama HTTP {response.status_code}: {response.text[:200]}")
    data = response.json()
    text = str(((data or {}).get("message") or {}).get("content") or "").strip()
    if not text:
        raise RuntimeError("Ollama returned empty content")
    return text


def _json_object(text: str) -> dict:
    match = re.search(r"\{[\s\S]*\}", text or "")
    if not match:
        raise ValueError("no JSON object")
    loaded = json.loads(match.group(0))
    if not isinstance(loaded, dict):
        raise ValueError("not an object")
    return loaded


def is_obvious_task(text: str) -> bool:
    """Greetings, reminders, how-to, and requests. These never need a memory."""
    from memory_cards import _HOWTO, _OBLIGATION, _TASK

    raw = " ".join((text or "").split())
    if not raw:
        return True
    if _TASK.match(raw) or _HOWTO.match(raw) or _OBLIGATION.match(raw) or reminder_request(raw):
        return True
    try:
        from brain_council import is_simple_chat

        if is_simple_chat(raw) and not re.search(r"(?i)\b(my|our|we|i)\b", raw):
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


async def classify_turn(text: str, *, ask: Optional[AskModel] = None) -> TurnClass:
    """Personal-memory turn or not. The keyword gate can only add, never remove."""
    from memory_cards import asks_for_personal_memory

    started = time.perf_counter()
    raw = " ".join((text or "").split())
    if asks_for_personal_memory(raw):
        return TurnClass(True, "keyword")
    if is_obvious_task(raw):
        return TurnClass(False, "task")
    caller = ask or ask_box_model
    try:
        answer = await caller(
            CLASSIFY_SYSTEM,
            f"Message: {raw[:600]}",
            json_mode=True,
            num_predict=16,
            timeout=CLASSIFY_TIMEOUT,
        )
        parsed = _json_object(answer)
        value = parsed.get("personal")
        if isinstance(value, str):
            value = value.strip().lower() in {"true", "yes", "1"}
        if not isinstance(value, bool):
            raise ValueError(f"no personal flag in {answer[:80]!r}")
        ms = int((time.perf_counter() - started) * 1000)
        return TurnClass(value, "model", ms=ms)
    except Exception as exc:  # noqa: BLE001
        ms = int((time.perf_counter() - started) * 1000)
        return TurnClass(True, "fail-closed", ms=ms, error=str(exc)[:200])


_ABBREV_END = re.compile(
    r"(?:\b(?:St|Mt|Ft|Mr|Mrs|Ms|Dr|Jr|Sr|Rev|Gen|Col|Capt|Lt|Sgt|Prof|Ave|Blvd|Rd|No|vs|etc|approx|Co|Inc|Bros)\.|\b[A-Z]\.)$"
)


def split_sentences(text: str) -> list[str]:
    rows: list[str] = []
    for block in re.split(r"\n+", (text or "").strip()):
        block = block.strip()
        if not block:
            continue
        held = ""
        for part in re.split(r"(?<=[.!?])[\"')\]]?\s+(?=[\"'(\[]?[A-Z0-9])", block):
            part = part.strip()
            if not part:
                continue
            part = f"{held} {part}" if held else part
            # "a nurse at St. Mary's" is one sentence; checking "Mary's." alone drops the claim's subject.
            if _ABBREV_END.search(part):
                held = part
                continue
            held = ""
            rows.append(part)
        if held:
            rows.append(held)
    return rows


def evidence_text(cards: list[dict], owner_messages: list[str]) -> str:
    lines: list[str] = []
    for card in cards or []:
        people = ", ".join(card.get("people") or [])
        bits = [str(card.get("title") or "").strip(), str(card.get("era") or "").strip()]
        head = " / ".join(bit for bit in bits if bit)
        lines.append(
            f"CARD {head}: {'People: ' + people + '. ' if people else ''}{str(card.get('story') or '').strip()}"
        )
    for said in owner_messages or []:
        said = " ".join(str(said or "").split())
        if said:
            lines.append(f"OWNER SAID: {said[:600]}")
    return "\n".join(lines) or "(no evidence: nothing about the owner's life is known)"


def strip_false_promises(text: str, *, reminder_created: bool = False) -> str:
    """The twin cannot promise a reminder it did not create."""
    if reminder_created:
        return text
    kept = [line for line in split_sentences(text) if not FALSE_PROMISE.search(line)]
    return " ".join(kept).strip()


# Lines that claim nothing about the owner's life: greetings, wishes, sign-offs, offers, thanks.
_HARMLESS = re.compile(
    r"(?i)^[\"'(\s\-*]*(?:"
    r"dear\b|happy (?:birthday|anniversary|holidays|new year|mother's day|father's day|thanksgiving|retirement|graduation)|"
    r"merry christmas|congrat\w*|wishing you|wish you|best wishes|warm(?:est)? wishes|i (?:hope|wish) (?:you|your|this|it)|"
    r"hope (?:you|your)|may (?:this|your|the|you|it)\b|here(?:'s| is)\b|cheers\b|every year\b|"
    r"(?:with (?:all )?(?:my )?|lots of |all my |sending (?:you )?)?love(?: you| ya)?\b|xo+|hugs|"
    r"i (?:love|adore|appreciate|miss) you|i'?m (?:so |incredibly |truly |really )?(?:grateful|lucky|blessed|thankful|proud)|"
    r"i feel (?:so |incredibly |truly |really )?(?:grateful|lucky|blessed|thankful)|"
    r"you'?re (?:(?:a|an|such a|so|truly|simply) )?(?:one of a kind|amazing|wonderful|the best|special|awesome|incredible|loved|"
    r"kind|beautiful|brilliant|inspiring|treasure|gift|light)|"
    r"(?:all the )?best\b|warmly|sincerely|take care|safe travels|see you|talk soon|bye|goodbye|good ?night|"
    r"enjoy\b|have (?:a|an|fun)\b|you(?:'ve| have) got this|proud of you|"
    r"thanks?\b|thank you|you're welcome|hi\b|hello|hey\b|good (?:morning|afternoon|evening)|"
    r"sure\b|of course|absolutely|sounds good|let me know|anything else|how about you|what about you|feel free|"
    r"i'?m (?:glad|happy|sorry|here|doing (?:well|good|great|fine|okay|ok|alright)|hanging in)|i'?d (?:love|be happy|be glad) to"
    r")"
)
# Story words. A wish that tells a story is a claim, not a greeting.
_STORY = re.compile(
    r"(?i)\b(?:taught|grew up|married|met|moved|lived|worked|served|bought|drove|remember\w*|used to|back in|"
    r"years ago|that time|when (?:we|i|you were)|summer|(?:our|that|the|my) (?:\w+ )?(?:trip|vacation)|camp\w*|our first|the day (?:we|you|i))\b"
)
_PLACEHOLDER = re.compile(r"\[[^\]\n]{1,40}\]")


def is_harmless(sentence: str, evidence: str) -> bool:
    """A greeting, wish, or sign-off with no life story and no name the evidence lacks."""
    line = " ".join((sentence or "").split())
    line = line.translate({0x2019: "'", 0x2018: "'", 0x201C: '"', 0x201D: '"'})
    line = _PLACEHOLDER.sub("", line).strip()
    if not re.search(r"[A-Za-z]", line):
        return True  # only a placeholder like [Your Name], or a divider
    if len(line) > 200 or not _HARMLESS.search(line) or _STORY.search(line):
        return False
    folded = (evidence or "").lower()
    for match in _STRONG_CLAIM.finditer(line):
        words = match.group(0).lower().split()
        # "my dear sister" is only an address when the owner named the sister.
        if words[0] not in {"my", "our"} or words[-1] not in folded:
            return False
    # A capital after a break (". ", "--- ", ": ") starts a sentence, not a name.
    for chunk in re.split(r"[.!?:;]+|-{2,}|\u2014", line):
        words = re.findall(r"[A-Za-z][A-Za-z'\-]*", chunk)
        for position, word in enumerate(words):
            clean = word.strip("'").removesuffix("'s")
            if position == 0 or not clean[:1].isupper() or clean.lower() in _COMMON_CAPS:
                continue
            if clean.lower() not in folded:
                return False
    return not re.search(r"\d", line) or not unseen_details(line, evidence)

_COMMON_CAPS = frozenset({
    "i", "i'm", "i've", "i'd", "i'll", "mom", "dad", "mama", "papa", "grandpa", "grandma", "ma", "pa", "sis", "bro",
    "ok", "okay", "yes", "no", "sure", "hi", "hello", "hey", "thanks", "happy", "love", "dear",
})


def unseen_details(sentence: str, evidence: str) -> list[str]:
    """Names and numbers in a life claim that the evidence never mentions."""
    folded = (evidence or "").lower()
    found: list[str] = []
    words = re.findall(r"[A-Za-z][A-Za-z'\-]*|\$?\d[\d,.:]*", sentence or "")
    for position, word in enumerate(words):
        clean = word.strip("'.,").rstrip("s").rstrip("'") if word[:1].isalpha() else word.strip(".,")
        if not clean:
            continue
        if word[:1].isdigit() or word[:1] == "$":
            digits = clean.lstrip("$")
            if digits and digits not in folded:
                found.append(word)
            continue
        if position == 0 or not word[:1].isupper():
            continue
        if word.lower() in _COMMON_CAPS or clean.lower() in _COMMON_CAPS:
            continue
        if clean.lower() not in folded and word.lower() not in folded:
            found.append(word)
    return found


def _rows(parsed: dict) -> list[dict]:
    rows = parsed.get("sentences")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    return []


def _flag(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
    return None


def _claims_from(parsed: dict) -> set[int]:
    claims: set[int] = set()
    for row in _rows(parsed):
        try:
            number = int(str(row.get("n")).strip())
        except (TypeError, ValueError):
            continue
        if _flag(row.get("personal_claim")):
            claims.add(number)
    return claims


def _unsupported_from(parsed: dict, count: int) -> set[int]:
    """Sentence numbers that make a life claim the evidence does not support.

    A missing or unreadable row for a sentence counts as unsupported only when it is a strong life claim;
    an unreadable answer raises so the caller fails closed.
    """
    rows = _rows(parsed)
    if not rows and "unsupported" in parsed:
        raw = parsed.get("unsupported")
        out: set[int] = set()
        for item in raw if isinstance(raw, list) else [raw]:
            try:
                out.add(int(str(item).strip().rstrip(".")))
            except ValueError:
                continue
        return out
    if not rows:
        raise ValueError("no sentence verdicts")
    bad: set[int] = set()
    seen: set[int] = set()
    for row in rows:
        try:
            number = int(str(row.get("n")).strip())
        except (TypeError, ValueError):
            continue
        seen.add(number)
        claim = _flag(row.get("personal_claim"))
        supported = _flag(row.get("supported"))
        if claim and supported is not True:
            bad.add(number)
    if not seen & set(range(1, count + 1)):
        raise ValueError("no verdict matched a sentence")
    # A sentence the model skipped is unchecked. Judge it by the strict heuristic.
    for number in range(1, count + 1):
        if number not in seen:
            bad.add(-number)
    return bad


def _heuristic_strip(sentences: list[str]) -> tuple[list[str], list[str]]:
    kept: list[str] = []
    removed: list[str] = []
    for line in sentences:
        if _STRONG_CLAIM.search(line):
            removed.append(line)
        else:
            kept.append(line)
    return kept, removed


async def verify_reply(
    reply: str,
    *,
    cards: list[dict],
    owner_messages: list[str],
    ask: Optional[AskModel] = None,
) -> Verdict:
    """Remove every personal claim that the cards and the owner's own words do not state."""
    started = time.perf_counter()
    sentences = split_sentences(reply)
    if not sentences:
        return Verdict(text="", source="skip")
    if not any(_CLAIM_WORDS.search(line) for line in sentences):
        return Verdict(text=" ".join(sentences), source="skip")
    numbered = "\n".join(f"{index}. {line}" for index, line in enumerate(sentences, 1))
    evidence = evidence_text(cards, owner_messages)
    prompt = f"EVIDENCE:\n{evidence}\n\nREPLY:\n{numbered}"
    caller = ask or ask_box_model
    try:
        answer = await caller(
            VERIFY_SYSTEM,
            prompt,
            json_mode=True,
            num_predict=24 + 24 * len(sentences),
            timeout=VERIFY_TIMEOUT,
        )
        parsed = _json_object(answer)
        flagged = _unsupported_from(parsed, len(sentences))
        bad = {number for number in flagged if number > 0}
        for index, line in enumerate(sentences, 1):
            if -index in flagged and _STRONG_CLAIM.search(line):
                bad.add(index)
            if index in bad:
                continue
            claimed = index in _claims_from(parsed) or bool(_STRONG_CLAIM.search(line))
            if claimed and unseen_details(line, evidence):
                bad.add(index)
        # A greeting or wish is never a life claim, even when the model flags it.
        bad = {
            index for index in bad
            if 1 <= index <= len(sentences) and not is_harmless(sentences[index - 1], evidence)
        }
        kept = [line for index, line in enumerate(sentences, 1) if index not in bad]
        removed = [line for index, line in enumerate(sentences, 1) if index in bad]
        ms = int((time.perf_counter() - started) * 1000)
        return Verdict(text=" ".join(kept).strip(), removed=removed, source="model", ms=ms)
    except Exception as exc:  # noqa: BLE001
        kept, removed = _heuristic_strip(sentences)
        ms = int((time.perf_counter() - started) * 1000)
        return Verdict(text=" ".join(kept).strip(), removed=removed, source="fail-closed", ms=ms, error=str(exc)[:200])


def card_quote(cards: list[dict]) -> str:
    """The owner's own words from the best card. Used when the model cannot be checked."""
    for card in cards or []:
        story = " ".join(str(card.get("story") or "").split())
        if story:
            return story
    return ""


async def answer_personal(
    question: str,
    *,
    cards: list[dict],
    owner_messages: list[str],
    name: str = "",
    ask: Optional[AskModel] = None,
) -> dict[str, Any]:
    """A personal answer from relevant approved cards only, then verified.

    Returns reply, cited cards, and a short trace for the lab log.
    """
    from memory_cards import NO_MEMORY_YET, _declines, as_owner_voice, citations_that_ground, grounding_block

    if not cards:
        return {"reply": NO_MEMORY_YET, "cited": [], "trace": {"path": "no-card"}}
    caller = ask or ask_box_model
    system = PERSONAL_SYSTEM.format(name=(name or "the owner").strip() or "the owner", no_memory=NO_MEMORY_YET)
    earlier = [line for line in owner_messages[:-1] if line] if owner_messages else []
    context = ""
    if earlier:
        context = "\n\nTHE OWNER SAID EARLIER IN THIS CHAT:\n" + "\n".join(f"- {line[:300]}" for line in earlier[-6:])
    prompt = f"{grounding_block(cards)}{context}\n\nQuestion: {question}"
    trace: dict[str, Any] = {"path": "cards"}
    try:
        draft = await caller(system, prompt, json_mode=False, num_predict=160, temperature=0.2, timeout=ANSWER_TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        trace["answer_error"] = str(exc)[:200]
        draft = ""
    draft = as_owner_voice(draft)
    draft = strip_false_promises(draft)
    if not draft or _declines(draft):
        return {"reply": NO_MEMORY_YET, "cited": [], "trace": {**trace, "path": "declined"}}
    verdict = await verify_reply(draft, cards=cards, owner_messages=owner_messages, ask=ask)
    trace.update({"verify": verdict.source, "removed": len(verdict.removed), "verify_ms": verdict.ms})
    final = verdict.text
    if verdict.source == "fail-closed":
        quoted = card_quote(cards)
        final = f"Here's what I have written down: {quoted}" if quoted else ""
    if not final or _declines(final):
        return {"reply": NO_MEMORY_YET, "cited": [], "trace": trace}
    cited = citations_that_ground(final, cards)
    if not cited:
        return {"reply": NO_MEMORY_YET, "cited": [], "trace": {**trace, "path": "uncited"}}
    return {"reply": final, "cited": cited, "trace": trace}


def reminder_request(text: str) -> Optional[dict[str, str]]:
    """'Remind me to call the dentist tomorrow at 9am' -> what and when."""
    match = _REMINDER.match(" ".join((text or "").split()))
    if not match:
        return None
    rest = match.group("rest").strip()
    when = ""
    found = _WHEN.search(rest)
    if found:
        when = found.group("when").strip()
        rest = rest[: found.start()].strip(" ,")
    rest = re.sub(r"(?i)\s+(?:for me|please)$", "", rest).strip(" ,.")
    if not rest:
        return None
    return {"what": rest, "when": when}


def resolve_reminder_due(
    text: str,
    when: str,
    user: dict | None,
    now: Optional[datetime] = None,
    *,
    requested_tz: Optional[str] = None,
) -> Optional[str]:
    """The owner's wall clock. 'tomorrow at 9am' is 9am where the owner lives.

    The zone is the one the browser sent, then the owner's saved zone, then HEIRLOOM_TIMEZONE, then UTC.
    """
    from capture_text import owner_timezone, resolve_due_at

    moment = now or datetime.now(timezone.utc)
    tz_name = owner_timezone(user, requested_tz)
    raw_due = None
    if when:
        try:
            import dateparser

            parsed = dateparser.parse(
                when,
                settings={
                    "PREFER_DATES_FROM": "future",
                    "TIMEZONE": tz_name,
                    "RETURN_AS_TIMEZONE_AWARE": True,
                    "RELATIVE_BASE": moment.astimezone(timezone.utc).replace(tzinfo=None),
                },
            )
            if parsed is not None:
                raw_due = parsed.isoformat()
        except Exception:  # noqa: BLE001
            raw_due = None
    try:
        return resolve_due_at(when or text, raw_due, tz_name, moment)
    except Exception:  # noqa: BLE001
        return raw_due


def reminder_reply(what: str, due_iso: Optional[str], user: dict | None, *, requested_tz: Optional[str] = None) -> str:
    if not due_iso:
        return f"Done. I saved a reminder to {what}. It has no time yet, so it's waiting on your Reminders list."
    try:
        from zoneinfo import ZoneInfo

        from capture_text import owner_timezone

        zone = ZoneInfo(owner_timezone(user, requested_tz))
        local = datetime.fromisoformat(due_iso).astimezone(zone)
        label = local.strftime("%a %b %d at %I:%M %p").replace(" 0", " ") + f" {local.tzname()}"
    except Exception:  # noqa: BLE001
        label = due_iso
    return f"Done. I saved a reminder to {what} for {label}. It's on your Reminders list."


async def remember_timezone(user: dict | None, requested: Optional[str]) -> Optional[str]:
    """Save the owner's last known IANA zone, so a later turn without one still uses it."""
    from capture_text import _valid_zone

    zone = _valid_zone(str(requested or ""))
    if not zone or not isinstance(user, dict) or not user.get("user_id"):
        return None
    if user.get("last_timezone") != zone:
        try:
            from deps import db

            await db.users.update_one({"user_id": user["user_id"]}, {"$set": {"last_timezone": zone}})
        except Exception:  # noqa: BLE001
            pass
        user["last_timezone"] = zone
    return zone


HEIR_NO_MEMORY = "I don't have that memory yet."


class TwinGuard:
    """The web chat's grounding, for twin turns that run through twin_runtime.

    Desktop, Companion, and Assist live turns call short_circuit() first. It makes a
    reminder or answers a life question from approved cards only. Any other reply
    goes through check(), which removes life claims the cards and owner never made.
    """

    def __init__(
        self,
        user: dict,
        text: str,
        *,
        conversation: dict | None = None,
        audience: str = "owner",
        timezone: Optional[str] = None,
        ask: Optional[AskModel] = None,
    ) -> None:
        self.user = user or {}
        self.text = text
        self.audience = (audience or "owner").strip().lower() or "owner"
        self.requested_tz = timezone
        self.ask = ask
        self.cards: list[dict] = []
        self.meta: dict[str, Any] = {}
        prior = [
            str(m.get("content") or "")
            for m in (conversation or {}).get("messages") or []
            if m.get("role") == "user" and m.get("content")
        ]
        # Only the owner's own words are evidence about the owner's life. An heir or caller
        # asking "you met her at a party, right?" must not turn that guess into a memory.
        self.owner_messages = prior + [text] if self.owner else []

    @property
    def owner(self) -> bool:
        return self.audience == "owner"

    def no_memory(self) -> str:
        from memory_cards import NO_MEMORY_YET

        return NO_MEMORY_YET if self.owner else HEIR_NO_MEMORY

    def history(self, messages: list[dict]) -> list[dict]:
        """Uncited twin lines are not memories. They never ground a new claim."""
        from memory_cards import history_without_invented_claims

        return history_without_invented_claims(messages)

    async def _load_cards(self) -> None:
        try:
            from routers.memory_loop import grounding_for_turn

            _block, self.cards = await grounding_for_turn(
                str(self.user.get("user_id") or ""),
                self.text,
                audience=self.audience,
                heir_surface=not self.owner,
            )
        except Exception:  # noqa: BLE001
            self.cards = []

    async def _reminder(self) -> Optional[dict[str, Any]]:
        asked = reminder_request(self.text)
        if not asked:
            return None
        from twin_tools import exec_set_reminder

        due = resolve_reminder_due(self.text, asked["when"], self.user, requested_tz=self.requested_tz)
        made = await exec_set_reminder(
            str(self.user.get("user_id") or ""),
            {"what": asked["what"], "when": due or ""},
        )
        ui = made.get("ui") or {}
        created = bool(ui.get("created"))
        reply = (
            reminder_reply(asked["what"], due, self.user, requested_tz=self.requested_tz)
            if created
            else "I couldn't save that reminder. Add it on the Reminders page so it isn't lost."
        )
        return {
            "reply": reply,
            "backend": "reminder",
            "action": {
                "kind": "reminder",
                "reminder_id": ui.get("reminder_id") or "",
                "text": asked["what"],
                "due_at": due,
                "created": created,
            },
            "meta": {"grounding": {"path": "reminder"}},
        }

    async def short_circuit(self) -> Optional[dict[str, Any]]:
        if self.owner:
            await remember_timezone(self.user, self.requested_tz)
            made = await self._reminder()
            if made:
                return made
        await self._load_cards()
        if getattr(self, "tool_names", None):
            # The owner asked for a tool (calendar, mail, weather...). Not a life question.
            self.meta = {"personal": False, "classifier": "tools"}
            return None
        turn = await classify_turn(self.text, ask=self.ask)
        self.meta = {"personal": turn.personal, "classifier": turn.source, "classifier_ms": turn.ms}
        if not turn.personal:
            return None
        answered = await answer_personal(
            self.text,
            cards=self.cards,
            owner_messages=self.owner_messages,
            name=str(self.user.get("name") or ""),
            ask=self.ask,
        )
        cited = answered.get("cited") or []
        self.meta.update(answered.get("trace") or {})
        reply = answered["reply"] if cited else self.no_memory()
        return {
            "reply": reply,
            "backend": "memory" if cited else "no-memory",
            "why": cited,
            "meta": {"grounded": bool(cited), "grounding": self.meta},
        }

    async def check(self, raw: str, evidence: Optional[list[str]] = None) -> tuple[str, list[dict]]:
        """``evidence`` is what a tool returned this turn; repeating it is not an invented claim."""
        from memory_cards import citations_that_ground

        draft = strip_false_promises(raw or "") or (raw or "")
        verdict = await verify_reply(
            draft, cards=self.cards, owner_messages=self.owner_messages + list(evidence or []), ask=self.ask
        )
        self.meta.update({"verify": verdict.source, "removed": len(verdict.removed), "verify_ms": verdict.ms})
        final = verdict.text or self.no_memory()
        return final, citations_that_ground(final, self.cards)
