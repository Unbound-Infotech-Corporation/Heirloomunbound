#!/usr/bin/env python3
"""Choose the one internal disk Ubuntu autoinstall is allowed to erase.

Fail closed. An empty serial, a serial that matches nothing, more than one
match, or a match that is removable, USB, or the boot stick aborts. This
module never partitions, wipes, or opens a disk for writing.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass

EXIT_OK = 0
EXIT_EMPTY = 10
EXIT_NO_MATCH = 11
EXIT_AMBIGUOUS = 12
EXIT_UNSAFE = 13
EXIT_BAD_SERIAL = 14
EXIT_CONFIG = 15

PLACEHOLDER = "HEIRLOOM-REFUSE-NO-DISK-MATCH"
SERIAL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]{2,126}$")


@dataclass(frozen=True)
class Disk:
    name: str
    serial: str
    tran: str
    removable: bool
    type: str
    size: str
    model: str
    id_serial: str = ""
    id_serial_short: str = ""


@dataclass(frozen=True)
class Decision:
    code: int
    message: str
    disk: Disk | None = None


def normalize_serial(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def unquote_config_value(value: object) -> str:
    """Drop one pair of matching quotes and the whitespace around a config value."""
    text = normalize_serial(value).strip("\r")
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1].strip().strip("\r")
    return text


def as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes"}


def sysfs_serial(name: str, sysfs_root: str) -> str:
    for relative in (f"block/{name}/serial", f"block/{name}/device/serial"):
        path = os.path.join(sysfs_root, relative)
        try:
            with open(path, encoding="utf-8") as handle:
                serial = handle.read().strip()
        except OSError:
            continue
        if serial:
            return serial
    return ""


def load_inventory(path: str, sysfs_root: str) -> list[Disk]:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict):
        devices = payload.get("blockdevices", [])
    elif isinstance(payload, list):
        devices = payload
    else:
        raise ValueError("disk inventory must be a list or an lsblk -J object")
    disks: list[Disk] = []
    for raw in devices:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        serial = normalize_serial(raw.get("serial"))
        if not serial:
            serial = sysfs_serial(name, sysfs_root)
        disks.append(
            Disk(
                name=name,
                serial=serial,
                tran=str(raw.get("tran") or "").strip().lower(),
                removable=as_bool(raw.get("rm", raw.get("removable"))),
                type=str(raw.get("type") or "").strip().lower(),
                size=str(raw.get("size") or "").strip(),
                model=str(raw.get("model") or "").strip(),
                id_serial=normalize_serial(raw.get("id_serial")),
                id_serial_short=normalize_serial(raw.get("id_serial_short")),
            )
        )
    return disks


def is_boot_media(disk: Disk, cdrom_names: set[str]) -> bool:
    if disk.name in cdrom_names:
        return True
    if disk.type in {"rom", "loop"}:
        return True
    if disk.name.startswith(("sr", "fd")):
        return True
    return False


def is_removable_or_usb(disk: Disk) -> bool:
    if disk.removable:
        return True
    if disk.tran == "usb":
        return True
    return False


def identifiers(disk: Disk) -> set[str]:
    found: set[str] = set()
    for value in (disk.serial, disk.id_serial, disk.id_serial_short):
        value = normalize_serial(value)
        if value:
            found.add(value)
    return found


def safe_udev_serial(value: str) -> str:
    """Serial subiquity can match as ID_SERIAL without treating it as a glob."""
    value = normalize_serial(value)
    if not value or "\n" in value or "\r" in value:
        return ""
    if re.search(r"[*?[]", value):
        return ""
    return value


def device_path(disk: Disk) -> str:
    if not re.fullmatch(r"[A-Za-z0-9]+", disk.name):
        raise ValueError(f"Refusing device name {disk.name!r}.")
    return f"/dev/{disk.name}"


def match_specs(disk: Disk) -> list[dict[str, str]]:
    specs: list[dict[str, str]] = []
    udev = safe_udev_serial(disk.id_serial)
    if udev:
        specs.append({"serial": udev})
    specs.append({"path": device_path(disk)})
    return specs


def decide(serial: str, disks: list[Disk], cdrom_names: set[str]) -> Decision:
    serial = unquote_config_value(serial)
    if serial == "" or serial == PLACEHOLDER:
        return Decision(
            EXIT_EMPTY,
            "TARGET_DISK_SERIAL is empty. Refusing to erase any disk.",
        )
    if not SERIAL_RE.match(serial):
        return Decision(
            EXIT_BAD_SERIAL,
            "TARGET_DISK_SERIAL contains characters the installer will not accept. "
            "Use the serial printed by lsblk, with no spaces or quotes.",
        )

    exact = [
        disk
        for disk in disks
        if disk.type == "disk" and serial in identifiers(disk)
    ]
    if not exact:
        return Decision(
            EXIT_NO_MATCH,
            f"No disk serial matches {serial}. Refusing to erase any disk.",
        )
    if len(exact) > 1:
        names = ", ".join(disk.name for disk in exact)
        return Decision(
            EXIT_AMBIGUOUS,
            f"Serial {serial} matches more than one disk ({names}). "
            "Refusing to erase any disk.",
        )
    disk = exact[0]
    if is_boot_media(disk, cdrom_names) or is_removable_or_usb(disk):
        return Decision(
            EXIT_UNSAFE,
            f"Serial {serial} is {disk.name}, which is removable, USB, or the "
            "boot stick. Refusing to erase it.",
        )
    return Decision(EXIT_OK, f"Matched /dev/{disk.name} serial {serial}.", disk)


def render_match_block(indent: str, disk: Disk) -> str:
    child = indent + "  "
    lines = [f"{indent}match:"]
    for spec in match_specs(disk):
        key, value = next(iter(spec.items()))
        lines.append(f"{child}- {key}: {json.dumps(value)}")
    return "\n".join(lines)


def replace_match_block(text: str, disk: Disk) -> str:
    if text.count(PLACEHOLDER) != 1:
        raise ValueError(
            f"{PLACEHOLDER} must appear exactly once in the autoinstall file "
            f"(found {text.count(PLACEHOLDER)})."
        )
    pattern = re.compile(
        r"^(?P<indent>[ \t]*)match:[ \t]*\n"
        r"(?P=indent)[ \t]+serial:[ \t]*(?:\"|')?"
        + re.escape(PLACEHOLDER)
        + r"(?:\"|')?[ \t]*$",
        re.MULTILINE,
    )

    def repl(match: re.Match[str]) -> str:
        return render_match_block(match.group("indent"), disk)

    updated, count = pattern.subn(repl, text, count=1)
    if count != 1:
        raise ValueError("Could not replace the storage match placeholder.")
    if PLACEHOLDER in updated:
        raise ValueError("Placeholder serial survived the rewrite. Refusing to continue.")
    path = device_path(disk)
    if json.dumps(path) not in updated:
        raise ValueError("Resolved device path was not written into the autoinstall file.")
    udev = safe_udev_serial(disk.id_serial)
    if udev and json.dumps(udev) not in updated:
        raise ValueError("udev ID_SERIAL was not written into the autoinstall file.")
    return updated


def write_match(autoinstall_path: str, record_path: str, serial: str, disk: Disk) -> None:
    with open(autoinstall_path, encoding="utf-8") as handle:
        original = handle.read()
    updated = replace_match_block(original, disk)
    parent = os.path.dirname(record_path)
    if parent:
        os.makedirs(parent, mode=0o755, exist_ok=True)
    auto_dir = os.path.dirname(autoinstall_path) or "."
    os.makedirs(auto_dir, mode=0o755, exist_ok=True)
    temporary = autoinstall_path + ".heirloom-tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(updated)
    os.replace(temporary, autoinstall_path)
    udev = safe_udev_serial(disk.id_serial)
    shown = disk.serial or disk.id_serial_short or udev
    record = (
        "# Disk the installer is allowed to erase. Written by resolve-disk.sh\n"
        "# after the owner serial matched exactly one internal, non-removable disk.\n"
        "# match.serial is udev ID_SERIAL. match.path is that disk in this boot.\n"
        "storage:\n"
        "  layout:\n"
        "    name: direct\n"
        f"{render_match_block('    ', disk)}\n"
        f"device: {device_path(disk)}\n"
        f"owner_serial: {json.dumps(serial)}\n"
        f"lsblk_serial: {json.dumps(shown)}\n"
        f"udev_serial: {json.dumps(udev)}\n"
        f"name: {json.dumps(disk.name)}\n"
        f"tran: {json.dumps(disk.tran)}\n"
        "removable: false\n"
    )
    record_temporary = record_path + ".heirloom-tmp"
    with open(record_temporary, "w", encoding="utf-8") as handle:
        handle.write(record)
    os.replace(record_temporary, record_path)


def parse_cdrom_names(value: str) -> set[str]:
    names: set[str] = set()
    for part in value.split(","):
        name = part.strip().removeprefix("/dev/")
        if name:
            names.add(_disk_name(name))
    return names


def _disk_name(name: str) -> str:
    if re.fullmatch(r"nvme\d+n\d+p\d+", name):
        return re.sub(r"p\d+$", "", name)
    if re.fullmatch(r"mmcblk\d+p\d+", name):
        return re.sub(r"p\d+$", "", name)
    if re.fullmatch(r"[a-z]+\d+", name) and not name.startswith("nvme"):
        return re.sub(r"\d+$", "", name)
    return name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--cdrom", default="")
    parser.add_argument("--autoinstall", default="")
    parser.add_argument("--record", default="")
    parser.add_argument("--sysfs", default=os.environ.get("HEIRLOOM_SYSFS_BLOCK", "/sys"))
    args = parser.parse_args(argv)

    try:
        disks = load_inventory(args.inventory, args.sysfs)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"HEIRLOOM_DISK_ABORT code={EXIT_CONFIG} {exc}", file=sys.stderr)
        return EXIT_CONFIG

    serial = unquote_config_value(args.serial)
    decision = decide(serial, disks, parse_cdrom_names(args.cdrom))
    if decision.code != EXIT_OK or decision.disk is None:
        print(f"HEIRLOOM_DISK_ABORT code={decision.code} {decision.message}", file=sys.stderr)
        return decision.code

    if args.autoinstall:
        try:
            record = args.record or "/run/heirloom-autoinstall/storage-match.yaml"
            write_match(args.autoinstall, record, serial, decision.disk)
        except (OSError, ValueError) as exc:
            print(f"HEIRLOOM_DISK_ABORT code={EXIT_CONFIG} {exc}", file=sys.stderr)
            return EXIT_CONFIG

    disk = decision.disk
    shown = disk.serial or disk.id_serial_short or disk.id_serial
    udev = safe_udev_serial(disk.id_serial) or "none"
    print(
        f"HEIRLOOM_DISK_MATCH device={device_path(disk)} "
        f"serial={shown} tran={disk.tran or 'unknown'} "
        f"udev_serial={udev} path={device_path(disk)}"
    )
    print(decision.message, file=sys.stderr)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
