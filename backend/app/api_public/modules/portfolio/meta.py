"""Module descriptor for `portfolio`. Mounted generically when listed in
EDGECUTE_ENABLED_MODULES. The `gating_tag` is what the (deferred) policy keys on.
"""
from app.api_public.modules.portfolio.router import router

MODULE = {
    "name": "portfolio",
    "version": "0.1.0",
    "gating_tag": "portfolio",
    "router": router,
    "description": "Combina backtests guardados en una cartera: equity agregada, Monte Carlo, VaR/CVaR, correlación y asignación de capital (Líderes/HRP).",
}
