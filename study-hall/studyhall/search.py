"""Public search targets and lead parsing. No logins, no joins, no posts."""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse
from xml.etree import ElementTree

COMMUNITY_HOSTS = (
    "reddit.com",
    "news.ycombinator.com",
    "discord.gg",
    "discord.com",
    "facebook.com",
    "mastodon.social",
    "bsky.app",
)

# These words also name non-AI pages. Alone they are not a reason to follow.
AMBIGUOUS_TERMS = frozenset({
    "grounding", "hallucination", "hallucinations",
    "memory", "memories", "agent", "agents", "model", "models",
    "voice", "voices", "prompt", "prompts", "assistant", "assistants",
    "transformer", "transformers", "attention",
})
AI_TERMS = frozenset({
    "ai", "llm", "llms", "chatbot", "chatbots", "rag", "gpt", "gemini",
    "ollama", "personalization", "conversational", "nlp", "neural",
})
AI_PHRASES = (
    "artificial intelligence",
    "language model",
    "large language",
    "machine learning",
    "neural network",
    "deep learning",
    "prompt engineering",
    "intelligent agent",
    "virtual assistant",
    "voice user interface",
    "voice interface",
    "symbol grounding",
)
_WIKI_TITLE = (
    ("hallucination", "Hallucination (artificial intelligence)"),
    ("grounding", "grounding (artificial intelligence)"),
    ("transformer", "Transformer (deep learning)"),
    ("attention", "Attention (machine learning)"),
    ("prompt", "Prompt engineering"),
    ("agent", "Intelligent agent"),
    ("assistant", "Virtual assistant"),
    ("memory", "Memory (artificial intelligence)"),
    ("voice", "Voice user interface"),
    ("model", "Language model"),
)
_WIKI_NAMESPACES = frozenset({
    "special", "help", "wikipedia", "portal", "talk", "category", "file",
    "template", "user", "draft", "module", "mediawiki",
})
_WIKI_LABELS = frozenset({
    "main page", "contents", "contact us", "contact", "about", "about wikipedia",
})


def wikipedia_query(query: str) -> str:
    """Prefer the AI article when a query uses an ambiguous word."""
    text = " ".join((query or "").split())
    lowered = text.lower()
    extras = []
    for word, title in _WIKI_TITLE:
        if re.search(rf"\b{word}s?\b", lowered) and title.lower() not in lowered:
            extras.append(title)
    if not extras:
        return text
    return text + " " + " ".join(extras)


def _plain(text: str) -> str:
    return unquote(text or "").replace("_", " ").lower()


def has_ai_context(text: str) -> bool:
    focus = _plain(text)
    if any(phrase in focus for phrase in AI_PHRASES):
        return True
    tokens = set(re.findall(r"[a-z0-9]+", focus))
    return bool(tokens & AI_TERMS)


def wikipedia_host(url: str) -> str:
    return (urlparse(url or "").hostname or "").lower().removeprefix("www.")


def wikipedia_chrome(url: str, title: str = "") -> bool:
    """Main page, namespaces, contact/contents/about, and other-language wikis."""
    host = wikipedia_host(url)
    if not host.endswith("wikipedia.org") and not host.endswith("wikimedia.org"):
        return False
    if host not in {"en.wikipedia.org", "en.m.wikipedia.org"}:
        return True
    path = unquote(urlparse(url).path or "")
    if "/wiki/" not in path:
        return True
    name = path.split("/wiki/", 1)[1].split("?")[0].strip("/")
    head = name.split("/", 1)[0]
    spaced = head.replace("_", " ").lower()
    if spaced in _WIKI_LABELS or head.lower() in {"main_page"}:
        return True
    namespace = head.split(":", 1)[0].lower() if ":" in head else ""
    if namespace in _WIKI_NAMESPACES:
        return True
    label = " ".join((title or "").replace("_", " ").split()).lower()
    label = label.removesuffix(" - wikipedia").strip()
    if label in _WIKI_LABELS:
        return True
    return False


def is_disambiguation(title: str, text: str = "", url: str = "") -> bool:
    blob = f"{title} {url}".lower()
    if "disambiguation" in blob:
        return True
    head = (text or "")[:900].lower()
    return "may refer to" in head


