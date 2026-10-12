"""``heirloom-box presence`` and the status lines for ``heirloom-box status``."""
from __future__ import annotations

import sys

from box_pause import share_pause
from presence_store import PresenceStore, presence_dir, presence_enabled, status_public


def _store() -> PresenceStore:
    return PresenceStore(presence_dir())


def format_status() -> str:
    payload = status_public(_store() if presence_enabled() else None)
    if not payload["enabled"]:
        return "enabled: no\n"
    cameras = payload.get("cameras") or []
    if cameras:
        names = ", ".join(str(item.get("path") or item.get("name") or "camera") for item in cameras if isinstance(item, dict))
    else:
        names = "none"
    present = payload.get("present") or []
    who = ", ".join(str(item.get("name") or "") for item in present if isinstance(item, dict) and item.get("name"))
    paused = "yes" if payload.get("paused") else "no"
    lines = [
        "enabled: yes",
        f"cameras: {names}",
        f"fps: {payload.get('fps') or 0}",
        f"enrolled: {payload.get('enrolled') or 0}",
        f"present: {who or 'nobody'}",
        f"paused: {paused}",
        f"model: {payload.get('model') or 'yunet+sface'}",
        f"backend: {payload.get('backend') or 'cpu'}",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "status"
    if command in {"-h", "--help", "help"}:
        print("Usage: presence_cli <status|pause|resume|forget>")
        return 0
    if command == "status":
        sys.stdout.write(format_status())
        return 0
    if not presence_enabled():
        print("Presence is off. Re-run the installer with --presence.", file=sys.stderr)
        return 1
    store = _store()
    if command == "pause":
        share_pause(True, "cli")
        store.set_paused(True, "cli")
        print("paused")
        return 0
    if command == "resume":
        share_pause(False, "")
        store.set_paused(False, "")
        print("resumed")
        return 0
    if command == "forget":
        store.forget_everyone()
        print("forgotten")
        return 0
    print(f"Unknown presence command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
