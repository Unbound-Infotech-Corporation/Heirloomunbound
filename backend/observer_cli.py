"""``heirloom-box observer`` and the status lines for ``heirloom-box status``."""
from __future__ import annotations

import sys

from observer_store import ObserverStore, observer_dir, observer_enabled, status_public


def _store() -> ObserverStore:
    return ObserverStore(observer_dir())


def format_status() -> str:
    payload = status_public(_store() if observer_enabled() else None)
    if not payload["enabled"]:
        return "enabled: no\n"
    disk = int(payload.get("disk_bytes") or 0)
    if disk >= 1024 * 1024:
        disk_label = f"{disk / (1024 * 1024):.1f} MB"
    else:
        disk_label = f"{disk} B"
    paused = "yes" if payload.get("paused") else "no"
    lines = [
        "enabled: yes",
        f"device: {payload.get('device') or 'none'}",
        f"signal: {payload.get('signal') or 'unknown'}",
        f"fps: {payload.get('fps') or 0}",
        f"model: {payload.get('model') or 'ocr'}",
        f"paused: {paused}",
        f"notes today: {payload.get('notes_today') or 0}",
        f"disk used: {disk_label}",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "status"
    if command in {"-h", "--help", "help"}:
        print("Usage: observer_cli <status|pause|resume|digest>")
        return 0
    if command == "status":
        sys.stdout.write(format_status())
        return 0
    if not observer_enabled():
        print("Observer is off. Re-run the installer with --observer.", file=sys.stderr)
        return 1
    store = _store()
    if command == "pause":
        store.set_paused(True, "cli")
        print("paused")
        return 0
    if command == "resume":
        store.set_paused(False, "")
        print("resumed")
        return 0
    if command == "digest":
        path = store.write_digest()
        print(path)
        return 0
    print(f"Unknown observer command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
