"""Tests for Module 4 — Black Swan + post-swan metrics (EPIC A4). Deterministic rng."""
import numpy as np
import pytest

from app.services.robustness_service import (
    RobustnessError,
    run_black_swan,
    _zone,
    _post_swan_ruin_risk,
)


def _rng():
    return np.random.default_rng(11)


def _trades(pnls):
    return [
        {"pnl": p, "size": 100, "entry_price": 10.0, "direction": "short", "return_pct": p / 1000.0}
        for p in pnls
    ]


def test_zone_thresholds():
    assert _zone(2.0, 15.0) == "GREEN"
    assert _zone(10.0, 30.0) == "YELLOW"
    assert _zone(25.0, 50.0) == "RED"
    assert _zone(4.0, 45.0) == "RED"   # drawdown > 40 dominates
    assert _zone(30.0, 10.0) == "RED"  # ruin > 20 dominates


def test_post_swan_balance_below_ruin_is_100():
    # start_capital = 1000 - 950 = 50 ≤ ruin threshold (100) ⇒ 100%
    risk = _post_swan_ruin_risk(np.array([10.0, -5.0]), init_cash=1000,
                                total_swan_loss=950, ruin_threshold=100, rng=_rng())
    assert risk == 100.0


def test_black_swan_full_shape():
    trades = _trades([100, -60, 80, -40, 50, -30] * 8)
    res = run_black_swan(trades, init_cash=10000, black_swan_count=3,
                         severity_multiplier=10.0, ruin_pct=10.0, rng=_rng())
    assert isinstance(res["time_to_recovery_trades"], int)
    assert 0.0 <= res["post_swan_ruin_risk_100t"] <= 100.0
    assert len(res["sensitivity_matrix"]) == 6  # 3 position sizes × 2 severities
    for cell in res["sensitivity_matrix"]:
        assert cell["zone"] in ("GREEN", "YELLOW", "RED")
        assert set(("position_size_pct", "severity_multiplier",
                    "ruin_probability", "max_drawdown")) <= cell.keys()


def test_empty_trades_raises():
    with pytest.raises(RobustnessError) as exc:
        run_black_swan([], rng=_rng())
    assert exc.value.code == "INVALID_STRATEGY"
