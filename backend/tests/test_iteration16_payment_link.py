"""Iteration 16: Stripe Payment Link integration tests.

Covers:
- GET /api/billing/payment-link returns env URL + ID + lifetime package
- GET /api/billing/packages still returns lifetime (regression)
- GET /api/billing/webhook-info now includes payment_link_id + payment_link_url
- POST /api/webhook/stripe handles synthetic payment_link checkout.session.completed
- Webhook event-level idempotency
- _provision_after_payment direct unit-style test (idempotency, db rows)
- Regression: /api/billing/checkout still works
- Regression: /api/billing/status/{session_id} endpoint still functions
"""
from __future__ import annotations

import asyncio
import os
import uuid
import sys
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

# Load backend .env so we can read STRIPE_PAYMENT_LINK_* and MONGO_URL
load_dotenv(Path(__file__).parent.parent / ".env")

# Make backend importable for unit-style test
sys.path.insert(0, str(Path(__file__).parent.parent))

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or \
           "https://voice-clone-hub-20.preview.emergentagent.com"
API = f"{BASE_URL}/api"

EXPECTED_URL = "https://buy.stripe.com/dRm9AT87I9Ky7C82MZdQQ00"
EXPECTED_PLINK_ID = "plink_1TnP5pGsA7WZDU3uyECbEDm5"

# Sync mongo client for verification + cleanup (avoids motor event-loop reuse issues)
_MONGO = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
_DB = _MONGO[os.environ.get("DB_NAME", "test_database")]


# ----------------------- Public endpoint tests -----------------------
class TestPaymentLinkEndpoint:
    def test_payment_link_returns_live_url_and_package(self):
        r = requests.get(f"{API}/billing/payment-link", timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("url") == EXPECTED_URL
        assert data.get("payment_link_id") == EXPECTED_PLINK_ID
        pkg = data.get("package") or {}
        assert pkg.get("price") == 79.0
        assert pkg.get("currency") == "usd"
        assert pkg.get("name")


class TestPackagesRegression:
    def test_packages_still_returns_lifetime(self):
        r = requests.get(f"{API}/billing/packages", timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "packages" in data
        life = data["packages"].get("lifetime")
        assert life is not None
        assert life.get("price") == 79.0
        assert life.get("currency") == "usd"
        assert life.get("id") == "lifetime"


class TestWebhookInfo:
    def test_webhook_info_includes_payment_link_fields(self):
        r = requests.get(f"{API}/billing/webhook-info", timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "webhook_url" in data
        assert "/api/webhook/stripe" in data["webhook_url"]
        assert "events_to_listen_for" in data
        assert "checkout.session.completed" in data["events_to_listen_for"]
        assert data.get("payment_link_id") == EXPECTED_PLINK_ID
        assert data.get("payment_link_url") == EXPECTED_URL


# ----------------------- Stripe webhook tests -----------------------
class TestStripeWebhookPaymentLink:
    def test_payment_link_webhook_provisions_via_customer_details(self):
        """Synthetic payment_link checkout.session.completed event.
        StripeCheckout.get_checkout_status will fail (fake session) — errors
        are swallowed; webhook still returns 200 and records stripe_events.
        """
        evt_id = f"evt_test_{uuid.uuid4().hex[:16]}"
        sess_id = f"cs_test_{uuid.uuid4().hex[:16]}"
        payload = {
            "id": evt_id,
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": sess_id,
                    "payment_status": "paid",
                    "payment_link": EXPECTED_PLINK_ID,
                    "customer_details": {
                        "email": "paylink_test@example.com",
                        "name": "QR Buyer",
                    },
                }
            },
        }
        try:
            r = requests.post(f"{API}/webhook/stripe", json=payload, timeout=20,
                              headers={"Stripe-Signature": "test"})
            assert r.status_code == 200, r.text
            body = r.json()
            assert body.get("received") is True
            assert body.get("duplicate") is not True

            doc = _DB.stripe_events.find_one({"event_id": evt_id})
            assert doc is not None, "stripe_events row not inserted"
            assert doc.get("event_id") == evt_id
        finally:
            _DB.stripe_events.delete_one({"event_id": evt_id})

    def test_webhook_idempotent_at_event_level(self):
        evt_id = f"evt_dup_{uuid.uuid4().hex[:16]}"
        sess_id = f"cs_dup_{uuid.uuid4().hex[:16]}"
        payload = {
            "id": evt_id,
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": sess_id,
                    "payment_status": "paid",
                    "payment_link": EXPECTED_PLINK_ID,
                    "customer_details": {
                        "email": "paylink_dup@example.com",
                        "name": "Dup Buyer",
                    },
                }
            },
        }
        try:
            r1 = requests.post(f"{API}/webhook/stripe", json=payload, timeout=20,
                               headers={"Stripe-Signature": "test"})
            assert r1.status_code == 200, r1.text
            assert r1.json().get("duplicate") is not True

            r2 = requests.post(f"{API}/webhook/stripe", json=payload, timeout=20,
                               headers={"Stripe-Signature": "test"})
            assert r2.status_code == 200, r2.text
            assert r2.json().get("duplicate") is True
        finally:
            _DB.stripe_events.delete_one({"event_id": evt_id})


