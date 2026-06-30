"""Push-to-talk recorder + upload helper.

Uses sounddevice + soundfile (already in the existing companion's deps).
Captures mono 16kHz WAV while a hotkey is held, then ships the bytes to
`/api/companion/voice` (the existing endpoint that transcribes + replies in
one round-trip).

This module is GUI-free — the main window owns the start/stop signals and
just calls `Recorder.start()` / `Recorder.stop()`.
"""
from __future__ import annotations

import io
from typing import List, Optional

import numpy as np
import sounddevice as sd
import soundfile as sf
from PySide6.QtCore import QObject, Signal

SAMPLE_RATE = 16000
CHANNELS = 1


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

    # ---- public ----
    def is_recording(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        if self._stream is not None:
            return
        self._chunks = []
        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="float32",
                callback=self._on_audio,
                blocksize=int(SAMPLE_RATE * 0.05),  # 50 ms
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
        buf = io.BytesIO()
        sf.write(buf, audio, SAMPLE_RATE, format="WAV", subtype="PCM_16")
        self.wav_bytes.emit(buf.getvalue())

    # ---- internal ----
    def _on_audio(self, indata, frames, time_info, status):
        if status:
            # XRuns are expected — don't spam errors
            pass
        block = indata.copy()
        self._chunks.append(block)
        # RMS for the visualiser
        try:
            rms = float(np.sqrt(np.mean(block * block)))
        except Exception:
            rms = 0.0
        # Map 0..0.3 → 0..1 so quiet speech still shows
        self.level.emit(min(1.0, rms * 3.5))
