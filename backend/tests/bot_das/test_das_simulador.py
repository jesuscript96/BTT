"""Tests del «DAS falso» (`app.bot_das.simulador_das`, documento §3.3 y fila de §10).

QUÉ HACE. Prueba el motor de cruce (`Emparejador`) sin socket —límite,
PostOnly, MKT, STOPLMTP, parciales, rechazos, halt/reabrir y ruta OPEN,
variantes de `%ORDER`, las 6 permutaciones de `%OrderAct/%TRADE/%POS`,
`desde_vela` con `ModeloSpread`, locates y GET— y el servidor TCP
(`SimuladorDAS`) en 127.0.0.1:0 con clientes crudos: LOGIN y volcado, watch con
`%IORDER/%IPOS/%ITRADE`, SB/UNSB, corte, emisión a trozos, latencia. Cada
línea que el simulador produce se pasa por el `Parser` real del protocolo: no
puede salir nada que el bot no entienda.

POR QUÉ ESTÁ AQUÍ. El simulador es la base de los tests del cliente, del
ejecutor y del vigilante y el motor de la fase sombra (R-O-03): si cruza mal,
todos esos tests prueban otra cosa sin avisar.

LAS TRAMPAS. Ningún sleep > 0,5 s (se espera por condición con plazo); los
sockets se cierran siempre (fixtures con finally); los usuarios son inventados
(«prueba»), nunca los del manual; nada de red salvo 127.0.0.1.
"""
from __future__ import annotations

import itertools
import json
import socket
import subprocess
import sys
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Callable, Optional

import pytest

from app.bot_das import simulador_das as sd
from app.bot_das.protocolo import Parser
from app.bot_das.reloj import ET, RelojSimulado
from app.bot_das.simulador_das import (
    Emparejador,
    LibroSimulado,
    ModeloSpread,
    ProgramaGuion,
    SimuladorDAS,
)
from app.bot_das.tipos import (
    MsgAccountInfo,
    MsgBP,
    MsgConexion,
    MsgDesconocido,
    MsgIssueStatus,
    MsgLDLU,
    MsgMarcador,
    MsgOrden,
    MsgOrderAct,
    MsgPos,
    MsgQuote,
    MsgRouteStatus,
    MsgShortInfo,
    MsgSLAvail,
    MsgSLMinCharge,
    MsgSLOrder,
    MsgSLRet,
    MsgSLReuse,
    MsgTrade,
)

FIXTURES = Path(__file__).parent / "fixtures"
GUION = FIXTURES / "guion_replay_ejemplo.json"
BACKEND = Path(__file__).resolve().parents[2]
CUENTA = "CUENTA_PRUEBA"
USUARIOS = {"prueba": "prueba"}          # inventados (§3.3): nunca las credenciales de ejemplo del manual
T1 = 126800001                           # tokens con el esquema del bot para el 25-sep-2026 (día 268)
T2 = 126800002
T3 = 126800003
PLAZO_S = 2.0


# ══════════════════════════════════════════════════════════════════════
# ayudantes
# ══════════════════════════════════════════════════════════════════════
def D(x: str) -> Decimal:
    return Decimal(x)


def parsear(lineas: list[str], watch: bool = False) -> list:
    """Parsea con el Parser REAL y exige que ninguna línea quede como MsgDesconocido."""
    parser = Parser(lambda t: True, watch=watch, cuenta=CUENTA)
    mensajes = [parser.parsear(x) for x in lineas]
    malas = [m.cruda for m in mensajes if isinstance(m, MsgDesconocido)]
    assert not malas, f"líneas que el bot no entendería: {malas}"
    return mensajes


def claves(lineas: list[str]) -> list[str]:
    return [x.split(" ", 2)[0] + ("" if not x.startswith("%OrderAct") else " " + x.split(" ")[2]) for x in lineas]


def de_tipo(mensajes: list, clase: type) -> list:
    return [m for m in mensajes if isinstance(m, clase)]


def ultima_orden(mensajes: list) -> MsgOrden:
    ordenes = de_tipo(mensajes, MsgOrden)
    assert ordenes, "no llegó ningún %ORDER"
    return ordenes[-1]


@pytest.fixture
def emp(libro: LibroSimulado, reloj: RelojSimulado) -> Emparejador:
    return Emparejador(libro, reloj)


def orden(libro: LibroSimulado, id_das: int) -> dict:
    return next(o for o in libro.ordenes() if o["id"] == id_das)


# ══════════════════════════════════════════════════════════════════════
# ModeloSpread y desde_vela (injerto A §8.24, riesgo 28)
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("cierre, pct, minimo, bid, ask", [
    pytest.param("2.45", "0.5", 1, "2.44", "2.46", id="8.24-spread-0.5pct-redondeado-al-tick"),
    pytest.param("10", "0.5", 1, "9.97", "10.02", id="8.24-spread-exacto-5-ticks"),
    pytest.param("2.45", "0", 1, "2.44", "2.45", id="8.24-minimo-1-tick-con-pct-0"),
    pytest.param("2.45", "0", 0, "2.45", "2.45", id="8.24-spread-cero"),
    pytest.param("0.5", "0.5", 1, "0.4987", "0.5012", id="8.24-menos-de-1-dolar-tick-0.0001"),
    pytest.param("2.4567", "0.5", 3, "2.44", "2.47", id="8.24-cierre-fuera-de-tick-y-minimo-3"),
    pytest.param("0.9999", "0.5", 1, "0.9974", "1.01", id="8.24-ask-cruza-1-dolar-sube-al-centimo"),
    pytest.param("0.0002", "50", 5, "0.0001", "0.0006", id="8.24-bid-no-baja-de-un-tick"),
])
def test_spread_precios(cierre, pct, minimo, bid, ask):
    b, a = ModeloSpread(pct=D(pct), minimo_ticks=minimo).precios(D(cierre))
    assert (b, a) == (D(bid), D(ask))
    assert isinstance(b, Decimal) and isinstance(a, Decimal)
    assert a >= b


@pytest.mark.parametrize("kwargs", [
    pytest.param({"pct": 0.5}, id="pct-float-no"),
    pytest.param({"pct": D("-1")}, id="pct-negativo"),
    pytest.param({"pct": D("NaN")}, id="pct-nan"),
    pytest.param({"minimo_ticks": -1}, id="minimo-negativo"),
    pytest.param({"tamano_bid": 0}, id="tamano-bid-0"),
    pytest.param({"tamano_ask": 1.5}, id="tamano-float"),
    pytest.param({"tamano_ask": True}, id="tamano-bool"),
])
def test_spread_invalido(kwargs):
    with pytest.raises(ValueError):
        ModeloSpread(**kwargs)


def test_desde_vela_convierte_float_una_vez_y_emite_quote(libro: LibroSimulado):
    """Riesgo 12: la vela de fuente_senales trae float; el libro guarda Decimal(str(x)) y tamaños del modelo."""
    vela = {"open": 2.4, "high": 2.5, "low": 2.3, "close": 2.45, "volume": 12345.0}
    lineas = libro.desde_vela("ABCD", vela, ModeloSpread(tamano_bid=300, tamano_ask=700))
    q = libro.cotizacion("ABCD")
    assert (q["bid"], q["ask"], q["last"], q["volumen"]) == (D("2.44"), D("2.46"), D("2.45"), 12345)
    assert (q["tamano_bid"], q["tamano_ask"]) == (300, 700)
    (msg,) = parsear(lineas)
    assert isinstance(msg, MsgQuote)
    assert msg.campos == {"A": "2.46", "Asz": "7", "B": "2.44", "Bsz": "3", "V": "12345", "L": "2.45"}


@pytest.mark.parametrize("vela", [
    pytest.param({"open": 1.0}, id="sin-close"),
    pytest.param({"close": float("nan")}, id="close-nan"),
    pytest.param({"close": 0}, id="close-cero"),
    pytest.param({"close": True}, id="close-bool"),
])
def test_desde_vela_invalida(libro: LibroSimulado, vela):
    with pytest.raises(ValueError):
        libro.desde_vela("ABCD", vela, ModeloSpread())


def test_desde_vela_exige_modelo(libro: LibroSimulado):
    with pytest.raises(ValueError):
        libro.desde_vela("ABCD", {"close": 2.45}, {"pct": "0.5"})


# ══════════════════════════════════════════════════════════════════════
# LibroSimulado: cotizaciones y validaciones
# ══════════════════════════════════════════════════════════════════════
def test_cotizar_quote_en_lotes_y_sin_notacion_cientifica(libro: LibroSimulado):
    (linea,) = libro.cotizar("ABCD", D("100"), D("100.01"), last=D("1E+2"), volumen=5, vwap=D("99.5"),
                             tamano_bid=250, tamano_ask=1000)
    assert linea == "$Quote ABCD A:100.01 Asz:10 B:100 Bsz:2 V:5 L:100 VWAP:99.5"
    assert "E" not in linea


def test_cotizar_sin_tamanos_es_liquidez_sin_tope(libro: LibroSimulado):
    (linea,) = libro.cotizar("ABCD", D("2.44"), D("2.46"))
    assert linea == "$Quote ABCD A:2.46 B:2.44"
    assert libro.cotizacion("ABCD")["tamano_bid"] is None
    assert libro.cotizacion("WXYZ") is None


def test_cotizar_conserva_last_si_no_llega(libro: LibroSimulado):
    libro.cotizar("ABCD", D("2.44"), D("2.46"), last=D("2.45"))
    libro.cotizar("ABCD", D("2.40"), D("2.42"))
    assert libro.cotizacion("ABCD")["last"] == D("2.45")


@pytest.mark.parametrize("args, kwargs", [
    pytest.param(("ABCD", D("2.46"), D("2.44")), {}, id="libro-cruzado"),
    pytest.param(("ABCD", D("0"), D("2.44")), {}, id="bid-cero"),
    pytest.param(("ABCD", D("NaN"), D("2.44")), {}, id="bid-nan"),
    pytest.param(("AB CD", D("2.44"), D("2.46")), {}, id="ticker-con-espacio"),
    pytest.param(("ABCD", D("2.44"), D("2.46")), {"volumen": 1.5}, id="volumen-float"),
    pytest.param(("ABCD", D("2.44"), D("2.46")), {"tamano_bid": -1}, id="tamano-negativo"),
])
def test_cotizar_invalido(libro: LibroSimulado, args, kwargs):
    with pytest.raises(ValueError):
        libro.cotizar(*args, **kwargs)


