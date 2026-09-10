"""Las salidas por tramos (take profits parciales) tienen que avisar TODAS.

EL FALLO QUE ESTO CUBRE. El motor recordaba las salidas ya avisadas por
`entry_idx`, o sea POR ENTRADA. Con take profits parciales una sola entrada
cierra en varios trades, así que avisaba del primer tramo y **descartaba los
demás en silencio**.

Pasó de verdad el 10-sep-2026 con `Estrategia 1B 50k`, que tiene tres:

    partial_take_profits = [HOUR:08:15 → 25 %, HOUR:08:30 → 50 %, HOUR:08:45 → 25 %]

Saltó el de las 08:15 para siete tickers y el de las 08:30 no avisó a nadie, con
el bot en marcha, sin una sola excepción ni línea de error. Jaume se quedó sin
saber que tenía que cerrar el 50 % de sus posiciones.

Efecto colateral: el dato de «cuántas acciones cerrar» que se añadió el 9-sep
estaba muerto para el 2º y 3er tramo, porque nunca llegaban a emitirse.
"""
import numpy as np
import pandas as pd
import pytest

from app.services import bot_alerts_engine as mod

VENTANA = {"inicio": "04:00", "fin": "16:00"}   # lejos del final: nada de EOD


def _frame(n):
    """Un frame mínimo: al motor le basta con timestamp y close aquí, porque
    `simulate` y `translate_strategy` van sustituidos."""
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-09-10 08:00", periods=n, freq="1min"),
        "open": np.full(n, 10.0), "high": np.full(n, 10.0),
        "low": np.full(n, 10.0), "close": np.full(n, 10.0),
        "volume": np.full(n, 1000.0),
    })


def _tramo(size, motivo="Partial TP (Hour)", exit_idx=1, precio=9.0):
    return {"entry_idx": 0, "exit_idx": exit_idx, "size": size,
            "exit_price": precio, "exit_reason": motivo, "status": "Closed"}


@pytest.fixture
def motor(monkeypatch):
    """Un MotorAlertas con el simulador sustituido: cada llamada devuelve los
    trades que la prueba quiera, que es como crece la lista en vivo."""
    guion = {"trades": []}

    def falso_simulate(**kw):
        return {"trades": list(guion["trades"])}

    def falso_translate(frame, sdef, stats, compiled=None):
        n = len(frame)
        return {"direction": "Short", "entries": np.zeros(n, dtype=bool)}

    monkeypatch.setattr(mod, "simulate", falso_simulate)
    monkeypatch.setattr(mod, "translate_strategy", falso_translate)
    monkeypatch.setattr(mod, "_kwargs_simulate", lambda *a, **k: {})

    m = mod.MotorAlertas([])
    m._guion = guion
    return m


EST = {
    "strategy_id": "s1", "name": "Estrategia 1B 50k", "definition": {},
    "compiled": None, "riesgo_usd": 300.0, "ventana": VENTANA,
}


def _vela(motor, n_velas, trades):
    """Avanza una vela con la lista de trades que exista en ese momento."""
    motor._guion["trades"] = trades
    return motor._procesar_estrategia("TNON", _frame(n_velas), {}, EST)


def test_los_tres_tramos_avisan_uno_por_uno(motor):
    """Lo que fallaba: solo salía el primero."""
    # vela 1: aún no ha cerrado nada
    assert _vela(motor, 2, []) == []

    # vela 2: cierra el primer tramo (25 %)
    ev = _vela(motor, 3, [_tramo(250.0)])
    assert len(ev) == 1
    assert ev[0].tipo == "salida"
    assert ev[0].acciones == 250.0

    # vela 3: cierra el segundo (50 %) — ANTES no avisaba
    ev = _vela(motor, 4, [_tramo(250.0), _tramo(500.0, exit_idx=3)])
    assert len(ev) == 1, "el segundo tramo se perdia en silencio"
    assert ev[0].acciones == 500.0

    # vela 4: cierra el tercero (25 %)
    ev = _vela(motor, 5, [_tramo(250.0), _tramo(500.0, exit_idx=3),
                          _tramo(250.0, exit_idx=4)])
    assert len(ev) == 1
    assert ev[0].acciones == 250.0


def test_un_tramo_ya_avisado_no_se_repite(motor):
    """El motor se llama en CADA vela con la lista entera, así que sin memoria
    avisaría del mismo tramo una y otra vez."""
    _vela(motor, 3, [_tramo(250.0)])
    for velas in (4, 5, 6):
        assert _vela(motor, velas, [_tramo(250.0)]) == []


