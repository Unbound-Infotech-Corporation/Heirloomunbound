"""Classify first-run vendor screens so the stay-on-top coach can auto-advance.

Heirloom looks at a screenshot the dedicated PC already captured (same path
as twin `see_screen`). It only names the *kind* of page. It never extracts
API keys, passwords, or captcha answers, and it never drives vendor DOM.
"""
from __future__ import annotations

import json
import re
from typing import Optional

COACH_STEPS = ("create_account", "verify_email", "find_key", "paste_key")
SCENES = frozenset(
    {
        "signup_form",
        "captcha",
        "check_email",
        "email_inbox",
        "email_verified",
        "logged_in_dashboard",
        "api_keys_page",
        "api_key_visible",
        "unknown",
    }
)

# current_step → scene → later step to jump to (never backwards).
_ADVANCE = {
    "create_account": {
        "check_email": "verify_email",
        "email_inbox": "verify_email",
        "email_verified": "find_key",
        "logged_in_dashboard": "find_key",
        "api_keys_page": "find_key",
        "api_key_visible": "paste_key",
    },
    "verify_email": {
        "email_verified": "find_key",
        "logged_in_dashboard": "find_key",
        "api_keys_page": "find_key",
        "api_key_visible": "paste_key",
    },
    "find_key": {
        "api_keys_page": "paste_key",
        "api_key_visible": "paste_key",
    },
}

_HINTS = {
    ("create_account", "signup_form"): (
        "Paste your email if the box is empty, then click I'm not a robot."
    ),
    ("create_account", "captcha"): (
        "Complete their robot check — Heirloom cannot click it."
    ),
    ("create_account", "check_email"): "They want you to verify — continue when the inbox is open.",
    ("verify_email", "email_inbox"): "Open their message and click Verify / Confirm.",
    ("verify_email", "check_email"): "Stay in the inbox until you click their verify link.",
    ("find_key", "logged_in_dashboard"): "Open API Keys — use Re-open page if you lost the tab.",
    ("find_key", "api_keys_page"): "Create or copy a key, then paste it into Heirloom.",
    ("paste_key", "api_key_visible"): (
        "Copy the key on their page, then paste it into this Heirloom box. "
        "We never read it off the screen."
    ),
    ("paste_key", "api_keys_page"): "Paste the key into Heirloom — not into chat, not into the guide as a screenshot.",
}

_KEYISH = re.compile(
    r"(sk_[A-Za-z0-9_\-]{8,}|key_id\s*:\s*\S+|api[_-]?key\s*[:=]\s*\S+)",
    re.I,
)
_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)
_JSON_OBJECT = re.compile(r"\{[^{}]*\}", re.S)


def step_index(step_id: str) -> int:
    try:
        return COACH_STEPS.index(step_id)
    except ValueError:
        return 0


def sanitize_hint(hint: str | None) -> str:
    text = " ".join(str(hint or "").split())
    if not text:
        return ""
    if _KEYISH.search(text):
        return (
            "Copy the key on their page, then paste it into Heirloom. "
            "We never read it off the screen."
        )
    return text[:240]


def hint_for_scene(current_step: str, scene: str, model_hint: str = "") -> str:
    canned = _HINTS.get((current_step, scene)) or ""
    return sanitize_hint(canned or model_hint)


def next_step_for_scene(current_step: str, scene: str) -> Optional[str]:
    """Return a later coach step, or None to stay. Never scrapes a key."""
    if current_step not in COACH_STEPS or scene not in SCENES:
        return None
    if current_step == "paste_key":
        return None
    target = (_ADVANCE.get(current_step) or {}).get(scene)
    if not target:
        return None
    if step_index(target) <= step_index(current_step):
        return None
    return target


def strip_data_url(image_b64: str) -> str:
    raw = (image_b64 or "").strip()
    if raw.lower().startswith("data:") and "," in raw:
        return raw.split(",", 1)[1]
    return raw


def parse_scene_payload(text: str) -> dict:
    blob = (text or "").strip()
    if not blob:
        return {"scene": "unknown", "hint": ""}
    fenced = _JSON_FENCE.search(blob)
    if fenced:
        blob = fenced.group(1)
    else:
        match = _JSON_OBJECT.search(blob)
        if match:
            blob = match.group(0)
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return {"scene": "unknown", "hint": ""}
    if not isinstance(data, dict):
        return {"scene": "unknown", "hint": ""}
    scene = str(data.get("scene") or "unknown").strip().lower()
    if scene not in SCENES:
        scene = "unknown"
    return {"scene": scene, "hint": sanitize_hint(data.get("hint"))}


def observe_result(
    *,
    current_step: str,
    scene: str,
    hint: str = "",
    watching: bool = True,
) -> dict:
    step = current_step if current_step in COACH_STEPS else "create_account"
    clean_scene = scene if scene in SCENES else "unknown"
    advance = next_step_for_scene(step, clean_scene)
    return {
        "scene": clean_scene,
        "hint": hint_for_scene(step, clean_scene, hint),
        "current_step": step,
        "advance_to_step": advance,
        "watching": watching,
    }


async def classify_vendor_screen(
    *,
    image_b64: str,
    service_label: str,
    current_step: str,
) -> dict:
    """Vision classify. Deletes nothing on disk — caller must not persist the image."""
    from deps import EMERGENT_LLM_KEY

    if not (EMERGENT_LLM_KEY or "").strip():
        return observe_result(
            current_step=current_step,
            scene="unknown",
            hint="Screen watch needs a vision key. Use Continue, or pick Maximum so local llava can help later.",
            watching=False,
        )
    raw = strip_data_url(image_b64)
    if not raw or len(raw) < 32:
        return observe_result(
            current_step=current_step,
            scene="unknown",
            hint="No screenshot yet — keep the vendor page in front.",
            watching=False,
        )
    if len(raw) > 2_000_000:
        return observe_result(
            current_step=current_step,
            scene="unknown",
            hint="Screenshot was too large. Use Continue.",
            watching=False,
        )
    prompt = (
        f"Vendor: {service_label}. Expected Heirloom step: {current_step}.\n"
        "Name the kind of page. Reply JSON only:\n"
        '{"scene":"signup_form","hint":"one short sentence"}\n'
        "scene must be one of: signup_form, captcha, check_email, email_inbox, "
        "email_verified, logged_in_dashboard, api_keys_page, api_key_visible, unknown.\n"
        "Never repeat API keys, passwords, emails' full bodies, or captcha text. "
        "If a secret is visible, scene=api_key_visible and tell them to paste it into Heirloom."
    )
    try:
        from emergentintegrations.llm.chat import ImageContent, LlmChat, StreamDone, TextDelta, UserMessage

        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id="heirloom_vendor_coach",
            system_message=(
                "You classify a first-run vendor setup screenshot for Heirloom. "
                "Return JSON only. Never transcribe secrets."
            ),
        ).with_model("anthropic", "claude-sonnet-4-6")
        text = ""
        async for ev in chat.stream_message(
            UserMessage(text=prompt, file_contents=[ImageContent(image_base64=raw)])
        ):
            if isinstance(ev, TextDelta):
                text += ev.content
            elif isinstance(ev, StreamDone):
                break
        parsed = parse_scene_payload(text)
    except Exception:  # noqa: BLE001 — fail open; human Continue still works
        return observe_result(
            current_step=current_step,
            scene="unknown",
            hint="Couldn't read the screen. Click Continue when you have finished this step.",
            watching=False,
        )
    return observe_result(
        current_step=current_step,
        scene=parsed["scene"],
        hint=parsed.get("hint") or "",
        watching=True,
    )
