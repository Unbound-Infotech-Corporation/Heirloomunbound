"""'Would C L say that?' — owner cases scored on this machine.

Cases are prompts plus reference replies drawn from saved owner
conversations and the style profile. The runner asks a chosen local brain,
then scores style with the local embedding and factual consistency with a
local judge model. Results go to Mongo. No cloud model is called.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from memory_guard import cosine_unit, embed_local
from owner_style import STYLE_KEYS

CompleteFn = Callable[[str], Awaitable[str]]
JudgeFn = Callable[[str, str, str], Awaitable[tuple[float, str]]]

JUDGE_SYSTEM = (
    "You score factual consistency using only the reference reply. "
    "Do not use outside knowledge. Do not add facts. "
    'Reply with JSON {"score": number from 0 to 1, "note": "short"}. '
    "Score 1 when the candidate does not contradict the reference. "
    "Score 0 when it states a conflicting fact."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip(text: str, limit: int) -> str:
    return str(text or "").strip()[:limit]


def cases_from_messages(messages: list[dict], *, limit: int = 12) -> list[dict]:
    """Pair each owner line with the assistant reply that followed it."""
    found: list[dict] = []
    pending: Optional[str] = None
    for message in messages or []:
        role = str(message.get("role") or "")
        content = _clip(message.get("content") or "", 1200)
        if role == "user" and content:
            pending = content[:800]
            continue
        if role == "assistant" and pending and content:
            found.append({
                "prompt": pending,
                "reference": content[:1200],
                "source": "conversation",
            })
            pending = None
            if len(found) >= limit:
                break
    return found


def case_from_style(profile: Optional[dict]) -> Optional[dict]:
    if not isinstance(profile, dict):
        return None
    bits: list[str] = []
    for key in STYLE_KEYS:
        value = _clip(profile.get(key) or "", 400)
        if value:
            bits.append(f"{key}: {value}")
    if not bits:
        return None
    return {
        "prompt": "Say hello the way you usually would.",
        "reference": " ".join(bits)[:1200],
        "source": "style",
    }


def style_text(profile: Optional[dict]) -> str:
    row = case_from_style(profile)
    if not row:
        return ""
    return str(row.get("reference") or "")


def selectable_conversations(conversations: list[dict]) -> list[dict]:
    """Owner threads only. Heir portal ids are not reference material."""
    rows: list[dict] = []
    for conv in conversations or []:
        cid = str(conv.get("conversation_id") or "")
        if cid.startswith("heir_"):
            continue
        audience = str(conv.get("audience") or "owner").strip().lower() or "owner"
        if audience not in {"owner", ""}:
            continue
        rows.extend(list(conv.get("messages") or []))
    return rows


def style_score(reply: str, reference: str, profile_text: str = "") -> float:
    reply_vec = embed_local(reply)
    reference_score = cosine_unit(reply_vec, embed_local(reference))
    if (profile_text or "").strip():
        profile_score = cosine_unit(reply_vec, embed_local(profile_text))
        return round(0.7 * reference_score + 0.3 * profile_score, 4)
    return round(reference_score, 4)


def parse_judge(raw: str) -> tuple[float, str]:
    text = (raw or "").strip()
    if not text:
        return 0.0, "judge did not answer"
    fence = re.search(r"\{.*\}", text, re.DOTALL)
    if fence:
        text = fence.group(0)
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return 0.0, "judge did not answer"
    if not isinstance(loaded, dict):
        return 0.0, "judge did not answer"
    try:
        score = float(loaded.get("score"))
    except (TypeError, ValueError):
        return 0.0, "judge did not answer"
    if score < 0.0:
        score = 0.0
    if score > 1.0:
        score = 1.0
    note = _clip(loaded.get("note") or "", 240)
    return round(score, 4), note


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


async def execute_run(
    cases: list[dict],
    *,
    brain: str,
    complete: CompleteFn,
    judge: JudgeFn,
    profile_text: str = "",
    model: str = "",
) -> dict[str, Any]:
    """Score one brain. `complete` and `judge` are local callables."""
    name = (brain or "").strip().lower()
    if name not in {"local", "remote"}:
        raise ValueError("Brain must be local or remote")
    rows: list[dict] = []
    for case in cases or []:
        prompt = _clip(case.get("prompt") or "", 800)
        reference = _clip(case.get("reference") or "", 1200)
        if not prompt or not reference:
            continue
        try:
            reply = _clip(await complete(prompt), 2000)
        except Exception as exc:  # noqa: BLE001
            rows.append({
                "case_id": case.get("case_id") or "",
                "prompt": prompt,
                "style": 0.0,
                "factual": 0.0,
                "note": f"brain did not answer: {type(exc).__name__}",
                "reply": "",
            })
            continue
        try:
            factual, note = await judge(prompt, reference, reply)
        except Exception:  # noqa: BLE001
            factual, note = 0.0, "judge did not answer"
        rows.append({
            "case_id": case.get("case_id") or "",
            "prompt": prompt,
            "style": style_score(reply, reference, profile_text),
            "factual": factual,
            "note": note,
            "reply": reply,
        })
    return {
        "run_id": f"wsr_{uuid.uuid4().hex[:12]}",
        "brain": name,
        "model": model,
        "created_at": _now(),
        "mean_style": _mean([float(row["style"]) for row in rows]),
        "mean_factual": _mean([float(row["factual"]) for row in rows]),
        "cases": rows,
    }


def local_only_reason() -> Optional[str]:
    from llm_provider import box_mode, uses_ollama

    if box_mode() or uses_ollama():
        return None
    return "Would-say runs on local Ollama only"


def judge_user(prompt: str, reference: str, reply: str) -> str:
    return (
        f"Prompt:\n{prompt}\n\n"
        f"Reference reply:\n{reference}\n\n"
        f"Candidate reply:\n{reply}\n"
    )
