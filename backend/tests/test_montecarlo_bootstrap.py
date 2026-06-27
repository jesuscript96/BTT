"""Tests for Module 1 — Monte Carlo bootstrap (EPIC A1). Deterministic rng."""
import numpy as np
import pytest

from app.services.robustness_service import (
    RobustnessError,
    run_montecarlo_bootstrap,
    _compute_k,
)


def _rng():
    return np.random.default_rng(42)


def _trades(pnls, dates=None):
    out = []
    for i, p in enumerate(pnls):
        t = {"pnl": p, "size": 100, "entry_price": 10.0, "direction": "short", "return_pct": p / 1000.0}
        if dates:
            t["date"] = dates[i]
        out.append(t)
    return out


def test_response_shape_and_percentiles():
    trades = _trades([100, -50, 80, -30, 60] * 10)
    res = run_montecarlo_bootstrap(trades, init_cash=10000, simulations=200, n_trades_limit=40, rng=_rng())
    assert res["simulations_run"] == 200
    assert res["n_trades_calculated"] == 40
    for key in ("p5", "p25", "p50", "p75", "p95"):
        assert key in res["percentiles"]
        assert len(res["percentiles"][key]) == 41  # k + 1
    assert set(("ruin_probability", "worst_drawdown", "extreme_drawdown_p95",
                "extreme_drawdown_p99", "probability_negative_return")) <= res.keys()


def test_forced_ruin_all_losses():
    trades = _trades([-100] * 20)
    res = run_montecarlo_bootstrap(trades, init_cash=1000, simulations=100, ruin_pct=10.0,
                                   n_trades_limit=50, rng=_rng())
    # Every curve marches straight down past the 10% ruin threshold (=100).
    assert res["ruin_probability"] == 100.0
    assert res["probability_negative_return"] == 100.0
    assert res["worst_drawdown"] < 0


def test_healthy_strategy_no_ruin():
    trades = _trades([100] * 20)
    res = run_montecarlo_bootstrap(trades, init_cash=10000, simulations=100, ruin_pct=10.0,
                                   n_trades_limit=30, rng=_rng())
    assert res["ruin_probability"] == 0.0
    assert res["probability_negative_return"] == 0.0


def test_empty_trades_raises():
    with pytest.raises(RobustnessError) as exc:
        run_montecarlo_bootstrap([], rng=_rng())
    assert exc.value.code == "INVALID_STRATEGY"


def test_simulations_out_of_bounds():
    with pytest.raises(RobustnessError) as exc:
        run_montecarlo_bootstrap(_trades([10, -5]), simulations=99999, rng=_rng())
    assert exc.value.code == "PARAMETER_OUT_OF_BOUNDS"


def test_compute_k_period_fallback_quarter_is_65():
    # No parseable dates ⇒ 260 trades/year baseline ⇒ quarter = 65 (PRD §07).
    trades = _trades([10, -5, 8])
    assert _compute_k(trades, n_trades_limit=500, period_unit="trimestre") == 65
    assert _compute_k(trades, n_trades_limit=500, period_unit="año") == 260
    assert _compute_k(trades, n_trades_limit=123, period_unit=None) == 123


def test_compute_k_uses_date_span():
    # 100 trades spanning ~1 year ⇒ ~100/yr ⇒ quarter ≈ 25.
    dates = [f"2024-{(i % 12) + 1:02d}-15" for i in range(100)]
    trades = _trades([10] * 100, dates=dates)
    k = _compute_k(trades, n_trades_limit=500, period_unit="trimestre")
    assert 20 <= k <= 30
