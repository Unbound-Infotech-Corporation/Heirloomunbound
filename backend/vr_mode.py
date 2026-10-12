"""Owner VR preference for the Heirloom Room.

The saved toggle is a preference. It is not a session. Launch always
returns to the normal screen, even when a headset is plugged in and the
saved switch is on. Eye-tracking notes are aggregated dwell only.
"""
from __future__ import annotations

import uuid
from typing import Any

from observer_learn import fingerprint, tokenize
from owner_pairing import is_owner_audience

VR_GAZE_SOURCE = "vr_gaze"
GAZE_AREAS = ("twin", "seat", "room", "floor", "elsewhere")
MIN_DWELL_MS = 400
MAX_DWELL_MS = 30 * 60 * 1000
_RAW_KEYS = frozenset(
    {
        "origin",
        "direction",
        "ray",
        "quaternion",
        "pupil",
        "gaze",
        "gaze_x",
        "gaze_y",
        "gaze_z",
        "x",
        "y",
        "z",
        "raw",
        "samples_raw",
        "stream",
        "matrix",
    }
)
_AREA_LABELS = {
    "twin": "the twin",
    "seat": "the twin's seat",
    "room": "the room",
    "floor": "the floor",
    "elsewhere": "elsewhere in the room",
}


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def owner_vr_allowed(*, audience: str | None, heir_surface: bool = False) -> bool:
    """VR and gaze notes are an owner sitting. Heirs stay on the normal screen."""
    if heir_surface:
        return False
    return is_owner_audience(audience)


def default_vr_prefs() -> dict[str, bool]:
    return {"enabled": False, "gaze_enabled": False}


def clamp_vr_prefs(raw: dict | None) -> dict[str, bool]:
    """Persist the two switches. Drop any session or raw-gaze fields."""
    src = raw if isinstance(raw, dict) else {}
    gaze_raw = src.get("gaze_enabled", src.get("gazeEnabled"))
    return {
        "enabled": _as_bool(src.get("enabled"), False),
        "gaze_enabled": _as_bool(gaze_raw, False),
    }


def should_auto_enter(*, headset_connected: bool = False, enabled: bool = False) -> bool:
    """A connected headset never starts VR. The owner turns it on."""
    del headset_connected, enabled
    return False


def launch_vr_state(raw: dict | None, *, headset_connected: bool = False) -> dict[str, Any]:
    prefs = clamp_vr_prefs(raw)
    return {
        **prefs,
        "session_active": False,
        "auto_enter": should_auto_enter(headset_connected=headset_connected, enabled=prefs["enabled"]),
    }


def plan_toggle(
    prefs: dict | None,
    *,
    next_enabled: bool,
    gesture: bool,
    surface: str,
    session_active: bool,
) -> dict[str, Any]:
    """Decide whether a switch change may start or end a headset session.

    ``surface`` is ``room`` (the sit view) or ``settings``. Settings never
    start a session. A session starts only from the Room, and only on the
    click that turns VR on.
    """
    current = clamp_vr_prefs(prefs)
    if not gesture:
        return {
            "prefs": current,
            "start_session": False,
            "end_session": False,
            "reason": "no-gesture",
        }
    if not next_enabled:
        return {
            "prefs": {"enabled": False, "gaze_enabled": current["gaze_enabled"]},
            "start_session": False,
            "end_session": True,
            "reason": "toggled-off",
        }
    nxt = {"enabled": True, "gaze_enabled": current["gaze_enabled"]}
    if surface != "room":
        return {
            "prefs": nxt,
            "start_session": False,
            "end_session": False,
            "reason": "settings",
        }
    return {
        "prefs": nxt,
        "start_session": not session_active,
        "end_session": False,
        "reason": "user-gesture",
    }


def plan_enter(*, enabled: bool, gesture: bool, session_active: bool) -> dict[str, Any]:
    """Enter control for a preference that was already on at launch."""
    if not gesture:
        return {"start_session": False, "reason": "no-gesture"}
    if not enabled:
        return {"start_session": False, "reason": "off"}
    if session_active:
        return {"start_session": False, "reason": "already"}
    return {"start_session": True, "reason": "user-gesture"}


