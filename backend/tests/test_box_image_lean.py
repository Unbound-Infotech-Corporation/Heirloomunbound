"""The box images carry only what the server uses."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_server_requirements_skip_the_desktop_gui_and_unused_cloud_packages():
    req = (ROOT / "backend" / "requirements.txt").read_text(encoding="utf-8").lower()
    for name in ("pyside6", "shiboken6", "pandas==", "boto3==", "botocore==", "s3transfer==", "jq=="):
        assert name not in req, name
    # The desktop zip still asks the owner's PC for its GUI toolkit.
    desktop = (ROOT / "backend" / "companion_desktop" / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "pyside6" in desktop


def test_gcc_does_not_stay_in_the_api_image():
    api = (ROOT / "box" / "Dockerfile.api").read_text(encoding="utf-8")
    install = api.index("apt-get install -y --no-install-recommends gcc")
    purge = api.index("apt-get purge -y --auto-remove gcc")
    assert install < purge
    assert "RUN" not in api[install:purge]  # one layer


def test_the_web_image_ships_no_source_maps():
    web = (ROOT / "box" / "Dockerfile.web").read_text(encoding="utf-8")
    assert "GENERATE_SOURCEMAP=false" in web
