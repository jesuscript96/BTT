"""Test fixtures for the public API. These tests NEVER touch the engine or real
data: the facade is replaced by a fake, and the store uses a temp SQLite file.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api_public.app import app
from app.api_public.core import store as store_mod
from app.api_public.core import ratelimit
from app.api_public.facade import Facade, get_facade


def make_raw(n_trades: int = 3, n_equity: int = 5, with_nan_day: bool = True) -> dict:
    """A realistic raw engine result (shape from run_backtest())."""
    equity = [{"time": 1_700_000_000 + i * 60, "value": 10_000 + i * 5.0} for i in range(n_equity)]
    drawdown = [{"time": 1_700_000_000 + i * 60, "value": -float(i)} for i in range(n_equity)]
    trades = []
    for i in range(n_trades):
        trades.append({
            "ticker": "AAPL", "date": "2024-01-02",
            "entry_time": "2024-01-02 09:31:00", "exit_time": "2024-01-02 09:45:00",
            "entry_price": 10.0 + i, "exit_price": 9.5 + i, "pnl": 40.0 - i,
            "fees": 0.5, "return_pct": -3.9, "direction": "short", "status": "closed",
            "size": 95, "exit_reason": "Take Profit", "mae": -0.4, "mfe": 0.6,
            "r_multiple": 1.7, "entry_hour": 9, "entry_weekday": 2, "gap_pct": 12.4,
            "stop_loss": 10.5,
        })
    day = {
        "ticker": "AAPL", "date": "2024-01-02", "total_return_pct": 1.2,
        "max_drawdown_pct": 0.8, "win_rate_pct": 66.6, "total_trades": n_trades,
        "profit_factor": 1.6, "sharpe_ratio": None if with_nan_day else 0.9,  # NaN sanitized -> None
        "sortino_ratio": 1.1, "expectancy": 5.0, "best_trade_pct": 3.1,
        "worst_trade_pct": -1.2, "init_value": 10000, "end_value": 10120, "gap_pct": 12.4,
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


class FakeFacade(Facade):
    def __init__(self, raw=None, ticker_days=10, tickers=3, run_error=None):
        self._raw = raw if raw is not None else make_raw()
        self._ticker_days = ticker_days
        self._tickers = tickers
        self._run_error = run_error

    def preview_universe(self, dataset_id, date_from=None, date_to=None, preconditions=None, apply_day="gap_day"):
        return {"ticker_days": self._ticker_days, "tickers": self._tickers}

    def run_backtest(self, request_kwargs):
        if self._run_error is not None:
            raise self._run_error
        return self._raw


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    ratelimit.reset_limiter()
    yield
    ratelimit.reset_limiter()


@pytest.fixture
def store(tmp_path):
    s = store_mod.Store(str(tmp_path / "test.sqlite"))
    store_mod.set_store(s)
    yield s
    s.close()
    store_mod.set_store(None)


@pytest.fixture
def api_token(store):
    token, _row = store.create_api_key(owner_id="user_1", plan="default")
    return token


@pytest.fixture
def fake_facade():
    return FakeFacade()


@pytest.fixture
def client(fake_facade):
    app.dependency_overrides[get_facade] = lambda: fake_facade
    c = TestClient(app, raise_server_exceptions=False)
    yield c
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers(api_token):
    return {"Authorization": f"Bearer {api_token}"}
