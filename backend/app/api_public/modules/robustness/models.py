"""Pydantic DTOs for the public `robustness` module (docs/robustez/PRD §3).

The identifier is `run_id` (= a saved Baúl backtest_results id). Output DTOs
mirror the robustness_service result shape so the OpenAPI contract stays honest.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class CurvePoint(BaseModel):
    time: int
    value: float


# ── Module 1 — Monte Carlo ───────────────────────────────────
class MontecarloBody(BaseModel):
    run_id: str = Field(..., description="ID del run guardado en el Baúl.")
    init_cash: float = 10000.0
    simulations: int = Field(1000, ge=1, le=10000)
    ruin_pct: float = 10.0
    n_trades_limit: int = Field(500, ge=1)
    period_unit: Optional[str] = Field(None, description='"mes" | "trimestre" | "año" | null')


class MontecarloResult(BaseModel):
    simulations_run: int
    ruin_probability: float
    worst_drawdown: float
    median_drawdown: float
    extreme_drawdown_p95: float
    extreme_drawdown_p99: float
    probability_negative_return: float
    n_trades_calculated: int
    percentiles: dict[str, list[CurvePoint]]


# ── Module 3 — Sensitivity ───────────────────────────────────
class LocateRange(BaseModel):
    min: float = 0.5
    max: float = 3.0
    step: float = 0.5


class SensitivityBody(BaseModel):
    run_id: str
    locate_range: LocateRange = Field(default_factory=LocateRange)
    slippage_probability: float = 0.0
    slippage_value: float = 0.0
    init_cash: float = 10000.0


class SensitivityResult(BaseModel):
    critical_locate_threshold: Optional[float]
    curves: dict[str, list[CurvePoint]]


# ── Module 4 — Black Swan ────────────────────────────────────
class BlackSwanBody(BaseModel):
    run_id: str
    init_cash: float = 10000.0
    black_swan_count: int = Field(3, ge=0)
    severity_multiplier: float = 10.0
    ruin_pct: float = 10.0


class BlackSwanCell(BaseModel):
    position_size_pct: float
    severity_multiplier: float
    ruin_probability: float
    max_drawdown: float
    zone: str


class BlackSwanResult(BaseModel):
    time_to_recovery_trades: int
    post_swan_ruin_risk_100t: float
    sensitivity_matrix: list[BlackSwanCell]
