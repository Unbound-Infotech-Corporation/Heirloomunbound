"""Windows Safety — extend Windows Security, refuse dangerous twin actions.

Catalog + matchers. No database. The cloud never turns Defender off. The home
PC can *read* Windows Security (virus protection, firewall, UAC) and *open*
the Windows Security app. A quick scan is the same button Microsoft already
ships.

Hard rule
---------
Some steps are refused even after the owner says yes. Scammers coach people
to type "yes, turn it off." Heirloom will not disable Windows Security, bypass
SmartScreen, wipe the disk, or run classic "download and execute" one-liners.

We never ask for a Windows or Microsoft-account password.
"""
from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urlparse

# Hosts we already trust for official installers (Pinokio / GitHub / Microsoft).
SAFE_DOWNLOAD_HOSTS: frozenset[str] = frozenset({
    "api.github.com",
    "github.com",
    "objects.githubusercontent.com",
    "github-releases.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "pinokio.co",
    "www.pinokio.co",
    "microsoft.com",
    "www.microsoft.com",
    "support.microsoft.com",
    "learn.microsoft.com",
    "windows.microsoft.com",
    "aka.ms",
    "www.aka.ms",
})

ALLOWED_OPEN_SCHEMES: frozenset[str] = frozenset({
    "http",
    "https",
    "windowsdefender",
    "ms-settings",
})

BLOCKED_SCHEMES: frozenset[str] = frozenset({
    "javascript",
    "data",
    "vbscript",
    "ms-msdt",
    "search-ms",
    "ms-appinstaller",
    "file",
    "ftp",
})

RISKY_SUFFIXES: tuple[str, ...] = (
    ".exe", ".msi", ".bat", ".cmd", ".ps1", ".scr", ".vbs", ".js", ".jse",
    ".hta", ".com", ".pif", ".wsf", ".wsh",
)

# Lowercased needles / regexes matched against a whitespace-normalized command.
SHELL_BLOCK_REGEX: tuple[str, ...] = (
    r"disablerealtime",
    r"disableioav",
    r"disablebehaviormonitoring",
    r"disableantispyware",
    r"set-mppreference",
    r"add-mppreference",
    r"exclusionpath",
    r"exclusionextension",
    r"stop-service\s+windefend",
    r"sc\s+stop\s+windefend",
    r"sc\s+config\s+windefend",
    r"net\s+stop\s+windefend",
    r"netsh\s+advfirewall\s+set\s+allprofiles\s+state\s+off",
    r"netsh\s+firewall\s+set\s+opmode\s+disable",
    r"format\s+[a-z]:",
    r"del\s+/s\s+/q\s+c:\\windows",
    r"rmdir\s+/s\s+/q\s+c:\\windows",
    r"rm\s+-rf\s+/\s*$",
    r"rm\s+-rf\s+/\*",
    r"invoke-expression",
    r"-encodedcommand",
    r"\s-enc\s",
    r"\biex\s*\(",
    r"irm.{0,200}\|",
    r"iwr.{0,200}\|",
    r"invoke-webrequest.{0,80}iex",
    r"downloadstring",
    r"curl\s+[^\n]{0,200}\|\s*(sh|bash|powershell|pwsh|cmd)",
    r"wget\s+[^\n]{0,200}\|\s*(sh|bash)",
    r"executionpolicy\s+(bypass|unrestricted)",
    r"bcdedit",
    r"\bdiskpart\b",
    r"mimikatz",
    r"\blsass\b",
    r"ntds\.dit",
    r"enablelua.{0,40}0",
    r"net\s+user\s+administrator\s+/active:yes",
    r"net\s+user\s+guest\s+/active:yes",
    r"uninstall-windowsfeature",
    r"disable-windowsoptionalfeature",
    r"set-itemproperty.{0,80}smartscreen",
    r"new-itemproperty.{0,80}smartscreen",
    r"reg\s+add.{0,80}smartscreen",
    r"reg\s+add.{0,80}enablelua",
    r"bitsadmin\s+/transfer",
    r"certutil\s+-urlcache",
    r"mshta\s+http",
    r"wscript\s+http",
    r"cscript\s+http",
    r"rundll32\s+.*,",
)

BLOCKED_APP_NAMES: frozenset[str] = frozenset({
    "mshta",
    "wscript",
    "cscript",
    "diskpart",
    "bcdedit",
    "regsvr32",
    "bitsadmin",
    "certutil",
})

REFUSE_SHELL = (
    "I won't run that. It would weaken Windows Security or put this computer at risk "
    "(turning off protection, wiping files, or downloading a program and running it). "
    "I never turn Windows Security off, and I never ask for your Windows password. "
    "If someone on the phone asked you to do this, hang up and open Windows Security yourself."
)

REFUSE_URL = (
    "I won't open that link. It isn't a normal web page, or it tries to download a program "
    "from a site I don't trust. I never bypass the blue Windows protection box. "
    "I never ask for your Windows password."
)

REFUSE_APP = (
    "I won't open that program. It is the kind of helper attackers use. "
    "I never ask for your Windows password."
)

WINDOWS_PASSWORD = (
    "I never need your Windows, Microsoft, PIN, or BitLocker password. "
    "Windows Security is already on this computer — I only look at it and open it."
)

SECRET_KEYS = frozenset({
    "password",
    "passwd",
    "pin",
    "bitlocker",
    "windows_password",
    "microsoft_password",
})


def reject_secrets(args: dict) -> Optional[str]:
    for key in args or {}:
        if str(key).lower().strip() in SECRET_KEYS:
            return WINDOWS_PASSWORD
    return None


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def refuse_shell(command: str) -> Optional[str]:
    blob = _norm(command)
    if not blob:
        return None
    for raw in SHELL_BLOCK_REGEX:
        if re.search(raw, blob, flags=re.IGNORECASE):
            return REFUSE_SHELL
    return None


