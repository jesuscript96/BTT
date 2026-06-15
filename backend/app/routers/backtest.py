import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.data_service import fetch_day_candles
from app.services.backtest_orchestrator import (
    BacktestRequest,
    run_backtest_orchestrator,
    generate_mock_candles,
)
from app.services.montecarlo_service import run_montecarlo
from app.services.what_if_service import run_what_if

logger = logging.getLogger("backtester.backtest")

router = APIRouter(prefix="/api", tags=["backtest"])

backtest_progress = {}

@router.get("/backtest/progress/{dataset_id}")
def get_backtest_progress(dataset_id: str):
    if dataset_id not in backtest_progress:
        return {"status": "not_running", "percent": 0.0, "current": 0, "total": 0}
    return backtest_progress[dataset_id]


@router.post("/backtest/cancel/{dataset_id}")
def cancel_backtest(dataset_id: str):
    backtest_progress[dataset_id] = {
        "status": "cancelled",
        "percent": 0.0,
        "current": 0,
        "total": 0
    }
    return {"status": "success", "message": "Backtest cancellation requested"}



class MonteCarloRequest(BaseModel):
    pnls: list[float]
    init_cash: float = 10000.0
    simulations: int = 1000


class WhatIfRequest(BaseModel):
    trades: list[dict]
    init_cash: float = 10000.0
    risk_r: float = 100.0
    params: dict


@router.post("/backtest")
def run_backtest_endpoint(req: BacktestRequest):
    # Clear cancelled state if this is a fresh run
    if req.dataset_id in backtest_progress and backtest_progress[req.dataset_id].get("status") == "cancelled":
        backtest_progress.pop(req.dataset_id, None)

    # Check if dataset precache is running (state lives in users.duckdb so it
    # survives backend restarts and is shared across workers).
    from app.routers.query import get_precache_state
    state = get_precache_state(req.dataset_id)
    if state and state.get("status") == "running":
        percent = state.get("percent", 0.0)
        raise HTTPException(
            status_code=400,
            detail=f"Espera a que se cargue el dataset (progreso: {percent}%)"
        )
    return run_backtest_orchestrator(req)


@router.get("/candles")
def get_candles(dataset_id: str, ticker: str, date: str):
    if dataset_id == "mock_dataset_1":
        return generate_mock_candles(ticker, date)

    candles = fetch_day_candles(dataset_id, ticker, date)
    if not candles:
        raise HTTPException(status_code=404, detail="No candle data found")
    return {"ticker": ticker, "date": date, "candles": candles}


