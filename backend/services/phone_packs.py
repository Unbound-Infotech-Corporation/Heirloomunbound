"""Which desktop abilities the phone companion is allowed to offer.

Rule: if it isn't on at the desktop, don't offer it on the phone — the owner
isn't using it, and packing it onto a phone just wastes space.

Exception: phone calls. Answering and placing calls is the reason the
companion exists on a handset, so that pack is always available.
"""
from __future__ import annotations

PHONE_CALLS = {
    "id": "phone_calls",
    "name": "Phone calls",
    "tagline": "Answer incoming calls as your twin, and place calls when you want.",
    "icon": "phone",
    "category": "phone",
    "requires_companion": False,
    "always_on": True,
}


def phone_enabled_ids(row: dict | None) -> set[str]:
    """IDs the owner turned on for the phone.

    `phone_calls` defaults ON unless they explicitly switched it off.
    """
    row = row or {}
    enabled = set(row.get("enabled") or [])
    if "phone_calls" not in (row.get("explicit_off") or []):
        enabled.add("phone_calls")
    return enabled


def visible_integrations(
    abilities: list[dict],
    desktop_states: dict,
    phone_row: dict | None = None,
) -> list[dict]:
    """Phone-calls pack first, then every ability that is actually on at the desktop."""
    enabled_on_phone = phone_enabled_ids(phone_row)
    items: list[dict] = [{
        **PHONE_CALLS,
        "desktop_enabled": True,
        "phone_enabled": "phone_calls" in enabled_on_phone,
        "locked": False,
        "reason": "The reason this app exists on a phone.",
    }]
    for ability in abilities:
        state = desktop_states.get(ability["id"]) or {}
        if not state.get("enabled"):
            continue
        items.append({
            "id": ability["id"],
            "name": ability["name"],
            "tagline": ability["tagline"],
            "icon": ability["icon"],
            "category": ability["category"],
            "requires_companion": ability.get("requires_companion", False),
            "always_on": False,
            "desktop_enabled": True,
            "phone_enabled": ability["id"] in enabled_on_phone,
            "locked": False,
            "reason": "On at the desktop, so it's available here. Leave it off to save space.",
        })
    return items
