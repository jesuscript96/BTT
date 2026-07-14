"""
Entitlements policy — single source of truth for tiers and feature access.

Free / Mid / Pro siguen prácticamente abiertos (booleans True, limits -1 = ilimitado):
la app se comporta como antes para ellos. Lo que varía hoy por tier es
`admin.preview_features` (solo Admin) y el tier "Beta", que sí restringe de verdad.

"Beta" (2026-07) es para los beta-testers invitados: solo Screener, Ticker Analysis,
Backtester y Baúl. Es el ÚNICO tier con `market.analysis.access` en False.

Para activar el resto de restricciones (ver docs/entitlements/ARQUITECTURA.md) basta
con editar los valores de POLICY — el comentario tras cada límite muestra el valor de
producción propuesto. Pero OJO: para que un cambio aquí BLOQUEE algo, el endpoint tiene
que llevar `Depends(require(...))`. Hoy solo lo llevan los de Market Analysis, Market
Sentiment y el portal de API; el resto del backend sigue sin guarda.
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
    "screener.access": "boolean",
    "api.portal.access": "boolean",
    "market.sentiment.access": "boolean",
    "market.analysis.access": "boolean",
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
        "screener.access": True,
        "api.portal.access": True,
        "market.sentiment.access": True,
        "market.analysis.access": True,
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
        "screener.access": True,
        "api.portal.access": False,
        "market.sentiment.access": False,
        "market.analysis.access": True,
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
        "screener.access": True,
        "api.portal.access": False,
        "market.sentiment.access": False,
        "market.analysis.access": True,
        "admin.preview_features": False,
    },
    # Beta-testers invitados (2026-07): SOLO Screener, Ticker Analysis, Backtester
    # y Baúl. Todo lo demás cerrado — es el único tier con market.analysis.access
    # en False, y por eso el gating de Market Analysis solo muerde aquí.
    "Beta": {
        "backtester.run": True,
        "backtester.surface_3d": True,
        "backtester.runs_per_day": -1,
        "backtester.date_range_years": -1,
        "ticker.edgie_assessment": True,
        "ticker.edgie_messages_per_day": -1,
        "vault.access": True,
        "vault.max_strategies": -1,
        "api.access": False,
        "api.runs_per_month": 0,
        "screener.access": True,
        "api.portal.access": False,
        "market.sentiment.access": False,
        "market.analysis.access": False,
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
        "screener.access": True,
        "api.portal.access": False,
        "market.sentiment.access": False,
        "market.analysis.access": True,
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