@router.get("/candles/multi")
def get_multi_candles(
    dataset_id: str,
    ticker: str,
    date: str,
    apply_day: str = "gap_day",
    swing_active: bool = False,
    swing_target_day: str = "gap_1_day"
):
    count = 1
    if apply_day == "gap_1_day":
        count = 2
    elif apply_day == "gap_2_day":
        count = 3

    if swing_active:
        if swing_target_day == "gap_2_day":
            count = max(count, 3)
        elif swing_target_day == "gap_1_day":
            count = max(count, 2)

    if dataset_id == "mock_dataset_1":
        from datetime import datetime, timedelta
        try:
            base_dt = datetime.strptime(date, "%Y-%m-%d")
        except Exception:
            base_dt = datetime.now()
        
        if apply_day == "gap_day":
            dates = [
                date,
                (base_dt + timedelta(days=1)).strftime("%Y-%m-%d"),
                (base_dt + timedelta(days=2)).strftime("%Y-%m-%d")
            ]
        elif apply_day == "gap_1_day":
            dates = [
                (base_dt - timedelta(days=1)).strftime("%Y-%m-%d"),
                date,
                (base_dt + timedelta(days=1)).strftime("%Y-%m-%d")
            ]
        else: # gap_2_day
            dates = [
                (base_dt - timedelta(days=2)).strftime("%Y-%m-%d"),
                (base_dt - timedelta(days=1)).strftime("%Y-%m-%d"),
                date
            ]
        dates = dates[:count]
    else:
        from app.database import get_db_connection
        con = get_db_connection()
        try:
            if apply_day == "gap_day":
                query = """
                    SELECT DISTINCT CAST("timestamp" AS DATE) AS date_str
                    FROM daily_metrics
                    WHERE ticker = ? AND CAST("timestamp" AS DATE) > CAST(? AS DATE)
                    ORDER BY "timestamp" ASC
                    LIMIT 2
                """
                rows = con.execute(query, [ticker, date]).fetchall()
                succeeding = [str(r[0]) for r in rows]
                dates = [date] + succeeding
            elif apply_day == "gap_1_day":
                query_pre = """
                    SELECT DISTINCT CAST("timestamp" AS DATE) AS date_str
                    FROM daily_metrics
                    WHERE ticker = ? AND CAST("timestamp" AS DATE) < CAST(? AS DATE)
                    ORDER BY "timestamp" DESC
                    LIMIT 1
                """
                row_pre = con.execute(query_pre, [ticker, date]).fetchone()
                gap_day = str(row_pre[0]) if row_pre else date
                
                query_suc = """
                    SELECT DISTINCT CAST("timestamp" AS DATE) AS date_str
                    FROM daily_metrics
                    WHERE ticker = ? AND CAST("timestamp" AS DATE) > CAST(? AS DATE)
                    ORDER BY "timestamp" ASC
                    LIMIT 1
                """
                row_suc = con.execute(query_suc, [ticker, date]).fetchone()
                gap_2_day = str(row_suc[0]) if row_suc else None
                
                dates = [gap_day, date]
                if gap_2_day:
                    dates.append(gap_2_day)
            else: # gap_2_day
                query_pre = """
                    SELECT DISTINCT CAST("timestamp" AS DATE) AS date_str
                    FROM daily_metrics
                    WHERE ticker = ? AND CAST("timestamp" AS DATE) < CAST(? AS DATE)
                    ORDER BY "timestamp" DESC
                    LIMIT 2
                """
                rows_pre = con.execute(query_pre, [ticker, date]).fetchall()
                preceding = [str(r[0]) for r in rows_pre]
                if len(preceding) == 2:
                    dates = [preceding[1], preceding[0], date]
                elif len(preceding) == 1:
                    dates = [preceding[0], date]
                else:
                    dates = [date]
            
            dates = dates[:count]
        except Exception as e:
            # Fallback
            from app.services.data_service import fetch_preceding_trading_dates
            dates = fetch_preceding_trading_dates(ticker, date, count)
            if not dates:
                dates = [date]

    result = {}
    day_labels = []
    if len(dates) == 1:
        day_labels = ["gap_day"]
    elif len(dates) == 2:
        day_labels = ["gap_day", "gap_1_day"]
    elif len(dates) == 3:
        day_labels = ["gap_day", "gap_1_day", "gap_2_day"]
    else:
        day_labels = [f"day_{i}" for i in range(len(dates))]

    for idx, d in enumerate(dates):
        label = day_labels[idx] if idx < len(day_labels) else f"day_{idx}"
        if dataset_id == "mock_dataset_1":
            candles = generate_mock_candles(ticker, d)
        else:
            candles = fetch_day_candles(dataset_id, ticker, d)
        result[label] = {
            "date": d,
            "candles": candles
        }
    return result




@router.post("/montecarlo")
def run_montecarlo_endpoint(req: MonteCarloRequest):
    if not req.pnls:
        raise HTTPException(status_code=400, detail="No trades provided")
    if req.simulations < 100 or req.simulations > 10000:
        raise HTTPException(
            status_code=400, detail="Simulations must be between 100 and 10000"
        )
    try:
        return run_montecarlo(req.pnls, req.init_cash, req.simulations)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error en Monte Carlo: {str(e)}"
        )


@router.post("/what-if")
def run_what_if_endpoint(req: WhatIfRequest):
    if not req.trades:
        raise HTTPException(status_code=400, detail="No trades provided for simulation")
    try:
        return run_what_if(req.trades, req.params, req.init_cash, req.risk_r)
    except Exception as e:
        logger.error(f"  what-if FAILED: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error en simulación What-if: {str(e)}")
