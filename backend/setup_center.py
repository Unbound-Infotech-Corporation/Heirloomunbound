"""Setup Center: checklist, guided pages, and a Linux Twin Box restore.

The restore copies a backup onto a destination the owner names. It never
deletes the source, never writes under ``/var/lib/heirloom`` (the live Linux
Twin Box), and never applies the uncommitted ``git-preserve`` hotfix onto a
git checkout. Inventory is read-only and does not load secret file contents.

Cloud chat-model keys (OpenAI, Gemini, Anthropic, ElevenLabs, and the rest)
are an owner decision. This module refuses to store them. Guided pages are
for downloads and non-LLM services: Hugging Face files, Resend, Home
Assistant, and smart-home vendors.

Twin model choice is untouched. See ``model_router.py``.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from owner_privacy import (
    cloud_model_key_flow,
    is_private_http_url,
    mask_secret,
    secret_for_log,
)

LINUX_LIVE_ROOT = "/var/lib/heirloom"
HOTFIX_NOTE = (
    "Uncommitted hotfix from ~/Heirloomunbound, kept under git-preserve/. "
    "Copied for you to review. It is not applied to a git checkout, and the "
    "PC it came from is not changed."
)

SLOT_DIRS = ("vault", "owner", "observer", "presence", "lab", "lab-reports", "backups")

GUIDED_FLOWS: tuple[dict[str, Any], ...] = (
    {
        "id": "huggingface",
        "title": "Hugging Face download token",
        "kind": "download",
        "paste": True,
        "url": "https://huggingface.co/settings/tokens",
        "what_it_is": "A key for downloading model files. It does not chat, and it is not the twin.",
        "steps": (
            "Sign in to Hugging Face.",
            "Open Settings, then Access Tokens.",
            "Create a read token.",
            "Paste it here. Heirloom stores it masked and does not write it in the log.",
        ),
    },
    {
        "id": "home_assistant",
        "title": "Home Assistant",
        "kind": "smart_home",
        "paste": True,
        "url": "http://homeassistant.local:8123/profile/security",
        "what_it_is": "Optional bridge for lights, plugs, and thermostats already in Home Assistant.",
        "steps": (
            "Open Home Assistant on your home network.",
            "Open your profile, then Security.",
            "Create a long-lived access token.",
            "Paste the token here and enter the local address, such as http://homeassistant.local:8123.",
        ),
    },
    {
        "id": "resend",
        "title": "Resend (email drafts)",
        "kind": "email",
        "paste": True,
        "url": "https://resend.com/api-keys",
        "what_it_is": "Optional. Heirloom can draft mail. It does not send until you approve, and this update does not send at all.",
        "steps": (
            "Open Resend and sign in.",
            "Open API Keys and create a key.",
            "Paste it here. Sending still waits for a later approval step.",
        ),
    },
    {
        "id": "hue",
        "title": "Philips Hue",
        "kind": "smart_home",
        "paste": False,
        "url": "https://account.meethue.com/",
        "what_it_is": "Hue on your network does not need an account. Press the button on the bridge when Heirloom asks. The account page is only if you already use one.",
        "steps": (
            "Plug in the Hue bridge and wait until the lights are reachable in the Hue app.",
            "When Heirloom asks, press the round button on the bridge.",
            "Skip the website if the bridge is found on your network.",
        ),
    },
    {
        "id": "kasa",
        "title": "TP-Link Kasa",
        "kind": "smart_home",
        "paste": False,
        "url": "https://www.tplinkcloud.com/",
        "what_it_is": "Kasa plugs are controlled on your home network. The website is only if a plug asks you to sign in.",
        "steps": (
            "Plug in the Kasa device and join it to your Wi-Fi.",
            "Prefer the local connection Heirloom finds.",
            "Open the TP-Link page only if the device still asks for a cloud sign-in.",
        ),
    },
    {
        "id": "tapo",
        "title": "TP-Link Tapo",
        "kind": "smart_home",
        "paste": False,
        "url": "https://www.tapo.com/",
        "what_it_is": "Tapo plugs. Local control first. The website is the account page when a sign-in is required.",
        "steps": (
            "Join the plug to your Wi-Fi from the Tapo app.",
            "Come back. Heirloom looks for it on the network.",
        ),
    },
    {
        "id": "shelly",
        "title": "Shelly",
        "kind": "smart_home",
        "paste": False,
        "url": "https://control.shelly.cloud/",
        "what_it_is": "Shelly relays speak on your network. A Shelly cloud account is optional.",
        "steps": (
            "Connect the Shelly to your Wi-Fi.",
            "Use the local address Heirloom finds. Open Shelly Cloud only if you want the cloud copy.",
        ),
    },
    {
        "id": "wemo",
        "title": "Wemo",
        "kind": "smart_home",
        "paste": False,
        "url": "https://www.belkin.com/support/",
        "what_it_is": "Wemo plugs are discovered on the network.",
        "steps": (
            "Put the Wemo on your Wi-Fi.",
            "If setup fails, Belkin's support page has the reset steps. Heirloom does not sign in for you.",
        ),
    },
    {
        "id": "meross",
        "title": "Meross",
        "kind": "smart_home",
        "paste": False,
        "url": "https://www.meross.com/",
        "what_it_is": "Meross plugs. Home Assistant is the easy local bridge when the plug has no local API.",
        "steps": (
            "Join the plug to Wi-Fi in the Meross app.",
            "If Heirloom cannot see it locally, add it in Home Assistant, then use the Home Assistant token.",
        ),
    },
    {
        "id": "ecobee",
        "title": "ecobee",
        "kind": "smart_home",
        "paste": False,
        "url": "https://www.ecobee.com/home/developer/login.jsp",
        "what_it_is": "ecobee thermostats. Home Assistant is the preferred bridge. The developer page is only if you connect ecobee yourself.",
        "steps": (
            "Prefer Home Assistant if it already has the thermostat.",
            "Otherwise open the ecobee developer page and create an app key.",
            "Heirloom will not set the heat outside a safe family range.",
        ),
    },
    {
        "id": "nest",
        "title": "Nest",
        "kind": "smart_home",
        "paste": False,
        "url": "https://console.nest.google.com/device-access/",
        "what_it_is": "Nest uses a Google account. Home Assistant is easier when it is already linked.",
        "steps": (
            "Prefer Home Assistant if the thermostat is already there.",
            "Otherwise open Google Device Access and follow their sign-in.",
            "Heirloom does not store a Google password.",
        ),
    },
    {
        "id": "honeywell",
        "title": "Honeywell Home",
        "kind": "smart_home",
        "paste": False,
        "url": "https://developer.honeywellhome.com/",
        "what_it_is": "Honeywell thermostats. Home Assistant is the preferred bridge.",
        "steps": (
            "Prefer Home Assistant if the thermostat is already there.",
            "Otherwise open the Honeywell developer page.",
        ),
    },
    {
        "id": "lifx",
        "title": "LIFX",
        "kind": "smart_home",
        "paste": False,
        "url": "https://cloud.lifx.com/settings",
        "what_it_is": "LIFX lights can talk on your network. The cloud token page is optional.",
        "steps": (
            "Join the lights to your Wi-Fi.",
            "Use local discovery. Open the LIFX cloud page only if you want a cloud token.",
        ),
    },
    {
        "id": "govee",
        "title": "Govee",
        "kind": "smart_home",
        "paste": False,
        "url": "https://developer.govee.com/",
        "what_it_is": "Govee lights. A developer key is optional. Home Assistant can bridge them.",
        "steps": (
            "Join the lights to Wi-Fi.",
            "Open the Govee developer page only if a key is required.",
        ),
    },
    {
        "id": "wiz",
        "title": "WiZ",
        "kind": "smart_home",
        "paste": False,
        "url": "https://www.wizconnected.com/",
        "what_it_is": "WiZ lights are controlled on your network. No account is required.",
        "steps": (
            "Put the bulb on your Wi-Fi with the WiZ app.",
            "Come back. Heirloom sends local commands. You can ignore the website.",
        ),
    },
    {
        "id": "matter",
        "title": "Matter and Thread",
        "kind": "smart_home",
        "paste": False,
        "url": "",
        "what_it_is": "Matter devices are commissioned on your network. No vendor account.",
        "steps": (
            "Have the device's pairing code ready.",
            "Home Assistant is the bridge this update uses to control Matter devices.",
            "There is no website to open.",
        ),
    },
    {
        "id": "ollama",
        "title": "Ollama",
        "kind": "local_model",
        "paste": False,
        "url": "https://ollama.com/download",
        "what_it_is": "The local program that runs the twin and, later, a coder model. Nothing is hosted.",
        "steps": (
            "Download Ollama for Windows.",
            "Install it and leave it running.",
            "Heirloom pulls a local model. A hosted chat key is not required.",
        ),
    },
    {
        "id": "nvidia",
        "title": "NVIDIA driver",
        "kind": "driver",
        "paste": False,
        "url": "https://www.nvidia.com/Download/index.aspx",
        "what_it_is": "Only if this PC has an NVIDIA card and Windows has not already installed a driver.",
        "steps": (
            "Open NVIDIA's driver download page.",
            "Pick your card and Windows 11.",
            "Install the driver, then come back. Heirloom does not change fan curves.",
        ),
    },
    {
        "id": "windows_update",
        "title": "Windows Update",
        "kind": "windows",
        "paste": False,
        "url": "ms-settings:windowsupdate",
        "what_it_is": "Lets Windows finish driver and runtime updates.",
        "steps": ("Open Windows Update.", "Install updates.", "Come back to Heirloom."),
    },
    {
        "id": "firewall",
        "title": "Windows firewall",
        "kind": "windows",
        "paste": False,
        "url": "ms-settings:network-firewall",
        "what_it_is": "Allow Heirloom and Ollama on private networks if a prompt appears.",
        "steps": (
            "Open Firewall & network protection.",
            "If Windows asked to allow Heirloom or Ollama, allow it on private networks.",
        ),
    },
    {
        "id": "startup",
        "title": "Start with Windows",
        "kind": "windows",
        "paste": False,
        "url": "ms-settings:startupapps",
        "what_it_is": "Optional. Heirloom can open when you sign in.",
        "steps": ("Open Startup apps if you want to review it.", "You can turn this off later."),
    },
    {
        "id": "languagetool",
        "title": "LanguageTool on this PC",
        "kind": "writing",
        "paste": False,
        "url": "https://languagetool.org/download/",
        "what_it_is": "Optional grammar server you run yourself. Heirloom will not send writing to the public LanguageTool site.",
        "steps": (
            "Download LanguageTool and run it on this PC.",
            "Point Heirloom at http://127.0.0.1:8081. Any other address is refused.",
        ),
    },
    {
        "id": "dns",
        "title": "A public website (most families skip this)",
        "kind": "optional",
        "paste": False,
        "url": "",
        "what_it_is": "The Twin Box on your home network does not need a public website or a DNS change.",
        "steps": (
            "Skip this unless you already own a domain.",
            "If you do, open the DNS page at the company you bought the domain from. Heirloom does not change DNS.",
        ),
    },
)


class CloudModelDeferred(Exception):
    """Hosted chat-model keys are not collected in this update."""


class RestoreRefused(Exception):
    """The restore would touch the live Twin Box or the source tree."""


class SecretStore:
    """Holds pasted keys. ``public_view`` is safe to return and log."""

    def __init__(self) -> None:
        self._secrets: dict[tuple[str, str], str] = {}

    def put(self, user_id: str, flow_id: str, secret: str) -> None:
        self._secrets[(user_id, flow_id)] = secret

    def public_view(self, user_id: str) -> list[dict[str, Any]]:
        rows = []
        for (uid, flow_id), secret in self._secrets.items():
            if uid != user_id:
                continue
            rows.append({
                "flow_id": flow_id,
                "set": True,
                "masked": mask_secret(secret),
                "log": secret_for_log(secret),
            })
        return rows


class FileSecretStore(SecretStore):
    """Disk copy for the new PC. The public file never contains the key."""

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = Path(root)

    def put(self, user_id: str, flow_id: str, secret: str) -> None:
        super().put(user_id, flow_id, secret)
        self.root.mkdir(parents=True, exist_ok=True)
        secret_path = self.root / "secrets.json"
        public_path = self.root / "public.json"
        import json

        existing: dict[str, dict[str, str]] = {}
        if secret_path.is_file():
            existing = json.loads(secret_path.read_text(encoding="utf-8"))
        user_row = existing.setdefault(user_id, {})
        user_row[flow_id] = secret
        secret_path.write_text(json.dumps(existing), encoding="utf-8")
        try:
            os.chmod(secret_path, 0o600)
        except OSError:
            pass
        public_path.write_text(
            json.dumps({"keys": self.public_view(user_id)}),
            encoding="utf-8",
        )


def flows() -> list[dict[str, Any]]:
    return [_public_flow(row) for row in GUIDED_FLOWS]


def flow_by_id(flow_id: str) -> dict[str, Any] | None:
    key = (flow_id or "").strip()
    for row in GUIDED_FLOWS:
        if row["id"] == key:
            return row
    return None


def _public_flow(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "kind": row["kind"],
        "paste": bool(row.get("paste")),
        "url": row.get("url") or "",
        "what_it_is": row["what_it_is"],
        "steps": list(row["steps"]),
    }


def accept_secret(flow_id: str, secret: str, *, base_url: str | None = None) -> dict[str, Any]:
    """Check a pasted key. The return value never includes the key."""
    if cloud_model_key_flow(flow_id):
        raise CloudModelDeferred(
            "Cloud model keys stay an owner decision. They are not stored in this update."
        )
    flow = flow_by_id(flow_id)
    if flow is None or not flow.get("paste"):
        raise CloudModelDeferred("That page does not take a pasted key.")
    raw = (secret or "").strip()
    if not raw:
        return {"ok": False, "flow_id": flow_id, "masked": mask_secret(raw), "detail": "Paste the key first."}
    if flow_id == "huggingface" and not raw.startswith("hf_"):
        return {
            "ok": False,
            "flow_id": flow_id,
            "masked": mask_secret(raw),
            "detail": "A Hugging Face token usually starts with hf_.",
        }
    if flow_id == "home_assistant":
        if not base_url or not is_private_http_url(base_url):
            return {
                "ok": False,
                "flow_id": flow_id,
                "masked": mask_secret(raw),
                "detail": "Home Assistant stays on your home network. Use its local address.",
            }
    return {
        "ok": True,
        "flow_id": flow_id,
        "masked": mask_secret(raw),
        "stored": True,
        "detail": "Saved on this PC. The log only says [redacted].",
        "log": secret_for_log(raw),
    }


def checklist(signals: dict[str, Any] | None) -> list[dict[str, Any]]:
    src = signals or {}
    profile = str(src.get("profile") or "")
    tiers = {"small", "medium", "large", "dedicated"}

    def row(step_id: str, title: str, status: str, detail: str, *, optional: bool = False) -> dict[str, Any]:
        return {
            "id": step_id,
            "title": title,
            "status": status,
            "detail": detail,
            "optional": optional,
        }

    hardware = "ready" if src.get("hardware_ok") or int(src.get("free_bytes") or 0) > 0 else "needs_you"
    return [
        row("hardware", "This PC", hardware, src.get("hardware_line") or "Disk space picks a starting size."),
        row(
            "tier",
            "Install size",
            "ready" if profile in tiers else "needs_you",
            profile or "Choose Small, Medium, Large, or Dedicated.",
        ),
        row(
            "hearing",
            "Hearing",
            "ready" if src.get("whisper_ready") else "needs_you",
            "The hearing download resumes if it stops.",
        ),
        row(
            "mind",
            "Talking mind",
            "ready" if src.get("ollama_ready") else "needs_you",
            "Local Ollama. The twin does not use a hosted chat model.",
        ),
        row(
            "voice",
            "Voice",
            "ready" if src.get("voice_ready") else "needs_you",
            "Local voice on this PC. A copied-voice account is not started for you.",
        ),
        row(
            "companion",
            "Companion and capture",
            "ready" if src.get("companion_paired") else "needs_you",
            "Paste the device token from the pairing screen.",
        ),
        row(
            "startup",
            "Start with Windows",
            "ready" if src.get("startup_enabled") else "needs_you",
            "Optional. You can turn it off later.",
        ),
        row(
            "backup",
            "Backup and restore",
            "ready" if src.get("backup_seen") else "needs_you",
            "Import the Linux copy: vault, owner keys, observer, presence, lab, a Mongo dump, Odysseus, and git-preserve.",
        ),
        row(
            "smart_home",
            "Smart home",
            "ready" if src.get("smart_home_ready") else "optional",
            "Lights, plugs, and thermostats on your home network.",
            optional=True,
        ),
        row(
            "writing",
            "Writing",
            "ready",
            "Spelling, grammar, dictionary, and thesaurus work with no internet.",
            optional=True,
        ),
        row(
            "accounts",
            "Optional accounts",
            "optional",
            "Hugging Face downloads, Resend, and smart-home sign-in. Chat-model keys are not part of this step.",
            optional=True,
        ),
    ]


def repair_plan(signals: dict[str, Any] | None) -> list[dict[str, Any]]:
    src = signals or {}
    steps: list[dict[str, Any]] = []
    if not src.get("whisper_ready"):
        steps.append({
            "id": "hearing",
            "title": "Download hearing again",
            "detail": "The download resumes from what is already on disk.",
            "auto": True,
        })
    if not src.get("ollama_ready"):
        steps.append({
            "id": "mind",
            "title": "Start the talking mind",
            "detail": "Open Ollama on this PC. Heirloom does not switch the twin to a hosted model.",
            "auto": False,
        })
    if not src.get("companion_paired"):
        steps.append({
            "id": "companion",
            "title": "Pair this PC again",
            "detail": "Paste the device token. Nothing on the Linux Twin Box is changed.",
            "auto": False,
        })
    if not src.get("voice_ready"):
        steps.append({
            "id": "voice",
            "title": "Finish local voice",
            "detail": "Retry the local voice download. No cloud voice key is required.",
            "auto": True,
        })
    if not steps:
        steps.append({
            "id": "ok",
            "title": "Nothing to repair",
            "detail": "The checked pieces look ready.",
            "auto": False,
        })
    return steps


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return False
    return True


def _linux_live(path: Path) -> bool:
    return _is_within(path, Path(LINUX_LIVE_ROOT))


def _secret_name(name: str) -> bool:
    lowered = name.lower()
    return (
        lowered in {".env", "box.env", "owner.pass", "odysseus.token", "id_rsa", "credentials.json"}
        or lowered.endswith(".token")
        or lowered.endswith(".pem")
        or lowered.endswith(".key")
    )


def _data_base(root: Path) -> Path:
    packed = root / "heirloom"
    if (packed / "vault").is_dir() or (packed / "owner").is_dir() or (packed / "box.env").is_file():
        return packed
    return root


def _is_dump(path: Path) -> bool:
    name = path.name.lower()
    if name.endswith(".archive") or name.endswith(".bson"):
        return True
    return "mongo" in name or name.startswith("dump")


def inventory_backup(source: Path) -> dict[str, Any]:
    """Read-only catalog. Secret files contribute a name and a size, never bytes."""
    root = Path(source)
    if not root.is_dir():
        raise RestoreRefused("The backup folder was not found.")
    base = _data_base(root)
    slots: dict[str, Any] = {}
    files: list[dict[str, Any]] = []
    for name in SLOT_DIRS:
        slot = base / name
        if not slot.is_dir():
            continue
        slots[name] = {"present": True}
        for path in slot.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            if name == "backups" and not _is_dump(path):
                continue
            rel = path.relative_to(root).as_posix()
            files.append({
                "path": rel,
                "bytes": path.stat().st_size,
                "secret": _secret_name(path.name),
            })
    env = base / "box.env"
    if env.is_file() and not env.is_symlink():
        slots["box.env"] = {"present": True}
        files.append({"path": env.relative_to(root).as_posix(), "bytes": env.stat().st_size, "secret": True})
    for label, candidates in (
        ("odysseus", (root / "odysseus", root / "odysseus-app")),
        ("git-preserve", (root / "git-preserve", base / "git-preserve")),
    ):
        found = next((p for p in candidates if p.is_dir()), None)
        if found is None:
            continue
        slots[label] = {"present": True}
        for path in found.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            rel = path.relative_to(root).as_posix()
            files.append({
                "path": rel,
                "bytes": path.stat().st_size,
                "secret": _secret_name(path.name),
            })
    dumps = [row["path"] for row in files if _is_dump(Path(row["path"]))]
    hotfix = "git-preserve" in slots
    return {
        "source": str(root),
        "slots": slots,
        "files": files,
        "mongo_dumps": dumps,
        "hotfix": {
            "present": hotfix,
            "applied_to_git": False,
            "note": HOTFIX_NOTE if hotfix else "",
        },
        "contents_loaded": False,
    }


def _refuse_destination(
    source: Path,
    dest: Path,
    *,
    box_mode: bool,
    data_root: Path | None,
    new_machine: bool,
) -> str | None:
    if source.resolve() == dest.resolve():
        return "The backup and the destination are the same folder."
    if dest.exists() and _is_within(source, dest):
        return "The destination contains the backup. Nothing was written."
    if _is_within(dest, source):
        return "The destination is inside the backup. Nothing was written."
    if _linux_live(dest):
        return (
            "Refusing to write under /var/lib/heirloom. That folder is the live Linux Twin Box. "
            "Copy the backup to the new PC and import it there."
        )
    if data_root is not None and _is_within(dest, data_root):
        if _linux_live(data_root):
            return "Refusing to write into the live Linux data folder."
        if box_mode and not new_machine:
            return "Confirm this is the new PC before writing into its Heirloom folder."
    return None


def plan_restore(
    source: Path,
    dest: Path,
    *,
    box_mode: bool = False,
    data_root: Path | None = None,
    new_machine: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    root = Path(source)
    target = Path(dest)
    refused = None
    if not root.is_dir():
        refused = "The backup folder was not found."
    else:
        refused = _refuse_destination(
            root, target, box_mode=box_mode, data_root=data_root, new_machine=new_machine,
        )
    catalog = None
    copies: list[dict[str, str]] = []
    if refused is None:
        catalog = inventory_backup(root)
        for row in catalog["files"]:
            src_path = root / row["path"]
            rel = Path(row["path"])
            parts = rel.parts
            if parts[0] == "heirloom":
                rel = Path(*parts[1:]) if len(parts) > 1 else Path(parts[0])
            if parts[0] == "git-preserve" or (len(parts) > 1 and parts[1] == "git-preserve" and parts[0] == "heirloom"):
                if parts[0] == "heirloom":
                    tail = Path(*parts[2:]) if len(parts) > 2 else Path(".")
                else:
                    tail = Path(*parts[1:]) if len(parts) > 1 else Path(".")
                dest_path = target / "review" / "git-preserve" / tail
            else:
                dest_path = target / rel
            copies.append({
                "src": str(src_path),
                "dest": str(dest_path),
                "secret": "yes" if row["secret"] else "no",
            })
    hotfix = (catalog or {}).get("hotfix") or {"present": False, "applied_to_git": False, "note": ""}
    return {
        "source": str(root),
        "dest": str(target),
        "refused": refused,
        "confirm": bool(confirm),
        "copies": copies,
        "hotfix": hotfix,
        "deletes": [],
        "touches_live_box": False,
    }


def apply_restore(plan: dict[str, Any]) -> dict[str, Any]:
    """Copy files named by ``plan_restore``. Never deletes. Never writes the source."""
    if plan.get("refused"):
        raise RestoreRefused(str(plan["refused"]))
    if not plan.get("confirm"):
        raise RestoreRefused("Restore waits until you confirm it.")
    source = Path(plan["source"])
    written: list[dict[str, str]] = []
    for copy in plan.get("copies") or []:
        src = Path(copy["src"])
        dest = Path(copy["dest"])
        if not _is_within(src, source):
            raise RestoreRefused("A copy stepped outside the backup.")
        if _linux_live(dest) or _is_within(dest, source):
            raise RestoreRefused("Refusing to write into the backup or the live Linux Twin Box.")
        if not src.is_file():
            written.append({"dest": str(dest), "status": "missing"})
            continue
        before = src.read_bytes()
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            written.append({"dest": str(dest), "status": "left_in_place"})
        else:
            shutil.copy2(src, dest)
            written.append({"dest": str(dest), "status": "copied"})
        if src.read_bytes() != before:
            raise RestoreRefused("The backup changed while it was copied. Stopped.")
    return {
        "written": written,
        "hotfix_applied_to_git": False,
        "deleted": [],
    }


def box_mode_from_env() -> bool:
    return (os.environ.get("HEIRLOOM_BOX") or "").strip().lower() in {"1", "true", "yes", "on"}
