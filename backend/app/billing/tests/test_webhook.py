"""Tests for webhook processing + HTTP wiring + sync/reconcile (Fase 2D).

process_event is tested directly (no signatures). The HTTP endpoint is tested by
monkeypatching verify_and_construct_event to bypass real Stripe signatures.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.clerk import get_current_user_id
from app.billing import config
from app.billing import store as store_mod
from app.billing import webhook as webhook_mod
from app.billing.service import BillingService
from app.billing.store import Store
from app.billing.router import router as billing_router, get_billing_service
from app.billing.webhook import WebhookError, process_event, verify_and_construct_event


def evt(etype, obj, event_id="evt_1"):
    return {"id": event_id, "type": etype, "data": {"object": obj}}


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "billing.sqlite"))
    yield s
    s.close()


@pytest.fixture
def linked(store):
    """A store with u1 <-> cus_1 already linked."""
    store.upsert_customer("u1", "cus_1", email="a@b.com")
    return store


# ── process_event handlers ────────────────────────────────────────────────────
def test_checkout_completed_links_customer_and_records_trial(store):
    e = evt("checkout.session.completed", {
        "client_reference_id": "u1", "customer": "cus_1",
        "customer_details": {"email": "a@b.com"},
    })
    process_event(e, store)
    assert store.get_customer_by_user("u1").stripe_customer_id == "cus_1"
    assert store.has_used_trial("a@b.com") is True     # email trial recorded


def test_subscription_created_upserts(linked):
    e = evt("customer.subscription.created", {
        "id": "sub_1", "customer": "cus_1", "status": "trialing",
        "items": {"data": [{"price": {"id": "price_eur", "currency": "eur"},
                            "current_period_end": 222}]},
        "trial_end": 111, "cancel_at_period_end": False,
    })
    process_event(e, linked)
    sub = linked.get_latest_subscription_for_user("u1")
    assert sub.status == "trialing" and sub.current_period_end == 222


def test_subscription_updated_changes_status(linked):
    linked.upsert_subscription("sub_1", "u1", "cus_1", status="trialing")
    e = evt("customer.subscription.updated", {
        "id": "sub_1", "customer": "cus_1", "status": "active",
        "items": {"data": [{"price": {"id": "price_eur", "currency": "eur"}}]},
    })
    process_event(e, linked)
    assert linked.get_subscription("sub_1").status == "active"


def test_subscription_deleted_forces_canceled(linked):
    linked.upsert_subscription("sub_1", "u1", "cus_1", status="active")
    e = evt("customer.subscription.deleted", {
        "id": "sub_1", "customer": "cus_1", "status": "active",  # Stripe may send stale status
        "items": {"data": []},
    })
    process_event(e, linked)
    assert linked.get_subscription("sub_1").status == "canceled"


def test_invoice_paid_upserts_invoice(linked):
    e = evt("invoice.paid", {
        "id": "in_1", "customer": "cus_1", "status": "paid",
        "amount_paid": 2900, "currency": "eur", "lines": {"data": []},
    })
    process_event(e, linked)
    invs = linked.list_invoices("u1")
    assert len(invs) == 1 and invs[0].status == "paid"


def test_invoice_does_not_touch_subscription_status(linked):
    linked.upsert_subscription("sub_1", "u1", "cus_1", status="active")
    e = evt("invoice.payment_failed", {
        "id": "in_1", "customer": "cus_1", "status": "open", "lines": {"data": []},
    })
    process_event(e, linked)
    # invoice recorded, but status stays 'active' (subscription.updated is authority)
    assert linked.get_subscription("sub_1").status == "active"
    assert linked.get_invoice("in_1").status == "open"


def test_payment_method_attached_records_fingerprint(linked):
    e = evt("payment_method.attached", {
        "id": "pm_1", "customer": "cus_1",
        "card": {"brand": "visa", "last4": "4242", "exp_month": 12,
                 "exp_year": 2030, "fingerprint": "fp_abc"},
    })
    process_event(e, linked)
    assert linked.get_payment_method("pm_1").last4 == "4242"
    assert linked.has_used_trial("fp_abc") is True     # fingerprint anti-recycle


def test_customer_updated_sets_default_pm(linked):
    linked.upsert_payment_method("pm_1", "u1", brand="visa", last4="4242")
    e = evt("customer.updated", {
        "id": "cus_1", "invoice_settings": {"default_payment_method": "pm_1"},
    })
    process_event(e, linked)
    assert linked.get_default_payment_method("u1").stripe_pm_id == "pm_1"


def test_unattributable_event_is_noop(store):
    # No customer link for cus_unknown -> handler returns without error.
    e = evt("customer.subscription.updated", {
        "id": "sub_x", "customer": "cus_unknown", "status": "active",
        "items": {"data": []},
    })
    process_event(e, store)  # must not raise
    assert store.get_subscription("sub_x") is None


def test_unknown_event_type_ignored(linked):
    process_event(evt("customer.subscription.trial_will_end", {"id": "sub_1"}), linked)
    # nothing created/changed
    assert linked.get_latest_subscription_for_user("u1") is None


# ── verify_and_construct_event ────────────────────────────────────────────────
def test_verify_requires_secret():
    with pytest.raises(WebhookError):
        verify_and_construct_event(b"{}", "sig", "")


# ── HTTP endpoint (signature bypassed via monkeypatch) ────────────────────────
@pytest.fixture
def webhook_client(store, monkeypatch):
    store_mod.set_store(store)
    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRET", "whsec_test")
    app = FastAPI()
    app.include_router(billing_router, prefix="/api/billing")
    client = TestClient(app, raise_server_exceptions=False)
    yield client, monkeypatch
    store_mod.set_store(None)


def test_webhook_endpoint_processes_and_dedups(webhook_client, store):
    client, monkeypatch = webhook_client
    store.upsert_customer("u1", "cus_1")
    e = evt("customer.subscription.created", {
        "id": "sub_1", "customer": "cus_1", "status": "active",
        "items": {"data": [{"price": {"id": "p", "currency": "eur"}}]},
    }, event_id="evt_42")
    monkeypatch.setattr(webhook_mod, "verify_and_construct_event", lambda *a, **k: e)

    r1 = client.post("/api/billing/webhook", content=b"{}",
                     headers={"stripe-signature": "x"})
    assert r1.status_code == 200 and r1.json()["status"] == "ok"
    assert store.get_subscription("sub_1").status == "active"

    # Same event id again -> duplicate, skipped.
    r2 = client.post("/api/billing/webhook", content=b"{}",
                     headers={"stripe-signature": "x"})
    assert r2.json()["status"] == "duplicate"


def test_webhook_endpoint_bad_signature_400(webhook_client):
    client, monkeypatch = webhook_client

    def _boom(*a, **k):
        raise WebhookError("bad sig")

    monkeypatch.setattr(webhook_mod, "verify_and_construct_event", _boom)
    r = client.post("/api/billing/webhook", content=b"{}",
                    headers={"stripe-signature": "bad"})
    assert r.status_code == 400


# ── Sync return + reconcile (fake gateway) ────────────────────────────────────
class FakeReadGateway:
    def __init__(self, session=None, subs=None):
        self._session = session
        self._subs = subs or []

    def retrieve_checkout_session(self, session_id):
        return self._session

    def list_subscriptions(self, customer_id):
        return self._subs


def _client_with_svc(svc, user_id="u1"):
    app = FastAPI()
    app.include_router(billing_router, prefix="/api/billing")
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    app.dependency_overrides[get_billing_service] = lambda: svc
    return TestClient(app, raise_server_exceptions=False)


def test_sync_checkout_return_upserts_subscription(store):
    session = {
        "client_reference_id": "u1", "customer": "cus_1",
        "subscription": {
            "id": "sub_1", "customer": "cus_1", "status": "trialing",
            "items": {"data": [{"price": {"id": "p", "currency": "eur"},
                                "current_period_end": 222}]},
        },
    }
    svc = BillingService(store=store, gateway=FakeReadGateway(session=session))
    r = _client_with_svc(svc).post("/api/billing/checkout/sync", json={"session_id": "cs_1"})
    assert r.status_code == 200 and r.json()["status"] == "trialing"
    assert store.get_subscription("sub_1").status == "trialing"
    # customer link created on the fly even without the webhook.
    assert store.get_customer_by_user("u1").stripe_customer_id == "cus_1"


def test_sync_returns_null_when_no_subscription(store):
    svc = BillingService(store=store, gateway=FakeReadGateway(session={"subscription": None}))
    r = _client_with_svc(svc).post("/api/billing/checkout/sync", json={"session_id": "cs_1"})
    assert r.status_code == 200 and r.json()["synced"] is False


def test_reconcile_user_pulls_and_upserts(store):
    store.upsert_customer("u1", "cus_1")
    subs = [{"id": "sub_1", "customer": "cus_1", "status": "active",
             "items": {"data": [{"price": {"id": "p", "currency": "eur"}}]}}]
    svc = BillingService(store=store, gateway=FakeReadGateway(subs=subs))
    latest = svc.reconcile_user("u1")
    assert latest.status == "active"
    assert svc.reconcile_all() == 1
