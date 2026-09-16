# -*- coding: utf-8 -*-
"""El stop por ATR pasando por `run_backtest` ENTERO: el ATR es el del DIA
ENTERO (desde la primera vela del premercado), recortado con la sesion, y NO
el que saldria recalculando sobre los arrays ya recortados.

Jaume, 16-sep-2026: «tiene que coger todas las velas desde el inicio de
premarket, independientemente de la sesion». Ninguna de las dos versiones
mira el futuro (las 14 velas ANTERIORES en las dos); la diferencia es que con
sesion RTH el recorte previo dejaba las 14 primeras velas (09:30-09:43) sin
ATR — sin respaldo, sin entrar — mientras el bot, con el mismo frame de
market_frame, si lo tenia. Ahora backtest y bot van por la misma columna.

Montaje del mes sintetico copiado de `test_stop_vwap_run_backtest.py`.
"""
import numpy as np
import pandas as pd
import pytest

from app.db import gcs_cache, slab_builder, slab_store
from app.services.backtest_service import run_backtest
from app.services.indicators import _atr
from app.services.portfolio_sim import ATR_PERIODO_STOP

K_ATR = 2.0

# Corto que entra cuando el cierre esta por debajo del VWAP (senal frecuente,
# tambien en las primeras velas de RTH), stop = entrada + 2 x ATR de la vela
# de la senal. SIN respaldo: sin ATR no se entra, asi la diferencia se ve en
# el numero de trades y no solo en el nivel.
STRATEGY = {
    "name": "stop atr", "bias": "short", "apply_day": "gap_day",
    "entry_logic": {"timeframe": "1m", "root_condition": {"operator": "AND", "conditions": [
        {"type": "indicator_comparison", "timeframe": "1m",
         "source": {"name": "Bar Close"}, "comparator": "LESS_THAN", "target": {"name": "VWAP"}},
    ]}},
    "risk_management": {
        "use_hard_stop": True,
        "hard_stop": {"type": "ATR Multiplier", "value": K_ATR},
        "accept_reentries": True, "max_reentries": -1,
    },
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


_DAYS = ["2025-09-01", "2025-09-02", "2025-09-03"]


def _setup_month(n_tickers=4, y=2025, m=9):
    qual_rows, dias = [], {}
    for i in range(n_tickers):
        tk = f"TK{i:02d}"
        partes = [_mk_day(tk, d, seed=i * 10 + j) for j, d in enumerate(_DAYS)]
        for d, p in zip(_DAYS, partes):
            dias[(tk, d)] = p
        month = pd.concat(partes, ignore_index=True)
        month = gcs_cache._downcast_intraday(month)
        gcs_cache._atomic_write_parquet(month, gcs_cache._ticker_cache_path(y, m, "opt", tk))
        for d in _DAYS[:2]:
            qual_rows.append({"ticker": tk, "date": d, "prev_close": 8.0, "gap_pct": 60.0,
                              "yesterday_open": 7.7, "lag_rth_open_1": 7.7})
    return pd.DataFrame(qual_rows), dias


def _stream(qualifying, y=2025, m=9):
    vp = qualifying[["ticker", "date"]].drop_duplicates().copy()
    df_month = gcs_cache._fetch_and_cache_month(
        y, m, "local/intraday_1m_optimized", vp, batch_size=500, mi=1, n_months=1)
    for key, day_df in df_month.groupby(["date", "ticker"], observed=True):
        yield key, day_df


def _run(qualifying, stream=None):
    return run_backtest(
        qualifying_df=qualifying.copy(), strategy_def=STRATEGY,
        init_cash=10000.0, risk_r=100.0, risk_type="FIXED",
        market_sessions=["rth"],
        day_group_iter=iter(stream) if stream is not None else iter(()),
        n_groups_hint=len(qualifying),
    )


def _atr_del_dia(day_df, desde=None):
    """ATR por vela del dia (o desde una hora), indexado por timestamp. Con
    los MISMOS float32 que guarda la cache, para comparar exacto."""
    d = gcs_cache._downcast_intraday(day_df.copy())
    if desde is not None:
        d = d[pd.to_datetime(d["timestamp"]).dt.strftime("%H:%M") >= desde]
    vals = _atr(d["high"].values.astype(np.float64), d["low"].values.astype(np.float64),
                d["close"].values.astype(np.float64), ATR_PERIODO_STOP)
    return pd.Series(vals, index=pd.to_datetime(d["timestamp"]).values)


def test_el_stop_es_el_atr_del_dia_entero_y_entra_en_las_primeras_velas_de_rth():
    qualifying, dias = _setup_month()
    res = _run(qualifying, _stream(qualifying))
    trades = res["trades"]
    assert len(trades) > 0, "el fixture debe producir trades"

    comprobados = 0
    tempranas = 0
    for t in trades:
        day_df = dias[(t["ticker"], t["date"])]
        completo = _atr_del_dia(day_df)
        solo_rth = _atr_del_dia(day_df, desde="09:30")
        # El nivel se resuelve con el ATR de la vela de la SENAL (la ultima
        # cerrada); la entrada se rellena en la siguiente (`entry_time`), como
        # con el VWAP o el HOD: el stop es el ATR que se veia al decidir entrar.
        ts_entrada = pd.Timestamp(t["entry_time"]) - pd.Timedelta(minutes=1)
        if ts_entrada not in completo.index:
            continue
        a_completo = float(completo.loc[ts_entrada])
        assert a_completo > 0
        esperado = t["entry_price"] + K_ATR * a_completo
        assert t["stop_loss"] == pytest.approx(esperado, rel=1e-6), (t["ticker"], t["date"], t["entry_time"])
        # y NO es el ATR que arrancaria a las 09:30: en las 14 primeras velas
        # de RTH ese ni existe (NaN) y antes del cambio no se entraba.
        a_rth = float(solo_rth.loc[ts_entrada])
        if np.isnan(a_rth):
            tempranas += 1
        else:
            assert abs(a_rth - a_completo) > 1e-9 or ts_entrada.strftime("%H:%M") > "10:30"
        assert t["stop_loss"] > t["entry_price"]
        comprobados += 1
    assert comprobados > 0
    # Lo que demuestra el cambio: hay entradas entre 09:30 y 09:43 con stop.
    assert tempranas > 0, "el fixture debe entrar en las 14 primeras velas de RTH"


def test_los_tres_caminos_y_el_jit_dan_lo_mismo(monkeypatch):
    qualifying, _ = _setup_month()
    res_seq = _run(qualifying, _stream(qualifying))
    assert len(res_seq["trades"]) > 0

    slab_builder.build_month_from_ticker_cache(2025, 9, "opt")
    monkeypatch.setenv("BTT_SLAB_STREAM_ENABLED", "1")
    res_slab = _run(qualifying)
    assert res_slab["trades"] == res_seq["trades"]

    monkeypatch.setenv("BACKTEST_PARALLEL_WORKERS", "2")
    res_pool = _run(qualifying)
    assert res_pool["trades"] == res_seq["trades"]
    monkeypatch.delenv("BACKTEST_PARALLEL_WORKERS", raising=False)

    monkeypatch.setenv("BACKTEST_NUMBA_SIM", "1")
    res_jit = _run(qualifying)
    assert len(res_jit["trades"]) == len(res_seq["trades"])
    for a, b in zip(res_jit["trades"], res_seq["trades"]):
        for campo in ("ticker", "date", "entry_time", "exit_time"):
            assert a[campo] == b[campo], campo
        for campo in ("stop_loss", "size", "entry_price", "exit_price", "pnl"):
            assert a[campo] == pytest.approx(b[campo], rel=1e-9), campo
