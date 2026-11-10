"""Live Room events. The stream is server-sent events."""
from __future__ import annotations

import json
from datetime import datetime, timezone

COLORS = {
    "phi4:14b": "#e0b07a",
    "mistral-small3.2:24b": "#8fb4c9",
    "gemma3:27b": "#d0a0c4",
    "llama3.1:8b": "#f0d2b0",
    "owner": "#f4f0e8",
}


def sse(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"


def parse_sse(frame: str) -> tuple[str, dict]:
    event = "message"
    data = ""
    for line in frame.splitlines():
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data += line.split(":", 1)[1].strip()
    return event, json.loads(data or "{}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def chat_event(name: str, text: str, *, role: str = "reader") -> dict:
    return {
        "event": "chat",
        "data": {
            "name": name,
            "role": role,
            "color": COLORS.get(name, "#c4bbb0"),
            "text": text[:700],
            "at": _now(),
        },
    }


def script_discussion(title: str, text: str, *, tag: str = "") -> list[dict]:
    """A readable room when no local model is answering. Still grounded in the page."""
    clip = " ".join((text or "").split())[:220]
    craft = " This is assistant craft, so a concrete idea can wait in the queue." if tag == "assistant craft" else ""
    return [
        chat_event("phi4:14b", f"Useful: “{title}” says {clip}"),
        chat_event("mistral-small3.2:24b", "Dubious if we treat any of this as the owner’s life. Keep the citation attached."),
        chat_event("gemma3:27b", f"The twin could use the method and still say when something was not filed.{craft}"),
        chat_event("llama3.1:8b", "Pinning a draft lesson. It is not filed until you say so.", role="moderator"),
    ]


def lesson_event(lesson: dict) -> dict:
    return {"event": "lesson", "data": lesson}


def proposal_event(proposal: dict) -> dict:
    return {"event": "proposal", "data": proposal}
