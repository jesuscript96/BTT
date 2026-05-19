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
    return run_backtest_orchestrator(req)


@router.get("/candles")
def get_candles(dataset_id: str, ticker: str, date: str):
    if dataset_id == "mock_dataset_1":
        return generate_mock_candles(ticker, date)

    candles = fetch_day_candles(dataset_id, ticker, date)
    if not candles:
        raise HTTPException(status_code=404, detail="No candle data found")
    return {"ticker": ticker, "date": date, "candles": candles}


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
