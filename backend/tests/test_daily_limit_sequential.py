"""El cortacircuitos diario TAMBIEN en el camino secuencial de run_backtest.

Regresion de un bug real (2026-08-24): el limite estaba implementado solo en
`simulate_and_accumulate` (caminos SLAB y PARALLEL). El bucle secuencial de
`run_backtest` llama a `simulate()` directamente, y es el que corre por defecto
sin BTT_SLAB_STREAM_ENABLED ni BACKTEST_PARALLEL_WORKERS — asi que el ajuste no
hacia absolutamente nada y el usuario veia resultados identicos con y sin el.

Mismo patron que la piramidacion (MEMORIA §10.2): la funcionalidad vive en un
camino y el usuario corre por otro.
"""
import numpy as np
import pandas as pd
import pytest

from app.db import gcs_cache, slab_store
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
    # Se BORRAN a proposito: asi corre el camino SECUENCIAL, que es el que
    # tenia el bug y el que usa la maquina del usuario.
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


def _datos(n_tickers=6):
    days = ["2025-09-01", "2025-09-02", "2025-09-03"]
    qual_rows, trozos = [], []
    for i in range(n_tickers):
        tk = f"TK{i:02d}"
        for j, d in enumerate(days):
            trozos.append(_mk_day(tk, d, seed=i * 10 + j))
        for d in days[:2]:
            qual_rows.append({"ticker": tk, "date": d, "prev_close": 8.0, "gap_pct": 60.0,
                              "yesterday_open": 7.7, "lag_rth_open_1": 7.7})
    return pd.DataFrame(qual_rows), pd.concat(trozos, ignore_index=True)


def _corre(tope, stop_pct=15):
    """`stop_pct` bajo escalona las salidas: sin eso todo cierra a EOD y el
    corte no tiene nada que recortar (ver el test de abajo)."""
    qual, intraday = _datos()
    rm = dict(STRATEGY["risk_management"])
    rm["hard_stop"] = {"type": "Percentage", "value": stop_pct}
    if tope is not None:
        rm["daily_loss_limit"] = tope
    sd = {**STRATEGY, "risk_management": rm}
    return run_backtest(
        qualifying_df=qual, intraday_df=intraday, strategy_def=sd,
        init_cash=10000.0, risk_r=100.0, risk_type="FIXED",
        market_sessions=["rth"],
        day_group_iter=None, n_groups_hint=None,
    )


def _resumen(r):
    tr = r.get("trades", [])
    return len(tr), round(sum(t.get("pnl", 0.0) for t in tr), 4)


def test_el_camino_secuencial_genera_trades():
    """Guardia del propio test: sin trades no probaria nada."""
    n, _ = _resumen(_corre(None))
    assert n > 0, "el fixture debe producir trades o el test es vacio"


def test_el_tope_recorta_operaciones_en_el_secuencial():
    """EL BUG: antes salia exactamente igual con y sin el tope.

    Con `stop_pct=1` las salidas quedan escalonadas (10:05, 10:18, 10:59), asi
    que hay entradas POSTERIORES al corte y el tope tiene algo que recortar.
    """
    base = _corre(None, stop_pct=1)
    n_base, pnl_base = _resumen(base)

    con = _corre({"enabled": True, "unit": "CASH", "value": 1.0,
                  "on_open_positions": "CLOSE_ALL"}, stop_pct=1)
    n_con, pnl_con = _resumen(con)

    assert (n_con, pnl_con) != (n_base, pnl_base), (
        f"el tope no cambio nada: base={n_base} trades/{pnl_base}$, "
        f"con tope={n_con} trades/{pnl_con}$"
    )
    assert n_con <= n_base, "el tope solo puede quitar operaciones, nunca añadir"
    assert base.get("daily_limit_log") == []
    assert len(con.get("daily_limit_log") or []) > 0, "debe registrar las sesiones cortadas"


def test_el_tope_se_EJECUTA_aunque_todo_cierre_a_EOD():
    """El mecanismo corre en el secuencial aunque no pueda recortar nada.

    Con el stop por defecto todas las posiciones cierran a la vez (EOD), asi que
    no queda nada abierto que cortar ni entradas posteriores: los trades no
    cambian. Pero la bitacora SI se rellena — y antes del fix estaba vacia
    porque el camino secuencial ni miraba el tope.
    """
    con = _corre({"enabled": True, "unit": "CASH", "value": 1.0,
                  "on_open_positions": "CLOSE_ALL"})
    log = con.get("daily_limit_log") or []
    assert len(log) > 0, "el camino secuencial debe evaluar el tope"
    # Se paso del tope dentro de una sola tanda de cierres simultaneos.
    assert any(e["overshoot"] > 0 for e in log)


def test_apagado_es_identico_a_no_ponerlo():
    """enabled=false no puede alterar ni un decimal."""
    sin = _corre(None)
    apagado = _corre({"enabled": False, "unit": "CASH", "value": 1000.0,
                      "on_open_positions": "LET_RUN"})
    assert _resumen(sin) == _resumen(apagado)
    assert sin["aggregate_metrics"] == apagado["aggregate_metrics"]


def test_tope_enorme_no_llega_a_saltar():
    """Un tope inalcanzable deja el backtest igual que sin tope."""
    sin = _corre(None)
    holgado = _corre({"enabled": True, "unit": "CASH", "value": 1_000_000.0,
                      "on_open_positions": "CLOSE_ALL"})
    assert _resumen(sin) == _resumen(holgado)
    assert (holgado.get("daily_limit_log") or []) == []
