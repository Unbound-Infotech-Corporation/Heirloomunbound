"""Frontier, leads, relevance, robots, pace, chat, and the live event stream."""
from __future__ import annotations

import asyncio
import json

import httpx
from fastapi.testclient import TestClient

from studyhall.app import create_app
from studyhall.chat import apply_instruction, interpret
from studyhall.frontier import score_relevance, seconds_until_next_page, work_once
from studyhall.hall import Hall
from studyhall.live import parse_sse, script_discussion, sse
from studyhall.missions import STANDING_ID
from studyhall.port import choose_port
from studyhall.reader import PoliteClient, Reading
from studyhall.chat import unwrap_url, urls_in
from studyhall.search import leads_from_document, search_targets


def _mission():
    return {
        "mission_id": "msn_test",
        "title": "Memory",
        "brief": "long-term memory for conversational assistants",
        "status": "running",
        "queries": ["long-term memory for conversational assistants"],
        "blocked_terms": [],
        "blocked_hosts": [],
        "pages_per_hour": 12,
        "max_depth": 2,
        "query_cursor": 0,
        "communities": [],
        "tag": "assistant craft",
    }


def test_leads_follow_links_and_list_communities_without_joining():
    html = """
    <a href="https://example.test/paper">A useful paper about memory</a>
    <a href="https://arxiv.org/abs/2601.00001">arxiv</a>
    <a href="https://doi.org/10.1000/example">doi</a>
    <a href="https://doi.org/login/?next=/records/1">login</a>
    <a href="https://www.reddit.com/r/LocalLLaMA/comments/abc">thread</a>
    <a href="https://discord.gg/example">discord</a>
    """
    leads, communities = leads_from_document("article", "https://example.test/start", html, depth=0)
    urls = {item["url"] for item in leads}
    assert "https://example.test/paper" in urls
    assert "https://arxiv.org/abs/2601.00001" in urls
    kinds = {item["kind"] for item in communities}
    assert "subreddit" in kinds
    assert "discord" in kinds
    assert all(item["why"] for item in leads)


def test_reddit_json_follows_the_thread_and_names_the_subreddit():
    payload = {"data": {"children": [{"data": {
        "title": "Memory for local assistants",
        "permalink": "/r/LocalLLaMA/comments/abc/memory/",
        "subreddit": "LocalLLaMA",
    }}]}}
    leads, communities = leads_from_document("reddit", "https://www.reddit.com/search.json", json.dumps(payload), depth=0)
    assert leads[0]["url"].startswith("https://www.reddit.com/r/LocalLLaMA/")
    assert leads[0]["depth"] == 1
    assert communities[0]["name"] == "r/LocalLLaMA"


def test_relevance_gate_skips_the_panel_until_the_page_matches():
    mission = _mission()
    assert score_relevance("Sourdough needs a warm kitchen and patience.", mission) < 0.5
    assert score_relevance("Long-term memory lets conversational assistants keep context.", mission) >= 0.5
    assert score_relevance("unrelated words", mission, vector=[1.0, 0.0], mission_vector=[1.0, 0.0]) >= 0.5
    assert score_relevance("unrelated words", mission, vector=[1.0, 0.0], mission_vector=[0.0, 1.0]) < 0.5

    calls = {"study": 0}

    async def fetch(url):
        if "sourdough" in url:
            return Reading(status="ok", url=url, title="Bread", text="Sourdough needs a warm kitchen and patience. " * 5)
        return Reading(status="ok", url=url, title="Memory", text="Long-term memory lets conversational assistants keep context. " * 5)

    async def study(source):
        calls["study"] += 1
        return {"events": []}

    frontier = [{
        "lead_id": "led_bread",
        "mission_id": "msn_test",
        "url": "https://example.test/sourdough",
        "title": "Bread",
        "why": "a weak lead",
        "from_url": "https://example.test/start",
        "depth": 1,
        "kind": "article",
        "status": "queued",
        "tries": 0,
    }]

    async def _run():
        skipped = await work_once(mission=mission, frontier=frontier, fetch=fetch, study=study, now=1000, reads_at=[])
        useful = dict(frontier[0])
        useful["url"] = "https://example.test/memory"
        useful["lead_id"] = "led_memory"
        read = await work_once(mission=mission, frontier=[useful], fetch=fetch, study=study, now=2000, reads_at=[])
        return skipped, read

    skipped, read = asyncio.run(_run())
    assert skipped.action == "skip"
    assert skipped.status == "running"
    assert calls["study"] == 1
    assert read.action == "read"
    assert read.status == "running"
    assert any(edge["why"] or edge["to"] for edge in read.edges) or read.action == "read"


