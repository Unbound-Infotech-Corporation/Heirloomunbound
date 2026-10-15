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
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from observer_audio import (  # noqa: E402
    alsa_device_string,
    audio_iteration,
    drain_chunks,
    fault_text,
    parse_arecord_listing,
    pick_mic_device,
    pick_system_device,
    spool_dir,
    sweep_stale,
    whisper_compute_type,
    whisper_device,
    whisper_model_name,
)
from observer_capture import (  # noqa: E402
    IdleClock,
    analysis_due,
    assert_ram_dir,
    ffmpeg_clip_command,
    ffmpeg_grab_command,
    ffmpeg_gray_command,
    parse_v4l2_format,
    pick_capture_device,
    ram_budget_bytes,
    ring_slot_count,
    sample_interval_s,
    scene_delta,
    signal_verdict,
    trim_ram_dir,
)
from observer_models import (  # noqa: E402
    keep_alive_payload,
    observer_pair_for_vram_mib,
    parse_vision_reply,
    residency_for,
    same_model,
)
from observer_learn import is_capture_device_label  # noqa: E402
from observer_pipeline import consider_frame  # noqa: E402
from observer_privacy import pause_decision  # noqa: E402
from box_pause import merged_state  # noqa: E402
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


def probe_geometry(device: str) -> tuple[int | None, int | None]:
    """Current negotiated size. 720x480 means the XR1 Lite has no HDMI lock."""
    if not shutil.which("v4l2-ctl"):
        return None, None
    try:
        completed = subprocess.run(
            ["v4l2-ctl", "-d", device, "--get-fmt-video"],
            check=False,
            capture_output=True,
            timeout=4,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, None
    width, height, _pixel = parse_v4l2_format(completed.stdout.decode("utf-8", errors="replace"))
    return width, height


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
    stderr = completed.stderr.decode("utf-8", errors="replace")
    if "720x480" in stderr.replace(" ", "") or "720 x 480" in stderr:
        return b"", "fallback-size"
    if completed.returncode != 0 or not completed.stdout:
        return b"", "no-signal"
    return completed.stdout, ""


def grab_jpeg(device: str, dest: Path) -> str:
    if not shutil.which("ffmpeg"):
        return "ffmpeg-missing"
    command = ffmpeg_grab_command(device, dest)
    try:
        completed = subprocess.run(command, check=False, capture_output=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return str(exc)
    if completed.returncode == 0 and dest.is_file():
        return ""
    return "grab-failed"


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
    if "OLLAMA_OBSERVER_MODEL" in os.environ:
        return (os.environ.get("OLLAMA_OBSERVER_MODEL") or "").strip()
    return observer_pair_for_vram_mib(os.environ.get("OBSERVER_VRAM_MIB", "0")).vision


def twin_model_name() -> str:
    configured = (os.environ.get("OLLAMA_TWIN_MODEL") or "").strip()
    if configured:
        return configured
    return observer_pair_for_vram_mib(os.environ.get("OBSERVER_VRAM_MIB", "0")).twin


def _ollama_json(url: str, path: str, payload: dict | None = None, timeout: float = 10) -> dict:
    import json
    import urllib.request

    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{url}{path}",
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    return body if isinstance(body, dict) else {}


def release_twin_if_exclusive(url: str, twin: str, vision: str) -> str:
    """Unload the chat model before vision when both cannot reside on the GPU.

    Returns the vision ``keep_alive`` value. A shared pair keeps the chat model
    loaded and lets the vision model expire after a short burst.
    """
    plan = residency_for(twin, vision, os.environ.get("OBSERVER_VRAM_MIB", "0"))
    override = (os.environ.get("OBSERVER_VISION_KEEP_ALIVE") or "").strip()
    if plan.fits or not twin or not vision:
        return override or plan.vision_keep_alive
    # Exclusive: do not honor a long keep-alive. The vision weights must leave
    # before the chat model is loaded again.
    try:
        loaded = _ollama_json(url, "/api/ps")
    except (OSError, ValueError):
        return "0"
    names = [str(item.get("name") or "") for item in loaded.get("models") or [] if isinstance(item, dict)]
    if any(same_model(name, twin) for name in names):
        try:
            _ollama_json(url, "/api/generate", {"model": twin, "keep_alive": 0})
        except (OSError, ValueError):
            return "0"
    return "0"


def ollama_see(image: Path, model: str) -> dict | None:
    """Local Ollama only. Returns None when the model is unset or the call fails."""
    if not model:
        return None
    import base64
    import json
    import urllib.request

    url = (os.environ.get("OBSERVER_OLLAMA_URL") or "http://127.0.0.1:11434").rstrip("/")
    keep = release_twin_if_exclusive(url, twin_model_name(), model)
    payload = {
        "model": model,
        "stream": False,
        "keep_alive": keep_alive_payload(keep),
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
    return parse_vision_reply(content)


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


_status_lock = threading.Lock()
_whisper_lock = threading.Lock()
_whisper_model = None
_whisper_failed_at = 0.0


def _write_status(store: ObserverStore, **fields: object) -> None:
    with _status_lock:
        current = store.read_status()
        current.update(fields)
        public = status_public(store)
        current["disk_bytes"] = public["disk_bytes"]
        current["notes_today"] = public["notes_today"]
        current["updated_at"] = datetime.now().astimezone().isoformat()
        store.write_status(current)


def _write_audio_status(store: ObserverStore, audio: dict) -> None:
    with _status_lock:
        current = store.read_status()
        current["audio"] = audio
        current["updated_at"] = datetime.now().astimezone().isoformat()
        store.write_status(current)


def _list_alsa() -> list[dict]:
    if not shutil.which("arecord"):
        return []
    try:
        completed = subprocess.run(["arecord", "-l"], check=False, capture_output=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return parse_arecord_listing(completed.stdout.decode("utf-8", errors="replace"))


def _capture_alsa(device: dict, seconds: float) -> bytes:
    if not shutil.which("arecord"):
        return b""
    length = max(1, int(round(seconds)))
    command = [
        "arecord",
        "-q",
        "-D",
        alsa_device_string(device),
        "-f",
        "S16_LE",
        "-r",
        "16000",
        "-c",
        "1",
        "-d",
        str(length),
        "-t",
        "raw",
    ]
    try:
        completed = subprocess.run(command, check=False, capture_output=True, timeout=length + 4)
    except (OSError, subprocess.TimeoutExpired):
        return b""
    if completed.returncode != 0:
        return b""
    return completed.stdout


def _transcribe_pcm(pcm: bytes) -> str:
    """faster-whisper on CUDA when the installer selected it. PCM is not kept."""
    global _whisper_model, _whisper_failed_at
    if not pcm:
        return ""
    now = time.monotonic()
    if _whisper_model is None and _whisper_failed_at and now - _whisper_failed_at < 60:
        raise RuntimeError("whisper-unavailable")
    with _whisper_lock:
        if _whisper_model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                _whisper_failed_at = time.monotonic()
                raise RuntimeError("whisper-missing") from exc
            cache = (os.environ.get("OBSERVER_WHISPER_CACHE") or "").strip()
            if not cache:
                cache = str(observer_dir() / "whisper")
            device = whisper_device()
            try:
                _whisper_model = WhisperModel(
                    whisper_model_name(),
                    device=device,
                    compute_type=whisper_compute_type(device),
                    download_root=cache,
                )
            except Exception:
                _whisper_failed_at = time.monotonic()
                raise
        model = _whisper_model
    import numpy as np

    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    segments, _info = model.transcribe(audio, vad_filter=True, language="en")
    return " ".join(segment.text.strip() for segment in segments if segment.text).strip()


def _audio_loop(store: ObserverStore, stop: threading.Event) -> None:
    """System audio and the microphone stay in separate windows."""
    if (os.environ.get("OBSERVER_AUDIO") or "").strip().lower() not in {"1", "true", "yes", "on"}:
        _write_audio_status(
            store,
            {
                "installed": False,
                "transcripts_only": True,
                "model": "",
                "system": {"enabled": False, "source": "off", "status": "off", "device": ""},
                "mic": {"enabled": False, "source": "off", "status": "off", "device": ""},
            },
        )
        return
    window = _env_float("OBSERVER_AUDIO_WINDOW_S", 3.0)
    spool = spool_dir()
    hotkey = os.environ.get("OBSERVER_HOTKEY_PHRASE", "HEIRLOOM PAUSE")
    quiet = os.environ.get("OBSERVER_QUIET_HOURS", "")
    faults = {"system": "", "mic": ""}
    while not stop.is_set():
        try:
            sweep_stale(spool)
            state = merged_state(store.read_state())
            paused, _reason = pause_decision(
                state,
                now=datetime.now().astimezone(),
                hotkey_phrase=hotkey,
                quiet_hours=quiet,
            )
            system_on = store.audio_toggle("audio_system")
            mic_on = store.audio_toggle("audio_mic")
            devices = _list_alsa()
            system_dev = pick_system_device(devices) if system_on and not paused else None
            mic_dev = pick_mic_device(devices) if mic_on and not paused else None
            captured: dict[str, bytes] = {"system": b"", "mic": b""}

            def _cap(name: str, device: dict) -> None:
                captured[name] = _capture_alsa(device, window)

            workers: list[threading.Thread] = []
            if system_dev is not None:
                workers.append(threading.Thread(target=_cap, args=("system", system_dev), daemon=True))
            if mic_dev is not None:
                workers.append(threading.Thread(target=_cap, args=("mic", mic_dev), daemon=True))
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=window + 5)
            if not workers:
                stop.wait(1.0)
            companion_system = b"" if paused else drain_chunks(spool, "system")
            companion_mic = b"" if paused else drain_chunks(spool, "mic")
            if paused:
                drain_chunks(spool, "system")
                drain_chunks(spool, "mic")
            local_system = captured["system"]
            local_mic = captured["mic"]
            if system_dev is not None:
                companion_system = b""
            if mic_dev is not None:
                companion_mic = b""
            result = audio_iteration(
                devices=devices,
                system_enabled=system_on,
                mic_enabled=mic_on,
                paused=paused,
                local_system=local_system,
                local_mic=local_mic,
                companion_system=companion_system,
                companion_mic=companion_mic,
                transcribe=_transcribe_pcm,
                hotkey_phrase=hotkey,
                prior_faults=faults,
            )
            reported = result.get("faults") if isinstance(result.get("faults"), dict) else {}
            for name in ("system", "mic"):
                message = str(reported.get(name) or "")
                if message and message != faults.get(name):
                    print(f"observer audio {name}: {message}", file=sys.stderr)
            faults = {"system": str(reported.get("system") or ""), "mic": str(reported.get("mic") or "")}
            for note in result["notes"]:
                if note.get("latch_pause"):
                    store.latch_hotkey()
                    continue
                store.add_transcript(
                    {
                        "channel": note.get("channel") or "",
                        "text": note.get("text") or "",
                        "activity": note.get("activity") or "",
                        "dropped": bool(note.get("dropped")),
                        "reason": note.get("reason") or "",
                        "ts": datetime.now().astimezone().isoformat(),
                    }
                )
            _write_audio_status(
                store,
                {
                    "installed": True,
                    "transcripts_only": True,
                    "model": result.get("model") or whisper_model_name(),
                    "system": result["system"],
                    "mic": result["mic"],
                },
            )
        except Exception as exc:
            message = fault_text(exc)
            faults = {"system": message, "mic": message}
            print(f"observer audio: {message}", file=sys.stderr)
            _write_audio_status(
                store,
                {
                    "installed": True,
                    "transcripts_only": True,
                    "model": whisper_model_name(),
                    "system": {"enabled": True, "source": "off", "status": "error", "device": "", "error": message},
                    "mic": {"enabled": True, "source": "off", "status": "error", "device": "", "error": message},
                },
            )
        stop.wait(0.4)


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
    last_grab: float | None = None
    base_fps = _env_float("OBSERVER_SAMPLE_FPS", 2.0)
    burst_fps = _env_float("OBSERVER_BURST_FPS", 8.0)
    hotkey = os.environ.get("OBSERVER_HOTKEY_PHRASE", "HEIRLOOM PAUSE")
    quiet = os.environ.get("OBSERVER_QUIET_HOURS", "")
    model_name = vision_model_name() or "ocr"
    ring_slots = ring_slot_count()
    ram_budget = ram_budget_bytes()
    ring_slot = 0
    plan = residency_for(
        twin_model_name(),
        "" if model_name == "ocr" else model_name,
        os.environ.get("OBSERVER_VRAM_MIB", "0"),
    )

    audio_stop = threading.Event()
    threading.Thread(target=_audio_loop, args=(store, audio_stop), name="observer-audio", daemon=True).start()

    while True:
        now_dt = datetime.now().astimezone()
        state = merged_state(store.read_state())
        paused, reason = pause_decision(state, now=now_dt, hotkey_phrase=hotkey, quiet_hours=quiet)
        if paused and reason in {"cli", "web", "hotkey", "schedule"}:
            _write_status(
                store,
                device=store.read_status().get("device") or "",
                signal="paused",
                fps=0,
                model=model_name,
                residency=plan.mode,
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
                residency=plan.mode,
                paused=False,
                pause_reason="",
            )
            time.sleep(2)
            continue

        gray, err = grab_gray(str(device["path"]))
        width, height = probe_geometry(str(device["path"]))
        now_mono_grab = time.monotonic()
        gap = None if last_grab is None else now_mono_grab - last_grab
        repeated = bool(previous) and previous == gray
        live, _signal_reason = signal_verdict(
            gray=gray,
            width=width,
            height=height,
            gap_s=gap,
            repeated=repeated,
            grab_error=err,
        )
        if gray and not err:
            last_grab = now_mono_grab
        delta = scene_delta(previous, gray) if gray else 1.0
        interval = sample_interval_s(delta, base_fps=base_fps, burst_fps=burst_fps)
        if not live:
            idle.update(True, time.monotonic())
            _write_status(
                store,
                device=device["path"],
                device_name=device.get("name") or "",
                signal="no-signal",
                fps=base_fps,
                model=model_name,
                residency=plan.mode,
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
        ring = ram / f"ring-{ring_slot % ring_slots}.gray"
        ring.write_bytes(gray)
        ring_slot += 1
        trim_ram_dir(ram, ram_budget)

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
            device_name = str(device.get("name") or "")
            seen_app = "" if is_capture_device_label(device_name) else device_name
            result = consider_frame(ocr=ocr, app=seen_app, model=use_model, hotkey_phrase=hotkey)
            jpeg.unlink(missing_ok=True)
            if result["latch_pause"]:
                store.latch_hotkey()
            elif result["dropped"]:
                store.add_observations(
                    [{"ts": now_dt.isoformat(), "dropped": True, "reason": result["reason"]}]
                )
            else:
                from presence_cues import attach_presence_fields

                title = result["text"][:120]
                if is_capture_device_label(title):
                    title = ""
                row = {
                    "ts": now_dt.isoformat(),
                    "activity": result["activity"],
                    "app": seen_app,
                    "title": title,
                    "game": result["game"],
                    "text": result["text"],
                    "scene_delta": round(delta, 3),
                }
                store.add_observations([attach_presence_fields(row)])
                if clips_enabled() and delta >= 0.35:
                    keep_highlight(store, str(device["path"]), ram, _env_float("OBSERVER_CLIP_SECONDS", 8))
            if clips_enabled():
                store.prune(cap_bytes=disk_cap_bytes())
            trim_ram_dir(ram, ram_budget)
            last_analysis = now_mono

        _write_status(
            store,
            device=device["path"],
            device_name=device.get("name") or "",
            signal="signal",
            fps=round(1.0 / interval, 2),
            model=model_name,
            residency=plan.mode,
            paused=False,
            pause_reason="",
            idle_seconds=0,
        )
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
