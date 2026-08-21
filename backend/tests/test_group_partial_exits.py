"""PRD_03 — _group_partial_exits: agrupar ejecuciones de una posición en 1 trade.

Verifica lo que pide el PRD:
- Identidad: sin parciales (entry_idx distintos) las métricas por-trade no cambian.
- Con parciales (mismo entry_idx consecutivo): 1 trade; pnl == Σ pnl de las legs;
  n_executions y legs correctos; exit_* de la última ejecución.
"""
from __future__ import annotations

from app.services.backtest_service import _group_partial_exits


def _exec(entry_idx, pnl, size, *, exit_idx=None, exit_price=100.0,
          exit_reason="EOD", exit_time="t", r_multiple=1.0,
          ticker="TK00", date="2025-09-01"):
    """Un registro de ejecución con las claves que produce _enrich_trades."""
    return {
        "ticker": ticker,
        "date": date,
        "entry_idx": entry_idx,
        "exit_idx": exit_idx if exit_idx is not None else entry_idx + 1,
        "entry_price": 100.0,
        "exit_price": exit_price,
        "exit_time": exit_time,
        "exit_time_epoch": 1000,
        "exit_reason": exit_reason,
        "pnl": pnl,
        "fees": 0.0,
        "size": size,
        "r_multiple": r_multiple,
        "mae": 0.0,
        "mfe": 0.0,
        "return_pct": 0.0,
    }


def test_lt2_returns_as_is():
    assert _group_partial_exits([]) == []
    one = [_exec(5, 100.0, 10)]
    assert _group_partial_exits(one) == one  # sin cambios (ni legs)


def test_two_positions_distinct_entry_idx_stay_separate():
    # Dos posiciones (1 ejecución cada una) → siguen siendo 2 trades.
    recs = [_exec(5, 100.0, 10, exit_reason="TP"), _exec(9, -30.0, 8, exit_reason="SL")]
    out = _group_partial_exits(recs)
    assert len(out) == 2
    # Métricas por-trade intactas (identidad): pnl/size sin tocar.
    assert out[0]["pnl"] == 100.0 and out[0]["size"] == 10
    assert out[1]["pnl"] == -30.0 and out[1]["size"] == 8
    assert out[0]["exit_reason"] == "TP" and out[1]["exit_reason"] == "SL"
    # single-path: recibe su leg única pero NO añade n_executions (no es agregado).
    assert "n_executions" not in out[0]
    assert out[0]["legs"][0]["pnl"] == 100.0


def test_partials_grouped_into_one_trade():
    # Parcial (idx 5) + cierre final (idx 5) → 1 trade.
    recs = [
        _exec(5, 600.0, 300, exit_reason="Partial TP", exit_price=102.0, exit_time="t1"),
        _exec(5, 1400.0, 700, exit_reason="EOD", exit_price=102.0, exit_time="t2"),
    ]
    out = _group_partial_exits(recs)
    assert len(out) == 1
    trade = out[0]
    assert trade["n_executions"] == 2
    assert trade["pnl"] == 2000.0                 # Σ pnl de las legs
    assert trade["size"] == 1000                  # Σ size
    assert trade["exit_reason"] == "EOD"          # de la última ejecución
    assert trade["exit_time"] == "t2"
    assert trade["exit_reasons"] == ["Partial TP", "EOD"]
    assert len(trade["legs"]) == 2
    assert sum(leg["pnl"] for leg in trade["legs"]) == trade["pnl"]  # pnl == Σ legs


def test_mixed_partial_then_separate_position():
    # [A(idx5,parcial), B(idx5,cierre), C(idx7)] → 2 trades: {A,B} y {C}.
    recs = [
        _exec(5, 100.0, 300, exit_reason="Partial TP"),
        _exec(5, 200.0, 700, exit_reason="EOD"),
        _exec(7, -50.0, 500, exit_reason="SL"),
    ]
    out = _group_partial_exits(recs)
    assert len(out) == 2
    assert out[0]["n_executions"] == 2 and out[0]["pnl"] == 300.0
    assert out[1]["pnl"] == -50.0 and out[1]["exit_reason"] == "SL"


def test_same_entry_idx_different_day_not_merged():
    # Clave compuesta: mismo entry_idx pero (ticker,date) distintos → NO se fusionan.
    recs = [
        _exec(5, 100.0, 10, date="2025-09-01"),
        _exec(5, 200.0, 10, date="2025-09-02"),
    ]
    out = _group_partial_exits(recs)
    assert len(out) == 2
    assert out[0]["pnl"] == 100.0 and out[1]["pnl"] == 200.0
    # Mismo día pero distinto ticker tampoco.
    recs2 = [_exec(5, 1.0, 10, ticker="AAA"), _exec(5, 2.0, 10, ticker="BBB")]
    assert len(_group_partial_exits(recs2)) == 2


def test_total_trades_equals_positions_and_pnl_sums():
    # 2 posiciones: una con 3 ejecuciones (2 parciales + cierre), otra simple.
    recs = [
        _exec(3, 10.0, 100, exit_reason="Partial TP"),
        _exec(3, 20.0, 100, exit_reason="Partial TP"),
        _exec(3, 30.0, 100, exit_reason="EOD"),
        _exec(8, -5.0, 50, exit_reason="SL"),
    ]
    out = _group_partial_exits(recs)
    assert len(out) == 2                          # total_trades == nº posiciones
    assert out[0]["n_executions"] == 3
    assert out[0]["pnl"] == 60.0                  # 10+20+30
    assert out[0]["size"] == 300
