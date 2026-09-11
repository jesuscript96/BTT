"""
Coste de Black Swan (2026-09-11). Ver app/services/bswan.py.

Lo que se prueba, en este orden:
  1. Sin `bswan` NADA cambia: ni claves nuevas en los trades del motor, ni
     resultado distinto, y el kwarg `bswan=None` pasa por `sim_dispatch` al
     kernel JIT sin reventar (la trampa que ya mordio con `ev_gate`).
  2. Modo «mercado»: cierra en la vela del mechazo al stop penalizado; sin
     stop cruzado, a la apertura penalizada; por tramos si hay particion; el
     largo mira la mecha hacia abajo.
  3. Modo «manual»: no cierra en la vela aunque cruce el stop, ni en las
     siguientes; cierra al cierre de la vela a N minutos; EOD sigue mandando.
  4. Descriptivo: `anotar_mechas` mide la mecha maxima SOLO mientras se esta
     dentro (una salida por senal no expone su vela).
  5. De punta a punta por `run_backtest` (camino SECUENCIAL, el que corre en
     esta maquina): las claves llegan a los trades finales, el resumen cuenta
     bien y el PnL baja con el coste.
"""
import numpy as np
import pandas as pd
import pytest

from app.services import sim_dispatch
from app.services.bswan import (
    ConfigBSwan, anotar_mechas, mechas_adversas, precio_bs, tramos_bs,
)
from app.services.backtest_service import _enrich_trades, _group_partial_exits
from app.services.portfolio_sim import simulate as sim_py

NS_MIN = 60_000_000_000
T0 = 1_756_800_000 * 1_000_000_000 + 4 * 3600 * 1_000_000_000

# Corto a 1,00 $ con stop del 20 % (nivel 1,20). 1.000 $ de riesgo a valor de
# mercado = 1.000 acciones. Sin comisiones ni slippage para que las cifras se
# puedan hacer de cabeza.
KW = dict(direction="shortonly", init_cash=100_000.0, risk_r=1000.0, risk_type="FIXED",
          sl_stop=0.20, fees=0.0, slippage=0.0, look_ahead_prevention=True)


def _velas(n=20, precio=1.0):
    """Dia plano: todas las velas a `precio`, mecha del 1 % que no toca nada.
    Entrada en la vela 2 -> fill en la apertura de la 3."""
    close = np.full(n, precio)
    open_ = np.full(n, precio)
    high = np.full(n, precio * 1.01)
    low = np.full(n, precio * 0.99)
    ts = (T0 + np.arange(n) * NS_MIN).astype(np.int64)
    entries = np.zeros(n, dtype=bool)
    entries[2] = True
    exits = np.zeros(n, dtype=bool)
    return dict(close=close, open_=open_, high=high, low=low,
                entries=entries, exits=exits, timestamps=ts)


def _mechazo(v, i, open_px, high_px, low_px=None, close_px=None):
    v["open_"][i] = open_px
    v["high"][i] = high_px
    v["low"][i] = low_px if low_px is not None else open_px
    v["close"][i] = close_px if close_px is not None else open_px


# ── 1. Sin coste no cambia nada ────────────────────────────────────────────

def test_sin_coste_ni_claves_nuevas_ni_resumen():
    v = _velas()
    _mechazo(v, 6, 0.5, 25.0)
    r = sim_py(**v, **KW)
    assert "bswan" not in r
    for t in r["trades"]:
        assert not any(k.startswith("bs_") for k in t), t


def test_bswan_none_pasa_por_el_dispatcher_al_jit(monkeypatch):
    """La trampa de `ev_gate`: con el kernel activo, un kwarg que el JIT no
    conoce mata cada ticker-dia y la corrida acaba con cero trades."""
    monkeypatch.setenv("BACKTEST_NUMBA_SIM", "1")
    v = _velas()
    _mechazo(v, 6, 0.5, 25.0)
    r_jit = sim_dispatch.simulate(**v, **KW, bswan=None)
    r_py = sim_py(**v, **KW)
    assert r_jit["trades"] == r_py["trades"]
    assert r_jit["trades"][0]["exit_reason"] == "SL"


