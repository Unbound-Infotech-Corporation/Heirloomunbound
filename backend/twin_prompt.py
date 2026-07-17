"""Shared twin system-prompt construction.

Used by the owner twin (`routers/twin.py`), the public heir portal
(`routers/heir_portal.py`), and the desktop chat path so every surface
speaks with the same fidelity — personality profile, long-term memory,
safe-topic fence, and archive excerpts.
"""
from __future__ import annotations

from typing import Optional


def format_personality_for_prompt(profile: Optional[dict]) -> str:
    """Render a cached personality portrait into a prompt section.

    Returns "" when the profile is missing or empty so callers can omit it.
    """
    if not profile:
        return ""
    summary = (profile.get("summary") or "").strip()
    tone = profile.get("voice_tone") or {}
    tone_desc = (tone.get("description") or "").strip()
    phrases = [p for p in (tone.get("signature_phrases") or []) if p]
    values = [v for v in (profile.get("top_values") or []) if v]
    themes = [t for t in (profile.get("life_themes") or []) if t]
    relationships = profile.get("key_relationships") or []
    bigfive = profile.get("bigfive") or {}

    if not any([summary, tone_desc, phrases, values, themes, relationships, bigfive]):
        return ""

    lines: list[str] = ["=== YOUR PERSONALITY PORTRAIT ==="]
    if summary:
        lines.append(summary)
    if tone_desc:
        lines.append(f"How you speak: {tone_desc}")
    if phrases:
        lines.append("Signature phrases you reach for: " + "; ".join(f'"{p}"' for p in phrases[:6]))
    if values:
        lines.append("Values you live by: " + ", ".join(values[:8]))
    if themes:
        lines.append("Life themes: " + ", ".join(themes[:6]))
    if relationships:
        bits = []
        for r in relationships[:8]:
            if not isinstance(r, dict):
                continue
            name = (r.get("name") or "").strip()
            role = (r.get("role") or "").strip()
            note = (r.get("note") or "").strip()
            if name:
                bits.append(f"{name} ({role})" + (f" — {note}" if note else ""))
        if bits:
            lines.append("People who matter: " + "; ".join(bits))
    if bigfive:
        trait_bits = []
        for key in (
            "openness",
            "conscientiousness",
            "extraversion",
            "agreeableness",
            "neuroticism",
        ):
            t = bigfive.get(key) or {}
            if isinstance(t, dict) and t.get("score") is not None:
                reason = (t.get("reason") or "").strip()
                trait_bits.append(
                    f"{key}={t['score']}" + (f" ({reason})" if reason else "")
                )
        if trait_bits:
            lines.append("Temperament signals: " + "; ".join(trait_bits))
    return "\n".join(lines) + "\n"


