"""Pure state -> tier resolution (Fase 2B).

`resolve_tier(user_id)` reads the local billing store (entitlement_grants +
subscriptions) and returns a tier STRING that already exists in
entitlements/policy.POLICY. It invents no entitlements; it only picks which
existing tier ("Admin" | "Pro" | "Locked") applies given the subscription state
and any manual grant. The state->tier table is
docs/FASE1_DISENO_TRIAL_SUSCRIPCION_STRIPE.md §3.

DORMANT in this phase: nothing calls this yet. get_tier (entitlements/
middleware.py) still resolves from Clerk exactly as before. The wiring happens
at cutover (Fase 2G), behind BILLING_ENABLED. This module imports NEITHER
middleware NOR Clerk — it is a leaf that only depends on the store and on policy
constants, so it can be unit-tested in complete isolation.
"""
from __future__ import annotations

import time
from typing import Optional

from app.billing import store as store_mod
from app.billing.store import Store

# Tiers this resolver can return. All three already exist in POLICY.
TIER_ADMIN = "Admin"
TIER_PRO = "Pro"
TIER_LOCKED = "Locked"

# Stripe subscription.status values that KEEP access (map to Pro).
#   - trialing/active: paid or in trial.
#   - past_due: failed charge, still in Stripe's Smart Retries window (decision
#     #4). We keep Pro until Stripe moves it to unpaid/canceled.
# Everything else (canceled|unpaid|incomplete|incomplete_expired|unknown) is
# fail-closed to Locked.
ACCESS_STATUSES = frozenset({"trialing", "active", "past_due"})


def _grant_is_active(expires_at: Optional[float], now: float) -> bool:
    """A grant with no expiry is perpetual; otherwise active until expires_at."""
    return expires_at is None or expires_at > now


def resolve_tier(
    user_id: Optional[str],
    now: Optional[float] = None,
    store: Optional[Store] = None,
) -> str:
    """Resolve the access tier for a user from local billing state.

    Precedence (first match wins):
      1. Active Admin grant            -> "Admin"
      2. Active Pro grant (comped /    -> "Pro"
         migration-trial window)
      3. Latest subscription in an     -> "Pro"
         access status (trialing/
         active/past_due)
      4. Anything else / no record     -> "Locked"  (fail-closed)

    `now` and `store` are injectable for tests; they default to the wall clock
    and the process singleton.
    """
    if not user_id:
        return TIER_LOCKED

    now = time.time() if now is None else now
    st = store if store is not None else store_mod.get_store()

    # 1 & 2 — manual grant wins over subscription state (Admin over Pro).
    grant = st.get_grant(user_id)
    if grant is not None and _grant_is_active(grant.expires_at, now):
        if grant.grant_tier == TIER_ADMIN:
            return TIER_ADMIN
        if grant.grant_tier == TIER_PRO:
            return TIER_PRO
        # An unknown grant_tier is not trusted for access.
        return TIER_LOCKED

    # 3 — subscription state.
    sub = st.get_latest_subscription_for_user(user_id)
    if sub is not None and sub.status in ACCESS_STATUSES:
        return TIER_PRO

    # 4 — no active grant, no access-granting subscription.
    return TIER_LOCKED
