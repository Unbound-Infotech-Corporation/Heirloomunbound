"""Smoke tests for live twin / OBS setup helpers (no live HTTP required)."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_avatar_studio_auto_activates_front():
    src = (ROOT / "routers" / "avatar_studio.py").read_text(encoding="utf-8")
    assert 'angle == "front"' in src
    assert "activated_as_twin" in src
    assert "avatar_source_url" in src


def test_avatar_poll_publishes_to_live():
    src = (ROOT / "routers" / "avatar.py").read_text(encoding="utf-8")
    assert "publish_avatar" in src
    assert 'status == "done"' in src


def test_live_me_reports_custom_face():
    src = (ROOT / "routers" / "live.py").read_text(encoding="utf-8")
    assert "has_custom_face" in src
    assert "using_default_face" in src
    assert "Upload your face first" in src


def test_twin_live_obs_mode_in_frontend():
    src = (ROOT / ".." / "frontend" / "src" / "pages" / "TwinLive.jsx").read_text(
        encoding="utf-8"
    )
    assert "obs-mode" in src
    assert 'data-testid="live-obs"' in src
    assert "obsMode" in src


def test_css_has_obs_transparency():
    css = (ROOT / ".." / "frontend" / "src" / "index.css").read_text(encoding="utf-8")
    assert "html.obs-mode" in css
    assert "transparent !important" in css
