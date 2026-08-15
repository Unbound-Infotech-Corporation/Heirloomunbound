"""Second brain that keeps the twin sounding like the owner.

Twin chat already speaks as the user. This module does two quiet jobs:

1. Format the cached personality portrait for the twin's system prompt
   (read-only — never regenerate the portrait on a chat turn).
2. After a handful of new messages, ask the Quick-replies model to extract
   phrases and beliefs the owner actually said, then store them as memory
   facts and signature phrases.

Local (home-PC) Quick-replies models are skipped — that path is too slow
for a background pass. Cloud Quick replies still run even if they share a
provider with Twin chat; the prompt is a different job (listen, don't speak).
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

VOICE_COUNCIL_AFTER_MESSAGES = 8  # four user/assistant turns
MAX_SIGNATURE_PHRASES = 8
MAX_NEW_FACTS = 8

VOICE_COUNCIL_SYSTEM = """You listen to how this person actually talks. Extract only what is clearly theirs.

Return ONLY a JSON object — no prose, no markdown fences — with this shape:
{
  "phrases": ["exact short phrases they used, max 6"],
  "beliefs": ["short beliefs they stated, max 4"],
  "corrections": ["if they said they do not like something the twin assumed, note it, max 4"]
}

Rules:
- Only include things the USER said. Ignore the ASSISTANT (that is their twin).
- Phrases should be short and characteristic — how they actually word things.
- No invented biography. If unsure, omit.
- Empty lists are fine when the talk was small talk.
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_json_object(text: str) -> Optional[dict]:
    if not text:
        return None
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _clean_strings(raw: object, *, cap: int, max_len: int) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = " ".join(str(item).split())
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text[:max_len])
        if len(out) >= cap:
            break
    return out


def format_portrait_for_prompt(profile: Optional[dict]) -> str:
    """Turn a cached personality_profiles document into twin prompt text.

    Omits Big Five scores — too clinical for a grandmother-simple voice.
    """
    if not isinstance(profile, dict):
        return ""
    parts: list[str] = []
    tone_raw = profile.get("voice_tone")
    tone = tone_raw if isinstance(tone_raw, dict) else {}
    description = str(tone.get("description") or "").strip()
    if description:
        parts.append(description)
    phrases = [
        str(p).strip()
        for p in (tone.get("signature_phrases") or [])
        if str(p).strip()
    ]
    if phrases:
        quoted = ", ".join(f'"{p}"' for p in phrases[:MAX_SIGNATURE_PHRASES])
        parts.append(f"You often say: {quoted}")
    values = [
        str(v).strip()
        for v in (profile.get("top_values") or [])
        if str(v).strip()
    ]
    if values:
        parts.append("What matters to you: " + ", ".join(values[:6]))
    summary = str(profile.get("summary") or "").strip()
    if summary:
        parts.append(summary)
    return "\n".join(parts)


def render_twin_voice_section(voice_blob: str) -> str:
    blob = (voice_blob or "").strip()
    if not blob:
        return ""
    return (
        "\n\n=== HOW YOU SOUND ===\n"
        f"{blob}\n"
        "Stay in this voice. If a later memory fact contradicts this, the newer fact wins.\n"
    )


def parse_council_reply(text: str) -> dict[str, list[str]]:
    parsed = _extract_json_object(text) or {}
    return {
        "phrases": _clean_strings(parsed.get("phrases"), cap=6, max_len=80),
        "beliefs": _clean_strings(parsed.get("beliefs"), cap=4, max_len=220),
        "corrections": _clean_strings(parsed.get("corrections"), cap=4, max_len=220),
    }


def merge_signature_phrases(
    existing: list[str] | None,
    incoming: list[str] | None,
    *,
    cap: int = MAX_SIGNATURE_PHRASES,
) -> list[str]:
    """Prefer freshly heard phrases, then keep older ones, de-duped."""
    out: list[str] = []
    seen: set[str] = set()

    def add(raw: object) -> None:
        text = " ".join(str(raw).split())
        if not text or len(text) > 80:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(text)

    for phrase in incoming or []:
        add(phrase)
        if len(out) >= cap:
            return out[:cap]
    for phrase in existing or []:
        add(phrase)
        if len(out) >= cap:
            return out[:cap]
    return out


def should_run_council(
    *,
    cheap_kind: str,
    new_message_count: int,
    user_turn_count: int,
    threshold: int = VOICE_COUNCIL_AFTER_MESSAGES,
) -> bool:
    if cheap_kind == "local":
        return False
    if new_message_count < threshold:
        return False
    if user_turn_count < 2:
        return False
    return True


