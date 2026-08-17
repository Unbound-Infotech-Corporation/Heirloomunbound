"""Push-to-talk + live-listen recorder with streaming-software mic controls.

Uses sounddevice for capture (WASAPI shared on Windows) so the selected
microphone, gain, high-pass, and noise gate actually apply. Playback of
the twin goes through MixerSession / QAudioOutput so the Windows mixer
slider is this process — never the system master volume.
"""
from __future__ import annotations

import io
from typing import List, Optional

import numpy as np
import sounddevice as sd
import soundfile as sf
from PySide6.QtCore import QObject, QTimer, Signal

from . import mixer as mixer_mod

SAMPLE_RATE = 16000
CHANNELS = 1


def _resolve_sd_device(device_id: str, kind: str) -> Optional[int]:
    """Map our stored id ('default' | Qt id | PortAudio index | name) to a
    sounddevice device index. Returns None for host default."""
    if not device_id or device_id == "default":
        return None
    try:
        if str(device_id).isdigit():
            return int(device_id)
    except Exception:
        pass
    try:
        devices = sd.query_devices()
    except Exception:
        return None
    needle = str(device_id).lower()
    for i, d in enumerate(devices):
        name = str(d.get("name") or "").lower()
        if needle == name or needle in name:
            if kind == "input" and d.get("max_input_channels", 0) > 0:
                return i
            if kind == "output" and d.get("max_output_channels", 0) > 0:
                return i
    return None


def list_input_devices() -> list:
    return list_portaudio_devices().get("inputs") or []


def list_output_devices() -> list:
    try:
        qt = mixer_mod.list_qt_devices()
        if qt.get("outputs"):
            return qt["outputs"]
    except Exception:
        pass
    return list_portaudio_devices().get("outputs") or []


