"""Thin async wrapper around the Heirloom backend.

Runs every HTTP call in a worker thread via Qt's QThreadPool so the UI never
blocks. We expose two helpers:

- `api.get_async(path, on_ok, on_err)`
- `api.post_async(path, json, on_ok, on_err)`
- `api.post_multipart_async(path, files, on_ok, on_err)`

Each fires `on_ok(dict)` or `on_err(str)` on the GUI thread when done.
"""
from __future__ import annotations

import io
import json
from typing import Callable, Optional

import requests
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from . import config

_POOL: Optional[QThreadPool] = None


def _pool() -> QThreadPool:
    global _POOL
    if _POOL is None:
        _POOL = QThreadPool.globalInstance()
    return _POOL


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.DEVICE_TOKEN}",
        "Accept": "application/json",
    }


class _Signals(QObject):
    ok = Signal(object)
    err = Signal(str)


class _Job(QRunnable):
    def __init__(self, fn: Callable):
        super().__init__()
        self.fn = fn
        self.signals = _Signals()

    @Slot()
    def run(self) -> None:  # pragma: no cover — runs in worker
        try:
            result = self.fn()
            self.signals.ok.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.signals.err.emit(str(exc))


def _submit(fn: Callable, on_ok: Optional[Callable], on_err: Optional[Callable]) -> None:
    job = _Job(fn)
    if on_ok is not None:
        job.signals.ok.connect(on_ok)
    if on_err is not None:
        job.signals.err.connect(on_err)
    _pool().start(job)


def _url(path: str) -> str:
    base = config.BACKEND_URL.rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    if not path.startswith("/api"):
        path = "/api" + path
    return f"{base}{path}"


def _check(r: requests.Response) -> dict:
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text[:200])
        except Exception:
            detail = r.text[:200]
        raise RuntimeError(f"HTTP {r.status_code}: {detail}")
    if not r.content:
        return {}
    try:
        return r.json()
    except ValueError:
        return {"raw": r.text}


# ---- public helpers ----
def get_async(
    path: str,
    on_ok: Optional[Callable] = None,
    on_err: Optional[Callable] = None,
    timeout: float = 30.0,
) -> None:
    _submit(
        lambda: _check(requests.get(_url(path), headers=_headers(), timeout=timeout)),
        on_ok,
        on_err,
    )


def post_async(
    path: str,
    payload: Optional[dict] = None,
    on_ok: Optional[Callable] = None,
    on_err: Optional[Callable] = None,
    timeout: float = 60.0,
) -> None:
    body = json.dumps(payload or {}).encode("utf-8")
    headers = {**_headers(), "Content-Type": "application/json"}
    _submit(
        lambda: _check(
            requests.post(_url(path), data=body, headers=headers, timeout=timeout)
        ),
        on_ok,
        on_err,
    )


def post_multipart_async(
    path: str,
    files: dict,
    data: Optional[dict] = None,
    on_ok: Optional[Callable] = None,
    on_err: Optional[Callable] = None,
    timeout: float = 120.0,
) -> None:
    """For audio uploads."""
    _submit(
        lambda: _check(
            requests.post(
                _url(path),
                files=files,
                data=data or {},
                headers=_headers(),
                timeout=timeout,
            )
        ),
        on_ok,
        on_err,
    )
