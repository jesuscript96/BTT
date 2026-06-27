"""
Tests for the robustness data loader (EPIC A0).

Uses an isolated in-memory DuckDB (no real data, no MotherDuck) by injecting the
connection into the loader. Covers the PRD §2.6 edge cases for data loading.
"""
import json

import duckdb
import pytest

from app.services.robustness_service import (
    RobustnessError,
    _load_trades,
    _load_strategy_def,
    _net_profit,
    _extract_pnls,
)


def _make_db():
    """Fresh in-memory DB mirroring the real schema (subset used by the loader)."""
    con = duckdb.connect(":memory:")
    con.execute(
        """
        CREATE TABLE backtest_results (
            id VARCHAR PRIMARY KEY,
            strategy_ids JSON,
            results_json JSON
        )
        """
    )
    con.execute(
        """
        CREATE TABLE strategies (
            id VARCHAR PRIMARY KEY,
            definition JSON
        )
        """
    )
    return con


def _insert_run(con, run_id, trades, strategy_ids=None):
    results_json = {"trades": trades, "aggregate_metrics": {"total_trades": len(trades)}}
    con.execute(
        "INSERT INTO backtest_results (id, strategy_ids, results_json) VALUES (?, ?, ?)",
        (run_id, json.dumps(strategy_ids or []), json.dumps(results_json)),
    )


SAMPLE_TRADES = [
    {"ticker": "AMD", "pnl": 120.0, "size": 100, "entry_price": 10.0, "direction": "short", "return_pct": 1.2},
    {"ticker": "AMD", "pnl": -40.0, "size": 100, "entry_price": 12.0, "direction": "short", "return_pct": -0.4},
    {"ticker": "TSLA", "pnl": 80.0, "size": 50, "entry_price": 20.0, "direction": "long", "return_pct": 0.8},
]


def test_load_trades_valid_run():
    con = _make_db()
    _insert_run(con, "run_ok", SAMPLE_TRADES)
    trades, results_json = _load_trades("run_ok", con=con)
    assert len(trades) == 3
    assert trades[0]["ticker"] == "AMD"
    assert "aggregate_metrics" in results_json


def test_load_trades_missing_run_raises_invalid():
    con = _make_db()
    with pytest.raises(RobustnessError) as exc:
        _load_trades("does_not_exist", con=con)
    assert exc.value.code == "INVALID_STRATEGY"


def test_load_trades_empty_trades_raises():
    con = _make_db()
    _insert_run(con, "run_empty", [])
    with pytest.raises(RobustnessError) as exc:
        _load_trades("run_empty", con=con)
    assert exc.value.code == "INVALID_STRATEGY"
    assert "No trades available" in exc.value.message


def test_load_strategy_def_resolves_definition():
    con = _make_db()
    con.execute(
        "INSERT INTO strategies (id, definition) VALUES (?, ?)",
        ("strat_1", json.dumps({"indicators": [{"params": {"period": 20}}]})),
    )
    _insert_run(con, "run_with_strat", SAMPLE_TRADES, strategy_ids=["strat_1"])
    definition = _load_strategy_def("run_with_strat", con=con)
    assert definition["indicators"][0]["params"]["period"] == 20


def test_load_strategy_def_missing_strategy_raises():
    con = _make_db()
    _insert_run(con, "run_no_strat", SAMPLE_TRADES, strategy_ids=["ghost"])
    with pytest.raises(RobustnessError) as exc:
        _load_strategy_def("run_no_strat", con=con)
    assert exc.value.code == "INVALID_STRATEGY"


def test_helpers_net_profit_and_pnls():
    assert _net_profit(SAMPLE_TRADES) == pytest.approx(160.0)
    assert _extract_pnls(SAMPLE_TRADES) == [120.0, -40.0, 80.0]