@pytest.mark.parametrize("llamada", [
    pytest.param(lambda lib: lib.halt("ABCD", "T", "10:00:00"), id="R-F-01-halt-con-TA-T"),
    pytest.param(lambda lib: lib.halt("ABCD", "H", "10 00"), id="R-F-01-tat-con-espacio"),
    pytest.param(lambda lib: lib.bandas("ABCD", D("3"), D("2")), id="R-F-02-bandas-invertidas"),
    pytest.param(lambda lib: lib.rechazar_siguiente("x", "Execute"), id="R-B-07-accion-desconocida"),
    pytest.param(lambda lib: lib.rechazar_siguiente("a\nb"), id="R-B-07-notas-multilinea"),
    pytest.param(lambda lib: lib.rechazar_siguiente("x", token_o_orden="1"), id="R-B-07-token-texto"),
    pytest.param(lambda lib: lib.llenar_parcial(D("0")), id="R-B-02-fraccion-cero"),
    pytest.param(lambda lib: lib.llenar_parcial(D("1.5")), id="R-B-02-fraccion-mayor-1"),
    pytest.param(lambda lib: lib.sembrar_posicion("ABCD", 1.0, D("2")), id="F12-neta-float"),
    pytest.param(lambda lib: lib.configurar_locate("ABCD", tipo_ruta=2), id="R-H-tipo-ruta-2"),
    pytest.param(lambda lib: lib.configurar_locate("ABCD", disponibles=-1), id="R-H-disponibles-negativos"),
])
def test_libro_valida_entradas(libro: LibroSimulado, llamada):
    with pytest.raises(ValueError):
        llamada(libro)


# ══════════════════════════════════════════════════════════════════════
# Emparejador: reglas de cruce (§3.3)
# ══════════════════════════════════════════════════════════════════════
def test_venta_limite_bajo_bid_se_llena_al_bid(libro, emp):
    """§3.3: venta límite con precio ≤ bid se llena al LLEGAR, al bid (liquidez quitada)."""
    libro.cotizar("ABCD", D("2.45"), D("2.47"), last=D("2.46"))
    lineas = emp.recibir(f"NEWORDER {T1} SS ABCD SAGEPRO 300 2.44 TIF=DAY+")
    msgs = parsear(lineas)
    assert claves(lineas) == ["%OrderAct Sending", "%OrderAct Accept", "%ORDER", "%OrderAct Execute", "%ORDER",
                              "%TRADE", "%POS"]
    ejecucion = de_tipo(msgs, MsgOrderAct)[-1]
    assert (ejecucion.accion, ejecucion.lado, ejecucion.qty, ejecucion.precio, ejecucion.token) == (
        "Execute", "SS", 300, D("2.45"), T1)
    assert ejecucion.notas == ""
    (trade,) = de_tipo(msgs, MsgTrade)
    assert (trade.qty, trade.precio, trade.liq, trade.id_orden) == (300, D("2.45"), "-", ejecucion.id)
    (pos,) = de_tipo(msgs, MsgPos)
    assert (pos.neta, pos.tipo, pos.avg) == (-300, 3, D("2.45"))
    o = ultima_orden(msgs)
    assert (o.estado.value, o.qty, o.lvqty, o.token) == ("Executed", 300, 0, T1)
    assert libro.posiciones() == {"ABCD": -300}


def test_orderact_notas_vacias_lleva_dos_espacios(libro, emp):
    """Manual L934-936: notas vacías = DOS espacios antes del token."""
    libro.cotizar("ABCD", D("2.45"), D("2.47"))
    lineas = emp.recibir(f"NEWORDER {T1} SS ABCD SAGEREB 100 2.5 PostOnly TIF=DAY+")
    assert lineas[1].endswith(f"  {T1}")


def test_venta_postonly_que_cruza_se_rechaza(libro, emp):
    """§3.3: PostOnly que cruzaría → Send_Rej «PostOnly would cross», %ORDER Rejected, sin posición."""
    libro.cotizar("ABCD", D("2.45"), D("2.47"))
    lineas = emp.recibir(f"NEWORDER {T1} SS ABCD SAGEREB 300 2.45 PostOnly TIF=DAY+")
    msgs = parsear(lineas)
    rechazo = [m for m in de_tipo(msgs, MsgOrderAct) if m.accion == "Send_Rej"]
    assert len(rechazo) == 1
    assert (rechazo[0].notas, rechazo[0].token, rechazo[0].qty) == ("PostOnly would cross", T1, 300)
    assert ultima_orden(msgs).estado.value == "Rejected"
    assert libro.posiciones() == {}
    assert not de_tipo(msgs, MsgTrade)


def test_venta_limite_reposa_y_se_llena_a_su_precio(libro, emp):
    """§3.3: sobre el bid reposa (Accepted) y se llena a SU precio cuando bid ≥ precio (liquidez añadida)."""
    libro.cotizar("ABCD", D("2.45"), D("2.47"))
    msgs = parsear(emp.recibir(f"NEWORDER {T1} SS ABCD SAGEREB 300 2.46 PostOnly TIF=DAY+"))
    assert ultima_orden(msgs).estado.value == "Accepted"
    assert emp.tic() == []
    libro.cotizar("ABCD", D("2.46"), D("2.48"))
    msgs = parsear(emp.tic())
    (trade,) = de_tipo(msgs, MsgTrade)
    assert (trade.precio, trade.qty, trade.liq) == (D("2.46"), 300, "+")
    assert libro.posiciones()["ABCD"] == -300


def test_venta_reposa_llenada_con_bid_por_encima_va_a_su_precio(libro, emp):
    libro.cotizar("ABCD", D("2.45"), D("2.47"))
    emp.recibir(f"NEWORDER {T1} SS ABCD SAGEREB 100 2.46 TIF=DAY+")
    libro.cotizar("ABCD", D("2.50"), D("2.52"))
    (trade,) = de_tipo(parsear(emp.tic()), MsgTrade)
    assert trade.precio == D("2.46")


def test_compra_limite_sobre_ask_se_llena_al_ask(libro, emp):
    """Compra simétrica: precio ≥ ask se llena al ask; cubre el corto con P/L realizado."""
    libro.sembrar_posicion("ABCD", -300, D("2.50"))
    libro.cotizar("ABCD", D("2.38"), D("2.40"))
    msgs = parsear(emp.recibir(f"NEWORDER {T2} B ABCD SAGEPRO 300 2.42 TIF=DAY+"))
    (trade,) = de_tipo(msgs, MsgTrade)
    assert (trade.precio, trade.pl) == (D("2.4"), D("30"))
    (pos,) = de_tipo(msgs, MsgPos)
    assert pos.neta == 0
    assert libro.posiciones() == {"ABCD": 0}


def test_compra_postonly_que_cruza_se_rechaza(libro, emp):
    libro.cotizar("ABCD", D("2.38"), D("2.40"))
    msgs = parsear(emp.recibir(f"NEWORDER {T2} B ABCD SAGEREB 100 2.4 PostOnly TIF=DAY+"))
    assert [m.notas for m in de_tipo(msgs, MsgOrderAct) if m.accion == "Send_Rej"] == ["PostOnly would cross"]


def test_compra_limite_reposa_y_se_llena_cuando_ask_baja(libro, emp):
    libro.cotizar("ABCD", D("2.38"), D("2.40"))
    emp.recibir(f"NEWORDER {T2} B ABCD SAGEREB 100 2.39 PostOnly TIF=DAY+")
    assert emp.tic() == []
    libro.cotizar("ABCD", D("2.37"), D("2.39"))
    (trade,) = de_tipo(parsear(emp.tic()), MsgTrade)
    assert (trade.precio, trade.lado, trade.liq) == (D("2.39"), "B", "+")
    assert libro.posiciones()["ABCD"] == 100


@pytest.mark.parametrize("lado, precio_fill, neta", [
    pytest.param("B", "2.47", 200, id="R-F-01-MKT-compra-al-ask"),
    pytest.param("SS", "2.45", -200, id="MKT-corto-al-bid"),
    pytest.param("S", "2.45", -200, id="MKT-venta-al-bid"),
])
def test_mercado_al_toque(libro, emp, lado, precio_fill, neta):
    libro.cotizar("ABCD", D("2.45"), D("2.47"))
    msgs = parsear(emp.recibir(f"NEWORDER {T1} {lado} ABCD OPEN 200 MKT TIF=DAY"))
    (trade,) = de_tipo(msgs, MsgTrade)
    assert trade.precio == D(precio_fill)
    assert ultima_orden(msgs).tipo == "MKT"
    assert libro.posiciones()["ABCD"] == neta


def test_mercado_sin_cotizacion_espera_a_la_primera(libro, emp):
    msgs = parsear(emp.recibir(f"NEWORDER {T1} B ABCD SAGEPRO 100 MKT TIF=DAY"))
    assert ultima_orden(msgs).estado.value == "Accepted"
    libro.cotizar("ABCD", D("2.45"), D("2.47"))
    (trade,) = de_tipo(parsear(emp.tic()), MsgTrade)
    assert (trade.precio, trade.liq) == (D("2.47"), "-")


def test_stoplmtp_compra_se_dispara_con_last_y_pasa_a_limite(libro, emp):
    """§3.3 / R-C-01: STOPLMTP de compra se dispara cuando last ≥ stop y se llena al ask si ask ≤ límite."""
    libro.cotizar("ABCD", D("2.89"), D("2.91"), last=D("2.90"))
    msgs = parsear(emp.recibir(f"NEWORDER {T3} B ABCD STOP 300 STOPLMTP 2.97 2.99 TIF=DAY+"))
    o = ultima_orden(msgs)
    assert (o.tipo, o.estado.value, o.precio) == ("SLP: 2.97 2.99", "Accepted", D("2.99"))
    libro.cotizar("ABCD", D("2.95"), D("2.96"), last=D("2.96"))
    assert emp.tic() == []
    assert orden(libro, o.id)["disparada"] is False
    libro.cotizar("ABCD", D("2.97"), D("2.98"), last=D("2.97"))
    (trade,) = de_tipo(parsear(emp.tic()), MsgTrade)
    assert (trade.precio, trade.qty, trade.liq) == (D("2.98"), 300, "-")
    assert orden(libro, o.id)["disparada"] is True


def test_stoplmtp_disparado_con_ask_sobre_limite_reposa_como_limite(libro, emp):
    libro.cotizar("ABCD", D("2.89"), D("2.91"), last=D("2.90"))
    msgs = parsear(emp.recibir(f"NEWORDER {T3} B ABCD STOP 300 STOPLMTP 2.97 2.99 TIF=DAY+"))
    id_das = ultima_orden(msgs).id
    libro.cotizar("ABCD", D("3.03"), D("3.05"), last=D("3.04"))
    assert emp.tic() == []
    assert orden(libro, id_das)["disparada"] is True
    libro.cotizar("ABCD", D("2.97"), D("2.99"), last=D("2.98"))
    (trade,) = de_tipo(parsear(emp.tic()), MsgTrade)
    assert (trade.precio, trade.liq) == (D("2.99"), "+")


