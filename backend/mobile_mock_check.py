"""End-to-end smoke for the phone app API and the Twilio line in mock mode, against a throwaway DB.

    DB_NAME=hl_mock_<anything> TWILIO_MODE=mock python -m mobile_mock_check

It refuses to run unless DB_NAME starts with "hl_mock_", builds a minimal API (mobile, desktop,
companion, twilio_line routers) on 127.0.0.1, makes a fake owner + session, pairs a "phone",
chats, speaks, sends voice, simulates an SMS and a call, then drops the whole throwaway DB.
Uses the box's local Ollama, Whisper and voice; nothing leaves the box, no Twilio account.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

OWNER_NUMBER = "+15555550100"
STRANGER = "+15555550199"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _req(method: str, url: str, *, token: str = "", body=None, form=None, raw=None, headers=None, timeout=300):
    h = dict(headers or {})
    data = None
    if token:
        h["Authorization"] = "Bearer " + token
    if body is not None:
        data, h["Content-Type"] = json.dumps(body).encode(), "application/json"
    elif form is not None:
        data, h["Content-Type"] = urllib.parse.urlencode(form).encode(), "application/x-www-form-urlencoded"
    elif raw is not None:
        data, ctype = raw
        h["Content-Type"] = ctype
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), time.time() - t0
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), time.time() - t0


def _multipart(fields: dict, file_field: str, filename: str, payload: bytes, ctype: str):
    boundary = "hl" + secrets.token_hex(8)
    out = b""
    for k, v in fields.items():
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    out += (f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n").encode() + payload + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return out, f"multipart/form-data; boundary={boundary}"


def main() -> int:
    db_name = os.environ.get("DB_NAME", "")
    if not db_name.startswith("hl_mock_"):
        print("Refusing: set DB_NAME=hl_mock_<something> (a throwaway database).")
        return 2
    os.environ.setdefault("TWILIO_MODE", "mock")
    import uvicorn
    from fastapi import APIRouter, FastAPI

    from deps import db
    from routers import companion, desktop, mobile, twilio_line

    app = FastAPI()
    server_loop: list = []

    @app.on_event("startup")
    async def _grab_loop() -> None:  # Motor binds to the server's loop; run our DB setup there too
        server_loop.append(asyncio.get_running_loop())
    api = APIRouter(prefix="/api")
    for r in (companion.router, mobile.router, twilio_line.router, desktop.router):
        api.include_router(r)
    app.include_router(api)
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)

    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, info: str = "") -> None:
        results.append((name, ok, info))
        print(("PASS " if ok else "FAIL ") + name + (f"  [{info}]" if info else ""), flush=True)

    def run(make):  # make() is called on the server loop, so Motor's futures bind there
        async def _wait():
            return await make()

        return asyncio.run_coroutine_threadsafe(_wait(), server_loop[0]).result(60)
    try:
        uid = "user_mock_" + secrets.token_hex(4)
        session = "sess_mock_" + secrets.token_urlsafe(16)
        now = datetime.now(timezone.utc)
        run(lambda: db.users.insert_one({"user_id": uid, "name": "Test Owner", "email": "owner@example.invalid",
                                 "audience": "owner", "created_at": now.isoformat()}))
        run(lambda: db.user_sessions.insert_one({"user_id": uid, "session_token": session,
                                         "expires_at": (now + timedelta(hours=1)).isoformat()}))
        run(lambda: db.twin_phone_settings.insert_one({"user_id": uid, "answering": True, "owner_e164": OWNER_NUMBER,
                                                "who_can_call": "allowlist", "unknown_policy": "decline"}))

        st, body, _ = _req("POST", base + "/api/mobile/pair/start", token=session,
                           body={"box_url": "https://box.example.invalid:8443"})
        start = json.loads(body) if st == 200 else {}
        check("owner starts pairing", st == 200 and start.get("qr", "").startswith("heirloom://pair?"), start.get("code", str(st)))
        st, body, _ = _req("POST", base + "/api/mobile/pair/claim", body={"code": "WRONG000", "platform": "ios"})
        check("wrong code refused", st == 404, str(st))
        code = start.get("code", "").lower()  # typed in lower case with the dash
        st, body, _ = _req("POST", base + "/api/mobile/pair/claim", body={"code": code, "platform": "android"})
        dev = json.loads(body) if st == 200 else {}
        phone = dev.get("device_token", "")
        check("phone claims code", st == 200 and phone.startswith("mob_"), dev.get("device_id", str(st)))
        st, _, _ = _req("POST", base + "/api/mobile/pair/claim", body={"code": code, "platform": "android"})
        check("code is single use", st == 404, str(st))
        st, body, _ = _req("GET", base + "/api/mobile/me", token=phone)
        check("phone /me", st == 200 and json.loads(body).get("local_only") is True, body.decode()[:80])
        st, _, _ = _req("GET", base + "/api/mobile/devices", token=phone)
        check("phone token cannot list devices", st in (401, 403), str(st))

        st, body, dt = _req("POST", base + "/api/desktop/chat", token=phone, body={"text": "Hi, are you there?", "mode": "twin"})
        reply = json.loads(body).get("reply", "") if st == 200 else body.decode()[:120]
        check("phone chat (local model)", st == 200 and bool(reply), f"{dt:.1f}s: {reply[:70]}")

        st, wav, dt = _req("GET", base + "/api/mobile/speak.wav?" + urllib.parse.urlencode({"text": "Testing the phone voice."}),
                           token=phone, timeout=180)
        voice_ok = st == 200 and wav.startswith(b"RIFF")
        check("box voice for phone", voice_ok, f"{dt:.1f}s, {len(wav)} bytes" if voice_ok else f"{st} {wav[:80]!r}")

        if voice_ok:
            payload, ctype = _multipart({"audience": "owner"}, "audio", "talk.wav", wav, "audio/wav")
            st, body, dt = _req("POST", base + "/api/companion/voice", token=phone, raw=(payload, ctype))
            data = json.loads(body) if st == 200 else {}
            check("phone voice -> local Whisper -> Twin", st == 200 and "phone voice" in data.get("user_text", "").lower(),
                  f"{dt:.1f}s heard={data.get('user_text', body[:80])!r}")

        mock = {"X-Heirloom-Mock": "1"}
        st, body, _ = _req("POST", base + "/api/twilio/sms", form={"From": OWNER_NUMBER, "Body": "hello"})
        check("sms without mock header refused", st == 403, str(st))
        st, body, dt = _req("POST", base + "/api/twilio/sms", headers=mock,
                            form={"From": OWNER_NUMBER, "To": "+15550000000", "Body": "Hi Twin, quick test text.", "MessageSid": "SMmock"})
        txt = body.decode()
        check("owner SMS answered (TwiML Message)", st == 200 and "<Message>" in txt, f"{dt:.1f}s {txt[:110]}")
        st, body, _ = _req("POST", base + "/api/twilio/sms", headers=mock,
                           form={"From": STRANGER, "To": "+15550000000", "Body": "who is this", "MessageSid": "SMmock2"})
        check("unknown texter declined", st == 200 and "<Response" in body.decode(), body.decode()[:110])

        call = "CAmock" + secrets.token_hex(4)
        st, body, dt = _req("POST", base + "/api/twilio/voice", headers=mock,
                            form={"From": OWNER_NUMBER, "To": "+15550000000", "CallSid": call})
        txt = body.decode()
        check("owner call greeted (Play + Record, no Say)", st == 200 and "<Record" in txt and "<Say" not in txt, f"{dt:.1f}s {txt[:120]}")
        if voice_ok:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fh:
                fh.write(wav)
                path = fh.name
            st, body, dt = _req("POST", base + "/api/twilio/voice/turn", headers=mock,
                                form={"From": OWNER_NUMBER, "CallSid": call, "RecordingUrl": "file://" + path, "RecordingSid": "REmock"})
            txt = body.decode()
            os.unlink(path)
            check("call turn: Whisper -> Twin -> voice Play", st == 200 and "<Play>" in txt and "<Say" not in txt, f"{dt:.1f}s {txt[:140]}")
            clip = txt.split("<Play>")[1].split("</Play>")[0] if "<Play>" in txt else ""
            if clip:
                path_part = urllib.parse.urlsplit(clip).path
                st, audio, _ = _req("GET", base + path_part)
                check("reply clip served", st == 200 and audio.startswith(b"RIFF"), f"{len(audio)} bytes")
        st, body, _ = _req("POST", base + "/api/twilio/voice/turn", headers=mock,
                           form={"From": OWNER_NUMBER, "CallSid": call, "RecordingUrl": "file:///etc/passwd", "RecordingSid": "REx"})
        check("mock recording must be a .wav", st == 200 and "passwd" not in body.decode(), body.decode()[:100])
        st, body, _ = _req("GET", base + "/api/twilio/status", token=session)
        check("status hides the auth token", st == 200 and "auth_token\": \"" not in body.decode(), body.decode()[:140])

        st, _, _ = _req("DELETE", base + f"/api/mobile/devices/{dev.get('device_id', 'x')}", token=session)
        st2, _, _ = _req("GET", base + "/api/mobile/me", token=phone)
        check("owner revokes phone", st == 200 and st2 in (401, 403), f"{st} then {st2}")
    finally:
        try:
            run(lambda: db.client.drop_database(db_name))
            names = run(lambda: db.client.list_database_names())
            print(("PASS " if db_name not in names else "FAIL ") + f"throwaway DB {db_name} dropped", flush=True)
        finally:
            server.should_exit = True
            thread.join(timeout=10)
    bad = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
