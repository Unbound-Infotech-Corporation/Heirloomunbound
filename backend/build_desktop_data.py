"""Bake the /app/backend/companion_desktop/ tree into a single Python module.

Emergent's deploy bundler ships .py files but filters non-Python directories,
so /app/backend/companion_desktop/ shows up empty in production. To work
around that, this script reads every file in the source tree and writes them
into companion_desktop_data.py as a dict[path -> bytes].

The runtime (routers/companion.py) then prefers the in-memory dict over the
filesystem — same zip output, but the data is now compiled INTO the backend
package so Emergent will always include it.

Run this any time the desktop app source changes:

    cd /app/backend && python build_desktop_data.py
"""
from __future__ import annotations

import base64
import pathlib
import subprocess

SRC_ROOT = pathlib.Path(__file__).resolve().parent / "companion_desktop"
OUT = pathlib.Path(__file__).resolve().parent / "companion_desktop_data.py"


def git_short_sha() -> str:
    root = pathlib.Path(__file__).resolve().parents[1]
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=root,
                stderr=subprocess.DEVNULL,
            )
            .decode("ascii")
            .strip()
            or "dev"
        )
    except Exception:
        return "dev"


def stamp_build_id(rel: str, data: bytes, sha: str) -> bytes:
    if rel != "heirloom/__init__.py":
        return data
    text = data.decode("utf-8")
    text = text.replace('BUILD_ID = "dev"', f'BUILD_ID = "{sha}"')
    return text.encode("utf-8")


# Local PyInstaller / publish trees must never ship inside the Emergent bake.
_SKIP_DIR_NAMES = frozenset({
    "__pycache__",
    "build",
    "dist",
    ".venv",
    "venv",
    ".pytest_cache",
})


def collect_files() -> tuple[list[tuple[str, bytes]], str]:
    sha = git_short_sha()
    files: list[tuple[str, bytes]] = []
    for p in sorted(SRC_ROOT.rglob("*")):
        if not p.is_file():
            continue
        if any(part in _SKIP_DIR_NAMES for part in p.parts):
            continue
        rel = p.relative_to(SRC_ROOT).as_posix()
        files.append((rel, stamp_build_id(rel, p.read_bytes(), sha)))
    return files, sha


def build_module(files: list[tuple[str, bytes]], sha: str) -> str:
    lines = [
        '"""GENERATED — do not edit by hand. Regenerate with build_desktop_data.py."""',
        "import base64",
        "",
        f"DESKTOP_BUILD = {sha!r}",
        "DESKTOP_FILES: dict[str, bytes] = {",
    ]
    for rel, data in files:
        b64 = base64.b64encode(data).decode("ascii")
        # Emit as adjacent string literals (Python concatenates them automatically)
        chunks = [b64[i : i + 72] for i in range(0, len(b64), 72)]
        joined = "".join(f'\n        "{c}"' for c in chunks)
        lines.append(
            f"    {rel!r}: base64.b64decode({joined}\n    ),"
        )
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    if not SRC_ROOT.is_dir():
        raise SystemExit(f"source not found at {SRC_ROOT}")
    files, sha = collect_files()
    if not files:
        raise SystemExit(f"no files under {SRC_ROOT}")
    OUT.write_text(build_module(files, sha), encoding="utf-8")
    total = sum(len(b) for _, b in files)
    print(f"baked {len(files)} files ({total:,} bytes) build={sha} -> {OUT}")


if __name__ == "__main__":
    main()