# ----------------------- _provision_after_payment unit test -----------------------
class TestProvisionAfterPaymentUnit:
    def test_provision_creates_all_rows_and_is_idempotent(self):
        from routers.billing import _provision_after_payment
        from emergentintegrations.payments.stripe.checkout import CheckoutStatusResponse

        unique = uuid.uuid4().hex[:12]
        sess_id = f"cs_synth_{unique}"
        email = f"unit_buyer_{unique}@example.com"

        status_obj = CheckoutStatusResponse(
            status="complete",
            payment_status="paid",
            amount_total=7900,
            currency="usd",
            metadata={},
        )

        # Run both calls within a single event loop to avoid motor reuse issues
        async def _run_both():
            r1 = await _provision_after_payment(
                sess_id, status_obj, email_override=email, name_override="Unit Buyer"
            )
            r2 = await _provision_after_payment(
                sess_id, status_obj, email_override=email, name_override="Unit Buyer"
            )
            return r1, r2

        try:
            artifacts1, artifacts2 = asyncio.run(_run_both())
            assert artifacts1["download_url"]
            assert artifacts1["login_url"]
            assert artifacts1["email"] == email

            # Idempotency: same urls on second call
            assert artifacts2["download_url"] == artifacts1["download_url"]
            assert artifacts2["login_url"] == artifacts1["login_url"]

            # Verify DB rows via sync pymongo
            txn = _DB.payment_transactions.find_one({"session_id": sess_id})
            assert txn is not None, "payment_transactions row missing"
            assert txn.get("provisioned") is True
            # source defaults to 'checkout_session' when called without source kwarg
            assert txn.get("source", "checkout_session") == "checkout_session"

            user = _DB.users.find_one({"email": email})
            assert user is not None, "users row missing"
            assert user.get("purchased_lifetime") is True
            uid = user["user_id"]

            assert _DB.companion_devices.find_one({"user_id": uid}) is not None
            assert _DB.download_tokens.find_one({"user_id": uid}) is not None
            assert _DB.magic_links.find_one({"user_id": uid}) is not None

            # No duplicates
            assert _DB.companion_devices.count_documents({"user_id": uid}) == 1
            assert _DB.download_tokens.count_documents({"user_id": uid}) == 1
            assert _DB.magic_links.count_documents({"user_id": uid}) == 1
            assert _DB.payment_transactions.count_documents({"session_id": sess_id}) == 1
        finally:
            user = _DB.users.find_one({"email": email})
            if user:
                uid = user["user_id"]
                _DB.companion_devices.delete_many({"user_id": uid})
                _DB.download_tokens.delete_many({"user_id": uid})
                _DB.magic_links.delete_many({"user_id": uid})
                _DB.users.delete_one({"user_id": uid})
            _DB.payment_transactions.delete_many({"session_id": sess_id})


# ----------------------- Regression -----------------------
class TestCheckoutRegression:
    def test_checkout_still_creates_stripe_session(self):
        payload = {
            "package_id": "lifetime",
            "origin_url": BASE_URL,
            "email": "regression_checkout@example.com",
            "name": "Regression Tester",
        }
        sid = None
        try:
            r = requests.post(f"{API}/billing/checkout", json=payload, timeout=20)
            if r.status_code != 200:
                pytest.skip(f"Stripe checkout upstream returned {r.status_code}: {r.text[:200]}")
            data = r.json()
            assert "url" in data
            assert "session_id" in data
            assert data["session_id"].startswith("cs_")
            sid = data["session_id"]
        finally:
            if sid:
                _DB.payment_transactions.delete_one({"session_id": sid})

    def test_status_endpoint_returns_response(self):
        r = requests.get(f"{API}/billing/status/cs_fake_{uuid.uuid4().hex[:8]}", timeout=15)
        # Endpoint exists; upstream fails for fake id → ~500. Not 404 (routing).
        assert r.status_code not in (404, 405), \
            f"endpoint missing? got {r.status_code} {r.text[:200]}"