def search_targets(query: str, *, searxng: str = "", skip_hosts: set[str] | None = None) -> list[dict]:
    """Free endpoints that are either allowed by robots or a documented public API.

    Wikipedia's robots.txt disallows ``/w/api.php`` except a few actions, and allows
    ordinary ``/wiki/`` articles. Reddit's robots.txt disallows anonymous fetches.
    Those two are not seeded here.
    """
    q = quote_plus(" ".join((query or "").split()))
    if not q:
        return []
    why = f"Search for {query.strip()}"
    targets = [
        {"url": f"https://api.openalex.org/works?search={q}&per-page=5", "kind": "openalex", "why": why},
        {"url": f"https://api.semanticscholar.org/graph/v1/paper/search?query={q}&limit=5&fields=title,url,abstract", "kind": "semanticscholar", "why": why},
        {"url": f"https://api.crossref.org/works?query={q}&rows=5", "kind": "crossref", "why": why},
        {"url": f"https://export.arxiv.org/api/query?search_query=all:{q}&start=0&max_results=5", "kind": "arxiv", "why": why},
        {"url": f"https://hn.algolia.com/api/v1/search?query={q}&tags=story&hitsPerPage=5", "kind": "hn", "why": why},
        {"url": f"https://html.duckduckgo.com/html/?q={quote_plus(wikipedia_query(query) + ' site:en.wikipedia.org')}", "kind": "duckduckgo", "why": why + " on Wikipedia"},
        {"url": f"https://html.duckduckgo.com/html/?q={q}", "kind": "duckduckgo", "why": why},
        {"url": f"https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?q={q}&limit=5", "kind": "bluesky", "why": why},
    ]
    base = (searxng or "").strip().rstrip("/")
    if base:
        targets.append({"url": f"{base}/search?q={q}&format=json", "kind": "searxng", "why": why})
    skipped = {host.lower() for host in (skip_hosts or set())}
    if not skipped:
        return targets
    return [item for item in targets if (urlparse(item["url"]).hostname or "").lower() not in skipped]


REDDIT_NOTE = (
    "Reddit’s robots.txt disallows anonymous reading, including RSS. "
    "Add a Reddit token in Automate if you want those communities. "
    "Study Hall will not pretend the threads were fetched."
)


def community_targets(communities: list[dict]) -> tuple[list[dict], list[str]]:
    out = []
    notices = []
    reddit = False
    for item in communities:
        url = str(item.get("url") or "")
        name = str(item.get("name") or url)
        if "reddit.com" in url:
            reddit = True
            continue
        if "news.ycombinator.com" in url:
            out.append({
                "url": "https://hn.algolia.com/api/v1/search?query=AI%20assistant&tags=story&hitsPerPage=5",
                "kind": "hn",
                "why": f"Watched community {name}",
            })
    if reddit:
        notices.append(REDDIT_NOTE)
    return out, notices


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        attr = {key.lower(): value or "" for key, value in attrs}
        self._href = attr.get("href") or ""
        self._text = []

    def handle_data(self, data):
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href:
            self.links.append((self._href, " ".join(self._text).strip()))
            self._href = ""


def _abs(base: str, href: str) -> str:
    if not href or href.startswith(("#", "mailto:", "javascript:")):
        return ""
    # DuckDuckGo wraps the real link in uddg=
    if "uddg=" in href:
        wrapped = parse_qs(urlparse(href).query).get("uddg", [])
        if wrapped:
            return wrapped[0]
    absolute = urljoin(base, href)
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"}:
        return ""
    return absolute.split("#", 1)[0]


