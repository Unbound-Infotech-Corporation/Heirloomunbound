"""Sign this computer in with Google in the browser.

Heirloom never sees a Google password. Google's page asks. We catch the
one-time session on this computer, then pair a house token (comp_…).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional
from urllib.parse import parse_qs, quote, urlparse

import requests

from . import config

_DONE_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Heirloom</title></head>
<body style="font-family:Segoe UI,sans-serif;background:#f4e8c8;color:#3a2418;padding:48px;">
<h1 style="font-size:28px;">You're signed in.</h1>
<p>You can close this tab and go back to Heirloom.</p>
<p>We never asked for a Google or Windows password.</p>
<script>
function send(id) {
  fetch("/done", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({session_id: id})});
}
function grab() {
  const hash = (location.hash || "").replace(/^#/, "");
  const query = (location.search || "").replace(/^\\?/, "");
  const blob = hash + "&" + query;
  const m = blob.match(/session_id=([^&]+)/);
  if (m) { send(decodeURIComponent(m[1])); }
}
grab();
window.addEventListener("hashchange", grab);
setTimeout(grab, 400);
</script>
</body></html>
"""


def house_url(base_url: str | None = None) -> str:
    house = (base_url or config.BACKEND_URL or "").strip().rstrip("/")
    if not house.startswith("http") or "localhost" in house:
        return config.PUBLIC_HOUSE
    return house


def open_browser(url: str) -> bool:
    """Open Google in the real browser. Call this from the window thread.

    Heirloom.bat uses pythonw.exe. webbrowser.open() from a worker thread
    often does nothing there, so we try Windows' own open first.
    """
    blob = (url or "").strip()
    if not blob.startswith("http"):
        return False
    if sys.platform == "win32":
        try:
            os.startfile(blob)  # type: ignore[attr-defined]
            return True
        except Exception:
            pass
        try:
            subprocess.Popen(["cmd", "/c", "start", "", blob], close_fds=True)
            return True
        except Exception:
            pass
    try:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        if QDesktopServices.openUrl(QUrl(blob)):
            return True
    except Exception:
        pass
    try:
        return bool(webbrowser.open(blob, new=1))
    except Exception:
        return False


class GoogleCatcher:
    """Listen on this computer for the Google redirect, then hand back session_id."""

    def __init__(self) -> None:
        self.auth_url = ""
        self._ready = threading.Event()
        self._started = threading.Event()
        self._box: dict[str, str] = {}
        self._httpd: Optional[ThreadingHTTPServer] = None

    def start(self) -> str:
        box = self._box
        ready = self._ready

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args) -> None:  # noqa: D401
                return

            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                qs = parse_qs(parsed.query)
                sid = str((qs.get("session_id") or [""])[0]).strip()
                if sid:
                    box["session_id"] = sid
                    ready.set()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(_DONE_HTML.encode("utf-8"))

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    data = json.loads(raw.decode("utf-8") or "{}")
                except json.JSONDecodeError:
                    data = {}
                sid = str(data.get("session_id") or "").strip()
                if sid:
                    box["session_id"] = sid
                    ready.set()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"ok")

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd = httpd
        port = int(httpd.server_address[1])

        def _serve() -> None:
            self._started.set()
            httpd.serve_forever()

        thread = threading.Thread(target=_serve, daemon=True)
        thread.start()
        self._started.wait(5)
        redirect = f"http://127.0.0.1:{port}/callback"
        self.auth_url = "https://auth.emergentagent.com/?redirect=" + quote(redirect, safe="")
        return self.auth_url

    def wait(self, timeout: float = 240) -> str:
        try:
            self._ready.wait(timeout)
        finally:
            self.close()
        return self._box.get("session_id") or ""

    def close(self) -> None:
        httpd = self._httpd
        self._httpd = None
        if httpd is None:
            return
        try:
            httpd.shutdown()
        except Exception:
            pass
        try:
            httpd.server_close()
        except Exception:
            pass


def start_pair_flow(base_url: str | None = None) -> tuple[GoogleCatcher, str, str]:
    """Start the listener and return (catcher, Google URL, house). Open the URL in the window thread."""
    house = house_url(base_url)
    catcher = GoogleCatcher()
    url = catcher.start()
    return catcher, url, house


def finish_pair_flow(catcher: GoogleCatcher, house: str) -> dict[str, Any]:
    """Wait for Google, then pair this computer. Safe on a worker thread."""
    session_id = catcher.wait()
    if not session_id:
        raise RuntimeError(
            "The browser sign-in didn’t finish. Tap Sign in with Google again."
        )
    return _exchange_and_register(house, session_id)


def pair_this_computer(base_url: str | None = None) -> dict[str, Any]:
    """Open Google, pair this PC, remember the house token."""
    catcher, url, house = start_pair_flow(base_url)
    open_browser(url)
    return finish_pair_flow(catcher, house)


def _session_token_from(sess: requests.Session, response: requests.Response) -> str:
    tok = sess.cookies.get("session_token") or ""
    if tok:
        return tok
    for cookie in sess.cookies:
        if cookie.name == "session_token" and cookie.value:
            return cookie.value
    raw = response.headers.get("Set-Cookie") or ""
    match = re.search(r"session_token=([^;]+)", raw)
    return match.group(1) if match else ""


def _exchange_and_register(house: str, session_id: str) -> dict[str, Any]:
    sess = requests.Session()
    sess.headers.update({"Accept": "application/json"})
    r = sess.post(
        f"{house}/api/auth/session",
        json={"session_id": session_id},
        timeout=30,
    )
    if r.status_code >= 400:
        raise RuntimeError(
            "Google didn’t finish signing in. Tap Sign in with Google again. "
            "We never ask you to type a Google password here."
        )
    user: dict[str, Any] = {}
    try:
        body = r.json()
        if isinstance(body, dict):
            user = body
    except ValueError:
        user = {}
    token = _session_token_from(sess, r)
    if token:
        sess.headers["Authorization"] = f"Bearer {token}"
    reg = sess.post(
        f"{house}/api/companion/register",
        json={"name": "This computer"},
        timeout=30,
    )
    if reg.status_code >= 400:
        raise RuntimeError(
            "Signed in, but this computer didn’t pair. Tap Sign in with Google again."
        )
    data = reg.json() if reg.content else {}
    device_token = str(data.get("device_token") or "").strip()
    if not device_token.startswith("comp_"):
        raise RuntimeError("That sign-in didn’t pair this computer. Try Google again.")
    config.persist_login(device_token, house)
    return {
        "device_token": device_token,
        "house_url": house,
        "user": user,
        "note": "This computer is signed in. Talk to your twin in the big window.",
    }
