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
    SIMPLE_SETUP,
    assert_setup_payload_safe,
    consent_is_given,
    default_recipe_for,
    host_is_allowed,
    is_known_angle,
    is_known_engine,
    is_known_kind,
    normalize_body,
    pick_pinokio_asset,
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
    setup = cat["setup"]
    assert setup is SIMPLE_SETUP
    assert setup["no_accounts"] is True
    assert setup["no_passwords"] is True
    assert "never" in setup["consent"].lower()
    assert "password" in setup["consent"].lower()
    assert all(u.startswith("https://pinokio.co/") for u in setup["apps"])
    assert len(setup["steps"]) >= 4


_GH = "https://github.com/pinokiocomputer/pinokio/releases/download/v8.0.40"


def _asset(name: str, host: str = "github.com") -> dict:
    if host == "github.com":
        url = f"{_GH}/{name}"
    else:
        url = f"https://{host}/{name}"
    return {"name": name, "browser_download_url": url}


PINOKIO_ASSETS = [
    _asset("Pinokio.exe.blockmap"),
    _asset("Pinokio.exe"),
    _asset("Pinokio-8.0.40-arm64.dmg"),
    _asset("Pinokio-8.0.40.dmg"),
    _asset("Pinokio-8.0.40.AppImage"),
    _asset("Pinokio-8.0.40-arm64.AppImage"),
    _asset("Pinokio-8.0.40-amd64.deb"),
    {"name": "evil.exe", "browser_download_url": "https://evil.example/Pinokio.exe"},
]


def test_host_allowlist_only_github_release_hosts():
    assert host_is_allowed(f"{_GH}/Pinokio.exe")
    assert host_is_allowed("https://objects.githubusercontent.com/foo")
    assert host_is_allowed("https://github-releases.githubusercontent.com/foo")
    assert not host_is_allowed("https://evil.example/Pinokio.exe")
    assert not host_is_allowed("https://github.com.evil.com/x")
    assert not host_is_allowed("")


def test_pick_pinokio_asset_windows_mac_linux():
    win = pick_pinokio_asset(PINOKIO_ASSETS, "Windows", "AMD64")
    assert win is not None
    assert win["name"] == "Pinokio.exe"
    mac_arm = pick_pinokio_asset(PINOKIO_ASSETS, "Darwin", "arm64")
    assert mac_arm["name"] == "Pinokio-8.0.40-arm64.dmg"
    mac_intel = pick_pinokio_asset(PINOKIO_ASSETS, "macOS", "x86_64")
    assert mac_intel["name"] == "Pinokio-8.0.40.dmg"
    linux = pick_pinokio_asset(PINOKIO_ASSETS, "Linux", "x86_64")
    assert linux["name"] == "Pinokio-8.0.40.AppImage"
    linux_arm = pick_pinokio_asset(PINOKIO_ASSETS, "Linux", "aarch64")
    assert linux_arm["name"] == "Pinokio-8.0.40-arm64.AppImage"


def test_pick_pinokio_ignores_blockmap_and_foreign_hosts():
    only_bad = [
        _asset("Pinokio.exe.blockmap"),
        {"name": "Pinokio.exe", "browser_download_url": "https://evil.example/Pinokio.exe"},
    ]
    assert pick_pinokio_asset(only_bad, "Windows", "AMD64") is None


def test_setup_requires_consent_and_rejects_passwords():
    assert consent_is_given({"consent": True})
    assert consent_is_given({"consent": "yes"})
    assert not consent_is_given({"consent": False})
    assert not consent_is_given({})
    assert_setup_payload_safe({"consent": True})
    try:
        assert_setup_payload_safe({"consent": False})
        raise AssertionError("expected consent error")
    except ValueError as exc:
        assert "Tick the box" in str(exc)
    try:
        assert_setup_payload_safe({"consent": True, "password": "grandma-birthday"})
        raise AssertionError("expected password reject")
    except ValueError as exc:
        assert "never" in str(exc).lower()
        assert "password" in str(exc).lower()
    try:
        assert_setup_payload_safe({"consent": True, "email": "a@b.c"})
        raise AssertionError("expected email reject")
    except ValueError as exc:
        assert "account" in str(exc).lower()


def test_companion_picker_matches_backend():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "companion_desktop"))
    from heirloom.pinokio_setup import _pick_local

    picked = _pick_local(PINOKIO_ASSETS, "Windows", "AMD64")
    assert picked is not None
    assert picked["name"] == "Pinokio.exe"
    mac = _pick_local(PINOKIO_ASSETS, "Darwin", "arm64")
    assert mac["name"].endswith("-arm64.dmg")


def test_companion_script_mentions_easy_setup_and_no_passwords():
    companion = Path(__file__).resolve().parents[1] / "routers" / "companion.py"
    text = companion.read_text(encoding="utf-8")
    assert 'COMPANION_SCRIPT_VERSION = "2026.08.15.3"' in text
    assert "def run_avatar_setup" in text
    assert '"avatar_setup"' in text
    assert "No accounts. No passwords." in text
