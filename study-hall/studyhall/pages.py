"""What kind of page a lead is. Marketing and nav are not readings."""
from __future__ import annotations

import re
from urllib.parse import unquote, urlparse

QUEUED_PER_HOST = 5

SKIP_KINDS = frozenset({
    "product", "pricing", "demo", "tour", "ebook", "whitepaper", "webinar",
    "careers", "press", "signup", "store", "customer", "partner", "legal",
})
KEEP_KINDS = frozenset({"article", "docs", "paper", "thread", "research"})

_STORE_HOSTS = (
    "chromewebstore.google.com",
    "chrome.google.com",
    "addons.mozilla.org",
    "apps.apple.com",
    "play.google.com",
    "marketplace.visualstudio.com",
    "microsoftedge.microsoft.com",
)
_KEEP_SEGMENTS = {
    "blog": "article",
    "blogs": "article",
    "post": "article",
    "posts": "article",
    "article": "article",
    "articles": "article",
    "research": "research",
    "paper": "paper",
    "papers": "paper",
    "docs": "docs",
    "doc": "docs",
    "documentation": "docs",
    "reference": "docs",
}
_SKIP_SEGMENTS = {
    "pricing": "pricing",
    "price": "pricing",
    "prices": "pricing",
    "plans": "pricing",
    "product": "product",
    "products": "product",
    "features": "product",
    "feature": "product",
    "solutions": "product",
    "solution": "product",
    "platform": "product",
    "enterprise": "product",
    "business": "product",
    "demo": "demo",
    "demos": "demo",
    "tour": "tour",
    "ebook": "ebook",
    "ebooks": "ebook",
    "whitepaper": "whitepaper",
    "whitepapers": "whitepaper",
    "webinar": "webinar",
    "webinars": "webinar",
    "career": "careers",
    "careers": "careers",
    "job": "careers",
    "jobs": "careers",
    "press": "press",
    "newsroom": "press",
    "news": "press",
    "funding": "press",
    "gartner": "press",
    "signup": "signup",
    "register": "signup",
    "download": "signup",
    "downloads": "signup",
    "try": "signup",
        "customers": "customer",
    "customer": "customer",
    "tools": "product",
    "tool": "product",
    "partners": "partner",
    "partner": "partner",
    "legal": "legal",
    "privacy": "legal",
    "terms": "legal",
    "cookies": "legal",
    "imprint": "legal",
}
_COMPOUNDS = {
    "product-tour": "tour",
    "case-study": "customer",
    "case-studies": "customer",
    "customer-stories": "customer",
    "customer-story": "customer",
    "white-paper": "whitepaper",
    "white-papers": "whitepaper",
    "sign-up": "signup",
    "get-started": "signup",
    "book-a-demo": "demo",
    "request-a-demo": "demo",
    "try-chatgpt": "signup",
    "safety-hub": "product",
    "deployment-safety": "product",
    "news-blog": "press",
    "press-release": "press",
    "press-releases": "press",
}
_ANCHORS = (
    ("try chatgpt", "signup"),
    ("try it free", "signup"),
    ("sign up", "signup"),
    ("get started", "signup"),
    ("book a demo", "demo"),
    ("request a demo", "demo"),
    ("product tour", "tour"),
    ("download the ebook", "ebook"),
    ("download ebook", "ebook"),
    ("white paper", "whitepaper"),
    ("whitepaper", "whitepaper"),
    ("watch the webinar", "webinar"),
    ("chatgpt business", "product"),
    ("deployment safety hub", "product"),
    ("safety hub", "product"),
)


def _host(url: str) -> str:
    return (urlparse(url or "").hostname or "").lower().removeprefix("www.")


def _segments(path: str) -> list[str]:
    return [part for part in unquote(path or "").lower().split("/") if part]


def _pitch(title: str) -> str:
    """Funding, partnership, and launch headlines are announcements, not research."""
    label = " ".join((title or "").lower().split())
    if not label:
        return ""
    if re.search(r"\bsecures\s+\$", label) or (re.search(r"\$\s?\d", label) and "funding" in label):
        return "press"
    if re.search(r"\braise[sd]?\b", label):
        return "press"
    if re.search(r"\bpartners?\s+with\b", label) or re.search(r"\bpartnership\b", label):
        return "press"
    if re.search(r"\bannounces?\b", label) or re.search(r"\bannouncement\b", label):
        return "press"
    if re.search(r"\blaunch(es|ed)?\b", label):
        return "press"
    return ""


