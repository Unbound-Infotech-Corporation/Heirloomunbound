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
    token = (config.DEVICE_TOKEN or "").strip()
    headers = {"Accept": "application/json"}
    if token and not token.startswith("__"):
        headers["Authorization"] = f"Bearer {token}"
    return headers


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
def run_async(
    fn: Callable,
    on_ok: Optional[Callable] = None,
    on_err: Optional[Callable] = None,
) -> None:
    """Run any callable off the GUI thread."""
    _submit(fn, on_ok, on_err)


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


def put_async(
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
            requests.put(_url(path), data=body, headers=headers, timeout=timeout)
        ),
        on_ok,
        on_err,
    )


def probe_local_url(
    url: str,
    method: str = "GET",
    payload: Optional[dict] = None,
    api_key: Optional[str] = None,
    on_ok: Optional[Callable] = None,
    on_err: Optional[Callable] = None,
    timeout: float = 4.0,
) -> None:
    """Fire-and-forget HTTP probe against a user-supplied local endpoint.

    Used by the "Test connection" buttons in the Local AI settings tab. Runs
    in the worker pool so a hung 127.0.0.1 server never freezes the UI.
    NEVER attaches the Heirloom DEVICE_TOKEN — this hits the user's own PC.
    """
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    def _do() -> dict:
        m = method.upper()
        if m == "GET":
            r = requests.get(url, headers=headers, timeout=timeout)
        else:
            body = json.dumps(payload or {}).encode("utf-8")
            headers["Content-Type"] = "application/json"
            r = requests.post(url, data=body, headers=headers, timeout=timeout)
        try:
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        except Exception:  # noqa: BLE001
            data = {}
        return {"ok": 200 <= r.status_code < 500, "status": r.status_code, "data": data}

    _submit(_do, on_ok, on_err)