def _worth_following(url: str, title: str) -> bool:
    """Citation-like links only. Site menus and login pages are not leads."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    if any(bit in path for bit in ("/login", "/signup", "/sign-in", "/help", "/faq", "/browse", "send_staff", "send_author")):
        return False
    if host.endswith("doi.org"):
        return path.startswith("/10.")
    if host.endswith("arxiv.org"):
        return path.startswith(("/abs/", "/pdf/", "/html/"))
    if "wikipedia.org" in host or host.endswith("wikimedia.org"):
        if wikipedia_chrome(url, title):
            return False
        return has_ai_context(f"{title} {unquote(url)}")
    if path.endswith(".pdf"):
        return True
    label = " ".join((title or "").split())
    if label.lower() in {"home", "contact", "search", "menu", "next", "previous", "login"}:
        return False
    return len(label.split()) >= 4


def _community_from_url(url: str) -> dict | None:
    host = (urlparse(url).hostname or "").lower()
    if host.endswith("reddit.com") and "/r/" in urlparse(url).path:
        name = urlparse(url).path.split("/r/", 1)[1].split("/", 1)[0]
        return {"name": f"r/{name}", "url": f"https://www.reddit.com/r/{name}/", "kind": "subreddit", "why": "Named in a public page"}
    if "discord.gg" in host or (host.endswith("discord.com") and "/invite" in url):
        return {"name": "Discord invite", "url": url, "kind": "discord", "why": "Listed on a public page. Study Hall does not join."}
    if host.endswith("facebook.com") and "/groups/" in url:
        return {"name": "Facebook group", "url": url, "kind": "facebook", "why": "Listed on a public page. Study Hall does not join."}
    if host.endswith("bsky.app"):
        return {"name": "Bluesky", "url": url, "kind": "bluesky", "why": "Public Bluesky page"}
    if "news.ycombinator.com" in host:
        return {"name": "Hacker News", "url": "https://news.ycombinator.com/", "kind": "forum", "why": "Named in a public page"}
    return None


def _openalex_abstract(work: dict) -> str:
    inverted = work.get("abstract_inverted_index") or {}
    if not isinstance(inverted, dict) or not inverted:
        return ""
    placed: list[tuple[int, str]] = []
    for word, positions in inverted.items():
        for position in positions or []:
            try:
                placed.append((int(position), str(word)))
            except (TypeError, ValueError):
                continue
    placed.sort()
    return " ".join(word for _pos, word in placed)[:4000]


def _youtube_id(url: str) -> str:
    parsed = urlparse(url)
    if "youtu.be" in (parsed.hostname or ""):
        return parsed.path.strip("/").split("/")[0]
    if "youtube.com" in (parsed.hostname or ""):
        return parse_qs(parsed.query).get("v", [""])[0]
    return ""


def leads_from_document(kind: str, page_url: str, body: str, *, depth: int) -> tuple[list[dict], list[dict]]:
    """Child links and communities to watch. Communities are listed, never joined."""
    leads: list[dict] = []
    communities: list[dict] = []
    next_depth = depth + 1

    def add_lead(url: str, title: str, why: str, lead_kind: str = "article"):
        if not url or not url.startswith("http"):
            return
        video = _youtube_id(url)
        if video:
            lead_kind = "video"
            why = why or "YouTube link on a public page. A transcript is read only if the page exposes one."
        leads.append({
            "url": url[:1000],
            "title": (title or url)[:240],
            "why": why[:240],
            "from_url": page_url,
            "depth": next_depth,
            "kind": lead_kind,
            "text": "",
        })

    def add_community(url: str):
        found = _community_from_url(url)
        if found:
            communities.append(found)

    kind = (kind or "").lower()
    raw = body or ""
    if kind == "wikipedia":
        try:
            payload = json.loads(raw)
            titles = payload[1] if len(payload) > 1 else []
            urls = payload[3] if len(payload) > 3 else []
            for index, url in enumerate(urls):
                title = titles[index] if index < len(titles) else url
                if wikipedia_chrome(str(url), str(title)) or not has_ai_context(f"{title} {url}"):
                    continue
                add_lead(url, title, "Wikipedia open search")
        except (json.JSONDecodeError, TypeError, IndexError):
            pass
    elif kind == "arxiv":
        try:
            root = ElementTree.fromstring(raw)
        except ElementTree.ParseError:
            root = None
        if root is not None:
            for node in root.iter():
                if _local(node.tag) != "entry":
                    continue
                title = ""
                link = ""
                for child in list(node):
                    if _local(child.tag) == "title":
                        title = "".join(child.itertext()).strip()
                    if _local(child.tag) == "id":
                        link = (child.text or "").strip()
                add_lead(link, title, "arXiv paper", "paper")
    elif kind in {"openalex", "semanticscholar", "crossref", "hn", "reddit", "searxng", "bluesky"}:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            if kind == "openalex":
                for work in payload.get("results") or []:
                    access = work.get("open_access") or {}
                    loc = access.get("oa_url") or ((work.get("primary_location") or {}).get("landing_page_url")) or work.get("doi") or work.get("id") or ""
                    add_lead(str(loc), str(work.get("display_name") or ""), "OpenAlex work", "paper")
                    if leads:
                        leads[-1]["text"] = _openalex_abstract(work)
            elif kind == "semanticscholar":
                for paper in payload.get("data") or []:
                    add_lead(str(paper.get("url") or ""), str(paper.get("title") or ""), "Semantic Scholar paper", "paper")
                    if leads:
                        leads[-1]["text"] = str(paper.get("abstract") or "")[:4000]
            elif kind == "crossref":
                for item in (payload.get("message") or {}).get("items") or []:
                    title = " ".join(item.get("title") or [])
                    link = ""
                    for candidate in item.get("link") or []:
                        if candidate.get("URL"):
                            link = candidate["URL"]
                            break
                    link = link or item.get("URL") or ""
                    add_lead(str(link), title, "Crossref work", "paper")
                    if leads:
                        leads[-1]["text"] = str(item.get("abstract") or "")[:4000]
            elif kind == "hn":
                for hit in payload.get("hits") or []:
                    url = hit.get("url") or hit.get("story_url") or ""
                    if not url and hit.get("objectID"):
                        url = f"https://news.ycombinator.com/item?id={hit['objectID']}"
                    add_lead(str(url), str(hit.get("title") or ""), "Hacker News story")
                    add_community("https://news.ycombinator.com/")
            elif kind == "reddit":
                children = ((payload.get("data") or {}).get("children")) or []
                for child in children:
                    data = child.get("data") or {}
                    permalink = data.get("permalink") or ""
                    url = data.get("url") or ""
                    title = data.get("title") or ""
                    if permalink:
                        add_lead("https://www.reddit.com" + permalink, title, "Public Reddit thread", "thread")
                    elif url:
                        add_lead(url, title, "Linked from a public Reddit post")
                    sub = data.get("subreddit")
                    if sub:
                        add_community(f"https://www.reddit.com/r/{sub}/")
            elif kind == "searxng":
                for hit in payload.get("results") or []:
                    add_lead(str(hit.get("url") or ""), str(hit.get("title") or ""), "SearXNG result")
            elif kind == "bluesky":
                for post in payload.get("posts") or []:
                    uri = str(post.get("uri") or "")
                    text = str((post.get("record") or {}).get("text") or "")
                    handle = str((post.get("author") or {}).get("handle") or "")
                    if handle:
                        add_community(f"https://bsky.app/profile/{handle}")
                    if uri:
                        add_lead(f"https://bsky.app/profile/{handle}", text[:80] or handle, "Public Bluesky post", "post")
    else:
        parser = _LinkParser()
        try:
            parser.feed(raw)
        except Exception:
            parser.links = []
        for href, text in parser.links:
            absolute = _abs(page_url, href)
            if not absolute:
                continue
            add_community(absolute)
            host = urlparse(absolute).hostname or ""
            if any(host.endswith(item) for item in COMMUNITY_HOSTS):
                continue
            if kind == "duckduckgo" and "uddg=" not in href and "uddg=" not in absolute:
                continue
            if kind != "duckduckgo" and not _worth_following(absolute, text):
                continue
            if wikipedia_chrome(absolute, text):
                continue
            if wikipedia_host(absolute).endswith("wikipedia.org") and not has_ai_context(f"{text} {unquote(absolute)}"):
                continue
            add_lead(absolute, text, "Link on the page")
        for match in re.findall(r"https?://arxiv\.org/abs/\d{4}\.\d{4,5}", raw):
            add_lead(match, match, "Cited arXiv id", "paper")

    # unique
    seen: set[str] = set()
    unique_leads = []
    for lead in leads:
        if lead["url"] in seen or lead["url"] == page_url:
            continue
        seen.add(lead["url"])
        unique_leads.append(lead)
    seen_c: set[str] = set()
    unique_communities = []
    for item in communities:
        if item["url"] in seen_c:
            continue
        seen_c.add(item["url"])
        unique_communities.append(item)
    return unique_leads[:12], unique_communities[:8]
