"""Local observer files. Notes and short clips only. Never a raw stream."""
from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from observer_learn import (
    fingerprint,
    jaccard,
    normalize_note_text,
    notes_from_observations,
    render_digest_section,
    habit_identity,
    same_note_text,
    suppressed,
    tokenize,
    transcript_note,
)

logger = logging.getLogger(__name__)
from vr_mode import VR_GAZE_SOURCE

_ON = frozenset({"1", "true", "yes", "on"})
DEFAULT_DIR = "/var/lib/heirloom/observer"
DEFAULT_CAP_BYTES = 512 * 1024 * 1024
DEFAULT_CLIP_TTL_DAYS = 7
DEFAULT_CLIP_MINUTES = 10
HIGH_CONFIDENCE = 0.75
HEARD_TEXT_CAP = 1200
NOTE_HOURLY_CAP = 40
NOTE_DAILY_CAP = 80
PENDING_RETENTION_DAYS = 21
PENDING_KEEP_MAX = 240
_HEARD_PREFIX = 48
_HEARD_JACCARD = 0.82
_rate_warned = False


def _flag(name: str, raw: Optional[str] = None) -> bool:
    if raw is None:
        raw = os.environ.get(name, "")
    return (raw or "").strip().lower() in _ON


def observer_enabled(raw: Optional[str] = None) -> bool:
    return _flag("HEIRLOOM_OBSERVER", raw)


def observer_dir(raw: Optional[str] = None) -> Path:
    if raw is None:
        raw = os.environ.get("HEIRLOOM_OBSERVER_DIR", "")
    text = (raw or "").strip()
    if not text:
        from box_pause import data_root

        text = str(data_root() / "observer")
    return Path(text)


def _now(now: Optional[datetime] = None) -> datetime:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _day(now: Optional[datetime] = None) -> str:
    return _now(now).date().isoformat()


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.is_file():
        return fallback
    try:
        loaded = json.loads(path.read_text(encoding="utf-8") or "null")
    except (OSError, json.JSONDecodeError):
        return fallback
    return fallback if loaded is None else loaded


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
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


def _append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n")


def _rewrite_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    body = "".join(json.dumps(row, ensure_ascii=True, sort_keys=True) + "\n" for row in rows)
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(path)


def disk_used(root: Path) -> int:
    total = 0
    if not root.exists():
        return 0
    for path in root.rglob("*"):
        if path.is_file():
            try:
                total += path.stat().st_size
            except OSError:
                continue
    return total


def clips_enabled(raw: Optional[str] = None) -> bool:
    return _flag("OBSERVER_CLIPS", raw)


def clip_max_seconds(raw: Optional[str] = None) -> int:
    if raw is None:
        raw = os.environ.get("OBSERVER_CLIP_MAX_MINUTES_PER_DAY", str(DEFAULT_CLIP_MINUTES))
    try:
        minutes = float(raw or DEFAULT_CLIP_MINUTES)
    except (TypeError, ValueError):
        minutes = float(DEFAULT_CLIP_MINUTES)
    return max(0, int(minutes * 60))


def disk_cap_bytes(raw: Optional[str] = None) -> int:
    if raw is None:
        raw = os.environ.get("OBSERVER_DISK_CAP_BYTES", str(DEFAULT_CAP_BYTES))
    try:
        value = int(raw or DEFAULT_CAP_BYTES)
    except (TypeError, ValueError):
        value = DEFAULT_CAP_BYTES
    return max(0, value)


class ObserverStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.notes_path = self.root / "notes.jsonl"
        self.observations_path = self.root / "observations.jsonl"
        self.suppress_path = self.root / "suppressions.json"
        self.state_path = self.root / "state.json"
        self.status_path = self.root / "status.json"
        self.clips_dir = self.root / "clips"
        self.clip_index = self.clips_dir / "index.jsonl"
        self.digest_dir = self.root / "digests"

    def read_notes(self) -> list[dict]:
        return _read_jsonl(self.notes_path)

    def read_suppressions(self) -> list[dict]:
        loaded = _read_json(self.suppress_path, [])
        return loaded if isinstance(loaded, list) else []

    def read_state(self) -> dict:
        loaded = _read_json(self.state_path, {})
        return loaded if isinstance(loaded, dict) else {}

    def read_status(self) -> dict:
        loaded = _read_json(self.status_path, {})
        return loaded if isinstance(loaded, dict) else {}

    def write_state(self, state: dict) -> None:
        _write_json(self.state_path, state)

    def write_status(self, status: dict) -> None:
        _write_json(self.status_path, status)

    def set_paused(self, paused: bool, reason: str) -> dict:
        state = self.read_state()
        state["paused"] = bool(paused)
        state["reason"] = reason if paused else ""
        if "hotkey_phrase" not in state:
            state["hotkey_phrase"] = os.environ.get("OBSERVER_HOTKEY_PHRASE", "HEIRLOOM PAUSE")
        self.write_state(state)
        return state

    def latch_hotkey(self) -> dict:
        return self.set_paused(True, "hotkey")

    def add_observations(self, rows: list[dict]) -> list[dict]:
        """Append allowed observations and any new notes. Dropped frames are not rows.

        The same sentence is not written again while it is still the recent
        picture. Identical notes are also skipped when the draft is built.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        recent = _read_jsonl(self.observations_path)[-12:]
        for row in rows:
            if row.get("dropped"):
                _append_jsonl(
                    self.observations_path,
                    {
                        "ts": row.get("ts") or _now().isoformat(),
                        "dropped": True,
                        "reason": str(row.get("reason") or "sensitive"),
                        "source": "observer",
                    },
                )
                continue
            text = str(row.get("text") or "")
            activity = str(row.get("activity") or "unknown")
            channel = str(row.get("channel") or "")
            if text and _recent_duplicate(recent, text=text, activity=activity, channel=channel):
                continue
            stored = {
                "ts": row.get("ts") or _now().isoformat(),
                "activity": activity,
                "app": row.get("app") or "",
                "title": row.get("title") or "",
                "game": row.get("game") or "",
                "text": text,
                "owner_phrases": row.get("owner_phrases") or [],
                "scene_delta": row.get("scene_delta") or 0,
                "source": "observer",
                "channel": channel,
                "presence": row.get("presence") or "",
                "presence_note": row.get("presence_note") or "",
                "presence_people": row.get("presence_people") or [],
            }
            _append_jsonl(self.observations_path, stored)
            recent.append(stored)
        return self._generate_notes()

    def add_transcript(self, row: dict) -> dict:
        """Merge one labeled transcript into the timeline and the note memory.

        The text is the transcript. PCM is not written here.
        """
        channel = str(row.get("channel") or "")
        if channel not in {"mic", "system"}:
            return {"stored": False, "reason": "channel"}
        if bool(self.read_state().get("paused")):
            return {"stored": False, "reason": "paused"}
        self.root.mkdir(parents=True, exist_ok=True)
        moment = str(row.get("ts") or _now().isoformat())
        if row.get("dropped"):
            _append_jsonl(
                self.observations_path,
                {
                    "ts": moment,
                    "dropped": True,
                    "reason": str(row.get("reason") or "sensitive"),
                    "source": "observer",
                    "channel": channel,
                    "activity": "speech" if channel == "mic" else "heard",
                },
            )
            return {"stored": False, "reason": str(row.get("reason") or "sensitive")}
        text = str(row.get("text") or "").strip()
        if not text:
            return {"stored": False, "reason": "empty"}
        activity = str(row.get("activity") or ("speech" if channel == "mic" else "heard"))
        recent = _read_jsonl(self.observations_path)[-12:]
        if _recent_duplicate(recent, text=text, activity=activity, channel=channel):
            return {"stored": False, "reason": "duplicate"}
        _append_jsonl(
            self.observations_path,
            {
                "ts": moment,
                "activity": activity,
                "app": "",
                "title": text[:120],
                "game": "",
                "text": text,
                "source": "observer",
                "channel": channel,
                "scene_delta": 0,
            },
        )
        note = transcript_note(channel=channel, text=text, created_at=moment)
        result = self._append_note(note)
        if result.get("reason") == "rate":
            return {"stored": True, "reason": "rate", "note": None}
        return result

    def audio_toggle(self, key: str) -> bool:
        state = self.read_state()
        if key in state:
            return bool(state.get(key))
        return _flag("OBSERVER_AUDIO")

    def set_audio_toggles(self, *, system: Optional[bool] = None, mic: Optional[bool] = None) -> dict:
        state = self.read_state()
        if system is not None:
            state["audio_system"] = bool(system)
        if mic is not None:
            state["audio_mic"] = bool(mic)
        if "hotkey_phrase" not in state:
            state["hotkey_phrase"] = os.environ.get("OBSERVER_HOTKEY_PHRASE", "HEIRLOOM PAUSE")
        self.write_state(state)
        return {"system": self.audio_toggle("audio_system"), "mic": self.audio_toggle("audio_mic")}

    def _generate_notes(self) -> list[dict]:
        existing = self.read_notes()
        known = {row.get("fingerprint") for row in existing}
        created: list[dict] = []
        drafts = notes_from_observations(
            _read_jsonl(self.observations_path),
            suppressions=self.read_suppressions(),
        )
        known_text = {normalize_note_text(str(row.get("text") or "")) for row in existing}
        known_habits = {
            habit_identity(str(row.get("text") or ""))
            for row in existing
            if str(row.get("kind") or "") == "habit"
        }
        for note in drafts:
            folded = normalize_note_text(str(note.get("text") or ""))
            if note.get("kind") == "habit":
                ident = habit_identity(str(note.get("text") or ""))
                if ident and ident in known_habits:
                    continue
            if note["fingerprint"] in known or (folded and folded in known_text):
                continue
            if note.get("kind") == "habit":
                ident = habit_identity(str(note.get("text") or ""))
                if ident:
                    known_habits.add(ident)
            if not note.get("created_at"):
                note["created_at"] = _now().isoformat()
            result = self._append_note(note)
            stored = result.get("note") if isinstance(result.get("note"), dict) else None
            if stored is None:
                continue
            if result.get("reason") == "merged":
                created.append(stored)
                continue
            known.add(stored.get("fingerprint"))
            folded_stored = normalize_note_text(str(stored.get("text") or ""))
            if folded_stored:
                known_text.add(folded_stored)
            if stored.get("kind") == "habit":
                ident = habit_identity(str(stored.get("text") or ""))
                if ident:
                    known_habits.add(ident)
            created.append(stored)
        return created

    def apply_feedback(self, note_id: str, vote: str) -> dict:
        key = (vote or "").strip().lower().replace(" ", "_").replace("'", "")
        aliases = {
            "thats_me": "thats_me",
            "that's_me": "thats_me",
            "me": "thats_me",
            "not_me": "not_me",
            "never": "never",
            "never_learn_this": "never",
        }
        action = aliases.get(key)
        if action is None:
            raise ValueError("vote must be thats_me, not_me, or never")
        notes = self.read_notes()
        found = None
        kept: list[dict] = []
        for note in notes:
            if note.get("id") == note_id:
                found = note
                continue
            kept.append(note)
        if found is None:
            raise KeyError(note_id)
        if action == "thats_me":
            found["status"] = "accepted"
            kept.append(found)
            _rewrite_jsonl(self.notes_path, kept)
            return found
        scope = "never" if action == "never" else "reject"
        self._add_suppression(found, scope)
        _rewrite_jsonl(self.notes_path, kept)
        return {"id": note_id, "removed": True, "scope": scope}

    def _add_suppression(self, note: dict, scope: str) -> None:
        rows = self.read_suppressions()
        rows.append(
            {
                "fingerprint": note.get("fingerprint") or "",
                "tokens": note.get("tokens") or tokenize(str(note.get("text") or "")),
                "kind": note.get("kind") or "",
                "topics": note.get("topics") or [],
                "scope": scope,
                "text": note.get("text") or "",
            }
        )
        _write_json(self.suppress_path, rows)

    def would_suppress(self, note: dict) -> bool:
        return suppressed(note, self.read_suppressions())

    def notes_for_day(self, day: str) -> list[dict]:
        rows = []
        for note in self.read_notes():
            created = str(note.get("created_at") or "")
            if created[:10] == day and note.get("status") != "rejected":
                rows.append(note)
        return rows

    def add_gaze_note(self, note: dict | None) -> dict:
        """Write one attention summary. Refuses a pause and anything that is not a gaze note.

        The stored row is the summary text only. Raw gaze fields on the input are dropped.
        """
        if not isinstance(note, dict) or note.get("source") != VR_GAZE_SOURCE:
            return {"stored": False, "reason": "not-gaze"}
        if bool(self.read_state().get("paused")):
            return {"stored": False, "reason": "paused"}
        stored = {
            "id": str(note.get("id") or ""),
            "source": VR_GAZE_SOURCE,
            "kind": "attention",
            "text": str(note.get("text") or "").strip(),
            "confidence": 0.55,
            "created_at": str(note.get("created_at") or _now().isoformat()),
            "status": "pending",
            "session_id": "",
            "fingerprint": str(note.get("fingerprint") or ""),
            "tokens": list(note.get("tokens") or []),
            "topics": [str(topic) for topic in (note.get("topics") or []) if str(topic)],
        }
        if not stored["text"] or not stored["id"]:
            return {"stored": False, "reason": "empty"}
        if self.would_suppress(stored):
            return {"stored": False, "reason": "suppressed"}
        self.root.mkdir(parents=True, exist_ok=True)
        result = self._append_note(stored)
        if result.get("reason") == "rate":
            return {"stored": False, "reason": "rate"}
        return {"stored": True, "note": result.get("note") or stored}

    def _append_note(self, note: dict) -> dict:
        """Write one note. Heard lines that grow are merged. New notes are rate-limited."""
        prepared = _prepare_stored_note(note)
        existing = self.read_notes()
        if str(prepared.get("kind") or "") == "heard":
            kept, rows, reason = _absorb_heard(existing, prepared)
            if reason == "merged":
                if rows != existing:
                    _rewrite_jsonl(self.notes_path, rows)
                return {"stored": True, "reason": "merged", "note": kept}
        if _note_exists(existing, str(prepared.get("text") or "")):
            return {"stored": True, "reason": "duplicate", "note": None}
        moment = _parse_iso(str(prepared.get("created_at") or "")) or _now()
        if _rate_limited(existing, moment):
            _warn_rate_limit()
            return {"stored": False, "reason": "rate", "note": None}
        if not prepared.get("created_at"):
            prepared["created_at"] = moment.isoformat()
        self.root.mkdir(parents=True, exist_ok=True)
        _append_jsonl(self.notes_path, prepared)
        return {"stored": True, "reason": "", "note": prepared}

    def compact_notes(self, *, now: Optional[datetime] = None) -> dict:
        """Back up ``notes.jsonl``, then dedupe. Accepted notes are never removed.

        A second run that finds nothing to change does not write another backup.
        """
        rows = self.read_notes()
        compacted = compact_note_rows(rows, now=now)
        accepted_ids = {
            str(note.get("id") or "")
            for note in rows
            if str(note.get("status") or "") == "accepted" and note.get("id")
        }
        kept_ids = {
            str(note.get("id") or "")
            for note in compacted
            if str(note.get("status") or "") == "accepted" and note.get("id")
        }
        accepted = sum(1 for note in compacted if str(note.get("status") or "") == "accepted")
        if not accepted_ids <= kept_ids:
            logger.error("observer compact refused to drop accepted notes")
            return {
                "changed": False,
                "before": len(rows),
                "after": len(rows),
                "accepted": sum(1 for note in rows if str(note.get("status") or "") == "accepted"),
                "backup": "",
                "refused": True,
            }
        if compacted == rows:
            return {
                "changed": False,
                "before": len(rows),
                "after": len(rows),
                "accepted": accepted,
                "backup": "",
            }
        backup = ""
        if self.notes_path.is_file():
            stamp = _now().strftime("%Y%m%dT%H%M%SZ")
            dest = self.notes_path.with_name(f"notes.jsonl.{stamp}.bak")
            if dest.exists():
                dest = self.notes_path.with_name(f"notes.jsonl.{stamp}-{uuid.uuid4().hex[:6]}.bak")
            self.notes_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.notes_path, dest)
            backup = str(dest)
        _rewrite_jsonl(self.notes_path, compacted)
        return {
            "changed": True,
            "before": len(rows),
            "after": len(compacted),
            "accepted": accepted,
            "backup": backup,
        }

    def visible_notes(self, *, audience: str, heir_surface: bool = False) -> list[dict]:
        """Heirs see accepted notes only. Owners also see pending. Nobody sees clips here.

        VR gaze notes stay with the owner even after That's me. Heirs are unchanged.
        """
        heir = heir_surface or (audience or "").strip().lower() == "heir"
        rows = []
        for note in self.read_notes():
            status = str(note.get("status") or "")
            if status not in {"accepted", "pending"}:
                continue
            if str(note.get("source") or "") == VR_GAZE_SOURCE and heir:
                continue
            if heir and status != "accepted":
                continue
            rows.append(_public_note(note))
        return rows

    def background_notes(self, *, audience: str, heir_surface: bool = False) -> list[dict]:
        """Accepted notes, plus the owner's high-confidence pending notes."""
        heir = heir_surface or (audience or "").strip().lower() == "heir"
        picked = []
        for note in self.visible_notes(audience=audience, heir_surface=heir_surface):
            if note["status"] == "accepted":
                picked.append(note)
            elif not heir and float(note.get("confidence") or 0) >= HIGH_CONFIDENCE:
                picked.append(note)
        return picked

    def export_for_audience(self, *, audience: str, heir_surface: bool = False) -> dict:
        heir = heir_surface or (audience or "").strip().lower() == "heir"
        return {
            "notes": self.visible_notes(audience=audience, heir_surface=heir_surface),
            "clips": [] if heir else self.clip_records(),
        }

    def clip_records(self) -> list[dict]:
        return _read_jsonl(self.clip_index)

    def clip_seconds_on(self, day: str) -> float:
        total = 0.0
        for row in self.clip_records():
            if str(row.get("day") or "") == day:
                total += float(row.get("seconds") or 0)
        return total

    def admit_clip(
        self,
        *,
        privacy_dropped: bool,
        duration_s: float,
        now: Optional[datetime] = None,
        enabled: Optional[bool] = None,
    ) -> bool:
        if privacy_dropped:
            return False
        if enabled is None:
            enabled = clips_enabled()
        if not enabled:
            return False
        if duration_s <= 0:
            return False
        used = self.clip_seconds_on(_day(now))
        return used + duration_s <= clip_max_seconds()

    def record_clip(self, *, name: str, seconds: float, now: Optional[datetime] = None) -> dict:
        moment = _now(now)
        row = {
            "id": f"clip_{uuid.uuid4().hex[:12]}",
            "name": name,
            "seconds": seconds,
            "day": moment.date().isoformat(),
            "created_at": moment.isoformat(),
            "expires_at": (moment + timedelta(days=clip_ttl_days())).isoformat(),
        }
        _append_jsonl(self.clip_index, row)
        return row

    def prune(
        self,
        *,
        now: Optional[datetime] = None,
        cap_bytes: Optional[int] = None,
        ttl_days: Optional[int] = None,
    ) -> dict:
        """Drop expired clips, then oldest clips, until the tree is under the cap.

        Notes stay. Observations are trimmed only after clips are gone and the
        tree is still over the cap.
        """
        moment = _now(now)
        limit = disk_cap_bytes() if cap_bytes is None else cap_bytes
        ttl = clip_ttl_days() if ttl_days is None else ttl_days
        removed: list[str] = []
        deadline = moment - timedelta(days=ttl)
        records = self.clip_records()
        keep: list[dict] = []
        for row in records:
            created = _parse_iso(str(row.get("created_at") or ""))
            expired = created is not None and created < deadline
            if expired:
                removed.extend(self._delete_clip(row))
                continue
            keep.append(row)
        _rewrite_jsonl(self.clip_index, keep)
        while disk_used(self.root) > limit and keep:
            oldest = keep.pop(0)
            removed.extend(self._delete_clip(oldest))
            _rewrite_jsonl(self.clip_index, keep)
        if disk_used(self.root) > limit:
            self._trim_observations()
            removed.append("observations-trimmed")
        return {"removed": removed, "disk_bytes": disk_used(self.root), "notes": len(self.read_notes())}

    def _delete_clip(self, row: dict) -> list[str]:
        name = str(row.get("name") or "")
        if not name or name in {".", ".."} or "/" in name or "\\" in name:
            return []
        path = self.clips_dir / name
        try:
            if path.is_file():
                path.unlink()
                return [name]
        except OSError:
            return []
        return [name] if not path.exists() else []

    def _trim_observations(self, keep_lines: int = 2000) -> None:
        rows = _read_jsonl(self.observations_path)
        if len(rows) > keep_lines:
            _rewrite_jsonl(self.observations_path, rows[-keep_lines:])

    def digest_notes(self, *, now: Optional[datetime] = None) -> list[dict]:
        return [_public_note(note) for note in self.notes_for_day(_day(now))]

    def digest_section(self, *, now: Optional[datetime] = None) -> str:
        return render_digest_section(self.digest_notes(now=now), day=_day(now))

    def write_digest(self, *, now: Optional[datetime] = None) -> Path:
        self.digest_dir.mkdir(parents=True, exist_ok=True)
        day = _day(now)
        path = self.digest_dir / f"observer-digest-{day}.md"
        path.write_text(self.digest_section(now=now), encoding="utf-8")
        return path


