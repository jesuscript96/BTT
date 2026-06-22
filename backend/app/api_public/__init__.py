"""Edgecute Backtest API — public B2D layer.

A modular, isolated public API mounted on top of the existing backtesting engine.
It NEVER imports the engine directly: the only bridge to the core is `facade.py`.

See docs/b2d-gateway/ for the full design. Structure:
    core/      cross-cutting: auth, gating, metering, ratelimit, errors, payload, store
    modules/   one self-contained package per domain (MVP: backtest)
    facade.py  the single permitted bridge to the engine
    app.py     ASGI app that mounts ENABLED_MODULES
"""

__version__ = "0.1.0"
