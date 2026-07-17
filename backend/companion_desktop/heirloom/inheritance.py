"""Inheritance Vault — export a portable Legacy Package from the desktop app.

Two layers:
1. Cloud package via GET /legacy/export (archive, personality, facts, letters)
2. Local vault snapshot (Documents/HeirloomVault journals + audio metadata)

Combined into one zip the owner can put on a USB drive or give to heirs.
"""
from __future__ import annotations

import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from . import config
from .vault import vault_root


def _api(path: str) -> str:
    return f"{config.BACKEND_URL.rstrip('/')}/api{path}"


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.DEVICE_TOKEN}"}


def export_inheritance_package(dest_dir: Optional[Path] = None) -> Path:
    """Build a combined Legacy Package zip. Returns the path written."""
    dest_dir = Path(dest_dir) if dest_dir else Path.home() / "Documents" / "HeirloomLegacy"
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    out = dest_dir / f"Heirloom-Inheritance-{stamp}.zip"

    # Fetch cloud package bytes (already a zip)
    cloud_bytes: Optional[bytes] = None
    cloud_error = None
    try:
        # Session auth isn't available on device token for /legacy/export —
        # so we rebuild a local-only package + attempt export via desktop me.
        # Prefer /legacy/export if the device token is accepted; otherwise
        # package the local vault and a status snapshot.
        r = requests.get(_api("/legacy/export-device"), headers=_headers(), timeout=120)
        if r.status_code == 200 and (
            "zip" in (r.headers.get("content-type") or "")
            or r.content[:2] == b"PK"
        ):
            cloud_bytes = r.content
        else:
            cloud_error = f"HTTP {r.status_code}: {(r.text or '')[:200]}"
    except Exception as exc:  # noqa: BLE001
        cloud_error = str(exc)

    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "README.txt",
            (
                "Heirloom Inheritance Package (desktop)\n"
                "======================================\n\n"
                "This zip was built by the Heirloom Windows app.\n"
                "It contains:\n"
                "  • local_vault/ — journals and transcripts from this PC\n"
                "  • cloud_legacy.zip — full cloud Inheritance Package (when available)\n"
                "  • desktop_manifest.json — device + export metadata\n\n"
                "Give this to your heirs alongside their Heir Portal link.\n"
            ),
        )
        manifest = {
            "exported_at": datetime.now().isoformat(),
            "backend": config.BACKEND_URL,
            "cloud_package_included": bool(cloud_bytes),
            "cloud_error": cloud_error,
            "vault_root": str(vault_root()),
        }
        zf.writestr("desktop_manifest.json", json.dumps(manifest, indent=2))

        if cloud_bytes:
            zf.writestr("cloud_legacy.zip", cloud_bytes)

        # Snapshot local vault (skip huge audio binaries in lite mode)
        root = vault_root()
        settings = config.load_settings()
        tier = (settings.get("storage_tier") or "partial").lower()
        if root.exists():
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                rel = path.relative_to(root)
                # Skip heavy audio in lite/partial to keep USB packages small
                if tier in ("lite", "partial") and path.suffix.lower() in {".wav", ".mp3", ".ogg", ".webm"}:
                    continue
                arcname = f"local_vault/{rel.as_posix()}"
                try:
                    zf.write(path, arcname)
                except Exception:
                    pass

    return out


def enable_windows_autostart() -> bool:
    """Create a Startup-folder shortcut to Heirloom.bat / the running exe."""
    import sys
    if sys.platform != "win32":
        return False
    try:
        startup = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        startup.mkdir(parents=True, exist_ok=True)
        link = startup / "Heirloom.lnk"
        # Prefer the running executable; fall back to a pythonw -m heirloom
        target = sys.executable
        args = ""
        if target.lower().endswith("python.exe") or target.lower().endswith("pythonw.exe"):
            target = target.replace("python.exe", "pythonw.exe")
            args = "-m heirloom"
        # Write a tiny VBScript to create the .lnk (no pywin32 dependency)
        vbs = (
            f'Set o = CreateObject("WScript.Shell")\n'
            f'Set s = o.CreateShortcut("{link}")\n'
            f's.TargetPath = "{target}"\n'
            f's.Arguments = "{args}"\n'
            f's.WorkingDirectory = "{Path(target).parent}"\n'
            f's.Description = "Heirloom Twin"\n'
            f's.Save\n'
        )
        script = config.app_data_dir() / "_autostart.vbs"
        script.write_text(vbs)
        import subprocess
        subprocess.run(["cscript", "//Nologo", str(script)], check=False, capture_output=True)
        return link.exists()
    except Exception:
        return False