def test_stoplmtp_ya_rebasado_al_llegar_se_dispara_en_el_acto(libro, emp):
    libro.cotizar("ABCD", D("2.97"), D("2.98"), last=D("2.98"))
    msgs = parsear(emp.recibir(f"NEWORDER {T3} B ABCD STOP 100 STOPLMTP 2.97 2.99 TIF=DAY+"))
    assert de_tipo(msgs, MsgTrade)[0].precio == D("2.98")


def test_stoplmtp_venta_se_dispara_con_last_bajo_el_stop(libro, emp):
    libro.sembrar_posicion("ABCD", 100, D("3"))
    libro.cotizar("ABCD", D("3.00"), D("3.02"), last=D("3.01"))
    emp.recibir(f"NEWORDER {T3} S ABCD STOP 100 STOPLMTP 2.9 2.85 TIF=DAY+")
    libro.cotizar("ABCD", D("2.88"), D("2.90"), last=D("2.89"))
    (trade,) = de_tipo(parsear(emp.tic()), MsgTrade)
    assert (trade.precio, trade.pl) == (D("2.88"), D("-12"))
    assert libro.posiciones()["ABCD"] == 0


def test_stoplmtp_sin_last_no_se_dispara(libro, emp):
    libro.cotizar("ABCD", D("3.00"), D("3.02"))
    emp.recibir(f"NEWORDER {T3} B ABCD STOP 100 STOPLMTP 2.97 2.99 TIF=DAY+")
    assert emp.tic() == []


# ══════════════════════════════════════════════════════════════════════
# parciales (R-B-02)
# ══════════════════════════════════════════════════════════════════════
def test_llenar_parcial_deja_el_resto_vivo_hasta_cancelar(libro, emp):
    """R-B-02: 300 con fracción 0,4 → 120 llenas, Partial, lvqty 180; CANCEL → Canceled por 180 (cxlqty)."""
    libro.llenar_parcial(D("0.4"))
    libro.cotizar("ABCD", D("2.45"), D("2.47"))
    msgs = parsear(emp.recibir(f"NEWORDER {T1} SS ABCD SAGEPRO 300 2.44 TIF=DAY+"))
    o = ultima_orden(msgs)
    assert (o.estado.value, o.lvqty, de_tipo(msgs, MsgTrade)[0].qty) == ("Partial", 180, 120)
    libro.cotizar("ABCD", D("2.45"), D("2.47"))
    assert emp.tic() == []
    msgs = parsear(emp.recibir(f"CANCEL {o.id}"))
    acts = de_tipo(msgs, MsgOrderAct)
    assert [(a.accion, a.qty) for a in acts] == [("Canceling", 180), ("Canceled", 180)]
    o = ultima_orden(msgs)
    assert (o.estado.value, o.lvqty, o.cxlqty, o.qty) == ("Canceled", 0, 180, 300)
    assert libro.posiciones()["ABCD"] == -120


def test_llenar_parcial_por_ticker_manda_sobre_global_y_uno_lo_quita(libro, emp):
    libro.llenar_parcial(D("0.5"))
    libro.llenar_parcial(D("0.1"), ticker="ABCD")
    libro.cotizar("ABCD", D("2.45"), D("2.47"))
    libro.cotizar("WXYZ", D("5.00"), D("5.02"))
    assert de_tipo(parsear(emp.recibir(f"NEWORDER {T1} SS ABCD SAGEPRO 100 2.44 TIF=DAY+")), MsgTrade)[0].qty == 10
    assert de_tipo(parsear(emp.recibir(f"NEWORDER {T2} SS WXYZ SAGEPRO 100 4.99 TIF=DAY+")), MsgTrade)[0].qty == 50
    libro.llenar_parcial(D("1"), ticker="ABCD")
    libro.llenar_parcial(D("1"))
    assert de_tipo(parsear(emp.recibir(f"NEWORDER {T3} SS ABCD SAGEPRO 100 2.44 TIF=DAY+")), MsgTrade)[0].qty == 100


def test_llenar_parcial_minimo_una_accion(libro, emp):
    libro.llenar_parcial(D("0.1"))
    libro.cotizar("ABCD", D("2.45"), D("2.47"))
    assert de_tipo(parsear(emp.recibir(f"NEWORDER {T1} SS ABCD SAGEPRO 5 2.44 TIF=DAY+")), MsgTrade)[0].qty == 1


def test_parcial_por_tamano_del_libro_que_se_consume(libro, emp):
    """§3.3: parcial por tamaño del libro; el tamaño se consume y la siguiente cotización lo repone."""
    libro.cotizar("ABCD", D("2.45"), D("2.47"), tamano_bid=100, tamano_ask=100)
    msgs = parsear(emp.recibir(f"NEWORDER {T1} SS ABCD SAGEPRO 300 2.44 TIF=DAY+"))
    assert (de_tipo(msgs, MsgTrade)[0].qty, ultima_orden(msgs).lvqty) == (100, 200)
    assert libro.cotizacion("ABCD")["tamano_bid"] == 0
    assert emp.tic() == []
    libro.cotizar("ABCD", D("2.45"), D("2.47"), tamano_bid=500, tamano_ask=500)
    msgs = parsear(emp.tic())
    (trade,) = de_tipo(msgs, MsgTrade)
    assert (trade.qty, trade.precio, ultima_orden(msgs).estado.value) == (200, D("2.44"), "Executed")
    assert libro.posiciones()["ABCD"] == -300


# ══════════════════════════════════════════════════════════════════════
# rechazos del guion (R-B-07, EP-1)
# ══════════════════════════════════════════════════════════════════════
def test_rechazar_siguiente_solo_la_siguiente(libro, emp):
    libro.cotizar("ABCD", D("2.45"), D("2.47"))
    libro.rechazar_siguiente("No shares to short")
    msgs = parsear(emp.recibir(f"NEWORDER {T1} SS ABCD SAGEREB 100 2.5 TIF=DAY+"))
    assert [(m.accion, m.notas) for m in de_tipo(msgs, MsgOrderAct)][-1] == ("Send_Rej", "No shares to short")
    assert ultima_orden(msgs).estado.value == "Rejected"
    msgs = parsear(emp.recibir(f"NEWORDER {T2} SS ABCD SAGEREB 100 2.5 TIF=DAY+"))
    assert ultima_orden(msgs).estado.value == "Accepted"


def test_rechazo_dirigido_a_un_token(libro, emp):
    libro.cotizar("ABCD", D("2.45"), D("2.47"))
    libro.rechazar_siguiente("Token dirigido", token_o_orden=T2)
    assert ultima_orden(parsear(emp.recibir(f"NEWORDER {T1} SS ABCD SAGEREB 100 2.5 TIF=DAY+"))).estado.value == \
        "Accepted"
    msgs = parsear(emp.recibir(f"NEWORDER {T2} SS ABCD SAGEREB 100 2.5 TIF=DAY+"))
    assert [m.notas for m in de_tipo(msgs, MsgOrderAct) if m.accion == "Send_Rej"] == ["Token dirigido"]


def test_rechazo_de_cancel_y_de_replace(libro, emp):
    libro.cotizar("ABCD", D("2.45"), D("2.47"))
    id_das = ultima_orden(parsear(emp.recibir(f"NEWORDER {T1} SS ABCD SAGEREB 100 2.5 TIF=DAY+"))).id
    libro.rechazar_siguiente("Too late to cancel", accion="CancelRej")
    libro.rechazar_siguiente("Replace blocked", accion="ReplaceRej", token_o_orden=id_das)
    (act,) = de_tipo(parsear(emp.recibir(f"CANCEL {id_das}")), MsgOrderAct)
    assert (act.accion, act.notas, act.token) == ("CancelRej", "Too late to cancel", T1)
    (act,) = de_tipo(parsear(emp.recibir(f"REPLACE {id_das} 100 2.51")), MsgOrderAct)
    assert (act.accion, act.notas) == ("ReplaceRej", "Replace blocked")
    assert orden(libro, id_das)["estado"] == "Accepted"


@pytest.mark.parametrize("linea, nota", [
    pytest.param(f"NEWORDER {T1} SS ABCD SAGEREB 100 2.455 TIF=DAY+", "Invalid price", id="riesgo12-fuera-de-tick"),
    pytest.param(f"NEWORDER {T1} SS ABCD SAGEREB 0 2.45 TIF=DAY+", "Invalid quantity", id="riesgo12-qty-cero"),
    pytest.param(f"NEWORDER {T1} B ABCD STOP 100 STOPLMTP 2.99 2.97 TIF=DAY+", "Invalid stop price",
                 id="R-C-01-limite-bajo-disparo"),
    pytest.param(f"NEWORDER {T1} B ABCD SAGEREB 100 MKT PostOnly TIF=DAY", "PostOnly only for limit orders",
                 id="postonly-en-mkt"),
    pytest.param(f"NEWORDER {T1} B ABCD SMAT 100 STOPMKT 2.9 TIF=DAY", "Order type not simulated",
                 id="tipo-no-simulado"),
])
def test_neworder_inaceptable_da_send_rej(libro, emp, linea, nota):
    libro.cotizar("ABCD", D("2.45"), D("2.47"))
    msgs = parsear(emp.recibir(linea))
    assert [m.notas for m in de_tipo(msgs, MsgOrderAct) if m.accion == "Send_Rej"] == [nota]
    assert ultima_orden(msgs).estado.value == "Rejected"


@pytest.mark.parametrize("linea", [
    pytest.param("NEWORDER", id="vacio"),
    pytest.param(f"NEWORDER {T1} SS ABCD SAGEREB 100", id="sin-precio"),
    pytest.param(f"NEWORDER {T1} XX ABCD SAGEREB 100 2.45 TIF=DAY", id="lado-desconocido"),
    pytest.param(f"NEWORDER abc SS ABCD SAGEREB 100 2.45 TIF=DAY", id="token-no-entero"),
    pytest.param(f"NEWORDER {2**31} SS ABCD SAGEREB 100 2.45 TIF=DAY", id="token-fuera-int32"),
    pytest.param(f"NEWORDER {T1} SS ABCD SAGEREB cien 2.45 TIF=DAY", id="qty-no-entera"),
    pytest.param(f"NEWORDER {T1} SS ABCD SAGEREB 100 dos TIF=DAY", id="precio-no-numerico"),
    pytest.param(f"NEWORDER {T1} SS ABCD SAGEREB 100 2.45 TIF=", id="tif-vacio"),
    pytest.param("CANCEL", id="cancel-sin-id"),
    pytest.param("CANCEL 424242", id="cancel-id-desconocido"),
    pytest.param("REPLACE 424242 100 2.45", id="replace-id-desconocido"),
    pytest.param("COMPLEXORDER Route=COMPL", id="complexorder-no-simulado"),
    pytest.param("GET NADA", id="get-desconocido"),
])
def test_comando_mal_formado_no_responde_y_queda_en_incidencias(emp, linea):
    """§5.15: DAS no acusa la sintaxis; el simulador no inventa respuesta y lo anota."""
    assert emp.recibir(linea) == []
    assert len(emp.incidencias()) == 1


