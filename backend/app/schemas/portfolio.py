"""Pydantic models for the Portfolio module. See docs/portfolio/03_CONTRATO_DATOS.md."""
from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class PortfolioCombineRequest(BaseModel):
    backtest_ids: List[str] = Field(..., min_length=1)
    weights: Optional[Dict[str, float]] = Field(
        None, description="backtest_id -> peso (suma 1.0). None = equiponderado."
    )
    init_cash: float = Field(10000.0, ge=100.0)


class PortfolioCombineResponse(BaseModel):
    timestamps: List[int]
    combined_equity: List[float]
    combined_drawdown: List[float]
    metrics: Dict[str, float]
    weights: Dict[str, float]


class MontecarloSimulationRequest(BaseModel):
    backtest_ids: List[str] = Field(..., min_length=1)
    weights: Optional[Dict[str, float]] = None
    simulations: int = Field(1000, ge=100, le=10000)
    init_cash: float = Field(10000.0, ge=100.0)


class MontecarloSimulationResponse(BaseModel):
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


class CorrelationMatrixRequest(BaseModel):
    backtest_ids: List[str] = Field(..., min_length=2)


class CorrelationMatrixResponse(BaseModel):
    labels: List[str]
    pearson: List[List[float]]
    spearman: List[List[float]]


class CapitalAllocationRequest(BaseModel):
    backtest_ids: List[str] = Field(..., min_length=1)
    method: Literal["leaders", "hrp"]
    lookback_days: int = Field(15, ge=2, description="Ventana para Líderes (default 15).")
    leaders_weights: Optional[List[float]] = Field(None, description="Pesos por ranking (mejor→peor).")
    init_cash: float = Field(10000.0, ge=100.0)


class CapitalAllocationResponse(BaseModel):
    weights: Dict[str, float]
    comparison_equity: List[float]
    comparison_drawdown: List[float]
    metrics: Dict[str, float]


class AccountScalingRequest(BaseModel):
    backtest_ids: List[str] = Field(..., min_length=1)
    weights: Optional[Dict[str, float]] = None
    init_cash: float = Field(10000.0, ge=100.0)
    mode: Literal["kelly", "fixed_pct", "drawdown_stop"]
    kelly_fraction: float = Field(0.5, ge=0.0, le=1.0)
    fixed_pct: Optional[float] = Field(None, ge=0.0, le=1.0)
    dd_stop_pct: float = Field(-20.0, le=0.0)


class AccountScalingResponse(BaseModel):
    equity: List[float]
    drawdown: List[float]
    metrics: Dict[str, float]
