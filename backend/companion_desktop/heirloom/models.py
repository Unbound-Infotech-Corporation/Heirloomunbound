"""Local model provisioner for the dedicated PC.

One-click from the studio Models window. Detects GPU + Ollama, installs
faster-whisper if missing, and writes a runtime probe the backend stores
on the companion device so the web UI can stop asking for pasted keys.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from . import config

ProgressFn = Callable[[str], None]


def _run(cmd: list[str], timeout: int = 20) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        return r.returncode, out
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)


def probe_gpu() -> dict[str, Any]:
    code, out = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"])
    if code != 0 or not out:
        return {"ready": False, "detail": "No NVIDIA GPU detected (nvidia-smi missing)."}
    line = out.splitlines()[0].strip()
    return {"ready": True, "detail": line, "name": line}


def probe_ollama() -> dict[str, Any]:
    if not shutil.which("ollama"):
        # Still might be a running daemon without CLI on PATH
        pass
    try:
        import urllib.request

        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
        models = [m.get("name") for m in (data.get("models") or []) if m.get("name")]
        return {
            "ready": True,
            "detail": f"{len(models)} model(s)" if models else "Ollama running, no models pulled yet",
            "models": models,
        }
    except Exception:
        return {"ready": False, "detail": "Ollama is not running on :11434"}


def probe_whisper() -> dict[str, Any]:
    try:
        import faster_whisper  # noqa: F401

        cache = Path.home() / ".cache" / "huggingface" / "hub"
        has = any(cache.glob("models--Systran--faster-whisper-*")) if cache.exists() else False
        return {
            "ready": True,
            "imported": True,
            "cached": has,
            "detail": "faster-whisper installed" + (" · model cached" if has else " · will download on first use"),
        }
    except Exception:
        return {"ready": False, "imported": False, "cached": False, "detail": "faster-whisper not installed"}


def probe_piper() -> dict[str, Any]:
    exe = shutil.which("piper")
    if exe:
        return {"ready": True, "detail": f"piper at {exe}"}
    return {"ready": False, "detail": "piper not on PATH"}


def full_probe() -> dict[str, Any]:
    gpu = probe_gpu()
    ollama = probe_ollama()
    whisper = probe_whisper()
    piper = probe_piper()
    bits = []
    if gpu.get("ready"):
        bits.append(gpu["detail"])
    if ollama.get("ready"):
        bits.append("Ollama up")
    if whisper.get("ready"):
        bits.append("Whisper ready")
    detail = " · ".join(bits) if bits else "Nothing local yet — run Provision."
    return {
        "gpu": gpu,
        "ollama": ollama,
        "whisper": whisper,
        "piper": piper,
        "detail": detail,
    }


def _pip_install(pkg: str, progress: Optional[ProgressFn] = None) -> str:
    if progress:
        progress(f"pip install {pkg}")
    code, out = _run([sys.executable, "-m", "pip", "install", "--upgrade", pkg], timeout=600)
    if code != 0:
        raise RuntimeError(f"pip install {pkg} failed: {out[-400:]}")
    return out[-200:]


def provision(features: list[str] | None = None, progress: Optional[ProgressFn] = None) -> dict[str, Any]:
    """Idempotent. Safe to run on every boot; only downloads what's missing."""
    wanted = set(features or ["stt", "tts", "twin", "vision"])
    log: list[str] = []

    def note(msg: str) -> None:
        log.append(msg)
        if progress:
            progress(msg)

    if "stt" in wanted:
        w = probe_whisper()
        if not w.get("imported"):
            note("Installing faster-whisper for local speech-to-text…")
            _pip_install("faster-whisper", progress)
        else:
            note("faster-whisper already installed.")
        # Touch the model so the first utterance isn't a 400MB stall.
        try:
            from faster_whisper import WhisperModel

            note("Warming Whisper base (downloads once, then cached)…")
            device = "cuda" if probe_gpu().get("ready") else "cpu"
            compute = "float16" if device == "cuda" else "int8"
            WhisperModel("base", device=device, compute_type=compute)
            note(f"Whisper base ready on {device}.")
        except Exception as exc:  # noqa: BLE001
            note(f"Whisper warmup skipped: {exc}")

    if "twin" in wanted or "vision" in wanted:
        ol = probe_ollama()
        if ol.get("ready"):
            models = ol.get("models") or []
            if "twin" in wanted and not any(str(m).startswith("llama3") for m in models):
                note("Pulling llama3.1 via Ollama (this is the local twin)…")
                _run(["ollama", "pull", "llama3.1"], timeout=3600)
            if "vision" in wanted and not any("llava" in str(m) for m in models):
                note("Pulling llava via Ollama for screen vision…")
                _run(["ollama", "pull", "llava"], timeout=3600)
            note("Ollama models checked.")
        else:
            note("Ollama not running — cloud Claude stays in charge until you start it.")

    if "tts" in wanted:
        p = probe_piper()
        if p.get("ready"):
            note("Piper already on PATH.")
        else:
            note("Piper not installed; ElevenLabs/OpenAI TTS remain the voice path.")

    probe = full_probe()
    settings = config.load_settings()
    settings["runtime_probe"] = probe
    settings["last_provision_log"] = log
    config.save_settings(settings)
    probe["log"] = log
    return probe
