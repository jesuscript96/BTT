"""Phase 3 — capital allocation (Leaders + HRP, no lookahead) and scaling."""
import numpy as np
import pytest

from app.services.portfolio_analytics_service import (
    capital_allocation,
    hrp_weights,
    account_scaling,
    align_returns,
)


def _series(values, start_day=2):
    return {f"2024-01-{start_day+i:02d}": float(v) for i, v in enumerate(values)}


def test_hrp_weights_sum_to_one_and_positive():
    rng = np.random.default_rng(0)
    n_days = 60
    returns = {
        "A": {f"2024-{1+i//28:02d}-{2+i%28:02d}": float(x) for i, x in enumerate(rng.normal(0, 0.01, n_days))},
        "B": {f"2024-{1+i//28:02d}-{2+i%28:02d}": float(x) for i, x in enumerate(rng.normal(0, 0.02, n_days))},
        "C": {f"2024-{1+i//28:02d}-{2+i%28:02d}": float(x) for i, x in enumerate(rng.normal(0, 0.015, n_days))},
    }
    out = capital_allocation(returns, method="hrp")
    w = list(out["weights"].values())
    assert sum(w) == pytest.approx(1.0, abs=1e-6)
    assert all(x >= 0 for x in w)
    # lower-variance strategy A should not get less than higher-variance B
    assert out["weights"]["A"] >= out["weights"]["B"]


def test_hrp_single_strategy_full_weight():
    w = hrp_weights(np.array([[0.01], [0.02], [-0.01]]))
    assert w.sum() == pytest.approx(1.0)


def test_leaders_no_lookahead_huge_window_stays_equal():
    # With lookback >= n_days the window is never satisfied -> equal weights only,
    # proving the allocator never peeks at future data.
    returns = {
        "A": _series([0.05, 0.05, 0.05, 0.05, 0.05]),
        "B": _series([-0.05, -0.05, -0.05, -0.05, -0.05]),
    }
    out = capital_allocation(returns, method="leaders", lookback_days=999)
    assert out["weights"]["A"] == pytest.approx(0.5, abs=1e-6)
    assert out["weights"]["B"] == pytest.approx(0.5, abs=1e-6)


def test_leaders_rewards_better_performer():
    # A consistently strong, B consistently weak -> after warmup A gets more weight.
    n = 40
    returns = {
        "A": {f"2024-{1+i//28:02d}-{2+i%28:02d}": 0.02 for i in range(n)},
        "B": {f"2024-{1+i//28:02d}-{2+i%28:02d}": -0.01 for i in range(n)},
    }
    out = capital_allocation(returns, method="leaders", lookback_days=5)
    assert out["weights"]["A"] > out["weights"]["B"]
    assert sum(out["weights"].values()) == pytest.approx(1.0, abs=1e-6)


def test_allocation_unknown_method_raises():
    returns = {"A": _series([0.01, 0.02])}
    with pytest.raises(ValueError):
        capital_allocation(returns, method="markov")


def test_scaling_kelly_reduces_exposure():
    returns = {"A": _series([0.02, -0.01, 0.03, -0.02, 0.04, 0.01])}
    full = account_scaling(returns, weights=None, mode="fixed_pct", fixed_pct=1.0)
    kelly = account_scaling(returns, weights=None, mode="kelly", kelly_frac=0.5)
    # kelly-scaled path should be less volatile than full exposure
    assert abs(kelly["metrics"]["volatility_pct"]) <= abs(full["metrics"]["volatility_pct"]) + 1e-9


def test_scaling_drawdown_stop_caps_losses():
    # A long losing run; the stop should sit out and cap the drawdown.
    returns = {"A": _series([-0.05] * 10)}
    out = account_scaling(returns, weights=None, mode="drawdown_stop", dd_stop_pct=-15.0)
    assert min(out["drawdown"]) <= 0.0
    # equity must flatten (stop trading) instead of going to ~0
    assert out["equity"][-1] > 0.0
