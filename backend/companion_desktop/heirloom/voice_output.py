"""Play twin speech through the cloned voice API (fallback: OS TTS)."""
from __future__ import annotations

import os
import platform
import subprocess
import tempfile
from typing import Optional

import requests

from . import config


def speak_cloned_or_system(text: str) -> bool:
    """Return True if cloned voice played successfully."""
    if not text:
        return False
    snippet = text.replace('"', "'")[:500]
    if not config.DEVICE_TOKEN:
        _speak_system(snippet)
        return False
    try:
        r = requests.post(
            f"{config.BACKEND_URL.rstrip('/')}/api/desktop/speak",
            headers={"Authorization": f"Bearer {config.DEVICE_TOKEN}"},
            json={"text": snippet},
            timeout=90,
        )
        if r.status_code != 200 or not r.content:
            _speak_system(snippet)
            return False
        fd, path = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        with open(path, "wb") as f:
            f.write(r.content)
        if platform.system() == "Windows":
            # Let default app play; avatar panel handles in-GUI playback.
            try:
                os.startfile(path)  # type: ignore[attr-defined]
                return True
            except Exception:
                pass
        elif platform.system() == "Darwin":
            subprocess.Popen(["afplay", path])
            return True
        else:
            subprocess.Popen(["mpg123", "-q", path])
            return True
    except Exception:
        _speak_system(snippet)
        return False


def _speak_system(text: str) -> None:
    try:
        if platform.system() == "Darwin":
            subprocess.Popen(["say", text])
        elif platform.system() == "Windows":
            ps = (
                "Add-Type -AssemblyName System.Speech;"
                f'(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak("{text}")'
            )
            subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", ps],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            subprocess.Popen(["espeak", text])
    except Exception as exc:  # noqa: BLE001
        print(f"[say] TTS failed: {exc}")
