"""Observer notes in the Twin prompt. Lower priority than filed vault entries."""
from __future__ import annotations

from dataclasses import dataclass

from observer_learn import jaccard, tokenize
from observer_store import ObserverStore, observer_dir, observer_enabled

WATCHED_SOURCE = "from what I've watched"


@dataclass(frozen=True)
class ObserverAttach:
    block: str
    citation: str
    relied: bool


def relies_on_watched(query: str, notes: list[dict]) -> bool:
    query_tokens = set(tokenize(query))
    if not query_tokens:
        return False
    for note in notes:
        note_tokens = set(note.get("tokens") or tokenize(str(note.get("text") or "")))
        if not note_tokens:
            continue
        if len(query_tokens & note_tokens) >= 2:
            return True
        if jaccard(query_tokens, note_tokens) >= 0.34:
            return True
    return False


def observer_prompt_block(notes: list[dict]) -> str:
    if not notes:
        return ""
    lines = [
        "OBSERVER BACKGROUND (lower priority than CORE, STABLE FACTS, and PASSAGES the owner filed. "
        "These are inferences from watching the screen, not filed memory. "
        "If an answer depends on this section, the source label is "
        f"\"{WATCHED_SOURCE}\". If neither the filed passages nor this section answer, "
        "say you don't remember. Never present a watched inference as something they filed.):"
    ]
    for note in notes:
        kind = note.get("kind") or "note"
        confidence = float(note.get("confidence") or 0)
        status = note.get("status") or "pending"
        lines.append(f"- ({kind}, {status}, confidence {confidence:.2f}) {note.get('text') or ''}")
    return "\n".join(lines)


def apply_source_label(citation: str, relied: bool) -> str:
    if not relied:
        return citation or ""
    current = (citation or "").strip()
    if WATCHED_SOURCE in current:
        return current
    if current:
        return f"{current} · {WATCHED_SOURCE}"
    return WATCHED_SOURCE


def block_grounded_miss(grounded_miss: bool, watched_relied: bool) -> bool:
    """Vault silence stands unless a watched note actually bears on the question."""
    return bool(grounded_miss) and not watched_relied


def attach_observer_context(
    citation: str,
    query: str,
    *,
    audience: str = "owner",
    heir_surface: bool = False,
    notes: list[dict] | None = None,
    enabled: bool | None = None,
    store: ObserverStore | None = None,
) -> ObserverAttach:
    """No-op unless the observer is on. Heirs only receive accepted notes."""
    if enabled is None:
        enabled = observer_enabled()
    if not enabled:
        return ObserverAttach("", citation or "", False)
    if notes is None:
        try:
            active = store or ObserverStore(observer_dir())
            notes = active.background_notes(audience=audience, heir_surface=heir_surface)
        except OSError:
            notes = []
    block = observer_prompt_block(notes)
    relied = bool(block) and relies_on_watched(query, notes)
    return ObserverAttach(block, apply_source_label(citation, relied), relied)


def nightly_digest_markdown() -> str:
    if not observer_enabled():
        return ""
    try:
        return ObserverStore(observer_dir()).digest_section()
    except OSError:
        return ""
