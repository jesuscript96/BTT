# -*- coding: utf-8 -*-
"""Camino de condiciones (Alvaro, PRD 2026-09-16) + disparo por recorrido
(sailor, 2026-09-16): integrados el 17-sep.

El recorrido del precio va pegado al ULTIMO paso del camino: los pasos
intermedios enganchan por sus condiciones y el ultimo solo engancha (y
dispara) en la primera vela en que se cumple Y el precio lleva el recorrido
pedido. Un nivel normal con recorrido y un camino sin recorrido siguen
exactamente como estaban (lo vigilan sus propias suites).
"""
import numpy as np
import pandas as pd

from app.services.portfolio_sim import simulate, _recorrido_cumplido

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


def test_recorrido_cumplido_es_la_misma_regla_de_siempre():
    mv = {"pct": 5.0, "dir": "favor", "ref": "entry"}
    # corto: a favor = hacia abajo
    assert _recorrido_cumplido(mv, 9.5, 10.0, 0.0, False) is True
    assert _recorrido_cumplido(mv, 9.6, 10.0, 0.0, False) is False
    assert _recorrido_cumplido(mv, 10.5, 10.0, 0.0, True) is True
    # "desde el ultimo disparo" con ultimo precio; sin el, la entrada
    assert _recorrido_cumplido({**mv, "ref": "last"}, 9.5, 10.0, 9.9, False) is False
    assert _recorrido_cumplido({**mv, "ref": "last"}, 9.5, 10.0, 0.0, False) is True
    assert _recorrido_cumplido({**mv, "dir": "contra"}, 10.5, 10.0, 0.0, False) is True
    assert _recorrido_cumplido(mv, 9.0, 0.0, 0.0, False) is False


def test_el_recorrido_va_pegado_al_ultimo_paso_del_camino():
    """Corto a 10 (fill en la barra 2). A engancha en la 4. B es cierta de la
    6 en adelante, pero el precio solo lleva un 5 % a favor (<= 9,5) desde la
    barra 9: el camino dispara ahi (fill en la 10), no en la 6."""
    closes = [10.0] * 9 + [9.4] * 11
    mv = {"pct": 5.0, "dir": "favor", "ref": "entry"}
    con = _correr(closes, [_nivel(pasos=[_senal(4), _rango(6, N - 1)], move=mv)])
    assert con == [10]
    # El mismo camino sin recorrido dispara en cuanto engancha B (fill en la 7).
    sin = _correr(closes, [_nivel(pasos=[_senal(4), _rango(6, N - 1)])])
    assert sin == [7]


def test_el_recorrido_no_toca_a_los_pasos_intermedios():
    """A (paso 1) engancha en la barra 4 aunque el precio no haya recorrido
    nada: el recorrido solo condiciona al ultimo paso. Con B en la barra 6 y
    precio ya con el 5 % desde la 5, dispara con B (fill en la 7)."""
    closes = [10.0] * 5 + [9.4] * 15
    mv = {"pct": 5.0, "dir": "favor", "ref": "entry"}
    assert _correr(closes, [_nivel(pasos=[_senal(4), _senal(6)], move=mv)]) == [7]


def test_el_ultimo_paso_no_engancha_sin_recorrido_y_no_se_queda_colgado():
    """B solo es cierta en la barra 6 y el recorrido no llega hasta la 9: el
    ultimo paso no engancha en la 6 (no hay recorrido) y en la 9 ya no hay B:
    cero anadidos, y el nivel sigue vivo para una B posterior (barra 12)."""
    closes = [10.0] * 9 + [9.4] * 11
    mv = {"pct": 5.0, "dir": "favor", "ref": "entry"}
    assert _correr(closes, [_nivel(pasos=[_senal(4), _senal(6)], move=mv)]) == []
    assert _correr(closes, [_nivel(pasos=[_senal(4), _senal(6, 12)], move=mv)]) == [13]


def test_un_nivel_normal_con_recorrido_sigue_igual():
    """La regla de siempre (16-sep): condiciones AND recorrido, con flanco."""
    closes = [10.0] * 9 + [9.4] * 11
    mv = {"pct": 5.0, "dir": "favor", "ref": "entry"}
    assert _correr(closes, [_nivel(senal=_rango(4, N - 1), move=mv)]) == [10]
