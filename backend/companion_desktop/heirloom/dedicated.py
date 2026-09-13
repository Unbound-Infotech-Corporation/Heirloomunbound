"""Dedicated-PC machine role for Heirloom Unbound.

Consecrates this computer: install_profile flag, start-with-Windows,
optional high-performance power plan (explicit consent), warm engine
probes, standing-routine / live-listen defaults, branding stub, and an
overnight maintenance hook. Never fights IT policy silently.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from . import config

ProgressFn = Callable[[str], None]

CONSENT_COPY = (
    "This PC exists for Heirloom Unbound. It will start with Windows, keep "
    "local models warm, and treat the vault drive as the home of the twin. "
    "You can still turn live listen and standing routines off later."
)

BRANDING_MARK = "Heirloom Unbound · Dedicated"

HIGH_PERFORMANCE_GUID = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"


def _note(progress: Optional[ProgressFn], msg: str) -> None:
    if progress:
        progress(msg)


def write_install_profile(settings: dict[str, Any], profile_id: str = "dedicated") -> dict[str, Any]:
    settings["install_profile"] = profile_id
    settings["space_profile"] = profile_id
    settings["disk_profile"] = profile_id
    if profile_id == "dedicated":
        settings["machine_role"] = "dedicated"
    return settings


def register_start_with_windows(enabled: bool = True, progress: Optional[ProgressFn] = None) -> dict[str, Any]:
    """HKCU Run key, plus a Startup-folder shortcut note. User-scope only."""
    result: dict[str, Any] = {"ok": False, "method": None, "detail": ""}
    if not enabled:
        result["ok"] = True
        result["detail"] = "Start with Windows left off."
        return result
    if sys.platform != "win32":
        result["ok"] = True
        result["method"] = "noop"
        result["detail"] = "Start-with-Windows is recorded; registry apply waits for Windows."
        _note(progress, result["detail"])
        return result

    launch = _launch_command()
    try:
        import winreg  # type: ignore

        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run")
        winreg.SetValueEx(key, "HeirloomUnbound", 0, winreg.REG_SZ, launch)
        winreg.CloseKey(key)
        result["ok"] = True
        result["method"] = "run_key"
        result["detail"] = "Heirloom Unbound will start with this Windows sign-in."
        _note(progress, result["detail"])
        _write_startup_folder(launch)
        return result
    except Exception as exc:  # noqa: BLE001
        result["detail"] = f"Run key failed: {exc}"
        _note(progress, result["detail"])
        return result


def document_always_on_service() -> str:
    return (
        "Optional always-on service: after Setup, Task Scheduler can run "
        "HeirloomUnbound at system start (SYSTEM, highest privileges) if this "
        "PC should stay warm when nobody is signed in. Heirloom Unbound does "
        "not install a Windows service by default."
    )


def apply_high_performance_power_plan(consent: bool, progress: Optional[ProgressFn] = None) -> dict[str, Any]:
    """Suggest / apply the High performance plan only with explicit consent."""
    if not consent:
        msg = (
            "High-performance power plan not applied. IT policy stays as-is. "
            "You can switch it later in Windows Power Options if this machine "
            "is yours to tune."
        )
        _note(progress, msg)
        return {"ok": True, "applied": False, "detail": msg}
    if sys.platform != "win32":
        msg = "Power-plan consent recorded. Apply waits for Windows (powercfg)."
        _note(progress, msg)
        return {"ok": True, "applied": False, "detail": msg}
    try:
        r = subprocess.run(
            ["powercfg", "/setactive", HIGH_PERFORMANCE_GUID],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if r.returncode == 0:
            msg = "High performance power plan is active (you consented)."
            _note(progress, msg)
            return {"ok": True, "applied": True, "detail": msg}
        msg = f"powercfg declined ({r.returncode}). IT policy was not overridden."
        _note(progress, msg)
        return {"ok": False, "applied": False, "detail": msg}
    except Exception as exc:  # noqa: BLE001
        msg = f"Could not change the power plan: {exc}"
        _note(progress, msg)
        return {"ok": False, "applied": False, "detail": msg}


def write_branding_assets(enabled: bool, progress: Optional[ProgressFn] = None) -> dict[str, Any]:
    if not enabled:
        return {"ok": True, "written": False, "detail": "Dedicated branding skipped."}
    dest = config.app_data_dir() / "branding"
    dest.mkdir(parents=True, exist_ok=True)
    mark = dest / "dedicated.txt"
    mark.write_text(
        f"{BRANDING_MARK}\n"
        "Optional desktop and lock-screen mark for a machine that exists for the twin.\n",
        encoding="utf-8",
    )
    _note(progress, f"Wrote {BRANDING_MARK} mark to {mark}.")
    return {"ok": True, "written": True, "path": str(mark), "detail": BRANDING_MARK}


def overnight_maintenance_stub(progress: Optional[ProgressFn] = None) -> dict[str, Any]:
    """Keep models current. Dedicated PCs schedule this overnight — no Pinokio."""
    _note(progress, "Overnight maintenance hook: probe local engines, refresh stale pulls.")
    try:
        from .models import full_probe

        probe = full_probe()
    except Exception as exc:  # noqa: BLE001
        probe = {"error": str(exc)}
    return {
        "ok": True,
        "stub": True,
        "hint": "Heirloom Unbound will re-check Ollama / Whisper / clone engines overnight.",
        "pinokio": False,
        "probe": {k: (v or {}).get("ready") if isinstance(v, dict) else v for k, v in (probe or {}).items() if k != "log"},
    }


def apply_machine_role(
    *,
    consent: bool,
    vault_drive: str = "",
    start_with_windows: bool = True,
    power_plan_consent: bool = False,
    warm_engines: bool = True,
    live_listen: bool = True,
    branding: bool = False,
    progress: Optional[ProgressFn] = None,
) -> dict[str, Any]:
    """Persist dedicated role into companion settings.json."""
    if not consent:
        raise ValueError("Dedicated PC mode needs explicit consent that this PC exists for Heirloom Unbound.")

    settings = config.load_settings()
    write_install_profile(settings, "dedicated")
    settings["dedicated_consent"] = True
    settings["dedicated_consent_copy"] = CONSENT_COPY
    settings["start_with_windows"] = bool(start_with_windows)
    settings["power_plan_consent"] = bool(power_plan_consent)
    settings["warm_engines"] = bool(warm_engines)
    settings["live_listen_default"] = bool(live_listen)
    settings["branding_dedicated"] = bool(branding)
    settings["maintenance_schedule"] = "midnight"
    settings["storage_tier"] = "full"
    settings["standing_routines_default"] = True
    if vault_drive:
        settings["vault_folder"] = str(vault_drive).strip()
        settings["vault_drive"] = str(vault_drive).strip()
    settings["always_on_service_note"] = document_always_on_service()

    startup = register_start_with_windows(start_with_windows, progress)
    power = apply_high_performance_power_plan(power_plan_consent, progress)
    brand = write_branding_assets(branding, progress)

    config.save_settings(settings)
    _note(progress, "Wrote install_profile: dedicated so Models Studio and Terminal know this role.")
    return {
        "ok": True,
        "install_profile": "dedicated",
        "settings_path": str(config.SETTINGS_PATH),
        "startup": startup,
        "power": power,
        "branding": brand,
        "always_on_service": settings["always_on_service_note"],
    }


def warm_engine_probes(progress: Optional[ProgressFn] = None) -> dict[str, Any]:
    """Auto-start / probe Ollama, Voicebox, Qwen3-TTS, LatentSync listeners."""
    from .models import engine_urls, full_probe, probe_ollama

    _note(progress, "Warming local engines for the dedicated PC…")
    ol = probe_ollama()
    if not ol.get("ready"):
        _try_start_ollama(progress)
    probe = full_probe()
    urls = engine_urls()
    rows = []
    for key in ("ollama", "voicebox", "qwen3_tts", "latentsync"):
        row = probe.get(key) or {}
        ready = bool(row.get("ready"))
        line = f"{key}: {'listening' if ready else 'not listening'} · {urls.get(key + '_url', row.get('url', ''))}"
        if not ready:
            line += " — coach: start the official MSI/Docker/pip listener. Engine failure does not abort Heirloom Unbound."
        _note(progress, line)
        rows.append({"id": key, "ready": ready, "detail": line})
    return {"ok": True, "engines": rows, "probe": probe}


def _try_start_ollama(progress: Optional[ProgressFn] = None) -> None:
    exe = "ollama"
    try:
        subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _note(progress, "Started ollama serve in the background.")
    except Exception as exc:  # noqa: BLE001
        _note(progress, f"Ollama did not auto-start: {exc}")


def _launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    here = Path(__file__).resolve().parents[1]
    bat = here / "Heirloom.bat"
    if bat.exists():
        return f'"{bat}"'
    return f'"{sys.executable}" -m heirloom'


def _write_startup_folder(launch: str) -> None:
    try:
        startup = Path(os.environ.get("APPDATA") or "") / r"Microsoft\Windows\Start Menu\Programs\Startup"
        if not startup.exists():
            return
        cmd = startup / "HeirloomUnbound.cmd"
        cmd.write_text(f"@echo off\nstart \"\" {launch}\n", encoding="ascii")
    except Exception:
        pass
