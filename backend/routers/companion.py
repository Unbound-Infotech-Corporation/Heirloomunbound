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
    """Companion polls every few seconds for queued commands."""
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
    return {"commands": pending, "server_time": datetime.now(timezone.utc).isoformat()}


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
    ).with_model("anthropic", "claude-sonnet-4-6")
    try:
        reply = await chat.send_message(UserMessage(text=spoken))
        reply_text = reply if isinstance(reply, str) else getattr(reply, "content", str(reply))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM failed: {exc!s}") from exc

    # 4) Parse action lines
    lines = reply_text.splitlines()
    clean_lines = []
    invoked = []
    for line in lines:
        s = line.strip()
        if s.startswith("::ACTION") and "skill_id=" in s:
            sid = s.split("skill_id=", 1)[1].split("::", 1)[0].strip()
            skill = await db.skills.find_one(
                {"skill_id": sid, "user_id": user["user_id"], "enabled": True}, {"_id": 0}
            )
            if skill:
                invoked.append({"skill_id": sid, "name": skill.get("name")})
                # Queue invocation by hitting it inline (best-effort)
                try:
                    import httpx
                    async with httpx.AsyncClient(timeout=10.0) as h:
                        r = await h.request(
                            skill.get("method", "POST"),
                            skill["webhook_url"],
                            headers=skill.get("headers") or {},
                            content=skill.get("body_template") or None,
                        )
                    invoked[-1]["status"] = r.status_code
                except Exception as exc:  # noqa: BLE001
                    invoked[-1]["status"] = 0
                    invoked[-1]["error"] = str(exc)
        else:
            clean_lines.append(line)
    spoken_reply = "\n".join(clean_lines).strip() or reply_text

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
async def download_script(token: str, user: dict = Depends(get_current_user)):
    """Returns the companion.py file with the user's device token & backend URL baked in."""
    device = await db.companion_devices.find_one(
        {"device_token": token, "user_id": user["user_id"], "revoked": False}, {"_id": 0}
    )
    if not device:
        raise HTTPException(status_code=404, detail="Device token not found")
    import os
    backend_url = os.environ.get("PUBLIC_BACKEND_URL", "")
    # Build content
    script = _build_companion_script(token, backend_url)
    from fastapi import Response
    return Response(
        content=script,
        media_type="text/x-python",
        headers={"Content-Disposition": 'attachment; filename="heirloom_companion.py"'},
    )


def _build_companion_script(token: str, backend_url_hint: str) -> str:
    return COMPANION_TEMPLATE.replace("__DEVICE_TOKEN__", token).replace(
        "__BACKEND_URL_HINT__", backend_url_hint or ""
    )


COMPANION_TEMPLATE = r'''#!/usr/bin/env python3
"""
Heirloom — Local PC Companion (push-to-talk + skills bridge)

What this does:
- Polls your Heirloom cloud every 3s for queued OS commands and runs them.
- Push-to-talk: hold Ctrl+Space, speak, release. Audio is sent to your Twin in the cloud.
- The Twin's text reply is printed, and it may invoke webhook skills (lights, scripts).
- Your archive stays in the cloud; this script is purely the local hands+ears.

Setup (one time):
    pip install requests sounddevice numpy pynput soundfile

Run:
    python heirloom_companion.py
    # or set HEIRLOOM_BACKEND_URL env var to override the baked-in URL

Privacy:
- Audio is sent only to your own Heirloom backend over HTTPS.
- The device token can be revoked any time from your Heirloom Settings page.
"""

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
            text = payload.get("text", "")
            if platform.system() == "Darwin":
                subprocess.run(["say", text])
            elif platform.system() == "Windows":
                ps = f'Add-Type -AssemblyName System.Speech;(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak("{text}")'
                subprocess.run(["powershell", "-Command", ps])
            else:
                subprocess.run(["espeak", text])
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
            send_audio(recording["frames"])

    def send_audio(frames):
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
            print(f"\n  you: {data.get('user_text','')}\n  twin: {data.get('reply','')}")
            for a in data.get("actions") or []:
                print(f"  → action: {a.get('name')} ({a.get('status')})")
            print()
        elif r is not None:
            print(f"  voice → {r.status_code}: {r.text[:200]}")

    def callback(indata, frames, time_info, status):
        if recording["on"]:
            recording["frames"].append(indata.copy())

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, callback=callback):
        with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
            listener.join()


def main():
    print("\n╭─────────────────────────────────────────╮")
    print("│  Heirloom — Local Companion             │")
    print("│  press Ctrl+C to quit                   │")
    print("╰─────────────────────────────────────────╯")
    print(f"backend: {BACKEND_URL}")
    print(f"token  : {DEVICE_TOKEN[:14]}…")

    # Verify token
    r = safe_get("/companion/poll")
    if not r or r.status_code != 200:
        print("\n❌ Could not authenticate with backend. Check the token & URL.")
        sys.exit(1)
    print("✓ authenticated.\n")

    threading.Thread(target=poll_loop, daemon=True).start()
    try:
        ptt_loop()
        # If PTT not available, just keep polling
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\nbye.")


if __name__ == "__main__":
    main()
'''
