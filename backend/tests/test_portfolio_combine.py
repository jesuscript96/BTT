"""Phase 1 — combine curves, calendar alignment, 0% fill, metrics."""
import numpy as np
import pytest

from app.services.portfolio_analytics_service import (
    daily_returns_from_results_json,
    align_returns,
    combine_returns,
    normalize_weights,
)


def test_daily_returns_from_global_equity():
    rj = {
        "global_equity": [
            {"time": 1704067200, "value": 10000.0},  # 2023-12-31 (point 0)
            {"time": 1704153600, "value": 10100.0},  # +1%
            {"time": 1704240000, "value": 10201.0},  # +1%
        ]
    }
    series = daily_returns_from_results_json(rj)
    vals = list(series.values())
    assert len(series) == 2
    assert vals[0] == pytest.approx(0.01, abs=1e-6)
    assert vals[1] == pytest.approx(0.01, abs=1e-6)


def test_daily_returns_fallback_from_trades():
    rj = {"trades": [
        {"date": "2024-01-02", "pnl": 100.0},
        {"date": "2024-01-02", "pnl": 50.0},
        {"date": "2024-01-03", "pnl": -30.0},
    ]}
    series = daily_returns_from_results_json(rj, capital_base=10000.0)
    assert series["2024-01-02"] == pytest.approx(0.015)
    assert series["2024-01-03"] == pytest.approx(-0.003)


def test_unusable_results_json_returns_empty():
    assert daily_returns_from_results_json({}) == {}
    assert daily_returns_from_results_json({"global_equity": [{"time": 1, "value": 1}]}) == {}


def test_alignment_fills_missing_days_with_zero():
    returns = {
        "A": {"2024-01-02": 0.01, "2024-01-03": 0.02},
        "B": {"2024-01-03": -0.01, "2024-01-04": 0.03},
    }
    ids, dates, matrix = align_returns(returns)
    assert dates == ["2024-01-02", "2024-01-03", "2024-01-04"]
    a, b = ids.index("A"), ids.index("B")
    # A has no trade on 01-04 -> 0.0 ; B has none on 01-02 -> 0.0
    assert matrix[2, a] == 0.0
    assert matrix[0, b] == 0.0
    assert matrix[1, a] == pytest.approx(0.02)
    assert matrix[1, b] == pytest.approx(-0.01)


def test_combine_equal_weights_compounding():
    returns = {
        "A": {"2024-01-02": 0.01, "2024-01-03": 0.02},
        "B": {"2024-01-03": -0.01, "2024-01-04": 0.03},
    }
    out = combine_returns(returns, init_cash=10000.0)
    # port returns: [0.005, 0.005, 0.015]
    eq = out["combined_equity"]
    assert len(eq) == 4  # 3 days + base point
    assert eq[0] == 10000.0
    assert eq[1] == pytest.approx(10050.0, abs=0.01)
    assert eq[2] == pytest.approx(10100.25, abs=0.01)
    assert eq[3] == pytest.approx(10251.75, abs=0.05)
    assert out["metrics"]["n_days"] == 3
    assert out["metrics"]["max_drawdown_pct"] <= 0.0


def test_custom_weights_are_normalised():
    ids = ["A", "B", "C"]
    w = normalize_weights(ids, {"A": 2.0, "B": 1.0, "C": 1.0})
    assert w.sum() == pytest.approx(1.0)
    assert w[0] == pytest.approx(0.5)


def test_combine_drawdown_is_negative_on_losses():
    returns = {"A": {"2024-01-02": 0.10, "2024-01-03": -0.20, "2024-01-04": 0.05}}
    out = combine_returns(returns, init_cash=10000.0)
    assert min(out["combined_drawdown"]) < 0.0
    assert out["metrics"]["max_drawdown_pct"] < 0.0
