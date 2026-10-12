"""Short cues Observer can attach to a session. No frames, no embeddings."""
from __future__ import annotations

from typing import Optional


def room_cue(present: list) -> str:
    for item in present or []:
        if isinstance(item, dict) and str(item.get("name") or "").strip():
            return "at_desk"
        if isinstance(item, str) and item.strip():
            return "at_desk"
    return "away"


def cue_for_title(present: list, title: str = "") -> dict:
    cue = room_cue(present)
    names: list[str] = []
    for item in present or []:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
        else:
            name = str(item or "").strip()
        if name:
            names.append(name)
    screen = (title or "").strip()
    if cue == "at_desk" and screen:
        note = f"at desk while {screen} is on screen"
    elif cue == "at_desk":
        note = "at desk"
    else:
        note = "away"
    return {"presence": cue, "presence_note": note, "presence_people": names}


def observer_presence_fields(title: str = "") -> dict:
    """Empty when Presence is off. Failures stay empty so Observer keeps writing."""
    try:
        from presence_store import presence_enabled, status_public

        if not presence_enabled():
            return {}
        status = status_public()
    except OSError:
        return {}
    if not status.get("enabled"):
        return {}
    return cue_for_title(status.get("present") or [], title)


def attach_presence_fields(row: dict, title: str = "") -> dict:
    extra = observer_presence_fields(title or str(row.get("title") or ""))
    if not extra:
        return row
    merged = dict(row)
    merged.update(extra)
    return merged
