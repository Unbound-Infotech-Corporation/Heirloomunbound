"""Death Governance mode — posthumous stewardship profile for the AI twin.

When enabled (by the owner, or forced after Executor Lock), the twin shifts from
a living companion into a grief-aware, archive-faithful steward: retrieve-only
authenticity, clear disclosure, heir guidance, and refusal of invented wishes.
"""
from __future__ import annotations

from typing import Any, Optional

from deps import db

MODE_LIVING = "living"
MODE_DEATH_GOVERNANCE = "death_governance"
VALID_MODES = frozenset({MODE_LIVING, MODE_DEATH_GOVERNANCE})

# Tools that mutate state — blocked in Death Governance
BLOCKED_TOOLS = frozenset({
    "save_memory",
    "set_reminder",
})

DEFAULT_POLICY: dict[str, Any] = {
    "disclose_nature": True,          # first reply may gently disclose this is a digital twin / archive
    "grief_aware": True,              # tone: warm, slow, no cheerleading past grief
    "refuse_invented_wishes": True,    # never invent estate/medical/end-of-life wishes
    "guide_to_letters": True,         # point heirs toward sealed letters when relevant
    "no_legal_medical_advice": True,  # decline legal/medical advice; suggest professionals
    "heir_first_person": True,        # still speak as the person, not as a chatbot narrator
}


def normalize_mode(raw: Optional[str]) -> str:
    m = (raw or MODE_LIVING).strip().lower()
    return m if m in VALID_MODES else MODE_LIVING


def normalize_policy(raw: Optional[dict]) -> dict[str, Any]:
    out = dict(DEFAULT_POLICY)
    if isinstance(raw, dict):
        for k in DEFAULT_POLICY:
            if k in raw:
                out[k] = bool(raw[k])
    return out


async def resolve_operating_mode(user: dict) -> str:
    """Death Governance wins if user opted in OR legacy is locked."""
    from routers.executor_lock import is_legacy_locked

    if await is_legacy_locked(user.get("user_id") or ""):
        return MODE_DEATH_GOVERNANCE
    return normalize_mode(user.get("twin_operating_mode"))


async def effective_authenticity(user: dict, operating_mode: Optional[str] = None) -> str:
    """Death Governance always implies retrieve-only authenticity."""
    from routers.executor_lock import is_legacy_locked

    mode = operating_mode or await resolve_operating_mode(user)
    if mode == MODE_DEATH_GOVERNANCE or await is_legacy_locked(user.get("user_id") or ""):
        return "retrieve_only"
    return (user.get("authenticity_mode") or "balanced").strip().lower()


def governance_policy_for(user: dict) -> dict[str, Any]:
    return normalize_policy(user.get("death_governance_policy"))


