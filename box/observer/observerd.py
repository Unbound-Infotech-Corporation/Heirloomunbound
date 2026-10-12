#!/usr/bin/env python3
"""Heirloom Observer capture loop.

Samples a UVC HDMI capture device, drops sensitive frames before OCR text or
a vision model is kept, and writes notes under /var/lib/heirloom/observer.
The ring buffer stays in /run. Nothing here is the raw stream on disk.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from observer_capture import (  # noqa: E402
    IdleClock,
    analysis_due,
    assert_ram_dir,
    ffmpeg_clip_command,
    ffmpeg_grab_command,
    ffmpeg_gray_command,
    is_no_signal,
    pick_capture_device,
    sample_interval_s,
    scene_delta,
)
from observer_models import vision_model_for_vram_mib  # noqa: E402
from observer_pipeline import consider_frame  # noqa: E402
from observer_privacy import pause_decision  # noqa: E402
from observer_store import (  # noqa: E402
    ObserverStore,
    clips_enabled,
    disk_cap_bytes,
    observer_dir,
    observer_enabled,
    status_public,
)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def list_video_devices(sysfs: Path | None = None) -> list[dict]:
    root = sysfs or Path("/sys/class/video4linux")
    devices: list[dict] = []
    if not root.is_dir():
        return devices
    for node in sorted(root.iterdir()):
        name_path = node / "name"
        index_path = node / "index"
        try:
            name = name_path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            name = ""
        try:
            index = int(index_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            index = 99
        devices.append({"path": f"/dev/{node.name}", "name": name, "index": index})
    return devices


def grab_gray(device: str) -> tuple[bytes, str]:
    if not shutil.which("ffmpeg"):
        return b"", "ffmpeg-missing"
    try:
        completed = subprocess.run(
            ffmpeg_gray_command(device),
            check=False,
            capture_output=True,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return b"", str(exc)
    if completed.returncode != 0 or not completed.stdout:
        return b"", "no-signal"
    return completed.stdout, ""


def grab_jpeg(device: str, dest: Path) -> str:
    if not shutil.which("ffmpeg"):
        return "ffmpeg-missing"
    attempts = (
        ffmpeg_grab_command(device, dest),
        ffmpeg_grab_command(device, dest, input_format=None, width=1280, height=720),
    )
    last = "grab-failed"
    for command in attempts:
        try:
            completed = subprocess.run(command, check=False, capture_output=True, timeout=8)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return str(exc)
        if completed.returncode == 0 and dest.is_file():
            return ""
        last = "grab-failed"
    return last


def ocr_image(path: Path) -> str:
    if not shutil.which("tesseract"):
        return ""
    try:
        completed = subprocess.run(
            ["tesseract", os.fspath(path), "stdout", "-l", "eng", "--psm", "6"],
            check=False,
            capture_output=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout.decode("utf-8", errors="replace")


def vision_model_name() -> str:
    override = (os.environ.get("OLLAMA_OBSERVER_MODEL") or "").strip()
    if override:
        return override
    return vision_model_for_vram_mib(os.environ.get("OBSERVER_VRAM_MIB", "0"))


def ollama_see(image: Path, model: str) -> dict | None:
    """Local Ollama only. Returns None when the model is unset or the call fails."""
    if not model:
        return None
    import base64
    import json
    import urllib.request

    url = (os.environ.get("OBSERVER_OLLAMA_URL") or "http://127.0.0.1:11434").rstrip("/")
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Describe this screen in one sentence. Reply with JSON keys "
                    "activity (work, play, browsing, media), app, game, summary. "
                    "Do not invent text that is not visible."
                ),
                "images": [base64.b64encode(image.read_bytes()).decode("ascii")],
            }
        ],
    }
    request = urllib.request.Request(
        f"{url}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    content = ((body.get("message") or {}).get("content") or "").strip()
    if content.startswith("{") and content.endswith("}"):
        try:
            parsed = json.loads(content)
        except ValueError:
            return {"summary": content}
        return parsed if isinstance(parsed, dict) else {"summary": content}
    return {"summary": content} if content else None


def keep_highlight(store: ObserverStore, device: str, ram: Path, seconds: float) -> None:
    """Record a short clip only after a frame was allowed, and only while the day budget remains.

    The file is encoded in RAM with no audio. It moves under the observer clip
    directory after ``admit_clip`` says yes. A failed grab leaves no file.
    """
    if seconds <= 0 or not shutil.which("ffmpeg"):
        return
    if not store.admit_clip(privacy_dropped=False, duration_s=seconds):
        return
    dest = ram / "highlight.mkv"
    try:
        completed = subprocess.run(
            ffmpeg_clip_command(device, dest, seconds=seconds),
            check=False,
            capture_output=True,
            timeout=max(20, int(seconds) + 15),
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        dest.unlink(missing_ok=True)
        return
    if completed.returncode != 0 or not dest.is_file() or dest.stat().st_size <= 0:
        dest.unlink(missing_ok=True)
        return
    if not store.admit_clip(privacy_dropped=False, duration_s=seconds):
        dest.unlink(missing_ok=True)
        return
    store.clips_dir.mkdir(parents=True, exist_ok=True)
    name = f"highlight-{int(time.time())}.mkv"
    shutil.move(os.fspath(dest), os.fspath(store.clips_dir / name))
    store.record_clip(name=name, seconds=seconds)


def _write_status(store: ObserverStore, **fields: object) -> None:
    current = store.read_status()
    current.update(fields)
    current["disk_bytes"] = status_public(store)["disk_bytes"]
    current["notes_today"] = status_public(store)["notes_today"]
    current["updated_at"] = datetime.now().astimezone().isoformat()
    store.write_status(current)


def main() -> int:
    if not observer_enabled():
        print("HEIRLOOM_OBSERVER is off", file=sys.stderr)
        return 0
    ram = assert_ram_dir(os.environ.get("OBSERVER_RAM_DIR", "/run/heirloom-observer"))
    ram.mkdir(parents=True, exist_ok=True)
    store = ObserverStore(observer_dir())
    store.root.mkdir(parents=True, exist_ok=True)
    idle = IdleClock()
    previous = b""
    last_analysis = 0.0
    base_fps = _env_float("OBSERVER_SAMPLE_FPS", 2.0)
    burst_fps = _env_float("OBSERVER_BURST_FPS", 8.0)
    hotkey = os.environ.get("OBSERVER_HOTKEY_PHRASE", "HEIRLOOM PAUSE")
    quiet = os.environ.get("OBSERVER_QUIET_HOURS", "")
    model_name = vision_model_name() or "ocr"
    ring_slot = 0

    while True:
        now_dt = datetime.now().astimezone()
        state = store.read_state()
        paused, reason = pause_decision(state, now=now_dt, hotkey_phrase=hotkey, quiet_hours=quiet)
        if paused and reason in {"cli", "web", "hotkey", "schedule"}:
            _write_status(
                store,
                device=store.read_status().get("device") or "",
                signal="paused",
                fps=0,
                model=model_name,
                paused=True,
                pause_reason=reason,
                idle_seconds=0,
            )
            time.sleep(2)
            continue

        device = pick_capture_device(list_video_devices())
        if device is None or not Path(str(device["path"])).exists():
            _write_status(
                store,
                device="",
                signal="no-device",
                fps=0,
                model=model_name,
                paused=False,
                pause_reason="",
            )
            time.sleep(2)
            continue

        gray, err = grab_gray(str(device["path"]))
        delta = scene_delta(previous, gray) if gray else 1.0
        interval = sample_interval_s(delta, base_fps=base_fps, burst_fps=burst_fps)
        if err or is_no_signal(gray):
            idle.update(True, time.monotonic())
            _write_status(
                store,
                device=device["path"],
                device_name=device.get("name") or "",
                signal="no-signal",
                fps=base_fps,
                model=model_name,
                paused=False,
                pause_reason="",
                idle_seconds=int(idle.current(time.monotonic())),
                last_error=err,
            )
            previous = b""
            time.sleep(interval)
            continue

        ended = idle.update(False, time.monotonic())
        if ended and ended >= 1:
            store.add_observations(
                [
                    {
                        "ts": now_dt.isoformat(),
                        "activity": "idle",
                        "text": f"No signal for {int(ended)} seconds.",
                    }
                ]
            )
        previous = gray
        ring = ram / f"ring-{ring_slot % 8}.gray"
        ring.write_bytes(gray)
        ring_slot += 1

        now_mono = time.monotonic()
        if analysis_due(scene_delta=delta, since_last_s=now_mono - last_analysis):
            jpeg = ram / "frame.jpg"
            grab_error = grab_jpeg(str(device["path"]), jpeg)
            ocr = "" if grab_error else ocr_image(jpeg)
            looked, look_reason = pause_decision(
                state, now=now_dt, screen_text=ocr, hotkey_phrase=hotkey, quiet_hours=quiet
            )
            if looked and look_reason == "hotkey":
                store.latch_hotkey()
                jpeg.unlink(missing_ok=True)
                last_analysis = now_mono
                continue

            def _model(_payload: dict, _path: Path = jpeg) -> dict | None:
                if not jpeg.is_file() or model_name == "ocr":
                    return None
                return ollama_see(_path, model_name if model_name != "ocr" else "")

            use_model = None if model_name == "ocr" else _model
            result = consider_frame(ocr=ocr, app=str(device.get("name") or ""), model=use_model, hotkey_phrase=hotkey)
            jpeg.unlink(missing_ok=True)
            if result["latch_pause"]:
                store.latch_hotkey()
            elif result["dropped"]:
                store.add_observations(
                    [{"ts": now_dt.isoformat(), "dropped": True, "reason": result["reason"]}]
                )
            else:
                store.add_observations(
                    [
                        {
                            "ts": now_dt.isoformat(),
                            "activity": result["activity"],
                            "app": str(device.get("name") or ""),
                            "title": result["text"][:120],
                            "game": result["game"],
                            "text": result["text"],
                            "scene_delta": round(delta, 3),
                        }
                    ]
                )
                if clips_enabled() and delta >= 0.35:
                    keep_highlight(store, str(device["path"]), ram, _env_float("OBSERVER_CLIP_SECONDS", 8))
            if clips_enabled():
                store.prune(cap_bytes=disk_cap_bytes())
            last_analysis = now_mono

        _write_status(
            store,
            device=device["path"],
            device_name=device.get("name") or "",
            signal="signal",
            fps=round(1.0 / interval, 2),
            model=model_name,
            paused=False,
            pause_reason="",
            idle_seconds=0,
        )
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
