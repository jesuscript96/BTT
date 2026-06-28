"""Portfolio module — combine saved backtests into a portfolio and analyse risk.

Thin router: validates input, loads the caller's saved backtests from the Baul
(scoped by user_id), delegates ALL maths to portfolio_analytics_service, and
serialises. See docs/portfolio/.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user_id
from app.schemas.portfolio import (
    AccountScalingRequest, AccountScalingResponse,
    CapitalAllocationRequest, CapitalAllocationResponse,
    CorrelationMatrixRequest, CorrelationMatrixResponse,
    MontecarloSimulationRequest, MontecarloSimulationResponse,
    PortfolioCombineRequest, PortfolioCombineResponse,
)
from app.services import portfolio_analytics_service as svc
from app.services.portfolio_loader import load_returns

router = APIRouter(prefix="/api/portfolio", tags=["Portfolio"])


def _load_returns(
    backtest_ids: List[str], user_id: Optional[str], capital_base: float = svc.DEFAULT_INIT_CASH
) -> Tuple[Dict[str, Dict[str, float]], Dict[str, str]]:
    """Load the caller's backtests as daily returns; raise 422 listing any id
    that is missing or has no usable daily curve."""
    returns_by_id, labels, bad = load_returns(backtest_ids, user_id, capital_base)
    if bad:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_backtest", "ids": bad,
                    "message": "Estos backtests no se pueden combinar; re-ejecútalos en el Baúl."},
        )
    return returns_by_id, labels


def _guard(min_count: int, returns_by_id: Dict, code: str, msg: str) -> None:
    if len(returns_by_id) < min_count:
        raise HTTPException(status_code=422, detail={"code": code, "message": msg})


@router.post("/combine", response_model=PortfolioCombineResponse)
def combine(req: PortfolioCombineRequest, user_id: Optional[str] = Depends(get_current_user_id)):
    returns, _ = _load_returns(req.backtest_ids, user_id, req.init_cash)
    try:
        return svc.combine_returns(returns, req.weights, req.init_cash)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)})


@router.post("/montecarlo", response_model=MontecarloSimulationResponse)
def montecarlo(req: MontecarloSimulationRequest, user_id: Optional[str] = Depends(get_current_user_id)):
    returns, _ = _load_returns(req.backtest_ids, user_id, req.init_cash)
    try:
        return svc.portfolio_montecarlo(returns, req.weights, req.simulations, req.init_cash)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)})


@router.post("/correlation", response_model=CorrelationMatrixResponse)
def correlation(req: CorrelationMatrixRequest, user_id: Optional[str] = Depends(get_current_user_id)):
    returns, labels = _load_returns(req.backtest_ids, user_id)
    _guard(2, returns, "insufficient_strategies", "Necesitas al menos 2 estrategias.")
    return svc.correlation_matrices(returns, labels)


@router.post("/allocation", response_model=CapitalAllocationResponse)
def allocation(req: CapitalAllocationRequest, user_id: Optional[str] = Depends(get_current_user_id)):
    returns, _ = _load_returns(req.backtest_ids, user_id, req.init_cash)
    if req.method == "hrp":
        _guard(2, returns, "insufficient_strategies", "HRP necesita al menos 2 estrategias.")
    try:
        return svc.capital_allocation(
            returns, req.method, req.lookback_days, req.leaders_weights, req.init_cash
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)})


@router.post("/scaling", response_model=AccountScalingResponse)
def scaling(req: AccountScalingRequest, user_id: Optional[str] = Depends(get_current_user_id)):
    returns, _ = _load_returns(req.backtest_ids, user_id, req.init_cash)
    try:
        return svc.account_scaling(
            returns, req.weights, req.init_cash, req.mode,
            req.kelly_fraction, req.fixed_pct, req.dd_stop_pct,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)})
