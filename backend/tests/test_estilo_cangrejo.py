# -*- coding: utf-8 -*-
"""Estilo Cangrejo — los dos modos del PRD de Álvaro (`docs/PRD_ESTILO_CANGREJO.md`).

QUÉ SE PRUEBA Y POR QUÉ ESTÁ ORDENADO ASÍ:

  1. La matemática de cada modo aislada (los dos helpers).
  2. Que el Modo A mueve la SALIDA REAL, no solo el sizing — ahí estaba el
     riesgo: el stop porcentual se recalcula en cada barra desde `entry_price`,
     así que era fácil dimensionar con un stop y salir por otro.
  3. La REGLA Nº1 del PRD: sin campos, resultado idéntico bit a bit. Un techo
     nuevo que cambie una corrida vieja invalidaría todo el histórico.
  4. Exclusividad con el híbrido y el arbitraje a favor de Cangrejo.
  5. PARIDAD Python ↔ kernel Numba. Es lo que permite que una estrategia con
     Cangrejo NO caiga al motor lento, a diferencia del híbrido.
  6. Las TRES CAPAS: el campo declarado en pydantic, o se cae sin error.
"""
import os

import numpy as np
import pytest

from app.services import sim_dispatch
from app.services.portfolio_sim import (
    aprieta_stop_cangrejo,
    simulate,
    tope_cangrejo,
)
from app.schemas.strategy import RiskManagement


# ── material común ────────────────────────────────────────────────────────
def _serie():
    """Largo que entra a 1,00, se hunde hasta 0,45 y vuelve.

    Con SL al 50 % el stop está en 0,50 y la vela de 0,45 lo cruza: sirve para
    ver dónde sale con y sin el Modo A.
    """
    close = np.array([1.00, 1.00, 1.00, 0.90, 0.70, 0.45, 0.60, 0.80, 1.00, 1.00])
    entries = np.zeros(10, dtype=bool)
    entries[1] = True
    return dict(
        close=close, open_=close.copy(), high=close * 1.02, low=close * 0.98,
        entries=entries, exits=np.zeros(10, dtype=bool),
        timestamps=(np.arange(10) * 60_000_000_000
                    + 1_700_000_000_000_000_000).astype(np.int64),
    )


BASE = dict(direction="longonly", init_cash=10_000.0, risk_r=100.0,
            risk_type="PERCENT", sl_stop=0.50, look_ahead_prevention=True)


def _correr(**extra):
    return simulate(**_serie(), **{**BASE, **extra})


# ══ 1. La matemática de cada modo ═════════════════════════════════════════
def test_modo_a_apretar_el_ejemplo_del_prd():
    """Entrada 1,00, SL estructural en 2,00 (corto), tope 50 % -> 1,50."""
    assert aprieta_stop_cangrejo(1.00, 2.00, 50.0, is_long=False) == pytest.approx(1.50)


def test_modo_a_en_largo():
    assert aprieta_stop_cangrejo(1.00, 0.20, 50.0, is_long=True) == pytest.approx(0.50)


def test_modo_a_solo_aprieta_nunca_afloja():
    """Un stop que YA está más cerca que el tope se devuelve intacto."""
    assert aprieta_stop_cangrejo(1.00, 0.90, 50.0, is_long=True) == 0.90


def test_modo_a_sin_datos_devuelve_el_stop():
    """Sin tope, sin stop o con entrada absurda no se inventa nada."""
    assert aprieta_stop_cangrejo(1.00, 0.20, None, True) == 0.20
    assert aprieta_stop_cangrejo(1.00, 0.20, 0.0, True) == 0.20
    assert aprieta_stop_cangrejo(1.00, 0.0, 50.0, True) == 0.0
    assert aprieta_stop_cangrejo(0.0, 0.20, 50.0, True) == 0.20


def test_modo_b_el_ejemplo_del_prd():
    """Cuenta 10.000, tope 3 % (300 $), SL al 100 % de distancia -> 300 acciones."""
    assert tope_cangrejo(10_000.0, 3.0, 1.00) == pytest.approx(300.0)


