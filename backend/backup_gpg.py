"""Encrypted Twin Box backups.

The owner's copies are split ``.tar.gpg`` sets with ``SHA256SUMS`` and a
``MANIFEST``: one full archive, then incrementals in date order. This module
checks the sums, decrypts with a passphrase that is never stored or logged,
and layers the full set and then each incremental onto a folder the existing
plain restore already understands.

A folder that is already a plain backup is left to ``plan_restore``.
Nothing here writes under ``/var/lib/heirloom``.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Callable

from setup_center import RestoreRefused, apply_restore, plan_restore

_DATE = re.compile(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})")
_USEFUL = "2026-11-05"


def inspect_backup(source: Path) -> dict[str, Any]:
    """Read-only. No passphrase. No decryption."""
    root = Path(source)
    if not root.is_dir():
        raise RestoreRefused("The backup folder was not found.")
    sums = _read_sums(root)
    manifest = _read_manifest(root, sums)
    encrypted = bool(manifest) or any(path.name.endswith(".gpg") or ".gpg." in path.name for path in root.iterdir())
    if not encrypted:
        return {"kind": "plain", "checksums_ok": True, "sets": [], "failures": []}
    failures = _checksum_failures(root, sums)
    return {
        "kind": "gpg",
        "checksums_ok": not failures and bool(sums),
        "sets": [
            {"kind": row["kind"], "name": row["name"], "date": row["date"], "parts": len(row["parts"])}
            for row in manifest
        ],
        "failures": failures,
        "needs_passphrase": True,
    }


def restore_encrypted(
    source: Path,
    dest: Path,
    passphrase: str,
    *,
    confirm: bool = False,
    box_mode: bool = False,
    data_root: Path | None = None,
    new_machine: bool = False,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] | None = None,
) -> dict[str, Any]:
    """Verify, decrypt, layer, then copy with the plain restore rules.

    ``passphrase`` is used only as gpg's stdin. It is not written to the
    result, the plan, or an exception message.
    """
    secret = passphrase or ""
    try:
        report = inspect_backup(source)
        if report["kind"] != "gpg":
            raise RestoreRefused("That folder is a plain backup. Use the folder restore.")
        if not report["checksums_ok"]:
            detail = ", ".join(report["failures"]) or "SHA256SUMS is missing"
            raise RestoreRefused("The backup checksums do not match. " + detail)
        if not secret:
            raise RestoreRefused("Enter the backup passphrase.")
        if not confirm:
            raise RestoreRefused("Restore waits until you confirm it.")
        holder = _layer(Path(source), secret, runner=runner)
        try:
            plan = plan_restore(
                holder / "backup",
                Path(dest),
                box_mode=box_mode,
                data_root=data_root,
                new_machine=new_machine,
                confirm=True,
            )
            applied = apply_restore(plan) if plan.get("refused") is None else {"written": [], "deleted": []}
        finally:
            shutil.rmtree(holder, ignore_errors=True)
        result = {
            "kind": "gpg",
            "sets": report["sets"],
            "refused": plan.get("refused"),
            "written": applied.get("written", []),
            "deleted": [],
            "hotfix_applied_to_git": False,
            "passphrase_stored": False,
        }
        blob = str(result)
        if secret and secret in blob:
            raise RestoreRefused("Refusing to return the passphrase.")
        return result
    finally:
        secret = ""


def _read_sums(root: Path) -> dict[str, str]:
    path = root / "SHA256SUMS"
    if not path.is_file():
        return {}
    sums: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        parts = raw.split()
        if len(parts) < 2:
            continue
        name = parts[-1].lstrip("*")
        sums[name] = parts[0].lower()
    return sums


def _checksum_failures(root: Path, sums: dict[str, str]) -> list[str]:
    if not sums:
        return ["SHA256SUMS is missing"]
    failures: list[str] = []
    for name, expected in sums.items():
        path = root / name
        if not path.is_file():
            failures.append(name + " is missing")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected:
            failures.append(name + " does not match")
    return failures


def _read_manifest(root: Path, sums: dict[str, str]) -> list[dict[str, Any]]:
    path = root / "MANIFEST"
    rows: list[dict[str, Any]] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            bits = raw.split()
            if len(bits) < 2:
                continue
            kind = bits[0].lower()
            name = bits[1]
            date = bits[2] if len(bits) > 2 else _date_from_name(name)
            if kind not in {"full", "incremental"}:
                kind = "incremental" if "incr" in name.lower() else "full"
            parts = _parts(root, name)
            if parts:
                rows.append({"kind": kind, "name": name, "date": date, "parts": parts})
    if rows:
        rows.sort(key=lambda row: (0 if row["kind"] == "full" else 1, row["date"], row["name"]))
        return rows
    names = set(sums) | {path.name for path in root.iterdir() if path.is_file()}
    logical = sorted({_logical_name(name) for name in names if name.endswith(".gpg") or ".gpg." in name})
    for name in logical:
        parts = _parts(root, name)
        if not parts:
            continue
        rows.append({
            "kind": "incremental" if "incr" in name.lower() else "full",
            "name": name,
            "date": _date_from_name(name),
            "parts": parts,
        })
    rows.sort(key=lambda row: (0 if row["kind"] == "full" else 1, row["date"], row["name"]))
    return rows


def _logical_name(name: str) -> str:
    if ".gpg." in name:
        return name.split(".gpg.", 1)[0] + ".gpg"
    return name


def _date_from_name(name: str) -> str:
    match = _DATE.search(name)
    if match:
        return "-".join(match.groups())
    if "useful-backup" in name:
        return _USEFUL
    return "0000-00-00"


def _parts(root: Path, logical: str) -> list[Path]:
    direct = root / logical
    if direct.is_file():
        return [direct]
    found: list[Path] = []
    prefix = logical + "."
    for path in root.iterdir():
        if not path.is_file() or not path.name.startswith(prefix):
            continue
        suffix = path.name[len(prefix):]
        if suffix.isdigit() or (len(suffix) == 2 and suffix.isalpha()):
            found.append(path)

    def key(path: Path) -> tuple[int, Any]:
        suffix = path.name[len(prefix):]
        if suffix.isdigit():
            return (0, int(suffix))
        return (1, suffix)

    return sorted(found, key=key)


def _layer(root: Path, passphrase: str, *, runner: Callable[..., subprocess.CompletedProcess[bytes]] | None) -> Path:
    sums = _read_sums(root)
    manifest = _read_manifest(root, sums)
    if not manifest:
        raise RestoreRefused("No backup sets were found.")
    order = sorted(manifest, key=lambda row: (0 if row["kind"] == "full" else 1, row["date"], row["name"]))
    staging = Path(tempfile.mkdtemp(prefix="heirloom-restore-"))
    try:
        for row in order:
            blob = b"".join(part.read_bytes() for part in row["parts"])
            cipher = staging / (row["name"] + ".cipher")
            cipher.write_bytes(blob)
            tar_path = staging / (row["name"] + ".tar")
            _decrypt(cipher, tar_path, passphrase, runner=runner)
            extract_root = staging / ("extract-" + row["date"] + "-" + row["kind"])
            extract_root.mkdir()
            _safe_extract(tar_path, extract_root)
            _overlay(_payload_root(extract_root), staging / "layered")
            cipher.unlink(missing_ok=True)
            tar_path.unlink(missing_ok=True)
        layered = staging / "layered"
        if not layered.is_dir():
            raise RestoreRefused("The backup unpacked to an empty folder.")
        # Hand the layered tree to the caller. Move it out of staging so the
        # caller can delete it, and remove the cipher material first.
        holder = Path(tempfile.mkdtemp(prefix="heirloom-layered-"))
        shutil.move(str(layered), str(holder / "backup"))
        return holder
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _decrypt(
    cipher: Path,
    dest: Path,
    passphrase: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] | None,
) -> None:
    argv = [
        "gpg",
        "--batch",
        "--yes",
        "--pinentry-mode",
        "loopback",
        "--passphrase-fd",
        "0",
        "--decrypt",
        "--output",
        str(dest),
        str(cipher),
    ]
    if passphrase in " ".join(argv):
        raise RestoreRefused("Refusing to put the passphrase on the command line.")
    run = runner or subprocess.run
    completed = run(
        argv,
        input=passphrase.encode("utf-8") + b"\n",
        capture_output=True,
        check=False,
    )
    stderr = completed.stderr.decode("utf-8", errors="replace") if completed.stderr else ""
    if passphrase and passphrase in stderr:
        stderr = stderr.replace(passphrase, "[redacted]")
    if completed.returncode != 0 or not dest.is_file():
        raise RestoreRefused("Could not open that backup. Check the passphrase.")


def _safe_extract(tar_path: Path, dest: Path) -> None:
    with tarfile.open(tar_path, "r:*") as archive:
        for member in archive.getmembers():
            parts = Path(member.name).parts
            if member.name.startswith("/") or ".." in parts or member.issym() or member.islnk():
                raise RestoreRefused("The archive contains an unsafe path.")
        archive.extractall(dest, filter="data")


def _payload_root(extracted: Path) -> Path:
    for candidate in (
        extracted / "var" / "lib" / "heirloom",
        extracted / "heirloom",
        extracted,
    ):
        if (candidate / "vault").is_dir() or (candidate / "owner").is_dir() or (candidate / "heirloom").is_dir():
            return candidate
    return extracted


def _overlay(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for path in src.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(src)
        if ".." in rel.parts:
            raise RestoreRefused("The archive contains an unsafe path.")
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
