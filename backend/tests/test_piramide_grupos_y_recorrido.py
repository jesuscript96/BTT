# -*- coding: utf-8 -*-
"""Piramidación por GRUPOS y disparo por RECORRIDO del precio (16-sep-2026).

Lo pidió Jaume: (1) poder tener, por ejemplo, tres pirámides donde dos van en
secuencia y la tercera es independiente — hasta hoy el modo era uno solo para
toda la lista; (2) que un nivel pueda disparar «si X % de recorrido del precio
(no de la vela) a favor o en contra», como un take profit / stop loss de la
propia pirámide, además de por condiciones.

Se prueba por las tres capas de verdad (compile -> translate -> simulate),
que es donde ya se han perdido claves otras veces.
"""
import numpy as np
import pandas as pd
import pytest

from app.services.portfolio_sim import simulate
from app.services.strategy_engine import compile_strategy_def, translate_strategy

SIEMPRE = {
    "type": "group", "operator": "AND",
    "conditions": [{
        "type": "indicator_comparison",
        "source": {"name": "Bar Close", "offset": 0},
        "comparator": "GREATER_THAN", "target": 0.0, "timeframe": "1m",
    }],
}
NUNCA = {
    "type": "group", "operator": "AND",
    "conditions": [{
        "type": "indicator_comparison",
        "source": {"name": "Bar Close", "offset": 0},
        "comparator": "LESS_THAN", "target": 0.0, "timeframe": "1m",
    }],
}
VACIO = {"type": "group", "operator": "AND", "conditions": []}


def _frame(close, inicio="2026-09-16 04:00"):
    close = np.asarray(close, dtype=np.float64)
    ts = pd.date_range(inicio, periods=len(close), freq="1min")
    return pd.DataFrame({
        "timestamp": ts, "open": close, "high": close * 1.001,
        "low": close * 0.999, "close": close, "volume": np.full(len(close), 100000.0),
    })


def _nivel(**kw):
    base = {"times": 1, "root_condition": SIEMPRE, "action": "add", "unit": "usd", "capital_pct": 100}
    base.update(kw)
    return base


def _definicion(niveles, bias="long", groups=None, mode="individual", entrada=None):
    pyr = {"timeframe": "1m", "mode": mode, "levels": niveles}
    if groups is not None:
        pyr["groups"] = groups
    return {
        "bias": bias, "market_sessions": ["custom"],
        "custom_start_time": "04:00", "custom_end_time": "09:00",
        "entry_logic": {"timeframe": "1m", "root_condition": entrada or SIEMPRE},
        "exit_logic": {"timeframe": "1m", "root_condition": VACIO},
        "risk_management": {"size_by_sl": False, "use_hard_stop": False},
        "pyramiding": pyr,
    }


def _correr(definicion, close, entrada_en=0):
    """compile -> translate -> simulate, entrando UNA vez en la vela `entrada_en`."""
    frame = _frame(close)
    comp = compile_strategy_def(definicion)
    s = translate_strategy(frame, definicion, {}, compiled=comp)
    n = len(frame)
    entries = np.zeros(n, dtype=bool)
    entries[entrada_en] = True
    res = simulate(
        close=frame["close"].values, open_=frame["open"].values,
        high=frame["high"].values, low=frame["low"].values,
        entries=entries, exits=np.zeros(n, dtype=bool),
        direction=s["direction"], init_cash=100_000.0, risk_r=1000.0, risk_type="FIXED",
        look_ahead_prevention=True,
        timestamps=pd.to_datetime(frame["timestamp"]).values.astype("datetime64[ns]").astype(np.int64),
        pyramid_levels=s["pyramid_levels"], pyramid_sequential=s["pyramid_sequential"],
    )
    ejec = []
    for t in res["trades"]:
        ejec += t.get("pyr_executions") or []
    return res, s, ejec


# ══ Grupos ═════════════════════════════════════════════════════════════════

def test_sin_groups_todo_es_el_grupo_0_con_el_modo_global():
    """Regla nº1: una definición de antes (mode + levels) se compila igual."""
    comp = compile_strategy_def(_definicion([_nivel(), _nivel()], mode="sequential"))
    lv = comp["pyramid_levels_def"]
    assert [x["group"] for x in lv] == [0, 0]
    assert all(x["sequential"] for x in lv)
    assert comp["pyramid_sequential"] is True
    comp2 = compile_strategy_def(_definicion([_nivel(), _nivel()], mode="individual"))
    assert not any(x["sequential"] for x in comp2["pyramid_levels_def"])


def test_dos_en_secuencia_y_una_independiente():
    """El caso de Jaume: G0 secuencial (1 y 2), G1 individual (3).

    Con condiciones «siempre», en modo secuencial puro solo disparan en
    orden, una por vela. Con grupos: el nivel 3 dispara EN LA MISMA vela que
    el 1 (no espera a nadie) y el 2 espera al 1.
    """
    close = np.full(30, 10.0)
    niveles = [_nivel(group=0), _nivel(group=0), _nivel(group=1)]
    grupos = [{"mode": "sequential"}, {"mode": "individual"}]
    _, _, ejec = _correr(_definicion(niveles, groups=grupos), close)
    por_nivel = {e["level"]: e["idx"] for e in ejec}
    assert set(por_nivel) == {1, 2, 3}
    assert por_nivel[3] == por_nivel[1], "el grupo independiente no espera al secuencial"
    assert por_nivel[2] > por_nivel[1], "dentro del grupo secuencial, el 2 espera al 1"


