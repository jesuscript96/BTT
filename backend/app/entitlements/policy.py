"""
Entitlements policy — single source of truth for tiers and feature access.

Phase 1 / MVP: everything is open (booleans True, limits -1 = unlimited) for
every tier, so the app behaves exactly as before. The ONLY thing that varies by
tier today is `admin.preview_features`, which gates in-development features and
is True only for the "Admin" tier (Jaume).

To activate real restrictions later (see docs/entitlements/ARQUITECTURA.md),
edit the values in POLICY below — nothing else in the codebase needs to change.
The comment after each limit shows the proposed production value.
"""
from typing import Dict, Union

# Default tier for any user without an explicit tier in Clerk publicMetadata.
FREE_TIER = "Free"

FeatureValue = Union[bool, int]

# Feature catalog. "boolean" = on/off access; "limit" = numeric cap (-1 = ∞).
FEATURE_TYPES: Dict[str, str] = {
    "backtester.run": "boolean",
    "backtester.surface_3d": "boolean",
    "backtester.runs_per_day": "limit",
    "backtester.date_range_years": "limit",
    "ticker.edgie_assessment": "boolean",
    "ticker.edgie_messages_per_day": "limit",
    "vault.access": "boolean",
    "vault.max_strategies": "limit",
    "api.access": "boolean",
    "api.runs_per_month": "limit",
    # Internal flag: unlocks features still in development. Admin-only.
    "admin.preview_features": "boolean",
}

# Limit features that are tracked as time-windowed counters in Redis (usage.py).
# Other limits (date_range_years, max_strategies) are state caps, not rate
# counters, so they are NOT reported under the endpoint's "usage" block.
LIMIT_WINDOWS: Dict[str, str] = {
    "backtester.runs_per_day": "day",
    "ticker.edgie_messages_per_day": "day",
    "api.runs_per_month": "month",
}

# Declarative tier table — THE source of truth.
# MVP: all open. Comments show the proposed production values to flip later.
POLICY: Dict[str, Dict[str, FeatureValue]] = {
    "Admin": {
        "backtester.run": True,
        "backtester.surface_3d": True,
        "backtester.runs_per_day": -1,
        "backtester.date_range_years": -1,
        "ticker.edgie_assessment": True,
        "ticker.edgie_messages_per_day": -1,
        "vault.access": True,
        "vault.max_strategies": -1,
        "api.access": True,
        "api.runs_per_month": -1,
        "admin.preview_features": True,   # only Admin sees in-development features
    },
    "Pro": {
        "backtester.run": True,
        "backtester.surface_3d": True,
        "backtester.runs_per_day": -1,    # prod: -1
        "backtester.date_range_years": -1,  # prod: -1
        "ticker.edgie_assessment": True,
        "ticker.edgie_messages_per_day": -1,  # prod: -1
        "vault.access": True,
        "vault.max_strategies": -1,       # prod: -1
        "api.access": True,
        "api.runs_per_month": -1,         # prod: -1
        "admin.preview_features": False,
    },
    "Mid": {
        "backtester.run": True,
        "backtester.surface_3d": True,    # prod: True
        "backtester.runs_per_day": -1,    # prod: 50
        "backtester.date_range_years": -1,  # prod: 4
        "ticker.edgie_assessment": True,
        "ticker.edgie_messages_per_day": -1,  # prod: -1
        "vault.access": True,
        "vault.max_strategies": -1,       # prod: 25
        "api.access": True,               # prod: False
        "api.runs_per_month": -1,         # prod: 0
        "admin.preview_features": False,
    },
    "Free": {
        "backtester.run": True,
        "backtester.surface_3d": True,    # prod: False
        "backtester.runs_per_day": -1,    # prod: 5
        "backtester.date_range_years": -1,  # prod: 2
        "ticker.edgie_assessment": True,
        "ticker.edgie_messages_per_day": -1,  # prod: 5
        "vault.access": True,
        "vault.max_strategies": -1,       # prod: 3
        "api.access": True,               # prod: False
        "api.runs_per_month": -1,         # prod: 0
        "admin.preview_features": False,
    },
}


def tier_policy(tier: str) -> Dict[str, FeatureValue]:
    """Return a COPY of the full feature map for a tier (Free if unknown)."""
    return dict(POLICY.get(tier, POLICY[FREE_TIER]))


def can(tier: str, feature: str) -> bool:
    """Boolean access check. Unknown tier -> Free; unknown feature -> allow."""
    table = POLICY.get(tier, POLICY[FREE_TIER])
    return bool(table.get(feature, True))


def limit(tier: str, feature: str) -> int:
    """Numeric limit (-1 = unlimited). Unknown tier -> Free; unknown -> -1."""
    table = POLICY.get(tier, POLICY[FREE_TIER])
    value = table.get(feature, -1)
    # Defensive: a boolean stored where a limit is expected -> treat as unlimited.
    if isinstance(value, bool):
        return -1
    return int(value)


def is_unlimited(value: int) -> bool:
    return value == -1
