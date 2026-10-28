"""LAN screen frames from the Windows companion.

The companion posts a JPEG of the primary display. The bytes stay in a RAM
spool until the daemon reads them. Notes still go through the capture
pipeline: privacy, the local vision model, and retention. Nothing is sent
off the machine.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

from observer_learn import is_capture_device_label
from observer_pipeline import consider_frame

CAPTURE_DEVICE = "/dev/video0"
SOURCES = ("network", "capture", "auto")
DEFAULT_SOURCE = "auto"
DEFAULT_FRESH_S = 3.0
TARGET_WIDTH = 1920
MAX_JPEG_BYTES = 2_500_000
SPOOL_MAX_AGE_S = 30.0


def configured_source(raw: str | None = None) -> str:
    """``network``, ``capture``, or ``auto``. Anything else is ``auto``."""
    if raw is None:
        raw = os.environ.get("OBSERVER_SOURCE", DEFAULT_SOURCE)
    value = (raw or DEFAULT_SOURCE).strip().lower()
    if value in SOURCES:
        return value
    return DEFAULT_SOURCE


def fresh_window_s(raw: str | float | None = None) -> float:
    """How recently a companion frame must have arrived to count as the picture."""
    if raw is None:
        raw = os.environ.get("OBSERVER_NETWORK_FRESH_S", str(DEFAULT_FRESH_S))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = DEFAULT_FRESH_S
    if value <= 0:
        return DEFAULT_FRESH_S
    return value


def screen_spool(raw: str | None = None) -> Path:
    """RAM spool shared by the API and the daemon. Tests set ``OBSERVER_SCREEN_SPOOL``."""
    if raw is None:
        raw = os.environ.get("OBSERVER_SCREEN_SPOOL", "")
    text = (raw or "").strip()
    if text:
        path = Path(text)
        path.mkdir(parents=True, exist_ok=True)
        return path
    ram = Path("/run/heirloom-observer/screen")
    try:
        ram.mkdir(parents=True, exist_ok=True)
        return ram
    except OSError:
        pass
    shm = Path("/dev/shm/heirloom-observer/screen")
    try:
        if Path("/dev/shm").is_dir():
            shm.mkdir(parents=True, exist_ok=True)
            return shm
    except OSError:
        pass
    from observer_store import observer_dir

    inbox = observer_dir() / "screen-inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    return inbox


def looks_like_jpeg(data: bytes) -> bool:
    return len(data) >= 4 and data.startswith(b"\xff\xd8") and b"\xff\xd9" in data


def accept_frame(*, jpeg: bytes, paused: bool, enabled: bool, spool: Path) -> dict:
    """Park one companion JPEG. A pause or a bad body is not written."""
    if paused:
        return {"accepted": False, "reason": "paused", "bytes": 0}
    if not enabled:
        return {"accepted": False, "reason": "off", "bytes": 0}
    if not jpeg:
        return {"accepted": False, "reason": "empty", "bytes": 0}
    if len(jpeg) > MAX_JPEG_BYTES:
        return {"accepted": False, "reason": "too-large", "bytes": len(jpeg)}
    if not looks_like_jpeg(jpeg):
        return {"accepted": False, "reason": "not-jpeg", "bytes": len(jpeg)}
    spool.mkdir(parents=True, exist_ok=True)
    path = spool / f"{time.time_ns()}.jpg"
    path.write_bytes(jpeg)
    return {"accepted": True, "reason": "", "bytes": len(jpeg)}


def discard_frames(root: Path) -> int:
    """Delete every parked JPEG. Used when Observer is paused."""
    if not root.is_dir():
        return 0
    removed = 0
    for path in root.glob("*.jpg"):
        try:
            path.unlink()
        except OSError:
            continue
        removed += 1
    return removed


def sweep_frames(root: Path, *, max_age_s: float = SPOOL_MAX_AGE_S, now: float | None = None) -> int:
    """Delete leftover JPEGs. A stopped daemon must not leave a picture behind."""
    moment = time.time() if now is None else now
    if not root.is_dir():
        return 0
    removed = 0
    for path in root.glob("*.jpg"):
        try:
            age = moment - path.stat().st_mtime
        except OSError:
            continue
        if age < max_age_s:
            continue
        try:
            path.unlink()
        except OSError:
            continue
        removed += 1
    return removed


def latest_frame(
    root: Path,
    *,
    now: float | None = None,
    fresh_s: float | None = None,
) -> tuple[bytes, float] | None:
    """Read and delete the newest JPEG when it is still inside the fresh window.

    Older files are deleted too. A stale newest file is deleted and not returned.
    """
    window = fresh_window_s() if fresh_s is None else fresh_s
    moment = time.time() if now is None else now
    if not root.is_dir():
        return None
    files = [path for path in root.glob("*.jpg") if path.is_file()]
    if not files:
        return None
    files.sort(key=lambda path: path.stat().st_mtime)
    newest = files[-1]
    try:
        age = max(0.0, moment - newest.stat().st_mtime)
        data = newest.read_bytes()
    except OSError:
        data = b""
        age = window + 1
    for path in files:
        try:
            path.unlink()
        except OSError:
            pass
    if not data or age > window:
        return None
    return data, age


class NetworkInbox:
    """Remember the last companion JPEG so a gap between posts is still "recent".

    The spool file is deleted when it is read. The fresh window is what decides
    whether ``auto`` stays on the network picture.
    """

    def __init__(self) -> None:
        self.jpeg = b""
        self.received_at = 0.0

    def push(self, jpeg: bytes, *, received_at: float) -> None:
        if not jpeg:
            return
        self.jpeg = jpeg
        self.received_at = received_at

    def age(self, now: float, fresh_s: float) -> float | None:
        if not self.jpeg or self.received_at <= 0:
            return None
        elapsed = now - self.received_at
        if elapsed > fresh_s:
            self.clear()
            return None
        return max(0.0, elapsed)

    def clear(self) -> None:
        self.jpeg = b""
        self.received_at = 0.0


def choose_source(*, mode: str, network_age_s: float | None, fresh_s: float) -> dict:
    """Pick the picture for this iteration.

    ``auto`` uses a network frame that arrived within ``fresh_s``. Otherwise it
    falls back to ``/dev/video0``. ``network`` never opens the capture card.
    ``capture`` keeps the existing UVC picker and ignores companion frames.
    """
    selected = configured_source(mode)
    fresh = network_age_s is not None and 0 <= network_age_s <= fresh_s
    if selected == "capture":
        return {"mode": "capture", "source": "capture", "device": "", "fresh": False, "signal": ""}
    if selected == "network" or fresh:
        return {
            "mode": selected,
            "source": "network",
            "device": "",
            "fresh": fresh,
            "signal": "ok" if fresh else "no-signal",
        }
    return {
        "mode": "auto",
        "source": "capture",
        "device": CAPTURE_DEVICE,
        "fresh": False,
        "signal": "",
    }


def status_fields(
    choice: dict,
    *,
    fps: float = 0,
    device: str = "",
    capture_signal: str = "",
) -> dict:
    """Health fields for one choice. A fresh network picture reports signal ``ok``."""
    source = str(choice.get("source") or "")
    signal = str(choice.get("signal") or capture_signal or "unknown")
    shown = device
    if not shown:
        shown = "network" if source == "network" else ""
    return {
        "source": source,
        "mode": str(choice.get("mode") or ""),
        "signal": signal,
        "device": shown,
        "fps": fps,
    }


def jpeg_to_gray(jpeg: bytes, *, width: int = 160, height: int = 90) -> bytes:
    """A small gray thumbnail for scene change. Empty when ffmpeg cannot decode."""
    if not jpeg or not shutil.which("ffmpeg"):
        return b""
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
        "-frames:v",
        "1",
        "-vf",
        f"scale={width}:{height}",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "pipe:1",
    ]
    try:
        completed = subprocess.run(
            command,
            input=jpeg,
            check=False,
            capture_output=True,
            timeout=4,
        )
    except (OSError, subprocess.TimeoutExpired):
        return b""
    if completed.returncode != 0 or not completed.stdout:
        return b""
    return completed.stdout


def commit_frame(
    store,
    *,
    ocr: str,
    app: str = "",
    model: Optional[Callable] = None,
    hotkey_phrase: str = "",
    now_iso: str,
    delta: float,
    jpeg_path: Path | None = None,
    highlight: Optional[Callable[[], None]] = None,
    clips: bool = False,
    cap_bytes: int | None = None,
) -> dict:
    """Privacy, vision notes, and retention. HDMI and the LAN both call this.

    The model runs only after the privacy filter allows the frame. The JPEG
    is deleted before a highlight is recorded. ``prune`` is the disk cap.
    """
    result = consider_frame(ocr=ocr, app=app, model=model, hotkey_phrase=hotkey_phrase)
    if jpeg_path is not None:
        jpeg_path.unlink(missing_ok=True)
    if result["latch_pause"]:
        store.latch_hotkey()
    elif result["dropped"]:
        store.add_observations(
            [{"ts": now_iso, "dropped": True, "reason": result["reason"]}]
        )
    else:
        from presence_cues import attach_presence_fields

        title = result["text"][:120]
        if is_capture_device_label(title):
            title = ""
        row = {
            "ts": now_iso,
            "activity": result["activity"],
            "app": app,
            "title": title,
            "game": result["game"],
            "text": result["text"],
            "scene_delta": round(delta, 3),
        }
        store.add_observations([attach_presence_fields(row)])
        if clips and delta >= 0.35 and highlight is not None:
            highlight()
    if clips and cap_bytes is not None:
        store.prune(cap_bytes=cap_bytes)
    return result
