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
        useful["title"] = "Long-term memory for conversational assistants"
        useful["why"] = "OpenAlex work on long-term memory"
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
        "title": "Long-term memory for conversational assistants",
        "why": "a paper on long-term memory",
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
        "title": "Long-term memory for conversational assistants",
        "status": "queued",
        "depth": 0,
        "kind": "article",
        "tries": 0,
        "why": "paper on long-term memory",
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
        {"lead_id": "led_paper", "mission_id": "msn_test", "url": "https://example.test/memory-paper", "title": "Long-term memory for conversational assistants", "status": "queued", "depth": 1, "kind": "paper", "tries": 0, "why": "OpenAlex work on long-term memory", "from_url": "https://api.openalex.org/works", "text": "long-term memory"},
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


def test_real_panel_lines_are_not_the_stock_script(tmp_path):
    from studyhall.discover import Seat
    from studyhall.live import short_turn
    from studyhall.panel import run_study

    seen = []

    async def complete(seat, messages):
        system = messages[0]["content"]
        if "ROUND: pin" in system:
            return json.dumps({"summary": "Cite this paper for the twin.", "why_it_matters": "It is a method, not a memory.", "confidence": 0.7, "citations": [], "proposals": []})
        if "ROUND: critique" in system:
            return json.dumps({"keep": f"{seat.model} would keep the citation.", "reject": "Skip hype.", "agree": "Yes."})
        return json.dumps({"useful": f"{seat.model} finds the memory method useful.", "not_useful": "", "cautions": ""})

    def on_note(note):
        seen.append(short_turn(note.round, note.parsed, note.text, placeholder=note.placeholder, model=note.model))

    reader = Seat("phi4:14b", "http://127.0.0.1:11435", "study", "ollama", "reader")
    moderator = Seat("llama3.1:8b", "http://127.0.0.1:11435", "study", "ollama", "moderator")
    source = {"title": "Memory", "url": "https://example.test/m", "date": "", "text": "Long-term memory lets conversational assistants keep context. " * 10}
    asyncio.run(run_study(source, [reader], moderator, complete, on_note=on_note))
    blob = " ".join(seen)
    assert "phi4:14b finds the memory method useful" in blob
    assert "would keep the citation" in blob
    assert "Cite this paper for the twin" in blob
    assert "Dubious if we treat" not in blob
    assert "Placeholder" in short_turn("read", {}, "phi4 did not answer.", placeholder=True, model="phi4:14b")


def test_marketing_links_are_skipped_before_fetch():
    mission = _mission()
    called = []

    async def fetch(url):
        called.append(url)
        return Reading(status="ok", url=url, title="Ad", text="Long-term memory for conversational assistants. " * 5)

    frontier = [{
        "lead_id": "led_ad",
        "mission_id": "msn_test",
        "url": "https://github.com/features/copilot",
        "title": "GitHub Copilot pricing",
        "why": "a link",
        "from_url": "https://github.com/org/repo",
        "depth": 1,
        "kind": "article",
        "status": "queued",
        "tries": 0,
        "text": "product marketing",
    }]
    step = asyncio.run(work_once(mission=mission, frontier=frontier, fetch=fetch, study=_no_study, now=20, reads_at=[]))
    assert called == []
    assert step.frontier[0]["status"] == "off_topic"
    assert "Skipped" in step.events[0]["data"]["message"]


def test_provider_key_stays_masked_and_the_cap_holds(tmp_path):
    from studyhall.providers import load_providers, public_view, record_use, update_provider, within_cap

    update_provider(tmp_path, "openai", {"key": "sk-test-secret-1234", "enabled": True, "cap_hour": 1, "cap_day": 2})
    view = public_view(tmp_path)["openai"]
    blob = json.dumps(view)
    assert "sk-test-secret" not in blob
    assert view["key_mask"].endswith("1234")
    assert view["key_set"] is True
    record_use(tmp_path, "openai")
    assert within_cap(load_providers(tmp_path)["openai"]) is False