def test_recibir_exige_texto_y_parte_por_saltos(libro, emp):
    with pytest.raises(TypeError):
        emp.recibir(b"GET BP")
    lineas = emp.recibir("GET BP\r\nGET BP")
    assert [x for x in lineas if x.startswith("BP ")] == ["BP 100000 100000"] * 2
    assert emp.recibir("") == []


# ══════════════════════════════════════════════════════════════════════
# CANCEL / REPLACE
# ══════════════════════════════════════════════════════════════════════
def test_cancel_allsymb_y_all(libro, emp):
    libro.cotizar("ABCD", D("2.45"), D("2.47"))
    libro.cotizar("WXYZ", D("5.00"), D("5.02"))
    emp.recibir(f"NEWORDER {T1} SS ABCD SAGEREB 100 2.5 TIF=DAY+")
    emp.recibir(f"NEWORDER {T2} SS ABCD SAGEREB 100 2.51 TIF=DAY+")
    emp.recibir(f"NEWORDER {T3} SS WXYZ SAGEREB 100 5.1 TIF=DAY+")
    msgs = parsear(emp.recibir("CANCEL ALLSYMB ABCD"))
    assert sorted(m.token for m in de_tipo(msgs, MsgOrderAct) if m.accion == "Canceled") == [T1, T2]
    assert [o["estado"] for o in libro.ordenes()] == ["Canceled", "Canceled", "Accepted"]
    msgs = parsear(emp.recibir("cancel all"))
    assert [m.token for m in de_tipo(msgs, MsgOrderAct) if m.accion == "Canceled"] == [T3]
    assert emp.recibir("CANCEL ALL") == []


def test_cancel_de_orden_cerrada_da_cancelrej(libro, emp):
    libro.cotizar("ABCD", D("2.45"), D("2.47"))
    id_das = ultima_orden(parsear(emp.recibir(f"NEWORDER {T1} SS ABCD SAGEPRO 100 2.44 TIF=DAY+"))).id
    (act,) = de_tipo(parsear(emp.recibir(f"CANCEL {id_das}")), MsgOrderAct)
    assert (act.accion, act.notas) == ("CancelRej", "Order not open")


def test_replace_limite_cambia_cantidad_abierta_y_precio(libro, emp):
    """Perseguir al ask (R-D-08) por REPLACE: `share` = nueva cantidad ABIERTA; si ahora cruza, se llena."""
    libro.cotizar("ABCD", D("2.45"), D("2.47"))
    id_das = ultima_orden(parsear(emp.recibir(f"NEWORDER {T2} B ABCD SAGEREB 200 2.44 TIF=DAY+"))).id
    msgs = parsear(emp.recibir(f"REPLACE {id_das} 150 2.46"))
    assert [(a.accion, a.qty) for a in de_tipo(msgs, MsgOrderAct)] == [("Replacing", 200), ("Replaced", 150)]
    o = ultima_orden(msgs)
    assert (o.qty, o.lvqty, o.precio, o.estado.value) == (150, 150, D("2.46"), "Accepted")
    msgs = parsear(emp.recibir(f"REPLACE {id_das} 150 2.47"))
    (trade,) = de_tipo(msgs, MsgTrade)
    assert (trade.qty, trade.precio) == (150, D("2.47"))


@pytest.mark.parametrize("conserva, tipo_despues", [
    pytest.param(True, "SLP: 3.05 3.1", id="5.6-replace-conserva-pre-post"),
    pytest.param(False, "SL: 3.05 3.1", id="5.6-replace-pierde-pre-post"),
])
def test_replace_stoplmtp_y_tipo_crudo(libro, reloj, conserva, tipo_despues):
    """§5.6 / 2h.8: REPLACE … STOPLMT sobre un STOPLMTP; con replace_conserva_pp=False el Type cambia (lo detecta tipo_conserva_pp)."""
    emp = Emparejador(libro, reloj, replace_conserva_pp=conserva)
    libro.cotizar("ABCD", D("2.89"), D("2.91"), last=D("2.90"))
    id_das = ultima_orden(parsear(emp.recibir(f"NEWORDER {T3} B ABCD STOP 300 STOPLMTP 2.97 2.99 TIF=DAY+"))).id
    msgs = parsear(emp.recibir(f"REPLACE {id_das} 200 STOPLMT 3.05 3.1"))
    o = ultima_orden(msgs)
    assert (o.tipo, o.lvqty, o.precio) == (tipo_despues, 200, D("3.1"))
    assert orden(libro, id_das)["stop"] == D("3.05")


@pytest.mark.parametrize("comando, nota", [
    pytest.param("REPLACE {id} 100 2.46", "Replace type mismatch", id="5.6-limite-sobre-stop"),
    pytest.param("REPLACE {id} 0 STOPLMT 2.97 2.99", "Invalid quantity", id="qty-cero"),
    pytest.param("REPLACE {id} 100 STOPLMT 2.975 2.99", "Invalid price", id="riesgo12-fuera-de-tick"),
    pytest.param("REPLACE {id} 100 STOPLMT 2.99 2.97", "Invalid stop price", id="limite-bajo-disparo"),
])
def test_replace_inaceptable(libro, emp, comando, nota):
    libro.cotizar("ABCD", D("2.89"), D("2.91"), last=D("2.90"))
    id_das = ultima_orden(parsear(emp.recibir(f"NEWORDER {T3} B ABCD STOP 300 STOPLMTP 2.97 2.99 TIF=DAY+"))).id
    (act,) = de_tipo(parsear(emp.recibir(comando.format(id=id_das))), MsgOrderAct)
    assert (act.accion, act.notas) == ("ReplaceRej", nota)


def _orden_de_2_con_1_llena(libro: LibroSimulado, emp: Emparejador) -> int:
    """Canario de A-02: una límite de 2 acciones que llena 1 y deja 1 viva (la sonda de comprobar_das)."""
    libro.llenar_parcial(D("0.5"), ticker="ABCD")
    libro.cotizar("ABCD", D("2.45"), D("2.47"))
    msgs = parsear(emp.recibir(f"NEWORDER {T1} SS ABCD SAGEPRO 2 2.44 TIF=DAY+"))
    o = ultima_orden(msgs)
    assert (o.estado.value, o.qty, o.lvqty) == ("Partial", 2, 1)
    libro.llenar_parcial(D("1"), ticker="ABCD")
    libro.cotizar("ABCD", D("2.40"), D("2.42"))       # que el REPLACE no cruce: la orden reposa
    return o.id


@pytest.mark.parametrize("share_es_abierta, share, qty, lvqty", [
    pytest.param(True, 1, 2, 1, id="A-02-abierta-share-1-deja-1-viva"),
    pytest.param(True, 2, 3, 2, id="A-02-abierta-share-2-deja-2-vivas"),
    pytest.param(False, 2, 2, 1, id="A-02-total-share-2-deja-1-viva"),
    pytest.param(False, 3, 3, 2, id="A-02-total-share-3-deja-2-vivas"),
])
def test_A_02_replace_share_en_los_dos_modos(libro, reloj, share_es_abierta, share, qty, lvqty):
    """A-02: sobre una orden parcialmente llena, `share` es la ABIERTA o la TOTAL según el interruptor."""
    emp = Emparejador(libro, reloj, replace_share_es_abierta=share_es_abierta)
    id_das = _orden_de_2_con_1_llena(libro, emp)
    msgs = parsear(emp.recibir(f"REPLACE {id_das} {share} 2.5"))
    assert [a.accion for a in de_tipo(msgs, MsgOrderAct)] == ["Replacing", "Replaced"]
    o = ultima_orden(msgs)
    assert (o.qty, o.lvqty, o.precio) == (qty, lvqty, D("2.5"))


@pytest.mark.parametrize("share", [1, 0])
def test_A_02_modo_total_share_no_mayor_que_llenas_se_rechaza(libro, reloj, share):
    """A-02: en el modo TOTAL un share ≤ llenas dejaría 0 abiertas: ReplaceRej y la orden sigue como estaba."""
    emp = Emparejador(libro, reloj, replace_share_es_abierta=False)
    id_das = _orden_de_2_con_1_llena(libro, emp)
    (act,) = de_tipo(parsear(emp.recibir(f"REPLACE {id_das} {share} 2.5")), MsgOrderAct)
    assert (act.accion, act.notas) == ("ReplaceRej", "Invalid quantity")
    assert (orden(libro, id_das)["lvqty"], orden(libro, id_das)["qty"]) == (1, 2)


@pytest.mark.parametrize("share_es_abierta", [True, False])
@pytest.mark.parametrize("abierta", [1, 3])
def test_A_02_share_de_replace_y_simulador_coinciden(libro, reloj, share_es_abierta, abierta):
    """A-02: el share que calcula `tipos.share_de_replace` deja viva EXACTAMENTE la cantidad pedida en los dos modos."""
    from app.bot_das.tipos import share_de_replace
    emp = Emparejador(libro, reloj, replace_share_es_abierta=share_es_abierta)
    id_das = _orden_de_2_con_1_llena(libro, emp)
    share = share_de_replace(abierta, llenas=1, share_es_abierta=share_es_abierta)
    o = ultima_orden(parsear(emp.recibir(f"REPLACE {id_das} {share} 2.5")))
    assert o.lvqty == abierta


def test_A_02_defecto_es_el_de_tipos(libro, reloj):
    from app.bot_das.tipos import REPLACE_SHARE_ES_ABIERTA
    assert Emparejador(libro, reloj).replace_share_es_abierta is REPLACE_SHARE_ES_ABIERTA


def test_replace_postonly_que_cruzaria_se_rechaza(libro, emp):
    libro.cotizar("ABCD", D("2.45"), D("2.47"))
    id_das = ultima_orden(parsear(emp.recibir(f"NEWORDER {T1} SS ABCD SAGEREB 100 2.5 PostOnly TIF=DAY+"))).id
    (act,) = de_tipo(parsear(emp.recibir(f"REPLACE {id_das} 100 2.45")), MsgOrderAct)
    assert (act.accion, act.notas) == ("ReplaceRej", "PostOnly would cross")


