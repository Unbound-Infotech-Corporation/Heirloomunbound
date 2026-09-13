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
from .engine_probes import (
    LATENTSYNC_DEFAULT,
    MUSETALK_DEFAULT,
    QWEN3_TTS_DEFAULT,
    VOICEBOX_DEFAULT,
    probe_latentsync,
    probe_musetalk,
    probe_qwen3_tts,
    probe_voicebox,
)
from .studio_log import info as log_info
from .studio_log import warn as log_warn

ProgressFn = Callable[[str], None]

_ENGINE_URL_KEYS = {
    "voicebox_url": VOICEBOX_DEFAULT,
    "qwen3_tts_url": QWEN3_TTS_DEFAULT,
    "latentsync_url": LATENTSYNC_DEFAULT,
    "musetalk_url": MUSETALK_DEFAULT,
}


def engine_urls() -> dict[str, str]:
    """Voicebox / Qwen3-TTS / LatentSync URLs from last poll or defaults."""
    settings = config.load_settings()
    remote = {}
    compute = settings.get("studio_compute")
    if isinstance(compute, dict) and isinstance(compute.get("remote"), dict):
        remote = compute["remote"]
    out = {}
    for key, default in _ENGINE_URL_KEYS.items():
        url = str(remote.get(key) or default).strip().rstrip("/")
        if not url.startswith(("http://", "https://")):
            url = default
        out[key] = url
    return out


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
    urls = engine_urls()
    gpu = probe_gpu()
    ollama = probe_ollama()
    whisper = probe_whisper()
    piper = probe_piper()
    voicebox = probe_voicebox(urls["voicebox_url"])
    qwen3 = probe_qwen3_tts(urls["qwen3_tts_url"])
    latentsync = probe_latentsync(urls["latentsync_url"])
    musetalk = probe_musetalk(urls["musetalk_url"])
    bits = []
    if gpu.get("ready"):
        bits.append(gpu["detail"])
    if ollama.get("ready"):
        bits.append("Ollama up")
    if whisper.get("ready"):
        bits.append("Whisper ready")
    if voicebox.get("ready"):
        bits.append("Voicebox up")
    if qwen3.get("ready"):
        bits.append("Qwen3-TTS up")
    if latentsync.get("ready"):
        bits.append("LatentSync up")
    detail = " · ".join(bits) if bits else "Nothing local yet — install engines, then Probe."
    probe = {
        "gpu": gpu,
        "ollama": ollama,
        "whisper": whisper,
        "piper": piper,
        "voicebox": voicebox,
        "qwen3_tts": qwen3,
        "latentsync": latentsync,
        "musetalk": musetalk,
        "detail": detail,
    }
    try:
        log_info(
            "probe",
            f"probe refresh · {detail}",
            voicebox=bool(voicebox.get("ready")),
            qwen3_tts=bool(qwen3.get("ready")),
            latentsync=bool(latentsync.get("ready")),
        )
    except Exception:
        pass
    return probe


def resolve_tts_backend_local(
    model_map: dict | None,
    probe: dict | None,
    *,
    has_voice_clone: bool = False,
) -> str:
    """Mirror of server resolve_tts_backend — used when the studio API is offline."""
    pick = str((model_map or {}).get("tts") or "auto")
    voicebox = bool((probe or {}).get("voicebox", {}).get("ready"))
    qwen = bool((probe or {}).get("qwen3_tts", {}).get("ready"))
    piper = bool((probe or {}).get("piper", {}).get("ready"))

    def fallback(skip: str = "") -> str:
        if skip != "voicebox" and voicebox:
            return "voicebox"
        if skip != "qwen3_tts" and qwen:
            return "qwen3_tts"
        if skip != "elevenlabs" and has_voice_clone:
            return "elevenlabs"
        if skip != "local_piper" and piper:
            return "local_piper"
        return "openai_tts"

    if pick == "voicebox":
        return "voicebox" if voicebox else fallback("voicebox")
    if pick == "qwen3_tts":
        return "qwen3_tts" if qwen else fallback("qwen3_tts")
    if pick == "elevenlabs":
        return "elevenlabs" if has_voice_clone else fallback("elevenlabs")
    if pick == "openai_tts":
        return "openai_tts"
    if pick == "local_piper":
        return "local_piper" if piper else fallback("local_piper")
    return fallback()


def coach_install_lines() -> list[str]:
    """Vendor-coach style copy. Never downloads an installer."""
    urls = engine_urls()
    return [
        "Heirloom Unbound does not install Voicebox, Qwen3-TTS, or LatentSync for you (no Pinokio).",
        f"Voicebox: install the official MSI or Docker image, start it, then Probe. Default {urls['voicebox_url']}.",
        f"Qwen3-TTS: pip or Docker, OpenAI-compatible GET /v1/models. Default {urls['qwen3_tts_url']}.",
        f"LatentSync (talking likeness): start the local HTTP engine, then Probe. Default {urls['latentsync_url']}.",
        "When an engine is listening, Auto TTS prefers Voicebox, then Qwen3-TTS, then cloned ElevenLabs, then Piper.",
    ]