def plan_gaze(prefs: dict | None, *, next_gaze: bool, gesture: bool) -> dict[str, Any]:
    current = clamp_vr_prefs(prefs)
    if not gesture:
        return {"prefs": current, "start_session": False, "reason": "no-gesture"}
    return {
        "prefs": {"enabled": current["enabled"], "gaze_enabled": bool(next_gaze)},
        "start_session": False,
        "reason": "gaze",
    }


def sanitize_gaze_samples(samples: Any) -> list[dict[str, Any]]:
    """Keep area and dwell. Drop rays, pupils, and unknown areas."""
    if not isinstance(samples, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for item in samples:
        if not isinstance(item, dict):
            continue
        if _RAW_KEYS.intersection(item):
            # A row that carries a raw sample is not stored, even if it also
            # names an area. The caller sends summaries, not the stream.
            item = {key: value for key, value in item.items() if key not in _RAW_KEYS}
        area = str(item.get("area") or "").strip().lower()
        if area not in GAZE_AREAS:
            continue
        try:
            dwell = int(item.get("dwell_ms") or 0)
        except (TypeError, ValueError):
            continue
        if dwell <= 0:
            continue
        cleaned.append({"area": area, "dwell_ms": min(dwell, MAX_DWELL_MS)})
    return cleaned


def aggregate_gaze(samples: Any) -> list[dict[str, Any]]:
    totals: dict[str, int] = {}
    order: list[str] = []
    for row in sanitize_gaze_samples(samples):
        area = str(row["area"])
        if area not in totals:
            order.append(area)
            totals[area] = 0
        totals[area] += int(row["dwell_ms"])
    return [
        {"area": area, "dwell_ms": totals[area]}
        for area in order
        if totals[area] >= MIN_DWELL_MS
    ]


def format_gaze_note(summaries: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for row in summaries:
        area = str(row.get("area") or "")
        label = _AREA_LABELS.get(area)
        if not label:
            continue
        seconds = max(1, int(round(int(row.get("dwell_ms") or 0) / 1000)))
        unit = "second" if seconds == 1 else "seconds"
        parts.append(f"{label} for {seconds} {unit}")
    if not parts:
        return ""
    if len(parts) == 1:
        body = parts[0]
    else:
        body = ", ".join(parts[:-1]) + f" and {parts[-1]}"
    return f"In VR, looked at {body}."


def build_gaze_note(summaries: list[dict[str, Any]], *, created_at: str = "") -> dict[str, Any] | None:
    text = format_gaze_note(summaries)
    if not text:
        return None
    topics = [str(row["area"]) for row in summaries if row.get("area") in GAZE_AREAS]
    return {
        "id": f"gaze_{uuid.uuid4().hex[:12]}",
        "source": VR_GAZE_SOURCE,
        "kind": "attention",
        "text": text,
        "confidence": 0.55,
        "created_at": created_at,
        "status": "pending",
        "session_id": "",
        "fingerprint": fingerprint(text),
        "tokens": tokenize(text),
        "topics": topics,
    }


def accept_gaze(
    samples: Any,
    *,
    audience: str | None,
    heir_surface: bool = False,
    gaze_enabled: bool = False,
    paused: bool = False,
    observer_on: bool = False,
) -> dict[str, Any]:
    """Whether an attention summary may be written. Never stores a raw stream."""
    if not owner_vr_allowed(audience=audience, heir_surface=heir_surface):
        return {"ok": False, "stored": False, "status": 404, "reason": "heir"}
    summaries = aggregate_gaze(samples)
    if not gaze_enabled:
        return {"ok": True, "stored": False, "status": 200, "reason": "opt-in-off", "summaries": summaries}
    if paused:
        return {"ok": True, "stored": False, "status": 200, "reason": "paused", "summaries": summaries}
    if not observer_on:
        return {"ok": True, "stored": False, "status": 200, "reason": "observer-off", "summaries": summaries}
    note = build_gaze_note(summaries)
    if note is None:
        return {"ok": True, "stored": False, "status": 200, "reason": "empty", "summaries": summaries}
    return {"ok": True, "stored": True, "status": 200, "reason": "ok", "summaries": summaries, "note": note}
