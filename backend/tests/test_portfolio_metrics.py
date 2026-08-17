"""
M5 — Portfolio metrics sanity on a realistic dispersed series (PRD §PART1).

Asserts that ``combine_portfolio`` produces SANE ranges (|Sharpe| < 5,
|Calmar| < 100, maxDD <= 0) and that the combined return reconciles with the
sum of per-strategy contributions. Also guards the Calmar explosion (215M bug).

Run directly (bypasses the DB-coupled conftest):
    backend/.venv/Scripts/python.exe tests/test_portfolio_metrics.py
or via pytest:
    backend/.venv/Scripts/python.exe -m pytest tests/test_portfolio_metrics.py -q
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.portfolio_service import (  # noqa: E402
    combine_portfolio,
    _strategy_cache_key,
    _aggregate_partials,
)

RNG = np.random.default_rng(20260811)


def _trading_days(start: str, end: str) -> list[str]:
    """Weekday (Mon–Fri) ISO dates between start and end inclusive."""
    s = datetime.fromisoformat(start).date()
    e = datetime.fromisoformat(end).date()
    out, d = [], s
    while d <= e:
        if d.weekday() < 5:  # Mon-Fri (proxy for XNYS sessions)
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _make_strategy_trades(
    sid: str,
    days: list[str],
    n: int,
    win_rate: float,
    avg_win_pct: float,
    avg_loss_pct: float,
) -> list[dict]:
    """Realistic dispersed trades: ``n`` trades spread across ``days``.

    ``return_pct`` is the strategy-level (size-independent) trade return; the
    portfolio re-sizes it by ``p_k · E``. Win/loss magnitudes are drawn with
    realistic per-trade dispersion so the daily-resampled Sharpe is sane.
    """
    idx = sorted(RNG.choice(len(days), size=n, replace=False))
    trades = []
    for k, i in enumerate(idx):
        day = days[int(i)]
        entry_dt = datetime.fromisoformat(day + "T13:30:00").replace(tzinfo=timezone.utc)
        hold_hours = int(RNG.integers(3, 7))
        exit_dt = entry_dt + timedelta(hours=hold_hours)
        win = RNG.random() < win_rate
        rp = float(RNG.normal(avg_win_pct if win else -avg_loss_pct, 0.6))
        trades.append(
            {
                "strategy_id": sid,
                "ticker": f"T{k % 20:03d}",
                "date": day,
                "entry_time_epoch": int(entry_dt.timestamp()),
                "exit_time_epoch": int(exit_dt.timestamp()),
                "return_pct": rp,
            }
        )
    return trades


def test_realistic_portfolio_metrics_sane():
    """~73 trades over ~500 days → Sharpe/Calmar/maxDD in realistic ranges."""
    days = _trading_days("2025-01-02", "2026-05-30")  # ~500 calendar days
    a = _make_strategy_trades("sailor", days, n=38, win_rate=0.56, avg_win_pct=1.4, avg_loss_pct=1.0)
    b = _make_strategy_trades(
        "definitiva", days, n=35, win_rate=0.52, avg_win_pct=1.6, avg_loss_pct=1.1
    )

    res = combine_portfolio(
        per_strategy_trades={"sailor": a, "definitiva": b},
        weights_pct={"sailor": 0.05, "definitiva": 0.08},
        init_cash=10000.0,
        max_total_exposure_pct=100.0,
    )
    agg = res["aggregate_metrics"]
    print("\n[portfolio] combined metrics:", agg)

    # ── Sane ranges (PRD M5) ──
    assert abs(agg["sharpe"]) < 5, f"Sharpe {agg['sharpe']} not sane (|x| < 5)"
    assert agg["calmar"] is None or abs(agg["calmar"]) < 100, (
        f"Calmar {agg['calmar']} not sane (|x| < 100)"
    )
    assert agg["max_drawdown_pct"] <= 0, f"maxDD {agg['max_drawdown_pct']} must be <= 0"
    assert agg["total_trades"] == len(a) + len(b)

    # ── Reconciliation (PRD acceptance #2): combined return ≈ Σ contributions ──
    contrib_sum = sum(ps["return_contribution_pct"] for ps in res["per_strategy"].values())
    assert abs(contrib_sum - agg["total_return_pct"]) < 0.01, (
        f"combined return {agg['total_return_pct']} != sum contributions {contrib_sum}"
    )

    # ── Standalone maxDD matches the per-strategy table (M4) ──
    for sid in res["strategy_order"]:
        sa = res["standalone"][sid]["aggregate_metrics"]["max_drawdown_pct"]
        ps = res["per_strategy"][sid]["max_drawdown_pct"]
        assert sa == ps, f"{sid}: standalone maxDD {sa} != per_strategy {ps}"


def test_calmar_no_explosion_on_near_flat_curve():
    """A near-monotonic equity (tiny/zero drawdown) must NOT yield a 215M Calmar."""
    days = _trading_days("2025-01-02", "2025-06-30")
    trades = []
    for day in days[:30]:
        entry_dt = datetime.fromisoformat(day + "T13:30:00").replace(tzinfo=timezone.utc)
        trades.append(
            {
                "strategy_id": "x",
                "ticker": "T",
                "date": day,
                "entry_time_epoch": int(entry_dt.timestamp()),
                "exit_time_epoch": int((entry_dt + timedelta(hours=4)).timestamp()),
                "return_pct": float(RNG.normal(0.8, 0.05)),  # tiny, consistent +
            }
        )
    res = combine_portfolio({"x": trades}, {"x": 0.10}, 10000.0)
    calmar = res["aggregate_metrics"]["calmar"]
    print("\n[portfolio] near-flat calmar:", calmar)
    assert calmar is None or abs(calmar) < 1000, f"Calmar exploded: {calmar}"


def test_combined_maxdd_benefits_from_diversification():
    """Two lowly-correlated strategies → combined maxDD no worse than the sum
    of standalone maxDDs (the diversification benefit the UI highlights)."""
    days = _trading_days("2025-01-02", "2026-05-30")
    # Different win patterns on different day subsets → low correlation.
    a_days = days[0::2]
    b_days = days[1::2]
    a = _make_strategy_trades("a", a_days, n=35, win_rate=0.55, avg_win_pct=1.5, avg_loss_pct=1.1)
    b = _make_strategy_trades("b", b_days, n=35, win_rate=0.50, avg_win_pct=1.7, avg_loss_pct=1.2)
    res = combine_portfolio({"a": a, "b": b}, {"a": 0.07, "b": 0.07}, 10000.0)
    combined_dd = res["aggregate_metrics"]["max_drawdown_pct"]
    sum_dd = sum(
        res["standalone"][s]["aggregate_metrics"]["max_drawdown_pct"]
        for s in res["strategy_order"]
    )
    print(f"\n[portfolio] combined maxDD={combined_dd:.3f}%  sum standalone={sum_dd:.3f}%")
    assert combined_dd >= sum_dd, "combined maxDD should be >= (less negative than) the sum"


# ──────────────────────────────────────────────────────────────────────────
# PRD FIX_CRITICO T4 — zero-duration leak tests (the exact case that broke it)
# ──────────────────────────────────────────────────────────────────────────
def test_zero_duration_trades_close_and_realize_pnl():
    """Zero-duration trades (exit == entry) MUST open + close and realize PnL.

    This is the exact case that caused the permanent exposure leak: the exit
    was processed before the trade's own entry, so the entry reserved notional
    that was never freed. Here every trade must close and contribute PnL, and
    open_positions_leaked must be 0. (PRD FIX_CRITICO T4.)
    """
    days = _trading_days("2025-01-02", "2025-03-31")
    trades = []
    for k, day in enumerate(days[:20]):
        entry_dt = datetime.fromisoformat(day + "T13:30:00").replace(tzinfo=timezone.utc)
        entry_e = int(entry_dt.timestamp())
        zero_duration = (k % 2 == 0)
        exit_e = entry_e if zero_duration else int((entry_dt + timedelta(hours=3)).timestamp())
        rp = 2.0 if zero_duration else -1.0
        trades.append(
            {
                "strategy_id": "s",
                "ticker": f"T{k}",
                "date": day,
                "entry_time_epoch": entry_e,
                "exit_time_epoch": exit_e,
                "return_pct": float(rp),
            }
        )
    res = combine_portfolio({"s": trades}, {"s": 0.05}, 10000.0, 100.0)

    # No leak — every opened position was closed.
    assert res["open_positions_leaked"] == 0, res["open_positions_leaked"]
    # All 20 registered (5% each, spread over distinct days → no saturation).
    assert res["trades_registrados"] == 20, res["trades_registrados"]
    assert res["skipped_by_cap"] == 0
    # Every registered trade realized PnL (none left open with pnl_dollars None).
    never_closed = [t for t in res["combined_trades"] if t.get("pnl_dollars") is None]
    assert never_closed == [], f"{len(never_closed)} trades never realized PnL"
    # Equity moved (10 winners @2% on 5% size vs 10 losers @1%).
    assert res["aggregate_metrics"]["final_equity"] != 10000.0
    print(
        f"[OK] zero_duration: 20 trades registered, leaked={res['open_positions_leaked']}, "
        f"final={res['aggregate_metrics']['final_equity']}"
    )


def test_saturation_anti_regression_zero_duration():
    """200 zero-duration trades @5% cap 100% spread over a date range → ALL 200
    must register (no saturation from leaked exposure).

    Before the fix, ~20 leaked positions (5% each) saturated the 100% cap and
    silently dropped every later entry → the curve "died" after a few days.
    (PRD FIX_CRITICO T4 — anti-regression of the saturation.)
    """
    days = _trading_days("2024-01-02", "2025-05-30")  # plenty of distinct weekdays
    assert len(days) >= 200, len(days)
    trades = []
    for k, day in enumerate(days[:200]):
        e = int(
            datetime.fromisoformat(day + "T13:30:00")
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )
        trades.append(
            {
                "strategy_id": "s",
                "ticker": f"T{k}",
                "date": day,
                "entry_time_epoch": e,
                "exit_time_epoch": e,  # ZERO DURATION (exit == entry)
                "return_pct": 1.0,
            }
        )
    res = combine_portfolio({"s": trades}, {"s": 0.05}, 10000.0, 100.0)

    assert res["open_positions_leaked"] == 0
    assert res["trades_registrados"] == 200, (
        f"expected 200 registered, got {res['trades_registrados']} "
        f"(skipped_by_cap={res['skipped_by_cap']})"
    )
    assert res["skipped_by_cap"] == 0

    # The curve must span the FULL entry-date range (not die after a few days).
    # Since 2026-08-14 the combined curve is DENSE DAILY (one point per day at
    # 00:00 UTC), so compare at DATE granularity — intraday entry epochs are
    # always later than their own day's curve point.
    entry_days = sorted({t["date"] for t in trades})
    curve_days = sorted(
        {
            datetime.fromtimestamp(p["time"], tz=timezone.utc).strftime("%Y-%m-%d")
            for p in res["equity_curve"]
        }
    )
    assert curve_days[0] <= entry_days[0]
    assert curve_days[-1] >= entry_days[-1], (
        f"curve truncated: ends {curve_days[-1]} < last entry day {entry_days[-1]}"
    )
    print(
        f"[OK] saturation: 200/200 registered, curve spans "
        f"{curve_days[0]}->{curve_days[-1]}"
    )


def test_reconciliation_holds():
    """T3: trades_entrada_totales == trades_registrados + skipped_by_cap, and
    input_trades_per_strategy is exposed for comparison."""
    days = _trading_days("2025-01-02", "2025-06-30")
    a = _make_strategy_trades("a", days, n=30, win_rate=0.5, avg_win_pct=1.5, avg_loss_pct=1.0)
    b = _make_strategy_trades("b", days, n=30, win_rate=0.5, avg_win_pct=1.5, avg_loss_pct=1.0)
    res = combine_portfolio({"a": a, "b": b}, {"a": 0.05, "b": 0.05}, 10000.0, 100.0)

    assert res["trades_entrada_totales"] == res["trades_registrados"] + res["skipped_by_cap"], (
        f"reconciliation failed: {res['trades_entrada_totales']} != "
        f"{res['trades_registrados']} + {res['skipped_by_cap']}"
    )
    assert res["input_trades_per_strategy"] == {"a": 30, "b": 30}
    print(
        f"[OK] reconciliation: {res['trades_entrada_totales']} = "
        f"{res['trades_registrados']} + {res['skipped_by_cap']}"
    )


def test_combined_curve_covers_input_date_range():
    """The combined equity curve must span the SAME date range as the input
    trades — not die early. The leak truncated it to a few days."""
    days = _trading_days("2025-01-02", "2025-07-31")  # ~7 months
    a = _make_strategy_trades("a", days, n=40, win_rate=0.55, avg_win_pct=1.4, avg_loss_pct=1.0)
    b = _make_strategy_trades("b", days, n=35, win_rate=0.50, avg_win_pct=1.6, avg_loss_pct=1.1)
    # inject some zero-duration trades into both (the case that broke it)
    for k in range(5):
        day = days[10 + k * 7]
        e = int(
            datetime.fromisoformat(day + "T14:00:00")
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )
        a.append(
            {"strategy_id": "a", "ticker": f"Z{k}", "date": day,
             "entry_time_epoch": e, "exit_time_epoch": e, "return_pct": 1.5}
        )
        b.append(
            {"strategy_id": "b", "ticker": f"Z{k}", "date": day,
             "entry_time_epoch": e, "exit_time_epoch": e, "return_pct": -1.0}
        )
    res = combine_portfolio({"a": a, "b": b}, {"a": 0.05, "b": 0.05}, 10000.0, 100.0)

    # Dense-daily curve since 2026-08-14 → compare at DATE granularity.
    all_entry_days = sorted({t["date"] for t in a + b})
    curve_days = sorted(
        {
            datetime.fromtimestamp(p["time"], tz=timezone.utc).strftime("%Y-%m-%d")
            for p in res["equity_curve"]
        }
    )
    assert curve_days[0] <= all_entry_days[0]
    assert curve_days[-1] >= all_entry_days[-1], "curve truncated before last trade"
    assert res["open_positions_leaked"] == 0
    print(
        f"[OK] curve range covers input: {curve_days[0]}->{curve_days[-1]} "
        f"vs input {all_entry_days[0]}->{all_entry_days[-1]}"
    )


# ──────────────────────────────────────────────────────────────────────────
# PRD R3 T7 — sizing base diaria + costes
# ──────────────────────────────────────────────────────────────────────────
def test_fixed_sizing_is_linear():
    """R3 T7: fixed mode -> PnL is LINEAR (no compounding).

    N trades of the same return_pct -> total PnL = N * pct * init * ret/100.
    Every notional == pct*init (constant)."""
    init = 10000.0
    pct = 0.10
    ret = 4.0
    n = 5
    days = _trading_days("2025-01-02", "2025-01-10")[:n]
    trades = []
    for k, day in enumerate(days):
        e = int(
            datetime.fromisoformat(day + "T13:30:00")
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )
        trades.append(
            {
                "strategy_id": "s",
                "ticker": f"T{k}",
                "date": day,
                "entry_time_epoch": e,
                "exit_time_epoch": e + 3600,
                "return_pct": ret,
            }
        )
    res = combine_portfolio({"s": trades}, {"s": pct}, init, 100.0, sizing_mode="fixed")
    expected_pnl = n * pct * init * ret / 100.0  # 5 * 0.10 * 10000 * 4/100 = 200
    assert abs(res["aggregate_metrics"]["final_equity"] - (init + expected_pnl)) < 1e-6, (
        res["aggregate_metrics"]["final_equity"]
    )
    assert abs(res["aggregate_metrics"]["total_return_pct"] - (expected_pnl / init * 100)) < 1e-4
    for t in res["combined_trades"]:
        assert abs(t["notional"] - pct * init) < 1e-6, t["notional"]
    print(f"[OK] fixed linear: final={res['aggregate_metrics']['final_equity']} (expected {init + expected_pnl})")


def test_daily_compound_two_days_exact():
    """R3 T7: daily_compound -> base rolls once per day; within a day constant.

    Day1 base=10000 (notional 1000, 2 winners @10% -> E=10200 at close).
    Day2 base=10200 (notional 1020, @10% -> E=10302)."""
    init = 10000.0
    pct = 0.10
    d1, d2 = "2025-01-02", "2025-01-03"

    def _e(day, hh, mm=0):
        return int(
            datetime.fromisoformat(f"{day}T{hh:02d}:{mm:02d}:00")
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )

    trades = [
        {"strategy_id": "s", "ticker": "A", "date": d1,
         "entry_time_epoch": _e(d1, 13, 30), "exit_time_epoch": _e(d1, 14, 30), "return_pct": 10.0},
        {"strategy_id": "s", "ticker": "B", "date": d1,
         "entry_time_epoch": _e(d1, 15, 0), "exit_time_epoch": _e(d1, 16, 0), "return_pct": 10.0},
        {"strategy_id": "s", "ticker": "C", "date": d2,
         "entry_time_epoch": _e(d2, 13, 30), "exit_time_epoch": _e(d2, 14, 30), "return_pct": 10.0},
    ]
    res = combine_portfolio({"s": trades}, {"s": pct}, init, 100.0, sizing_mode="daily_compound")
    assert abs(res["aggregate_metrics"]["final_equity"] - 10302.0) < 1e-6, (
        res["aggregate_metrics"]["final_equity"]
    )
    by_date: dict[str, list[float]] = {}
    for t in res["combined_trades"]:
        by_date.setdefault(t["date"], []).append(t["notional"])
    # Day1: both trades use base 10000 -> notional 1000 (no intraday compounding)
    assert all(abs(x - 1000.0) < 1e-6 for x in by_date[d1]), by_date[d1]
    # Day2: rolled base 10200 -> notional 1020
    assert abs(by_date[d2][0] - 1020.0) < 1e-6, by_date[d2]
    print("[OK] daily_compound: final=10302, day1 notional=1000, day2 notional=1020")


def test_no_intraday_compounding():
    """R3 T7: NO intraday compounding in EITHER mode — 50 trades same day.

    Before R3, notional = pct * E reinvested after every trade (compounding).
    Now every trade on the same day uses the SAME base -> constant notional."""
    init = 10000.0
    pct = 0.05
    ret = 2.0
    day = "2025-01-02"
    base_e = int(
        datetime.fromisoformat(day + "T09:30:00")
        .replace(tzinfo=timezone.utc)
        .timestamp()
    )
    trades = []
    for k in range(50):
        e = base_e + k * 120  # sequential non-overlapping 1-min trades
        trades.append(
            {
                "strategy_id": "s",
                "ticker": f"T{k}",
                "date": day,
                "entry_time_epoch": e,
                "exit_time_epoch": e + 60,
                "return_pct": ret,
            }
        )
    expected = init + 50 * pct * init * ret / 100.0  # 10500
    for mode in ("fixed", "daily_compound"):
        res = combine_portfolio({"s": trades}, {"s": pct}, init, 100.0, sizing_mode=mode)
        for t in res["combined_trades"]:
            assert abs(t["notional"] - pct * init) < 1e-6, f"{mode}: notional {t['notional']}"
        assert abs(res["aggregate_metrics"]["final_equity"] - expected) < 1e-6, (
            f"{mode}: final {res['aggregate_metrics']['final_equity']}"
        )
        print(f"[OK] no intraday compounding ({mode}): all notionals={pct * init}, final={expected}")


def test_cache_key_includes_costs():
    """R3 T7/T4: costs are part of the cache key -> a cost change re-runs.

    The fee/slippage deduction itself happens in the sim
    (portfolio_sim_jit.py:556, ``pnl = gross - fees``); this test guards the
    portfolio plumbing so a cost change is NOT silently served from cache."""
    sdef = {"name": "X", "dataset_id": "ds"}
    k0 = _strategy_cache_key("ds", "2025-01-01", "2025-01-31", sdef, {})
    k1 = _strategy_cache_key("ds", "2025-01-01", "2025-01-31", sdef, {"fees": 0.1})
    k2 = _strategy_cache_key("ds", "2025-01-01", "2025-01-31", sdef, {"fees": 0.1, "slippage": 0.001})
    assert k0 != k1, "fees change must alter the cache key"
    assert k1 != k2, "slippage change must alter the cache key"
    assert k0 == _strategy_cache_key("ds", "2025-01-01", "2025-01-31", sdef, {}), "same costs -> same key"
    print(f"[OK] cache key includes costs: {k0} != {k1} != {k2}")


# ──────────────────────────────────────────────────────────────────────────
# R4 — partials: one ENTRADA = one position (aggregation + sizing once)
# ──────────────────────────────────────────────────────────────────────────
def test_aggregate_partials_unit():
    """R4 T1: _aggregate_partials groups by (ticker, entry_epoch), sums ret, max exit.

    Mirrors the PRD's verified real example (CHOW 2026-01-02: two partials
    7.0088 + 14.3168 = 21.33%). Round numbers here for an exact assertion.
    """
    e = 1000
    trades = [
        {"ticker": "X", "date": "d", "entry_time_epoch": e, "exit_time_epoch": e + 10,
         "return_pct": 7.0, "pnl": 3.5, "r_multiple": 0.04, "exit_reason": "Partial TP"},
        {"ticker": "X", "date": "d", "entry_time_epoch": e, "exit_time_epoch": e + 20,
         "return_pct": 14.0, "pnl": 7.0, "r_multiple": 0.07, "exit_reason": "EOD"},
        {"ticker": "Y", "date": "d", "entry_time_epoch": e + 100, "exit_time_epoch": e + 110,
         "return_pct": -2.0, "pnl": -1.0, "r_multiple": -0.01, "exit_reason": "SL"},
    ]
    positions, n_raw = _aggregate_partials(trades)
    assert n_raw == 3
    assert len(positions) == 2  # X (merged) + Y
    x = [p for p in positions if p["ticker"] == "X"][0]
    assert abs(x["return_pct"] - 21.0) < 1e-9          # additive
    assert x["exit_time_epoch"] == e + 20              # last partial exit
    assert x["n_partials"] == 2
    assert abs(x["pnl_backtest"] - 10.5) < 1e-9
    assert x["exit_reasons"] == ["Partial TP", "EOD"]
    print("[OK] aggregate_partials: 2 partials -> 1 position, ret summed, max exit")


def test_partials_aggregate_into_one_position():
    """R4 T1/T2: 3 partials of ONE entry -> 1 position, sized ONCE.

    return_pct of partials are additive (verified on real Sailor data). The
    portfolio must size the ENTRY once (notional = pct*base), not 3x.
    """
    sid = "sailor"
    entry = 1_000_000
    trades = [
        {"strategy_id": sid, "ticker": "CHOW", "date": "2026-01-02",
         "entry_time_epoch": entry, "exit_time_epoch": entry + 3600, "return_pct": 10.0},
        {"strategy_id": sid, "ticker": "CHOW", "date": "2026-01-02",
         "entry_time_epoch": entry, "exit_time_epoch": entry + 7200, "return_pct": 5.0},
        {"strategy_id": sid, "ticker": "CHOW", "date": "2026-01-02",
         "entry_time_epoch": entry, "exit_time_epoch": entry + 10800, "return_pct": -3.0},
    ]
    res = combine_portfolio(
        per_strategy_trades={sid: trades},
        weights_pct={sid: 0.10},
        init_cash=10000.0,
        max_total_exposure_pct=100.0,
        sizing_mode="fixed",
    )
    # 3 raw rows -> 1 aggregated position
    assert res["input_rows_per_strategy"][sid] == 3
    assert res["positions_per_strategy"][sid] == 1
    assert res["positions_registradas"] == 1
    assert res["open_positions_leaked"] == 0
    # reconciliation: positions == registradas + skipped_by_cap
    assert res["positions_per_strategy"][sid] == res["positions_registradas"] + res["skipped_by_cap"]

    ct = res["combined_trades"]
    assert len(ct) == 1, f"expected 1 position, got {len(ct)}"
    # additive return: 10 + 5 - 3 = 12
    assert abs(ct[0]["return_pct"] - 12.0) < 1e-9
    # sized ONCE: notional = 0.10 * 10000 = 1000 (NOT 3x)
    assert abs(ct[0]["notional"] - 1000.0) < 1e-6
    # pnl = 1000 * 12/100 = 120
    assert abs(ct[0]["pnl_dollars"] - 120.0) < 1e-6
    # exit = last partial (entry + 10800)
    assert ct[0]["exit_time_epoch"] == entry + 10800
    print("[OK] partials -> 1 position sized once (notional=1000, pnl=120)")


def test_mixed_simple_and_partials():
    """R4 T1/T3: positions == distinct entries (simple entries + partial entries)."""
    sid = "sailor"
    e = 1_000_000
    trades = [
        # entry A: single row
        {"strategy_id": sid, "ticker": "A", "date": "2026-01-02",
         "entry_time_epoch": e, "exit_time_epoch": e + 100, "return_pct": 2.0},
        # entry B: 2 partials (same entry epoch)
        {"strategy_id": sid, "ticker": "B", "date": "2026-01-02",
         "entry_time_epoch": e + 200, "exit_time_epoch": e + 300, "return_pct": 3.0},
        {"strategy_id": sid, "ticker": "B", "date": "2026-01-02",
         "entry_time_epoch": e + 200, "exit_time_epoch": e + 400, "return_pct": 4.0},
        # entry C: single row
        {"strategy_id": sid, "ticker": "C", "date": "2026-01-02",
         "entry_time_epoch": e + 500, "exit_time_epoch": e + 600, "return_pct": -1.0},
    ]
    res = combine_portfolio(
        per_strategy_trades={sid: trades},
        weights_pct={sid: 0.05},
        init_cash=10000.0,
        max_total_exposure_pct=100.0,
    )
    assert res["input_rows_per_strategy"][sid] == 4   # 4 raw rows
    assert res["positions_per_strategy"][sid] == 3    # A, B(merged), C
    assert res["positions_registradas"] == 3
    assert res["open_positions_leaked"] == 0
    assert res["positions_per_strategy"][sid] == res["positions_registradas"] + res["skipped_by_cap"]
    # standalone must aggregate the same way (T3): 1 strategy -> 3 positions
    sa_trades = res["combined_trades"]
    assert len(sa_trades) == 3
    # entry B's merged return = 3 + 4 = 7
    b = [t for t in sa_trades if t["ticker"] == "B"][0]
    assert abs(b["return_pct"] - 7.0) < 1e-9
    print("[OK] mixed simple+partials -> 3 positions from 4 rows (B merged to +7%)")


if __name__ == "__main__":
    test_realistic_portfolio_metrics_sane()
    print("OK realistic_portfolio_metrics_sane")
    test_calmar_no_explosion_on_near_flat_curve()
    print("OK calmar_no_explosion_on_near_flat_curve")
    test_combined_maxdd_benefits_from_diversification()
    print("OK combined_maxdd_benefits_from_diversification")
    test_zero_duration_trades_close_and_realize_pnl()
    print("OK zero_duration_trades_close_and_realize_pnl")
    test_saturation_anti_regression_zero_duration()
    print("OK saturation_anti_regression_zero_duration")
    test_reconciliation_holds()
    print("OK reconciliation_holds")
    test_combined_curve_covers_input_date_range()
    print("OK combined_curve_covers_input_date_range")
    test_fixed_sizing_is_linear()
    print("OK fixed_sizing_is_linear")
    test_daily_compound_two_days_exact()
    print("OK daily_compound_two_days_exact")
    test_no_intraday_compounding()
    print("OK no_intraday_compounding")
    test_cache_key_includes_costs()
    print("OK cache_key_includes_costs")
    test_aggregate_partials_unit()
    print("OK aggregate_partials_unit")
    test_partials_aggregate_into_one_position()
    print("OK partials_aggregate_into_one_position")
    test_mixed_simple_and_partials()
    print("OK mixed_simple_and_partials")
    print("\nALL PORTFOLIO METRIC TESTS PASSED")
