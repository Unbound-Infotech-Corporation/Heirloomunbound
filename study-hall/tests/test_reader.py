"""Ingestion: clean text, citations, robots, rate limit, paywalls, feeds, PDFs."""
from __future__ import annotations

import asyncio
import json

import httpx

from studyhall.embed import cosine, is_duplicate_vector, text_hash
from studyhall.reader import PoliteClient, extract_html, extract_pdf, looks_like_paywall, parse_feed


ARTICLE = """<!doctype html>
<html><head>
<meta property="og:title" content="Grief and the grounded twin">
<meta property="article:published_time" content="2026-04-12T08:00:00Z">
<title>Ignored title</title>
</head>
<body>
<nav>Skip me</nav>
<article>
<h1>Grief and the grounded twin</h1>
<p>A twin should cite what it knows.</p>
<script>secretToken()</script>
<p>Voice work needs consent.</p>
</article>
<footer>Subscribe to continue reading our newsletter</footer>
</body></html>
"""


def test_html_keeps_title_date_and_drops_script():
    extracted = extract_html(ARTICLE, "https://example.test/grief")
    assert extracted["title"] == "Grief and the grounded twin"
    assert extracted["date"].startswith("2026-04-12")
    assert "cite what it knows" in extracted["text"]
    assert "Voice work needs consent" in extracted["text"]
    assert "secretToken" not in extracted["text"]
    assert "Skip me" not in extracted["text"]


def test_paywall_marker_on_a_short_page():
    short = "<html><title>Locked</title><article><p>Subscribe to continue reading.</p></article></html>"
    extracted = extract_html(short)
    assert looks_like_paywall(extracted["text"]) is True
    long_page = "<html><article><p>Subscribe to continue is mentioned, then the essay goes on. " + ("memory " * 200) + "</p></article></html>"
    extracted_long = extract_html(long_page)
    assert "subscribe to continue" in extracted_long["text"].lower()
    assert looks_like_paywall(extracted_long["text"]) is False


def test_rss_items_keep_link_and_date():
    raw = """<?xml version="1.0"?>
    <rss version="2.0"><channel><title>Lab</title>
    <item>
      <title>Long-term memory</title>
      <link>https://example.test/memory</link>
      <pubDate>Wed, 18 Mar 2026 00:00:00 GMT</pubDate>
    </item>
    </channel></rss>"""
    items = parse_feed(raw, "https://example.test/feed")
    assert items[0]["title"] == "Long-term memory"
    assert items[0]["url"] == "https://example.test/memory"
    assert "2026" in items[0]["date"]


def _pdf(text: str) -> bytes:
    safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content = f"BT /F1 12 Tf 72 720 Td ({safe}) Tj ET\n".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    startxref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{startxref}\n%%EOF\n"
    ).encode()
    return bytes(out)


def test_pdf_text_is_extracted():
    extracted = extract_pdf(_pdf("Voice cloning needs a cited consent."))
    assert "cited consent" in extracted["text"]


def _client(handler, *, interval=0.0, clock=None, sleep=None):
    return PoliteClient(
        min_interval=interval,
        clock=clock,
        sleep=sleep,
        transport=httpx.MockTransport(handler),
    )


def test_robots_disallow_never_fetches_the_page():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
        return httpx.Response(200, text="<html><article><p>should not be stored</p></article></html>")

    async def _run():
        client = _client(handler)
        try:
            reading = await client.fetch("http://press.test/private")
            return reading
        finally:
            await client.aclose()

    reading = asyncio.run(_run())
    assert reading.status == "robots"
    assert seen == ["/robots.txt"]
    assert reading.text == ""


def test_article_fetch_keeps_citation_and_blocks_paywall():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404, text="missing")
        if request.url.path == "/open":
            return httpx.Response(200, text=ARTICLE, headers={"content-type": "text/html"})
        if request.url.path == "/locked":
            locked = "<html><title>Members</title><article><p>Subscribe to continue reading this essay.</p></article></html>"
            return httpx.Response(200, text=locked, headers={"content-type": "text/html"})
        return httpx.Response(404, text="no")

    async def _run():
        client = _client(handler)
        try:
            open_reading = await client.fetch("http://press.test/open")
            locked = await client.fetch("http://press.test/locked")
            return open_reading, locked
        finally:
            await client.aclose()

    open_reading, locked = asyncio.run(_run())
    assert open_reading.status == "ok"
    assert open_reading.title == "Grief and the grounded twin"
    assert open_reading.date.startswith("2026-04-12")
    assert open_reading.url == "http://press.test/open"
    assert "secretToken" not in open_reading.text
    assert locked.status == "paywall"
    assert locked.text == ""
    assert locked.title == "Members"
    assert locked.citation()["url"] == "http://press.test/locked"


def test_rate_limit_waits_between_requests_to_one_host():
    clock = {"t": 0.0}
    slept = []

    def now():
        return clock["t"]

    async def sleep(seconds):
        slept.append(seconds)
        clock["t"] += seconds

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(200, text=ARTICLE, headers={"content-type": "text/html"})

    async def _run():
        client = _client(handler, interval=1.5, clock=now, sleep=sleep)
        try:
            first = await client.fetch("http://press.test/a")
            second = await client.fetch("http://press.test/b")
            return first, second
        finally:
            await client.aclose()

    first, second = asyncio.run(_run())
    assert first.status == "ok" and second.status == "ok"
    assert slept
    assert min(slept) >= 1.5


def test_feed_and_topic_and_metadata_host():
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if host == "en.wikipedia.org":
            payload = ["voice cloning", ["Voice cloning"], ["A short open summary."], ["https://en.wikipedia.org/wiki/Voice_cloning"]]
            return httpx.Response(200, text=json.dumps(payload), headers={"content-type": "application/json"})
        if host == "export.arxiv.org":
            raw = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
            <entry><title>Memory for assistants</title><id>https://arxiv.org/abs/2601.00001</id>
            <published>2026-01-02T00:00:00Z</published></entry></feed>"""
            return httpx.Response(200, text=raw, headers={"content-type": "application/atom+xml"})
        return httpx.Response(404, text="no")

    async def _run():
        client = _client(handler)
        try:
            from studyhall.reader import topic_candidates

            found = await topic_candidates(client, "voice cloning")
            blocked = await client.fetch("http://169.254.169.254/latest/meta-data")
            return found, blocked
        finally:
            await client.aclose()

    found, blocked = asyncio.run(_run())
    origins = {item["origin"] for item in found["candidates"]}
    assert "wikipedia" in origins
    assert "arxiv" in origins
    assert found["candidates"][0]["url"].startswith("https://")
    assert blocked.status == "error"
    assert blocked.text == ""


def test_text_hash_and_embedding_duplicate():
    assert text_hash("Voice  cloning") == text_hash("voice cloning")
    assert is_duplicate_vector([1.0, 0.0], [[0.0, 1.0]]) is False
    assert is_duplicate_vector([2.0, 0.0], [[1.0, 0.0]]) is True
    assert cosine([1.0, 0.0], [0.6, 0.8]) < 0.92
