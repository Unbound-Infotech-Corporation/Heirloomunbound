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


def capture_and_upload_screenshot(cmd_id):
    img = None
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
    except Exception:
        import mss
        from PIL import Image
        with mss.mss() as s:
            raw = s.grab(s.monitors[0])
            img = Image.frombytes("RGB", raw.size, raw.rgb)
    img = img.convert("RGB")
    max_w = 1600
    if img.width > max_w:
        img = img.resize((max_w, int(img.height * max_w / img.width)))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=75)
    buf.seek(0)
    files = {"file": ("screen.jpg", buf, "image/jpeg")}
    r = requests.post(_api("/companion/screenshot"), headers=_headers(),
                      data={"cmd_id": cmd_id}, files=files, timeout=30)
    if r.status_code == 200:
        return "ok", "captured"
    return "error", f"upload failed ({r.status_code})"


def restore_photo_via_local(payload: dict) -> tuple[str, str]:
    """Fetch a photo from Heirloom, run it through the user's local image
    provider (ComfyUI or OpenAI-compat image API), and upload the result
    back to /api/restoration/jobs/{job_id}/result.

    Payload shape (from routers.restoration.create_job):
        {job_id, photo_id, kind, prompt_hint,
         provider: {base_url, api_key, model, provider_type, comfy_workflow}}
    """
    import json as _json

    job_id = payload.get("job_id")
    photo_id = payload.get("photo_id")
    kind = (payload.get("kind") or "restore").lower()
    prompt_hint = (payload.get("prompt_hint") or "").strip()
    prov = payload.get("provider") or {}
    base_url = (prov.get("base_url") or "").rstrip("/")
    api_key = (prov.get("api_key") or "").strip()
    model = (prov.get("model") or "").strip()
    ptype = (prov.get("provider_type") or "comfyui").lower()

    def _fail(reason: str) -> tuple[str, str]:
        try:
            requests.post(_api(f"/restoration/jobs/{job_id}/fail"),
                          headers=_headers(), json={"reason": reason[:400]}, timeout=15)
        except Exception:
            pass
        return "error", reason

    if not base_url:
        return _fail("no local image provider base_url configured")
    if not photo_id or not job_id:
        return _fail("missing job_id or photo_id")

    # 1. Download source photo via signed URL (companion has device token, so
    # it can hit /companion/photo-file which authorises by device_token).
    src_endpoint = _api(f"/companion/photo-file/{photo_id}")
    try:
        pr = requests.get(src_endpoint, headers=_headers(), timeout=45)
        if pr.status_code != 200:
            return _fail(f"could not fetch source photo (HTTP {pr.status_code})")
        source_bytes = pr.content
        source_ct = pr.headers.get("content-type", "image/jpeg")
    except Exception as exc:
        return _fail(f"source fetch error: {exc}")

    prompt = prompt_hint or {
        "restore":  "restore this old photo, remove scratches and grain, keep faces natural",
        "colorize": "colorize this black and white photo naturally",
        "upscale":  "upscale, sharpen and denoise this photo, preserve textures",
    }.get(kind, "restore old photo")

    # 2. Run the provider
    try:
        if ptype == "comfyui":
            out_bytes, out_ct = _run_comfyui(base_url, api_key, prov.get("comfy_workflow") or "", source_bytes, prompt, model)
        else:
            out_bytes, out_ct = _run_openai_image_edit(base_url, api_key, model or "gpt-image-1", source_bytes, prompt)
    except Exception as exc:
        return _fail(f"provider error: {exc}")

    if not out_bytes:
        return _fail("provider returned no image")

    # 3. Upload result back
    try:
        files = {"file": ("restored.png", io.BytesIO(out_bytes), out_ct or "image/png")}
        r = requests.post(_api(f"/restoration/jobs/{job_id}/result"),
                          headers=_headers(), files=files, timeout=90)
        if r.status_code != 200:
            return _fail(f"result upload failed (HTTP {r.status_code})")
    except Exception as exc:
        return _fail(f"result upload error: {exc}")

    return "ok", f"restored (kind={kind})"


def _run_openai_image_edit(base_url: str, api_key: str, model: str, image_bytes: bytes, prompt: str) -> tuple[bytes, str]:
    """Fallback path for OpenAI-compat image APIs (edits endpoint)."""
    files = {"image": ("in.png", io.BytesIO(image_bytes), "image/png")}
    data = {"prompt": prompt, "model": model, "response_format": "b64_json", "n": "1"}
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    r = requests.post(base_url.rstrip("/") + "/images/edits",
                      headers=headers, files=files, data=data, timeout=180)
    r.raise_for_status()
    body = r.json()
    b64 = body["data"][0].get("b64_json") or ""
    if not b64:
        # Fallback to URL variant
        url = body["data"][0].get("url")
        if not url:
            raise RuntimeError("no b64_json or url in response")
        r2 = requests.get(url, timeout=60)
        r2.raise_for_status()
        return r2.content, r2.headers.get("content-type", "image/png")
    import base64
    return base64.b64decode(b64), "image/png"


