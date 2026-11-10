"""Fetch and clean readings. Honor robots.txt, wait between requests, skip paywalls."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Awaitable, Callable, Optional
from urllib.parse import quote_plus, urljoin, urlparse
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

import httpx

from studyhall.config import USER_AGENT

Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]

MAX_BYTES = 8_000_000
MAX_REDIRECTS = 4
PAYWALL_MARKERS = (
    "subscribe to continue",
    "subscribe to read",
    "sign in to read",
    "log in to read",
    "you've reached your free",
    "you have reached your free",
    "this article is for subscribers",
    "to continue reading",
    "register to continue",
    "already a subscriber",
)
SKIP_TAGS = {"script", "style", "noscript", "svg", "canvas", "iframe", "form", "nav", "footer", "aside", "button"}
BLOCKED_HOSTS = {
    "metadata.google.internal",
    "metadata.google.com",
}
BLOCKED_IPS = {"169.254.169.254", "169.254.170.2"}


@dataclass
class Reading:
    status: str
    url: str
    title: str = ""
    date: str = ""
    text: str = ""
    kind: str = "article"
    message: str = ""
    items: list[dict] = field(default_factory=list)
    content_type: str = ""
    raw: str = ""
    temporary: bool = False
    retry_after: float = 0.0

    def citation(self) -> dict:
        return {"title": self.title, "url": self.url, "date": self.date}


# Documented machine APIs. export.arxiv.org robots.txt is a blanket Disallow,
# which would make the public API unreachable. These prefixes are the API itself.
OFFICIAL_API_PREFIXES = (
    "https://export.arxiv.org/api/",
    "http://export.arxiv.org/api/",
    "https://api.openalex.org/",
    "http://api.openalex.org/",
    "https://api.semanticscholar.org/",
    "https://api.crossref.org/",
    "https://hn.algolia.com/",
)


def _retry_after(header: str | None, failures: int) -> float:
    raw = (header or "").strip()
    try:
        wait = float(raw)
    except ValueError:
        wait = 30.0 * (2 ** min(failures, 5))
    return max(15.0, min(wait, 900.0))


def official_api(url: str) -> bool:
    return any((url or "").startswith(prefix) for prefix in OFFICIAL_API_PREFIXES)


class _ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self._capture = False
        self._seen_body = False
        self._stack: list[str] = []
        self.title_parts: list[str] = []
        self.in_title = False
        self.meta: dict[str, str] = {}
        self.time_values: list[str] = []
        self.article: list[str] = []
        self.body: list[str] = []
        self._pending_time = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]):
        name = tag.lower()
        self._stack.append(name)
        attr = {key.lower(): (value or "") for key, value in attrs}
        if name in ("article", "main"):
            self._capture = True
        if name == "title":
            self.in_title = True
        if name == "meta":
            key = (attr.get("property") or attr.get("name") or "").lower()
            content = attr.get("content") or ""
            if key and content:
                self.meta[key] = content
        if name == "time" and attr.get("datetime"):
            self.time_values.append(attr["datetime"])
        if name in SKIP_TAGS:
            self._skip += 1

    def handle_endtag(self, tag: str):
        name = tag.lower()
        if name == "title":
            self.in_title = False
        if self._stack:
            self._stack.pop()
        if name in SKIP_TAGS and self._skip:
            self._skip -= 1
        if name in ("article", "main") and name not in self._stack:
            self._capture = "article" in self._stack or "main" in self._stack

    def handle_data(self, data: str):
        if self.in_title:
            self.title_parts.append(data)
        if self._skip or not data.strip():
            return
        if self._capture or "article" in self._stack or "main" in self._stack:
            self.article.append(data.strip())
        elif "body" in self._stack or self._seen_body:
            self.body.append(data.strip())
        if "body" in self._stack:
            self._seen_body = True


def _collapse(parts: list[str]) -> str:
    text = " ".join(part.strip() for part in parts if part and part.strip())
    return " ".join(text.split())


def extract_html(raw: str, url: str = "") -> dict:
    parser = _ArticleParser()
    try:
        parser.feed(raw or "")
        parser.close()
    except Exception:
        parser = _ArticleParser()
    title = (
        parser.meta.get("og:title")
        or parser.meta.get("twitter:title")
        or _collapse(parser.title_parts)
        or url
    )
    date = (
        parser.meta.get("article:published_time")
        or parser.meta.get("pubdate")
        or parser.meta.get("date")
        or parser.meta.get("dc.date")
        or (parser.time_values[0] if parser.time_values else "")
    )
    text = _collapse(parser.article) or _collapse(parser.body)
    return {"title": title.strip()[:300], "date": (date or "")[:40], "text": text[:80000]}


def looks_like_paywall(text: str, raw: str = "") -> bool:
    """A subscribe line in the article itself, with almost no article left to read.

    A footer button does not count. The marker has to be in the text we would keep.
    """
    del raw
    hay = (text or "").lower()
    if not any(marker in hay for marker in PAYWALL_MARKERS):
        return False
    return len(text or "") < 900


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _child_text(node: ElementTree.Element, name: str) -> str:
    for child in list(node):
        if _local(child.tag) == name:
            return "".join(child.itertext()).strip()
    return ""


def _link_href(node: ElementTree.Element) -> str:
    for child in list(node):
        if _local(child.tag) != "link":
            continue
        href = child.attrib.get("href") or ""
        rel = (child.attrib.get("rel") or "alternate").lower()
        if href and rel in {"alternate", ""}:
            return href.strip()
        text = (child.text or "").strip()
        if text.startswith("http"):
            return text
    return ""


def parse_feed(raw: str, page_url: str = "") -> list[dict]:
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        return []
    items: list[dict] = []
    for node in root.iter():
        kind = _local(node.tag)
        if kind not in {"item", "entry"}:
            continue
        title = _child_text(node, "title")
        link = _link_href(node) or _child_text(node, "link") or _child_text(node, "id")
        if link and page_url and not link.startswith("http"):
            link = urljoin(page_url, link)
        date = (
            _child_text(node, "pubDate")
            or _child_text(node, "published")
            or _child_text(node, "updated")
            or _child_text(node, "date")
        )
        summary = _child_text(node, "description") or _child_text(node, "summary")
        if title or link:
            items.append({
                "title": title[:300],
                "url": link[:1000],
                "date": date[:40],
                "summary": " ".join(summary.split())[:500],
            })
    return items[:40]


def extract_pdf(data: bytes) -> dict:
    from pypdf import PdfReader
    from io import BytesIO

    reader = PdfReader(BytesIO(data))
    meta = reader.metadata
    title = ""
    date = ""
    if meta is not None:
        title = str(meta.title or "")
        date = str(getattr(meta, "creation_date", "") or meta.get("/CreationDate") or "")
    pages = []
    for page in reader.pages[:40]:
        pages.append(page.extract_text() or "")
    text = "\n".join(pages)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return {"title": title.strip()[:300], "date": date[:40], "text": text.strip()[:80000]}


def _blocked_host(host: str) -> bool:
    name = (host or "").strip().lower().rstrip(".")
    if name in BLOCKED_HOSTS or name in BLOCKED_IPS:
        return True
    if name.endswith(".metadata.google.internal"):
        return True
    return False


def _origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


class PoliteClient:
    """One request at a time per host, after robots.txt, with no cookies and no paywall bypass."""

    def __init__(
        self,
        *,
        min_interval: float = 1.5,
        user_agent: str = USER_AGENT,
        clock: Clock | None = None,
        sleep: Sleep | None = None,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.min_interval = min_interval
        self.user_agent = user_agent
        self.clock = clock or time.monotonic
        self.sleep = sleep or asyncio.sleep
        self.timeout = timeout
        self._last: dict[str, float] = {}
        self._robots: dict[str, tuple[str, RobotFileParser | None]] = {}
        self._crawl: dict[str, float] = {}
        self._api_note: set[str] = set()
        self._cooldown: dict[str, float] = {}
        self._fail_count: dict[str, int] = {}
        self._lock = asyncio.Lock()
        self.client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/pdf,application/xml,text/xml,application/rss+xml,*/*;q=0.8",
            },
            transport=transport,
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    async def _reserve(self, host: str) -> float:
        async with self._lock:
            now = self.clock()
            interval = max(self.min_interval, self._crawl.get(host, 0.0))
            earliest = self._last.get(host, 0.0) + (interval if host in self._last else 0.0)
            wait = max(0.0, earliest - now)
            self._last[host] = now + wait
            return wait

    async def _get(self, url: str) -> httpx.Response:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Only web links can be read. Paste an http or https address.")
        host = parsed.hostname or ""
        if _blocked_host(host):
            raise ValueError("That address is not a reading source.")
        wait = await self._reserve(host)
        if wait:
            await self.sleep(wait)
        response = await self.client.get(url)
        if response.status_code in {301, 302, 303, 307, 308}:
            return response
        if len(response.content) > MAX_BYTES:
            raise ValueError("That file is larger than Study Hall will store.")
        return response

    async def _robots_body(self, origin: str) -> tuple[str, str]:
        """RFC 9309. Returns (allow_all|temporary|rules, body). Redirects are followed."""
        current = origin + "/robots.txt"
        for _hop in range(MAX_REDIRECTS + 1):
            try:
                response = await self._get(current)
            except httpx.HTTPError:
                return "temporary", ""
            except ValueError:
                return "temporary", ""
            code = response.status_code
            if code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location") or ""
                if not location:
                    return "temporary", ""
                current = urljoin(current, location)
                continue
            if code == 429 or code >= 500:
                return "temporary", ""
            if 400 <= code < 500:
                return "allow_all", ""
            if 200 <= code < 300:
                return "rules", response.text[:200_000]
            return "temporary", ""
        return "temporary", ""

    async def _robots_for(self, url: str) -> tuple[str, RobotFileParser | None]:
        origin = _origin(url)
        cached = self._robots.get(origin)
        if cached is not None:
            return cached
        mode, body = await self._robots_body(origin)
        if mode == "temporary":
            return "temporary", None
        parser = RobotFileParser()
        if mode == "allow_all":
            parser.parse(["User-agent: *", "Allow: /"])
        else:
            parser.parse(body.splitlines())
        delay = parser.crawl_delay(self.user_agent) or parser.crawl_delay("*")
        if delay:
            host = urlparse(url).hostname or ""
            # A published crawl-delay is politeness, capped so one host cannot stall the room for minutes.
            self._crawl[host] = max(self._crawl.get(host, 0.0), min(float(delay), 20.0))
        self._robots[origin] = (mode, parser)
        return mode, parser

    def _allowed(self, parser: RobotFileParser | None, url: str) -> bool:
        if official_api(url):
            host = urlparse(url).hostname or ""
            self._api_note.add(host)
            return True
        if parser is None:
            return False
        return bool(parser.can_fetch(self.user_agent, url))

    async def fetch(self, url: str) -> Reading:
        current = url
        try:
            for _hop in range(MAX_REDIRECTS + 1):
                parsed = urlparse(current)
                if parsed.scheme not in {"http", "https"} or _blocked_host(parsed.hostname or ""):
                    return Reading(status="error", url=url, message="That address is not a reading source.")
                mode, robots = await self._robots_for(current)
                if mode == "temporary":
                    return Reading(
                        status="retry",
                        url=current,
                        temporary=True,
                        message="robots.txt could not be reached. This page will be tried again.",
                    )
                if not self._allowed(robots, current):
                    return Reading(
                        status="robots",
                        url=current,
                        message="robots.txt asks Study Hall not to read this page.",
                    )
                response = await self._get(current)
                if response.status_code == 429:
                    host = parsed.hostname or ""
                    wait = _retry_after(response.headers.get("retry-after"), self._fail_count.get(host, 0))
                    self._fail_count[host] = self._fail_count.get(host, 0) + 1
                    self._cooldown[host] = time.time() + wait
                    return Reading(
                        status="retry",
                        url=current,
                        temporary=True,
                        retry_after=wait,
                        message=f"{host} returned 429. Waiting {int(wait)}s. Other sources will cover this query.",
                    )
                if response.status_code in {401, 402, 403}:
                    return Reading(
                        status="paywall",
                        url=current,
                        message="The site refused the page. Study Hall does not try to get around a login or a paywall.",
                    )
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location") or ""
                    if not location:
                        return Reading(status="error", url=current, message="The site redirected without a destination.")
                    current = urljoin(current, location)
                    continue
                if response.status_code >= 400:
                    return Reading(status="error", url=current, message=f"The site returned {response.status_code}.")
                return self._interpret(current, response)
        except ValueError as exc:
            return Reading(status="error", url=url, message=str(exc))
        except httpx.HTTPError:
            return Reading(status="error", url=url, message="The page could not be reached.")
        return Reading(status="error", url=url, message="Too many redirects.")

    def _interpret(self, url: str, response: httpx.Response) -> Reading:
        ctype = (response.headers.get("content-type") or "").lower()
        body = response.content[:MAX_BYTES]
        if "pdf" in ctype or url.lower().split("?", 1)[0].endswith(".pdf") or body.startswith(b"%PDF"):
            try:
                extracted = extract_pdf(body)
            except Exception:
                return Reading(status="error", url=url, message="This PDF could not be read.", content_type=ctype)
            if not extracted["text"]:
                return Reading(status="error", url=url, title=extracted["title"], message="This PDF has no extractable text.", kind="pdf")
            return Reading(
                status="ok",
                url=url,
                title=extracted["title"] or url,
                date=extracted["date"],
                text=extracted["text"],
                kind="pdf",
                content_type=ctype,
            )
        text_body = response.text
        head = text_body.lstrip()[:200].lower()
        if "html" not in ctype and ("json" in ctype or head.startswith("{") or head.startswith("[")):
            return Reading(status="ok", url=url, title=url, text=text_body[:80000], kind="json", content_type=ctype, raw=text_body[:200000])
        if "xml" in ctype or "rss" in ctype or "atom" in ctype or head.startswith("<?xml") or head.startswith("<rss") or head.startswith("<feed"):
            items = parse_feed(text_body, url)
            if items:
                title = items[0]["title"] if len(items) == 1 else urlparse(url).netloc
                return Reading(status="ok", url=url, title=title or url, kind="feed", items=items, content_type=ctype, raw=text_body[:200000])
        extracted = extract_html(text_body, url)
        if looks_like_paywall(extracted["text"], text_body):
            return Reading(
                status="paywall",
                url=url,
                title=extracted["title"],
                date=extracted["date"],
                text="",
                message="This looks like a paywalled page. The citation was kept and the article was not stored.",
                content_type=ctype,
            )
        if len(extracted["text"]) < 80:
            if "http" in text_body:
                return Reading(
                    status="ok",
                    url=url,
                    title=extracted["title"] or url,
                    date=extracted["date"],
                    text=extracted["text"] or extracted["title"],
                    kind="links",
                    content_type=ctype,
                    raw=text_body[:200000],
                )
            return Reading(
                status="error",
                url=url,
                title=extracted["title"],
                date=extracted["date"],
                message="This page had almost no readable text.",
                content_type=ctype,
            )
        return Reading(
            status="ok",
            url=url,
            title=extracted["title"] or url,
            date=extracted["date"],
            text=extracted["text"],
            kind="article",
            content_type=ctype,
            raw=text_body[:200000],
        )


async def topic_candidates(client: PoliteClient, topic: str) -> dict:
    query = " ".join((topic or "").split())
    if not query:
        return {"topic": "", "candidates": [], "notes": ["Type a topic to look for open readings."]}
    notes: list[str] = []
    candidates: list[dict] = []
    wiki = (
        "https://en.wikipedia.org/w/api.php?action=opensearch&limit=5&namespace=0&format=json&search="
        + quote_plus(query)
    )
    wiki_reading = await client.fetch(wiki)
    if wiki_reading.status == "ok" and wiki_reading.kind == "json":
        try:
            import json
            payload = json.loads(wiki_reading.text)
            titles = payload[1] if len(payload) > 1 else []
            blurbs = payload[2] if len(payload) > 2 else []
            urls = payload[3] if len(payload) > 3 else []
            for index, title in enumerate(titles):
                candidates.append({
                    "title": title,
                    "url": urls[index] if index < len(urls) else "",
                    "date": "",
                    "origin": "wikipedia",
                    "summary": blurbs[index] if index < len(blurbs) else "",
                })
        except (ValueError, IndexError, TypeError):
            notes.append("Wikipedia did not return a reading list.")
    else:
        notes.append(wiki_reading.message or "Wikipedia was not read.")

    arxiv = "https://export.arxiv.org/api/query?search_query=all:" + quote_plus(query) + "&start=0&max_results=5"
    paper = await client.fetch(arxiv)
    if paper.status == "ok" and paper.kind == "feed":
        for item in paper.items:
            item = dict(item)
            item["origin"] = "arxiv"
            candidates.append(item)
    elif paper.status != "ok":
        notes.append(paper.message or "arXiv was not read.")
    return {"topic": query, "candidates": [c for c in candidates if c.get("url")], "notes": notes}