def test_el_porcentaje_de_la_posicion_sale_bien_en_cada_tramo(motor):
    """`posicion_total` es lo que se abrió: la suma de todos los tramos. Es lo
    que convierte «cierra 500 acciones» en «cierra el 50 % de 1.000»."""
    todos = [_tramo(250.0), _tramo(500.0, exit_idx=3), _tramo(250.0, exit_idx=4)]
    ev = _vela(motor, 5, todos)
    assert len(ev) == 3                      # de golpe: los tres a la vez
    assert [e.acciones for e in ev] == [250.0, 500.0, 250.0]
    assert all(e.posicion_total == 1000.0 for e in ev)


def test_dos_tramos_en_la_misma_vela_no_se_pisan(motor):
    """Pasa al arrancar el bot con las dos horas ya cumplidas: los dos tramos
    salen con el MISMO `exit_idx`, así que la clave no puede ser esa. Y el 1º y
    el 3º de 1B son los dos del 25 %, así que tampoco puede ser el tamaño."""
    ev = _vela(motor, 4, [_tramo(250.0, exit_idx=3), _tramo(250.0, exit_idx=3)])
    assert len(ev) == 2, "dos tramos iguales en la misma vela se fusionaban en uno"


def test_dos_entradas_distintas_siguen_separadas(motor):
    """La memoria es por (entrada, tramo): dos entradas del mismo ticker no
    pueden taparse entre ellas."""
    a = {"entry_idx": 0, "exit_idx": 2, "size": 100.0, "exit_price": 9.0,
         "exit_reason": "TP", "status": "Closed"}
    b = {"entry_idx": 5, "exit_idx": 7, "size": 200.0, "exit_price": 8.0,
         "exit_reason": "TP", "status": "Closed"}
    ev = _vela(motor, 9, [a, b])
    assert len(ev) == 2
    assert {e.acciones for e in ev} == {100.0, 200.0}


def test_el_cierre_sintetico_del_borde_no_avisa_ni_gasta_el_tramo(motor):
    """Un `EOD` en la última vela es la posición VIVA, no una salida. No se
    avisa — y cuando de verdad cierre, ese mismo tramo tiene que poder avisar."""
    vivo = {"entry_idx": 0, "exit_idx": 3, "size": 1000.0, "exit_price": 9.0,
            "exit_reason": "EOD", "status": "Closed"}
    assert _vela(motor, 4, [vivo]) == []

    # ahora cierra de verdad, en el mismo hueco
    real = {"entry_idx": 0, "exit_idx": 3, "size": 1000.0, "exit_price": 9.0,
            "exit_reason": "Partial TP (Hour)", "status": "Closed"}
    ev = _vela(motor, 5, [real])
    assert len(ev) == 1
    assert ev[0].acciones == 1000.0


# ── lo que QUEDA abierto, que es lo que se teclea en el broker ───────────
#
# `posicion_total - acciones` solo vale para el PRIMER tramo. Con los tres de
# 1B (25 %, 50 %, 25 % sobre 1.000) esa resta decia «quedan 500» en el segundo
# (quedan 250) y «quedan 750» en el tercero, que es el que cierra del todo.
#
# El simulador deja SIEMPRE un EOD sintetico con lo que sigue abierto, asi que
# la suma de tramos da la posicion original aunque aun no haya cerrado entera.
def _eod(size, exit_idx=9):
    return _tramo(size, motivo="EOD", exit_idx=exit_idx)


def test_lo_que_queda_descuenta_los_tramos_ya_cerrados(motor):
    ev = _vela(motor, 6, [_tramo(250.0), _eod(750.0)])
    assert ev[0].posicion_total == 1000.0
    assert ev[0].posicion_restante == 750.0

    ev = _vela(motor, 7, [_tramo(250.0), _tramo(500.0, exit_idx=3), _eod(250.0)])
    assert ev[0].acciones == 500.0
    assert ev[0].posicion_total == 1000.0
    assert ev[0].posicion_restante == 250.0, "antes decia 500: no descontaba el 1er tramo"


def test_el_ultimo_tramo_deja_la_posicion_a_cero(motor):
    _vela(motor, 6, [_tramo(250.0), _eod(750.0)])
    _vela(motor, 7, [_tramo(250.0), _tramo(500.0, exit_idx=3), _eod(250.0)])
    ev = _vela(motor, 8, [_tramo(250.0), _tramo(500.0, exit_idx=3),
                          _tramo(250.0, exit_idx=4)])
    assert ev[0].acciones == 250.0
    assert ev[0].posicion_restante == 0.0


