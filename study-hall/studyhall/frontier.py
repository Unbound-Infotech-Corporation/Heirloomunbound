"""Crawl frontier. Budgets pace the room. They do not stop it."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable
from urllib.parse import urlparse

from studyhall.embed import cosine, keyword_overlap
from studyhall.search import community_targets, leads_from_document, search_targets

INDEX_KINDS = {"wikipedia", "arxiv", "openalex", "semanticscholar", "crossref", "hn", "reddit", "duckduckgo", "bluesky", "searxng"}
PAGE_KINDS = {"article", "paper", "thread", "post", "pdf", "video"}

RELEVANCE_FLOOR = 0.5
Fetch = Callable[[str], Awaitable[object]]
Study = Callable[[dict], Awaitable[dict | None]]


def score_relevance(text: str, mission: dict, *, vector: list[float] | None = None, mission_vector: list[float] | None = None) -> float:
    """Lexical overlap, lifted by a local embedding when one is already in hand."""
    blob = " ".join(mission.get("queries") or []) + " " + str(mission.get("brief") or "") + " " + str(mission.get("title") or "")
    lexical = min(1.0, keyword_overlap(blob, text) / 3)
    if vector and mission_vector and len(vector) == len(mission_vector):
        semantic = max(0.0, cosine(vector, mission_vector))
        return max(lexical, semantic)
    return lexical


def is_blocked(url: str, text: str, mission: dict) -> str:
    hay = f"{url} {text}".lower()
    host = (urlparse(url).hostname or "").lower()
    for blocked in mission.get("blocked_hosts") or []:
        if blocked and blocked in host:
            return str(blocked)
    for term in mission.get("blocked_terms") or []:
        if term and str(term).lower() in hay:
            return str(term)
    return ""


def highlight_span(text: str, mission: dict) -> str:
    """The sentence that best matches the mission, for the reader highlight."""
    sentences = [part.strip() for part in text.replace("\n", " ").split(". ") if part.strip()]
    if not sentences:
        return ""
    blob = " ".join(mission.get("queries") or [])
    best = max(sentences, key=lambda sentence: keyword_overlap(blob, sentence))
    if keyword_overlap(blob, best) == 0:
        return sentences[0][:280]
    return best[:280]


@dataclass
class Step:
    action: str
    status: str
    wait: float = 0.0
    frontier: list = field(default_factory=list)
    events: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    communities: list = field(default_factory=list)
    read: bool = False


def _lead_id() -> str:
    return f"led_{uuid.uuid4().hex[:12]}"


def enqueue(frontier: list[dict], leads: list[dict], mission_id: str) -> list[dict]:
    seen = {item.get("url") for item in frontier}
    out = list(frontier)
    for lead in leads:
        url = lead.get("url") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        out.append({
            "lead_id": lead.get("lead_id") or _lead_id(),
            "mission_id": mission_id,
            "url": url,
            "title": lead.get("title") or url,
            "why": lead.get("why") or "Followed a lead",
            "from_url": lead.get("from_url") or "",
            "depth": int(lead.get("depth") or 0),
            "kind": lead.get("kind") or "article",
            "text": (lead.get("text") or "")[:4000],
            "status": "queued",
            "tries": 0,
        })
    return out


def seed_leads(mission: dict, *, searxng: str = "") -> list[dict]:
    queries = list(mission.get("queries") or [])
    if not queries:
        queries = [mission.get("title") or "assistant"]
    cursor = int(mission.get("query_cursor") or 0) % len(queries)
    query = queries[cursor]
    leads = []
    for target in search_targets(query, searxng=searxng):
        leads.append({
            "url": target["url"],
            "title": query,
            "why": target["why"],
            "from_url": "",
            "depth": 0,
            "kind": target["kind"],
        })
    community_leads, notices = community_targets(mission.get("communities") or [])
    for target in community_leads:
        leads.append({
            "url": target["url"],
            "title": mission.get("title") or "",
            "why": target["why"],
            "from_url": "",
            "depth": 0,
            "kind": target["kind"],
        })
    if notices and not mission.get("reddit_noted"):
        mission["reddit_noted"] = True
        mission["_notices"] = notices
    mission["query_cursor"] = cursor + 1
    return leads


def seconds_until_next_page(reads_at: list[float], now: float, pages_per_hour: int) -> float:
    """How long to wait so the room stays under the pace. Zero means go ahead."""
    pace = max(1, int(pages_per_hour or 1))
    gap = 3600 / pace
    recent = [stamp for stamp in reads_at if now - stamp < 3600]
    if recent and now - max(recent) < gap:
        return gap - (now - max(recent))
    if len(recent) >= pace:
        return max(0.0, 3600 - (now - min(recent)))
    return 0.0


def _due(item: dict, now: float) -> bool:
    if item.get("status") == "queued":
        return True
    if item.get("status") == "error" and float(item.get("retry_at") or 0) <= now:
        return True
    return False


def _replace(frontier: list[dict], lead_id: str, updated: dict) -> list[dict]:
    return [updated if item.get("lead_id") == lead_id else item for item in frontier]


def _backoff(tries: int) -> float:
    return float(min(300, 5 * (2 ** max(0, tries - 1))))


async def work_once(
    *,
    mission: dict,
    frontier: list[dict],
    fetch: Fetch,
    study: Study,
    now: float,
    reads_at: list[float],
    searxng: str = "",
    vector_of=None,
) -> Step:
    """One unit of work. A dry frontier, a full pace, or a dead network does not stop the mission."""
    status = str(mission.get("status") or "stopped")
    if status != "running":
        return Step(action="idle", status=status, wait=0.5, frontier=frontier)
    wait = seconds_until_next_page(reads_at, now, int(mission.get("pages_per_hour") or 600))
    if wait > 0:
        return Step(
            action="pace",
            status="running",
            wait=wait,
            frontier=frontier,
            events=[{"event": "activity", "data": {"message": "Pacing. The hourly page budget only slows the room.", "url": ""}}],
        )
    mission_id = mission["mission_id"]
    max_depth = int(mission.get("max_depth") or 2)
    queued = [
        item for item in frontier
        if item.get("mission_id") == mission_id and _due(item, now) and int(item.get("depth") or 0) <= max_depth
    ]
    if not queued:
        seeded = seed_leads(mission, searxng=searxng)
        events = [{"event": "activity", "data": {"message": "The frontier was quiet, so the mission seeded the next queries and watched communities.", "url": ""}}]
        for note in mission.pop("_notices", []) or []:
            events.append({"event": "activity", "data": {"message": note, "url": ""}})
        return Step(
            action="reseed",
            status="running",
            wait=0.2,
            frontier=enqueue(frontier, seeded, mission_id),
            events=events,
        )
    queued.sort(key=lambda lead: (0 if lead.get("kind") in PAGE_KINDS or lead.get("text") else 1, int(lead.get("depth") or 0)))
    item = queued[0]
    if "reddit.com" in (item.get("url") or "") and not item.get("text"):
        updated = {**item, "status": "needs_key"}
        return Step(
            action="skip",
            status="running",
            frontier=_replace(frontier, item["lead_id"], updated),
            events=[{"event": "activity", "data": {"message": "Reddit blocks anonymous reading. It is listed under communities to watch, not fetched.", "url": item["url"]}}],
        )
    url = item["url"]
    try:
        reading = await fetch(url)
    except Exception as exc:  # network or parser — back off, stay running
        tries = int(item.get("tries") or 0) + 1
        updated = {**item, "status": "error", "tries": tries, "retry_at": now + _backoff(tries), "error": exc.__class__.__name__}
        return Step(
            action="error",
            status="running",
            wait=min(30.0, _backoff(tries)),
            frontier=_replace(frontier, item["lead_id"], updated),
            events=[{"event": "activity", "data": {"message": f"Could not read this page ({exc.__class__.__name__}). It will be tried again.", "url": url}}],
        )
    read_status = getattr(reading, "status", "") or (reading.get("status") if isinstance(reading, dict) else "")
    text = getattr(reading, "text", "") if not isinstance(reading, dict) else reading.get("text") or ""
    title = getattr(reading, "title", "") if not isinstance(reading, dict) else reading.get("title") or ""
    kind = getattr(reading, "kind", "") if not isinstance(reading, dict) else reading.get("kind") or item.get("kind") or ""
    raw = getattr(reading, "raw", "") if not isinstance(reading, dict) else reading.get("raw") or ""
    items = getattr(reading, "items", None) if not isinstance(reading, dict) else reading.get("items")
    message = getattr(reading, "message", "") if not isinstance(reading, dict) else reading.get("message") or ""
    if read_status != "ok":
        abstract = (item.get("text") or "").strip()
        temporary = bool(getattr(reading, "temporary", False)) or read_status in {"retry", "error"}
        if temporary and len(abstract) < 80:
            tries = int(item.get("tries") or 0) + 1
            updated = {**item, "status": "error", "tries": tries, "retry_at": now + _backoff(tries)}
            return Step(
                action="error",
                status="running",
                wait=min(20.0, _backoff(tries)),
                frontier=_replace(frontier, item["lead_id"], updated),
                events=[{"event": "activity", "data": {"message": message or "This page will be tried again.", "url": url}}],
            )
        if len(abstract) >= 80 and read_status in {"robots", "paywall", "error", "retry"}:
            text = abstract
            title = title or item.get("title") or url
            message = message or "The landing page was closed, so the API abstract is what the panel reads."
        else:
            updated = {**item, "status": read_status or "skip"}
            return Step(
                action="skip",
                status="running",
                wait=0.0,
                frontier=_replace(frontier, item["lead_id"], updated),
                events=[{"event": "activity", "data": {"message": message or f"Skipped ({read_status}).", "url": url}}],
            )
    if item.get("kind") in INDEX_KINDS and read_status == "ok":
        parse_kind = item.get("kind") or ""
        body = raw or text
        leads, communities = leads_from_document(parse_kind, url, body, depth=int(item.get("depth") or 0))
        for entry in items or []:
            if isinstance(entry, dict) and entry.get("url"):
                leads.append({
                    "url": entry["url"],
                    "title": entry.get("title") or entry["url"],
                    "why": "Item in the feed",
                    "from_url": url,
                    "depth": int(item.get("depth") or 0) + 1,
                    "kind": "article",
                })
        kept = [lead for lead in leads if int(lead.get("depth") or 0) <= max_depth and not is_blocked(lead["url"], lead.get("title") or "", mission)]
        updated = {**item, "status": "read", "read_at": now}
        return Step(
            action="read",
            status="running",
            frontier=enqueue(_replace(frontier, item["lead_id"], updated), kept, mission_id),
            events=[{"event": "activity", "data": {"message": f"Opened a public index and followed {len(kept)} leads. The panel waits for a real page.", "url": url}}],
            edges=[{"from": url, "to": lead["url"], "why": lead["why"], "mission_id": mission_id} for lead in kept],
            communities=communities,
            read=True,
        )
    block = is_blocked(url, f"{title} {text}", mission)
    if block:
        updated = {**item, "status": "blocked"}
        return Step(
            action="skip",
            status="running",
            wait=0.0,
            frontier=_replace(frontier, item["lead_id"], updated),
            events=[{"event": "activity", "data": {"message": f"Skipped because “{block}” is blocked.", "url": url}}],
        )
    mission_vector = None
    page_vector = None
    if vector_of is not None:
        try:
            page_vector = vector_of(text[:2000])
            mission_vector = vector_of(" ".join(mission.get("queries") or []))
        except Exception:
            page_vector = None
    relevance = score_relevance(text, mission, vector=page_vector, mission_vector=mission_vector)
    mark = highlight_span(text, mission)
    looking = {
        "event": "looking",
        "data": {
            "url": url,
            "title": title or item.get("title") or url,
            "text": text[:4000],
            "highlight": mark,
            "why": item.get("why") or "",
            "from_url": item.get("from_url") or "",
            "kind": kind or item.get("kind") or "",
            "relevance": round(relevance, 3),
        },
    }
    if relevance < RELEVANCE_FLOOR:
        updated = {**item, "status": "irrelevant", "relevance": relevance}
        return Step(
            action="skip",
            status="running",
            wait=0.0,
            frontier=_replace(frontier, item["lead_id"], updated),
            events=[looking, {"event": "activity", "data": {"message": f"Read the title and moved on. Relevance {relevance:.2f} is below the line, so the panel was not asked.", "url": url}}],
        )
    parse_kind = item.get("kind") or kind or ""
    body = raw or text
    leads, communities = leads_from_document(parse_kind, url, body, depth=int(item.get("depth") or 0))
    for entry in items or []:
        if not isinstance(entry, dict) or not entry.get("url"):
            continue
        leads.append({
            "url": entry["url"],
            "title": entry.get("title") or entry["url"],
            "why": "Item in the feed",
            "from_url": url,
            "depth": int(item.get("depth") or 0) + 1,
            "kind": "article",
        })
    kept = [lead for lead in leads if int(lead.get("depth") or 0) <= max_depth and not is_blocked(lead["url"], lead.get("title") or "", mission)]
    edges = [{"from": url, "to": lead["url"], "why": lead["why"], "mission_id": mission_id} for lead in kept]
    study_payload = None
    try:
        study_payload = await study({
            "url": url,
            "title": title,
            "text": text,
            "date": getattr(reading, "date", "") if not isinstance(reading, dict) else reading.get("date") or "",
            "kind": kind,
            "tag": mission.get("tag") or "",
            "focus": mission.get("tag") or "",
        })
    except Exception as exc:
        tries = int(item.get("tries") or 0) + 1
        updated = {**item, "status": "error", "tries": tries, "retry_at": now + _backoff(tries)}
        return Step(
            action="error",
            status="running",
            wait=min(30.0, _backoff(tries)),
            frontier=enqueue(_replace(frontier, item["lead_id"], updated), kept, mission_id),
            events=[looking, {"event": "activity", "data": {"message": f"The panel did not answer ({exc.__class__.__name__}). The page stays queued for another try.", "url": url}}],
            edges=edges,
            communities=communities,
        )
    updated = {**item, "status": "read", "relevance": relevance, "read_at": now}
    events = [looking, {"event": "activity", "data": {"message": f"Followed “{item.get('why') or 'a lead'}” and asked the panel.", "url": url}}]
    if isinstance(study_payload, dict):
        events.extend(study_payload.get("events") or [])
    return Step(
        action="read",
        status="running",
        wait=0.0,
        frontier=enqueue(_replace(frontier, item["lead_id"], updated), kept, mission_id),
        events=events,
        edges=edges,
        communities=communities,
        read=True,
    )