def _pip_install(pkg: str, progress: Optional[ProgressFn] = None) -> str:
    if progress:
        progress(f"pip install {pkg}")
    code, out = _run([sys.executable, "-m", "pip", "install", "--upgrade", pkg], timeout=600)
    if code != 0:
        raise RuntimeError(f"pip install {pkg} failed: {out[-400:]}")
    return out[-200:]


def provision(
    features: list[str] | None = None,
    progress: Optional[ProgressFn] = None,
    profile_id: str | None = None,
) -> dict[str, Any]:
    """Idempotent. Safe to run on every boot; only downloads what's missing.

    Engine listeners (Voicebox / Qwen3-TTS / LatentSync) coach on failure and
    never abort the whole install. Small completes on CPU without Ollama.
    """
    from .space_profiles import normalize_profile_id, provision_features, provision_manifest, space_profile

    profile_id = normalize_profile_id(profile_id) if profile_id else None
    if profile_id:
        wanted = set(features or provision_features(profile_id))
        whisper_name = space_profile(profile_id).get("whisper") or "base"
        manifest = provision_manifest(profile_id)
    else:
        wanted = set(features or ["stt", "tts", "twin", "vision"])
        whisper_name = "base"
        manifest = {"id": None, "gpu_required": False, "abort_on_engine_failure": False}

    log: list[str] = []
    fatal: Optional[str] = None

    def note(msg: str) -> None:
        log.append(msg)
        if progress:
            progress(msg)

    if profile_id:
        note(f"Heirloom Unbound · {space_profile(profile_id)['label']} · resume-safe downloads")
        note("No Pinokio. Official Hugging Face / Ollama / MSI / Docker / pip only.")

    if "stt" in wanted:
        w = probe_whisper()
        if not w.get("imported"):
            note("Installing faster-whisper for local speech-to-text…")
            try:
                _pip_install("faster-whisper", progress)
            except Exception as exc:  # noqa: BLE001
                note(f"faster-whisper install failed (not fatal): {exc}")
        else:
            note("faster-whisper already installed.")
        try:
            from faster_whisper import WhisperModel

            note(f"Warming Whisper {whisper_name} (downloads once, then cached)…")
            device = "cuda" if probe_gpu().get("ready") else "cpu"
            compute = "float16" if device == "cuda" else "int8"
            WhisperModel(whisper_name, device=device, compute_type=compute)
            note(f"Whisper {whisper_name} ready on {device}.")
        except Exception as exc:  # noqa: BLE001
            note(f"Whisper warmup skipped: {exc}")

    needs_mind = "twin" in wanted or "vision" in wanted
    if needs_mind:
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
            if profile_id == "small":
                note("Small install: Ollama is not required. Twin stays cloud Auto.")
            else:
                note("Ollama not running — cloud Claude stays in charge until you start it.")

    wants_engines = bool(
        wanted & {"tts", "avatar", "voicebox", "qwen3_tts", "latentsync", "voice_clone"}
    )
    if wants_engines:
        for line in coach_install_lines():
            note(line)
            try:
                log_info("companion", line)
            except Exception:
                pass
        urls = engine_urls()
        vb = probe_voicebox(urls["voicebox_url"])
        q3 = probe_qwen3_tts(urls["qwen3_tts_url"])
        ls = probe_latentsync(urls["latentsync_url"])
        if "voicebox" in wanted or "voice_clone" in wanted or "tts" in wanted:
            if vb.get("ready"):
                note("Voicebox is listening — Auto TTS will prefer it.")
            else:
                note("Voicebox not detected. Install the official MSI or Docker, start it, then Probe. Setup continues.")
                try:
                    log_warn("tts", vb.get("detail") or "Voicebox not ready")
                except Exception:
                    pass
        if "qwen3_tts" in wanted or "voice_clone" in wanted or "tts" in wanted:
            if q3.get("ready"):
                note("Qwen3-TTS is listening.")
            else:
                note("Qwen3-TTS not detected. Install via pip or Docker, then Probe. Setup continues.")
        if "latentsync" in wanted or "avatar" in wanted:
            if ls.get("ready"):
                note("LatentSync is listening.")
            else:
                note("LatentSync not detected. Start the local HTTP engine, then Probe. Setup continues.")
        p = probe_piper()
        if p.get("ready"):
            note("Piper already on PATH.")
        else:
            note("Piper not installed; it stays a fallback after local clone engines.")

    if "machine_role" in wanted and profile_id == "dedicated":
        note("Dedicated PC role: install_profile will be written by the dedicated module.")

    probe = full_probe()
    settings = config.load_settings()
    settings["runtime_probe"] = probe
    settings["last_provision_log"] = log
    if profile_id:
        settings["space_profile"] = profile_id
        settings["install_profile"] = profile_id
        settings["disk_profile"] = profile_id
        settings["provision_manifest"] = {k: manifest.get(k) for k in ("id", "whisper", "features", "warm_engines")}
    config.save_settings(settings)
    probe["log"] = log
    if fatal:
        probe["error"] = fatal
    return probe