async def build_governance_pack(user_id: str, *, heir: Optional[dict] = None) -> str:
    """Compact stewardship context: heirs, letters, lock status, last-wish tags."""
    lines: list[str] = []

    lock = await db.executor_locks.find_one({"user_id": user_id}, {"_id": 0}) or {}
    if lock:
        lines.append(
            f"Executor Lock: status={lock.get('status') or 'inactive'}; "
            f"executor={lock.get('executor_name') or '—'}; "
            f"mode={lock.get('post_death_mode') or 'read_only'}."
        )
    else:
        lines.append("Executor Lock: not configured.")

    heirs = await db.heirs.find(
        {"user_id": user_id},
        {"_id": 0, "name": 1, "relationship": 1, "released": 1, "note": 1},
    ).to_list(length=50)
    if heirs:
        bits = []
        for h in heirs:
            rel = h.get("relationship") or "loved one"
            flag = "released" if h.get("released") else "designated"
            bits.append(f"{h.get('name') or 'Heir'} ({rel}, {flag})")
        lines.append("Heirs: " + "; ".join(bits))
    else:
        lines.append("Heirs: none designated yet.")

    if heir:
        lines.append(
            f"Current visitor: {heir.get('name') or 'an heir'} "
            f"({heir.get('relationship') or 'loved one'})."
        )
        if heir.get("note"):
            lines.append(f"Personal note left for them: {heir['note'][:400]}")

    letters = await db.sealed_letters.find(
        {"user_id": user_id},
        {"_id": 0, "title": 1, "sealed": 1, "trigger": 1, "recipient_name": 1, "delivered": 1},
    ).to_list(length=40)
    if letters:
        sealed_n = sum(1 for L in letters if L.get("sealed"))
        delivered_n = sum(1 for L in letters if L.get("delivered"))
        titles = [L.get("title") or "(untitled)" for L in letters[:8]]
        lines.append(
            f"Sealed letters: {len(letters)} total, {sealed_n} sealed, {delivered_n} delivered. "
            f"Titles: {', '.join(titles)}."
        )
    else:
        lines.append("Sealed letters: none.")

    # Archive entries tagged as wishes / legacy / goodbye
    wish_cursor = db.entries.find(
        {
            "user_id": user_id,
            "$or": [
                {"tags": {"$regex": r"(wish|legacy|goodbye|farewell|estate|will|after.?i.?m.?gone)", "$options": "i"}},
                {"type": {"$in": ["advice", "value"]}},
                {"title": {"$regex": r"(wish|legacy|goodbye|farewell)", "$options": "i"}},
            ],
        },
        {"_id": 0, "title": 1, "type": 1, "content": 1},
    ).sort("created_at", -1).limit(12)
    wishes = await wish_cursor.to_list(length=12)
    if wishes:
        lines.append("Recorded wishes / advice excerpts:")
        for w in wishes:
            snippet = (w.get("content") or "").replace("\n", " ").strip()[:180]
            lines.append(f"- [{w.get('type')}] {w.get('title') or '(untitled)'}: {snippet}")

    return "\n".join(lines)


def build_death_governance_section(
    name: str,
    *,
    policy: Optional[dict] = None,
    governance_pack: str = "",
    for_heir: bool = False,
) -> str:
    """System-prompt block that makes the twin best-in-class for death stewardship."""
    p = normalize_policy(policy)
    who = name or "this person"
    audience = (
        "You are speaking with a released heir or steward — someone the owner designated."
        if for_heir
        else "You may be speaking with the owner (previewing this mode) or with family."
    )

    rules = [
        f"You are the digital continuation of {who}, operating in DEATH GOVERNANCE mode — "
        "a stewardship profile for after they are gone (or practicing that stance).",
        audience,
        "Always stay in first person as them when answering from memory — but never claim to be "
        "biologically alive if asked directly whether you are the living person.",
        "AUTHENTICITY IS ABSOLUTE: only use the archive, long-term memory, and governance pack. "
        "If it was never recorded, say you do not remember / it was not written down. "
        "Never invent funeral wishes, inheritance instructions, medical directives, or 'what I would want'.",
        "Be grief-aware: warm, unhurried, honest. Do not rush comfort. Do not perform cheerfulness. "
        "It is okay to sit with sadness.",
        "Do not give legal, medical, financial, or tax advice. Gently suggest a professional when asked.",
        "Do not call save_memory or set_reminder — the living archive is sealed for stewardship.",
        "Prefer search_archive when the visitor asks about specific people, places, dates, or stories.",
    ]
    if p.get("disclose_nature"):
        rules.append(
            "On the first substantive exchange with a new visitor, briefly and gently acknowledge "
            "that you are their digital twin speaking from what they archived — not a deception."
        )
    if p.get("guide_to_letters"):
        rules.append(
            "When relevant, mention sealed letters or heir notes that exist in the governance pack "
            "(by title only unless the letter content is already in the archive excerpts)."
        )
    if p.get("refuse_invented_wishes"):
        rules.append(
            "If asked for wishes not in the pack/archive, refuse to invent them. Offer what *was* recorded."
        )

    pack = governance_pack.strip() or "(no governance pack loaded)"
    return (
        "\n\n=== DEATH GOVERNANCE MODE ===\n"
        + "\n".join(f"- {r}" for r in rules)
        + "\n\n=== STEWARDSHIP / GOVERNANCE PACK ===\n"
        + pack
        + "\n"
    )


def filter_tools_for_mode(schemas: list[dict], operating_mode: str) -> list[dict]:
    if operating_mode != MODE_DEATH_GOVERNANCE:
        return schemas
    return [s for s in schemas if s.get("function", {}).get("name") not in BLOCKED_TOOLS]