def play_test_tone(device_id: str = "default", volume: int = 80) -> None:
    """440 Hz beep on the selected output so the user can confirm the mixer session."""
    try:
        sr = 44100
        t = np.linspace(0, 0.35, int(sr * 0.35), False)
        amp = max(0.02, min(0.4, (int(volume) / 100.0) * 0.3))
        wave = (amp * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        sd.play(wave, sr, device=_resolve_sd_device(str(device_id or "default"), "output"))
    except Exception as exc:  # noqa: BLE001
        print(f"[audio] test tone failed: {exc}")


def list_portaudio_devices() -> dict:
    inputs, outputs = [], []
    try:
        hostapis = sd.query_hostapis()
        default_in, default_out = sd.default.device
        for i, d in enumerate(sd.query_devices()):
            api = ""
            try:
                api = hostapis[d["hostapi"]]["name"]
            except Exception:
                pass
            rec = {
                "id": str(i),
                "name": f"{d.get('name')} ({api})" if api else d.get("name"),
                "hostapi": api,
                "channels_in": int(d.get("max_input_channels") or 0),
                "channels_out": int(d.get("max_output_channels") or 0),
            }
            if rec["channels_in"] > 0:
                inputs.append({**rec, "kind": "input", "default": i == default_in})
            if rec["channels_out"] > 0:
                outputs.append({**rec, "kind": "output", "default": i == default_out})
    except Exception as exc:  # noqa: BLE001
        return {"inputs": [], "outputs": [], "error": str(exc)}
    return {"inputs": inputs, "outputs": outputs}


class Recorder(QObject):
    """Holds a single in-progress recording. Emits `level` (0..1) at ~20 Hz
    so the UI can animate a waveform. On stop, emits `wav_bytes` once."""

    level = Signal(float)
    wav_bytes = Signal(bytes)
    error = Signal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._stream: Optional[sd.InputStream] = None
        self._chunks: List[np.ndarray] = []
        self._settings = {
            "input_device_id": "default",
            "input_gain": 100,
            "mute_input": False,
            "noise_gate_db": -45,
            "high_pass_hz": 80,
            "noise_suppression": True,
            "monitor_input": False,
            "sample_rate": SAMPLE_RATE,
        }
        self._hp_state = 0.0
        self._monitor_playing = False

    def apply_settings(self, settings: dict) -> None:
        if isinstance(settings, dict):
            self._settings.update(settings)

    def is_recording(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        if self._stream is not None:
            return
        self._chunks = []
        self._hp_state = 0.0
        rate = int(self._settings.get("sample_rate") or SAMPLE_RATE)
        if rate not in (16000, 44100, 48000):
            rate = SAMPLE_RATE
        device = _resolve_sd_device(str(self._settings.get("input_device_id") or "default"), "input")
        try:
            self._stream = sd.InputStream(
                samplerate=rate,
                channels=CHANNELS,
                dtype="float32",
                callback=self._on_audio,
                blocksize=int(rate * 0.05),
                device=device,
                latency="low",
            )
            self._stream.start()
        except Exception as exc:  # noqa: BLE001
            self._stream = None
            self.error.emit(f"Mic open failed: {exc}")

    def stop(self) -> None:
        s = self._stream
        if s is None:
            return
        self._stream = None
        try:
            s.stop()
            s.close()
        except Exception:
            pass
        if not self._chunks:
            self.wav_bytes.emit(b"")
            return
        audio = np.concatenate(self._chunks, axis=0)
        # Always encode 16 kHz for the backend Whisper path
        target = SAMPLE_RATE
        src_rate = int(self._settings.get("sample_rate") or SAMPLE_RATE)
        if src_rate != target and audio.size:
            duration = audio.shape[0] / float(src_rate)
            n = max(1, int(duration * target))
            x_old = np.linspace(0.0, 1.0, audio.shape[0], endpoint=False)
            x_new = np.linspace(0.0, 1.0, n, endpoint=False)
            audio = np.interp(x_new, x_old, audio[:, 0]).astype(np.float32)
            audio = audio.reshape(-1, 1)
        buf = io.BytesIO()
        sf.write(buf, audio, SAMPLE_RATE, format="WAV", subtype="PCM_16")
        self.wav_bytes.emit(buf.getvalue())

    def _process(self, block: np.ndarray) -> np.ndarray:
        if self._settings.get("mute_input"):
            return np.zeros_like(block)
        gain = max(0.0, min(2.0, (int(self._settings.get("input_gain") or 100)) / 100.0))
        y = block * gain
        hp = int(self._settings.get("high_pass_hz") or 0)
        rate = float(self._settings.get("sample_rate") or SAMPLE_RATE)
        if hp > 0 and y.size:
            # One-pole high-pass
            rc = 1.0 / (2.0 * np.pi * hp)
            dt = 1.0 / rate
            a = rc / (rc + dt)
            out = np.empty_like(y)
            prev_x = self._hp_state
            prev_y = 0.0
            flat = y[:, 0]
            acc = np.empty_like(flat)
            for i, x in enumerate(flat):
                prev_y = a * (prev_y + x - prev_x)
                prev_x = x
                acc[i] = prev_y
            self._hp_state = float(prev_x)
            out[:, 0] = acc
            y = out
        if self._settings.get("noise_suppression"):
            # Cheap spectral subtraction stand-in: shrink bins near the noise floor
            floor = 10 ** (float(self._settings.get("noise_gate_db") or -45) / 20.0)
            rms = float(np.sqrt(np.mean(y * y))) if y.size else 0.0
            if rms < floor * 1.5:
                y = y * max(0.0, rms / max(floor, 1e-6) - 1.0)
        gate = 10 ** (float(self._settings.get("noise_gate_db") or -45) / 20.0)
        rms = float(np.sqrt(np.mean(y * y))) if y.size else 0.0
        if rms < gate:
            y = np.zeros_like(y)
        return np.clip(y, -1.0, 1.0)

    def _maybe_monitor(self, block: np.ndarray) -> None:
        if not self._settings.get("monitor_input") or self._settings.get("mute_input"):
            return
        if block.size == 0:
            return
        try:
            rate = int(self._settings.get("sample_rate") or SAMPLE_RATE)
            out_dev = _resolve_sd_device(str(self._settings.get("output_device_id") or "default"), "output")
            quiet = (block * 0.35).astype(np.float32)
            sd.play(quiet, rate, device=out_dev, blocking=False)
        except Exception:
            pass

    def _on_audio(self, indata, frames, time_info, status):
        block = self._process(indata.copy())
        self._maybe_monitor(block)
        self._chunks.append(block)
        try:
            rms = float(np.sqrt(np.mean(block * block)))
        except Exception:
            rms = 0.0
        self.level.emit(min(1.0, rms * 3.5))


class LiveListen(QObject):
    """Always-on room mic: when energy stays above the gate, treat it as
    speech, then emit wav_bytes after hangover silence — 'speak when you
    walk into the room'."""

    started = Signal()
    stopped = Signal()
    wav_bytes = Signal(bytes)
    level = Signal(float)
    error = Signal(str)

    def __init__(self, recorder: Recorder, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.recorder = recorder
        self._enabled = False
        self._hangover_ms = 900
        self._silent_ms = 0
        self._speech = False
        self._tick = QTimer(self)
        self._tick.setInterval(50)
        self._tick.timeout.connect(self._on_tick)
        self.recorder.level.connect(self._on_level)
        self.recorder.wav_bytes.connect(self._on_wav)
        self.recorder.error.connect(self.error)
        self._last_level = 0.0

    def set_enabled(self, enabled: bool, hangover_ms: int = 900) -> None:
        self._hangover_ms = hangover_ms
        self._enabled = bool(enabled)
        if self._enabled:
            if not self.recorder.is_recording():
                self.recorder.start()
            self._tick.start()
        else:
            self._tick.stop()
            if self.recorder.is_recording() and self._speech:
                self.recorder.stop()
            elif self.recorder.is_recording():
                # Drop the idle buffer
                self.recorder._chunks = []  # noqa: SLF001
                self.recorder.stop()
            self._speech = False

    def _on_level(self, level: float) -> None:
        self._last_level = level
        self.level.emit(level)

    def _on_tick(self) -> None:
        if not self._enabled:
            return
        if not self.recorder.is_recording():
            self.recorder.start()
            return
        speaking = self._last_level > 0.08
        if speaking:
            if not self._speech:
                self._speech = True
                self.started.emit()
            self._silent_ms = 0
        elif self._speech:
            self._silent_ms += 50
            if self._silent_ms >= self._hangover_ms:
                self._speech = False
                self.recorder.stop()

    def _on_wav(self, wav: bytes) -> None:
        if self._enabled and wav:
            self.wav_bytes.emit(wav)
            self.stopped.emit()
            # Restart capture for the next utterance
            QTimer.singleShot(200, self.recorder.start)