def test_con_coste_el_dispatcher_desvia_al_python(monkeypatch):
    monkeypatch.setenv("BACKTEST_NUMBA_SIM", "1")
    v = _velas()
    _mechazo(v, 6, 0.5, 25.0)
    r = sim_dispatch.simulate(**v, **KW, bswan=ConfigBSwan(umbral_pct=200.0))
    assert r["trades"][0]["exit_reason"] == "BS"


def test_umbral_no_alcanzado_es_identico_al_motor_de_siempre():
    v = _velas()
    _mechazo(v, 6, 0.5, 1.1)           # 120 %, por debajo del stop (1,20)
    base = sim_py(**v, **KW)
    r = sim_py(**v, **KW, bswan=ConfigBSwan(umbral_pct=200.0))
    assert r["trades"] == base["trades"]
    assert r["bswan"] == []
    np.testing.assert_array_equal(r["equity"], base["equity"])


# ── 2. Modo «mercado» ──────────────────────────────────────────────────────

def test_mercado_cierra_en_la_vela_al_stop_penalizado():
    """El ejemplo de Jaume: corto en 1, stop al 20 %, en 0,50 mecha del
    5.000 %. Debia salir a 1,20; con slippage del 100 % sale a 2,40."""
    v = _velas()
    _mechazo(v, 6, 0.5, 25.0, close_px=0.6)
    base = sim_py(**v, **KW)
    assert base["trades"][0]["exit_reason"] == "SL"
    assert base["trades"][0]["exit_price"] == pytest.approx(1.2)

    cfg = ConfigBSwan(modo="mercado", umbral_pct=200.0, slippage_pct=100.0, particion=0.0)
    r = sim_py(**v, **KW, bswan=cfg)
    t = r["trades"]
    assert len(t) == 1
    assert t[0]["exit_reason"] == "BS"
    assert t[0]["exit_idx"] == 6
    assert t[0]["exit_price"] == pytest.approx(2.4)
    assert t[0]["bs_base_price"] == pytest.approx(1.2)
    assert t[0]["bs_trigger_pct"] == pytest.approx(4900.0)
    assert t[0]["bs_tramos"] == 1 and t[0]["bs_tramo"] == 1
    assert t[0]["bs_slip_pct"] == pytest.approx(100.0)
    assert t[0]["pnl"] == pytest.approx((1.0 - 2.4) * 1000.0)
    assert t[0]["bs_penalty"] == pytest.approx((2.4 - 1.2) * 1000.0)
    assert len(r["bswan"]) == 1
    assert r["bswan"][0]["penalizacion"] == pytest.approx(1200.0)
    # La equity refleja el cierre penalizado, no el stop limpio.
    assert r["equity"][-1] == pytest.approx(100_000.0 + (1.0 - 2.4) * 1000.0)


def test_mecha_que_no_cruza_el_stop_no_es_black_swan():
    """REGLA DE JAUME: un fogonazo del 120 % que no llega al stop (1,20) no
    barre ninguna orden. El trade sigue abierto y acaba igual que sin coste."""
    v = _velas()
    _mechazo(v, 6, 0.5, 1.1)
    base = sim_py(**v, **KW)
    r = sim_py(**v, **KW, bswan=ConfigBSwan(umbral_pct=100.0, slippage_pct=100.0))
    assert base["trades"][0]["exit_reason"] == "EOD"
    assert r["trades"] == base["trades"]
    assert r["bswan"] == []


def test_sin_stop_configurado_no_hay_black_swan():
    """Sin stop no hay nada que barrer: ni con una mecha del 4.900 %."""
    v = _velas()
    _mechazo(v, 6, 0.5, 25.0)
    kw = {**KW, "sl_stop": None}
    base = sim_py(**v, **kw)
    r = sim_py(**v, **kw, bswan=ConfigBSwan(umbral_pct=100.0, slippage_pct=100.0))
    assert base["trades"][0]["exit_reason"] == "EOD"
    assert r["trades"] == base["trades"]
    assert r["bswan"] == []


