"""Local first-run vendor URLs — no live API required."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "companion_desktop"))

from heirloom.vendor_handoffs import local_handoffs, provision_features  # noqa: E402


def test_local_handoffs_cover_three_vendors():
    items = local_handoffs("ada@gmail.com")
    ids = [h["id"] for h in items]
    assert ids == ["elevenlabs", "did", "fal"]
    el = items[0]
    assert el["save_path"] == "/voice-clone/api-key"
    steps = {s["id"]: s for s in el["coach_steps"]}
    assert steps["create_account"]["auto_open"] is True
    assert "elevenlabs.io" in steps["create_account"]["open_url"]
    assert "email=ada" in steps["create_account"]["open_url"]
    assert "elevenlabs.io" in steps["create_account"]["open_url"]
    assert steps["verify_email"]["open_url"].startswith("https://mail.google.com")
    assert steps["paste_key"]["kind"] == "paste"
    assert "sk_" in steps["paste_key"]["placeholder"]


def test_provision_features_match_disk_profiles():
    assert provision_features("lite") == ["stt"]
    assert "twin" in provision_features("full")
    assert "vision" in provision_features("max")
    assert provision_features("unknown") == provision_features("full")
