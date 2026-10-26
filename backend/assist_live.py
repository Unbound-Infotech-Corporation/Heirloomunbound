"""Assist beside the owner on BIGDEAL.

The twin may answer only after the microphone addresses it. System audio is
context. Computer work waits for a spoken or clicked yes, and a short deny
list never runs. Heirs and family get none of this. A posthumous memorial
gets no live room context.

Raw microphone audio is not kept here. Screen text is a summary, never a frame.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from memorial_mode import POSTHUMOUS, memorial_is_posthumous
from observer_privacy import redact_stored_text, screen_is_sensitive
from owner_pairing import is_owner_audience

PTT_WINDOW_S = 8.0
PROACTIVE_GAP_S = 600.0
PROACTIVE_HOUR_CAP = 3
RECENT_LIMIT = 12
RECEIPT_LIMIT = 20
MIC_LINE_LIMIT = 40

_FORBIDDEN_STATE_KEYS = frozenset({
    "pcm",
    "audio_pcm",
    "jpeg",
    "jpg",
    "frame",
    "video",
    "wav_bytes",
    "raw_audio",
    "raw_video",
})

_YES_EXPLICIT = frozenset({"yes", "yeah", "yep", "do it", "confirm", "yes please", "yes do it"})
_YES_NORMAL = _YES_EXPLICIT | frozenset({
    "ok",
    "okay",
    "sure",
    "go ahead",
    "please do",
    "ok do it",
    "sure do it",
})

_MUTE = re.compile(r"\b(?:mute|be quiet|stop talking|hush)\b", re.IGNORECASE)
_UNMUTE = re.compile(r"\b(?:unmute|you can talk)\b", re.IGNORECASE)
_CALL = re.compile(
    r"\b(?:zoom|microsoft teams|teams meeting|google meet|discord call|face ?time|"
    r"on a call|phone call|skype)\b",
    re.IGNORECASE,
)
_FULLSCREEN = re.compile(r"\b(?:full ?screen|borderless)\b", re.IGNORECASE)
_WORTH = re.compile(r"\b(?:error|failed|failure|crashed|stuck|reminder)\b", re.IGNORECASE)
_HOST = re.compile(r"(?<!\d)192\.168\.0\.(?:16|19)(?!\d)")
_PASSWORD = re.compile(r"\b(?:passwords?|passphrases?|owner password)\b", re.IGNORECASE)
_BOOT = re.compile(
    r"\b(?:bcdedit|msconfig|bootrec|boot settings|startup settings|safe mode)\b",
    re.IGNORECASE,
)
_POWER = re.compile(r"\b(?:reboot|shut ?down|power ?off|poweroff)\b", re.IGNORECASE)
_RESTART_PC = re.compile(
    r"\brestart\b.*\b(?:pc|computer|windows|machine)\b|\b(?:pc|computer|windows|machine)\b.*\brestart\b",
    re.IGNORECASE,
)
_MEDIA = re.compile(r"\b(?:song|music|track|video|playlist)\b", re.IGNORECASE)
_WIPE = re.compile(r"\b(?:wipe|diskpart)\b|\bclean all\b|\bcipher\s+/w\b", re.IGNORECASE)
_FORMAT = re.compile(r"\bformat\b.*\b(?:drive|disk|volume|c:|d:)\b|\b(?:drive|disk|volume)\b.*\bformat\b", re.IGNORECASE)
_OPEN = re.compile(r"\b(?:open|launch|start)\s+(.+)$", re.IGNORECASE)
_VOLUME = re.compile(r"\bvolume(?:\s+(?:to|at))?\s+(\d{1,3})\b", re.IGNORECASE)
_TYPE = re.compile(r"\btype\s+(.+)$", re.IGNORECASE)
_LOCK = re.compile(r"\block\b.*\b(?:pc|computer|windows)\b|\b(?:pc|computer)\b.*\block\b", re.IGNORECASE)
_SLEEP = re.compile(r"\bsleep\b.*\b(?:pc|computer|windows)\b|\b(?:pc|computer)\b.*\bsleep\b", re.IGNORECASE)
_RUN = re.compile(r"^(?:please\s+)?(?:run|command)\s+(.+)$", re.IGNORECASE)
_DELETE_NAME = re.compile(r"\b(?:delete|remove)\s+([A-Za-z0-9._ -]{1,80})$", re.IGNORECASE)
_SIMPLE_NAME = re.compile(r"^[A-Za-z0-9._ -]{1,80}$")
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


def default_state() -> dict[str, Any]:
    return {
        "wake_phrase": "",
        "twin_name": "Twin",
        "proactive": False,
        "muted": False,
        "ptt_until": 0.0,
        "paused": False,
        "inbox": None,
        "answered_id": "",
        "pending": None,
        "caption": "",
        "caption_id": "",
        "receipt": None,
        "receipts": [],
        "recent": [],
        "screen_summary": "",
        "screen_dropped_reason": "",
        "on_call": False,
        "fullscreen_game": False,
        "last_proactive_at": 0.0,
        "proactive_times": [],
        "proactive_due": False,
        "seq": 0,
        "audio_id": "",
        "listening": True,
    }


def wake_phrase_for(twin_name: str, configured: str = "") -> str:
    custom = " ".join((configured or "").split())
    if custom:
        return custom
    name = " ".join((twin_name or "").split()) or "Twin"
    return f"hey {name}"


def _words(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def strip_label(text: str, channel: str) -> str:
    raw = (text or "").strip()
    prefix = "User said:" if channel == "mic" else "Watching/heard:"
    if raw.lower().startswith(prefix.lower()):
        raw = raw[len(prefix):].strip()
    return raw


def detect_address(
    text: str,
    *,
    channel: str,
    wake_phrase: str,
    push_to_talk: bool,
    paused: bool,
) -> dict[str, Any]:
    """Only the microphone can start a turn. Pause means we are not listening."""
    if paused:
        return {"listening": False, "triggered": False, "reason": "paused", "utterance": ""}
    if channel != "mic":
        return {"listening": True, "triggered": False, "reason": "channel", "utterance": ""}
    spoken = strip_label(text, "mic")
    if not spoken:
        return {"listening": True, "triggered": False, "reason": "empty", "utterance": ""}
    if push_to_talk:
        return {"listening": True, "triggered": True, "reason": "ptt", "utterance": spoken}
    phrase = _words(wake_phrase)
    heard = _words(spoken)
    if phrase and (heard == phrase or heard.startswith(phrase + " ")):
        rest = heard[len(phrase):].strip()
        utterance = rest or spoken
        if rest:
            # Keep the owner's casing for the part after the wake phrase.
            original_words = spoken.split()
            phrase_len = len(phrase.split())
            utterance = " ".join(original_words[phrase_len:]).strip() or rest
        return {"listening": True, "triggered": True, "reason": "wake", "utterance": utterance}
    return {"listening": True, "triggered": False, "reason": "ignored", "utterance": ""}


def gate_for(
    audience: str | None,
    *,
    heir_surface: bool = False,
    memorial: Any = None,
) -> dict[str, bool]:
    """Heirs and family never get PC tools, the screen, or observer context.

    Posthumous memorial mode is still the owner's voice, with no live room.
    """
    owner = is_owner_audience(audience) and not heir_surface
    memorial_on = memorial_is_posthumous(memorial) if not isinstance(memorial, str) else memorial == POSTHUMOUS
    if isinstance(memorial, str):
        memorial_on = memorial.strip().lower() == POSTHUMOUS
    live = owner and not memorial_on
    return {
        "owner": owner,
        "pc_tools": owner,
        "screen": live,
        "observer": live,
        "live_context": live,
    }


def is_affirmative(text: str, *, explicit: bool) -> bool:
    heard = _words(text)
    allowed = _YES_EXPLICIT if explicit else _YES_NORMAL
    return heard in allowed


def judge_action(text: str) -> Optional[dict[str, Any]]:
    """Classify one addressed utterance. None means talk only."""
    spoken = " ".join((text or "").split())
    if not spoken:
        return None
    folded = spoken.lower()
    if _HOST.search(spoken):
        return _action("deny", "run_command", {}, "Denied. That address stays off this path.", spoken)
    if _PASSWORD.search(spoken):
        return _action("deny", "type_text", {}, "Denied. Owner passwords stay off this path.", spoken)
    if _BOOT.search(spoken) or (_POWER.search(spoken) and not _MEDIA.search(spoken)) or _RESTART_PC.search(spoken):
        return _action("deny", "power_action", {"action": "shutdown"}, "Denied. Reboot, shutdown, and boot settings stay off this path.", spoken)
    if _WIPE.search(spoken) or _FORMAT.search(spoken):
        return _action("deny", "run_command", {}, "Denied. Format and wipe stay off this path.", spoken)
    if re.search(r"\b(?:delete|remove)\b", folded):
        delete = _DELETE_NAME.search(spoken.strip())
        name = delete.group(1).strip() if delete else ""
        simple = bool(name) and bool(_SIMPLE_NAME.match(name)) and not re.search(r"[\\/]|[.]{2}", name)
        if simple:
            return _action(
                "explicit",
                "run_command",
                {"command": f"del \"{name}\"", "confirmed": False},
                f"Delete {name}",
                spoken,
            )
        return _action("deny", "run_command", {}, "Denied. That delete is not a single file name.", spoken)
    if re.search(r"\b(?:buy|purchase|pay for|check ?out)\b", folded):
        return _action("explicit", "purchase", {}, "Purchase", spoken)
    if re.search(r"\b(?:send|e-?mail)\b", folded):
        return _action("explicit", "send_message", {}, "Send", spoken)
    volume = _VOLUME.search(spoken)
    if volume:
        level = max(0, min(100, int(volume.group(1))))
        return _action("confirm", "set_volume", {"level": level}, f"Set volume to {level}", spoken)
    if _LOCK.search(spoken):
        return _action("confirm", "power_action", {"action": "lock"}, "Lock this PC", spoken)
    if _SLEEP.search(spoken):
        return _action("confirm", "power_action", {"action": "sleep"}, "Sleep this PC", spoken)
    opened = _OPEN.search(spoken)
    if opened:
        target = opened.group(1).strip(" .")
        if target:
            return _action("confirm", "open_on_pc", {"target": target}, f"Open {target}", spoken)
    typed = _TYPE.search(spoken)
    if typed:
        body = typed.group(1).strip()
        if body:
            return _action("confirm", "type_text", {"text": body}, "Type on this PC", spoken)
    ran = _RUN.search(spoken)
    if ran:
        command = ran.group(1).strip()
        if command:
            nested = judge_action(command)
            if nested and nested["verdict"] == "deny":
                return nested
            return _action(
                "confirm",
                "run_command",
                {"command": command, "confirmed": False},
                f"Run {command}",
                spoken,
            )
    return None


def _action(verdict: str, tool: str, args: dict, label: str, utterance: str) -> dict[str, Any]:
    return {
        "verdict": verdict,
        "tool": tool,
        "args": dict(args),
        "label": label,
        "summary": label,
        "utterance": utterance,
    }


def room_flags(text: str, activity: str = "", dropped_reason: str = "") -> tuple[bool, bool]:
    blob = text or ""
    on_call = dropped_reason == "chat" or bool(_CALL.search(blob))
    game = (activity or "").strip().lower() == "game"
    fullscreen = bool(_FULLSCREEN.search(blob)) and (game or "game" in blob.lower())
    return on_call, fullscreen


def proactive_allowed(
    state: dict,
    gate: dict[str, bool],
    *,
    now: float,
) -> bool:
    if not state.get("proactive"):
        return False
    if state.get("muted") or state.get("paused"):
        return False
    if not gate.get("live_context"):
        return False
    if state.get("on_call") or state.get("fullscreen_game"):
        return False
    if state.get("inbox"):
        return False
    summary = str(state.get("screen_summary") or "")
    if not _WORTH.search(summary):
        return False
    if screen_is_sensitive(summary).drop:
        return False
    last = float(state.get("last_proactive_at") or 0)
    if last and now - last < PROACTIVE_GAP_S:
        return False
    times = [float(item) for item in state.get("proactive_times") or [] if now - float(item) < 3600]
    if len(times) >= PROACTIVE_HOUR_CAP:
        return False
    return True


def extra_system_for(state: dict, gate: dict[str, bool]) -> str:
    if not gate.get("live_context"):
        return ""
    lines = [
        "ROOM CONTEXT (local to this PC, lower priority than filed memory). "
        "This is what is happening now. It is not a memory you lived.",
    ]
    if gate.get("observer"):
        for row in (state.get("recent") or [])[-8:]:
            if not isinstance(row, dict):
                continue
            label = "User said" if row.get("channel") == "mic" else "Watching/heard"
            text = redact_stored_text(str(row.get("text") or ""), limit=280)
            if text and not screen_is_sensitive(text).drop:
                lines.append(f"- {label}: {text}")
    if gate.get("screen"):
        summary = str(state.get("screen_summary") or "")
        if screen_is_sensitive(summary).drop:
            summary = ""
        lines.append("Screen: " + (redact_stored_text(summary, limit=280) if summary else "not available"))
    else:
        lines.append("Screen: not available")
    lines.append(
        "Assist owns the computer. Do not claim you sent, bought, deleted, rebooted, "
        "or typed a password. Ask nothing of the cloud."
    )
    return "\n".join(lines)


def public_view(state: dict) -> dict[str, Any]:
    pending = state.get("pending") if isinstance(state.get("pending"), dict) else None
    receipt = state.get("receipt") if isinstance(state.get("receipt"), dict) else None
    return {
        "listening": bool(state.get("listening")) and not bool(state.get("paused")),
        "caption": str(state.get("caption") or ""),
        "caption_id": str(state.get("caption_id") or ""),
        "pending": (
            {
                "id": pending.get("id") or "",
                "label": pending.get("label") or "",
                "explicit": pending.get("verdict") == "explicit",
            }
            if pending
            else None
        ),
        "receipt": receipt,
        "receipts": _public_receipts(state),
        "muted": bool(state.get("muted")),
        "proactive": bool(state.get("proactive")),
        "wake_phrase": wake_phrase_for(str(state.get("twin_name") or ""), str(state.get("wake_phrase") or "")),
        "has_audio": bool(state.get("audio_id")),
        "audio_id": str(state.get("audio_id") or ""),
    }


def _public_receipts(state: dict) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in (state.get("receipts") or [])[-8:]:
        if not isinstance(row, dict):
            continue
        summary = " ".join(str(row.get("summary") or "").split())
        if not summary:
            continue
        rows.append({"status": str(row.get("status") or ""), "summary": summary[:280]})
    return rows


def _copy(state: dict | None) -> dict[str, Any]:
    base = default_state()
    if isinstance(state, dict):
        for key, value in state.items():
            if key in _FORBIDDEN_STATE_KEYS:
                continue
            base[key] = value
    base["recent"] = [row for row in base.get("recent") or [] if isinstance(row, dict)][-RECENT_LIMIT:]
    base["receipts"] = [row for row in base.get("receipts") or [] if isinstance(row, dict)][-RECEIPT_LIMIT:]
    base["proactive"] = bool(base.get("proactive"))
    base["muted"] = bool(base.get("muted"))
    return base


def _nid(state: dict, now: float, prefix: str) -> str:
    seq = int(state.get("seq") or 0) + 1
    state["seq"] = seq
    return f"{prefix}_{int(now)}_{seq}"


def _remember(state: dict, channel: str, text: str) -> None:
    cleaned = redact_stored_text(text, limit=280)
    if not cleaned or screen_is_sensitive(cleaned).drop:
        return
    recent = list(state.get("recent") or [])
    recent.append({"channel": channel, "text": cleaned})
    state["recent"] = recent[-RECENT_LIMIT:]


def reduce_settings(state: dict | None, patch: dict) -> dict[str, Any]:
    current = _copy(state)
    if "wake_phrase" in patch and patch["wake_phrase"] is not None:
        current["wake_phrase"] = str(patch["wake_phrase"]).strip()[:80]
    if "twin_name" in patch and patch["twin_name"] is not None:
        current["twin_name"] = str(patch["twin_name"]).strip()[:80] or "Twin"
    if "proactive" in patch and patch["proactive"] is not None:
        current["proactive"] = bool(patch["proactive"])
    return current


def reduce_pause(state: dict | None, paused: bool) -> dict[str, Any]:
    current = _copy(state)
    current["paused"] = bool(paused)
    current["listening"] = not bool(paused)
    if paused:
        current["ptt_until"] = 0.0
        current["inbox"] = None
        current["proactive_due"] = False
    return current


def reduce_ptt(state: dict | None, *, now: float, held: bool) -> dict[str, Any]:
    current = _copy(state)
    if current.get("paused") or not held:
        current["ptt_until"] = 0.0
        return current
    current["ptt_until"] = float(now) + PTT_WINDOW_S
    return current


def reduce_mute(state: dict | None, muted: bool) -> dict[str, Any]:
    current = _copy(state)
    current["muted"] = bool(muted)
    if muted:
        current["proactive_due"] = False
    return current


def reduce_heard(
    state: dict | None,
    *,
    text: str,
    channel: str,
    now: float,
    paused: bool | None = None,
) -> dict[str, Any]:
    current = _copy(state)
    if paused is not None:
        current["paused"] = bool(paused)
    if current.get("paused"):
        return reduce_pause(current, True)
    current["listening"] = True
    spoken = strip_label(text, channel if channel in {"mic", "system"} else "mic")
    if channel == "system":
        if spoken:
            _remember(current, "system", spoken)
            on_call, _fullscreen = room_flags(spoken)
            if on_call:
                current["on_call"] = True
        return current
    if channel != "mic" or not spoken:
        return current
    if _UNMUTE.search(spoken):
        current["muted"] = False
    elif _MUTE.search(spoken):
        current["muted"] = True
        current["proactive_due"] = False
        _remember(current, "mic", spoken)
        return current
    _remember(current, "mic", spoken)
    pending = current.get("pending") if isinstance(current.get("pending"), dict) else None
    if pending and is_affirmative(spoken, explicit=pending.get("verdict") == "explicit"):
        current["inbox"] = {"id": _nid(current, now, "say"), "text": spoken}
        return current
    phrase = wake_phrase_for(str(current.get("twin_name") or ""), str(current.get("wake_phrase") or ""))
    ptt = float(current.get("ptt_until") or 0) >= float(now)
    address = detect_address(
        spoken,
        channel="mic",
        wake_phrase=phrase,
        push_to_talk=ptt,
        paused=False,
    )
    if address["triggered"]:
        current["ptt_until"] = 0.0
        current["inbox"] = {"id": _nid(current, now, "say"), "text": address["utterance"]}
    return current


def reduce_screen(
    state: dict | None,
    *,
    text: str,
    activity: str = "",
    dropped_reason: str = "",
    now: float = 0.0,
    gate: dict[str, bool] | None = None,
) -> dict[str, Any]:
    current = _copy(state)
    if current.get("paused"):
        current["proactive_due"] = False
        return current
    summary = "" if dropped_reason else redact_stored_text(text or "", limit=280)
    if summary and screen_is_sensitive(summary).drop:
        dropped_reason = screen_is_sensitive(summary).reason or dropped_reason or "sensitive"
        summary = ""
    on_call, fullscreen = room_flags(summary or text or "", activity, dropped_reason)
    current["screen_summary"] = summary
    current["screen_dropped_reason"] = dropped_reason
    current["on_call"] = on_call
    current["fullscreen_game"] = fullscreen
    active_gate = gate or gate_for("owner")
    current["proactive_due"] = proactive_allowed(current, active_gate, now=now)
    return current


def _receipt(action: dict, *, ok: bool, needs_confirm: bool, summary: str) -> dict[str, Any]:
    from assist_receipt import build_assist_receipt

    row = {
        "id": action.get("id") or "",
        "name": action.get("tool") or "tool",
        "summary": summary,
        "ui": {"ok": ok, "needs_confirm": needs_confirm, "label": action.get("label") or summary},
    }
    built = build_assist_receipt([row], reply=summary, include=True)
    return built or {"status": "failed", "summary": summary, "steps": [], "plan": None}


def _store_receipt(state: dict, receipt: dict) -> None:
    state["receipt"] = receipt
    receipts = list(state.get("receipts") or [])
    receipts.append(receipt)
    state["receipts"] = receipts[-RECEIPT_LIMIT:]


def _speak(state: dict, now: float, text: str) -> None:
    caption = " ".join((text or "").split())
    state["caption"] = caption[:500]
    state["caption_id"] = _nid(state, now, "cap")
    state["audio_id"] = ""


async def advance_state(
    state: dict | None,
    *,
    now: float,
    audience: str,
    heir_surface: bool = False,
    memorial: Any = None,
    paused: bool = False,
    clicked_id: str = "",
    declined_id: str = "",
    turn: Any = None,
    execute: Any = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """One poll. `turn` is run_twin_turn. Denied work never reaches `execute`."""
    current = reduce_pause(_copy(state), paused)
    gate = gate_for(audience, heir_surface=heir_surface, memorial=memorial)
    if not gate["owner"]:
        current["inbox"] = None
        current["pending"] = None
        current["screen_summary"] = ""
        current["recent"] = []
        current["proactive_due"] = False
        current["caption"] = ""
        return current, public_view(current)
    if not gate["pc_tools"]:
        current["pending"] = None
    if paused:
        return current, public_view(current)

    pending = current.get("pending") if isinstance(current.get("pending"), dict) else None
    if declined_id and pending and str(pending.get("id") or "") == declined_id:
        current = _decline(current, pending, now=now)
        pending = None
    if clicked_id and pending and str(pending.get("id") or "") == clicked_id and gate["pc_tools"]:
        current = await _commit(current, pending, now=now, execute=execute)
        pending = current.get("pending") if isinstance(current.get("pending"), dict) else None

    inbox = current.get("inbox") if isinstance(current.get("inbox"), dict) else None
    answered_now = False
    if inbox and str(inbox.get("id") or "") != str(current.get("answered_id") or ""):
        utterance = str(inbox.get("text") or "").strip()
        result = await _speak_through_twin(turn, utterance, extra_system_for(current, gate))
        current["answered_id"] = str(inbox.get("id") or "")
        current["inbox"] = None
        answered_now = True
        if result.get("crisis") or result.get("backend") == "local_unavailable":
            _speak(current, now, result.get("reply") or "")
            current["pending"] = None
        else:
            current = await _apply_utterance(
                current,
                utterance,
                reply=str(result.get("reply") or ""),
                now=now,
                execute=execute,
                allow_tools=gate["pc_tools"],
            )

    if not answered_now and proactive_allowed(current, gate, now=now) and current.get("proactive_due"):
        prompt = (
            "One short aside about the room, only if it is worth interrupting. "
            "If it is not, answer with exactly …"
        )
        result = await _speak_through_twin(turn, prompt, extra_system_for(current, gate))
        current["proactive_due"] = False
        current["last_proactive_at"] = float(now)
        times = [float(item) for item in current.get("proactive_times") or [] if now - float(item) < 3600]
        times.append(float(now))
        current["proactive_times"] = times[-12:]
        reply = str(result.get("reply") or "").strip()
        if result.get("crisis"):
            _speak(current, now, reply)
        elif reply and reply not in {"…", "...", "…."}:
            _speak(current, now, reply)
    elif not proactive_allowed(current, gate, now=now):
        current["proactive_due"] = False
    return current, public_view(current)


async def _speak_through_twin(turn: Any, message: str, extra_system: str) -> dict[str, Any]:
    if turn is None:
        return {"reply": "", "crisis": False, "backend": "local_unavailable"}
    result = await turn(
        message,
        extra_system=extra_system,
        local_only=True,
        role="twin",
        twin_backend="ollama",
        source="assist_live",
    )
    if isinstance(result, dict):
        return {
            "reply": str(result.get("reply") or ""),
            "crisis": bool(result.get("crisis")),
            "backend": str(result.get("backend") or ""),
        }
    return {
        "reply": str(getattr(result, "reply", "") or ""),
        "crisis": bool(getattr(result, "crisis", False)),
        "backend": str(getattr(result, "backend", "") or ""),
    }


async def _apply_utterance(
    state: dict,
    utterance: str,
    *,
    reply: str,
    now: float,
    execute: Any,
    allow_tools: bool,
) -> dict:
    pending = state.get("pending") if isinstance(state.get("pending"), dict) else None
    action = judge_action(utterance) if allow_tools else None
    if action is None and pending and is_affirmative(utterance, explicit=pending.get("verdict") == "explicit"):
        return await _commit(state, pending, now=now, execute=execute)
    if action is None:
        _speak(state, now, reply or "I'm here.")
        return state
    if action["verdict"] == "deny":
        receipt = _receipt(action, ok=False, needs_confirm=False, summary=action["label"])
        _store_receipt(state, receipt)
        state["pending"] = None
        _speak(state, now, action["label"])
        return state
    action = dict(action)
    action["id"] = _nid(state, now, "act")
    state["pending"] = action
    receipt = _receipt(
        action,
        ok=False,
        needs_confirm=True,
        summary=f"Waiting for yes — {action['label']}",
    )
    _store_receipt(state, receipt)
    ask = f"Say yes to {action['label']}."
    spoken = reply.strip()
    _speak(state, now, f"{spoken} {ask}".strip() if spoken else ask)
    return state


def _decline(state: dict, pending: dict, *, now: float) -> dict:
    """No leaves the action unrun. This never calls the PC tool."""
    label = str(pending.get("label") or "that")
    summary = f"No. Left {label} alone."
    receipt = _receipt(pending, ok=False, needs_confirm=False, summary=summary)
    _store_receipt(state, receipt)
    state["pending"] = None
    _speak(state, now, summary)
    return state


async def _commit(state: dict, pending: dict, *, now: float, execute: Any) -> dict:
    again = judge_action(str(pending.get("utterance") or ""))
    if again is None or again["verdict"] == "deny" or pending.get("verdict") == "deny":
        label = (again or {}).get("label") or "Denied."
        receipt = _receipt(pending, ok=False, needs_confirm=False, summary=label)
        _store_receipt(state, receipt)
        state["pending"] = None
        _speak(state, now, label)
        return state
    args = dict(pending.get("args") or {})
    if pending.get("tool") == "run_command":
        args["confirmed"] = True
    outgoing = dict(pending)
    outgoing["args"] = args
    summary = str(pending.get("label") or "Done")
    ok = True
    if pending.get("tool") in {"send_message", "purchase"}:
        summary = (
            "Confirmed. This path does not send mail or submit a payment."
        )
    elif execute is not None:
        try:
            result = await execute(outgoing)
        except Exception as exc:  # noqa: BLE001
            result = {"summary": str(exc)[:200], "ui": {"ok": False}}
        if isinstance(result, dict):
            summary = str(result.get("summary") or summary)
            ui = result.get("ui") if isinstance(result.get("ui"), dict) else {}
            ok = bool(ui.get("ok", True))
    receipt = _receipt(outgoing, ok=ok, needs_confirm=False, summary=summary)
    _store_receipt(state, receipt)
    state["pending"] = None
    _speak(state, now, summary)
    return state


def loopback_speak_wav_url(raw: str | None = None) -> str:
    """Chatterbox on this box. Any other host is refused before a socket opens."""
    if raw is None:
        raw = os.environ.get("PRESENCE_SPEAK_URL", "http://127.0.0.1:8010/speak")
    text = (raw or "").strip() or "http://127.0.0.1:8010/speak"
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in _LOOPBACK:
        raise ValueError("Chatterbox stays on this box")
    path = parsed.path or "/speak"
    if path.endswith("/speak"):
        path = path + ".wav"
    return parsed._replace(path=path).geturl()


def state_path(root: Path | None = None) -> Path:
    if root is None:
        from observer_store import observer_dir

        root = observer_dir()
    return Path(root) / "assist_live.json"


def load_state(root: Path | None = None) -> dict[str, Any]:
    path = state_path(root)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_state()
    if not isinstance(loaded, dict):
        return default_state()
    return _copy(loaded)


def save_state(state: dict, root: Path | None = None) -> None:
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _copy(state)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def mic_transcript(root: Path, *, paused: bool, limit: int = MIC_LINE_LIMIT) -> dict[str, Any]:
    """Recent owner microphone words from the observer transcript.

    System audio is omitted. Pause is reported and this function does not write.
    Sensitive lines are dropped. Raw audio is not read.
    """
    path = Path(root) / "observations.jsonl"
    try:
        raw = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        raw = []
    lines: list[dict[str, str]] = []
    for line in raw[-400:]:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict) or row.get("dropped"):
            continue
        if str(row.get("channel") or "") != "mic":
            continue
        activity = str(row.get("activity") or "speech")
        if activity not in {"speech", ""}:
            continue
        text = strip_label(str(row.get("text") or ""), "mic")
        if not text or screen_is_sensitive(text).drop:
            continue
        text = redact_stored_text(text, limit=280)
        if not text:
            continue
        ts = str(row.get("ts") or "")
        digest = hashlib.sha256(f"{ts}|{text}".encode("utf-8")).hexdigest()[:16]
        lines.append({"id": digest, "text": text, "ts": ts})
    kept = lines[-max(1, limit):]
    return {
        "listening": not paused,
        "paused": bool(paused),
        "lines": kept,
    }


def tail_screen(root: Path) -> dict[str, str]:
    """Last vision note as text. Frames and clips are not opened."""
    path = Path(root) / "observations.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {"text": "", "activity": "", "dropped_reason": ""}
    for line in reversed(lines[-40:]):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        channel = str(row.get("channel") or "")
        activity = str(row.get("activity") or "")
        if channel in {"mic", "system"} or activity in {"speech", "heard"}:
            continue
        if row.get("dropped"):
            return {"text": "", "activity": activity, "dropped_reason": str(row.get("reason") or "sensitive")}
        return {
            "text": str(row.get("text") or ""),
            "activity": activity,
            "dropped_reason": "",
        }
    return {"text": "", "activity": "", "dropped_reason": ""}


def ingest_heard(
    root: Path,
    *,
    text: str,
    channel: str,
    paused: bool,
    now: float,
) -> dict[str, Any]:
    screen = tail_screen(root)
    state = reduce_heard(load_state(root), text=text, channel=channel, now=now, paused=paused)
    if not paused:
        state = reduce_screen(
            state,
            text=screen["text"],
            activity=screen["activity"],
            dropped_reason=screen["dropped_reason"],
            now=now,
        )
    save_state(state, root)
    return state


def cloud_fallback_allowed(local_only: bool) -> bool:
    """Assist-live never trades a missing local model for a cloud call."""
    return not local_only
