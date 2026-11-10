"""A small debate room. Readers critique each other, then a moderator pins one lesson card.

Modelled on the local brain council: several drafts, a revision, one pinned result.
The room never sees the vault. It only sees the reading in front of it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from studyhall.discover import Seat

Complete = Callable[[Seat, list[dict]], Awaitable[str]]

AREAS = {"memory", "voice", "prompts", "safety", "ux"}
EXCERPT = 12000

READ_SYSTEM = """ROUND: read
You are a reader in Heirloom Study Hall. You study for the Heirloom Unbound twin: a local-first family twin that answers from what the owner filed and must not invent a life.

Read the source. Keep only what would help the twin do its work better — memory, voice, grief-aware conversation, safety, or provenance. Drop hype.

Return only JSON:
{"useful": "", "not_useful": "", "cautions": ""}"""

CRITIQUE_SYSTEM = """ROUND: critique
You are critiquing other readers in Heirloom Study Hall. Judge what is actually useful for the Heirloom twin. Reject anything that would weaken grounding, safety, or the rule that study notes are not the owner's biography.

Return only JSON:
{"agree": "", "reject": "", "keep": ""}"""

REVISE_SYSTEM = """ROUND: revise
Revise your note after the critique. Keep only what survived. Do not add facts that were not in the source.

Return only JSON:
{"useful": "", "cautions": ""}"""

PIN_SYSTEM = """ROUND: pin
You are the moderator of Heirloom Study Hall. Pin one short lesson card. You cannot change the twin. You only recommend.

The card is research the owner may file. It is not a memory of their life.

Return only JSON with this shape:
{"summary": "", "why_it_matters": "", "confidence": 0.5, "citations": [{"title": "", "url": "", "locator": ""}], "proposals": [{"area": "memory", "title": "", "idea": ""}]}

