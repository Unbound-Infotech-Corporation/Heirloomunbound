"""Plain-language instructions for the research room."""
from __future__ import annotations

import base64
import re
from urllib.parse import parse_qs, unquote, urlparse

from studyhall.embed import keyword_overlap
from studyhall.missions import STANDING_ID, add_block, add_query, create_mission, get_mission, list_missions, set_status
from studyhall.store import Store

_RESEARCH = re.compile(
    r"^(?:please\s+)?(?:find|look into|research|study|search for)\b(?:\s+the best current research on|\s+how|\s+into|\s+for)?\s*(.+)$",
    re.IGNORECASE,
)
_IGNORE = re.compile(
    r"^(?:please\s+)?(?:ignore|block|skip|don't|do not)\s+(?:read\s+|use\s+|include\s+)?(.+?)(?:\s+sources)?$",
    re.IGNORECASE,
)
_PAUSE = re.compile(r"\b(pause|hold)\b", re.IGNORECASE)
_STOP = re.compile(r"\bstop\b", re.IGNORECASE)
_START = re.compile(r"\b(start|resume|continue)\b", re.IGNORECASE)
_PROGRESS = re.compile(r"\b(progress|status|how is it going|what are you doing)\b", re.IGNORECASE)
_LEARNED = re.compile(r"\b(what have we learned|what did we (?:find|learn)|what's been learned|summarize what)\b", re.IGNORECASE)


def _clean_topic(text: str) -> str:
    topic = text.strip().strip("?.!\"'")
    topic = re.sub(r"^(the best current research on|research on|about)\s+", "", topic, flags=re.IGNORECASE)
    return " ".join(topic.split())[:240]


_URL = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
LOGIN_HOSTS = (
    "facebook.com",
    "fb.com",
    "instagram.com",
    "linkedin.com",
    "x.com",
    "twitter.com",
)


def unwrap_url(url: str) -> str:
    """Turn a Bing or Google redirect into the article it points at."""
    raw = (url or "").strip().rstrip(").,;\"'")
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    query = parse_qs(parsed.query)
    if "bing.com" in host and parsed.path.startswith("/ck/"):
        token = (query.get("u") or [""])[0]
        if token.startswith("a1"):
            token = token[2:]
        padding = "=" * ((4 - len(token) % 4) % 4)
        try:
            decoded = base64.urlsafe_b64decode(token + padding).decode("utf-8", "replace")
        except Exception:
            decoded = ""
        if decoded.startswith("http"):
            return decoded
    if "google." in host and parsed.path == "/url":
        target = unquote((query.get("q") or query.get("url") or [""])[0])
        if target.startswith("http"):
            return target
    return raw


def urls_in(text: str) -> list[str]:
    return [unwrap_url(match) for match in _URL.findall(text or "")]


def login_wall(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == name or host.endswith("." + name) for name in LOGIN_HOSTS)


def interpret(text: str) -> dict:
    """A deterministic reading of an owner instruction. A model may refine the reply, not the action."""
    raw = " ".join((text or "").split())
    if not raw:
        return {"action": "none", "detail": ""}
    found = urls_in(raw)
    if found:
        return {"action": "read_url", "detail": found[0], "urls": found}
    if _PAUSE.search(raw) and not _RESEARCH.match(raw):
        return {"action": "pause", "detail": raw}
    if _STOP.search(raw) and not _RESEARCH.match(raw):
        return {"action": "stop", "detail": raw}
    if _START.search(raw) and not _RESEARCH.match(raw):
        return {"action": "start", "detail": raw}
    ignore = _IGNORE.match(raw)
    if ignore:
        detail = _clean_topic(ignore.group(1))
        detail = re.sub(r"\b(sources?|topics?)\b", "", detail, flags=re.IGNORECASE).strip()
        return {"action": "block", "detail": detail or raw}
    if _PROGRESS.search(raw) or _LEARNED.search(raw):
        return {"action": "progress" if _PROGRESS.search(raw) and not _LEARNED.search(raw) else "learned", "detail": raw}
    research = _RESEARCH.match(raw)
    if research:
        return {"action": "research", "detail": _clean_topic(research.group(1))}
    if raw.endswith("?") or raw.lower().startswith(("what", "how", "why", "where", "who")):
        return {"action": "answer", "detail": raw}
    return {"action": "answer", "detail": raw}


