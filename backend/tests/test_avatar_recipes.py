"""Local twin recipes — Pinokio/ComfyUI catalog (no Mongo)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.avatar_recipes import (
    ANGLES,
    BUILDS,
    ENGINES,
    JOB_KINDS,
    PINOKIO_APPS,
    RECIPES,
    default_recipe_for,
    is_known_angle,
    is_known_engine,
    is_known_kind,
    normalize_body,
    public_catalog,
    recipe_for,
    still_prompt,
)


def test_catalog_covers_look_talk_still_and_pinokio_host():
    kinds = {r["kind"] for r in RECIPES}
    assert kinds == {"look", "talk", "still"}
    assert any(a["id"] == "pinokio-liveportrait" for a in PINOKIO_APPS)
    assert any(a["id"] == "pinokio-comfy" for a in PINOKIO_APPS)
    assert recipe_for("liveportrait")["kind"] == "look"
    assert recipe_for("echomimic")["kind"] == "talk"
    assert recipe_for("instantid")["kind"] == "still"
    assert recipe_for("nope") is None


def test_defaults_and_known_ids():
    assert default_recipe_for("look")["id"] == "liveportrait"
    assert default_recipe_for("talk")["id"] == "echomimic"
    assert default_recipe_for("still")["id"] == "instantid"
    assert is_known_kind("look") and is_known_kind("talk") and is_known_kind("still")
    assert not is_known_kind("deepfake")
    assert is_known_angle("full") and is_known_angle("three_quarter")
    assert not is_known_angle("back")
    assert set(ANGLES) == {"front", "left", "right", "three_quarter", "full"}
    assert is_known_engine("auto") and is_known_engine("local") and is_known_engine("did")
    assert not is_known_engine("runway")
    assert set(ENGINES) == {"auto", "local", "did"}
    assert "average" in BUILDS
    assert all(r["pinokio_url"].startswith("https://") for r in RECIPES)
    assert all(r["vram_gb"] >= 6 for r in RECIPES)


def test_normalize_body_clamps_and_defaults():
    raw = {
        "height_cm": "400",
        "weight_kg": "5",
        "build": "hero",
        "presentation": "??",
        "notes": "x" * 800,
    }
    body = normalize_body(raw)
    assert body["height_cm"] == 230
    assert body["weight_kg"] == 30
    assert body["build"] == "average"
    assert body["presentation"] == "unspecified"
    assert len(body["notes"]) == 500


def test_normalize_body_empty_and_valid():
    empty = normalize_body(None)
    assert empty["height_cm"] is None
    assert empty["build"] == "average"
    ok = normalize_body({"height_cm": 178, "build": "athletic", "presentation": "masculine", "notes": "glasses"})
    assert ok["height_cm"] == 178
    assert ok["build"] == "athletic"
    assert ok["presentation"] == "masculine"
    assert ok["notes"] == "glasses"


def test_still_prompt_includes_measurements():
    prompt = still_prompt({"height_cm": 165, "build": "slim", "presentation": "feminine", "notes": "curly hair"})
    assert "165" in prompt
    assert "slim" in prompt
    assert "feminine" in prompt
    assert "curly hair" in prompt
    assert "reference photos" in prompt
    extra = still_prompt({}, extra="wearing a red coat")
    assert "red coat" in extra


def test_public_catalog_honest_and_complete():
    cat = public_catalog()
    assert "home computer" in cat["honest"]
    assert cat["recipes"] is RECIPES
    assert cat["pinokio"] is PINOKIO_APPS
    assert set(cat["angles"]) == set(ANGLES)
    assert set(JOB_KINDS) == {"still", "talk", "look"}
    blob = " ".join(r["blurb"] for r in RECIPES).lower()
    assert "webcam" in blob or "look" in blob