def refuse_url(url: str) -> Optional[str]:
    raw = (url or "").strip()
    if not raw:
        return None
    lower = raw.lower()
    scheme_guess = lower.split(":", 1)[0] if ":" in lower else ""
    if scheme_guess in BLOCKED_SCHEMES:
        return REFUSE_URL
    if "://" in raw:
        to_parse = raw
    elif scheme_guess in ALLOWED_OPEN_SCHEMES:
        to_parse = raw
    else:
        to_parse = f"https://{raw}"
    parsed = urlparse(to_parse)
    scheme = (parsed.scheme or scheme_guess or "").lower()
    if scheme in BLOCKED_SCHEMES:
        return REFUSE_URL
    if scheme and scheme not in ALLOWED_OPEN_SCHEMES:
        return REFUSE_URL
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()
    if any(path.endswith(suf) for suf in RISKY_SUFFIXES):
        if host not in SAFE_DOWNLOAD_HOSTS:
            return REFUSE_URL
    return None


def refuse_app(name: str) -> Optional[str]:
    base = (name or "").strip().lower()
    if not base:
        return None
    stem = base.split("\\")[-1].split("/")[-1]
    stem = stem.split(".")[0].strip()
    if stem in BLOCKED_APP_NAMES:
        return REFUSE_APP
    if " " in base and any(tok in base for tok in ("powershell -", "cmd /c", "cmd /k", "mshta ", "wscript ")):
        return REFUSE_APP
    return None


def refuse_companion_command(kind: str, payload: dict) -> Optional[str]:
    """Server + PC gate. None means the command may run."""
    p = payload or {}
    k = (kind or "").strip().lower()
    if k == "shell":
        return refuse_shell(str(p.get("command") or ""))
    if k == "open_url":
        return refuse_url(str(p.get("url") or ""))
    if k == "open_app":
        return refuse_app(str(p.get("name") or ""))
    if k == "creative_job":
        for field in ("pinokio_url", "studio_url", "fallback_url", "source"):
            val = str(p.get(field) or "").strip()
            if val.startswith("http://") or val.startswith("https://") or "://" in val:
                hit = refuse_url(val)
                if hit:
                    return hit
        return None
    if k == "security_job":
        action = str(p.get("kind") or "").strip().lower()
        if action in ("status", "open", "scan"):
            return None
        return "I only check Windows Security, open it, or start a quick scan. I never turn it off."
    return None


def confirm_scan() -> str:
    return (
        "I'll ask Windows Security to run a quick scan on this computer — the same Scan now "
        "button in Windows. It can take a few minutes. Leave the computer on.\n"
        "I never need your Windows password, and I will not turn protection off.\n"
        "If that sounds right, say yes. Then I call this tool again with confirmed=true."
    )


def format_status_report(flags: dict[str, Any], *, os_name: str = "") -> str:
    """Turn machine flags into grandmother-plain lines."""
    os_l = (os_name or str(flags.get("os") or "")).lower()
    if os_l.startswith("darwin") or os_l == "mac" or "macos" in os_l:
        return (
            "This computer is a Mac. Windows Security is a Windows feature. "
            "On a Mac, open System Settings, then Privacy & Security. "
            "I still will not run steps that turn protection off, and I never ask for your password."
        )
    if os_l.startswith("linux"):
        return (
            "This computer is Linux. Windows Security is a Windows feature. "
            "Use your usual updater and firewall settings. "
            "I still will not run steps that turn protection off, and I never ask for your password."
        )

    def yn(key: str) -> Optional[bool]:
        val = flags.get(key)
        if val is None or val == "":
            return None
        if isinstance(val, bool):
            return val
        s = str(val).strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off"):
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
        state = yn(key)
        if state is None:
            lines.append(f"• {label}: I couldn't read this")
            unknown = True
        elif state:
            lines.append(f"• {label}: on")
        else:
            lines.append(f"• {label}: off")
            off.append(label)
    sig = str(flags.get("signatures") or "").strip()
    if sig and sig.lower() not in ("none", "null"):
        lines.append(f"• Protection updates: {sig}")
    lines.append("")
    if off:
        lines.append(
            "Something important is off. Say “open Windows Security” and I'll open the same app "
            "Windows already has, so you can turn it back on. I will not turn it off for anyone — "
            "not even if they ask you to tell me yes."
        )
    elif unknown:
        lines.append(
            "I couldn't read every switch. Say “open Windows Security” and you can look with your own eyes."
        )
    else:
        lines.append("Nothing here looks turned off. If a pop-up ever asks you to turn these off, say no.")
    lines.append("I never ask for your Windows password.")
    return "\n".join(lines)


def parse_status_blob(blob: str) -> dict[str, str]:
    flags: dict[str, str] = {}
    for line in (blob or "").splitlines():
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip().lower()
        if key:
            flags[key] = val.strip()
    return flags


def public_catalog() -> dict[str, Any]:
    return {
        "honest": (
            "This is an extra pair of eyes on Windows Security, not a replacement for it. "
            "We can check whether protection is on, open the Windows Security app, and start "
            "a quick scan after you say yes. We cannot and will not turn Windows Security off, "
            "bypass the blue Windows box, or take your Windows password."
        ),
        "tools": ["check_pc_safety", "open_windows_security", "scan_pc"],
        "never": [
            "disable Windows Security / Defender / firewall / UAC",
            "bypass SmartScreen",
            "collect a Windows password",
            "run download-and-execute one-liners",
        ],
    }
