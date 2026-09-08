"""Walk-forward: el eje de parametros y el analisis por valor.

Cubre los dos arreglos del 2026-08-30:

  1. Un parametro ENTERO (una hora de reloj, un periodo de indicador) redondea y
     DEDUPLICA su eje. Antes `linspace` devolvia decimales que colapsaban en el
     mismo minuto al escribirse, y se pagaban backtests para repetir lo mismo.

  2. `_param_analysis` acepta la posicion del parametro dentro de la
     combinacion. Antes leia siempre `params[0]`, asi que barrer dos era
     imposible: la pantalla entera de "que valor conviene usar" se apagaba.
"""
import numpy as np

from app.services.robustness_wfo import _axis, _param_analysis


# ── El eje ────────────────────────────────────────────────────────────────

DEF_HORA = {"risk_management": {"take_profit": {"value": "HOUR:15:30"}}}


def test_eje_continuo_no_redondea():
    """Un porcentaje sigue siendo continuo: nada que redondear."""
    pc = {"path": "risk_management.hard_stop.offset_pct", "min": 0.5, "max": 5.0, "steps": 6}
    assert _axis(pc, {}) == [0.5, 1.4, 2.3, 3.2, 4.1, 5.0]


def test_eje_de_hora_se_deduplica():
    """15:30-15:35 en 10 pasos son SEIS horas distintas, no diez.

    Es el caso que motivo el arreglo: se lanzaban 10 backtests por ventana para
    probar 6 valores, y los 4 repetidos entraban en la tabla de mesetas como
    filas propias, alisando la curva y aparentando una meseta que no existia.
    """
    pc = {"path": "risk_management.take_profit.value", "min": 930, "max": 935, "steps": 10}
    assert _axis(pc, DEF_HORA) == [930, 931, 932, 933, 934, 935]


def test_eje_entero_por_nombre_de_clave():
    """`period` y compañia son enteros aunque no sean horas."""
    pc = {"path": "indicators.0.params.period", "min": 5, "max": 9, "steps": 10}
    assert _axis(pc, {}) == [5, 6, 7, 8, 9]


def test_eje_entero_igual_que_el_optimizador():
    """Misma formula que `run_optimization_grid`, para que no se separen."""
    for lo, hi, steps in [(5, 9, 10), (1, 20, 6), (10, 13, 8), (3, 3, 5)]:
        pc = {"path": "indicators.0.params.period", "min": lo, "max": hi, "steps": steps}
        if lo == hi:
            esperado = [lo]
        else:
            esperado = sorted({int(round(x)) for x in np.linspace(lo, hi, steps)})
        assert _axis(pc, {}) == esperado, (lo, hi, steps)


def test_eje_de_un_solo_paso():
    assert _axis({"path": "x.pct", "min": 3, "max": 8, "steps": 1}, {}) == [3.0]
    assert _axis({"path": "x.period", "min": 3, "max": 8, "steps": 1}, {}) == [3]


# ── El analisis por valor ─────────────────────────────────────────────────

def _ventana(valores, puntuaciones, ganador):
    return {
        "trials": [{"params": [v], "score": s} for v, s in zip(valores, puntuaciones)],
        "best_params": [ganador],
    }


def test_analisis_de_un_parametro():
    """Recomienda por MESETA, no por la media suelta, y cuenta victorias."""
    vals = [1.0, 2.0, 3.0, 4.0]
    rows = [
        _ventana(vals, [0.1, 0.9, 1.0, 0.2], 3.0),
        _ventana(vals, [0.1, 0.9, 1.0, 0.2], 3.0),
    ]
    pa = _param_analysis(rows, vals, {"label": "X"})
    assert pa["recommended"] == 3.0
    assert [pv["wins"] for pv in pa["per_value"]] == [0, 0, 2, 0]
    assert pa["at_edge"] is False


def test_analisis_de_dos_parametros_marginaliza():
    """Cada eje se lee promediando sobre los valores del otro.

    Con puntuacion aditiva (`score = fa[a] + fb[b]`) la media marginal de cada
    eje es exacta y se puede comprobar a mano.
    """
    fa = {1.0: 0.1, 2.0: 0.9, 3.0: 1.0, 4.0: 0.2}
    fb = {10.0: 0.0, 20.0: 0.4, 30.0: 0.5, 40.0: 0.1}
    eje_a, eje_b = sorted(fa), sorted(fb)
    trials = [{"params": [a, b], "score": round(fa[a] + fb[b], 6)} for a in eje_a for b in eje_b]
    rows = [{"trials": trials, "best_params": [3.0, 30.0]} for _ in range(2)]

    pa_a = _param_analysis(rows, eje_a, {"label": "A"}, 0)
    pa_b = _param_analysis(rows, eje_b, {"label": "B"}, 1)

    media_a, media_b = sum(fa.values()) / 4, sum(fb.values()) / 4
    assert [pv["mean"] for pv in pa_a["per_value"]] == [round(fa[v] + media_b, 4) for v in eje_a]
    assert [pv["mean"] for pv in pa_b["per_value"]] == [round(fb[v] + media_a, 4) for v in eje_b]
    assert pa_a["recommended"] == 3.0
    assert pa_b["recommended"] == 30.0
    # El SEGUNDO eje es el que no se veia: antes `params[0]` no casaba con
    # ningun valor de B y la tabla salia entera vacia.
    assert all(pv["mean"] is not None for pv in pa_b["per_value"])
    assert [pv["wins"] for pv in pa_b["per_value"]] == [0, 0, 2, 0]


def test_analisis_con_dimension_inexistente_no_revienta():
    """Un resultado a medias no debe tumbar la pantalla."""
    rows = [{"trials": [{"params": [1.0], "score": 0.5}], "best_params": [1.0]}]
    pa = _param_analysis(rows, [10.0, 20.0], {"label": "B"}, 1)
    assert all(pv["mean"] is None for pv in pa["per_value"])
    assert pa["winner_values"] == []


# ── La meseta en ejes cortos ──────────────────────────────────────────────
#
# Fuera de la rejilla el eje se supone plano (el extremo se repite), y a
# igualdad de meseta gana el que mejor puntua. Sin las dos cosas, un eje de dos
# o tres valores recomendaba SIEMPRE el primero, fuese el mejor o el peor.

def test_meseta_con_dos_valores_recomienda_el_mejor():
    vals = [1.0, 2.0]
    rows = [_ventana(vals, [0.1, 1.1], 2.0) for _ in range(2)]
    pa = _param_analysis(rows, vals, {"label": "X"})
    assert pa["recommended"] == 2.0
    # Con solo dos valores, cualquiera de los dos esta en el borde del rango.
    assert pa["at_edge"] is True


def test_meseta_con_tres_valores_simetricos_recomienda_el_centro():
    vals = [1.0, 2.0, 3.0]
    rows = [_ventana(vals, [0.2, 1.0, 0.2], 2.0) for _ in range(2)]
    pa = _param_analysis(rows, vals, {"label": "X"})
    assert pa["recommended"] == 2.0
    assert pa["at_edge"] is False


def test_meseta_sigue_prefiriendo_la_zona_ancha_al_pico_aislado():
    """Lo que la meseta existe para hacer, que no debe cambiar."""
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    #        pico aislado ^          ^ zona ancha
    rows = [_ventana(vals, [0.0, 1.2, 0.0, 0.9, 0.95], 2.0) for _ in range(2)]
    pa = _param_analysis(rows, vals, {"label": "X"})
    assert pa["recommended"] in (4.0, 5.0)
