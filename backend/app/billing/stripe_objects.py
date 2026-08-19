"""Pure parsers: Stripe event objects -> plain dicts of store fields (Fase 2D).

No SDK, no store, no I/O — just dict-in/dict-out, so they unit-test against
captured payloads. Shared by the webhook handlers AND the synchronous
checkout-return path (§4 step 5a), so the mapping lives in exactly one place.

Defensive on purpose: Stripe moved some fields across API versions
(current_period_end and invoice.subscription drifted from top-level into
items/parent), and IDs arrive sometimes as strings, sometimes as expanded
objects. Each getter tries the known locations and falls back.
"""
from __future__ import annotations

from typing import Optional


def _id(value) -> Optional[str]:
    """A Stripe reference is either an id string or an expanded object with 'id'."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("id")
    return None


def _subscription_period_end(obj: dict) -> Optional[float]:
    # Newer API versions put current_period_end on the subscription item.
    top = obj.get("current_period_end")
    if top is not None:
        return top
    items = (obj.get("items") or {}).get("data") or []
    if items:
        return items[0].get("current_period_end")
    return None


def _invoice_subscription_id(obj: dict) -> Optional[str]:
    # Top-level `subscription` was deprecated in the 2025 API; try the newer
    # locations too.
    sub = obj.get("subscription")
    if sub:
        return _id(sub)
    parent = obj.get("parent") or {}
    details = parent.get("subscription_details") or {}
    if details.get("subscription"):
        return _id(details.get("subscription"))
    lines = (obj.get("lines") or {}).get("data") or []
    if lines:
        return _id(lines[0].get("subscription"))
    return None


def parse_subscription(obj: dict) -> dict:
    """Map a Stripe Subscription object to subscriptions-table fields.
    Returns everything EXCEPT user_id (the caller resolves that from customer)."""
    items = (obj.get("items") or {}).get("data") or []
    price = (items[0].get("price") if items else {}) or {}
    return {
        "stripe_subscription_id": obj["id"],
        "stripe_customer_id": _id(obj.get("customer")),
        "status": obj["status"],
        "price_id": price.get("id"),
        "currency": price.get("currency") or obj.get("currency"),
        "trial_end": obj.get("trial_end"),
        "current_period_end": _subscription_period_end(obj),
        "cancel_at_period_end": bool(obj.get("cancel_at_period_end", False)),
        "canceled_at": obj.get("canceled_at"),
        "default_pm_id": _id(obj.get("default_payment_method")),
    }


def parse_invoice(obj: dict) -> dict:
    """Map a Stripe Invoice object to invoices-table fields (minus user_id)."""
    lines = (obj.get("lines") or {}).get("data") or []
    period = (lines[0].get("period") if lines else {}) or {}
    return {
        "stripe_invoice_id": obj["id"],
        "subscription_id": _invoice_subscription_id(obj),
        "status": obj["status"],
        "amount_due": obj.get("amount_due"),
        "amount_paid": obj.get("amount_paid"),
        "currency": obj.get("currency"),
        "hosted_invoice_url": obj.get("hosted_invoice_url"),
        "invoice_pdf": obj.get("invoice_pdf"),
        "period_start": obj.get("period_start") or period.get("start"),
        "period_end": obj.get("period_end") or period.get("end"),
    }


def parse_payment_method(obj: dict) -> dict:
    """Map a Stripe PaymentMethod object to payment_methods-table fields
    (minus user_id) plus 'customer' and the card 'fingerprint' (anti-recycle)."""
    card = obj.get("card") or {}
    return {
        "stripe_pm_id": obj["id"],
        "customer": _id(obj.get("customer")),
        "brand": card.get("brand"),
        "last4": card.get("last4"),
        "exp_month": card.get("exp_month"),
        "exp_year": card.get("exp_year"),
        "fingerprint": card.get("fingerprint"),
    }
