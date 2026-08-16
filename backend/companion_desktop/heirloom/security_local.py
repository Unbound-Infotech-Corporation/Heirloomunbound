"""Read Windows Security and open the Windows Security app on this PC."""
from __future__ import annotations

import platform
import subprocess
import webbrowser
from typing import Optional


_STATUS_PS = r"""
$ErrorActionPreference = 'SilentlyContinue'
$os = [System.Environment]::OSVersion.VersionString
Write-Output ("os=Windows")
$mp = Get-MpComputerStatus
if ($mp) {
  Write-Output ("antivirus=" + [bool]$mp.AntivirusEnabled)
  Write-Output ("realtime=" + [bool]$mp.RealTimeProtectionEnabled)
  Write-Output ("signatures=" + $mp.AntivirusSignatureLastUpdated)
} else {
  Write-Output "antivirus="
  Write-Output "realtime="
}
$fwOn = $true
Get-NetFirewallProfile | ForEach-Object {
  if (-not $_.Enabled) { $fwOn = $false }
  Write-Output ("firewall_" + $_.Name.ToLower() + "=" + [bool]$_.Enabled)
}
Write-Output ("firewall=" + [bool]$fwOn)
$uac = (Get-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' -Name EnableLUA).EnableLUA
Write-Output ("uac=" + [int]$uac)
""".strip()


def run_security_job(payload: dict) -> tuple[str, str]:
    kind = (payload.get("kind") or "status").strip().lower()
    system = platform.system()
    if kind == "open":
        return _open_security_app(system)
    if kind == "scan":
        return _quick_scan(system)
    if kind == "status":
        return _status(system)
    return "error", "I only check Windows Security, open it, or start a quick scan."


def _open_security_app(system: str) -> tuple[str, str]:
    if system == "Windows":
        for target in ("windowsdefender:", "ms-settings:windowsdefender"):
            try:
                webbrowser.open(target)
            except Exception:
                continue
        return "ok", "Opened Windows Security. Look for Virus & threat protection. I never need your Windows password."
    if system == "Darwin":
        subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security"], check=False)
        return "ok", "Opened Privacy & Security on this Mac. Windows Security is a Windows feature."
    return "ok", "On Linux, open your usual security settings. Windows Security is a Windows feature."


def _quick_scan(system: str) -> tuple[str, str]:
    if system != "Windows":
        return "ok", "A Windows Security quick scan only runs on Windows. On this computer, use the built-in security settings."
    _open_security_app(system)
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", "Start-MpScan -ScanType QuickScan"],
            creationflags=flags,
        )
        return "ok", (
            "Windows Security started a quick scan. I opened that same Windows app so you can watch it. "
            "Leave the computer on. I never need your Windows password."
        )
    except Exception as exc:  # noqa: BLE001
        return "error", (
            "Couldn't start the scan from here. Open Windows Security and tap Scan now. "
            f"{str(exc)[:240]}"
        )


def _status(system: str) -> tuple[str, str]:
    if system != "Windows":
        os_name = "mac" if system == "Darwin" else "linux"
        return "ok", _format_non_windows(os_name)
    ok, out = _ps(_STATUS_PS)
    if not ok:
        return "ok", (
            "I couldn't read Windows Security automatically. Say “open Windows Security” "
            "and you can look with your own eyes. I never ask for your Windows password."
        )
    flags = _parse(out)
    return "ok", _format_windows(flags)


def _format_non_windows(os_name: str) -> str:
    if os_name == "mac":
        return (
            "This computer is a Mac. Windows Security is a Windows feature. "
            "On a Mac, open System Settings, then Privacy & Security. "
            "I still will not run steps that turn protection off, and I never ask for your password."
        )
    return (
        "This computer is Linux. Windows Security is a Windows feature. "
        "Use your usual updater and firewall settings. "
        "I still will not run steps that turn protection off, and I never ask for your password."
    )


def _format_windows(flags: dict[str, str]) -> str:
    def on(key: str) -> Optional[bool]:
        val = (flags.get(key) or "").strip().lower()
        if val in ("true", "1", "yes", "on"):
            return True
        if val in ("false", "0", "no", "off"):
            return False
        return None

    lines = ["Windows Security on this computer:"]
    mapping = (
        ("antivirus", "Virus & threat protection"),
        ("realtime", "Real-time protection"),
        ("firewall", "Firewall"),
        ("uac", "Ask before big changes (UAC)"),
    )
    off: list[str] = []
    unknown = False
    for key, label in mapping:
        state = on(key)
        if state is None:
            lines.append(f"• {label}: I couldn't read this")
            unknown = True
        elif state:
            lines.append(f"• {label}: on")
        else:
            lines.append(f"• {label}: off")
            off.append(label)
    sig = (flags.get("signatures") or "").strip()
    if sig and sig.lower() not in ("none", "null"):
        lines.append(f"• Protection updates: {sig}")
    lines.append("")
    if off:
        lines.append(
            "Something important is off. Say “open Windows Security” and I'll open the same app "
            "Windows already has, so you can turn it back on. I will not turn it off for anyone."
        )
    elif unknown:
        lines.append("I couldn't read every switch. Say “open Windows Security” and look with your own eyes.")
    else:
        lines.append("Nothing here looks turned off. If a pop-up ever asks you to turn these off, say no.")
    lines.append("I never ask for your Windows password.")
    return "\n".join(lines)


def _parse(blob: str) -> dict[str, str]:
    flags: dict[str, str] = {}
    for line in (blob or "").splitlines():
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip().lower()
        if key:
            flags[key] = val.strip()
    return flags


def _ps(cmd: str) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True,
            text=True,
            timeout=45,
        )
        out = ((r.stdout or "") + ("\n" + r.stderr if r.stderr else "")).strip()
        return r.returncode == 0, out
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)
