"""Twin is the main bot. Other assistants are Clones.

Slice 1 is the routing spine only. On an owner Sit turn the Twin decides:

- answer itself
- hand off to one Clone (name, role, declared abilities)
- or Assist, using the existing Do / As you / both classifier as the PC leg

Explicit ``@CloneName`` or ``clone_id`` always wins. Unclear stays with the
Twin. Heirs, callers, and heir surfaces never enter this router.

Extension points (not built): a ``MainBotClassifier`` may be a cheap LLM.
``autonomy`` is stored (``ask`` default, ``act`` later) and is not enforced.
Assignments, approve-before-send, connectors, per-clone routines, per-clone
memory, and Clone-to-Clone messaging are later slices.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence

from assistants import (
    PC_ABILITY_IDS,
    chat_role_for_specialist,
    clone_abilities,
    match_assistant,
    mention_from_text,
)
from owner_rail import (
    ROUTE_ASSIST,
    ROUTE_BOTH,
    ROUTE_TWIN,
    classify_owner_turn,
    owner_mode_allowed,
)

HANDLER_TWIN = "twin"
HANDLER_CLONE = "clone"
HANDLER_ASSIST = "assist"
HANDLERS = frozenset({HANDLER_TWIN, HANDLER_CLONE, HANDLER_ASSIST})

_SCORE_FLOOR = 6
_SCORE_MARGIN = 2

_STOP = frozenset({
    "a", "an", "the", "and", "or", "to", "of", "for", "in", "on", "my", "me",
    "i", "you", "your", "their", "this", "that", "with", "from", "about",
    "into", "it", "is", "are", "was", "be", "as", "at", "by", "not", "no",
    "never", "do", "does", "up", "out", "they", "them", "we", "our", "just",
    "than", "then", "what", "when", "where", "who", "how", "why", "can",
    "could", "would", "should", "please", "help",
})

# Cues for declared abilities. PC abilities are not cues — Assist owns that leg.
_ABILITY_CUES: dict[str, re.Pattern[str]] = {
    "web": re.compile(
        r"\b(?:look\s+up|lookup|weather|forecast|google|search the web|web search|news|fetch)\b",
        re.IGNORECASE,
    ),
    "music": re.compile(r"\b(?:playlist|song|album|artist|spotify)\b", re.IGNORECASE),
    "smart_home": re.compile(r"\b(?:lights|thermostat|scene|webhook)\b", re.IGNORECASE),
    "phone": re.compile(r"\b(?:phone call|dial)\b", re.IGNORECASE),
}


class MainBotClassifier(Protocol):
    """Cheap, deterministic decision. Tests inject a fake. Production uses heuristic."""

    def classify(self, text: str, clones: Sequence[Mapping[str, Any]]) -> "MainBotDecision":
        ...


@dataclass(frozen=True)
class MainBotDecision:
    handler: str
    chip: str
    reason: str
    close_loop: str
    execution: str
    rail: str
    message: str
    clone_id: Optional[str] = None
    clone_name: Optional[str] = None
    explicit: bool = False
    fenced: bool = False

    def as_handoff(self) -> dict[str, Any]:
        return handoff_payload(self)


def twin_self_voice_note() -> str:
    """Owner Twin turn: first person as the twin, never as a Clone."""
    return (
        "This turn is yours. You are the twin, the person. "
        "A clone did not take this turn. Do not speak as a named specialist clone. "
        "Speak in first person as yourself."
    )


def handoff_chip(handler: str, clone_name: Optional[str] = None) -> str:
    if handler == HANDLER_CLONE:
        name = (clone_name or "Clone").strip() or "Clone"
        return f"Clone: {name}"
    if handler == HANDLER_ASSIST:
        return "Do"
    return "Twin"


def handoff_payload(decision: MainBotDecision) -> dict[str, Any]:
    out: dict[str, Any] = {
        "handler": decision.handler,
        "reason": decision.reason,
        "close_loop": decision.close_loop,
        "chip": decision.chip,
    }
    if decision.clone_id:
        out["clone_id"] = decision.clone_id
        out["clone_name"] = decision.clone_name or ""
    return out


def compose_routed_reply(body: str, decision: MainBotDecision) -> str:
    """Append the Twin's close-the-loop line when someone else did the work."""
    text = (body or "").strip()
    if decision.handler == HANDLER_TWIN or decision.fenced:
        return text or "I heard you."
    line = (decision.close_loop or "").strip()
    if not line:
        return text or "I heard you."
    if not text:
        return line
    if line in text:
        return text
    return f"{text}\n\n{line}"


