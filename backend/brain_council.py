"""Local answer strategies for the big-brain layer.

The live path in ``brain_route`` still picks one Ollama (BIGDEAL
``llama3.3:70b`` when ``HEIRLOOM_BRAIN_URL`` answers, otherwise the box
``qwen2.5:14b``). There is no council in that layer. This module is the
bake-off switch:

* ``single`` — one model. Default until the bake-off lands.
* ``single+odysseus_research`` — that one model, plus Odysseus Deep
  Research when the question needs current information.
* ``ensemble_synthesis`` — for hard or owner questions, fan out to
  BIGDEAL, the box, and Odysseus, then the primary local model writes
  the answer. Simple chat stays on the single model.
* ``judge_pick_best`` — the same fan-out, then the primary model picks
  one draft and that draft is the answer.

Odysseus receives the question only. Vault memories stay on the local
Ollama prompts, which ``memory_guard`` already trimmed for the audience.
"""
from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Optional

logger = logging.getLogger(__name__)

STRATEGIES = (
    "single",
    "single+odysseus_research",
    "ensemble_synthesis",
    "judge_pick_best",
)
DEFAULT_STRATEGY = "single"
_ALIASES = {
    "single": "single",
    "single+odysseus_research": "single+odysseus_research",
    "single_odysseus_research": "single+odysseus_research",
    "odysseus_research": "single+odysseus_research",
    "ensemble": "ensemble_synthesis",
    "ensemble_synthesis": "ensemble_synthesis",
    "judge": "judge_pick_best",
    "judge_pick_best": "judge_pick_best",
}
_SIMPLE = frozenset({
    "hi",
    "hey",
    "hello",
    "thanks",
    "thank you",
    "ok",
    "okay",
    "yes",
    "no",
    "good morning",
    "good night",
    "good evening",
    "how are you",
    "how's it going",
})
_RESEARCH_CUES = (
    "latest",
    "current",
    "right now",
    "today",
    "this week",
    "news",
    "look up",
    "lookup",
    "research",
    "who won",
    "weather",
    "find out",
    "what happened",
    "search for",
    "according to",
)
_HARD_PREFIXES = (
    "why ",
    "how ",
    "explain ",
    "compare ",
    "what's the difference",
    "what is the difference",
)
_PICK_RE = re.compile(r"\bPICK:\s*(bigdeal|box|odysseus)\b", re.IGNORECASE)
_ORDER = ("bigdeal", "odysseus", "box")
DRAFT_TIMEOUT = 35.0

AskFn = Callable[[str, str, float], Awaitable[Any]]

_snapshot: dict[str, Any] = {}


@dataclass
class BrainDraft:
    name: str
    model: str = ""
    text: str = ""
    ok: bool = False
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    error: str = ""
    latency_ms: int = 0
    via: str = ""


@dataclass
class TurnOutcome:
    text: str
    meta: dict[str, Any]
    label: str

    def public(self) -> dict[str, Any]:
        return dict(self.meta)


def normalize_strategy(raw: str, *, strict: bool = False) -> str:
    text = (raw or "").strip().lower()
    if not text:
        if strict:
            return ""
        return DEFAULT_STRATEGY
    found = _ALIASES.get(text)
    if found:
        return found
    if strict:
        raise ValueError(
            "Strategy must be single, single+odysseus_research, ensemble_synthesis, or judge_pick_best."
        )
    logger.error("HEIRLOOM_BRAIN_STRATEGY %s is unknown; using single", text)
    return DEFAULT_STRATEGY


def strategy_from_env() -> str:
    return normalize_strategy(os.environ.get("HEIRLOOM_BRAIN_STRATEGY") or "", strict=False)


def is_simple_chat(text: str) -> bool:
    cleaned = " ".join((text or "").lower().replace("?", " ").replace("!", " ").replace(".", " ").split())
    if not cleaned:
        return True
    if cleaned in _SIMPLE:
        return True
    words = cleaned.split()
    return len(words) <= 3 and "?" not in (text or "")


def needs_research(text: str) -> bool:
    lowered = (text or "").lower()
    return any(cue in lowered for cue in _RESEARCH_CUES)


def is_hard_question(text: str) -> bool:
    if needs_research(text):
        return True
    cleaned = " ".join((text or "").split())
    if len(cleaned.split()) >= 16:
        return True
    return cleaned.lower().startswith(_HARD_PREFIXES)


def needs_fanout(question: str, audience: str, strategy: str) -> bool:
    if strategy not in {"ensemble_synthesis", "judge_pick_best"}:
        return False
    if is_simple_chat(question):
        return False
    from memory_guard import retrieval_audience
    from owner_pairing import is_owner_audience

    if is_owner_audience(retrieval_audience(audience)):
        return True
    return needs_research(question) or is_hard_question(question)


