"""Module descriptor for `robustness` (docs/b2d-gateway/05 §0).

The `gating_tag` is the key the (deferred) monetization policy uses — the policy
itself (free/paid, who, when) is NOT decided here (decisión de Jesús,
docs/b2d-gateway/07 + docs/robustez/06 §Decisiones abiertas).
"""
from app.api_public.modules.robustness.router import router

MODULE = {
    "name": "robustness",
    "version": "0.1.0",
    "gating_tag": "robustness",
    "router": router,
    "description": "Stress-test de estrategias guardadas: Montecarlo bootstrap, sensibilidad de locates/slippage y Black Swan.",
}
