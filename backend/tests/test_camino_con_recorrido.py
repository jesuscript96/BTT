# -*- coding: utf-8 -*-
"""Camino de condiciones (Alvaro, PRD 2026-09-16) + disparo por recorrido
(sailor, 2026-09-16): integrados el 17-sep.

El recorrido del precio dentro de un camino va, por defecto, como PRIMER
paso (Jaume, 17-sep): una condicion inicial que engancha por flanco como las
demas y, una vez cumplida, da paso al siguiente aunque luego el precio se
vuelva. Con `move.pos = "last"` se exige en la vela del disparo, pegado al
ultimo paso. Un nivel normal con recorrido y un camino sin recorrido siguen
exactamente como estaban (lo vigilan sus propias suites).
"""
import numpy as np
import pandas as pd

from app.services.portfolio_sim import simulate, _recorrido_cumplido
from app.services.strategy_engine import _parse_pyr_move

CASH, RISK, N = 10000.0, 100.0, 20


def _dia(closes):
    n = len(closes)
    close = np.asarray(closes, dtype=float)
    open_ = close.copy()
    high = close + 0.05
    low = close - 0.05
    ts = pd.date_range("2026-09-17 04:00", periods=n, freq="1min")
    return open_, high, low, close, ts.values.astype("datetime64[ns]").astype(np.int64)


def _senal(*barras, n=N):
    s = np.zeros(n, dtype=bool)
    for b in barras:
        s[b] = True
    return s


def _rango(desde, hasta, n=N):
    s = np.zeros(n, dtype=bool)
    s[desde:hasta + 1] = True
    return s


def _nivel(pasos=None, senal=None, move=None, max_fires=1):
    nv = {
        "action": "add", "capital_frac": 0.0, "max_fires": max_fires,
        "unit": "usd", "amount_usd": 100.0, "size_by_sl": False,
        "hybrid_stop": False, "hybrid_black_swan_pct": None,
        "hybrid_max_loss_pct": None, "group": 0, "sequential": False,
        "move": move,
    }
    if pasos is not None:
        nv["steps_signals"] = pasos
        nv["same_bar"] = True
    else:
        nv["signals"] = senal
    return nv


def _correr(closes, niveles, entrada=1, salida=18):
    open_, high, low, close, ts = _dia(closes)
    hods = np.maximum.accumulate(high)
    lods = np.minimum.accumulate(low)
    prev_h = np.empty_like(hods); prev_h[0] = high[0]; prev_h[1:] = hods[:-1]
    prev_l = np.empty_like(lods); prev_l[0] = low[0]; prev_l[1:] = lods[:-1]
    res = simulate(
        close=close, open_=open_, high=high, low=low,
        entries=_senal(entrada), exits=_senal(salida), direction="shortonly",
        init_cash=CASH, risk_r=RISK, risk_type="FIXED",
        fees=0.0, fee_type="PERCENT", slippage=0.0, look_ahead_prevention=True,
        pyramid_levels=niveles, pyramid_sequential=False, timestamps=ts,
        hods=hods, lods=lods, prev_highs=prev_h, prev_lows=prev_l,
    )
    return [e["idx"] for t in res["trades"] for e in (t.get("pyr_executions") or []) if e["kind"] == "add"]


MV = {"pct": 5.0, "dir": "favor", "ref": "entry"}          # pos ausente = "first"
MV_LAST = {**MV, "pos": "last"}


def test_recorrido_cumplido_es_la_misma_regla_de_siempre():
    # corto: a favor = hacia abajo
    assert _recorrido_cumplido(MV, 9.5, 10.0, 0.0, False) is True
    assert _recorrido_cumplido(MV, 9.6, 10.0, 0.0, False) is False
    assert _recorrido_cumplido(MV, 10.5, 10.0, 0.0, True) is True
    # "desde el ultimo disparo" con ultimo precio; sin el, la entrada
    assert _recorrido_cumplido({**MV, "ref": "last"}, 9.5, 10.0, 9.9, False) is False
    assert _recorrido_cumplido({**MV, "ref": "last"}, 9.5, 10.0, 0.0, False) is True
    assert _recorrido_cumplido({**MV, "dir": "contra"}, 10.5, 10.0, 0.0, False) is True
    assert _recorrido_cumplido(MV, 9.0, 0.0, 0.0, False) is False


