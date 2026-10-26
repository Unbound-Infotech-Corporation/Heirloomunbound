"""Wake gating, owner-only room context, confirm-before-act, deny list, pause."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from assist_live import (
    advance_state,
    cloud_fallback_allowed,
    default_state,
    detect_address,
    extra_system_for,
    gate_for,
    ingest_heard,
    judge_action,
    load_state,
    loopback_speak_wav_url,
    proactive_allowed,
    reduce_heard,
    reduce_mute,
    reduce_pause,
    reduce_ptt,
    reduce_screen,
    reduce_settings,
    room_flags,
    save_state,
    wake_phrase_for,
)
from assist_live_runner import fetch_chatterbox_wav, store_wav, take_wav
from deps import get_current_user
from routers.assist_live import router


def _run(coro):
    return asyncio.run(coro)


class _Calls:
    def __init__(self, reply="On it.", *, crisis=False, backend="ollama"):
        self.reply = reply
        self.crisis = crisis
        self.backend = backend
        self.turns = []
        self.actions = []

    async def turn(self, message, *, extra_system, local_only, role, twin_backend, source):
        self.turns.append(
            {
                "message": message,
                "extra_system": extra_system,
                "local_only": local_only,
                "role": role,
                "twin_backend": twin_backend,
                "source": source,
            }
        )
        return {"reply": self.reply, "crisis": self.crisis, "backend": self.backend}

    async def execute(self, action):
        self.actions.append(action)
        return {"summary": "Done — " + action["label"], "ui": {"ok": True}}


def test_wake_is_mic_only_and_the_phrase_is_configurable():
    assert wake_phrase_for("C L", "") == "hey C L"
    assert wake_phrase_for("C L", "hey heirloom") == "hey heirloom"
    hit = detect_address(
        "hey C L open notepad",
        channel="mic",
        wake_phrase="hey C L",
        push_to_talk=False,
        paused=False,
    )
    assert hit["triggered"] is True
    assert hit["reason"] == "wake"
    assert hit["utterance"] == "open notepad"
    missed = detect_address(
        "hey Twin open notepad",
        channel="mic",
        wake_phrase="hey C L",
        push_to_talk=False,
        paused=False,
    )
    assert missed["triggered"] is False
    speakers = detect_address(
        "hey C L open notepad",
        channel="system",
        wake_phrase="hey C L",
        push_to_talk=True,
        paused=False,
    )
    assert speakers["listening"] is True
    assert speakers["triggered"] is False
    assert speakers["reason"] == "channel"
    paused = detect_address(
        "hey C L open notepad",
        channel="mic",
        wake_phrase="hey C L",
        push_to_talk=True,
        paused=True,
    )
    assert paused["listening"] is False
    assert paused["triggered"] is False
    assert paused["reason"] == "paused"


def test_push_to_talk_arms_only_the_microphone():
    state = reduce_settings(default_state(), {"twin_name": "C L"})
    armed = reduce_ptt(state, now=1_000.0, held=True)
    heard = reduce_heard(armed, text="open notepad", channel="mic", now=1_001.0)
    assert heard["inbox"]["text"] == "open notepad"
    leaked = reduce_heard(armed, text="hey C L shut down", channel="system", now=1_001.0)
    assert leaked["inbox"] is None
    expired = reduce_heard(armed, text="open notepad", channel="mic", now=1_000.0 + 30)
    assert expired["inbox"] is None


def test_pause_stops_listening_and_blocks_yes():
    state = reduce_settings(default_state(), {"twin_name": "C L"})
    state = reduce_heard(state, text="hey C L open notepad", channel="mic", now=10, paused=False)
    assert state["inbox"]["text"] == "open notepad"
    stopped = reduce_heard(state, text="yes", channel="mic", now=11, paused=True)
    assert stopped["listening"] is False
    assert stopped["paused"] is True
    assert stopped["inbox"] is None
    calls = _Calls()
    _state, view = _run(
        advance_state(
            stopped,
            now=12,
            audience="owner",
            paused=True,
            clicked_id="act_1",
            turn=calls.turn,
            execute=calls.execute,
        )
    )
    assert view["listening"] is False
    assert calls.turns == []
    assert calls.actions == []
    resumed, resumed_view = _run(
        advance_state(stopped, now=13, audience="owner", paused=False, turn=calls.turn, execute=calls.execute)
    )
    assert resumed["paused"] is False
    assert resumed_view["listening"] is True


def test_owner_context_stays_off_heirs_family_and_memorial():
    assert gate_for("owner")["pc_tools"] is True
    assert gate_for("owner")["live_context"] is True
    for audience in ("heir", "caller", "family"):
        gate = gate_for(audience)
        assert gate["owner"] is False
        assert gate["pc_tools"] is False
        assert gate["screen"] is False
        assert gate["observer"] is False
    assert gate_for("owner", heir_surface=True)["pc_tools"] is False
    memorial = gate_for("owner", memorial="posthumous")
    assert memorial["owner"] is True
    assert memorial["pc_tools"] is True
    assert memorial["live_context"] is False
    assert memorial["screen"] is False
    assert memorial["observer"] is False

    room = reduce_screen(
        default_state(),
        text="Editor showing an error dialog",
        activity="work",
        now=50,
    )
    room = reduce_heard(reduce_settings(room, {"twin_name": "C L"}), text="User said: earlier", channel="mic", now=51)
    assert extra_system_for(room, gate_for("owner")) 
    assert "error dialog" in extra_system_for(room, gate_for("owner"))
    assert extra_system_for(room, gate_for("heir")) == ""
    assert extra_system_for(room, gate_for("family")) == ""
    assert extra_system_for(room, gate_for("owner", memorial="posthumous")) == ""

    calls = _Calls()
    room["inbox"] = {"id": "say_1", "text": "what is on screen"}
    _state, _view = _run(
        advance_state(
            room,
            now=60,
            audience="owner",
            memorial="posthumous",
            turn=calls.turn,
            execute=calls.execute,
        )
    )
    assert calls.turns[0]["extra_system"] == ""
    assert calls.turns[0]["local_only"] is True
    assert calls.turns[0]["role"] == "twin"
    assert calls.turns[0]["twin_backend"] == "ollama"
    assert calls.turns[0]["source"] == "assist_live"

    heir_calls = _Calls()
    _state, view = _run(
        advance_state(
            room,
            now=61,
            audience="family",
            heir_surface=False,
            turn=heir_calls.turn,
            execute=heir_calls.execute,
        )
    )
    assert heir_calls.turns == []
    assert heir_calls.actions == []
    assert view["caption"] == ""
    assert view["pending"] is None


def test_sensitive_screen_text_never_enters_the_room_prompt():
    state = reduce_screen(default_state(), text="1Password vault is open", activity="work", now=5)
    assert state["screen_summary"] == ""
    assert state["screen_dropped_reason"]
    assert "1Password" not in extra_system_for(state, gate_for("owner"))
    assert "Screen: not available" in extra_system_for(state, gate_for("owner"))


def test_every_action_waits_and_the_deny_list_never_runs():
    calls = _Calls(reply="Sure.")
    state = default_state()
    state, view = _run(
        advance_state(
            {**state, "inbox": {"id": "say_open", "text": "open notepad"}},
            now=20,
            audience="owner",
            turn=calls.turn,
            execute=calls.execute,
        )
    )
    assert calls.actions == []
    assert view["pending"]["label"] == "Open notepad"
    assert view["receipt"]["status"] == "waiting_confirm"
    assert "Say yes" in view["caption"]
    assert state["pending"]["args"].get("confirmed") is not True
    aside = _Calls(reply="The build failed.")
    busy = reduce_screen(reduce_settings(default_state(), {"proactive": True}), text="Build failed with an error", now=20)
    busy["inbox"] = {"id": "say_busy", "text": "open notepad"}
    busy["proactive_due"] = True
    _busy, busy_view = _run(
        advance_state(busy, now=20, audience="owner", turn=aside.turn, execute=aside.execute)
    )
    assert len(aside.turns) == 1
    assert aside.turns[0]["message"] == "open notepad"
    assert "Say yes" in busy_view["caption"]

    denied = _Calls()
    for utterance in (
        "shut down the pc",
        "reboot",
        "restart the computer",
        "open boot settings",
        "wipe the disk",
        "format the d drive",
        "ping 192.168.0.16",
        "ssh 192.168.0.19",
        "type my password",
        "delete C:\\Windows\\System32",
    ):
        _state, view = _run(
            advance_state(
                {**default_state(), "inbox": {"id": "say_" + utterance[:12], "text": utterance}},
                now=21,
                audience="owner",
                turn=denied.turn,
                execute=denied.execute,
            )
        )
        assert view["pending"] is None, utterance
        assert view["receipt"]["status"] == "failed", utterance
        assert view["caption"].startswith("Denied"), utterance
    assert denied.actions == []
    assert judge_action("ping 192.168.0.160") is None or judge_action("ping 192.168.0.160")["verdict"] != "deny"
    assert judge_action("restart the song") is None


def test_spoken_yes_and_click_confirm_explicit_words_for_send_buy_delete():
    calls = _Calls(reply="Ready.")
    opened, _view = _run(
        advance_state(
            {**default_state(), "inbox": {"id": "s1", "text": "set the volume to 15"}},
            now=30,
            audience="owner",
            turn=calls.turn,
            execute=calls.execute,
        )
    )
    assert opened["pending"]["tool"] == "set_volume"
    system_yes = reduce_heard(opened, text="yes", channel="system", now=31)
    assert system_yes["inbox"] is None
    still, _view = _run(
        advance_state(system_yes, now=32, audience="owner", turn=calls.turn, execute=calls.execute)
    )
    assert still["pending"]["id"] == opened["pending"]["id"]
    assert calls.actions == []

    mic_yes = reduce_heard(still, text="yes", channel="mic", now=33)
    assert mic_yes["inbox"]["text"] == "yes"
    done, view = _run(
        advance_state(mic_yes, now=34, audience="owner", turn=calls.turn, execute=calls.execute)
    )
    assert calls.actions and calls.actions[-1]["tool"] == "set_volume"
    assert view["pending"] is None
    assert view["receipt"]["status"] == "did"
    assert done["pending"] is None

    delete_calls = _Calls()
    waiting, view = _run(
        advance_state(
            {**default_state(), "inbox": {"id": "d1", "text": "delete notes.txt"}},
            now=40,
            audience="owner",
            turn=delete_calls.turn,
            execute=delete_calls.execute,
        )
    )
    assert view["pending"]["explicit"] is True
    casual = dict(waiting)
    casual["inbox"] = {"id": "d2", "text": "ok"}
    held, _view = _run(
        advance_state(casual, now=41, audience="owner", turn=delete_calls.turn, execute=delete_calls.execute)
    )
    assert held["pending"] is not None
    assert delete_calls.actions == []
    clicked, view = _run(
        advance_state(
            held,
            now=42,
            audience="owner",
            clicked_id=held["pending"]["id"],
            turn=delete_calls.turn,
            execute=delete_calls.execute,
        )
    )
    assert delete_calls.actions[-1]["args"]["confirmed"] is True
    assert "del \"notes.txt\"" in delete_calls.actions[-1]["args"]["command"]
    assert view["receipt"]["status"] == "did"
    assert clicked["pending"] is None

    for utterance, tool in (("send an email to sam", "send_message"), ("buy the ticket", "purchase")):
        buy = _Calls()
        pending, _view = _run(
            advance_state(
                {**default_state(), "inbox": {"id": "e1", "text": utterance}},
                now=50,
                audience="owner",
                turn=buy.turn,
                execute=buy.execute,
            )
        )
        finished, view = _run(
            advance_state(
                {**pending, "inbox": {"id": "e2", "text": "yes"}},
                now=51,
                audience="owner",
                turn=buy.turn,
                execute=buy.execute,
            )
        )
        assert buy.actions == []
        assert "does not send" in view["caption"] or "payment" in view["caption"]
        assert finished["pending"] is None


def test_crisis_and_local_refusal_do_not_run_the_action():
    crisis = _Calls(reply="Call 988.", crisis=True, backend="crisis")
    _state, view = _run(
        advance_state(
            {**default_state(), "inbox": {"id": "c1", "text": "shut down the pc"}},
            now=70,
            audience="owner",
            turn=crisis.turn,
            execute=crisis.execute,
        )
    )
    assert view["caption"] == "Call 988."
    assert view["pending"] is None
    assert crisis.actions == []

    local = _Calls(reply="I won't send this to the cloud.", backend="local_unavailable")
    _state, view = _run(
        advance_state(
            {**default_state(), "inbox": {"id": "c2", "text": "open notepad"}},
            now=71,
            audience="owner",
            turn=local.turn,
            execute=local.execute,
        )
    )
    assert "cloud" in view["caption"]
    assert view["pending"] is None
    assert local.actions == []


def test_proactive_is_off_rate_limited_and_suppressed():
    quiet = reduce_screen(default_state(), text="Editor showing an error dialog", activity="work", now=100)
    assert quiet["proactive"] is False
    assert quiet["proactive_due"] is False
    enabled = reduce_settings(quiet, {"proactive": True})
    due = reduce_screen(enabled, text="Build failed with an error", activity="work", now=100)
    assert due["proactive_due"] is True
    assert proactive_allowed(due, gate_for("owner"), now=100) is True
    soon = dict(due)
    soon["last_proactive_at"] = 90
    assert proactive_allowed(soon, gate_for("owner"), now=100) is False
    crowded = dict(due)
    crowded["proactive_times"] = [100 - 10, 100 - 20, 100 - 30]
    assert proactive_allowed(crowded, gate_for("owner"), now=100) is False
    muted = reduce_mute(due, True)
    assert proactive_allowed(muted, gate_for("owner"), now=100) is False
    voice = reduce_heard(due, text="be quiet", channel="mic", now=101)
    assert voice["muted"] is True
    assert voice["inbox"] is None
    speakers = reduce_heard(due, text="mute", channel="system", now=102)
    assert speakers["muted"] is False
    on_call, fullscreen = room_flags("Zoom meeting", activity="work")
    assert on_call is True and fullscreen is False
    _call, game = room_flags("fullscreen", activity="game")
    assert game is True
    windowed, not_full = room_flags("Playing chess", activity="game")
    assert windowed is False and not_full is False
    paused = reduce_pause(due, True)
    assert proactive_allowed(paused, gate_for("owner"), now=200) is False
    assert proactive_allowed(due, gate_for("owner", memorial="posthumous"), now=200) is False

    calls = _Calls(reply="The build failed.")
    _state, view = _run(
        advance_state(due, now=200, audience="owner", turn=calls.turn, execute=calls.execute)
    )
    assert calls.turns[0]["local_only"] is True
    assert "build failed" in view["caption"].lower() or view["caption"]
    shrug = _Calls(reply="…")
    again = reduce_screen(enabled, text="Build failed with an error", activity="work", now=900)
    _state, view = _run(
        advance_state(again, now=900, audience="owner", turn=shrug.turn, execute=shrug.execute)
    )
    assert view["caption"] == ""


def test_state_keeps_no_raw_audio_and_speech_stays_on_loopback(tmp_path: Path):
    dirty = default_state()
    dirty["pcm"] = b"\x00\x01"
    dirty["jpeg"] = "frame"
    save_state(dirty, tmp_path)
    loaded = load_state(tmp_path)
    assert "pcm" not in loaded
    assert "jpeg" not in loaded
    raw = json.loads((tmp_path / "assist_live.json").read_text(encoding="utf-8"))
    assert "pcm" not in raw
    assert "raw_audio" not in raw
    ingest_heard(tmp_path, text="User said: hey C L", channel="mic", paused=True, now=5)
    assert load_state(tmp_path)["listening"] is False
    wav_url = loopback_speak_wav_url("http://127.0.0.1:8010/speak")
    assert wav_url == "http://127.0.0.1:8010/speak.wav"
    try:
        loopback_speak_wav_url("http://192.168.0.16/speak")
    except ValueError as exc:
        assert "box" in str(exc)
    else:
        raise AssertionError("remote speak url was accepted")
    try:
        fetch_chatterbox_wav("hello", url="https://example.com/speak")
    except ValueError:
        pass
    else:
        raise AssertionError("cloud speak was attempted")
    store_wav(tmp_path, "cap_1", b"RIFF....")
    assert take_wav(tmp_path, "cap_1") == b"RIFF...."
    assert take_wav(tmp_path, "cap_1") is None
    assert cloud_fallback_allowed(False) is True
    assert cloud_fallback_allowed(True) is False


def test_runtime_refuses_cloud_before_the_claude_client():
    runtime = (Path(__file__).resolve().parents[1] / "twin_runtime.py").read_text(encoding="utf-8")
    live = (Path(__file__).resolve().parents[1] / "assist_live.py").read_text(encoding="utf-8")
    runner = (Path(__file__).resolve().parents[1] / "assist_live_runner.py").read_text(encoding="utf-8")
    assert "ASSIST_LIVE_LOCAL_ONLY" in runtime
    assert runtime.index("await intercept_crisis") < runtime.index("LlmChat(")
    assert runtime.index("ASSIST_LIVE_LOCAL_ONLY") < runtime.index("LlmChat(")
    assert "llm_provider" not in live
    assert "model_router" not in live
    assert "local_only=True" in runner
    assert "run_twin_turn" in runner


def test_routes_are_owner_only(tmp_path, monkeypatch):
    monkeypatch.setenv("HEIRLOOM_OBSERVER", "1")
    monkeypatch.setenv("HEIRLOOM_OBSERVER_DIR", str(tmp_path))
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "heir",
        "audience": "family",
        "heir_surface": True,
    }
    client = TestClient(app)
    assert client.get("/api/assist/live").status_code == 404
    assert client.post("/api/assist/live/ptt", json={"held": True}).status_code == 404
    assert client.post("/api/assist/live/confirm", json={"id": "act"}).status_code == 404

    app.dependency_overrides[get_current_user] = lambda: {"user_id": "owner", "audience": "owner"}
    saved = client.put("/api/assist/live/settings", json={"twin_name": "C L", "proactive": False})
    assert saved.status_code == 200
    assert saved.json()["wake_phrase"] == "hey C L"
    assert saved.json()["proactive"] is False
    polled = client.get("/api/assist/live")
    assert polled.status_code == 200
    assert polled.json()["listening"] is True
    assert polled.json()["wake_phrase"] == "hey C L"
    (tmp_path / "state.json").write_text('{"paused": true, "reason": "web"}\n', encoding="utf-8")
    paused = client.get("/api/assist/live")
    assert paused.status_code == 200
    assert paused.json()["listening"] is False
    assert client.post("/api/assist/live/mute", json={"muted": True}).json()["muted"] is True
    assert client.post("/api/assist/live/ptt", json={"held": True}).json()["ptt"] is False