def test_modo_b_escala_con_la_distancia():
    """Media distancia, doble tamaño: la PÉRDIDA es lo que queda fijo."""
    assert tope_cangrejo(10_000.0, 3.0, 0.50) == pytest.approx(600.0)


def test_modo_b_sin_datos_no_topa():
    """SIN STOP no hay pérdida definida que topar: None, no un cero silencioso."""
    assert tope_cangrejo(10_000.0, 3.0, 0.0) is None
    assert tope_cangrejo(0.0, 3.0, 1.0) is None
    assert tope_cangrejo(10_000.0, None, 1.0) is None
    assert tope_cangrejo(10_000.0, 0.0, 1.0) is None


# ══ 2. El Modo A mueve la SALIDA, no solo el tamaño ═══════════════════════
def test_modo_a_cambia_donde_se_sale():
    t = _correr(cangrejo_active=True, cangrejo_max_sl_dist_pct=20.0)["trades"][0]
    assert t["stop_loss"] == pytest.approx(0.80)
    assert t["exit_reason"] == "SL"
    # LA CLAVE: sale en el stop APRETADO (0,80), no en el 50 % original (0,50).
    assert t["exit_price"] == pytest.approx(0.80)


def test_modo_a_no_toca_el_tamano():
    sin = _correr()["trades"][0]
    con = _correr(cangrejo_active=True, cangrejo_max_sl_dist_pct=20.0)["trades"][0]
    assert con["size"] == pytest.approx(sin["size"])


def test_modo_a_con_stop_estructural():
    """Con SL de estructura el nivel viene de un array, no de un porcentaje."""
    d = _serie()
    lods = np.full(10, 0.30)   # nivel muy lejano: 70 % de recorrido
    t = simulate(**d, direction="longonly", init_cash=10_000.0, risk_r=100.0,
                 risk_type="PERCENT", look_ahead_prevention=True,
                 hs_type="Market Structure (HOD/LOD)", hs_value="LOD",
                 hs_operator="<", hs_offset_pct=0.0, lods=lods,
                 cangrejo_active=True, cangrejo_max_sl_dist_pct=25.0)["trades"][0]
    assert t["stop_loss"] == pytest.approx(0.75)
    assert t["exit_price"] == pytest.approx(0.75)


# ══ 3. El Modo B encoge el tamaño y NO toca el stop ═══════════════════════
def test_modo_b_encoge_el_tamano():
    t = _correr(size_by_sl=True, cangrejo_active=True,
                cangrejo_max_loss_at_sl_pct=1.0)["trades"][0]
    # 1 % de 10.000 = 100 $; distancia 1,00 - 0,50 = 0,50 -> 200 acciones.
    assert t["size"] == pytest.approx(200.0)
    assert t["stop_loss"] == pytest.approx(0.50)   # el stop NO se mueve


def test_modo_b_tambien_sin_size_by_sl():
    """A DIFERENCIA DEL HÍBRIDO, el Modo B no exige `size_by_sl`.

    Es un techo sobre el sizing que haya, y por valor de mercado es justo donde
    la pérdida al stop se descontrola.
    """
    t = _correr(size_by_sl=False, cangrejo_active=True,
                cangrejo_max_loss_at_sl_pct=1.0)["trades"][0]
    assert t["size"] == pytest.approx(200.0)


def test_modo_b_la_perdida_real_respeta_el_tope():
    t = _correr(size_by_sl=True, cangrejo_active=True,
                cangrejo_max_loss_at_sl_pct=1.0)["trades"][0]
    assert t["exit_reason"] == "SL"
    assert abs(t["pnl"]) <= 100.0 + 1e-6


def test_modo_b_usa_la_distancia_YA_apretada():
    """Con los dos modos en el payload, B mide sobre el stop apretado por A."""
    t = _correr(size_by_sl=True, cangrejo_active=True,
                cangrejo_max_sl_dist_pct=20.0,
                cangrejo_max_loss_at_sl_pct=1.0)["trades"][0]
    # distancia apretada = 0,20 -> 100 $ / 0,20 = 500 acciones
    assert t["size"] == pytest.approx(500.0)


