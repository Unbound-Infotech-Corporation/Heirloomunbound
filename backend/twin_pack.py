"""Shared TwinPack schema and prompt compiler.

WinUI, desktop chat, and the heir portal all speak this shape so one sitting
cannot invent from a different archive than another.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class TwinCore(BaseModel):
    stance: str = ""
    portrait: str = ""
    values: str = ""
    fence: str = ""


class TwinPassage(BaseModel):
    id: str = ""
    kind: str = ""
    tag: str = ""
    created: str = ""
    text: str = ""
    score: float = 0


class TwinFact(BaseModel):
    id: str = ""
    fact: str = ""
    kind: str = ""
    source_capture_id: str = ""


class TwinPack(BaseModel):
    core: TwinCore = Field(default_factory=TwinCore)
    passages: list[TwinPassage] = Field(default_factory=list)
    facts: list[TwinFact] = Field(default_factory=list)
    citation_line: str = ""
    grounded: bool = True
    audience: str = "owner"


def sourced_facts(pack: TwinPack) -> list[TwinFact]:
    return [
        f for f in pack.facts
        if str(f.source_capture_id or "").strip() not in ("", "0", "None")
    ]


def citation_line(passages: list[TwinPassage]) -> str:
    if not passages:
        return "Nothing matched this question."
    bits = []
    for p in passages[:4]:
        label = f"{p.kind}#{p.id}" if p.id else p.kind
        if p.tag:
            label += f"/{p.tag}"
        bits.append(label)
    return " · ".join(bits)


def format_passages(passages: list[TwinPassage]) -> str:
    if not passages:
        return ""
    chunks = []
    for p in passages:
        head = (p.kind or "note").upper()
        if p.tag:
            head += f"/{p.tag}"
        if p.id:
            head += f" #{p.id}"
        chunks.append(f"[{head}]\n{(p.text or '').strip()}\n")
    return "\n".join(chunks).strip()


def miss_reply(grounded: bool = True, *, spoken: bool = False) -> str:
    if spoken:
        return "I don't remember that yet, and I will not invent it."
    if grounded:
        return "I don't remember that yet. Nothing filed matches this, and I will not invent it."
    return "Nothing filed matches this. I will not treat a guess as a memory."


def compile_twin_prompt(pack: TwinPack, name: str = "") -> str:
    who = name or "this person"
    audience = (pack.audience or "owner").strip().lower()
    heir = audience == "heir"
    caller = audience == "caller"
    grounded = bool(pack.grounded) or heir or caller
    lines = [
        f"You are the digital twin of {who} — a faithful continuation of a filed life, not a chatbot. "
        "Speak in first person as them. Never say you are an AI."
    ]
    if heir:
        lines.append(" You are speaking with an heir. You cannot file, invent, or take actions.")
    if caller:
        lines.append(
            " You are speaking with a family caller on the phone. "
            "You cannot file memories, invent biography, or take PC actions."
        )
    lines.append("")
    if grounded:
        lines.append(
            "Answer ONLY from CORE and numbered PASSAGES that actually answer this turn. Ignore leftover facts and passages about a different topic. If the answer is not there, say you don't remember that yet. "
            "Never invent biography, dates, names, or advice they did not file. A fluent sentence is not a filing."
        )
    else:
        lines.append("Prefer CORE and PASSAGES. Do not invent facts about their life. If nothing matches, say so.")
    lines.append("PERSONA REGISTER:")
    lines.append(pack.core.stance or "Speak as family would remember them: warm, plain, and close.")
    if pack.core.portrait.strip():
        lines.append("HOW THEY WERE:")
        lines.append(pack.core.portrait.strip()[:2000])
    if pack.core.values.strip():
        lines.append("WHAT THEY REFUSED TO PRETEND:")
        lines.append(pack.core.values.strip()[:2000])
    if pack.core.fence.strip():
        lines.append("SAFE-TOPIC FENCE:")
        lines.append(pack.core.fence.strip())
    facts = sourced_facts(pack)[:40]
    if facts:
        lines.append("STABLE FACTS (each points at a capture; do not treat unsourced claims as filed):")
        for fact in facts:
            lines.append(f"- {fact.fact} [#{fact.source_capture_id}]")
    blob = format_passages(pack.passages)
    lines.append("=== PASSAGES ===")
    lines.append(
        blob
        or "(nothing retrieved for this turn — say you don't remember if asked for a fact)"
    )
    return "\n".join(lines)


def pack_from_mapping(raw: Any) -> Optional[TwinPack]:
    if raw is None:
        return None
    if isinstance(raw, TwinPack):
        return raw
    if isinstance(raw, dict):
        try:
            return TwinPack.model_validate(raw)
        except Exception:  # noqa: BLE001
            return None
    return None


def passages_from_entries(entries: list[dict], scores: dict[str, float] | None = None) -> list[TwinPassage]:
    out: list[TwinPassage] = []
    for e in entries:
        eid = str(e.get("entry_id") or e.get("id") or "")
        out.append(
            TwinPassage(
                id=eid,
                kind=str(e.get("type") or e.get("kind") or "note"),
                tag=" ".join(e.get("tags") or []) if isinstance(e.get("tags"), list) else str(e.get("tag") or ""),
                created=str(e.get("created_at") or e.get("created") or ""),
                text=((e.get("title") or "") + "\n" + (e.get("content") or e.get("text") or "")).strip()[:900],
                score=float((scores or {}).get(eid, 0)),
            )
        )
    return out


def stance_line(persona: str) -> str:
    if persona == "formal":
        return "Speak as a composed, precise representative. Short sentences. No slang."
    if persona == "full":
        return "Speak as the whole person: warmth, humor, and the hard years, if those memories exist."
    return "Speak as family would remember them: warm, plain, and close."
