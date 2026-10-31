"""Owner talking-style profile. Local Ollama only. Heirs never see it.

Built from owner lines already saved by twin_runtime._persist_pair. Updated
incrementally: a handful of new lines are folded into the stored profile
instead of re-reading the whole archive every turn.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

STYLE_KEYS = (
    "word_choice",
    "sentence_length",
    "punctuation",
    "casing",
    "deliberate_typos",
    "humor",
    "opens",
    "closes",
    "skips",
    "topics",
)

FIELD_LIMIT = 600
PENDING_LIMIT = 24
REFRESH_EVERY = 4

LoadFn = Callable[[str], Awaitable[dict]]
SaveFn = Callable[[str, dict], Awaitable[None]]
CompleteFn = Callable[[str, str], Awaitable[str]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def empty_profile() -> dict[str, Any]:
    profile: dict[str, Any] = {key: "" for key in STYLE_KEYS}
    profile["sample_count"] = 0
    profile["pending"] = []
    profile["updated_at"] = ""
    return profile


def _clip(value: Any) -> str:
    return str(value or "").strip()[:FIELD_LIMIT]


def parse_model_json(raw: str) -> Optional[dict[str, str]]:
    """Pull the style object out of an Ollama reply. Unknown keys are dropped."""
    text = (raw or "").strip()
    if not text:
        return None
    fence = re.search(r"\{.*\}", text, re.DOTALL)
    if fence:
        text = fence.group(0)
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, dict):
        return None
    found = {key: _clip(loaded.get(key)) for key in STYLE_KEYS if _clip(loaded.get(key))}
    return found or None


def merge_profile(previous: Optional[dict], update: Optional[dict], *, added: int) -> dict[str, Any]:
    """Keep prior lines when the model leaves a field blank. Count the new samples."""
    base = empty_profile()
    if previous:
        for key in STYLE_KEYS:
            base[key] = _clip(previous.get(key))
        try:
            base["sample_count"] = int(previous.get("sample_count") or 0)
        except (TypeError, ValueError):
            base["sample_count"] = 0
    if update:
        for key in STYLE_KEYS:
            incoming = _clip(update.get(key))
            if incoming:
                base[key] = incoming
    base["sample_count"] = max(0, int(base["sample_count"])) + max(0, int(added))
    base["pending"] = []
    base["updated_at"] = _now()
    return base


def owner_lines(messages: list[dict], *, limit: int = 12) -> list[str]:
    lines: list[str] = []
    for message in messages or []:
        if str(message.get("role") or "") != "user":
            continue
        text = str(message.get("content") or "").strip()
        if text:
            lines.append(text[:800])
    return lines[-limit:]


def analysis_prompt(profile: dict, lines: list[str]) -> tuple[str, str]:
    system = (
        "You describe how this owner writes. Reply with one JSON object and no other text. "
        "Keys: word_choice, sentence_length, punctuation, casing, deliberate_typos, humor, "
        "opens, closes, skips, topics. "
        "Cover word choice, typical sentence length, punctuation and casing, deliberate typos, "
        "humor, how he opens and closes, what he skips, and topics he likes. "
        "Keep each value under 80 words. Do not invent biography, dates, names, or advice. "
        "This is style, not a memory. Stay on the messages given. "
        "Keep an owner-edited line unless the new messages clearly change it."
    )
    prior = {key: profile.get(key) or "" for key in STYLE_KEYS}
    user = (
        "Current profile:\n"
        + json.dumps(prior, ensure_ascii=True)
        + "\n\nNew owner messages:\n"
        + "\n".join(f"- {line}" for line in lines)
    )
    return system, user


def needs_model(pending_count: int, *, force: bool = False) -> bool:
    if pending_count <= 0:
        return False
    if force:
        return True
    return pending_count >= REFRESH_EVERY


def fold_pending(profile: Optional[dict], lines: list[str], model_json: Optional[str]) -> dict[str, Any]:
    base = empty_profile()
    if profile:
        base.update({key: _clip(profile.get(key)) for key in STYLE_KEYS})
        base["sample_count"] = int(profile.get("sample_count") or 0)
        base["pending"] = list(profile.get("pending") or [])
        base["updated_at"] = profile.get("updated_at") or ""
    pending = [str(item).strip() for item in base["pending"] if str(item).strip()]
    for line in lines:
        text = (line or "").strip()
        if text:
            pending.append(text[:800])
    pending = pending[-PENDING_LIMIT:]
    parsed = parse_model_json(model_json or "")
    if parsed is None:
        base["pending"] = pending
        return base
    merged = merge_profile(base, parsed, added=len(pending))
    merged["pending"] = []
    return merged


def style_register_block(profile: Optional[dict], *, audience: str) -> str:
    """Persona-register text for the owner. Heirs and callers get nothing."""
    from owner_pairing import is_owner_audience

    if not is_owner_audience(audience) or not profile:
        return ""
    lines = []
    labels = {
        "word_choice": "Word choice",
        "sentence_length": "Sentence length",
        "punctuation": "Punctuation",
        "casing": "Casing",
        "deliberate_typos": "Deliberate typos",
        "humor": "Humor",
        "opens": "How he opens",
        "closes": "How he closes",
        "skips": "What he skips",
        "topics": "Topics he likes",
    }
    for key, label in labels.items():
        value = _clip(profile.get(key))
        if value:
            lines.append(f"- {label}: {value}")
    if not lines:
        return ""
    return (
        "HOW THIS OWNER TALKS (style only — do not recite it, and do not treat it as biography):\n"
        + "\n".join(lines)
    )


def public_profile(profile: Optional[dict]) -> dict[str, Any]:
    base = empty_profile()
    if profile:
        for key in STYLE_KEYS:
            base[key] = _clip(profile.get(key))
        try:
            base["sample_count"] = int(profile.get("sample_count") or 0)
        except (TypeError, ValueError):
            base["sample_count"] = 0
        base["updated_at"] = str(profile.get("updated_at") or "")
        base["pending_count"] = len(profile.get("pending") or [])
    else:
        base["pending_count"] = 0
    base.pop("pending", None)
    return base


def apply_owner_edit(previous: Optional[dict], fields: dict) -> dict[str, Any]:
    """Owner edits win, including a cleared field. Sample count stays put."""
    merged = empty_profile()
    if previous:
        try:
            merged["sample_count"] = int(previous.get("sample_count") or 0)
        except (TypeError, ValueError):
            merged["sample_count"] = 0
        merged["pending"] = list(previous.get("pending") or [])
    for key in STYLE_KEYS:
        if key in fields:
            merged[key] = _clip(fields.get(key))
        elif previous:
            merged[key] = _clip(previous.get(key))
    merged["updated_at"] = _now()
    return merged


async def note_owner_line(
    user_id: str,
    text: str,
    *,
    load: LoadFn,
    save: SaveFn,
    complete: CompleteFn,
    force: bool = False,
) -> dict[str, Any]:
    profile = await load(user_id) or empty_profile()
    pending = [str(item).strip() for item in (profile.get("pending") or []) if str(item).strip()]
    line = (text or "").strip()
    if line:
        pending.append(line[:800])
    pending = pending[-PENDING_LIMIT:]
    profile = dict(profile)
    profile["pending"] = pending
    if not needs_model(len(pending), force=force):
        await save(user_id, profile)
        return profile
    system, user = analysis_prompt(profile, pending)
    try:
        raw = await complete(system, user)
    except Exception:
        await save(user_id, profile)
        return profile
    updated = fold_pending(profile, [], raw)
    if parse_model_json(raw) is None:
        updated["pending"] = pending
    await save(user_id, updated)
    return updated


async def profile_for_prompt(user_id: str) -> Optional[dict]:
    doc = await _load_doc(user_id)
    if not doc:
        return None
    if not any(_clip(doc.get(key)) for key in STYLE_KEYS):
        return None
    return doc


async def _load_doc(user_id: str) -> dict:
    from deps import db

    found = await db.owner_style.find_one({"user_id": user_id}, {"_id": 0})
    return found or {}


async def _save_doc(user_id: str, profile: dict) -> None:
    from deps import db

    stored = {key: profile.get(key) for key in (*STYLE_KEYS, "sample_count", "pending", "updated_at")}
    stored["user_id"] = user_id
    await db.owner_style.update_one({"user_id": user_id}, {"$set": stored}, upsert=True)


async def complete_local(system: str, user: str) -> str:
    """Ollama on this machine. Never a cloud chat completion."""
    from local_inference import ollama_chat

    return await ollama_chat(
        system,
        [{"role": "user", "content": user}],
        timeout=60,
    )


def schedule_owner_line(user_id: str, text: str) -> None:
    cleaned = (text or "").strip()
    if not user_id or not cleaned:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_safe_note(user_id, cleaned))


async def _safe_note(user_id: str, text: str) -> None:
    try:
        await note_owner_line(
            user_id,
            text,
            load=_load_doc,
            save=_save_doc,
            complete=complete_local,
        )
    except Exception:
        return
