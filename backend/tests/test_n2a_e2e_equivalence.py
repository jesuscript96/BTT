"""E2E N2a: run_backtest completo con BTT_N2A_NATIVE_ENABLED=1 vs legacy.

Complementa test_n2a_native_equivalence.py (nivel translate) validando el
pipeline entero: slab stream -> _compute_signals_for_pair (fast path nativo)
-> simulate_and_accumulate. Resultado EXACTO (dicts enteros ==) contra el run
legacy con el flag OFF. Incluye el caso gated (indicador no nativo) que debe
caer al legacy dentro del worker y dar lo mismo.

Fixture sintético idéntico en construcción al de
test_run_backtest_slab_equivalence.py (offline, sin GCS).
"""
import numpy as np
import pandas as pd
import pytest

from app.db import gcs_cache, slab_builder, slab_store
from app.services.backtest_service import run_backtest
from app.services.strategy_engine import compile_strategy_def

# Estrategia nativa-elegible que ejercita: comparaciones 1m, indicador de sesión
# causal (PM High Gap), condición en tf 5m (resample+closed-bar), CROSSES y
# ventana horaria.
STRATEGY_NATIVE = {
    "bias": "short", "apply_day": "gap_day",
    "entry_logic": {
        "timeframe": "1m",
        "root_condition": {"operator": "AND", "conditions": [
            {"type": "indicator_comparison", "timeframe": "1m",
             "source": {"name": "Bar Close"}, "comparator": "LESS_THAN", "target": {"name": "VWAP"}},
            {"type": "indicator_comparison", "timeframe": "1m",
             "source": {"name": "Bar Open"}, "comparator": "GREATER_THAN", "target": {"name": "VWAP"}},
            {"type": "indicator_comparison", "timeframe": "1m",
             "source": {"name": "PM High Gap (%)"}, "comparator": "GREATER_THAN", "target": -50},
            {"type": "indicator_comparison", "timeframe": "5m",
             "source": {"name": "RSI", "period": 7}, "comparator": "LESS_THAN", "target": 100},
        ]},
        "entry_time_windows": [{"from_time": "04:30", "to_time": "15:30"}],
    },
    "exit_logic": {
        "timeframe": "1m",
        "root_condition": {"operator": "AND", "conditions": [
            {"type": "indicator_comparison", "timeframe": "1m",
             "source": {"name": "Close"}, "comparator": "CROSSES_ABOVE", "target": {"name": "VWAP"}},
        ]},
    },
    "risk_management": {"use_hard_stop": True, "hard_stop": {"type": "Percentage", "value": 15},
                        "accept_reentries": True, "max_reentries": -1},
}

# Igual pero con un indicador NO nativo: el gate debe mandarla al legacy
# dentro del worker (resultado idéntico, sin 0-trades silencioso).
STRATEGY_GATED = {
    "bias": "short", "apply_day": "gap_day",
    "entry_logic": {
        "timeframe": "1m",
        "root_condition": {"operator": "AND", "conditions": [
            {"type": "indicator_comparison", "timeframe": "1m",
             "source": {"name": "Bar Close"}, "comparator": "LESS_THAN", "target": {"name": "VWAP"}},
            {"type": "indicator_comparison", "timeframe": "1m",
             "source": {"name": "Williams %R", "period": 14}, "comparator": "LESS_THAN", "target": 0},
        ]},
    },
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
    monkeypatch.delenv("BTT_N2A_NATIVE_ENABLED", raising=False)
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


def _month_stream(qualifying, y=2025, m=9):
    vp = qualifying[["ticker", "date"]].drop_duplicates().copy()
    df_month = gcs_cache._fetch_and_cache_month(
        y, m, "local/intraday_1m_optimized", vp, batch_size=500, mi=1, n_months=1)
    yield from df_month.groupby(["date", "ticker"], observed=True)


def _run(qualifying, strategy, use_stream=True):
    return run_backtest(
        qualifying_df=qualifying.copy(), strategy_def=strategy,
        init_cash=10000.0, risk_r=100.0, risk_type="FIXED",
        market_sessions=["pre", "rth"],
        day_group_iter=_month_stream(qualifying) if use_stream else iter(()),
        n_groups_hint=len(qualifying),
    )


def _assert_results_equal(a, b):
    assert a["aggregate_metrics"] == b["aggregate_metrics"]
    assert a["trades"] == b["trades"]
    assert a["day_results"] == b["day_results"]
    assert a["equity_curves"] == b["equity_curves"]
    assert a["global_equity"] == b["global_equity"]
    assert a["global_drawdown"] == b["global_drawdown"]


def test_n2a_on_igual_a_legacy_e2e(monkeypatch):
    assert not compile_strategy_def(STRATEGY_NATIVE)["_indicator_plan"]["has_special"], \
        "STRATEGY_NATIVE debe ser nativa-elegible (si no, el test no ejercita N2a)"
    qualifying = _setup_month()

    res_legacy = _run(qualifying, STRATEGY_NATIVE)
    assert len(res_legacy["trades"]) > 0, "el fixture debe producir trades"

    slab_builder.build_month_from_ticker_cache(2025, 9, "opt")
    monkeypatch.setenv("BTT_SLAB_STREAM_ENABLED", "1")

    # slab + N2A OFF (sanity: el slab en sí ya es equivalente)
    res_slab_off = _run(qualifying, STRATEGY_NATIVE, use_stream=False)
    _assert_results_equal(res_legacy, res_slab_off)

    # slab + N2A ON: el fast path nativo produce EXACTAMENTE lo mismo
    monkeypatch.setenv("BTT_N2A_NATIVE_ENABLED", "1")
    res_n2a = _run(qualifying, STRATEGY_NATIVE, use_stream=False)
    _assert_results_equal(res_legacy, res_n2a)


def test_n2a_on_estrategia_gated_cae_a_legacy_e2e(monkeypatch):
    assert compile_strategy_def(STRATEGY_GATED)["_indicator_plan"]["has_special"], \
        "STRATEGY_GATED debe gatear (Williams %R no es nativo)"
    qualifying = _setup_month()

    res_legacy = _run(qualifying, STRATEGY_GATED)
    assert len(res_legacy["trades"]) > 0, "el fixture debe producir trades"

    slab_builder.build_month_from_ticker_cache(2025, 9, "opt")
    monkeypatch.setenv("BTT_SLAB_STREAM_ENABLED", "1")
    monkeypatch.setenv("BTT_N2A_NATIVE_ENABLED", "1")
    res_gated = _run(qualifying, STRATEGY_GATED, use_stream=False)
    _assert_results_equal(res_legacy, res_gated)
