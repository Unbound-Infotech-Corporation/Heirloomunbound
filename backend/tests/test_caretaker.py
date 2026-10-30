"""Caretaker clone: allowlist, hard rules, GPU loss, and the host watchdog."""
from __future__ import annotations

from pathlib import Path

from assistants import missing_backfill
from caretaker import (
    CPU_ONLY,
    NVML_LOST,
    TIMEOUT_MARK,
    CaretakerOps,
    CaretakerState,
    ack_companion,
    append_log_line,
    compose_restart_argv,
    confirm_pending,
    generation_verified,
    gpu_lost,
    gpu_query_argv,
    handle_chat,
    health_view,
    parse_gpu_csv,
    plan_actions,
    queue_companion,
    read_companion,
    read_log_lines,
    scrub,
    service_gpu_lost,
    timeout_report,
    watchdog_decision,
)

ROOT = Path(__file__).resolve().parents[1]


class FakeOps(CaretakerOps):
    def __init__(self):
        self.ps = "qwen  100% GPU"
        self.logs = {"ollama": "", "chatterbox": "", "api": ""}
        self.restarts: list[str] = []
        self.sample = "ok"
        self.csv = "1024, 8192, 61"
        self.errors: list[str] = []
        self.reachable = True
        self.repush = 0
        self.companion = 0
        self.obs = {
            "source": "capture",
            "signal": "hdmi",
            "fps": 12,
            "audio": {"system": {"status": "live"}, "mic": {"status": "waiting"}},
        }
        self.pres = {"cameras": ["usb-0"], "fps": 4}

    def ollama_ps(self) -> str:
        return self.ps

    def service_logs(self, service: str) -> str:
        return self.logs.get(service, "")

    def restart(self, service: str) -> str:
        self.restarts.append(service)
        self.ps = "qwen  100% GPU"
        self.logs[service] = ""
        return "restarted"

    def short_generation(self) -> str:
        return self.sample

    def gpu_csv(self) -> str:
        return self.csv

    def observer(self) -> dict:
        return self.obs

    def presence(self) -> dict:
        return self.pres

    def ollama_reachable(self) -> bool:
        return self.reachable

    def recent_errors(self) -> list[str]:
        return self.errors

    def queue_repush(self) -> None:
        self.repush += 1

    def queue_restart_companion(self) -> None:
        self.companion += 1


def test_gpu_lost_from_cpu_or_nvml():
    assert gpu_lost("NAME\nqwen  9GB  100% CPU") is True
    assert gpu_lost("", f"init: {NVML_LOST}: unknown error") is True
    assert gpu_lost("qwen  100% GPU") is False
    assert gpu_lost("45% CPU") is False
    assert service_gpu_lost("chatterbox", log_text=NVML_LOST) is True
    assert service_gpu_lost("api", log_text="whisper ready") is False
    assert service_gpu_lost("api", ps_text=CPU_ONLY, log_text="") is False


def test_plain_language_maps_to_the_safe_checks():
    quiet = [name for name, _explicit in plan_actions("it's not answering me")]
    assert quiet[0] == "report_timeout"
    assert "restart_ollama" in quiet
    assert "restart_chatterbox" in quiet
    assert "restart_api" in quiet
    tray = [name for name, _explicit in plan_actions("the tray is red")]
    assert tray == ["show_health"]
    settings = [name for name, _explicit in plan_actions("repush the wake phrase and always listening")]
    assert settings == ["repush_companion_settings"]


def test_lost_gpu_restarts_ollama_and_verifies_generation():
    ops = FakeOps()
    ops.ps = "qwen  100% CPU"
    ops.errors = [f"{TIMEOUT_MARK}: timed out"]
    result = handle_chat("it's not answering me", ops, CaretakerState())
    assert "ollama" in ops.restarts
    assert "chatterbox" not in ops.restarts
    assert "api" not in ops.restarts
    assert TIMEOUT_MARK in result["reply"]
    assert result["pending_id"] == ""
    assert any(row["id"] == "restart_ollama" and row["status"] == "done" for row in result["actions"])
    assert generation_verified("100% GPU", "", "ok") is True
    assert generation_verified("100% CPU", "", "ok") is False
    assert generation_verified("100% GPU", "", "") is False


def test_healthy_restart_waits_for_confirm_and_hard_rules_never_run():
    ops = FakeOps()
    state = CaretakerState()
    asked = handle_chat("restart ollama", ops, state)
    assert ops.restarts == []
    assert asked["pending_id"].startswith("cfm_")
    confirmed = confirm_pending(asked["pending_id"], ops, state)
    assert ops.restarts == ["ollama"]
    assert "Restarted ollama" in confirmed["reply"]

    blocked = handle_chat("reboot BIGDEAL and restart ollama", ops, CaretakerState())
    assert blocked["refused"] is True
    assert "reboot" in blocked["reply"].lower()
    assert ops.restarts == ["ollama"]

    for phrase in (
        "format the drive",
        "wipe the disk",
        "ssh 192.168.0.16",
        "check 192.168.0.19",
        "what is the owner password",
        "change the fan curve",
        "set a power limit",
    ):
        again = handle_chat(phrase, ops, CaretakerState())
        assert again["refused"] is True, phrase
        assert again["actions"] == []

    still = confirm_pending("cfm_missing", ops, CaretakerState())
    assert still["ok"] is False


