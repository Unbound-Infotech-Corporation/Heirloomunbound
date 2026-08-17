"""Command runtime for the Heirloom desktop app.

Polls the backend for OS commands the Twin has queued (open apps, control
volume/media, power, notify, type, clipboard, screenshot for vision, system
status, find file, shell) and executes them locally — then reports results
back. Runs in its own QThread so the Qt UI never blocks.

This mirrors the executor baked into the single-file companion script so the
full desktop app has the exact same "Twin can use my computer" abilities.
"""
from __future__ import annotations

import io
import os
import platform
import subprocess
import time
import webbrowser

import requests
from PySide6.QtCore import QThread, Signal

from . import config

POLL_INTERVAL_SEC = 3


def _api(path: str) -> str:
    return f"{config.BACKEND_URL.rstrip('/')}/api{path}"


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.DEVICE_TOKEN}"}


# ---------- OS helpers (cross-platform) ----------
def _ps(cmd: str):
    r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                       capture_output=True, text=True, timeout=30)
    return (r.returncode == 0), ((r.stdout or "") + (r.stderr or "")).strip()


def open_app(name: str) -> str:
    system = platform.system()
    if system == "Windows":
        os.startfile(name)  # type: ignore[attr-defined]
    elif system == "Darwin":
        subprocess.run(["open", "-a", name], check=True)
    else:
        subprocess.Popen([name])
    return f"opened {name}"


# Optional hook so the UI can apply set_volume to the Heirloom WASAPI
# session instead of the system master (which hid us from the mixer).
_volume_hook = None
_provision_hook = None


def register_volume_hook(fn) -> None:
    global _volume_hook
    _volume_hook = fn


def register_provision_hook(fn) -> None:
    global _provision_hook
    _provision_hook = fn


