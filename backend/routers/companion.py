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
        "script_version": COMPANION_SCRIPT_VERSION,
    }


COMPANION_SCRIPT_VERSION = "2026.02.27.1"  # bump whenever _build_companion_script materially changes


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


@router.get("/public-script")
async def public_download_script(token: str, wake_word: bool = False):
    """Public variant of /script — used by the one-click Windows installer.

    The .bat installer runs on the user's PC and has no browser session, so it
    authenticates with the device_token alone. The token IS the credential
    (random 256-bit), and possessing it already authorizes commands, so reading
    the script is no escalation.
    """
    device = await db.companion_devices.find_one(
        {"device_token": token, "revoked": False}, {"_id": 0}
    )
    if not device:
        raise HTTPException(status_code=404, detail="Device token not found or revoked")
    import os
    backend_url = os.environ.get("PUBLIC_BACKEND_URL", "")
    script = _build_companion_script(token, backend_url, wake_word=wake_word)
    from fastapi import Response
    return Response(
        content=script,
        media_type="text/x-python",
        headers={"Content-Disposition": 'attachment; filename="heirloom_companion.py"'},
    )


@router.get("/easy-installer")
async def easy_installer(
    token: str,
    wake_word: bool = False,
    user: dict = Depends(get_current_user),
):
    """Returns a single self-contained .bat file that does EVERYTHING in one click:

    1. Silently installs Python 3.12 via winget if missing (Win 10 1809+/Win 11).
    2. Downloads the personalized companion script from /api/companion/public-script.
    3. pip-installs deps to user-site (no admin).
    4. Drops a VBS launcher to run the script HIDDEN (no flashing console).
    5. Adds a Startup-folder shortcut → auto-starts on every Windows login.
    6. Launches it immediately.

    End-user double-clicks → ~60s of silent install → tray icon appears → done.
    """
    device = await db.companion_devices.find_one(
        {"device_token": token, "user_id": user["user_id"], "revoked": False}, {"_id": 0}
    )
    if not device:
        raise HTTPException(status_code=404, detail="Device token not found")

    import os
    backend_url = os.environ.get("PUBLIC_BACKEND_URL", "").rstrip("/")
    if not backend_url:
        raise HTTPException(status_code=500, detail="PUBLIC_BACKEND_URL not configured")

    bat = (
        _WINDOWS_EASY_INSTALLER_BAT
        .replace("__BACKEND_URL__", backend_url)
        .replace("__DEVICE_TOKEN__", token)
        .replace("__WAKE_WORD__", "true" if wake_word else "false")
    )
    from fastapi import Response
    return Response(
        content=bat,
        media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="HeirloomInstall.bat"'},
    )


def _build_companion_script(token: str, backend_url_hint: str, wake_word: bool = False) -> str:
    return (
        COMPANION_TEMPLATE
        .replace("__DEVICE_TOKEN__", token)
        .replace("__BACKEND_URL_HINT__", backend_url_hint or "")
        .replace("__WAKE_WORD_DEFAULT__", "True" if wake_word else "False")
        .replace("__SCRIPT_VERSION__", COMPANION_SCRIPT_VERSION)
    )


# ---------- Windows one-click package ----------
def build_windows_zip_bytes(token: str, wake_word: bool = False) -> bytes:
    """Reusable helper — returns the in-memory bytes of the personalized
    Windows .zip package for `token`. Used by /windows-package and by the
    public /download/{download_token} endpoint after a successful purchase."""
    import io
    import os
    import zipfile

    backend_url = os.environ.get("PUBLIC_BACKEND_URL", "")
    script = _build_companion_script(token, backend_url, wake_word=wake_word)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("heirloom_companion.py", script)
        z.writestr("Heirloom.bat", _WINDOWS_LAUNCHER_BAT)
        z.writestr("Build-Exe.bat", _WINDOWS_BUILD_EXE_BAT)
        z.writestr("make_icon.py", _MAKE_ICON_PY)
        z.writestr("version_info.txt", _VERSION_INFO_TXT)
        z.writestr("Sign-Exe.bat", _SIGN_EXE_BAT)
        z.writestr("README.txt", _WINDOWS_README)
    return buf.getvalue()


