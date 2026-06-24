"""Deterministic sandbox facade — NO engine, NO external data.

Opt-in via `EDGECUTE_DEMO_FACADE=1` (wired in app.create_app). It mirrors the
shape of a real `run_backtest()` result so the full HTTP surface can be exercised
by automated test suites (the Bruno collection in `backend/bruno/`) and local
demos without MotherDuck/GCS or numba. It is NEVER enabled in production.

The canned numbers match what the pytest suite asserts (3 trades, 10 ticker-days,
a 10-point intraday series for AAPL/2024-01-02) so both suites agree.
"""
from __future__ import annotations

from app.api_public.facade import Facade, set_facade

# Sentinel dataset that resolves to an oversized universe so the cap path
# (`universe_too_large` / `within_cap=false`) can be exercised over HTTP.
HUGE_DATASET_REF = "huge_dataset"


def _demo_raw() -> dict:
    """A realistic raw engine result (same shape as run_backtest())."""
    n_trades = 3
    equity = [{"time": 1_700_000_000 + i * 60, "value": 10_000 + i * 5.0} for i in range(5)]
    drawdown = [{"time": 1_700_000_000 + i * 60, "value": -float(i)} for i in range(5)]
    trades = [
        {
            "ticker": "AAPL", "date": "2024-01-02",
            "entry_time": "2024-01-02 09:31:00", "exit_time": "2024-01-02 09:45:00",
            "entry_price": 10.0 + i, "exit_price": 9.5 + i, "pnl": 40.0 - i,
            "fees": 0.5, "return_pct": -3.9, "direction": "short", "status": "closed",
            "size": 95, "exit_reason": "Take Profit", "mae": -0.4, "mfe": 0.6,
            "r_multiple": 1.7, "entry_hour": 9, "entry_weekday": 2, "gap_pct": 12.4,
            "stop_loss": 10.5,
        }
        for i in range(n_trades)
    ]
    day = {
        "ticker": "AAPL", "date": "2024-01-02", "total_return_pct": 1.2,
        "max_drawdown_pct": 0.8, "win_rate_pct": 66.6, "total_trades": n_trades,
        "profit_factor": 1.6, "sharpe_ratio": 0.9, "sortino_ratio": 1.1,
        "expectancy": 5.0, "best_trade_pct": 3.1, "worst_trade_pct": -1.2,
        "init_value": 10000, "end_value": 10120, "gap_pct": 12.4,
    }
    return {
        "aggregate_metrics": {
            "total_trades": n_trades, "win_rate_pct": 66.6, "total_pnl": 120.0,
            "total_pnl_net": 110.0, "total_return_pct": 1.2, "avg_sharpe": 1.83,
            "sortino_ratio": 2.41, "max_drawdown_pct": 8.7, "expectancy": 7.0,
        },
        "global_equity": equity,
        "global_drawdown": drawdown,
        "day_results": [day],
        "trades": trades,
        "equity_curves": [
            {"ticker": "AAPL", "date": "2024-01-02",
             "equity": [{"time": 1_700_000_000 + i * 60, "value": 10_000 + i} for i in range(10)]}
        ],
    }


class DemoFacade(Facade):
    """Returns canned, deterministic data. No engine, no I/O."""

    def preview_universe(self, dataset_id, date_from=None, date_to=None,
                         preconditions=None, apply_day="gap_day"):
        if dataset_id == HUGE_DATASET_REF:
            # Big enough to blow past any sane plan cap.
            return {"ticker_days": 10_000_000, "tickers": 100_000}
        return {"ticker_days": 10, "tickers": 3}

    def run_backtest(self, request_kwargs):
        return _demo_raw()


def install_demo_facade() -> None:
    set_facade(DemoFacade())