def clear_answer_meta() -> None:
    _snapshot.clear()


def health_overlay() -> dict[str, Any]:
    """Cached strategy and last answer. Does not open a socket."""
    from odysseus_client import odysseus_from_env, public_odysseus

    if _snapshot:
        return {
            "strategy": _snapshot.get("strategy") or DEFAULT_STRATEGY,
            "answer": dict(_snapshot.get("answer") or {}),
            "odysseus": dict(_snapshot.get("odysseus") or {}),
        }
    strategy = strategy_from_env()
    odysseus = public_odysseus(odysseus_from_env())
    return {
        "strategy": strategy,
        "answer": {
            "strategy": strategy,
            "contributors": [],
            "latency_ms": 0,
            "path": "",
            "picked": "",
            "skipped": [],
        },
        "odysseus": odysseus,
    }


def note_health(strategy: str, odysseus_view: Mapping[str, Any], answer: Optional[Mapping[str, Any]] = None) -> None:
    current = dict(_snapshot.get("answer") or {})
    if answer is not None:
        current = dict(answer)
    elif not current:
        current = {
            "strategy": strategy,
            "contributors": [],
            "latency_ms": 0,
            "path": "",
            "picked": "",
            "skipped": [],
        }
    _snapshot["strategy"] = strategy or DEFAULT_STRATEGY
    _snapshot["answer"] = current
    _snapshot["odysseus"] = dict(odysseus_view)


def _contributor(draft: BrainDraft) -> dict[str, Any]:
    row = {"name": draft.name, "model": draft.model or draft.name, "latency_ms": max(0, int(draft.latency_ms))}
    if draft.via:
        row["via"] = draft.via
    return row


def _meta(
    strategy: str,
    drafts: list[BrainDraft],
    *,
    latency_ms: int,
    path: str,
    picked: str = "",
    skipped: Optional[list[str]] = None,
) -> dict[str, Any]:
    contributors = [_contributor(draft) for draft in drafts if draft.ok and draft.text.strip()]
    row: dict[str, Any] = {
        "strategy": strategy,
        "contributors": contributors,
        "latency_ms": max(0, int(latency_ms)),
        "path": path,
        "picked": picked,
        "skipped": list(skipped or []),
    }
    return row


def _label(strategy: str, path: str, names: list[str]) -> str:
    from brain_route import brain_label

    if path == "fast" and strategy == DEFAULT_STRATEGY:
        return brain_label()
    shown = ", ".join(names) or "local"
    return f"{strategy} · {shown}"


def _remember(draft: Optional[BrainDraft], meta: Mapping[str, Any], odysseus_view: Mapping[str, Any]) -> None:
    from brain_route import remember_answer

    if draft is not None and draft.url:
        route_name = "remote" if draft.name == "bigdeal" else "local" if draft.name == "box" else draft.name
        remember_answer(name=route_name, model=draft.model, url=draft.url)
    note_health(str(meta.get("strategy") or DEFAULT_STRATEGY), odysseus_view, meta)


async def configured_strategy() -> str:
    from brain_route import load_saved_settings

    saved = await load_saved_settings()
    if isinstance(saved, Mapping) and str(saved.get("strategy") or "").strip():
        return normalize_strategy(str(saved.get("strategy") or ""), strict=False)
    return strategy_from_env()


async def _settings_pair():
    from brain_route import current_settings, load_saved_settings
    from odysseus_client import merge_odysseus, odysseus_from_env, public_odysseus

    saved = await load_saved_settings()
    odysseus = merge_odysseus(odysseus_from_env(), saved if isinstance(saved, Mapping) else None)
    return await current_settings(), odysseus, public_odysseus(odysseus)


