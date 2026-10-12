#!/usr/bin/env python3
"""Heirloom Presence camera loop.

Samples USB webcams at a low rate, runs face recognition only after motion,
and writes embeddings that the owner already asked to keep. Raw frames stay
in memory. Unknown faces are not enrolled.
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from box_pause import merged_state  # noqa: E402
from observer_privacy import pause_decision  # noqa: E402
from presence_match import SeenFace, motion_open, step, touch_present  # noqa: E402
from presence_models import DETECTOR, RECOGNIZER, clamp_fps  # noqa: E402
from presence_speak import speak_greeting  # noqa: E402
from presence_store import PresenceStore, presence_dir, presence_enabled  # noqa: E402
from presence_vision import (  # noqa: E402
    PresenceVisionError,
    faces_from_frame,
    model_label,
    prepare_models,
)

_CAPTURE_TOKENS = ("xr1", "evga", "elgato", "4k60", "cam link", "hdmi")


def list_video_devices(sysfs: Path | None = None) -> list[dict]:
    root = sysfs or Path("/sys/class/video4linux")
    devices: list[dict] = []
    if not root.is_dir():
        return devices
    for node in sorted(root.iterdir()):
        name_path = node / "name"
        index_path = node / "index"
        try:
            name = name_path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            name = ""
        try:
            index = int(index_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            index = 99
        devices.append({"path": f"/dev/{node.name}", "name": name, "index": index})
    return devices


def is_capture_card(name: str) -> bool:
    lowered = (name or "").lower()
    if "metadata" in lowered:
        return True
    return any(token in lowered for token in _CAPTURE_TOKENS)


def observer_device_path() -> str:
    try:
        from observer_store import ObserverStore, observer_dir, observer_enabled

        if not observer_enabled():
            return ""
        status = ObserverStore(observer_dir()).read_status()
    except OSError:
        return ""
    return str(status.get("device") or "")


def pick_webcams(devices: list[dict], *, skip_paths: set[str] | None = None, forced: list[str] | None = None) -> list[dict]:
    """USB webcams. HDMI capture cards belong to Observer."""
    skip = {path for path in (skip_paths or set()) if path}
    if forced:
        chosen = []
        by_path = {str(device.get("path") or ""): device for device in devices}
        for path in forced:
            device = by_path.get(path) or {"path": path, "name": path, "index": 99}
            if is_capture_card(str(device.get("name") or "")):
                continue
            chosen.append(device)
        return chosen
    chosen = []
    for device in devices:
        path = str(device.get("path") or "")
        name = str(device.get("name") or "")
        if not path or path in skip:
            continue
        if is_capture_card(name):
            continue
        chosen.append(device)
    chosen.sort(key=lambda device: int(device.get("index") or 99))
    return chosen


def _quiet_hours(settings: dict) -> str:
    local = str(settings.get("quiet_hours") or os.environ.get("PRESENCE_QUIET_HOURS") or "").strip()
    if local:
        return local
    return os.environ.get("OBSERVER_QUIET_HOURS", "")


def _budget_mib() -> int:
    try:
        return int(os.environ.get("PRESENCE_VRAM_BUDGET_MIB", "512") or "512")
    except ValueError:
        return 512


class CameraPool:
    """Opens each webcam and drops it when a read fails so the next loop reconnects."""

    def __init__(self) -> None:
        self._caps: dict[str, object] = {}
        self._cv2 = None

    def bind(self, cv2_module: object) -> None:
        self._cv2 = cv2_module

    def close(self) -> None:
        for cap in self._caps.values():
            release = getattr(cap, "release", None)
            if release:
                release()
        self._caps.clear()

    def frames(self, devices: list[dict]) -> tuple[list[dict], list[dict]]:
        if self._cv2 is None:
            return [], [{"path": device.get("path") or "", "name": device.get("name") or "", "open": False} for device in devices]
        wanted = {str(device["path"]) for device in devices}
        for path in list(self._caps):
            if path not in wanted:
                release = getattr(self._caps[path], "release", None)
                if release:
                    release()
                self._caps.pop(path, None)
        grabbed = []
        status = []
        for device in devices:
            path = str(device["path"])
            cap = self._caps.get(path)
            if cap is None or not getattr(cap, "isOpened", lambda: False)():
                cap = self._cv2.VideoCapture(path, self._cv2.CAP_V4L2)
                try:
                    cap.set(self._cv2.CAP_PROP_FRAME_WIDTH, 640)
                    cap.set(self._cv2.CAP_PROP_FRAME_HEIGHT, 480)
                except Exception:
                    pass
                self._caps[path] = cap
            ok = False
            frame = None
            if getattr(cap, "isOpened", lambda: False)():
                ok, frame = cap.read()
            if not ok:
                release = getattr(cap, "release", None)
                if release:
                    release()
                self._caps.pop(path, None)
            else:
                grabbed.append({"device": device, "frame": frame})
            status.append({
                "path": path,
                "name": device.get("name") or "",
                "open": bool(ok),
            })
        return grabbed, status


def _gray_bytes(cv2, frame) -> bytes:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (160, 90))
    return small.tobytes()


def _process_jobs(store: PresenceStore, cv2, detector, recognizer, pool: CameraPool, devices: list[dict]) -> None:
    jobs = store.pending_jobs()
    if not jobs:
        return
    grabbed, _status = pool.frames(devices)
    face = None
    if grabbed and detector is not None and recognizer is not None:
        found = faces_from_frame(cv2, detector, recognizer, grabbed[0]["frame"])
        face = found[0] if found else None
    for job in jobs:
        kind = job.get("kind")
        job_id = str(job.get("id") or "")
        if kind == "photo":
            inbox = store.inbox_root / f"{job_id}.jpg"
            if detector is None or not inbox.is_file():
                store.fail_job(job_id, "photo was not readable")
                continue
            frame = cv2.imread(str(inbox))
            found = faces_from_frame(cv2, detector, recognizer, frame) if frame is not None else []
            if not found:
                store.fail_job(job_id, "no face in that photo")
                continue
            try:
                store.add_sample(str(job.get("person_id") or ""), found[0]["embedding"], found[0]["thumb"] or None)
            except (KeyError, ValueError) as exc:
                store.fail_job(job_id, str(exc))
                continue
            store.finish_job(job_id, {"sample_count": store.get_person(str(job.get("person_id") or ""))["sample_count"]})
            continue
        if face is None:
            store.fail_job(job_id, "no face in front of the camera")
            continue
        if kind == "capture":
            try:
                person = store.add_sample(str(job.get("person_id") or ""), face["embedding"], face["thumb"] or None)
            except (KeyError, ValueError) as exc:
                store.fail_job(job_id, str(exc))
                continue
            store.finish_job(job_id, {"sample_count": person["sample_count"]})
            continue
        if kind == "test":
            from presence_match import best_match

            found = best_match(face["embedding"], store.enrolled_vectors(), store.read_settings()["threshold"])
            if found is None:
                store.finish_job(job_id, {"matched": False, "stored": False})
            else:
                store.finish_job(job_id, {
                    "matched": True,
                    "stored": False,
                    "person_id": found.person_id,
                    "name": found.name,
                    "score": found.score,
                })


def main() -> int:
    if not presence_enabled():
        print("Presence is off. Install with --presence.", file=sys.stderr)
        return 0
    store = PresenceStore(presence_dir())
    store.ensure()
    fps = clamp_fps(os.environ.get("PRESENCE_FPS", "3"))
    interval = 1.0 / fps
    pool = CameraPool()
    engines = None
    previous: dict[str, bytes] = {}
    model_dir = store.root / "models"
    while True:
        started = time.monotonic()
        now = datetime.now(timezone.utc)
        store.purge_unknown(now)
        store.expire_jobs(now)
        settings = store.read_settings()
        state = merged_state(store.read_state())
        paused, reason = pause_decision(state, now=now, quiet_hours=_quiet_hours(settings))
        forced = [item.strip() for item in os.environ.get("PRESENCE_DEVICES", "").split(",") if item.strip()]
        skip = {observer_device_path()}
        devices = pick_webcams(list_video_devices(), skip_paths=skip, forced=forced or None)
        if paused:
            pool.close()
            store.write_runtime({
                "paused": True,
                "pause_reason": reason,
                "cameras": [{"path": device.get("path") or "", "name": device.get("name") or "", "open": False} for device in devices],
                "fps": 0,
                "model": model_label(),
                "backend": "",
                "updated_at": now.isoformat(),
            })
            time.sleep(interval)
            continue
        try:
            if engines is None:
                cv2, detector, recognizer, used = prepare_models(model_dir, _budget_mib())
                pool.bind(cv2)
                engines = (cv2, detector, recognizer, used)
        except PresenceVisionError as exc:
            store.write_runtime({
                "paused": False,
                "cameras": [],
                "fps": 0,
                "model": model_label(),
                "backend": "unavailable",
                "detail": str(exc)[:160],
                "updated_at": now.isoformat(),
            })
            time.sleep(max(interval, 2.0))
            continue
        cv2, detector, recognizer, used = engines
        grabbed, camera_status = pool.frames(devices)
        seen: list[SeenFace] = []
        any_motion = False
        motion_threshold = float(settings.get("motion_threshold") or 0.04)
        for item in grabbed:
            device = item["device"]
            path = str(device.get("path") or "")
            gray = _gray_bytes(cv2, item["frame"])
            opened, _delta = motion_open(previous.get(path, b""), gray, motion_threshold)
            previous[path] = gray
            if not opened:
                continue
            any_motion = True
            for face in faces_from_frame(cv2, detector, recognizer, item["frame"]):
                seen.append(SeenFace(
                    embedding=face["embedding"],
                    camera=path,
                    thumb=face["thumb"] or None,
                ))
        greetings: list[dict] = []
        if grabbed and not any_motion:
            store.write_tracked(touch_present(store.read_tracked(), now))
        else:
            result = step(
                seen,
                store.enrolled_vectors(),
                store.read_tracked(),
                now,
                threshold=float(settings.get("threshold") or 0.36),
                debounce_minutes=float(settings.get("debounce_minutes") or 10),
                depart_seconds=float(settings.get("depart_seconds") or 30),
                unknown_debounce_minutes=float(settings.get("unknown_debounce_minutes") or 10),
                unknown_thumbnails=bool(settings.get("unknown_thumbnails")),
                cameras_live=bool(grabbed),
            )
            store.apply_step(result)
            greetings = result.greetings
        for greeting in greetings:
            speak_greeting(str(greeting.get("text") or ""))
        if grabbed:
            try:
                _process_jobs(store, cv2, detector, recognizer, pool, devices)
            except PresenceVisionError:
                pass
        elapsed = max(time.monotonic() - started, 0.001)
        store.write_runtime({
            "paused": False,
            "pause_reason": "",
            "cameras": camera_status,
            "fps": round(1.0 / elapsed, 2) if grabbed else 0,
            "model": f"{DETECTOR.filename} ({DETECTOR.license}) + {RECOGNIZER.filename} ({RECOGNIZER.license})",
            "backend": used,
            "updated_at": now.isoformat(),
        })
        remain = interval - (time.monotonic() - started)
        if remain > 0:
            time.sleep(remain)


if __name__ == "__main__":
    raise SystemExit(main())
