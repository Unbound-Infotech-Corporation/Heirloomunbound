"""Smart home safety, local commands, and discovery."""
from __future__ import annotations

import pytest

from smart_home import (
    SmartHomeRefused,
    assert_lan_target,
    classify_discovery,
    clamp_setpoint,
    ha_service,
    ha_token_url,
    hue_set,
    kasa_datagram,
    kasa_decrypt,
    matter_plan,
    prepare_action,
    shelly_set,
    wiz_pilot,
)


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def request(self, method, url, json_body=None, headers=None):
        self.calls.append({"method": method, "url": url, "json": json_body, "headers": headers})
        return {"ok": True}


def test_heat_and_cool_stay_in_a_family_range():
    heat = clamp_setpoint("heat", 95)
    assert heat["limited"] is True
    assert heat["applied"] == 74
    cool = clamp_setpoint("cool", 50)
    assert cool["applied"] == 68
    mild = clamp_setpoint("heat", 70)
    assert mild["limited"] is False
    assert mild["applied"] == 70
    celsius = clamp_setpoint("heat", 40, "C")
    assert celsius["limited"] is True
    assert celsius["applied"] <= 23.5


def test_reads_are_free_and_changes_wait():
    light = {"id": "light.hall", "name": "Hall light", "kind": "light"}
    reading = prepare_action(light, "read")
    assert reading["executed"] is True
    assert reading["needs_approval"] is False
    waiting = prepare_action(light, "off")
    assert waiting["needs_approval"] is True
    assert waiting["executed"] is False
    done = prepare_action(light, "off", approved=True)
    assert done["executed"] is True


def test_always_allow_does_not_turn_off_critical_devices():
    fridge = {"id": "plug.fridge", "name": "Kitchen fridge", "kind": "plug"}
    blocked = prepare_action(fridge, "off", always_allow=True, approved=True)
    assert blocked["executed"] is False
    assert blocked["critical"] is True
    allowed = prepare_action(fridge, "off", approved=True, critical_confirm=True)
    assert allowed["executed"] is True
    thermostat = {"id": "climate.hall", "name": "Hall thermostat", "kind": "thermostat"}
    off = prepare_action(thermostat, "thermostat_off", always_allow=True, approved=True)
    assert off["executed"] is False
    heat = prepare_action(thermostat, "set_heat", 95, always_allow=True)
    assert heat["executed"] is True
    assert heat["applied_value"] == 74
    assert heat["limited"] is True


def test_commands_stay_on_the_lan():
    assert assert_lan_target("192.168.1.50") == "192.168.1.50"
    assert assert_lan_target("shelly1") == "shelly1"
    with pytest.raises(SmartHomeRefused):
        assert_lan_target("8.8.8.8")
    with pytest.raises(SmartHomeRefused):
        assert_lan_target("evil.example")
    with pytest.raises(SmartHomeRefused):
        assert_lan_target("[2001:4860:4860::8888]:8123")
    assert assert_lan_target("[fe80::1]") == "[fe80::1]"
    assert ha_token_url("homeassistant.local:8123") == "http://homeassistant.local:8123/profile/security"
    transport = FakeTransport()
    public = shelly_set(transport, "192.168.1.40", True)
    assert public["authorization"] == ""
    assert transport.calls[0]["json"]["method"] == "Switch.Set"
    username = "hue-user-secret"
    public = hue_set(transport, "192.168.1.30", username, "1", True)
    assert username not in public["summary"]
    wiz = wiz_pilot("wiz-bulb.local", False)
    assert wiz["port"] == 38899
    assert wiz["payload"]["params"]["state"] is False
    body = kasa_decrypt(kasa_datagram(True))
    assert '"state":1' in body
    token = "ha-long-lived-token"
    public = ha_service(transport, "http://127.0.0.1:8123", token, "light", "turn_on", "light.hall")
    assert token not in public["summary"]
    assert public["authorization"] == ""
    assert transport.calls[-1]["headers"]["Authorization"].endswith(token)
    with pytest.raises(SmartHomeRefused):
        ha_service(transport, "https://example.com", token, "light", "turn_on", "light.hall")


def test_ssdp_replies_become_devices():
    from smart_home import parse_ssdp_message, scan_ssdp

    raw = "\r\n".join([
        "HTTP/1.1 200 OK",
        "ST: urn:Belkin:device:controllee:1",
        "USN: uuid:wemo-1",
        "SERVER: Unspecified, UPnP/1.0, Unspecified",
        "LOCATION: http://192.168.1.40:49153/setup.xml",
        "",
    ])
    record = parse_ssdp_message(raw)
    assert record["host"] == "192.168.1.40"
    found = scan_ssdp(lambda _payload, _timeout: [raw.encode()])
    assert found[0]["vendor"] == "wemo"
    assert found[0]["local"] is True
    hue = classify_discovery({"source": "mdns", "service": "_hue._tcp.local", "name": "Bridge", "host": "192.168.1.8"})
    assert hue["vendor"] == "hue"
    matter = classify_discovery({"source": "mdns", "service": "_matter._tcp.local", "name": "Bulb"})
    assert matter["matter"] is True
    home = classify_discovery({"source": "mdns", "service": "_home-assistant._tcp.local", "host": "homeassistant.local"})
    assert home["home_assistant"] is True
    wemo = classify_discovery({"source": "ssdp", "st": "urn:Belkin:device:controllee:1", "name": "Wemo"})
    assert wemo["vendor"] == "wemo"
    assert ha_token_url("homeassistant.local").endswith("/profile/security")
    assert matter_plan()["cloud"] is False
