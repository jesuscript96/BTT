# -*- coding: utf-8 -*-
"""`/evf` con paquetes de 100 y veredicto POR ESTRATEGIA.

EL FALLO QUE ARREGLA ESTO (Jaume, 8-sep-2026): «yo cuando pago locates no es por
unidad, es por paquetes, y ese paquete entero es el que se divide entre todas las
acciones». El comando calculaba el fade con el precio del bróker tal cual, o sea
como si se alquilaran exactamente las acciones que se operan. Con 150 acciones se
pagan DOS paquetes —200 acciones de alquiler— y el coste real por acción sube un
33 %. La cuenta de paquetes ya existía en el código, pero colgada de un cuarto
parámetro OPCIONAL Y NO DOCUMENTADO: en la práctica no se usaba nunca.

LA REGLA QUE NO SE PUEDE ROMPER: esto es SOLO consulta. El tamaño que da `/evf`
es una estimación al precio del momento y NO debe coincidir con el del aviso —
el aviso sale de su propia vela y es la orden que se teclea en el bróker.
Igualarlos daría un tamaño de entrada equivocado, que es lo contrario de lo que
se quiere.
"""
import pandas as pd
import pytest

from app.services.bot_alerts_comandos import (
    NEGATIVA,
    POSITIVA,
    responder,
    veredicto_locates,
)
from app.services.bot_alerts_engine import estimar_por_estrategia, stop_estimado


def _fila(nombre="1B 50k", riesgo=300.0, ev=2.4, acciones=150.0, motivo=None):
    return {"nombre": nombre, "riesgo_usd": riesgo, "ev_pct": ev,
            "acciones": acciones, "stop": None, "motivo": motivo}


# ══ 1. La aritmética de los paquetes ══════════════════════════════════════
def test_150_acciones_pagan_2_paquetes():
    """El ejemplo de Jaume: 150 acciones NO son 150 locates."""
    r = veredicto_locates("MIMI", 1.0, 0.01, 0, estrategias=[_fila(acciones=150)])
    assert "2 paquetes" in r
    assert "200 alquiladas" in r
    # coste real = 2 x 100 x 0,01 / 150 = 0,013333
    assert "0.0133" in r


def test_101_acciones_casi_doblan_el_coste():
    """El peor punto del diente de sierra: justo pasada la frontera."""
    r = veredicto_locates("MIMI", 1.0, 0.01, 0, estrategias=[_fila(acciones=101)])
    assert "2 paquetes" in r
    # 2 x 100 x 0,01 / 101 = 0,019802 -> casi el doble de 0,01
    assert "0.0198" in r


def test_100_justas_no_encarecen_nada():
    """Multiplo exacto: el coste real ES el del broker y no se repite."""
    r = veredicto_locates("MIMI", 1.0, 0.01, 0, estrategias=[_fila(acciones=100)])
    assert "1 paquete" in r
    assert "nominal" not in r        # no hay nada que aclarar


def test_el_redondeo_puede_dar_la_vuelta_al_veredicto():
    """Y solo pasa cuando el margen ya era estrecho — justo cuando se pregunta.

    precio 3 $, locate 0,01 $/accion, EV 0,40 %.
      nominal:      fade 0,3333 %  -> margen +0,067 pp  -> COMPENSA
      301 acciones: fade 0,4430 %  -> margen -0,043 pp  -> NO COMPENSA
    """
    holgado = veredicto_locates("MIMI", 3.0, 0.01, 0,
                                estrategias=[_fila(ev=0.40, acciones=300)])
    justo = veredicto_locates("MIMI", 3.0, 0.01, 0,
                              estrategias=[_fila(ev=0.40, acciones=301)])
    assert POSITIVA in holgado
    assert NEGATIVA in justo


def test_el_tamano_grande_diluye_el_redondeo():
    """Con posiciones grandes es ruido, y el mensaje no debe dramatizarlo."""
    r = veredicto_locates("MIMI", 1.0, 0.01, 0, estrategias=[_fila(acciones=10_000)])
    assert "100 paquetes" in r
    assert "nominal" not in r


# ══ 2. Un veredicto POR ESTRATEGIA ════════════════════════════════════════
def test_cada_estrategia_tiene_su_veredicto():
    """Distinto riesgo y distinto EV = distinto tamaño y distinto veredicto.

    El mismo locate puede compensar para una estrategia y no para otra; un
    veredicto unico no podia decir eso.
    """
    r = veredicto_locates("MIMI", 1.0, 0.01, 0, estrategias=[
        _fila("Buena", ev=5.0, acciones=500),
        _fila("Mala", ev=0.5, acciones=101),
    ])
    assert "Buena" in r and "Mala" in r
    assert POSITIVA in r and NEGATIVA in r