confidence is a number from 0 to 1.
area is one of: memory, voice, prompts, safety, ux.
proposals lists behavior or product ideas worth a human decision. Use an empty array if the source should not change how the twin behaves.
Cite the source you were given. Do not invent URLs."""


@dataclass
class RoundNote:
    seat: str
    model: str
    host: str
    round: str
    text: str
    parsed: dict = field(default_factory=dict)


@dataclass
class PanelResult:
    engine: str
    notes: list[RoundNote]
    lesson: dict
    proposals: list[dict]


def parse_json_object(text: str) -> dict | None:
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _clip(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def clean_confidence(value: object) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.4
    if number < 0:
        return 0.0
    if number > 1:
        return 1.0
    return number


def clean_proposals(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = _clip(item.get("title"), 140)
        idea = _clip(item.get("idea"), 800)
        if not title and not idea:
            continue
        area = str(item.get("area") or "other").strip().lower()
        if area not in AREAS:
            area = "other"
        out.append({"area": area, "title": title or idea[:140], "idea": idea})
    return out[:8]


def ensure_citation(card: dict, source: dict) -> None:
    cleaned = []
    for item in card.get("citations") or []:
        if not isinstance(item, dict):
            continue
        cleaned.append({
            "title": _clip(item.get("title") or source.get("title"), 200),
            "url": _clip(item.get("url") or source.get("url"), 500),
            "locator": _clip(item.get("locator") or "", 120),
        })
    source_url = str(source.get("url") or "")
    if source_url and not any(item["url"] == source_url for item in cleaned):
        cleaned.insert(0, {
            "title": _clip(source.get("title") or source_url, 200),
            "url": source_url,
            "locator": _clip(source.get("date") or "", 120),
        })
    card["citations"] = cleaned[:6]


def source_message(source: dict) -> str:
    text = str(source.get("text") or "")[:EXCERPT]
    return (
        f"TITLE: {source.get('title') or ''}\n"
        f"DATE: {source.get('date') or ''}\n"
        f"URL: {source.get('url') or ''}\n\n"
        f"TEXT:\n{text}"
    )


def _field(blob: str, label: str) -> str:
    prefix = label + ":"
    for line in (blob or "").splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


async def practice_complete(seat: Seat, messages: list[dict]) -> str:
    """A scripted room so the owner can see the panel with no model running."""
    system = messages[0]["content"] if messages else ""
    user = messages[-1]["content"] if messages else ""
    title = _field(user, "TITLE") or "this source"
    if "ROUND: pin" in system:
        return json.dumps({
            "summary": (
                f"From “{title}”: keep the twin grounded in what was filed, cite the source, "
                "and treat grief as something to acknowledge without inventing a life."
            ),
            "why_it_matters": "Heirloom should learn the method and still refuse unsourced biography.",
            "confidence": 0.64,
            "citations": [],
            "proposals": [
                {
                    "area": "prompts",
                    "title": "Label study notes as research",
                    "idea": "When a filed study note is used, name it as research rather than as a memory.",
                },
                {
                    "area": "memory",
                    "title": "Keep provenance on every filed lesson",
                    "idea": "Do not store a study lesson without its source URL and title.",
                },
            ],
        })
    if "ROUND: critique" in system:
        return json.dumps({
            "agree": "Provenance and grounding are the useful part.",
            "reject": "Any suggestion to invent memories or bypass a source.",
            "keep": "Cite the source and do not treat the note as biography.",
        })
    if "ROUND: revise" in system:
        return json.dumps({
            "useful": f"“{title}” is useful as a method: cite sources and stay grounded.",
            "cautions": "Do not file this as something the owner lived.",
        })
    return json.dumps({
        "useful": f"The useful part of “{title}” is the method, not a new biography.",
        "not_useful": "Vendor hype and unsourced claims.",
        "cautions": "Study notes are not memories.",
    })


def _note(seat: Seat, round_name: str, raw: str) -> RoundNote:
    parsed = parse_json_object(raw) or {}
    return RoundNote(seat.model, seat.model, seat.host, round_name, raw.strip()[:4000], parsed)


async def _ask(seat: Seat, system: str, user: str, complete: Complete) -> RoundNote:
    try:
        raw = await complete(seat, [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])
    except Exception as exc:  # a dead model should not sink the room
        raw = json.dumps({"useful": "", "cautions": f"{seat.model} did not answer ({exc.__class__.__name__})."})
    round_name = "read"
    if "ROUND: critique" in system:
        round_name = "critique"
    elif "ROUND: revise" in system:
        round_name = "revise"
    elif "ROUND: pin" in system:
        round_name = "pin"
    return _note(seat, round_name, raw or "")


def _render_notes(notes: list[RoundNote]) -> str:
    lines = []
    for note in notes:
        body = note.parsed or {"text": note.text[:800]}
        lines.append(f"[{note.seat} / {note.round}]\n{json.dumps(body, ensure_ascii=False)}")
    return "\n\n".join(lines)


def _fallback_card(source: dict, revised: list[RoundNote]) -> dict:
    useful = []
    for note in revised:
        line = _clip((note.parsed or {}).get("useful") or note.text, 280)
        if line:
            useful.append(line)
    summary = useful[0] if useful else "The panel could not pin a clean lesson from this reading."
    return {
        "summary": summary,
        "why_it_matters": "Kept as a cautious note because the moderator did not return a card.",
        "confidence": 0.35,
        "citations": [],
        "proposals": [],
        "parsed": False,
    }


async def run_study(
    source: dict,
    readers: list[Seat],
    moderator: Seat,
    complete: Complete,
    *,
    engine: str = "local",
    already_filed: Optional[list[str]] = None,
    focus: str = "",
) -> PanelResult:
    if not readers:
        raise ValueError("The panel has no readers.")
    import asyncio

    opening = source_message(source)
    read_notes = list(await asyncio.gather(*[_ask(seat, READ_SYSTEM, opening, complete) for seat in readers]))

    critique_prompt = "Other readers wrote:\n\n" + _render_notes(read_notes) + "\n\nSOURCE:\n" + opening[:4000]
    critiques = list(await asyncio.gather(*[_ask(seat, CRITIQUE_SYSTEM, critique_prompt, complete) for seat in readers]))

    revise_prompt = "Your critique round:\n\n" + _render_notes(critiques) + "\n\nSOURCE:\n" + opening[:4000]
    revised = list(await asyncio.gather(*[_ask(seat, REVISE_SYSTEM, revise_prompt, complete) for seat in readers]))

    filed = [title for title in (already_filed or []) if title][:6]
    filed_block = ""
    if filed:
        filed_block = "ALREADY FILED (do not repeat these lessons):\n" + "\n".join(f"- {title}" for title in filed) + "\n\n"
    focus_block = f"FOCUS: {focus}\n\n" if focus else ""
    pin_user = focus_block + filed_block + "REVISED NOTES:\n" + _render_notes(revised) + "\n\nSOURCE:\n" + opening[:5000]
    pinned = await _ask(moderator, PIN_SYSTEM, pin_user, complete)
    parsed = pinned.parsed
    if not parsed or not _clip(parsed.get("summary"), 20):
        card = _fallback_card(source, revised)
    else:
        card = {
            "summary": _clip(parsed.get("summary"), 700),
            "why_it_matters": _clip(parsed.get("why_it_matters"), 400),
            "confidence": clean_confidence(parsed.get("confidence")),
            "citations": parsed.get("citations") or [],
            "proposals": clean_proposals(parsed.get("proposals")),
            "parsed": True,
        }
    ensure_citation(card, source)
    proposals = clean_proposals(card.pop("proposals"))
    notes = read_notes + critiques + revised + [pinned]
    lesson = {
        "summary": card["summary"],
        "why_it_matters": card["why_it_matters"],
        "confidence": card["confidence"],
        "citations": card["citations"],
        "parsed": bool(card.get("parsed")),
        "engine": engine,
        "moderator": moderator.model,
        "readers": [seat.model for seat in readers],
        "source_url": source.get("url") or "",
        "source_title": source.get("title") or "",
        "source_date": source.get("date") or "",
    }
    return PanelResult(engine=engine, notes=notes, lesson=lesson, proposals=proposals)
