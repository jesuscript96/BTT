"""Tests for the pure Stripe-object parsers (Fase 2D). Dict-in/dict-out.

Covers the cross-version field drift explicitly: current_period_end on the
subscription ITEM, invoice.subscription under parent.subscription_details, and
references arriving as either id-strings or expanded objects.
"""
from __future__ import annotations

from app.billing.stripe_objects import (
    parse_invoice,
    parse_payment_method,
    parse_subscription,
)


def test_parse_subscription_new_api_shape():
    # current_period_end on the item; default_payment_method as a string id.
    obj = {
        "id": "sub_1", "customer": "cus_1", "status": "trialing",
        "cancel_at_period_end": False, "trial_end": 111,
        "items": {"data": [{"price": {"id": "price_eur", "currency": "eur"},
                            "current_period_end": 222}]},
        "default_payment_method": "pm_1",
    }
    f = parse_subscription(obj)
    assert f["stripe_subscription_id"] == "sub_1"
    assert f["stripe_customer_id"] == "cus_1"
    assert f["status"] == "trialing"
    assert f["price_id"] == "price_eur" and f["currency"] == "eur"
    assert f["trial_end"] == 111
    assert f["current_period_end"] == 222          # read from the item
    assert f["cancel_at_period_end"] is False
    assert f["default_pm_id"] == "pm_1"


def test_parse_subscription_old_api_shape_with_expanded_refs():
    # top-level current_period_end; customer + default_payment_method expanded.
    obj = {
        "id": "sub_2", "customer": {"id": "cus_2"}, "status": "active",
        "current_period_end": 999, "cancel_at_period_end": True,
        "items": {"data": [{"price": {"id": "p", "currency": "usd"}}]},
        "default_payment_method": {"id": "pm_2"},
    }
    f = parse_subscription(obj)
    assert f["stripe_customer_id"] == "cus_2"       # unwrapped from object
    assert f["current_period_end"] == 999           # top-level
    assert f["cancel_at_period_end"] is True
    assert f["default_pm_id"] == "pm_2"


def test_parse_invoice_new_api_subscription_in_parent():
    obj = {
        "id": "in_1", "customer": "cus_1", "status": "paid",
        "amount_due": 2900, "amount_paid": 2900, "currency": "eur",
        "hosted_invoice_url": "https://h", "invoice_pdf": "https://p",
        "parent": {"subscription_details": {"subscription": "sub_1"}},
        "lines": {"data": [{"period": {"start": 1, "end": 2}}]},
    }
    f = parse_invoice(obj)
    assert f["stripe_invoice_id"] == "in_1"
    assert f["subscription_id"] == "sub_1"          # from parent.subscription_details
    assert f["amount_paid"] == 2900 and f["currency"] == "eur"
    assert f["period_start"] == 1 and f["period_end"] == 2


def test_parse_invoice_old_api_top_level():
    obj = {
        "id": "in_2", "customer": "cus_2", "status": "open",
        "subscription": "sub_2", "period_start": 10, "period_end": 20,
        "lines": {"data": []},
    }
    f = parse_invoice(obj)
    assert f["subscription_id"] == "sub_2"
    assert f["period_start"] == 10 and f["period_end"] == 20


def test_parse_payment_method():
    obj = {
        "id": "pm_1", "customer": "cus_1",
        "card": {"brand": "visa", "last4": "4242", "exp_month": 12,
                 "exp_year": 2030, "fingerprint": "fp_abc"},
    }
    f = parse_payment_method(obj)
    assert f["stripe_pm_id"] == "pm_1" and f["customer"] == "cus_1"
    assert f["brand"] == "visa" and f["last4"] == "4242"
    assert f["exp_month"] == 12 and f["exp_year"] == 2030
    assert f["fingerprint"] == "fp_abc"
