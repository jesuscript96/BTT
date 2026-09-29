"""Prealerta SIMPLE de los AÑADIDOS (29-sep-2026).

Jaume: «prefiero que avise añadido por condiciones». Hasta hoy, con posición
abierta la prealerta simple se callaba del todo: el 28-sep salieron 46
prealertas, todas de entrada, y los 10 añadidos llegaron sin aviso previo.

Ahora, con posición viva en ESA estrategia, se mira cada nivel que añade por
condiciones con el mismo «todas menos una» que la entrada.
"""
from types import SimpleNamespace

import pandas as pd

from app.services.bot_alerts_engine import _EstadoPar
from app.services.bot_alerts_prealerta_simple import PrealertaSimple
from app.services.bot_alerts_telegram import formatear

TK = "AAA"


def _cond(op, valor):
    return {"type": "indicator_comparison", "source": {"name": "Bar Close", "offset": 0},
            "comparator": op, "target": valor, "timeframe": "1m"}


# El cierre de la última vela es 2.0: «> 1» se cumple, «> 5» no.
SI, NO = _cond("GREATER_THAN", 1.0), _cond("GREATER_THAN", 5.0)


def _velas(n=30):
    base = pd.Timestamp("2026-09-29 08:00:00")
    return [{"timestamp": str(base + pd.Timedelta(minutes=i)), "open": 2.0, "high": 2.05,
             "low": 1.95, "close": 2.0, "volume": 10000.0} for i in range(n)]


def _estrategia(niveles, entrada=(SI, NO)):
    sdef = {"direction": "shortonly",
            "entry_logic": {"timeframe": "1m",
                            "root_condition": {"type": "group", "operator": "AND",
                                               "conditions": list(entrada)}},
            "pyramiding": {"timeframe": "1m", "levels": niveles}}
    return {"strategy_id": "id-A", "name": "Estrategia A", "definition": sdef,
            "compiled": {}, "riesgo_usd": 100.0}


def _nivel(conds, **extra):
    return {"times": 1, "action": "add",
            "root_condition": {"type": "group", "operator": "AND", "conditions": list(conds)},
            **extra}


def _runner(est, estado=None):
    motor = SimpleNamespace(estrategias=[est], _estado={})
    if estado is not None:
        motor._estado[(TK, est["strategy_id"])] = estado
    return SimpleNamespace(_velas={TK: _velas()}, _stats={TK: {"prev_close": 1.0}}, motor=motor)


def _dentro(**kw):
    e = _EstadoPar()
    e.entradas_avisadas.add(10)
    e.idx_ultima_entrada_avisada = 10
    for k, v in kw.items():
        setattr(e, k, v)
    return e


def test_fuera_de_posicion_sigue_prealertando_la_entrada():
    evs = PrealertaSimple().evaluar(_runner(_estrategia([_nivel([SI, NO])])), TK)
    assert [e.tipo for e in evs] == ["entrada"]
    assert evs[0].motivo == "Falta: Bar Close > 5.0"


def test_dentro_prealerta_el_anyadido_y_no_la_entrada():
    """EL CAMBIO. Antes: con posición, nada."""
    evs = PrealertaSimple().evaluar(_runner(_estrategia([_nivel([SI, NO])]), _dentro()), TK)
    assert len(evs) == 1
    e = evs[0]
    assert (e.tipo, e.nivel, e.accion_piramide, e.estado) == ("piramide", 1, "add", "prealerta")
    assert e.motivo == "Falta: Bar Close > 5.0"


def test_nivel_ya_disparado_sus_veces_no_prealerta():
    """EL FALLO DEL 29-sep. El simulador numera el nivel desde 1 («lv_idx + 1»);
    se comparaba con el índice desde 0 y el añadido hecho no contaba: BKYI
    añadió a las 11:21 (times=1) y siguió prealertando hasta el cierre."""
    estado = _dentro(piramides_avisadas={(11, 1, 15)})
    evs = PrealertaSimple().evaluar(_runner(_estrategia([_nivel([SI, NO])]), estado), TK)
    assert evs == []


def test_un_disparo_de_una_posicion_anterior_no_cuenta():
    estado = _dentro(piramides_avisadas={(3, 1, 5)})     # de la entrada de antes
    evs = PrealertaSimple().evaluar(_runner(_estrategia([_nivel([SI, NO])]), estado), TK)
    assert [e.tipo for e in evs] == ["piramide"]


def test_niveles_por_recorrido_reducciones_y_caminos_no_prealertan():
    niveles = [_nivel([SI, NO], trigger="move", move_pct=5),
               _nivel([SI, NO], action="reduce"),
               {"times": 1, "action": "add", "steps": [{"conditions": [SI]}, {"conditions": [NO]}]}]
    evs = PrealertaSimple().evaluar(_runner(_estrategia(niveles), _dentro()), TK)
    assert evs == []


def test_a_mas_de_una_condicion_o_ya_cumplido_no_prealerta():
    niveles = [_nivel([SI, NO, NO]), _nivel([SI, SI])]
    evs = PrealertaSimple().evaluar(_runner(_estrategia(niveles), _dentro()), TK)
    assert evs == []


def test_dos_niveles_a_una_condicion_dan_dos_prealertas():
    niveles = [_nivel([SI, NO]), _nivel([NO, SI])]
    evs = PrealertaSimple().evaluar(_runner(_estrategia(niveles), _dentro()), TK)
    assert sorted(e.nivel for e in evs) == [1, 2]


def test_el_freno_va_por_nivel():
    p = PrealertaSimple(cada_min=10)
    r = _runner(_estrategia([_nivel([SI, NO])]), _dentro())
    assert len(p.evaluar(r, TK)) == 1
    assert p.evaluar(r, TK) == []          # misma vela: frenada


def test_telegram_dice_que_falta_y_no_pone_acciones():
    e = PrealertaSimple().evaluar(_runner(_estrategia([_nivel([SI, NO])]), _dentro()), TK)[0]
    texto = formatear(e)
    assert "PREALERTA" in texto and "AÑADIR" in texto
    assert "Falta: Bar Close &gt; 5.0" in texto or "Falta: Bar Close > 5.0" in texto
    assert "Acciones" not in texto