def test_manual_no_se_arma_si_la_mecha_no_cruza_el_stop():
    """En manual la regla es la misma: sin stop cruzado no se suspende nada,
    y un stop cruzado DESPUES sale como SL normal."""
    v = _velas()
    _mechazo(v, 6, 0.5, 1.1)          # 120 %, no llega a 1,20
    v["high"][8] = 1.5                 # este si cruza, y no hay espera armada
    r = sim_py(**v, **KW, bswan=ConfigBSwan(modo="manual", umbral_pct=100.0, minutos=3.0))
    t = r["trades"][0]
    assert t["exit_reason"] == "SL" and t["exit_idx"] == 8
    assert "bs_modo" not in t
    assert r["bswan"] == []


def test_mercado_particiona_y_escalona_el_slippage():
    """1.500 acciones con particion del 50 % y slippage del 100 %: la mitad
    sale un 100 % peor y la otra mitad un 200 % peor (ejemplo de Jaume)."""
    v = _velas()
    _mechazo(v, 6, 0.5, 25.0)
    kw = {**KW, "risk_r": 1500.0}
    cfg = ConfigBSwan(umbral_pct=200.0, slippage_pct=100.0, particion=50.0)
    r = sim_py(**v, **kw, bswan=cfg)
    t = r["trades"]
    assert [x["exit_reason"] for x in t] == ["BS", "BS"]
    assert [x["size"] for x in t] == [pytest.approx(750.0), pytest.approx(750.0)]
    assert [x["exit_price"] for x in t] == [pytest.approx(2.4), pytest.approx(3.6)]
    assert [x["bs_tramo"] for x in t] == [1, 2] and all(x["bs_tramos"] == 2 for x in t)
    assert [x["bs_slip_pct"] for x in t] == [pytest.approx(100.0), pytest.approx(200.0)]
    assert r["bswan"][0]["penalizacion"] == pytest.approx((2.4 - 1.2) * 750 + (3.6 - 1.2) * 750)

    # Agrupado como lo ve la UI: UN trade con dos ejecuciones etiquetadas.
    ts = pd.Series(pd.to_datetime(v["timestamps"]))
    g = _group_partial_exits(_enrich_trades(t, ts, "XX", "2025-09-01", {}, 1500.0))
    assert len(g) == 1
    assert g[0]["n_executions"] == 2
    assert g[0]["size"] == pytest.approx(1500.0)
    assert g[0]["bs_slip_pct"] == pytest.approx(200.0)
    assert g[0]["bs_penalty"] == pytest.approx(2700.0)
    assert g[0]["bs_tramos"] == 2 and "bs_tramo" not in g[0]
    etiquetas = [e["label"] for e in g[0]["executions"] if e["kind"] == "exit"]
    assert etiquetas == ["BS 1/2 +100%", "BS 2/2 +200%"]


def test_mercado_particion_del_30_deja_el_resto_en_el_cuarto_escalon():
    """30 % -> 30/30/30 y el 10 % que queda al +400 % (ejemplo de Jaume)."""
    v = _velas()
    _mechazo(v, 6, 0.5, 25.0)
    cfg = ConfigBSwan(umbral_pct=200.0, slippage_pct=100.0, particion=30.0)
    r = sim_py(**v, **KW, bswan=cfg)
    t = r["trades"]
    assert [x["size"] for x in t] == [pytest.approx(300.0)] * 3 + [pytest.approx(100.0)]
    assert [x["bs_slip_pct"] for x in t] == [100.0, 200.0, 300.0, 400.0]
    assert [x["exit_price"] for x in t] == [pytest.approx(p) for p in (2.4, 3.6, 4.8, 6.0)]
    assert all(x["bs_tramos"] == 4 for x in t)


def test_mercado_en_largo_mira_la_mecha_hacia_abajo():
    v = _velas()
    _mechazo(v, 6, 0.9, 0.9, low_px=0.1, close_px=0.5)   # (0,9-0,1)/0,9 = 88,9 %
    kw = {**KW, "direction": "longonly"}
    r = sim_py(**v, **kw, bswan=ConfigBSwan(umbral_pct=50.0, slippage_pct=50.0))
    t = r["trades"][0]
    assert t["exit_reason"] == "BS"
    assert t["bs_trigger_pct"] == pytest.approx(88.8889, abs=1e-3)
    assert t["bs_base_price"] == pytest.approx(0.8)      # el stop del largo
    assert t["exit_price"] == pytest.approx(0.4)
    assert t["pnl"] == pytest.approx((0.4 - 1.0) * 1000.0)