def test_el_compilador_lee_move_pos_y_por_defecto_es_primer_paso():
    base = {"trigger": "move", "move_pct": 5}
    assert _parse_pyr_move(base)["pos"] == "first"
    assert _parse_pyr_move({**base, "move_pos": "last"})["pos"] == "last"
    assert _parse_pyr_move({**base, "move_pos": "disparo"})["pos"] == "last"
    assert _parse_pyr_move({**base, "move_pos": "first"})["pos"] == "first"


def test_por_defecto_el_recorrido_es_el_primer_paso_y_no_hace_falta_que_se_mantenga():
    """Corto a 10 (fill en la barra 2). El precio llega al 5 % a favor en la
    barra 4 (engancha el recorrido) y se VUELVE en la 6 (ya no lo cumple).
    A engancha en la 8 y B en la 10: dispara con B (fill en la 11) aunque
    en ese momento el precio este por encima de la entrada."""
    closes = [10.0] * 4 + [9.4, 9.4] + [10.3] * 14
    con = _correr(closes, [_nivel(pasos=[_senal(8), _senal(10)], move=MV)])
    assert con == [11]


def test_el_primer_paso_es_el_recorrido_y_los_de_condiciones_esperan_su_turno():
    """A es cierta en la barra 3, ANTES de que el precio llegue al 5 % (barra
    5): no cuenta, porque A no tiene el turno hasta que engancha el recorrido.
    Con A otra vez en la 7 y B en la 9, dispara con B (fill en la 10)."""
    closes = [10.0] * 5 + [9.4] * 15
    assert _correr(closes, [_nivel(pasos=[_senal(3, 7), _senal(9)], move=MV)]) == [10]
    # Sin la segunda A, el camino se queda esperando: cero anadidos.
    assert _correr(closes, [_nivel(pasos=[_senal(3), _senal(9)], move=MV)]) == []


def test_recorrido_ya_cumplido_al_entrar_engancha_en_la_primera_vela():
    """Como cualquier paso (Q2=A): si al entrar el precio ya lleva el recorrido,
    el primer paso engancha en la primera vela post-entrada y sigue con A y B."""
    closes = [10.0, 10.0, 10.0, 9.4] + [9.4] * 16     # fill en la 2 a 10; la 3 ya a 9,4
    assert _correr(closes, [_nivel(pasos=[_senal(5), _senal(7)], move=MV)]) == [8]


def test_con_pos_last_el_recorrido_se_exige_en_el_disparo():
    """La forma alternativa: A engancha en la 4; B es cierta de la 6 en
    adelante, pero el 5 % a favor solo llega en la 9: dispara ahi (fill 10)."""
    closes = [10.0] * 9 + [9.4] * 11
    assert _correr(closes, [_nivel(pasos=[_senal(4), _rango(6, N - 1)], move=MV_LAST)]) == [10]
    # y no toca a los pasos intermedios: A engancha en la 4 sin recorrido
    closes2 = [10.0] * 5 + [9.4] * 15
    assert _correr(closes2, [_nivel(pasos=[_senal(4), _senal(6)], move=MV_LAST)]) == [7]


def test_un_camino_sin_recorrido_y_un_nivel_normal_siguen_igual():
    closes = [10.0] * 9 + [9.4] * 11
    assert _correr(closes, [_nivel(pasos=[_senal(4), _rango(6, N - 1)])]) == [7]
    # nivel normal con recorrido: condiciones AND recorrido, con flanco (16-sep)
    assert _correr(closes, [_nivel(senal=_rango(4, N - 1), move=MV)]) == [10]