def test_secuencial_puro_sigue_igual_que_antes():
    """Control: el mismo trío con el modo global secuencial dispara 1, 2, 3 en
    velas distintas y en orden — el comportamiento de siempre."""
    close = np.full(30, 10.0)
    _, _, ejec = _correr(_definicion([_nivel(), _nivel(), _nivel()], mode="sequential"), close)
    idx = [e["idx"] for e in sorted(ejec, key=lambda e: e["level"])]
    assert idx[0] < idx[1] < idx[2]


def test_dos_grupos_secuenciales_avanzan_cada_uno_por_su_cuenta():
    close = np.full(30, 10.0)
    niveles = [_nivel(group=0), _nivel(group=0), _nivel(group=1), _nivel(group=1)]
    grupos = [{"mode": "sequential"}, {"mode": "sequential"}]
    _, _, ejec = _correr(_definicion(niveles, groups=grupos), close)
    por_nivel = {e["level"]: e["idx"] for e in ejec}
    assert por_nivel[1] == por_nivel[3]           # los dos primeros, a la vez
    assert por_nivel[2] == por_nivel[4]           # y los dos segundos, a la vez
    assert por_nivel[2] > por_nivel[1]


def test_el_grupo_no_se_sale_de_la_lista_de_groups():
    """Un nivel con `group` más allá de la lista cae al modo global, no revienta."""
    comp = compile_strategy_def(_definicion([_nivel(group=7)], groups=[{"mode": "sequential"}],
                                            mode="individual"))
    assert comp["pyramid_levels_def"][0]["sequential"] is False


# ══ Disparo por recorrido ══════════════════════════════════════════════════

def test_solo_por_recorrido_no_necesita_condiciones():
    """Antes, un nivel sin condiciones se descartaba en silencio."""
    comp = compile_strategy_def(_definicion([
        _nivel(root_condition=VACIO, trigger="move", move_pct=5, move_dir="favor"),
        _nivel(root_condition=VACIO),                                    # este sí se descarta
    ]))
    assert len(comp["pyramid_levels_def"]) == 1
    # `pos` (17-sep): donde va el recorrido dentro de un camino; "first" por defecto.
    assert comp["pyramid_levels_def"][0]["move"] == {"pct": 5.0, "dir": "favor", "ref": "entry", "pos": "first"}


def test_a_favor_desde_la_entrada_largo():
    """Largo a 100; el nivel añade cuando lleva +5 %: la primera vela con
    cierre >= 105 es la señal y se ejecuta en la apertura de la siguiente."""
    close = np.array([100.0] * 3 + list(np.linspace(100, 110, 21)) + [110.0] * 6)
    niveles = [_nivel(root_condition=VACIO, trigger="move", move_pct=5, move_dir="favor")]
    res, s, ejec = _correr(_definicion(niveles), close, entrada_en=0)
    entry = res["trades"][0]["entry_price"]
    assert entry == pytest.approx(100.0)
    assert len(ejec) == 1 and ejec[0]["kind"] == "add"
    senal = ejec[0]["idx"] - 1
    assert close[senal] >= 105.0 and close[senal - 1] < 105.0


def test_en_contra_corto_quita():
    """Corto a 100; «quitar la mitad si va 3 % en contra» = precio >= 103."""
    close = np.array([100.0] * 3 + list(np.linspace(100, 106, 13)) + [106.0] * 6)
    niveles = [_nivel(root_condition=VACIO, action="reduce", unit="pct", capital_pct=50,
                      trigger="move", move_pct=3, move_dir="contra")]
    res, _, ejec = _correr(_definicion(niveles, bias="short"), close, entrada_en=0)
    assert len(ejec) == 1 and ejec[0]["kind"] == "reduce"
    senal = ejec[0]["idx"] - 1
    assert close[senal] >= 103.0 and close[senal - 1] < 103.0
    # la mitad fuera: lo que queda vivo es igual a lo que se cerro
    assert ejec[0]["position_size"] == pytest.approx(ejec[0]["size"], rel=1e-6)


def test_a_favor_en_un_corto_es_precio_hacia_abajo():
    close = np.array([100.0] * 3 + list(np.linspace(100, 90, 21)) + [90.0] * 6)
    niveles = [_nivel(root_condition=VACIO, trigger="move", move_pct=5, move_dir="favor")]
    _, _, ejec = _correr(_definicion(niveles, bias="short"), close, entrada_en=0)
    assert len(ejec) == 1
    senal = ejec[0]["idx"] - 1
    assert close[senal] <= 95.0 and close[senal - 1] > 95.0


