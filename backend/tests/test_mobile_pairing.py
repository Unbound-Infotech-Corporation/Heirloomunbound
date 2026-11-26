"""Phone pairing: one-time codes, QR payload, limits. Pure logic, no database."""
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mobile_pairing as mp  # noqa: E402

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)


def run(coro):
    return asyncio.run(coro)


def test_code_pairs_a_phone_once_and_is_stored_hashed():
    store = mp.MemoryStore()
    started = run(mp.start(store, "user_1", "https://192.168.0.110/", pin="abc=", now=NOW))
    assert len(started["code"]) == 9 and started["code"][4] == "-"
    raw = started["code"].replace("-", "")
    assert all(ch in mp.ALPHABET for ch in raw)
    assert raw not in str(store.codes)  # only the hash is kept
    assert mp.parse_qr(started["qr"]) == {"box": "https://192.168.0.110", "code": raw, "pin": "abc="}

    lim = mp.FailLimiter()
    got = run(mp.claim(store, started["code"].lower().replace("-", " "), device_name="Dale's Pixel",
                       platform="Android", client="10.0.0.5", limiter=lim, now=NOW + timedelta(minutes=2)))
    assert got["device_token"].startswith("mob_") and got["name"] == "Dale's Pixel"
    dev = store.devices[0]
    assert dev["kind"] == "phone" and dev["platform"] == "android" and dev["user_id"] == "user_1"
    with pytest.raises(mp.PairingError) as again:
        run(mp.claim(store, raw, device_name="x", platform="android", client="10.0.0.5", limiter=lim, now=NOW))
    assert again.value.status == 404


def test_expired_codes_fail_and_wrong_codes_are_rate_limited():
    store = mp.MemoryStore()
    started = run(mp.start(store, "u", "https://box", now=NOW))
    lim = mp.FailLimiter(limit=3)
    with pytest.raises(mp.PairingError) as late:
        run(mp.claim(store, started["code"], device_name="", platform="ios", client="a", limiter=lim,
                     now=NOW + mp.CODE_TTL + timedelta(seconds=1)))
    assert late.value.status == 404
    for _ in range(2):
        with pytest.raises(mp.PairingError):
            run(mp.claim(store, "ZZZZZZZZ", device_name="", platform="ios", client="a", limiter=lim, now=NOW))
    with pytest.raises(mp.PairingError) as blocked:
        run(mp.claim(store, "ZZZZZZZZ", device_name="", platform="ios", client="a", limiter=lim, now=NOW))
    assert blocked.value.status == 429
    # another phone on another address is not blocked
    fresh = run(mp.start(store, "u", "https://box", now=NOW))
    assert run(mp.claim(store, fresh["code"], device_name="", platform="ios", client="b", limiter=lim, now=NOW))["name"] == "iPhone"


def test_open_code_limit_and_platform_check():
    store = mp.MemoryStore()
    for _ in range(mp.MAX_OPEN_CODES):
        run(mp.start(store, "u", "https://box", now=NOW))
    with pytest.raises(mp.PairingError) as many:
        run(mp.start(store, "u", "https://box", now=NOW))
    assert many.value.status == 429
    code = run(mp.start(store, "v", "https://box", now=NOW))["code"]
    with pytest.raises(mp.PairingError) as bad:
        run(mp.claim(store, code, device_name="", platform="windows", client="c", limiter=mp.FailLimiter(), now=NOW))
    assert bad.value.status == 400


def test_qr_parser_rejects_foreign_links():
    assert mp.parse_qr("https://evil.example/pair?code=ABCDEFGH") == {}
    assert mp.parse_qr("heirloom://pair?box=javascript:alert(1)&code=ABCDEFGH") == {}
    assert mp.parse_qr("heirloom://pair?box=https://b&code=SHORT") == {}
