"""First-run setup must be grandmother-simple and succeed without extra clicks."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
DESKTOP = ROOT / "companion_desktop"
FRONTEND = REPO / "frontend" / "src" / "pages"
sys.path.insert(0, str(ROOT))


def test_bat_reinstalls_when_requirements_change_and_logs():
    text = (DESKTOP / "Heirloom.bat").read_text(encoding="utf-8", errors="replace")
    assert "requirements.ok" in text
    assert "setup.log" in text
    assert "Python.Python.3.12" in text
    assert "winget" in text
    assert "import PySide6, requests, PIL" in text
    assert "Add python.exe to PATH" in text


def test_companion_page_one_download_and_download_again():
    text = (FRONTEND / "Companion.jsx").read_text(encoding="utf-8")
    assert "Download Heirloom" in text
    assert "Download again" in text
    assert "companion-register" in text
    assert "download-desktop-app" in text
    assert "/companion/devices/${deviceId}/desktop-package" in text or "/companion/devices/${" in text
    assert "tokens can't be retrieved" not in text.lower()
    assert "Issue token" not in text


def test_desktop_package_can_be_redownloaded_without_listing_token():
    text = (ROOT / "routers" / "companion.py").read_text(encoding="utf-8")
    assert 'COMPANION_SCRIPT_VERSION = "2026.08.15.6"' in text
    assert '@router.get("/devices/{device_id}/desktop-package")' in text
    assert "device_token" in text
    assert '{"_id": 0, "device_token": 0}' in text or '"device_token": 0' in text
    assert "def desktop_package_for_device" in text
    assert "User-Agent" in text
    assert "_open_look_app" not in text  # baked script inlines the look-app guard
    assert 'if found:' in text
    assert "liveportrait" in text
    assert "Couldn't copy your photo" in text


def test_queue_setup_requires_front_photo_and_opened_pc():
    text = (ROOT / "services" / "avatar_jobs.py").read_text(encoding="utf-8")
    assert "Add a photo of your face first" in text
    assert 'if not dev.get("last_seen")' in text
    assert "Double-click Heirloom.bat" in text
    assert "Download Heirloom for the home computer first" in text
    assert '("queued", "dispatched", "processing")' in text


def test_pinokio_does_not_open_item_urls_until_installed():
    text = (DESKTOP / "heirloom" / "pinokio_setup.py").read_text(encoding="utf-8")
    assert "def _open_look_app" in text
    assert "_open_look_app(payload.get(\"apps\") or [])" in text
    assert "HeirloomDesktop/1.0" in text
    # LivePortrait URL is only opened after Pinokio itself is found.
    found_block = text.split("if found:", 1)[1].split("else:", 1)[0]
    assert "_open_look_app" in found_block
    else_block = text.split("else:", 1)[1].split("copied = _copy_photos", 1)[0]
    assert "_open_look_app" not in else_block
    assert "Couldn't copy your photo" in text


def test_front_upload_sets_active_face():
    text = (ROOT / "routers" / "avatar_studio.py").read_text(encoding="utf-8")
    assert 'if angle == "front"' in text
    assert '"avatar_source_url": public_url' in text
    assert '"seen": seen' in text
    assert '"next": home_next' in text
    assert "double-click heirloom.bat" in text.lower()


def test_avatar_studio_polls_and_offers_download():
    text = (FRONTEND / "AvatarStudio.jsx").read_text(encoding="utf-8")
    assert "Get Heirloom for this computer" in text
    assert "avatar-get-heirloom" in text
    assert "Try again" in text
    assert "data.home.next" in text
    assert "setInterval" in text
    assert "Add a photo of your face first" in text
    assert "Double-click Heirloom.bat" in text


def test_desktop_crash_writes_setup_log():
    main = (DESKTOP / "heirloom" / "__main__.py").read_text(encoding="utf-8")
    window = (DESKTOP / "heirloom" / "ui" / "main_window.py").read_text(encoding="utf-8")
    readme = (DESKTOP / "README.txt").read_text(encoding="utf-8")
    assert "setup.log" in main
    assert "Download it again from Local PC" in main or "Download Heirloom" in main
    assert "this copy isn’t signed in" in window.lower() or "isn’t signed in" in window
    assert "Download again" in window
    assert "winget" in readme.lower() or "installs it" in readme
    assert "setup.log" in readme
    assert "Download again" in readme


def test_simple_setup_starts_with_the_bat():
    from services.avatar_recipes import SIMPLE_SETUP

    assert SIMPLE_SETUP["steps"][0].startswith("On the home computer")
    assert "Heirloom.bat" in SIMPLE_SETUP["steps"][0]
    assert SIMPLE_SETUP["no_accounts"] is True
    assert SIMPLE_SETUP["no_passwords"] is True
