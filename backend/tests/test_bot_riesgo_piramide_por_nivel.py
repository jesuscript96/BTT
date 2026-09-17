# -*- coding: utf-8 -*-
"""El bot de alarmas con UNA cantidad por pirámide (16-sep-2026).

Lo pidió Jaume: cada pirámide de la estrategia puede llevar su dinero, el
cuadro de mandos lo pide una a una y el bot lo usa. Hasta hoy había un solo
«riesgo pirámide» para todos los niveles.

Lo delicado es el ÍNDICE: el cuadro numera las pirámides tal cual están en
la definición guardada, pero el compilador descarta las inválidas (sin
condiciones ni recorrido, o con cantidad 0), así que la posición en la lista
compilada NO es la de la definición. Por eso cada nivel compilado lleva su
`def_index`, y es lo que se usa aquí.
"""
import json
import numpy as np
import pandas as pd

from app.services.bot_alerts_engine import _niveles_con_riesgo, _kwargs_simulate
from app.services.strategy_engine import compile_strategy_def, translate_strategy

SIEMPRE = {"type": "group", "operator": "AND", "conditions": [{
    "type": "indicator_comparison", "source": {"name": "Bar Close", "offset": 0},
    "comparator": "GREATER_THAN", "target": 0.0, "timeframe": "1m"}]}
VACIO = {"type": "group", "operator": "AND", "conditions": []}


def _nivel(**kw):
    base = {"times": 1, "root_condition": SIEMPRE, "action": "add", "unit": "pct", "capital_pct": 1}
    base.update(kw)
    return base


def _definicion(niveles):
    return {
        "bias": "long", "market_sessions": ["custom"],
        "custom_start_time": "04:00", "custom_end_time": "09:00",
        "entry_logic": {"timeframe": "1m", "root_condition": SIEMPRE},
        "exit_logic": {"timeframe": "1m", "root_condition": VACIO},
        "risk_management": {"size_by_sl": False, "use_hard_stop": False},
        "pyramiding": {"timeframe": "1m", "mode": "individual", "levels": niveles},
    }


def _senales(definicion, n=30):
    ts = pd.date_range("2026-09-16 04:00", periods=n, freq="1min")
    close = np.full(n, 10.0)
    frame = pd.DataFrame({"timestamp": ts, "open": close, "high": close * 1.001,
                          "low": close * 0.999, "close": close, "volume": np.full(n, 1e5)})
    return translate_strategy(frame, definicion, {}, compiled=compile_strategy_def(definicion)), frame


def test_cada_nivel_lleva_su_cantidad():
    s, _ = _senales(_definicion([_nivel(), _nivel(action="reduce", capital_pct=50), _nivel()]))
    fuera = _niveles_con_riesgo(s["pyramid_levels"], None, [150.0, 40.0, 300.0])
    assert [(l["unit"], l["amount_usd"]) for l in fuera] == [("usd", 150.0), ("usd", 40.0), ("usd", 300.0)]


def test_el_nivel_sin_cantidad_cae_al_global_y_sin_global_a_la_estrategia():
    s, _ = _senales(_definicion([_nivel(), _nivel(), _nivel()]))
    fuera = _niveles_con_riesgo(s["pyramid_levels"], 200.0, [150.0, None, 0])
    assert [l["amount_usd"] for l in fuera] == [150.0, 200.0, 200.0]
    fuera2 = _niveles_con_riesgo(s["pyramid_levels"], None, [150.0, None, None])
    assert fuera2[0]["amount_usd"] == 150.0
    assert fuera2[1]["unit"] == "pct" and "amount_usd" in fuera2[1] and fuera2[1]["amount_usd"] == 0.0
    assert fuera2[2]["unit"] == "pct"


def test_sin_lista_se_comporta_como_antes():
    s, _ = _senales(_definicion([_nivel(), _nivel()]))
    assert _niveles_con_riesgo(s["pyramid_levels"], 200.0) == _niveles_con_riesgo(s["pyramid_levels"], 200.0, None)
    assert all(l["amount_usd"] == 200.0 for l in _niveles_con_riesgo(s["pyramid_levels"], 200.0, []))
    assert _niveles_con_riesgo(s["pyramid_levels"], None, None) is s["pyramid_levels"]


def test_el_indice_es_el_de_la_definicion_aunque_se_descarte_un_nivel():
    """La pirámide 2 de la definición no vale (sin condiciones ni recorrido):
    el compilador la salta, pero la cantidad de la pirámide 3 sigue siendo la
    TERCERA de la lista del cuadro, no la segunda."""
    s, _ = _senales(_definicion([_nivel(), _nivel(root_condition=VACIO), _nivel()]))
    assert [l["def_index"] for l in s["pyramid_levels"]] == [0, 2]
    fuera = _niveles_con_riesgo(s["pyramid_levels"], None, [100.0, 999.0, 300.0])
    assert [l["amount_usd"] for l in fuera] == [100.0, 300.0]


def test_llega_al_simulador_por_kwargs_simulate():
    d = _definicion([_nivel(), _nivel()])
    s, frame = _senales(d)
    frame = frame.assign(hod=frame["high"], lod=frame["low"], pm_high=frame["high"],
                         pm_low=frame["low"], prev_high=frame["high"], prev_low=frame["low"])
    kw = _kwargs_simulate(frame, s, d, 300.0, 200.0, None, [50.0, None])
    assert [l["amount_usd"] for l in kw["pyramid_levels"]] == [50.0, 200.0]


def test_se_guarda_y_se_lee_de_la_tabla(tmp_path):
    import duckdb
    from app.services import bot_alerts_service as bas
    con = duckdb.connect(str(tmp_path / "t.duckdb"))
    # El DDL se recuerda en un flag de modulo pensado para UNA base de datos:
    # se fuerza aqui y se devuelve al salir, para no dejar sin tabla a otro
    # test que abra su propia conexion despues.
    antes = bas._DDL_DONE
    bas._DDL_DONE = False
    try:
        fila = bas.set_watch(con, "s1", True, 300.0, 200.0, None, None, [150.0, None, "40"])
        assert fila["riesgos_piramide"] == [150.0, None, 40.0]
        w = bas.get_watch(con)["s1"]
        assert w["riesgos_piramide"] == [150.0, None, 40.0]
        assert w["riesgo_piramide_usd"] == 200.0
        # todo vacio = None, no una lista de nadas
        bas.set_watch(con, "s2", True, 300.0, None, None, None, [None, 0, ""])
        assert bas.get_watch(con)["s2"]["riesgos_piramide"] is None
    finally:
        bas._DDL_DONE = antes


def test_describir_piramides_numera_como_la_definicion():
    from app.services.bot_alerts_service import describir_piramides
    d = _definicion([
        _nivel(group=0), _nivel(root_condition=VACIO, trigger="move", move_pct=3, move_dir="contra",
                                move_ref="last", action="reduce", capital_pct=50, group=1)])
    d["pyramiding"]["groups"] = [{"mode": "sequential"}, {"mode": "individual"}]
    ps = describir_piramides(d)
    assert [p["i"] for p in ps] == [0, 1]
    assert ps[0]["modo"] == "sequential" and ps[0]["disparo"] == "por condiciones" and ps[0]["cantidad"] == "1%"
    assert ps[1]["accion"] == "reduce" and ps[1]["grupo"] == 1 and ps[1]["modo"] == "individual"
    assert ps[1]["disparo"] == "si 3% en contra desde el ultimo disparo"