def test_hand_tool_safety_is_rejected_and_ai_safety_is_kept():
    mission = _mission()
    mission["title"] = "Become a better AI assistant"
    mission["brief"] = "Study how a local family twin can be a better assistant: memory, voice, empathy, tool safety, grounding."
    mission["queries"] = ["tool use confirmation and action safety", "AI assistant memory and prompts"]
    hand = "Hand tool inspection safety https://safetymanualosha.com/hand-tool-inspection-safety Link on the page"
    article = "AI safety for language model assistants and prompts https://example.test/ai-safety-assistants"
    assert score_relevance(hand, mission) < 0.5
    assert score_relevance(article, mission) >= 0.5
    assert score_relevance("safety checklist inspection talk training guide tips", mission) < 0.5
    assert score_relevance(hand, mission, vector=[1.0, 0.0], mission_vector=[0.2, 0.2]) < 0.5
    assert score_relevance("workplace notes", mission, vector=[1.0, 0.0], mission_vector=[1.0, 0.0]) >= 0.5

    called = []

    async def fetch(url):
        called.append(url)
        if "assistant-notes" in url:
            return Reading(
                status="ok",
                url=url,
                title="Hand tool inspection safety",
                text="Hand tool inspection safety checklist for the workplace. " * 8,
                raw='<a href="https://simplysub.com/safety-checklist">checklist</a>',
                kind="article",
            )
        return Reading(
            status="ok",
            url=url,
            title="AI safety for assistants",
            text="AI safety for language model assistants: memory, prompts, and grounding. " * 8,
            kind="article",
        )

    studied = []

    async def study(source):
        studied.append(source["url"])
        return {"events": []}

    hand_lead = {
        "lead_id": "led_hand",
        "mission_id": "msn_test",
        "url": "https://safetymanualosha.com/hand-tool-inspection-safety",
        "title": "Hand tool inspection safety",
        "why": "Link on the page",
        "from_url": "https://example.test/start",
        "depth": 1,
        "kind": "article",
        "status": "queued",
        "tries": 0,
    }
    sibling = {
        "lead_id": "led_sib",
        "mission_id": "msn_test",
        "url": "https://simplysub.com/safety-checklist",
        "title": "Safety checklist",
        "why": "Link on the page",
        "from_url": "https://safetymanualosha.com/hand-tool-inspection-safety",
        "depth": 1,
        "kind": "article",
        "status": "queued",
        "tries": 0,
    }
    rejected = asyncio.run(work_once(
        mission=mission, frontier=[hand_lead, sibling], fetch=fetch, study=study, now=30, reads_at=[],
    ))
    assert called == []
    assert studied == []
    assert rejected.action == "skip"
    assert rejected.frontier[0]["status"] == "off_topic"

    # A link that looks like the mission can still be a workplace page once the body is read.
    bait = dict(hand_lead)
    bait["lead_id"] = "led_bait"
    bait["title"] = "Notes for AI assistants"
    bait["why"] = "assistant memory"
    bait["url"] = "https://notes.example.test/assistant-notes"
    body = asyncio.run(work_once(mission=mission, frontier=[bait], fetch=fetch, study=study, now=40, reads_at=[]))
    assert called == ["https://notes.example.test/assistant-notes"]
    assert studied == []
    assert body.action == "skip"
    assert "notes.example.test" in mission["drift_hosts"]
    assert all("simplysub.com" not in item.get("url", "") for item in body.frontier)
    assert "\u201c" not in body.events[-1]["data"]["message"]
    assert "\u201d" not in body.events[-1]["data"]["message"]

    good = {
        "lead_id": "led_ai",
        "mission_id": "msn_test",
        "url": "https://example.test/ai-safety-assistants",
        "title": "AI safety for language model assistants",
        "why": "assistant prompts and memory",
        "from_url": "",
        "depth": 1,
        "kind": "article",
        "status": "queued",
        "tries": 0,
    }
    kept = asyncio.run(work_once(mission=mission, frontier=[good], fetch=fetch, study=study, now=50, reads_at=[]))
    assert studied == ["https://example.test/ai-safety-assistants"]
    assert kept.action == "read"
    message = kept.events[-1]["data"]["message"]
    assert "Followed 'assistant prompts and memory'" in message
    assert "\u201c" not in message and "\u201d" not in message


