"""Local presence files. Embeddings and one thumbnail per person. Never a video."""
from __future__ import annotations

import base64
import json
import os
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from presence_match import present_people
from presence_models import DEFAULT_THRESHOLD

_ON = frozenset({"1", "true", "yes", "on"})
DEFAULT_DIR = "/var/lib/heirloom/presence"
UNKNOWN_TTL = timedelta(hours=24)
INBOX_TTL = timedelta(minutes=15)
JOB_TTL = timedelta(seconds=45)
MAX_THUMB_BYTES = 48 * 1024
MAX_EMBEDDING = 1024
MIN_EMBEDDING = 32
JPEG_MAGIC = b"\xff\xd8\xff"


def _flag(name: str, raw: Optional[str] = None) -> bool:
    if raw is None:
        raw = os.environ.get(name, "")
    return (raw or "").strip().lower() in _ON


def presence_enabled(raw: Optional[str] = None) -> bool:
    return _flag("HEIRLOOM_PRESENCE", raw)


def presence_dir(raw: Optional[str] = None) -> Path:
    if raw is None:
        raw = os.environ.get("HEIRLOOM_PRESENCE_DIR", DEFAULT_DIR)
    text = (raw or "").strip() or DEFAULT_DIR
    return Path(text)


def _now(now: Optional[datetime] = None) -> datetime:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _iso(now: Optional[datetime] = None) -> str:
    return _now(now).isoformat()


