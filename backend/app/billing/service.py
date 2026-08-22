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
from app.billing.store import BillingCustomer, Store, Subscription
from app.billing.stripe_client import StripeGateway
from app.billing.stripe_objects import _id, parse_subscription
from app.billing.tier_resolver import resolve_tier


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

        # Path B (B1): an admin may grant this user a PREFERENTIAL trial length
        # keyed by user_id. It is claimed one-shot (consume_trial_override is
        # atomic on consumed_at) and deliberately overrides BOTH the default
        # window AND the anti-recycle default — an admin granting days is an
        # authorized exception. Card is still ALWAYS collected (B1), so the
        # anti-abuse fingerprint is unchanged; only the day count moves.
        override_days = self._store.consume_trial_override(user_id)
        if override_days is not None:
            trial_days = override_days
        else:
            trial_days = None if used_trial else config.BILLING_TRIAL_DAYS

        try:
            return self._gateway.create_checkout_session(
                customer_id=customer.stripe_customer_id,
                price_id=config.STRIPE_PRICE_ID_MONTHLY_EUR,
                client_reference_id=user_id,
                success_url=success,
                cancel_url=cancel,
                trial_days=trial_days,
            )
        except Exception:
            # The Checkout call failed AFTER we claimed the override — give it
            # back so a transient Stripe error never burns the admin's grant.
            if override_days is not None:
                self._store.rearm_trial_override(user_id)
            raise

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

    # ── Synchronous checkout confirmation (§4 step 5a) ───────────────────────
    def sync_checkout_return(self, session_id: str) -> Optional[Subscription]:
        """Called on the success_url: retrieve the Checkout Session (subscription
        expanded) and upsert the subscription NOW, so access does not wait on the
        webhook. Idempotent with the webhook path (same parser, same upsert)."""
        session = self._gateway.retrieve_checkout_session(session_id)
        sub_obj = session.get("subscription")
        if not sub_obj or isinstance(sub_obj, str):
            # No expanded subscription (e.g. not completed yet) — nothing to sync.
            return None
        fields = parse_subscription(sub_obj)
        user_id = session.get("client_reference_id")
        if not user_id:
            customer = self._store.get_customer_by_stripe_id(fields["stripe_customer_id"])
            user_id = customer.user_id if customer else None
        if not user_id:
            return None
        # Ensure the customer link exists (webhook may not have arrived yet).
        if self._store.get_customer_by_user(user_id) is None:
            store_customer_id = fields["stripe_customer_id"] or _id(session.get("customer"))
            if store_customer_id:
                self._store.upsert_customer(user_id, store_customer_id)
        return self._store.upsert_subscription(user_id=user_id, **fields)

    # ── Reconciliation (heal missed webhooks) ────────────────────────────────
    def reconcile_user(self, user_id: str) -> Optional[Subscription]:
        """Re-pull the user's subscriptions from Stripe and upsert the latest.
        Stripe is the source of truth; this repairs local drift."""
        customer = self._store.get_customer_by_user(user_id)
        if customer is None:
            return None
        subs = self._gateway.list_subscriptions(customer.stripe_customer_id)
        latest: Optional[Subscription] = None
        for sub_obj in subs:
            fields = parse_subscription(sub_obj)
            latest = self._store.upsert_subscription(user_id=user_id, **fields)
        return latest

    def reconcile_all(self) -> int:
        """Reconcile every known customer. Returns the count reconciled. Meant to
        run from a nightly job (host cron / scheduler), not a request path."""
        count = 0
        for customer in self._store.list_customers():
            if self.reconcile_user(customer.user_id) is not None:
                count += 1
        return count

    # ── Billing summary for the UI (GET /api/billing/me) ─────────────────────
    def _reconcile_identity_email(self, user_id: str, email: Optional[str]) -> None:
        """Materialize/revoke ADMIN or COURTESY access from the email lists (Fase 3).

        With a TRUSTED email (Clerk JWT), drive the user's single entitlement grant
        from the two email allowlists, admin winning over comped:
          - listed as admin  -> Admin grant (reason='admin', perpetual)
          - else listed comped -> Pro grant (reason='comped', perpetual)
          - on neither list  -> delete ONLY an identity grant (reason in
                                admin/comped); never touch a migration-trial or
                                subscription-derived grant.
        Keyed by user_id so the product gate (resolve_tier) honors it too, and it
        auto-applies the moment an invited colleague/admin registers. Idempotent:
        only writes when the current grant differs from the target, so it does not
        churn the store on every /me. No-op without a trusted email, so we never
        grant or revoke something we can't verify.
        """
        if not email:
            return
        grant = self._store.get_grant(user_id)
        is_identity_grant = grant is not None and grant.reason in ("admin", "comped")

        if self._store.has_admin_email(email):
            already = (
                grant is not None
                and grant.grant_tier == "Admin"
                and grant.reason == "admin"
            )
            if not already:
                self._store.upsert_grant(user_id, "Admin", reason="admin", expires_at=None)
        elif self._store.has_comped_email(email):
            already = (
                grant is not None
                and grant.grant_tier == "Pro"
                and grant.reason == "comped"
            )
            if not already:
                self._store.upsert_grant(user_id, "Pro", reason="comped", expires_at=None)
        elif is_identity_grant:
            # No longer on either list: revoke on next /me.
            self._store.delete_grant(user_id)

    def _reconcile_trial_override_email(self, user_id: str, email: Optional[str]) -> None:
        """Seed a preferential trial length from the email list (Fase 3).

        With a TRUSTED email: if the email carries a preferential trial and the user
        has NO override yet, seed a one-shot trial_override keyed by user_id. Seed
        ONCE only — never re-arm from the list, so a consumed preferential trial
        cannot recycle on every login. Migration-proof: after a Clerk-instance
        change the same email re-seeds under the new user_id automatically. No-op
        without a trusted email or if the user already has an override (pending or
        consumed)."""
        if not email:
            return
        row = self._store.get_trial_override_email(email)
        if row is None:
            return
        if self._store.get_trial_override(user_id) is None:
            days, reason, granted_by = row
            self._store.set_trial_override(
                user_id, days, reason=reason, granted_by=granted_by
            )

    def get_billing_summary(self, user_id: str, email: Optional[str] = None) -> dict:
        """Read-only snapshot for the billing section (no Stripe call): resolved
        tier + subscription + default payment method + invoices + the trial
        countdown source (subscription.trial_end or a migration grant) + a single
        `stage` string that tells the frontend which screen to render (Fase 3)."""
        # Identity-by-email reconciliation first (may seed/revoke an admin or
        # comped grant, and seed a preferential trial). These materialize grants
        # keyed by user_id so resolve_tier + the product gate honor them too.
        self._reconcile_identity_email(user_id, email)
        self._reconcile_trial_override_email(user_id, email)
        # Admin/comped allowlists (env, user_id-based) win over subscription state
        # (same precedence as get_tier), so neither ever sees the card gate. The
        # email path above feeds resolve_tier via a materialized grant; these env
        # lists remain as a user_id-based override. Without this the summary would
        # resolve_tier() → Locked for an env-listed user with no grant/sub.
        is_comped = bool(user_id and user_id in config.billing_comped_user_ids())
        if user_id and user_id in config.billing_admin_ids():
            tier = "Admin"
        elif is_comped:
            tier = "Pro"  # comped: full access, free (no card, no charge)
        else:
            tier = resolve_tier(user_id, store=self._store)
        sub = self._store.get_latest_subscription_for_user(user_id)
        pm = self._store.get_default_payment_method(user_id)
        grant = self._store.get_grant(user_id)
        invoices = self._store.list_invoices(user_id)
        return {
            "tier": tier,
            "access": tier != "Locked",
            # Admin precedence over comped (matches get_tier); _billing_stage
            # returns "admin" when tier is Admin.
            "stage": "comped" if (is_comped and tier != "Admin") else _billing_stage(tier, sub, grant),
            "plan": {
                "label": config.BILLING_PLAN_LABEL,
                "amount_cents": config.BILLING_PLAN_AMOUNT_CENTS,
                "currency": config.BILLING_PLAN_CURRENCY,
                "interval": config.BILLING_PLAN_INTERVAL,
            },
            "subscription": _subscription_dict(sub),
            "grant": _grant_dict(grant),
            "payment_method": _payment_method_dict(pm),
            "invoices": [_invoice_dict(i) for i in invoices],
        }


