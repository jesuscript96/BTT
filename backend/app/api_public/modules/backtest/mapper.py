"""Map the public API contract <-> the engine's BacktestRequest, and shape the raw
engine result into the public DTO applying payload rules (downsample/paginate/include).
"""
from __future__ import annotations

from typing import Optional

from app.api_public.core.errors import ApiError
from app.api_public.core.payload import downsample_series, paginate_trades
from app.api_public.modules.backtest.models import BacktestCreate


def to_request_kwargs(body: BacktestCreate) -> dict:
    """Build kwargs for the engine BacktestRequest. MVP requires an existing dataset."""
    uni = body.universe
    if uni is None or not uni.dataset_ref:
        if uni is not None and uni.filters:
            raise ApiError(
                "not_implemented",
                "La creación de universo por filtros es v2. Usa 'universe.dataset_ref' "
                "con un dataset existente, o 'mock_dataset_1' para el sandbox.",
                details={"hint": "universe.dataset_ref"},
            )
        raise ApiError(
            "invalid_universe",
            "Falta 'universe.dataset_ref' (un dataset existente o 'mock_dataset_1').",
            details={"hint": "universe.dataset_ref"},
        )

    ex = body.execution
    return {
        "dataset_id": uni.dataset_ref,
        "strategy_definition": body.strategy.model_dump(mode="json"),
        "init_cash": ex.init_cash,
        "risk_r": ex.risk_r,
        "risk_type": ex.risk_type,
        "fixed_ratio_delta": ex.fixed_ratio_delta,
        "size_by_sl": ex.size_by_sl,
        "fees": ex.fees,
        "fee_type": ex.fee_type,
        "monthly_expenses": ex.monthly_expenses,
        "slippage": ex.slippage,
        "start_date": uni.date_from,
        "end_date": uni.date_to,
        "market_sessions": ex.market_sessions,
        "custom_start_time": ex.custom_start_time,
        "custom_end_time": ex.custom_end_time,
        "locates_cost": ex.locates_cost,
        "look_ahead_prevention": ex.look_ahead_prevention,
    }


def _clean_series(points) -> list[dict]:
    """Drop points whose value is None (engine sanitizes NaN/inf -> None) so the
    downsampler and the typed DTO never see a non-numeric value."""
    out = []
    for p in points or []:
        v = p.get("value")
        t = p.get("time")
        if v is None or t is None:
            continue
        out.append({"time": t, "value": v})
    return out


def build_result(
    raw: dict,
    include: list[str],
    trades_limit: Optional[int],
    trades_cursor: Optional[str],
) -> tuple[dict, dict]:
    """Return (result_dto, partial_meta). `equity_curves` (intraday) is NEVER included
    here — it's the payload bomb; fetched one series at a time via /intraday."""
    wanted = set(include or [])
    result: dict = {}
    downsampled = False

    if "metrics" in wanted:
        result["aggregate_metrics"] = raw.get("aggregate_metrics") or {}

    if "equity" in wanted:
        ge, d1 = downsample_series(_clean_series(raw.get("global_equity")))
        gd, d2 = downsample_series(_clean_series(raw.get("global_drawdown")))
        result["global_equity"] = ge
        result["global_drawdown"] = gd
        downsampled = d1 or d2

    if "days" in wanted:
        result["day_results"] = raw.get("day_results") or []

    if "trades" in wanted:
        result["trades"] = paginate_trades(
            raw.get("trades") or [], trades_limit, trades_cursor
        )

    meta = {
        "trades_total": len(raw.get("trades") or []),
        "downsampled": downsampled,
    }
    return result, meta


def find_intraday_series(raw: dict, ticker: str, date: str) -> Optional[dict]:
    """Pull a single intraday equity series from the stored raw result."""
    for series in raw.get("equity_curves") or []:
        if str(series.get("ticker")) == ticker and str(series.get("date")) == date:
            return {
                "ticker": ticker,
                "date": date,
                "equity": series.get("equity") or [],
            }
    return None
