"""Companion local-voice probes — no Qt, no live API."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "companion_desktop"))

from heirloom.engine_probes import probe_latentsync, probe_qwen3_tts, probe_voicebox  # noqa: E402
from heirloom.models import coach_install_lines, full_probe, resolve_tts_backend_local  # noqa: E402
from heirloom.ticket_redact import build_snapshot, redact_text  # noqa: E402


def test_companion_probes_refused_without_crash():
    vb = probe_voicebox("http://127.0.0.1:1")
    q3 = probe_qwen3_tts("http://127.0.0.1:1")
    ls = probe_latentsync("http://127.0.0.1:1")
    assert vb["ready"] is False
    assert q3["ready"] is False
    assert ls["ready"] is False
    assert vb["url"].startswith("http://")


def test_companion_full_probe_has_engine_rows():
    probe = full_probe()
    for key in ("voicebox", "qwen3_tts", "latentsync", "gpu", "ollama", "whisper", "piper"):
        assert key in probe
        assert "ready" in (probe[key] or {})


def test_companion_resolve_prefers_voicebox():
    probe = {"voicebox": {"ready": True}, "qwen3_tts": {"ready": True}}
    assert resolve_tts_backend_local({"tts": "auto"}, probe, has_voice_clone=True) == "voicebox"
    probe["voicebox"] = {"ready": False}
    assert resolve_tts_backend_local({"tts": "auto"}, probe, has_voice_clone=True) == "qwen3_tts"


def test_coach_copy_no_pinokio_and_no_silent_install():
    lines = " ".join(coach_install_lines()).lower()
    assert "pinokio" not in lines or "no pinokio" in lines
    assert "voicebox" in lines
    assert "qwen3" in lines
    assert "does not install" in lines or "never" in lines


def test_companion_ticket_redact():
    assert "sk_live_abcdefghij" not in redact_text("sk_live_abcdefghij")
    snap = build_snapshot(
        build_id="dev",
        companion_version="0.5.0",
        probe={"voicebox": {"ready": False, "url": "http://127.0.0.1:17493"}, "journal": "secret story"},
        model_map={"tts": "auto"},
        compute={"mode": "local"},
        log_lines=["Authorization: Bearer abcdefghijklmnop"],
    )
    blob = str(snap)
    assert "secret story" not in blob
    assert "abcdefghijklmnop" not in blob
