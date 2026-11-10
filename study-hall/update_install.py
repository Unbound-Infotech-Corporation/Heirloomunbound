"""Copy Study Hall onto an existing install without nesting code folders.

PowerShell's ``Copy-Item -Recurse`` drops a source directory inside a destination
directory of the same name (``studyhall\\studyhall``). This replaces code
folders outright and leaves the owner's data alone.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

PRESERVE_DIRS = {"data", "ollama-models", "logs", ".venv"}
PRESERVE_FILES = {"setup-models.ps1", "config.json"}
OBSOLETE_FILES = {"Launch-StudyHall.ps1"}
SKIP_SOURCE = PRESERVE_DIRS | {"__pycache__", ".pytest_cache", ".git"}


def update_tree(source: Path, dest: Path) -> dict:
    source = source.resolve()
    dest = dest.resolve()
    report = {"copied": [], "removed_obsolete": [], "preserved": []}
    if source == dest:
        report["skipped"] = "source and destination are the same folder"
        return report
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("data", "ollama-models", "logs"):
        (dest / name).mkdir(exist_ok=True)
    (dest / "data" / "knowledge").mkdir(exist_ok=True)

    for name in OBSOLETE_FILES:
        stale = dest / name
        if stale.is_file():
            stale.unlink()
            report["removed_obsolete"].append(name)

    for name in sorted(PRESERVE_DIRS | PRESERVE_FILES):
        if (dest / name).exists():
            report["preserved"].append(name)

    for item in sorted(source.iterdir(), key=lambda path: path.name):
        if item.name in SKIP_SOURCE or item.name.startswith("."):
            continue
        target = dest / item.name
        if item.name in PRESERVE_FILES and target.exists():
            continue
        if item.name in PRESERVE_DIRS:
            continue
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(
                item,
                target,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
            )
        else:
            if target.is_dir():
                shutil.rmtree(target)
            shutil.copy2(item, target)
        report["copied"].append(item.name)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Update a Study Hall install in place.")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--dest", type=Path, required=True)
    args = parser.parse_args(argv)
    report = update_tree(args.source, args.dest)
    print(
        f"Updated {args.dest} ({len(report['copied'])} items). "
        f"Kept {', '.join(report['preserved']) or 'nothing extra'}."
    )
    if report["removed_obsolete"]:
        print("Removed obsolete " + ", ".join(report["removed_obsolete"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
