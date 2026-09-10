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
# `sl_stop` es la FRACCIÓN que `translate_strategy` calcula para el porcentaje;
# el simulador la aplica sobre el precio de entrada. Los otros tres tipos de stop
# (estructura, ATR e importe fijo) se resuelven como NIVEL y tienen sus tests
# más abajo.
@pytest.mark.parametrize("tipo,valor,sl_stop", [
    ("Percentage", 25, 0.25),        # el de «RTH prueba 1»
    ("Percentage", 2, 0.02),
    ("Percentage", 60, 0.60),
    # «Fixed Amount» tampoco entra ya aqui: desde el 10-sep-2026 es un NIVEL
    # (`entrada -/+ importe`), no una fraccion. Tiene sus tests abajo.
    # El ATR YA NO entra aquí: desde el 10-sep-2026 no se colapsa a fracción,
    # se resuelve como NIVEL con el ATR de la barra. Tiene sus tests abajo.
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


# ══ Stop por ATR: es un NIVEL, no una fracción ════════════════════════════
#
# EL FALLO QUE ARREGLA ESTO (10-sep-2026). El «ATR Multiplier» calculaba su
# `sl_stop` como `media del ATR del DÍA ENTERO / primer cierre del día`. Esa
# media incluye barras POSTERIORES a la entrada, así que miraba al futuro; y
# además daba la misma fracción a todas las entradas del día. Medido sobre un
# día que explota por la tarde: una entrada de la mañana recibía un stop 4,6x
# más ancho del que le tocaba, y dentro de la explosión 5x más estrecho.
#
# Ahora el nivel se resuelve en la barra, `entry -/+ k x ATR[i]`, y por eso el
# ATR viaja al simulador como ARRAY y al bot como columna del frame. Aquí se
# cruzan las dos vías, que es lo único que evita que se separen en silencio.
ATR_BARRA = 2.0
K_ATR = 2.0


def _frame_con_atr(atr_val=ATR_BARRA):
    import pandas as pd
    return pd.DataFrame({"hod": [PRECIO], "lod": [PRECIO], "pm_high": [PRECIO],
                         "pm_low": [PRECIO], "prev_high": [0.0], "prev_low": [0.0],
                         "atr": [atr_val]})


def _sim_atr(atr_val=ATR_BARRA, **kw):
    """El simulador con el stop por ATR. Devuelve el trade entero."""
    close = np.full(N, PRECIO)
    entries = np.zeros(N, dtype=bool)
    entries[1] = True
    res = simulate(
        close=close, open_=close.copy(), high=close * 1.001, low=close * 0.999,
        entries=entries, exits=np.zeros(N, dtype=bool),
        direction="shortonly", init_cash=1_000_000.0,
        risk_r=300.0, risk_type="FIXED", look_ahead_prevention=True,
        timestamps=(np.arange(N) * 60_000_000_000).astype(np.int64),
        hs_type="ATR Multiplier", hs_value=K_ATR,
        atrs=np.full(N, atr_val), **kw,
    )
    return res["trades"][0] if res["trades"] else None


@pytest.mark.parametrize("atr_val", [0.5, 2.0, 6.0])
def test_atr_el_nivel_coincide_en_las_dos_vias(atr_val):
    """El stop del aviso y el del simulador son el mismo precio."""
    t = _sim_atr(atr_val, size_by_sl=True)
    bot = stop_estimado(_sdef("ATR Multiplier", K_ATR), _frame_con_atr(atr_val),
                        0, PRECIO, es_largo=False, sl_stop=None)
    assert bot == pytest.approx(PRECIO + K_ATR * atr_val)
    assert bot == pytest.approx(t["stop_loss"])


@pytest.mark.parametrize("atr_val", [0.5, 2.0, 6.0])
def test_atr_el_tamano_coincide_en_las_dos_vias(atr_val):
    """Y con «Shares por SL», el mismo número de acciones."""
    sim = _sim_atr(atr_val, size_by_sl=True)["size"]
    stop = stop_estimado(_sdef("ATR Multiplier", K_ATR), _frame_con_atr(atr_val),
                         0, PRECIO, es_largo=False, sl_stop=None)
    bot = calcular_acciones(300.0, PRECIO, stop, True)
    assert bot == pytest.approx(sim)
    assert bot == pytest.approx(300.0 / (K_ATR * atr_val))


def test_atr_el_stop_se_mueve_con_el_atr():
    """Lo que la versión vieja NO hacía: dos ATR distintos, dos stops distintos.
    Antes las dos entradas del día compartían la misma fracción."""
    flojo = _sim_atr(0.5, size_by_sl=True)
    fuerte = _sim_atr(6.0, size_by_sl=True)
    assert flojo["stop_loss"] != fuerte["stop_loss"]
    assert flojo["size"] > fuerte["size"]        # stop más cerca, más acciones


def test_atr_sin_atr_no_se_entra():
    """Durante las primeras barras del día el ATR es NaN. Sin ATR no se sabe
    cuánto se mueve esto: no se entra, ni en el motor ni en el aviso."""
    close = np.full(N, PRECIO)
    entries = np.zeros(N, dtype=bool)
    entries[1] = True
    res = simulate(
        close=close, open_=close.copy(), high=close * 1.001, low=close * 0.999,
        entries=entries, exits=np.zeros(N, dtype=bool),
        direction="shortonly", init_cash=1_000_000.0, risk_r=300.0,
        risk_type="FIXED", look_ahead_prevention=True,
        timestamps=(np.arange(N) * 60_000_000_000).astype(np.int64),
        hs_type="ATR Multiplier", hs_value=K_ATR,
        atrs=np.full(N, np.nan), size_by_sl=True,
    )
    assert res["trades"] == []
    import pandas as pd
    frame = _frame_con_atr(float("nan"))
    assert stop_estimado(_sdef("ATR Multiplier", K_ATR), frame, 0, PRECIO,
                         es_largo=False, sl_stop=None) is None


def test_atr_hibrido_recorta_igual_en_las_dos_vias():
    """El techo híbrido muerde sobre el tamaño que salió del ATR."""
    sim = _sim_atr(size_by_sl=True, hybrid_stop=True,
                   hybrid_black_swan_pct=50.0, hybrid_max_loss_pct=0.05)["size"]
    stop = stop_estimado(_sdef("ATR Multiplier", K_ATR, hybrid_stop=True,
                               hybrid_black_swan_pct=50.0,
                               hybrid_max_loss_pct=0.05),
                         _frame_con_atr(), 0, PRECIO, es_largo=False, sl_stop=None)
    bot = calcular_acciones(300.0, PRECIO, stop, True,
                            hibrido={"black_swan_pct": 50.0, "max_loss_pct": 0.05,
                                     "capital": 1_000_000.0})
    assert bot == pytest.approx(sim)


def test_atr_cangrejo_modo_a_aprieta_el_stop():
    """Modo A: el stop nunca a más del X % del entry. Con ATR 6 el stop iría a
    112 (12 %); con tope del 3 % pasa a 103."""
    t = _sim_atr(6.0, size_by_sl=True, cangrejo_active=True,
                 cangrejo_max_sl_dist_pct=3.0)
    assert t["stop_loss"] == pytest.approx(103.0)
    assert t["size"] == pytest.approx(300.0 / 3.0)


def test_atr_cangrejo_modo_b_topa_el_tamano():
    """Modo B: el SL nunca cuesta más del X % de la cuenta. Distancia 4 $ y
    0,01 % de 1.000.000 = 100 $ -> 25 acciones, que topa las 75."""
    t = _sim_atr(size_by_sl=True, cangrejo_active=True,
                 cangrejo_max_loss_at_sl_pct=0.01)
    assert t["size"] == pytest.approx(25.0)


# ══ Respaldo del stop por ATR ═════════════════════════════════════════════
#
# Durante las primeras velas del día el ATR(14) no existe todavía. Sin respaldo
# no se entra; con `atr_fallback_pct` se entra con un stop en % del precio SOLO
# en ese tramo. Lo que se guarda aquí es que el respaldo NO se salta ninguno de
# los topes: pasa por Cangrejo A y B, por el híbrido y por «Shares por SL»
# exactamente igual que el ATR, porque los tres miran el PRECIO del stop y no
# la fracción.
FB_PCT = 5.0     # respaldo del 5 % -> stop de un corto en 105, distancia 5


def _sim_sin_atr(**kw):
    """El simulador con el ATR en NaN, o sea en el tramo del respaldo."""
    close = np.full(N, PRECIO)
    entries = np.zeros(N, dtype=bool)
    entries[1] = True
    res = simulate(
        close=close, open_=close.copy(), high=close * 1.001, low=close * 0.999,
        entries=entries, exits=np.zeros(N, dtype=bool),
        direction="shortonly", init_cash=1_000_000.0,
        risk_r=300.0, risk_type="FIXED", look_ahead_prevention=True,
        timestamps=(np.arange(N) * 60_000_000_000).astype(np.int64),
        hs_type="ATR Multiplier", hs_value=K_ATR,
        atrs=np.full(N, np.nan), **kw,
    )
    return res["trades"][0] if res["trades"] else None


def test_respaldo_sin_el_no_se_entra_con_el_si():
    assert _sim_sin_atr(size_by_sl=True) is None
    t = _sim_sin_atr(size_by_sl=True, hs_atr_fallback_pct=FB_PCT)
    assert t is not None
    assert t["stop_loss"] == pytest.approx(PRECIO * (1 + FB_PCT / 100.0))   # 105


def test_respaldo_por_distancia_al_stop():
    """riesgo / distancia = 300 / 5 = 60 acciones."""
    t = _sim_sin_atr(size_by_sl=True, hs_atr_fallback_pct=FB_PCT)
    assert t["size"] == pytest.approx(60.0)


def test_respaldo_por_valor_de_mercado():
    """Sin «Shares por SL» se dimensiona por precio, como cualquier otro stop."""
    t = _sim_sin_atr(size_by_sl=False, hs_atr_fallback_pct=FB_PCT)
    assert t["size"] == pytest.approx(3.0)          # 300 $ / 100 $


def test_respaldo_pasa_por_el_hibrido():
    """(0,05 % x 1.000.000) / 50 % = 1.000 $ -> 10 acciones, que topa las 60."""
    t = _sim_sin_atr(size_by_sl=True, hs_atr_fallback_pct=FB_PCT,
                     hybrid_stop=True, hybrid_black_swan_pct=50.0,
                     hybrid_max_loss_pct=0.05)
    assert t["size"] == pytest.approx(10.0)


def test_respaldo_pasa_por_cangrejo_modo_a():
    """Modo A: el stop del respaldo (5 %) se aprieta al 3 % y el tamaño sube."""
    t = _sim_sin_atr(size_by_sl=True, hs_atr_fallback_pct=FB_PCT,
                     cangrejo_active=True, cangrejo_max_sl_dist_pct=3.0)
    assert t["stop_loss"] == pytest.approx(103.0)
    assert t["size"] == pytest.approx(100.0)        # 300 / 3


def test_respaldo_pasa_por_cangrejo_modo_b():
    """Modo B: 0,01 % de 1.000.000 = 100 $ entre una distancia de 5 -> 20."""
    t = _sim_sin_atr(size_by_sl=True, hs_atr_fallback_pct=FB_PCT,
                     cangrejo_active=True, cangrejo_max_loss_at_sl_pct=0.01)
    assert t["size"] == pytest.approx(20.0)


def test_respaldo_paridad_python_jit():
    """El kernel tiene su propia copia de la rama: si divergen, el backtest da
    una cosa u otra según BACKTEST_NUMBA_SIM, sin avisar."""
    from app.services.sim_dispatch import simulate_jit
    close = np.full(N, PRECIO)
    entries = np.zeros(N, dtype=bool)
    entries[1] = True
    base = dict(
        close=close, open_=close.copy(), high=close * 1.001, low=close * 0.999,
        entries=entries, exits=np.zeros(N, dtype=bool), direction="shortonly",
        init_cash=1_000_000.0, risk_r=300.0, risk_type="FIXED",
        look_ahead_prevention=True,
        timestamps=(np.arange(N) * 60_000_000_000).astype(np.int64),
        hs_type="ATR Multiplier", hs_value=K_ATR, atrs=np.full(N, np.nan),
        hs_atr_fallback_pct=FB_PCT, size_by_sl=True,
        cangrejo_active=True, cangrejo_max_sl_dist_pct=3.0,
    )
    t_py = simulate(**base)["trades"][0]
    t_jit = simulate_jit(**base)["trades"][0]
    for campo in ("stop_loss", "size", "entry_price"):
        assert t_py[campo] == pytest.approx(t_jit[campo]), campo


def test_respaldo_el_aviso_dice_lo_mismo_que_el_motor():
    """Y el bot, que resuelve su stop por otro camino."""
    sim = _sim_sin_atr(size_by_sl=True, hs_atr_fallback_pct=FB_PCT)
    sdef = _sdef("ATR Multiplier", K_ATR)
    sdef["risk_management"]["hard_stop"]["atr_fallback_pct"] = FB_PCT
    stop = stop_estimado(sdef, _frame_con_atr(float("nan")), 0, PRECIO,
                         es_largo=False, sl_stop=None)
    assert stop == pytest.approx(sim["stop_loss"])
    assert calcular_acciones(300.0, PRECIO, stop, True) == pytest.approx(sim["size"])


def test_respaldo_solo_actua_donde_falta_el_atr():
    """Con ATR válido manda el ATR, no el respaldo: 2 x 2 = 4 de distancia
    (75 acciones), no el 5 % del respaldo (60)."""
    t = _sim_atr(size_by_sl=True, hs_atr_fallback_pct=FB_PCT)
    assert t["stop_loss"] == pytest.approx(PRECIO + K_ATR * ATR_BARRA)
    assert t["size"] == pytest.approx(75.0)


# ══ El ULTIMO PIVOTE como nivel de stop ═══════════════════════════════════
#
# A diferencia de HOD o «Previous Max», que son extremos CORRIDOS y nunca bajan,
# el pivote es el último sitio donde el precio giró de verdad. Con la secuencia
# 100 -> 110 -> 105 -> 100, «Previous Max» y el pivote alto valen los dos 110;
# pero si luego el precio hace un techo más bajo, el pivote baja con él y el
# «Previous Max» se queda arriba para siempre. Para un stop eso es la diferencia
# entre estar pegado al nivel o a diez figuras de distancia.
#
# El pivote se confirma con RETARDO (N velas), y ese retardo es justo lo que lo
# hace causal. Mientras no hay ninguno confirmado, el motor cae a su respaldo.


def _serie_con_pivote():
    """100, 110, 105, 100, 100... -> con ventana 1, pivote alto = 110."""
    px = np.full(N, 100.0)
    px[1] = 110.0
    px[2] = 105.0
    return px


def _sim_pivote(valor="Ultimo pivote alto", win=1, entrada=5, **kw):
    from app.services.portfolio_sim import pivotes_para_stop
    px = _serie_con_pivote()
    ts = (np.arange(N) * 60_000_000_000).astype(np.int64)
    arrays = {"high": px, "low": px, "timestamp": ts.astype("datetime64[ns]")}
    piv_h, piv_l = pivotes_para_stop(arrays, win)
    entries = np.zeros(N, dtype=bool)
    entries[entrada] = True
    res = simulate(
        close=px, open_=px.copy(), high=px, low=px,
        entries=entries, exits=np.zeros(N, dtype=bool),
        direction="shortonly", init_cash=1_000_000.0,
        risk_r=300.0, risk_type="FIXED", look_ahead_prevention=True,
        timestamps=ts,
        hs_type="Market Structure (HOD/LOD)", hs_value=valor,
        hs_operator=">=", hs_offset_pct=0.0,
        pivot_highs=piv_h, pivot_lows=piv_l, **kw,
    )
    return (res["trades"][0] if res["trades"] else None), piv_h, piv_l


def test_pivote_el_stop_es_el_ultimo_techo():
    t, piv_h, _ = _sim_pivote(size_by_sl=True)
    assert piv_h[5] == pytest.approx(110.0)       # confirmado desde la vela 2
    assert t is not None
    assert t["stop_loss"] == pytest.approx(110.0)
    assert t["size"] == pytest.approx(300.0 / 10.0)   # riesgo / distancia


def test_pivote_sin_confirmar_cae_al_respaldo_del_5_por_ciento():
    """QUE PASA MIENTRAS NO HAY NINGUN PIVOTE CONFIRMADO.

    Con ventana 4 el pivote no llega a tiempo para una entrada en la vela 3. El
    motor NO rechaza la operacion: cae al respaldo del 5 % que el stop
    estructural aplica desde siempre cuando el nivel no se resuelve (mismo trato
    que un HOD que todavia no existe). No es un caso especial del pivote.

    OJO: es distinto del stop por ATR, donde sin ATR NO se entra salvo que se
    ponga `atr_fallback_pct`. Si algun dia se quiere la misma politica aqui,
    hay que cambiarla para TODOS los niveles estructurales, no solo el pivote.
    """
    t, piv_h, _ = _sim_pivote(win=4, entrada=3, size_by_sl=True)
    assert np.isnan(piv_h[3])                      # no hay pivote todavia
    assert t is not None
    assert t["stop_loss"] == pytest.approx(105.0)  # 100 x 1,05 (corto)
    assert t["size"] == pytest.approx(60.0)        # 300 / 5


def test_pivote_paridad_python_jit():
    from app.services.sim_dispatch import simulate_jit
    from app.services.portfolio_sim import pivotes_para_stop
    px = _serie_con_pivote()
    ts = (np.arange(N) * 60_000_000_000).astype(np.int64)
    piv_h, piv_l = pivotes_para_stop(
        {"high": px, "low": px, "timestamp": ts.astype("datetime64[ns]")}, 1)
    entries = np.zeros(N, dtype=bool)
    entries[5] = True
    base = dict(
        close=px, open_=px.copy(), high=px, low=px,
        entries=entries, exits=np.zeros(N, dtype=bool), direction="shortonly",
        init_cash=1_000_000.0, risk_r=300.0, risk_type="FIXED",
        look_ahead_prevention=True, timestamps=ts,
        hs_type="Market Structure (HOD/LOD)", hs_value="Ultimo pivote alto",
        hs_operator=">=", hs_offset_pct=0.0,
        pivot_highs=piv_h, pivot_lows=piv_l, size_by_sl=True,
    )
    t_py = simulate(**base)["trades"][0]
    t_jit = simulate_jit(**base)["trades"][0]
    for campo in ("stop_loss", "size", "entry_price"):
        assert t_py[campo] == pytest.approx(t_jit[campo]), campo


def test_pivote_el_aviso_dice_lo_mismo_que_el_motor():
    """El bot resuelve el pivote por su propio camino (`nivel_stop`), con la
    MISMA función. Si alguna vez se separan, esto lo caza."""
    import pandas as pd
    from app.services.portfolio_sim import pivotes_para_stop
    px = _serie_con_pivote()
    ts = pd.to_datetime((np.arange(N) * 60_000_000_000).astype("datetime64[ns]"))
    frame = pd.DataFrame({
        "high": px, "low": px, "close": px, "timestamp": ts,
        "hod": px, "lod": px, "pm_high": px, "pm_low": px,
        "prev_high": np.zeros(N), "prev_low": np.zeros(N),
    })
    sdef = _sdef("Market Structure (HOD/LOD)", "Ultimo pivote alto")
    sdef["risk_management"]["hard_stop"]["operator"] = ">="
    sdef["risk_management"]["hard_stop"]["offset_pct"] = 0
    sdef["risk_management"]["hard_stop"]["pivot_window"] = 1
    stop = stop_estimado(sdef, frame, 5, 100.0, es_largo=False, sl_stop=None)
    t, _, _ = _sim_pivote(size_by_sl=True)
    assert stop == pytest.approx(110.0)
    assert stop == pytest.approx(t["stop_loss"])
    assert calcular_acciones(300.0, 100.0, stop, True) == pytest.approx(t["size"])


def test_pivote_pasa_por_cangrejo_y_por_el_hibrido():
    """Como cualquier otro nivel: los topes miran el precio del stop."""
    t_a, _, _ = _sim_pivote(size_by_sl=True, cangrejo_active=True,
                            cangrejo_max_sl_dist_pct=4.0)
    assert t_a["stop_loss"] == pytest.approx(104.0)      # apretado del 10 % al 4 %
    assert t_a["size"] == pytest.approx(75.0)            # 300 / 4

    t_b, _, _ = _sim_pivote(size_by_sl=True, cangrejo_active=True,
                            cangrejo_max_loss_at_sl_pct=0.01)
    assert t_b["size"] == pytest.approx(10.0)            # 100 $ / 10 de distancia

    t_h, _, _ = _sim_pivote(size_by_sl=True, hybrid_stop=True,
                            hybrid_black_swan_pct=50.0, hybrid_max_loss_pct=0.05)
    assert t_h["size"] == pytest.approx(10.0)            # 1.000 $ / 100 $ de precio


# ══ El respaldo del stop estructural, ahora ajustable ═════════════════════
#
# Cuando el nivel no se resuelve (el pivote sin confirmar, un PMH que no existe)
# el motor cae a un respaldo en % del precio. Era un 5 % CLAVADO en el código, y
# estaba escrito tres veces: en portfolio_sim, en el kernel JIT y en el bot. Se
# hace ajustable con `hard_stop.struct_fallback_pct`, y sin él sigue siendo 5.


@pytest.mark.parametrize("pct,stop_esperado,size_esperado", [
    (None, 105.0, 60.0),      # el 5 % de siempre
    (2.0, 102.0, 150.0),      # más ceñido -> más acciones
    (12.0, 112.0, 25.0),      # más ancho  -> menos acciones
])
def test_respaldo_estructural_es_ajustable(pct, stop_esperado, size_esperado):
    kw = {} if pct is None else {"hs_struct_fallback_pct": pct}
    t, piv_h, _ = _sim_pivote(win=4, entrada=3, size_by_sl=True, **kw)
    assert np.isnan(piv_h[3])                       # no hay pivote todavía
    assert t["stop_loss"] == pytest.approx(stop_esperado)
    assert t["size"] == pytest.approx(size_esperado)


def test_respaldo_estructural_paridad_python_jit():
    """El 5 % estaba escrito por separado en el kernel: si uno se ajusta y el
    otro no, el backtest da una cosa u otra según BACKTEST_NUMBA_SIM."""
    from app.services.sim_dispatch import simulate_jit
    from app.services.portfolio_sim import pivotes_para_stop
    px = _serie_con_pivote()
    ts = (np.arange(N) * 60_000_000_000).astype(np.int64)
    piv_h, piv_l = pivotes_para_stop(
        {"high": px, "low": px, "timestamp": ts.astype("datetime64[ns]")}, 4)
    entries = np.zeros(N, dtype=bool)
    entries[3] = True
    base = dict(
        close=px, open_=px.copy(), high=px, low=px,
        entries=entries, exits=np.zeros(N, dtype=bool), direction="shortonly",
        init_cash=1_000_000.0, risk_r=300.0, risk_type="FIXED",
        look_ahead_prevention=True, timestamps=ts,
        hs_type="Market Structure (HOD/LOD)", hs_value="Ultimo pivote alto",
        hs_operator=">=", hs_offset_pct=0.0,
        pivot_highs=piv_h, pivot_lows=piv_l, size_by_sl=True,
        hs_struct_fallback_pct=3.0,
    )
    t_py = simulate(**base)["trades"][0]
    t_jit = simulate_jit(**base)["trades"][0]
    assert t_py["stop_loss"] == pytest.approx(103.0)
    assert t_py["stop_loss"] == pytest.approx(t_jit["stop_loss"])
    assert t_py["size"] == pytest.approx(t_jit["size"])


def test_respaldo_estructural_el_aviso_dice_lo_mismo():
    """El bot tenía su propia copia del 5 %."""
    import pandas as pd
    px = _serie_con_pivote()
    ts = pd.to_datetime((np.arange(N) * 60_000_000_000).astype("datetime64[ns]"))
    frame = pd.DataFrame({
        "high": px, "low": px, "close": px, "timestamp": ts,
        "hod": np.zeros(N), "lod": np.zeros(N), "pm_high": np.zeros(N),
        "pm_low": np.zeros(N), "prev_high": np.zeros(N), "prev_low": np.zeros(N),
    })
    sdef = _sdef("Market Structure (HOD/LOD)", "Ultimo pivote alto")
    sdef["risk_management"]["hard_stop"].update(
        {"operator": ">=", "offset_pct": 0, "pivot_window": 4,
         "struct_fallback_pct": 3.0})
    stop = stop_estimado(sdef, frame, 3, 100.0, es_largo=False, sl_stop=None)
    t, _, _ = _sim_pivote(win=4, entrada=3, size_by_sl=True,
                          hs_struct_fallback_pct=3.0)
    assert stop == pytest.approx(103.0)
    assert stop == pytest.approx(t["stop_loss"])


# ══ IMPORTE FIJO: el bug del cierre de la primera vela ════════════════════
#
# EL FALLO (corregido el 10-sep-2026). «Fixed Amount» se convertía en fracción
# dividiendo el importe entre el cierre de la PRIMERA VELA DEL DÍA, y esa
# fracción se aplicaba luego al precio de entrada. O sea que «15 centavos» solo
# eran 15 centavos si entrabas exactamente al precio de apertura; entrando más
# arriba, el stop se ensanchaba solo y nada lo decía.
#
# Con un día que abre en 70 y una entrada en 100, un importe de 5 $ daba:
#     fracción = 5 / 70 = 0,0714  ->  stop = 100 x 1,0714 = 107,14
# cuando lo que se pidió eran 5 $, o sea 105.
IMPORTE = 5.0


def _sim_importe(primer_cierre=PRECIO, **kw):
    """Serie que ABRE en `primer_cierre` y entra a 100, para destapar el bug."""
    close = np.full(N, PRECIO)
    close[0] = primer_cierre
    entries = np.zeros(N, dtype=bool)
    entries[3] = True
    res = simulate(
        close=close, open_=close.copy(), high=close * 1.001, low=close * 0.999,
        entries=entries, exits=np.zeros(N, dtype=bool),
        direction="shortonly", init_cash=1_000_000.0,
        risk_r=300.0, risk_type="FIXED", look_ahead_prevention=True,
        timestamps=(np.arange(N) * 60_000_000_000).astype(np.int64),
        hs_type="Fixed Amount", hs_value=IMPORTE, **kw,
    )
    return res["trades"][0] if res["trades"] else None


@pytest.mark.parametrize("primer_cierre", [70.0, 100.0, 140.0])
def test_importe_fijo_no_depende_de_la_primera_vela(primer_cierre):
    """5 $ son 5 $, abra el día donde abra. Este es el test del bug."""
    t = _sim_importe(primer_cierre, size_by_sl=True)
    assert t["stop_loss"] == pytest.approx(PRECIO + IMPORTE)   # 105, siempre
    assert t["size"] == pytest.approx(300.0 / IMPORTE)         # 60 acciones


def test_importe_fijo_el_aviso_dice_lo_mismo():
    sim = _sim_importe(70.0, size_by_sl=True)
    stop = stop_estimado(_sdef("Fixed Amount", IMPORTE), None, 0, PRECIO,
                         es_largo=False, sl_stop=None)
    assert stop == pytest.approx(105.0)
    assert stop == pytest.approx(sim["stop_loss"])
    assert calcular_acciones(300.0, PRECIO, stop, True) == pytest.approx(sim["size"])


def test_importe_fijo_paridad_python_jit():
    from app.services.sim_dispatch import simulate_jit
    close = np.full(N, PRECIO)
    close[0] = 70.0
    entries = np.zeros(N, dtype=bool)
    entries[3] = True
    base = dict(
        close=close, open_=close.copy(), high=close * 1.001, low=close * 0.999,
        entries=entries, exits=np.zeros(N, dtype=bool), direction="shortonly",
        init_cash=1_000_000.0, risk_r=300.0, risk_type="FIXED",
        look_ahead_prevention=True,
        timestamps=(np.arange(N) * 60_000_000_000).astype(np.int64),
        hs_type="Fixed Amount", hs_value=IMPORTE, size_by_sl=True,
    )
    t_py = simulate(**base)["trades"][0]
    t_jit = simulate_jit(**base)["trades"][0]
    assert t_py["stop_loss"] == pytest.approx(105.0)
    assert t_py["stop_loss"] == pytest.approx(t_jit["stop_loss"])
    assert t_py["size"] == pytest.approx(t_jit["size"])


def test_importe_fijo_pasa_por_cangrejo_y_el_hibrido():
    t_a = _sim_importe(size_by_sl=True, cangrejo_active=True,
                       cangrejo_max_sl_dist_pct=2.0)
    assert t_a["stop_loss"] == pytest.approx(102.0)      # apretado de 5 $ a 2 %
    t_b = _sim_importe(size_by_sl=True, cangrejo_active=True,
                       cangrejo_max_loss_at_sl_pct=0.01)
    assert t_b["size"] == pytest.approx(20.0)            # 100 $ / 5 de distancia
    t_h = _sim_importe(size_by_sl=True, hybrid_stop=True,
                       hybrid_black_swan_pct=50.0, hybrid_max_loss_pct=0.05)
    assert t_h["size"] == pytest.approx(10.0)
