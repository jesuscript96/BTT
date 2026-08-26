"""Tests for the billing service + router (Fase 2C).

No Stripe SDK, no network: a FakeStripeGateway records calls and returns canned
ids/urls. A temp store isolates each test. get_tier/Clerk are untouched.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.clerk import get_current_user_id
from app.billing import config
from app.billing.service import BillingError, BillingService, normalize_email
from app.billing.store import Store
from app.billing.router import router as billing_router, get_billing_service


class FakeStripeGateway:
    """Records outbound calls; returns deterministic fake ids/urls."""

    def __init__(self):
        self.customers_created: list[dict] = []
        self.checkout_calls: list[dict] = []
        self.portal_calls: list[dict] = []

    def create_customer(self, email, metadata):
        cid = f"cus_fake_{len(self.customers_created) + 1}"
        self.customers_created.append({"id": cid, "email": email, "metadata": metadata})
        return cid

    def create_checkout_session(self, *, customer_id, price_id, client_reference_id,
                                success_url, cancel_url, trial_days):
        self.checkout_calls.append(dict(
            customer_id=customer_id, price_id=price_id, client_reference_id=client_reference_id,
            success_url=success_url, cancel_url=cancel_url, trial_days=trial_days,
        ))
        return {"id": f"cs_fake_{len(self.checkout_calls)}", "url": "https://checkout.stripe.test/s"}

    def create_billing_portal_session(self, customer_id, return_url):
        self.portal_calls.append(dict(customer_id=customer_id, return_url=return_url))
        return "https://portal.stripe.test/s"


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "billing.sqlite"))
    yield s
    s.close()


@pytest.fixture
def gw():
    return FakeStripeGateway()


@pytest.fixture
def svc(store, gw):
    return BillingService(store=store, gateway=gw)


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    """Configure Stripe env for the duration of a test (module-level attrs)."""
    monkeypatch.setattr(config, "STRIPE_PRICE_ID_MONTHLY_EUR", "price_test_eur")
    monkeypatch.setattr(config, "BILLING_SUCCESS_URL", "https://app.test/ok")
    monkeypatch.setattr(config, "BILLING_CANCEL_URL", "https://app.test/cancel")
    monkeypatch.setattr(config, "BILLING_PORTAL_RETURN_URL", "https://app.test/billing")
    monkeypatch.setattr(config, "BILLING_TRIAL_DAYS", 7)
    yield


# ── Customer ─────────────────────────────────────────────────────────────────
def test_get_or_create_customer_is_idempotent(svc, gw, store):
    c1 = svc.get_or_create_customer("u1", "a@b.com")
    c2 = svc.get_or_create_customer("u1", "a@b.com")
    assert c1.stripe_customer_id == c2.stripe_customer_id
    assert len(gw.customers_created) == 1               # created in Stripe once
    assert gw.customers_created[0]["metadata"] == {"clerk_user_id": "u1"}
    assert store.get_customer_by_user("u1") is not None


# ── Checkout trial decision (anti-recycle by email) ──────────────────────────
def test_first_checkout_gets_trial(svc, gw):
    session = svc.start_subscription_checkout("u1", "a@b.com")
    assert session["url"].startswith("https://")
    call = gw.checkout_calls[-1]
    assert call["trial_days"] == 7
    assert call["client_reference_id"] == "u1"
    assert call["price_id"] == "price_test_eur"


def test_returning_email_gets_no_trial(svc, gw, store):
    store.record_trial(normalize_email("A@B.com"), "email")   # already trialed
    svc.start_subscription_checkout("u1", "a@b.com")           # different casing
    assert gw.checkout_calls[-1]["trial_days"] is None          # immediate charge


# ── Trial override (Path B: preferential per-user trial days) ────────────────
def test_checkout_uses_trial_override_days(svc, gw, store):
    store.set_trial_override("u1", 14, reason="socio Al", granted_by="adrian")
    svc.start_subscription_checkout("u1", "a@b.com")
    assert gw.checkout_calls[-1]["trial_days"] == 14           # override wins over default 7
    assert store.get_trial_override("u1").consumed_at is not None  # consumed one-shot


def test_trial_override_is_one_shot_then_falls_back(svc, gw, store):
    store.set_trial_override("u1", 21)
    svc.start_subscription_checkout("u1", "a@b.com")
    assert gw.checkout_calls[-1]["trial_days"] == 21
    # A second checkout for the same user no longer sees the override.
    svc.start_subscription_checkout("u1", "a@b.com")
    assert gw.checkout_calls[-1]["trial_days"] == 7            # back to default


# ── trial_offer_days in the summary (drives the PRE-checkout copy) ────────────
def test_summary_trial_offer_days_default(svc):
    assert svc.get_billing_summary("newbie")["trial_offer_days"] == 7


def test_summary_trial_offer_days_preferential_and_read_only(svc, store):
    store.set_trial_override("u1", 14)
    s = svc.get_billing_summary("u1")
    assert s["trial_offer_days"] == 14                         # 14-day user never reads 7
    # the summary is READ-ONLY: it must NOT consume the one-shot override
    assert store.get_trial_override("u1").consumed_at is None


def test_summary_trial_offer_days_returning_email_is_zero(svc, store):
    store.record_trial(normalize_email("a@b.com"), "email")    # already trialed
    assert svc.get_billing_summary("u1", email="a@b.com")["trial_offer_days"] == 0


def test_trial_override_beats_used_trial(svc, gw, store):
    # Even a returning email (would normally get NO trial) gets the admin grant.
    store.record_trial(normalize_email("a@b.com"), "email")
    store.set_trial_override("u1", 30)
    svc.start_subscription_checkout("u1", "a@b.com")
    assert gw.checkout_calls[-1]["trial_days"] == 30


def test_trial_override_rearmed_when_stripe_fails(svc, gw, store, monkeypatch):
    store.set_trial_override("u1", 14)

    def boom(**kwargs):
        raise RuntimeError("stripe down")

    monkeypatch.setattr(gw, "create_checkout_session", boom)
    with pytest.raises(RuntimeError):
        svc.start_subscription_checkout("u1", "a@b.com")
    # The failed Checkout must NOT burn the grant — it stays pending.
    assert store.get_trial_override("u1").consumed_at is None
    assert store.consume_trial_override("u1") == 14


def test_checkout_uses_body_urls_over_config(svc, gw):
    svc.start_subscription_checkout("u1", "a@b.com",
                                    success_url="https://x/ok", cancel_url="https://x/no")
    call = gw.checkout_calls[-1]
    assert call["success_url"] == "https://x/ok" and call["cancel_url"] == "https://x/no"


def test_checkout_missing_price_raises(svc, monkeypatch):
    monkeypatch.setattr(config, "STRIPE_PRICE_ID_MONTHLY_EUR", "")
    with pytest.raises(BillingError):
        svc.start_subscription_checkout("u1", "a@b.com")


# ── Billing Portal ───────────────────────────────────────────────────────────
def test_portal_without_customer_raises(svc):
    with pytest.raises(BillingError):
        svc.open_billing_portal("ghost")


def test_portal_with_customer_returns_url(svc, gw):
    svc.get_or_create_customer("u1", "a@b.com")
    url = svc.open_billing_portal("u1")
    assert url.startswith("https://")
    assert gw.portal_calls[-1]["customer_id"].startswith("cus_fake_")


# ── Router (HTTP) ─────────────────────────────────────────────────────────────
def _client(svc, user_id="u1"):
    app = FastAPI()
    app.include_router(billing_router, prefix="/api/billing")
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    app.dependency_overrides[get_billing_service] = lambda: svc
    return TestClient(app, raise_server_exceptions=False)


def test_checkout_endpoint_returns_url(svc, gw):
    r = _client(svc).post("/api/billing/checkout", json={"email": "a@b.com"})
    assert r.status_code == 200
    assert r.json()["checkout_url"].startswith("https://")
    assert r.json()["session_id"].startswith("cs_fake_")
    assert gw.checkout_calls[-1]["trial_days"] == 7


def test_checkout_endpoint_requires_auth(svc):
    r = _client(svc, user_id=None).post("/api/billing/checkout", json={"email": "a@b.com"})
    assert r.status_code == 401


def test_portal_endpoint_no_customer_is_400(svc):
    r = _client(svc).post("/api/billing/portal", json={})
    assert r.status_code == 400


def test_portal_endpoint_returns_url_for_existing_customer(svc):
    svc.get_or_create_customer("u1", "a@b.com")
    r = _client(svc).post("/api/billing/portal", json={})
    assert r.status_code == 200
    assert r.json()["portal_url"].startswith("https://")


# ── Billing summary (GET /me) ─────────────────────────────────────────────────
def test_billing_summary_locked_when_empty(svc):
    s = svc.get_billing_summary("ghost")
    assert s["tier"] == "Locked" and s["access"] is False
    assert s["subscription"] is None and s["invoices"] == []
    assert s["plan"]["amount_cents"] == 2900 and s["plan"]["currency"] == "eur"


def test_billing_summary_reflects_active_subscription(svc, store):
    store.upsert_customer("u1", "cus_1")
    store.upsert_subscription("sub_1", "u1", "cus_1", status="active", current_period_end=222)
    store.upsert_payment_method("pm_1", "u1", brand="visa", last4="4242", is_default=True)
    store.upsert_invoice("in_1", "u1", status="paid", amount_paid=2900, currency="eur")
    s = svc.get_billing_summary("u1")
    assert s["tier"] == "Pro" and s["access"] is True
    assert s["subscription"]["status"] == "active"
    assert s["subscription"]["current_period_end"] == 222
    assert s["payment_method"]["last4"] == "4242"
    assert len(s["invoices"]) == 1 and s["invoices"][0]["status"] == "paid"


# ── Onboarding/gate stage (Fase 3) ────────────────────────────────────────────
def test_stage_onboarding_for_brand_new_user(svc):
    # No customer, no subscription, no grant → new user must hit the card gate.
    s = svc.get_billing_summary("newbie")
    assert s["stage"] == "onboarding" and s["access"] is False


def test_stage_resubscribe_for_returning_canceled_user(svc, store):
    # Had a subscription, now canceled (baja consumida) → returning, no access.
    store.upsert_customer("u1", "cus_1")
    store.upsert_subscription("sub_1", "u1", "cus_1", status="canceled")
    s = svc.get_billing_summary("u1")
    assert s["stage"] == "resubscribe" and s["access"] is False


def test_stage_trialing_active_past_due(svc, store):
    store.upsert_customer("u1", "cus_1")
    store.upsert_subscription("sub_1", "u1", "cus_1", status="trialing")
    assert svc.get_billing_summary("u1")["stage"] == "trialing"
    store.upsert_subscription("sub_1", "u1", "cus_1", status="active")
    assert svc.get_billing_summary("u1")["stage"] == "active"
    store.upsert_subscription("sub_1", "u1", "cus_1", status="past_due")
    assert svc.get_billing_summary("u1")["stage"] == "past_due"


def test_stage_trial_grant_for_migrated_user(svc, store):
    store.upsert_grant("u1", "Pro", reason="migration-trial", expires_at=9_999_999_999.0)
    s = svc.get_billing_summary("u1")
    assert s["stage"] == "trial_grant" and s["access"] is True


def test_stage_admin(svc, store):
    store.upsert_grant("u1", "Admin", reason="internal")
    assert svc.get_billing_summary("u1")["stage"] == "admin"


def test_comped_allowlist_full_access_free(svc, monkeypatch):
    # A comped colleague (no grant/sub) gets Pro access + stage "comped", free.
    monkeypatch.setenv("BILLING_COMPED_USER_IDS", "friend_1, friend_2")
    s = svc.get_billing_summary("friend_2")
    assert s["tier"] == "Pro" and s["stage"] == "comped" and s["access"] is True
    assert s["subscription"] is None  # never went through Stripe
    # Removing them from the list drops access to the gate (revoke = they pay).
    monkeypatch.setenv("BILLING_COMPED_USER_IDS", "friend_1")
    assert svc.get_billing_summary("friend_2")["stage"] == "onboarding"


def test_comped_email_materializes_and_revokes(svc, store):
    # Listed email → /me seeds a perpetual comped grant → full access, stage comped.
    store.add_comped_email("Colega@Edgecute.com", granted_by="adrian")
    s = svc.get_billing_summary("u_colega", email="colega@edgecute.com")
    assert s["tier"] == "Pro" and s["stage"] == "comped" and s["access"] is True
    g = store.get_grant("u_colega")
    assert g is not None and g.reason == "comped" and g.expires_at is None
    # Delisted → next /me revokes (deletes the comped grant) → back to the gate.
    store.remove_comped_email("colega@edgecute.com")
    s2 = svc.get_billing_summary("u_colega", email="colega@edgecute.com")
    assert s2["stage"] == "onboarding" and s2["access"] is False
    assert store.get_grant("u_colega") is None


def test_comped_email_needs_trusted_email(svc, store):
    # Without a trusted email (JWT template not set), nothing is materialized.
    store.add_comped_email("colega@edgecute.com")
    assert svc.get_billing_summary("u_colega", email=None)["stage"] == "onboarding"


def test_comped_reconcile_leaves_migration_grant_alone(svc, store):
    # A migration-trial grant must NOT be revoked by comped reconciliation.
    store.upsert_grant("u1", "Pro", reason="migration-trial", expires_at=9_999_999_999.0)
    s = svc.get_billing_summary("u1", email="not-listed@x.com")
    assert s["stage"] == "trial_grant"
    assert store.get_grant("u1") is not None


def test_admin_beats_comped(svc, monkeypatch):
    monkeypatch.setenv("BILLING_ADMIN_USER_IDS", "u1")
    monkeypatch.setenv("BILLING_COMPED_USER_IDS", "u1")
    assert svc.get_billing_summary("u1")["stage"] == "admin"  # admin precedence


def test_admin_allowlist_never_sees_gate(svc, monkeypatch):
    # An admin in BILLING_ADMIN_USER_IDS has NO grant/sub, yet must resolve to
    # Admin (access, no card gate) — mirrors get_tier's allowlist precedence.
    monkeypatch.setenv("BILLING_ADMIN_USER_IDS", "admin_1, admin_2")
    s = svc.get_billing_summary("admin_2")
    assert s["tier"] == "Admin" and s["stage"] == "admin" and s["access"] is True
    # A non-listed user with the same empty state still hits onboarding.
    assert svc.get_billing_summary("rando")["stage"] == "onboarding"


def test_billing_me_endpoint_exposes_grant_countdown(svc, store):
    store.upsert_grant("u1", "Pro", reason="migration-trial", expires_at=9_999_999_999.0)
    r = _client(svc).get("/api/billing/me")
    assert r.status_code == 200
    body = r.json()
    assert body["tier"] == "Pro" and body["access"] is True
    assert body["grant"]["reason"] == "migration-trial"
    assert body["grant"]["expires_at"] == 9_999_999_999.0


def test_billing_me_requires_auth(svc):
    r = _client(svc, user_id=None).get("/api/billing/me")
    assert r.status_code == 401
