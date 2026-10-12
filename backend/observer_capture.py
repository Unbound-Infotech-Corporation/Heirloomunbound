"""Capture planning: device pick, sample rate, RAM ring, no-signal.

Frames live under ``/run`` or ``/dev/shm`` only. This module does not open a
device; the daemon does.
"""
from __future__ import annotations

import os
from pathlib import Path

_RAM_ROOTS = ("/run/", "/dev/shm/")
_PREFER = ("xr1", "evga", "uvc", "usb video", "usb2.0 camera", "capture")
# 32 GB system RAM also holds Ubuntu, Docker, Mongo, and any Ollama spill.
DEFAULT_RING_SLOTS = 4
DEFAULT_RAM_BUDGET_BYTES = 64 * 1024 * 1024
MAX_RAM_BUDGET_BYTES = 256 * 1024 * 1024


class IdleClock:
    """Tracks a no-signal stretch. The returned elapsed time is what gets logged."""

    def __init__(self) -> None:
        self.started: float | None = None

    def update(self, idle: bool, now: float) -> float | None:
        if idle:
            if self.started is None:
                self.started = now
            return None
        if self.started is None:
            return None
        elapsed = max(0.0, now - self.started)
        self.started = None
        return elapsed

    def current(self, now: float) -> float:
        if self.started is None:
            return 0.0
        return max(0.0, now - self.started)


def ring_slot_count(raw: str | int | None = None) -> int:
    """How many gray thumbnails to keep. Capped so a bad setting cannot grow the ring."""
    if raw is None:
        raw = os.environ.get("OBSERVER_RING_SLOTS", str(DEFAULT_RING_SLOTS))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_RING_SLOTS
    return max(1, min(value, 8))


def ram_budget_bytes(raw: str | int | None = None) -> int:
    """Byte cap for ``/run/heirloom-observer``. Default 64 MiB on the 32 GB box."""
    if raw is None:
        raw = os.environ.get("OBSERVER_RAM_BUDGET_BYTES", str(DEFAULT_RAM_BUDGET_BYTES))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_RAM_BUDGET_BYTES
    return max(1024 * 1024, min(value, MAX_RAM_BUDGET_BYTES))


def trim_ram_dir(root: Path, budget_bytes: int) -> int:
    """Delete oldest files until the directory is within ``budget_bytes``."""
    if budget_bytes < 0:
        raise ValueError("RAM budget must be >= 0")
    files = [path for path in root.iterdir() if path.is_file()]
    files.sort(key=lambda path: path.stat().st_mtime)
    total = 0
    sized: list[tuple[Path, int]] = []
    for path in files:
        try:
            size = path.stat().st_size
        except OSError:
            continue
        sized.append((path, size))
        total += size
    removed = 0
    for path, size in sized:
        if total <= budget_bytes:
            break
        try:
            path.unlink()
        except OSError:
            continue
        total -= size
        removed += 1
    return removed


def assert_ram_dir(path: Path | str) -> Path:
    """Refuse a ring buffer that would land on persistent disk."""
    raw = os.fspath(path)
    if not raw.startswith("/"):
        raise ValueError("observer ring buffer path must be absolute")
    normalized = raw if raw.endswith("/") else raw + "/"
    if not normalized.startswith(_RAM_ROOTS):
        raise ValueError("observer ring buffer must stay in RAM (/run or /dev/shm)")
    return Path(raw)


def sample_interval_s(
    scene_delta: float,
    *,
    base_fps: float = 2.0,
    burst_fps: float = 8.0,
    burst_at: float = 0.35,
) -> float:
    """Seconds to sleep. High scene change (games) uses the burst rate."""
    fps = burst_fps if scene_delta >= burst_at else base_fps
    if fps <= 0:
        return 1.0
    return 1.0 / fps


def analysis_due(
    *,
    scene_delta: float,
    since_last_s: float,
    burst_at: float = 0.35,
    calm_every_s: float = 15.0,
    burst_every_s: float = 4.0,
) -> bool:
    """Scene-change sampling is cheap. OCR and the vision model run less often."""
    if scene_delta >= burst_at:
        return since_last_s >= burst_every_s
    return since_last_s >= calm_every_s


def scene_delta(prev: bytes, curr: bytes) -> float:
    if not prev or not curr:
        return 1.0
    size = min(len(prev), len(curr))
    if size == 0:
        return 1.0
    changed = sum(1 for index in range(size) if prev[index] != curr[index])
    return changed / size


def is_no_signal(gray: bytes, *, threshold: int = 12) -> bool:
    if not gray:
        return True
    return (sum(gray) / len(gray)) < threshold


def pick_capture_device(devices: list[dict]) -> dict | None:
    """Prefer a UVC capture node. Skip metadata nodes. Lowest index breaks ties."""
    usable = []
    for device in devices:
        name = str(device.get("name") or "")
        if "metadata" in name.lower():
            continue
        path = str(device.get("path") or "")
        if not path:
            continue
        usable.append(device)
    if not usable:
        return None

    def rank(device: dict) -> tuple[int, int]:
        name = str(device.get("name") or "").lower()
        preferred = 0 if any(token in name for token in _PREFER) else 1
        try:
            index = int(device.get("index", 99))
        except (TypeError, ValueError):
            index = 99
        return preferred, index

    return sorted(usable, key=rank)[0]


def ffmpeg_grab_command(
    device: str,
    dest: Path,
    *,
    width: int = 1920,
    height: int = 1080,
    input_format: str | None = "mjpeg",
) -> list[str]:
    """One scaled frame from V4L2. ``dest`` must already be a RAM path."""
    assert_ram_dir(dest.parent)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-fflags",
        "nobuffer",
        "-f",
        "v4l2",
    ]
    if input_format:
        command.extend(["-input_format", input_format])
    command.extend(
        [
            "-video_size",
            f"{width}x{height}",
            "-i",
            device,
            "-frames:v",
            "1",
            "-vf",
            "scale=640:360",
            "-y",
            os.fspath(dest),
        ]
    )
    return command


def ffmpeg_clip_command(
    device: str,
    dest: Path,
    *,
    seconds: float = 8,
    width: int = 1280,
    height: int = 720,
) -> list[str]:
    """A short highlight in RAM. No audio. The daemon moves it to disk only after the privacy gate."""
    assert_ram_dir(dest.parent)
    length = int(round(seconds))
    if length <= 0:
        raise ValueError("clip seconds must be positive")
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-fflags",
        "nobuffer",
        "-f",
        "v4l2",
        "-i",
        device,
        "-t",
        str(length),
        "-an",
        "-vf",
        f"scale={width}:{height}",
        "-c:v",
        "mpeg4",
        "-q:v",
        "8",
        "-y",
        os.fspath(dest),
    ]


def ffmpeg_gray_command(device: str, *, width: int = 160, height: int = 90) -> list[str]:
    """Raw gray thumbnail on stdout for scene-change and no-signal checks."""
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-fflags",
        "nobuffer",
        "-f",
        "v4l2",
        "-i",
        device,
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