def test_se_dice_el_riesgo_de_cada_una():
    r = veredicto_locates("MIMI", 1.0, 0.01, 0,
                          estrategias=[_fila(riesgo=300.0)])
    assert "riesgo 300 $" in r


def test_sin_ev_no_se_inventa_veredicto():
    """Una estrategia sin EV en el cuadro de mandos se dice, no se rellena."""
    r = veredicto_locates("MIMI", 1.0, 0.01, 0, estrategias=[_fila(ev=None)])
    assert POSITIVA not in r and NEGATIVA not in r
    assert "sin EV" in r


def test_sin_riesgo_no_hay_tamano():
    r = veredicto_locates("MIMI", 1.0, 0.01, 0,
                          estrategias=[_fila(riesgo=None, acciones=None,
                                             motivo="sin riesgo fijado en el cuadro de mandos")])
    assert "sin riesgo fijado" in r


def test_avisa_de_que_los_tamanos_son_estimados():
    """LA FRASE IMPORTANTE: si alguien teclea estas acciones en el broker
    creyendo que son las del aviso, mete una posicion equivocada."""
    r = veredicto_locates("MIMI", 1.0, 0.01, 0, estrategias=[_fila()])
    assert "estimados" in r


# ══ 3. El camino de siempre NO cambia ═════════════════════════════════════
def test_sin_estrategias_se_comporta_como_antes():
    """Con un EV escrito a mano sigue saliendo el veredicto unico de siempre."""
    r = veredicto_locates("MIMI", 0.8422, 0.010, 2.4)
    assert POSITIVA in r
    assert "1.187" in r


def test_un_ev_escrito_a_mano_pisa_el_desglose():
    """Escribir el EV sirve para probar un valor suelto, y eso se conserva."""
    llamadas = []

    def _estimacion(tk, precio):
        llamadas.append(tk)
        return [_fila()]

    r = responder("/evf MIMI 0.01 6.4", lambda t: 1.0, estimacion_de=_estimacion)
    assert llamadas == [], "con EV a mano no se pide la estimacion"
    assert "1B 50k" not in r


def test_sin_ev_y_sin_estimacion_lo_dice():
    r = responder("/evf MIMI 0.01", lambda t: 1.0)
    assert "No tengo EV" in r


def test_una_estimacion_que_falla_no_tumba_el_comando():
    """Preguntar por Telegram NUNCA puede romper el bucle de velas."""
    def _rota(tk, precio):
        raise RuntimeError("el runner esta a medias")

    r = responder("/evf MIMI 0.01", lambda t: 1.0, ev_guardado=2.4,
                  estimacion_de=_rota)
    assert r and POSITIVA in r          # cae al veredicto unico, no revienta


# ══ 4. El stop estimado ═══════════════════════════════════════════════════
def _sdef(hard_stop, bias="short", size_by_sl=True):
    return {"bias": bias,
            "risk_management": {"use_hard_stop": True, "hard_stop": hard_stop,
                                "size_by_sl": size_by_sl}}


def test_el_stop_por_porcentaje_SI_se_resuelve():
    """`nivel_stop` devuelve None con stop porcentual porque en el backtest lo
    resuelve el simulador a partir de `sl_stop`. `stop_estimado` SI lo resuelve,
    usando esa misma fraccion: sin ella el tamano saldria por precio y no por
    riesgo, que es otro numero (y por eso el aviso daba 57 acciones donde el
    motor dimensiona 230).

    LA FRACCION SE PASA, NO SE RECALCULA. Rehacerla a mano salia mal en «Fixed
    Amount», donde el motor divide el importe entre el PRIMER CIERRE DEL DIA y
    no entre el precio de ahora."""
    stop = stop_estimado(_sdef({"type": "Percentage", "value": 10}),
                         None, 0, 2.0, es_largo=False, sl_stop=0.10)
    assert stop == pytest.approx(2.2)        # short: 10 % por encima


def test_el_stop_por_porcentaje_en_largo():
    stop = stop_estimado(_sdef({"type": "Percentage", "value": 10}, bias="long"),
                         None, 0, 2.0, es_largo=True, sl_stop=0.10)
    assert stop == pytest.approx(1.8)