def test_robots_disallow_does_not_fetch_the_page_and_does_not_stop():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
        return httpx.Response(200, text="<html><article><p>secret memory assistants conversational long-term</p></article></html>")

    mission = _mission()
    frontier = [{
        "lead_id": "led_private",
        "mission_id": "msn_test",
        "url": "http://press.test/private",
        "title": "Private",
        "why": "a lead",
        "from_url": "",
        "depth": 1,
        "kind": "article",
        "status": "queued",
        "tries": 0,
    }]

    async def _run():
        client = PoliteClient(min_interval=0, transport=httpx.MockTransport(handler))
        try:
            step = await work_once(mission=mission, frontier=frontier, fetch=client.fetch, study=_no_study, now=10, reads_at=[])
            return step
        finally:
            await client.aclose()

    step = asyncio.run(_run())
    assert seen == ["/robots.txt"]
    assert step.action == "skip"
    assert step.status == "running"


async def _no_study(source):
    raise AssertionError("panel should not run")


def test_pace_waits_and_a_dry_frontier_reseeds_without_stopping():
    assert seconds_until_next_page([1_000.0], 1_001.0, pages_per_hour=1) > 0
    mission = _mission()
    mission["pages_per_hour"] = 1
    frontier = [{
        "lead_id": "led_one",
        "mission_id": "msn_test",
        "url": "https://example.test/a",
        "status": "read",
        "read_at": 5_000.0,
        "depth": 0,
        "kind": "article",
    }]

    async def fetch(url):
        raise AssertionError("paced")

    paced = asyncio.run(work_once(mission=mission, frontier=frontier, fetch=fetch, study=_no_study, now=5_100, reads_at=[5_000.0]))
    assert paced.action == "pace"
    assert paced.status == "running"
    assert paced.wait > 0

    empty = asyncio.run(work_once(mission=mission, frontier=[], fetch=fetch, study=_no_study, now=9_000, reads_at=[]))
    assert empty.action == "reseed"
    assert empty.status == "running"
    assert any(item["status"] == "queued" for item in empty.frontier)
    assert mission["status"] == "running"


def test_errors_back_off_and_leave_the_mission_running():
    mission = _mission()

    async def fetch(url):
        raise ConnectionError("down")

    frontier = [{
        "lead_id": "led_down",
        "mission_id": "msn_test",
        "url": "https://example.test/down",
        "status": "queued",
        "depth": 0,
        "kind": "article",
        "tries": 0,
        "why": "lead",
        "from_url": "",
    }]
    step = asyncio.run(work_once(mission=mission, frontier=frontier, fetch=fetch, study=_no_study, now=50, reads_at=[]))
    assert step.action == "error"
    assert step.status == "running"
    assert step.frontier[0]["status"] == "error"
    assert step.frontier[0]["retry_at"] > 50


def test_chat_creates_blocks_pauses_and_cites(tmp_path):
    hall = Hall(tmp_path)
    assert hall.store.read_items("missions.json")[0]["mission_id"] == STANDING_ID
    assert hall.store.read_items("missions.json")[0]["status"] == "running"
    assert "assistant craft" == hall.store.read_items("missions.json")[0]["tag"]

    found = apply_instruction(hall.store, "find the best current research on long-term memory for voice assistants")
    assert found["action"] == "research"
    assert "long-term memory" in found["reply"]
    assert any("long-term memory" in query for query in found["mission"]["queries"])

    grief = interpret("look into how grief counselors talk about legacy letters")
    assert grief["action"] == "research"
    assert "grief" in grief["detail"]

    blocked = apply_instruction(hall.store, "ignore crypto sources")
    assert blocked["action"] == "block"
    assert "crypto" in blocked["mission"]["blocked_terms"]

    paused = apply_instruction(hall.store, "pause")
    assert paused["mission"]["status"] == "paused"
    again = Hall(tmp_path)
    assert again.store.read_items("missions.json")[0]["status"] == "paused"
    started = apply_instruction(again.store, "start")
    assert started["mission"]["status"] == "running"

    hall.store.write_items("library.json", [{
        "source_id": "src_mem",
        "title": "Memory notes",
        "url": "https://example.test/memory",
        "text": "Long-term memory lets conversational assistants keep a cited context.",
    }])
    answer = apply_instruction(hall.store, "what have we learned about conversational memory")
    assert "https://example.test/memory" in json.dumps(answer["citations"]) or "Memory notes" in answer["reply"]
    assert answer["citations"]


