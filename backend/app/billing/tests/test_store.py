"""Unit tests for the billing store (Fase 2A). Data-only; no Stripe, no HTTP.

Each test uses a temp SQLite file, so nothing touches prod or users.duckdb.
"""
from __future__ import annotations

import time

import pytest

from app.billing.store import (
    MAX_TRIAL_OVERRIDE_DAYS,
    MIN_TRIAL_OVERRIDE_DAYS,
    Store,
)


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "billing.sqlite"))
    yield s
    s.close()


# ── Customers ─────────────────────────────────────────────────────────────────
def test_customer_roundtrip_and_lookups(store):
    c = store.upsert_customer("user_1", "cus_abc", email="a@b.com")
    assert c.user_id == "user_1" and c.stripe_customer_id == "cus_abc"
    assert store.get_customer_by_user("user_1").stripe_customer_id == "cus_abc"
    assert store.get_customer_by_stripe_id("cus_abc").user_id == "user_1"
    assert store.get_customer_by_user("nobody") is None


def test_customer_upsert_preserves_created_at(store):
    c1 = store.upsert_customer("user_1", "cus_abc", email="a@b.com")
    time.sleep(0.01)
    c2 = store.upsert_customer("user_1", "cus_abc", email="new@b.com")
    assert c2.email == "new@b.com"
    assert c2.created_at == c1.created_at        # created_at frozen
    assert c2.updated_at >= c1.updated_at        # updated_at advances


# ── Subscriptions ─────────────────────────────────────────────────────────────
def test_subscription_upsert_and_status_transition(store):
    store.upsert_subscription(
        "sub_1", "user_1", "cus_abc", status="trialing",
        price_id="price_eur_monthly", currency="eur",
        trial_end=2_000_000_000.0, current_period_end=2_000_000_000.0,
    )
    s = store.get_subscription("sub_1")
    assert s.status == "trialing" and s.currency == "eur"
    assert s.cancel_at_period_end is False

    # Webhook-style update: trial -> active, mark cancel_at_period_end.
    store.upsert_subscription(
        "sub_1", "user_1", "cus_abc", status="active",
        price_id="price_eur_monthly", currency="eur",
        current_period_end=2_100_000_000.0, cancel_at_period_end=True,
    )
    s2 = store.get_subscription("sub_1")
    assert s2.status == "active"
    assert s2.cancel_at_period_end is True
    assert s2.current_period_end == 2_100_000_000.0


def test_latest_subscription_for_user(store):
    store.upsert_subscription("sub_old", "user_1", "cus_abc", status="canceled")
    time.sleep(0.01)
    store.upsert_subscription("sub_new", "user_1", "cus_abc", status="active")
    latest = store.get_latest_subscription_for_user("user_1")
    assert latest.stripe_subscription_id == "sub_new"
    assert len(store.list_subscriptions_for_user("user_1")) == 2
    assert store.get_latest_subscription_for_user("nobody") is None


# ── Payment methods ───────────────────────────────────────────────────────────
def test_payment_method_single_default_invariant(store):
    store.upsert_payment_method("pm_1", "user_1", brand="visa", last4="4242", is_default=True)
    store.upsert_payment_method("pm_2", "user_1", brand="mastercard", last4="5555", is_default=False)
    assert store.get_default_payment_method("user_1").stripe_pm_id == "pm_1"

    # Promote pm_2; pm_1 must lose the flag.
    store.set_default_payment_method("user_1", "pm_2")
    assert store.get_default_payment_method("user_1").stripe_pm_id == "pm_2"
    assert store.get_payment_method("pm_1").is_default is False
    assert len(store.list_payment_methods("user_1")) == 2


# ── Invoices ──────────────────────────────────────────────────────────────────
def test_invoice_roundtrip_and_status_update(store):
    store.upsert_invoice(
        "in_1", "user_1", status="open", subscription_id="sub_1",
        amount_due=2900, currency="eur", hosted_invoice_url="https://stripe/inv/1",
    )
    assert store.get_invoice("in_1").status == "open"
    # payment_failed -> later paid: same id upserts.
    store.upsert_invoice("in_1", "user_1", status="paid", amount_paid=2900, currency="eur")
    inv = store.get_invoice("in_1")
    assert inv.status == "paid" and inv.amount_paid == 2900
    assert len(store.list_invoices("user_1")) == 1


