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
import textwrap

SRC_ROOT = pathlib.Path(__file__).resolve().parent / "companion_desktop"
OUT = pathlib.Path(__file__).resolve().parent / "companion_desktop_data.py"
WRITING_LOCAL_SRC = pathlib.Path(__file__).resolve().parent / "services" / "writing_local.py"
WRITING_LOCAL_DST = SRC_ROOT / "heirloom" / "writing_local.py"


def sync_writing_local() -> None:
    """Keep the desktop copy identical to the cloud local brain."""
    if not WRITING_LOCAL_SRC.is_file():
        raise SystemExit(f"missing {WRITING_LOCAL_SRC}")
    WRITING_LOCAL_DST.parent.mkdir(parents=True, exist_ok=True)
    WRITING_LOCAL_DST.write_text(WRITING_LOCAL_SRC.read_text(encoding="utf-8"), encoding="utf-8")


def collect_files() -> list[tuple[str, bytes]]:
    files: list[tuple[str, bytes]] = []
    for p in sorted(SRC_ROOT.rglob("*")):
        if not p.is_file():
            continue
        if "__pycache__" in p.parts:
            continue
        rel = p.relative_to(SRC_ROOT).as_posix()
        files.append((rel, p.read_bytes()))
    return files


def build_module(files: list[tuple[str, bytes]]) -> str:
    lines = [
        '"""GENERATED — do not edit by hand. Regenerate with build_desktop_data.py."""',
        "import base64",
        "",
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
    sync_writing_local()
    files = collect_files()
    if not files:
        raise SystemExit(f"no files under {SRC_ROOT}")
    OUT.write_text(build_module(files), encoding="utf-8")
    total = sum(len(b) for _, b in files)
    print(f"baked {len(files)} files ({total:,} bytes) → {OUT}")


if __name__ == "__main__":
    main()
