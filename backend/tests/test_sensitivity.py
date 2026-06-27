"""Tests for Module 3 — locate/slippage sensitivity (EPIC A3). Deterministic rng."""
import numpy as np
import pytest

from app.services.robustness_service import (
    RobustnessError,
    run_sensitivity,
    critical_locate_threshold,
)


def _rng():
    return np.random.default_rng(7)


SHORTS = [
    {"pnl": 120.0, "size": 100, "entry_price": 10.0, "direction": "short", "return_pct": 1.2},
    {"pnl": -40.0, "size": 100, "entry_price": 12.0, "direction": "short", "return_pct": -0.4},
]
LONGS = [
    {"pnl": 50.0, "size": 50, "entry_price": 20.0, "direction": "long", "return_pct": 0.5},
    {"pnl": -10.0, "size": 50, "entry_price": 22.0, "direction": "long", "return_pct": -0.1},
]


def test_critical_threshold_closed_form():
    # NP_base = 120 - 40 = 80 ; notional shorts = 100*10 + 100*12 = 2200
    # C_crit = 80 / 2200 * 100 = 3.6364 %
    assert critical_locate_threshold(SHORTS) == pytest.approx(3.6364, abs=1e-4)


def test_no_shorts_threshold_is_none():
    assert critical_locate_threshold(LONGS) is None


def test_curves_count_matches_locates():
    res = run_sensitivity(SHORTS, {"min": 0.5, "max": 3.0, "step": 0.5}, rng=_rng())
    # [0.5, 1.0, 1.5, 2.0, 2.5, 3.0] ⇒ 6 curves
    assert len(res["curves"]) == 6
    assert "locate_0.5" in res["curves"] and "locate_3.0" in res["curves"]
    assert res["critical_locate_threshold"] == pytest.approx(3.6364, abs=1e-4)


def test_higher_locate_lowers_final_equity():
    res = run_sensitivity(SHORTS, {"min": 0.5, "max": 3.0, "step": 0.5}, rng=_rng())
    final_low = res["curves"]["locate_0.5"][-1]["value"]
    final_high = res["curves"]["locate_3.0"][-1]["value"]
    assert final_high < final_low


def test_zero_step_raises():
    with pytest.raises(RobustnessError) as exc:
        run_sensitivity(SHORTS, {"min": 0.5, "max": 3.0, "step": 0.0}, rng=_rng())
    assert exc.value.code == "PARAMETER_OUT_OF_BOUNDS"
