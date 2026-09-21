"""VR compatibility catalog and OpenXR probe — no vendor binaries."""
from pathlib import Path

from vr_compat import CATALOG_PATH, headset_ids, load_catalog, probe_openxr, public_catalog, read_openxr_runtime

ROOT = Path(__file__).resolve().parents[2]


def test_catalog_covers_requested_tiers():
    data = load_catalog()
    ids = {h["id"] for h in data["headsets"]}
    assert {"quest", "index", "vive", "wmr", "pico", "psvr2", "alvr_other", "vision_pro", "cardboard"} <= ids
    tiers = {h["id"]: h["tier"] for h in data["headsets"]}
    assert tiers["quest"] == "A"
    assert tiers["index"] == "A"
    assert tiers["pico"] == "B"
    assert tiers["psvr2"] == "B"
    assert tiers["vision_pro"] == "C"
    assert tiers["cardboard"] == "C"
    assert data["headsets"][3]["id"] == "wmr"
    wmr = next(h for h in data["headsets"] if h["id"] == "wmr")
    assert wmr.get("deprecated") is True


def test_software_links_are_official_and_unbundled():
    data = load_catalog()
    sw = data["software"]
    assert sw["meta_horizon_link"]["free"] is True
    assert "oculus.com/download_app" in sw["meta_horizon_link"]["url"]
    assert sw["alvr"]["url"].startswith("https://github.com/alvr-org/ALVR")
    assert sw["pico_connect"]["url"].startswith("https://www.picoxr.com/")
    assert "2580190" in sw["psvr2_app"]["url"]
    assert sw["virtual_desktop"]["free"] is False
    assert sw["virtual_desktop"]["kind"] == "paid_optional"
    assert "crack" not in sw["virtual_desktop"]["url"].lower()
    legal = data["legal"]
    assert legal["no_cracks"] is True
    assert legal["no_bundled_installers"] is True
    catalog_text = CATALOG_PATH.read_text(encoding="utf-8").lower()
    assert "cracked" in catalog_text
    assert ".exe" not in catalog_text or "add_runtime.bat" in catalog_text


def test_psvr2_is_not_alvr():
    data = load_catalog()
    psvr = next(h for h in data["headsets"] if h["id"] == "psvr2")
    assert "alvr" not in psvr["paths"]
    assert psvr["recommended_path"] == "psvr2_adapter"
    steps = " ".join(s["body"] for s in data["checklists"]["psvr2_adapter"])
    assert "ALVR" in steps or "alvr" in steps.lower()
    assert "DisplayPort" in steps or "DP 1.4" in steps


def test_public_catalog_refuses_binary_redistribution():
    pub = public_catalog()
    assert pub["redistributes_binaries"] is False
    assert headset_ids()


def test_openxr_probe_reads_runtime_json(tmp_path, monkeypatch):
    runtime = tmp_path / "active_runtime.json"
    runtime.write_text(
        '{"file_format_version":"1.0.0","runtime":{"name":"SteamVR","library_path":"steamxr_win64.dll"}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENXR_RUNTIME_JSON", str(runtime))
    hit = probe_openxr()
    assert hit["found"] is True
    assert hit["runtime_name"] == "SteamVR"
    missing = tmp_path / "nope.json"
    assert read_openxr_runtime(missing) is None


def test_markdown_matrix_lists_every_headset():
    md = (ROOT / "docs" / "vr-compatibility.md").read_text(encoding="utf-8")
    for name in ("Quest", "Index", "Pico", "PSVR2", "Vision Pro", "Cardboard", "ALVR", "OpenXR"):
        assert name in md
    assert "Virtual Desktop" in md
    assert "crack" in md.lower() or "cracked" in md.lower()
    assert "add_runtime.bat" in md


def test_vr_routes_are_registered_before_room_id():
    """Static /rooms/vr must not be captured as a room_id."""
    vr_src = (ROOT / "backend" / "routers" / "vr_setup.py").read_text(encoding="utf-8")
    rooms_src = (ROOT / "backend" / "routers" / "rooms.py").read_text(encoding="utf-8")
    assert 'prefix="/rooms/vr"' in vr_src
    assert 'prefix="/rooms"' in rooms_src
    server = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    assert "vr_setup.router" in server
    assert server.index("vr_setup.router") < server.index("rooms.router")


def test_heir_portal_does_not_link_vr_setup():
    portal = (ROOT / "frontend" / "src" / "pages" / "HeirPortal.jsx").read_text(encoding="utf-8")
    assert "/rooms/vr" not in portal
    assert "vr-headsets" not in portal


def test_public_help_vr_routes_are_unprotected():
    app = (ROOT / "frontend" / "src" / "App.js").read_text(encoding="utf-8")
    assert 'path="/support/vr"' in app
    assert 'path="/support/vr/matrix"' in app
    assert app.index('path="/support/vr"') < app.index('path="/rooms/vr"')
    support = (ROOT / "frontend" / "src" / "pages" / "Support.jsx").read_text(encoding="utf-8")
    assert 'to="/support/vr"' in support
