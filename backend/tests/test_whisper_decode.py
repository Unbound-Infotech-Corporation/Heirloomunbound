"""faster-whisper must decode a wav with the pinned PyAV. PyAV 19 drops metadata_errors."""
from __future__ import annotations

import math
import struct
import wave
from pathlib import Path


def test_faster_whisper_decodes_a_generated_wav(tmp_path: Path):
    path = tmp_path / "tone.wav"
    rate = 16000
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(2000 * math.sin(2 * math.pi * 440 * i / rate)))
            for i in range(rate // 2)
        )
        handle.writeframes(frames)
    from faster_whisper.audio import decode_audio

    audio = decode_audio(str(path), sampling_rate=rate)
    assert len(audio) > 1000
