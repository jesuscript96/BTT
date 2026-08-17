"""
Smoke test for portfolio_service.combine_portfolio (no DB / no orchestrator).

Modelo desde 2026-08-14 (suma de curvas, sin backtest conjunto):
  1. Basic sizing math: notional = p_k · base, pnl$ = notional · return_pct/100.
  2. Exposure cap scales/skips trades DENTRO de una estrategia (nunca entre
     estrategias: ninguna puede desplazar a otra).
  3. Suma de curvas: PnL combinado == Σ PnL standalone, y la curva total es
     la suma diaria (equivalencia con testearlas juntas).
  4. Diversification (§6.3): combined maxDD < sum of standalone maxDDs when
     the two strategies are uncorrelated (trade on different days).
  5. Correlation matrix: diagonal = 1, off-diagonal reflects overlap.
  6. Recombine determinism: same trades + weights → identical result.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.portfolio_service import combine_portfolio


def _trade(sid, day, entry_epoch, exit_epoch, return_pct, ticker="X"):
    return {
        "strategy_id": sid,
        "ticker": ticker,
        "date": day,
        "entry_time_epoch": entry_epoch,
        "exit_time_epoch": exit_epoch,
        "return_pct": return_pct,
    }


def test_basic_sizing():
    # One strategy, one winning trade +5% return, p_k=10%, init 10000.
    trades = {
        "A": [_trade("A", "2026-01-02", 1000, 2000, 5.0)],
    }
    res = combine_portfolio(trades, {"A": 0.10}, 10000.0, 100.0)
    # notional = 0.10 * 10000 = 1000; pnl$ = 1000 * 5% = 50
    assert abs(res["aggregate_metrics"]["final_equity"] - 10050.0) < 1e-6, res["aggregate_metrics"]
    assert abs(res["aggregate_metrics"]["total_return_pct"] - 0.5) < 1e-4
    assert res["aggregate_metrics"]["total_trades"] == 1
    assert res["per_strategy"]["A"]["return_contribution_dollars"] == 50.0
    print("[OK] basic_sizing: final=10050, return=0.5%")


def test_exposure_cap_scales():
    # Cap applies WITHIN a strategy (never between strategies). Two concurrent
    # trades of the SAME strategy, each 60% → cap 100% scales the 2nd.
    trades = {
        "A": [
            _trade("A", "2026-01-02", 1000, 5000, 10.0, ticker="X"),
            _trade("A", "2026-01-02", 1001, 5001, 10.0, ticker="Y"),
        ],
    }
    res = combine_portfolio(trades, {"A": 0.60}, 10000.0, 100.0)
    ct = sorted(res["combined_trades"], key=lambda t: t["notional"])
    # 1st notional = 6000 (fits); 2nd wants 6000 but only 4000 room → scaled.
    assert ct[0]["notional"] == 4000.0 and ct[0]["scaled"] is True, ct
    assert ct[1]["notional"] == 6000.0, ct
    assert res["scaled_by_cap"] == 1, res["scaled_by_cap"]
    print("[OK] exposure_cap: within-strategy 2nd trade scaled 6000→4000")


def test_exposure_cap_skips():
    # Cap 50% within one strategy: 1st trade takes 50%, 2nd wants 50%
    # concurrently → 0 room → skipped.
    trades = {
        "A": [
            _trade("A", "2026-01-02", 1000, 5000, 10.0, ticker="X"),
            _trade("A", "2026-01-02", 1001, 5001, 10.0, ticker="Y"),
        ],
    }
    res = combine_portfolio(trades, {"A": 0.50}, 10000.0, 50.0)
    assert len(res["combined_trades"]) == 1, res["combined_trades"]
    assert res["combined_trades"][0]["notional"] == 5000.0
    assert res["skipped_by_cap"] == 1, res["skipped_by_cap"]
    print("[OK] exposure_cap_skip: 2nd within-strategy trade omitted (no room)")


def test_cap_never_displaces_across_strategies():
    # Two strategies each at 60% concurrently → joint exposure 120% > cap 100%,
    # but the cap is PER STRATEGY now: both run at full notional, none scaled.
    trades = {
        "A": [_trade("A", "2026-01-02", 1000, 5000, 10.0)],
        "B": [_trade("B", "2026-01-02", 1001, 5001, 10.0)],
    }
    res = combine_portfolio(trades, {"A": 0.60, "B": 0.60}, 10000.0, 100.0)
    ct = {t["strategy_id"]: t for t in res["combined_trades"]}
    assert ct["A"]["notional"] == 6000.0, ct["A"]
    assert ct["B"]["notional"] == 6000.0 and not ct["B"]["scaled"], ct["B"]
    assert res["skipped_by_cap"] == 0 and res["scaled_by_cap"] == 0
    print("[OK] cap per-strategy: A=6000 and B=6000 both full (no displacement)")


def test_sum_of_curves():
    # Core property of the 2026-08-14 model: combining == summing the daily
    # PnL curves. Combined PnL == Σ standalone PnLs, and the total equity
    # curve is init_cash + cumulative summed daily PnL.
    trades = {
        "A": [
            _trade("A", "2026-01-02", 1000, 2000, 5.0),
            _trade("A", "2026-01-04", 5000, 6000, -2.0),
        ],
        "B": [
            _trade("B", "2026-01-02", 1500, 2500, 3.0),
            _trade("B", "2026-01-03", 3000, 4000, -1.0),
        ],
    }
    w = {"A": 0.10, "B": 0.05}
    res = combine_portfolio(trades, w, 10000.0)
    comb_pnl = res["aggregate_metrics"]["final_equity"] - 10000.0
    sa_pnl = sum(
        res["standalone"][sid]["aggregate_metrics"]["final_equity"] - 10000.0
        for sid in ("A", "B")
    )
    # A: 1000*5% + 1000*(-2%) = 30 ; B: 500*3% + 500*(-1%) = 10 → total 40.
    assert abs(comb_pnl - 40.0) < 1e-6, comb_pnl
    assert abs(sa_pnl - 40.0) < 1e-6, sa_pnl
    assert abs(comb_pnl - sa_pnl) < 1e-9
    # Daily totals: 01-02 → +50+15=65 ; 01-03 → -5 ; 01-04 → -20.
    d = res["daily_pnl_total"]
    assert abs(d["2026-01-02"] - 65.0) < 1e-6, d
    assert abs(d["2026-01-03"] - (-5.0)) < 1e-6, d
    assert abs(d["2026-01-04"] - (-20.0)) < 1e-6, d
    assert res["combination_mode"] == "sum_of_daily_pnl_curves"
    print(f"[OK] sum_of_curves: combined pnl={comb_pnl} == A+B standalone={sa_pnl}")


def test_diversification():
    # A trades days 1-2, B trades days 3-4 (uncorrelated, non-overlapping).
    # Each has a -10% trade (big DD) on different days → combined DD < sum.
    trades = {
        "A": [
            _trade("A", "2026-01-02", 100_000, 200_000, -10.0),
            _trade("A", "2026-01-03", 300_000, 400_000, 8.0),
        ],
        "B": [
            _trade("B", "2026-01-04", 500_000, 600_000, -10.0),
            _trade("B", "2026-01-05", 700_000, 800_000, 8.0),
        ],
    }
    res = combine_portfolio(trades, {"A": 0.05, "B": 0.05}, 10000.0, 100.0)
    comb_dd = res["aggregate_metrics"]["max_drawdown_pct"]
    sa_dd = res["standalone"]["A"]["aggregate_metrics"]["max_drawdown_pct"]
    sb_dd = res["standalone"]["B"]["aggregate_metrics"]["max_drawdown_pct"]
    print(f"   combined maxDD={comb_dd}%  standalone A={sa_dd}% B={sb_dd}%  sum={sa_dd+sb_dd}%")
    # Combined DD should be <= the worst standalone (diversification), and
    # strictly less than the sum of the two standalone DDs.
    assert comb_dd > sa_dd + sb_dd, f"diversification failed: {comb_dd} vs {sa_dd+sb_dd}"
    print("[OK] diversification: combined maxDD > (more negative than) sum → wait, check sign")


def test_diversification_sign():
    # max_drawdown_pct is NEGATIVE. "combined < sum" means more-negative? No:
    # §6.3 says maxDD combined < maxDD_A + maxDD_B in ABSOLUTE terms (the
    # combined drawdown is smaller in magnitude). Redo with absolute values.
    trades = {
        "A": [
            _trade("A", "2026-01-02", 100_000, 200_000, -10.0),
            _trade("A", "2026-01-03", 300_000, 400_000, 8.0),
        ],
        "B": [
            _trade("B", "2026-01-04", 500_000, 600_000, -10.0),
            _trade("B", "2026-01-05", 700_000, 800_000, 8.0),
        ],
    }
    res = combine_portfolio(trades, {"A": 0.05, "B": 0.05}, 10000.0, 100.0)
    comb_dd = abs(res["aggregate_metrics"]["max_drawdown_pct"])
    sa_dd = abs(res["standalone"]["A"]["aggregate_metrics"]["max_drawdown_pct"])
    sb_dd = abs(res["standalone"]["B"]["aggregate_metrics"]["max_drawdown_pct"])
    print(f"   |combined maxDD|={comb_dd}%  |A|={sa_dd}%  |B|={sb_dd}%  |A|+|B|={sa_dd+sb_dd}%")
    assert comb_dd < sa_dd + sb_dd - 1e-9, f"diversification failed: {comb_dd} >= {sa_dd+sb_dd}"
    print("[OK] diversification: |combined maxDD| < |A| + |B|")


def test_correlation():
    # Need multiple days with variance for Pearson. Identical return pattern on
    # the same 3 days → correlation ~1.0. Anti-correlated → ~-1.0.
    same = {
        "A": [
            _trade("A", "2026-01-02", 1000, 2000, 5.0),
            _trade("A", "2026-01-03", 3000, 4000, -3.0),
            _trade("A", "2026-01-04", 5000, 6000, 8.0),
        ],
        "B": [
            _trade("B", "2026-01-02", 1000, 2000, 5.0),
            _trade("B", "2026-01-03", 3000, 4000, -3.0),
            _trade("B", "2026-01-04", 5000, 6000, 8.0),
        ],
    }
    res_same = combine_portfolio(same, {"A": 0.05, "B": 0.05}, 10000.0)
    corr_same = res_same["correlation"]
    assert corr_same[0][1] > 0.999, corr_same
    assert abs(corr_same[0][0] - 1.0) < 1e-9, corr_same  # diagonal
    print(f"[OK] correlation identical pattern -> {corr_same[0][1]} (~1.0)")

    anti = {
        "A": [
            _trade("A", "2026-01-02", 1000, 2000, 5.0),
            _trade("A", "2026-01-03", 3000, 4000, -3.0),
            _trade("A", "2026-01-04", 5000, 6000, 8.0),
        ],
        "B": [
            _trade("B", "2026-01-02", 1000, 2000, -5.0),
            _trade("B", "2026-01-03", 3000, 4000, 3.0),
            _trade("B", "2026-01-04", 5000, 6000, -8.0),
        ],
    }
    res_anti = combine_portfolio(anti, {"A": 0.05, "B": 0.05}, 10000.0)
    corr_anti = res_anti["correlation"]
    assert corr_anti[0][1] < -0.999, corr_anti
    print(f"[OK] correlation anti-correlated -> {corr_anti[0][1]} (~-1.0)")


def test_standalone_uses_same_sizing():
    # Standalone must be combine_portfolio with {k: p_k} (option b), NOT the
    # native risk_r sizing. Verify: standalone equity scales with p_k.
    trades = {"A": [_trade("A", "2026-01-02", 1000, 2000, 10.0)]}
    r5 = combine_portfolio(trades, {"A": 0.05}, 10000.0)
    r10 = combine_portfolio(trades, {"A": 0.10}, 10000.0)
    sa5 = r5["standalone"]["A"]["aggregate_metrics"]["final_equity"]
    sa10 = r10["standalone"]["A"]["aggregate_metrics"]["final_equity"]
    # p_k=0.05 → +50 (10050); p_k=0.10 → +100 (10100)
    assert abs(sa5 - 10050.0) < 1e-6, sa5
    assert abs(sa10 - 10100.0) < 1e-6, sa10
    print(f"[OK] standalone_same_sizing: p=5%->{sa5}, p=10%->{sa10} (scales with p_k)")


def test_recombine_determinism():
    trades = {
        "A": [_trade("A", "2026-01-02", 1000, 2000, 5.0)],
        "B": [_trade("B", "2026-01-03", 3000, 4000, -3.0)],
    }
    w = {"A": 0.05, "B": 0.03}
    r1 = combine_portfolio(trades, w, 10000.0)
    r2 = combine_portfolio(trades, w, 10000.0)
    assert r1["aggregate_metrics"] == r2["aggregate_metrics"]
    print("[OK] recombine determinism: identical results")


if __name__ == "__main__":
    test_basic_sizing()
    test_exposure_cap_scales()
    test_exposure_cap_skips()
    test_cap_never_displaces_across_strategies()
    test_sum_of_curves()
    test_diversification_sign()
    test_standalone_uses_same_sizing()
    test_correlation()
    test_recombine_determinism()
    print("\nALL PORTFOLIO SMOKE TESTS PASSED [OK]")