@router.get("/windows-package")
async def windows_package(
    token: str,
    wake_word: bool = False,
    user: dict = Depends(get_current_user),
):
    """Returns a .zip containing the companion script + a one-click Windows
    launcher (.bat) that installs dependencies and runs it. End-user just
    double-clicks Heirloom.bat — no terminal, no Python knowledge required."""
    device = await db.companion_devices.find_one(
        {"device_token": token, "user_id": user["user_id"], "revoked": False}, {"_id": 0}
    )
    if not device:
        raise HTTPException(status_code=404, detail="Device token not found")

    payload = build_windows_zip_bytes(token, wake_word=wake_word)

    from fastapi import Response
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="HeirloomCompanion-Windows.zip"'},
    )


_WINDOWS_EASY_INSTALLER_BAT = r"""@echo off
setlocal EnableDelayedExpansion
title Heirloom Companion - Easy install
mode con: cols=72 lines=24

echo.
echo               -- Heirloom Companion: Easy install --
echo  --------------------------------------------------------------
echo.
echo   This will:
echo     * Install Python ^(silent, only if missing^)
echo     * Drop the companion at:  %%LOCALAPPDATA%%\Heirloom
echo     * Start automatically every time you sign in to Windows
echo     * Run hidden in the background ^(look for the tray icon^)
echo.
echo   ~60 seconds. Press any key to begin, or close to cancel.
echo.
pause >nul

set "INSTALL_DIR=%LOCALAPPDATA%\Heirloom"
set "BACKEND_URL=__BACKEND_URL__"
set "DEVICE_TOKEN=__DEVICE_TOKEN__"
set "WAKE_WORD=__WAKE_WORD__"

if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%" >nul 2>&1

echo  [1/5] Checking Python...
set "PY="
where py >nul 2>nul && set "PY=py"
if "%PY%"=="" ( where python >nul 2>nul && set "PY=python" )

if "%PY%"=="" (
  echo        Not found. Installing silently via winget ^(~30s^)...
  where winget >nul 2>nul
  if errorlevel 1 (
    echo.
    echo   X  Your Windows is older than 10 ver. 1809 ^(no winget^).
    echo      Please install Python 3.11+ from https://python.org/downloads
    echo      then re-run this installer.
    echo.
    pause
    exit /b 1
  )
  winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements >nul 2>&1
  for /f "delims=" %%i in ('dir /b /s "%LOCALAPPDATA%\Programs\Python\python.exe" 2^>nul') do set "PY=%%i"
  if "!PY!"=="" (
    echo.
    echo   X  Python install did not complete. Open https://python.org/downloads
    echo      install manually, then re-run this installer.
    pause
    exit /b 1
  )
)

echo        ok.
echo  [2/5] Downloading the companion script...
set "SCRIPT_URL=%BACKEND_URL%/api/companion/public-script?token=%DEVICE_TOKEN%&wake_word=%WAKE_WORD%"
curl -sS -L --fail "%SCRIPT_URL%" -o "%INSTALL_DIR%\heirloom_companion.py"
if errorlevel 1 (
  echo.
  echo   X  Could not download from %BACKEND_URL%
  echo      Check your internet connection and try again. If it still fails,
  echo      your device token may have been revoked - go back to the
  echo      Heirloom website, revoke the device and issue a fresh token.
  pause
  exit /b 1
)

echo        ok.
echo  [3/5] Installing Python packages ^(may take 30-60s the first time^)...
"%PY%" -m pip install --quiet --disable-pip-version-check --upgrade --user requests sounddevice soundfile numpy pynput pystray Pillow >nul 2>&1
if /i "%WAKE_WORD%"=="true" (
  echo        + wake-word engine...
  "%PY%" -m pip install --quiet --disable-pip-version-check --upgrade --user openwakeword >nul 2>&1
)

echo        ok.
echo  [4/5] Creating hidden launcher + Startup shortcut...

REM Build the VBS launcher: runs python totally hidden (no flashing console).
REM We use Chr(34) inside VBS for quote chars, so the .bat doesn't need triple quotes.
> "%INSTALL_DIR%\HeirloomCompanion.vbs" echo Set WS = CreateObject^("WScript.Shell"^)
>> "%INSTALL_DIR%\HeirloomCompanion.vbs" echo WS.Run Chr^(34^) ^& "%PY%" ^& Chr^(34^) ^& " " ^& Chr^(34^) ^& "%INSTALL_DIR%\heirloom_companion.py" ^& Chr^(34^), 0, False

REM Create / refresh shortcut in the Startup folder
set "SC=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Heirloom Companion.lnk"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$WshShell = New-Object -ComObject WScript.Shell;" ^
  "$s = $WshShell.CreateShortcut('%SC%');" ^
  "$s.TargetPath = '%INSTALL_DIR%\HeirloomCompanion.vbs';" ^
  "$s.WorkingDirectory = '%INSTALL_DIR%';" ^
  "$s.WindowStyle = 7;" ^
  "$s.Description = 'Heirloom Companion - your AI twin, listening locally';" ^
  "$s.Save();" >nul 2>&1

echo        ok.
echo  [5/5] Launching now...
start "" wscript.exe "%INSTALL_DIR%\HeirloomCompanion.vbs"

echo.
echo  ==============================================================
echo    Heirloom is now running. Look for the tray icon near the
echo    clock ^(bottom-right of your screen^).
echo.
echo    It will auto-start every time you sign in.
echo    To stop: right-click the tray icon then Quit.
echo    To remove: delete  %INSTALL_DIR%
echo               and  "Heirloom Companion.lnk" from your Startup folder.
echo  ==============================================================
echo.
echo  This window closes in 8 seconds.
ping -n 9 127.0.0.1 >nul
exit /b 0
"""


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
setlocal EnableDelayedExpansion
title Heirloom Companion - Build .exe

