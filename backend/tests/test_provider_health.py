"""Backend tests for the provider health check feature (iteration 38)."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback to reading frontend/.env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")

SESSION_TOKEN = "test_routing_session"
USER_ID = "test-routing-user"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {SESSION_TOKEN}",
        "Content-Type": "application/json",
    })
    return s


# ---------- Regression: existing endpoints still work ----------
class TestRegression:
    def test_catalog(self, client):
        r = client.get(f"{BASE_URL}/api/routing/catalog")
        assert r.status_code == 200
        data = r.json()
        assert "providers" in data and len(data["providers"]) >= 6

    def test_config_no_key_leak(self, client):
        r = client.get(f"{BASE_URL}/api/routing/config")
        assert r.status_code == 200
        data = r.json()
        for pid, pcfg in data["providers"].items():
            assert pcfg.get("api_key") in ("", None), f"{pid} leaked api_key"
            assert "has_key" in pcfg

    def test_usage(self, client):
        r = client.get(f"{BASE_URL}/api/routing/usage?days=30")
        assert r.status_code == 200
        assert "total_cost_usd" in r.json()

    def test_chat_emergent(self, client):
        r = client.post(f"{BASE_URL}/api/routing/chat", json={
            "task": "chat",
            "messages": [{"role": "user", "content": "Say 'ok'."}],
            "provider": "emergent",
        })
        assert r.status_code == 200
        assert r.json().get("ok") is True


# ---------- Auth ----------
class TestAuth:
    def test_health_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/routing/health")
        assert r.status_code in (401, 403)

    def test_health_check_requires_auth(self):
        r = requests.post(f"{BASE_URL}/api/routing/health/check")
        assert r.status_code in (401, 403)


# ---------- Health endpoints ----------
class TestHealth:
    def test_force_check_all(self, client):
        r = client.post(f"{BASE_URL}/api/routing/health/check")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        # test-routing-user has emergent + openai enabled
        provs = {row["provider"]: row for row in data}
        assert "emergent" in provs
        assert "openai" in provs
        # No api_key field leaked
        for row in data:
            assert "api_key" not in row
            assert "user_id" not in row
            assert set(row.keys()) >= {"provider", "status", "last_checked"}

    def test_emergent_green(self, client):
        r = client.post(f"{BASE_URL}/api/routing/health/check?provider=emergent")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["provider"] == "emergent"
        assert data[0]["status"] == "green"
        assert data[0]["error"] in (None, "")

    def test_openai_red_with_401_error(self, client):
        r = client.post(f"{BASE_URL}/api/routing/health/check?provider=openai")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        row = data[0]
        assert row["provider"] == "openai"
        assert row["status"] == "red"
        assert row["error"] and "401" in row["error"]
        assert len(row["error"]) <= 200  # ~180 truncated

    def test_unknown_provider_400(self, client):
        r = client.post(f"{BASE_URL}/api/routing/health/check?provider=notreal")
        assert r.status_code == 400
        assert "unknown provider" in r.text.lower()

    def test_get_health_returns_probed(self, client):
        # First force a probe
        client.post(f"{BASE_URL}/api/routing/health/check")
        r = client.get(f"{BASE_URL}/api/routing/health")
        assert r.status_code == 200
        data = r.json()
        provs = {row["provider"] for row in data}
        assert "emergent" in provs and "openai" in provs
        for row in data:
            assert "api_key" not in row

    def test_upsert_no_duplicates_and_timestamp_advances(self, client):
        # Run check twice
        r1 = client.post(f"{BASE_URL}/api/routing/health/check?provider=emergent")
        t1 = r1.json()[0]["last_checked"]
        time.sleep(1.2)
        r2 = client.post(f"{BASE_URL}/api/routing/health/check?provider=emergent")
        t2 = r2.json()[0]["last_checked"]
        assert t2 > t1, "last_checked should advance"

        # Query DB via GET — count of emergent rows must be 1
        all_h = client.get(f"{BASE_URL}/api/routing/health").json()
        em_rows = [r for r in all_h if r["provider"] == "emergent"]
        assert len(em_rows) == 1, f"expected 1 emergent row, got {len(em_rows)}"

    def test_disabled_provider_direct_probe(self, client):
        # anthropic is disabled for this user
        r = client.post(f"{BASE_URL}/api/routing/health/check?provider=anthropic")
        assert r.status_code == 200
        row = r.json()[0]
        assert row["provider"] == "anthropic"
        assert row["status"] == "unknown"
        assert row["error"] == "disabled"

    def test_enabled_provider_missing_key(self, client):
        """Enable gemini without a key, then probe."""
        # Get current config
        cur = client.get(f"{BASE_URL}/api/routing/config").json()
        # Build payload — enable gemini, keep others as-is (api_key="" = no change)
        payload = {
            "providers": {pid: {
                "enabled": bool(p["enabled"]) if pid != "gemini" else True,
                "api_key": "",  # no change
                "default_model": p.get("default_model", ""),
                "monthly_budget_usd": p.get("monthly_budget_usd", 0),
            } for pid, p in cur["providers"].items()},
            "task_routes": cur["task_routes"],
            "fallback_order": cur["fallback_order"],
        }
        # Ensure gemini currently has no key
        assert cur["providers"]["gemini"]["has_key"] is False
        put = client.put(f"{BASE_URL}/api/routing/config", json=payload)
        assert put.status_code == 200

        try:
            r = client.post(f"{BASE_URL}/api/routing/health/check?provider=gemini")
            assert r.status_code == 200
            row = r.json()[0]
            assert row["provider"] == "gemini"
            assert row["status"] == "red"
            assert "no api key" in (row["error"] or "").lower()
        finally:
            # Revert gemini to disabled
            payload["providers"]["gemini"]["enabled"] = False
            client.put(f"{BASE_URL}/api/routing/config", json=payload)
