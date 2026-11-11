"""Split gpg Twin backups: checksums, passphrase handling, incremental layering."""
from __future__ import annotations

import hashlib
import subprocess
import tarfile
from pathlib import Path

import pytest

from backup_gpg import inspect_backup, restore_encrypted
from setup_center import RestoreRefused

PASSPHRASE = "correct horse battery staple"


def _sha_line(path: Path, root: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"{digest}  {path.relative_to(root).as_posix()}"


def _tar(path: Path, files: dict[str, str]) -> None:
    with tarfile.open(path, "w") as archive:
        for name, text in files.items():
            source = path.parent / ("src-" + Path(name).name)
            source.write_text(text, encoding="utf-8")
            archive.add(source, arcname=name)
            source.unlink()


def _encrypt(plain: Path, dest: Path, passphrase: str) -> None:
    subprocess.run(
        [
            "gpg", "--batch", "--yes", "--pinentry-mode", "loopback",
            "--passphrase-fd", "0", "--symmetric", "--cipher-algo", "AES256",
            "--output", str(dest), str(plain),
        ],
        input=(passphrase + "\n").encode(),
        check=True,
        capture_output=True,
    )


def _split(path: Path, folder: Path, logical: str) -> list[Path]:
    blob = path.read_bytes()
    mid = max(1, len(blob) // 2)
    parts = []
    for index, chunk in enumerate((blob[:mid], blob[mid:])):
        part = folder / f"{logical}.{index:03d}"
        part.write_bytes(chunk)
        parts.append(part)
    return parts


def _backup(folder: Path) -> None:
    full_tar = folder / "full.tar"
    incr_tar = folder / "incr.tar"
    _tar(full_tar, {
        "heirloom/vault/memory.txt": "oak tree original",
        "heirloom/owner/odysseus.token": "token-value-not-a-passphrase",
    })
    _tar(incr_tar, {
        "heirloom/vault/memory.txt": "oak tree updated",
        "heirloom/lab/turn.jsonl": "{}\n",
    })
    full_gpg = folder / "twinbox-useful-backup.tar.gpg"
    incr_gpg = folder / "twinbox-incr-20261108.tar.gpg"
    _encrypt(full_tar, full_gpg, PASSPHRASE)
    _encrypt(incr_tar, incr_gpg, PASSPHRASE)
    full_tar.unlink()
    incr_tar.unlink()
    parts = _split(full_gpg, folder, full_gpg.name) + _split(incr_gpg, folder, incr_gpg.name)
    full_gpg.unlink()
    incr_gpg.unlink()
    lines = [_sha_line(part, folder) for part in parts]
    (folder / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (folder / "MANIFEST").write_text(
        "\n".join([
            "# Twin Box",
            "full twinbox-useful-backup.tar.gpg 2026-11-05",
            "incremental twinbox-incr-20261108.tar.gpg 2026-11-08",
            "",
        ]),
        encoding="utf-8",
    )


def test_inspect_orders_the_full_set_before_incrementals(tmp_path: Path):
    _backup(tmp_path)
    report = inspect_backup(tmp_path)
    assert report["kind"] == "gpg"
    assert report["checksums_ok"] is True
    assert report["needs_passphrase"] is True
    assert [row["name"] for row in report["sets"]] == [
        "twinbox-useful-backup.tar.gpg",
        "twinbox-incr-20261108.tar.gpg",
    ]
    assert PASSPHRASE not in str(report)


def test_bad_checksum_refuses_before_decrypt(tmp_path: Path):
    _backup(tmp_path)
    sums = tmp_path / "SHA256SUMS"
    sums.write_text("deadbeef  twinbox-useful-backup.tar.gpg.000\n", encoding="utf-8")
    with pytest.raises(RestoreRefused) as caught:
        restore_encrypted(tmp_path, tmp_path / "out", PASSPHRASE, confirm=True, new_machine=True)
    assert PASSPHRASE not in str(caught.value)


def test_restore_layers_incrementals_and_hides_the_passphrase(tmp_path: Path):
    source = tmp_path / "drive"
    dest = tmp_path / "new-pc"
    source.mkdir()
    _backup(source)
    with pytest.raises(RestoreRefused) as wrong:
        restore_encrypted(source, dest, "not-the-passphrase", confirm=True, new_machine=True)
    assert "not-the-passphrase" not in str(wrong.value)
    result = restore_encrypted(source, dest, PASSPHRASE, confirm=True, new_machine=True)
    assert result["passphrase_stored"] is False
    assert result["refused"] is None
    assert PASSPHRASE not in str(result)
    assert (dest / "vault" / "memory.txt").read_text(encoding="utf-8") == "oak tree updated"
    assert (dest / "owner" / "odysseus.token").read_text(encoding="utf-8") == "token-value-not-a-passphrase"
    assert (dest / "lab" / "turn.jsonl").is_file()
    assert not Path("/var/lib/heirloom").exists()


def test_live_linux_root_is_still_refused(tmp_path: Path):
    _backup(tmp_path)
    result = restore_encrypted(
        tmp_path,
        Path("/var/lib/heirloom/imported"),
        PASSPHRASE,
        confirm=True,
        new_machine=True,
        box_mode=True,
    )
    assert result["refused"]
    assert "live Linux" in result["refused"]
    assert result["written"] == []
    assert PASSPHRASE not in str(result)
