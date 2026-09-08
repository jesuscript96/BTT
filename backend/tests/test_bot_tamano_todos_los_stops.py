# -*- coding: utf-8 -*-
"""El tamaño del AVISO tiene que coincidir con el que dimensiona el SIMULADOR.

EL FALLO QUE ARREGLA ESTO (8-sep-2026). El aviso calculaba su stop con
`nivel_stop`, que devuelve None para todo lo que no sea estructura porque en el
backtest ese caso lo resuelve el simulador a partir de `sl_stop`. Al llegar a
`calcular_acciones` ese None hacía caer el tamaño a `riesgo / precio`, o sea que
**dejaba de dimensionar por riesgo aunque la estrategia tuviera «Shares por SL»
encendido** — sin error y sin log.

Medido con la configuración real de Jaume, estrategia «RTH prueba 1» (stop 25 %,
riesgo 300 $) sobre WYHG a 5,22 $:

    aviso     ->  57 acciones,  arriesga  75 $
    simulador -> 230 acciones,  arriesga 300 $     <- lo correcto

Un factor 4. Aquí se cruzan las dos vías para CADA tipo de stop y CADA modo de
tamaño, que es la única forma de que no vuelva a divergir una de ellas sola.
"""
import numpy as np
import pytest

from app.services.bot_alerts_engine import calcular_acciones, stop_estimado
from app.services.portfolio_sim import simulate

# Serie plana: así el precio de entrada es exactamente 100,00 y las dos vías
# se comparan sobre el mismo número sin arrastrar diferencias de la vela.
N = 12
PRECIO = 100.0


def _tamano_del_simulador(**kw):
    """Las acciones que abre `portfolio_sim` en su primera entrada."""
    close = np.full(N, PRECIO)
    entries = np.zeros(N, dtype=bool)
    entries[1] = True
    res = simulate(
        close=close, open_=close.copy(), high=close * 1.001, low=close * 0.999,
        entries=entries, exits=np.zeros(N, dtype=bool),
        direction="shortonly", init_cash=1_000_000.0,
        risk_r=300.0, risk_type="FIXED", look_ahead_prevention=True,
        timestamps=(np.arange(N) * 60_000_000_000).astype(np.int64), **kw,
    )
    return res["trades"][0]["size"] if res["trades"] else 0.0


def _tamano_del_aviso(sdef, sl_stop, **kw):
    """Las acciones que propondría el bot al mismo precio."""
    stop = stop_estimado(sdef, None, 0, PRECIO, es_largo=False, sl_stop=sl_stop)
    rm = sdef["risk_management"]
    return calcular_acciones(300.0, PRECIO, stop,
                             bool(rm.get("size_by_sl")), **kw)


def _sdef(tipo, valor, size_by_sl=True, **rm_extra):
    return {"bias": "short", "risk_management": {
        "use_hard_stop": True, "size_by_sl": size_by_sl,
        "hard_stop": {"type": tipo, "value": valor}, **rm_extra}}


# ══ Cada tipo de stop, con «Shares por SL» ════════════════════════════════
# `sl_stop` es la FRACCIÓN que `translate_strategy` calcula para cada tipo; el
# simulador la aplica igual venga de un porcentaje, de un importe fijo o del
# ATR, así que basta con recorrer valores distintos para cubrir los tres.
@pytest.mark.parametrize("tipo,valor,sl_stop", [
    ("Percentage", 25, 0.25),        # el de «RTH prueba 1»
    ("Percentage", 2, 0.02),
    ("Percentage", 60, 0.60),
    ("Fixed Amount", 5, 0.05),       # 5 $ sobre un primer cierre de 100
    ("ATR Multiplier", 2, 0.031),    # ATR medio x multiplicador, ya en fracción
])
def test_por_distancia_al_stop(tipo, valor, sl_stop):
    sim = _tamano_del_simulador(sl_stop=sl_stop, size_by_sl=True)
    bot = _tamano_del_aviso(_sdef(tipo, valor), sl_stop)
    assert bot == pytest.approx(sim), f"{tipo} {valor}: aviso {bot} vs motor {sim}"


def test_el_caso_real_que_lo_destapo():
    """«RTH prueba 1»: stop 25 %, riesgo 300 $. Antes daba 57 y no 230."""
    sim = _tamano_del_simulador(sl_stop=0.25, size_by_sl=True)
    bot = _tamano_del_aviso(_sdef("Percentage", 25), 0.25)
    assert bot == pytest.approx(sim)
    assert bot == pytest.approx(300.0 / 25.0)      # riesgo / distancia
    # Y lo que de verdad importa: que arriesgue lo que dice arriesgar.
    stop = stop_estimado(_sdef("Percentage", 25), None, 0, PRECIO, False, 0.25)
    assert bot * abs(PRECIO - stop) == pytest.approx(300.0)


# ══ Por valor de mercado (sin «Shares por SL») ════════════════════════════
def test_por_valor_de_mercado():
    """Sin `size_by_sl` las dos vías van por precio, y ya coincidían."""
    sim = _tamano_del_simulador(sl_stop=0.25, size_by_sl=False)
    bot = _tamano_del_aviso(_sdef("Percentage", 25, size_by_sl=False), 0.25)
    assert bot == pytest.approx(sim) == pytest.approx(3.0)   # 300 $ / 100 $


