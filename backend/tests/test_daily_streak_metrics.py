"""
Unit tests for the daily win/loss streak metrics in _aggregate_metrics.

Contract under test (agreed with Álvaro 2026-08-28):
  - A "day" = a date WITH trades. No-trade days (weekends, rest days) do NOT
    break a streak; only the sequence of traded days matters.
  - Day PnL is net of locates fees (same figure the global equity curve uses).
  - A flat day (net PnL == 0) counts as a losing day — same convention as
    pnl == 0 trades in the trade-level streaks.

Pure unit test: synthetic trades only, no DB, no fixtures from conftest.
Runnable standalone:  python tests/test_daily_streak_metrics.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # backend/ on path

from app.services.backtest_service import _aggregate_metrics


def _t(date: str, pnl: float) -> dict:
    return {"date": date, "pnl": pnl}


def _metrics(trades, locates=None):
    return _aggregate_metrics(
        day_results=[],
        trades=trades,
        global_eq=[],
        global_dd=[],
        init_cash=10_000.0,
        locates_fee_by_date=locates or {},
    )


def test_basic_daily_streaks():
    # Day P&L: +100, +50, -30, +80, -30, -100  ->  W W L W L L L
    # Trade P&L sequence: +100 +50 -30 +80 -10 -20 -40 -60
    trades = [
        _t("2026-01-05", 100),
        _t("2026-01-06", 50),
        _t("2026-01-07", -30),
        _t("2026-01-08", 80),
        _t("2026-01-09", -10),
        _t("2026-01-09", -20),
        _t("2026-01-12", -40),
        _t("2026-01-13", -60),
    ]
    m = _metrics(trades)
    assert m["max_consecutive_winning_days"] == 2
    assert m["max_consecutive_losing_days"] == 3
    # Trade-level streaks unchanged: 2 wins, 4 losses (losses span the two
    # trades of 01-09 plus 01-12 and 01-13).
    assert m["max_consecutive_wins"] == 2
    assert m["max_consecutive_losses"] == 4


def test_no_trade_gap_does_not_break_streak():
    # Fri +100, then Mon/Tue: weekend (and any longer gap) must not split the run.
    trades = [
        _t("2026-01-02", 100),
        _t("2026-01-05", 100),
        _t("2026-01-06", 100),
    ]
    m = _metrics(trades)
    assert m["max_consecutive_winning_days"] == 3

    # A two-week vacation between two green days keeps them "consecutive"
    # (consecutive TRADED days, not calendar days).
    trades_far = [_t("2026-01-06", 100), _t("2026-01-20", 100)]
    m_far = _metrics(trades_far)
    assert m_far["max_consecutive_winning_days"] == 2


def test_day_pnl_is_net_of_locates_and_flat_day_loses():
    # Gross +50 on the day, but 100 in locates -> net -50 -> losing day.
    m = _metrics(
        [_t("2026-01-05", 50), _t("2026-01-06", -50)],
        locates={"2026-01-05": 100},
    )
    assert m["max_consecutive_winning_days"] == 0
    assert m["max_consecutive_losing_days"] == 2

    # Flat day (net 0) counts as a losing day, mirroring the trade convention.
    m_flat = _metrics([_t("2026-01-05", 0), _t("2026-01-06", 70)])
    assert m_flat["max_consecutive_losing_days"] == 1
    assert m_flat["max_consecutive_winning_days"] == 1


def test_empty_inputs_return_zeroed_keys():
    m = _aggregate_metrics([], [], [], [], 10_000.0)
    assert m["max_consecutive_winning_days"] == 0
    assert m["max_consecutive_losing_days"] == 0


if __name__ == "__main__":
    test_basic_daily_streaks()
    test_no_trade_gap_does_not_break_streak()
    test_day_pnl_is_net_of_locates_and_flat_day_loses()
    test_empty_inputs_return_zeroed_keys()
    print("OK")
