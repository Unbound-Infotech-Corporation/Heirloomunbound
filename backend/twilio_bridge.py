"""Optional Twilio number for the Twin: family can call or text it. Twilio only routes the call or
text. Hearing (Whisper), the model, memory and the voice (Chatterbox) all run on the owner's box.

Modes (TWILIO_MODE):
  off   default. The /api/twilio routes answer 404.
  mock  no Twilio account: webhooks are accepted only from this machine with the header
        X-Heirloom-Mock: 1, recordings are read from local files, nothing is sent to Twilio.
        `python -m twilio_bridge simulate-sms +15551234567 "hello"` drives it end to end.
  live  real webhooks, checked with X-Twilio-Signature (HMAC-SHA1 with TWILIO_AUTH_TOKEN).

Config (placeholders in heirloom.env / box.env; nothing is bought or provisioned by Heirloom):
  TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER, HEIRLOOM_PUBLIC_URL (the https
  address Twilio can reach, e.g. a Cloudflare Tunnel to this box).

Calls use <Record>, not Twilio's speech recognition or text-to-speech: each caller turn is a short
recording that the box downloads, transcribes locally, answers, and speaks back with <Play> of a wav
the box rendered. In live mode the recording is deleted from Twilio right after it is downloaded.
Who may call or text uses the same owner settings as the phone line (phone_policy.decide_inbound).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional
from xml.sax.saxutils import escape

MODES = {"off", "mock", "live"}
PLACEHOLDER = "REPLACE_ME"
MAX_SMS_CHARS = 1500
RECORD_MAX_S = 30
AUDIO_TTL_S = 3600
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@dataclass
class TwilioConfig:
    mode: str = "off"
    account_sid: str = ""
    auth_token: str = ""
    number: str = ""
    public_url: str = ""

    @property
    def ready(self) -> bool:
        if self.mode == "mock":
            return True
        if self.mode != "live":
            return False
        fields = (self.account_sid, self.auth_token, self.number, self.public_url)
        return all(f and PLACEHOLDER not in f for f in fields) and self.public_url.startswith("https://")

    def public(self) -> dict:
        """What the owner's settings page may show: never the token."""
        def state(value: str) -> str:
            return "missing" if not value or PLACEHOLDER in value else "set"

        return {"mode": self.mode, "ready": self.ready, "account_sid": state(self.account_sid),
                "auth_token": state(self.auth_token), "number": self.number if state(self.number) == "set" else "",
                "public_url": self.public_url if state(self.public_url) == "set" else ""}


def config(env: Optional[Mapping[str, str]] = None) -> TwilioConfig:
    env = os.environ if env is None else env
    mode = (env.get("TWILIO_MODE") or "off").strip().lower()
    return TwilioConfig(mode=mode if mode in MODES else "off",
                        account_sid=(env.get("TWILIO_ACCOUNT_SID") or "").strip(),
                        auth_token=(env.get("TWILIO_AUTH_TOKEN") or "").strip(),
                        number=(env.get("TWILIO_PHONE_NUMBER") or "").strip(),
                        public_url=(env.get("HEIRLOOM_PUBLIC_URL") or "").strip().rstrip("/"))


def expected_signature(auth_token: str, url: str, params: Mapping[str, str]) -> str:
    """Twilio's request signature: base64(HMAC-SHA1(token, url + key1 + value1 + key2 + ...))."""
    payload = url + "".join(k + str(params[k]) for k in sorted(params))
    digest = hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def request_allowed(cfg: TwilioConfig, *, url: str, params: Mapping[str, str], signature: str,
                    client_host: str, mock_header: str) -> bool:
    if cfg.mode == "live":
        if not cfg.ready or not signature:
            return False
        return hmac.compare_digest(expected_signature(cfg.auth_token, url, params), signature)
    if cfg.mode == "mock":
        return client_host in _LOOPBACK and mock_header == "1"
    return False


def webhook_url(cfg: TwilioConfig, path: str) -> str:
    """The URL Twilio signs: our public address plus the path it was configured with."""
    return cfg.public_url + path


# ---------------------------------------------------------------------- TwiML