def set_system_volume(level):
    system = platform.system()
    level = max(0, min(100, int(level)))
    if system == "Darwin":
        subprocess.run(["osascript", "-e", f"set volume output volume {level}"], check=False)
        return "ok", f"volume {level}%"
    if system == "Windows":
        try:
            from ctypes import POINTER, cast
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            devices = AudioUtilities.GetSpeakers()
            iface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            vol = cast(iface, POINTER(IAudioEndpointVolume))
            vol.SetMasterVolumeLevelScalar(level / 100.0, None)
            return "ok", f"volume {level}%"
        except Exception:
            presses = max(1, level // 2)
            _ps("$w=New-Object -ComObject WScript.Shell;1..50|%{$w.SendKeys([char]174)};1.." + str(presses) + "|%{$w.SendKeys([char]175)}")
            return "ok", f"volume ~{level}% (install pycaw for exact)"
    subprocess.run(["bash", "-c", f"amixer -q -D pulse sset Master {level}% || pactl set-sink-volume @DEFAULT_SINK@ {level}%"], check=False)
    return "ok", f"volume {level}%"


def media_key(action):
    system = platform.system()
    if system == "Windows":
        codes = {"playpause": 179, "play": 179, "pause": 179, "next": 176,
                 "previous": 177, "prev": 177, "volume_up": 175, "volume_down": 174, "mute": 173}
        code = codes.get(action)
        if code is None:
            return "error", f"unknown media action {action}"
        _ps("$w=New-Object -ComObject WScript.Shell;$w.SendKeys([char]" + str(code) + ")")
        return "ok", action
    if system == "Darwin":
        if action == "mute":
            subprocess.run(["osascript", "-e", "set volume output muted true"], check=False)
            return "ok", "mute"
        if action in ("volume_up", "volume_down"):
            op = "+" if action == "volume_up" else "-"
            subprocess.run(["osascript", "-e", f"set volume output volume (output volume of (get volume settings) {op} 10)"], check=False)
            return "ok", action
        keymap = {"playpause": 16, "play": 16, "pause": 16, "next": 17, "previous": 18, "prev": 18}
        subprocess.run(["osascript", "-e", f'tell application "System Events" to key code {keymap.get(action, 16)}'], check=False)
        return "ok", action
    pmap = {"playpause": "play-pause", "play": "play", "pause": "pause", "next": "next", "previous": "previous", "prev": "previous"}
    if action in pmap:
        subprocess.run(["playerctl", pmap[action]], check=False)
    elif action == "mute":
        subprocess.run(["bash", "-c", "amixer -q -D pulse sset Master toggle || pactl set-sink-mute @DEFAULT_SINK@ toggle"], check=False)
    else:
        d = "5%+" if action == "volume_up" else "5%-"
        subprocess.run(["bash", "-c", f"amixer -q -D pulse sset Master {d} || pactl set-sink-volume @DEFAULT_SINK@ {d}"], check=False)
    return "ok", action


def power_action(action):
    system = platform.system()
    if system == "Windows":
        cmds = {"lock": "rundll32.exe user32.dll,LockWorkStation",
                "sleep": "rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
                "shutdown": "shutdown /s /t 5", "restart": "shutdown /r /t 5"}
    elif system == "Darwin":
        cmds = {"lock": "pmset displaysleepnow", "sleep": "pmset sleepnow",
                "shutdown": "osascript -e 'tell app \"System Events\" to shut down'",
                "restart": "osascript -e 'tell app \"System Events\" to restart'"}
    else:
        cmds = {"lock": "loginctl lock-session || xdg-screensaver lock",
                "sleep": "systemctl suspend", "shutdown": "shutdown -h +0", "restart": "shutdown -r +0"}
    c = cmds.get(action)
    if not c:
        return "error", f"unknown power action {action}"
    subprocess.Popen(c, shell=True)
    return "ok", action


def notify_desktop(title, message):
    system = platform.system()
    if system == "Windows":
        t = (title or "Heirloom").replace('"', "'")
        m = (message or "").replace('"', "'")
        ps = ("Add-Type -AssemblyName System.Windows.Forms;"
              "Add-Type -AssemblyName System.Drawing;"
              "$n=New-Object System.Windows.Forms.NotifyIcon;"
              "$n.Icon=[System.Drawing.SystemIcons]::Information;$n.Visible=$true;"
              f'$n.BalloonTipTitle="{t}";$n.BalloonTipText="{m}";'
              "$n.ShowBalloonTip(6000);Start-Sleep -Seconds 7;$n.Dispose()")
        subprocess.Popen(["powershell", "-NoProfile", "-Command", ps])
        return "ok", "notified"
    if system == "Darwin":
        subprocess.run(["osascript", "-e", f'display notification "{message}" with title "{title}"'], check=False)
        return "ok", "notified"
    subprocess.run(["notify-send", title or "Heirloom", message or ""], check=False)
    return "ok", "notified"


def _sendkeys_escape(text):
    out = []
    for ch in text:
        if ch == "{":
            out.append("{{}")
        elif ch == "}":
            out.append("{}}")
        elif ch in "+^%~()[]":
            out.append("{" + ch + "}")
        elif ch == "\n":
            out.append("{ENTER}")
        else:
            out.append(ch)
    return "".join(out).replace('"', '""')


def type_text(text):
    try:
        from pynput.keyboard import Controller
        Controller().type(text)
        return "ok", "typed"
    except Exception:
        pass
    system = platform.system()
    if system == "Windows":
        _ps('$w=New-Object -ComObject WScript.Shell;$w.SendKeys("' + _sendkeys_escape(text) + '")')
        return "ok", "typed"
    if system == "Darwin":
        esc = text.replace('"', chr(92) + '"')
        subprocess.run(["osascript", "-e", f'tell application "System Events" to keystroke "{esc}"'], check=False)
        return "ok", "typed"
    subprocess.run(["xdotool", "type", "--clearmodifiers", text], check=False)
    return "ok", "typed"


def clipboard_get():
    system = platform.system()
    if system == "Windows":
        ok, out = _ps("Get-Clipboard -Raw")
        return ("ok" if ok else "error"), out
    if system == "Darwin":
        r = subprocess.run(["pbpaste"], capture_output=True, text=True)
        return "ok", r.stdout
    r = subprocess.run(["bash", "-c", "xclip -selection clipboard -o 2>/dev/null || xsel -b 2>/dev/null"], capture_output=True, text=True)
    return "ok", r.stdout


def clipboard_set(text):
    system = platform.system()
    if system == "Windows":
        subprocess.run(["powershell", "-NoProfile", "-Command", "$input | Set-Clipboard"], input=text, text=True)
        return "ok", "copied"
    if system == "Darwin":
        subprocess.run(["pbcopy"], input=text, text=True)
        return "ok", "copied"
    subprocess.run(["bash", "-c", "xclip -selection clipboard 2>/dev/null || xsel -b 2>/dev/null"], input=text, text=True)
    return "ok", "copied"


def system_status():
    lines = [f"OS: {platform.platform()}", f"Machine: {platform.node()} ({platform.machine()})"]
    try:
        import psutil
        lines.append(f"CPU: {psutil.cpu_percent(interval=0.5)}% across {psutil.cpu_count()} logical cores")
        vm = psutil.virtual_memory()
        lines.append(f"RAM: {vm.percent}% used ({vm.used // (1024**3)} / {vm.total // (1024**3)} GB)")
        du = psutil.disk_usage(os.path.expanduser("~"))
        lines.append(f"Disk: {du.percent}% used ({du.used // (1024**3)} / {du.total // (1024**3)} GB)")
        try:
            bat = psutil.sensors_battery()
            if bat:
                lines.append(f"Battery: {int(bat.percent)}%" + (" (charging)" if bat.power_plugged else ""))
        except Exception:
            pass
    except Exception:
        lines.append("(install psutil for CPU/RAM/disk detail)")
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu", "--format=csv,noheader,nounits"],
                          capture_output=True, text=True, timeout=8)
        if r.returncode == 0 and r.stdout.strip():
            for ln in r.stdout.strip().splitlines():
                p = [x.strip() for x in ln.split(",")]
                if len(p) >= 5:
                    lines.append(f"GPU: {p[0]} — {p[1]}% util, {p[2]}/{p[3]} MB VRAM, {p[4]}C")
    except Exception:
        pass
    return "ok", "\n".join(lines)


