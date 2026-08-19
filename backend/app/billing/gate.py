"""Subscription gate for product endpoints (Fase 2E).

Adds a server-side guard to the product surfaces that historically had NONE
(Backtester, Ticker Analysis, Baúl, Screener), so that "no subscription = no
product" is REAL and not just a hidden menu item.

Dormancy is the whole point: when BILLING_ENABLED is false (default, prod today)
the gate is a strict NO-OP — it returns True BEFORE looking at the token, so
currently-public endpoints stay public and authed ones are unchanged, with zero
added Clerk/JWT cost. It only starts enforcing at cutover (Fase 2G), and it
enforces from the LOCAL store (resolve_tier), never a per-request Clerk call.

We deliberately do NOT depend on get_current_user_id (which RAISES 401 on
anonymous requests) — that would change behavior on public endpoints even while
dormant. Instead we read the Authorization header and resolve identity the
non-raising way only when actually enforcing.
"""
from __future__ import annotations

from typing import Optional

from fastapi import Header, HTTPException

from app.auth.clerk import get_optional_user_id
from app.billing import config
from app.entitlements.checker import EntitlementError, check_can


def subscription_gate(feature: str):
    """Dependency factory. Allows the request only if the caller's resolved tier
    can access `feature`. No-op while BILLING_ENABLED is off."""

    def _dependency(authorization: Optional[str] = Header(default=None)) -> bool:
        if not config.BILLING_ENABLED:
            return True  # dormant: do not even parse the token
        # Import here to avoid a load-time cycle (middleware imports billing).
        from app.entitlements.middleware import get_tier

        user_id = get_optional_user_id(authorization)  # never raises; None if anon
        # get_tier under BILLING_ENABLED = admin allowlist + resolve_tier(local
        # store); anon -> Locked. Same resolution as require(), so admins granted
        # via the env allowlist are not wrongly blocked here.
        tier = get_tier(user_id)
        try:
            check_can(tier, feature)
        except EntitlementError as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "subscription_required",
                    "feature": exc.feature,
                    "reason": exc.reason,
                },
            )
        return True

    return _dependency