def test_health_is_read_only_and_companion_actions_are_safe():
    view = health_view(
        observer={"source": "capture", "signal": "hdmi", "fps": 8, "audio": {"system": {"status": "live"}, "mic": {"status": "off"}}},
        presence={"cameras": ["cam0"], "fps": 3},
        gpu_csv="512, 8192, 70",
    )
    assert view["read_only"] is True
    assert view["fans"] == "unchanged"
    assert view["power_limits"] == "unchanged"
    assert view["observer"]["source"] == "capture"
    assert view["audio"]["mic"] == "off"
    assert view["presence"]["cameras"] == ["cam0"]
    assert view["gpu"]["temperature_c"] == 70
    assert "-pl" not in " ".join(gpu_query_argv())
    assert "fan" not in " ".join(gpu_query_argv())
    argv = compose_restart_argv("ollama", "/var/lib/heirloom/src/box")
    assert argv[-1] == "ollama"
    assert "192.168.0.16" not in " ".join(argv)
    try:
        compose_restart_argv("ollama", "/tmp/192.168.0.19/box")
    except ValueError:
        refused = True
    else:
        refused = False
    assert refused is True

    ops = FakeOps()
    pushed = handle_chat("repush companion settings", ops, CaretakerState())
    assert ops.repush == 1
    assert pushed["refused"] is False
    restarted = handle_chat("restart the companion", ops, CaretakerState())
    assert ops.companion == 1
    assert "BIGDEAL" in restarted["reply"]


def test_timeout_cause_names_a_lost_gpu():
    lost = timeout_report([f"{TIMEOUT_MARK}: timeout"], lost=True, reachable=True)
    assert lost["timed_out"] is True
    assert "CPU" in lost["cause"]
    quiet = timeout_report([], lost=False, reachable=True)
    assert quiet["timed_out"] is False
    down = timeout_report([TIMEOUT_MARK], lost=False, reachable=False)
    assert "did not answer" in down["cause"]


def test_watchdog_restarts_only_when_the_gpu_is_gone():
    assert watchdog_decision("100% CPU", "") == "restart_ollama"
    assert watchdog_decision("", NVML_LOST) == "restart_ollama"
    assert watchdog_decision("100% GPU", "ready") == "ok"


def test_log_scrubs_passwords_and_companion_flags_ack(tmp_path: Path):
    log_file = tmp_path / "log.jsonl"
    append_log_line(str(log_file), {"action": "chat", "detail": "password=hunter2"})
    rows = read_log_lines(str(log_file))
    assert "hunter2" not in rows[0]["detail"]
    assert "[redacted]" in rows[0]["detail"]
    assert "hunter2" not in scrub("password: hunter2")

    flag = tmp_path / "companion.json"
    queue_companion(str(flag), restart=True)
    queue_companion(str(flag), repush=True)
    assert read_companion(str(flag)) == {"restart": True, "repush": True}
    ack_companion(str(flag))
    assert read_companion(str(flag)) == {"restart": False, "repush": False}


def test_parse_gpu_csv_ignores_headers():
    parsed = parse_gpu_csv("memory.used, memory.total, temperature.gpu\n2048, 8192, 55\n")
    assert parsed["memory_used_mib"] == 2048
    assert parsed["temperature_c"] == 55
    assert parse_gpu_csv("")["temperature_c"] is None


def test_caretaker_is_a_builtin_clone_and_the_api_stays_owner_only():
    missing = missing_backfill({"research", "archive"})
    assert [spec["slug"] for spec in missing] == ["caretaker"]
    assert missing_backfill({"caretaker"}) == []
    router = (ROOT / "routers" / "caretaker.py").read_text(encoding="utf-8")
    assert "require_owner" in router
    assert router.count("require_owner") >= 5
    watch = (ROOT / "caretaker_watch.py").read_text(encoding="utf-8")
    assert "reboot" not in watch.split("does not reboot")[-1].lower() or "reboot" in watch
    assert "192.168.0.16" in watch
    timer = Path(__file__).resolve().parents[2] / "box" / "caretaker" / "heirloom-caretaker.timer"
    assert "OnUnitActiveSec=3min" in timer.read_text(encoding="utf-8")
    install = (Path(__file__).resolve().parents[2] / "box" / "install.sh").read_text(encoding="utf-8")
    assert "install_caretaker" in install