def test_startup_prune_drops_workplace_safety_hosts():
    from studyhall.frontier import prune_frontier

    mission = _mission()
    items = [
        {"url": "https://www.safetymanualosha.com/hand-tool-inspection-safety", "status": "queued", "kind": "article", "title": "Hand tool inspection safety", "why": "Link on the page"},
        {"url": "https://simplysub.com/checklist", "status": "queued", "kind": "article", "title": "Safety checklist", "why": "Link on the page"},
        {"url": "https://safetytalklibrary.com/talks/hand-tools", "status": "error", "kind": "article", "title": "Hand tool talk", "why": "Link on the page"},
        {"url": "https://example.test/ai-safety-assistants", "status": "queued", "kind": "article", "title": "AI safety for assistants", "why": "memory and prompts"},
        {"url": "https://api.openalex.org/works?search=assistants", "status": "queued", "kind": "openalex", "title": "search", "why": "index"},
    ]
    kept, dropped = prune_frontier(items, mission)
    assert dropped == 3
    urls = {item["url"] for item in kept}
    assert "https://example.test/ai-safety-assistants" in urls
    assert any("openalex.org" in url for url in urls)
    assert not any("safetymanualosha" in url or "simplysub.com" in url or "safetytalklibrary" in url for url in urls)


def test_semantic_scholar_429_cools_down_and_uses_other_sources():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if request.headers.get("x-try") == "bare":
            return httpx.Response(429, text="slow")
        return httpx.Response(429, text="slow", headers={"retry-after": "45"})

    async def _fetch():
        client = PoliteClient(min_interval=0, transport=httpx.MockTransport(handler))
        try:
            first = await client.fetch("https://api.semanticscholar.org/graph/v1/paper/search?query=assistant&limit=5")
            return first
        finally:
            await client.aclose()

    reading = asyncio.run(_fetch())
    assert reading.status == "retry"
    assert reading.temporary is True
    assert reading.retry_after == 45

    mission = _mission()
    frontier = [{
        "lead_id": "led_s2",
        "mission_id": "msn_test",
        "url": "https://api.semanticscholar.org/graph/v1/paper/search?query=assistant&limit=5",
        "title": "long-term memory for conversational assistants",
        "why": "Search for assistants",
        "from_url": "",
        "depth": 0,
        "kind": "semanticscholar",
        "status": "queued",
        "tries": 0,
    }]

    async def fetch(url):
        return Reading(status="retry", url=url, temporary=True, retry_after=45, message="429")

    step = asyncio.run(work_once(mission=mission, frontier=frontier, fetch=fetch, study=_no_study, now=80, reads_at=[]))
    urls = [item["url"] for item in step.frontier if item.get("status") == "queued"]
    assert any(url.startswith("https://api.openalex.org/") for url in urls)
    assert any(url.startswith("https://export.arxiv.org/api/") for url in urls)
    assert mission["host_cooldown"]["api.semanticscholar.org"] == 125
    assert "OpenAlex and arXiv" in step.events[0]["data"]["message"]
    cooled = search_targets("assistants", skip_hosts={"api.semanticscholar.org"})
    assert not any("semanticscholar.org" in item["url"] for item in cooled)
    assert any("openalex.org" in item["url"] for item in cooled)


