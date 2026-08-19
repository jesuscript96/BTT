"""Thin wrapper over the Stripe SDK (Fase 2C).

Every Stripe call the MVP needs sits behind this small surface so:
  - the service layer is testable with a fake (no network, no SDK),
  - the `stripe` import stays LAZY (out of module-import time) — the billing
    package remains importable without the package installed or a key set, which
    is what keeps the whole feature dormant in prod until cutover (Fase 2G).

Only outbound "create" calls live here for 2C. Parsing inbound Stripe objects
(subscriptions/invoices) belongs to the webhook + reconciliation (Fase 2D).
"""
from __future__ import annotations

from typing import Optional

from app.billing import config


class StripeError(Exception):
    """Raised when Stripe is misconfigured or a call fails."""


class StripeGateway:
    """Wraps the Stripe SDK. Constructing it REQUIRES a secret key, so it is only
    built on demand (never at import) — a caller without a key gets a clean
    StripeError instead of a boot-time crash."""

    def __init__(self, api_key: Optional[str] = None):
        key = api_key or config.STRIPE_SECRET_KEY
        if not key:
            raise StripeError("STRIPE_SECRET_KEY not configured")
        import stripe  # lazy: keeps the SDK out of billing's import path

        stripe.api_key = key
        self._stripe = stripe

    def create_customer(self, email: Optional[str], metadata: dict) -> str:
        """Create a Stripe Customer; return its id. metadata carries
        clerk_user_id so the webhook can tie the subscription to the user."""
        try:
            c = self._stripe.Customer.create(email=email, metadata=metadata)
        except Exception as exc:  # stripe.error.* — normalize to our type
            raise StripeError(f"create_customer failed: {exc}") from exc
        return c["id"]

    def create_checkout_session(
        self,
        *,
        customer_id: str,
        price_id: str,
        client_reference_id: str,
        success_url: str,
        cancel_url: str,
        trial_days: Optional[int],
    ) -> dict:
        """Create a subscription Checkout Session. Card is ALWAYS collected
        (payment_method_collection='always'), even with a trial (business rule
        §4). trial_days=None => no trial (immediate charge; used when the
        identity already consumed its trial)."""
        params: dict = {
            "mode": "subscription",
            "customer": customer_id,
            "line_items": [{"price": price_id, "quantity": 1}],
            "client_reference_id": client_reference_id,
            "success_url": success_url,
            "cancel_url": cancel_url,
            "payment_method_collection": "always",
        }
        if trial_days and trial_days > 0:
            params["subscription_data"] = {"trial_period_days": int(trial_days)}
        try:
            s = self._stripe.checkout.Session.create(**params)
        except Exception as exc:
            raise StripeError(f"create_checkout_session failed: {exc}") from exc
        return {"id": s["id"], "url": s["url"]}

    def create_billing_portal_session(self, customer_id: str, return_url: str) -> str:
        """Create a Billing Portal Session; return its URL. The Portal covers
        update-card / cancel / view-invoices out of the box (§8)."""
        try:
            s = self._stripe.billing_portal.Session.create(
                customer=customer_id, return_url=return_url
            )
        except Exception as exc:
            raise StripeError(f"create_billing_portal_session failed: {exc}") from exc
        return s["url"]

    # ── Reads (Fase 2D: sync return + reconciliation) ─────────────────────────
    def retrieve_checkout_session(self, session_id: str) -> dict:
        """Retrieve a Checkout Session with its subscription expanded, for the
        synchronous access confirmation on the success_url (§4 step 5a)."""
        try:
            s = self._stripe.checkout.Session.retrieve(
                session_id, expand=["subscription"]
            )
        except Exception as exc:
            raise StripeError(f"retrieve_checkout_session failed: {exc}") from exc
        return dict(s)

    def list_subscriptions(self, customer_id: str) -> list[dict]:
        """List a customer's subscriptions (all statuses) for reconciliation."""
        try:
            resp = self._stripe.Subscription.list(customer=customer_id, status="all")
        except Exception as exc:
            raise StripeError(f"list_subscriptions failed: {exc}") from exc
        return [dict(s) for s in (resp.get("data") or [])]
