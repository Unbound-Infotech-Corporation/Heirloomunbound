"""Host watchdog. Every few minutes, restart ollama when it has lost the GPU.

This process does not reboot the machine, format disks, change fans or power
limits, read the owner password, or contact 192.168.0.16 / 192.168.0.19.
"""
from __future__ import annotations

import os
import sys

from caretaker import HostOps, gpu_lost, watchdog_decision


def _record_observer_unit() -> None:
    """Write a fresh unit snapshot the API health check can read. Best effort."""
    import json
    import subprocess
    from pathlib import Path

    from caretaker import parse_systemctl_show

    data_root = Path((os.environ.get("HEIRLOOM_DATA_ROOT") or "/var/lib/heirloom").strip() or "/var/lib/heirloom")
    try:
        completed = subprocess.run(
            [
                "systemctl", "show", "heirloom-observer.service",
                "-p", "NRestarts", "-p", "ActiveState", "-p", "SubState", "-p", "Result",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
        snapshot = parse_systemctl_show((completed.stdout or "") + (completed.stderr or ""))
    except (OSError, subprocess.TimeoutExpired):
        return
    folder = data_root / "observer"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "unit.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(snapshot, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError:
        return


def _apply_observer_wish() -> None:
    """Match the systemd unit to the owner's opt-in file. No-op when they agree."""
    import json
    import subprocess
    from pathlib import Path

    from caretaker import observer_opt_actions

    data_root = Path((os.environ.get("HEIRLOOM_DATA_ROOT") or "/var/lib/heirloom").strip() or "/var/lib/heirloom")
    wish_path = data_root / "observer" / "owner-opt-in.json"
    if not wish_path.is_file():
        return
    try:
        wished = bool(json.loads(wish_path.read_text(encoding="utf-8")).get("enabled"))
    except (OSError, json.JSONDecodeError, TypeError):
        return
    etc = Path("/etc/heirloom/observer.opt-in")
    env_file = data_root / "box.env"
    env_on = False
    lines: list[str] = []
    if env_file.is_file():
        lines = env_file.read_text(encoding="utf-8").splitlines()
        for line in lines:
            if line.startswith("HEIRLOOM_OBSERVER="):
                env_on = line.split("=", 1)[1].strip().lower() in {"1", "true", "yes", "on"}
    actions = observer_opt_actions(wished=wished, etc_present=etc.is_file(), env_on=env_on)
    if not actions:
        return
    enabled = actions == ["enable"]
    try:
        if enabled:
            etc.parent.mkdir(parents=True, exist_ok=True)
            etc.write_text("on\n", encoding="utf-8")
        elif etc.is_file():
            etc.unlink()
        flag = "1" if enabled else "0"
        replaced = False
        updated = []
        for line in lines:
            if line.startswith("HEIRLOOM_OBSERVER="):
                updated.append(f"HEIRLOOM_OBSERVER={flag}")
                replaced = True
            else:
                updated.append(line)
        if not replaced:
            updated.append(f"HEIRLOOM_OBSERVER={flag}")
        if lines or env_file.parent.is_dir():
            env_file.write_text("\n".join(updated) + ("\n" if updated else ""), encoding="utf-8")
        if enabled:
            subprocess.run(["systemctl", "reset-failed", "heirloom-observer.service"], check=False, timeout=20)
            subprocess.run(["systemctl", "enable", "--now", "heirloom-observer.service"], check=False, timeout=20)
        else:
            subprocess.run(["systemctl", "disable", "--now", "heirloom-observer.service"], check=False, timeout=20)
            subprocess.run(["systemctl", "reset-failed", "heirloom-observer.service"], check=False, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"caretaker watchdog could not apply the observer opt-in: {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    del argv
    try:
        _record_observer_unit()
    except Exception as exc:  # noqa: BLE001
        print(f"caretaker watchdog could not record the observer unit: {exc}", file=sys.stderr)
    try:
        _apply_observer_wish()
    except Exception as exc:  # noqa: BLE001
        print(f"caretaker watchdog could not apply the observer opt-in: {exc}", file=sys.stderr)
    root = (os.environ.get("HEIRLOOM_ROOT") or "").strip()
    compose = os.path.join(root, "box") if root else ""
    ops = HostOps(compose_dir=compose)
    try:
        ps_text = ops.ollama_ps()
        log_text = ops.service_logs("ollama")
    except Exception as exc:  # noqa: BLE001
        print(f"caretaker watchdog could not read ollama: {exc}", file=sys.stderr)
        return 0
    try:
        repaired = ops.repair_observer_mount()
    except Exception as exc:  # noqa: BLE001
        print(f"caretaker watchdog could not check the observer mount: {exc}", file=sys.stderr)
        repaired = ""
    if repaired:
        print("caretaker watchdog: observer mount was stale, recreated box-api-1")
    decision = watchdog_decision(ps_text, log_text)
    if decision != "restart_ollama":
        print("caretaker watchdog: ollama still has the GPU")
        return 0
    if not gpu_lost(ps_text, log_text):
        print("caretaker watchdog: ollama still has the GPU")
        return 0
    print("caretaker watchdog: ollama lost the GPU, restarting the container")
    try:
        ops.restart("ollama")
        sample = ops.short_generation()
        print(f"caretaker watchdog: generation check {sample[:180]}")
    except Exception as exc:  # noqa: BLE001
        print(f"caretaker watchdog restart failed: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