def test_desde_el_ultimo_disparo_encadena_escalones():
    """Un nivel «+5 % desde el último disparo» con 3 veces: añade a +5 %, y
    luego cada +5 % medido desde el precio del añadido anterior (no desde la
    entrada), o sea ~105, ~110,25 y ~115,76."""
    close = np.array([100.0] * 3 + list(np.linspace(100, 125, 101)) + [125.0] * 6)
    niveles = [_nivel(root_condition=VACIO, trigger="move", move_pct=5, move_dir="favor",
                      move_ref="last", times=3)]
    _, _, ejec = _correr(_definicion(niveles), close, entrada_en=0)
    assert len(ejec) == 3
    ref = 100.0
    for e in ejec:
        senal = e["idx"] - 1
        assert close[senal] >= ref * 1.05 and close[senal - 1] < ref * 1.05, (ref, close[senal])
        ref = e["price"]                          # el siguiente escalón, desde este añadido


def test_desde_la_entrada_con_varias_veces_no_encadena():
    """Mismo nivel pero medido desde la ENTRADA: cruzar +5 % es un evento; con
    el precio subiendo sin volver, dispara una vez aunque tenga 3 veces."""
    close = np.array([100.0] * 3 + list(np.linspace(100, 125, 101)) + [125.0] * 6)
    niveles = [_nivel(root_condition=VACIO, trigger="move", move_pct=5, move_dir="favor",
                      move_ref="entry", times=3)]
    _, _, ejec = _correr(_definicion(niveles), close, entrada_en=0)
    assert len(ejec) == 1


def test_recorrido_y_condiciones_son_un_and():
    """Con condiciones además del recorrido, hacen falta las dos."""
    close = np.array([100.0] * 3 + list(np.linspace(100, 110, 21)) + [110.0] * 6)
    niveles = [_nivel(root_condition=NUNCA, trigger="move", move_pct=5, move_dir="favor")]
    _, _, ejec = _correr(_definicion(niveles), close, entrada_en=0)
    assert ejec == []


def test_el_recorrido_es_del_precio_no_de_la_vela():
    """Velas de +1 % cada una: ninguna vela recorre el 5 %, pero el precio sí
    lo lleva acumulado desde la entrada — y eso es lo que dispara."""
    close = 100.0 * np.cumprod(np.r_[1.0, np.full(29, 1.01)])
    niveles = [_nivel(root_condition=VACIO, trigger="move", move_pct=5, move_dir="favor")]
    _, _, ejec = _correr(_definicion(niveles), close, entrada_en=0)
    assert len(ejec) == 1


def test_las_claves_llegan_al_simulador_por_translate():
    """La regla de las tres capas: group / sequential / move viajan enteras."""
    frame = _frame(np.full(20, 10.0))
    d = _definicion([_nivel(group=1, trigger="move", move_pct=2, move_dir="contra", move_ref="last")],
                    groups=[{"mode": "individual"}, {"mode": "sequential"}])
    s = translate_strategy(frame, d, {}, compiled=compile_strategy_def(d))
    lv = s["pyramid_levels"][0]
    assert lv["group"] == 1 and lv["sequential"] is True
    assert lv["move"] == {"pct": 2.0, "dir": "contra", "ref": "last", "pos": "first"}
    assert np.asarray(lv["signals"]).all()       # sin condiciones: la señal lógica es «siempre»


def test_desde_el_ultimo_disparo_es_el_ultimo_de_SU_grupo():
    """Medido en una corrida real: con «desde el último disparo» = cualquier
    nivel, una QUITA del grupo 2 (en contra) reseteaba la escalera del grupo 1
    y el segundo añadido saltaba a un 3 % por debajo de la quita, no del
    primer añadido. Los grupos son independientes: cada uno lleva su último
    disparo. Largo: G1 = escalera de +5 % desde el último disparo (2 veces);
    G2 = quitar si −4 %. El precio sube a 106 (añadido 1 a ~106), baja a 95
    (quita de G2), y vuelve a 108: el añadido 2 tiene que esperar a 106 x 1,05
    = 111,3, así que con un máximo de 108 NO dispara."""
    close = np.array([100.0] * 3 + list(np.linspace(100, 106, 7)) + list(np.linspace(106, 95, 12))
                     + list(np.linspace(95, 108, 14)) + [108.0] * 5)
    niveles = [_nivel(group=0, root_condition=VACIO, trigger="move", move_pct=5, move_dir="favor",
                      move_ref="last", times=2),
               _nivel(group=1, root_condition=VACIO, action="reduce", unit="pct", capital_pct=50,
                      trigger="move", move_pct=4, move_dir="contra", move_ref="entry")]
    grupos = [{"mode": "individual"}, {"mode": "individual"}]
    _, _, ejec = _correr(_definicion(niveles, groups=grupos), close, entrada_en=0)
    kinds = [(e["level"], e["kind"]) for e in ejec]
    assert kinds.count((1, "add")) == 1, kinds        # solo el primer escalón
    assert (2, "reduce") in kinds, kinds               # la quita del otro grupo sí
