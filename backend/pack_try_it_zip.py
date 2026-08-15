"""Build a grandmother-simple try-it zip for Unbound Keyboard.

Unzip, copy to Desktop, double-click Try-Unbound-Keyboard.bat.

    python3 pack_try_it_zip.py
    python3 pack_try_it_zip.py /tmp/Heirloom-Unbound-Keyboard.zip
"""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = Path(__file__).resolve().parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
DESKTOP = BACKEND / "companion_desktop"
ANDROID = ROOT / "android" / "unbound-keyboard"

SKIP_DIR_NAMES = {
    "__pycache__",
    ".gradle",
    ".idea",
    "build",
    ".git",
}
SKIP_FILE_NAMES = {
    "local.properties",
    ".DS_Store",
}


def _skip(path: Path, root: Path) -> bool:
    rel_parts = path.relative_to(root).parts
    if any(part in SKIP_DIR_NAMES for part in rel_parts[:-1]):
        return True
    if path.name in SKIP_FILE_NAMES:
        return True
    if path.suffix in {".pyc", ".pyo"}:
        return True
    return False


def _add_tree(zf: zipfile.ZipFile, src_root: Path, zip_prefix: str) -> int:
    count = 0
    for path in sorted(src_root.rglob("*")):
        if not path.is_file() or _skip(path, src_root):
            continue
        rel = path.relative_to(src_root).as_posix()
        info = zipfile.ZipInfo(f"{zip_prefix}/{rel}")
        info.compress_type = zipfile.ZIP_DEFLATED
        if path.name in {"run.sh", "Try-Unbound-Keyboard.bat", "Heirloom.bat"}:
            info.external_attr = 0o755 << 16
        zf.writestr(info, path.read_bytes())
        count += 1
    return count


def build_try_it_zip(dest: Path) -> Path:
    if not DESKTOP.is_dir():
        raise SystemExit(f"missing desktop app at {DESKTOP}")
    if not ANDROID.is_dir():
        raise SystemExit(f"missing Android keyboard at {ANDROID}")

    from build_desktop_data import sync_writing_local

    sync_writing_local()

    dest.parent.mkdir(parents=True, exist_ok=True)
    start_here = (DESKTOP / "START HERE.txt").read_bytes()

    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        info = zipfile.ZipInfo("Heirloom-Unbound-Keyboard/START HERE.txt")
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, start_here)
        win = _add_tree(zf, DESKTOP, "Heirloom-Unbound-Keyboard/Windows")
        droid = _add_tree(zf, ANDROID, "Heirloom-Unbound-Keyboard/Android")
        apk = ANDROID / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
        if apk.is_file():
            apk_info = zipfile.ZipInfo("Heirloom-Unbound-Keyboard/Android/UnboundKeyboard.apk")
            apk_info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(apk_info, apk.read_bytes())
            droid += 1
            artifacts = Path("/opt/cursor/artifacts")
            if artifacts.is_dir() or artifacts.parent.is_dir():
                artifacts.mkdir(parents=True, exist_ok=True)
                (artifacts / "UnboundKeyboard.apk").write_bytes(apk.read_bytes())

    size = dest.stat().st_size
    print(f"wrote {dest} ({size:,} bytes, {win} Windows files, {droid} Android files)")
    return dest


def default_destinations() -> list[Path]:
    dests = [Path("/tmp/Heirloom-Unbound-Keyboard.zip")]
    artifacts = Path("/opt/cursor/artifacts")
    if artifacts.is_dir() or artifacts.parent.is_dir():
        dests.append(artifacts / "Heirloom-Unbound-Keyboard.zip")
    return dests


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pack Unbound Keyboard try-it zip")
    parser.add_argument("dest", nargs="?", help="Zip path (default: /tmp and artifacts)")
    args = parser.parse_args(argv)
    if args.dest:
        build_try_it_zip(Path(args.dest))
        return 0
    for dest in default_destinations():
        try:
            build_try_it_zip(dest)
        except OSError as exc:
            print(f"skip {dest}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