# ══════════════════════════════════════════════════════════════════════
# halt y ruta OPEN (R-F-01, EP-2)
# ══════════════════════════════════════════════════════════════════════
def test_halt_para_los_fills_y_reabrir_llena_open_al_precio(libro, emp):
    libro.cotizar("ABCD", D("2.45"), D("2.47"), last=D("2.46"))
    id_resto = ultima_orden(parsear(emp.recibir(f"NEWORDER {T1} B ABCD SAGEREB 100 2.40 TIF=DAY+"))).id
    libro.halt("ABCD", "H", "10:15:00")
    (st,) = parsear(emp.recibir("GET SymStatus ABCD"))
    assert (st.ta, st.tat, st.ssr) == ("H", "10:15:00", False)
    libro.cotizar("ABCD", D("2.30"), D("2.35"))
    assert emp.tic() == []                                  # nada se llena en halt aunque cruce
    msgs = parsear(emp.recibir(f"NEWORDER {T2} B ABCD OPEN 100 MKT TIF=DAY"))
    id_open = ultima_orden(msgs).id
    assert (ultima_orden(msgs).estado.value, de_tipo(msgs, MsgTrade)) == ("Accepted", [])
    libro.cotizar("ABCD", D("3.05"), D("3.15"))
    assert emp.tic() == []
    libro.reabrir("ABCD", D("3.1"), tat="10:20:00")
    msgs = parsear(emp.tic())
    trades = de_tipo(msgs, MsgTrade)
    assert [(t.id_orden, t.precio, t.qty) for t in trades] == [(id_open, D("3.1"), 100)]
    assert orden(libro, id_resto)["estado"] == "Accepted"
    (st,) = parsear(emp.recibir("GET SymStatus ABCD"))
    assert (st.ta, st.tat) == ("T", "10:20:00")
    assert libro.en_halt("ABCD") is False


def test_reabrir_open_limite_solo_si_cruza(libro, emp):
    libro.cotizar("ABCD", D("2.45"), D("2.47"))
    libro.halt("ABCD", "P", "10:15:00")
    id_si = ultima_orden(parsear(emp.recibir(f"NEWORDER {T1} B ABCD OPEN 100 3.2 TIF=DAY"))).id
    id_no = ultima_orden(parsear(emp.recibir(f"NEWORDER {T2} B ABCD OPEN 100 3 TIF=DAY"))).id
    libro.reabrir("ABCD", D("3.1"))
    assert [t.id_orden for t in de_tipo(parsear(emp.tic()), MsgTrade)] == [id_si]
    assert orden(libro, id_no)["estado"] == "Accepted"


def test_open_en_halt_configurable_a_rechazo(libro, reloj):
    emp = Emparejador(libro, reloj, open_en_halt="rechazar")
    libro.halt("ABCD", "H", "10:15:00")
    msgs = parsear(emp.recibir(f"NEWORDER {T2} B ABCD OPEN 100 MKT TIF=DAY"))
    assert [m.notas for m in de_tipo(msgs, MsgOrderAct) if m.accion == "Send_Rej"] == [
        "OPEN route not available during halt"]


def test_reabrir_sin_cotizacion_pone_bid_y_ask(libro, emp):
    libro.halt("ABCD", "H", "10:15:00")
    libro.reabrir("ABCD", D("3.1"))
    q = libro.cotizacion("ABCD")
    assert (q["bid"], q["ask"], q["last"]) == (D("3.1"), D("3.1"), D("3.1"))


def test_halt_nuevo_anula_una_reapertura_pendiente(libro, emp):
    libro.halt("ABCD", "H", "10:15:00")
    emp.recibir(f"NEWORDER {T2} B ABCD OPEN 100 MKT TIF=DAY")
    libro.reabrir("ABCD", D("3.1"))
    libro.halt("ABCD", "H", "10:21:00")
    assert emp.tic() == []


# ══════════════════════════════════════════════════════════════════════
# variantes no documentadas (§5.2, §5.3, §5.12)
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("variante, datos, order_src", [
    pytest.param(19, 18, "CMDAPI", id="5.3-order-19-campos"),
    pytest.param(15, 15, None, id="5.3-order-15-campos"),
])
def test_variante_order(libro, reloj, variante, datos, order_src):
    """§5.3: el «19» del manual cuenta la palabra clave (18 datos, L343-351); el «15» no (15 datos, L930-932)."""
    emp = Emparejador(libro, reloj, variante_order=variante)
    libro.cotizar("ABCD", D("2.45"), D("2.47"))
    lineas = emp.recibir(f"NEWORDER {T1} SS ABCD SAGEREB 100 2.5 TIF=DAY+ Pref=ARCA")
    linea_order = next(x for x in lineas if x.startswith("%ORDER "))
    assert len(linea_order.split()) - 1 == datos
    o = ultima_orden(parsear(lineas))
    assert (o.order_src, o.cuenta, o.trader, o.token) == (order_src, CUENTA, "TRPRUEBA", T1)
    if variante == 19:
        assert (o.tif, o.pref) == ("DAY+", "ARCA")
    volcado = emp.volcado()
    assert volcado[2] == (sd.CABECERA_ORDER_19 if variante == 19 else sd.CABECERA_ORDER_15)


@pytest.mark.parametrize("tipo_stop_crudo, esperado", [
    pytest.param("SLP", "SLP: 2.97 2.99", id="5.2-captura-del-socio"),
    pytest.param("StopLmtPP", "StopLmtPP: 2.97 2.99", id="5.2-otro-prefijo"),
    pytest.param("STOPLMTP {stop}/{precio} PP", "STOPLMTP 2.97/2.99 PP", id="5.2-plantilla"),
])
def test_tipo_stop_crudo(libro, reloj, tipo_stop_crudo, esperado):
    """Riesgo 1: el Type de varias palabras no desplaza qty/precio en el parser anclado por la derecha."""
    emp = Emparejador(libro, reloj, tipo_stop_crudo=tipo_stop_crudo)
    o = ultima_orden(parsear(emp.recibir(f"NEWORDER {T3} B ABCD STOP 300 STOPLMTP 2.97 2.99 TIF=DAY+")))
    assert (o.tipo, o.qty, o.lvqty, o.precio, o.ruta) == (esperado, 300, 300, D("2.99"), "STOP")


PERMUTACIONES = list(itertools.permutations(sd.ORDEN_MENSAJES_DEFECTO))


@pytest.mark.parametrize("orden_mensajes", PERMUTACIONES, ids=["5.12-" + "-".join(p) for p in PERMUTACIONES])
def test_seis_permutaciones_de_mensajes_del_fill(libro, reloj, orden_mensajes):
    """Riesgo 8 / §5.12: el orden %OrderAct/%TRADE/%POS no está documentado; el simulador produce los 6."""
    emp = Emparejador(libro, reloj, orden_mensajes=orden_mensajes)
    libro.cotizar("ABCD", D("2.45"), D("2.47"))
    lineas = emp.recibir(f"NEWORDER {T1} SS ABCD SAGEPRO 300 2.44 TIF=DAY+")
    parsear(lineas)
    fill = lineas[3:]
    grupos = {"OrderAct": ["%OrderAct Execute", "%ORDER"], "TRADE": ["%TRADE"], "POS": ["%POS"]}
    assert claves(fill) == [c for g in orden_mensajes for c in grupos[g]]


@pytest.mark.parametrize("negativa, qty_cruda", [
    pytest.param(True, -300, id="riesgo9-corto-negativo"),
    pytest.param(False, 300, id="riesgo9-corto-positivo"),
])
def test_qty_corto_negativa(libro, reloj, negativa, qty_cruda):
    """Riesgo 9: el signo de %POS en cortos no está documentado; con los dos, normalizar_pos da −300."""
    emp = Emparejador(libro, reloj, qty_corto_negativa=negativa)
    libro.cotizar("ABCD", D("2.45"), D("2.47"))
    (pos,) = de_tipo(parsear(emp.recibir(f"NEWORDER {T1} SS ABCD SAGEPRO 300 2.44 TIF=DAY+")), MsgPos)
    assert (pos.qty_cruda, pos.neta, pos.tipo) == (qty_cruda, -300, 3)


@pytest.mark.parametrize("kwargs", [
    pytest.param({"variante_order": 17}, id="variante-17"),
    pytest.param({"tipo_stop_crudo": ""}, id="tipo-stop-vacio"),
    pytest.param({"tipo_stop_crudo": "SLP\n"}, id="tipo-stop-con-salto"),
    pytest.param({"tipo_stop_crudo": "{nada}"}, id="plantilla-mala"),
    pytest.param({"latencia_s": -1}, id="latencia-negativa"),
    pytest.param({"latencia_s": True}, id="latencia-bool"),
    pytest.param({"orden_mensajes": ("OrderAct", "TRADE")}, id="orden-incompleto"),
    pytest.param({"orden_mensajes": ("OrderAct", "TRADE", "TRADE")}, id="orden-repetido"),
    pytest.param({"open_en_halt": "ignorar"}, id="open-en-halt-desconocido"),
    pytest.param({"replace_share_es_abierta": 1}, id="A-02-share-no-bool"),
])
def test_emparejador_valida_parametros(libro, reloj, kwargs):
    with pytest.raises(ValueError):
        Emparejador(libro, reloj, **kwargs)


def test_emparejador_exige_libro_y_reloj(libro, reloj):
    with pytest.raises(TypeError):
        Emparejador({}, reloj)
    with pytest.raises(TypeError):
        Emparejador(libro, object())


# ══════════════════════════════════════════════════════════════════════
# posiciones (media, giro, P/L) y GET
# ══════════════════════════════════════════════════════════════════════
def test_media_ponderada_giro_y_realizado(libro, emp):
    libro.cotizar("ABCD", D("2.00"), D("2.02"))
    emp.recibir(f"NEWORDER {T1} SS ABCD SAGEPRO 100 2 TIF=DAY+")
    libro.cotizar("ABCD", D("2.30"), D("2.32"))
    msgs = parsear(emp.recibir(f"NEWORDER {T2} SS ABCD SAGEPRO 200 2.3 TIF=DAY+"))
    assert de_tipo(msgs, MsgPos)[0].avg == D("2.2")
    libro.cotizar("ABCD", D("2.08"), D("2.10"))
    msgs = parsear(emp.recibir(f"NEWORDER {T3} B ABCD SAGEPRO 400 2.1 TIF=DAY+"))
    (trade,) = de_tipo(msgs, MsgTrade)
    (pos,) = de_tipo(msgs, MsgPos)
    assert (trade.pl, pos.neta, pos.tipo, pos.avg, pos.realizado) == (D("30"), 100, 2, D("2.1"), D("30"))
    assert all(isinstance(t["precio"], Decimal) and isinstance(t["pl"], Decimal) for t in libro.trades())