def test_mercado_con_trailing_activo_parte_del_nivel_del_trailing():
    """Sin stop fijo, con trailing del 10 % ya activado (el precio bajo a
    0,50): el nivel vigente es 0,50 + 0,10 = 0,60 y la mecha lo cruza."""
    v = _velas()
    for i in range(4, 6):
        v["open_"][i] = v["close"][i] = 0.5
        v["high"][i] = 0.51
        v["low"][i] = 0.5
    _mechazo(v, 6, 0.5, 25.0)
    kw = {**KW, "sl_stop": None, "sl_trail": True, "trail_pct": 0.10}
    base = sim_py(**v, **kw)
    assert base["trades"][0]["exit_reason"] == "Trailing"
    assert base["trades"][0]["exit_price"] == pytest.approx(0.6)
    r = sim_py(**v, **kw, bswan=ConfigBSwan(umbral_pct=200.0, slippage_pct=100.0))
    t = r["trades"][0]
    assert t["exit_reason"] == "BS"
    assert t["bs_base_price"] == pytest.approx(0.6)
    assert t["exit_price"] == pytest.approx(1.2)


def test_mercado_la_reentrada_posterior_sigue_funcionando():
    """Tras un cierre por BS la estrategia puede reentrar: el flag de espera
    se rearma en la entrada y la segunda posicion vive normal."""
    v = _velas(n=30)
    _mechazo(v, 6, 0.5, 25.0)
    v["entries"][10] = True
    kw = {**KW, "accumulate": True}
    r = sim_py(**v, **kw, bswan=ConfigBSwan(umbral_pct=200.0, slippage_pct=100.0))
    assert [t["exit_reason"] for t in r["trades"]] == ["BS", "EOD"]
    assert r["trades"][1]["entry_idx"] == 11
    assert not any(k.startswith("bs_") for k in r["trades"][1])


# ── 3. Modo «manual» ───────────────────────────────────────────────────────

def test_manual_no_cierra_en_la_vela_y_cierra_a_los_n_minutos():
    v = _velas()
    _mechazo(v, 6, 0.5, 25.0)
    v["high"][7] = 1.5                 # cruza el stop (1,20) durante la espera
    cfg = ConfigBSwan(modo="manual", umbral_pct=200.0, minutos=3.0)
    r = sim_py(**v, **KW, bswan=cfg)
    t = r["trades"]
    assert len(t) == 1
    assert t[0]["exit_reason"] == "BS Manual"
    assert t[0]["exit_idx"] == 9        # deteccion en la 6, +3 min = la 9
    assert t[0]["exit_price"] == pytest.approx(v["close"][9])
    assert t[0]["bs_modo"] == "manual"
    assert t[0]["bs_trigger_pct"] == pytest.approx(4900.0)
    assert len(r["bswan"]) == 1
    ev = r["bswan"][0]
    assert (ev["idx"], ev["modo"]) == (6, "manual")
    assert ev["mecha_pct"] == pytest.approx(4900.0)
    assert ev["stop"] == pytest.approx(1.2)      # el stop que la mecha cruzo


def test_manual_eod_sigue_mandando_durante_la_espera():
    v = _velas(n=20)
    _mechazo(v, 18, 0.5, 25.0)
    cfg = ConfigBSwan(modo="manual", umbral_pct=200.0, minutos=10.0)
    r = sim_py(**v, **KW, bswan=cfg)
    t = r["trades"][0]
    assert t["exit_reason"] == "EOD"
    assert t["exit_idx"] == 19
    assert t["bs_modo"] == "manual"


def test_manual_sin_timestamps_cuenta_velas_como_minutos():
    v = _velas()
    v.pop("timestamps")
    _mechazo(v, 6, 0.5, 25.0)
    cfg = ConfigBSwan(modo="manual", umbral_pct=200.0, minutos=2.0)
    r = sim_py(**v, **KW, bswan=cfg)
    assert r["trades"][0]["exit_reason"] == "BS Manual"
    assert r["trades"][0]["exit_idx"] == 8


# ── 4. Descriptivo ─────────────────────────────────────────────────────────

