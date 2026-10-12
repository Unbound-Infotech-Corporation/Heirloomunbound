"""One frame's decision. Privacy runs before the model and before storage."""
from __future__ import annotations

from typing import Any, Callable, Optional

from observer_learn import classify_activity
from observer_privacy import hotkey_detected, redact_stored_text, screen_is_sensitive

ModelFn = Callable[[dict], Any]


def consider_frame(
    *,
    ocr: str,
    app: str = "",
    title: str = "",
    model: Optional[ModelFn] = None,
    hotkey_phrase: str = "",
) -> dict:
    """Drop sensitive frames with the model uncalled. Allowed text is redacted."""
    visible = "\n".join(part for part in (app, title, ocr) if part)
    if hotkey_detected(visible, hotkey_phrase):
        return {
            "dropped": True,
            "reason": "hotkey",
            "model_called": False,
            "store_text": False,
            "latch_pause": True,
            "activity": "",
            "game": "",
            "text": "",
        }
    decision = screen_is_sensitive(ocr, app_hint=f"{app}\n{title}")
    if decision.drop:
        return {
            "dropped": True,
            "reason": decision.reason,
            "model_called": False,
            "store_text": False,
            "latch_pause": False,
            "activity": "",
            "game": "",
            "text": "",
        }
    activity, game = classify_activity(f"{title}\n{ocr}", app)
    summary = ""
    called = False
    if model is not None:
        called = True
        raw = model({"ocr": ocr, "app": app, "title": title})
        if isinstance(raw, dict):
            activity = str(raw.get("activity") or activity)
            game = str(raw.get("game") or game)
            summary = str(raw.get("summary") or "")
        elif isinstance(raw, str):
            summary = raw
    excerpt = redact_stored_text(summary or ocr)
    return {
        "dropped": False,
        "reason": "",
        "model_called": called,
        "store_text": True,
        "latch_pause": False,
        "activity": activity,
        "game": game,
        "text": excerpt,
    }