def _sentences(text: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text or "") if part.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def grounded_reply(question: str, sources: list[dict], lessons: list[dict]) -> dict:
    """Answer only from text already in the library or in lesson cards."""
    citations = []
    snippets = []
    for source in sources:
        blob = " ".join([str(source.get("title") or ""), str(source.get("text") or "")])
        if keyword_overlap(question, blob) < 2:
            continue
        sentence = ""
        for line in _sentences(str(source.get("text") or "")):
            if keyword_overlap(question, line) >= 1:
                sentence = line
                break
        if not sentence:
            continue
        citations.append({
            "title": source.get("title") or source.get("url") or "Reading",
            "url": source.get("url") or "",
        })
        snippets.append(sentence[:320])
        if len(snippets) == 2:
            break
    for lesson in lessons:
        blob = " ".join([str(lesson.get("summary") or ""), str(lesson.get("why_it_matters") or ""), str(lesson.get("source_title") or "")])
        if keyword_overlap(question, blob) < 2:
            continue
        citations.append({
            "title": lesson.get("source_title") or "Lesson",
            "url": lesson.get("source_url") or "",
        })
        snippets.append(str(lesson.get("summary") or "")[:320])
        if len(snippets) == 3:
            break
    if not snippets:
        return {
            "reply": "Nothing already read answers that. I will not guess. Give me a topic and I will go look.",
            "citations": [],
        }
    lines = " ".join(snippets[:2])
    cite = "; ".join(item["title"] for item in citations[:3])
    return {
        "reply": f"From what is already in the library: {lines} Source: {cite}.",
        "citations": citations[:3],
    }


def _target_mission(store: Store) -> dict:
    missions = list_missions(store)
    running = [item for item in missions if item.get("status") == "running"]
    if running:
        standing = [item for item in running if item.get("standing")]
        return standing[0] if standing else running[0]
    standing = [item for item in missions if item.get("mission_id") == STANDING_ID]
    return standing[0] if standing else missions[0]


def apply_instruction(store: Store, text: str) -> dict:
    """Act on an instruction and return the reply. Does not file lessons or change twin code."""
    parsed = interpret(text)
    action = parsed["action"]
    detail = parsed["detail"]
    mission = _target_mission(store)
    if action == "pause":
        updated = set_status(store, mission["mission_id"], "paused")
        return {"reply": f"Paused “{updated['title']}”. It will sit until you start it again.", "action": action, "mission": updated, "citations": []}
    if action == "stop":
        updated = set_status(store, mission["mission_id"], "stopped")
        return {"reply": f"Stopped “{updated['title']}”. Say start when you want it moving again.", "action": action, "mission": updated, "citations": []}
    if action == "start":
        updated = set_status(store, mission["mission_id"], "running")
        return {"reply": f"“{updated['title']}” is running. It keeps going until you pause or stop it.", "action": action, "mission": updated, "citations": []}
    if action == "block":
        term = add_block(store, detail)
        return {"reply": f"I’ll skip anything about “{term}”. The room stays on.", "action": action, "mission": get_mission(store, mission["mission_id"]), "citations": []}
    if action == "research":
        if mission.get("standing") and detail:
            updated = add_query(store, mission["mission_id"], detail)
            reply = f"Added “{detail}” to “{updated['title']}”. I’ll look through public sources and the panel will draft cards for you to file."
        else:
            updated = create_mission(store, title=detail[:80], query=detail)
            reply = f"Started “{updated['title']}”. It runs until you pause or stop it."
        return {"reply": reply, "action": action, "mission": updated, "citations": []}
    if action == "progress":
        queued = len([item for item in store.read_items("frontier.json") if item.get("status") == "queued"])
        read = len([item for item in store.read_items("frontier.json") if item.get("status") == "read"])
        lessons = len(store.read_items("lessons.json"))
        return {
            "reply": f"“{mission['title']}” is {mission.get('status')}. {read} pages read, {queued} still waiting, {lessons} lesson cards so far. None of them are filed until you say so.",
            "action": action,
            "mission": mission,
            "citations": [],
        }
    sources = store.read_items("library.json")
    lessons = store.read_items("lessons.json")
    grounded = grounded_reply(detail or text, sources, lessons)
    grounded["action"] = "answer"
    grounded["mission"] = mission
    return grounded