def test_anotar_mechas_solo_mientras_se_esta_dentro():
    v = _velas()
    v["high"][1] = 5.0          # antes de entrar: no cuenta
    v["high"][5] = 1.6          # dentro: 60 %
    v["exits"][8] = True        # salida por senal -> fill en la apertura de la 9
    v["high"][9] = 3.0          # la vela del fill ya no expone
    kw = {**KW, "sl_stop": None}
    r = sim_py(**v, **kw)
    t = r["trades"]
    assert t[0]["exit_reason"] == "Signal" and t[0]["exit_idx"] == 9
    anotar_mechas(t, v["open_"], v["high"], v["low"], is_long=False, look_ahead_prevention=True)
    assert t[0]["bs_wick_pct"] == pytest.approx(60.0)
    assert t[0]["bs_wick_idx"] == 5
    assert "bs_wick_hit_stop" not in t[0]      # sin stop no se anota


def test_anotar_mechas_dice_si_la_mecha_sobrepaso_el_stop():
    """`bs_wick_hit_stop`: el extremo en crudo de la vela de la mecha maxima
    contra el nivel del stop del trade (regla de Jaume, en la vista
    descriptiva). Con stop del 20 % (1,20): 1,60 lo sobrepasa, 1,10 no."""
    v = _velas()
    v["high"][5] = 1.6
    r = sim_py(**v, **KW)
    t = r["trades"]
    assert t[0]["exit_reason"] == "SL" and t[0]["exit_idx"] == 5
    anotar_mechas(t, v["open_"], v["high"], v["low"], is_long=False)
    assert t[0]["bs_wick_idx"] == 5 and t[0]["bs_wick_hit_stop"] is True

    v2 = _velas()
    v2["high"][5] = 1.1
    r2 = sim_py(**v2, **KW)
    t2 = r2["trades"]
    anotar_mechas(t2, v2["open_"], v2["high"], v2["low"], is_long=False)
    assert t2[0]["bs_wick_idx"] == 5 and t2[0]["bs_wick_hit_stop"] is False


def test_helpers_puros():
    assert tramos_bs(1500, 50, 100) == [(750.0, 100.0), (750.0, 200.0)]
    assert tramos_bs(1000, 30, 100) == [(300.0, 100.0), (300.0, 200.0), (300.0, 300.0), (100.0, 400.0)]
    assert tramos_bs(3000, 100 / 3, 50) == [pytest.approx((1000.0, 50.0)), pytest.approx((1000.0, 100.0)),
                                            pytest.approx((1000.0, 150.0))]
    assert tramos_bs(1000, 0, 100) == [(1000.0, 100.0)]
    assert tramos_bs(1000, 100, 100) == [(1000.0, 100.0)]
    assert tramos_bs(0, 50, 100) == []
    with pytest.raises(ValueError):
        ConfigBSwan(particion=150.0)
    assert precio_bs(1.2, 100, is_long=False) == pytest.approx(2.4)
    assert precio_bs(0.8, 50, is_long=True) == pytest.approx(0.4)
    assert precio_bs(0.8, 150, is_long=True) == 0.0
    m = mechas_adversas(np.array([1.0, 0.0, 2.0]), np.array([3.0, 5.0, 2.0]), np.array([0.5, 0.0, 1.0]), False)
    assert list(m) == [pytest.approx(200.0), 0.0, 0.0]
    with pytest.raises(ValueError):
        ConfigBSwan(modo="loquesea")
    with pytest.raises(ValueError):
        ConfigBSwan(umbral_pct=0.0)
    with pytest.raises(ValueError):
        ConfigBSwan(modo="manual", minutos=0.0)


# ── 5. De punta a punta por run_backtest (camino secuencial) ───────────────

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


