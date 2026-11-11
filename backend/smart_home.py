"""Local smart-home control for the owner.

Reads are free. Changes wait for Confirm the first time, then an optional
per-device always-allow. Turning off a critical device (fridge, medical,
sump, furnace, and the like) or switching a thermostat off always asks again.
Always-allow does not cover those. Heat and cool setpoints are clamped to a
family range.

Commands stay on the home network. Nothing here sends owner memories.
Discovery parsers classify mDNS and SSDP records. They do not scan the live
Twin Box network by themselves.

Vendors: ecobee, Nest, Honeywell, Kasa, Tapo, Shelly, Wemo, Meross, Hue,
LIFX, Govee, WiZ, Matter, and Home Assistant as an optional bridge.
"""
from __future__ import annotations

import ipaddress
import json
from typing import Any
from urllib.parse import urlparse

from owner_privacy import is_private_http_url

HEAT_F = (60, 74)
COOL_F = (68, 78)

CRITICAL_WORDS = (
    "fridge",
    "freezer",
    "sump",
    "oxygen",
    "medical",
    "furnace",
    "water heater",
    "water-heater",
    "well pump",
    "smoke",
    "carbon monoxide",
    "cpap",
)

READ_ACTIONS = frozenset({"read", "state"})
OFF_ACTIONS = frozenset({"off", "turn_off", "thermostat_off"})

MDNS_VENDORS = {
    "_hue._tcp": "hue",
    "_shelly._tcp": "shelly",
    "_matter._tcp": "matter",
    "_hap._tcp": "homekit",
    "_lifx._tcp": "lifx",
    "_lifx._udp": "lifx",
    "_wemo._tcp": "wemo",
    "_kasa._tcp": "kasa",
    "_tplink-smarthome._tcp": "kasa",
    "_home-assistant._tcp": "home_assistant",
    "_home-assistant-ios._tcp": "home_assistant",
    "_googlecast._tcp": "cast",
    "_wiz._tcp": "wiz",
}


class SmartHomeRefused(Exception):
    """The command would leave the home network or skip a safety check."""


class Transport:
    """HTTP stand-in. Tests pass a fake. A live client can wrap this later."""

    def request(
        self,
        method: str,
        url: str,
        json_body: dict | None = None,
        headers: dict | None = None,
    ) -> dict:
        raise NotImplementedError


def is_critical(name: str, role: str = "") -> bool:
    blob = f"{name} {role}".lower()
    return any(word in blob for word in CRITICAL_WORDS)


def clamp_setpoint(mode: str, value: float, unit: str = "F") -> dict[str, Any]:
    """Clamp heat and cool to a family range. Extremes are not applied."""
    unit_name = (unit or "F").strip().upper()
    if unit_name == "C":
        requested_f = value * 9.0 / 5.0 + 32.0
    else:
        unit_name = "F"
        requested_f = float(value)
    low, high = HEAT_F if mode == "heat" else COOL_F
    applied_f = min(high, max(low, requested_f))
    limited = abs(applied_f - requested_f) > 0.05
    if unit_name == "C":
        applied = round((applied_f - 32.0) * 5.0 / 9.0, 1)
        show_low = round((low - 32.0) * 5.0 / 9.0, 1)
        show_high = round((high - 32.0) * 5.0 / 9.0, 1)
    else:
        applied = round(applied_f, 1)
        show_low, show_high = low, high
    reason = ""
    if limited:
        kind = "Heat" if mode == "heat" else "Cooling"
        reason = (
            f"{kind} stays between {show_low}° and {show_high}° "
            "so the house is not pushed to an extreme."
        )
    return {
        "requested": value,
        "applied": applied,
        "unit": unit_name,
        "limited": limited,
        "reason": reason,
    }


def prepare_action(
    device: dict[str, Any],
    action: str,
    value: float | None = None,
    *,
    unit: str = "F",
    always_allow: bool = False,
    approved: bool = False,
    critical_confirm: bool = False,
) -> dict[str, Any]:
    """Decide whether a device action may run. This does not perform it."""
    kind = (device.get("kind") or "").strip().lower()
    critical = bool(device.get("critical")) or is_critical(
        str(device.get("name") or ""), str(device.get("role") or ""),
    )
    result: dict[str, Any] = {
        "device_id": device.get("id") or "",
        "action": action,
        "allow": False,
        "executed": False,
        "needs_approval": False,
        "critical": critical,
        "limited": False,
        "applied_value": value,
        "reason": "",
        "read": action in READ_ACTIONS,
    }
    if action in READ_ACTIONS:
        result["allow"] = True
        result["executed"] = True
        result["reason"] = "Reading is always allowed."
        return result
    if kind == "thermostat" and action in {"set_heat", "set_cool"} and value is not None:
        mode = "heat" if action == "set_heat" else "cool"
        clamped = clamp_setpoint(mode, float(value), unit)
        result["applied_value"] = clamped["applied"]
        result["limited"] = clamped["limited"]
        result["reason"] = clamped["reason"]
    turning_off = action in OFF_ACTIONS
    hard_stop = (critical and turning_off) or (kind == "thermostat" and action == "thermostat_off")
    if hard_stop:
        result["critical"] = True
        result["needs_approval"] = True
        if not (approved and critical_confirm):
            result["reason"] = (
                "This looks important. Confirm before turning it off. "
                "Always-allow does not cover it."
            )
            return result
        result["allow"] = True
        result["executed"] = True
        result["needs_approval"] = False
        result["reason"] = "Confirmed off."
        return result
    if always_allow:
        result["allow"] = True
        result["executed"] = True
        extra = "Allowed for this device."
        result["reason"] = (result["reason"] + " " + extra).strip()
        return result
    if not approved:
        result["needs_approval"] = True
        extra = "Waiting for Confirm."
        result["reason"] = (result["reason"] + " " + extra).strip()
        return result
    result["allow"] = True
    result["executed"] = True
    if not result["reason"]:
        result["reason"] = "Confirmed."
    return result


