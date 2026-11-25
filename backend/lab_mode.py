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


def turns_on_day(turns: list[Mapping[str, Any]], day: str) -> list[Mapping[str, Any]]:
    """Rows whose timestamp is that calendar day. Undated rows are not counted as today."""
    stamp = (day or "").strip()[:10]
    picked: list[Mapping[str, Any]] = []
    for row in turns:
        ts = str(row.get("ts") or "")[:10]
        if stamp and ts == stamp:
            picked.append(row)
    return picked


def _count_lines(summary: dict[str, Any], *, failed: int) -> list[str]:
    return [
        f"- Turns: {summary['turns']}",
        f"- Useful: {summary['up']}",
        f"- Not useful: {summary['down']}",
        f"- Failed replies: {failed}",
        (
            "- Approvals created / approved / declined: "
            f"{summary['approvals_created']} / {summary['approvals_approved']} / {summary['approvals_declined']}"
        ),
    ]


def render_report(
    turns: list[Mapping[str, Any]],
    *,
    day: str,
    observer_markdown: str = "",
    extras: Optional[Mapping[str, Any]] = None,
) -> str:
    """Local markdown. Today is that calendar day. All-time is labeled as all-time."""
    today_rows = turns_on_day(list(turns), day)
    today = summarize_turns(today_rows)
    everything = summarize_turns(list(turns))
    extra = dict(extras or {})
    lines = [
        f"# Heirloom lab report — {day}",
        "",
        "Local only. This file stays on the box.",
        "",
        "## Today",
        *_count_lines(today, failed=today["errors"]),
        f"- New memories: {int(extra.get('memories_today') or 0)}",
        f"- Conversations: {int(extra.get('conversations_today') or 0)}",
        f"- Observer cards: {int(extra.get('observer_cards_today') or 0)}",
        f"- Unanswered prompts: {int(extra.get('unanswered_prompts') or 0)}",
        "",
        "## All-time",
        "These totals are everything on the box, not what happened today.",
        *_count_lines(everything, failed=everything["errors"]),
        f"- Memories: {int(extra.get('memories_all') or 0)}",
        f"- Conversations: {int(extra.get('conversations_all') or 0)}",
        f"- Observer cards: {int(extra.get('observer_cards_all') or 0)}",
        "",
        "## By route (today)",
    ]
    routes = today["by_route"]
    if not routes:
        lines.append("- (none)")
    else:
        for name in sorted(routes):
            lines.append(f"- {name}: {routes[name]}")
    lines.extend(["", "## Errors (today)"])
    errors = 0
    for row in today_rows:
        err = str(row.get("error") or "").strip()
        if not err:
            continue
        errors += 1
        lines.append(f"- {row.get('route') or 'unknown'}: {err}")
    if errors == 0:
        lines.append("- (none)")
    lines.extend(["", "## Notes (today)"])
    notes = 0
    for row in today_rows:
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
    digest = (observer_markdown or "").strip()
    if digest:
        lines.extend(["", digest])
    lines.append("")
    return "\n".join(lines)


def write_report(
    turns: list[Mapping[str, Any]],
    dest: Path,
    *,
    day: Optional[str] = None,
    keep: int = 30,
    observer_markdown: str = "",
    extras: Optional[Mapping[str, Any]] = None,
) -> Path:
    folder = Path(dest)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = day or _day()
    path = folder / f"lab-report-{stamp}.md"
    path.write_text(
        render_report(turns, day=stamp, observer_markdown=observer_markdown, extras=extras),
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


def _match_count(row: Mapping[str, Any], query: Mapping[str, Any]) -> bool:
    for key, expected in query.items():
        value = row.get(key)
        if isinstance(expected, Mapping) and "$regex" in expected:
            prefix = str(expected["$regex"])
            if prefix.startswith("^"):
                prefix = prefix[1:]
            if not str(value or "").startswith(prefix):
                return False
        elif value != expected:
            return False
    return True


class _CountDB:
    """Tiny stand-in so report counts can be tested without Mongo."""

    def __init__(self, tables: Mapping[str, list[Mapping[str, Any]]]) -> None:
        self.tables = tables

    def __getitem__(self, name: str) -> "_CountDB":
        self._name = name
        return self

    def count_documents(self, query: Mapping[str, Any]) -> int:
        rows = self.tables.get(getattr(self, "_name", ""), [])
        return sum(1 for row in rows if _match_count(row, query))


def activity_counts(day: str, db: Any = None) -> dict[str, int]:
    """Vault memories, conversations, and unanswered prompts for one day.

    Approved memory cards are also vault entries, so entries are the count.
    Cards fill in only when the entry write did not happen.
    """
    database = db if db is not None else _activity_db()
    if database is None:
        return {}

    def n(collection: str, query: Mapping[str, Any]) -> int:
        try:
            return int(database[collection].count_documents(query))
        except (OSError, TypeError, ValueError, AttributeError):
            return 0

    prefix = {"$regex": f"^{day}"}
    memories_today = n("entries", {"type": "memory", "created_at": prefix})
    memories_all = n("entries", {"type": "memory"})
    if memories_all == 0:
        memories_all = n("memory_cards", {"status": "approved"})
        memories_today = n("memory_cards", {"status": "approved", "approved_at": prefix})
    return {
        "memories_today": memories_today,
        "memories_all": memories_all,
        "conversations_today": n("conversations", {"created_at": prefix}),
        "conversations_all": n("conversations", {}),
        "unanswered_prompts": n("daily_prompts", {"status": "unanswered"}),
    }


def _activity_db() -> Any:
    url = (os.environ.get("MONGO_URL") or "").strip()
    if not url:
        return None
    try:
        from pymongo import MongoClient

        client = MongoClient(url, serverSelectionTimeoutMS=400)
        client.admin.command("ping")
    except Exception:
        return None
    name = (os.environ.get("DB_NAME") or "heirloom").strip() or "heirloom"
    return client[name]


def publish_report(
    store: LabStore,
    dest: Path,
    *,
    now: Optional[datetime] = None,
    token: Optional[str] = None,
    repo: Optional[str] = None,
    opener: Any = None,
    extras: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Write today's markdown. File a GitHub issue only when token and repo are set."""
    stamp = _day(now)
    digest = ""
    try:
        from observer_prompt import nightly_digest_markdown

        digest = nightly_digest_markdown()
    except OSError:
        digest = ""
    counts = dict(extras or {})
    try:
        for key, value in activity_counts(stamp).items():
            counts.setdefault(key, value)
    except OSError:
        pass
    try:
        from observer_store import ObserverStore, observer_dir

        notes = ObserverStore(observer_dir()).read_notes()
        counts.setdefault("observer_cards_all", len(notes))
        counts.setdefault(
            "observer_cards_today",
            sum(1 for note in notes if str(note.get("created_at") or "")[:10] == stamp),
        )
    except OSError:
        counts.setdefault("observer_cards_all", 0)
        counts.setdefault("observer_cards_today", 0)
    path = write_report(store.read_all(), dest, day=stamp, observer_markdown=digest, extras=counts)
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
