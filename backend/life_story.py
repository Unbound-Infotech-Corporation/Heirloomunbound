"""Guided life-story interview and memory imports. Everything becomes a *pending* card.

A buyer sits down for 30 to 60 minutes, by voice or typing, and answers questions
chapter by chapter. Each answer is drafted into a memory card by the local model
(``memory_cards.draft_card``, which falls back to the owner's own words when the
model invents). Photos with captions, letters and documents, and exported chats
become pending cards the same way. Nothing reaches the twin until the owner
approves a card; approved cards are what grounding reads.

Local model only. Pure logic lives here so it can be tested without Mongo.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Iterable, Optional

from memory_cards import _tokens, approve_fields, card_from_model, draft_card, entry_from_card, new_card_doc

log = logging.getLogger(__name__)

Complete = Callable[[str, str], Awaitable[str]]

MINUTES_PER_ANSWER = 1.25
MAX_FOLLOWUPS = 12
MIN_CONTENT_WORDS = 3

# (key, title, questions). The first two questions of each chapter make the short interview.
CHAPTERS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("roots", "Where you come from", (
        "Where and when were you born, and who was in the house when you were small?",
        "Describe the home you grew up in. What room do you remember best, and why?",
        "What did your family do on an ordinary weekend?",
        "What was a smell, sound, or food that still takes you back to childhood?",
    )),
    ("family", "Your parents and family", (
        "Tell me about your mother, or whoever raised you. What was she like on a good day?",
        "Tell me about your father, or the other person who raised you. What did he teach you without saying it?",
        "Who else in the family mattered to you growing up? Grandparents, brothers, sisters, cousins?",
        "Is there a family story that always got told at gatherings? Tell it the way it was told.",
    )),
    ("school", "School and growing up", (
        "What was school like for you? Was there a teacher you still remember?",
        "Who was your best friend as a kid, and what did you two get up to?",
        "What did you want to be when you grew up, and how did that change?",
        "Tell me about a time you got in trouble, and what happened after.",
    )),
    ("young", "Leaving home", (
        "When did you first live on your own, and what was that place like?",
        "What was your first real job? What did it pay, and what did you learn there?",
        "What was your first car, or how did you get around back then?",
        "What music, places, or friends filled your twenties?",
    )),
    ("work", "Work and calling", (
        "What work have you done most of your life, and how did you end up in it?",
        "What is something you were proud of building, fixing, or finishing?",
        "Who was the best boss or mentor you ever had, and what did they do right?",
        "What was the hardest stretch at work, and how did you get through it?",
    )),
    ("love", "Love and partnership", (
        "How did you meet the people you loved most? Start with the one who matters most to tell about.",
        "What did a good day together look like?",
        "What have you learned about making love last, or about letting it go?",
    )),
    ("children", "Children and the people you raised", (
        "If you have children or people you helped raise, tell me about the day each one came into your life.",
        "What do you hope they remember about growing up with you?",
        "What is a funny or tender moment with them that nobody else would know?",
    )),
    ("hard", "Hard times", (
        "What is the hardest thing you have lived through?",
        "Who or what helped you through it?",
        "Is there anything you would do differently, if you could?",
    )),
    ("joy", "Joys, habits, and taste", (
        "What do you do when you have a free afternoon?",
        "What are your favorite foods, songs, places, or sayings?",
        "Is there a recipe, a trick, or a skill you would want someone to learn from you?",
    )),
    ("beliefs", "What you believe", (
        "What do you believe about how to treat people?",
        "What role has faith, or the lack of it, played in your life?",
        "What is something you changed your mind about as you got older?",
    )),
    ("legacy", "For the people after you", (
        "What do you want your family to know about you that they might not?",
        "What advice would you give a grandchild on their eighteenth birthday?",
        "How do you want to be remembered?",
    )),
)

FOLLOWUP_SYSTEM = (
    "You are a gentle biographer. Read the person's answer and ask ONE short follow-up question "
    "about something they actually said, to draw out a specific detail (a name, a place, a moment). "
    "Use only names and things from their answer. Never ask for a detail they already gave. "
    "Do not add facts. Do not comment. "
    "Return only the question. If the answer is too short or painful to press on, return NONE."
)


def plan(length: str = "full") -> list[dict[str, str]]:
    """The question queue. 'short' is about 30 minutes; 'full' about 45 to 60."""
    take = 2 if length == "short" else 99
    rows: list[dict[str, str]] = []
    for key, title, questions in CHAPTERS:
        for i, question in enumerate(questions[:take]):
            rows.append({"qid": f"{key}.{i + 1}", "chapter": key, "chapter_title": title, "question": question, "kind": "core"})
    return rows


def estimate_minutes(count: int) -> int:
    return int(round(count * MINUTES_PER_ANSWER))


def new_session(user_id: str, length: str = "full", *, now: Optional[datetime] = None) -> dict[str, Any]:
    moment = (now or datetime.now(timezone.utc)).isoformat()
    length = "short" if length == "short" else "full"
    return {
        "interview_id": f"liv_{uuid.uuid4().hex[:12]}",
        "user_id": user_id,
        "length": length,
        "status": "active",
        "queue": plan(length),
        "done": {},  # qid -> {"status": answered|skipped|too_short, "card_id": ...}
        "followups": 0,
        "started_at": moment,
        "updated_at": moment,
    }


def current_item(session: dict) -> Optional[dict]:
    done = session.get("done") or {}
    for item in session.get("queue") or []:
        if item["qid"] not in done:
            return item
    return None


def progress(session: dict) -> dict[str, Any]:
    queue = session.get("queue") or []
    done = session.get("done") or {}
    answered = sum(1 for v in done.values() if v.get("status") == "answered")
    left = sum(1 for item in queue if item["qid"] not in done)
    chapters = []
    for key, title, _ in CHAPTERS:
        items = [item for item in queue if item["chapter"] == key]
        if not items:
            continue
        chapters.append({
            "key": key,
            "title": title,
            "total": len(items),
            "done": sum(1 for item in items if item["qid"] in done),
        })
    return {
        "answered": answered,
        "remaining": left,
        "total": len(queue),
        "minutes_left": estimate_minutes(left),
        "chapters": chapters,
    }


def mark(session: dict, qid: str, status: str, card_id: str = "", *, now: Optional[datetime] = None) -> dict:
    done = dict(session.get("done") or {})
    done[qid] = {"status": status, "card_id": card_id}
    session["done"] = done
    session["updated_at"] = (now or datetime.now(timezone.utc)).isoformat()
    if current_item(session) is None:
        session["status"] = "finished"
    return session


def skip_chapter(session: dict, chapter: str) -> dict:
    for item in session.get("queue") or []:
        if item["chapter"] == chapter and item["qid"] not in (session.get("done") or {}):
            mark(session, item["qid"], "skipped")
    return session


def substantial(answer: str) -> bool:
    return len(_tokens(answer or "")) >= MIN_CONTENT_WORDS


_CAP_WORD = re.compile(r"\b[A-Z][a-z]{2,}\b")
_COMMON_CAPS = frozenset({
    "What", "Who", "Where", "When", "Why", "How", "Did", "Do", "Does", "Was", "Were", "Is", "Are",
    "Can", "Could", "Would", "Tell", "You", "Your", "The", "And", "That", "This", "Have", "Had",
    "Which", "Any", "Anything", "Something", "Describe", "Remember",
})


def followup_from_model(answer: str, model_text: str) -> Optional[str]:
    """Keep the follow-up only if it is one short question about what they actually said."""
    text = " ".join((model_text or "").strip().strip('"').split())
    if not text or text.upper().startswith("NONE"):
        return None
    if "?" not in text:
        return None
    text = text[: text.index("?") + 1]
    if len(text) > 220 or len(text) < 12:
        return None
    if not (_tokens(text) & _tokens(answer)):
        return None
    answer_lower = (answer or "").lower()
    for name in _CAP_WORD.findall(text):
        if name in _COMMON_CAPS:
            continue
        if name.lower() not in answer_lower:
            return None  # a name or place they never said
    return text


def add_followup(session: dict, after_qid: str, question: str) -> Optional[dict]:
    if int(session.get("followups") or 0) >= MAX_FOLLOWUPS:
        return None
    queue = list(session.get("queue") or [])
    idx = next((i for i, item in enumerate(queue) if item["qid"] == after_qid), None)
    if idx is None:
        return None
    base = queue[idx]
    item = {
        "qid": f"{after_qid}.f",
        "chapter": base["chapter"],
        "chapter_title": base["chapter_title"],
        "question": question,
        "kind": "followup",
    }
    if any(row["qid"] == item["qid"] for row in queue):
        return None
    queue.insert(idx + 1, item)
    session["queue"] = queue
    session["followups"] = int(session.get("followups") or 0) + 1
    return item


async def ask_followup(answer: str, question: str, complete: Complete) -> Optional[str]:
    if len(_tokens(answer)) < 8:
        return None
    try:
        raw = await complete(FOLLOWUP_SYSTEM, f"Question: {question}\n\nTheir answer:\n{answer}")
    except Exception:  # noqa: BLE001
        return None
    return followup_from_model(answer, raw)


def tag_card(card: dict, *, source: str, ref: str = "", chapter: str = "", people: Iterable[str] = (),
             era: str = "", media: Optional[dict] = None) -> dict:
    card = dict(card)
    card["source"] = source
    if ref:
        card["source_ref"] = ref
    if chapter:
        card["chapter"] = chapter
    # People are names or family words ("Dad"), not roles the model picked up ("foreman").
    card["people"] = [p for p in card.get("people") or [] if any(ch.isupper() for ch in str(p))]
    extra = [p for p in people if p and p not in (card.get("people") or [])]
    if extra:
        card["people"] = list(card.get("people") or []) + extra[: max(0, 8 - len(card.get("people") or []))]
    if era and not card.get("era"):
        card["era"] = era
    if media:
        card["media"] = media
    return card


# ---------------------------------------------------------------- exported messages

@dataclass
class Msg:
    when: Optional[datetime]
    sender: str
    text: str


_WA_US = re.compile(
    r"^\u200e?\[?(\d{1,2})[/.](\d{1,2})[/.](\d{2,4}),? (\d{1,2}):(\d{2})(?::(\d{2}))?\s?([AaPp]\.?[Mm]\.?)?\]?\s?[-\u2013]?\s?([^:]{1,60}?): (.*)$"
)
_SYSTEM_LINES = ("<Media omitted>", "Messages and calls are end-to-end encrypted", "This message was deleted",
                 "image omitted", "video omitted", "sticker omitted", "audio omitted", "<attached:")


def _wa_time(d1: str, d2: str, y: str, hh: str, mm: str, ampm: Optional[str], day_first: bool) -> Optional[datetime]:
    year = int(y) + (2000 if len(y) == 2 else 0)
    month, day = (int(d2), int(d1)) if day_first else (int(d1), int(d2))
    hour = int(hh)
    if ampm:
        pm = ampm.lower().startswith("p")
        hour = (hour % 12) + (12 if pm else 0)
    try:
        return datetime(year, month, day, hour, int(mm))
    except ValueError:
        return None


def parse_whatsapp(text: str) -> list[Msg]:
    lines = (text or "").splitlines()
    heads = [_WA_US.match(line) for line in lines]
    # Day-first when any first field is above 12.
    day_first = any(m and int(m.group(1)) > 12 for m in heads)
    out: list[Msg] = []
    for line, m in zip(lines, heads):
        if m:
            d1, d2, y, hh, mm, _ss, ampm, sender, body = m.groups()
            out.append(Msg(_wa_time(d1, d2, y, hh, mm, ampm, day_first), sender.strip(), body.strip()))
        elif out and line.strip():
            out[-1].text += "\n" + line.strip()
    return [m for m in out if m.text and not any(s in m.text for s in _SYSTEM_LINES)]


def _fix_mojibake(s: str) -> str:
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def parse_meta_json(data: Any) -> list[Msg]:
    """Facebook Messenger / Instagram 'Download your information' JSON."""
    rows = data.get("messages") if isinstance(data, dict) else None
    out: list[Msg] = []
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("content"):
            continue
        ts = row.get("timestamp_ms")
        when = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).replace(tzinfo=None) if isinstance(ts, (int, float)) else None
        out.append(Msg(when, _fix_mojibake(str(row.get("sender_name") or "")), _fix_mojibake(str(row["content"]))))
    out.sort(key=lambda m: m.when or datetime.min)
    return out


_COLS = {
    "when": ("date", "time", "timestamp", "sent", "datetime", "message date"),
    "sender": ("sender", "from", "author", "name", "sender name", "contact"),
    "text": ("text", "body", "message", "content", "msg"),
}


def _parse_when(value: str) -> Optional[datetime]:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        pass
    for fmt in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M", "%m/%d/%Y", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def parse_csv_messages(text: str) -> list[Msg]:
    reader = csv.DictReader(io.StringIO(text))
    fields = {f.lower().strip(): f for f in (reader.fieldnames or [])}

    def pick(kind: str) -> Optional[str]:
        for name in _COLS[kind]:
            if name in fields:
                return fields[name]
        return None

    col_text, col_sender, col_when = pick("text"), pick("sender"), pick("when")
    if not col_text or not col_sender:
        return []
    out = []
    for row in reader:
        body = (row.get(col_text) or "").strip()
        if body:
            out.append(Msg(_parse_when(row.get(col_when) or "") if col_when else None, (row.get(col_sender) or "").strip(), body))
    return out


def parse_messages(filename: str, raw: bytes) -> tuple[str, list[Msg]]:
    text = raw.decode("utf-8-sig", errors="replace")
    name = (filename or "").lower()
    if name.endswith(".json"):
        try:
            return "messenger", parse_meta_json(json.loads(text))
        except json.JSONDecodeError:
            return "unknown", []
    if name.endswith(".csv"):
        return "csv", parse_csv_messages(text)
    msgs = parse_whatsapp(text)
    return ("whatsapp" if msgs else "unknown"), msgs


def senders(msgs: list[Msg]) -> list[dict[str, Any]]:
    counts = Counter(m.sender for m in msgs if m.sender)
    return [{"name": name, "messages": n} for name, n in counts.most_common(20)]


def passages_from_messages(msgs: list[Msg], me: str, *, max_cards: int = 25, min_words: int = 12) -> list[dict[str, Any]]:
    """The owner's own words, one passage per day, richest days first, then put back in order.

    Other people's messages never become the story; their names go in ``people``.
    """
    me_key = me.strip().lower()
    days: dict[str, dict[str, Any]] = {}
    for m in msgs:
        day = m.when.date().isoformat() if m.when else "undated"
        slot = days.setdefault(day, {"mine": [], "others": Counter()})
        if m.sender.strip().lower() == me_key:
            slot["mine"].append(m.text)
        elif m.sender:
            slot["others"][m.sender] += 1
    rows = []
    for day, slot in days.items():
        words = " ".join(" ".join(slot["mine"]).split())
        if len(words.split()) < min_words or len(_tokens(words)) < MIN_CONTENT_WORDS:
            continue
        others = [name for name, _ in slot["others"].most_common(3)]
        rows.append({
            "day": day,
            "transcript": words[:4000],
            "people": others,
            "era": day[:4] if day != "undated" else "",
            "question": f"Messages with {', '.join(others) or 'someone'}" + (f" on {day}" if day != "undated" else ""),
            "weight": len(words.split()),
        })
    best = sorted(rows, key=lambda r: r["weight"], reverse=True)[:max_cards]
    return sorted(best, key=lambda r: r["day"])


# ---------------------------------------------------------------- letters and documents

def passages_from_document(text: str, title: str, *, author: str = "", max_cards: int = 20, target_chars: int = 1200) -> list[dict[str, Any]]:
    paras = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text or "")]
    paras = [p for p in paras if p]
    chunks: list[str] = []
    buf = ""
    for para in paras:
        if buf and len(buf) + len(para) > target_chars:
            chunks.append(buf)
            buf = ""
        buf = f"{buf} {para}".strip()
    if buf:
        chunks.append(buf)
    rows = []
    for i, chunk in enumerate(chunks[:max_cards]):
        if len(_tokens(chunk)) < MIN_CONTENT_WORDS:
            continue
        story_prefix = f"A letter to me from {author}: " if author else ""
        rows.append({
            "transcript": story_prefix + chunk,
            "question": f"From {title}" + (f" (part {i + 1})" if len(chunks) > 1 else ""),
            "people": [author] if author else [],
            "era": "",
            "keepsake": bool(author),
        })
    return rows


# ---------------------------------------------------------------- photos

def photo_details(raw: bytes) -> dict[str, str]:
    """Caption and date the camera or an earlier app wrote into the photo, if any."""
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001
        return {}
    try:
        img = Image.open(io.BytesIO(raw))
        exif = img.getexif()
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, str] = {}
    desc = exif.get(0x010E)  # ImageDescription
    if isinstance(desc, bytes):
        desc = desc.decode("utf-8", errors="ignore")
    if desc and str(desc).strip():
        out["caption"] = " ".join(str(desc).split())[:1000]
    taken = None
    try:
        taken = exif.get_ifd(0x8769).get(0x9003)  # DateTimeOriginal
    except Exception:  # noqa: BLE001
        taken = None
    taken = taken or exif.get(0x0132)  # DateTime
    if taken:
        m = re.match(r"(\d{4}):(\d{2}):(\d{2})", str(taken))
        if m:
            out["taken_at"] = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return out


def photo_transcript(caption: str, taken_at: str = "", place: str = "") -> str:
    words = " ".join((caption or "").split())
    bits = [words]
    if place:
        bits.append(f"Place: {place}.")
    if taken_at:
        bits.append(f"Photo taken {taken_at}.")
    return " ".join(b for b in bits if b)


# ---------------------------------------------------------------- drafting

async def draft_pending_card(user_id: str, transcript: str, question: str, complete: Complete, **tags: Any) -> dict:
    """One pending card. The model drafts title/era/people; the story stays in their words."""
    draft = await draft_card(transcript, question, complete)
    card = new_card_doc(user_id, draft)
    return tag_card(card, **tags)


def quick_card(user_id: str, transcript: str, question: str, **tags: Any) -> dict:
    """Same card without the model (used when the model is down)."""
    return tag_card(new_card_doc(user_id, card_from_model(transcript, question, "")), **tags)


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


async def run_import(job: dict, passages: list[dict], *, source: str, complete: Complete, store: Any) -> None:
    """Draft each passage into a pending card, updating the job's progress as it goes."""
    done = 0
    status = "ready"
    try:
        for row in passages:
            tags = dict(source=source, ref=job["import_id"], people=row.get("people") or [], era=row.get("era") or "")
            try:
                card = await draft_pending_card(job["user_id"], row["transcript"], row["question"], complete, **tags)
            except Exception:  # noqa: BLE001 - keep their words when the model is down
                card = quick_card(job["user_id"], row["transcript"], row["question"], **tags)
            if row.get("keepsake"):
                # Someone else's letter: keep their exact words, never a retelling.
                card["keepsake"] = True
                card["story"] = row["transcript"][:4000]
            await store.memory_cards.insert_one(dict(card))
            done += 1
            await store.memory_imports.update_one({"import_id": job["import_id"]}, {"$set": {"done": done, "updated_at": _stamp()}})
    except Exception:  # noqa: BLE001
        log.exception("memory import %s failed", job.get("import_id"))
        status = "failed"
    await store.memory_imports.update_one({"import_id": job["import_id"]}, {"$set": {"status": status, "done": done, "updated_at": _stamp()}})


async def approve_card(store: Any, user_id: str, card_id: str, edits: Optional[dict] = None) -> Optional[dict]:
    """Approve one card and add it to the vault, exactly as the Record page does."""
    card = await store.memory_cards.find_one({"card_id": card_id, "user_id": user_id}, {"_id": 0})
    if not card:
        return None
    updated = approve_fields(card, edits or {})
    await store.memory_cards.update_one({"card_id": card_id, "user_id": user_id}, {"$set": updated})
    if str(card.get("status") or "") != "approved":
        await store.entries.insert_one(entry_from_card({**card, **updated}))
    return updated