def test_los_tres_mensajes_de_telegram_salen_bien(motor):
    """La prueba que pidio Jaume: «todos los take profits, con la cantidad de
    acciones y demas, todo como en el primer take profit»."""
    from app.services import bot_alerts_telegram as tg
    import re

    def texto(evs):
        return re.sub("<[^>]+>", "", tg.formatear(evs[0]))

    t1 = texto(_vela(motor, 6, [_tramo(250.0), _eod(750.0)]))
    assert "CIERRE PARCIAL" in t1
    assert "Acciones a cerrar: 250" in t1
    assert "25 % de 1.000" in t1 and "quedan 750" in t1

    t2 = texto(_vela(motor, 7, [_tramo(250.0), _tramo(500.0, exit_idx=3), _eod(250.0)]))
    assert "CIERRE PARCIAL" in t2
    assert "Acciones a cerrar: 500" in t2
    assert "50 % de 1.000" in t2 and "quedan 250" in t2

    t3 = texto(_vela(motor, 8, [_tramo(250.0), _tramo(500.0, exit_idx=3),
                                _tramo(250.0, exit_idx=4)]))
    assert "CIERRE POS." in t3, "el ultimo tramo cierra del todo, no es parcial"
    assert "Acciones a cerrar: 250" in t3


# ── NO ES SOLO PARA 1B NI SOLO POR HORA ──────────────────────────────────
#
# Requisito de Jaume: «que el arreglo no sea exclusivo para esta estrategia,
# debe tenerlo en cuenta para cualquiera, ya sea salir por % y hora, como por
# minutos como cualquier cosa».
#
# El arreglo vive en el motor y NO mira `exit_reason` en ningun momento: opera
# sobre los trades que emite el simulador, sean del tipo que sean. Esto lo
# demuestra en vez de darlo por hecho. Los cuatro tipos que existen salen de
# `portfolio_sim.py`:
#
#     Partial TP          (por distancia en %)
#     Partial TP (Hour)   (a una hora del reloj)
#     Partial TP (Time)   (a los N minutos de entrar)
#     Partial TP (EOD)    (al cierre de la sesion)
TIPOS = ["Partial TP", "Partial TP (Hour)", "Partial TP (Time)", "Partial TP (EOD)"]


@pytest.mark.parametrize("motivo", TIPOS)
def test_los_tramos_avisan_sea_cual_sea_el_tipo_de_salida(motor, motivo):
    ev = _vela(motor, 6, [_tramo(300.0, motivo=motivo), _eod(700.0)])
    assert len(ev) == 1 and ev[0].acciones == 300.0
    assert ev[0].posicion_restante == 700.0

    ev = _vela(motor, 7, [_tramo(300.0, motivo=motivo),
                          _tramo(400.0, motivo=motivo, exit_idx=3), _eod(300.0)])
    assert len(ev) == 1, f"el 2o tramo se perdia con {motivo}"
    assert ev[0].acciones == 400.0
    assert ev[0].posicion_restante == 300.0

    ev = _vela(motor, 8, [_tramo(300.0, motivo=motivo),
                          _tramo(400.0, motivo=motivo, exit_idx=3),
                          _tramo(300.0, motivo=motivo, exit_idx=4)])
    assert len(ev) == 1 and ev[0].posicion_restante == 0.0


def test_tipos_MEZCLADOS_en_la_misma_posicion(motor):
    """Una estrategia puede tener un tramo por % y otro por hora. Nada en el
    motor los distingue, asi que la mezcla tiene que funcionar igual."""
    ev = _vela(motor, 6, [_tramo(250.0, motivo="Partial TP"), _eod(750.0)])
    assert ev[0].acciones == 250.0 and ev[0].posicion_restante == 750.0

    ev = _vela(motor, 7, [_tramo(250.0, motivo="Partial TP"),
                          _tramo(500.0, motivo="Partial TP (Hour)", exit_idx=3),
                          _eod(250.0)])
    assert ev[0].acciones == 500.0 and ev[0].posicion_restante == 250.0

    # y el resto lo cierra un STOP, no un take profit
    ev = _vela(motor, 8, [_tramo(250.0, motivo="Partial TP"),
                          _tramo(500.0, motivo="Partial TP (Hour)", exit_idx=3),
                          _tramo(250.0, motivo="Stop Loss", exit_idx=4)])
    assert len(ev) == 1
    assert ev[0].motivo == "Stop Loss"
    assert ev[0].posicion_restante == 0.0


def test_una_salida_normal_de_una_sola_pieza_no_cambia(motor):
    """Sin parciales, un unico trade cierra la posicion entera: tiene que
    seguir saliendo como CIERRE POS. y sin la linea de porcentajes."""
    from app.services import bot_alerts_telegram as tg
    import re
    ev = _vela(motor, 5, [_tramo(1000.0, motivo="Take Profit", exit_idx=3)])
    assert len(ev) == 1
    assert ev[0].posicion_total == 1000.0
    assert ev[0].posicion_restante == 0.0
    t = re.sub("<[^>]+>", "", tg.formatear(ev[0]))
    assert "CIERRE POS." in t
    assert "quedan" not in t

