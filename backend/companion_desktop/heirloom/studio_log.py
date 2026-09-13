"""Ring-buffer + append-only studio.log for the Heirloom Unbound Terminal."""
from __future__ import annotations

import json
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from . import config

LEVELS = ("debug", "info", "warn", "error", "ticket")
SOURCES = ("probe", "router", "tts", "stt", "twin", "avatar", "companion", "ui", "ticket")
RING_MAX = 8000

Listener = Callable[[dict], None]


def log_dir() -> Path:
    return config.app_data_dir()


def studio_log_path() -> Path:
    return log_dir() / "studio.log"


def faults_log_path() -> Path:
    """Sibling of WinUI faults.log — companion writes studio.log beside it."""
    return log_dir() / "faults.log"


class StudioLog:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._lines: deque[dict] = deque(maxlen=RING_MAX)
        self._listeners: list[Listener] = []
        self._seq = 0

    def subscribe(self, fn: Listener) -> None:
        with self._lock:
            if fn not in self._listeners:
                self._listeners.append(fn)

    def unsubscribe(self, fn: Listener) -> None:
        with self._lock:
            self._listeners = [x for x in self._listeners if x is not fn]

    def append(self, level: str, source: str, message: str, extra: Optional[dict] = None) -> dict:
        lvl = level if level in LEVELS else "info"
        src = source if source in SOURCES else "companion"
        rec = {
            "id": 0,
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": lvl,
            "source": src,
            "message": str(message or "")[:2000],
        }
        if extra:
            rec["extra"] = extra
        listeners: list[Listener] = []
        with self._lock:
            self._seq += 1
            rec["id"] = self._seq
            self._lines.append(rec)
            listeners = list(self._listeners)
        self._write_file(rec)
        for fn in listeners:
            try:
                fn(rec)
            except Exception:
                pass
        return rec

    def _write_file(self, rec: dict) -> None:
        try:
            path = studio_log_path()
            line = json.dumps(
                {k: rec[k] for k in ("ts", "level", "source", "message") if k in rec},
                ensure_ascii=False,
            )
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            pass

    def snapshot(self, *, last: int = 200, level: str = "", source: str = "") -> list[dict]:
        with self._lock:
            rows = list(self._lines)
        if level:
            rows = [r for r in rows if r.get("level") == level]
        if source:
            rows = [r for r in rows if r.get("source") == source]
        if last and last > 0:
            rows = rows[-last:]
        return rows

    def clear_ring(self) -> None:
        with self._lock:
            self._lines.clear()

    def format_line(self, rec: dict) -> str:
        ts = str(rec.get("ts") or "")[11:19]
        return f"{ts}  {rec.get('level', 'info'):<6}  {rec.get('source', ''):<10}  {rec.get('message', '')}"


_LOG: Optional[StudioLog] = None


def get_log() -> StudioLog:
    global _LOG  # noqa: PLW0603
    if _LOG is None:
        _LOG = StudioLog()
    return _LOG


def log(level: str, source: str, message: str, extra: Optional[dict[str, Any]] = None) -> dict:
    return get_log().append(level, source, message, extra)


def info(source: str, message: str, **extra: Any) -> dict:
    return log("info", source, message, extra or None)


def warn(source: str, message: str, **extra: Any) -> dict:
    return log("warn", source, message, extra or None)


def error(source: str, message: str, **extra: Any) -> dict:
    return log("error", source, message, extra or None)


def ticket(source: str, message: str, **extra: Any) -> dict:
    return log("ticket", source, message, extra or None)
