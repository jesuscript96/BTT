"""
EPIC E (GATE) — run_backtest completo: path legacy vs modo slab, resultados idénticos.

Compara el dict de resultado ENTERO (aggregate_metrics, trades, day_results,
equity_curves, global_equity, global_drawdown) entre:
  (a) flag OFF + stream legacy (generator groupby como el del orchestrator)
  (b) flag ON  + slabs construidos (inline, 1 worker)
  (c) flag ON  + pool forkserver (2 workers)
Además verifica que en modo slab el stream legacy NO se consume (lazy).
"""
import numpy as np
import pandas as pd
import pytest

from app.db import gcs_cache, slab_builder, slab_store
from app.services.backtest_service import run_backtest

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
def _isolated(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr(gcs_cache, "LOCAL_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("BTT_SLAB_DIR", str(tmp_path / "slabs"))
    monkeypatch.delenv("BTT_SLAB_STREAM_ENABLED", raising=False)
    monkeypatch.delenv("BACKTEST_PARALLEL_WORKERS", raising=False)
    monkeypatch.setenv("BACKTEST_NUMBA_SIM", "0")
    slab_store._OPEN_SLABS.clear()
    with gcs_cache._MONTH_CACHE_LOCK:
        gcs_cache._MONTH_CACHE.clear()
        gcs_cache._MONTH_CACHE_SIZES.clear()
    yield
    slab_store._OPEN_SLABS.clear()


def _mk_day(ticker, date, n=420, seed=0):
    rng = np.random.default_rng(seed)
    ts = pd.date_range(f"{date} 04:00", periods=n, freq="1min")
    close = 8.0 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    open_ = close * np.exp(rng.normal(0, 0.004, n))
    return pd.DataFrame({
        "ticker": ticker, "date": date, "timestamp": ts,
        "open": open_, "high": np.maximum(open_, close) * 1.004,
        "low": np.minimum(open_, close) * 0.996, "close": close,
        "volume": rng.integers(100, 50000, n),
    })


def _setup_month(n_tickers=6, y=2025, m=9):
    days = ["2025-09-01", "2025-09-02", "2025-09-03"]
    qual_rows = []
    for i in range(n_tickers):
        tk = f"TK{i:02d}"
        month = pd.concat([_mk_day(tk, d, seed=i * 10 + j) for j, d in enumerate(days)],
                          ignore_index=True)
        month = gcs_cache._downcast_intraday(month)
        gcs_cache._atomic_write_parquet(month, gcs_cache._ticker_cache_path(y, m, "opt", tk))
        for d in days[:2]:
            qual_rows.append({"ticker": tk, "date": d, "prev_close": 8.0, "gap_pct": 60.0,
                              "yesterday_open": 7.7, "lag_rth_open_1": 7.7})
    return pd.DataFrame(qual_rows)


class _CountingStream:
    """Generator wrapper que cuenta cuántos grupos se consumieron."""

    def __init__(self, qualifying, y=2025, m=9):
        self.consumed = 0
        self._qual = qualifying
        self._ym = (y, m)

    def __iter__(self):
        y, m = self._ym
        vp = self._qual[["ticker", "date"]].drop_duplicates().copy()
        df_month = gcs_cache._fetch_and_cache_month(
            y, m, "local/intraday_1m_optimized", vp, batch_size=500, mi=1, n_months=1)
        for key, day_df in df_month.groupby(["date", "ticker"], observed=True):
            self.consumed += 1
            yield key, day_df


def _run(qualifying, stream=None):
    return run_backtest(
        qualifying_df=qualifying.copy(), strategy_def=STRATEGY,
        init_cash=10000.0, risk_r=100.0, risk_type="FIXED",
        market_sessions=["rth"],
        day_group_iter=iter(stream) if stream is not None else iter(()),
        n_groups_hint=len(qualifying),
    )


def _assert_results_equal(a, b):
    assert a["aggregate_metrics"] == b["aggregate_metrics"]
    assert a["trades"] == b["trades"]
    assert a["day_results"] == b["day_results"]
    assert a["equity_curves"] == b["equity_curves"]
    assert a["global_equity"] == b["global_equity"]
    assert a["global_drawdown"] == b["global_drawdown"]


def test_run_backtest_slab_equals_legacy(monkeypatch):
    qualifying = _setup_month()

    # (a) legacy
    stream = _CountingStream(qualifying)
    res_legacy = _run(qualifying, stream)
    assert stream.consumed > 0
    assert len(res_legacy["trades"]) > 0, "el fixture debe producir trades"

    # (b) slab inline
    slab_builder.build_month_from_ticker_cache(2025, 9, "opt")
    monkeypatch.setenv("BTT_SLAB_STREAM_ENABLED", "1")
    stream2 = _CountingStream(qualifying)
    res_slab = _run(qualifying, stream2)
    assert stream2.consumed == 0, "en modo slab el stream legacy NO debe consumirse"
    _assert_results_equal(res_legacy, res_slab)


def test_run_backtest_slab_fallback_month_without_slab(monkeypatch):
    """Mes sin slab: el modo slab cae al path legacy por-mes y sigue idéntico."""
    qualifying = _setup_month()
    res_legacy = _run(qualifying, _CountingStream(qualifying))

    monkeypatch.setenv("BTT_SLAB_STREAM_ENABLED", "1")  # sin construir slabs
    res_slab_fb = _run(qualifying, _CountingStream(qualifying))
    _assert_results_equal(res_legacy, res_slab_fb)


def test_run_backtest_slab_with_workers(monkeypatch):
    """Pool forkserver (2 workers) con refs mmap: idéntico al inline."""
    qualifying = _setup_month()
    slab_builder.build_month_from_ticker_cache(2025, 9, "opt")
    monkeypatch.setenv("BTT_SLAB_STREAM_ENABLED", "1")

    res_inline = _run(qualifying)
    monkeypatch.setenv("BACKTEST_PARALLEL_WORKERS", "2")
    res_pool = _run(qualifying)
    _assert_results_equal(res_inline, res_pool)
    assert len(res_pool["trades"]) > 0


def test_run_backtest_slab_with_jit(monkeypatch):
    """Slab + kernel Numba: resultado completo idéntico al legacy puro."""
    qualifying = _setup_month()
    res_legacy = _run(qualifying, _CountingStream(qualifying))

    slab_builder.build_month_from_ticker_cache(2025, 9, "opt")
    monkeypatch.setenv("BTT_SLAB_STREAM_ENABLED", "1")
    monkeypatch.setenv("BACKTEST_NUMBA_SIM", "1")
    res_full = _run(qualifying)
    _assert_results_equal(res_legacy, res_full)
