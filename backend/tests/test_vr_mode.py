"""VR preference, gaze summaries, and the heir fence. No headset required."""
from observer_prompt import notes_for_prompt
from observer_store import ObserverStore
from vr_mode import (
    VR_GAZE_SOURCE,
    accept_gaze,
    aggregate_gaze,
    clamp_vr_prefs,
    launch_vr_state,
    owner_vr_allowed,
    plan_enter,
    plan_gaze,
    plan_toggle,
    should_auto_enter,
)


def test_launch_is_off_and_never_auto_enters():
    fresh = launch_vr_state(None, headset_connected=True)
    assert fresh["enabled"] is False
    assert fresh["gaze_enabled"] is False
    assert fresh["session_active"] is False
    assert fresh["auto_enter"] is False
    saved = launch_vr_state(
        {"enabled": True, "gaze_enabled": True, "session_active": True, "origin": [0, 0, 0]},
        headset_connected=True,
    )
    assert saved["enabled"] is True
    assert saved["gaze_enabled"] is True
    assert saved["session_active"] is False
    assert saved["auto_enter"] is False
    assert "origin" not in saved
    assert should_auto_enter(headset_connected=True, enabled=True) is False


def test_toggle_starts_only_on_a_room_gesture():
    prefs = clamp_vr_prefs({"enabled": False, "gaze_enabled": False})
    quiet = plan_toggle(prefs, next_enabled=True, gesture=False, surface="room", session_active=False)
    assert quiet["start_session"] is False
    assert quiet["reason"] == "no-gesture"
    settings = plan_toggle(prefs, next_enabled=True, gesture=True, surface="settings", session_active=False)
    assert settings["start_session"] is False
    assert settings["prefs"]["enabled"] is True
    room = plan_toggle(prefs, next_enabled=True, gesture=True, surface="room", session_active=False)
    assert room["start_session"] is True
    assert room["reason"] == "user-gesture"
    off = plan_toggle(room["prefs"], next_enabled=False, gesture=True, surface="room", session_active=True)
    assert off["end_session"] is True
    assert off["prefs"]["enabled"] is False
    assert off["start_session"] is False


def test_saved_on_still_needs_a_click_to_enter():
    launched = launch_vr_state({"enabled": True, "gaze_enabled": False})
    assert launched["session_active"] is False
    assert plan_enter(enabled=True, gesture=False, session_active=False)["start_session"] is False
    entered = plan_enter(enabled=True, gesture=True, session_active=False)
    assert entered["start_session"] is True
    assert plan_enter(enabled=False, gesture=True, session_active=False)["reason"] == "off"


def test_gaze_toggle_does_not_start_vr_and_defaults_off():
    decision = plan_gaze({"enabled": False, "gaze_enabled": False}, next_gaze=True, gesture=True)
    assert decision["start_session"] is False
    assert decision["prefs"]["gaze_enabled"] is True
    assert decision["prefs"]["enabled"] is False
    assert plan_gaze({"enabled": True}, next_gaze=True, gesture=False)["reason"] == "no-gesture"


def test_gaze_aggregation_drops_raw_samples_and_short_glances():
    rows = aggregate_gaze(
        [
            {"area": "twin", "dwell_ms": 250, "origin": [0, 1, 0], "direction": [0, 0, -1]},
            {"area": "twin", "dwell_ms": 800},
            {"area": "floor", "dwell_ms": 1200, "pupil": 0.4},
            {"area": "secret", "dwell_ms": 9000},
            {"area": "room", "dwell_ms": 100},
        ]
    )
    assert rows == [
        {"area": "twin", "dwell_ms": 1050},
        {"area": "floor", "dwell_ms": 1200},
    ]
    assert all("origin" not in row and "pupil" not in row for row in rows)


def test_gaze_opt_in_pause_and_heir_fence(tmp_path):
    samples = [{"area": "twin", "dwell_ms": 2000}, {"area": "seat", "dwell_ms": 900}]
    heir = accept_gaze(samples, audience="heir", gaze_enabled=True, observer_on=True)
    assert heir["status"] == 404
    assert heir["stored"] is False
    caller = accept_gaze(samples, audience="owner", heir_surface=True, gaze_enabled=True, observer_on=True)
    assert caller["reason"] == "heir"
    opted_out = accept_gaze(samples, audience="owner", gaze_enabled=False, observer_on=True)
    assert opted_out["stored"] is False
    assert opted_out["reason"] == "opt-in-off"
    paused = accept_gaze(samples, audience="owner", gaze_enabled=True, paused=True, observer_on=True)
    assert paused["reason"] == "paused"
    assert paused["stored"] is False
    off = accept_gaze(samples, audience="owner", gaze_enabled=True, observer_on=False)
    assert off["reason"] == "observer-off"

    store = ObserverStore(tmp_path)
    store.set_paused(True, "web")
    blocked = store.add_gaze_note(accept_gaze(samples, audience="owner", gaze_enabled=True, observer_on=True)["note"])
    assert blocked["stored"] is False
    assert store.read_notes() == []

    store.set_paused(False, "")
    decision = accept_gaze(samples, audience="owner", gaze_enabled=True, observer_on=True)
    assert decision["stored"] is True
    written = store.add_gaze_note(decision["note"])
    assert written["stored"] is True
    note = store.read_notes()[0]
    assert note["source"] == VR_GAZE_SOURCE
    assert "origin" not in note
    assert "direction" not in note
    blob = str(note)
    assert "pupil" not in blob
    assert note["text"].startswith("In VR, looked at the twin")
    store.apply_feedback(note["id"], "thats_me")
    assert store.visible_notes(audience="heir") == []
    owner_view = store.visible_notes(audience="owner")
    assert owner_view[0]["source"] == VR_GAZE_SOURCE
    assert notes_for_prompt(store.read_notes(), audience="owner") == []
    assert notes_for_prompt(store.read_notes(), audience="heir") == []
    assert owner_vr_allowed(audience="heir") is False
    assert owner_vr_allowed(audience="owner") is True
