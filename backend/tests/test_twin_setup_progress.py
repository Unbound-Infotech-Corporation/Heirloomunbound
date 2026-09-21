"""Twin first-run progress: voice + likeness photos, dismissible coach."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio_setup import (
    LIKENESS_PHOTOS_NEEDED,
    TWIN_DEFAULT_AVATAR_SOURCE,
    TWIN_SETUP_STEPS,
    build_twin_setup_progress,
    clamp_setup,
    setup_catalog,
)


def test_incomplete_account_shows_critical_coach():
    out = build_twin_setup_progress()
    assert out["visible"] is True
    assert out["youre_set"] is False
    assert out["remaining_critical"] == 2
    assert out["voice_ready"] is False
    assert out["likeness_ready"] is False
    assert out["likeness_needed"] == LIKENESS_PHOTOS_NEEDED
    ids = [s["id"] for s in out["steps"]]
    assert ids == ["voice", "likeness", "avatar"]
    voice = out["steps"][0]
    assert voice["critical"] is True
    assert "your voice" in voice["benefit"].lower() or "speaks as you" in voice["benefit"].lower()
    assert len(voice["examples"]) == 3


def test_voice_and_three_photos_clears_coach():
    out = build_twin_setup_progress(
        voice_id="voice_abc",
        voice_name="Pat",
        photo_count=3,
        avatar_source_url="https://example.com/me.jpg",
    )
    assert out["voice_ready"] is True
    assert out["likeness_ready"] is True
    assert out["avatar_ready"] is True
    assert out["remaining_critical"] == 0
    assert out["all_critical_done"] is True
    assert out["visible"] is False
    assert out["youre_set"] is True
    assert out["voice_name"] == "Pat"


def test_three_avatar_angles_count_as_likeness():
    out = build_twin_setup_progress(
        voice_id="v1",
        avatar_angles={"front", "left", "right"},
    )
    assert out["likeness_have"] == 3
    assert out["likeness_ready"] is True
    assert out["remaining_critical"] == 0
    assert out["visible"] is False


def test_stock_presenter_is_not_your_face():
    out = build_twin_setup_progress(avatar_source_url=TWIN_DEFAULT_AVATAR_SOURCE)
    assert out["avatar_ready"] is False
    assert out["steps"][2]["done"] is False


def test_dismissed_coach_hides_until_reopened():
    hidden = build_twin_setup_progress(coach_dismissed=True, coach_dismissed_at="2026-01-01T00:00:00Z")
    assert hidden["visible"] is False
    assert hidden["coach_dismissed"] is True
    assert hidden["remaining_critical"] == 2
    reopened = build_twin_setup_progress(coach_dismissed=False)
    assert reopened["visible"] is True
    assert reopened["coach_dismissed"] is False


def test_dismissed_flag_clears_once_critical_steps_done():
    out = build_twin_setup_progress(
        voice_id="v1",
        photo_count=3,
        coach_dismissed=True,
        coach_dismissed_at="2026-01-01T00:00:00Z",
    )
    assert out["all_critical_done"] is True
    assert out["coach_dismissed"] is False
    assert out["visible"] is False
    assert out["youre_set"] is True


def test_clamp_setup_persists_coach_dismissal():
    out = clamp_setup({"coach_dismissed": True, "coach_dismissed_at": "2026-09-21T00:00:00Z"})
    assert out["coach_dismissed"] is True
    assert out["coach_dismissed_at"] == "2026-09-21T00:00:00Z"
    cleared = clamp_setup({"coach_dismissed": False})
    assert cleared["coach_dismissed"] is False
    assert cleared["coach_dismissed_at"] is None


def test_catalog_advertises_twin_setup_steps():
    catalog = setup_catalog()
    assert catalog["likeness_photos_needed"] == 3
    ids = [s["id"] for s in catalog["twin_setup_steps"]]
    assert ids == ["voice", "likeness", "avatar"]
    assert TWIN_SETUP_STEPS[0]["href"] == "/setup#voice"
    assert "VR" in TWIN_SETUP_STEPS[0]["unlocks"][2] or "Room" in TWIN_SETUP_STEPS[0]["unlocks"][2]


def test_partial_photos_keeps_likeness_open():
    out = build_twin_setup_progress(voice_id="v1", photo_count=1, avatar_angles={"front"})
    assert out["likeness_have"] == 1
    assert out["likeness_ready"] is False
    assert out["remaining_critical"] == 1
    assert out["visible"] is True
    assert out["steps"][1]["have"] == 1
    assert out["steps"][1]["needed"] == 3