def clip_ttl_days(raw: Optional[str] = None) -> int:
    if raw is None:
        raw = os.environ.get("OBSERVER_CLIP_TTL_DAYS", str(DEFAULT_CLIP_TTL_DAYS))
    try:
        value = int(raw or DEFAULT_CLIP_TTL_DAYS)
    except (TypeError, ValueError):
        value = DEFAULT_CLIP_TTL_DAYS
    return max(1, value)


def _parse_iso(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _public_note(note: dict) -> dict:
    source = str(note.get("source") or "observer")
    if source != VR_GAZE_SOURCE:
        source = "observer"
    return {
        "id": note.get("id") or "",
        "source": source,
        "kind": note.get("kind") or "",
        "text": note.get("text") or "",
        "confidence": note.get("confidence") or 0,
        "created_at": note.get("created_at") or "",
        "status": note.get("status") or "pending",
        "session_id": note.get("session_id") or "",
        "fingerprint": note.get("fingerprint") or "",
        "tokens": note.get("tokens") or [],
        "topics": note.get("topics") or [],
    }


def _screen_mode(raw: Optional[str] = None) -> str:
    """Configured picture source. Kept here so health does not import the spool."""
    if raw is None:
        raw = os.environ.get("OBSERVER_SOURCE", "auto")
    value = (raw or "auto").strip().lower()
    if value in {"network", "capture", "auto"}:
        return value
    return "auto"


def status_public(store: Optional[ObserverStore] = None) -> dict:
    """Shape used by ``GET /api/health`` and ``heirloom-box status``. No secrets."""
    enabled = observer_enabled()
    if store is None:
        store = ObserverStore(observer_dir())
    status = store.read_status() if enabled else {}
    state = store.read_state() if enabled else {}
    from box_pause import read_pause

    shared = read_pause()
    paused = bool(state.get("paused")) or bool(status.get("paused")) or bool(shared.get("paused"))
    try:
        used = disk_used(store.root) if enabled else 0
        notes_today = len(store.notes_for_day(_day())) if enabled else 0
    except OSError:
        used = int(status.get("disk_bytes") or 0)
        notes_today = int(status.get("notes_today") or 0)
    audio = _audio_public(status if enabled else {}, state if enabled else {})
    source = str(status.get("source") or "") if enabled else ""
    recorded_mode = str(status.get("mode") or "")
    mode = ""
    if enabled:
        mode = recorded_mode if recorded_mode in {"network", "capture", "auto"} else _screen_mode()
    return {
        "enabled": enabled,
        "paused": paused if enabled else False,
        "device": str(status.get("device") or ""),
        "source": source,
        "mode": mode,
        "signal": str(status.get("signal") or ("off" if not enabled else "unknown")),
        "fps": status.get("fps") or 0,
        "model": str(status.get("model") or ""),
        "notes_today": notes_today,
        "disk_bytes": used,
        "audio": audio,
    }


def _audio_public(status: dict, state: dict) -> dict:
    """Stream status for ``/api/health``. No PCM and no transcript text."""
    recorded = status.get("audio") if isinstance(status.get("audio"), dict) else {}
    installed = _flag("OBSERVER_AUDIO") or bool(recorded.get("installed"))

    def enabled(key: str, stream: dict) -> bool:
        if key in state:
            return bool(state.get(key))
        if "enabled" in stream:
            return bool(stream.get("enabled"))
        return installed

    def stream(name: str, key: str) -> dict:
        raw = recorded.get(name) if isinstance(recorded.get(name), dict) else {}
        on = enabled(key, raw)
        status_name = str(raw.get("status") or ("off" if not on else "waiting"))
        if not on:
            status_name = "off"
        error = str(raw.get("error") or "").strip()
        if status_name != "error":
            error = ""
        return {
            "enabled": on,
            "source": str(raw.get("source") or "off"),
            "status": status_name,
            "device": str(raw.get("device") or ""),
            "error": error[:160],
        }

    return {
        "installed": installed,
        "transcripts_only": True,
        "model": str(recorded.get("model") or ""),
        "system": stream("system", "audio_system"),
        "mic": stream("mic", "audio_mic"),
    }


def _recent_duplicate(rows: list[dict], *, text: str, activity: str, channel: str) -> bool:
    """Skip a sentence that repeats the latest row of the same stream.

    An alternating pattern (a death, a retry, the same death) stays, so a
    habit can still be counted. A still screen does not write the same note
    again.
    """
    for prev in reversed(rows):
        if str(prev.get("channel") or "") != channel:
            continue
        if str(prev.get("activity") or "") != activity:
            continue
        return same_note_text(str(prev.get("text") or ""), text)
    return False


def clip_stored_text(text: str, limit: int = HEARD_TEXT_CAP) -> str:
    folded = " ".join((text or "").split())
    if len(folded) <= limit:
        return folded
    return folded[: limit - 1].rstrip() + "…"


def heard_related(left: str, right: str) -> bool:
    """True when two heard lines are the same utterance, or one grew from the other."""
    a = normalize_note_text(left)
    b = normalize_note_text(right)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) >= _HEARD_PREFIX and long.startswith(short):
        return True
    return jaccard(tokenize(left), tokenize(right)) >= _HEARD_JACCARD


