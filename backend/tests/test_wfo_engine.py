"""Tests for Module 2 — WFO pure helpers (EPIC A2).

These cover the partitioning + formulas WITHOUT running the engine (the heavy
orchestrator run_walk_forward needs real market data and runs in background).
"""
import pytest

from app.services.robustness_service import (
    RobustnessError,
    _walk_forward_windows,
    _wfe,
    _win_rate_penalty,
    _build_param_axes,
    _concatenated_oos_drawdown,
)


def _dates(n):
    # 2024-01-01 .. sequential, lexicographically sortable.
    return [f"2024-{(i // 28) % 12 + 1:02d}-{(i % 28) + 1:02d}" for i in range(n)]


def test_single_window_anti_lookahead():
    dates = _dates(10)
    windows = _walk_forward_windows(dates, is_pct=70, oos_pct=30, step_pct=30)
    assert len(windows) == 1
    w = windows[0]
    # No overlap: every IS date strictly before every OOS date.
    assert max(w["is"]) < min(w["oos"])
    assert len(w["is"]) == 7 and len(w["oos"]) == 3


def test_multiple_rolling_windows_non_overlapping_within():
    dates = _dates(20)
    windows = _walk_forward_windows(dates, is_pct=50, oos_pct=25, step_pct=25)
    assert len(windows) >= 2
    for w in windows:
        assert max(w["is"]) < min(w["oos"])  # anti-lookahead per window


def test_invalid_percentages_raise():
    with pytest.raises(RobustnessError) as exc:
        _walk_forward_windows(_dates(10), is_pct=0, oos_pct=30, step_pct=30)
    assert exc.value.code == "PARAMETER_OUT_OF_BOUNDS"


def test_wfe_formula_and_zero_guard():
    assert _wfe(1.23, 1.8) == pytest.approx(68.33, abs=0.01)
    assert _wfe(1.0, 0.0) == 0.0       # IS metric == 0 ⇒ 0.0 (no /0)
    assert _wfe(1.0, -2.0) == 0.0      # IS metric < 0 ⇒ 0.0


def test_win_rate_penalty():
    assert _win_rate_penalty(55.2, 46.7) == pytest.approx(8.5, abs=1e-6)


def test_param_axes_capped_at_50_combos():
    cfgs = [
        {"id": "a", "path": "x.a", "min": 0, "max": 10, "steps": 10},
        {"id": "b", "path": "x.b", "min": 0, "max": 10, "steps": 10},
    ]
    axes = _build_param_axes(cfgs, max_combos=50)
    product = 1
    for ax in axes:
        product *= len(ax["values"])
    assert product <= 50


def test_concatenated_oos_drawdown():
    trades = [
        {"pnl": 100, "entry_time": "2024-01-01"},
        {"pnl": -300, "entry_time": "2024-01-02"},
        {"pnl": 50, "entry_time": "2024-01-03"},
    ]
    dd = _concatenated_oos_drawdown(trades, init_cash=10000)
    assert dd < 0  # there is a drawdown