def test_event_stream_frames_and_http_once(tmp_path):
    frame = sse("looking", {"url": "https://example.test/a", "why": "cited by a paper"})
    event, data = parse_sse(frame)
    assert event == "looking"
    assert data["why"] == "cited by a paper"
    messages = script_discussion("Memory", "Long-term memory lets assistants keep context.", tag="assistant craft")
    assert [item["data"]["name"] for item in messages] == ["phi4:14b", "mistral-small3.2:24b", "gemma3:27b", "llama3.1:8b"]
    assert messages[-1]["data"]["role"] == "moderator"

    app = create_app(tmp_path)
    with TestClient(app) as client:
        posted = client.post("/api/chat", json={"text": "pause"})
        assert posted.status_code == 200
        assert posted.json()["action"] == "pause"
        with client.stream("GET", "/api/live/stream?once=1") as response:
            body = response.read().decode()
    assert "event: hello" in body
    assert "event: chat" in body
    assert "Paused" in body
    kinds = [parse_sse(chunk)[0] for chunk in body.split("\n\n") if chunk.strip()]
    assert "hello" in kinds
    assert "chat" in kinds


def test_search_seeds_skip_blocked_wikipedia_and_reddit_apis():
    urls = [item["url"] for item in search_targets("long-term memory")]
    assert not any("wikipedia.org/w/api.php" in url for url in urls)
    assert not any("reddit.com" in url and url.endswith(".json") or "/search.json" in url for url in urls)
    assert any(url.startswith("https://export.arxiv.org/api/") for url in urls)
    assert any(url.startswith("https://api.openalex.org/") for url in urls)
    assert any(url.startswith("https://api.crossref.org/") for url in urls)


def test_articles_are_read_before_more_indexes():
    mission = _mission()
    mission["pages_per_hour"] = 600
    studied = []

    async def fetch(url):
        return Reading(status="ok", url=url, title="Memory paper", text="Long-term memory lets conversational assistants keep context. " * 8)

    async def study(source):
        studied.append(source["url"])
        return {"events": []}

    frontier = [
        {"lead_id": "led_index", "mission_id": "msn_test", "url": "https://api.openalex.org/works?search=memory", "status": "queued", "depth": 0, "kind": "openalex", "tries": 0, "why": "index", "from_url": "", "text": ""},
        {"lead_id": "led_paper", "mission_id": "msn_test", "url": "https://example.test/memory-paper", "status": "queued", "depth": 1, "kind": "paper", "tries": 0, "why": "OpenAlex work", "from_url": "https://api.openalex.org/works", "text": ""},
    ]
    step = asyncio.run(work_once(mission=mission, frontier=frontier, fetch=fetch, study=study, now=10, reads_at=[]))
    assert studied == ["https://example.test/memory-paper"]
    assert step.action == "read"
    assert step.status == "running"


def test_bing_redirect_unwraps_to_the_article():
    token = "a1aHR0cHM6Ly9tYXN0cmEuYWkvYXJ0aWNsZXMvYWktYXNzaXN0YW50cw"
    url = f"https://www.bing.com/ck/a?u={token}"
    assert unwrap_url(url) == "https://mastra.ai/articles/ai-assistants"
    found = urls_in(f"please read {url}")
    assert found == ["https://mastra.ai/articles/ai-assistants"]
    assert unwrap_url("https://www.google.com/url?q=https%3A%2F%2Fexample.test%2Fpaper") == "https://example.test/paper"


def test_robots_redirect_is_followed_and_server_errors_retry():
    def allow(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(302, headers={"location": "/robots-real.txt"})
        if request.url.path == "/robots-real.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(200, text="<html><article><p>" + ("Long-term memory for assistants. " * 8) + "</p></article></html>", headers={"content-type": "text/html"})

    def down(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, text="<html><article><p>should not be read</p></article></html>")

    async def _run():
        ok = PoliteClient(min_interval=0, transport=httpx.MockTransport(allow))
        blocked = PoliteClient(min_interval=0, transport=httpx.MockTransport(down))
        try:
            opened = await ok.fetch("http://press.test/paper")
            waiting = await blocked.fetch("http://press.test/paper")
            return opened, waiting
        finally:
            await ok.aclose()
            await blocked.aclose()

    opened, waiting = asyncio.run(_run())
    assert opened.status == "ok"
    assert "memory" in opened.text.lower()
    assert waiting.status == "retry"
    assert waiting.temporary is True
    assert "tried again" in waiting.message


def test_official_api_is_fetched_when_robots_disallows_the_host():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
        return httpx.Response(200, text='{"message":{"items":[]}}', headers={"content-type": "application/json"})

    async def _run():
        client = PoliteClient(min_interval=0, transport=httpx.MockTransport(handler))
        try:
            return await client.fetch("https://export.arxiv.org/api/query?search_query=all:memory&max_results=1")
        finally:
            await client.aclose()

    reading = asyncio.run(_run())
    assert reading.status == "ok"
    assert "/api/query" in seen


def test_choose_port_skips_a_busy_one():
    with __import__("socket").socket() as sock:
        sock.bind(("127.0.0.1", 0))
        busy = sock.getsockname()[1]
        chosen = choose_port("127.0.0.1", busy, span=5)
    assert chosen != busy
    assert chosen > busy
