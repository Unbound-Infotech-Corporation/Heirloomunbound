"""Room facts for the owner Twin. Heirs receive an empty string."""
from __future__ import annotations

from typing import Optional

from owner_pairing import is_owner_audience


def presence_prompt_block(status: Optional[dict], *, audience: str, enabled: bool = True) -> str:
    if not enabled or not is_owner_audience(audience):
        return ""
    payload = status or {}
    present = payload.get("present") or []
    if not present:
        return (
            "The room cameras do not see anyone you have taught. "
            "Do not greet a person by name."
        )
    lines = ["People in the room right now:"]
    for person in present:
        if not isinstance(person, dict):
            continue
        name = str(person.get("name") or "").strip()
        if not name:
            continue
        relation = str(person.get("relationship") or "").strip()
        if relation:
            lines.append(f"- {name} ({relation})")
        else:
            lines.append(f"- {name}")
    if len(lines) == 1:
        return (
            "The room cameras do not see anyone you have taught. "
            "Do not greet a person by name."
        )
    lines.append("If someone just arrived, you can say welcome back. Do not invent anyone who is not listed.")
    return "\n".join(lines)


def attach_presence_context(*, audience: str) -> str:
    if not is_owner_audience(audience):
        return ""
    try:
        from presence_store import presence_enabled, status_public

        if not presence_enabled():
            return ""
        status = status_public()
    except OSError:
        return ""
    return presence_prompt_block(status, audience=audience, enabled=True)
