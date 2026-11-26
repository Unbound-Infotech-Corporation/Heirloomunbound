"""Twilio bridge: config placeholders, signature check, TwiML, audio cache. No network, no account."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import twilio_bridge as tb  # noqa: E402

PARAMS = {"CallSid": "CA1234567890ABCDE", "Caller": "+12349013030", "Digits": "1234",
          "From": "+12349013030", "To": "+18005551212"}
URL = "https://example.com/myapp.php?foo=1&bar=2"
# Computed with twilio.request_validator.RequestValidator("12345").compute_signature(URL, PARAMS).
OFFICIAL = "vNe7KK2kJwCsxc9K3OLkkKB3qqI="


def test_default_is_off_and_placeholders_are_not_ready():
    assert tb.config({}).mode == "off" and not tb.config({}).ready
    cfg = tb.config({"TWILIO_MODE": "live", "TWILIO_ACCOUNT_SID": "ACREPLACE_ME", "TWILIO_AUTH_TOKEN": "REPLACE_ME",
                     "TWILIO_PHONE_NUMBER": "+15550001111", "HEIRLOOM_PUBLIC_URL": "https://box.example"})
    assert not cfg.ready
    shown = cfg.public()
    assert shown["auth_token"] == "missing" and "REPLACE_ME" not in str(shown)
    assert tb.config({"TWILIO_MODE": "banana"}).mode == "off"
    assert tb.config({"TWILIO_MODE": "mock"}).ready


def test_public_view_never_shows_the_token():
    cfg = tb.config({"TWILIO_MODE": "live", "TWILIO_ACCOUNT_SID": "AC1", "TWILIO_AUTH_TOKEN": "supersecret",
                     "TWILIO_PHONE_NUMBER": "+15550001111", "HEIRLOOM_PUBLIC_URL": "https://box.example/"})
    assert cfg.ready and cfg.public_url == "https://box.example"
    assert "supersecret" not in str(cfg.public()) and cfg.public()["auth_token"] == "set"
    assert not tb.config({**{"TWILIO_MODE": "live", "TWILIO_ACCOUNT_SID": "AC1", "TWILIO_AUTH_TOKEN": "t",
                              "TWILIO_PHONE_NUMBER": "+1555", "HEIRLOOM_PUBLIC_URL": "http://plain.example"}}).ready


def test_signature_matches_twilios_own_validator():
    assert tb.expected_signature("12345", URL, PARAMS) == OFFICIAL


def test_live_requests_need_a_valid_signature_and_mock_needs_loopback():
    live = tb.TwilioConfig("live", "AC1", "12345", "+18005551212", "https://example.com")
    ok = dict(url=URL, params=PARAMS, client_host="54.1.2.3", mock_header="")
    assert tb.request_allowed(live, signature=OFFICIAL, **ok)
    assert not tb.request_allowed(live, signature="", **ok)
    assert not tb.request_allowed(live, signature=OFFICIAL, **{**ok, "params": {**PARAMS, "Digits": "9"}})
    mock = tb.TwilioConfig("mock")
    assert tb.request_allowed(mock, url=URL, params={}, signature="", client_host="127.0.0.1", mock_header="1")
    assert not tb.request_allowed(mock, url=URL, params={}, signature="", client_host="192.168.0.5", mock_header="1")
    assert not tb.request_allowed(mock, url=URL, params={}, signature="", client_host="127.0.0.1", mock_header="")
    assert not tb.request_allowed(tb.TwilioConfig("off"), url=URL, params={}, signature=OFFICIAL,
                                  client_host="127.0.0.1", mock_header="1")


def test_twiml_is_escaped_and_uses_record_and_play_not_twilio_speech():
    xml = tb.twiml(tb.play("https://box/a.wav?x=1&y=2"), tb.record("https://box/api/twilio/voice/turn"))
    assert "&amp;y=2" in xml and "<Record " in xml and "<Gather" not in xml and "<Say" not in xml
    sms = tb.twiml(tb.message("Tom & Jerry <3 " + "x" * 2000))
    assert "Tom &amp; Jerry &lt;3" in sms and len(sms) < tb.MAX_SMS_CHARS + 200


def test_recordings_only_come_from_twilio():
    assert tb.recording_host_ok("https://api.twilio.com/2010-04-01/Accounts/AC1/Recordings/RE1")
    assert not tb.recording_host_ok("http://api.twilio.com/x")
    assert not tb.recording_host_ok("https://evil.example/api.twilio.com")
    assert not tb.recording_host_ok("file:///etc/passwd")
    assert tb.recording_wav_url("https://api.twilio.com/R/RE1").endswith("RE1.wav")


def test_audio_cache_ids_are_safe_and_old_clips_go(tmp_path):
    cache = tb.AudioCache(tmp_path / "audio")
    clip = cache.put(b"RIFF....WAVE")
    assert cache.get(clip) == b"RIFF....WAVE"
    assert cache.get("../../etc/passwd") is None and cache.get("") is None
    old = time.time() - tb.AUDIO_TTL_S - 5
    os.utime(tmp_path / "audio" / f"{clip}.wav", (old, old))
    assert cache.prune() == 1 and cache.get(clip) is None


def test_sms_text_is_plain():
    assert tb.sms_text("**Yes**, Emma caught it.") == "Yes, Emma caught it."
    assert "make it up" in tb.sms_text("")


def test_voice_url_prefers_the_api_view(monkeypatch):
    monkeypatch.setenv("PRESENCE_SPEAK_URL", "http://127.0.0.1:8010/speak")
    monkeypatch.delenv("HEIRLOOM_VOICE_URL", raising=False)
    assert tb.voice_wav_url() == "http://127.0.0.1:8010/speak.wav"
    monkeypatch.setenv("HEIRLOOM_VOICE_URL", "http://chatterbox:8010/speak/")
    assert tb.voice_wav_url() == "http://chatterbox:8010/speak.wav"
