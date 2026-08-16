"""Sign this computer in with Google in the browser.

Heirloom never sees a Google password. Google's page asks. We catch the
one-time session on this computer, then pair a house token (comp_…).
"""
from __future__ import annotations

import json
import re
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
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


def pair_this_computer(base_url: str | None = None) -> dict[str, Any]:
    """Open Google in the browser, pair this PC, remember the house token."""
    house = (base_url or config.BACKEND_URL or "").strip().rstrip("/")
    if not house.startswith("http") or "localhost" in house:
        house = config.PUBLIC_HOUSE
    session_id = _catch_session_id()
    if not session_id:
        raise RuntimeError(
            "The browser sign-in didn’t finish. Tap Continue with Google again."
        )
    return _exchange_and_register(house, session_id)


def _catch_session_id() -> str:
    ready = threading.Event()
    started = threading.Event()
    box: dict[str, str] = {}

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
    port = int(httpd.server_address[1])

    def _serve() -> None:
        started.set()
        httpd.serve_forever()

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    started.wait(5)
    redirect = f"http://127.0.0.1:{port}/callback"
    url = "https://auth.emergentagent.com/?redirect=" + quote(redirect, safe="")
    try:
        webbrowser.open(url)
        ready.wait(240)
    finally:
        httpd.shutdown()
        httpd.server_close()
    return box.get("session_id") or ""


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
            "Google didn’t finish signing in. Tap Continue with Google again. "
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
            "Signed in, but this computer didn’t pair. Tap Continue with Google again."
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