def test_sin_la_fraccion_no_se_inventa_el_stop():
    """Sin `sl_stop` no hay de donde sacarlo, y devolver un numero a ojo seria
    peor: acabaria en un tamano equivocado sin que nada avisara."""
    assert stop_estimado(_sdef({"type": "Percentage", "value": 10}),
                         None, 0, 2.0, es_largo=False) is None


def test_un_stop_que_no_se_sabe_calcular_no_se_inventa():
    """ATR y compania necesitan el frame del simulador: mejor None que un
    numero falso que acabaria en un tamano falso."""
    assert stop_estimado(_sdef({"type": "ATR Multiplier", "value": 2}),
                         None, 0, 2.0, es_largo=False) is None


def test_de_stop_a_acciones():
    """La cuenta entera: riesgo 300 $, stop al 10 % de 2,00 -> 0,20 de
    distancia -> 1.500 acciones."""
    filas = estimar_por_estrategia(
        [{"name": "X", "riesgo_usd": 300.0, "ev_pct": 2.4,
          "definition": _sdef({"type": "Percentage", "value": 10})}],
        lambda e: e["definition"], None, 0, 2.0, lambda e: 0.10,
    )
    assert filas[0]["acciones"] == pytest.approx(1500.0)
    assert filas[0]["stop"] == pytest.approx(2.2)


def test_sin_size_by_sl_el_tamano_va_por_precio():
    filas = estimar_por_estrategia(
        [{"name": "X", "riesgo_usd": 300.0, "ev_pct": 2.4,
          "definition": _sdef({"type": "Percentage", "value": 10}, size_by_sl=False)}],
        lambda e: e["definition"], None, 0, 2.0, lambda e: 0.10,
    )
    assert filas[0]["acciones"] == pytest.approx(150.0)   # 300 / 2,00


def test_una_estrategia_sin_riesgo_se_salta_pero_aparece():
    filas = estimar_por_estrategia(
        [{"name": "X", "riesgo_usd": None, "ev_pct": 2.4,
          "definition": _sdef({"type": "Percentage", "value": 10})}],
        lambda e: e["definition"], None, 0, 2.0, lambda e: 0.10,
    )
    assert filas[0]["acciones"] is None
    assert "sin riesgo" in filas[0]["motivo"]


# ══ 5. Las coletillas ═════════════════════════════════════════════════════
# Jaume las echó de menos al ver el desglose nuevo: la primera versión del
# veredicto por estrategia devolvía antes de llegar al `random.choice`, así que
# el mensaje salía correcto y seco. Son parte del comando, no un adorno.

def test_cada_estrategia_lleva_su_coletilla():
    r = veredicto_locates("MIMI", 1.0, 0.01, 0, estrategias=[
        _fila("Buena", ev=5.0, acciones=500),
        _fila("Mala", ev=0.05, acciones=101),
    ])
    from app.services.bot_alerts_comandos import _FRASES_NO, _FRASES_SI
    assert any(f in r for f in _FRASES_SI), "falta la coletilla del veredicto bueno"
    assert any(f in r for f in _FRASES_NO), "falta la del malo"


def test_no_se_repite_la_misma_frase_en_un_mensaje():
    """Tres estrategias con el MISMO veredicto no pueden salir con la misma
    frase tres veces: con `random.choice` a pelo pasaba y parecía roto."""
    from app.services.bot_alerts_comandos import _FRASES_SI
    for _ in range(40):
        r = veredicto_locates("MIMI", 1.0, 0.01, 0, estrategias=[
            _fila("A", ev=5.0, acciones=500),
            _fila("B", ev=5.0, acciones=500),
            _fila("C", ev=5.0, acciones=500),
        ])
        usadas = [f for f in _FRASES_SI if f in r]
        assert len(usadas) == 3, f"salieron {len(usadas)} frases distintas, no 3"


def test_la_coletilla_va_pegada_a_su_veredicto():
    """Con varias estrategias, una frase suelta al final no diría a cuál se
    refiere. Tiene que ir en la línea siguiente a su propio veredicto."""
    from app.services.bot_alerts_comandos import _FRASES_NO
    r = veredicto_locates("MIMI", 1.0, 0.01, 0, estrategias=[
        _fila("Buena", ev=5.0, acciones=500),
        _fila("Mala", ev=0.05, acciones=101),
    ])
    lineas = r.split("\n")
    i = next(k for k, l in enumerate(lineas) if NEGATIVA in l)
    assert any(f in lineas[i + 1] for f in _FRASES_NO)
