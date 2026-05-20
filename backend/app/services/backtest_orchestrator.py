import gc
import json
import logging
import random
import time

from datetime import datetime, timezone

from fastapi import HTTPException
from pydantic import BaseModel

from app.services.data_service import (
    get_strategy,
    fetch_qualifying_data,
    get_intraday_stream,
    _resolve_filters,
)
from app.services.backtest_service import run_backtest

logger = logging.getLogger("backtester.orchestrator")


class BacktestRequest(BaseModel):
    dataset_id: str
    strategy_id: str
    init_cash: float = 10000.0
    risk_r: float = 100.0
    risk_type: str = "FIXED"
    fixed_ratio_delta: float = 500.0
    size_by_sl: bool = False
    fees: float = 0.0
    fee_type: str = "PERCENT"
    monthly_expenses: float = 0.0
    slippage: float = 0.0
    start_date: str | None = None
    end_date: str | None = None
    market_sessions: list[str] | None = None
    custom_start_time: str | None = None
    custom_end_time: str | None = None
    locates_cost: float = 0.0
    look_ahead_prevention: bool = False


def generate_mock_candles(ticker: str, date: str) -> dict:
    """Generate synthetic 1-min candles (390 bars, 9:30→16:00 ET) for mock dataset testing."""
    random.seed(hash(f"{ticker}{date}") & 0xFFFFFF)
    try:
        base_dt = datetime.strptime(date, "%Y-%m-%d").replace(
            hour=9, minute=30, tzinfo=timezone.utc
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date format")

    price = random.uniform(50, 300)
    candles = []
    for i in range(390):
        ts = int(base_dt.timestamp()) + i * 60
        change = random.gauss(0, 0.003) * price
        open_ = round(price, 2)
        close = round(max(price + change, 0.5), 2)
        high = round(max(open_, close) * (1 + abs(random.gauss(0, 0.001))), 2)
        low = round(min(open_, close) * (1 - abs(random.gauss(0, 0.001))), 2)
        volume = random.randint(1000, 50000)
        candles.append({
            "time": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "vwap": None,
        })
        price = close

    return {"ticker": ticker, "date": date, "candles": candles}


def run_backtest_orchestrator(req: BacktestRequest) -> dict:
    t0 = time.time()
    logger.info(f"BACKTEST START dataset={req.dataset_id} strategy={req.strategy_id}")

    # ── STRATEGY LOAD + VALIDATION ──
    strategy = get_strategy(req.strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")

    if req.size_by_sl:
        rm = strategy["definition"].get("risk_management", {})
        has_hard_stop = rm.get("use_hard_stop") and rm.get("hard_stop", {}).get("value", 0) > 0
        has_trailing = rm.get("trailing_stop", {}).get("active", False)
        if not has_hard_stop and not has_trailing:
            raise HTTPException(
                status_code=400,
                detail="La estrategia no tiene configurado un Stop Loss. "
                       "Desactiva 'Size por Distancia al SL' o añade un Stop Loss a la estrategia.",
            )

    logger.info(f"  strategy loaded ({round(time.time()-t0, 2)}s)")

    try:
        # ── PHASE 1: qualifying data (from local cache — fast) ──
        t_fetch = time.time()
        qualifying = fetch_qualifying_data(req.dataset_id, req.start_date, req.end_date)

        if qualifying.empty:
            logger.warning(f"  No qualifying data for dataset={req.dataset_id}")
            return {
                "aggregate_metrics": {},
                "day_results": [],
                "trades": [],
                "equity_curves": [],
                "global_equity": [],
                "global_drawdown": [],
            }

        if req.start_date:
            qualifying = qualifying[qualifying["date"].astype(str) >= req.start_date]
        if req.end_date:
            qualifying = qualifying[qualifying["date"].astype(str) <= req.end_date]

        n_qualifying = len(qualifying)
        n_tickers = qualifying["ticker"].nunique()
        logger.info(
            f"  qualifying: {n_qualifying} rows, {n_tickers} tickers "
            f"({round(time.time()-t_fetch, 2)}s)"
        )

        # ── PHASE 2: resolve date range for streaming ──
        filters = _resolve_filters(req.dataset_id, req.start_date, req.end_date)
        date_from = filters.get("start_date") or filters.get("date_from")
        date_to = filters.get("end_date") or filters.get("date_to")

        # ── PHASE 3: create streaming iterator ──
        print(f"[DEBUG] calling get_intraday_stream with qualifying={len(qualifying)} rows, date_from={date_from}, date_to={date_to}")
        intraday_stream = get_intraday_stream(qualifying, date_from, date_to)
        print(f"[DEBUG] intraday_stream created: type={type(intraday_stream)}")

        # ── PHASE 4: run backtest with streaming ──
        results = run_backtest(
            qualifying_df=qualifying,
            strategy_def=strategy["definition"],
            init_cash=req.init_cash,
            risk_r=req.risk_r,
            risk_type=req.risk_type,
            fixed_ratio_delta=req.fixed_ratio_delta,
            size_by_sl=req.size_by_sl,
            fees=req.fees,
            fee_type=req.fee_type,
            slippage=req.slippage,
            market_sessions=req.market_sessions,
            custom_start_time=req.custom_start_time,
            custom_end_time=req.custom_end_time,
            locates_cost=req.locates_cost,
            look_ahead_prevention=req.look_ahead_prevention,
            day_group_iter=intraday_stream,
            n_groups_hint=n_qualifying,
            monthly_expenses=req.monthly_expenses,
        )

        gc.collect()
        total_elapsed = round(time.time() - t0, 2)
        n_trades = len(results.get("trades", []))
        n_days = len(results.get("day_results", []))
        logger.info(
            f"BACKTEST DONE {n_days} days, {n_trades} trades, total={total_elapsed}s"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"  backtest FAILED after {round(time.time()-t0, 2)}s: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error en backtest: {str(e)}")

    return results
