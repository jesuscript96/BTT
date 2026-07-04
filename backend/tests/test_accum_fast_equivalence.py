"""
EPIC D — los helpers rápidos de acumulación producen EXACTAMENTE lo mismo que los
originales de backtest_service (que quedan intactos como referencia y para el
path secuencial legacy).
"""
import numpy as np
import pandas as pd

from app.services.backtest_service import _enrich_trades, _extract_equity_from_values
from app.services.backtest_signals import _enrich_trades_arr, _extract_equity_arr


def _mk_ts(n, start="2025-09-03 09:30"):
    return pd.date_range(start, periods=n, freq="1min").values  # datetime64[ns]


def _mk_raw_trades(rng, n_bars, k):
    out = []
    for _ in range(k):
        ei = int(rng.integers(0, n_bars - 1))
        xi = int(rng.integers(ei, n_bars))
        rec = {
            "entry_idx": ei, "exit_idx": xi,
            "entry_price": round(float(rng.uniform(1, 50)), 6),
            "exit_price": round(float(rng.uniform(1, 50)), 6),
            "pnl": round(float(rng.normal(0, 40)), 4),
            "return_pct": round(float(rng.normal(0, 3)), 4),
            "direction": "Short", "status": "Closed",
            "size": round(float(rng.uniform(1, 500)), 6),
            "exit_reason": "SL", "mae": round(float(rng.uniform(0, 5)), 4),
            "stop_loss": round(float(rng.uniform(1, 60)), 6),
        }
        if rng.random() < 0.5:
            rec["fees"] = round(float(rng.uniform(0, 2)), 4)
        if rng.random() < 0.7:
            rec["mfe"] = round(float(rng.uniform(0, 5)), 4)
        out.append(rec)
    # índices fuera de rango (el original los recorta con min())
    out.append({**out[-1], "entry_idx": n_bars + 7, "exit_idx": n_bars + 9})
    return out


def test_enrich_trades_arr_identical():
    rng = np.random.default_rng(11)
    for n_bars in (30, 390):
        ts_dt64 = _mk_ts(n_bars)
        ts_series = pd.Series(ts_dt64)
        ts_epoch = ts_dt64.astype("datetime64[s]").astype("int64")
        raw = _mk_raw_trades(rng, n_bars, 6)
        for risk_unit in (100.0, 0.0, -5.0):
            for gap in (55.5, None):
                ref = _enrich_trades(raw, ts_series, "TK1", "2025-09-03",
                                     {"whatever": 1}, risk_unit, gap_pct=gap)
                fast = _enrich_trades_arr(raw, ts_dt64, ts_epoch, "TK1", "2025-09-03",
                                          risk_unit, gap)
                assert fast == ref


def test_enrich_trades_arr_empty():
    ts = _mk_ts(10)
    assert _enrich_trades_arr([], ts, ts.astype("datetime64[s]").astype("int64"),
                              "T", "2025-01-01", 100.0, None) == []


def test_extract_equity_arr_identical():
    rng = np.random.default_rng(12)
    for n in (0, 5, 199, 200, 201, 900):
        ts_dt64 = _mk_ts(max(n, 1))[:n] if n else np.array([], dtype="datetime64[ns]")
        eq = 10000 + rng.normal(0, 20, n).cumsum() if n else np.array([])
        ts_series = pd.Series(ts_dt64)
        ts_epoch = ts_dt64.astype("datetime64[s]").astype("int64")
        ref = _extract_equity_from_values(np.asarray(eq), ts_series)
        fast = _extract_equity_arr(np.asarray(eq), ts_epoch)
        assert fast == ref, f"n={n}"


def test_extract_equity_arr_len_mismatch():
    """eq_vals más corto/largo que timestamps: mismo comportamiento (min de ambos)."""
    ts_dt64 = _mk_ts(50)
    ts_epoch = ts_dt64.astype("datetime64[s]").astype("int64")
    eq = np.linspace(1, 2, 30)
    ref = _extract_equity_from_values(eq, pd.Series(ts_dt64))
    fast = _extract_equity_arr(eq, ts_epoch)
    assert fast == ref