def test_modo_b_usa_hybrid_capital_si_viene():
    """El bot manda ahí la cuenta de verdad: su `init_cash` es un nominal."""
    t = _correr(size_by_sl=True, cangrejo_active=True,
                cangrejo_max_loss_at_sl_pct=1.0,
                hybrid_capital=1_000.0)["trades"][0]
    assert t["size"] == pytest.approx(20.0)   # 1 % de 1.000 = 10 $ / 0,50


# ══ 4. REGLA Nº1: sin campos, resultado idéntico ══════════════════════════
def test_apagado_es_identico():
    assert _correr()["trades"] == _correr(cangrejo_active=False)["trades"]


def test_activo_sin_campos_es_identico():
    """Encenderlo sin rellenar nada NO puede cambiar una corrida."""
    assert _correr()["trades"] == _correr(cangrejo_active=True)["trades"]


def test_un_tope_que_no_muerde_es_identico():
    """Incidente reproducido por Álvaro: con los topes por encima del sizing
    que ya hay, los resultados salen iguales. Es CORRECTO, no un bug."""
    base = _correr()["trades"]
    assert _correr(cangrejo_active=True, cangrejo_max_sl_dist_pct=90.0)["trades"] == base
    assert _correr(cangrejo_active=True,
                   cangrejo_max_loss_at_sl_pct=99.0)["trades"] == base


# ══ 5. Exclusividad con el híbrido ════════════════════════════════════════
def test_cangrejo_gana_al_hibrido():
    """Un payload con los dos: manda Cangrejo (PRD §2)."""
    t = _correr(size_by_sl=True,
                hybrid_stop=True, hybrid_black_swan_pct=5_000.0,
                hybrid_max_loss_pct=50.0,
                cangrejo_active=True,
                cangrejo_max_loss_at_sl_pct=1.0)["trades"][0]
    assert t["size"] == pytest.approx(200.0)   # el del Modo B, no el del híbrido


def test_el_hibrido_solo_manda_sin_cangrejo():
    t = _correr(size_by_sl=True, hybrid_stop=True,
                hybrid_black_swan_pct=5_000.0,
                hybrid_max_loss_pct=50.0)["trades"][0]
    # techo híbrido = 50/5000 x 10.000 = 100 $ de exposición / 1,00 = 100 acciones
    assert t["size"] == pytest.approx(100.0)


# ══ 6. Paridad con el kernel Numba ════════════════════════════════════════
_CASOS_PARIDAD = [
    dict(),
    dict(cangrejo_active=True, cangrejo_max_sl_dist_pct=20.0),
    dict(cangrejo_active=True, cangrejo_max_sl_dist_pct=5.0),
    dict(cangrejo_active=True, cangrejo_max_loss_at_sl_pct=1.0, size_by_sl=True),
    dict(cangrejo_active=True, cangrejo_max_loss_at_sl_pct=0.5),
    dict(cangrejo_active=True, cangrejo_max_sl_dist_pct=30.0,
         cangrejo_max_loss_at_sl_pct=2.0, size_by_sl=True),
    dict(cangrejo_active=True, cangrejo_max_sl_dist_pct=15.0,
         sl_trail=True, trail_pct=0.10),
    dict(cangrejo_active=True, cangrejo_max_sl_dist_pct=25.0,
         hybrid_capital=2_000.0, cangrejo_max_loss_at_sl_pct=1.0),
]


@pytest.mark.parametrize("extra", _CASOS_PARIDAD)
def test_paridad_python_vs_numba(extra, monkeypatch):
    """El kernel tiene que dar EXACTAMENTE lo mismo, o el JIT miente.

    Es la prueba que sostiene la decisión de NO desviar Cangrejo al motor
    Python: si diverge, el genético estaría optimizando otra cosa.
    """
    py = simulate(**_serie(), **{**BASE, **extra})
    monkeypatch.setenv("BACKTEST_NUMBA_SIM", "1")
    jit = sim_dispatch.simulate(**_serie(), **{**BASE, **extra})
    assert py["trades"] == jit["trades"]
    assert np.array_equal(py["equity"], jit["equity"])