def build_council_user_payload(
    messages: list[dict],
    known_phrases: list[str] | None = None,
) -> str:
    lines: list[str] = []
    phrases = [str(p).strip() for p in (known_phrases or []) if str(p).strip()]
    if phrases:
        lines.append("Phrases already captured:")
        for phrase in phrases[:MAX_SIGNATURE_PHRASES]:
            lines.append(f"- {phrase}")
        lines.append("")
    lines.append(
        "Recent talk (USER is the person; ASSISTANT is their twin — extract from USER):"
    )
    for message in messages:
        role = str(message.get("role") or "user").upper()
        if role not in ("USER", "ASSISTANT"):
            continue
        content = str(message.get("content") or "").strip()[:1500]
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)[:12000]


def plan_voice_updates(
    notes: dict,
    *,
    existing_facts: list[dict],
    existing_phrases: list[str] | None,
) -> dict[str, list]:
    seen = {
        str(fact.get("fact") or "").strip().lower()
        for fact in existing_facts
        if isinstance(fact, dict)
    }
    new_facts: list[dict[str, str]] = []

    def add_fact(text: object, kind: str) -> None:
        fact = " ".join(str(text).split())
        if not fact:
            return
        key = fact.lower()
        if key in seen:
            return
        seen.add(key)
        new_facts.append({"fact": fact[:280], "kind": kind})

    for phrase in notes.get("phrases") or []:
        add_fact(f'They often say: "{phrase}"', "phrase")
    for belief in notes.get("beliefs") or []:
        add_fact(belief, "belief")
    for correction in notes.get("corrections") or []:
        add_fact(correction, "belief")

    return {
        "facts": new_facts[:MAX_NEW_FACTS],
        "phrases": merge_signature_phrases(existing_phrases, notes.get("phrases") or []),
    }


async def maybe_run_voice_council(user_id: str, conversation_id: str) -> Optional[dict]:
    """After a twin turn is saved. Best-effort; never raises to the caller."""
    from deps import db
    from services.model_runtime import complete_text, resolve_runtime

    conv = await db.conversations.find_one(
        {"conversation_id": conversation_id, "user_id": user_id},
        {"_id": 0, "messages": 1, "voice_council_through": 1},
    )
    if not conv:
        return None
    messages = conv.get("messages") or []
    through = int(conv.get("voice_council_through") or 0)
    if through < 0:
        through = 0
    new_messages = messages[through:]
    user_turns = [
        m for m in new_messages
        if m.get("role") == "user" and str(m.get("content") or "").strip()
    ]
    try:
        cheap = await resolve_runtime(user_id, "cheap")
    except Exception:  # noqa: BLE001
        return None
    if not should_run_council(
        cheap_kind=str(cheap.get("kind") or ""),
        new_message_count=len(new_messages),
        user_turn_count=len(user_turns),
    ):
        return None

    profile = await db.personality_profiles.find_one({"user_id": user_id}, {"_id": 0})
    tone = (profile or {}).get("voice_tone") if isinstance(profile, dict) else {}
    existing_phrases = list((tone or {}).get("signature_phrases") or [])
    payload = build_council_user_payload(new_messages[-16:], existing_phrases)
    if not payload.strip():
        return None
    try:
        raw, _resolved = await complete_text(
            user_id,
            "cheap",
            session_id=f"voice_council_{conversation_id}_{len(messages)}",
            system_message=VOICE_COUNCIL_SYSTEM,
            user_text=payload,
        )
    except Exception:  # noqa: BLE001
        return None

    notes = parse_council_reply(raw)
    existing_facts = await db.memory_facts.find(
        {"user_id": user_id}, {"_id": 0, "fact": 1}
    ).to_list(length=200)
    plan = plan_voice_updates(
        notes,
        existing_facts=existing_facts,
        existing_phrases=existing_phrases,
    )
    now = _now_iso()
    for fact in plan["facts"]:
        await db.memory_facts.insert_one({
            "fact_id": f"fact_{uuid.uuid4().hex[:10]}",
            "user_id": user_id,
            "fact": fact["fact"],
            "kind": fact["kind"],
            "source": "voice_council",
            "source_entry_id": None,
            "created_at": now,
        })

    if profile is not None and plan["phrases"] != existing_phrases:
        voice_tone = dict(profile.get("voice_tone") or {})
        voice_tone["signature_phrases"] = plan["phrases"]
        await db.personality_profiles.update_one(
            {"user_id": user_id},
            {"$set": {"voice_tone": voice_tone, "voice_council_at": now}},
        )

    await db.conversations.update_one(
        {"conversation_id": conversation_id, "user_id": user_id},
        {"$set": {"voice_council_through": len(messages)}},
    )
    return {
        "facts_added": len(plan["facts"]),
        "phrases": plan["phrases"],
    }