REM ============================================================
REM  Heirloom Companion -- Build a sellable Windows executable
REM
REM  What this does:
REM   1. Generates an app icon (heirloom.ico) using Pillow.
REM   2. Bundles heirloom_companion.py into ONE single-file .exe
REM      using PyInstaller, with proper Windows file metadata
REM      (Unbound Infotech, version, product name, icon).
REM   3. Output:  dist\HeirloomCompanion.exe
REM
REM  Run this ONCE on the PC where you want the .exe.
REM  Subsequent rebuilds are much faster.
REM ============================================================

cd /d "%~dp0"

echo.
echo  [1/4] Locating Python...
set "PY="
where py >nul 2>nul && (set "PY=py")
if "!PY!"=="" (
  where python >nul 2>nul && (set "PY=python")
)
if "!PY!"=="" (
  echo  X  Python is not installed.
  echo     Install Python 3.11+ from https://python.org/downloads/
  echo     and check the "Add Python to PATH" box during install.
  pause & exit /b 1
)
echo      Using: !PY!

echo.
echo  [2/4] Installing build dependencies (one-time, ~1 minute)...
!PY! -m pip install --quiet --upgrade --user pyinstaller pillow requests sounddevice soundfile numpy pynput pystray
if errorlevel 1 (
  echo      Retrying with verbose output...
  !PY! -m pip install --upgrade --user pyinstaller pillow requests sounddevice soundfile numpy pynput pystray
  if errorlevel 1 (
    echo  X  Could not install dependencies. Check your internet connection.
    pause & exit /b 1
  )
)

