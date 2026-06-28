"""Public request/response models for the `portfolio` module.

Kept separate from the internal `app.schemas.portfolio` so the public surface is
controlled independently of internal changes.
"""
from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class CombineRequest(BaseModel):
    backtest_ids: List[str] = Field(..., min_length=1, description="IDs de backtests guardados a combinar.")
    weights: Optional[Dict[str, float]] = Field(None, description="backtest_id -> peso (suma 1.0). None = equiponderado.")
    init_cash: float = Field(10000.0, ge=100.0)


class CombineResponse(BaseModel):
    timestamps: List[int]
    combined_equity: List[float]
    combined_drawdown: List[float]
    metrics: Dict[str, float]
    weights: Dict[str, float]


class MontecarloRequest(BaseModel):
    backtest_ids: List[str] = Field(..., min_length=1)
    weights: Optional[Dict[str, float]] = None
    simulations: int = Field(1000, ge=100, le=10000)
    init_cash: float = Field(10000.0, ge=100.0)


class MontecarloResponse(BaseModel):
    percentiles: Dict[str, List[float]]
    var_95_pct: float
    var_95_usd: float
    var_99_pct: float
    var_99_usd: float
    cvar_95_pct: float
    cvar_95_usd: float
    cvar_99_pct: float
    cvar_99_usd: float
    ruin_probability: float


class CorrelationRequest(BaseModel):
    backtest_ids: List[str] = Field(..., min_length=2)


class CorrelationResponse(BaseModel):
    labels: List[str]
    pearson: List[List[float]]
    spearman: List[List[float]]


class AllocationRequest(BaseModel):
    backtest_ids: List[str] = Field(..., min_length=1)
    method: Literal["leaders", "hrp"]
    lookback_days: int = Field(15, ge=2)
    leaders_weights: Optional[List[float]] = None
    init_cash: float = Field(10000.0, ge=100.0)


class AllocationResponse(BaseModel):
    weights: Dict[str, float]
    comparison_equity: List[float]
    comparison_drawdown: List[float]
    metrics: Dict[str, float]
