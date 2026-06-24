"""Module descriptor for `backtest`.

Every module exposes a `MODULE` descriptor so the app can mount it generically
(docs/b2d-gateway/05 §0). The `gating_tag` is what the (deferred) policy keys on.
"""
from app.api_public.modules.backtest.router import router

MODULE = {
    "name": "backtest",
    "version": "0.1.0",
    "gating_tag": "backtest",
    "router": router,
    "description": "Ejecuta backtests de gaps/short-selling y devuelve métricas, equity y trades.",
}