echo.
echo  [3/4] Generating app icon (heirloom.ico)...
!PY! "%~dp0make_icon.py"
if not exist "%~dp0heirloom.ico" (
  echo  !  Icon generation failed; building without a custom icon.
  set "ICON_FLAG="
) else (
  set "ICON_FLAG=--icon=heirloom.ico"
)

echo.
echo  [4/4] Building HeirloomCompanion.exe (takes 2-4 minutes the first time)...
echo      You can step away. The exe will appear in:  dist\HeirloomCompanion.exe
echo.

REM Clean previous builds so re-runs are deterministic
if exist build rmdir /s /q build 2>nul
if exist dist  rmdir /s /q dist  2>nul
if exist HeirloomCompanion.spec del HeirloomCompanion.spec 2>nul

!PY! -m PyInstaller ^
  --noconfirm ^
  --onefile ^
  --windowed ^
  --name HeirloomCompanion ^
  !ICON_FLAG! ^
  --version-file=version_info.txt ^
  --hidden-import=pystray._win32 ^
  --hidden-import=PIL._tkinter_finder ^
  --hidden-import=sounddevice ^
  --hidden-import=soundfile ^
  --hidden-import=pynput.keyboard._win32 ^
  --hidden-import=pynput.mouse._win32 ^
  --collect-data=sounddevice ^
  --collect-data=soundfile ^
  heirloom_companion.py

if errorlevel 1 (
  echo.
  echo  X  Build failed. See messages above.
  pause & exit /b 1
)

if not exist "dist\HeirloomCompanion.exe" (
  echo  X  Build appeared to succeed but no .exe found. See PyInstaller log above.
  pause & exit /b 1
)

echo.
echo  =================================================================
echo   DONE.
echo.
echo   Your app:  %CD%\dist\HeirloomCompanion.exe
echo.
echo   Copy it anywhere -- double-click to run. No Python required.
echo   To sign it for distribution: see Sign-Exe.bat (optional).
echo  =================================================================
echo.
explorer "%CD%\dist"
pause
"""


_MAKE_ICON_PY = '''"""Generates heirloom.ico -- a multi-resolution Windows icon.
Bundled with the Build-Exe package so users don\'t need a designer.