def find_file(query, open_it):
    home = os.path.expanduser("~")
    roots = [os.path.join(home, d) for d in ("Desktop", "Documents", "Downloads")] + [home]
    ql = (query or "").lower()
    matches = []
    start = time.time()
    seen = set()
    for root in roots:
        if root in seen or not os.path.isdir(root):
            continue
        seen.add(root)
        for dirpath, dirnames, filenames in os.walk(root):
            if time.time() - start > 10:
                break
            for n in list(filenames) + list(dirnames):
                if ql in n.lower():
                    matches.append(os.path.join(dirpath, n))
                    if len(matches) >= 10:
                        break
            if len(matches) >= 10:
                break
        if len(matches) >= 10 or time.time() - start > 10:
            break
    if not matches:
        return "ok", f"No files matching '{query}' in Desktop, Documents, or Downloads."
    result = "Found:\n" + "\n".join(f"- {m}" for m in matches[:10])
    if open_it:
        top = matches[0]
        try:
            if platform.system() == "Windows":
                os.startfile(top)  # type: ignore[attr-defined]
            elif platform.system() == "Darwin":
                subprocess.run(["open", top], check=False)
            else:
                subprocess.run(["xdg-open", top], check=False)
            result += f"\nOpened: {top}"
        except Exception as e:
            result += f"\n(couldn't open: {e})"
    return "ok", result


def speak_locally(text: str) -> None:
    """Speak reminder / say-command text through cloned voice when possible."""
    from .voice_output import speak_cloned_or_system

    speak_cloned_or_system(text)


def capture_and_upload_screenshot(cmd_id):
    img = None
    errors = []
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"ImageGrab: {exc}")
        try:
            import mss
            from PIL import Image
            with mss.mss() as s:
                raw = s.grab(s.monitors[0])
                img = Image.frombytes("RGB", raw.size, raw.rgb)
        except Exception as exc2:  # noqa: BLE001
            errors.append(f"mss: {exc2}")
            return "error", "screenshot failed — install Pillow + mss. " + "; ".join(errors)
    img = img.convert("RGB")
    max_w = 1600
    if img.width > max_w:
        img = img.resize((max_w, int(img.height * max_w / img.width)))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=75)
    buf.seek(0)
    files = {"file": ("screen.jpg", buf, "image/jpeg")}
    try:
        r = requests.post(
            _api("/companion/screenshot"),
            headers=_headers(),
            data={"cmd_id": cmd_id},
            files=files,
            timeout=30,
        )
    except Exception as exc:  # noqa: BLE001
        return "error", f"upload failed: {exc}"
    if r.status_code == 200:
        return "ok", "captured"
    return "error", f"upload failed ({r.status_code})"


