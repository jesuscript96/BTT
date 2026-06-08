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
def get_multi_candles(dataset_id: str, ticker: str, date: str, apply_day: str = "gap_day"):
    count = 1
    if apply_day == "gap_1_day":
        count = 2
    elif apply_day == "gap_2_day":
        count = 3

    if dataset_id == "mock_dataset_1":
        from datetime import datetime, timedelta
        try:
            base_dt = datetime.strptime(date, "%Y-%m-%d")
        except Exception:
            base_dt = datetime.now()
        
        dates = []
        for i in range(count - 1, -1, -1):
            d_str = (base_dt - timedelta(days=i)).strftime("%Y-%m-%d")
            dates.append(d_str)
    else:
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
        # If it's mock, use generate_mock_candles
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