def test_el_dispatcher_no_desvia_cangrejo_al_python(monkeypatch):
    """Con Cangrejo Y híbrido, el híbrido está muerto: el kernel es válido."""
    monkeypatch.setenv("BACKTEST_NUMBA_SIM", "1")
    llamadas = []
    real = sim_dispatch._legacy_simulate
    monkeypatch.setattr(sim_dispatch, "_legacy_simulate",
                        lambda **kw: (llamadas.append(1), real(**kw))[1])
    sim_dispatch.simulate(**_serie(), **BASE, size_by_sl=True,
                          hybrid_stop=True, hybrid_black_swan_pct=5_000.0,
                          hybrid_max_loss_pct=50.0,
                          cangrejo_active=True, cangrejo_max_loss_at_sl_pct=1.0)
    assert llamadas == [], "con Cangrejo activo NO debe caer al motor Python"


def test_el_dispatcher_si_desvia_el_hibrido_solo(monkeypatch):
    """Sin Cangrejo, el híbrido sigue yendo al Python: el kernel no lo tiene."""
    monkeypatch.setenv("BACKTEST_NUMBA_SIM", "1")
    llamadas = []
    real = sim_dispatch._legacy_simulate
    monkeypatch.setattr(sim_dispatch, "_legacy_simulate",
                        lambda **kw: (llamadas.append(1), real(**kw))[1])
    sim_dispatch.simulate(**_serie(), **BASE, size_by_sl=True,
                          hybrid_stop=True, hybrid_black_swan_pct=5_000.0,
                          hybrid_max_loss_pct=50.0)
    assert llamadas == [1]


# ══ 7. TRES CAPAS: pydantic tiene que aceptar los campos ══════════════════
def test_los_campos_sobreviven_a_pydantic():
    """Sin declararlos, `extra='ignore'` los tira SIN error, SIN log y SIN 422
    — es lo que le pasó a `size_by_sl` y por eso salían estrategias con la
    opción apagada."""
    d = RiskManagement(cangrejo_active=True, cangrejo_mode="perdida",
                       cangrejo_max_sl_dist_pct=50.0,
                       cangrejo_max_loss_at_sl_pct=3.0).model_dump()
    assert d["cangrejo_active"] is True
    assert d["cangrejo_mode"] == "perdida"
    assert d["cangrejo_max_sl_dist_pct"] == 50.0
    assert d["cangrejo_max_loss_at_sl_pct"] == 3.0


def test_los_campos_inertes_tambien_se_admiten():
    """Sin UI y sin motor que los lea, pero un borrador viejo no debe reventar."""
    d = RiskManagement(cangrejo_max_mv_entry_pct=10.0,
                       cangrejo_max_mv_pyr_pct=5.0).model_dump()
    assert d["cangrejo_max_mv_entry_pct"] == 10.0
    assert d["cangrejo_max_mv_pyr_pct"] == 5.0


def test_por_defecto_apagado():
    d = RiskManagement().model_dump()
    assert d["cangrejo_active"] is False
    assert d["cangrejo_mode"] is None
    assert d["cangrejo_max_sl_dist_pct"] is None
    assert d["cangrejo_max_loss_at_sl_pct"] is None


# ══ 8. Pirámide: el techo de pérdida cuenta la posición ENTERA ════════
# DIVERGENCIA CONSCIENTE con el PRD, que solo habla de entradas y reentradas.
# Sin esto, una estrategia que piramide esquiva el techo entero: entra con el
# tamaño topado y añade sin mirar. La pérdida al stop de la posición COMPLETA
# tiene que seguir cabiendo en el tope.