def assert_lan_target(host: str) -> str:
    """Accept a home-network host. Refuse public internet hosts."""
    raw = (host or "").strip()
    if not raw or "://" in raw or " " in raw or len(raw) > 253:
        raise SmartHomeRefused("That does not look like a device on your home network.")
    name = raw
    if name.count(":") == 1 and "." in name:
        name = name.rsplit(":", 1)[0]
    name = name.strip("[]")
    try:
        ip = ipaddress.ip_address(name)
    except ValueError:
        ip = None
    if ip is not None:
        if not (ip.is_private or ip.is_loopback or ip.is_link_local):
            raise SmartHomeRefused("Smart home commands stay on your home network.")
        return raw
    lowered = name.lower().rstrip(".")
    if lowered == "localhost" or lowered.endswith(".local") or lowered.endswith(".lan") or "." not in lowered:
        return raw
    raise SmartHomeRefused("Use a home-network address such as 192.168.x.x or a .local name.")


def classify_discovery(record: dict[str, Any]) -> dict[str, Any]:
    """Map one mDNS or SSDP record to a vendor. Unknown records stay unknown."""
    source = (record.get("source") or "").strip().lower()
    service = (record.get("service") or record.get("st") or "").strip().lower()
    server = (record.get("server") or "").lower()
    name = record.get("name") or ""
    vendor = "unknown"
    if source == "ssdp" or service.startswith("urn:"):
        if "belkin" in service or "belkin" in server or "wemo" in name.lower():
            vendor = "wemo"
        elif "hue" in server or "philips" in server:
            vendor = "hue"
        elif "shelly" in server:
            vendor = "shelly"
    else:
        for key, label in MDNS_VENDORS.items():
            if key in service:
                vendor = label
                break
    return {
        "vendor": vendor,
        "name": name,
        "host": record.get("host") or "",
        "service": service,
        "local": True,
        "home_assistant": vendor == "home_assistant",
        "matter": vendor == "matter",
    }


def ha_token_url(host: str) -> str:
    target = assert_lan_target(host)
    base = f"http://{target}:8123"
    return base.rstrip("/") + "/profile/security"


def _public_call(vendor: str, summary: str) -> dict[str, Any]:
    return {"vendor": vendor, "summary": summary, "authorization": ""}


def shelly_set(transport: Transport, host: str, on: bool) -> dict[str, Any]:
    target = assert_lan_target(host)
    transport.request(
        "POST",
        f"http://{target}/rpc",
        {"id": 1, "method": "Switch.Set", "params": {"id": 0, "on": bool(on)}},
        None,
    )
    return _public_call("shelly", "Turned the Shelly on." if on else "Turned the Shelly off.")


def hue_set(
    transport: Transport,
    host: str,
    username: str,
    light_id: str,
    on: bool,
) -> dict[str, Any]:
    target = assert_lan_target(host)
    if not username or not light_id:
        raise SmartHomeRefused("The Hue bridge needs the local link and a light.")
    transport.request(
        "PUT",
        f"http://{target}/api/{username}/lights/{light_id}/state",
        {"on": bool(on)},
        None,
    )
    return _public_call("hue", "Turned the Hue light on." if on else "Turned the Hue light off.")


def wiz_pilot(host: str, on: bool) -> dict[str, Any]:
    """WiZ local UDP payload. The caller sends it to port 38899."""
    target = assert_lan_target(host)
    return {
        "vendor": "wiz",
        "host": target,
        "port": 38899,
        "payload": {"method": "setPilot", "params": {"state": bool(on)}},
        "summary": "Turned the WiZ light on." if on else "Turned the WiZ light off.",
    }


def kasa_encrypt(payload: str) -> bytes:
    key = 171
    out = bytearray()
    for byte in payload.encode("utf-8"):
        key = key ^ byte
        out.append(key)
    return bytes(out)


def kasa_decrypt(data: bytes) -> str:
    key = 171
    out = bytearray()
    for byte in data:
        out.append(key ^ byte)
        key = byte
    return out.decode("utf-8")


def kasa_datagram(on: bool) -> bytes:
    state = 1 if on else 0
    body = json.dumps({"system": {"set_relay_state": {"state": state}}}, separators=(",", ":"))
    return kasa_encrypt(body)


def ha_service(
    transport: Transport,
    base_url: str,
    token: str,
    domain: str,
    service: str,
    entity_id: str,
) -> dict[str, Any]:
    if not is_private_http_url(base_url):
        raise SmartHomeRefused("Home Assistant stays on your home network.")
    if not token:
        raise SmartHomeRefused("Paste the Home Assistant token first.")
    root = base_url.rstrip("/")
    transport.request(
        "POST",
        f"{root}/api/services/{domain}/{service}",
        {"entity_id": entity_id},
        {"Authorization": f"Bearer {token}"},
    )
    return _public_call("home_assistant", f"Asked Home Assistant to {service.replace('_', ' ')} {entity_id}.")


def matter_plan() -> dict[str, Any]:
    return {
        "vendor": "matter",
        "control": "home_assistant",
        "summary": (
            "Matter devices are commissioned on your network. "
            "Control them through Home Assistant in this update."
        ),
        "cloud": False,
    }


def receipt_summary(decision: dict[str, Any]) -> str:
    if decision.get("needs_approval"):
        return decision.get("reason") or "Waiting for Confirm."
    if decision.get("limited"):
        return decision.get("reason") or "Adjusted to a safe temperature."
    return decision.get("reason") or "Done."


def host_of(url: str) -> str:
    return urlparse(url).hostname or ""