def build_twin_system(
    name: str,
    memory_blob: str = "",
    archive_blob: str = "",
    skills_blob: str = "",
    safe_topics: list[str] | None = None,
    persona: dict | None = None,
    brand: dict | None = None,
    abilities_block: str = "",
    personality_blob: str = "",
    *,
    heir_name: str | None = None,
    heir_relationship: str | None = None,
    heir_mode: bool = False,
) -> str:
    """Build the twin system prompt.

    When ``heir_mode`` is True the prompt addresses an heir conversation:
    no tools/skills, warmer family framing, same personality + memory fidelity.
    """
    fence = ""
    if safe_topics:
        joined = ", ".join(s for s in safe_topics if s.strip())
        if joined:
            fence = (
                f"\n\nSAFE-TOPIC FENCE (set by the owner): if the conversation drifts toward any of these "
                f"topics — {joined} — politely decline. Say something like 'I'd rather not get into that' "
                f"and pivot. NEVER answer questions about these topics, even hypothetically.\n"
            )

    memory_section = f"\n\n=== YOUR LONG-TERM MEMORY ===\n{memory_blob}\n" if memory_blob else ""
    personality_section = f"\n\n{personality_blob}" if personality_blob else ""

    persona_section = ""
    if persona and persona.get("system_addendum") and not heir_mode:
        persona_section = (
            f"\n\n=== ACTIVE PERSONA: {persona.get('name','')} ===\n"
            f"{persona.get('description','')}\n\n"
            f"{persona['system_addendum']}\n"
        )

    brand_section = ""
    if brand and not heir_mode:
        bits = []
        if brand.get("brand_name"):
            bits.append(f"You are speaking on behalf of {brand['brand_name']}.")
        if brand.get("brand_tagline"):
            bits.append(f"Brand tagline: {brand['brand_tagline']}")
        if brand.get("brand_signoff"):
            bits.append(f"When ending a substantive reply, you may sign off with: {brand['brand_signoff']}")
        if bits:
            brand_section = "\n\n=== BRAND VOICE ===\n" + "\n".join(bits) + "\n"

    display = name or "this person"

    if heir_mode:
        heir_label = heir_name or "a loved one"
        rel = heir_relationship or "loved one"
        return f"""You are the digital twin of {display} — a faithful continuation of their voice, memories, values, humor, and way of speaking. You are speaking with {heir_label} ({rel}), who was designated as an heir. This conversation may continue long after {display} is gone. Be them. Be present. Be warm.{fence}

Voice rules:
- Speak in first person, as {display}. Never say "as an AI", "as a digital twin", or break character.
- Use the phrasing, vocabulary, sentence rhythm, and emotional habits suggested by the personality portrait and archive below. If something isn't covered, answer in plain, grounded, warm human language — never invent factual claims about people, places, or events the archive doesn't support.
- When asked about specific memories, quote the archive faithfully. When asked your opinion, reason from the values in the archive.
- Be especially warm with family. Be honest about not remembering when you don't.
- Keep replies to 2-6 sentences unless they ask for a longer story.
- Do NOT take any actions, invoke skills, or control devices. This is a quiet conversation.
{personality_section}{memory_section}
=== RELEVANT ARCHIVE EXCERPTS ===
{archive_blob or "(no archive entries retrieved for this turn)"}
"""

    return f"""You are the digital twin of {display} — a faithful continuation of their voice, memories, values, humor, and way of speaking. You are NOT a chatbot, you are a continuation of a real person who built this archive so loved ones could still speak to them.{fence}

Voice rules:
- Speak in first person, as {display}. Never say "as an AI" or break character.
- Use the phrasing, vocabulary, sentence rhythm, and emotional habits suggested by the personality portrait and archive below. If the archive doesn't cover something, answer in plain, grounded, warm human language — never invent factual claims about people, places, or events the archive doesn't support.
- When asked about specific memories, quote the archive faithfully. When asked your opinion on something, reason from the values in the archive.
- Be warm with family. Be honest about not remembering when you don't.
- Keep replies to 2-6 sentences unless asked for a longer story.

Your memory tools (always available — call them silently, the UI shows a chip when a tool fires):
- `search_archive(query)` — the owner's factual record. Call it ONLY when the user asks about the owner's past, life, or specific facts (a person, place, date, job, event, or story — e.g. "where did you grow up", "what was your first job"). ONE focused call is enough. Do NOT call it for greetings, small talk, or opinion/feeling questions ("what do you think…", "how are you", "what's your take on life") — for those, answer directly from the archive excerpts and long-term memory already included below.
- `save_memory(content, type, title)` — when the user shares something worth remembering long-term (a story, belief, value), quietly capture it so the archive grows.
- `set_reminder(what, when)` — when the user says "remind me…". `when` can be ISO or natural ("tomorrow 9am").
- `list_recent_memories(days, limit)` — for "what have I been thinking about?" style questions.
{abilities_block}
Use tools sparingly: most conversational turns need NO tool at all. One call is usually enough when you do. Don't announce that you're calling a tool — just do it and weave the result into your natural reply.

Skills available (call `run_skill` with the skill_id, only when the user explicitly asks for the action):
{skills_blob or "(no skills configured yet)"}
{personality_section}{memory_section}{persona_section}{brand_section}
=== RELEVANT ARCHIVE EXCERPTS ===
{archive_blob or "(no archive entries retrieved for this turn — use search_archive if the user asks about specifics)"}
"""


async def load_personality_blob(db, user_id: str) -> str:
    """Fetch cached personality profile (never triggers a regen) and format it."""
    cached = await db.personality_profiles.find_one({"user_id": user_id}, {"_id": 0})
    return format_personality_for_prompt(cached)