def _run_comfyui(base_url: str, api_key: str, workflow_str: str, image_bytes: bytes, prompt: str, model: str) -> tuple[bytes, str]:
    """POST an image → ComfyUI, run the user's workflow, poll for the result.

    If the user hasn't pasted a workflow, we use a minimal default that:
      LoadImage → FaceRestoreCFWithModel(GFPGAN) → SaveImage
    Requires the user to have GFPGAN + reactor node installed in their ComfyUI
    (which is one-click via Pinokio). If a node is missing ComfyUI returns a
    clear error string that we bubble up to the UI.
    """
    from .comfy_client import run_comfy_media

    uploaded_name = "input.png"
    default = _default_gfpgan_workflow(uploaded_name, prompt)
    # run_comfy_media uploads as input.png, matching the default graph.
    return run_comfy_media(
        base_url,
        api_key,
        workflow_str,
        image_bytes,
        prompt,
        model,
        timeout_sec=300,
        default_workflow=default if not (workflow_str or "").strip() else None,
    )


def _default_gfpgan_workflow(image_name: str, prompt: str) -> dict:
    """Minimal ComfyUI graph that loads an image and runs GFPGAN face restore.

    Node IDs are strings (ComfyUI convention). The FaceRestoreCFWithModel node
    ships with ComfyUI-Impact-Pack; if the user's ComfyUI doesn't have it,
    they can paste a custom workflow via Settings.
    """
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "2": {"class_type": "FaceRestoreCFWithModel",
              "inputs": {"facerestore_model": ["3", 0], "image": ["1", 0], "facedetection": "retinaface_resnet50"}},
        "3": {"class_type": "FaceRestoreModelLoader",
              "inputs": {"model_name": "GFPGANv1.4.pth"}},
        "4": {"class_type": "SaveImage",
              "inputs": {"images": ["2", 0], "filename_prefix": "heirloom_restored"}},
    }


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
            return set_system_volume(payload.get("level", 50))
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
            return "ok", "spoken"  # desktop app speaks replies elsewhere
        if kind == "restore_photo":
            return restore_photo_via_local(payload)
        if kind == "pull_model":
            from .local_ai import pull_model
            return pull_model(payload.get("model", ""))
        if kind == "list_models":
            from .local_ai import list_local_models
            return list_local_models()
        if kind == "llm_chat":
            from .local_ai import llm_chat_local
            return llm_chat_local(payload)
        if kind == "avatar_setup":
            from .pinokio_setup import run_easy_setup
            return run_easy_setup(payload)
        if kind in ("avatar_still", "avatar_talk", "avatar_look"):
            from .avatar_local import run_avatar_job
            body = dict(payload)
            body["kind"] = {
                "avatar_still": "still",
                "avatar_talk": "talk",
                "avatar_look": "look",
            }[kind]
            return run_avatar_job(body)
        return "error", f"unknown kind {kind}"
    except Exception as e:
        return "error", str(e)


class CommandPoller(QThread):
    """Polls /companion/poll every few seconds and executes queued commands."""

    ran = Signal(str)  # emits a short human label when a command runs

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:  # pragma: no cover — runs in a worker thread
        if not config.DEVICE_TOKEN:
            return
        while self._running:
            try:
                r = requests.get(_api("/companion/poll"), headers=_headers(), timeout=15)
                if r.status_code == 200:
                    for cmd in (r.json() or {}).get("commands", []):
                        status, output = execute(cmd)
                        label = cmd.get("kind", "command")
                        self.ran.emit(f"{label} · {status}")
                        try:
                            requests.post(_api("/companion/result"), headers=_headers(),
                                          json={"cmd_id": cmd.get("cmd_id"), "status": status, "output": output},
                                          timeout=15)
                        except Exception:
                            pass
                    try:
                        from .local_ai import list_local_models, ollama_installed
                        st, out = list_local_models()
                        models = []
                        if st == "ok":
                            models = [ln.split()[0] for ln in out.splitlines() if ln.split() and not ln.startswith("(")]
                        requests.post(
                            _api("/companion/status"),
                            headers=_headers(),
                            json={"ollama": ollama_installed() or st == "ok", "models": models},
                            timeout=10,
                        )
                    except Exception:
                        pass
            except Exception:
                pass
            for _ in range(POLL_INTERVAL_SEC * 2):
                if not self._running:
                    break
                time.sleep(0.5)
