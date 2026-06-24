"""Usage metering (always on). Records consumption to the ledger so ANY future
billing/quota policy can be applied without code changes (docs/b2d-gateway/05 §5).

We record the REAL `ticker_days` and `trades` the engine reports — the orchestrator
already exposes them, so metering needs no engine instrumentation.
"""
from __future__ import annotations

from app.api_public.core.auth import Principal
from app.api_public.core.store import get_store


def record_run(
    principal: Principal, module: str, action: str, ticker_days: int = 0, trades: int = 0
) -> None:
    get_store().record_usage(
        api_key_id=principal.api_key_id,
        module=module,
        action=action,
        ticker_days=int(ticker_days or 0),
        trades=int(trades or 0),
    )
