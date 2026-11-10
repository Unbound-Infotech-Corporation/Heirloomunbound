"""Research missions. The standing assistant-craft mission starts running."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from studyhall.store import Store

STANDING_ID = "msn_assistant_craft"

STANDING_QUERIES = (
    "long-term memory for conversational assistants",
    "personalization without inventing a user's biography",
    "grief-aware conversation and legacy letters",
    "voice interface turn-taking",
    "tool use confirmation and action safety",
    "grounding and hallucination reduction",
    "evaluating conversational assistants",
    "prompt techniques for grounded answers",
    "user trust in AI assistants",
    "local language model assistant design",
)

STANDING_COMMUNITIES = (
    {"name": "r/LocalLLaMA", "url": "https://www.reddit.com/r/LocalLLaMA/", "kind": "subreddit"},
    {"name": "r/MachineLearning", "url": "https://www.reddit.com/r/MachineLearning/", "kind": "subreddit"},
    {"name": "Hacker News", "url": "https://news.ycombinator.com/", "kind": "forum"},
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id() -> str:
    return f"msn_{uuid.uuid4().hex[:12]}"


def standing_mission() -> dict:
    return {
        "mission_id": STANDING_ID,
        "title": "Become a better AI assistant",
        "brief": (
            "Study how a local family twin can be a better assistant: memory, voice, "
            "empathy, tool safety, grounding, evaluation, prompts, and trust. "
            "Practitioner talk counts. Lessons are assistant craft. Nothing is filed until the owner says so."
        ),
        "standing": True,
        "tag": "assistant craft",
        "status": "running",
        "queries": list(STANDING_QUERIES),
        "blocked_terms": [],
        "blocked_hosts": [],
        "pages_per_hour": 12,
        "max_depth": 2,
        "query_cursor": 0,
        "communities": [dict(item) for item in STANDING_COMMUNITIES],
        "created_at": _now(),
    }


def ensure_standing(store: Store) -> dict:
    """Create the standing mission once. A later pause or stop is left alone."""
    items = store.read_items("missions.json")
    for item in items:
        if item.get("mission_id") == STANDING_ID or item.get("standing"):
            return item
    mission = standing_mission()
    items.insert(0, mission)
    store.write_items("missions.json", items)
    return mission


def list_missions(store: Store) -> list[dict]:
    ensure_standing(store)
    return store.read_items("missions.json")


def get_mission(store: Store, mission_id: str) -> dict | None:
    ensure_standing(store)
    for item in store.read_items("missions.json"):
        if item.get("mission_id") == mission_id:
            return item
    return None


def save_mission(store: Store, mission: dict) -> dict:
    items = store.read_items("missions.json")
    found = False
    for index, item in enumerate(items):
        if item.get("mission_id") == mission.get("mission_id"):
            items[index] = mission
            found = True
            break
    if not found:
        items.append(mission)
    store.write_items("missions.json", items)
    return mission


def set_status(store: Store, mission_id: str, status: str) -> dict:
    if status not in {"running", "paused", "stopped"}:
        raise ValueError("Status is running, paused, or stopped.")
    mission = get_mission(store, mission_id)
    if mission is None:
        raise KeyError(mission_id)
    mission["status"] = status
    mission["updated_at"] = _now()
    return save_mission(store, mission)


def create_mission(store: Store, *, title: str, query: str, tag: str = "") -> dict:
    mission = {
        "mission_id": _id(),
        "title": title.strip()[:160] or query.strip()[:160],
        "brief": query.strip()[:500],
        "standing": False,
        "tag": tag,
        "status": "running",
        "queries": [query.strip()],
        "blocked_terms": [],
        "blocked_hosts": [],
        "pages_per_hour": 12,
        "max_depth": 2,
        "query_cursor": 0,
        "communities": [],
        "created_at": _now(),
    }
    return save_mission(store, mission)


def add_block(store: Store, term: str) -> str:
    """Block a term on every mission. The crawl skips matching pages and keeps going."""
    cleaned = " ".join(term.lower().split())
    if not cleaned:
        raise ValueError("Say what to ignore.")
    ensure_standing(store)
    for mission in store.read_items("missions.json"):
        terms = [str(item).lower() for item in mission.get("blocked_terms") or []]
        if cleaned not in terms:
            mission.setdefault("blocked_terms", []).append(cleaned)
            save_mission(store, mission)
    return cleaned


def add_query(store: Store, mission_id: str, query: str) -> dict:
    mission = get_mission(store, mission_id)
    if mission is None:
        raise KeyError(mission_id)
    text = " ".join(query.split())
    queries = list(mission.get("queries") or [])
    if text and text.lower() not in {item.lower() for item in queries}:
        queries.append(text)
        mission["query_cursor"] = len(queries) - 1
    mission["queries"] = queries
    if mission.get("status") == "stopped":
        mission["status"] = "running"
    return save_mission(store, mission)


def running_missions(store: Store) -> list[dict]:
    return [item for item in list_missions(store) if item.get("status") == "running"]
