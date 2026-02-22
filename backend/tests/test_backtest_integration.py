"""
Integration tests for backtester: commission per share, locates, lookahead, risk_per_trade_usd, market_interval.
Uses current Strategy schema (EntryLogic, ConditionGroup, ComparisonCondition).
"""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from app.backtester.engine import BacktestEngine
from app.routers.backtest import filter_market_data_by_interval_and_dates
from app.schemas.strategy import (
    Strategy,
    EntryLogic,
    ExitLogic,
    ConditionGroup,
    ComparisonCondition,
    IndicatorConfig,
    IndicatorType,
    Comparator,
    RiskManagement,
)


def _make_ohlcv(ticker: str, n_bars: int, start: datetime, interval_min: int = 1):
    """Generate minimal OHLCV with timestamps."""
    ts = [start + timedelta(minutes=i * interval_min) for i in range(n_bars)]
    base = 100.0
    np.random.seed(42)
    close = base + np.cumsum(np.random.randn(n_bars) * 0.5)
    high = close + np.abs(np.random.randn(n_bars))
    low = close - np.abs(np.random.randn(n_bars))
    open_ = np.roll(close, 1)
    open_[0] = base
    vol = np.random.randint(1000, 10000, n_bars)
    return pd.DataFrame({
        "ticker": ticker,
        "timestamp": ts,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": vol,
    })


def _strategy_with_close_above_sma():
    """Strategy: Close > SMA(5) as entry; empty exit (only SL/TP)."""
    entry = EntryLogic(
        timeframe="1m",
        root_condition=ConditionGroup(
            type="group",
            operator="AND",
            conditions=[
                ComparisonCondition(
                    type="indicator_comparison",
                    source=IndicatorConfig(name=IndicatorType.CLOSE),
                    comparator=Comparator.GT,
                    target=IndicatorConfig(name=IndicatorType.SMA, period=5),
                )
            ],
        ),
    )
    exit_logic = ExitLogic(
        timeframe="1m",
        root_condition=ConditionGroup(
            type="group",
            operator="AND",
            conditions=[
                ComparisonCondition(
                    type="indicator_comparison",
                    source=IndicatorConfig(name=IndicatorType.CLOSE),
                    comparator=Comparator.LT,
                    target=0.0,
                )
            ],
        ),
    )
    return Strategy(
        id="int-test-1",
        name="Close > SMA5",
        bias="long",
        entry_logic=entry,
        exit_logic=exit_logic,
        risk_management=RiskManagement(
            use_hard_stop=True,
            use_take_profit=True,
            hard_stop={"type": "Percentage", "value": 2.0},
            take_profit={"type": "Percentage", "value": 4.0},
        ),
    )


class TestBacktestParams:
    """Test commission per share, locates, risk_per_trade_usd, lookahead."""

    def test_engine_accepts_commission_per_share_and_locates(self):
        df = _make_ohlcv("T1", 50, datetime(2024, 6, 1, 9, 30))
        strategy = _strategy_with_close_above_sma()
        engine = BacktestEngine(
            strategies=[strategy],
            weights={strategy.id: 100.0},
            market_data=df,
            commission_per_trade=0,
            commission_per_share=0.01,
            locate_cost_per_100=1.0,
            slippage_pct=0,
            lookahead_prevention=False,
            risk_per_trade_usd=500.0,
            initial_capital=10000,
            max_holding_minutes=60,
        )
        result = engine.run()
        assert result.initial_capital == 10000
        assert result.total_trades >= 0
        if result.total_trades > 0:
            assert all("side" in t for t in result.trades)

    def test_engine_with_lookahead_prevention(self):
        df = _make_ohlcv("T1", 30, datetime(2024, 6, 1, 9, 30))
        strategy = _strategy_with_close_above_sma()
        engine = BacktestEngine(
            strategies=[strategy],
            weights={strategy.id: 100.0},
            market_data=df,
            commission_per_trade=1.0,
            lookahead_prevention=True,
            initial_capital=10000,
            max_holding_minutes=60,
        )
        result = engine.run()
        assert result.initial_capital == 10000

    def test_engine_with_risk_per_trade_usd(self):
        df = _make_ohlcv("T1", 40, datetime(2024, 6, 1, 10, 0))
        strategy = _strategy_with_close_above_sma()
        engine = BacktestEngine(
            strategies=[strategy],
            weights={strategy.id: 100.0},
            market_data=df,
            commission_per_trade=0.5,
            risk_per_trade_usd=200.0,
            initial_capital=5000,
            max_holding_minutes=30,
        )
        result = engine.run()
        assert result.initial_capital == 5000


class TestMarketIntervalFilter:
    """Test date/interval filter used before engine."""

    def test_filter_market_data_by_interval_rth_only(self):
        # Bars at 08:00 (PM), 10:00 (RTH), 17:00 (AM)
        df = pd.DataFrame({
            "ticker": ["A", "A", "A"],
            "timestamp": pd.to_datetime([
                "2024-06-01 08:00:00",
                "2024-06-01 10:00:00",
                "2024-06-01 17:00:00",
            ]),
            "open": [100, 101, 102],
            "high": [101, 102, 103],
            "low": [99, 100, 101],
            "close": [100.5, 101.5, 102.5],
            "volume": [1000, 1000, 1000],
        })
        filtered = filter_market_data_by_interval_and_dates(
            df, market_interval=["RTH"], date_from=None, date_to=None
        )
        assert len(filtered) == 1
        assert filtered["timestamp"].iloc[0].hour == 10

    def test_filter_market_data_multiple_intervals(self):
        df = pd.DataFrame({
            "ticker": ["A"] * 4,
            "timestamp": pd.to_datetime([
                "2024-06-01 08:00:00",
                "2024-06-01 10:00:00",
                "2024-06-01 17:00:00",
                "2024-06-01 19:00:00",
            ]),
            "open": [100] * 4,
            "high": [101] * 4,
            "low": [99] * 4,
            "close": [100] * 4,
            "volume": [1000] * 4,
        })
        filtered = filter_market_data_by_interval_and_dates(
            df, market_interval=["PM", "RTH"], date_from=None, date_to=None
        )
        assert len(filtered) == 2  # 08:00 PM, 10:00 RTH

    def test_filter_market_data_by_date(self):
        df = pd.DataFrame({
            "ticker": ["A"] * 3,
            "timestamp": pd.to_datetime(["2024-05-30 10:00", "2024-06-01 10:00", "2024-06-03 10:00"]),
            "open": [100] * 3,
            "high": [101] * 3,
            "low": [99] * 3,
            "close": [100] * 3,
            "volume": [1000] * 3,
        })
        filtered = filter_market_data_by_interval_and_dates(
            df, market_interval=None, date_from="2024-06-01", date_to="2024-06-02"
        )
        assert len(filtered) == 1
        assert pd.Timestamp(filtered["timestamp"].iloc[0]).date().isoformat() == "2024-06-01"
