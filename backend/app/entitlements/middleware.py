"""
FastAPI dependencies for entitlement enforcement.

    @router.post("/surface")
    async def run_surface(_=Depends(require("backtester.surface_3d"))):
        ...

    @router.post("/run")
    async def run_backtest(
        _=Depends(require("backtester.run")),
        __=Depends(consume("backtester.runs_per_day")),
    ):
        ...

Tier resolution (`get_tier`) currently reads Clerk publicMetadata.tier via the
Clerk REST API. It fails open to "Free" whenever auth is disabled, the secret
is missing, the user has no tier, or the call errors — the app must never break
because tier lookup hiccupped.
"""
import os
from typing import Optional

import httpx
from fastapi import Depends, HTTPException

from app.auth.clerk import get_current_user_id
from app.entitlements import policy, usage
from app.entitlements.checker import EntitlementError, check_can, check_limit

CLERK_API_BASE = "https://api.clerk.com/v1"
_CLERK_TIMEOUT = 5.0


def get_tier(user_id: Optional[str]) -> str:
    """
    Resolve a user's tier from Clerk publicMetadata.tier.

    Fails open to Free on any of: no user_id (auth disabled / anonymous),
    no CLERK_SECRET_KEY, missing/unknown tier, or a network/HTTP error.
    """
    if not user_id:
        return policy.FREE_TIER

    secret = os.getenv("CLERK_SECRET_KEY", "").strip()
    if not secret:
        return policy.FREE_TIER

    try:
        resp = httpx.get(
            f"{CLERK_API_BASE}/users/{user_id}",
            headers={"Authorization": f"Bearer {secret}"},
            timeout=_CLERK_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        tier = (data.get("public_metadata") or {}).get("tier")
        if tier in policy.POLICY:
            return tier
    except Exception:
        pass
    return policy.FREE_TIER


# Kept as the documented internal name; get_tier is the public, reusable form.
_get_tier = get_tier


def require(feature: str):
    """Dependency that allows the request only if the tier can access `feature`."""

    def _dependency(user_id: Optional[str] = Depends(get_current_user_id)) -> bool:
        tier = get_tier(user_id)
        try:
            check_can(tier, feature)
        except EntitlementError as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "forbidden",
                    "feature": exc.feature,
                    "reason": exc.reason,
                },
            )
        return True

    return _dependency


def consume(feature: str):
    """
    Dependency that enforces a quota AND consumes one unit of it.

    Checks the current usage against the tier's limit; on pass, increments the
    counter. Unlimited tiers/features still pass through without blocking (and
    increment harmlessly for visibility).
    """

    def _dependency(user_id: Optional[str] = Depends(get_current_user_id)) -> bool:
        tier = get_tier(user_id)
        current = usage.get_usage(user_id, feature) if user_id else 0
        try:
            check_limit(tier, feature, current)
        except EntitlementError as exc:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "limit_reached",
                    "feature": exc.feature,
                    "reason": exc.reason,
                },
            )
        if user_id:
            usage.increment_usage(user_id, feature)
        return True

    return _dependency
