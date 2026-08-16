"""Unstick this app in the Windows Volume Mixer.

Qt's QAudioOutput on WASAPI often registers the process at ~1% in
sndvol.exe. QAudioOutput.setVolume() is a software gain — it does not
move ISimpleAudioVolume, which is the Mixer slider, so the slider looks
frozen at 1.

After the twin starts talking (when the WASAPI session exists), we set
this process's session volume through Core Audio. No-op on other OSes,
and if pycaw is not installed yet.
"""
from __future__ import annotations

import os
import sys
from typing import Optional


def set_app_session_volume(level: float) -> bool:
    """Set this process's Windows session volume (0.0–1.0).

    Returns True when at least one session for this PID was updated.
    """
    if sys.platform != "win32":
        return False
    try:
        value = max(0.0, min(1.0, float(level)))
    except (TypeError, ValueError):
        return False
    try:
        from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
    except Exception:
        return False
    pid = os.getpid()
    try:
        sessions = AudioUtilities.GetAllSessions()
    except Exception:
        return False
    updated = False
    for session in sessions:
        if _session_pid(session) != pid:
            continue
        try:
            simple = getattr(session, "SimpleAudioVolume", None)
            if simple is None:
                simple = session._ctl.QueryInterface(ISimpleAudioVolume)
            simple.SetMasterVolume(value, None)
            simple.SetMute(0, None)
            updated = True
        except Exception:
            continue
    return updated


def _session_pid(session: object) -> Optional[int]:
    """Best-effort process id for a pycaw audio session."""
    for attr in ("ProcessId",):
        try:
            raw = getattr(session, attr, None)
            if raw is None:
                continue
            val = raw() if callable(raw) else raw
            return int(val)
        except Exception:
            continue
    try:
        proc = getattr(session, "Process", None)
        if proc is not None:
            return int(proc.pid)
    except Exception:
        pass
    try:
        ctl = getattr(session, "_ctl", None)
        if ctl is not None:
            return int(ctl.GetProcessId())
    except Exception:
        return None
    return None
