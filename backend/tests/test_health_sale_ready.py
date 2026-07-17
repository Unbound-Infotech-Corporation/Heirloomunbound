"""Relaunch readiness: health probes + purchase helpers."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deps import user_has_paid_access


def test_user_has_paid_access_lifetime():
    assert user_has_paid_access({"purchased_lifetime": True}) is True
    assert user_has_paid_access({"is_tester": True}) is True
    assert user_has_paid_access({"is_admin": True}) is True
    assert user_has_paid_access({}) is False
    assert user_has_paid_access({"purchased_lifetime": False}) is False


@pytest.mark.asyncio
async def test_health_ping_shape():
    from routers.health import ping

    data = await ping()
    assert data["ok"] is True
    assert "ts" in data


@pytest.mark.asyncio
async def test_health_reports_missing_sale_keys(monkeypatch):
    monkeypatch.setenv("EMERGENT_LLM_KEY", "ek_test")
    monkeypatch.setenv("STRIPE_API_KEY", "")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "")
    monkeypatch.setenv("STRIPE_PAYMENT_LINK_URL", "")
    monkeypatch.setenv("RESEND_API_KEY", "")
    monkeypatch.setenv("SENDER_EMAIL", "onboarding@resend.dev")
    monkeypatch.setenv("PUBLIC_BACKEND_URL", "")
    monkeypatch.setenv("PUBLIC_FRONTEND_URL", "")
    monkeypatch.delenv("ENFORCE_PURCHASE", raising=False)

    mock_client = MagicMock()
    mock_client.admin.command = AsyncMock(return_value={"ok": 1})
    mock_client.close = MagicMock()

    with patch("routers.health.AsyncIOMotorClient", return_value=mock_client):
        from routers import health as health_mod

        data = await health_mod.health()

    assert data["app"] == "digital-heirloom"
    assert data["status"] in {"ok", "degraded", "down"}
    assert data["sale_ready"] is False
    assert "stripe_api_key" in data["missing"]
    assert data["enforce_purchase"] is False
    assert data["recommended_prod_domain"] == "https://heirloomunbound.com"


@pytest.mark.asyncio
async def test_health_sale_ready_when_configured(monkeypatch):
    monkeypatch.setenv("EMERGENT_LLM_KEY", "ek_test")
    monkeypatch.setenv("STRIPE_API_KEY", "sk_live_x")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_x")
    monkeypatch.setenv("STRIPE_PAYMENT_LINK_URL", "https://buy.stripe.com/test")
    monkeypatch.setenv("RESEND_API_KEY", "re_x")
    monkeypatch.setenv("SENDER_EMAIL", "hello@heirloomunbound.com")
    monkeypatch.setenv("PUBLIC_BACKEND_URL", "https://heirloomunbound.com")
    monkeypatch.setenv("PUBLIC_FRONTEND_URL", "https://heirloomunbound.com")
    monkeypatch.setenv("ENFORCE_PURCHASE", "true")

    mock_client = MagicMock()
    mock_client.admin.command = AsyncMock(return_value={"ok": 1})
    mock_client.close = MagicMock()

    with patch("routers.health.AsyncIOMotorClient", return_value=mock_client):
        from routers import health as health_mod

        data = await health_mod.health()

    assert data["sale_ready"] is True
    assert data["checks"]["stripe_live_mode"] is True
    assert data["checks"]["resend_prod_sender"] is True
    assert data["enforce_purchase"] is True
    assert data["missing"] == []
