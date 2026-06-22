"""Configuration for the public API. All values via env (CODING_RULES.md), with
sensible technical defaults. NO monetization policy lives here — tiers/prices are
a product decision (docs/b2d-gateway/07). The values below are technical limits.
"""
import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# ── Identity ────────────────────────────────────────────────────────────────
API_TITLE = "Edgecute Backtest API"
API_VERSION = "0.1.0"
API_PREFIX = "/v1"

# ── Modular composition ──────────────────────────────────────────────────────
# Comma-separated list of enabled modules. MVP ships only `backtest`.
ENABLED_MODULES = [
    m.strip() for m in os.getenv("EDGECUTE_ENABLED_MODULES", "backtest").split(",") if m.strip()
]

# ── Technical limits (NOT pricing — see docs/b2d-gateway/07 §B) ───────────────
# Hard cap so the synchronous API always finishes within the platform envelope.
# Size it from a load test against the deployed backend (Railway + uvicorn).
MAX_TICKER_DAYS_PER_RUN = _int("EDGECUTE_MAX_TICKER_DAYS", 50_000)
# Equity/drawdown series get LTTB-downsampled above this many points (payload rule).
EQUITY_DOWNSAMPLE_MAX_POINTS = _int("EDGECUTE_EQUITY_MAX_POINTS", 2_000)
# Trades pagination.
TRADES_DEFAULT_LIMIT = _int("EDGECUTE_TRADES_DEFAULT_LIMIT", 500)
TRADES_MAX_LIMIT = _int("EDGECUTE_TRADES_MAX_LIMIT", 5_000)
# In-process rate limit (requests per minute per API key). Redis = v2.
RATE_LIMIT_RPM = _int("EDGECUTE_RATE_LIMIT_RPM", 120)

# ── Store ────────────────────────────────────────────────────────────────────
# SQLite by default (zero-infra, runnable/testable). Prod points to Postgres via
# a DATABASE_URL (DSN), swap implemented behind the Store abstraction.
STORE_PATH = os.getenv("EDGECUTE_STORE_PATH", os.path.join(os.getcwd(), "edgecute_api.sqlite"))
DATABASE_URL = os.getenv("EDGECUTE_DATABASE_URL")  # reserved for Postgres (v2)

# ── Auth ─────────────────────────────────────────────────────────────────────
# When False, requests resolve to a synthetic principal (dev only). Prod = True.
AUTH_REQUIRED = os.getenv("EDGECUTE_AUTH_REQUIRED", "true").lower() in ("1", "true", "yes")

# ── Technical plan defaults (mechanism, not policy) ──────────────────────────
# A single neutral plan. The *policy* (who gets what, pricing) is decided later
# and applied as config/data — see docs/b2d-gateway/07 §A. The gating hook
# (core/gating.py) defaults to allow.
DEFAULT_PLAN = {
    "name": "default",
    "max_ticker_days_per_run": MAX_TICKER_DAYS_PER_RUN,
    "rate_limit_rpm": RATE_LIMIT_RPM,
}
