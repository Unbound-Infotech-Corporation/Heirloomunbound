"""Recognition decisions on embeddings the caller already computed.

This module does not open a camera, load a model, or create a person.
An unknown face stays unknown.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from observer_capture import scene_delta
from presence_models import DEFAULT_THRESHOLD

_UNKNOWN_KEY = "_unknown"


@dataclass
class SeenFace:
    embedding: list[float]
    camera: str = ""
    thumb: bytes | None = None


@dataclass
class Match:
    person_id: str
    name: str
    relationship: str
    score: float
    greeting: str


@dataclass
class PresenceStep:
    tracked: dict
    events: list[dict] = field(default_factory=list)
    greetings: list[dict] = field(default_factory=list)
    unknown_thumbs: list[tuple[str, bytes]] = field(default_factory=list)


def cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return -1.0
    dot = 0.0
    left_sq = 0.0
    right_sq = 0.0
    for a, b in zip(left, right):
        try:
            fa = float(a)
            fb = float(b)
        except (TypeError, ValueError):
            return -1.0
        if not math.isfinite(fa) or not math.isfinite(fb):
            return -1.0
        dot += fa * fb
        left_sq += fa * fa
        right_sq += fb * fb
    if left_sq <= 0.0 or right_sq <= 0.0:
        return -1.0
    return dot / math.sqrt(left_sq * right_sq)


def best_match(embedding: list[float], people: list[dict], threshold: float = DEFAULT_THRESHOLD) -> Optional[Match]:
    """Highest cosine at or above the threshold. Does not create a person."""
    try:
        floor = float(threshold)
    except (TypeError, ValueError):
        floor = DEFAULT_THRESHOLD
    chosen: Optional[Match] = None
    for person in people:
        samples = person.get("embeddings") or []
        if not isinstance(samples, list) or not samples:
            continue
        score = max((cosine(embedding, sample) for sample in samples if isinstance(sample, list)), default=-1.0)
        if score + 1e-9 < floor:
            continue
        person_id = str(person.get("id") or "")
        if not person_id:
            continue
        if chosen is None or score > chosen.score + 1e-12 or (
            abs(score - chosen.score) <= 1e-12 and person_id < chosen.person_id
        ):
            chosen = Match(
                person_id=person_id,
                name=str(person.get("name") or ""),
                relationship=str(person.get("relationship") or ""),
                score=score,
                greeting=str(person.get("greeting") or ""),
            )
    return chosen


def greeting_text(name: str, greeting: str = "") -> str:
    custom = (greeting or "").strip()
    if custom:
        return custom
    who = (name or "").strip()
    if who:
        return f"Welcome back, {who}."
    return "Welcome back."


def _as_utc(now: datetime) -> datetime:
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _parse_iso(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_utc(moment)


def should_greet(last_greeted: str | None, now: datetime, debounce_minutes: float) -> bool:
    try:
        window = float(debounce_minutes)
    except (TypeError, ValueError):
        window = 10.0
    if window <= 0:
        return True
    previous = _parse_iso(last_greeted)
    if previous is None:
        return True
    return _as_utc(now) - previous >= timedelta(minutes=window)


def motion_open(prev: bytes, curr: bytes, threshold: float = 0.04) -> tuple[bool, float]:
    """First frame only sets the reference. Later frames open the gate on change."""
    delta = scene_delta(prev, curr)
    if not prev or not curr:
        return False, delta
    try:
        floor = float(threshold)
    except (TypeError, ValueError):
        floor = 0.04
    return delta >= floor, delta


def _iso(now: datetime) -> str:
    return _as_utc(now).isoformat()


def step(
    seen: list[SeenFace],
    enrolled: list[dict],
    tracked: dict | None,
    now: datetime,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    debounce_minutes: float = 10,
    depart_seconds: float = 30,
    unknown_debounce_minutes: float = 10,
    unknown_thumbnails: bool = False,
    cameras_live: bool = True,
) -> PresenceStep:
    """Update who is here. Never appends a person to ``enrolled``."""
    state = dict(tracked or {})
    moment = _as_utc(now)
    stamp = _iso(moment)
    events: list[dict] = []
    greetings: list[dict] = []
    thumbs: list[tuple[str, bytes]] = []
    matched: dict[str, Match] = {}

    for face in seen:
        found = best_match(face.embedding, enrolled, threshold)
        if found is None:
            continue
        matched[found.person_id] = found

    unknown_faces = [face for face in seen if best_match(face.embedding, enrolled, threshold) is None]

    for person_id, found in matched.items():
        row = dict(state.get(person_id) or {})
        arrived = not bool(row.get("present"))
        row["present"] = True
        row["last_seen"] = stamp
        row["name"] = found.name
        row["relationship"] = found.relationship
        if arrived:
            row["arrived_at"] = stamp
            greet = should_greet(str(row.get("last_greeted") or ""), moment, debounce_minutes)
            if greet:
                row["last_greeted"] = stamp
            text = greeting_text(found.name, found.greeting)
            events.append({
                "ts": stamp,
                "kind": "arrival",
                "person_id": person_id,
                "name": found.name,
                "greeted": greet,
            })
            if greet:
                greetings.append({
                    "ts": stamp,
                    "person_id": person_id,
                    "name": found.name,
                    "text": text,
                })
        state[person_id] = row

    if cameras_live:
        try:
            depart_after = float(depart_seconds)
        except (TypeError, ValueError):
            depart_after = 30.0
        for person_id, raw in list(state.items()):
            if person_id.startswith("_") or not isinstance(raw, dict):
                continue
            if person_id in matched or not raw.get("present"):
                continue
            last = _parse_iso(str(raw.get("last_seen") or ""))
            if last is None:
                continue
            if moment - last >= timedelta(seconds=max(1.0, depart_after)):
                raw = dict(raw)
                raw["present"] = False
                state[person_id] = raw
                events.append({
                    "ts": stamp,
                    "kind": "departure",
                    "person_id": person_id,
                    "name": str(raw.get("name") or ""),
                    "greeted": False,
                })

    if unknown_faces:
        marker = dict(state.get(_UNKNOWN_KEY) or {})
        if should_greet(str(marker.get("last_at") or ""), moment, unknown_debounce_minutes):
            marker["last_at"] = stamp
            state[_UNKNOWN_KEY] = marker
            events.append({"ts": stamp, "kind": "unrecognized"})
            if unknown_thumbnails:
                thumb = next((face.thumb for face in unknown_faces if face.thumb), None)
                if thumb:
                    thumbs.append((stamp, thumb))

    return PresenceStep(tracked=state, events=events, greetings=greetings, unknown_thumbs=thumbs)


def touch_present(tracked: dict | None, now: datetime) -> dict:
    """A calm frame keeps people who are already here. It does not enroll anyone."""
    state = {key: (dict(value) if isinstance(value, dict) else value) for key, value in (tracked or {}).items()}
    stamp = _iso(now)
    for person_id, raw in list(state.items()):
        if person_id.startswith("_") or not isinstance(raw, dict) or not raw.get("present"):
            continue
        raw["last_seen"] = stamp
        state[person_id] = raw
    return state


def present_people(tracked: dict | None) -> list[dict]:
    rows: list[dict] = []
    for person_id, raw in (tracked or {}).items():
        if person_id.startswith("_") or not isinstance(raw, dict) or not raw.get("present"):
            continue
        rows.append({
            "id": person_id,
            "name": str(raw.get("name") or ""),
            "relationship": str(raw.get("relationship") or ""),
            "since": str(raw.get("arrived_at") or raw.get("last_seen") or ""),
        })
    rows.sort(key=lambda row: row["name"].lower())
    return rows
