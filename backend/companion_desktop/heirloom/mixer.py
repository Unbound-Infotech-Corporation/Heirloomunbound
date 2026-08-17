"""Windows / cross-platform audio session + device inventory.

Goals that the old path missed:
1. Heirloom must appear as its *own* slider in the Windows Volume Mixer —
   not by slamming the system master volume with SendKeys / endpoint volume.
2. Input and output devices must be selectable (OBS-style).
3. Session volume is 0–100 and is what `set_volume` from the Twin writes.

Qt Multimedia (QAudioSink) is used as the keepalive so the WASAPI session
belongs to *this* process under the name "Heirloom". pycaw then finds that
session by PID and sets SimpleAudioVolume.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Optional

from PySide6.QtCore import QByteArray, QIODevice, QObject, QTimer
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices


def set_app_identity() -> None:
    """Must run before the first audio stream. Makes the mixer label
    'Heirloom' instead of 'python.exe'."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(  # type: ignore[attr-defined]
            "UnboundInfotech.Heirloom"
        )
    except Exception:
        pass


def list_qt_devices() -> dict[str, list[dict[str, Any]]]:
    inputs = []
    outputs = []
    default_in = QMediaDevices.defaultAudioInput()
    default_out = QMediaDevices.defaultAudioOutput()
    for d in QMediaDevices.audioInputs():
        did = bytes(d.id()).decode("utf-8", "replace") if d.id() else d.description()
        inputs.append(
            {
                "id": did or "default",
                "name": d.description() or "Microphone",
                "kind": "input",
                "default": d.id() == default_in.id(),
            }
        )
    for d in QMediaDevices.audioOutputs():
        did = bytes(d.id()).decode("utf-8", "replace") if d.id() else d.description()
        outputs.append(
            {
                "id": did or "default",
                "name": d.description() or "Speakers",
                "kind": "output",
                "default": d.id() == default_out.id(),
            }
        )
    return {"inputs": inputs, "outputs": outputs}


def _match_output(device_id: str):
    default = QMediaDevices.defaultAudioOutput()
    if not device_id or device_id == "default":
        return default
    for d in QMediaDevices.audioOutputs():
        did = bytes(d.id()).decode("utf-8", "replace") if d.id() else d.description()
        if did == device_id or d.description() == device_id:
            return d
    return default


def _match_input(device_id: str):
    default = QMediaDevices.defaultAudioInput()
    if not device_id or device_id == "default":
        return default
    for d in QMediaDevices.audioInputs():
        did = bytes(d.id()).decode("utf-8", "replace") if d.id() else d.description()
        if did == device_id or d.description() == device_id:
            return d
    return default


class _SilenceDevice(QIODevice):
    """Endless zeros so the WASAPI session stays alive in the mixer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.open(QIODevice.ReadOnly)

    def readData(self, maxlen: int) -> bytes:  # noqa: N802
        return bytes(max(0, maxlen))

    def writeData(self, _data: QByteArray) -> int:  # noqa: N802
        return 0

    def bytesAvailable(self) -> int:  # noqa: N802
        return 48000


class MixerSession(QObject):
    """Persistent named output session + volume that Windows mixer can grab."""

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._sink: Optional[QAudioSink] = None
        self._silence = _SilenceDevice(self)
        self._device_id = "default"
        self._volume = 0.8
        self._muted = False
        self._timer = QTimer(self)
        self._timer.setInterval(15000)
        self._timer.timeout.connect(self._refresh_display_name)
        self.start("default")

    def start(self, device_id: str = "default") -> None:
        self._device_id = device_id or "default"
        self.stop()
        device = _match_output(self._device_id)
        fmt = QAudioFormat()
        fmt.setSampleRate(48000)
        fmt.setChannelCount(2)
        fmt.setSampleFormat(QAudioFormat.Float)
        if not device.isFormatSupported(fmt):
            fmt = device.preferredFormat()
        try:
            self._sink = QAudioSink(device, fmt, self)
            self._sink.setVolume(0.0 if self._muted else self._volume)
            self._sink.start(self._silence)
            self._timer.start()
            self._refresh_display_name()
        except Exception as exc:  # noqa: BLE001
            print(f"[mixer] keepalive failed: {exc}")
            self._sink = None

    def stop(self) -> None:
        if self._sink is not None:
            try:
                self._sink.stop()
            except Exception:
                pass
            self._sink = None

    def set_device(self, device_id: str) -> None:
        if device_id != self._device_id:
            self.start(device_id)

    def set_volume(self, level: int) -> None:
        self._volume = max(0.0, min(1.0, int(level) / 100.0))
        if self._sink is not None and not self._muted:
            self._sink.setVolume(self._volume)
        self._set_pycaw_volume(self._volume, self._muted)

    def set_mute(self, muted: bool) -> None:
        self._muted = bool(muted)
        if self._sink is not None:
            self._sink.setVolume(0.0 if self._muted else self._volume)
        self._set_pycaw_volume(self._volume, self._muted)

    def apply_to_qaudio(self, audio_out) -> None:
        """Keep QMediaPlayer's QAudioOutput on the same device + volume."""
        if audio_out is None:
            return
        try:
            audio_out.setDevice(_match_output(self._device_id))
            audio_out.setVolume(0.0 if self._muted else self._volume)
            audio_out.setMuted(self._muted)
        except Exception as exc:  # noqa: BLE001
            print(f"[mixer] qaudio apply failed: {exc}")

    def _set_pycaw_volume(self, scalar: float, muted: bool) -> None:
        if sys.platform != "win32":
            return
        try:
            from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
            from comtypes import CLSCTX_ALL  # noqa: F401

            pid = os.getpid()
            for session in AudioUtilities.GetAllSessions():
                proc = session.Process
                if proc is None or proc.pid != pid:
                    continue
                vol = session._ctl.QueryInterface(ISimpleAudioVolume)
                vol.SetMasterVolume(float(scalar), None)
                vol.SetMute(1 if muted else 0, None)
        except Exception:
            pass

    def _refresh_display_name(self) -> None:
        if sys.platform != "win32":
            return
        try:
            from pycaw.pycaw import AudioUtilities, IAudioSessionControl2

            pid = os.getpid()
            for session in AudioUtilities.GetAllSessions():
                proc = session.Process
                if proc is None or proc.pid != pid:
                    continue
                ctl = session._ctl.QueryInterface(IAudioSessionControl2)
                try:
                    ctl.SetDisplayName("Heirloom", None)
                except Exception:
                    pass
                try:
                    ctl.SetDuckingPreference(1)  # don't duck ourselves
                except Exception:
                    pass
        except Exception:
            pass
