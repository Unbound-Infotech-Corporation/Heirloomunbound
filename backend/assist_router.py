"""Assist task router for Heirloom Unbound.

Classifies a Do/PC request and runs the owner's per-category chain on a
local OpenAI-compatible server (Ollama or llama.cpp). Cloud is used only
when the owner turned it on, saved a key, and put a cloud slot in the chain.

Failures stay visible: the badge names the model that ran, and a miss
raises AssistRouteError instead of swapping in the Twin model.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
import httpx

from studio_defaults import (
    ASSIST_CATEGORY_LABELS,
    ASSIST_CATEGORIES,
    clamp_assist_settings,
    clamp_model_map,
    engine_url,
)

_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)b")

_CODE_NEEDLES = (
    "```",
    ".py",
    ".cs",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".cpp",
    ".java",
    "refactor",
    "compile",
    "traceback",
    "stack trace",
    "pull request",
    "implement",
    "debug",
    "unit test",
    "code review",
    "git diff",
    "function",
    "method",
    "class ",
    "bug",
    "patch",
    "repository",
    "migrate",
    "migration",
    "rewrite",
    "schema",
    "middleware",
    "endpoint",
    "parser",
    "diff ",
)
_RESEARCH_NEEDLES = (
    "look up",
    "search for",
    "what is the latest",
    "what is",
    "cite",
    "sources",
    "research",
    "according to",
    "news about",
    "find out",
)
_REASONING_NEEDLES = (
    "plan",
    "tradeoff",
    "trade-off",
    "architecture",
    "why should",
    "why ",
    "think through",
    "design",
    "pros and cons",
    "strategy",
    "compare",
)
_VISION_NEEDLES = (
    "screenshot",
    "look at the screen",
    "look at this image",
    "look at this picture",
    "what's on my screen",
    "what is on my screen",
    "what's on the screen",
    "see the screen",
    "this image",
    "this picture",
    "see_screen",
)
_RISK_NEEDLES = (
    "delete",
    "drop table",
    "drop column",
    "migration",
    "migrate",
    "auth",
    "password",
    "secret",
    "credential",
    "api key",
    "production",
    "force push",
    "rm -rf",
    "rewrite",
    "payment",
    "billing",
    "sudo ",
    "chmod ",
    "security",
    "deploy",
)

_CATEGORY_TIMEOUT = {
    "code": 90.0,
    "reasoning": 90.0,
    "research": 60.0,
    "chat": 45.0,
    "vision": 60.0,
}


class AssistRouteError(RuntimeError):
    def __init__(self, message: str, *, category: str, attempts: list[dict], badge: str):
        super().__init__(message)
        self.category = category
        self.attempts = attempts
        self.badge = badge


@dataclass
class Inventory:
    ollama_ready: bool = False
    ollama_models: list[str] = field(default_factory=list)
    ollama_reason: str = "Ollama is not running."
    llamacpp_ready: bool = False
    llamacpp_models: list[str] = field(default_factory=list)
    llamacpp_reason: str = "llama.cpp server is not running."
    cloud_enabled: bool = False
    cloud_has_key: bool = False
    cloud_base_url: str = ""
    cloud_model: str = ""


@dataclass(frozen=True)
class Candidate:
    backend: str
    model: str
    requested: str
    prior_misses: tuple[dict, ...] = ()


@dataclass
class AssistAnswer:
    reply: str
    badge: str
    category: str
    backend: str
    model: str
    degraded: bool
    attempts: list[dict]
    models: list[dict]
    drafts: dict | None = None
    error: str | None = None
    second_opinion: bool = False


def model_matches(spec: str, installed: str) -> bool:
    """True when installed is spec, or spec plus an Ollama-style :tag."""
    wanted = (spec or "").strip().lower()
    name = (installed or "").strip().lower()
    if not wanted or not name:
        return False
    if name == wanted:
        return True
    return name.startswith(wanted + ":")


def _size_key(name: str) -> float:
    match = _SIZE_RE.search(name.lower())
    return float(match.group(1)) if match else 0.0


def ranked_matches(spec: str, names: list[str]) -> list[str]:
    hits = [n for n in names if n and model_matches(spec, n)]
    return sorted(hits, key=_size_key, reverse=True)


def classify_assist_task(text: str, *, has_image: bool = False) -> str:
    """Rule classifier. Code beats research and reasoning. Vision beats text when an image is attached."""
    blob = (text or "").strip().lower()
    if has_image:
        return "vision"
    if any(needle in blob for needle in _VISION_NEEDLES):
        return "vision"
    if any(needle in blob for needle in _CODE_NEEDLES):
        return "code"
    if any(needle in blob for needle in _RESEARCH_NEEDLES):
        return "research"
    if any(needle in blob for needle in _REASONING_NEEDLES):
        return "reasoning"
    return "chat"


def is_risky_code(text: str) -> bool:
    blob = (text or "").lower()
    return any(needle in blob for needle in _RISK_NEEDLES)


def wants_second_opinion(text: str, category: str, mode: str) -> bool:
    if category != "code":
        return False
    if mode == "off":
        return False
    if mode == "always":
        return True
    return is_risky_code(text)


def settings_for_user(user: dict | None) -> dict:
    raw = dict((user or {}).get("studio_assist") or {})
    picker = clamp_model_map((user or {}).get("studio_models")).get("assist")
    if picker in {"auto", "manual"}:
        raw["picker"] = picker
    return clamp_assist_settings(raw)


def inventory_from_probe(probe: dict | None, settings: dict, *, has_key: bool) -> Inventory:
    probe = probe if isinstance(probe, dict) else {}
    ollama = probe.get("ollama") if isinstance(probe.get("ollama"), dict) else {}
    llama = probe.get("llamacpp") if isinstance(probe.get("llamacpp"), dict) else {}
    ollama_models = [str(m) for m in (ollama.get("models") or []) if str(m).strip()]
    llama_models = [str(m) for m in (llama.get("models") or []) if str(m).strip()]
    cloud = settings.get("cloud") or {}
    return Inventory(
        ollama_ready=bool(ollama.get("ready")) or bool(ollama_models),
        ollama_models=ollama_models,
        ollama_reason=str(ollama.get("detail") or "Ollama is not running."),
        llamacpp_ready=bool(llama.get("ready")) or bool(llama_models),
        llamacpp_models=llama_models,
        llamacpp_reason=str(llama.get("detail") or "llama.cpp server is not running."),
        cloud_enabled=bool(cloud.get("enabled")),
        cloud_has_key=bool(has_key),
        cloud_base_url=str(cloud.get("base_url") or ""),
        cloud_model=str(cloud.get("model") or ""),
    )


def _attempt(backend: str, model: str, status: str, reason: str) -> dict:
    return {"backend": backend, "model": model, "status": status, "reason": reason}


def expand_chain(chain: list[dict], inventory: Inventory) -> tuple[list[Candidate], list[dict]]:
    candidates: list[Candidate] = []
    attempts: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for slot in chain:
        backend = str(slot.get("backend") or "")
        spec = str(slot.get("model") or "")
        if backend == "cloud":
            if not inventory.cloud_enabled:
                attempts.append(_attempt(backend, spec, "skipped", "Cloud opt-in is off."))
                continue
            if not inventory.cloud_has_key:
                attempts.append(_attempt(backend, spec, "skipped", "Cloud key is missing."))
                continue
            if not inventory.cloud_base_url:
                attempts.append(_attempt(backend, spec, "skipped", "Cloud base URL is empty."))
                continue
            if not inventory.cloud_model:
                attempts.append(_attempt(backend, spec, "missing", "Cloud model name is empty."))
                continue
            if not model_matches(spec, inventory.cloud_model):
                attempts.append(
                    _attempt(
                        backend,
                        spec,
                        "missing",
                        f"Cloud model is {inventory.cloud_model}, not {spec}.",
                    )
                )
                continue
            key = ("cloud", inventory.cloud_model.lower())
            if key in seen:
                continue
            seen.add(key)
            candidates.append(Candidate("cloud", inventory.cloud_model, spec, tuple(attempts)))
            continue
        if backend == "ollama":
            ready, names, why = inventory.ollama_ready, inventory.ollama_models, inventory.ollama_reason
        elif backend == "llamacpp":
            ready, names, why = inventory.llamacpp_ready, inventory.llamacpp_models, inventory.llamacpp_reason
        else:
            attempts.append(_attempt(backend or "?", spec, "skipped", "Unknown backend."))
            continue
        if not ready:
            attempts.append(_attempt(backend, spec, "unavailable", why))
            continue
        matches = ranked_matches(spec, names)
        if not matches:
            attempts.append(_attempt(backend, spec, "missing", f"{spec} is not installed."))
            continue
        for name in matches:
            key = (backend, name.lower())
            if key in seen:
                continue
            seen.add(key)
            candidates.append(Candidate(backend, name, spec, tuple(attempts)))
    return candidates, attempts


def _label(category: str) -> str:
    return ASSIST_CATEGORY_LABELS.get(category, category)


def format_badge(
    category: str,
    *,
    runs: list[dict],
    attempts: list[dict],
    judge: dict | None = None,
    note: str = "",
) -> str:
    label = _label(category)
    if runs:
        parts = " + ".join(f"{row['backend']}/{row['model']}" for row in runs)
    else:
        parts = "did not run"
    badge = f"Assist · {label} · {parts}"
    if judge:
        badge += f" · judge {judge['backend']}/{judge['model']}"
    misses = [row for row in attempts if row.get("status") != "ran"]
    if misses:
        detail = "; ".join(
            f"{row['backend']}/{row['model']}: {row['reason']}" for row in misses
        )
        badge += f" · fallback ({detail})"
    if note:
        badge += f" · {note}"
    return badge


def loud_failure(category: str, attempts: list[dict], *, headline: str | None = None) -> str:
    badge = format_badge(category, runs=[], attempts=attempts)
    lines = [badge, headline or f"Assist could not run a {_label(category)} model."]
    if attempts:
        for row in attempts:
            lines.append(f"- {row['backend']}/{row['model']}: {row['status']} — {row['reason']}")
    else:
        lines.append("- No models are configured for this category.")
    lines.append("Nothing else was substituted.")
    return "\n".join(lines)


def _fail(category: str, attempts: list[dict], headline: str | None = None) -> AssistRouteError:
    message = loud_failure(category, attempts, headline=headline)
    badge = format_badge(category, runs=[], attempts=attempts)
    return AssistRouteError(message, category=category, attempts=attempts, badge=badge)


def _chain_for(settings: dict, category: str) -> list[dict]:
    if settings.get("picker") == "manual":
        return [
            {
                "backend": settings.get("manual_backend") or "ollama",
                "model": settings.get("manual_model") or "",
            }
        ]
    routes = settings.get("routes") or {}
    chain = routes.get(category)
    return list(chain) if isinstance(chain, list) else []


def openai_base(url: str) -> str:
    raw = (url or "").strip().rstrip("/")
    if not raw:
        return ""
    if raw.endswith("/v1"):
        return raw
    return raw + "/v1"


class HttpAssistTransport:
    """OpenAI-compatible chat for Ollama, llama.cpp server, and an opt-in cloud host."""

    def __init__(self, *, ollama_base: str, llamacpp_base: str, cloud_base: str = "", cloud_key: str = ""):
        self.ollama_base = openai_base(ollama_base or "http://127.0.0.1:11434")
        self.llamacpp_base = openai_base(llamacpp_base or "http://127.0.0.1:8080/v1")
        self.cloud_base = openai_base(cloud_base)
        self.cloud_key = cloud_key or ""

    def _base(self, backend: str) -> tuple[str, str]:
        if backend == "ollama":
            return self.ollama_base, ""
        if backend == "llamacpp":
            return self.llamacpp_base, ""
        if backend == "cloud":
            if not self.cloud_key:
                raise AssistRouteError(
                    "Cloud key is missing.",
                    category="chat",
                    attempts=[],
                    badge="Assist · cloud key missing",
                )
            if not self.cloud_base:
                raise AssistRouteError(
                    "Cloud base URL is empty.",
                    category="chat",
                    attempts=[],
                    badge="Assist · cloud URL missing",
                )
            return self.cloud_base, self.cloud_key
        raise AssistRouteError(
            f"Unknown Assist backend {backend}.",
            category="chat",
            attempts=[],
            badge="Assist · unknown backend",
        )

    async def complete(self, *, backend: str, model: str, messages: list[dict], timeout: float) -> str:
        base, key = self._base(backend)
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        payload = {"model": model, "messages": messages, "stream": False}
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(f"{base}/chat/completions", json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"{backend} request failed: {exc}") from exc
        if response.status_code >= 400:
            snippet = (response.text or "")[:240].replace("\n", " ")
            raise RuntimeError(f"{backend} HTTP {response.status_code} ({model}): {snippet}")
        try:
            body = response.json()
        except ValueError as exc:
            raise RuntimeError(f"{backend} returned a non-JSON reply ({model}).") from exc
        choices = body.get("choices") if isinstance(body, dict) else None
        if not choices:
            raise RuntimeError(f"{backend} returned no choices ({model}).")
        message = (choices[0] or {}).get("message") or {}
        text = message.get("content")
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError(f"{backend} returned an empty reply ({model}).")
        return text


async def _run_candidates(
    candidates: list[Candidate],
    prior: list[dict],
    messages: list[dict],
    transport,
    *,
    category: str,
    allow_fallback: bool,
    timeout: float,
) -> tuple[str, Candidate, list[dict]]:
    attempts = list(prior)
    runtime_misses: list[dict] = []
    limit = 1 if not allow_fallback else len(candidates)
    for candidate in candidates[:limit]:
        try:
            reply = await transport.complete(
                backend=candidate.backend,
                model=candidate.model,
                messages=messages,
                timeout=timeout,
            )
        except Exception as exc:  # noqa: BLE001 — surfaced in the attempt log
            row = _attempt(candidate.backend, candidate.model, "failed", str(exc))
            attempts.append(row)
            runtime_misses.append(row)
            if not allow_fallback:
                break
            continue
        attempts.append(_attempt(candidate.backend, candidate.model, "ran", "answered"))
        return reply, candidate, attempts
    raise _fail(category, attempts)


def _judge_messages(user_text: str, primary: Candidate, primary_text: str, second: Candidate, second_text: str) -> list[dict]:
    system = (
        "You are the Heirloom Unbound Assist judge. You work for the owner. "
        "You are not their twin and you do not speak as them. "
        "Compare the two drafts. Keep the safer change. Do not invent files or biography. "
        "Return the merged answer the owner should see, then one short note of what you kept from each draft."
    )
    user = (
        f"REQUEST:\n{user_text}\n\n"
        f"DRAFT A ({primary.backend}/{primary.model}):\n{primary_text}\n\n"
        f"DRAFT B ({second.backend}/{second.model}):\n{second_text}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _unjudged(primary: Candidate, primary_text: str, second: Candidate, second_text: str, reason: str) -> str:
    return (
        "Second opinion did not finish. The judge did not run.\n"
        f"{reason}\n\n"
        f"Primary ({primary.backend}/{primary.model}):\n{primary_text}\n\n"
        f"Second ({second.backend}/{second.model}):\n{second_text}"
    )


async def answer_assist(
    text: str,
    *,
    system: str,
    history: list[dict] | None = None,
    settings: dict | None = None,
    probe: dict | None = None,
    cloud_key: str = "",
    ollama_base: str = "",
    llamacpp_base: str = "",
    has_image: bool = False,
    transport=None,
    inventory: Inventory | None = None,
) -> AssistAnswer:
    cfg = clamp_assist_settings(settings)
    category = classify_assist_task(text, has_image=has_image)
    inv = inventory or inventory_from_probe(probe, cfg, has_key=bool(cloud_key))
    chain = _chain_for(cfg, category)
    if cfg.get("picker") == "manual" and not str(cfg.get("manual_model") or "").strip():
        raise _fail(category, [], "Manual Assist override has no model. Choose one, or switch the picker to Auto.")
    if not chain:
        raise _fail(category, [], f"The {_label(category)} route is empty.")

    candidates, misses = expand_chain(chain, inv)
    opinion = wants_second_opinion(text, category, str(cfg.get("second_opinion") or "auto"))
    manual = cfg.get("picker") == "manual"
    if manual and opinion:
        opinion = False
        manual_note = "second opinion skipped: manual override is one model"
    else:
        manual_note = ""

    if opinion and len(candidates) < 2:
        only = candidates[0].model if candidates else "none"
        raise _fail(
            category,
            misses,
            f"Second opinion needs two different code models. Only {only} is available.",
        )
    if not candidates:
        raise _fail(category, misses)

    http = transport or HttpAssistTransport(
        ollama_base=ollama_base,
        llamacpp_base=llamacpp_base,
        cloud_base=str((cfg.get("cloud") or {}).get("base_url") or ""),
        cloud_key=cloud_key,
    )
    prior = list(history or [])
    messages = [{"role": "system", "content": system}, *prior, {"role": "user", "content": text}]
    timeout = _CATEGORY_TIMEOUT.get(category, 60.0)

    if not opinion:
        pool = candidates[:1] if manual else candidates
        reply, chosen, attempts = await _run_candidates(
            pool,
            [],
            messages,
            http,
            category=category,
            allow_fallback=not manual,
            timeout=timeout,
        )
        failed = [row for row in attempts if row["status"] == "failed"]
        prior = list(chosen.prior_misses)
        degraded = bool(prior or failed or manual_note)
        runs = [{"role": "primary", "backend": chosen.backend, "model": chosen.model}]
        badge = format_badge(category, runs=runs, attempts=prior + failed, note=manual_note)
        return AssistAnswer(
            reply=reply,
            badge=badge,
            category=category,
            backend=chosen.backend,
            model=chosen.model,
            degraded=degraded,
            attempts=prior + attempts,
            models=runs,
            second_opinion=False,
        )

    collected: list[tuple[Candidate, str]] = []
    attempts = []
    pending = list(candidates)
    while pending and len(collected) < 2:
        candidate = pending.pop(0)
        try:
            reply = await http.complete(
                backend=candidate.backend,
                model=candidate.model,
                messages=messages,
                timeout=timeout,
            )
        except Exception as exc:  # noqa: BLE001 — recorded, then the next model is tried
            attempts.append(_attempt(candidate.backend, candidate.model, "failed", str(exc)))
            continue
        attempts.append(_attempt(candidate.backend, candidate.model, "ran", "answered"))
        collected.append((candidate, reply))
    if len(collected) < 2:
        raise _fail(
            category,
            list(candidates[-1].prior_misses) + attempts if candidates else attempts,
            "Second opinion needs two different code models. A second call did not succeed.",
        )

    primary, primary_text = collected[0]
    second, second_text = collected[1]
    attempts = list(primary.prior_misses) + attempts
    judge_chain = list((cfg.get("routes") or {}).get("reasoning") or [])
    judge_candidates, judge_misses = expand_chain(judge_chain, inv)
    draft_payload = {
        "primary": {"backend": primary.backend, "model": primary.model, "text": primary_text},
        "second": {"backend": second.backend, "model": second.model, "text": second_text},
    }
    runs = [
        {"role": "primary", "backend": primary.backend, "model": primary.model},
        {"role": "second", "backend": second.backend, "model": second.model},
    ]
    if not judge_candidates:
        reason = loud_failure("reasoning", judge_misses, headline="No reasoning model is available to judge.")
        reply = _unjudged(primary, primary_text, second, second_text, reason)
        badge = format_badge(category, runs=runs, attempts=attempts, note="judge did not run")
        return AssistAnswer(
            reply=reply,
            badge=badge,
            category=category,
            backend=primary.backend,
            model=primary.model,
            degraded=True,
            attempts=attempts + judge_misses,
            models=runs,
            drafts=draft_payload,
            error=reason,
            second_opinion=True,
        )
    try:
        judged, judge, judge_attempts = await _run_candidates(
            judge_candidates,
            judge_misses,
            _judge_messages(text, primary, primary_text, second, second_text),
            http,
            category="reasoning",
            allow_fallback=True,
            timeout=_CATEGORY_TIMEOUT["reasoning"],
        )
    except AssistRouteError as exc:
        reply = _unjudged(primary, primary_text, second, second_text, str(exc))
        badge = format_badge(category, runs=runs, attempts=attempts, note="judge failed")
        return AssistAnswer(
            reply=reply,
            badge=badge,
            category=category,
            backend=primary.backend,
            model=primary.model,
            degraded=True,
            attempts=attempts + exc.attempts,
            models=runs,
            drafts=draft_payload,
            error=str(exc),
            second_opinion=True,
        )
    judge_row = {"role": "judge", "backend": judge.backend, "model": judge.model}
    draft_payload["judge"] = {"backend": judge.backend, "model": judge.model, "text": judged}
    shown = [row for row in attempts + judge_attempts if row["status"] != "ran"]
    badge = format_badge(category, runs=runs, attempts=shown, judge=judge_row)
    return AssistAnswer(
        reply=judged,
        badge=badge,
        category=category,
        backend=primary.backend,
        model=primary.model,
        degraded=bool(shown),
        attempts=attempts + judge_attempts,
        models=runs + [judge_row],
        drafts=draft_payload,
        second_opinion=True,
    )


def preview_assist(
    text: str,
    *,
    settings: dict | None,
    probe: dict | None,
    has_key: bool,
    has_image: bool = False,
) -> dict:
    """Dry run: which model would answer. Does not call a backend."""
    cfg = clamp_assist_settings(settings)
    category = classify_assist_task(text, has_image=has_image)
    inv = inventory_from_probe(probe, cfg, has_key=has_key)
    try:
        chain = _chain_for(cfg, category)
        if cfg.get("picker") == "manual" and not str(cfg.get("manual_model") or "").strip():
            raise _fail(category, [], "Manual Assist override has no model. Choose one, or switch the picker to Auto.")
        candidates, misses = expand_chain(chain, inv)
        opinion = wants_second_opinion(text, category, str(cfg.get("second_opinion") or "auto"))
        note = ""
        if cfg.get("picker") == "manual" and opinion:
            opinion = False
            note = "second opinion skipped: manual override is one model"
        if opinion and len(candidates) < 2:
            only = candidates[0].model if candidates else "none"
            raise _fail(
                category,
                misses,
                f"Second opinion needs two different code models. Only {only} is available.",
            )
        if not candidates:
            raise _fail(category, misses)
        chosen = candidates[0]
        second = candidates[1] if opinion else None
        runs = [{"role": "primary", "backend": chosen.backend, "model": chosen.model}]
        if second:
            runs.append({"role": "second", "backend": second.backend, "model": second.model})
        prior = list(chosen.prior_misses)
        badge = format_badge(category, runs=runs, attempts=prior, note=note)
        return {
            "ok": True,
            "category": category,
            "badge": badge,
            "backend": chosen.backend,
            "model": chosen.model,
            "second_model": second.model if second else None,
            "degraded": bool(prior) or bool(note),
            "second_opinion": opinion,
            "attempts": prior,
            "error": None,
        }
    except AssistRouteError as exc:
        return {
            "ok": False,
            "category": exc.category,
            "badge": exc.badge,
            "backend": None,
            "model": None,
            "second_model": None,
            "degraded": True,
            "second_opinion": False,
            "attempts": exc.attempts,
            "error": str(exc),
        }


def answer_payload(answer: AssistAnswer) -> dict:
    detail = {
        "category": answer.category,
        "degraded": answer.degraded,
        "models": answer.models,
        "attempts": answer.attempts,
        "second_opinion": answer.second_opinion,
        "error": answer.error,
        "drafts": answer.drafts,
    }
    return {
        "reply": answer.reply,
        "model_badge": answer.badge,
        "model_detail": detail,
        "backend": answer.backend,
        "model": answer.model,
        "category": answer.category,
    }


def readiness(settings: dict, probe: dict | None, *, has_key: bool) -> tuple[bool, str]:
    cfg = clamp_assist_settings(settings)
    inv = inventory_from_probe(probe, cfg, has_key=has_key)
    ready: list[str] = []
    blocked: list[str] = []
    for cat in ASSIST_CATEGORIES:
        chain = _chain_for(cfg, cat)
        candidates, misses = expand_chain(chain, inv)
        if candidates:
            ready.append(_label(cat))
        else:
            why = misses[0]["reason"] if misses else "route is empty"
            blocked.append(f"{_label(cat)} ({why})")
    if ready:
        detail = "Ready: " + ", ".join(ready)
        if blocked:
            detail += ". Blocked: " + "; ".join(blocked)
        return True, detail
    return False, "Blocked: " + "; ".join(blocked)


ASSIST_TRY_SYSTEM = (
    "You are Heirloom Assist, the copilot on this PC. You work for the owner. "
    "You are not their digital twin. Never speak as them."
)


async def complete_for_user(
    user: dict,
    text: str,
    *,
    system: str | None = None,
    has_image: bool = False,
    probe: dict | None = None,
) -> AssistAnswer:
    cfg = settings_for_user(user)
    ollama, llama = bases_for_user(user)
    if probe is None:
        stored = user.get("companion_runtime_probe")
        probe = stored if isinstance(stored, dict) else None
    return await answer_assist(
        text,
        system=system or ASSIST_TRY_SYSTEM,
        settings=cfg,
        probe=probe,
        cloud_key=(user.get("assist_cloud_api_key") or "").strip(),
        ollama_base=ollama,
        llamacpp_base=llama,
        has_image=has_image,
    )


def bases_for_user(user: dict) -> tuple[str, str]:
    from studio_compute import resolve_ollama_url

    ollama = resolve_ollama_url(user) or engine_url(user.get("studio_compute"), "ollama_url")
    llama = engine_url(user.get("studio_compute"), "llamacpp_url")
    return ollama, llama


def public_assist_state(user: dict, probe: dict | None) -> dict:
    cfg = settings_for_user(user)
    has_key = bool((user.get("assist_cloud_api_key") or "").strip())
    ok, detail = readiness(cfg, probe, has_key=has_key)
    inv = inventory_from_probe(probe, cfg, has_key=has_key)
    return {
        "picker": cfg["picker"],
        "manual_backend": cfg["manual_backend"],
        "manual_model": cfg["manual_model"],
        "second_opinion": cfg["second_opinion"],
        "routes": cfg["routes"],
        "categories": [
            {"id": cat, "label": ASSIST_CATEGORY_LABELS[cat]}
            for cat in ASSIST_CATEGORIES
        ],
        "cloud": {**cfg["cloud"], "has_key": has_key},
        "installed": {
            "ollama": inv.ollama_models,
            "llamacpp": inv.llamacpp_models,
        },
        "ready": ok,
        "detail": detail,
    }
