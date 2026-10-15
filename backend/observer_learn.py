"""Turn allowed observations into sessions and vault notes. No frames."""
from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime
from typing import Any, Iterable, Optional

_STOP = frozenset(
    "the a an and or of to in on for with from at by as is are was were be been "
    "it this that he she they his her you your i we our".split()
)
_WORK = (
    "visual studio",
    "vscode",
    "vs code",
    "intellij",
    "terminal",
    "powershell",
    "windows terminal",
    "google docs",
    "notion",
    "figma",
    "outlook",
    "excel",
    "word",
    "libreoffice",
)
_BROWSE = ("chrome", "firefox", "edge", "safari", "browser")
_MEDIA = ("youtube", "netflix", "vlc", "spotify", "plex", "mpv")
_GAME = (
    "steam",
    "epic games",
    "minecraft",
    "hades",
    "elden ring",
    "overwatch",
    "valorant",
    "league of legends",
    "fortnite",
    "baldur",
    "stardew",
)
_FAILURE = re.compile(r"(?i)\b(?:you died|game over|defeat|respawn|wasted|try again)\b")
_RETRY = re.compile(r"(?i)\b(?:retry|respawn|continue|load save|try again)\b")
_RISK = re.compile(r"(?i)\b(?:all in|aggressive|reckless|low health|rush)\b")
_PATIENCE = re.compile(r"(?i)\b(?:wait|stealth|patient|camp|hold position)\b")
_EXPLORE = re.compile(r"(?i)\b(?:explore|side quest|wander|map)\b")
_OBJECTIVE = re.compile(r"(?i)\b(?:objective|quest marker|main quest|mission)\b")


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9']+", (text or "").lower())
    out: list[str] = []
    for word in words:
        if len(word) < 3 or word in _STOP:
            continue
        out.append(word)
        if len(word) > 4 and word.endswith("s") and word[:-1] not in _STOP:
            out.append(word[:-1])
        stem = _light_stem(word)
        if stem and stem not in _STOP and stem not in out:
            out.append(stem)
    return out


def _light_stem(word: str) -> str:
    """Enough to match stayed/stay and switching/switch. Stems shorter than 4 are dropped."""
    if len(word) > 5 and word.endswith("ing"):
        stem = word[:-3]
    elif len(word) > 5 and word.endswith("ed"):
        stem = word[:-2]
    else:
        return ""
    return stem if len(stem) >= 4 else ""


_TRANSCRIPT_ACTIVITIES = frozenset({"speech", "heard"})


def normalize_note_text(text: str) -> str:
    """Compare notes without case, punctuation, or extra spaces."""
    folded = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", folded).strip()


def same_note_text(left: str, right: str) -> bool:
    a = normalize_note_text(left)
    b = normalize_note_text(right)
    return bool(a) and a == b


def fingerprint(text: str) -> str:
    tokens = sorted(set(tokenize(text)))
    return hashlib.sha256(" ".join(tokens).encode("utf-8")).hexdigest()[:16]


def jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    a = set(left)
    b = set(right)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _parse_ts(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


_CAPTURE_MARKERS = ("xr1", "evga", "uvc", "usb video", "capture box", "video capture")


def is_capture_device_label(name: str) -> bool:
    """True when the string is the HDMI capture card, not a program the owner opened.

    The XR1 enumerates as a name like ``EVGA XR1 Lite Capture Box Video``. That
    label is the camera, so it cannot become "Often in …".
    """
    folded = re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()
    if not folded or len(folded.split()) > 12:
        return False
    return any(marker in folded for marker in _CAPTURE_MARKERS)


def habit_identity(text: str) -> str:
    """Same habit ignoring the sample count, which changes every analysis."""
    folded = normalize_note_text(text)
    folded = re.sub(r"\b\d+\s+samples this stretch\b", "", folded)
    return re.sub(r"\s+", " ", folded).strip()


def classify_activity(text: str, app: str = "") -> tuple[str, str]:
    """Return ``(activity, game)``. Activity is work, play, browsing, media, or unknown."""
    blob = f"{app}\n{text}".lower()
    game = ""
    for name in _GAME:
        if name in blob:
            game = name.title() if name != "epic games" else "Epic Games"
            if name == "steam":
                game = _game_after_steam(text) or "Steam"
            return "play", game
    for name in _MEDIA:
        if name in blob:
            return "media", ""
    for name in _WORK:
        if name in blob:
            return "work", ""
    for name in _BROWSE:
        if name in blob:
            return "browsing", ""
    hinted = (app or "").strip()
    if hinted:
        return "unknown", ""
    return "unknown", ""


def _game_after_steam(text: str) -> str:
    match = re.search(r"(?i)\bsteam\b[:\-\s]+([A-Z][\w' ]{2,40})", text or "")
    if not match:
        return ""
    return match.group(1).strip()


def game_decision_summary(texts: list[str], game: str) -> str:
    blob = "\n".join(texts)
    failures = len(_FAILURE.findall(blob))
    retries = len(_RETRY.findall(blob))
    bits: list[str] = []
    title = game or "a game"
    if failures and retries:
        bits.append(
            f"After a loss in {title} he retries quickly instead of stopping "
            f"({failures} failure cues, {retries} retry cues)."
        )
    elif failures:
        bits.append(f"In {title} a loss shows up on screen and he stays in the game.")
    if _RISK.search(blob):
        bits.append(f"In {title} he takes the riskier line when the screen offers one.")
    if _PATIENCE.search(blob):
        bits.append(f"In {title} he waits and plays the patient line.")
    if _EXPLORE.search(blob) and not _OBJECTIVE.search(blob):
        bits.append(f"In {title} he explores instead of pushing the objective.")
    elif _OBJECTIVE.search(blob) and not _EXPLORE.search(blob):
        bits.append(f"In {title} he follows the objective.")
    elif _EXPLORE.search(blob) and _OBJECTIVE.search(blob):
        bits.append(f"In {title} he mixes exploration with the objective.")
    if not bits:
        return f"Played {title}."
    return " ".join(bits)


def segment_sessions(observations: list[dict], *, gap_s: float = 600.0) -> list[dict]:
    """Contiguous activity spans. A gap or a different activity starts a session."""
    ordered = sorted(
        observations,
        key=lambda row: _parse_ts(row.get("ts")) or datetime.min,
    )
    sessions: list[dict] = []
    current: dict | None = None
    for row in ordered:
        activity = str(row.get("activity") or "unknown")
        if activity == "idle":
            if current is not None:
                sessions.append(_close_session(current))
                current = None
            continue
        moment = _parse_ts(row.get("ts"))
        if current is None:
            current = _open_session(row, activity, moment)
            continue
        previous = current["end"]
        gap = 0.0
        if moment is not None and previous is not None:
            gap = (moment - previous).total_seconds()
        if activity != current["activity"] or gap > gap_s:
            sessions.append(_close_session(current))
            current = _open_session(row, activity, moment)
            continue
        current["rows"].append(row)
        if moment is not None:
            current["end"] = moment
    if current is not None:
        sessions.append(_close_session(current))
    return sessions


def _open_session(row: dict, activity: str, moment: Optional[datetime]) -> dict:
    return {
        "activity": activity,
        "start": moment,
        "end": moment,
        "rows": [row],
    }


def _close_session(current: dict) -> dict:
    start = current["start"]
    end = current["end"]
    focus = 0.0
    if start is not None and end is not None:
        focus = max(0.0, (end - start).total_seconds())
    titles: list[str] = []
    for row in current["rows"]:
        title = str(row.get("title") or row.get("app") or "").strip()
        if not title or title in titles or is_capture_device_label(title):
            continue
        titles.append(title)
    games = [str(row.get("game") or "") for row in current["rows"] if row.get("game")]
    return {
        "id": f"ses_{uuid.uuid4().hex[:12]}",
        "activity": current["activity"],
        "start": start.isoformat() if start else "",
        "end": end.isoformat() if end else "",
        "focus_seconds": int(focus),
        "titles": titles,
        "game": games[-1] if games else "",
        "rows": current["rows"],
    }


def count_switches(sessions: list[dict]) -> int:
    total = 0
    previous = ""
    for session in sessions:
        activity = str(session.get("activity") or "")
        if previous and activity != previous:
            total += 1
        previous = activity
    return total


def suppressed(candidate: dict, suppressions: list[dict]) -> bool:
    tokens = candidate.get("tokens") or tokenize(candidate.get("text") or "")
    topics = set(candidate.get("topics") or [])
    kind = str(candidate.get("kind") or "")
    digest = candidate.get("fingerprint") or fingerprint(candidate.get("text") or "")
    for item in suppressions:
        other = item.get("tokens") or []
        score = jaccard(tokens, other)
        scope = str(item.get("scope") or "reject")
        if digest and digest == item.get("fingerprint"):
            return True
        if scope == "never":
            if score >= 0.34:
                return True
            shared = topics & set(item.get("topics") or [])
            if shared and kind and kind == item.get("kind"):
                return True
        elif score >= 0.5:
            return True
    return False


def notes_from_observations(
    observations: list[dict],
    *,
    suppressions: list[dict] | None = None,
) -> list[dict]:
    """Structured notes. Caller still runs suppression; this filters too.

    Transcript rows already became speech notes. They stay out of habit and
    workflow drafts so a spoken line is not also "often in User said".
    """
    blocked = list(suppressions or [])
    observations = [
        row
        for row in observations
        if not row.get("channel") and str(row.get("activity") or "") not in _TRANSCRIPT_ACTIVITIES
    ]
    sessions = segment_sessions(observations)
    drafts: list[dict] = []
    drafts.extend(_workflow_notes(sessions))
    drafts.extend(_habit_notes(observations))
    drafts.extend(_focus_notes(sessions))
    drafts.extend(_game_notes(sessions))
    drafts.extend(_vocabulary_notes(observations))
    kept: list[dict] = []
    seen: set[str] = set()
    for note in drafts:
        if note["fingerprint"] in seen or suppressed(note, blocked):
            continue
        seen.add(note["fingerprint"])
        kept.append(note)
    return kept


def transcript_note(*, channel: str, text: str, created_at: str = "") -> dict:
    """One memory row for a transcript. Mic and system audio stay separate kinds."""
    kind = "speech" if channel == "mic" else "heard"
    topics = ["user said"] if channel == "mic" else ["watching heard"]
    return _make_note(kind=kind, text=text, confidence=0.82, topics=topics, created_at=created_at)


def _make_note(
    *,
    kind: str,
    text: str,
    confidence: float,
    session_id: str = "",
    topics: list[str] | None = None,
    created_at: str = "",
) -> dict:
    tokens = tokenize(text)
    return {
        "id": f"obs_{uuid.uuid4().hex[:12]}",
        "source": "observer",
        "kind": kind,
        "text": text.strip(),
        "confidence": round(max(0.0, min(0.99, confidence)), 2),
        "created_at": created_at,
        "status": "pending",
        "session_id": session_id,
        "fingerprint": fingerprint(text),
        "tokens": tokens,
        "topics": [topic.lower() for topic in (topics or []) if topic],
    }


def _workflow_notes(sessions: list[dict]) -> list[dict]:
    notes: list[dict] = []
    for session in sessions:
        if session["activity"] != "work":
            continue
        titles = [title for title in session["titles"] if title]
        if len(titles) < 3:
            continue
        steps = "; ".join(f"{index}. {title}" for index, title in enumerate(titles, start=1))
        text = f"Work session, step by step: {steps}."
        notes.append(
            _make_note(
                kind="workflow",
                text=text,
                confidence=min(0.92, 0.45 + 0.1 * len(titles)),
                session_id=session["id"],
                topics=titles[:4],
                created_at=session["end"],
            )
        )
    return notes


def _habit_notes(observations: list[dict]) -> list[dict]:
    counts: dict[str, int] = {}
    activity_for: dict[str, str] = {}
    for row in observations:
        app = str(row.get("app") or "").strip()
        title = str(row.get("title") or "").strip()
        if is_capture_device_label(app):
            app = ""
        if is_capture_device_label(title):
            title = ""
        app = app or title
        if not app or str(row.get("activity") or "") in {"", "idle", "unknown"}:
            continue
        counts[app] = counts.get(app, 0) + 1
        activity_for[app] = str(row.get("activity") or "unknown")
    notes: list[dict] = []
    for app, count in counts.items():
        if count < 4 or is_capture_device_label(app):
            continue
        activity = activity_for[app]
        text = f"Often in {app} during {activity}."
        notes.append(
            _make_note(
                kind="habit",
                text=text,
                confidence=min(0.9, 0.5 + 0.05 * count),
                topics=[app, activity],
            )
        )
    return notes


def _focus_notes(sessions: list[dict]) -> list[dict]:
    notes: list[dict] = []
    for session in sessions:
        minutes = int(session["focus_seconds"] // 60)
        if minutes < 25:
            continue
        text = (
            f"Stayed with {session['activity']} for {minutes} minutes "
            "before switching."
        )
        notes.append(
            _make_note(
                kind="preference",
                text=text,
                confidence=0.7 if minutes < 50 else 0.82,
                session_id=session["id"],
                topics=[session["activity"]],
                created_at=session["end"],
            )
        )
    return notes


def _game_notes(sessions: list[dict]) -> list[dict]:
    notes: list[dict] = []
    for session in sessions:
        if session["activity"] != "play":
            continue
        texts = [str(row.get("text") or "") for row in session["rows"]]
        game = session["game"] or "a game"
        summary = game_decision_summary(texts, game)
        cues = len(_FAILURE.findall("\n".join(texts))) + len(_RETRY.findall("\n".join(texts)))
        notes.append(
            _make_note(
                kind="decision_style",
                text=summary,
                confidence=min(0.9, 0.55 + 0.08 * max(cues, 1)),
                session_id=session["id"],
                topics=[game],
                created_at=session["end"],
            )
        )
    return notes


def _vocabulary_notes(observations: list[dict]) -> list[dict]:
    counts: dict[str, int] = {}
    for row in observations:
        phrases = row.get("owner_phrases") or []
        if isinstance(phrases, str):
            phrases = [phrases]
        for phrase in phrases:
            cleaned = re.sub(r"\s+", " ", str(phrase or "")).strip()
            if len(cleaned) < 4:
                continue
            key = cleaned.lower()
            counts[key] = counts.get(key, 0) + 1
    notes: list[dict] = []
    for phrase, count in counts.items():
        if count < 2:
            continue
        text = f"Phrasing he types: \"{phrase}\" (seen {count} times)."
        notes.append(
            _make_note(
                kind="vocabulary",
                text=text,
                confidence=min(0.88, 0.5 + 0.1 * count),
                topics=[phrase],
            )
        )
    return notes


def render_digest_section(notes: list[dict], *, day: str) -> str:
    lines = [
        "## What I learned about you",
        "",
        f"Day {day}. Local notes only. Heirs do not see clips or rejected items.",
        "",
    ]
    if not notes:
        lines.append("Nothing new.")
        lines.append("")
        return "\n".join(lines)
    for note in notes:
        status = note.get("status") or "pending"
        kind = note.get("kind") or "note"
        confidence = float(note.get("confidence") or 0)
        lines.append(f"- [{status}] ({kind}, {confidence:.2f}) {note.get('text') or ''}")
    lines.append("")
    return "\n".join(lines)
