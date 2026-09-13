"""Heirloom Unbound install sizes — catalog, aliases, planner, manifests."""
from __future__ import annotations

import sys
from pathlib import Path

from studio_setup import (
    PROFILE_ALIASES,
    SPACE_PROFILES,
    clamp_setup,
    normalize_profile_id,
    provision_features,
    provision_manifest,
    recommend_profile,
    setup_catalog,
    space_profile,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "companion_desktop"))
from heirloom.dedicated import apply_machine_role, write_install_profile  # noqa: E402
from heirloom.space_profiles import (  # noqa: E402
    normalize_profile_id as companion_normalize,
    provision_features as companion_features,
    recommend_profile as companion_recommend,
)


def test_canonical_ids_are_the_four_unbound_sizes():
    ids = [p["id"] for p in SPACE_PROFILES]
    assert ids == ["small", "medium", "large", "dedicated"]
    assert {p["label"] for p in SPACE_PROFILES} == {"Small", "Medium", "Large", "Dedicated PC"}


def test_legacy_aliases_map_to_canonical():
    assert PROFILE_ALIASES["lite"] == "small"
    assert PROFILE_ALIASES["full"] == "medium"
    assert PROFILE_ALIASES["max"] == "large"
    assert normalize_profile_id("lite") == "small"
    assert normalize_profile_id("full") == "medium"
    assert normalize_profile_id("max") == "large"
    assert normalize_profile_id("studio") == "large"
    assert normalize_profile_id("SMALL") == "small"
    assert normalize_profile_id("nope") == "medium"
    assert space_profile("lite")["id"] == "small"
    assert space_profile("max")["id"] == "large"


def test_clamp_setup_canonicalizes_and_keeps_aliases_working():
    out = clamp_setup({"space_profile": "max", "vendor_email": "YOU@Example.COM"})
    assert out["space_profile"] == "large"
    assert out["install_profile"] == "large"
    assert out["vendor_email"] == "you@example.com"
    junk = clamp_setup({"space_profile": "huge", "vendor_email": "not-an-email"})
    assert junk["space_profile"] == "medium"
    lite = clamp_setup({"space_profile": "lite"})
    assert lite["space_profile"] == "small"
    assert lite["install_profile"] == "small"


def test_dedicated_writes_install_profile_flag():
    out = clamp_setup({"space_profile": "dedicated", "dedicated_consent": True, "vault_drive": "D:/HeirloomVault"})
    assert out["space_profile"] == "dedicated"
    assert out["install_profile"] == "dedicated"
    assert out["dedicated_consent"] is True
    assert out["vault_drive"] == "D:/HeirloomVault"

    settings = {"space_profile": "medium"}
    write_install_profile(settings, "dedicated")
    assert settings["install_profile"] == "dedicated"
    assert settings["machine_role"] == "dedicated"