def test_wikipedia_everyday_senses_and_chrome_are_rejected():
    from urllib.parse import unquote

    from studyhall.frontier import prune_frontier
    from studyhall.search import wikipedia_query

    mission = _mission()
    mission["queries"] = ["grounding and hallucination reduction"]
    rejected = [
        "Grounding - Wikipedia",
        "Hallucination - Wikipedia",
        "Grounding (discipline technique)",
        "Nature therapy",
        "Sensory deprivation",
        "Main Page",
        "Contents",
        "Contact us",
    ]
    accepted = "Hallucination (artificial intelligence)"
    for title in rejected:
        assert score_relevance(title, mission) < 0.5
    assert score_relevance(accepted, mission) >= 0.5
    assert score_relevance(accepted, mission, vector=[0.0, 1.0], mission_vector=[1.0, 0.0]) >= 0.5
    assert score_relevance("Grounding - Wikipedia", mission, vector=[1.0, 0.0], mission_vector=[1.0, 0.0]) >= 0.5

    wiki_url = unquote(next(
        item["url"] for item in search_targets("grounding and hallucination reduction")
        if "site:en.wikipedia.org" in unquote(item["url"]).replace("+", " ") or "site%3Aen.wikipedia.org" in item["url"]
    )).replace("+", " ")
    assert "Hallucination (artificial intelligence)" in wiki_url
    assert wikipedia_query("grounding and hallucination reduction").startswith("grounding and hallucination reduction")

    html = """
    <p>Grounding may refer to:</p>
    <a href="https://en.wikipedia.org/wiki/Grounding">Grounding - Wikipedia</a>
    <a href="https://en.wikipedia.org/wiki/Hallucination">Hallucination - Wikipedia</a>
    <a href="https://en.wikipedia.org/wiki/Grounding_(discipline_technique)">Grounding (discipline technique)</a>
    <a href="https://en.wikipedia.org/wiki/Nature_therapy">Nature therapy</a>
    <a href="https://en.wikipedia.org/wiki/Sensory_deprivation">Sensory deprivation</a>
    <a href="https://en.wikipedia.org/wiki/Main_Page">Main Page</a>
    <a href="https://en.wikipedia.org/wiki/Wikipedia:Contents">Contents</a>
    <a href="https://en.wikipedia.org/wiki/Wikipedia:Contact_us">Contact us</a>
    <a href="https://en.wikipedia.org/wiki/Wikipedia:About">About</a>
    <a href="https://en.wikipedia.org/wiki/Special:Search">Search</a>
    <a href="https://en.wikipedia.org/wiki/Help:Contents">Help</a>
    <a href="https://en.wikipedia.org/wiki/Talk:Grounding">Talk</a>
    <a href="https://en.wikipedia.org/wiki/Category:Safety">Category</a>
    <a href="https://de.wikipedia.org/wiki/Erdung">Erdung</a>
    <a href="https://fr.wikipedia.org/wiki/Hallucination">Hallucination</a>
    <a href="https://en.wikipedia.org/wiki/Hallucination_(artificial_intelligence)">Hallucination (artificial intelligence)</a>
    """
    leads, _communities = leads_from_document("article", "https://en.wikipedia.org/wiki/Grounding_(disambiguation)", html, depth=0)
    assert [item["title"] for item in leads] == ["Hallucination (artificial intelligence)"]

    ddg = """
    <a href="/l/?uddg=https%3A%2F%2Fen.wikipedia.org%2Fwiki%2FGrounding">Grounding - Wikipedia</a>
    <a href="/l/?uddg=https%3A%2F%2Fen.wikipedia.org%2Fwiki%2FHallucination">Hallucination - Wikipedia</a>
    <a href="/l/?uddg=https%3A%2F%2Fen.wikipedia.org%2Fwiki%2FHallucination_%28artificial_intelligence%29">Hallucination (artificial intelligence)</a>
    """
    found, _communities = leads_from_document("duckduckgo", "https://html.duckduckgo.com/html/", ddg, depth=0)
    assert [item["title"] for item in found] == ["Hallucination (artificial intelligence)"]

    queued = []
    for title, url in [
        ("Grounding - Wikipedia", "https://en.wikipedia.org/wiki/Grounding"),
        ("Hallucination - Wikipedia", "https://en.wikipedia.org/wiki/Hallucination"),
        ("Grounding (discipline technique)", "https://en.wikipedia.org/wiki/Grounding_(discipline_technique)"),
        ("Nature therapy", "https://en.wikipedia.org/wiki/Nature_therapy"),
        ("Sensory deprivation", "https://en.wikipedia.org/wiki/Sensory_deprivation"),
        ("Main Page", "https://en.wikipedia.org/wiki/Main_Page"),
        ("Contents", "https://en.wikipedia.org/wiki/Wikipedia:Contents"),
        ("Contact us", "https://en.wikipedia.org/wiki/Wikipedia:Contact_us"),
        ("Erdung", "https://de.wikipedia.org/wiki/Erdung"),
        (accepted, "https://en.wikipedia.org/wiki/Hallucination_(artificial_intelligence)"),
    ]:
        queued.append({
            "url": url,
            "title": title,
            "why": "Search for grounding and hallucination reduction on Wikipedia",
            "status": "queued",
            "kind": "article",
            "text": "",
        })
    kept, dropped = prune_frontier(queued, mission)
    assert dropped == 9
    assert [item["title"] for item in kept] == [accepted]

    studied = []

    async def fetch(url):
        if "disambiguation" in url:
            return Reading(
                status="ok",
                url=url,
                title="Grounding",
                text="Grounding may refer to:",
                raw=html,
                kind="article",
            )
        return Reading(
            status="ok",
            url=url,
            title="Grounding - Wikipedia",
            text="Grounding (discipline technique) is a parenting method. Nature therapy and sensory deprivation are related pages. " * 4,
            raw=html,
            kind="article",
        )

    async def study(source):
        studied.append(source["url"])
        return {"events": []}

    parent = "https://en.wikipedia.org/wiki/Grounding"
    child = {
        "lead_id": "led_child",
        "mission_id": "msn_test",
        "url": "https://en.wikipedia.org/wiki/Nature_therapy",
        "title": "Nature therapy",
        "why": "Link on the page",
        "from_url": parent,
        "depth": 2,
        "kind": "article",
        "status": "queued",
        "tries": 0,
    }
    sibling = {
        "lead_id": "led_ai_wiki",
        "mission_id": "msn_test",
        "url": "https://en.wikipedia.org/wiki/Hallucination_(artificial_intelligence)",
        "title": accepted,
        "why": "AI sense",
        "from_url": "https://en.wikipedia.org/wiki/Hallucination_(disambiguation)",
        "depth": 1,
        "kind": "article",
        "status": "queued",
        "tries": 0,
    }
    page = {
        "lead_id": "led_ground",
        "mission_id": "msn_test",
        "url": parent,
        "title": accepted,
        "why": "Search for grounding and hallucination reduction",
        "from_url": "",
        "depth": 1,
        "kind": "article",
        "status": "queued",
        "tries": 0,
        "text": "",
    }
    failed = asyncio.run(work_once(
        mission=mission, frontier=[page, child, sibling], fetch=fetch, study=study, now=70, reads_at=[],
    ))
    assert studied == []
    assert failed.action == "skip"
    urls = {item["url"] for item in failed.frontier}
    assert "https://en.wikipedia.org/wiki/Nature_therapy" not in urls
    assert "https://en.wikipedia.org/wiki/Hallucination_(artificial_intelligence)" in urls
    assert "en.wikipedia.org" not in (mission.get("drift_hosts") or [])

    dab = dict(page)
    dab["lead_id"] = "led_dab"
    dab["url"] = "https://en.wikipedia.org/wiki/Grounding_(disambiguation)"
    dab["title"] = "Grounding (disambiguation)"
    opened = asyncio.run(work_once(mission=mission, frontier=[dab], fetch=fetch, study=study, now=80, reads_at=[]))
    assert studied == []
    assert [item["title"] for item in opened.frontier if item.get("status") == "queued"] == [accepted]


