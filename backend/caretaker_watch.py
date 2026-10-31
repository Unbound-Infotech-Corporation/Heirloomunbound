"""Host watchdog. Every few minutes, restart ollama when it has lost the GPU.

This process does not reboot the machine, format disks, change fans or power
limits, read the owner password, or contact 192.168.0.16 / 192.168.0.19.
"""
from __future__ import annotations

import os
import sys

from caretaker import HostOps, gpu_lost, watchdog_decision


def main(argv: list[str] | None = None) -> int:
    del argv
    root = (os.environ.get("HEIRLOOM_ROOT") or "").strip()
    compose = os.path.join(root, "box") if root else ""
    ops = HostOps(compose_dir=compose)
    try:
        ps_text = ops.ollama_ps()
        log_text = ops.service_logs("ollama")
    except Exception as exc:  # noqa: BLE001
        print(f"caretaker watchdog could not read ollama: {exc}", file=sys.stderr)
        return 0
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