def test_dedicated_apply_requires_consent(tmp_path, monkeypatch):
    from heirloom import config as companion_config

    monkeypatch.setattr(companion_config, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(companion_config, "app_data_dir", lambda: tmp_path)
    try:
        apply_machine_role(consent=False)
        raise AssertionError("expected consent error")
    except ValueError as exc:
        assert "Heirloom Unbound" in str(exc)
    result = apply_machine_role(
        consent=True,
        vault_drive=str(tmp_path / "vault"),
        start_with_windows=True,
        power_plan_consent=False,
        branding=True,
    )
    assert result["install_profile"] == "dedicated"
    saved = companion_config.load_settings()
    assert saved["install_profile"] == "dedicated"
    assert saved["machine_role"] == "dedicated"
    assert saved["maintenance_schedule"] == "midnight"
    assert (tmp_path / "branding" / "dedicated.txt").read_text(encoding="utf-8").startswith("Heirloom Unbound · Dedicated")


def test_planner_recommends_dedicated_only_when_huge():
    assert recommend_profile(10) == "small"
    assert recommend_profile(39) == "small"
    assert recommend_profile(40) == "medium"
    assert recommend_profile(99) == "medium"
    assert recommend_profile(100) == "large"
    assert recommend_profile(179) == "large"
    assert recommend_profile(180) == "dedicated"
    assert recommend_profile(400) == "dedicated"
    assert recommend_profile(None) == "small"
    assert companion_recommend(180) == "dedicated"
    assert companion_recommend(50) == "medium"


def test_provision_features_per_tier():
    assert provision_features("small") == ["stt", "tts"]
    assert "twin" not in provision_features("small")
    assert "ollama" not in " ".join(provision_features("small"))
    med = provision_features("medium")
    assert "twin" in med and "voice_clone" in med
    assert "latentsync" not in med
    large = provision_features("large")
    assert "vision" in large and "voicebox" in large and "qwen3_tts" in large and "latentsync" in large
    ded = provision_features("dedicated")
    assert "machine_role" in ded
    assert set(large) <= set(ded)
    assert provision_features("lite") == provision_features("small")
    assert provision_features("full") == provision_features("medium")
    assert provision_features("max") == provision_features("large")
    assert companion_features("lite") == provision_features("small")
    assert companion_normalize("max") == "large"


def test_provision_manifest_small_has_no_gpu_and_large_documents_goods():
    small = provision_manifest("small")
    assert small["gpu_required"] is False
    assert small["pinokio"] is False
    assert small["abort_on_engine_failure"] is False
    assert small["whisper"] == "base"
    ids = {a["id"] for a in small["artifacts"]}
    assert "whisper-base" in ids
    assert "ollama-llama31" not in ids
    assert "latentsync" not in ids

    large = provision_manifest("large")
    assert large["approx_bytes"] >= 100 * 1024 ** 3
    assert large["whisper"] == "large-v3"
    art = {a["id"] for a in large["artifacts"]}
    assert {"whisper-large-v3", "voicebox", "qwen3-tts-1-7b", "latentsync", "ollama-llava"} <= art
    assert all(a.get("install") != "pinokio" for a in large["artifacts"])

    dedicated = provision_manifest("dedicated")
    assert dedicated["machine_role"] is True
    assert dedicated["warm_engines"] == ["ollama", "voicebox", "qwen3_tts", "latentsync"]


def test_catalog_exposes_aliases_and_unbound_branding():
    cat = setup_catalog()
    assert cat["product"] == "Heirloom Unbound"
    assert cat["full_power_gb"]["min"] == 100
    assert cat["full_power_gb"]["max"] == 160
    assert cat["profile_aliases"]["lite"] == "small"
    assert [p["id"] for p in cat["space_profiles"]] == ["small", "medium", "large", "dedicated"]
    large = next(p for p in cat["space_profiles"] if p["id"] == "large")
    assert large["gb_min"] == 100
    assert "manifest" in large


def test_provision_cli_recommends_without_downloading(capsys):
    from heirloom.provision_cli import main

    assert main(["--recommend-gb", "12"]) == 0
    assert capsys.readouterr().out.strip() == "small"
    assert main(["--recommend-gb", "200"]) == 0
    assert capsys.readouterr().out.strip() == "dedicated"


def test_installer_sources_name_heirloom_unbound_and_four_sizes():
    root = Path(__file__).resolve().parents[2]
    iss = (root / "desktop" / "installer" / "HeirloomUnbound.iss").read_text(encoding="utf-8")
    readme = (root / "desktop" / "installer" / "README.md").read_text(encoding="utf-8")
    assert "Heirloom Unbound Setup" in iss
    assert "Heirloom Unbound" in iss
    for word in ("Small", "Medium", "Large", "Dedicated PC"):
        assert word in iss
        assert word in readme
    assert "Pinokio" in iss
    assert "SmartScreen" in readme
    assert "lite" in readme and "small" in readme.lower()
    bat = (root / "desktop" / "installer" / "Build-HeirloomUnbound-Setup.bat").read_text(encoding="utf-8")
    assert "HeirloomUnboundSetup" in bat
    assert "ISCC" in bat
