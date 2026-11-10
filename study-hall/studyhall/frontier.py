"""Crawl frontier. Budgets pace the room. They do not stop it."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable
from urllib.parse import urlparse

from studyhall.embed import cosine, keyword_overlap
from studyhall.pages import QUEUED_PER_HOST, is_marketing
from studyhall.search import (
    AMBIGUOUS_TERMS,
    community_targets,
    has_ai_context,
    is_disambiguation,
    leads_from_document,
    search_targets,
    wikipedia_chrome,
    wikipedia_host,
)

INDEX_KINDS = {"wikipedia", "arxiv", "openalex", "semanticscholar", "crossref", "hn", "reddit", "duckduckgo", "bluesky", "searxng"}
PAGE_KINDS = {"article", "paper", "thread", "post", "pdf", "video"}

RELEVANCE_FLOOR = 0.5
EMBED_ACCEPT = 0.72
Fetch = Callable[[str], Awaitable[object]]
Study = Callable[[dict], Awaitable[dict | None]]

# A lone "safety" or "checklist" is not the mission. These words never qualify a page by themselves.
_GENERIC = frozenset({
    "safety", "guide", "guides", "tips", "tip", "checklist", "checklists",
    "training", "talk", "talks", "inspection", "inspections", "tool", "tools",
    "manual", "manuals", "workplace", "osha", "procedure", "procedures",
    "hand", "hands",
})
DRIFT_HOSTS = frozenset({
    "safetymanualosha.com",
    "simplysub.com",
    "safetytalklibrary.com",
})


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def _host(url: str) -> str:
    return (urlparse(url or "").hostname or "").lower().removeprefix("www.")


def host_penalized(host: str, mission: dict) -> bool:
    name = (host or "").lower().removeprefix("www.")
    banned = set(DRIFT_HOSTS) | {str(item).lower().removeprefix("www.") for item in mission.get("drift_hosts") or []}
    return any(name == item or name.endswith("." + item) for item in banned if item)


def matches_mission(
    text: str,
    mission: dict,
    *,
    vector: list[float] | None = None,
    mission_vector: list[float] | None = None,
) -> tuple[bool, float, str]:
    """True only for assistant-context terms, or a high embedding match.

    Generic words that also appear in the mission (safety, tool, talk) are not enough.
    """
    semantic = 0.0
    if vector and mission_vector and len(vector) == len(mission_vector):
        semantic = max(0.0, cosine(vector, mission_vector))
    if semantic >= EMBED_ACCEPT:
        return True, semantic, f"Followed. Embedding similarity {semantic:.2f} against the mission."
    ambiguous = sorted(_tokens(text) & AMBIGUOUS_TERMS)
    generic = sorted(_tokens(text) & _GENERIC)
    if has_ai_context(text):
        score = max(semantic, min(1.0, 0.75 if ambiguous else 0.5))
        return True, score, "Followed. The title or lead has an AI sense."
    if ambiguous:
        named = ", ".join(ambiguous)
        return False, semantic, f"Skipped. '{named}' is another sense unless the title or lead says it is about AI."
    named = ", ".join(generic[:4]) or "those words"
    return False, semantic, f"Skipped. '{named}' is not enough without an assistant, model, or AI term."


def score_relevance(text: str, mission: dict, *, vector: list[float] | None = None, mission_vector: list[float] | None = None) -> float:
    ok, score, _reason = matches_mission(text, mission, vector=vector, mission_vector=mission_vector)
    if ok:
        return max(score, RELEVANCE_FLOOR)
    return min(score, RELEVANCE_FLOOR - 0.01)


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


def _queued_on_host(items: list[dict], host: str) -> int:
    return sum(1 for item in items if _host(str(item.get("url") or "")) == host and item.get("status") == "queued")


def enqueue(frontier: list[dict], leads: list[dict], mission_id: str) -> list[dict]:
    seen = {item.get("url") for item in frontier}
    out = list(frontier)
    for lead in leads:
        url = lead.get("url") or ""
        if not url or url in seen:
            continue
        if is_marketing(url, str(lead.get("title") or "")):
            continue
        host = _host(url)
        if host and _queued_on_host(out, host) >= QUEUED_PER_HOST:
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


def _cooling_hosts(mission: dict, now: float) -> set[str]:
    cooling = set()
    for host, until in (mission.get("host_cooldown") or {}).items():
        try:
            if float(until) > now:
                cooling.add(str(host).lower())
        except (TypeError, ValueError):
            continue
    return cooling


def seed_leads(mission: dict, *, searxng: str = "", now: float = 0.0) -> list[dict]:
    queries = list(mission.get("queries") or [])
    if not queries:
        queries = [mission.get("title") or "assistant"]
    cursor = int(mission.get("query_cursor") or 0) % len(queries)
    query = queries[cursor]
    leads = []
    for target in search_targets(query, searxng=searxng, skip_hosts=_cooling_hosts(mission, now)):
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


_MARKETING = (
    "/pricing", "/product", "/features/", "github.com/features", "/login", "/signup",
    "/enterprise", "/solutions", "/marketplace", "/customer-stories",
    "copilot", "codespaces", "secret-protection", "/security/secret",
)
_HOST_CAP = 4


def _lead_blob(lead: dict) -> str:
    """Title, URL, and lead text. The reason we queued it is not evidence."""
    return " ".join([
        str(lead.get("title") or ""),
        str(lead.get("url") or ""),
        str(lead.get("text") or ""),
    ])


def _canon(url: str) -> str:
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = (parsed.path or "").rstrip("/")
    return f"{host}{path}"


def _wikipedia(url: str) -> bool:
    host = wikipedia_host(url)
    return host.endswith("wikipedia.org") or host.endswith("wikimedia.org")


def _cap_queued(items: list[dict], limit: int) -> tuple[list[dict], int]:
    counts: dict[str, int] = {}
    kept: list[dict] = []
    dropped = 0
    for item in items:
        if item.get("status") != "queued":
            kept.append(item)
            continue
        host = _host(str(item.get("url") or ""))
        seen = counts.get(host, 0)
        if host and seen >= limit:
            dropped += 1
            continue
        counts[host] = seen + 1
        kept.append(item)
    return kept, dropped


def _penalize_host(mission: dict, host: str, now: float) -> None:
    """Deprioritize a host for an hour. Other readings on that host can still be queued."""
    if not host:
        return
    penalties = mission.setdefault("host_penalty", {})
    try:
        current = float(penalties.get(host) or 0)
    except (TypeError, ValueError):
        current = 0.0
    penalties[host] = max(current, now + 3600)


def drop_children(frontier: list[dict], page_url: str) -> list[dict]:
    page = _canon(page_url)
    if not page:
        return frontier
    kept = []
    for item in frontier:
        parent = _canon(str(item.get("from_url") or ""))
        if parent and parent == page and item.get("status") in {"queued", "error", "retry"}:
            continue
        kept.append(item)
    return kept


def _vectors(vector_of, text: str, mission: dict) -> tuple[list[float] | None, list[float] | None]:
    if vector_of is None:
        return None, None
    blob = " ".join(mission.get("queries") or []) + " " + str(mission.get("brief") or "") + " " + str(mission.get("title") or "")
    try:
        return vector_of(text[:2000]), vector_of(blob[:2000])
    except Exception:
        return None, None


def _preflight(lead: dict, mission: dict, frontier: list[dict], now: float, vector_of=None) -> tuple[bool, str]:
    """Score a lead before spending a fetch. Indexes are decided by the caller."""
    blob = _lead_blob(lead)
    lowered = blob.lower()
    host = _host(str(lead.get("url") or ""))
    if host_penalized(host, mission):
        return False, f"Skipped. {host} drifted off the mission, so its links are dropped."
    if wikipedia_chrome(str(lead.get("url") or ""), str(lead.get("title") or "")):
        return False, "Skipped. Wikipedia navigation, other languages, and project pages are not readings."
    if "disambiguation" in lowered:
        return True, "Disambiguation page. Only entries with an AI sense will be followed."
    if is_marketing(str(lead.get("url") or ""), str(lead.get("title") or "")) or any(bit in lowered for bit in _MARKETING):
        return False, "Skipped before fetching. This is a product, pricing, or other marketing page."
    lead_vector, mission_vector = _vectors(vector_of, blob, mission)
    ok, score, reason = matches_mission(blob, mission, vector=lead_vector, mission_vector=mission_vector)
    recent = [
        item for item in frontier
        if _host(str(item.get("url") or "")) == host
        and item.get("status") == "read"
        and now - float(item.get("read_at") or 0) < 3600
    ]
    if host and len(recent) >= _HOST_CAP and score < 0.85:
        return False, f"Skipped. {host} already had {len(recent)} pages this hour, and this lead scores {score:.2f}."
    if not ok:
        return False, "Skipped before fetching. " + reason
    return True, reason


def prune_frontier(items: list[dict], mission: dict) -> tuple[list[dict], int]:
    """Drop queued leads on hosts that drifted, and leads with no assistant terms."""
    kept: list[dict] = []
    dropped = 0
    for item in items:
        host = _host(str(item.get("url") or ""))
        waiting = item.get("status") in {"queued", "error", "retry", "off_topic", "marketing"}
        if waiting and host_penalized(host, mission):
            dropped += 1
            continue
        if waiting and is_marketing(str(item.get("url") or ""), str(item.get("title") or "")):
            dropped += 1
            continue
        if waiting and wikipedia_chrome(str(item.get("url") or ""), str(item.get("title") or "")):
            dropped += 1
            continue
        if waiting and _wikipedia(str(item.get("url") or "")) and not has_ai_context(_lead_blob(item)):
            dropped += 1
            continue
        if waiting and item.get("kind") not in INDEX_KINDS:
            ok, _score, _reason = matches_mission(_lead_blob(item), mission)
            if not ok:
                dropped += 1
                continue
        kept.append(item)
    kept, overflow = _cap_queued(kept, QUEUED_PER_HOST)
    return kept, dropped + overflow


def penalize(frontier: list[dict], mission: dict, host: str, page_url: str) -> list[dict]:
    """Drop this page's children. A shared encyclopedia is not banned outright."""
    wiki = _wikipedia("https://" + host) if host else False
    if host and not wiki:
        mission.setdefault("drift_hosts", [])
        if host not in mission["drift_hosts"]:
            mission["drift_hosts"].append(host)
    kept = drop_children(frontier, page_url)
    if wiki:
        return kept
    narrowed = []
    for item in kept:
        if _host(str(item.get("url") or "")) == host and item.get("status") in {"queued", "error", "retry"}:
            continue
        narrowed.append(item)
    return narrowed


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
    classify=None,
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
    cooling = _cooling_hosts(mission, now)
    queued = [
        item for item in frontier
        if item.get("mission_id") == mission_id and _due(item, now) and int(item.get("depth") or 0) <= max_depth
        and _host(str(item.get("url") or "")) not in cooling
    ]
    if not queued:
        seeded = seed_leads(mission, searxng=searxng, now=now)
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
    recent_hosts = {
        _host(str(item.get("url") or ""))
        for item in frontier
        if item.get("status") == "read" and now - float(item.get("read_at") or 0) < 3600
    }
    penalized = mission.get("host_penalty") or {}

    def _held(lead: dict) -> int:
        host = _host(str(lead.get("url") or ""))
        if host in recent_hosts:
            return 1
        try:
            if float(penalized.get(host) or 0) > now:
                return 1
        except (TypeError, ValueError):
            pass
        return 0

    queued.sort(key=lambda lead: (_held(lead), 0 if lead.get("kind") in PAGE_KINDS or lead.get("text") else 1, int(lead.get("depth") or 0)))
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
    if item.get("kind") not in INDEX_KINDS:
        allowed, reason = _preflight(item, mission, frontier, now, vector_of=vector_of)
        if not allowed:
            updated = {**item, "status": "off_topic"}
            return Step(
                action="skip",
                status="running",
                frontier=drop_children(_replace(frontier, item["lead_id"], updated), url),
                events=[{"event": "activity", "data": {"message": reason, "url": url}}],
            )
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
            wait = float(getattr(reading, "retry_after", 0) or 0) or _backoff(tries)
            host = _host(url)
            updated = {**item, "status": "error", "tries": tries, "retry_at": now + wait}
            nxt = _replace(frontier, item["lead_id"], updated)
            note = message or "This page will be tried again."
            if "semanticscholar.org" in host:
                mission.setdefault("host_cooldown", {})[host] = now + wait
                query = (mission.get("queries") or ["assistant"])[0]
                from urllib.parse import quote_plus
                q = quote_plus(query)
                nxt = enqueue(nxt, [
                    {"url": f"https://api.openalex.org/works?search={q}&per-page=5", "title": query, "why": "OpenAlex while Semantic Scholar cools down", "depth": 0, "kind": "openalex"},
                    {"url": f"https://export.arxiv.org/api/query?search_query=all:{q}&start=0&max_results=5", "title": query, "why": "arXiv while Semantic Scholar cools down", "depth": 0, "kind": "arxiv"},
                ], mission_id)
                note = f"Semantic Scholar returned 429. Waiting {int(wait)}s and using OpenAlex and arXiv."
            return Step(
                action="error",
                status="running",
                wait=min(20.0, wait),
                frontier=nxt,
                events=[{"event": "activity", "data": {"message": note, "url": url}}],
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
            events=[{"event": "activity", "data": {"message": f"Skipped because '{block}' is blocked.", "url": url}}],
        )
    lead_text = (title or "") + "\n" + (text or "")[:700]
    page_vector, mission_vector = _vectors(vector_of, text, mission)
    if is_disambiguation(title or item.get("title") or "", text, url):
        parse_kind = item.get("kind") or kind or ""
        body = raw or text
        leads, communities = leads_from_document(parse_kind, url, body, depth=int(item.get("depth") or 0))
        kept = [
            lead for lead in leads
            if int(lead.get("depth") or 0) <= max_depth
            and not is_blocked(lead["url"], lead.get("title") or "", mission)
            and not wikipedia_chrome(lead["url"], lead.get("title") or "")
            and has_ai_context(f"{lead.get('title') or ''} {lead.get('url') or ''}")
        ]
        updated = {**item, "status": "disambiguation", "relevance": 0}
        return Step(
            action="skip",
            status="running",
            frontier=enqueue(drop_children(_replace(frontier, item["lead_id"], updated), url), kept, mission_id),
            events=[{"event": "activity", "data": {"message": f"Disambiguation page. Followed {len(kept)} entries that name an AI sense.", "url": url}}],
            edges=[{"from": url, "to": lead["url"], "why": lead["why"], "mission_id": mission_id} for lead in kept],
            communities=communities,
        )
    if is_marketing(url, title or item.get("title") or "", text=text, raw=raw or ""):
        _penalize_host(mission, _host(url), now)
        updated = {**item, "status": "marketing", "relevance": 0}
        return Step(
            action="skip",
            status="running",
            wait=0.0,
            frontier=drop_children(_replace(frontier, item["lead_id"], updated), url),
            events=[{"event": "activity", "data": {"message": "Skipped. The page is product, pricing, or other marketing, so the panel was not asked and its links were dropped.", "url": url}}],
        )
    on_topic, relevance, topic_reason = matches_mission(lead_text, mission, vector=page_vector, mission_vector=mission_vector)
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
    if not on_topic:
        host = _host(url)
        updated = {**item, "status": "off_topic", "relevance": relevance}
        cleaned = penalize(_replace(frontier, item["lead_id"], updated), mission, host, url)
        return Step(
            action="skip",
            status="running",
            wait=0.0,
            frontier=cleaned,
            events=[looking, {"event": "activity", "data": {"message": f"Off topic ({topic_reason}) The panel was not asked, and links from this page were dropped.", "url": url}}],
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
    if classify is not None:
        try:
            verdict = await classify(url, title or item.get("title") or "", (text or "")[:1500])
        except Exception:
            verdict = {"kind": "research_or_educational", "reason": "The page-type check did not answer."}
        if str((verdict or {}).get("kind") or "") == "marketing_pr_tool":
            reason = str((verdict or {}).get("reason") or "It reads as marketing.")
            _penalize_host(mission, _host(url), now)
            updated = {**item, "status": "marketing", "relevance": relevance}
            return Step(
                action="skip",
                status="running",
                wait=0.0,
                frontier=drop_children(_replace(frontier, item["lead_id"], updated), url),
                events=[looking, {"event": "activity", "data": {"message": f"Skipped. The page looks like marketing. {reason} The panel was not asked and its links were dropped.", "url": url}}],
            )
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
    events = [looking, {"event": "activity", "data": {"message": f"Followed '{item.get('why') or 'a lead'}'. {topic_reason}", "url": url}}]
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
