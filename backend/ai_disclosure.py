"""Label outbound owner messages as AI-assisted.

Off unless ``HEIRLOOM_AI_DISCLOSURE=1``. The Twin Box installer turns it on.
The label is written into the approval payload, so the owner sees it on the
card before anything is sent. Approving still sends that exact payload.
"""
from __future__ import annotations

import os
from typing import Any, Optional

AI_DISCLOSURE = (
    "This message was drafted with Heirloom, an AI, and sent after the owner approved it."
)

_ON = frozenset({"1", "true", "yes", "on"})


def disclosure_enabled(raw: Optional[str] = None) -> bool:
    if raw is None:
        raw = os.environ.get("HEIRLOOM_AI_DISCLOSURE", "")
    return (raw or "").strip().lower() in _ON


def _append(text: str) -> str:
    if AI_DISCLOSURE in text:
        return text
    base = text.rstrip()
    if not base:
        return AI_DISCLOSURE
    return f"{base}\n\n{AI_DISCLOSURE}"


def label_outbound_payload(
    payload: dict[str, Any],
    *,
    action_kind: str,
    enabled: Optional[bool] = None,
) -> dict[str, Any]:
    """Copy ``payload`` and append the disclosure to send/post text.

    Delete and spend are not messages. When the flag is off the payload is
    returned unchanged.
    """
    if enabled is None:
        enabled = disclosure_enabled()
    if not enabled or action_kind not in {"send", "post"}:
        return payload
    out = dict(payload)
    if isinstance(out.get("body"), str):
        out["body"] = _append(out["body"])
    elif isinstance(out.get("text"), str):
        out["text"] = _append(out["text"])
    else:
        out["text"] = AI_DISCLOSURE
    return out