def _prepare_stored_note(note: dict) -> dict:
    prepared = dict(note)
    if str(prepared.get("kind") or "") != "heard":
        return prepared
    text = clip_stored_text(str(prepared.get("text") or ""))
    prepared["text"] = text
    prepared["tokens"] = tokenize(text)
    prepared["fingerprint"] = fingerprint(text)
    return prepared


def _longer_heard(current: str, proposed: str) -> str:
    if len(normalize_note_text(proposed)) > len(normalize_note_text(current)):
        return proposed
    return current


def _grew_from(current: str, proposed: str) -> bool:
    old = normalize_note_text(current)
    new = normalize_note_text(proposed)
    return bool(old) and len(new) > len(old) and new.startswith(old)


def _with_heard_text(note: dict, text: str) -> dict:
    updated = dict(note)
    updated["text"] = text
    updated["tokens"] = tokenize(text)
    updated["fingerprint"] = fingerprint(text)
    return updated


def _absorb_heard(notes: list[dict], incoming: dict) -> tuple[dict, list[dict], str]:
    """Fold one heard line into an existing heard note. The longest copy is kept.

    An accepted note keeps its id and status. Its text grows only when the new
    line is the same words with more after them.
    """
    for index, note in enumerate(notes):
        if str(note.get("kind") or "") != "heard":
            continue
        if not heard_related(str(note.get("text") or ""), str(incoming.get("text") or "")):
            continue
        current = str(note.get("text") or "")
        proposed = str(incoming.get("text") or "")
        if str(note.get("status") or "") == "accepted" and not _grew_from(current, proposed):
            return note, notes, "merged"
        longer = _longer_heard(current, proposed)
        if longer == current:
            return note, notes, "merged"
        updated = _with_heard_text(note, longer)
        if str(note.get("status") or "") == "accepted":
            updated["status"] = "accepted"
        rows = list(notes)
        rows[index] = updated
        return updated, rows, "merged"
    return incoming, notes, "new"


