"""Stripe webhook: signature verification + idempotent event dispatch (Fase 2D).

The event matrix is docs/FASE1_DISENO_TRIAL_SUSCRIPCION_STRIPE.md §5. Every
handler is idempotent (store upserts), so processing an event twice is harmless.

Idempotency strategy: the router guards with is_event_processed() up front, then
we process, then mark_event_processed() on success. We mark AFTER handling (not
before) so a transient failure returns non-2xx and Stripe RETRIES rather than
the event being silently swallowed. Idempotent upserts make the small
race-window duplicate harmless.

Status authority: subscription.* events are the sole authority on
subscription.status. invoice.* events only upsert the invoice (they do NOT flip
status) — Stripe fires customer.subscription.updated (e.g. -> past_due) alongside
the invoice, so we avoid two writers fighting over the same field.
"""
from __future__ import annotations

from typing import Optional

from app.billing import config
from app.billing.service import normalize_email
from app.billing.store import Store
from app.billing.stripe_objects import (
    _id,
    parse_invoice,
    parse_payment_method,
    parse_subscription,
)


class WebhookError(Exception):
    """Signature verification failed or the payload was unparseable."""


def verify_and_construct_event(payload: bytes, sig_header: str, secret: str) -> dict:
    """Verify the Stripe signature and return the event as a dict. Raises
    WebhookError on any verification/parse failure."""
    if not secret:
        raise WebhookError("STRIPE_WEBHOOK_SECRET not configured")
    import stripe  # lazy

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
    except stripe.SignatureVerificationError as exc:
        raise WebhookError(f"signature verification failed: {exc}") from exc
    except Exception as exc:
        raise WebhookError(f"invalid webhook payload: {exc}") from exc
    # construct_event returns a StripeObject; normalize to a plain dict.
    return dict(event)


# ── Dispatch ──────────────────────────────────────────────────────────────────
_SUBSCRIPTION_UPSERT = frozenset(
    {"customer.subscription.created", "customer.subscription.updated"}
)
_INVOICE_EVENTS = frozenset(
    {"invoice.paid", "invoice.payment_succeeded", "invoice.payment_failed",
     "invoice.finalized", "invoice.created"}
)


def process_event(event: dict, store: Store) -> None:
    """Dispatch one event to its handler. Unknown/notification-only events
    (e.g. customer.subscription.trial_will_end) are ignored on purpose."""
    etype = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}

    if etype == "checkout.session.completed":
        _handle_checkout_completed(obj, store)
    elif etype in _SUBSCRIPTION_UPSERT:
        _handle_subscription_upsert(obj, store)
    elif etype == "customer.subscription.deleted":
        _handle_subscription_deleted(obj, store)
    elif etype in _INVOICE_EVENTS:
        _handle_invoice(obj, store)
    elif etype == "payment_method.attached":
        _handle_payment_method_attached(obj, store)
    elif etype == "customer.updated":
        _handle_customer_updated(obj, store)
    # else: no state change (notification-only or irrelevant) — intentionally ignored.


def _user_id_for_customer(store: Store, stripe_customer_id: Optional[str]) -> Optional[str]:
    if not stripe_customer_id:
        return None
    cust = store.get_customer_by_stripe_id(stripe_customer_id)
    return cust.user_id if cust else None


def _handle_checkout_completed(session: dict, store: Store) -> None:
    """Link customer<->user via client_reference_id and record the email trial.
    The subscription itself is populated by customer.subscription.created."""
    user_id = session.get("client_reference_id")
    customer_id = _id(session.get("customer"))
    if not user_id or not customer_id:
        return
    existing = store.get_customer_by_user(user_id)
    email = existing.email if existing else (session.get("customer_details") or {}).get("email")
    store.upsert_customer(user_id, customer_id, email=email)
    if email:
        store.record_trial(normalize_email(email), "email")


def _handle_subscription_upsert(sub: dict, store: Store) -> None:
    fields = parse_subscription(sub)
    user_id = _user_id_for_customer(store, fields["stripe_customer_id"])
    if not user_id:
        return
    store.upsert_subscription(user_id=user_id, **fields)


def _handle_subscription_deleted(sub: dict, store: Store) -> None:
    fields = parse_subscription(sub)
    user_id = _user_id_for_customer(store, fields["stripe_customer_id"])
    if not user_id:
        return
    fields["status"] = "canceled"  # deleted => canceled, whatever Stripe sent
    store.upsert_subscription(user_id=user_id, **fields)


def _handle_invoice(inv: dict, store: Store) -> None:
    fields = parse_invoice(inv)
    user_id = _user_id_for_customer(store, _id(inv.get("customer")))
    if not user_id:
        return
    # Invoice-only write; status transitions come from subscription.* events.
    store.upsert_invoice(user_id=user_id, **fields)


def _handle_payment_method_attached(pm: dict, store: Store) -> None:
    fields = parse_payment_method(pm)
    user_id = _user_id_for_customer(store, fields["customer"])
    if not user_id:
        return
    store.upsert_payment_method(
        fields["stripe_pm_id"], user_id, brand=fields["brand"], last4=fields["last4"],
        exp_month=fields["exp_month"], exp_year=fields["exp_year"], is_default=False,
    )
    # Anti-recycle: same physical card -> same fingerprint, even on a new account.
    if fields.get("fingerprint"):
        store.record_trial(fields["fingerprint"], "card_fingerprint")


def _handle_customer_updated(cust: dict, store: Store) -> None:
    user_id = _user_id_for_customer(store, cust.get("id"))
    if not user_id:
        return
    default_pm = _id((cust.get("invoice_settings") or {}).get("default_payment_method"))
    if not default_pm:
        return
    if store.get_payment_method(default_pm) is None:
        store.upsert_payment_method(default_pm, user_id)  # minimal row; details fill on attach
    store.set_default_payment_method(user_id, default_pm)