def _con_piramide(**extra):
    """Short a 100 con un añadido de 300 $ en la vela 4. Stop al 2 % (2 $).

    Sin Cangrejo: entrada 1000 $ / 2 $ = 500 acciones, añadido 300/100 = 3.
    """
    n = 12
    sig = np.zeros(n, dtype=bool)
    sig[4] = True
    lv = {"signals": sig, "action": "add", "capital_frac": 0.0,
          "max_fires": 1, "unit": "usd", "amount_usd": 300.0}
    t = simulate(
        close=np.array([100.0] * n), open_=np.array([100.0] * n),
        high=np.array([101.0] * n), low=np.array([99.0] * n),
        entries=np.array([False, True] + [False] * (n - 2)),
        exits=np.array([False] * (n - 2) + [True, False]),
        direction="shortonly", init_cash=100_000.0,
        risk_r=1000.0, risk_type="FIXED", accumulate=True,
        size_by_sl=True, sl_stop=0.02,
        pyramid_levels=[lv], **extra,
    )["trades"]
    ex = (t[0].get("pyr_executions") or []) if t else []
    # OJO: `size` del trade es la posicion FINAL (entrada + anadidos), no la
    # entrada sola. Se devuelven las dos cosas: el total y lo que anadio la
    # piramide, que es lo que este bloque vigila.
    return (t[0]["size"] if t else 0.0), (ex[0]["size"] if ex else 0.0)


def test_la_piramide_sin_cangrejo_no_cambia():
    """Regla nº1 también aquí: sin campos, el añadido es el de siempre."""
    total, anadido = _con_piramide()
    assert anadido == pytest.approx(3.0)
    assert total == pytest.approx(503.0)   # 500 de entrada + 3 del anadido


def test_el_anadido_se_recorta_al_cupo_que_queda():
    """La entrada gasta 1.000 $ del cupo de 1.002 $: al añadido le queda 1 acción."""
    total, anadido = _con_piramide(cangrejo_active=True,
                                   cangrejo_max_loss_at_sl_pct=1.002)
    # La entrada (500 acciones x 2 $ = 1.000 $) no llega a topar; al añadido
    # solo le quedan 2 $ de cupo, o sea 1 acción en vez de 3.
    assert anadido == pytest.approx(1.0)
    assert total == pytest.approx(501.0)


def test_el_anadido_se_anula_si_no_queda_cupo():
    """Cupo 1.000 $ y la entrada ya se lo lleva entero: no se añade nada."""
    total, anadido = _con_piramide(cangrejo_active=True,
                                   cangrejo_max_loss_at_sl_pct=1.0)
    assert anadido == 0.0
    assert total == pytest.approx(500.0)   # se queda solo la entrada


# ══ 9. DE PUNTA A PUNTA: de `risk_management` a `simulate` ════════════════
# Las TRES CAPAS otra vez, pero desde arriba: no basta con que el motor sepa
# hacerlo, tiene que LLEGARLE. El patrón del cortacircuitos diario (la
# funcionalidad vivía en un camino y el usuario corría por otro) y el de
# `size_by_sl` (pydantic lo tiraba sin decir nada) son el mismo fallo visto
# desde dos alturas. Se prueba por el camino SECUENCIAL, que es el que usa la
# máquina de Jaume.
import pandas as pd

from app.db import gcs_cache, slab_store
from app.services.backtest_service import run_backtest

_STRAT_E2E = {
    "bias": "short", "apply_day": "gap_day",
    "entry_logic": {"timeframe": "1m", "root_condition": {"operator": "AND", "conditions": [
        {"type": "indicator_comparison", "timeframe": "1m",
         "source": {"name": "Bar Close"}, "comparator": "LESS_THAN", "target": {"name": "VWAP"}},
        {"type": "indicator_comparison", "timeframe": "1m",
         "source": {"name": "Bar Open"}, "comparator": "GREATER_THAN", "target": {"name": "VWAP"}},
    ]}},
    "risk_management": {"use_hard_stop": True,
                        "hard_stop": {"type": "Percentage", "value": 15},
                        "accept_reentries": True, "max_reentries": -1},
}


