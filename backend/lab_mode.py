"""Owner-only lab mode for the Twin Box.

Off unless ``HEIRLOOM_LAB_MODE=1``. Telemetry and usefulness reports stay on
local disk. Heirs, callers, and the heir surface never enter. Nothing here
relaxes approvals.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from owner_pairing import is_owner_audience

_ON = frozenset({"1", "true", "yes", "on"})
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_VOTES = frozenset({"up", "down"})

DEFAULT_LAB_DIR = "/var/lib/heirloom/lab"
DEFAULT_REPORT_DIR = "/var/lib/heirloom/lab-reports"


def _flag(name: str, raw: Optional[str] = None) -> bool:
    if raw is None:
        raw = os.environ.get(name, "")
    return (raw or "").strip().lower() in _ON


def lab_mode_enabled(raw: Optional[str] = None) -> bool:
    return _flag("HEIRLOOM_LAB_MODE", raw)


def box_mode_enabled(raw: Optional[str] = None) -> bool:
    return _flag("HEIRLOOM_BOX", raw)


def lab_allowed(
    *,
    audience: Optional[str],
    heir_surface: bool = False,
    enabled: Optional[bool] = None,
) -> bool:
    """Heirs and callers never see lab mode, even when the process flag is on."""
    if enabled is None:
        enabled = lab_mode_enabled()
    if not enabled or heir_surface:
        return False
    return is_owner_audience(audience)


def lab_dir(raw: Optional[str] = None) -> Path:
    if raw is None:
        raw = os.environ.get("HEIRLOOM_LAB_DIR", DEFAULT_LAB_DIR)
    text = (raw or "").strip() or DEFAULT_LAB_DIR
    return Path(text)


def report_dir(raw: Optional[str] = None) -> Path:
    if raw is None:
        raw = os.environ.get("HEIRLOOM_LAB_REPORT_DIR", DEFAULT_REPORT_DIR)
    text = (raw or "").strip() or DEFAULT_REPORT_DIR
    return Path(text)


def _now_iso(now: Optional[datetime] = None) -> str:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


def _day(now: Optional[datetime] = None) -> str:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).date().isoformat()


class LabStore:
    """Append-only JSONL on disk. No Mongo, no network."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.turns_path = self.root / "turns.jsonl"

    def append(self, record: Mapping[str, Any]) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        turn_id = str(record.get("turn_id") or f"lab_{uuid.uuid4().hex[:16]}")
        row = dict(record)
        row["turn_id"] = turn_id
        with self.turns_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n")
        return turn_id

    def read_all(self) -> list[dict[str, Any]]:
        if not self.turns_path.is_file():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.turns_path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                loaded = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(loaded, dict):
                rows.append(loaded)
        return rows

    def set_feedback(self, turn_id: str, vote: str, note: str = "") -> dict[str, Any]:
        key = (vote or "").strip().lower()
        if key not in _VOTES:
            raise ValueError("vote must be up or down")
        cleaned = (note or "").strip()[:500]
        rows = self.read_all()
        found: Optional[dict[str, Any]] = None
        for row in rows:
            if row.get("turn_id") == turn_id:
                row["feedback"] = {"vote": key, "note": cleaned}
                found = row
                break
        if found is None:
            raise KeyError(turn_id)
        self._rewrite(rows)
        return found

    def _rewrite(self, rows: list[dict[str, Any]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = "".join(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n" for row in rows)
        tmp = self.turns_path.with_suffix(".jsonl.tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(self.turns_path)


def default_store() -> LabStore:
    return LabStore(lab_dir())


def record_chat_turn(
    *,
    route: str,
    latency_ms: Optional[int] = None,
    model: str = "",
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
    approvals_created: int = 0,
    approvals_approved: int = 0,
    approvals_declined: int = 0,
    error: Optional[str] = None,
    audience: Optional[str] = "owner",
    heir_surface: bool = False,
    user_id: str = "",
    store: Optional[LabStore] = None,
    now: Optional[datetime] = None,
) -> Optional[str]:
    """Write one local telemetry row. Returns None when lab mode does not apply.

    Message text is not stored. A disk error must not break the chat.
    """
    if not lab_allowed(audience=audience, heir_surface=heir_surface):
        return None
    target = store or default_store()
    record = {
        "turn_id": f"lab_{uuid.uuid4().hex[:16]}",
        "ts": _now_iso(now),
        "route": (route or "unknown").strip().lower()[:40] or "unknown",
        "latency_ms": latency_ms,
        "model": (model or "")[:120],
        "tokens": {
            "prompt": prompt_tokens,
            "completion": completion_tokens,
        },
        "approvals_created": int(approvals_created or 0),
        "approvals_approved": int(approvals_approved or 0),
        "approvals_declined": int(approvals_declined or 0),
        "error": (error or "")[:300] or None,
        "user_id": (user_id or "")[:80],
        "feedback": None,
    }
    try:
        return target.append(record)
    except OSError:
        return None


def summarize_turns(turns: list[Mapping[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "turns": 0,
        "up": 0,
        "down": 0,
        "errors": 0,
        "approvals_created": 0,
        "approvals_approved": 0,
        "approvals_declined": 0,
        "by_route": {},
    }
    routes: dict[str, int] = {}
    for row in turns:
        summary["turns"] += 1
        route = str(row.get("route") or "unknown")
        routes[route] = routes.get(route, 0) + 1
        feedback = row.get("feedback") if isinstance(row.get("feedback"), Mapping) else {}
        vote = str(feedback.get("vote") or "")
        if vote == "up":
            summary["up"] += 1
        elif vote == "down":
            summary["down"] += 1
        if row.get("error"):
            summary["errors"] += 1
        summary["approvals_created"] += int(row.get("approvals_created") or 0)
        summary["approvals_approved"] += int(row.get("approvals_approved") or 0)
        summary["approvals_declined"] += int(row.get("approvals_declined") or 0)
    summary["by_route"] = routes
    return summary


def render_report(
    turns: list[Mapping[str, Any]],
    *,
    day: str,
    observer_markdown: str = "",
) -> str:
    """Local markdown. No transcripts."""
    summary = summarize_turns(turns)
    lines = [
        f"# Heirloom lab report — {day}",
        "",
        "Local only. This file stays on the box.",
        "",
        "## Counts",
        f"- Turns: {summary['turns']}",
        f"- Useful: {summary['up']}",
        f"- Not useful: {summary['down']}",
        f"- Errors: {summary['errors']}",
        (
            "- Approvals created / approved / declined: "
            f"{summary['approvals_created']} / {summary['approvals_approved']} / {summary['approvals_declined']}"
        ),
        "",
        "## By route",
    ]
    routes = summary["by_route"]
    if not routes:
        lines.append("- (none)")
    else:
        for name in sorted(routes):
            lines.append(f"- {name}: {routes[name]}")
    lines.extend(["", "## Errors"])
    errors = 0
    for row in turns:
        err = str(row.get("error") or "").strip()
        if not err:
            continue
        errors += 1
        lines.append(f"- {row.get('route') or 'unknown'}: {err}")
    if errors == 0:
        lines.append("- (none)")
    lines.extend(["", "## Notes"])
    notes = 0
    for row in turns:
        feedback = row.get("feedback") if isinstance(row.get("feedback"), Mapping) else None
        if not feedback:
            continue
        note = str(feedback.get("note") or "").strip()
        if not note:
            continue
        notes += 1
        vote = str(feedback.get("vote") or "")
        lines.append(f"- {vote} ({row.get('route') or 'unknown'}): {note}")
    if notes == 0:
        lines.append("- (none)")
    extra = (observer_markdown or "").strip()
    if extra:
        lines.extend(["", extra])
    lines.append("")
    return "\n".join(lines)


def write_report(
    turns: list[Mapping[str, Any]],
    dest: Path,
    *,
    day: Optional[str] = None,
    keep: int = 30,
    observer_markdown: str = "",
) -> Path:
    folder = Path(dest)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = day or _day()
    path = folder / f"lab-report-{stamp}.md"
    path.write_text(
        render_report(turns, day=stamp, observer_markdown=observer_markdown),
        encoding="utf-8",
    )
    _rotate(folder, keep=keep)
    return path


def _rotate(folder: Path, *, keep: int) -> None:
    files = sorted(folder.glob("lab-report-*.md"))
    extra = len(files) - keep
    if extra <= 0:
        return
    for old in files[:extra]:
        try:
            old.unlink()
        except OSError:
            continue


def github_issue_target(
    *,
    token: Optional[str] = None,
    repo: Optional[str] = None,
) -> Optional[tuple[str, str]]:
    """Return ``(token, repo)`` only when both are set. Default is off."""
    if token is None:
        token = os.environ.get("GITHUB_TOKEN", "")
    if repo is None:
        repo = os.environ.get("HEIRLOOM_LAB_GITHUB_REPO", "")
    tok = (token or "").strip()
    name = (repo or "").strip()
    if not tok or not name or not _REPO.fullmatch(name):
        return None
    return tok, name


def build_github_issue(markdown: str, *, day: str) -> dict[str, Any]:
    return {
        "title": f"Lab report {day}",
        "body": markdown,
        "labels": ["lab-report"],
    }


def file_github_issue(
    markdown: str,
    *,
    token: str,
    repo: str,
    day: str,
    opener: Any = None,
) -> str:
    """POST one issue. ``opener`` is for tests; production uses urllib."""
    issue = build_github_issue(markdown, day=day)
    url = f"https://api.github.com/repos/{repo}/issues"
    data = json.dumps(issue).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "heirloom-twin-box",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    send = opener or urllib.request.urlopen
    try:
        with send(request, timeout=20) as response:
            raw = response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GitHub issue failed: {exc}") from exc
    loaded = json.loads(raw.decode("utf-8") or "{}")
    html = loaded.get("html_url") if isinstance(loaded, dict) else ""
    return str(html or "")


def publish_report(
    store: LabStore,
    dest: Path,
    *,
    now: Optional[datetime] = None,
    token: Optional[str] = None,
    repo: Optional[str] = None,
    opener: Any = None,
) -> dict[str, Any]:
    """Write today's markdown. File a GitHub issue only when token and repo are set."""
    stamp = _day(now)
    digest = ""
    try:
        from observer_prompt import nightly_digest_markdown

        digest = nightly_digest_markdown()
    except OSError:
        digest = ""
    path = write_report(store.read_all(), dest, day=stamp, observer_markdown=digest)
    result: dict[str, Any] = {
        "path": str(path),
        "day": stamp,
        "github": "skipped",
        "detail": "",
    }
    target = github_issue_target(token=token, repo=repo)
    if target is None:
        return result
    tok, name = target
    try:
        url = file_github_issue(path.read_text(encoding="utf-8"), token=tok, repo=name, day=stamp, opener=opener)
    except (RuntimeError, OSError, ValueError) as exc:
        result["github"] = "error"
        result["detail"] = str(exc)[:300]
        return result
    result["github"] = "filed"
    result["detail"] = url
    return result
