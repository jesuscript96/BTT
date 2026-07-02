"""
EPIC B · T-B6 (GATE) — Equivalencia bit a bit: stream legacy vs slab.

Mismo mes sintético servido por:
  (a) path actual: _fetch_and_cache_month → groupby(date,ticker) → _preprocess_pair
  (b) slab: build_month_from_ticker_cache → iter_slab_groups

Se exige: misma secuencia de pares (mismo orden) y, por par, igualdad EXACTA
(np.array_equal) de O/H/L/C/V/ts tras la limpieza. Además, el dict de señales
producido por ambas vías (day_df vs pair_arrays) debe ser idéntico campo a campo.
"""
import numpy as np
import pandas as pd
import pytest

from app.db import gcs_cache, slab_builder, slab_store
from app.services.backtest_signals import _compute_signals_for_pair, _preprocess_pair
from app.services.strategy_engine import compile_strategy_def

STRATEGY = {
    "bias": "short", "apply_day": "gap_day",
    "entry_logic": {"timeframe": "1m", "root_condition": {"operator": "AND", "conditions": [
        {"type": "indicator_comparison", "timeframe": "1m",
         "source": {"name": "Bar Close"}, "comparator": "LESS_THAN", "target": {"name": "VWAP"}},
        {"type": "indicator_comparison", "timeframe": "1m",
         "source": {"name": "Bar Open"}, "comparator": "GREATER_THAN", "target": {"name": "VWAP"}},
    ]}},
    "risk_management": {"use_hard_stop": True, "hard_stop": {"type": "Percentage", "value": 15},
                        "accept_reentries": True, "max_reentries": -1},
}


