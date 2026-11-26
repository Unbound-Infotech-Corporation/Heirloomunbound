"""Step 4: Heirloom on one Windows PC. Config, tier choice, disk check, web serving. No network."""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "heirloom")

import pytest  # noqa: E402

import local_box  # noqa: E402
import model_tiers  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def hw(vram: int, ram: int = 65536, vendor: str = "nvidia") -> model_tiers.Hardware:
    return model_tiers.Hardware(vendor=vendor, gpu="test", vram_mib=vram, ram_mib=ram)


@pytest.mark.parametrize("vram,vendor,ram,tier,model,voice", [
    (32607, "nvidia", 65536, "xl", "gemma4:26b", True),     # RTX 5090
    (24576, "nvidia", 65536, "large", "gemma4:12b", True),  # RTX 3090
    (16384, "nvidia", 32768, "medium", "gemma4:12b", True),
    (12288, "nvidia", 32768, "small", "qwen3.5:4b", True),
    (8192, "nvidia", 16384, "compact", "qwen3.5:4b", False),
    (0, "none", 16384, "cpu", "gemma4:e4b", False),
    (0, "none", 8192, "cpu", "gemma4:e2b", False),
    (8192, "intel", 16384, "cpu", "gemma4:e4b", False),     # Intel iGPU: CPU tier
])
def test_plan_follows_the_tier_table(tmp_path, monkeypatch, vram, vendor, ram, tier, model, voice):
    monkeypatch.delenv("HEIRLOOM_MODEL_OVERRIDE", raising=False)
    out = local_box.plan(tmp_path, hardware=hw(vram, ram, vendor))
    assert (out["tier"], out["model"], out["voice"]) == (tier, model, voice)
    assert out["need_gb"] == local_box.need_gb(model, voice)
    assert out["whisper_device"] == ("cuda" if vendor == "nvidia" and vram >= 6144 else "cpu")


def test_disk_check_blocks_a_full_drive(tmp_path, monkeypatch):
    monkeypatch.setattr(local_box, "free_gb", lambda path: 12.0)
    out = local_box.plan(tmp_path, hardware=hw(32607))
    assert out["need_gb"] > 12 and out["disk_ok"] is False
    assert local_box.need_gb("qwen3.5:4b", False) < local_box.need_gb("gemma4:26b", True)


def test_init_writes_local_only_env_and_keeps_secrets_and_owner_edits(tmp_path):
    data, web = tmp_path / "data", tmp_path / "web"
    chosen = local_box.plan(data, hardware=hw(24576))
    local_box.init(data, web, api_port=18101, mongo_port=27181, chosen=chosen)
    env = local_box.read_env(data / "heirloom.env")
    assert env["MONGO_URL"] == "mongodb://127.0.0.1:27181" and env["HEIRLOOM_API_PORT"] == "18101"
    assert env["OLLAMA_TWIN_MODEL"] == "gemma4:12b" and env["OLLAMA_CONTEXT_LENGTH"] == "16384"
    assert env["HEIRLOOM_BOX"] == "1" and env["HEIRLOOM_DATA_DIR"] == str(data)
    for cloud in ("EMERGENT_LLM_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY"):
        assert cloud not in env
    assert len(env["CONNECTOR_SECRET_KEY"]) >= 40
    for sub in ("mongo", "owner", "vault", "files", "skills", "whisper"):
        assert (data / sub).is_dir()
    # Re-running setup keeps the connector key (sealed tokens stay readable) and hand edits.
    with (data / "heirloom.env").open("a", encoding="utf-8") as fh:
        fh.write("HEIRLOOM_SEARXNG_URL=http://127.0.0.1:8888\n")
    local_box.init(data, web, api_port=18101, mongo_port=27181, chosen=chosen)
    again = local_box.read_env(data / "heirloom.env")
    assert again["CONNECTOR_SECRET_KEY"] == env["CONNECTOR_SECRET_KEY"]
    assert again["HEIRLOOM_SEARXNG_URL"] == "http://127.0.0.1:8888"


def test_set_owner_stores_only_a_hash(tmp_path, monkeypatch):
    data = tmp_path / "data"
    local_box.init(data, tmp_path / "web", chosen=local_box.plan(data, hardware=hw(0, 16384, "none")))
    for key in list(os.environ):
        if key.startswith("HEIRLOOM_"):
            monkeypatch.delenv(key, raising=False)
    local_box.set_owner(data, "Owner@Example.com", "correct horse battery")
    text = (data / "owner" / "owner.pass").read_text()
    assert "email=owner@example.com" in text and "hash=" in text and "correct horse" not in text
    from box_owner import verify_owner_password

    assert verify_owner_password("owner@example.com", "correct horse battery", data / "owner" / "owner.pass")
    with pytest.raises(ValueError):
        local_box.set_owner(data, "owner@example.com", "short")


