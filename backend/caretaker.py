"""Caretaker clone: diagnose the Twin Box and the BIGDEAL Companion.

Owner-only. Safe actions run immediately. Anything past that allowlist waits
for confirm. Hard rules never run, even after confirm.

Ollama-only. This module does not call a cloud model and does not read the
owner password file.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

FORBIDDEN_HOSTS = ("192.168.0.16", "192.168.0.19")
NVML_LOST = "Failed to initialize NVML"
CPU_ONLY = "100% CPU"
TIMEOUT_MARK = "Local twin (Ollama) failed"

SAFE_ACTIONS = frozenset({
    "show_health",
    "report_timeout",
    "restart_ollama",
    "restart_chatterbox",
    "restart_api",
    "repush_companion_settings",
    "restart_companion",
})

GPU_SERVICES = frozenset({"ollama", "chatterbox", "api"})
RESTART_ACTIONS = {
    "restart_ollama": "ollama",
    "restart_chatterbox": "chatterbox",
    "restart_api": "api",
}

REFUSAL_COPY = {
    "reboot": "Caretaker will not reboot BIGDEAL.",
    "format": "Caretaker will not format or wipe a drive.",
    "password": "Caretaker does not ask for or handle the owner password.",
    "fan": "Caretaker does not change fan curves. GPU temperature is read-only.",
    "power": "Caretaker does not change power limits.",
    "host": "Caretaker does not touch 192.168.0.16 or 192.168.0.19.",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def scrub(text: str) -> str:
    """Drop anything that looks like a password before it is logged or echoed."""
    raw = text or ""
    raw = re.sub(r"(?i)(password\s*[:=]\s*)(\S+)", r"\1[redacted]", raw)
    raw = re.sub(r"(?i)\b(owner\.pass)\b", "[redacted]", raw)
    return raw


def hard_refusal(text: str) -> Optional[str]:
    """Return a refusal code, or None when the text is allowed to proceed."""
    raw = text or ""
    lowered = raw.lower()
    if any(host in raw for host in FORBIDDEN_HOSTS):
        return "host"
    if re.search(r"\b(format|mkfs|diskpart|wipe)\b", lowered) or "wipe the" in lowered or "format the" in lowered:
        return "format"
    if re.search(r"\breboot\b", lowered) or "restart bigdeal" in lowered or "shutdown bigdeal" in lowered:
        return "reboot"
    if re.search(r"\bpassword\b", lowered) or "owner.pass" in lowered:
        return "password"
    if re.search(r"fan\s*curve", lowered) or re.search(r"\b(set|change|raise|lower)\b.{0,24}\bfan\b", lowered):
        return "fan"
    if "power limit" in lowered or "power-limit" in lowered or re.search(r"nvidia-smi\s+-pl\b", lowered):
        return "power"
    return None


def gpu_lost(ps_text: str = "", log_text: str = "") -> bool:
    """True when Ollama is on CPU or a container log says NVML failed to init."""
    blob = f"{ps_text or ''}\n{log_text or ''}"
    if NVML_LOST in blob:
        return True
    return CPU_ONLY in blob


def service_gpu_lost(service: str, *, ps_text: str = "", log_text: str = "") -> bool:
    if service not in GPU_SERVICES:
        return False
    if service == "ollama":
        return gpu_lost(ps_text, log_text)
    return gpu_lost("", log_text)


def parse_gpu_csv(text: str) -> dict[str, Optional[int]]:
    """nvidia-smi csv: memory.used, memory.total, temperature.gpu. Read-only."""
    empty: dict[str, Optional[int]] = {
        "memory_used_mib": None,
        "memory_total_mib": None,
        "temperature_c": None,
    }
    line = ""
    for raw in (text or "").splitlines():
        if raw.strip() and "memory" not in raw.lower():
            line = raw.strip()
            break
    if not line:
        return empty
    parts = [part.strip() for part in line.split(",")]
    if len(parts) < 3:
        return empty

    def num(value: str) -> Optional[int]:
        try:
            return int(float(value))
        except ValueError:
            return None

    return {
        "memory_used_mib": num(parts[0]),
        "memory_total_mib": num(parts[1]),
        "temperature_c": num(parts[2]),
    }


def gpu_query_argv() -> list[str]:
    """Read memory and temperature. No fan or power-limit flags."""
    return [
        "nvidia-smi",
        "--query-gpu=memory.used,memory.total,temperature.gpu",
        "--format=csv,noheader,nounits",
    ]


def compose_restart_argv(service: str, directory: str) -> list[str]:
    if service not in GPU_SERVICES:
        raise ValueError("refused")
    folder = (directory or "").strip()
    if not folder or any(host in folder for host in FORBIDDEN_HOSTS):
        raise ValueError("refused")
    return [
        "docker",
        "compose",
        "--project-directory",
        folder,
        "-f",
        f"{folder}/docker-compose.yml",
        "restart",
        service,
    ]


def generation_verified(ps_after: str, logs_after: str, sample: str) -> bool:
    if gpu_lost(ps_after, logs_after):
        return False
    return bool((sample or "").strip())


def timeout_report(errors: list[str], *, lost: bool, reachable: bool) -> dict[str, Any]:
    hits = [scrub(item) for item in errors if TIMEOUT_MARK in (item or "")]
    if not hits and not lost:
        return {"timed_out": False, "cause": "", "samples": []}
    if lost:
        cause = (
            "Ollama is on CPU because the GPU was lost "
            f"({CPU_ONLY} or {NVML_LOST}). "
            f"Chat turns fail with {TIMEOUT_MARK} until the ollama container is restarted."
        )
    elif not reachable:
        cause = f"Ollama did not answer. {TIMEOUT_MARK} because the local model service is down."
    else:
        cause = (
            f"A chat turn failed with {TIMEOUT_MARK}. "
            "The GPU still looks attached, so this is a model or timeout error, not a lost GPU."
        )
    return {"timed_out": True, "cause": cause, "samples": hits[:3]}


def health_view(
    *,
    observer: Optional[dict] = None,
    presence: Optional[dict] = None,
    gpu_csv: str = "",
) -> dict[str, Any]:
    """Read-only snapshot. Fan curves and power limits are never included as writes."""
    obs = observer or {}
    audio = obs.get("audio") if isinstance(obs.get("audio"), dict) else {}
    pres = presence or {}
    cameras = pres.get("cameras") if isinstance(pres.get("cameras"), list) else []
    return {
        "read_only": True,
        "fans": "unchanged",
        "power_limits": "unchanged",
        "observer": {
            "source": obs.get("source") or "",
            "signal": obs.get("signal") or "",
            "fps": obs.get("fps") or 0,
        },
        "audio": {
            "system": (audio.get("system") or {}).get("status") if isinstance(audio.get("system"), dict) else "",
            "mic": (audio.get("mic") or {}).get("status") if isinstance(audio.get("mic"), dict) else "",
        },
        "presence": {
            "cameras": [str(cam) for cam in cameras[:8]],
            "fps": pres.get("fps") or 0,
        },
        "gpu": parse_gpu_csv(gpu_csv),
    }


def _wants(text: str, *needles: str) -> bool:
    lowered = text.lower()
    return any(needle in lowered for needle in needles)


def plan_actions(text: str) -> list[tuple[str, bool]]:
    """Map plain language onto checks. The bool is True when the user named that restart."""
    lowered = (text or "").lower()
    actions: list[tuple[str, bool]] = []

    def add(action: str, explicit: bool = False) -> None:
        for index, (name, was_explicit) in enumerate(actions):
            if name == action:
                if explicit and not was_explicit:
                    actions[index] = (action, True)
                return
        actions.append((action, explicit))

    if _wants(lowered, "not answering", "isn't answering", "isnt answering", "not responding", "timed out", "timeout", "local twin"):
        add("report_timeout")
        add("restart_ollama")
        add("restart_chatterbox")
        add("restart_api")
    if _wants(lowered, "tray is red", "tray's red", "tray red", "red tray", "lamp is red", "tray icon"):
        add("show_health")
    if _wants(lowered, "health", "temperature", "gpu memory", "camera", "how is the box", "status"):
        add("show_health")
    if _wants(lowered, "repush", "re-push", "push settings", "push companion", "wake phrase", "always listening"):
        add("repush_companion_settings")
    if "companion" in lowered and _wants(lowered, "restart", "relaunch", "start again"):
        add("restart_companion", True)
    if "ollama" in lowered and "restart" in lowered:
        add("restart_ollama", True)
    if "chatterbox" in lowered and "restart" in lowered:
        add("restart_chatterbox", True)
    if ("whisper" in lowered or "the api" in lowered) and "restart" in lowered:
        add("restart_api", True)
    return actions


@dataclass
class CaretakerState:
    pending: dict[str, dict[str, str]] = field(default_factory=dict)
    log: list[dict[str, str]] = field(default_factory=list)

    def record(self, action: str, status: str, detail: str) -> None:
        self.log.append({
            "ts": _now(),
            "action": action,
            "status": status,
            "detail": scrub(detail)[:500],
        })
        if len(self.log) > 200:
            del self.log[:-200]


class CaretakerOps:
    """Host hooks. Tests substitute this. The default methods shell out."""

    def ollama_ps(self) -> str:
        return ""

    def service_logs(self, service: str) -> str:
        return ""

    def restart(self, service: str) -> str:
        return ""

    def short_generation(self) -> str:
        return ""

    def gpu_csv(self) -> str:
        return ""

    def observer(self) -> dict:
        return {}

    def presence(self) -> dict:
        return {}

    def ollama_reachable(self) -> bool:
        return True

    def recent_errors(self) -> list[str]:
        return []

    def queue_repush(self) -> None:
        return None

    def queue_restart_companion(self) -> None:
        return None


def _service_lost(ops: CaretakerOps, service: str) -> bool:
    ps = ops.ollama_ps() if service == "ollama" else ""
    return service_gpu_lost(service, ps_text=ps, log_text=ops.service_logs(service))


def authorize(action: str, *, lost: bool, confirmed: bool, text: str = "") -> str:
    """run, confirm, or refuse."""
    if hard_refusal(text) or hard_refusal(action):
        return "refuse"
    if action not in SAFE_ACTIONS:
        return "refuse" if confirmed else "confirm"
    service = RESTART_ACTIONS.get(action)
    if service is not None and not lost and not confirmed:
        return "confirm"
    return "run"


def _run_action(action: str, ops: CaretakerOps, *, lost: bool) -> tuple[str, str]:
    if action == "show_health":
        view = health_view(observer=ops.observer(), presence=ops.presence(), gpu_csv=ops.gpu_csv())
        return "done", json.dumps(view, sort_keys=True)
    if action == "report_timeout":
        report = timeout_report(ops.recent_errors(), lost=lost, reachable=ops.ollama_reachable())
        return "done", report["cause"] or "No timed-out twin turns in the recent log."
    if action in RESTART_ACTIONS:
        service = RESTART_ACTIONS[action]
        if not lost:
            return "skipped", f"{service} still has the GPU. Nothing was restarted."
        ops.restart(service)
        if service == "ollama":
            sample = ops.short_generation()
            ok = generation_verified(ops.ollama_ps(), ops.service_logs("ollama"), sample)
            if ok:
                return "done", "Restarted ollama and a short generation came back on the GPU."
            return "done", "Restarted ollama. The short generation did not confirm the GPU yet."
        label = "whisper (api)" if service == "api" else service
        return "done", f"Restarted {label} after it lost the GPU."
    if action == "repush_companion_settings":
        ops.queue_repush()
        return "done", "Asked BIGDEAL to re-push mic, system audio, always-listening, and the wake phrase."
    if action == "restart_companion":
        ops.queue_restart_companion()
        return "done", "Asked BIGDEAL to restart the Companion process."
    return "skipped", "That action is not on the list. Nothing ran."


def handle_chat(text: str, ops: CaretakerOps, state: CaretakerState) -> dict[str, Any]:
    shown = scrub(text)
    refusal = hard_refusal(text)
    if refusal:
        reply = REFUSAL_COPY[refusal]
        state.record("refused", "refused", reply)
        return {
            "ok": False,
            "refused": True,
            "reply": reply,
            "actions": [],
            "pending_id": "",
            "health": None,
            "log": state.log[-12:],
        }

    planned = plan_actions(text)
    if not planned:
        reply = (
            "I can check a lost GPU, a red tray, chat timeouts, companion settings, "
            "and a Companion restart. I will not reboot BIGDEAL, wipe a drive, "
            "change fans, or touch your password."
        )
        state.record("chat", "noted", reply)
        return {
            "ok": True,
            "refused": False,
            "reply": reply,
            "actions": [],
            "pending_id": "",
            "health": None,
            "log": state.log[-12:],
        }

    rows: list[dict[str, str]] = []
    pending_id = ""
    health = None
    bits: list[str] = []
    for action, explicit in planned:
        service = RESTART_ACTIONS.get(action)
        lost = _service_lost(ops, service) if service else _service_lost(ops, "ollama")
        decision = authorize(action, lost=lost, confirmed=False, text=text)
        if decision == "confirm" and not explicit:
            label = {"restart_ollama": "Ollama", "restart_chatterbox": "Chatterbox", "restart_api": "Whisper"}.get(action, action)
            detail = f"{label} still has the GPU. Nothing was restarted."
            rows.append({"id": action, "status": "skipped", "detail": detail})
            state.record(action, "skipped", detail)
            bits.append(detail)
            continue
        if decision == "refuse":
            reply = REFUSAL_COPY.get(hard_refusal(action) or "", "Refused.")
            rows.append({"id": action, "status": "refused", "detail": reply})
            state.record(action, "refused", reply)
            bits.append(reply)
            continue
        if decision == "confirm":
            token = "cfm_" + uuid.uuid4().hex[:12]
            state.pending[token] = {"action": action, "detail": shown[:240]}
            pending_id = pending_id or token
            detail = f"{action} is outside the automatic list. Confirm to run it."
            rows.append({"id": action, "status": "confirm", "detail": detail, "pending_id": token})
            state.record(action, "confirm", detail)
            bits.append(detail)
            continue
        status, detail = _run_action(action, ops, lost=lost)
        rows.append({"id": action, "status": status, "detail": detail})
        state.record(action, status, detail)
        bits.append(detail)
        if action == "show_health":
            health = health_view(observer=ops.observer(), presence=ops.presence(), gpu_csv=ops.gpu_csv())

    names = {name for name, _explicit in planned}
    if health is None and "show_health" not in names and any(item["id"].startswith("restart_") for item in rows):
        health = health_view(observer=ops.observer(), presence=ops.presence(), gpu_csv=ops.gpu_csv())

    return {
        "ok": True,
        "refused": False,
        "reply": " ".join(bit for bit in bits if bit),
        "actions": rows,
        "pending_id": pending_id,
        "health": health,
        "log": state.log[-12:],
    }


def confirm_pending(pending_id: str, ops: CaretakerOps, state: CaretakerState) -> dict[str, Any]:
    item = state.pending.pop((pending_id or "").strip(), None)
    if not item:
        return {"ok": False, "reply": "Nothing is waiting for confirm.", "actions": [], "log": state.log[-12:]}
    action = item.get("action") or ""
    detail = item.get("detail") or ""
    if hard_refusal(action) or hard_refusal(detail):
        code = hard_refusal(action) or hard_refusal(detail) or "format"
        reply = REFUSAL_COPY[code]
        state.record(action or "refused", "refused", reply)
        return {"ok": False, "refused": True, "reply": reply, "actions": [], "log": state.log[-12:]}
    if action not in SAFE_ACTIONS:
        reply = "That action is not on the list. Nothing ran."
        state.record(action or "custom", "skipped", reply)
        return {"ok": False, "reply": reply, "actions": [], "log": state.log[-12:]}
    service = RESTART_ACTIONS.get(action)
    lost = True if service else False
    status, message = _run_action(action, ops, lost=lost)
    if service and status == "skipped":
        ops.restart(service)
        label = "whisper (api)" if service == "api" else service
        if service == "ollama":
            sample = ops.short_generation()
            ok = generation_verified(ops.ollama_ps(), ops.service_logs("ollama"), sample)
            message = (
                "Restarted ollama after confirm. A short generation came back."
                if ok
                else "Restarted ollama after confirm. The short generation did not confirm yet."
            )
        else:
            message = f"Restarted {label} after confirm."
        status = "done"
    state.record(action, status, message)
    return {
        "ok": status == "done",
        "reply": message,
        "actions": [{"id": action, "status": status, "detail": message}],
        "log": state.log[-12:],
    }


def watchdog_decision(ps_text: str, log_text: str) -> str:
    """Host timer. Restart ollama only when the GPU is gone. Never reboot."""
    if gpu_lost(ps_text, log_text):
        return "restart_ollama"
    return "ok"


def append_log_line(path: str, row: dict[str, str]) -> None:
    from pathlib import Path

    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    safe = {key: scrub(str(value))[:500] for key, value in row.items()}
    with dest.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(safe, ensure_ascii=True, sort_keys=True) + "\n")


def read_log_lines(path: str, limit: int = 40) -> list[dict]:
    from pathlib import Path

    dest = Path(path)
    if not dest.is_file():
        return []
    rows: list[dict] = []
    for line in dest.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            rows.append(loaded)
    return rows[-limit:]


def queue_companion(path: str, *, restart: bool = False, repush: bool = False) -> None:
    from pathlib import Path

    dest = Path(path)
    current = read_companion(path)
    current["restart"] = bool(current.get("restart")) or restart
    current["repush"] = bool(current.get("repush")) or repush
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, sort_keys=True), encoding="utf-8")
    tmp.replace(dest)


def read_companion(path: str) -> dict[str, bool]:
    from pathlib import Path

    dest = Path(path)
    if not dest.is_file():
        return {"restart": False, "repush": False}
    try:
        loaded = json.loads(dest.read_text(encoding="utf-8") or "{}")
    except (OSError, json.JSONDecodeError):
        return {"restart": False, "repush": False}
    if not isinstance(loaded, dict):
        return {"restart": False, "repush": False}
    return {"restart": bool(loaded.get("restart")), "repush": bool(loaded.get("repush"))}


def ack_companion(path: str) -> None:
    from pathlib import Path

    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(json.dumps({"restart": False, "repush": False}), encoding="utf-8")
    tmp.replace(dest)


def log_path() -> str:
    import os
    from pathlib import Path

    root = (os.environ.get("HEIRLOOM_DATA_ROOT") or "/var/lib/heirloom").strip() or "/var/lib/heirloom"
    return str(Path(root) / "caretaker" / "log.jsonl")


def companion_path() -> str:
    import os
    from pathlib import Path

    root = (os.environ.get("HEIRLOOM_DATA_ROOT") or "/var/lib/heirloom").strip() or "/var/lib/heirloom"
    return str(Path(root) / "caretaker" / "companion.json")


Runner = Callable[[list[str]], str]


def _run(argv: list[str], runner: Optional[Runner] = None) -> str:
    if any(host in " ".join(argv) for host in FORBIDDEN_HOSTS):
        raise RuntimeError("refused")
    if runner is not None:
        return runner(argv)
    import subprocess

    try:
        completed = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return str(exc)
    return ((completed.stdout or "") + (completed.stderr or "")).strip()


class HostOps(CaretakerOps):
    """Box host operations. Generation uses local Ollama only."""

    def __init__(self, runner: Optional[Runner] = None, compose_dir: str = ""):
        self._runner = runner
        self._compose_dir = compose_dir

    def _compose(self, *args: str) -> list[str]:
        folder = self._compose_dir
        return [
            "docker", "compose",
            "--project-directory", folder,
            "-f", f"{folder}/docker-compose.yml",
            *args,
        ]

    def ollama_ps(self) -> str:
        if self._compose_dir:
            return _run(self._compose("exec", "-T", "ollama", "ollama", "ps"), self._runner)
        return _run(["docker", "exec", "ollama", "ollama", "ps"], self._runner)

    def service_logs(self, service: str) -> str:
        if service not in GPU_SERVICES:
            return ""
        if self._compose_dir:
            return _run(self._compose("logs", "--tail", "80", service), self._runner)
        return _run(["docker", "logs", "--tail", "80", service], self._runner)

    def restart(self, service: str) -> str:
        folder = self._compose_dir
        if folder:
            return _run(compose_restart_argv(service, folder), self._runner)
        if service not in GPU_SERVICES:
            return ""
        return _run(["docker", "restart", service], self._runner)

    def short_generation(self) -> str:
        import os

        model = (os.environ.get("OLLAMA_TWIN_MODEL") or "qwen2.5:14b").strip() or "qwen2.5:14b"
        body = json.dumps({
            "model": model,
            "prompt": "Say ok.",
            "stream": False,
            "options": {"num_predict": 8},
        })
        return _run([
            "curl", "-fsS", "-m", "20",
            "http://127.0.0.1:11434/api/generate",
            "-d", body,
        ], self._runner)

    def gpu_csv(self) -> str:
        return _run(gpu_query_argv(), self._runner)

    def observer(self) -> dict:
        return {}

    def presence(self) -> dict:
        return {}

    def queue_repush(self) -> None:
        queue_companion(companion_path(), repush=True)

    def queue_restart_companion(self) -> None:
        queue_companion(companion_path(), restart=True)