def test_vendor_marketing_is_not_a_reading():
    from studyhall.frontier import enqueue, prune_frontier
    from studyhall.pages import QUEUED_PER_HOST, classify_page

    mission = _mission()
    marketing = [
        ("https://www.k2view.com/product-tour", "Product tour"),
        ("https://www.k2view.com/products/ai-data-platform", "AI data platform"),
        ("https://www.k2view.com/pricing", "Pricing"),
        ("https://www.k2view.com/demo", "Book a demo"),
        ("https://www.k2view.com/resources/ebooks/ai-grounding", "Download the ebook"),
        ("https://www.k2view.com/resources/whitepapers/enterprise-ai", "White paper"),
        ("https://www.k2view.com/resources/webinars/ai-agents", "Watch the webinar"),
        ("https://www.k2view.com/gartner", "Gartner"),
        ("https://www.k2view.com/company/news/series-c-funding", "Funding news"),
        ("https://www.k2view.com/customers/case-study", "Case study"),
        ("https://www.k2view.com/partners", "Partners"),
        ("https://www.k2view.com/legal/privacy", "Privacy"),
        ("https://chromewebstore.google.com/detail/ai-assistant/abcd", "AI assistant extension"),
        ("https://chatgpt.com/", "Try ChatGPT"),
        ("https://openai.com/business", "ChatGPT Business"),
        ("https://openai.com/careers", "Careers"),
        ("https://openai.com/safety/deployment-safety-hub/", "Deployment Safety Hub"),
        ("https://openai.com/safety/deployment-safety-hub/evaluations", "Deployment Safety Hub evaluations"),
        ("https://openai.com/safety/deployment-safety-hub/monitoring", "Deployment Safety Hub monitoring"),
        ("https://openai.com/safety/deployment-safety-hub/policies", "Deployment Safety Hub policies"),
    ]
    for url, title in marketing:
        assert classify_page(url, title) not in {"article", "docs", "paper", "thread", "research", "unknown"}
    assert classify_page("https://www.k2view.com/blog/how-language-models-ground-answers", "How language models ground answers") == "article"
    assert classify_page("https://arxiv.org/abs/2601.00001", "Grounding language model assistants") == "paper"
    assert classify_page("https://platform.openai.com/docs/guides/safety", "Safety docs") == "docs"

    queued = [
        {"url": url, "title": title, "status": "queued", "kind": "article", "text": "AI assistants and language models"}
        for url, title in marketing
    ]
    queued.append({
        "url": "https://www.k2view.com/blog/how-language-models-ground-answers",
        "title": "How language models ground answers",
        "status": "queued",
        "kind": "article",
        "text": "Language model assistants keep conversational memory.",
    })
    kept, dropped = prune_frontier(queued, mission)
    assert dropped == len(marketing)
    assert [item["url"] for item in kept] == ["https://www.k2view.com/blog/how-language-models-ground-answers"]

    html = """
    <header><a href="https://openai.com/careers">Careers</a></header>
    <nav><a href="https://www.k2view.com/pricing">Pricing</a></nav>
    <article>
      <p>Language model assistants need conversational memory and grounding.</p>
      <a href="https://example.test/blog/memory-for-language-model-assistants">Long-term memory for language model assistants</a>
    </article>
    <footer><a href="https://www.k2view.com/legal/privacy">Privacy</a></footer>
    """
    leads, _communities = leads_from_document("article", "https://example.test/blog/start", html, depth=0)
    assert [item["url"] for item in leads] == ["https://example.test/blog/memory-for-language-model-assistants"]

    extras = [
        {"url": f"https://example.test/blog/memory-note-{index}", "title": "Long-term memory for conversational assistants", "from_url": "", "depth": 1, "kind": "article"}
        for index in range(8)
    ]
    capped = enqueue([], extras, "msn_test")
    assert len(capped) == QUEUED_PER_HOST

    called = []

    async def fetch(url):
        called.append(url)
        return Reading(status="ok", url=url, title="Try ChatGPT", text="AI " * 20, kind="article")

    frontier = [{
        "lead_id": "led_try",
        "mission_id": "msn_test",
        "url": "https://chatgpt.com/",
        "title": "Try ChatGPT",
        "why": "Link on the page",
        "from_url": "https://example.test/blog/start",
        "depth": 1,
        "kind": "article",
        "status": "queued",
        "tries": 0,
    }, {
        "lead_id": "led_child",
        "mission_id": "msn_test",
        "url": "https://openai.com/safety/deployment-safety-hub/monitoring",
        "title": "Deployment Safety Hub monitoring",
        "why": "Link on the page",
        "from_url": "https://chatgpt.com/",
        "depth": 2,
        "kind": "article",
        "status": "queued",
        "tries": 0,
    }]
    step = asyncio.run(work_once(mission=mission, frontier=frontier, fetch=fetch, study=_no_study, now=90, reads_at=[]))
    assert called == []
    assert step.frontier[0]["status"] == "off_topic"
    assert all(item.get("url") != "https://openai.com/safety/deployment-safety-hub/monitoring" for item in step.frontier)


def test_choose_port_skips_a_busy_one():
    with __import__("socket").socket() as sock:
        sock.bind(("127.0.0.1", 0))
        busy = sock.getsockname()[1]
        chosen = choose_port("127.0.0.1", busy, span=5)
    assert chosen != busy
    assert chosen > busy
