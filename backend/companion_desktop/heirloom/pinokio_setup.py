"""Download and launch official Pinokio on the home PC.

No accounts. No passwords. We only fetch the installer from GitHub releases
(allowlisted hosts) and open the LivePortrait / ComfyUI one-click pages.
Windows SmartScreen still needs one human click — we cannot (and should not)
bypass that.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from . import config


GITHUB_RELEASES = "https://api.github.com/repos/pinokiocomputer/pinokio/releases/latest"
ALLOWED_HOSTS = {
    "api.github.com",
    "github.com",
    "objects.githubusercontent.com",
    "github-releases.githubusercontent.com",
    "release-assets.githubusercontent.com",
}
MAX_INSTALLER_BYTES = 250 * 1024 * 1024
_GH_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "HeirloomDesktop/1.0",
}


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.DEVICE_TOKEN}"}


def _api(path: str) -> str:
    return f"{config.BACKEND_URL.rstrip('/')}/api{path}"


def run_easy_setup(payload: dict) -> tuple[str, str]:
    notes: list[str] = []
    folder = Path.home() / "Heirloom" / "avatar"
    folder.mkdir(parents=True, exist_ok=True)
    inst_dir = Path.home() / "Heirloom" / "installers"
    inst_dir.mkdir(parents=True, exist_ok=True)

    found = _pinokio_exe()
    if found:
        notes.append(f"Pinokio is already on this computer ({found}).")
        _launch_path(found)
        _open_look_app(payload.get("apps") or [])
        notes.append("Opened LivePortrait in Pinokio. Tap Install if it asks.")
    else:
        asset = _latest_installer()
        if not asset:
            return "error", "Couldn't find the official Pinokio download for this computer. Try Set up my twin again in a minute."
        dest = inst_dir / asset["name"]
        if dest.exists() and dest.stat().st_size > 1_000_000:
            notes.append(f"Using the installer already saved at {dest}.")
        else:
            notes.append(f"Downloading {asset['name']}…")
            try:
                _download(asset["url"], dest)
            except Exception as exc:  # noqa: BLE001
                return "error", f"Download failed: {exc}. Check the internet and tap Set up my twin again."
            notes.append(f"Saved installer to {dest}")
        _launch_path(dest)
        notes.append(
            "If a blue Windows box appears, click More info, then Run anyway. Then click Install."
        )

    copied = _copy_photos(folder, payload.get("images") or [])
    wanted = [i for i in (payload.get("images") or []) if isinstance(i, dict) and i.get("image_id")]
    if wanted and copied == 0:
        return "error", "Couldn't copy your photo onto this computer. Tap Set up my twin again."
    if copied:
        notes.append(f"Copied {copied} photo(s) into {folder}")

    readme = folder / "START_HERE.txt"
    readme.write_text(
        "\n".join(
            [
                "Your twin tools install on THIS computer. No extra accounts.",
                "",
                "1. Finish the Pinokio installer if it is on screen.",
                "2. If Windows shows a blue box: More info, then Run anyway.",
                "3. In Pinokio, tap Install on LivePortrait.",
                "4. Go back to Heirloom and tap Look at me.",
                "5. Turn on the webcam when LivePortrait asks.",
            ]
        ),
        encoding="utf-8",
    )
    _open_folder(folder)
    try:
        from .commands import notify_desktop

        notify_desktop("Heirloom", "Installing your twin tools. If Windows asks, click More info, then Run anyway.")
    except Exception:
        pass
    job_id = (payload.get("job_id") or "").strip()
    msg = " ".join(notes) or "Pinokio installer started."
    if job_id:
        try:
            requests.post(
                _api(f"/avatar-studio/jobs/{job_id}/note"),
                headers=_headers(),
                json={"message": msg[:1500]},
                timeout=15,
            )
        except Exception:
            pass
    return "ok", msg[:2000]


def _open_look_app(apps: list) -> None:
    """Open LivePortrait only after Pinokio itself is already installed."""
    urls = [u for u in (apps or []) if isinstance(u, str) and u.startswith("https://")]
    look = [u for u in urls if "liveportrait" in u.lower()]
    chosen = (look or urls)[:1]
    for url in chosen:
        webbrowser.open(url)


def _pinokio_exe() -> str | None:
    which = shutil.which("Pinokio") or shutil.which("pinokio")
    if which:
        return which
    home = Path.home()
    candidates = [
        home / "pinokio" / "Pinokio.exe",
        home / "pinokio" / "Pinokio.app",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Pinokio" / "Pinokio.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Pinokio" / "Pinokio.exe",
        Path("/Applications/Pinokio.app"),
        Path("/usr/local/bin/pinokio"),
    ]
    for p in candidates:
        if p and str(p) != "." and p.exists():
            return str(p)
    return None


def _host_ok(url: str) -> bool:
    host = (urlparse(url or "").hostname or "").lower()
    return host in ALLOWED_HOSTS


def _latest_installer() -> dict[str, str] | None:
    # Stay self-contained — the desktop app does not import backend services.
    last_exc: Exception | None = None
    for _attempt in range(3):
        try:
            r = requests.get(GITHUB_RELEASES, timeout=30, headers=_GH_HEADERS)
            r.raise_for_status()
            assets = (r.json() or {}).get("assets") or []
            picked = _pick_local(assets, platform.system(), platform.machine())
            if not picked or not _host_ok(picked.get("url") or ""):
                return None
            return {
                "name": picked.get("name") or "Pinokio.bin",
                "url": picked["url"],
            }
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
    if last_exc:
        raise last_exc
    return None


def _pick_local(
    assets: list,
    system: str | None = None,
    machine: str | None = None,
) -> dict[str, Any] | None:
    system = system or platform.system()
    machine = (machine or platform.machine() or "").lower()
    arm = machine in ("arm64", "aarch64")
    sys_name = system.lower()
    rows = []
    for raw in assets:
        name = str((raw or {}).get("name") or "")
        url = str((raw or {}).get("browser_download_url") or (raw or {}).get("url") or "")
        if not name or not url or "blockmap" in name.lower() or not _host_ok(url):
            continue
        rows.append({"name": name, "url": url})
    if sys_name.startswith("win"):
        for row in rows:
            if row["name"].lower() == "pinokio.exe":
                return row
        for row in rows:
            n = row["name"].lower()
            if n.endswith(".exe") and "setup" in n:
                return row
        for row in rows:
            if row["name"].lower().endswith(".exe"):
                return row
        return None
    if sys_name in ("darwin", "mac", "macos"):
        dmg = [r for r in rows if r["name"].lower().endswith(".dmg")]
        for row in dmg:
            if ("arm64" in row["name"].lower()) == arm:
                return row
        return dmg[0] if dmg else None
    if arm:
        for row in rows:
            n = row["name"].lower()
            if n.endswith(".appimage") and "arm64" in n:
                return row
    for row in rows:
        n = row["name"].lower()
        if n.endswith(".appimage") and "arm64" not in n:
            return row
    for row in rows:
        if row["name"].lower().endswith(".deb"):
            return row
    return None


def _download(url: str, dest: Path) -> None:
    if not _host_ok(url):
        raise RuntimeError("blocked download host")
    with requests.get(url, stream=True, timeout=120, allow_redirects=True) as r:
        r.raise_for_status()
        final = r.url or url
        if not _host_ok(final):
            raise RuntimeError("blocked download redirect")
        written = 0
        with dest.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                written += len(chunk)
                if written > MAX_INSTALLER_BYTES:
                    raise RuntimeError("installer larger than expected")
                f.write(chunk)


def _launch_path(path: str) -> None:
    p = Path(path)
    try:
        if platform.system() == "Windows":
            os.startfile(str(p))  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", str(p)])
        else:
            if p.suffix.lower() == ".appimage":
                p.chmod(p.stat().st_mode | 0o111)
                subprocess.Popen([str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
    except Exception:
        webbrowser.open(p.as_uri())


def _copy_photos(folder: Path, images: list) -> int:
    got = 0
    for i, item in enumerate(images or []):
        if not isinstance(item, dict):
            continue
        image_id = (item.get("image_id") or "").strip()
        angle = "".join(ch for ch in (item.get("angle") or f"img{i}") if ch.isalnum() or ch == "_")[:24] or f"img{i}"
        data = None
        ct = "image/jpeg"
        if image_id:
            try:
                r = requests.get(_api(f"/avatar-studio/companion-file/{image_id}"), headers=_headers(), timeout=45)
                if r.status_code == 200:
                    data, ct = r.content, r.headers.get("content-type") or ct
            except Exception:
                data = None
        if not data:
            continue
        ext = "png" if "png" in ct else ("webp" if "webp" in ct else "jpg")
        (folder / f"{angle}.{ext}").write_bytes(data)
        if angle == "front" or i == 0:
            (folder / f"front.{ext}").write_bytes(data)
        got += 1
    return got


def _open_folder(folder: Path) -> None:
    path = str(folder)
    try:
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.run(["open", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)
    except Exception:
        pass
