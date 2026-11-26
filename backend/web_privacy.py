"""Owner-only web search that never carries the owner's private words out.

A local model asked "find a recipe like the one my mom made in Duluth" may put
the private bits straight into the query. Before a query leaves the box it is
checked against the private texts the turn already holds (memory cards, the
archive, the owner's notes). A query that repeats a private phrase or a private
name is cut down to its public words; if nothing public is left it is refused.
Search goes through SearXNG on the LAN when ``HEIRLOOM_SEARXNG_URL`` is set
(no third-party account), otherwise DuckDuckGo. No cookies, no account, no
history is sent; only the query string.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Iterable

_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\-]*")
_COMMON = {
    "the", "and", "for", "with", "that", "this", "what", "when", "where", "how", "who", "why", "near",
    "best", "good", "recipe", "price", "news", "today", "weather", "open", "hours", "from", "about",
    "like", "into", "your", "our", "his", "her", "their", "there", "have", "has", "was", "were",
    "will", "would", "could", "should", "can", "find", "search", "look", "up", "latest", "new",
}
# Words that point at the owner's life and never belong in a search query.
_SELF = re.compile(r"\b(my|mine|me|i|i'm|i've|our|ours|we|us|grandma|grandpa|mom|dad|wife|husband|son|daughter)\b", re.I)


@dataclass
class Scrubbed:
    query: str
    removed: list[str] = field(default_factory=list)
    refused: bool = False


def private_vocabulary(private_texts: Iterable[str]) -> tuple[set[str], set[str]]:
    """Rare words and capitalised names from the private texts."""
    words: set[str] = set()
    names: set[str] = set()
    for text in private_texts or []:
        for token in _WORD.findall(text or ""):
            low = token.lower()
            if len(low) < 4 or low in _COMMON:
                continue
            words.add(low)
            if token[:1].isupper():
                names.add(low)
    return words, names


def scrub_query(query: str, private_texts: Iterable[str]) -> Scrubbed:
    raw = " ".join((query or "").split())
    if not raw:
        return Scrubbed(query="", refused=True)
    words, names = private_vocabulary(private_texts)
    kept: list[str] = []
    removed: list[str] = []
    for token in _WORD.findall(raw):
        low = token.lower()
        if _SELF.fullmatch(low):
            removed.append(token)
            continue
        # A private name always goes; a private word goes when it is not ordinary vocabulary.
        if low in names or (low in words and len(low) >= 6 and token[:1].isupper()):
            removed.append(token)
            continue
        kept.append(token)
    cleaned = " ".join(kept)
    useful = [t for t in kept if t.lower() not in _COMMON]
    return Scrubbed(query=cleaned, removed=removed, refused=not useful)


def search_backend() -> str:
    return "searxng" if os.environ.get("HEIRLOOM_SEARXNG_URL", "").strip() else "duckduckgo"


def searxng_search(query: str, max_results: int) -> list[dict]:
    import requests

    base = os.environ.get("HEIRLOOM_SEARXNG_URL", "").rstrip("/")
    response = requests.get(
        base + "/search",
        params={"q": query, "format": "json", "safesearch": 1},
        timeout=15,
        headers={"User-Agent": "Heirloom/1.0"},
    )
    response.raise_for_status()
    rows = (response.json() or {}).get("results") or []
    return [
        {"title": r.get("title") or "", "body": r.get("content") or "", "href": r.get("url") or ""}
        for r in rows[:max_results]
    ]


_PRIVATE_HOST = re.compile(
    r"^(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|169\.254\.|0\.0\.0\.0|\[?::1\]?|\[?f[cd][0-9a-f]{2}:)",
    re.I,
)


def public_url(url: str) -> bool:
    """web_fetch reads the public web only. LAN hosts and the box itself are off limits."""
    from urllib.parse import urlparse

    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if _PRIVATE_HOST.match(host) or host.endswith((".local", ".lan", ".internal", ".home.arpa")):
        return False
    if host in {"ollama", "mongo", "api", "web", "chatterbox", "odysseus"} or "." not in host:
        return False
    return True