# ══ Stop híbrido ══════════════════════════════════════════════════════════
def test_hibrido_el_techo_recorta_igual_en_las_dos_vias():
    """Techo = (max_loss% x capital) / black_swan%, en dólares de exposición."""
    sim = _tamano_del_simulador(sl_stop=0.02, size_by_sl=True, hybrid_stop=True,
                                hybrid_black_swan_pct=500.0,
                                hybrid_max_loss_pct=5.0,
                                hybrid_capital=10_000.0)
    bot = _tamano_del_aviso(
        _sdef("Percentage", 2), 0.02,
        hibrido={"capital": 10_000.0, "black_swan_pct": 500.0, "max_loss_pct": 5.0})
    assert bot == pytest.approx(sim)
    # 5 % de 10.000 = 500 $; / 500 % = 100 $ de exposición; / 100 $ = 1 acción.
    assert bot == pytest.approx(1.0)


def test_hibrido_que_no_muerde_deja_el_tamano_por_sl():
    sim = _tamano_del_simulador(sl_stop=0.25, size_by_sl=True, hybrid_stop=True,
                                hybrid_black_swan_pct=10.0,
                                hybrid_max_loss_pct=90.0,
                                hybrid_capital=10_000.0)
    bot = _tamano_del_aviso(
        _sdef("Percentage", 25), 0.25,
        hibrido={"capital": 10_000.0, "black_swan_pct": 10.0, "max_loss_pct": 90.0})
    assert bot == pytest.approx(sim) == pytest.approx(12.0)   # 300 / 25


# ══ Estilo Cangrejo ═══════════════════════════════════════════════════════
def test_cangrejo_modo_a_aprieta_el_stop_en_las_dos_vias():
    """Stop al 60 % apretado al 10 %: la distancia baja y el tamaño sube."""
    sim = _tamano_del_simulador(sl_stop=0.60, size_by_sl=True,
                                cangrejo_active=True,
                                cangrejo_max_sl_dist_pct=10.0)
    sdef = _sdef("Percentage", 60)
    stop = stop_estimado(sdef, None, 0, PRECIO, False, 0.60)
    from app.services.portfolio_sim import aprieta_stop_cangrejo
    stop = aprieta_stop_cangrejo(PRECIO, stop, 10.0, False)
    bot = calcular_acciones(300.0, PRECIO, stop, True)
    assert bot == pytest.approx(sim) == pytest.approx(30.0)   # 300 / 10


def test_cangrejo_modo_b_topa_igual_en_las_dos_vias():
    """Tope de pérdida del 1 % de 10.000 = 100 $, sobre una distancia de 2 $."""
    sim = _tamano_del_simulador(sl_stop=0.02, size_by_sl=True,
                                cangrejo_active=True,
                                cangrejo_max_loss_at_sl_pct=1.0,
                                hybrid_capital=10_000.0)
    bot = _tamano_del_aviso(
        _sdef("Percentage", 2), 0.02,
        cangrejo={"max_sl_dist_pct": None, "max_loss_pct": 1.0,
                  "capital": 10_000.0})
    assert bot == pytest.approx(sim) == pytest.approx(50.0)   # 100 $ / 2 $


def test_cangrejo_modo_b_tambien_por_valor_de_mercado():
    """A diferencia del híbrido, el Modo B no exige «Shares por SL»."""
    sim = _tamano_del_simulador(sl_stop=0.02, size_by_sl=False,
                                cangrejo_active=True,
                                cangrejo_max_loss_at_sl_pct=1.0,
                                hybrid_capital=10_000.0)
    bot = _tamano_del_aviso(
        _sdef("Percentage", 2, size_by_sl=False), 0.02,
        cangrejo={"max_sl_dist_pct": None, "max_loss_pct": 1.0,
                  "capital": 10_000.0})
    assert bot == pytest.approx(sim) == pytest.approx(3.0)   # el tope no muerde


# ══ Estructura: la vía que YA coincidía, para que siga coincidiendo ═══════
def test_stop_de_estructura_sigue_yendo_por_nivel_stop():
    """Con Market Structure, `stop_estimado` delega en `nivel_stop` y el
    `sl_stop` (que el motor deja en None para este tipo) se ignora."""
    import pandas as pd
    sdef = _sdef("Market Structure (HOD/LOD)", "Previous Max")
    sdef["risk_management"]["hard_stop"]["operator"] = ">="
    sdef["risk_management"]["hard_stop"]["offset_pct"] = 10
    frame = pd.DataFrame({"hod": [PRECIO], "lod": [PRECIO], "pm_high": [PRECIO],
                          "pm_low": [PRECIO], "prev_high": [110.0], "prev_low": [0.0]})
    stop = stop_estimado(sdef, frame, 0, PRECIO, es_largo=False, sl_stop=None)
    assert stop == pytest.approx(121.0)                      # 110 x 1,10
    assert calcular_acciones(300.0, PRECIO, stop, True) == pytest.approx(300.0 / 21.0)


def test_sin_stop_resoluble_no_se_inventa_uno():
    """Sin `sl_stop` y sin estructura no hay stop: mejor None que un número
    falso, que acabaría en un tamaño falso."""
    assert stop_estimado(_sdef("Percentage", 25), None, 0, PRECIO, False, None) is None
    assert stop_estimado(_sdef("Percentage", 25), None, 0, PRECIO, False, 0.0) is None
