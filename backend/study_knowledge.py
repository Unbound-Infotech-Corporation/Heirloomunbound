"""Approved Study Hall lessons for the twin prompt.

Study Hall is a separate app. It publishes one local file the twin can read.
Lessons are research the owner filed. They are not biography, and a missing
file leaves the prompt unchanged. They never satisfy a grounded miss.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

_STOP = {
    "the", "and", "for", "with", "that", "this", "from", "your", "about",
    "into", "what", "when", "where", "which", "have", "has", "was", "were",
    "are", "not", "but", "its", "their", "they", "you", "how", "can", "all",
    "should", "would", "could", "than", "then", "them", "been", "being",
}


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", (value or "").lower())
        if len(token) > 3 and token not in _STOP
    }


def candidate_files() -> list[Path]:
    files: list[Path] = []
    explicit = (os.environ.get("HEIRLOOM_STUDY_KNOWLEDGE") or "").strip()
    if explicit:
        files.append(Path(explicit))
    hall = (os.environ.get("HEIRLOOM_STUDY_HALL") or "").strip()
    if hall:
        files.append(Path(hall) / "knowledge" / "approved.json")
    root = (os.environ.get("HEIRLOOM_DATA_ROOT") or "").strip()
    if root:
        files.append(Path(root) / "study-hall" / "knowledge" / "approved.json")
    files.append(Path("G:/HeirloomStudyHall/data/knowledge/approved.json"))
    files.append(Path.home() / ".heirloom" / "study-hall" / "knowledge" / "approved.json")
    return files


def load_lessons(path: Path | None = None) -> list[dict]:
    chosen = path
    if chosen is None:
        for candidate in candidate_files():
            if candidate.is_file():
                chosen = candidate
                break
    if chosen is None or not chosen.is_file():
        return []
    try:
        loaded = json.loads(chosen.read_text(encoding="utf-8") or "null")
    except (OSError, json.JSONDecodeError, UnicodeError):
        return []
    lessons = loaded.get("lessons") if isinstance(loaded, dict) else None
    if not isinstance(lessons, list):
        return []
    return [row for row in lessons if isinstance(row, dict)]


def _blob(lesson: dict) -> str:
    citations = lesson.get("citations") or []
    titles = " ".join(str(item.get("title") or "") for item in citations if isinstance(item, dict))
    return " ".join([
        str(lesson.get("summary") or ""),
        str(lesson.get("why_it_matters") or ""),
        str(lesson.get("source_title") or ""),
        titles,
    ])


def _relevant(query: str, lessons: list[dict], limit: int = 3) -> list[dict]:
    wanted = _tokens(query)
    if not wanted:
        return []
    scored: list[tuple[int, float, dict]] = []
    for lesson in lessons:
        try:
            confidence = float(lesson.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < 0.35:
            continue
        have = _tokens(_blob(lesson))
        shared = wanted & have
        if len(shared) < 2 and not any(len(token) >= 8 for token in shared):
            continue
        scored.append((len(shared), confidence, lesson))
    scored.sort(key=lambda item: (-item[0], -item[1]))
    return [lesson for _overlap, _confidence, lesson in scored[:limit]]


def study_prompt_block(query: str, *, path: Path | None = None) -> str:
    """Cited research for this turn, or an empty string when nothing applies."""
    try:
        picked = _relevant(query, load_lessons(path))
    except OSError:
        return ""
    if not picked:
        return ""
    lines = [
        "APPROVED STUDY (research the owner filed in Study Hall. Lower priority than CORE, "
        "STABLE FACTS, and PASSAGES. This is not their life and not something they said. "
        "Never recite it as biography. If you use it, name the source.):"
    ]
    for lesson in picked:
        summary = " ".join(str(lesson.get("summary") or "").split())[:600]
        why = " ".join(str(lesson.get("why_it_matters") or "").split())[:300]
        title = str(lesson.get("source_title") or "Untitled")
        url = str(lesson.get("source_url") or "")
        try:
            confidence = float(lesson.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        engine = " practice panel" if lesson.get("engine") == "practice" else ""
        lines.append(
            f"- [{confidence:.2f}{engine}] {summary} {why} (Source: {title}, {url})"
        )
    return "\n".join(lines)


def attach_study_to_prompt(system: str, query: str, *, path: Path | None = None) -> str:
    block = study_prompt_block(query, path=path)
    if not block:
        return system
    return system.rstrip() + "\n\n" + block
