"""Tests for the Multi-provider AI Router + Usage Tracking (iteration 36)."""
import os
import time
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://voice-clone-hub-20.preview.emergentagent.com").rstrip("/")
API = f"{BASE}/api"
TOKEN = "test_routing_session"
HDRS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

EXPECTED_PROVIDERS = {"emergent", "openai", "anthropic", "gemini", "groq", "xai", "deepseek"}
EXPECTED_TASKS = {"chat", "interview", "tools", "cheap", "long_context", "embeddings"}


# ----- Catalog -----
def test_catalog_shape():
    r = requests.get(f"{API}/routing/catalog", headers=HDRS, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    pids = {p["id"] for p in data["providers"]}
    tids = {t["id"] for t in data["tasks"]}
    assert pids == EXPECTED_PROVIDERS
    assert tids == EXPECTED_TASKS
    # emergent must be BYOK=false
    emg = next(p for p in data["providers"] if p["id"] == "emergent")
    assert emg["byok"] is False
    # pricing present
    assert isinstance(data["pricing"], list) and len(data["pricing"]) > 0
    assert isinstance(data["default_fallback_order"], list)


# ----- Config -----
def test_get_config_defaults_and_no_key_leak():
    r = requests.get(f"{API}/routing/config", headers=HDRS, timeout=30)
    assert r.status_code == 200, r.text
    cfg = r.json()
    assert set(cfg["providers"].keys()) == EXPECTED_PROVIDERS
    assert set(cfg["task_routes"].keys()) == EXPECTED_TASKS
    # emergent enabled true by default; others enabled false by default (unless user modified)
    emg = cfg["providers"]["emergent"]
    assert emg["enabled"] is True
    # CRITICAL: never leak raw api_key; always has_key boolean + empty string
    for pid, pcfg in cfg["providers"].items():
        assert pcfg.get("api_key", "") == "", f"{pid} leaked api_key"
        assert "has_key" in pcfg


def test_put_config_saves_and_preserves_keys():
    # First: set a fake key + enable openai + set budget
    payload = {
        "providers": {
            pid: {
                "enabled": pid in ("emergent", "openai"),
                "api_key": "sk-TEST_placeholder_key_123" if pid == "openai" else "",
                "default_model": "",
                "monthly_budget_usd": 5.0 if pid == "openai" else 0.0,
            }
            for pid in EXPECTED_PROVIDERS
        },
        "task_routes": {
            "chat": "emergent", "interview": "emergent", "tools": "emergent",
            "cheap": "groq", "long_context": "gemini", "embeddings": "openai",
        },
        "fallback_order": ["emergent", "openai", "anthropic", "gemini", "groq", "xai", "deepseek"],
    }
    r = requests.put(f"{API}/routing/config", json=payload, headers=HDRS, timeout=30)
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["providers"]["openai"]["has_key"] is True
    assert saved["providers"]["openai"]["api_key"] == ""  # never returned
    assert saved["providers"]["openai"]["monthly_budget_usd"] == 5.0

    # Now: send empty api_key strings — should PRESERVE previously stored key
    payload["providers"]["openai"]["api_key"] = ""
    payload["providers"]["openai"]["monthly_budget_usd"] = 7.5
    r2 = requests.put(f"{API}/routing/config", json=payload, headers=HDRS, timeout=30)
    assert r2.status_code == 200
    saved2 = r2.json()
    assert saved2["providers"]["openai"]["has_key"] is True, "empty api_key wiped stored key!"
    assert saved2["providers"]["openai"]["monthly_budget_usd"] == 7.5

    # Task routes updated
    assert saved2["task_routes"]["cheap"] == "groq"


def test_put_config_updates_task_routes():
    r = requests.get(f"{API}/routing/config", headers=HDRS, timeout=30)
    cfg = r.json()
    # Flip chat -> anthropic
    cfg["task_routes"]["chat"] = "anthropic"
    # Build write payload with empty api_keys (preserve)
    payload = {
        "providers": {
            pid: {
                "enabled": pcfg.get("enabled", False),
                "api_key": "",
                "default_model": pcfg.get("default_model", ""),
                "monthly_budget_usd": pcfg.get("monthly_budget_usd", 0.0),
            }
            for pid, pcfg in cfg["providers"].items()
        },
        "task_routes": cfg["task_routes"],
        "fallback_order": cfg["fallback_order"],
    }
    r2 = requests.put(f"{API}/routing/config", json=payload, headers=HDRS, timeout=30)
    assert r2.status_code == 200
    assert r2.json()["task_routes"]["chat"] == "anthropic"

    # revert
    payload["task_routes"]["chat"] = "emergent"
    requests.put(f"{API}/routing/config", json=payload, headers=HDRS, timeout=30)


# ----- Chat via emergent -----
def test_chat_default_emergent():
    r = requests.post(
        f"{API}/routing/chat",
        json={"task": "chat", "messages": [{"role": "user", "content": "Say 'hello' in one word."}], "provider": "emergent"},
        headers=HDRS, timeout=120,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("ok") is True, data
    assert data["provider"] == "emergent"
    assert data["model"]
    assert isinstance(data["text"], str) and len(data["text"]) > 0
    assert data["prompt_tokens"] > 0
    assert data["completion_tokens"] > 0
    assert data["cost_usd"] >= 0


# ----- Fallback: openai (no key) -> emergent -----
def test_chat_openai_fallback_to_emergent():
    # Ensure openai is disabled or has no working key. Reset config to clear openai key first.
    reset_payload = {
        "providers": {
            pid: {"enabled": pid == "emergent", "api_key": "", "default_model": "", "monthly_budget_usd": 0.0}
            for pid in EXPECTED_PROVIDERS
        },
        "task_routes": {"chat": "emergent", "interview": "emergent", "tools": "emergent",
                        "cheap": "groq", "long_context": "gemini", "embeddings": "openai"},
        "fallback_order": ["emergent", "openai", "anthropic", "gemini", "groq", "xai", "deepseek"],
    }
    # BUT: we still need an openai key to test fallback path. So we set an obviously-bad key + enabled openai.
    reset_payload["providers"]["openai"]["enabled"] = True
    reset_payload["providers"]["openai"]["api_key"] = "sk-invalid-fallback-test-key-xyz"
    requests.put(f"{API}/routing/config", json=reset_payload, headers=HDRS, timeout=30)

    r = requests.post(
        f"{API}/routing/chat",
        json={"task": "chat", "messages": [{"role": "user", "content": "Hi"}], "provider": "openai"},
        headers=HDRS, timeout=180,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("ok") is True, data
    # Should have fallen back to emergent
    assert data["provider"] == "emergent", f"Expected fallback to emergent, got {data['provider']}"
    assert isinstance(data.get("attempted"), list) and len(data["attempted"]) >= 1
    assert data["attempted"][0]["provider"] == "openai"
    assert "error" in data["attempted"][0]


# ----- Verify bad key -----
def test_verify_invalid_openai_key():
    r = requests.post(
        f"{API}/routing/verify",
        json={"provider": "openai", "api_key": "sk-clearly-invalid-key-abc123"},
        headers=HDRS, timeout=60,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert "error" in data


def test_verify_unknown_provider():
    r = requests.post(
        f"{API}/routing/verify",
        json={"provider": "made_up", "api_key": "x"},
        headers=HDRS, timeout=30,
    )
    assert r.status_code == 400


def test_verify_emergent_no_key_needed():
    r = requests.post(
        f"{API}/routing/verify",
        json={"provider": "emergent", "api_key": ""},
        headers=HDRS, timeout=30,
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


# ----- Usage endpoints -----
def test_usage_summary_shape():
    r = requests.get(f"{API}/routing/usage?days=30", headers=HDRS, timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "total_cost_usd" in data
    assert "total_calls" in data
    assert isinstance(data["by_provider"], list)
    assert isinstance(data["by_task"], list)
    # After earlier chat calls, we should have >= 1 call and emergent should be present
    assert data["total_calls"] >= 1
    providers = {r["provider"] for r in data["by_provider"]}
    assert "emergent" in providers


def test_usage_events_shape():
    r = requests.get(f"{API}/routing/usage/events?limit=5", headers=HDRS, timeout=30)
    assert r.status_code == 200
    events = r.json()
    assert isinstance(events, list)
    assert len(events) >= 1
    ev = events[0]
    for field in ("provider", "model", "task", "prompt_tokens", "completion_tokens", "cost_usd", "ts"):
        assert field in ev, f"missing {field} in event: {ev}"
    # No mongodb _id leaked
    assert "_id" not in ev
    assert "user_id" not in ev


# ----- Resolve -----
def test_resolve_chat():
    r = requests.get(f"{API}/routing/resolve?task=chat", headers=HDRS, timeout=30)
    assert r.status_code == 200
    data = r.json()
    assert data["task"] == "chat"
    assert data["primary"] in EXPECTED_PROVIDERS
    assert isinstance(data["fallback_chain"], list)


def test_resolve_unknown_task_400():
    r = requests.get(f"{API}/routing/resolve?task=nope", headers=HDRS, timeout=30)
    assert r.status_code == 400


# ----- Chat validation errors -----
def test_chat_unknown_task_400():
    r = requests.post(
        f"{API}/routing/chat",
        json={"task": "bogus", "messages": [{"role": "user", "content": "hi"}]},
        headers=HDRS, timeout=30,
    )
    assert r.status_code == 400


def test_chat_unknown_provider_400():
    r = requests.post(
        f"{API}/routing/chat",
        json={"task": "chat", "messages": [{"role": "user", "content": "hi"}], "provider": "notreal"},
        headers=HDRS, timeout=30,
    )
    assert r.status_code == 400


# ----- Auth required -----
def test_config_requires_auth():
    r = requests.get(f"{API}/routing/config", timeout=15)
    assert r.status_code in (401, 403)


# ----- Regression -----
def test_dashboard_regression_no_500():
    r = requests.get(f"{API}/dashboard", headers=HDRS, timeout=60)
    assert r.status_code == 200, r.text
    # Should be a dict with something in it, no server error
    assert isinstance(r.json(), dict)


def test_twin_conversations_regression():
    r = requests.get(f"{API}/twin/conversations", headers=HDRS, timeout=30)
    assert r.status_code == 200, r.text


def test_providers_regression():
    r = requests.get(f"{API}/providers", headers=HDRS, timeout=30)
    # 200 or 404 (if renamed) — just no 500
    assert r.status_code != 500, r.text