@pytest.fixture
def _aislado(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr(gcs_cache, "LOCAL_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("BTT_SLAB_DIR", str(tmp_path / "slabs"))
    # Se borran para forzar el camino SECUENCIAL.
    monkeypatch.delenv("BTT_SLAB_STREAM_ENABLED", raising=False)
    monkeypatch.delenv("BACKTEST_PARALLEL_WORKERS", raising=False)
    slab_store._OPEN_SLABS.clear()
    with gcs_cache._MONTH_CACHE_LOCK:
        gcs_cache._MONTH_CACHE.clear()
        gcs_cache._MONTH_CACHE_SIZES.clear()
    yield
    slab_store._OPEN_SLABS.clear()


def _dia(ticker, date, n=420, seed=0):
    rng = np.random.default_rng(seed)
    ts = pd.date_range(f"{date} 04:00", periods=n, freq="1min")
    close = 8.0 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    open_ = close * np.exp(rng.normal(0, 0.004, n))
    return pd.DataFrame({
        "ticker": ticker, "date": date, "timestamp": ts,
        "open": open_, "high": np.maximum(open_, close) * 1.004,
        "low": np.minimum(open_, close) * 0.996, "close": close,
        "volume": rng.integers(100, 50_000, n),
    })


def _corre_e2e(**rm_extra):
    days = ["2025-09-01", "2025-09-02"]
    qual_rows, trozos = [], []
    for i in range(4):
        tk = f"TK{i:02d}"
        for j, d in enumerate(days):
            trozos.append(_dia(tk, d, seed=i * 10 + j))
        qual_rows.append({"ticker": tk, "date": days[0], "prev_close": 8.0,
                          "gap_pct": 60.0, "yesterday_open": 7.7,
                          "lag_rth_open_1": 7.7})
    rm = {**_STRAT_E2E["risk_management"], "size_by_sl": True, **rm_extra}
    return run_backtest(
        qualifying_df=pd.DataFrame(qual_rows),
        intraday_df=pd.concat(trozos, ignore_index=True),
        strategy_def={**_STRAT_E2E, "risk_management": rm},
        init_cash=10_000.0, risk_r=100.0, risk_type="FIXED",
        market_sessions=["rth"], day_group_iter=None, n_groups_hint=None,
    )


def _tam(res):
    return sorted(round(t["size"], 4) for t in res.get("trades", []))


@pytest.mark.parametrize("numba", ["0", "1"])
def test_e2e_el_modo_b_llega_desde_la_definicion(_aislado, monkeypatch, numba):
    """Puesto SOLO en `risk_management`, sin tocar ningún argumento.

    Se corre con el JIT apagado Y encendido: el camino tiene que dar lo mismo
    en los dos, o el genético (que corre con `BACKTEST_NUMBA_SIM=1`) estaría
    evaluando otra cosa que el backtest de la pantalla.
    """
    monkeypatch.setenv("BACKTEST_NUMBA_SIM", numba)
    base = _corre_e2e()
    assert _tam(base), "el fixture tiene que producir trades o el test es vacío"
    con = _corre_e2e(cangrejo_active=True, cangrejo_max_loss_at_sl_pct=0.05)
    assert _tam(con) != _tam(base), (
        "el tope no llegó al motor: mismos tamaños con y sin Cangrejo")
    # Es un TECHO: ninguna posición puede haber crecido.
    for a, b in zip(_tam(base), _tam(con)):
        assert b <= a + 1e-6


@pytest.mark.parametrize("numba", ["0", "1"])
def test_e2e_el_modo_a_llega_desde_la_definicion(_aislado, monkeypatch, numba):
    monkeypatch.setenv("BACKTEST_NUMBA_SIM", numba)
    base = _corre_e2e()
    con = _corre_e2e(cangrejo_active=True, cangrejo_max_sl_dist_pct=1.0)
    # El stop apretado cambia la distancia, y con `size_by_sl` eso cambia el
    # tamaño: si sale idéntico, el campo se cayó por el camino.
    assert _tam(con) != _tam(base)


def test_e2e_apagado_no_cambia_nada(_aislado, monkeypatch):
    """Lo que protege el histórico: una corrida vieja sigue dando lo mismo."""
    monkeypatch.setenv("BACKTEST_NUMBA_SIM", "0")
    a = _corre_e2e()
    b = _corre_e2e(cangrejo_active=False, cangrejo_max_sl_dist_pct=None,
                   cangrejo_max_loss_at_sl_pct=None)
    assert a["trades"] == b["trades"]