def _anchor_kind(title: str) -> str:
    label = " ".join((title or "").lower().split())
    if not label:
        return ""
    if "gartner" in label:
        return "press"
    for phrase, kind in _ANCHORS:
        if phrase in label:
            return kind
    return ""


def _path_kind(path: str) -> str:
    parts = _segments(path)
    skip = ""
    keep = ""
    joined = "/".join(parts)
    if "safety-hub" in joined or "deployment-safety" in joined:
        return "product"
    for part in parts:
        compound = _COMPOUNDS.get(part) or _COMPOUNDS.get(part.replace("_", "-"))
        if compound:
            skip = skip or compound
            continue
        token = part.replace("_", "-")
        if token.endswith("-generator") or token.endswith("-converter"):
            skip = skip or "product"
            continue
        if token in _SKIP_SEGMENTS:
            skip = skip or _SKIP_SEGMENTS[token]
            continue
        head = token.split("-", 1)[0]
        if head in _SKIP_SEGMENTS and head in {"ebook", "ebooks", "webinar", "webinars", "pricing", "careers", "jobs", "news", "press", "tools"}:
            skip = skip or _SKIP_SEGMENTS[head]
            continue
        if token in _KEEP_SEGMENTS:
            keep = keep or _KEEP_SEGMENTS[token]
    if keep and not skip:
        return keep
    if skip:
        return skip
    return keep


def _scholarly(host: str, path: str) -> str:
    if host.endswith("arxiv.org") and path.startswith(("/abs/", "/pdf/", "/html/", "/api/")):
        return "paper"
    if host.endswith("doi.org") and path.startswith("/10."):
        return "paper"
    if host in {"api.openalex.org", "api.semanticscholar.org", "api.crossref.org", "export.arxiv.org", "hn.algolia.com"}:
        return "paper"
    if "news.ycombinator.com" in host:
        return "thread"
    if host.endswith("reddit.com") and "/comments/" in path:
        return "thread"
    return ""


def _store(host: str, path: str) -> bool:
    if host in _STORE_HOSTS or host.endswith(".chromewebstore.google.com"):
        return True
    if host == "chrome.google.com" and "/webstore" in path:
        return True
    return False


def _form_gate(raw: str, text: str) -> bool:
    if len(text or "") >= 700:
        return False
    blob = (raw or "").lower()
    return "<form" in blob and any(word in blob for word in ("ebook", "whitepaper", "white paper", "webinar", "download the"))


def _link_hub(raw: str, text: str) -> bool:
    if len(text or "") >= 400:
        return False
    return (raw or "").lower().count("<a ") >= 25


def classify_page(url: str, title: str = "", *, text: str = "", raw: str = "") -> str:
    """Label a lead or a fetched page.

    URL path and anchor text decide product, pricing, and the other marketing
    types. A blog, doc, paper, or thread keeps that label. A long article body
    can still count as an article when the path itself is not marketing.
    """
    parsed = urlparse(url or "")
    host = _host(url)
    path = unquote(parsed.path or "").lower()
    if _store(host, path):
        return "store"
    scholarly = _scholarly(host, path)
    if scholarly:
        return scholarly
    path_kind = _path_kind(path)
    if path_kind in SKIP_KINDS:
        return path_kind
    pitch = _pitch(title)
    if pitch:
        return pitch
    anchor = _anchor_kind(title)
    if anchor in SKIP_KINDS and path_kind not in KEEP_KINDS:
        return anchor
    if path_kind in KEEP_KINDS:
        if path_kind == "article" and _form_gate(raw, text):
            return "ebook"
        return path_kind
    if _form_gate(raw, text):
        return "ebook"
    if text and len(text) >= 800:
        return "article"
    if _link_hub(raw, text):
        return "product"
    return "unknown"


def is_marketing(url: str, title: str = "", *, text: str = "", raw: str = "") -> bool:
    return classify_page(url, title, text=text, raw=raw) in SKIP_KINDS