def _squash_pending_heard(pending: list[dict], accepted: list[dict]) -> tuple[list[dict], list[dict]]:
    accepted_rows = [dict(note) for note in accepted]
    kept: list[dict] = []
    for note in pending:
        if str(note.get("kind") or "") != "heard":
            kept.append(note)
            continue
        prepared = _prepare_stored_note(note)
        matched = False
        for index, prior in enumerate(accepted_rows):
            if str(prior.get("kind") or "") != "heard":
                continue
            if not heard_related(str(prior.get("text") or ""), str(prepared.get("text") or "")):
                continue
            if _grew_from(str(prior.get("text") or ""), str(prepared.get("text") or "")):
                extended = _with_heard_text(prior, str(prepared.get("text") or ""))
                extended["status"] = "accepted"
                accepted_rows[index] = extended
            matched = True
            break
        if matched:
            continue
        _kept_note, rows, reason = _absorb_heard(kept, prepared)
        if reason == "merged":
            kept = rows
            continue
        kept.append(prepared)
    return accepted_rows, kept


def compact_note_rows(rows: list[dict], *, now: Optional[datetime] = None) -> list[dict]:
    """Keep every accepted note. Merge heard copies. Drop old and excess pending notes."""
    moment = _now(now)
    accepted: list[dict] = []
    pending: list[dict] = []
    for note in rows:
        if not isinstance(note, dict):
            continue
        status = str(note.get("status") or "pending").strip().lower()
        if status == "accepted":
            accepted.append(dict(note))
        elif status == "pending":
            pending.append(dict(note))
    accepted, pending = _squash_pending_heard(pending, accepted)
    cutoff = moment - timedelta(days=PENDING_RETENTION_DAYS)
    fresh: list[dict] = []
    for note in pending:
        created = _parse_iso(str(note.get("created_at") or ""))
        if created is not None and created < cutoff:
            continue
        fresh.append(note)
    fresh.sort(key=lambda note: (str(note.get("created_at") or ""), str(note.get("id") or "")))
    if len(fresh) > PENDING_KEEP_MAX:
        fresh = fresh[-PENDING_KEEP_MAX:]
    return accepted + fresh


def _rate_limited(notes: list[dict], moment: datetime) -> bool:
    moment = _now(moment)
    hour_cut = moment - timedelta(hours=1)
    day_cut = moment - timedelta(days=1)
    hour = 0
    day = 0
    slack = timedelta(seconds=1)
    for note in notes:
        created = _parse_iso(str(note.get("created_at") or ""))
        if created is None or created > moment + slack or created < day_cut:
            continue
        day += 1
        if created >= hour_cut:
            hour += 1
    return hour >= NOTE_HOURLY_CAP or day >= NOTE_DAILY_CAP


def _warn_rate_limit() -> None:
    global _rate_warned
    if _rate_warned:
        return
    _rate_warned = True
    logger.warning("observer note rate limit reached; further notes wait for the next window")


def _note_exists(notes: list[dict], text: str) -> bool:
    digest = fingerprint(text)
    folded = normalize_note_text(text)
    for note in notes:
        if note.get("fingerprint") == digest:
            return True
        if folded and normalize_note_text(str(note.get("text") or "")) == folded:
            return True
    return False
