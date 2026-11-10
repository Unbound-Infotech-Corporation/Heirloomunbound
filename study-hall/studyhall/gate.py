"""Cheap page-type check before the panel. One small local model, then a cache."""
from __future__ import annotations

import json

from studyhall.config import MAIN_OLLAMA, STUDY_OLLAMA
from studyhall.pages import SKIP_KINDS, classify_page

ALLOWED = frozenset({"research_or_educational", "discussion", "docs"})
MARKETING = "marketing_pr_tool"
REVIEW_NOTE = "source looked like marketing"

_MODELS = (
    (STUDY_OLLAMA, "llama3.1:8b"),
    (MAIN_OLLAMA, "qwen3:8b"),
)
_PROMPT = """Classify this page for a research reader. Reply with JSON only, no markdown.
{{"kind":"research_or_educational"|"discussion"|"docs"|"marketing_pr_tool","reason":"one short sentence"}}

research_or_educational: a paper, essay, or lesson that teaches a method.
discussion: a forum thread or a comment discussion.
docs: reference documentation.
marketing_pr_tool: a product page, a tool or generator landing page, a press release, a funding announcement, or a partnership announcement.

Title: {title}
URL: {url}
Text:
{excerpt}"""


def heuristic_kind(url: str, title: str = "") -> str:
    """Map a path or headline onto the gate's four labels. Empty when a model should look."""
    kind = classify_page(url, title)
    if kind in SKIP_KINDS:
        return MARKETING
    if kind in {"paper", "research"}:
        return "research_or_educational"
    if kind == "thread":
        return "discussion"
    if kind == "docs":
        return "docs"
    return ""


def _parse_verdict(raw: str) -> dict | None:
    start = (raw or "").find("{")
    end = (raw or "").rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    kind = str(payload.get("kind") or "").strip()
    if kind not in ALLOWED and kind != MARKETING:
        return None
    reason = " ".join(str(payload.get("reason") or "").split())[:240]
    return {"kind": kind, "reason": reason or kind}


async def _ask_local(prompt: str) -> str:
    import httpx

    timeout = httpx.Timeout(12.0, connect=2.0)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        last = ""
        for endpoint, model in _MODELS:
            try:
                response = await client.post(
                    endpoint.rstrip("/") + "/api/chat",
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                        "format": "json",
                        "options": {"temperature": 0, "num_predict": 80},
                    },
                )
                response.raise_for_status()
                return str(((response.json() or {}).get("message") or {}).get("content") or "")
            except Exception as exc:
                last = exc.__class__.__name__
                continue
        raise RuntimeError(last or "no-model")


class PageGate:
    def __init__(self, ask=None, cache: dict | None = None):
        self.ask = ask
        self.cache = cache if cache is not None else {}

    async def verdict(self, url: str, title: str = "", text: str = "") -> dict:
        key = url or title
        cached = self.cache.get(key)
        if isinstance(cached, dict) and cached.get("kind"):
            return cached
        guessed = heuristic_kind(url, title)
        if guessed:
            row = {"url": url, "kind": guessed, "reason": "The address and title already show the page type."}
            self.cache[key] = row
            return row
        prompt = _PROMPT.format(title=(title or "")[:200], url=url or "", excerpt=(text or "")[:1500])
        try:
            raw = await (self.ask(prompt) if self.ask is not None else _ask_local(prompt))
        except Exception:
            row = {"url": url, "kind": "research_or_educational", "reason": "The page-type check did not answer."}
            return row
        parsed = _parse_verdict(raw)
        if parsed is None:
            row = {"url": url, "kind": "research_or_educational", "reason": "The page-type check did not answer."}
            return row
        row = {"url": url, "kind": parsed["kind"], "reason": parsed["reason"]}
        self.cache[key] = row
        return row


async def flag_marketing_drafts(lessons: list[dict], gate: PageGate) -> int:
    """Mark draft cards whose source is marketing. Leave them for the owner."""
    marked = 0
    for lesson in lessons:
        if not isinstance(lesson, dict) or lesson.get("status") != "draft":
            continue
        if lesson.get("review_note"):
            continue
        url = str(lesson.get("source_url") or "")
        title = str(lesson.get("source_title") or lesson.get("summary") or "")
        if not url and not title:
            continue
        verdict = await gate.verdict(url, title, str(lesson.get("summary") or "")[:1500])
        if verdict.get("kind") != MARKETING:
            continue
        lesson["review_note"] = REVIEW_NOTE
        lesson["review_reason"] = verdict.get("reason") or ""
        marked += 1
    return marked