def test_web_serves_files_and_app_routes_but_not_api_or_escapes(tmp_path):
    import local_web

    (tmp_path / "static").mkdir()
    (tmp_path / "index.html").write_text('<div id="root"></div>')
    (tmp_path / "static" / "main.js").write_text("x")
    assert local_web.resolve(tmp_path, "").name == "index.html"
    assert local_web.resolve(tmp_path, "static/main.js").name == "main.js"
    assert local_web.resolve(tmp_path, "life-story").name == "index.html"
    for bad in ("api/health", "static/missing.js", "../secret.txt", "..\\..\\x.js"):
        with pytest.raises(FileNotFoundError):
            local_web.resolve(tmp_path, bad)


def test_csharp_tier_table_matches_python():
    """desktop ModelTiers.cs must pick what model_tiers.py picks."""
    import re

    src = (REPO / "desktop" / "Heirloom.BoxCore" / "ModelTiers.cs").read_text(encoding="utf-8")
    rows = re.findall(r'new\("(\w+)",\s*(\d+),\s*"([^"]+)",\s*"([^"]+)",\s*(\d+),\s*(\d+),\s*(true|false)\)', src)
    py = [(t.name, t.min_vram_mib, t.model, t.fallback, t.num_ctx, t.loaded_mib, t.voice_on_gpu) for t in model_tiers.TIERS]
    cs = [(n, int(v), m, f, int(c), int(l), b == "true") for n, v, m, f, c, l, b in rows]
    assert cs == py
    for name in ("BaseReserveMib", "VoiceReserveMib"):
        value = int(re.search(rf"{name}\s*=\s*(\d+)", src).group(1))
        assert value == getattr(model_tiers, "BASE_RESERVE_MIB" if name.startswith("Base") else "VOICE_RESERVE_MIB")


def test_installer_scripts_never_touch_the_desktop_app_folder_or_cloud_keys():
    folder = REPO / "desktop" / "installer" / "local-box"
    text = "\n".join(p.read_text(encoding="utf-8") for p in folder.glob("*.ps1"))
    assert "Fail \"C:\\Heirloom belongs to the Heirloom desktop app" in text
    for cloud in ("EMERGENT_LLM_KEY", "OPENAI_API_KEY", "api.openai.com", "anthropic"):
        assert cloud not in text
    assert "--bind_ip\", \"127.0.0.1\"" in text and "host\", \"127.0.0.1\"" in text


def test_installer_scripts_are_plain_ascii():
    """Windows PowerShell 5.1 reads a .ps1 without a BOM as ANSI: keep them ASCII so strangers see clean text."""
    for script in sorted((REPO / "desktop" / "installer" / "local-box").glob("*.ps1")):
        script.read_bytes().decode("ascii")


def test_env_keeps_every_folder_inside_the_data_folder(tmp_path):
    import local_box

    info = local_box.init(tmp_path / "data", tmp_path / "web", chosen={
        "model": "qwen3.5:4b", "tier": "small", "num_ctx": 8192, "whisper_device": "cpu", "voice": False})
    env = local_box.read_env(Path(info["env"]))
    for key, value in env.items():
        if key.endswith(("_DIR", "_ROOT", "_FILE", "_CACHE", "_HOME")) and key != "HEIRLOOM_WEB_DIR":
            assert "/var/lib" not in value and value.startswith(str(tmp_path)), key


def test_set_owner_from_stdin_drops_the_powershell_bom(tmp_path, monkeypatch):
    import io
    import local_box
    from box_owner import verify_owner_password

    data = tmp_path / "data"
    local_box.init(data, tmp_path / "web", chosen={
        "model": "qwen3.5:4b", "tier": "small", "num_ctx": 8192, "whisper_device": "cpu", "voice": False})
    monkeypatch.setattr("sys.stdin", io.StringIO("\ufeffcorrect horse battery\r\n"))
    assert local_box.main(["set-owner", "--data", str(data), "--email", "Owner@Example.com"]) == 0
    owner = data / "owner" / "owner.pass"
    assert verify_owner_password("owner@example.com", "correct horse battery", owner)

    monkeypatch.setenv("HEIRLOOM_SETUP_PASSWORD", "another good password")
    assert local_box.main(["set-owner", "--data", str(data), "--email", "owner@example.com", "--password-env"]) == 0
    assert verify_owner_password("owner@example.com", "another good password", owner)
    assert "HEIRLOOM_SETUP_PASSWORD" not in os.environ