def _parse_iso(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


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


def _new_id(prefix: str) -> str:
    return prefix + uuid.uuid4().hex[:12]


def clean_embedding(raw: list) -> list[float]:
    if not isinstance(raw, list) or not MIN_EMBEDDING <= len(raw) <= MAX_EMBEDDING:
        raise ValueError("Embedding length is not usable")
    values: list[float] = []
    for item in raw:
        try:
            number = float(item)
        except (TypeError, ValueError) as exc:
            raise ValueError("Embedding values must be numbers") from exc
        if number != number or number in {float("inf"), float("-inf")}:
            raise ValueError("Embedding values must be finite")
        values.append(number)
    return values


def accept_jpeg(blob: bytes) -> bytes:
    if not blob or not blob.startswith(JPEG_MAGIC):
        raise ValueError("Thumbnail must be a JPEG")
    if len(blob) > MAX_THUMB_BYTES:
        raise ValueError("Thumbnail is too large")
    return blob


def default_settings() -> dict:
    return {
        "threshold": DEFAULT_THRESHOLD,
        "debounce_minutes": 10,
        "depart_seconds": 30,
        "unknown_debounce_minutes": 10,
        "unknown_thumbnails": False,
        "quiet_hours": "",
        "sample_fps": 3,
        "motion_threshold": 0.04,
    }


class PresenceStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)

    @property
    def people_root(self) -> Path:
        return self.root / "people"

    @property
    def events_path(self) -> Path:
        return self.root / "events.jsonl"

    @property
    def state_path(self) -> Path:
        return self.root / "state.json"

    @property
    def settings_path(self) -> Path:
        return self.root / "settings.json"

    @property
    def runtime_path(self) -> Path:
        return self.root / "runtime.json"

    @property
    def tracked_path(self) -> Path:
        return self.root / "tracked.json"

    @property
    def jobs_root(self) -> Path:
        return self.root / "jobs"

    @property
    def inbox_root(self) -> Path:
        return self.root / "inbox"

    @property
    def unknown_root(self) -> Path:
        return self.root / "unknown"

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def read_state(self) -> dict:
        loaded = _read_json(self.state_path, {})
        return loaded if isinstance(loaded, dict) else {}

    def write_state(self, state: dict) -> None:
        _write_json(self.state_path, state)

    def set_paused(self, paused: bool, reason: str) -> dict:
        state = self.read_state()
        state["paused"] = bool(paused)
        state["reason"] = reason if paused else ""
        self.write_state(state)
        return state

    def read_settings(self) -> dict:
        loaded = _read_json(self.settings_path, {})
        settings = default_settings()
        if isinstance(loaded, dict):
            settings.update(loaded)
        settings["unknown_thumbnails"] = bool(settings.get("unknown_thumbnails"))
        try:
            settings["threshold"] = float(settings["threshold"])
        except (TypeError, ValueError):
            settings["threshold"] = DEFAULT_THRESHOLD
        return settings

    def write_settings(self, updates: dict) -> dict:
        settings = self.read_settings()
        allowed = {
            "threshold",
            "debounce_minutes",
            "depart_seconds",
            "unknown_debounce_minutes",
            "unknown_thumbnails",
            "quiet_hours",
            "sample_fps",
            "motion_threshold",
        }
        for key, value in updates.items():
            if key not in allowed:
                continue
            settings[key] = value
        if "unknown_thumbnails" in updates:
            settings["unknown_thumbnails"] = bool(updates.get("unknown_thumbnails"))
        try:
            threshold = float(settings["threshold"])
        except (TypeError, ValueError) as exc:
            raise ValueError("Threshold must be a number") from exc
        if not 0.05 <= threshold <= 0.95:
            raise ValueError("Threshold must be between 0.05 and 0.95")
        settings["threshold"] = threshold
        _write_json(self.settings_path, settings)
        return settings

    def read_runtime(self) -> dict:
        loaded = _read_json(self.runtime_path, {})
        return loaded if isinstance(loaded, dict) else {}

    def write_runtime(self, runtime: dict) -> None:
        _write_json(self.runtime_path, runtime)

    def read_tracked(self) -> dict:
        loaded = _read_json(self.tracked_path, {})
        return loaded if isinstance(loaded, dict) else {}

    def write_tracked(self, tracked: dict) -> None:
        _write_json(self.tracked_path, tracked)

    def _person_dir(self, person_id: str) -> Path:
        if not person_id or "/" in person_id or person_id.startswith("."):
            raise ValueError("Unknown person")
        return self.people_root / person_id

    def list_people(self) -> list[dict]:
        if not self.people_root.is_dir():
            return []
        rows: list[dict] = []
        for path in sorted(self.people_root.iterdir()):
            if not path.is_dir():
                continue
            meta = _read_json(path / "meta.json", {})
            if not isinstance(meta, dict) or not meta.get("id"):
                continue
            rows.append(self._public_person(meta, path))
        return rows

    def get_person(self, person_id: str) -> dict:
        path = self._person_dir(person_id)
        meta = _read_json(path / "meta.json", {})
        if not isinstance(meta, dict) or not meta.get("id"):
            raise KeyError(person_id)
        return self._public_person(meta, path)

    def _public_person(self, meta: dict, path: Path) -> dict:
        embeddings = _read_json(path / "embeddings.json", [])
        count = len(embeddings) if isinstance(embeddings, list) else 0
        return {
            "id": meta.get("id") or path.name,
            "name": meta.get("name") or "",
            "relationship": meta.get("relationship") or "",
            "greeting": meta.get("greeting") or "",
            "consent": bool(meta.get("consent")),
            "consented_at": meta.get("consented_at") or "",
            "created_at": meta.get("created_at") or "",
            "sample_count": count,
            "has_thumbnail": (path / "thumb.jpg").is_file(),
        }

    def enrolled_vectors(self) -> list[dict]:
        """Matcher input. Callers that answer an heir must not use this."""
        people: list[dict] = []
        for person in self.list_people():
            path = self._person_dir(str(person["id"]))
            embeddings = _read_json(path / "embeddings.json", [])
            if not isinstance(embeddings, list):
                embeddings = []
            people.append({
                "id": person["id"],
                "name": person["name"],
                "relationship": person["relationship"],
                "greeting": person["greeting"],
                "embeddings": [row for row in embeddings if isinstance(row, list)],
            })
        return people

    def create_person(
        self,
        *,
        name: str,
        relationship: str,
        greeting: str = "",
        consent: bool = False,
        now: Optional[datetime] = None,
    ) -> dict:
        who = (name or "").strip()
        if not who or len(who) > 80:
            raise ValueError("Name is required")
        if not consent:
            raise ValueError("Consent is required before a person is saved")
        relation = (relationship or "").strip()
        if not relation or len(relation) > 40:
            raise ValueError("Relationship is required")
        hello = (greeting or "").strip()
        if len(hello) > 200:
            raise ValueError("Greeting is too long")
        person_id = _new_id("prs_")
        stamp = _iso(now)
        meta = {
            "id": person_id,
            "name": who,
            "relationship": relation,
            "greeting": hello,
            "consent": True,
            "consented_at": stamp,
            "created_at": stamp,
        }
        path = self._person_dir(person_id)
        path.mkdir(parents=True, exist_ok=True)
        _write_json(path / "meta.json", meta)
        _write_json(path / "embeddings.json", [])
        return self._public_person(meta, path)

    def update_person(self, person_id: str, updates: dict) -> dict:
        path = self._person_dir(person_id)
        meta = _read_json(path / "meta.json", {})
        if not isinstance(meta, dict) or not meta.get("id"):
            raise KeyError(person_id)
        if "name" in updates:
            who = str(updates.get("name") or "").strip()
            if not who or len(who) > 80:
                raise ValueError("Name is required")
            meta["name"] = who
        if "relationship" in updates:
            relation = str(updates.get("relationship") or "").strip()
            if not relation or len(relation) > 40:
                raise ValueError("Relationship is required")
            meta["relationship"] = relation
        if "greeting" in updates:
            hello = str(updates.get("greeting") or "").strip()
            if len(hello) > 200:
                raise ValueError("Greeting is too long")
            meta["greeting"] = hello
        _write_json(path / "meta.json", meta)
        tracked = self.read_tracked()
        row = tracked.get(person_id)
        if isinstance(row, dict):
            row["name"] = meta.get("name") or ""
            row["relationship"] = meta.get("relationship") or ""
            tracked[person_id] = row
            self.write_tracked(tracked)
        return self._public_person(meta, path)

    def delete_person(self, person_id: str) -> None:
        path = self._person_dir(person_id)
        if not (path / "meta.json").is_file():
            raise KeyError(person_id)
        shutil.rmtree(path)
        tracked = self.read_tracked()
        if person_id in tracked:
            tracked.pop(person_id, None)
            self.write_tracked(tracked)

    def add_sample(self, person_id: str, embedding: list, thumb: bytes | None = None) -> dict:
        path = self._person_dir(person_id)
        meta = _read_json(path / "meta.json", {})
        if not isinstance(meta, dict) or not meta.get("consent"):
            raise KeyError(person_id)
        vector = clean_embedding(embedding)
        current = _read_json(path / "embeddings.json", [])
        if not isinstance(current, list):
            current = []
        if current and isinstance(current[0], list) and len(current[0]) != len(vector):
            raise ValueError("Embedding length does not match this person")
        current.append(vector)
        _write_json(path / "embeddings.json", current)
        if thumb:
            jpeg = accept_jpeg(thumb)
            thumb_path = path / "thumb.jpg"
            tmp = thumb_path.with_suffix(".jpg.tmp")
            tmp.write_bytes(jpeg)
            tmp.replace(thumb_path)
        return self._public_person(meta, path)

    def forget_everyone(self, now: Optional[datetime] = None) -> dict:
        """Delete every embedding, thumbnail, and unknown review image."""
        if self.people_root.exists():
            shutil.rmtree(self.people_root)
        if self.unknown_root.exists():
            shutil.rmtree(self.unknown_root)
        if self.inbox_root.exists():
            shutil.rmtree(self.inbox_root)
        preview = self.root / "preview.jpg"
        if preview.is_file():
            preview.unlink()
        self.write_tracked({})
        if self.events_path.is_file():
            self.events_path.unlink()
        _append_jsonl(self.events_path, {"ts": _iso(now), "kind": "forget"})
        return {"forgotten": True}

    def append_events(self, events: list[dict]) -> None:
        for event in events:
            kind = str(event.get("kind") or "")
            if kind == "unrecognized":
                _append_jsonl(self.events_path, {"ts": event.get("ts") or _iso(), "kind": "unrecognized"})
                continue
            if kind not in {"arrival", "departure", "greeting", "forget"}:
                continue
            row = {
                "ts": event.get("ts") or _iso(),
                "kind": kind,
                "person_id": str(event.get("person_id") or ""),
                "name": str(event.get("name") or ""),
                "greeted": bool(event.get("greeted")),
            }
            if kind == "greeting":
                row["text"] = str(event.get("text") or "")[:200]
            _append_jsonl(self.events_path, row)

    def read_events(self, limit: int = 50) -> list[dict]:
        rows = _read_jsonl(self.events_path)
        if limit > 0:
            rows = rows[-limit:]
        public: list[dict] = []
        for row in rows:
            kind = str(row.get("kind") or "")
            if kind == "unrecognized":
                public.append({"ts": row.get("ts") or "", "kind": "unrecognized"})
            else:
                item = {
                    "ts": row.get("ts") or "",
                    "kind": kind,
                    "person_id": row.get("person_id") or "",
                    "name": row.get("name") or "",
                    "greeted": bool(row.get("greeted")),
                }
                if row.get("text"):
                    item["text"] = row.get("text")
                public.append(item)
        return public

    def save_unknown_thumb(self, stamp: str, blob: bytes) -> None:
        if not self.read_settings().get("unknown_thumbnails"):
            return
        jpeg = accept_jpeg(blob)
        safe = "".join(ch if ch.isalnum() or ch in "T:-" else "-" for ch in stamp)[:40]
        path = self.unknown_root / f"{safe}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".jpg.tmp")
        tmp.write_bytes(jpeg)
        tmp.replace(path)

    def purge_unknown(self, now: Optional[datetime] = None) -> int:
        if not self.unknown_root.is_dir():
            return 0
        moment = _now(now)
        removed = 0
        for path in list(self.unknown_root.glob("*.jpg")):
            try:
                mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
            if moment - mtime >= UNKNOWN_TTL:
                path.unlink(missing_ok=True)
                removed += 1
        return removed

    def list_unknown(self) -> list[dict]:
        if not self.unknown_root.is_dir():
            return []
        rows = []
        for path in sorted(self.unknown_root.glob("*.jpg")):
            rows.append({"ts": path.stem, "has_thumbnail": True})
        return rows

    def unknown_thumb_path(self, stamp: str) -> Path:
        safe = Path(stamp).name
        path = self.unknown_root / f"{safe}.jpg"
        if not path.is_file():
            raise KeyError(stamp)
        return path

    def thumb_path(self, person_id: str) -> Path:
        path = self._person_dir(person_id) / "thumb.jpg"
        if not path.is_file():
            raise KeyError(person_id)
        return path

    def enqueue(self, kind: str, *, person_id: str = "", photo: bytes | None = None, now: Optional[datetime] = None) -> dict:
        if kind not in {"capture", "photo", "test"}:
            raise ValueError("Unknown capture job")
        if kind in {"capture", "photo"}:
            self.get_person(person_id)
        job_id = _new_id("job_")
        if photo is not None:
            if not photo.startswith(JPEG_MAGIC):
                raise ValueError("Photo must be a JPEG")
            if len(photo) > 2 * 1024 * 1024:
                raise ValueError("Photo is too large")
            self.inbox_root.mkdir(parents=True, exist_ok=True)
            inbox = self.inbox_root / f"{job_id}.jpg"
            tmp = inbox.with_suffix(".jpg.tmp")
            tmp.write_bytes(photo)
            tmp.replace(inbox)
        job = {
            "id": job_id,
            "kind": kind,
            "person_id": person_id,
            "status": "pending",
            "created_at": _iso(now),
            "result": {},
            "error": "",
        }
        _write_json(self.jobs_root / f"{job_id}.json", job)
        return job

    def get_job(self, job_id: str) -> dict:
        if not job_id or "/" in job_id or job_id.startswith("."):
            raise KeyError(job_id)
        loaded = _read_json(self.jobs_root / f"{job_id}.json", {})
        if not isinstance(loaded, dict) or not loaded.get("id"):
            raise KeyError(job_id)
        return loaded

    def pending_jobs(self) -> list[dict]:
        if not self.jobs_root.is_dir():
            return []
        rows = []
        for path in sorted(self.jobs_root.glob("*.json")):
            loaded = _read_json(path, {})
            if isinstance(loaded, dict) and loaded.get("status") == "pending":
                rows.append(loaded)
        return rows

    def finish_job(self, job_id: str, result: dict) -> dict:
        job = self.get_job(job_id)
        job["status"] = "done"
        job["result"] = result
        job["error"] = ""
        _write_json(self.jobs_root / f"{job_id}.json", job)
        inbox = self.inbox_root / f"{job_id}.jpg"
        inbox.unlink(missing_ok=True)
        return job

    def fail_job(self, job_id: str, error: str) -> dict:
        job = self.get_job(job_id)
        job["status"] = "failed"
        job["error"] = error[:200]
        _write_json(self.jobs_root / f"{job_id}.json", job)
        inbox = self.inbox_root / f"{job_id}.jpg"
        inbox.unlink(missing_ok=True)
        return job

    def expire_jobs(self, now: Optional[datetime] = None) -> int:
        moment = _now(now)
        expired = 0
        for job in self.pending_jobs():
            created = _parse_iso(str(job.get("created_at") or ""))
            if created is None or moment - created < JOB_TTL:
                continue
            self.fail_job(str(job["id"]), "camera service did not answer")
            expired += 1
        if self.inbox_root.is_dir():
            for path in list(self.inbox_root.glob("*.jpg")):
                try:
                    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                except OSError:
                    continue
                if moment - mtime >= INBOX_TTL:
                    path.unlink(missing_ok=True)
        return expired

    def apply_step(self, result: Any) -> None:
        self.write_tracked(result.tracked)
        self.append_events(result.events)
        for greeting in result.greetings:
            self.append_events([{
                "ts": greeting.get("ts"),
                "kind": "greeting",
                "person_id": greeting.get("person_id") or "",
                "name": greeting.get("name") or "",
                "text": greeting.get("text") or "",
                "greeted": True,
            }])
        for stamp, blob in result.unknown_thumbs:
            try:
                self.save_unknown_thumb(stamp, blob)
            except ValueError:
                continue

    def owner_names(self) -> list[str]:
        names = []
        for person in self.list_people():
            if str(person.get("relationship") or "").strip().lower() == "owner":
                names.append(str(person.get("name") or ""))
        return names