Brand: Heirloom by Unbound Infotech.
Design: an embossed amber "H" monogram on charcoal, framed by a thin
amber ring (a seal motif). Rendered at 4x then downsampled with LANCZOS
so edges stay crisp at every size from taskbar (16px) to Start menu (256px).
"""
from PIL import Image, ImageDraw

SIZES = [16, 32, 48, 64, 128, 256]
BG = (18, 17, 16, 255)          # charcoal
ACCENT = (214, 150, 99, 255)    # amber
RING = (214, 150, 99, 160)      # softer amber halo


def _draw(d, w, h, scale):
    """Draw the icon at canvas size w x h. All coords are float for AA."""
    cx, cy = w / 2.0, h / 2.0

    # Thin outer "seal" ring
    ring_r = min(w, h) * 0.46
    ring_thickness = max(1.0, w * 0.012)
    d.ellipse(
        (cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r),
        outline=RING,
        width=int(round(ring_thickness)),
    )

    # H monogram (drawn geometrically so we never depend on system fonts)
    h_w = w * 0.46          # total width of the H
    h_h = h * 0.56          # total height
    stroke = w * 0.095      # vertical stroke width
    cross_h = h * 0.085     # crossbar height

    left = cx - h_w / 2.0
    right = cx + h_w / 2.0
    top = cy - h_h / 2.0
    bot = cy + h_h / 2.0

    # Left vertical stroke
    d.rectangle((left, top, left + stroke, bot), fill=ACCENT)
    # Right vertical stroke
    d.rectangle((right - stroke, top, right, bot), fill=ACCENT)
    # Crossbar (sits slightly above center for a classical serif feel)
    cross_y = cy - cross_h * 0.65
    d.rectangle((left, cross_y, right, cross_y + cross_h), fill=ACCENT)


def render(size):
    """Render at 4x resolution then LANCZOS-downscale -- gives crisp AA."""
    scale = 4
    big = size * scale
    img = Image.new("RGBA", (big, big), BG)
    d = ImageDraw.Draw(img, "RGBA")
    _draw(d, big, big, scale)
    return img.resize((size, size), Image.LANCZOS)


def main():
    # Start from the 256 px master, let PIL include all sizes in the .ico
    big = render(256)
    big.save(
        "heirloom.ico",
        format="ICO",
        sizes=[(s, s) for s in SIZES],
    )
    print("Wrote heirloom.ico (", ", ".join(f"{s}x{s}" for s in SIZES), ")")


if __name__ == "__main__":
    main()
'''


# PyInstaller version metadata. This is what Windows displays in
# Right-click -> Properties -> Details on the .exe.
_VERSION_INFO_TXT = r"""# UTF-8
#
# For more details about fixed file info 'ffi' see:
# http://msdn.microsoft.com/en-us/library/ms646997.aspx
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=(1, 0, 0, 0),
    prodvers=(1, 0, 0, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        u'040904B0',
        [StringStruct(u'CompanyName', u'Unbound Infotech'),
        StringStruct(u'FileDescription', u'Heirloom Companion -- local twin'),
        StringStruct(u'FileVersion', u'1.0.0.0'),
        StringStruct(u'InternalName', u'HeirloomCompanion'),
        StringStruct(u'LegalCopyright', u'(c) Unbound Infotech. All rights reserved.'),
        StringStruct(u'OriginalFilename', u'HeirloomCompanion.exe'),
        StringStruct(u'ProductName', u'Heirloom Companion'),
        StringStruct(u'ProductVersion', u'1.0.0.0')])
      ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"""


# Optional: code-sign the exe if the user buys a Windows code-signing certificate later.
_SIGN_EXE_BAT = r"""@echo off
setlocal
title Heirloom Companion - Sign .exe (optional)

REM ============================================================
REM  Code-sign HeirloomCompanion.exe so Windows SmartScreen and
REM  customer antivirus won't scare buyers with warnings.
REM
REM  Requires:
REM   - A Windows code-signing certificate (.pfx file).
REM     Buy from: SSL.com, Sectigo, DigiCert, GoDaddy. ~$70-300/yr.
REM   - signtool.exe (comes with the Windows SDK).
REM
REM  Then run:   Sign-Exe.bat  path\to\cert.pfx  YOUR_PFX_PASSWORD
REM ============================================================

set "EXE=%~dp0dist\HeirloomCompanion.exe"
if not exist "%EXE%" (
  echo  X  No exe found at %EXE% -- run Build-Exe.bat first.
  pause & exit /b 1
)

if "%~1"=="" (
  echo  Usage: Sign-Exe.bat  path\to\cert.pfx  PFX_PASSWORD
  echo.
  echo  If you don't have a cert yet, buy one from SSL.com or Sectigo.
  echo  Until then, ship the unsigned exe; users will see one extra
  echo  SmartScreen warning until reputation builds up.
  pause & exit /b 0
)

where signtool >nul 2>nul
if errorlevel 1 (
  echo  X  signtool.exe not found. Install the Windows SDK from:
  echo     https://developer.microsoft.com/windows/downloads/windows-sdk/
  pause & exit /b 1
)

signtool sign /fd SHA256 /f "%~1" /p "%~2" /tr http://timestamp.digicert.com /td SHA256 "%EXE%"
if errorlevel 1 (
  echo  X  Signing failed.
  pause & exit /b 1
)

echo.
echo  Signed successfully.
echo  Verifying...
signtool verify /pa "%EXE%"
pause
"""


_WINDOWS_README = """Heirloom Companion for Windows
================================

THE EASY WAY (recommended for personal use)
-------------------------------------------
1. Install Python 3.11+ from https://python.org/downloads/
   CHECK the box that says "Add Python to PATH" during install.
