"""Run one Assist-live poll through twin_runtime, then optional local speech.

No cloud client is constructed here. Speech is Chatterbox on loopback, or
a caption when that service is down.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from time import time
from typing import Any, Optional

from assist_live import (
    advance_state,
    load_state,
    loopback_speak_wav_url,
    public_view,
    save_state,
)
from memorial_mode import memorial_from_user


def fetch_chatterbox_wav(text: str, *, url: Optional[str] = None, timeout: float = 3.0) -> bytes | None:
    phrase = " ".join((text or "").split())
    if not phrase:
        return None
    target = loopback_speak_wav_url(url)
    body = json.dumps({"text": phrase[:500]}).encode("utf-8")
    request = urllib.request.Request(
        target,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "audio/wav"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except (OSError, urllib.error.URLError, TimeoutError, ValueError):
        return None
    if payload[:4] == b"RIFF":
        return payload
    return None


def _audio_dir(root: Path) -> Path:
    folder = Path(root) / "assist-speak"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def store_wav(root: Path, audio_id: str, wav: bytes) -> None:
    folder = _audio_dir(root)
    for old in folder.glob("*.wav"):
        try:
            old.unlink()
        except OSError:
            continue
    (folder / f"{audio_id}.wav").write_bytes(wav)


def take_wav(root: Path, audio_id: str) -> bytes | None:
    path = _audio_dir(root) / f"{audio_id}.wav"
    try:
        payload = path.read_bytes()
    except OSError:
        return None
    try:
        path.unlink()
    except OSError:
        pass
    state = load_state(root)
    if state.get("audio_id") == audio_id:
        state["audio_id"] = ""
        save_state(state, root)
    return payload


async def advance_for_user(
    user: dict,
    *,
    clicked_id: str = "",
    declined_id: str = "",
    root: Path | None = None,
    now: float | None = None,
    turn: Any = None,
    execute: Any = None,
    speak: Any = None,
) -> dict[str, Any]:
    from box_pause import merged_state
    from observer_store import ObserverStore, observer_dir

    folder = Path(root) if root is not None else observer_dir()
    moment = time() if now is None else float(now)
    try:
        paused = bool(merged_state(ObserverStore(folder).read_state()).get("paused"))
    except OSError:
        paused = False
    state = load_state(folder)
    before = str(state.get("caption_id") or "")
    holder = {"id": str(state.get("conversation_id") or "")}

    async def default_turn(message: str, *, extra_system: str, local_only: bool, role: str, twin_backend: str, source: str):
        if not local_only:
            raise RuntimeError("Assist live refuses a cloud turn")
        from twin_runtime import ensure_conversation, run_twin_turn

        conversation = await ensure_conversation(
            user["user_id"],
            kind="assist_live",
            conversation_id=holder["id"] or None,
        )
        holder["id"] = conversation["conversation_id"]
        return await run_twin_turn(
            user,
            message,
            conversation=conversation,
            source=source,
            persist=True,
            role=role,
            twin_backend=twin_backend,
            audience="owner",
            extra_system=extra_system or None,
            local_only=True,
        )

    async def default_execute(action: dict) -> dict:
        tool = str(action.get("tool") or "")
        if tool in {"send_message", "purchase"}:
            return {
                "summary": "Confirmed. This path does not send mail or submit a payment.",
                "ui": {"ok": True},
            }
        from twin_tools import execute_tool

        return await execute_tool(tool, user["user_id"], action.get("args") or {}, audience="owner")

    new_state, view = await advance_state(
        state,
        now=moment,
        audience=str(user.get("audience") or "owner"),
        heir_surface=bool(user.get("heir_surface")),
        memorial=memorial_from_user(user),
        paused=paused,
        clicked_id=clicked_id,
        declined_id=declined_id,
        turn=turn or default_turn,
        execute=execute or default_execute,
    )
    if holder["id"]:
        new_state["conversation_id"] = holder["id"]
    caption = str(new_state.get("caption") or "")
    if caption and str(new_state.get("caption_id") or "") != before:
        speaker = speak if speak is not None else fetch_chatterbox_wav
        try:
            wav = speaker(caption)
        except (OSError, ValueError, urllib.error.URLError):
            wav = None
        if isinstance(wav, bytes) and wav[:4] == b"RIFF":
            audio_id = str(new_state.get("caption_id") or "")
            store_wav(folder, audio_id, wav)
            new_state["audio_id"] = audio_id
    save_state(new_state, folder)
    return public_view(new_state)