def room_for_assignments(store: Optional[PresenceStore] = None) -> dict | None:
    """None when Presence is off, so assignments are not held on a normal install."""
    if not presence_enabled():
        return None
    active = store or PresenceStore(presence_dir())
    status = status_public(active)
    return {
        "present_names": [str(row.get("name") or "") for row in status.get("present") or []],
        "owner_names": list(status.get("owner_names") or []),
    }


def decode_photo(raw: str) -> bytes:
    text = (raw or "").strip()
    if text.startswith("data:"):
        _, _, text = text.partition(",")
    try:
        blob = base64.b64decode(text, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Photo is not valid base64") from exc
    if not blob.startswith(JPEG_MAGIC):
        raise ValueError("Photo must be a JPEG")
    if len(blob) > 2 * 1024 * 1024:
        raise ValueError("Photo is too large")
    return blob


def status_public(store: Optional[PresenceStore] = None) -> dict:
    """Shape used by ``GET /api/health`` and ``heirloom-box status``. No embeddings."""
    enabled = presence_enabled()
    empty = {
        "enabled": False,
        "paused": False,
        "pause_reason": "",
        "cameras": [],
        "fps": 0,
        "enrolled": 0,
        "present": [],
        "owner_names": [],
        "model": "",
        "backend": "",
        "unknown_thumbnails": False,
    }
    if not enabled:
        return empty
    active = store or PresenceStore(presence_dir())
    try:
        active.purge_unknown()
        active.expire_jobs()
        state = active.read_state()
        runtime = active.read_runtime()
        settings = active.read_settings()
        people = active.list_people()
        present = present_people(active.read_tracked())
        owners = active.owner_names()
    except OSError:
        return {**empty, "enabled": True}
    from box_pause import read_pause

    shared = read_pause()
    paused = bool(state.get("paused")) or bool(runtime.get("paused")) or bool(shared.get("paused"))
    reason = str(state.get("reason") or runtime.get("pause_reason") or shared.get("reason") or "")
    cameras = runtime.get("cameras") if isinstance(runtime.get("cameras"), list) else []
    return {
        "enabled": True,
        "paused": paused,
        "pause_reason": reason if paused else "",
        "cameras": cameras,
        "fps": runtime.get("fps") or 0,
        "enrolled": len(people),
        "present": present,
        "owner_names": owners,
        "model": str(runtime.get("model") or ""),
        "backend": str(runtime.get("backend") or ""),
        "unknown_thumbnails": bool(settings.get("unknown_thumbnails")),
        "threshold": settings.get("threshold"),
        "debounce_minutes": settings.get("debounce_minutes"),
        "quiet_hours": settings.get("quiet_hours") or "",
    }
