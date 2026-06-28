"""Phase 2 — Monte Carlo, VaR/CVaR (95/99, % and USD), correlations."""
import numpy as np
import pytest

from app.services.portfolio_analytics_service import (
    portfolio_montecarlo,
    correlation_matrices,
    kelly_fraction,
    align_returns,
    portfolio_returns,
    normalize_weights,
    _var_cvar,
)


def _single(returns_list, start="2024-01-02"):
    dates = [f"2024-{1 + i // 28:02d}-{2 + i % 28:02d}" for i in range(len(returns_list))]
    return {"A": dict(zip(dates, returns_list))}


def test_var_cvar_signs_and_usd_consistency():
    rets = np.array([-0.05, -0.04, -0.03, -0.02, -0.01, 0.0, 0.01, 0.02, 0.03, 0.04])
    var_pct, var_usd, cvar_pct, cvar_usd = _var_cvar(rets, 0.95, 10000.0)
    assert var_pct < 0  # a loss
    assert cvar_pct <= var_pct  # tail loss is worse
    # USD must equal pct/100 * init_cash
    assert var_usd == pytest.approx(var_pct / 100.0 * 10000.0, abs=0.01)
    assert cvar_usd == pytest.approx(cvar_pct / 100.0 * 10000.0, abs=0.01)


def test_var_99_more_extreme_than_95():
    rets = np.linspace(-0.06, 0.06, 50)
    returns = {"A": {f"2024-{1+i//28:02d}-{2+i%28:02d}": float(r) for i, r in enumerate(rets)}}
    ids, dates, m = align_returns(returns)
    pr = portfolio_returns(m, normalize_weights(ids, None))
    v95, _, _, _ = _var_cvar(pr, 0.95, 10000.0)
    v99, _, _, _ = _var_cvar(pr, 0.99, 10000.0)
    assert v99 <= v95


def test_montecarlo_percentiles_ordered_and_deterministic():
    returns = {"A": {f"2024-{1+i//28:02d}-{2+i%28:02d}": float(r)
                     for i, r in enumerate(np.linspace(-0.03, 0.04, 40))}}
    out1 = portfolio_montecarlo(returns, simulations=500, init_cash=10000.0, seed=42)
    out2 = portfolio_montecarlo(returns, simulations=500, init_cash=10000.0, seed=42)
    assert out1 == out2  # reproducible with a seed
    final = {k: v[-1] for k, v in out1["percentiles"].items()}
    assert final["p5"] <= final["p50"] <= final["p95"]
    assert 0.0 <= out1["ruin_probability"] <= 100.0
    assert len(out1["percentiles"]["p50"]) == 41  # n_days + 1


def test_montecarlo_raises_on_no_overlap():
    with pytest.raises(ValueError):
        portfolio_montecarlo({}, simulations=100)


def test_correlation_identical_strategies_is_one():
    base = {f"2024-01-{2+i:02d}": float(r) for i, r in enumerate([0.01, -0.02, 0.03, -0.01, 0.02])}
    returns = {"A": dict(base), "B": dict(base)}
    out = correlation_matrices(returns)
    i, j = out["labels"].index("A"), out["labels"].index("B")
    assert out["pearson"][i][j] == pytest.approx(1.0, abs=1e-6)
    assert out["spearman"][i][j] == pytest.approx(1.0, abs=1e-6)


def test_correlation_opposite_strategies_is_negative_one():
    base = [0.01, -0.02, 0.03, -0.01, 0.02]
    dates = [f"2024-01-{2+i:02d}" for i in range(len(base))]
    returns = {
        "A": dict(zip(dates, base)),
        "B": dict(zip(dates, [-x for x in base])),
    }
    out = correlation_matrices(returns)
    i, j = out["labels"].index("A"), out["labels"].index("B")
    assert out["pearson"][i][j] == pytest.approx(-1.0, abs=1e-6)


def test_kelly_fraction_bounds():
    # win-heavy series -> positive fraction in [0,1]
    rets = np.array([0.02, 0.02, 0.02, -0.01])
    f = kelly_fraction(rets)
    assert 0.0 <= f <= 1.0
    assert f > 0.0
    # all losses -> 0
    assert kelly_fraction(np.array([-0.01, -0.02])) == 0.0
