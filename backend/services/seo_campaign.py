"""SEO campaign drafts from public web results. No ranking API, no passwords.

We do not invent search volumes. Phrases come from the topic plus titles
people already publish. The twin can drop the plan into a Doc or Sheet
after the owner says yes.
"""
from __future__ import annotations

import re
from typing import Any

_STOP = {
    "the", "a", "an", "of", "in", "on", "to", "for", "and", "or", "with",
    "how", "what", "why", "your", "you", "best", "top", "guide", "vs",
}


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9][a-z0-9'-]{2,}", (text or "").lower()) if t not in _STOP]


def keyword_ideas(topic: str, location: str = "", extra_titles: list[str] | None = None) -> list[str]:
    topic = " ".join((topic or "").split())
    if not topic:
        return []
    loc = " ".join((location or "").split())
    seeds = [
        topic,
        f"{topic} near me",
        f"best {topic}",
        f"{topic} for beginners",
        f"{topic} cost",
        f"{topic} vs",
        f"how to choose {topic}",
    ]
    if loc:
        seeds.insert(1, f"{topic} in {loc}")
        seeds.append(f"{topic} {loc}")
    seen: set[str] = set()
    out: list[str] = []
    for phrase in seeds:
        key = phrase.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(phrase)
    counts: dict[str, int] = {}
    for title in extra_titles or []:
        for tok in _tokens(title):
            if tok in _tokens(topic):
                continue
            counts[tok] = counts.get(tok, 0) + 1
    extras = sorted(counts, key=lambda k: (-counts[k], k))[:6]
    for tok in extras:
        phrase = f"{topic} {tok}"
        if phrase.lower() not in seen:
            seen.add(phrase.lower())
            out.append(phrase)
    return out[:12]


def social_post_ideas(topic: str, audience: str = "") -> list[str]:
    who = (audience or "the people you want to reach").strip()
    name = (topic or "this").strip()
    return [
        f"If you {name} and you're {who}, here's the one thing I'd start with this week.",
        f"Three mistakes I see with {name} — and the simple fix for each.",
        f"A quiet win: how {who} can get results from {name} without a huge budget.",
        f"Ask me anything about {name}. I'll answer in plain language.",
    ]


def week_plan(topic: str) -> list[str]:
    name = (topic or "your offer").strip()
    return [
        f"Week 1 — Publish a short explainer: what {name} is and who it's for.",
        f"Week 1 — Post one customer-style story or FAQ about {name}.",
        f"Week 2 — Share a how-to (3 steps) and a link to your page.",
        f"Week 2 — Reply to every comment; post a reminder with a clear next step.",
    ]


def page_outline(topic: str, audience: str = "") -> list[str]:
    who = (audience or "your customer").strip()
    name = (topic or "the offer").strip()
    return [
        f"Headline: {name} for {who}",
        "Opening: the problem in one paragraph",
        "What you do, in plain words",
        "Who it's for / who it's not for",
        "How it works (3 steps)",
        "Proof: a story, a number, or a quote you actually have",
        "Next step: one button or one phone number",
    ]


def assemble_campaign(
    topic: str,
    *,
    location: str = "",
    audience: str = "",
    results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    titles = [str(r.get("title") or "") for r in (results or []) if isinstance(r, dict)]
    keywords = keyword_ideas(topic, location, titles)
    return {
        "topic": (topic or "").strip(),
        "location": (location or "").strip(),
        "audience": (audience or "").strip(),
        "keywords": keywords,
        "posts": social_post_ideas(topic, audience),
        "weeks": week_plan(topic),
        "page": page_outline(topic, audience),
        "sources": [
            {"title": str(r.get("title") or ""), "url": str(r.get("href") or "")}
            for r in (results or [])[:5]
            if isinstance(r, dict) and (r.get("title") or r.get("href"))
        ],
        "honest": (
            "These phrases come from your topic and public pages — not secret Google rankings. "
            "Use them as a starting map, then write in your own voice."
        ),
    }


def format_campaign(plan: dict[str, Any]) -> str:
    topic = plan.get("topic") or "your business"
    lines = [
        f"SEO starter for {topic}",
        plan.get("honest") or "",
        "",
        "Phrases to write about:",
    ]
    for kw in plan.get("keywords") or []:
        lines.append(f"- {kw}")
    lines.append("")
    lines.append("Two-week posting plan:")
    for item in plan.get("weeks") or []:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("Draft posts (edit before posting):")
    for i, post in enumerate(plan.get("posts") or [], 1):
        lines.append(f"{i}. {post}")
    lines.append("")
    lines.append("Page outline:")
    for item in plan.get("page") or []:
        lines.append(f"- {item}")
    sources = plan.get("sources") or []
    if sources:
        lines.append("")
        lines.append("Pages we looked at:")
        for src in sources:
            title = src.get("title") or src.get("url")
            url = src.get("url") or ""
            lines.append(f"- {title} {url}".strip())
    lines.append("")
    lines.append(
        "Next: I can put this in a Google Doc or Sheet, or post one draft after you say yes."
    )
    return "\n".join(lines).strip()


def campaign_as_sheet(plan: dict[str, Any]) -> tuple[list[str], list[list[str]]]:
    headers = ["Kind", "Item"]
    rows: list[list[str]] = []
    for kw in plan.get("keywords") or []:
        rows.append(["phrase", str(kw)])
    for post in plan.get("posts") or []:
        rows.append(["post draft", str(post)])
    for item in plan.get("weeks") or []:
        rows.append(["week", str(item)])
    for item in plan.get("page") or []:
        rows.append(["page", str(item)])
    return headers, rows


def campaign_as_doc(plan: dict[str, Any]) -> str:
    return format_campaign(plan)