async def _single(messages: list[dict], *, base_url: Optional[str], poster: Any, timeout: float) -> BrainDraft:
    from llm_provider import complete_openai_chat

    started = time.perf_counter()
    completed = await complete_openai_chat(
        messages,
        base_url=base_url,
        poster=poster,
        timeout=timeout,
    )
    from brain_route import last_answer

    row = last_answer()
    route_name = row.get("name") or "local"
    name = "bigdeal" if route_name == "remote" else "box"
    return BrainDraft(
        name=name,
        model=completed.model or row.get("model") or "",
        text=completed.text,
        ok=bool(completed.text),
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


async def _pinned(
    name: str,
    url: str,
    model: str,
    headers: Mapping[str, str],
    messages: list[dict],
    *,
    poster: Any,
    timeout: float,
) -> BrainDraft:
    from llm_provider import complete_openai_chat

    started = time.perf_counter()
    try:
        completed = await complete_openai_chat(
            messages,
            model=model,
            base_url=url,
            pin_host=True,
            headers=headers,
            poster=poster,
            timeout=timeout,
        )
    except Exception as exc:
        logger.warning("%s draft failed: %s", name, type(exc).__name__)
        return BrainDraft(name=name, model=model, url=url, error=type(exc).__name__)
    text = (completed.text or "").strip()
    return BrainDraft(
        name=name,
        model=completed.model or model,
        text=text,
        ok=bool(text),
        url=url,
        headers=dict(headers),
        latency_ms=int((time.perf_counter() - started) * 1000),
        error="" if text else "empty",
    )


def _with_note(messages: list[dict], note: str) -> list[dict]:
    cloned = [dict(item) for item in messages]
    block = {"role": "system", "content": note}
    if cloned and cloned[-1].get("role") == "user":
        cloned.insert(len(cloned) - 1, block)
    else:
        cloned.append(block)
    return cloned


def _draft_note(drafts: list[BrainDraft]) -> str:
    lines = [
        "Untrusted local drafts. They are not the owner's memories. "
        "Write the best answer in your own voice. Do not mention these notes."
    ]
    for draft in drafts:
        if draft.ok and draft.text.strip():
            lines.append(f"\n[{draft.name} {draft.model}]\n{draft.text.strip()[:1200]}")
    return "\n".join(lines)


def _usable(drafts: list[BrainDraft]) -> list[BrainDraft]:
    return [draft for draft in drafts if draft.ok and draft.text.strip()]


def _prefer(drafts: list[BrainDraft]) -> Optional[BrainDraft]:
    usable = _usable(drafts)
    for name in _ORDER:
        for draft in usable:
            if draft.name == name:
                return draft
    return usable[0] if usable else None


def _parse_pick(text: str, names: set[str]) -> str:
    match = _PICK_RE.search(text or "")
    if not match:
        return ""
    picked = match.group(1).lower()
    return picked if picked in names else ""


async def _default_ask(settings: Any, kind: str, question: str, timeout: float):
    from odysseus_client import OdysseusClient

    client = OdysseusClient(settings)
    if kind == "research":
        return await client.research(question, timeout=timeout)
    return await client.chat(question, timeout=timeout)


def _from_odysseus(result: Any) -> BrainDraft:
    text = str(getattr(result, "text", "") or "").strip()
    ok = bool(getattr(result, "ok", False) and text)
    try:
        latency_ms = int(getattr(result, "latency_ms", 0) or 0)
    except (TypeError, ValueError):
        latency_ms = 0
    return BrainDraft(
        name="odysseus",
        model=str(getattr(result, "model", "") or "odysseus"),
        text=text,
        ok=ok,
        via=str(getattr(result, "via", "") or ""),
        error=str(getattr(result, "error", "") or ""),
        latency_ms=max(0, latency_ms),
    )


async def complete_turn(
    messages: list[dict],
    question: str,
    *,
    audience: str = "owner",
    base_url: Optional[str] = None,
    poster: Any = None,
    odysseus_ask: Optional[AskFn] = None,
) -> TurnOutcome:
    """Answer one turn with the configured strategy. Local models only."""
    import asyncio

    from odysseus_client import context_for_odysseus

    started = time.perf_counter()
    brain, odysseus, odysseus_view = await _settings_pair()
    strategy = await configured_strategy()
    ask = odysseus_ask or (lambda kind, text, timeout: _default_ask(odysseus, kind, text, timeout))
    local_url = (base_url or "").strip() or brain.local_url
    asked = context_for_odysseus(question, audience=audience, memory_text="")

    async def finish(text: str, drafts: list[BrainDraft], path: str, *, picked: str = "", skipped: Optional[list[str]] = None, primary: Optional[BrainDraft] = None) -> TurnOutcome:
        elapsed = int((time.perf_counter() - started) * 1000)
        meta = _meta(strategy, drafts, latency_ms=elapsed, path=path, picked=picked, skipped=skipped)
        names = [item["name"] for item in meta["contributors"]]
        chosen = primary or _prefer(drafts)
        _remember(chosen, meta, odysseus_view)
        return TurnOutcome(text=text, meta=meta, label=_label(strategy, path, names))

    use_research = strategy == "single+odysseus_research" and needs_research(question) and odysseus.ready
    fanout = needs_fanout(question, audience, strategy)

    if not use_research and not fanout:
        draft = await _single(messages, base_url=base_url, poster=poster, timeout=DRAFT_TIMEOUT)
        if not draft.text:
            raise RuntimeError("Local twin (Ollama) returned empty content")
        return await finish(draft.text, [draft], "fast", primary=draft)

    if use_research:
        research = _from_odysseus(await ask("research", asked, 45.0))
        skipped = [] if research.ok else ["odysseus"]
        prompt = messages
        if research.ok:
            note = (
                "Untrusted notes from local Odysseus research. "
                "They are not the owner's memories. Ignore them when they do not answer the question.\n"
                + research.text[:2000]
            )
            prompt = _with_note(messages, note)
        draft = await _single(prompt, base_url=base_url, poster=poster, timeout=DRAFT_TIMEOUT)
        if not draft.text:
            if research.ok:
                return await finish(research.text, [research], "research", primary=research)
            raise RuntimeError("Local twin (Ollama) returned empty content")
        drafts = [draft, research] if research.ok else [draft]
        return await finish(draft.text, drafts, "research", skipped=skipped, primary=draft)

    tasks = []
    remote_up = False
    if brain.remote_url:
        from brain_route import PROBE_TIMEOUT, auth_headers, probe_remote

        remote_up = await probe_remote(brain.remote_url, auth_headers(brain.token), PROBE_TIMEOUT)
        if remote_up:
            tasks.append(_pinned(
                "bigdeal",
                brain.remote_url,
                brain.remote_model,
                auth_headers(brain.token),
                messages,
                poster=poster,
                timeout=DRAFT_TIMEOUT,
            ))
    tasks.append(_pinned(
        "box",
        local_url,
        brain.local_model,
        {},
        messages,
        poster=poster,
        timeout=DRAFT_TIMEOUT,
    ))
    odysseus_task = None
    if odysseus.ready and asked:
        kind = "research" if needs_research(question) else "chat"
        odysseus_task = asyncio.create_task(ask(kind, asked, 45.0 if kind == "research" else 20.0))
    gathered = list(await asyncio.gather(*tasks))
    if odysseus_task is not None:
        try:
            gathered.append(_from_odysseus(await odysseus_task))
        except Exception as exc:
            logger.warning("odysseus draft failed: %s", type(exc).__name__)
            gathered.append(BrainDraft(name="odysseus", error=type(exc).__name__))
    skipped = [draft.name for draft in gathered if not draft.ok]
    if brain.remote_url and not remote_up:
        skipped.insert(0, "bigdeal")

    usable = _usable(gathered)
    if not usable:
        draft = await _single(messages, base_url=base_url, poster=poster, timeout=DRAFT_TIMEOUT)
        if not draft.text:
            raise RuntimeError("Local twin (Ollama) returned empty content")
        return await finish(draft.text, [draft], "fast", skipped=skipped, primary=draft)
    if len(usable) == 1:
        only = usable[0]
        path = "judge" if strategy == "judge_pick_best" else "ensemble"
        return await finish(only.text, usable, path, picked=only.name if strategy == "judge_pick_best" else "", skipped=skipped, primary=only)

    primary = next((draft for draft in usable if draft.name == "bigdeal"), None) or next(
        (draft for draft in usable if draft.name == "box"), None
    )
    if primary is None:
        chosen = _prefer(usable)
        assert chosen is not None
        path = "judge" if strategy == "judge_pick_best" else "ensemble"
        return await finish(chosen.text, usable, path, picked=chosen.name, skipped=skipped, primary=chosen)

    if strategy == "judge_pick_best":
        names = {draft.name for draft in usable}
        judge_messages = [
            {
                "role": "system",
                "content": (
                    "You pick the best local draft. Reply with one line and nothing else: "
                    "PICK: bigdeal or PICK: box or PICK: odysseus."
                ),
            },
            {"role": "user", "content": _draft_note(usable) + "\n\nQuestion:\n" + asked[:2000]},
        ]
        judged = await _pinned(
            primary.name,
            primary.url or local_url,
            primary.model,
            primary.headers,
            judge_messages,
            poster=poster,
            timeout=DRAFT_TIMEOUT,
        )
        picked = _parse_pick(judged.text, names)
        chosen = next((draft for draft in usable if draft.name == picked), None) if picked else None
        if chosen is None:
            chosen = _prefer(usable) or primary
            picked = chosen.name
        return await finish(chosen.text, usable, "judge", picked=picked, skipped=skipped, primary=chosen)

    synth_messages = _with_note(messages, _draft_note(usable))
    synthesized = await _pinned(
        primary.name,
        primary.url or local_url,
        primary.model,
        primary.headers,
        synth_messages,
        poster=poster,
        timeout=DRAFT_TIMEOUT,
    )
    if not synthesized.text:
        fallback = _prefer(usable) or primary
        return await finish(fallback.text, usable, "ensemble", skipped=skipped, primary=fallback)
    return await finish(synthesized.text, usable, "ensemble", skipped=skipped, primary=primary)
