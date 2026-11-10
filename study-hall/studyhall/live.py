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


def color_for(name: str, kind: str = "") -> str:
    if name in COLORS:
        return COLORS[name]
    if kind == "openai" or name.startswith("gpt-"):
        return "#1f8a4c" if "mini" not in name else "#7dcea0"
    if kind == "gemini" or name.startswith("gemini"):
        return "#674ea7" if name.endswith("pro") else "#8e7cc3"
    return "#c4bbb0"


def chat_event(name: str, text: str, *, role: str = "reader", kind: str = "", placeholder: bool = False) -> dict:
    return {
        "event": "chat",
        "data": {
            "name": name,
            "role": role,
            "kind": kind,
            "color": color_for(name, kind),
            "text": text[:700],
            "placeholder": placeholder,
            "at": _now(),
        },
    }


def short_turn(round_name: str, parsed: dict, raw: str, *, placeholder: bool = False, model: str = "") -> str:
    """One short line from a model's real reply."""
    if placeholder:
        detail = (raw or "").strip() or f"{model} did not answer."
        if not detail.lower().startswith("placeholder"):
            detail = f"Placeholder. {detail}"
        return detail[:320]
    if round_name == "critique":
        line = parsed.get("keep") or parsed.get("reject") or parsed.get("agree") or ""
    elif round_name == "pin":
        line = parsed.get("summary") or ""
        why = parsed.get("why_it_matters") or ""
        if why:
            line = f"{line} {why}".strip()
    else:
        line = parsed.get("useful") or parsed.get("cautions") or ""
    line = " ".join(str(line or raw or "").split())
    if not line:
        return f"Placeholder. {model or 'This seat'} returned nothing usable."
    return line[:320]


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
