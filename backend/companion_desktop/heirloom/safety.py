"""Refuse dangerous OS commands on the home PC (Windows Safety).

Mirrors backend/services/pc_security.py so the desktop app still protects
the machine if a bad command was queued. Keep the two lists in sync —
tests compare them.
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

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

BLOCKED_SCHEMES = {
    "javascript", "data", "vbscript", "ms-msdt", "search-ms",
    "ms-appinstaller", "file", "ftp",
}
ALLOWED_OPEN_SCHEMES = {"http", "https", "windowsdefender", "ms-settings"}
SAFE_DOWNLOAD_HOSTS = {
    "api.github.com", "github.com", "objects.githubusercontent.com",
    "github-releases.githubusercontent.com", "release-assets.githubusercontent.com",
    "pinokio.co", "www.pinokio.co",
    "microsoft.com", "www.microsoft.com", "support.microsoft.com",
    "learn.microsoft.com", "windows.microsoft.com", "aka.ms", "www.aka.ms",
}
RISKY_SUFFIXES = (
    ".exe", ".msi", ".bat", ".cmd", ".ps1", ".scr", ".vbs", ".js", ".jse",
    ".hta", ".com", ".pif", ".wsf", ".wsh",
)
BLOCKED_APP_NAMES = {
    "mshta", "wscript", "cscript", "diskpart", "bcdedit",
    "regsvr32", "bitsadmin", "certutil",
}

REFUSE = (
    "Blocked by Windows Safety. That step could weaken Windows Security "
    "or put this computer at risk. Heirloom never turns protection off."
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def refuse_shell(command: str) -> Optional[str]:
    blob = _norm(command)
    if not blob:
        return None
    for raw in SHELL_BLOCK_REGEX:
        if re.search(raw, blob, flags=re.IGNORECASE):
            return REFUSE
    return None


def refuse_url(url: str) -> Optional[str]:
    raw = (url or "").strip()
    if not raw:
        return None
    lower = raw.lower()
    scheme_guess = lower.split(":", 1)[0] if ":" in lower else ""
    if scheme_guess in BLOCKED_SCHEMES:
        return REFUSE
    if "://" in raw:
        to_parse = raw
    elif scheme_guess in ALLOWED_OPEN_SCHEMES:
        to_parse = raw
    else:
        to_parse = f"https://{raw}"
    parsed = urlparse(to_parse)
    scheme = (parsed.scheme or scheme_guess or "").lower()
    if scheme in BLOCKED_SCHEMES:
        return REFUSE
    if scheme and scheme not in ALLOWED_OPEN_SCHEMES:
        return REFUSE
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()
    if any(path.endswith(suf) for suf in RISKY_SUFFIXES) and host not in SAFE_DOWNLOAD_HOSTS:
        return REFUSE
    return None


def refuse_app(name: str) -> Optional[str]:
    base = (name or "").strip().lower()
    if not base:
        return None
    stem = base.split("\\")[-1].split("/")[-1].split(".")[0].strip()
    if stem in BLOCKED_APP_NAMES:
        return REFUSE
    if " " in base and any(tok in base for tok in ("powershell -", "cmd /c", "cmd /k", "mshta ", "wscript ")):
        return REFUSE
    return None


def refuse_command(kind: str, payload: dict) -> Optional[str]:
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
    if k == "writing_job":
        action = str(p.get("kind") or "").strip().lower()
        if action in ("paste_text", "read_clipboard"):
            return None
        return "I can paste your writing or read the clipboard. I do not watch every key."
    return None
