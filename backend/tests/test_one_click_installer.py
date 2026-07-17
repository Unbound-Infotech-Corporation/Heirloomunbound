"""Unit tests for the grandmother-friendly one-click Windows installer."""
from __future__ import annotations

import io
import zipfile

import pytest


def test_one_click_zip_contains_install_and_update(monkeypatch):
    monkeypatch.setenv("PUBLIC_BACKEND_URL", "https://heirloomunbound.com")
    from routers.companion import build_one_click_installer_zip_bytes

    token = "comp_test_token_abc123"
    raw = build_one_click_installer_zip_bytes(token, wake_word=False)
    zf = zipfile.ZipFile(io.BytesIO(raw))
    names = set(zf.namelist())
    assert "Double-click me - Install Heirloom.bat" in names
    assert "Update Heirloom.bat" in names
    assert "Read me first.txt" in names

    bat = zf.read("Double-click me - Install Heirloom.bat").decode("utf-8")
    assert token in bat
    assert "https://heirloomunbound.com" in bat
    assert "public-script" in bat
    assert "python-3.12.8-embed-amd64.zip" in bat  # portable Python fallback
    assert "winget install" in bat
    assert "Start Menu\\Programs\\Startup" in bat or "Startup\\Heirloom" in bat

    update = zf.read("Update Heirloom.bat").decode("utf-8")
    assert token in update
    assert "public-script" in update

    readme = zf.read("Read me first.txt").decode("utf-8")
    assert "Double-click" in readme


def test_one_click_requires_public_backend_url(monkeypatch):
    monkeypatch.delenv("PUBLIC_BACKEND_URL", raising=False)
    from fastapi import HTTPException
    from routers import companion as companion_mod

    with pytest.raises(HTTPException):
        companion_mod.build_one_click_installer_zip_bytes("comp_x")


def test_advanced_windows_zip_still_available(monkeypatch):
    monkeypatch.setenv("PUBLIC_BACKEND_URL", "https://heirloomunbound.com")
    from routers.companion import build_windows_zip_bytes

    raw = build_windows_zip_bytes("comp_adv_token")
    zf = zipfile.ZipFile(io.BytesIO(raw))
    assert "heirloom_companion.py" in zf.namelist()
    assert "Heirloom.bat" in zf.namelist()
    py = zf.read("heirloom_companion.py").decode("utf-8")
    assert "comp_adv_token" in py
    assert "Check for updates" in py