def test_get_respuestas_plausibles(libro, emp):
    libro.cotizar("ABCD", D("2.45"), D("2.47"), last=D("2.46"))
    libro.bandas("ABCD", D("2.2"), D("2.7"))
    libro.ssr("ABCD", True)
    libro.rutas["ALGO"] = False
    emp.recibir(f"NEWORDER {T1} SS ABCD SAGEPRO 100 2.44 TIF=DAY+")
    msgs = parsear(emp.recibir("GET BP"))
    assert isinstance(msgs[0], MsgMarcador) and msgs[0].nombre == "#buyingpower"
    assert (msgs[1].bp, msgs[1].bp_overnight) == (D("100000"), D("100000"))
    pos = parsear(emp.recibir("GET POSITIONS"))
    assert [type(m) for m in pos] == [MsgMarcador, MsgPos, MsgMarcador]
    assert pos[1].neta == -100
    assert parsear(emp.recibir("POSREFRESH"))[1].neta == -100
    ords = parsear(emp.recibir("GET ORDERS"))
    assert (ords[0].nombre, ords[-1].nombre, ords[1].estado.value) == ("#Order", "#OrderEnd", "Executed")
    trs = parsear(emp.recibir("GET TRADES"))
    assert (trs[0].nombre, trs[-1].nombre, trs[1].qty) == ("#Trade", "#TradeEnd", 100)
    (st,) = parsear(emp.recibir("GET SymStatus ABCD"))
    assert isinstance(st, MsgIssueStatus) and (st.ssr, st.ta) == (True, None)
    (ldlu,) = parsear(emp.recibir("GET LDLU ABCD"))
    assert isinstance(ldlu, MsgLDLU) and (ldlu.limit_down, ldlu.limit_up) == (D("2.2"), D("2.7"))
    assert emp.recibir("GET LDLU WXYZ") == []                 # sin bandas no hay respuesta (L1086-1088)
    (si,) = parsear(emp.recibir("GET SHORTINFO ABCD"))
    assert isinstance(si, MsgShortInfo) and si.shortable is True
    (cuenta,) = parsear(emp.recibir("GET AccountInfo"))
    assert isinstance(cuenta, MsgAccountInfo)
    assert (cuenta.realizado, cuenta.no_realizado) == (D("0"), D("-1"))
    rutas = parsear(emp.recibir("GET RouteStatus"))
    assert all(isinstance(r, MsgRouteStatus) for r in rutas)
    assert {r.ruta: r.habilitada for r in rutas}["ALGO"] is False
    assert emp.recibir("GET INTMSGS") == []
    assert emp.recibir("get bp")[1] == "BP 100000 100000"


def test_get_symstatus_sin_argumento_lista_los_conocidos(libro, emp):
    libro.cotizar("ABCD", D("2.45"), D("2.47"))
    libro.halt("WXYZ", "P", "10:00:00")
    assert emp.recibir("GET SymStatus") == ["$IssueStatus ABCD SSR:N", "$IssueStatus WXYZ SSR:N TA:P TAT:10:00:00"]


def test_volcado_con_posicion_sembrada(libro, emp):
    """F12: una posición anterior al LOGIN sale en el volcado."""
    libro.sembrar_posicion("ABCD", -200, D("2.5"))
    msgs = parsear(emp.volcado())
    assert [getattr(m, "nombre", type(m).__name__) for m in msgs] == [
        "#POS", "MsgPos", "#POSEND", "#Order", "#OrderEnd", "#Trade", "#TradeEnd"]
    assert (msgs[1].neta, msgs[1].avg) == (-200, D("2.5"))


# ══════════════════════════════════════════════════════════════════════
# locates (R-H-01..05, §5.22)
# ══════════════════════════════════════════════════════════════════════
def test_locate_inquire_y_compra_tipo_0(libro, emp):
    libro.configurar_locate("ABCD", precio=D("0.012"), disponibles=250, ruta="LOC3", minimo=D("2.5"))
    (ret,) = parsear(emp.recibir("SLPRICEINQUIRE ABCD 300 ALLROUTEWTTYPE1"))
    assert isinstance(ret, MsgSLRet)
    assert (ret.tipo, ret.precio, ret.tamano, ret.ruta, ret.notas, ret.cuenta) == (1, D("0.012"), 250, "LOC3", "",
                                                                                    CUENTA)
    msgs = parsear(emp.recibir("SLNEWORDER ABCD 300 LOC3 326800001"))
    assert [m.estado for m in msgs] == ["Pending", "Located"]
    assert (msgs[1].localizadas, msgs[1].abiertas, msgs[1].token) == (250, 50, 326800001)
    assert libro.locates()[0]["localizadas"] == 250
    (avail,) = parsear(emp.recibir(f"SLAvailQuery {CUENTA} ABCD"))
    assert isinstance(avail, MsgSLAvail) and avail.disponibles == 0
    (reuse,) = parsear(emp.recibir("SLReuseQuery ABCD"))
    assert isinstance(reuse, MsgSLReuse) and reuse.reutilizable is True
    cargos = parsear(emp.recibir("SLRouteMinCharge ALLROUTE"))
    assert all(isinstance(c, MsgSLMinCharge) for c in cargos)
    assert {c.ruta: c.minimo for c in cargos}["LOC3"] == D("2.5")
    listado = parsear(emp.recibir("GET LOCATES"))
    assert (listado[0].nombre, listado[-1].nombre, listado[1].estado) == ("#SLOrder", "#SLOrderEnd", "Located")


def test_locate_tipo_1_ofrece_y_se_acepta_o_rechaza(libro, emp):
    libro.configurar_locate("ABCD", tipo_ruta=1, ruta="LOC7", reutilizable=False)
    (ret,) = parsear(emp.recibir("SLPRICEINQUIRE ABCD 100 LOC7"))
    assert (ret.tipo, ret.notas) == (2, "Route type 1 does not support inquire")
    (oferta,) = parsear(emp.recibir("SLNEWORDER ABCD 100 LOC7 326800002"))
    assert isinstance(oferta, MsgSLOrder) and oferta.estado == "Offered"
    (hecho,) = parsear(emp.recibir(f"SLOFFEROPERATION {oferta.id} Accept"))
    assert (hecho.estado, hecho.localizadas) == ("Located", 100)
    (otra,) = parsear(emp.recibir("SLNEWORDER ABCD 100 LOC7 326800003"))
    (cerrada,) = parsear(emp.recibir(f"SLOFFEROPERATION {otra.id} Reject"))
    assert cerrada.estado == "Closed"
    assert emp.recibir("SLReuseQuery ALL") == ["$SLReuseQueryRet ABCD No"]


def test_locate_allroute_en_tipo_1_crea_orden_offered(libro, emp):
    """§5.22: SLPRICEINQUIRE … ALLROUTE en rutas tipo 1 CREA una orden Offered (por eso es mutante)."""
    libro.configurar_locate("ABCD", tipo_ruta=1)
    (oferta,) = parsear(emp.recibir("SLPRICEINQUIRE ABCD 100 ALLROUTE"))
    assert isinstance(oferta, MsgSLOrder) and (oferta.estado, oferta.token) == ("Offered", None)
    (cancelada,) = parsear(emp.recibir(f"SLCANCELORDER {oferta.id}"))
    assert cancelada.estado == "Canceled"
    assert emp.recibir(f"SLCANCELORDER {oferta.id}") == []
    assert len(emp.incidencias()) == 1


def test_locate_fallo_ya_shortable(libro, emp):
    libro.configurar_locate("ABCD", fallo="AlreadyShortable")
    for linea in ("SLPRICEINQUIRE ABCD 100 ALLROUTEWTTYPE1", "SLNEWORDER ABCD 100 LOCSIM 326800004"):
        (ret,) = parsear(emp.recibir(linea))
        assert (ret.tipo, ret.notas, ret.cuenta) == (2, "AlreadyShortable", CUENTA)
    libro.configurar_locate("ABCD", fallo="")
    assert parsear(emp.recibir("SLPRICEINQUIRE ABCD 100 ALLROUTEWTTYPE1"))[0].tipo == 1


