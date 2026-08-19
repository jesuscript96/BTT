"""Billing service (Fase 2C): orchestrates Stripe + the local store.

Outbound flows only (create customer / start checkout / open portal) and the
trial-vs-no-trial decision. Inbound state (webhook parsing, subscription
mirroring, reconciliation) is Fase 2D. Dormant: reachable only via the router,
which main.py mounts solely when BILLING_ENABLED.
"""
from __future__ import annotations

from typing import Optional

from app.billing import config
from app.billing import store as store_mod
from app.billing.store import BillingCustomer, Store
from app.billing.stripe_client import StripeGateway


class BillingError(Exception):
    """Domain error surfaced to the router as a 4xx (bad state / misconfig)."""


def normalize_email(email: str) -> str:
    """Identity key for the trial ledger. Lowercased + trimmed so casing/spacing
    variants of the same address dedupe to one trial."""
    return email.strip().lower()


class BillingService:
    def __init__(self, store: Optional[Store] = None, gateway: Optional[StripeGateway] = None):
        # gateway is constructed lazily by the caller in prod; tests inject a
        # fake. Only build the real one when neither is provided.
        self._store = store if store is not None else store_mod.get_store()
        self._gateway = gateway if gateway is not None else StripeGateway()

    # ── Customer ─────────────────────────────────────────────────────────────
    def get_or_create_customer(self, user_id: str, email: Optional[str]) -> BillingCustomer:
        """Idempotent: reuse the stored Stripe customer for this user, else
        create one in Stripe (tagging clerk_user_id) and persist the link."""
        existing = self._store.get_customer_by_user(user_id)
        if existing is not None:
            return existing
        customer_id = self._gateway.create_customer(
            email=email, metadata={"clerk_user_id": user_id}
        )
        return self._store.upsert_customer(user_id, customer_id, email=email)

    # ── Checkout ─────────────────────────────────────────────────────────────
    def start_subscription_checkout(
        self,
        user_id: str,
        email: Optional[str],
        success_url: Optional[str] = None,
        cancel_url: Optional[str] = None,
    ) -> dict:
        """Create a Checkout Session for the 29€/mo subscription. Returns
        {id, url}. Decides trial vs no-trial by the anti-recycle rule (§4).

        NOTE on anti-recycle: at checkout-creation time we only know the EMAIL,
        so we dedupe on email here; the card-fingerprint half of the rule is
        recorded by the webhook after payment (Fase 2D). So a first-time email
        gets the 7-day trial; a returning email is charged immediately.
        """
        if not config.STRIPE_PRICE_ID_MONTHLY_EUR:
            raise BillingError("STRIPE_PRICE_ID_MONTHLY_EUR not configured")
        success = success_url or config.BILLING_SUCCESS_URL
        cancel = cancel_url or config.BILLING_CANCEL_URL
        if not success or not cancel:
            raise BillingError("Checkout success_url/cancel_url not configured")

        customer = self.get_or_create_customer(user_id, email)

        used_trial = False
        if email:
            used_trial = self._store.has_used_trial(normalize_email(email))
        trial_days = None if used_trial else config.BILLING_TRIAL_DAYS

        return self._gateway.create_checkout_session(
            customer_id=customer.stripe_customer_id,
            price_id=config.STRIPE_PRICE_ID_MONTHLY_EUR,
            client_reference_id=user_id,
            success_url=success,
            cancel_url=cancel,
            trial_days=trial_days,
        )

    # ── Billing Portal ───────────────────────────────────────────────────────
    def open_billing_portal(self, user_id: str, return_url: Optional[str] = None) -> str:
        """Create a Billing Portal Session URL for an existing customer."""
        customer = self._store.get_customer_by_user(user_id)
        if customer is None:
            raise BillingError("No billing customer for this user")
        ret = return_url or config.BILLING_PORTAL_RETURN_URL
        if not ret:
            raise BillingError("BILLING_PORTAL_RETURN_URL not configured")
        return self._gateway.create_billing_portal_session(customer.stripe_customer_id, ret)