@pytest.fixture(autouse=True)
def _isolated_dirs(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr(gcs_cache, "LOCAL_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("BTT_SLAB_DIR", str(tmp_path / "slabs"))
    slab_store._OPEN_SLABS.clear()
    with gcs_cache._MONTH_CACHE_LOCK:
        gcs_cache._MONTH_CACHE.clear()
        gcs_cache._MONTH_CACHE_SIZES.clear()
    yield
    slab_store._OPEN_SLABS.clear()


def _mk_day(ticker, date, n=420, seed=0, dups=False, disorder=False):
    """Día 04:00→(04:00+n min). Con n=420 llega a 11:00 (incluye RTH)."""
    rng = np.random.default_rng(seed)
    ts = pd.date_range(f"{date} 04:00", periods=n, freq="1min")
    # paseo aleatorio (sube y baja) + ruido open/close amplio → velas rojas y verdes
    # cruzando VWAP en ambos sentidos (la estrategia SHORT necesita open>VWAP>close)
    close = 8.0 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    open_ = close * np.exp(rng.normal(0, 0.004, n))
    df = pd.DataFrame({
        "ticker": ticker, "date": date, "timestamp": ts,
        "open": open_,
        "high": np.maximum(open_, close) * 1.004,
        "low": np.minimum(open_, close) * 0.996,
        "close": close,
        "volume": rng.integers(100, 50000, n),
    })
    if dups:
        df = pd.concat([df, df.iloc[30:35]], ignore_index=True)
    if disorder:
        idx = np.arange(len(df))
        w = idx[50:90].copy()
        rng.shuffle(w)
        idx[50:90] = w
        df = df.iloc[idx].reset_index(drop=True)
    return df


def _build_month(y=2025, m=9, n_tickers=8):
    days = ["2025-09-01", "2025-09-02", "2025-09-03", "2025-09-04"]
    qual_rows = []
    for i in range(n_tickers):
        tk = f"TK{i:02d}"
        frames = []
        for j, d in enumerate(days):
            frames.append(_mk_day(tk, d, seed=i * 10 + j,
                                  dups=(i % 3 == 0), disorder=(i % 4 == 1)))
        month = pd.concat(frames, ignore_index=True)
        month = gcs_cache._downcast_intraday(month)
        gcs_cache._atomic_write_parquet(month, gcs_cache._ticker_cache_path(y, m, "opt", tk))
        for d in days[:2]:
            qual_rows.append({"ticker": tk, "date": d, "prev_close": 8.0,
                              "gap_pct": 55.0, "yesterday_open": 7.5, "lag_rth_open_1": 7.5})
    return pd.DataFrame(qual_rows)


def _legacy_pairs(qualifying, y=2025, m=9):
    qlk = {(r["ticker"], r["date"]): r for r in qualifying.to_dict("records")}
    vp = qualifying[["ticker", "date"]].drop_duplicates().copy()
    df_month = gcs_cache._fetch_and_cache_month(
        y, m, "local/intraday_1m_optimized", vp, batch_size=500, mi=1, n_months=1)
    out = []
    for (date, ticker), day_df in df_month.groupby(["date", "ticker"], observed=True):
        pre = _preprocess_pair(date, ticker, day_df, qlk, STRATEGY, {})
        if pre is not None:
            out.append(pre)
    return out, qlk


def _slab_pairs(qualifying, qlk, y=2025, m=9):
    slab_builder.build_month_from_ticker_cache(y, m, "opt")
    return list(slab_store.iter_slab_groups(qualifying, [(y, m)], STRATEGY, qlk))


def test_stream_equivalence_bit_exact():
    qualifying = _build_month()
    legacy, qlk = _legacy_pairs(qualifying)
    slab = _slab_pairs(qualifying, qlk)

    assert len(legacy) == len(slab) > 0
    for (l_date, l_tk, l_df, _), (s_date, s_tk, _, arrs) in zip(legacy, slab):
        assert (l_date, l_tk) == (s_date, s_tk), "orden de emisión distinto"
        # igualdad EXACTA tras limpieza (float32→float64 es determinista en ambos)
        np.testing.assert_array_equal(
            np.asarray(l_df["open"], dtype=np.float64), arrs.open, err_msg=f"open {l_tk} {l_date}")
        np.testing.assert_array_equal(
            np.asarray(l_df["high"], dtype=np.float64), arrs.high)
        np.testing.assert_array_equal(
            np.asarray(l_df["low"], dtype=np.float64), arrs.low)
        np.testing.assert_array_equal(
            np.asarray(l_df["close"], dtype=np.float64), arrs.close)
        np.testing.assert_array_equal(
            np.asarray(l_df["volume"], dtype=np.float64), arrs.volume)
        np.testing.assert_array_equal(
            pd.to_datetime(l_df["timestamp"]).values.astype(np.int64), arrs.ts_ns)


def _signals_equal(a, b):
    assert (a is None) == (b is None)
    if a is None:
        return
    scalar_keys = ["date", "ticker", "sig_direction", "sig_accept_reentries",
                   "sig_max_reentries", "sig_sl_stop", "sig_sl_trail", "sig_tp_stop",
                   "sig_tp_time_limit", "sig_trail_pct", "sig_partial_tps", "gap_pct"]
    for k in scalar_keys:
        assert a[k] == b[k], f"clave {k}: {a[k]!r} != {b[k]!r}"
    np.testing.assert_array_equal(a["entries_arr"], b["entries_arr"])
    np.testing.assert_array_equal(a["exits_arr"], b["exits_arr"])
    np.testing.assert_array_equal(a["patch_mask"], b["patch_mask"])
    np.testing.assert_array_equal(a["timestamps_arr"], b["timestamps_arr"])
    for k in ["open", "high", "low", "close", "volume", "hod", "lod",
              "pm_high", "pm_low", "prev_high", "prev_low"]:
        np.testing.assert_array_equal(
            np.asarray(a["arrays"][k], dtype=np.float64),
            np.asarray(b["arrays"][k], dtype=np.float64), err_msg=f"arrays[{k}]")
    np.testing.assert_array_equal(
        np.asarray(a["arrays"]["timestamp"], dtype="datetime64[ns]"),
        np.asarray(b["arrays"]["timestamp"], dtype="datetime64[ns]"))


@pytest.mark.parametrize("sessions", [["rth"], ["pre", "rth"], ["all"]])
def test_signals_equivalence_daydf_vs_pair_arrays(sessions):
    qualifying = _build_month()
    legacy, qlk = _legacy_pairs(qualifying)
    slab = _slab_pairs(qualifying, qlk)
    compiled = compile_strategy_def(STRATEGY)

    n_signals = 0
    for (l_date, l_tk, l_df, l_stats), (_, _, s_stats, arrs) in zip(legacy, slab):
        r_legacy = _compute_signals_for_pair(
            l_date, l_tk, l_df, l_stats, STRATEGY, compiled, sessions, None, None, False)
        r_slab = _compute_signals_for_pair(
            l_date, l_tk, None, s_stats, STRATEGY, compiled, sessions, None, None, False,
            pair_arrays=arrs)
        _signals_equal(r_legacy, r_slab)
        if r_legacy is not None:
            n_signals += 1
    assert n_signals > 0, "el test no ejercitó ningún par con señales"


def test_signals_equivalence_legacy_translate_path():
    """Sin _indicator_plan (path legacy con mini_df): también debe ser idéntico."""
    qualifying = _build_month(n_tickers=4)
    legacy, qlk = _legacy_pairs(qualifying)
    slab = _slab_pairs(qualifying, qlk)
    compiled = compile_strategy_def(STRATEGY)
    no_plan = {k: v for k, v in compiled.items() if k != "_indicator_plan"}

    checked = 0
    for (l_date, l_tk, l_df, l_stats), (_, _, s_stats, arrs) in zip(legacy, slab):
        r_legacy = _compute_signals_for_pair(
            l_date, l_tk, l_df, l_stats, STRATEGY, no_plan, ["rth"], None, None, False)
        r_slab = _compute_signals_for_pair(
            l_date, l_tk, None, s_stats, STRATEGY, no_plan, ["rth"], None, None, False,
            pair_arrays=arrs)
        _signals_equal(r_legacy, r_slab)
        checked += 1
    assert checked > 0