def twiml(*parts: str) -> str:
    return '<?xml version="1.0" encoding="UTF-8"?><Response>' + "".join(parts) + "</Response>"


def message(text: str) -> str:
    body = (text or "").strip()
    if len(body) > MAX_SMS_CHARS:
        body = body[: MAX_SMS_CHARS - 1].rstrip() + "…"
    return f"<Message>{escape(body)}</Message>"


def play(url: str) -> str:
    return f"<Play>{escape(url)}</Play>"


def record(action_url: str) -> str:
    return (f'<Record action="{escape(action_url)}" method="POST" maxLength="{RECORD_MAX_S}" timeout="3" '
            'playBeep="false" trim="trim-silence"/>')


def hangup() -> str:
    return "<Hangup/>"


# ---------------------------------------------------------------------- local audio for <Play>

class AudioCache:
    """Box-rendered wavs that Twilio fetches once to play. Random ids, deleted after an hour."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def put(self, wav: bytes) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        self.prune()
        clip = secrets.token_urlsafe(18)
        (self.root / f"{clip}.wav").write_bytes(wav)
        return clip

    def get(self, clip: str) -> Optional[bytes]:
        if not clip or not all(ch.isalnum() or ch in "-_" for ch in clip):
            return None
        path = self.root / f"{clip}.wav"
        return path.read_bytes() if path.is_file() else None

    def prune(self, now: Optional[float] = None) -> int:
        now = time.time() if now is None else now
        gone = 0
        for path in self.root.glob("*.wav"):
            if now - path.stat().st_mtime > AUDIO_TTL_S:
                path.unlink(missing_ok=True)
                gone += 1
        return gone


def recording_wav_url(recording_url: str) -> str:
    url = (recording_url or "").strip()
    return url if url.endswith(".wav") else url + ".wav"


def recording_host_ok(recording_url: str) -> bool:
    """Only download recordings from Twilio's API host (never an address taken from the request)."""
    host = urllib.parse.urlsplit(recording_url or "").hostname or ""
    return urllib.parse.urlsplit(recording_url or "").scheme == "https" and (
        host == "api.twilio.com" or host.endswith(".twilio.com"))


def basic_auth(cfg: TwilioConfig) -> str:
    raw = f"{cfg.account_sid}:{cfg.auth_token}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def sms_text(reply: str) -> str:
    """Texts are plain: drop markdown the model may add."""
    text = (reply or "").replace("**", "").replace("__", "").strip()
    return text or "I don't remember that yet, and I won't make it up."


def _simulate(argv: list[str]) -> int:
    """Post a mock webhook to the local API (TWILIO_MODE=mock on the API)."""
    import json
    import urllib.request

    if len(argv) < 3 or argv[0] not in {"simulate-sms", "simulate-call"}:
        print("usage: python -m twilio_bridge simulate-sms +15551234567 \"text\" [--api http://127.0.0.1:8001]\n"
              "       python -m twilio_bridge simulate-call +15551234567 path/to/turn.wav [--api URL]")
        return 2
    api = "http://127.0.0.1:8001"
    if "--api" in argv:
        api = argv[argv.index("--api") + 1].rstrip("/")
    sender, value = argv[1], argv[2]
    headers = {"X-Heirloom-Mock": "1", "Content-Type": "application/x-www-form-urlencoded"}

    def post(path: str, form: dict) -> str:
        req = urllib.request.Request(api + path, data=urllib.parse.urlencode(form).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=300) as resp:
            return resp.read().decode()

    if argv[0] == "simulate-sms":
        print(post("/api/twilio/sms", {"From": sender, "To": "+15550000000", "Body": value, "MessageSid": "SMmock"}))
        return 0
    call = "CAmock" + secrets.token_hex(4)
    print(post("/api/twilio/voice", {"From": sender, "To": "+15550000000", "CallSid": call}))
    print(post("/api/twilio/voice/turn", {"From": sender, "CallSid": call, "RecordingUrl": "file://" + os.path.abspath(value),
                                          "RecordingSid": "REmock"}))
    _ = json
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(_simulate(sys.argv[1:]))
