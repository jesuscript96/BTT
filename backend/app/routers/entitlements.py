"""
Entitlements endpoint — exposes the caller's tier, full policy, and current
usage so the frontend can show/hide features and render quota counters.

Mounted under /api/users in main.py  ->  GET /api/users/me/entitlements
"""
from typing import Optional

from fastapi import APIRouter, Depends

from app.auth.clerk import get_current_user_id
from app.entitlements import policy, usage
from app.entitlements.middleware import get_tier

router = APIRouter()


@router.get("/me/entitlements")
def get_my_entitlements(user_id: Optional[str] = Depends(get_current_user_id)):
    """Return the resolved tier, its full feature policy, and windowed usage."""
    tier = get_tier(user_id)

    usage_map = {}
    if user_id:
        for feature in policy.LIMIT_WINDOWS:
            usage_map[feature] = usage.get_usage(user_id, feature)

    return {
        "tier": tier,
        "entitlements": policy.tier_policy(tier),
        "usage": usage_map,
    }
