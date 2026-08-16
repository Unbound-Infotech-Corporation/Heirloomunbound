"""Run a creative job on the home PC: folder, prompt, Pinokio, studio app.

The cloud queues `creative_job`. This module writes ~/Heirloom/creative/<stamp>,
copies the prompt to the clipboard, opens Pinokio if needed, and launches the
studio the owner already has (Photoshop, CapCut, Ableton, …). We never wait on
a GPU render — Pinokio / ComfyUI do that in their own window.
"""
from __future__ import annotations

import glob
import os
import platform
import shutil
import subprocess
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def workspace(stamp: str = "") -> Path:
    safe = "".join(ch for ch in (stamp or "") if ch.isalnum() or ch in "-_")[:40]
    if not safe:
        safe = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    folder = Path.home() / "Heirloom" / "creative" / safe
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def run_creative_job(payload: dict) -> tuple[str, str]:
    kind = (payload.get("kind") or "").strip().lower()
    if kind not in ("art", "video", "music", "open"):
        return "error", f"unknown creative kind {kind}"

    notes: list[str] = []
    prompt = (payload.get("prompt") or "").strip()
    folder: Optional[Path] = None
    if kind != "open":
        folder = workspace((payload.get("title") or "").replace(" ", "-")[:24])
        (folder / "prompt.txt").write_text(prompt, encoding="utf-8")
        howto = (payload.get("howto") or "").strip() or "Your description is in prompt.txt.\n"
        (folder / "HOW_TO.txt").write_text(howto, encoding="utf-8")
        if payload.get("source"):
            (folder / "source.txt").write_text(str(payload.get("source")), encoding="utf-8")
        _clipboard_set(prompt)
        notes.append("Copied your description to the clipboard.")
        pinokio = (payload.get("pinokio_url") or "").strip()
        if pinokio:
            webbrowser.open(pinokio)
            notes.append("Opened Pinokio so the local model can install or run.")
        _open_folder(folder)
        notes.append(f"Folder: {folder}")

    opened, how = _open_studio(payload)
    if opened:
        notes.append(how)
    else:
        fallback = (payload.get("fallback_url") or payload.get("studio_url") or "").strip()
        if fallback:
            webbrowser.open(fallback)
            notes.append(f"Couldn't find {payload.get('studio_label') or 'that app'} on this PC, so I opened {fallback}.")
        else:
            notes.append(how or "Couldn't find that studio on this PC.")

    if kind == "open":
        return "ok", " ".join(notes) or "Opened the studio."
    return "ok", " ".join(notes)


def _open_studio(payload: dict) -> tuple[bool, str]:
    url = (payload.get("studio_url") or "").strip()
    if url:
        webbrowser.open(url)
        return True, f"Opened {payload.get('studio_label') or url}."

    system = platform.system()
    label = payload.get("studio_label") or "the studio"

    if system == "Windows":
        for pattern in payload.get("windows_globs") or []:
            matches = glob.glob(os.path.expandvars(pattern))
            matches = [m for m in matches if os.path.isfile(m)]
            if matches:
                path = sorted(matches)[-1]
                try:
                    os.startfile(path)  # type: ignore[attr-defined]
                    return True, f"Opened {label}."
                except Exception:
                    continue
        for name in payload.get("app_names") or []:
            if _windows_start(name):
                return True, f"Opened {label}."
    elif system == "Darwin":
        for name in list(payload.get("darwin_apps") or []) + list(payload.get("app_names") or []):
            if not name:
                continue
            r = subprocess.run(["open", "-a", name], capture_output=True, text=True)
            if r.returncode == 0:
                return True, f"Opened {label}."
    else:
        for bin_name in list(payload.get("linux_bins") or []) + list(payload.get("app_names") or []):
            if not bin_name:
                continue
            path = shutil.which(bin_name)
            if path:
                try:
                    subprocess.Popen([path])
                    return True, f"Opened {label}."
                except Exception:
                    continue
    return False, f"Couldn't find {label} on this PC."


def _windows_start(name: str) -> bool:
    if not name:
        return False
    try:
        os.startfile(name)  # type: ignore[attr-defined]
        return True
    except Exception:
        return False


def _clipboard_set(text: str) -> None:
    if not text:
        return
    system = platform.system()
    try:
        if system == "Windows":
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", "$input | Set-Clipboard"],
                input=text,
                text=True,
                timeout=10,
                check=False,
            )
        elif system == "Darwin":
            subprocess.run(["pbcopy"], input=text, text=True, timeout=10, check=False)
        else:
            subprocess.run(
                ["bash", "-c", "xclip -selection clipboard 2>/dev/null || xsel -b 2>/dev/null"],
                input=text,
                text=True,
                timeout=10,
                check=False,
            )
    except Exception:
        pass


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