# ══════════════════════════════════════════════════════════════════════
# SimuladorDAS por socket
# ══════════════════════════════════════════════════════════════════════
class ClientePrueba:
    """Cliente TCP crudo para los tests: manda líneas y acumula lo recibido, con plazos cortos."""

    def __init__(self, direccion: tuple[str, int]) -> None:
        self.sock = socket.create_connection(direccion, timeout=PLAZO_S)
        self.sock.settimeout(0.05)
        self.bruto = b""
        self.eof = False

    def enviar(self, linea: str) -> None:
        self.sock.sendall((linea + "\r\n").encode("latin-1"))

    def _leer(self) -> None:
        try:
            datos = self.sock.recv(65536)
        except socket.timeout:
            return
        except OSError:
            self.eof = True
            return
        if not datos:
            self.eof = True
        self.bruto += datos

    @property
    def lineas(self) -> list[str]:
        return [x.rstrip("\r") for x in self.bruto.decode("latin-1").split("\n")[:-1]]

    def esperar(self, condicion: Callable[[list[str]], bool], plazo: float = PLAZO_S) -> list[str]:
        limite = time.monotonic() + plazo
        while not condicion(self.lineas):
            if self.eof or time.monotonic() > limite:
                raise AssertionError(f"condición no cumplida; recibido: {self.lineas}")
            self._leer()
        return self.lineas

    def esperar_linea(self, prefijo: str, plazo: float = PLAZO_S) -> str:
        self.esperar(lambda ls: any(x.startswith(prefijo) for x in ls), plazo)
        return next(x for x in self.lineas if x.startswith(prefijo))

    def esperar_eof(self, plazo: float = PLAZO_S) -> bool:
        limite = time.monotonic() + plazo
        while not self.eof and time.monotonic() < limite:
            self._leer()
        return self.eof

    def sincronizar(self) -> None:
        """ECHO y espera su respuesta: todo lo enviado antes ya lo procesó el simulador."""
        n = sum(1 for x in self.lineas if x.startswith("ECHO"))
        self.enviar("ECHO")
        self.esperar(lambda ls: sum(1 for x in ls if x.startswith("ECHO")) > n)

    def login(self, watch: bool = False) -> list[str]:
        self.enviar(f"LOGIN prueba prueba {CUENTA} {1 if watch else 0}")
        return self.esperar(lambda ls: "#TradeEnd" in ls)

    def cerrar(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


@pytest.fixture
def servidor(libro, reloj):
    """SimuladorDAS con usuarios inventados; siempre parado al terminar (y sin errores internos)."""
    sim = SimuladorDAS(libro, reloj, usuarios=dict(USUARIOS))
    sim.arrancar()
    try:
        yield sim
    finally:
        sim.parar()
    assert sim.errores() == []


@pytest.fixture
def clientes(servidor):
    abiertos: list[ClientePrueba] = []

    def _nuevo() -> ClientePrueba:
        c = ClientePrueba(servidor.direccion)
        abiertos.append(c)
        return c
    try:
        yield _nuevo
    finally:
        for c in abiertos:
            c.cerrar()


def test_login_y_volcado(servidor, clientes, libro):
    """Manual L243-255: tras el LOGIN, estados de conexión y el volcado #POS…#POSEND, #Order…, #Trade…."""
    libro.sembrar_posicion("ABCD", -100, D("2.5"))
    c = clientes()
    lineas = c.login()
    # como el DAS real (01-oct): saludo al conectar y «#LOGIN SUCCESSED» antes de los estados y el volcado
    assert lineas[:3] == ["#Welcome to DAS Command API", "#Please login to continue.", "#LOGIN SUCCESSED"]
    msgs = parsear(lineas[3:])
    assert [type(m) for m in msgs[:2]] == [MsgConexion, MsgConexion]
    assert [getattr(m, "nombre", None) for m in msgs[2:]] == [
        "#POS", None, "#POSEND", "#Order", "#OrderEnd", "#Trade", "#TradeEnd"]
    assert servidor.esperar_logueadas(1)
    assert servidor.n_conexiones == 1
    assert servidor.recibidas() == [f"LOGIN prueba prueba {CUENTA} 0"]


def test_login_con_clave_mala_falla_y_se_ignora_lo_demas(servidor, clientes):
    """Como el DAS real (01-oct): clave mala → «ERROR:INVALID PASSWORD» tras el saludo; lo demás no se contesta."""
    c = clientes()
    esperado = ["#Welcome to DAS Command API", "#Please login to continue.", "ERROR:INVALID PASSWORD"]
    c.enviar(f"LOGIN prueba mala {CUENTA} 0")
    c.esperar(lambda ls: ls == esperado)
    c.enviar("GET BP")
    c.enviar("ECHO")
    time.sleep(0.1)
    c._leer()
    assert c.lineas == esperado
    assert servidor.n_conexiones == 0


def test_login_sin_usuarios_acepta_cualquiera(libro, reloj):
    sim = SimuladorDAS(libro, reloj)
    sim.arrancar()
    c = ClientePrueba(sim.direccion)
    try:
        c.enviar(f"LOGIN otro otra {CUENTA} 0")
        c.esperar(lambda ls: "#TradeEnd" in ls)
    finally:
        c.cerrar()
        sim.parar()


def test_orden_por_socket_y_watch_recibe_iorder_ipos_itrade(servidor, clientes, libro):
    """§3.3 / R-C-08: la conexión watch recibe %IORDER/%IPOS/%ITRADE de todo (y no %OrderAct)."""
    normal, otra, watch = clientes(), clientes(), clientes()
    normal.login()
    otra.login()
    watch.login(watch=True)
    assert servidor.esperar_logueadas(1, watch=True)
    servidor.cotizar("ABCD", D("2.45"), D("2.47"))
    normal.enviar(f"NEWORDER {T1} SS ABCD SAGEPRO 300 2.44 TIF=DAY+")
    normal.esperar_linea("%POS ")
    otra.esperar_linea("%POS ")
    watch.esperar_linea("%IPOS ")
    watch.esperar_linea("%ITRADE ")
    eventos_watch = [x for x in watch.lineas if x.startswith("%")]
    assert eventos_watch and all(x.split()[0] in ("%IORDER", "%IPOS", "%ITRADE") for x in eventos_watch)
    msgs = parsear(eventos_watch)
    (trade,) = de_tipo(msgs, MsgTrade)
    assert (trade.watch, trade.cuenta, trade.trader, trade.qty, trade.precio) == (True, CUENTA, "TRPRUEBA", 300,
                                                                                  D("2.45"))
    assert all(m.watch for m in de_tipo(msgs, MsgOrden) + de_tipo(msgs, MsgPos))
    assert any(x.startswith("%OrderAct") for x in otra.lineas)
    assert f"NEWORDER {T1} SS ABCD SAGEPRO 300 2.44 TIF=DAY+" in servidor.recibidas()


def test_watch_volcado_en_forma_i(servidor, clientes, libro):
    libro.sembrar_posicion("ABCD", -100, D("2.5"))
    watch = clientes()
    lineas = watch.login(watch=True)
    assert any(x.startswith("%IPOS ABCD") for x in lineas)
    assert not any(x.startswith("%POS ") for x in lineas)


def test_get_por_socket_solo_al_que_pregunta(servidor, clientes):
    a, b = clientes(), clientes()
    a.login()
    b.login()
    a.enviar("GET BP")
    assert a.esperar_linea("BP ") == "BP 100000 100000"
    b.sincronizar()
    assert not any(x.startswith("BP ") for x in b.lineas)


def test_sb_y_unsb_reparten_quote(servidor, clientes):
    c = clientes()
    c.login()
    servidor.cotizar("ABCD", D("2.45"), D("2.47"), last=D("2.46"))
    c.enviar("SB ABCD Lv1")
    assert c.esperar_linea("$Quote ABCD") == "$Quote ABCD A:2.47 B:2.45 L:2.46"
    servidor.cotizar("ABCD", D("2.44"), D("2.46"))
    c.esperar(lambda ls: sum(1 for x in ls if x.startswith("$Quote")) == 2)
    c.enviar("UNSB ABCD Lv1")
    c.sincronizar()
    servidor.cotizar("ABCD", D("2.43"), D("2.45"))
    c.sincronizar()
    assert sum(1 for x in c.lineas if x.startswith("$Quote")) == 2


def test_desde_vela_por_socket(servidor, clientes):
    c = clientes()
    c.login()
    c.enviar("SB ABCD Lv1")
    c.sincronizar()
    servidor.desde_vela("ABCD", {"close": 2.45, "volume": 1000.0}, ModeloSpread())
    assert c.esperar_linea("$Quote") == "$Quote ABCD A:2.46 Asz:5 B:2.44 Bsz:5 V:1000 L:2.45"


def test_cortar_normal_da_eof_y_deja_la_watch(servidor, clientes):
    """R-J-02: `cortar` simula el EOF; el puerto sigue abierto para reconectar."""
    normal, watch = clientes(), clientes()
    normal.login()
    watch.login(watch=True)
    assert servidor.esperar_logueadas(2)
    servidor.cortar("normal")
    assert normal.esperar_eof()
    watch.sincronizar()
    assert servidor.n_conexiones == 1
    otra = clientes()
    otra.login()
    servidor.cortar()
    assert watch.esperar_eof() and otra.esperar_eof()


def test_cortar_valida_argumento(servidor):
    with pytest.raises(ValueError):
        servidor.cortar("ninguna")


def test_quit_cierra_la_conexion(servidor, clientes):
    c = clientes()
    c.login()
    c.enviar("QUIT")
    assert c.esperar_eof()


def test_emitir_entero_y_a_trozos(servidor, clientes):
    """Para el cliente: una línea partida en varios recv y el fin de línea \\n suelto."""
    c = clientes()
    c.login()
    servidor.emitir("%OrderAct 1 Accept Buy ABCD 100 2.4 SAGEPRO 09:50:01  126800002")
    c.esperar_linea("%OrderAct 1 Accept")
    servidor.emitir_crudo("%POS ABCD 3 -3")
    c.esperar(lambda ls: c.bruto.endswith(b"%POS ABCD 3 -3"))
    assert not any(x.startswith("%POS ABCD") for x in c.lineas)       # media línea: aún no es una línea
    servidor.emitir_crudo(b"00 2.45 0 0 0 2026/09/25-09:49:30 -12\n")
    assert c.esperar_linea("%POS ABCD") == "%POS ABCD 3 -300 2.45 0 0 0 2026/09/25-09:49:30 -12"
    servidor.fin_linea = "\n"
    servidor.emitir("BP 1 2")
    c.esperar_linea("BP 1 2")
    assert c.bruto.endswith(b"BP 1 2\n") and not c.bruto.endswith(b"\r\nBP 1 2\n")


def test_emitir_a_watch(servidor, clientes):
    normal, watch = clientes(), clientes()
    normal.login()
    watch.login(watch=True)
    servidor.emitir("$Quote ABCD L:2", a_watch=True)
    watch.esperar_linea("$Quote ABCD L:2")
    normal.sincronizar()
    assert "$Quote ABCD L:2" not in normal.lineas
    with pytest.raises(TypeError):
        servidor.emitir(b"x")
    with pytest.raises(TypeError):
        servidor.emitir_crudo(123)


def test_echo_y_client(servidor, clientes):
    c = clientes()
    c.login()
    c.enviar("CLIENT")
    assert c.esperar_linea("CLIENT") == "CLIENT 1"
    c.enviar("ECHO OFF")
    assert c.esperar_linea("ECHO") == "ECHO OFF"


def test_latencia_retrasa_la_respuesta(libro, reloj):
    """R2-RED-2: determinista, sin reloj de pared. El `dormir` inyectado recibe
    exactamente `latencia_s` y BLOQUEA hasta que el test lo suelta: mientras está
    dormido no llega ninguna respuesta al NEWORDER; al soltarlo llega el `%ORDER`
    cuyo token es T1 (no cualquier `%ORDER`)."""
    import threading

    llamadas: list[float] = []
    dormido = threading.Event()
    soltar = threading.Event()

    def dormir(segundos: float) -> None:
        llamadas.append(segundos)
        dormido.set()
        assert soltar.wait(10.0), "el test no soltó al simulador"

    emp = Emparejador(libro, reloj, latencia_s=0.2)
    sim = SimuladorDAS(libro, reloj, emparejador=emp, dormir=dormir)
    sim.arrancar()
    c = ClientePrueba(sim.direccion)
    try:
        c.login()
        antes = len(c.lineas)
        c.enviar(f"NEWORDER {T1} SS ABCD SAGEREB 100 2.5 TIF=DAY+")
        assert dormido.wait(PLAZO_S), "el simulador no aplicó la latencia"
        assert llamadas == [0.2]
        for _ in range(5):                       # el hilo del simulador está parado dentro de dormir
            c._leer()
        assert c.lineas[antes:] == [], "llegó respuesta antes de cumplirse la latencia"
        soltar.set()
        c.esperar(lambda ls: any(getattr(m, "token", None) == T1
                                 for m in parsear([x for x in ls[antes:] if x.startswith("%ORDER ")])))
        assert llamadas == [0.2]
    finally:
        soltar.set()
        c.cerrar()
        sim.parar()


def test_latencia_por_defecto_duerme_con_time_sleep(libro, reloj):
    """R2-RED-2: sin `dormir` inyectado la latencia la aplica `time.sleep`; un `dormir` no invocable se rechaza."""
    assert SimuladorDAS(libro, reloj)._dormir is time.sleep
    with pytest.raises(TypeError):
        SimuladorDAS(libro, reloj, dormir=0.2)


def test_reabrir_por_simulador_difunde_el_fill(servidor, clientes, libro):
    c = clientes()
    c.login()
    libro.halt("ABCD", "H", "10:15:00")
    c.enviar(f"NEWORDER {T2} B ABCD OPEN 100 MKT TIF=DAY")
    c.esperar_linea("%ORDER ")
    lineas = servidor.reabrir("ABCD", D("3.1"))
    assert any(x.startswith("%TRADE") for x in lineas)
    trade = c.esperar_linea("%TRADE")
    assert parsear([trade])[0].precio == D("3.1")


def test_arrancar_idempotente_y_parar_idempotente(libro, reloj):
    sim = SimuladorDAS(libro, reloj)
    direccion = sim.arrancar()
    try:
        assert direccion[0] == "127.0.0.1" and direccion[1] > 0
        assert sim.arrancar() == direccion
    finally:
        sim.parar()
        sim.parar()
    with pytest.raises(OSError):
        socket.create_connection(direccion, timeout=0.3).close()


def test_fixture_de_conftest(simulador, direccion_simulador):
    """La fixture compartida `simulador` (conftest del lote 0) arranca en 127.0.0.1:0 y acepta el LOGIN."""
    c = ClientePrueba(direccion_simulador)
    try:
        c.enviar(f"LOGIN cualquiera clave {CUENTA} 0")
        c.esperar(lambda ls: "#TradeEnd" in ls)
    finally:
        c.cerrar()
    assert simulador.errores() == []


@pytest.mark.parametrize("kwargs", [
    pytest.param({"puerto": -1}, id="puerto-negativo"),
    pytest.param({"puerto": 70000}, id="puerto-grande"),
    pytest.param({"usuarios": {"prueba": 1}}, id="usuarios-no-texto"),
])
def test_simulador_valida_parametros(libro, reloj, kwargs):
    with pytest.raises(ValueError):
        SimuladorDAS(libro, reloj, **kwargs)


def test_simulador_exige_emparejador_del_mismo_libro(libro, reloj):
    with pytest.raises(ValueError):
        SimuladorDAS(libro, reloj, emparejador=Emparejador(LibroSimulado(), reloj))
    with pytest.raises(TypeError):
        SimuladorDAS(object(), reloj)


# ══════════════════════════════════════════════════════════════════════
# guion del replay y main
# ══════════════════════════════════════════════════════════════════════
def test_guion_de_ejemplo_se_carga_y_aplica(libro, reloj):
    programa = ProgramaGuion.cargar(GUION)
    assert programa.spread == ModeloSpread(pct=D("0.5"), minimo_ticks=1, tamano_bid=500, tamano_ask=500)
    programa.aplicar_inicio(libro)
    sim = SimuladorDAS(libro, reloj)
    emp = sim.emparejador
    libro.cotizar("ABCD", D("2.45"), D("2.47"))
    msgs = parsear(emp.recibir(f"NEWORDER {T1} SS ABCD SAGEPRO 100 2.44 TIF=DAY+"))
    assert [m.notas for m in de_tipo(msgs, MsgOrderAct) if m.accion == "Send_Rej"] == ["No shares to short"]
    msgs = parsear(emp.recibir(f"NEWORDER {T2} SS ABCD SAGEPRO 100 2.44 TIF=DAY+"))
    assert de_tipo(msgs, MsgTrade)[0].qty == 40                     # fill parcial 0,4 del guion
    antes = datetime(2026, 9, 25, 9, 44, 59, tzinfo=ET)
    assert programa.aplicar_hasta(sim, antes) == []
    assert programa.aplicar_hasta(sim, datetime(2026, 9, 25, 9, 45, tzinfo=ET)) == ["halt ABCD TA:H"]
    assert libro.en_halt("ABCD")
    assert programa.aplicar_hasta(sim, datetime(2026, 9, 25, 9, 46, tzinfo=ET)) == []
    emp.recibir(f"NEWORDER {T3} B ABCD OPEN 40 MKT TIF=DAY")
    assert programa.aplicar_hasta(sim, datetime(2026, 9, 25, 9, 50, 0, 500000, tzinfo=ET)) == ["reabrir ABCD a 3.1"]
    assert libro.en_halt("ABCD") is False
    assert libro.trades()[-1]["precio"] == D("3.1")
    assert programa.aplicar_hasta(sim, datetime(2026, 9, 25, 10, 0, tzinfo=ET)) == []


def test_guion_de_ejemplo_lo_lee_tambien_fuente_senales():
    """El mismo fichero sirve al `Guion` de fuente_senales (lote F): mismo modelo de spread."""
    fuente = pytest.importorskip("app.bot_das.fuente_senales")
    guion = fuente.Guion.cargar(GUION)
    assert guion.spread.como(ModeloSpread) == ProgramaGuion.cargar(GUION).spread
    assert len(guion.halts) == len(guion.rechazos) == len(guion.fills_parciales) == 1


@pytest.mark.parametrize("datos", [
    pytest.param([], id="no-objeto"),
    pytest.param({"extra": 1}, id="clave-desconocida"),
    pytest.param({"spread": {"pct": "x"}}, id="spread-pct-texto"),
    pytest.param({"spread": []}, id="spread-lista"),
    pytest.param({"halts": {}}, id="halts-no-lista"),
    pytest.param({"halts": [{"ticker": "ABCD", "desde": "9:45"}]}, id="hora-mal"),
    pytest.param({"halts": [{"ticker": "ABCD", "desde": "09:45", "hasta": "09:40", "precio_reapertura": "3"}]},
                 id="hasta-antes-de-desde"),
    pytest.param({"halts": [{"ticker": "ABCD", "desde": "09:45", "hasta": "09:50"}]}, id="hasta-sin-precio"),
    pytest.param({"halts": [{"ticker": "ABCD", "desde": "09:45", "ta": "T"}]}, id="ta-T"),
    pytest.param({"rechazos": [{"notas": ""}]}, id="rechazo-sin-notas"),
    pytest.param({"rechazos": [{"notas": "x", "accion": "Execute"}]}, id="rechazo-accion-mala"),
    pytest.param({"rechazos": [{"notas": "x", "token_o_orden": "1"}]}, id="rechazo-token-texto"),
    pytest.param({"fills_parciales": [{"fraccion": "0"}]}, id="parcial-cero"),
    pytest.param({"fills_parciales": [{"fraccion": "1.2"}]}, id="parcial-mayor-1"),
])
def test_guion_invalido(datos):
    with pytest.raises(ValueError):
        ProgramaGuion(datos)


def test_guion_vacio_usa_defectos():
    programa = ProgramaGuion({})
    assert programa.spread == ModeloSpread()
    assert programa.halts == programa.rechazos == programa.fills_parciales == []


def test_main_arranca_aplica_guion_y_para(capsys):
    assert sd.main(["--puerto", "0", "--guion", str(GUION), "--segundos", "0.3"]) == 0
    salida = capsys.readouterr().out
    assert "simulador DAS escuchando en 127.0.0.1:" in salida


def test_A_02_main_replace_share_total(monkeypatch):
    """A-02: `--replace-share-total` arranca el simulador con el emparejador en modo TOTAL; sin él, ABIERTA."""
    vistos: list[bool] = []
    original = sd.SimuladorDAS.__init__

    def espia(self, libro, reloj, *a, **kw):
        vistos.append(kw["emparejador"].replace_share_es_abierta)
        original(self, libro, reloj, *a, **kw)

    monkeypatch.setattr(sd.SimuladorDAS, "__init__", espia)
    assert sd.main(["--puerto", "0", "--segundos", "0", "--replace-share-total"]) == 0
    assert sd.main(["--puerto", "0", "--segundos", "0"]) == 0
    assert vistos == [False, True]


def test_main_usuario_sin_clave_es_error():
    with pytest.raises(SystemExit):
        sd.main(["--puerto", "0", "--usuario", "prueba", "--segundos", "0"])


def test_importar_no_abre_red_ni_hilos():
    """Convención §3: importar el módulo no ejecuta nada (ni hilos ni sockets ni pandas)."""
    codigo = ("import threading, sys; import app.bot_das.simulador_das; "
              "print(threading.active_count(), 'pandas' in sys.modules)")
    salida = subprocess.run([sys.executable, "-c", codigo], cwd=str(BACKEND), capture_output=True, text=True,
                            timeout=60, check=True).stdout.split()
    assert salida == ["1", "False"]


def test_ningun_mensaje_del_simulador_queda_desconocido(libro, emp):
    """Barrido: todo lo que el emparejador produce en un día corto lo entiende el Parser real."""
    libro.bandas("ABCD", D("2.2"), D("2.7"))
    libro.configurar_locate("ABCD", tipo_ruta=1)
    todas: list[str] = []
    todas += libro.cotizar("ABCD", D("2.45"), D("2.47"), last=D("2.46"), volumen=10, vwap=D("2.4"),
                           tamano_bid=300, tamano_ask=300)
    for linea in (f"NEWORDER {T1} SS ABCD SAGEREB 300 2.46 PostOnly TIF=DAY+",
                  f"NEWORDER {T2} B ABCD STOP 300 STOPLMTP 2.97 2.99 TIF=DAY+",
                  "SLPRICEINQUIRE ABCD 300 ALLROUTE", "SLNEWORDER ABCD 300 LOCSIM 326800005",
                  "GET BP", "GET POSITIONS", "GET ORDERS", "GET TRADES", "GET LOCATES", "GET SymStatus",
                  "GET LDLU", "GET SHORTINFO ABCD", "GET AccountInfo", "GET RouteStatus",
                  "SLRouteMinCharge ALLROUTE", "SLReuseQuery ABCD", f"SLAvailQuery {CUENTA} ABCD"):
        todas += emp.recibir(linea)
    todas += libro.cotizar("ABCD", D("2.98"), D("2.99"), last=D("2.98"))
    todas += emp.tic()
    todas += emp.volcado()
    msgs = parsear(todas)
    assert len(msgs) > 40
    assert emp.incidencias() == []
