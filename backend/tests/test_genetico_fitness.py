"""La nota del genetico: los modos nuevos (EV) y la trampa del riesgo porcentual.

Una corrida dura entre ocho y diez horas, asi que un fallo aqui no se ve hasta
la manyana siguiente y se lleva la noche por delante. De ahi que el fitness
tenga tests propios aunque sean cuatro cuentas.
"""
import math
import os
import sys

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from genetico.evaluador import _r_media, fitness  # noqa: E402

FIJO = {"risk_type": "FIXED", "risk_r": 100, "init_cash": 50000}
PCT = {"risk_type": "PERCENT", "risk_r": 1.0, "init_cash": 50000}   # 1% de 50k = 500 $

METRICAS = {"trades": 1600, "expectancy": 1.05, "pf": 1.77,
            "sharpe": -1.5, "dd_return": -1.02, "avg_r": 0.0105}


def nota(modo, m=None, min_trades=100, riesgo=FIJO):
    return fitness(m or METRICAS, {"fitness": modo, "min_trades": min_trades, "riesgo": riesgo})


# ── R media ─────────────────────────────────────────────────────────────────

def test_r_media_riesgo_fijo():
    assert _r_media(2.5, FIJO) == 0.025


def test_r_media_riesgo_porcentual_ya_no_es_none():
    """La trampa: `_f(None)` es 0.0, asi que devolver None dejaba a la poblacion
    ENTERA con fitness 0 en `avg_r` y `expR_sqrtN` — sin error y sin log."""
    assert _r_media(2.5, PCT) == 0.005          # 2,5 $ / (1% de 50.000)
    m = dict(METRICAS, avg_r=_r_media(METRICAS["expectancy"], PCT))
    assert nota("expR_sqrtN", m, riesgo=PCT) > 0


def test_r_media_sin_riesgo_declarado_es_none():
    assert _r_media(2.5, {"risk_type": "PERCENT", "risk_r": 0}) is None
    assert _r_media(2.5, {"risk_type": "FIXED", "risk_r": 0}) is None


def test_r_media_porcentual_no_cambia_el_orden():
    """Dividir por una constante ordena igual: es lo unico que le pide el
    genetico a la nota."""
    evs = [0.5, 1.05, 3.0, -0.2]
    rs = [_r_media(ev, PCT) for ev in evs]
    assert sorted(range(len(evs)), key=lambda i: evs[i]) == \
           sorted(range(len(rs)), key=lambda i: rs[i])


# ── Modos ───────────────────────────────────────────────────────────────────

def test_ev_es_el_pnl_medio_en_dolares():
    assert nota("ev") == 1.05


def test_ev_sqrtN_premia_operar_mas():
    assert nota("ev_sqrtN") == pytest.approx(1.05 * math.sqrt(1600))
    pocas = dict(METRICAS, trades=100)
    assert nota("ev_sqrtN", pocas) < nota("ev_sqrtN")      # mismo EV, menos N
    assert nota("ev", pocas) == nota("ev")                  # a EV pelado le da igual


def test_ev_y_r_media_ordenan_igual():
    """Son la misma curva a escala distinta; estan las dos por como se leen."""
    pob = [dict(METRICAS, expectancy=ev, avg_r=_r_media(ev, FIJO))
           for ev in (0.2, 1.05, 2.4, -0.5)]
    assert [pob.index(p) for p in sorted(pob, key=lambda m: nota("ev", m))] == \
           [pob.index(p) for p in sorted(pob, key=lambda m: nota("avg_r", m))]


def test_los_modos_de_siempre_no_se_mueven():
    """Hay corridas en marcha con `pf`: reanudarlas no puede cambiar la nota."""
    assert nota("pf") == 1.77
    assert nota("sharpe") == -1.5
    assert nota("dd_return") == -1.02
    assert nota("avg_r") == 0.0105
    assert nota("expR_sqrtN") == pytest.approx(0.0105 * math.sqrt(1600))


def test_el_suelo_de_operaciones_manda_sobre_todos_los_modos():
    for modo in ("expR_sqrtN", "ev_sqrtN", "avg_r", "ev", "pf", "dd_return", "sharpe"):
        assert nota(modo, min_trades=5000) == 0.0, modo


def test_modo_desconocido_revienta_y_no_devuelve_cero():
    """Un typo en el modo tiene que doler ya, no dejar la corrida a ciegas."""
    with pytest.raises(ValueError):
        nota("expectancy")      # el id bueno es "ev"


def test_los_modos_del_catalogo_existen_todos():
    """El desplegable de la pagina y el motor no pueden ir por separado."""
    sys.path.insert(0, os.path.join(RAIZ, "backend"))
    from app.routers.genetico import FITNESS
    for f in FITNESS:
        nota(f["id"])           # si falta uno, ValueError
