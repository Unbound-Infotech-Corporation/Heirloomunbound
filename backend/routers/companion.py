"""Local PC Companion: device registration, command queue (pull model), audio passthrough."""
import io
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

from emergentintegrations.llm.chat import LlmChat, UserMessage
from emergentintegrations.llm.openai import OpenAISpeechToText
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel

from deps import EMERGENT_LLM_KEY, db, get_current_user

router = APIRouter(prefix="/companion", tags=["companion"])

# ---------- Device auth ----------
async def get_device_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing device token")
    token = authorization.split(" ", 1)[1].strip()
    device = await db.companion_devices.find_one({"device_token": token, "revoked": False}, {"_id": 0})
    if not device:
        raise HTTPException(status_code=401, detail="Invalid device token")
    user = await db.users.find_one({"user_id": device["user_id"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    # Refresh last_seen on poll
    await db.companion_devices.update_one(
        {"device_id": device["device_id"]},
        {"$set": {"last_seen": datetime.now(timezone.utc).isoformat()}},
    )
    return {"user": user, "device": device}


# ---------- Registration (user-facing) ----------
class RegisterReq(BaseModel):
    name: str = "My PC"


@router.post("/register")
async def register_device(payload: RegisterReq, user: dict = Depends(get_current_user)):
    device_id = f"dev_{uuid.uuid4().hex[:10]}"
    token = "comp_" + secrets.token_urlsafe(32)
    doc = {
        "device_id": device_id,
        "user_id": user["user_id"],
        "name": payload.name or "My PC",
        "device_token": token,
        "revoked": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_seen": None,
    }
    await db.companion_devices.insert_one(doc)
    return {"device_id": device_id, "name": payload.name, "device_token": token}


@router.get("/devices")
async def list_devices(user: dict = Depends(get_current_user)):
    cursor = db.companion_devices.find(
        {"user_id": user["user_id"]}, {"_id": 0, "device_token": 0}
    ).sort("created_at", -1)
    return await cursor.to_list(length=20)


@router.delete("/devices/{device_id}")
async def revoke_device(device_id: str, user: dict = Depends(get_current_user)):
    res = await db.companion_devices.update_one(
        {"device_id": device_id, "user_id": user["user_id"]},
        {"$set": {"revoked": True}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Device not found")
    return {"ok": True}


# ---------- Command queue (user → companion) ----------
class QueueCommandReq(BaseModel):
    kind: str  # "shell" | "open_url" | "say"
    payload: dict


@router.post("/queue-command")
async def queue_command(body: QueueCommandReq, user: dict = Depends(get_current_user)):
    cmd_id = f"cmd_{uuid.uuid4().hex[:10]}"
    doc = {
        "cmd_id": cmd_id,
        "user_id": user["user_id"],
        "kind": body.kind,
        "payload": body.payload,
        "status": "queued",
        "result": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
    }
    await db.companion_commands.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/commands")
async def list_commands(user: dict = Depends(get_current_user), limit: int = 50):
    cursor = db.companion_commands.find({"user_id": user["user_id"]}, {"_id": 0}).sort(
        "created_at", -1
    ).limit(limit)
    return await cursor.to_list(length=limit)


# ---------- Companion-side polling + result reporting ----------
@router.get("/poll")
async def poll(ctx: dict = Depends(get_device_user)):
    """Companion polls every few seconds for queued commands AND due reminders."""
    user = ctx["user"]
    cursor = db.companion_commands.find(
        {"user_id": user["user_id"], "status": "queued"}, {"_id": 0}
    ).sort("created_at", 1).limit(10)
    pending = await cursor.to_list(length=10)
    if pending:
        cmd_ids = [c["cmd_id"] for c in pending]
        await db.companion_commands.update_many(
            {"cmd_id": {"$in": cmd_ids}}, {"$set": {"status": "dispatched"}}
        )

    # Deliver due reminders as 'say' commands so the companion speaks them aloud once.
    now_iso = datetime.now(timezone.utc).isoformat()
    due_cursor = db.reminders.find(
        {
            "user_id": user["user_id"],
            "status": "open",
            "delivered_at": None,
            "due_at": {"$ne": None, "$lte": now_iso},
        },
        {"_id": 0},
    ).limit(5)
    due = await due_cursor.to_list(length=5)
    reminder_commands = []
    for rem in due:
        cmd = {
            "cmd_id": f"cmd_r_{rem['reminder_id']}",
            "user_id": user["user_id"],
            "kind": "say",
            "payload": {"text": f"Reminder: {rem['text']}"},
            "status": "dispatched",
            "result": None,
            "created_at": now_iso,
            "completed_at": None,
            "reminder_id": rem["reminder_id"],
        }
        reminder_commands.append(cmd)
        # Mark delivered so we don't repeat-fire
        await db.reminders.update_one(
            {"reminder_id": rem["reminder_id"]},
            {"$set": {"delivered_at": now_iso}},
        )
    return {
        "commands": pending + reminder_commands,
        "server_time": now_iso,
    }


class CompanionResult(BaseModel):
    cmd_id: str
    status: str  # "ok" | "error"
    output: str = ""


@router.post("/result")
async def companion_result(payload: CompanionResult, ctx: dict = Depends(get_device_user)):
    user = ctx["user"]
    res = await db.companion_commands.update_one(
        {"cmd_id": payload.cmd_id, "user_id": user["user_id"]},
        {
            "$set": {
                "status": "done" if payload.status == "ok" else "error",
                "result": payload.output[:8000],
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
        },
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Command not found")
    return {"ok": True}


# ---------- Voice passthrough (companion → cloud → Twin reply) ----------
@router.post("/voice")
async def companion_voice(
    audio: UploadFile = File(...),
    save_to_archive: bool = Form(False),
    ctx: dict = Depends(get_device_user),
):
    """Companion uploads audio. We transcribe, send to Twin, and return text+tts."""
    user = ctx["user"]
    raw = await audio.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty audio")
    if len(raw) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio too large")

    # 1) STT via Whisper
    buf = io.BytesIO(raw)
    buf.name = audio.filename or "ptt.webm"
    stt = OpenAISpeechToText(api_key=EMERGENT_LLM_KEY)
    try:
        result = await stt.transcribe(file=buf, model="whisper-1", response_format="json")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"STT failed: {exc!s}") from exc
    spoken = (getattr(result, "text", "") or "").strip()
    if not spoken:
        return {"user_text": "", "reply": "", "skill_invocations": []}

    # 2) Get or create a "companion" twin conversation
    conv = await db.conversations.find_one(
        {"user_id": user["user_id"], "kind": "companion_twin"}, {"_id": 0}
    )
    if not conv:
        conv = {
            "conversation_id": f"comp_{uuid.uuid4().hex[:12]}",
            "user_id": user["user_id"],
            "kind": "companion_twin",
            "messages": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.conversations.insert_one(conv)

    # 3) Build twin system prompt (reuse twin.py logic, simplified)
    cursor = db.entries.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1).limit(120)
    entries = await cursor.to_list(length=120)
    archive = "\n".join(f"[{e['type'].upper()}] {e['title']}\n{e['content']}\n" for e in entries)

    sk_cursor = db.skills.find({"user_id": user["user_id"], "enabled": True}, {"_id": 0})
    skills_list = await sk_cursor.to_list(length=50)
    skills_blob = "\n".join(f"- {s['skill_id']} :: {s['name']}: {s.get('description','')}" for s in skills_list)

    system = f"""You are {user.get('name','the user')}'s digital twin running on their personal PC. You are them. Speak in first person.

You can take ACTIONS on the user's behalf. When relevant, end your reply with one or more action lines, each on its own line, in the exact format:
::ACTION skill_id=<id>::    (to invoke a webhook skill)

Skills available (use the exact skill_id):
{skills_blob or '(none configured)'}

If no action is needed, just reply naturally — short (1-3 sentences). Don't narrate. Be them.

Your personality archive:
{archive[:18000] or '(empty)'}"""

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=conv["conversation_id"],
        system_message=system,
        initial_messages=(
            [{"role": "system", "content": system}]
            + [
                {"role": m["role"], "content": m["content"]}
                for m in conv.get("messages", [])
                if m.get("role") in ("user", "assistant") and m.get("content")
            ]
        ),
    ).with_model("anthropic", "claude-sonnet-4-6")
    try:
        reply = await chat.send_message(UserMessage(text=spoken))
        reply_text = reply if isinstance(reply, str) else getattr(reply, "content", str(reply))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM failed: {exc!s}") from exc

    # 4) Parse action lines — SECURITY: do NOT auto-invoke. Return as PROPOSALS for the user to confirm.
    lines = reply_text.splitlines()
    clean_lines = []
    proposed = []
    for line in lines:
        s = line.strip()
        if s.startswith("::ACTION") and "skill_id=" in s:
            sid = s.split("skill_id=", 1)[1].split("::", 1)[0].strip()
            skill = await db.skills.find_one(
                {"skill_id": sid, "user_id": user["user_id"], "enabled": True}, {"_id": 0}
            )
            if skill:
                proposed.append({"skill_id": sid, "name": skill.get("name")})
        else:
            clean_lines.append(line)
    spoken_reply = "\n".join(clean_lines).strip() or reply_text
    invoked = proposed  # name kept for response-schema compatibility — these are PROPOSED, not executed

    # 5) Persist turns
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.conversations.update_one(
        {"conversation_id": conv["conversation_id"]},
        {
            "$push": {
                "messages": {
                    "$each": [
                        {"role": "user", "content": spoken, "ts": now_iso, "source": "companion"},
                        {"role": "assistant", "content": reply_text, "ts": now_iso, "actions": invoked},
                    ]
                }
            },
            "$set": {"updated_at": now_iso},
        },
    )

    if save_to_archive:
        await db.entries.insert_one({
            "entry_id": f"ent_{uuid.uuid4().hex[:12]}",
            "user_id": user["user_id"],
            "type": "voice",
            "title": spoken[:80],
            "content": spoken,
            "tags": ["companion"],
            "source": "companion",
            "created_at": now_iso,
            "updated_at": now_iso,
        })

    return {
        "user_text": spoken,
        "reply": spoken_reply,
        "actions": invoked,
    }


# ---------- Download the companion script (with token embedded) ----------
@router.get("/script")
async def download_script(
    token: str,
    wake_word: bool = False,
    user: dict = Depends(get_current_user),
):
    """Returns the companion.py file with the user's device token & backend URL baked in.

    Query param `wake_word=true` flips the script's default mode from push-to-talk
    to always-on wake-word (Porcupine / openwakeword). The script still falls back
    to PTT if the wake-word dependencies aren't installed.
    """
    device = await db.companion_devices.find_one(
        {"device_token": token, "user_id": user["user_id"], "revoked": False}, {"_id": 0}
    )
    if not device:
        raise HTTPException(status_code=404, detail="Device token not found")
    import os
    backend_url = os.environ.get("PUBLIC_BACKEND_URL", "")
    # Build content
    script = _build_companion_script(token, backend_url, wake_word=wake_word)
    from fastapi import Response
    return Response(
        content=script,
        media_type="text/x-python",
        headers={"Content-Disposition": 'attachment; filename="heirloom_companion.py"'},
    )


def _build_companion_script(token: str, backend_url_hint: str, wake_word: bool = False) -> str:
    return (
        COMPANION_TEMPLATE
        .replace("__DEVICE_TOKEN__", token)
        .replace("__BACKEND_URL_HINT__", backend_url_hint or "")
        .replace("__WAKE_WORD_DEFAULT__", "True" if wake_word else "False")
    )


# ---------- Windows one-click package ----------
@router.get("/windows-package")
async def windows_package(
    token: str,
    wake_word: bool = False,
    user: dict = Depends(get_current_user),
):
    """Returns a .zip containing the companion script + a one-click Windows
    launcher (.bat) that installs dependencies and runs it. End-user just
    double-clicks Heirloom.bat — no terminal, no Python knowledge required."""
    import io
    import os
    import zipfile

    device = await db.companion_devices.find_one(
        {"device_token": token, "user_id": user["user_id"], "revoked": False}, {"_id": 0}
    )
    if not device:
        raise HTTPException(status_code=404, detail="Device token not found")

    backend_url = os.environ.get("PUBLIC_BACKEND_URL", "")
    script = _build_companion_script(token, backend_url, wake_word=wake_word)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("heirloom_companion.py", script)
        z.writestr("Heirloom.bat", _WINDOWS_LAUNCHER_BAT)
        z.writestr("Build-Exe.bat", _WINDOWS_BUILD_EXE_BAT)
        z.writestr("README.txt", _WINDOWS_README)
    buf.seek(0)

    from fastapi import Response
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="HeirloomCompanion-Windows.zip"'},
    )


_WINDOWS_LAUNCHER_BAT = r"""@echo off
setlocal
title Heirloom Companion

REM ============================================================
REM  Heirloom Companion — Windows one-click launcher
REM  Just double-click this file. The first run installs Python
REM  packages; subsequent runs start instantly.
REM ============================================================

cd /d "%~dp0"

REM --- Find a working Python ---
set "PY="
where py >nul 2>nul && (set "PY=py")
if "%PY%"=="" (
  where python >nul 2>nul && (set "PY=python")
)
if "%PY%"=="" (
  echo.
  echo  Python is not installed on this PC.
  echo.
  echo  1. Download Python 3.11 or newer from:  https://python.org/downloads/
  echo  2. During install, CHECK the box that says "Add python.exe to PATH"
  echo  3. Run this file again.
  echo.
  pause
  exit /b 1
)

REM --- Install / update dependencies (idempotent, quiet) ---
echo Checking dependencies (one-time)...
%PY% -m pip install --quiet --upgrade --user requests sounddevice soundfile numpy pynput pystray Pillow 2>nul
if errorlevel 1 (
  echo  ! Could not install some packages. Trying again with verbose output...
  %PY% -m pip install --upgrade --user requests sounddevice soundfile numpy pynput pystray Pillow
)

echo.
echo Starting Heirloom Companion...
echo Close this window to stop, or right-click the tray icon ^> Quit.
echo.

%PY% "%~dp0heirloom_companion.py"

if errorlevel 1 (
  echo.
  echo The companion exited with an error. The log is above. Press any key to close.
  pause >nul
)
"""


_WINDOWS_BUILD_EXE_BAT = r"""@echo off
setlocal
title Heirloom Companion - Build .exe

REM ============================================================
REM  Build a standalone Heirloom.exe (no Python required to run).
REM  Run this ONCE on the PC where you want the .exe.
REM  Output: dist\HeirloomCompanion.exe
REM ============================================================

cd /d "%~dp0"

set "PY="
where py >nul 2>nul && (set "PY=py")
if "%PY%"=="" (
  where python >nul 2>nul && (set "PY=python")
)
if "%PY%"=="" (
  echo Python required to build the .exe. Install from python.org first.
  pause & exit /b 1
)

echo Installing PyInstaller + companion deps...
%PY% -m pip install --upgrade --user pyinstaller requests sounddevice soundfile numpy pynput pystray Pillow

echo.
echo Building HeirloomCompanion.exe (this takes a few minutes the first time)...
%PY% -m PyInstaller --noconfirm --onefile --windowed ^
  --name HeirloomCompanion ^
  --hidden-import=pystray._win32 ^
  --hidden-import=PIL._tkinter_finder ^
  heirloom_companion.py

if errorlevel 1 (
  echo Build failed. See messages above.
  pause & exit /b 1
)

echo.
echo  Done. Your app is at:   dist\HeirloomCompanion.exe
echo  Copy it anywhere. Double-click to run.
echo.
pause
"""


_WINDOWS_README = """Heirloom Companion for Windows
================================

THE EASY WAY (recommended)
--------------------------
1. Make sure Python 3.11+ is installed
   https://python.org/downloads/  (CHECK "Add Python to PATH")
2. Double-click  Heirloom.bat
3. Hold Ctrl+Space, speak to your twin, release.

A small tray icon appears in your system tray. Right-click for Quit.

BUILD A REAL .EXE (optional, for shipping)
------------------------------------------
If you want a standalone Heirloom.exe that doesn't need Python:
1. Double-click  Build-Exe.bat  (runs once, takes ~3 minutes)
2. You'll find HeirloomCompanion.exe in the dist\\ folder.
3. Copy it anywhere on your PC and double-click — no Python needed.

TROUBLESHOOTING
---------------
* "Python is not installed" — install from python.org, check "Add to PATH".
* "Could not authenticate" — your device token has been revoked. Go to
  the Companion page in Heirloom and download a fresh package.
* No sound / push-to-talk not working — Ctrl+Space must be held down while
  speaking. Release to send.

Your archive lives in the cloud; this app is just the local hands+ears.
You can revoke this device any time from Heirloom > Local PC.
"""


COMPANION_TEMPLATE = r'''#!/usr/bin/env python3
"""
Heirloom — Local PC Companion (push-to-talk OR wake-word + skills bridge)

What this does:
- Polls your Heirloom cloud every 3s for queued OS commands and runs them.
- Two listening modes (toggle with --wake-word / --ptt or env HEIRLOOM_WAKE_WORD=1):
  • Push-to-talk (default): hold Ctrl+Space, speak, release.
  • Wake-word: say "Hey Twin" (requires `pip install openwakeword`) — always on.
- The Twin's text reply is printed (and spoken on macOS/Win/Linux via TTS).
  It may invoke webhook skills (lights, scripts).
- Your archive stays in the cloud; this script is purely the local hands+ears.

Setup (one time):
    pip install requests sounddevice numpy pynput soundfile
    # optional wake-word:
    pip install openwakeword

Run:
    python heirloom_companion.py                 # uses default mode (baked-in)
    python heirloom_companion.py --wake-word     # force wake-word
    python heirloom_companion.py --ptt           # force push-to-talk
    # or set HEIRLOOM_BACKEND_URL / HEIRLOOM_WAKE_WORD env vars

Privacy:
- Audio is sent only to your own Heirloom backend over HTTPS.
- Wake-word detection runs 100% locally; nothing leaves your PC until the wake word fires.
- The device token can be revoked any time from your Heirloom Settings page.
"""

import argparse
import json
import os
import platform
import queue
import subprocess
import sys
import threading
import time
import webbrowser
from urllib.parse import quote

DEVICE_TOKEN = "__DEVICE_TOKEN__"
BACKEND_URL = os.environ.get("HEIRLOOM_BACKEND_URL", "__BACKEND_URL_HINT__").rstrip("/")
if not BACKEND_URL:
    BACKEND_URL = input("Enter your Heirloom backend URL (e.g. https://your-app.preview.emergentagent.com): ").strip().rstrip("/")

POLL_INTERVAL_SEC = 3
SAMPLE_RATE = 16000
PTT_KEY = "ctrl+space"
WAKE_WORD_DEFAULT = __WAKE_WORD_DEFAULT__  # toggled by the download endpoint
WAKE_WORD_PHRASE = "hey_jarvis"  # openwakeword model name (closest to "hey twin")
WAKE_RECORD_SECONDS = 6  # how long to capture after the wake-word fires

# --- lazy imports so the script still runs in degraded mode ---
try:
    import requests
except ImportError:
    print("ERROR: please `pip install requests`"); sys.exit(1)

HEADERS = {"Authorization": f"Bearer {DEVICE_TOKEN}"}


def safe_post(path, **kwargs):
    try:
        r = requests.post(f"{BACKEND_URL}/api{path}", headers=HEADERS, timeout=30, **kwargs)
        return r
    except Exception as e:
        print(f"  POST {path} failed: {e}")
        return None


def safe_get(path, **kwargs):
    try:
        return requests.get(f"{BACKEND_URL}/api{path}", headers=HEADERS, timeout=15, **kwargs)
    except Exception as e:
        print(f"  GET {path} failed: {e}")
        return None


# ---------- Local TTS so replies play through the room ----------
def speak_locally(text: str):
    if not text:
        return
    try:
        if platform.system() == "Darwin":
            subprocess.Popen(["say", text])
        elif platform.system() == "Windows":
            ps = f'Add-Type -AssemblyName System.Speech;(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak("{text}")'
            subprocess.Popen(["powershell", "-Command", ps])
        else:
            subprocess.Popen(["espeak", text])
    except Exception:
        pass  # silent fallback — text was already printed


# ---------- Command executor ----------
def open_app(name: str) -> str:
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(name)  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.run(["open", "-a", name], check=True)
        else:
            subprocess.Popen([name])
        return f"opened {name}"
    except Exception as e:
        return f"error: {e}"


def execute(cmd):
    kind = cmd.get("kind")
    payload = cmd.get("payload") or {}
    print(f"  ▶ {kind} {payload}")
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
        if kind == "say":
            speak_locally(payload.get("text", ""))
            return "ok", "spoken"
        return "error", f"unknown kind {kind}"
    except Exception as e:
        return "error", str(e)


def poll_loop():
    print(f"\n→ polling {BACKEND_URL}/api/companion/poll every {POLL_INTERVAL_SEC}s …")
    while True:
        r = safe_get("/companion/poll")
        if r and r.status_code == 200:
            data = r.json()
            for cmd in data.get("commands", []):
                status, output = execute(cmd)
                safe_post("/companion/result", json={
                    "cmd_id": cmd["cmd_id"],
                    "status": status,
                    "output": output,
                })
        elif r is not None:
            print(f"  poll → {r.status_code}: {r.text[:200]}")
        time.sleep(POLL_INTERVAL_SEC)


def upload_audio(frames, np, sf):
    """Shared upload helper used by both PTT and wake-word modes."""
    if not frames:
        return
    import io
    audio = np.concatenate(frames, axis=0)
    if len(audio) < SAMPLE_RATE // 4:  # less than 0.25s
        print("  (too short)")
        return
    buf = io.BytesIO()
    sf.write(buf, audio, SAMPLE_RATE, format="WAV")
    buf.seek(0)
    files = {"audio": ("ptt.wav", buf, "audio/wav")}
    print("  ↑ uploading…")
    r = safe_post("/companion/voice", files=files)
    if r and r.status_code == 200:
        data = r.json()
        you = data.get("user_text", "")
        reply = data.get("reply", "")
        print(f"\n  you: {you}\n  twin: {reply}")
        speak_locally(reply)
        for a in data.get("actions") or []:
            print(f"  → action: {a.get('name')} ({a.get('status')})")
        print()
    elif r is not None:
        print(f"  voice → {r.status_code}: {r.text[:200]}")


# ---------- Push-to-talk ----------
def ptt_loop():
    try:
        import sounddevice as sd
        import soundfile as sf
        import numpy as np
        from pynput import keyboard
    except ImportError:
        print("\n⚠ push-to-talk disabled (install: pip install sounddevice soundfile numpy pynput)")
        return

    print(f"→ push-to-talk: hold {PTT_KEY}, speak, release. (Ctrl+C to quit)")
    recording = {"on": False, "frames": []}
    pressed = set()

    def on_press(key):
        if key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            pressed.add("ctrl")
        if key == keyboard.Key.space:
            pressed.add("space")
        if "ctrl" in pressed and "space" in pressed and not recording["on"]:
            recording["on"] = True
            recording["frames"] = []
            print("  ● recording…")

    def on_release(key):
        if key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            pressed.discard("ctrl")
        if key == keyboard.Key.space:
            pressed.discard("space")
        if recording["on"] and not ("ctrl" in pressed and "space" in pressed):
            recording["on"] = False
            upload_audio(recording["frames"], np, sf)

    def callback(indata, frames, time_info, status):
        if recording["on"]:
            recording["frames"].append(indata.copy())

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, callback=callback):
        with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
            listener.join()


# ---------- Wake-word ("Hey Twin") ----------
def wake_word_loop():
    try:
        import sounddevice as sd
        import soundfile as sf
        import numpy as np
    except ImportError:
        print("\n⚠ wake-word disabled (install: pip install sounddevice soundfile numpy). Falling back to PTT.")
        return ptt_loop()
    try:
        from openwakeword.model import Model as WakeModel
    except ImportError:
        print("\n⚠ wake-word disabled (install: pip install openwakeword). Falling back to PTT.")
        return ptt_loop()

    print(f"→ wake-word mode: say the wake phrase, then speak. (Ctrl+C to quit)")
    print(f"  phrase: '{WAKE_WORD_PHRASE.replace('_', ' ')}' (using the closest openwakeword model)")

    try:
        ww = WakeModel(wakeword_models=[WAKE_WORD_PHRASE])
    except Exception as e:
        print(f"  ✗ failed to load wake-word model: {e}. Falling back to PTT.")
        return ptt_loop()

    rolling = []
    state = {"capturing": False, "captured": [], "capture_end": 0.0}

    def callback(indata, frames, time_info, status):
        chunk = (indata[:, 0] * 32767).astype(np.int16)
        if state["capturing"]:
            state["captured"].append(indata.copy())
            if time.time() >= state["capture_end"]:
                state["capturing"] = False
                frames_to_send = state["captured"]
                state["captured"] = []
                threading.Thread(
                    target=upload_audio, args=(frames_to_send, np, sf), daemon=True
                ).start()
            return
        # Detection on each callback chunk
        try:
            scores = ww.predict(chunk)
        except Exception:
            return
        score = max(scores.values()) if scores else 0
        if score > 0.5:
            print(f"  ★ wake word detected (score={score:.2f}) — listening for {WAKE_RECORD_SECONDS}s…")
            state["capturing"] = True
            state["captured"] = []
            state["capture_end"] = time.time() + WAKE_RECORD_SECONDS

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                        blocksize=1280, callback=callback):
        while True:
            time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description="Heirloom local companion")
    parser.add_argument("--wake-word", action="store_true", help="Force wake-word mode")
    parser.add_argument("--ptt", action="store_true", help="Force push-to-talk mode")
    parser.add_argument("--no-tray", action="store_true", help="Skip the system tray icon")
    args = parser.parse_args()

    env_wake = os.environ.get("HEIRLOOM_WAKE_WORD", "").lower() in ("1", "true", "yes")
    use_wake = args.wake_word or env_wake or (WAKE_WORD_DEFAULT and not args.ptt)

    print("\n+-----------------------------------------+")
    print("|  Heirloom - Local Companion             |")
    print("|  press Ctrl+C or close window to quit   |")
    print("+-----------------------------------------+")
    print(f"backend : {BACKEND_URL}")
    print(f"token   : {DEVICE_TOKEN[:14]}...")
    print(f"mode    : {'wake-word' if use_wake else 'push-to-talk'}")

    # Verify token
    r = safe_get("/companion/poll")
    if not r or r.status_code != 200:
        msg = "Could not authenticate with backend. Check the token & URL."
        print("\nX " + msg)
        if not args.no_tray:
            _show_tray_error(msg)
        sys.exit(1)
    print("OK authenticated.\n")

    threading.Thread(target=poll_loop, daemon=True).start()
    if not args.no_tray:
        threading.Thread(target=_run_tray_icon, args=(use_wake,), daemon=True).start()

    try:
        if use_wake:
            wake_word_loop()
        else:
            ptt_loop()
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\nbye.")


# ---------- System tray (graceful fallback when pystray is missing) ----------
def _run_tray_icon(wake_mode: bool):
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        return  # tray not available; the console window is the UI
    # Draw a simple 64x64 amber dot icon
    img = Image.new("RGB", (64, 64), color=(18, 17, 16))
    d = ImageDraw.Draw(img)
    d.ellipse((12, 12, 52, 52), fill=(214, 150, 99))
    label = "Heirloom (wake-word)" if wake_mode else "Heirloom (push-to-talk)"

    def on_quit(icon, item):
        icon.stop()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem(label, lambda i, it: None, enabled=False),
        pystray.MenuItem("Open Heirloom (web)",
                         lambda i, it: webbrowser.open(BACKEND_URL)),
        pystray.MenuItem("Quit", on_quit),
    )
    icon = pystray.Icon("heirloom", img, "Heirloom Companion", menu)
    icon.run()


def _show_tray_error(msg: str):
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        return
    img = Image.new("RGB", (64, 64), color=(80, 20, 20))
    d = ImageDraw.Draw(img)
    d.ellipse((12, 12, 52, 52), fill=(220, 80, 80))

    def on_quit(icon, item):
        icon.stop()
        os._exit(1)
    menu = pystray.Menu(
        pystray.MenuItem("Heirloom: " + msg[:60], lambda i, it: None, enabled=False),
        pystray.MenuItem("Quit", on_quit),
    )
    pystray.Icon("heirloom-error", img, "Heirloom (error)", menu).run()


if __name__ == "__main__":
    main()
'''