@pytest.fixture
def _secuencial(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr(gcs_cache, "LOCAL_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("BTT_SLAB_DIR", str(tmp_path / "slabs"))
    monkeypatch.delenv("BTT_SLAB_STREAM_ENABLED", raising=False)
    monkeypatch.delenv("BACKTEST_PARALLEL_WORKERS", raising=False)
    monkeypatch.setenv("BACKTEST_NUMBA_SIM", "1")   # como en la maquina de Jaume
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
    df = pd.DataFrame({
        "ticker": ticker, "date": date, "timestamp": ts,
        "open": open_, "high": np.maximum(open_, close) * 1.004,
        "low": np.minimum(open_, close) * 0.996, "close": close,
        "volume": rng.integers(100, 50000, n),
    })
    # Mechazos dentro de RTH (09:30 = vela 330): un 3.000 % en cuatro velas.
    for i in (340, 360, 380, 400):
        df.loc[i, "high"] = df.loc[i, "open"] * 31.0
    return df


def _datos(n_tickers=4):
    days = ["2025-09-01", "2025-09-02"]
    qual_rows, trozos = [], []
    for i in range(n_tickers):
        tk = f"TK{i:02d}"
        for j, d in enumerate(days):
            trozos.append(_mk_day(tk, d, seed=i * 10 + j))
            qual_rows.append({"ticker": tk, "date": d, "prev_close": 8.0, "gap_pct": 60.0,
                              "yesterday_open": 7.7, "lag_rth_open_1": 7.7})
    return pd.DataFrame(qual_rows), pd.concat(trozos, ignore_index=True)


def _corre(bswan=None):
    qual, intraday = _datos()
    return run_backtest(
        qualifying_df=qual, intraday_df=intraday, strategy_def=STRATEGY,
        init_cash=10000.0, risk_r=100.0, risk_type="FIXED",
        market_sessions=["rth"], day_group_iter=None, n_groups_hint=None,
        bswan=bswan,
    )


def test_e2e_descriptivo_siempre_y_sin_cambiar_nada(_secuencial):
    base = _corre(None)
    tr = base["trades"]
    assert len(tr) > 0, "el fixture debe producir trades"
    assert "bswan" not in base
    assert all(t.get("bs_wick_pct") is not None and t.get("bs_wick_time_epoch") is not None for t in tr)
    assert not any(t["exit_reason"].startswith("BS") for t in tr)
    # Los mechazos del fixture disparan el stop del 15 %: quedan como SL y con
    # la mecha anotada por encima del 100 %.
    expuestos = [t for t in tr if t["bs_wick_pct"] >= 100.0]
    assert expuestos, "algun trade debe haber estado dentro durante un mechazo"
    assert all(t["exit_reason"] == "SL" for t in expuestos)
    assert all(t.get("bs_wick_hit_stop") is True for t in expuestos)


def test_e2e_mercado_cierra_por_bs_y_cuenta(_secuencial):
    base = _corre(None)
    cfg = ConfigBSwan(modo="mercado", umbral_pct=200.0, slippage_pct=100.0, particion=0.0)
    con = _corre(cfg)
    tr = con["trades"]
    bs = [t for t in tr if t["exit_reason"] == "BS"]
    assert bs, "con el coste debe haber cierres por BS"
    assert all(t["bs_modo"] == "mercado" and t["bs_slip_pct"] == 100.0 for t in bs)
    assert all(t["exit_price"] == pytest.approx(t["bs_base_price"] * 2.0, rel=1e-6) for t in bs)
    res = con["bswan"]
    assert res["enabled"] and res["modo"] == "mercado" and res["umbral_pct"] == 200.0
    assert res["cierres_mercado"] == len(bs) == res["trades"]
    assert res["detecciones"] >= len(bs)
    assert res["penalizacion_usd"] == pytest.approx(sum(t["bs_penalty"] for t in bs), abs=0.05)
    assert res["penalizacion_usd"] > 0
    # Mismas operaciones, peor resultado: la penalizacion se ve en el total.
    assert len(tr) == len(base["trades"])
    assert con["aggregate_metrics"]["total_pnl"] < base["aggregate_metrics"]["total_pnl"]
    # Y los parametros del coste quedan escritos en el resultado.
    assert set(res) >= {"slippage_pct", "particion", "minutos", "tramos", "cierres_manual"}


def test_e2e_manual_cierra_diferido(_secuencial):
    cfg = ConfigBSwan(modo="manual", umbral_pct=200.0, minutos=5.0)
    con = _corre(cfg)
    manual = [t for t in con["trades"] if t.get("bs_modo") == "manual"]
    assert manual
    assert all(t["exit_reason"] in ("BS Manual", "EOD") for t in manual)
    assert any(t["exit_reason"] == "BS Manual" for t in manual)
    assert con["bswan"]["cierres_manual"] == sum(1 for t in manual if t["exit_reason"] == "BS Manual")