# ── Entitlement grants ────────────────────────────────────────────────────────
def test_grant_upsert_and_delete(store):
    store.upsert_grant("user_1", "Pro", reason="migration-trial", expires_at=2_000_000_000.0)
    g = store.get_grant("user_1")
    assert g.grant_tier == "Pro" and g.expires_at == 2_000_000_000.0
    # Promote to perpetual Admin.
    store.upsert_grant("user_1", "Admin", reason="internal")
    g2 = store.get_grant("user_1")
    assert g2.grant_tier == "Admin" and g2.expires_at is None
    store.delete_grant("user_1")
    assert store.get_grant("user_1") is None


# ── Webhook idempotency ───────────────────────────────────────────────────────
def test_webhook_event_dedup(store):
    assert store.mark_event_processed("evt_1", "customer.subscription.updated") is True
    # Stripe retries the same event -> second claim is a no-op.
    assert store.mark_event_processed("evt_1", "customer.subscription.updated") is False
    assert store.is_event_processed("evt_1") is True
    assert store.is_event_processed("evt_never") is False


# ── Trial ledger (anti-recycle) ───────────────────────────────────────────────
def test_trial_ledger_blocks_reuse(store):
    assert store.record_trial("a@b.com", "email") is True
    # Same identity (deleted+recreated account, same email) cannot trial again.
    assert store.record_trial("a@b.com", "email") is False
    assert store.has_used_trial("a@b.com") is True
    # A different identity (different card fingerprint) is free to trial.
    assert store.record_trial("fp_xyz", "card_fingerprint") is True
    assert store.has_used_trial("fp_other") is False


# ── Trial overrides (Path B: per-user preferential trial length) ──────────────
def test_trial_override_roundtrip_and_bounds(store):
    o = store.set_trial_override("user_1", 14, reason="socio", granted_by="adrian")
    assert o.days == 14 and o.consumed_at is None and o.granted_by == "adrian"
    assert store.get_trial_override("user_1").reason == "socio"
    assert store.get_trial_override("nobody") is None
    # Out-of-range days are rejected before they can reach Stripe.
    with pytest.raises(ValueError):
        store.set_trial_override("user_2", MAX_TRIAL_OVERRIDE_DAYS + 1)
    with pytest.raises(ValueError):
        store.set_trial_override("user_2", MIN_TRIAL_OVERRIDE_DAYS - 1)


def test_trial_override_consume_is_one_shot(store):
    store.set_trial_override("user_1", 21)
    assert store.consume_trial_override("user_1") == 21   # first claim gets the days
    assert store.consume_trial_override("user_1") is None  # already consumed
    assert store.get_trial_override("user_1").consumed_at is not None
    assert store.consume_trial_override("nobody") is None  # no override at all


def test_trial_override_reset_rearms(store):
    store.set_trial_override("user_1", 7)
    assert store.consume_trial_override("user_1") == 7
    # A deliberate admin re-grant re-arms the one-shot (consumed_at -> NULL).
    store.set_trial_override("user_1", 30)
    assert store.get_trial_override("user_1").consumed_at is None
    assert store.consume_trial_override("user_1") == 30


def test_trial_override_rearm_delete_and_list(store):
    store.set_trial_override("user_1", 10)
    store.set_trial_override("user_2", 14)
    store.consume_trial_override("user_1")
    # rearm undoes a claim (e.g. Checkout failed after consuming).
    store.rearm_trial_override("user_1")
    assert store.consume_trial_override("user_1") == 10
    assert len(store.list_trial_overrides()) == 2
    store.delete_trial_override("user_1")
    assert store.get_trial_override("user_1") is None
    assert len(store.list_trial_overrides()) == 1


# ── Persistence across connections (durability of the file) ───────────────────
def test_state_persists_across_reopen(tmp_path):
    path = str(tmp_path / "billing.sqlite")
    s1 = Store(path)
    s1.upsert_customer("user_1", "cus_abc")
    s1.upsert_subscription("sub_1", "user_1", "cus_abc", status="active")
    s1.close()

    s2 = Store(path)  # reopen the same file
    assert s2.get_customer_by_user("user_1").stripe_customer_id == "cus_abc"
    assert s2.get_latest_subscription_for_user("user_1").status == "active"
    s2.close()
