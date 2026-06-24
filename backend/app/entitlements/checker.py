"""
Pure entitlement checks against the policy. No I/O here — callers pass in the
current usage. Raises EntitlementError on denial so the middleware can map it to
the right HTTP status.
"""
from app.entitlements import policy


class EntitlementError(Exception):
    """Raised when a tier is denied access to a feature or hits its limit."""

    def __init__(self, feature: str, reason: str):
        self.feature = feature
        self.reason = reason
        super().__init__(f"{feature}: {reason}")


def check_can(tier: str, feature: str) -> bool:
    """Boolean access gate. Raises EntitlementError if the tier lacks access."""
    if not policy.can(tier, feature):
        raise EntitlementError(
            feature, f"Tier '{tier}' does not have access to '{feature}'."
        )
    return True


def check_limit(tier: str, feature: str, current_usage: int) -> bool:
    """
    Quota gate. Unlimited (-1) always passes. Raises EntitlementError when the
    current usage has already reached the tier's limit.
    """
    allowed = policy.limit(tier, feature)
    if policy.is_unlimited(allowed):
        return True
    if current_usage >= allowed:
        raise EntitlementError(
            feature,
            f"Limit reached for '{feature}' ({current_usage}/{allowed}).",
        )
    return True