def stamp_persisted_turn(turn: dict[str, Any], handoff: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """Write the handoff receipt onto one persisted assistant turn."""
    if not handoff:
        return turn
    stamped = {
        "handler": str(handoff.get("handler") or HANDLER_TWIN),
        "reason": str(handoff.get("reason") or ""),
        "close_loop": str(handoff.get("close_loop") or ""),
        "chip": str(handoff.get("chip") or ""),
    }
    if handoff.get("clone_id"):
        stamped["clone_id"] = handoff.get("clone_id")
    if handoff.get("clone_name"):
        stamped["clone_name"] = handoff.get("clone_name")
    turn["handoff"] = stamped
    if stamped["chip"]:
        turn["handoff_chip"] = stamped["chip"]
    return turn


def leg_allows_pc_tools(decision: MainBotDecision, leg: str) -> bool:
    """PC tools only on an Assist execution leg. Fenced and Clone-on-Twin never qualify."""
    if decision.fenced:
        return False
    if (leg or "").strip().lower() != ROUTE_ASSIST:
        return False
    return decision.execution in {ROUTE_ASSIST, ROUTE_BOTH}


def route_main_bot(
    text: str,
    clones: Sequence[Mapping[str, Any]],
    *,
    clone_id: Optional[str] = None,
    audience: Optional[str] = "owner",
    heir_surface: bool = False,
    classifier: Optional[MainBotClassifier] = None,
) -> MainBotDecision:
    """Route one owner Sit turn. Pure: no I/O, no clock."""
    raw = text or ""
    if not owner_mode_allowed(audience=audience, heir_surface=heir_surface):
        return _fenced(raw)

    enabled = [c for c in clones if c.get("enabled") is not False]
    disabled = [c for c in clones if c.get("enabled") is False]
    mention, remainder = mention_from_text(raw)
    explicit_id = (clone_id or "").strip() or None

    if explicit_id:
        chosen = match_assistant(enabled, assistant_id=explicit_id)
        if chosen:
            return _from_clone(chosen, raw, explicit=True, reason=f"You asked for {chosen.get('name') or 'that clone'}.")
        if match_assistant(disabled, assistant_id=explicit_id, include_disabled=True):
            return _twin_self(raw, reason="That clone is off, so I'll answer.")
        return _twin_self(raw, reason="I don't have that clone, so I'll answer.")

    if mention:
        chosen = match_assistant(enabled, mention=mention)
        if chosen:
            message = remainder.strip() or raw
            return _from_clone(
                chosen,
                message,
                explicit=True,
                reason=f"You asked for {chosen.get('name') or 'that clone'}.",
            )
        if match_assistant(disabled, mention=mention, include_disabled=True):
            return _twin_self(raw, reason="That clone is off, so I'll answer.")

    clf = classifier or HeuristicMainBotClassifier()
    return clf.classify(raw, enabled)


class HeuristicMainBotClassifier:
    """Keyword / role / ability match. The PC leg reuses classify_owner_turn."""

    def classify(self, text: str, clones: Sequence[Mapping[str, Any]]) -> MainBotDecision:
        return _heuristic_route(text, clones)


class LlmMainBotClassifier:
    """Optional cheap LLM. ``complete`` is injected; None means heuristic only.

    The model may pick the Twin or a non-PC Clone. Assist / PC stays on the
    heuristic so a classifier cannot grant pc_control, screen_vision, or terminal.
    Garbage output falls back to the heuristic.
    """

    def __init__(
        self,
        complete: Optional[Callable[[str], str]] = None,
        fallback: Optional[MainBotClassifier] = None,
    ) -> None:
        self.complete = complete
        self.fallback: MainBotClassifier = fallback or HeuristicMainBotClassifier()

    def classify(self, text: str, clones: Sequence[Mapping[str, Any]]) -> MainBotDecision:
        heuristic = self.fallback.classify(text, clones)
        if self.complete is None or heuristic.handler == HANDLER_ASSIST:
            return heuristic
        try:
            raw = self.complete(_classifier_prompt(text, clones))
            choice = parse_classifier_json(raw)
        except Exception:  # noqa: BLE001 — classifier failures stay on the heuristic
            return heuristic
        if not choice or choice["handler"] == HANDLER_ASSIST:
            return heuristic
        if choice["handler"] == HANDLER_TWIN:
            reason = choice["reason"] or heuristic.reason
            return _twin_self(text, reason=reason)
        chosen = match_assistant(list(clones), mention=choice["clone"])
        if not chosen or chat_role_for_specialist(dict(chosen)) == "assistant":
            return heuristic
        reason = choice["reason"] or f"{chosen.get('name') or 'That clone'} is the best match."
        return _from_clone(dict(chosen), text, explicit=False, reason=reason)


def parse_classifier_json(raw: str) -> Optional[dict[str, str]]:
    match = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    handler = str(data.get("handler") or "").strip().lower()
    if handler not in HANDLERS:
        return None
    reason = re.sub(r"\s+", " ", str(data.get("reason") or "")).strip()[:180]
    clone = str(data.get("clone") or "").strip()[:48]
    return {"handler": handler, "clone": clone, "reason": reason}


def _classifier_prompt(text: str, clones: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "Pick who should handle this owner turn. Reply with JSON only:",
        '{"handler":"twin"|"clone","clone":"<slug or empty>","reason":"one line"}',
        "handler assist is not allowed. If none of the clones clearly fit, choose twin.",
        "Clones:",
    ]
    for clone in clones:
        if chat_role_for_specialist(dict(clone)) == "assistant":
            continue
        name = str(clone.get("name") or "").strip()
        slug = str(clone.get("slug") or name).strip()
        role = str(clone.get("role") or "").strip()[:180]
        abilities = ", ".join(clone_abilities(dict(clone))) or "(none)"
        lines.append(f"- {name} slug={slug} role={role} abilities={abilities}")
    lines.append(f"Turn: {text}")
    return "\n".join(lines)


def _fenced(text: str) -> MainBotDecision:
    return MainBotDecision(
        handler=HANDLER_TWIN,
        chip="Twin",
        reason="This sitting stays with me.",
        close_loop="I'll answer this myself.",
        execution=ROUTE_TWIN,
        rail=ROUTE_TWIN,
        message=text,
        fenced=True,
    )


def _twin_self(text: str, *, reason: str) -> MainBotDecision:
    return MainBotDecision(
        handler=HANDLER_TWIN,
        chip="Twin",
        reason=_one_line(reason),
        close_loop="I'll answer this myself.",
        execution=ROUTE_TWIN,
        rail=ROUTE_TWIN,
        message=text,
    )


def _from_clone(clone: Mapping[str, Any], message: str, *, explicit: bool, reason: str) -> MainBotDecision:
    name = str(clone.get("name") or "Clone").strip() or "Clone"
    cid = str(clone.get("clone_id") or clone.get("assistant_id") or "").strip() or None
    through_assist = chat_role_for_specialist(dict(clone)) == "assistant"
    execution = ROUTE_ASSIST if through_assist else ROUTE_TWIN
    return MainBotDecision(
        handler=HANDLER_CLONE,
        chip=handoff_chip(HANDLER_CLONE, name),
        reason=_one_line(reason),
        close_loop=f"I'll hand this to {name}.",
        execution=execution,
        rail=execution,
        message=message,
        clone_id=cid,
        clone_name=name,
        explicit=explicit,
    )


def _heuristic_route(text: str, clones: Sequence[Mapping[str, Any]]) -> MainBotDecision:
    pc = classify_owner_turn(text)
    if pc.assist and pc.twin:
        return MainBotDecision(
            handler=HANDLER_ASSIST,
            chip="Do + As you",
            reason="This needs work on this PC and a note from me.",
            close_loop="I'll do the computer part, and I'll answer the rest myself.",
            execution=ROUTE_BOTH,
            rail=ROUTE_BOTH,
            message=text,
        )
    if pc.assist:
        return MainBotDecision(
            handler=HANDLER_ASSIST,
            chip="Do",
            reason="This is work on this PC.",
            close_loop="I'll have Assist do that on this PC.",
            execution=ROUTE_ASSIST,
            rail=ROUTE_ASSIST,
            message=text,
        )

    ranked = _rank_clones(text, clones)
    if ranked:
        best = ranked[0]
        second = ranked[1].score if len(ranked) > 1 else 0
        if best.score >= _SCORE_FLOOR and best.score - second >= _SCORE_MARGIN:
            role = str(best.clone.get("role") or "").strip()
            name = str(best.clone.get("name") or "Clone").strip() or "Clone"
            if role:
                reason = f"{name} matches this — {role[:80]}"
            else:
                reason = f"{name} is the best match."
            return _from_clone(best.clone, text, explicit=False, reason=reason)

    if pc.twin and "default_ask" not in pc.reasons:
        return _twin_self(text, reason="This one is mine to answer.")
    return _twin_self(text, reason="No specialist was a clear match.")


@dataclass(frozen=True)
class _Ranked:
    score: int
    clone: Mapping[str, Any]


def _rank_clones(text: str, clones: Sequence[Mapping[str, Any]]) -> list[_Ranked]:
    ranked: list[_Ranked] = []
    for clone in clones:
        if chat_role_for_specialist(dict(clone)) == "assistant":
            continue
        score = _score_clone(text, clone)
        if score <= 0:
            continue
        ranked.append(_Ranked(score=score, clone=clone))
    ranked.sort(key=lambda row: (-row.score, str(row.clone.get("name") or "").lower()))
    return ranked


def _score_clone(text: str, clone: Mapping[str, Any]) -> int:
    blob = text or ""
    score = 0
    name = str(clone.get("name") or "").strip()
    if len(name) >= 3 and re.search(rf"\b{re.escape(name)}\b", blob, re.IGNORECASE):
        score += 6
    overlap = _tokens(str(clone.get("role") or "")) & _tokens(blob)
    score += min(len(overlap), 4) * 2
    ability_hits = 0
    for ability in clone_abilities(dict(clone)):
        cue = _ABILITY_CUES.get(ability)
        if cue and cue.search(blob):
            ability_hits += 1
    score += min(ability_hits, 2) * 4
    return score


def _tokens(text: str) -> set[str]:
    out: set[str] = set()
    for word in re.findall(r"[a-z0-9']+", (text or "").lower()):
        if len(word) < 4 or word in _STOP:
            continue
        out.add(word)
        if word.endswith("s") and len(word) > 4:
            out.add(word[:-1])
    return out


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())[:180]