# ── Onboarding/gate stage (Fase 3) ────────────────────────────────────────────
# One string the frontend maps 1:1 to a screen, computed from authoritative
# state so the client never guesses new-vs-returning from partial signals.
#   admin        — internal, never gated (no card, no trial)
#   trialing     — Stripe trial running (access)
#   active       — paying (access)
#   past_due     — failed charge, Smart Retries window (access kept)
#   trial_grant  — migrated user on the in-app 7-day grant (access, no sub yet)
#   resubscribe  — was subscribed, now no access → returning user (baja→vuelve),
#                  Checkout WITHOUT trial (server-side anti-recycle decides)
#   onboarding   — never subscribed + no access → new user / REGISTRADO_SIN_TARJETA
#   comped       — courtesy allowlist (colleague): full access, free, no card.
#                  Set by the caller (allowlist) BEFORE this helper, not here.
def _billing_stage(tier: str, sub, grant) -> str:
    if tier == "Admin":
        return "admin"
    if tier != "Locked":  # has access
        if sub is not None and sub.status in ("trialing", "active", "past_due"):
            return sub.status
        if grant is not None and grant.grant_tier == "Pro":
            # A perpetual courtesy grant vs the expiring migration-trial grant.
            return "comped" if grant.reason == "comped" else "trial_grant"
        return "active"  # access via some other path; treat as active
    # No access (Locked). A prior subscription row means the user already went
    # through Checkout once → returning; otherwise they never put a card in.
    return "resubscribe" if sub is not None else "onboarding"


# ── Serializers (dataclass -> plain JSON dict for the API) ────────────────────
def _subscription_dict(sub) -> Optional[dict]:
    if sub is None:
        return None
    return {
        "status": sub.status,
        "price_id": sub.price_id,
        "currency": sub.currency,
        "trial_end": sub.trial_end,
        "current_period_end": sub.current_period_end,
        "cancel_at_period_end": sub.cancel_at_period_end,
        "canceled_at": sub.canceled_at,
    }


def _grant_dict(grant) -> Optional[dict]:
    if grant is None:
        return None
    return {
        "grant_tier": grant.grant_tier,
        "reason": grant.reason,
        "expires_at": grant.expires_at,
    }


def _payment_method_dict(pm) -> Optional[dict]:
    if pm is None:
        return None
    return {
        "brand": pm.brand,
        "last4": pm.last4,
        "exp_month": pm.exp_month,
        "exp_year": pm.exp_year,
    }


def _invoice_dict(inv) -> dict:
    return {
        "status": inv.status,
        "amount_due": inv.amount_due,
        "amount_paid": inv.amount_paid,
        "currency": inv.currency,
        "hosted_invoice_url": inv.hosted_invoice_url,
        "invoice_pdf": inv.invoice_pdf,
        "period_start": inv.period_start,
        "period_end": inv.period_end,
        "created_at": inv.created_at,
    }