def execute(cmd: dict):
    kind = cmd.get("kind")
    payload = cmd.get("payload") or {}
    try:
        if kind == "shell":
            r = subprocess.run(payload.get("command", ""), shell=True, capture_output=True, text=True, timeout=60)
            out = (r.stdout or "") + ("\n" + r.stderr if r.stderr else "")
            return ("ok" if r.returncode == 0 else "error"), out[:4000]
        if kind == "open_url":
            webbrowser.open(payload.get("url", ""))
            return "ok", "opened"
        if kind == "open_app":
            return "ok", open_app(payload.get("name", ""))
        if kind == "set_volume":
            level = payload.get("level", 50)
            if _volume_hook is not None:
                _volume_hook(level)
                return "ok", f"Heirloom session volume {level}%"
            return set_system_volume(level)
        if kind == "provision_models":
            if _provision_hook is not None:
                return _provision_hook(payload)
            from .models import provision

            result = provision(payload.get("features"))
            log = result.get("log") or [result.get("detail") or "provisioned"]
            return "ok", "\n".join(str(x) for x in log)
        if kind == "media_key":
            return media_key(payload.get("action", ""))
        if kind == "power":
            return power_action(payload.get("action", ""))
        if kind == "notify":
            return notify_desktop(payload.get("title", "Heirloom"), payload.get("message", ""))
        if kind == "type_text":
            return type_text(payload.get("text", ""))
        if kind == "clipboard_get":
            return clipboard_get()
        if kind == "clipboard_set":
            return clipboard_set(payload.get("text", ""))
        if kind == "system_status":
            return system_status()
        if kind == "find_file":
            return find_file(payload.get("query", ""), bool(payload.get("open")))
        if kind == "screenshot":
            return capture_and_upload_screenshot(cmd.get("cmd_id", ""))
        if kind == "say":
            speak_locally(payload.get("text", ""))
            return "ok", "spoken"
        return "error", f"unknown kind {kind}"
    except Exception as e:
        return "error", str(e)


class CommandPoller(QThread):
    """Polls /companion/poll every few seconds and executes queued commands."""

    ran = Signal(str)  # emits a short human label when a command runs
    status = Signal(str)  # emits connection / account status for the UI
    audio_settings = Signal(dict)
    model_map = Signal(dict)
    volume_command = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True
        self._consecutive_errors = 0
        self._runtime_every = 0

    def stop(self) -> None:
        self._running = False

    def _post_runtime(self) -> None:
        try:
            from .audio import list_input_devices, list_output_devices
            from .models import full_probe

            probe = full_probe()
            probe["audio_devices"] = list_input_devices() + list_output_devices()
            requests.post(
                _api("/companion/runtime"),
                headers=_headers(),
                json=probe,
                timeout=10,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[poller] runtime probe failed: {exc}")

    def run(self) -> None:  # pragma: no cover — runs in a worker thread
        if not config.DEVICE_TOKEN:
            self.status.emit("no device token")
            return
        while self._running:
            try:
                r = requests.get(_api("/companion/poll"), headers=_headers(), timeout=15)
                if r.status_code == 403:
                    detail = ""
                    try:
                        detail = (r.json() or {}).get("detail", "")
                    except Exception:  # noqa: BLE001
                        pass
                    self.status.emit(
                        "account inactive" if detail == "account_inactive" else "forbidden"
                    )
                    # Back off harder when the account is locked out
                    for _ in range(30):
                        if not self._running:
                            break
                        time.sleep(1)
                    continue
                if r.status_code == 401:
                    self.status.emit("auth failed — re-download the app")
                    time.sleep(15)
                    continue
                if r.status_code == 200:
                    self._consecutive_errors = 0
                    data = r.json() or {}
                    audio = data.get("audio_settings")
                    if isinstance(audio, dict):
                        self.audio_settings.emit(audio)
                    mmap = data.get("model_map")
                    if isinstance(mmap, dict):
                        self.model_map.emit(mmap)
                    self._runtime_every += 1
                    if self._runtime_every == 1 or self._runtime_every % 10 == 0:
                        self._post_runtime()
                    for cmd in data.get("commands", []):
                        if cmd.get("kind") == "set_volume":
                            level = int((cmd.get("payload") or {}).get("level") or 50)
                            level = max(0, min(100, level))
                            self.volume_command.emit(level)
                            status, output = "ok", f"Heirloom session volume {level}%"
                        else:
                            status, output = execute(cmd)
                        label = cmd.get("kind", "command")
                        self.ran.emit(f"{label} · {status}")
                        try:
                            requests.post(
                                _api("/companion/result"),
                                headers=_headers(),
                                json={
                                    "cmd_id": cmd.get("cmd_id"),
                                    "status": status,
                                    "output": output,
                                },
                                timeout=15,
                            )
                        except Exception as exc:  # noqa: BLE001
                            print(f"[poller] result post failed: {exc}")
                else:
                    self._consecutive_errors += 1
                    if self._consecutive_errors <= 3 or self._consecutive_errors % 10 == 0:
                        self.status.emit(f"poll HTTP {r.status_code}")
            except Exception as exc:  # noqa: BLE001
                self._consecutive_errors += 1
                if self._consecutive_errors <= 3 or self._consecutive_errors % 10 == 0:
                    self.status.emit(f"offline: {exc!s}"[:60])
            for _ in range(POLL_INTERVAL_SEC * 2):
                if not self._running:
                    break
                time.sleep(0.5)