2. Double-click  Heirloom.bat
3. Hold Ctrl+Space, speak to your twin, release.

A small tray icon appears in the Windows system tray.
Right-click it for Quit.

BUILD A REAL .EXE (for distribution / selling)
----------------------------------------------
If you want a standalone HeirloomCompanion.exe -- the kind you can
hand to a customer who has never heard of Python:

1. Double-click  Build-Exe.bat
   (takes ~3 minutes the first time -- it bundles Python + all libs
   + the audio drivers into a single ~25 MB .exe)
2. The finished app appears at:  dist\\HeirloomCompanion.exe
3. Right-click that .exe -> Properties -> Details. You'll see proper
   Windows metadata: Company "Unbound Infotech", Product "Heirloom
   Companion", version 1.0.0.0, and your custom amber icon.
4. Copy that single .exe anywhere. Double-click to run -- no Python
   install needed on the target PC. That's the file you sell.

CODE-SIGN THE .EXE (optional, recommended for selling)
------------------------------------------------------
Unsigned exes trigger SmartScreen warnings on customer PCs ("Windows
protected your PC"). To remove that:
1. Buy a Windows code-signing certificate (~$70-300/yr from SSL.com,
   Sectigo, GoDaddy, DigiCert). Get a .pfx file.
2. Install the Windows SDK (gives you signtool.exe).
3. Run:  Sign-Exe.bat  path\\to\\cert.pfx  YOUR_PFX_PASSWORD
4. Your exe now signs cleanly. Reputation builds with downloads.

TROUBLESHOOTING
---------------
* "Python is not installed" -- install from python.org, check "Add to PATH".
* "Could not authenticate" -- your device token was revoked. Go to the
  Companion page in Heirloom and re-issue a token (download a new zip).
* No microphone -- Windows Settings > Privacy > Microphone, allow
  desktop apps.
* Push-to-talk not working -- hold Ctrl+Space WHILE speaking, then
  release to send.

Your archive lives in the cloud at Heirloom. This .exe is just the
local hands+ears (mic + speaker + OS commands). The device token can be
revoked any time from Heirloom > Local PC.
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
SCRIPT_VERSION = "__SCRIPT_VERSION__"  # bumped by the server when a new build ships
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


def _check_and_self_update(server_version):
    """If the server reports a newer script version, re-download ourselves
    and exit. The Windows VBS launcher (or the user's `Heirloom.bat`) will
    restart us within seconds on the next sign-in / boot — but we also
    spawn a tiny re-exec so the new code starts immediately.
    """
    if not server_version or not SCRIPT_VERSION or server_version == SCRIPT_VERSION:
        return
    print(f"\n↻ Companion update available: {SCRIPT_VERSION} → {server_version}. Downloading…")
    try:
        url = f"{BACKEND_URL}/api/companion/public-script?token={DEVICE_TOKEN}"
        r = requests.get(url, timeout=30)
        if r.status_code != 200 or len(r.content) < 1000:
            print(f"  update fetch failed ({r.status_code})")
            return
        import sys
        my_path = os.path.abspath(__file__)
        backup = my_path + ".bak"
        try:
            os.replace(my_path, backup)
        except Exception:
            pass
        with open(my_path, "wb") as f:
            f.write(r.content)
        print(f"  → wrote new script to {my_path}. Restarting…")
        # Re-exec via the same Python interpreter
        os.execv(sys.executable, [sys.executable, my_path])
    except Exception as exc:
        print(f"  self-update failed: {exc}")


def poll_loop():
    print(f"\n→ polling {BACKEND_URL}/api/companion/poll every {POLL_INTERVAL_SEC}s …")
    print(f"  script version: {SCRIPT_VERSION}")
    while True:
        r = safe_get("/companion/poll")
        if r and r.status_code == 200:
            data = r.json()
            _check_and_self_update(data.get("script_version"))
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
