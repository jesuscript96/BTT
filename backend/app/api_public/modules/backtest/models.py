"""Pydantic models for the `backtest` module — the public data contract.

Strategy validation reuses the REAL engine schema (`app.schemas.strategy.StrategyCreate`),
so `/strategies/validate` is just Pydantic and the OpenAPI strategy schema is always
in sync with the engine. Output DTOs mirror the real `run_backtest()` shape
(docs/b2d-gateway/03).
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.strategy import StrategyCreate, PostGapPrecondition


IncludeSection = Literal["metrics", "equity", "days", "trades"]


class UniverseSpec(BaseModel):
    # MVP: reference an existing dataset (or "mock_dataset_1"). Filter-based universe
    # creation is v2 (requires the screener+precache pipeline).
    dataset_ref: Optional[str] = Field(
        default=None, description="ID de un dataset existente, o 'mock_dataset_1' (sandbox)."
    )
    filters: Optional[dict] = Field(
        default=None, description="[v2] Creación de universo por filtros. No soportado en el MVP."
    )
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    apply_day: Literal["gap_day", "gap_1_day", "gap_2_day"] = "gap_day"
    postgap_preconditions: Optional[list[PostGapPrecondition]] = None


class Execution(BaseModel):
    init_cash: float = 10000.0
    risk_r: float = 100.0
    risk_type: Literal["FIXED", "PERCENT", "FIXED_RATIO"] = "FIXED"
    fixed_ratio_delta: float = 500.0
    size_by_sl: bool = False
    fees: float = 0.0
    fee_type: Literal["PERCENT", "PER_SHARE"] = "PERCENT"
    slippage: float = 0.0
    locates_cost: float = 0.0
    monthly_expenses: float = 0.0
    market_sessions: list[str] = Field(default_factory=lambda: ["RTH"])
    custom_start_time: Optional[str] = None
    custom_end_time: Optional[str] = None
    look_ahead_prevention: bool = False


class BacktestCreate(BaseModel):
    universe: Optional[UniverseSpec] = None
    strategy: StrategyCreate
    execution: Execution = Field(default_factory=Execution)
    include: list[IncludeSection] = Field(default_factory=lambda: ["metrics", "equity", "days"])
    trades_limit: Optional[int] = Field(default=None, ge=1, le=5000)
    trades_cursor: Optional[str] = None


class StrategyValidation(BaseModel):
    valid: bool
    errors: list[dict] = Field(default_factory=list)


class UniversePreview(BaseModel):
    ticker_days: int
    tickers: int
    within_cap: bool
    cap: int


# ── Output DTOs (mirror run_backtest()) ──────────────────────────────────────
class EquityPoint(BaseModel):
    time: int
    value: float


class DayResult(BaseModel):
    # Numeric fields are Optional because the engine sanitizes NaN/inf to None.
    ticker: str
    date: str
    total_return_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    win_rate_pct: Optional[float] = None
    total_trades: Optional[int] = None
    profit_factor: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    expectancy: Optional[float] = None
    best_trade_pct: Optional[float] = None
    worst_trade_pct: Optional[float] = None
    init_value: Optional[float] = None
    end_value: Optional[float] = None
    gap_pct: Optional[float] = None

    model_config = {"extra": "allow"}


class Trade(BaseModel):
    ticker: str
    date: str
    entry_time: Optional[str] = None
    exit_time: Optional[str] = None
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    pnl: Optional[float] = None
    fees: Optional[float] = None
    return_pct: Optional[float] = None
    direction: Optional[str] = None
    status: Optional[str] = None
    size: Optional[float] = None
    exit_reason: Optional[str] = None
    mae: Optional[float] = None
    mfe: Optional[float] = None
    r_multiple: Optional[float] = None
    entry_hour: Optional[int] = None
    entry_weekday: Optional[int] = None
    gap_pct: Optional[float] = None
    stop_loss: Optional[float] = None

    model_config = {"extra": "allow"}


class TradesPage(BaseModel):
    items: list[Trade] = Field(default_factory=list)
    page: dict = Field(default_factory=dict)
    export_url: Optional[str] = None


class BacktestResult(BaseModel):
    aggregate_metrics: dict[str, Any] = Field(default_factory=dict)
    global_equity: Optional[list[EquityPoint]] = None
    global_drawdown: Optional[list[EquityPoint]] = None
    day_results: Optional[list[DayResult]] = None
    trades: Optional[TradesPage] = None


class JobProgress(BaseModel):
    percent: float = 0.0
    current: int = 0
    total: int = 0


class JobMeta(BaseModel):
    ticker_days: int = 0
    trades_total: int = 0
    engine_ms: int = 0
    downsampled: bool = False


class JobStatus(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    progress: Optional[JobProgress] = None
    meta: Optional[JobMeta] = None
    result: Optional[BacktestResult] = None


class IntradayEquity(BaseModel):
    ticker: str
    date: str
    equity: list[EquityPoint] = Field(default_factory=list)


class IndicatorCatalogEntry(BaseModel):
    name: str
    category: str
    params: list[str] = Field(default_factory=list)


class IndicatorCatalog(BaseModel):
    indicators: list[IndicatorCatalogEntry]
