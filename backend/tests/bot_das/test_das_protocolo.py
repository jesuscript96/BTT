"""Tests de `app.bot_das.protocolo` (fila `test_das_protocolo` de §10; §3.1, §4 y las 29 ambigüedades).

QUÉ DEMUESTRA. Que cada línea cruda de `fixtures/lineas_das.txt` se parsea
campo a campo como dice §4.2 (incluidos `%IORDER`, `%IPOS`, `%ITRADE` con su
orden de campos, `#buyingpower`, las 12 líneas de conexión, `%ORDER` de 15 y
19 campos y con tipo «SLP: 2.97 2.99»); que `parsear` NUNCA lanza (fuzz de
5.000 líneas con semilla fija); que los `cmd_*` producen EXACTAMENTE los
literales del manual; `es_mutante` exhaustivo; `formatear_precio`;
`normalizar_pos`; `redactar`.

POR QUÉ ESTÁ AQUÍ. El protocolo es la frontera con el dinero: un campo mal
leído (riesgo 1), un token confundido (riesgo 2), un precio «10.299999»
(riesgo 12) o un mutante que se cuela en sombra (riesgo 10) no dan error,
dan una posición equivocada.

LAS TRAMPAS. El fichero de casos lleva líneas crudas que EMPIEZAN por «#»
(marcadores, conexión): los comentarios son SOLO las líneas «# caso: …». Las
notas vacías de `%OrderAct`/`%SLRET` son DOS espacios que el editor no debe
tocar; el `$INTMSG` lleva tabuladores reales. Cuentas y traders inventados.
"""
from __future__ import annotations

import dataclasses
import inspect
import random
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.bot_das import protocolo as proto
from app.bot_das import tokens
from app.bot_das.protocolo import (
    CODIFICACION,
    CONEXION_LITERALES,
    ESTADOS_ORDEN,
    FIN_LINEA,
    LADOS,
    MUTANTES,
    Parser,
    PrecioFueraDeTick,
    cmd_cancel,
    cmd_cancel_all,
    cmd_cancel_allsymb,
    cmd_get,
    cmd_login,
    cmd_neworder,
    cmd_quit,
    cmd_replace,
    cmd_return_full_lv1,
    cmd_sb,
    cmd_sl_avail,
    cmd_sl_cancel,
    cmd_sl_inquire,
    cmd_sl_min_charge,
    cmd_sl_neworder,
    cmd_sl_offer,
    cmd_sl_reuse,
    cmd_unsb,
    es_mutante,
    formatear_precio,
    normalizar_pos,
    parsear,
    redactar,
)
from app.bot_das.tipos import (
    EstadoOrden,
    Lado,
    MensajeDAS,
    MsgAccountInfo,
    MsgBar,
    MsgBP,
    MsgConexion,
    MsgDesconocido,
    MsgInformativo,
    MsgIntMsg,
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
    MsgStInfoEx,
    MsgTrade,
    MsgTS,
    OrdenNueva,
    TipoOrden,
)

HOY = date(2026, 9, 25)                      # día 268: tokens nuestros 1_268_xxxxx (EJECUTOR) y 3_268_xxxxx (LOCATE)
FICHERO_CASOS = Path(__file__).parent / "fixtures" / "lineas_das.txt"
CUENTA = "CUENTA_PRUEBA"
D = Decimal


def es_nuestro(token: int) -> bool:
    return tokens.es_nuestro(token, HOY)


def leer_casos() -> dict[str, list[str]]:
    """{caso: [líneas crudas]}. Comentario = línea que empieza por «# caso:»; el resto son líneas crudas."""
    casos: dict[str, list[str]] = {}
    actual = None
    for linea in FICHERO_CASOS.read_text(encoding="utf-8").split("\n"):
        linea = linea.rstrip("\r")
        if linea.startswith("# caso:"):
            actual = linea[len("# caso:"):].split("|", 1)[0].strip()
            assert actual not in casos, f"caso repetido en el fichero: {actual}"
            casos[actual] = []
        elif linea == "":
            continue
        else:
            assert actual is not None, f"línea cruda sin «# caso:» delante: {linea!r}"
            casos[actual].append(linea)
    return casos


CASOS = leer_casos()


def _orden(**k):
    base = dict(order_src=None, tif=None, pref=None, watch=False, origoid=0, cuenta=CUENTA, trader="TRPRUEBA")
    base.update(k)
    return (MsgOrden, base)


def _act(**k):
    return (MsgOrderAct, k)


# caso → (regla que demuestra, clase esperada, campos esperados)
ESPERADOS: dict[str, tuple[str, type, dict]] = {
    "order_19": ("API-5.3-L343", *_orden(
        id=7001, token=126800001, ticker="ABCD", lado="SS", tipo="L", qty=300, lvqty=300, cxlqty=0,
        precio=D("2.45"), ruta="SAGEREB", estado=EstadoOrden.ACCEPTED, hora="09:49:27",
        order_src="CMDAPI", tif="DAY+", pref="N/A")),
    "order_15": ("API-5.3-L930", *_orden(
        id=7002, token=126800002, ticker="ABCD", lado="B", tipo="L", qty=100, lvqty=0, cxlqty=0,
        precio=D("2.4"), ruta="SAGEPRO", estado=EstadoOrden.EXECUTED, hora="09:50:01")),
    "order_tipo_slp": ("riesgo-1-API-5.2", *_orden(
        id=7003, token=126800003, ticker="ABCD", lado="B", tipo="SLP: 2.97 2.99", qty=300, lvqty=300, cxlqty=0,
        precio=D("2.99"), ruta="STOP", estado=EstadoOrden.ACCEPTED, hora="09:51:10",
        order_src="CMDAPI", tif="DAY+", pref="N/A")),
    "order_ajena": ("riesgo-2", *_orden(
        id=7004, token=None, ticker="WXYZ", lado="S", tipo="L", qty=50, lvqty=20, cxlqty=0, precio=D("10.3"),
        ruta="SMAT", estado=EstadoOrden.PARTIAL, hora="10:00:00", order_src="Montage", tif="DAY", pref="N/A")),
    "order_token_de_ayer": ("riesgo-2-R-A-05", *_orden(
        id=7005, token=None, ticker="ABCD", lado="SS", qty=100, estado=EstadoOrden.ACCEPTED,
        order_src="CMDAPI", tif="DAY+", pref="N/A")),
    "order_precio_no_numerico": ("L475-477", *_orden(
        id=7006, token=126800004, tipo="MKT", qty=100, precio=D("0"), ruta="OPEN", estado=EstadoOrden.HOLD,
        hora="09:25:00", order_src="CMDAPI", tif="DAY", pref="N/A")),
    "order_cuenta_con_nombre_de_estado": ("riesgo-1-ancla", *_orden(
        id=7007, token=126800005, tipo="L", qty=100, lvqty=100, precio=D("2.5"), estado=EstadoOrden.ACCEPTED,
        hora="09:31:00", cuenta="Closed", trader="12:00:00", order_src="CMDAPI", tif="DAY+", pref="N/A")),
    "iorder": ("L1436-watch", *_orden(
        id=7008, token=126800006, ticker="ABCD", lado="SS", tipo="L", qty=200, lvqty=200, precio=D("2.5"),
        estado=EstadoOrden.ACCEPTED, hora="09:52:00", order_src="CMDAPI", tif="DAY+", pref="N/A", watch=True)),
    "orderact_notas_vacias": ("API-5.4-L934", *_act(
        id=7001, accion="Accept", lado="SS", ticker="ABCD", qty=300, precio=D("2.45"), ruta="SAGEREB",
        hora="09:49:27", notas="", token=126800001)),
    "orderact_buy": ("API-5.5", *_act(
        id=7002, accion="Execute", lado="B", ticker="ABCD", qty=100, precio=D("2.4"), ruta="SAGEPRO",
        hora="09:50:01", notas="", token=126800002)),
    "orderact_numero_final_ajeno": ("riesgo-2-API-5.4", *_act(
        id=7010, accion="Send_Rej", lado="SS", qty=300, notas="No shares to short 12345", token=None)),
    "orderact_notas_y_token": ("API-5.4", *_act(
        id=7011, accion="Send_Rej", lado="B", qty=100, precio=D("2.5"), notas="PostOnly would cross",
        token=126800007)),
    "orderact_sin_notas_ni_token": ("API-5.3", *_act(
        id=7012, accion="Canceled", lado="S", ticker="WXYZ", qty=30, precio=D("10.3"), ruta="SMAT",
        hora="10:01:00", notas="", token=None)),
    "orderact_solo_numero_ajeno": ("riesgo-2", *_act(id=7013, accion="Accept", lado="S", notas="77", token=None)),
    "orderact_minusculas": ("L2037-mayusculas", *_act(
        id=7014, accion="Replaced", lado="SS", qty=200, precio=D("2.46"), token=126800008)),
    "trade_8": ("API-5.3-L508", MsgTrade, dict(
        id=9001, ticker="ABCD", lado="SS", qty=300, precio=D("2.45"), ruta="SAGEREB", hora="09:49:30",
        id_orden=7001, liq=None, ecn_fee=None, pl=None, cuenta=None, trader=None, watch=False)),
    "trade_11": ("API-5.3-L496", MsgTrade, dict(
        id=9002, lado="B", qty=100, precio=D("2.4"), id_orden=7002, liq="-", ecn_fee=D("0.3"), pl=D("-15.5"),
        watch=False)),
    "itrade": ("L1446-rama-propia", MsgTrade, dict(
        id=9003, ticker="ABCD", lado="SS", qty=200, precio=D("2.5"), ruta="SAGEREB", hora="09:52:05",
        id_orden=7008, cuenta=CUENTA, trader="TRPRUEBA", liq=None, ecn_fee=None, pl=None, watch=True)),
    "pos_9_corto_negativo": ("riesgo-9-injertoA-8.8", MsgPos, dict(
        ticker="ABCD", tipo=3, qty_cruda=-300, neta=-300, avg=D("2.45"), init_qty=0, init_precio=D("0"),
        realizado=D("0"), creada="2026/09/25-09:49:30", no_realizado=D("-12"), watch=False)),
    "pos_9_corto_positivo": ("riesgo-9-API-5.12", MsgPos, dict(
        ticker="EFGH", tipo=3, qty_cruda=100, neta=-100, avg=D("5.1"), no_realizado=D("25"))),
    "pos_8": ("API-5.3-L267", MsgPos, dict(
        ticker="WXYZ", tipo=2, qty_cruda=100, neta=100, avg=D("10.3"), no_realizado=None, watch=False)),
    "ipos": ("L1441-watch", MsgPos, dict(ticker="ABCD", tipo=3, qty_cruda=300, neta=-300, watch=True)),
    "marca_pos": ("API-5.13", MsgMarcador, dict(nombre="#POS")),
    "marca_posend": ("API-5.13", MsgMarcador, dict(nombre="#POSEND")),
    "marca_order": ("API-5.13", MsgMarcador, dict(nombre="#Order")),
    "marca_orderend": ("API-5.13", MsgMarcador, dict(nombre="#OrderEnd")),
    "marca_trade": ("API-5.13", MsgMarcador, dict(nombre="#Trade")),
    "marca_tradeend": ("API-5.13", MsgMarcador, dict(nombre="#TradeEnd")),
    "marca_slorder": ("API-5.13", MsgMarcador, dict(nombre="#SLOrder")),
    "marca_slorderend": ("API-5.13", MsgMarcador, dict(nombre="#SLOrderEnd")),
    "marca_buyingpower": ("API-5.14", MsgMarcador, dict(nombre="#buyingpower")),
    "bp": ("L993", MsgBP, dict(bp=D("94339.5"), bp_overnight=D("100000"))),
    "conexion_order_logon_ok": ("L1477", MsgConexion, dict(servidor="OrderServer", evento="Logon:Successful")),
    "conexion_order_logon_ko": ("L1478", MsgConexion, dict(servidor="OrderServer", evento="Logon:Failed")),
    "conexion_order_connect_ok": ("L1479", MsgConexion, dict(servidor="OrderServer", evento="Connect:Successful")),
    "conexion_order_connect_ko": ("L1480", MsgConexion, dict(servidor="OrderServer", evento="Connect:Failed")),
    "conexion_quote_logon_ok": ("L1481", MsgConexion, dict(servidor="QuoteServer", evento="Logon:Successful")),
    "conexion_quote_logon_ko": ("L1482", MsgConexion, dict(servidor="QuoteServer", evento="Logon:Failed")),
    "conexion_quote_connect_ok": ("L1483", MsgConexion, dict(servidor="QuoteServer", evento="Connect:Successful")),
    "conexion_quote_connect_ko": ("L1484", MsgConexion, dict(servidor="QuoteServer", evento="Connect:Failed")),
    "conexion_quote_heartbeat": ("API-5.26-L1485", MsgConexion, dict(servidor="QuoteServer", evento="Missing heartbeat")),
    "conexion_order_heartbeat": ("API-5.26-L1486", MsgConexion, dict(servidor="OrderServer", evento="Missing heartbeat")),
    "conexion_quote_perdida": ("API-5.26-L1489", MsgConexion, dict(servidor="QuoteServer", evento="Lost Connection")),
    "conexion_order_perdida": ("API-5.26-L1490", MsgConexion, dict(servidor="OrderServer", evento="Lost Connection")),
    "quote_completo": ("L1248", MsgQuote, dict(ticker="ABCD", campos={
        "A": "2.46", "Asz": "5", "B": "2.45", "Bsz": "3", "V": "1234567", "L": "2.45", "Hi": "3.1", "Lo": "2.2",
        "op": "0", "ycl": "1.7", "tcl": "0", "PE": "Q", "VWAP": "2.61", "T": "094930"})),
    "quote_parcial": ("riesgo-15-API-5.19", MsgQuote, dict(ticker="ABCD", campos={"V": "1240000"})),
    "quote_claves_desconocidas": ("API-5.19", MsgQuote, dict(
        ticker="ABCD", campos={"RVOL": "3.5", "tradesAllDay": "15230", "L": "2.44"})),
    "issuestatus_sin_ta": ("API-5.9-L1117", MsgIssueStatus, dict(ticker="ABCD", ssr=True, ta=None, tat=None)),
    "issuestatus_halt": ("API-5.9", MsgIssueStatus, dict(ticker="ABCD", ssr=False, ta="H", tat="10:15:00")),
    "symstatus": ("API-5.9", MsgIssueStatus, dict(ticker="WXYZ", ssr=False, ta="T", tat="10:20:00")),
    "shortinfo_7": ("API-5.3-L1029", MsgShortInfo, dict(
        ticker="ABCD", shortable=True, short_size=10000, marginable=True, tasa_larga=D("0"), tasa_corta=D("0"),
        prohibido=False, reg_sho=None)),
    "shortinfo_8": ("L206-RegSho", MsgShortInfo, dict(
        shortable=False, short_size=0, marginable=True, tasa_corta=D("100"), prohibido=False, reg_sho=True)),
    "stinfoex": ("API-5.21", MsgStInfoEx, dict(
        ticker="ABCD", valores={"ConcLong": D("200"), "ConcShr": D("50")}, texto="ConcLong: 200%,ConcShr: 50%;")),
    "ldlu": ("L1079", MsgLDLU, dict(ticker="ABCD", limit_down=D("2.2"), limit_up=D("2.7"))),
    "accountinfo": ("L1143", MsgAccountInfo, dict(
        open_eq=D("25000.00"), curr_eq=D("25310.50"), realizado=D("310.50"), no_realizado=D("-12.00"),
        net=D("298.50"), htb=D("1.20"), sec=D("0.05"), finra=D("0.01"), ecn=D("0.30"), comision=D("2.00"))),
    "slret_notas_vacias_con_cuenta": ("API-5.4-L1710", MsgSLRet, dict(
        tipo=1, ticker="ABCD", precio=D("0.01"), tamano=300, ruta="LOC3", notas="", cuenta=CUENTA)),
    "slret_fallo_con_cuenta": ("L1712", MsgSLRet, dict(
        tipo=2, precio=D("0"), tamano=0, ruta="LOC3", notas="AlreadyShortable", cuenta=CUENTA)),
    "slret_sin_cuenta": ("API-5.3", MsgSLRet, dict(tipo=2, notas="AlreadyShortable", cuenta=None)),
    "slret_notas_con_espacios": ("API-5.4", MsgSLRet, dict(notas="Not enough shares", cuenta=CUENTA)),
    "slorder_con_token": ("L1766-token", MsgSLOrder, dict(
        id=5001, ticker="ABCD", pedidas=300, abiertas=0, localizadas=300, precio=D("0.012"), estado="Located",
        ruta="LOC3", hora="09:40:02", limite=D("0"), token=326800001, notas="located ok")),
    "slorder_sin_token": ("API-5.3", MsgSLOrder, dict(
        id=5002, pedidas=300, abiertas=300, localizadas=0, precio=D("0"), estado="Offered", ruta="LOC7",
        hora="09:40:05", limite=D("0"), token=None, notas="offer pending")),
    "slmincharge_sin_dolar": ("API-5.10", MsgSLMinCharge, dict(ruta="LOC7", minimo=D("1"))),
    "slmincharge_con_dolar": ("API-5.10", MsgSLMinCharge, dict(ruta="LOC3", minimo=D("2.5"))),
    "slreuse": ("EP-9-L1818", MsgSLReuse, dict(ticker="ABCD", reutilizable=False)),
    "slavail": ("R-H-04-L1804", MsgSLAvail, dict(cuenta=CUENTA, ticker="ABCD", disponibles=200)),
    "routestatus_enabled": ("API-5.27", MsgRouteStatus, dict(ruta="SAGEREB", habilitada=True)),
    "routestatus_disabled": ("API-5.27", MsgRouteStatus, dict(ruta="ALGO", habilitada=False)),
    "ts": ("R-A-02-API-5.20", MsgTS, dict(
        ticker="ABCD", precio=D("2.45"), volumen=100, flag="R", hora="09:49:30", bolsa="Q", lado="B", condicion=32)),
    "bar_dia": ("L1373-HLOC", MsgBar, dict(
        ticker="ABCD", cuando="2026/09/24", high=D("1.9"), low=D("1.6"), open=D("1.7"), close=D("1.75"),
        volumen=18000917, min_type=None)),
    "bar_minuto": ("L1373-HLOC", MsgBar, dict(
        cuando="2026/09/25-09:49", high=D("2.5"), low=D("2.4"), open=D("2.48"), close=D("2.45"), volumen=50000,
        min_type=1)),
    "toplst": ("API-5.25", MsgInformativo, dict(palabra="$TopLst")),
    "lv2": ("API-5.25", MsgInformativo, dict(palabra="$Lv2")),
    "echo": ("API-5.25", MsgInformativo, dict(palabra="ECHO")),
    "client": ("API-5.25", MsgInformativo, dict(palabra="CLIENT")),
    "almohadilla_no_listada": ("API-5.25", MsgInformativo, dict(palabra="#ServidorNuevo:Algo:Distinto")),
    "basura": ("API-5.15", MsgDesconocido, dict(palabra="HOLA")),
    "order_truncada": ("API-5.15", MsgDesconocido, dict(palabra="%ORDER")),
    "trade_truncado": ("API-5.15", MsgDesconocido, dict(palabra="%TRADE")),
}
CASOS_MULTILINEA = {"intmsg"}


# ══════════════════════════════════════════════════════════════════════
# El fichero de casos
# ══════════════════════════════════════════════════════════════════════
def test_fichero_de_casos_y_tabla_coinciden():
    """Cada caso del fichero tiene sus asertos aquí y viceversa (una línea nueva sin asertos no pasa en silencio)."""
    assert set(CASOS) == set(ESPERADOS) | CASOS_MULTILINEA
    for caso, lineas in CASOS.items():
        esperado = 5 if caso == "intmsg" else 1
        assert len(lineas) == esperado, caso


def test_fichero_sin_credenciales_del_manual():
    """R-Q-01: ni las cuentas/traders de ejemplo del manual ni cuentas reales en las fixtures."""
    texto = FICHERO_CASOS.read_text(encoding="utf-8")
    for prohibido in ("TRBIAN", "730001", "BIAN "):
        assert prohibido not in texto


def test_notas_vacias_conservan_dos_espacios_en_el_fichero():
    """API-5.4: si un editor colapsara los dos espacios, el caso dejaría de probar lo que dice."""
    assert "09:49:27  126800001" in CASOS["orderact_notas_vacias"][0]
    assert "LOC3  CUENTA_PRUEBA" in CASOS["slret_notas_vacias_con_cuenta"][0]
    assert "\t" in CASOS["intmsg"][4]


@pytest.mark.parametrize("caso", [pytest.param(c, id=f"{c}-{r}") for c, (r, _k, _v) in ESPERADOS.items()])
def test_parse_de_cada_linea_del_fichero(caso):
    _regla, clase, campos = ESPERADOS[caso]
    linea = CASOS[caso][0]
    msg = Parser(es_nuestro).parsear(linea)
    assert type(msg) is clase, f"{caso}: {msg!r}"
    assert msg.cruda == linea
    for campo, valor in campos.items():
        obtenido = getattr(msg, campo)
        assert obtenido == valor, f"{caso}.{campo}: {obtenido!r} != {valor!r}"
        if isinstance(valor, Decimal):
            assert type(obtenido) is Decimal, f"{caso}.{campo} no es Decimal"


@pytest.mark.parametrize("caso", sorted(CASOS))
def test_ningun_campo_es_float(caso):
    """Riesgo 12: todo precio que sale del parser es Decimal, nunca float."""
    parser = Parser(es_nuestro)
    for linea in CASOS[caso]:
        msg = parser.parsear(linea)
        for f in dataclasses.fields(msg):
            valor = getattr(msg, f.name)
            assert not isinstance(valor, float), f"{caso}.{f.name} = {valor!r}"
            if isinstance(valor, dict):
                assert not any(isinstance(v, float) for v in valor.values())


def test_intmsg_multilinea_se_acumula_hasta_msg():
    """L1575-1610: cuatro partes informativas y `Msg` cierra el mensaje; `\\t` = salto de línea."""
    parser = Parser(es_nuestro)
    lineas = CASOS["intmsg"]
    intermedios = [parser.parsear(x) for x in lineas[:-1]]
    assert all(type(m) is MsgInformativo and m.palabra == "$INTMSG" for m in intermedios)
    final = parser.parsear(lineas[-1])
    assert type(final) is MsgIntMsg
    assert final.campos == {
        "Send Time": "2026/09/25 10:12:38", "From": "BROKER", "To": "ALL",
        "Title": "Aviso interno de prueba", "Msg": "Linea uno.\nLinea dos.\nFin.",
    }
    # El siguiente mensaje empieza limpio: un Msg suelto no arrastra el anterior.
    suelto = parser.parsear("$INTMSG Msg: solo cuerpo")
    assert type(suelto) is MsgIntMsg and suelto.campos == {"Msg": "solo cuerpo"}


def test_intmsg_send_time_reinicia_la_acumulacion():
    parser = Parser(es_nuestro)
    parser.parsear("$INTMSG Send Time: 2026/09/25 10:00:00")
    parser.parsear("$INTMSG From: VIEJO")
    parser.parsear("$INTMSG Send Time: 2026/09/25 10:05:00")
    final = parser.parsear("$INTMSG Msg: nuevo")
    assert final.campos == {"Send Time": "2026/09/25 10:05:00", "Msg": "nuevo"}


# ══════════════════════════════════════════════════════════════════════
# Detalles del parser
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("linea, notas, cuenta", [
    pytest.param("%SLRET 2 ABCD 0 0 LOC3 Not enough shares", "Not enough shares", None, id="API-5.4-sin-cuenta-exacta"),
    pytest.param("%SLRET 2 ABCD 0 0 LOC3 Not enough shares CUENTA_PRUEBA", "Not enough shares", CUENTA,
                 id="API-5.4-con-cuenta"),
    pytest.param("%SLRET 1 ABCD 0.01 300 LOC3  CUENTA_PRUEBA", "", CUENTA, id="API-5.4-notas-vacias"),
    pytest.param("%SLRET 2 ABCD 0 0 LOC3 OTRA", "OTRA", None, id="API-5.4-palabra-que-no-es-la-cuenta"),
])
def test_slret_con_cuenta_conocida_separa_exacto(linea, notas, cuenta):
    """API-5.4: con la cuenta del LOGIN la separación Notes/Account es exacta."""
    msg = Parser(es_nuestro, cuenta=CUENTA).parsear(linea)
    assert type(msg) is MsgSLRet
    assert (msg.notas, msg.cuenta) == (notas, cuenta)


def test_slret_sin_cuenta_heuristica_documentada():
    """API-5.4: sin cuenta conocida, con dos o más palabras la última se toma como cuenta (límite documentado)."""
    msg = Parser(es_nuestro).parsear("%SLRET 2 ABCD 0 0 LOC3 Not enough shares")
    assert (msg.notas, msg.cuenta) == ("Not enough", "shares")
    assert Parser(es_nuestro).cuenta is None
    assert Parser(es_nuestro, cuenta="  ").cuenta is None


def test_en_bloque_sigue_los_marcadores():
    """API-5.11: los marcadores son opcionales; `en_bloque` solo informa, no filtra."""
    parser = Parser(es_nuestro)
    assert parser.en_bloque is None
    pasos = [
        ("#POS symb type qty", "POS"), ("%POS ABCD 3 100 2.45 0 0 0 2026/09/25-09:49:30", "POS"),
        ("#buyingpower bp,nbp", "POS"), ("#POSEND", None), ("#Order id token", "Order"), ("#OrderEnd", None),
        ("#Trade id", "Trade"), ("#TradeEnd", None), ("#SLOrder id", "SLOrder"), ("#SLOrderEnd", None),
    ]
    for linea, bloque in pasos:
        parser.parsear(linea)
        assert parser.en_bloque == bloque, linea


def test_parser_watch_marca_ordenes_posiciones_y_trades():
    """L1436-1458 y §5.24: por la conexión watch todo es watch, aunque llegue sin la «I»."""
    parser = Parser(es_nuestro, watch=True)
    assert parser.watch is True
    assert parser.parsear(CASOS["order_19"][0]).watch is True
    assert parser.parsear(CASOS["pos_8"][0]).watch is True
    assert parser.parsear(CASOS["trade_8"][0]).watch is True


@pytest.mark.parametrize("linea", [
    pytest.param("#orderserver:logon:successful", id="L2037-minusculas"),
    pytest.param("  #OrderServer:Lost Connection  ", id="API-5.26-espacios-alrededor"),
    pytest.param("#ORDERSERVER:MISSING HEARTBEAT", id="API-5.26-mayusculas"),
])
def test_conexion_insensible_a_mayusculas_y_espacios(linea):
    msg = parsear(linea)
    assert type(msg) is MsgConexion
    assert msg.servidor == "OrderServer"


def test_conexion_con_texto_de_mas_no_se_confunde():
    """API-5.26: comparación ENTERA; «Lost Connection now» no es la línea documentada."""
    msg = parsear("#OrderServer:Lost Connection now")
    assert type(msg) is MsgInformativo


@pytest.mark.parametrize("final, cruda", [
    pytest.param("\r\n", "BP 1 2", id="API-5.1-crlf"),
    pytest.param("\n", "BP 1 2", id="API-5.1-lf"),
    pytest.param("\r", "BP 1 2", id="API-5.1-cr"),
])
def test_fin_de_linea_se_quita_de_la_cruda(final, cruda):
    msg = parsear("BP 1 2" + final)
    assert type(msg) is MsgBP and msg.cruda == cruda


def test_bytes_latin1_no_lanzan():
    """API-5.1: los bytes se decodifican en latin-1 con errors=replace (notas del bróker con no-ASCII)."""
    crudo = "%OrderAct 7010 Send_Rej Shrt ABCD 300 2.45 SAGEREB 09:49:28 Rechazo:ñandú 126800009".encode("latin-1")
    msg = Parser(es_nuestro).parsear(crudo)
    assert type(msg) is MsgOrderAct
    assert msg.notas == "Rechazo:ñandú" and msg.token == 126800009


@pytest.mark.parametrize("entrada", [
    pytest.param("", id="vacia"), pytest.param("   ", id="espacios"), pytest.param(None, id="None"),
    pytest.param(12345, id="entero"), pytest.param(b"\xff\xfe\x00", id="bytes-raros"),
])
def test_entradas_raras_dan_desconocido(entrada):
    """API-5.15: nunca se lanza."""
    msg = Parser(es_nuestro).parsear(entrada)
    assert isinstance(msg, MensajeDAS)
    assert type(msg) in (MsgDesconocido, MsgInformativo)


def test_es_nuestro_que_lanza_no_tumba_el_parser():
    """Frontera de callback: un `es_nuestro` roto hace que el token se trate como ajeno."""
    def roto(_t: int) -> bool:
        raise RuntimeError("fallo")
    msg = Parser(roto).parsear(CASOS["orderact_notas_y_token"][0])
    assert type(msg) is MsgOrderAct
    assert msg.token is None and msg.notas == "PostOnly would cross 126800007"


def test_parser_exige_callable():
    with pytest.raises(TypeError):
        Parser(None)  # type: ignore[arg-type]


def test_atajo_parsear_acepta_cualquier_token():
    """§3.1: el atajo sin estado de los tests acepta todo entero como token."""
    msg = parsear("%OrderAct 1 Accept Buy ABCD 1 2 SMAT 09:00:00  5")
    assert msg.token == 5 and msg.notas == ""


def test_trade_con_opcionales_no_numericos_no_pierde_el_fill():
    """Riesgo 8: un EcnFee/PL raro no hace perder la ejecución."""
    msg = parsear("%TRADE 9002 ABCD B 100 2.4 SAGEPRO 09:50:01 7002 + N/A ?")
    assert type(msg) is MsgTrade
    assert (msg.qty, msg.liq, msg.ecn_fee, msg.pl) == (100, "+", None, None)


@pytest.mark.parametrize("linea", [
    pytest.param("%ORDER x 1 ABCD B L 1 1 0 2 SMAT Accepted 09:00:00 0 C T", id="API-5.15-id-no-entero"),
    pytest.param("%ORDER 1 1 ABCD B L 1 1 0 2 SMAT Aceptada 09:00:00 0 C T", id="API-5.2-estado-fuera-del-conjunto"),
    pytest.param("%ORDER 1 1 ABCD B L 1 1 0 2 SMAT Accepted 9:00:00 0 C T", id="API-5.2-hora-mal"),
    pytest.param("%ORDER 1 1 ABCD B L 1 1 0 2 SMAT Accepted 09:00:00 0 C", id="API-5.3-faltan-campos"),
    pytest.param("%ORDER 1 1 ABCD B 1 1 0 2 SMAT Accepted 09:00:00 0 C T", id="API-5.2-sin-tipo"),
    pytest.param("%POS ABCD x 100 1 0 0 0 2026/09/25-09:00:00", id="API-5.15-tipo-pos"),
    pytest.param("$RouteStatus SAGEREB Quizas", id="L1567-estado-ruta"),
    pytest.param("$SLReuseQueryRet ABCD Tal", id="L1818-yes-no"),
    pytest.param("$SHORTINFO ABCD X 1 Y 0 0 N", id="L1017-y-n"),
    pytest.param("BP abc 1", id="L993-no-numerico"),
    pytest.param("BP NaN 1", id="L993-no-finito"),
    pytest.param("$INTMSG sin dos puntos", id="L1575-sin-clave"),
])
def test_lineas_malformadas_dan_desconocido(linea):
    msg = Parser(es_nuestro).parsear(linea)
    assert type(msg) is MsgDesconocido
    assert msg.cruda == linea


def test_lados_normalizados_y_desconocido_conservado():
    """API-5.5: Buy/Shrt/Sell/Short → B/SS/S; un valor raro se conserva para registrarlo."""
    assert LADOS == {"B": "B", "BUY": "B", "S": "S", "SELL": "S", "SS": "SS", "SHRT": "SS", "SHORT": "SS"}
    msg = parsear("%OrderAct 1 Accept Cover ABCD 1 2 SMAT 09:00:00")
    assert msg.lado == "Cover"


def test_constantes_del_protocolo():
    """§3.1: conjuntos cerrados del manual."""
    assert FIN_LINEA == "\r\n" and CODIFICACION == "latin-1"
    assert MUTANTES == frozenset({"NEWORDER", "CANCEL", "REPLACE", "COMPLEXORDER", "SCRIPT", "GSCRIPT",
                                  "SLNEWORDER", "SLOFFEROPERATION", "SLCANCELORDER"})
    assert ESTADOS_ORDEN == frozenset({"Closed", "Hold", "Sending", "Accepted", "Canceled", "Rejected",
                                       "Executed", "Partial", "Triggered"})
    assert len(CONEXION_LITERALES) == 12
    assert sum(" " in k for k in CONEXION_LITERALES) == 4
    assert proto.ACCIONES_ORDERACT == frozenset({"Sending", "Send_Rej", "Accept", "Canceling", "Canceled", "CancelRej",
                                                 "TimeOut", "Execute", "Close", "Replaced", "Replacing", "ReplaceRej"})
    assert proto.ESTADOS_LOCATE == frozenset({"Pending", "Waiting", "Located", "Offered", "Canceled", "Rejected",
                                              "Closed", "Declined"})


def test_modulo_puro_sin_red_ni_hilos():
    """§3.1 «puro»: importar protocolo no trae socket, hilos, tiempo ni logging."""
    fuente = inspect.getsource(proto)
    for prohibido in ("import socket", "import threading", "import time", "import logging", "import os"):
        assert prohibido not in fuente


# ══════════════════════════════════════════════════════════════════════
# Fuzz: `parsear` NUNCA lanza
# ══════════════════════════════════════════════════════════════════════
_BASURA = ["", " ", "  ", "NaN", "Infinity", "-inf", "1e999", "99999999999999999999", "Closed", "Accepted",
           "09:99:99", "10:00:00", "::", "$", "%", "\t", "é", "\x00", "-", "0", "-1", "SLP:", "2.97", "N/A",
           " ", "\x85", "#", "Msg:", "Send Time:"]
_CLAVES = ["%ORDER", "%IORDER", "%OrderAct", "%TRADE", "%ITRADE", "%POS", "%IPOS", "$Quote", "BP", "$SHORTINFO",
           "$STINFOEX", "$LDLU", "$IssueStatus", "$SymStatus", "$AccountInfo", "%SLRET", "%SLOrder",
           "$SLReuseQueryRet", "$SLAvailQueryRet", "SLRouteMinChargeRet", "$SLRouteMinChargeRet", "$RouteStatus",
           "$INTMSG", "$T&S", "$Bar", "#POS", "#OrderServer:Logon:Successful", "ECHO", "XYZ"]


def _linea_aleatoria(rnd: random.Random, corpus: list[str]):
    modo = rnd.randrange(5)
    base = rnd.choice(corpus)
    if modo == 0:                                        # truncada en un punto cualquiera
        return base[: rnd.randrange(len(base) + 1)]
    if modo == 1:                                        # campos sustituidos por basura
        partes = base.split(" ")
        for _ in range(rnd.randint(1, 4)):
            partes[rnd.randrange(len(partes))] = rnd.choice(_BASURA)
        return " ".join(partes)
    if modo == 2:                                        # palabra clave conocida + palabras al azar
        n = rnd.randint(0, 25)
        return " ".join([rnd.choice(_CLAVES)] + [rnd.choice(_BASURA + base.split()) for _ in range(n)])
    if modo == 3:                                        # caracteres imprimibles y de control al azar
        return "".join(chr(rnd.randrange(0, 0x2100)) for _ in range(rnd.randint(0, 80)))
    return bytes(rnd.randrange(256) for _ in range(rnd.randint(0, 60)))    # bytes crudos


def test_fuzz_5000_lineas_nunca_lanza():
    """API-5.15 y §10: 5.000 líneas aleatorias y truncadas (semilla fija) → siempre un MensajeDAS con la cruda."""
    rnd = random.Random(20260925)
    corpus = [linea for lineas in CASOS.values() for linea in lineas]
    con_estado = Parser(es_nuestro, cuenta=CUENTA)
    watch = Parser(es_nuestro, watch=True)
    for _ in range(5000):
        linea = _linea_aleatoria(rnd, corpus)
        for parser in (con_estado, watch):
            msg = parser.parsear(linea)
            assert isinstance(msg, MensajeDAS)
            if isinstance(linea, str):
                assert msg.cruda == linea.rstrip("\r\n")
        assert isinstance(parsear(linea), MensajeDAS)


# ══════════════════════════════════════════════════════════════════════
# Hacia DAS: literales exactos del manual
# ══════════════════════════════════════════════════════════════════════
def _o(**k) -> OrdenNueva:
    base = dict(token=1, lado=Lado.COMPRA, ticker="MSFT", ruta="ARCA", qty=100, tipo=TipoOrden.LIMITE,
                precio=D("200.5"))
    base.update(k)
    return OrdenNueva(**base)


@pytest.mark.parametrize("orden, literal", [
    pytest.param(_o(), "NEWORDER 1 B MSFT ARCA 100 200.5 TIF=DAY+", id="L546-limite"),
    pytest.param(_o(token=2, lado=Lado.VENTA, ruta="SMAT", tipo=TipoOrden.MERCADO, precio=None, tif="DAY"),
                 "NEWORDER 2 S MSFT SMAT 100 MKT TIF=DAY", id="L552-mercado"),
    pytest.param(_o(token=5, ruta="SMAT", tipo=TipoOrden.STOP_LIMITE_PP, stop=D("210.5"), precio=D("210.8"),
                    tif="DAY"),
                 "NEWORDER 5 B MSFT SMAT 100 STOPLMTP 210.5 210.8 TIF=DAY", id="L622-stoplmtp"),
    pytest.param(_o(post_only=True), "NEWORDER 1 B MSFT ARCA 100 200.5 PostOnly TIF=DAY+", id="L767-postonly"),
    pytest.param(_o(token=4, lado=Lado.VENTA, ruta="SMAT", tipo=TipoOrden.STOP_LIMITE_PP, stop=D("2.97"),
                    precio=D("2.94"), pref="ARCA"),
                 "NEWORDER 4 S MSFT SMAT 100 STOPLMTP 2.97 2.94 TIF=DAY+ Pref=ARCA", id="L794-pref"),
    pytest.param(_o(token=126800001, lado=Lado.CORTO, ticker="ABCD", ruta="MIAX", qty=3000, precio=D("0.1234"),
                    post_only=True),
                 "NEWORDER 126800001 SS ABCD MIAX 3000 0.1234 PostOnly TIF=DAY+", id="regla612-corto-menos-de-1"),
    pytest.param(_o(precio=D("10.30")), "NEWORDER 1 B MSFT ARCA 100 10.3 TIF=DAY+", id="API-5.28-sin-ceros"),
    pytest.param(_o(token=-5), "NEWORDER -5 B MSFT ARCA 100 200.5 TIF=DAY+", id="API-5.18-int32-negativo"),
])
def test_cmd_neworder_literales_del_manual(orden, literal):
    assert cmd_neworder(orden) == literal
    assert es_mutante(literal)


@pytest.mark.parametrize("orden", [
    pytest.param(_o(ticker="AB CD"), id="ticker-con-espacio"),
    pytest.param(_o(ruta=""), id="ruta-vacia"),
    pytest.param(_o(tif="DAY +"), id="tif-con-espacio"),
    pytest.param(_o(ticker="ABCD\r\nCANCEL ALL"), id="riesgo10-inyeccion-de-linea"),
    pytest.param(_o(pref="AR CA"), id="pref-con-espacio"),
])
def test_cmd_neworder_rechaza_campos_que_desplazarian_la_linea(orden):
    with pytest.raises(ValueError):
        cmd_neworder(orden)


def test_cmd_neworder_exige_ordennueva():
    with pytest.raises(TypeError):
        cmd_neworder("NEWORDER 1 B X ARCA 1 1")  # type: ignore[arg-type]


@pytest.mark.parametrize("args, literal", [
    pytest.param((1, 100, TipoOrden.LIMITE, D("200.5"), None), "REPLACE 1 100 200.5", id="L822-limite"),
    pytest.param((5, 100, TipoOrden.STOP_LIMITE_PP, D("210.8"), D("210.5")), "REPLACE 5 100 STOPLMT 210.5 210.8",
                 id="API-5.6-L850-stoplmtp-como-stoplmt"),
    pytest.param((2, 100, TipoOrden.MERCADO, None, None), "REPLACE 2 100 MKT", id="L831-mercado"),
    pytest.param((77, 300, TipoOrden.STOP_LIMITE_PP, D("0.5145"), D("0.5")), "REPLACE 77 300 STOPLMT 0.5 0.5145",
                 id="regla612-menos-de-1"),
])
def test_cmd_replace_literales(args, literal):
    assert cmd_replace(*args) == literal
    assert es_mutante(literal)


@pytest.mark.parametrize("args, error", [
    pytest.param((1, 100, TipoOrden.LIMITE, None, None), ValueError, id="limite-sin-precio"),
    pytest.param((1, 100, TipoOrden.LIMITE, D("2"), D("1")), ValueError, id="limite-con-stop"),
    pytest.param((1, 100, TipoOrden.STOP_LIMITE_PP, D("2"), None), ValueError, id="stop-sin-disparo"),
    pytest.param((1, 100, TipoOrden.MERCADO, D("2"), None), ValueError, id="mercado-con-precio"),
    pytest.param((1, 100, TipoOrden.LIMITE, D("10.299999"), None), PrecioFueraDeTick, id="riesgo12-fuera-de-tick"),
    pytest.param((0, 100, TipoOrden.LIMITE, D("2"), None), ValueError, id="id-cero"),
    pytest.param((1, True, TipoOrden.LIMITE, D("2"), None), ValueError, id="qty-bool"),
    pytest.param((1, 10.0, TipoOrden.LIMITE, D("2"), None), ValueError, id="qty-float"),
    pytest.param((1, 100, "LMT", D("2"), None), ValueError, id="tipo-texto"),
])
def test_cmd_replace_rechaza(args, error):
    with pytest.raises(error):
        cmd_replace(*args)


@pytest.mark.parametrize("literal, esperado", [
    pytest.param(cmd_cancel(123), "CANCEL 123", id="L803-cancel"),
    pytest.param(cmd_cancel_all(), "CANCEL ALL", id="L804-cancel-all"),
    pytest.param(cmd_cancel_allsymb("ABCD"), "CANCEL ALLSYMB ABCD", id="L806-cancel-allsymb"),
    pytest.param(cmd_login("prueba", "clave-inventada", CUENTA, False), "LOGIN prueba clave-inventada CUENTA_PRUEBA 0",
                 id="L244-login-normal"),
    pytest.param(cmd_login("prueba", "clave-inventada", CUENTA, True), "LOGIN prueba clave-inventada CUENTA_PRUEBA 1",
                 id="L244-login-watch"),
    pytest.param(cmd_sb("ABCD"), "SB ABCD Lv1", id="L1173-sb"),
    pytest.param(cmd_sb("ABCD", "tms"), "SB ABCD tms", id="L1174-sb-tms"),
    pytest.param(cmd_unsb("ABCD"), "UNSB ABCD Lv1", id="L1238-unsb"),
    pytest.param(cmd_unsb("ABCD", "lv2"), "UNSB ABCD Lv2", id="L1240-unsb-lv2-mayusculas-del-manual"),
    pytest.param(cmd_return_full_lv1(False), "ReturnFullLv1 NO", id="L1532-returnfull-no"),
    pytest.param(cmd_return_full_lv1(True), "ReturnFullLv1 YES", id="L1530-returnfull-si"),
    pytest.param(cmd_sl_inquire("ABCD", 300, "ALLROUTEWTTYPE1"), "SLPRICEINQUIRE ABCD 300 ALLROUTEWTTYPE1",
                 id="R-H-01-L1648-inquire"),
    pytest.param(cmd_sl_neworder("ABCD", 300, "LOC3", 326800001), "SLNEWORDER ABCD 300 LOC3 326800001",
                 id="L1671-sl-neworder"),
    pytest.param(cmd_sl_offer(5001, True), "SLOFFEROPERATION 5001 Accept", id="L1692-offer-accept"),
    pytest.param(cmd_sl_offer(5001, False), "SLOFFEROPERATION 5001 Reject", id="L1693-offer-reject"),
    pytest.param(cmd_sl_cancel(5001), "SLCANCELORDER 5001", id="L1686-sl-cancel"),
    pytest.param(cmd_sl_reuse("ABCD"), "SLReuseQuery ABCD", id="EP-9-L1810-reuse"),
    pytest.param(cmd_sl_avail(CUENTA, "ABCD"), "SLAvailQuery CUENTA_PRUEBA ABCD", id="API-5.23-L1796-avail"),
    pytest.param(cmd_sl_min_charge("ALLROUTE"), "SLRouteMinCharge ALLROUTE", id="L1823-min-charge"),
    pytest.param(cmd_quit(), "QUIT", id="L1619-quit"),
])
def test_cmd_literales(literal, esperado):
    assert literal == esperado


@pytest.mark.parametrize("llamada", [
    pytest.param(lambda: cmd_cancel(0), id="cancel-cero"),
    pytest.param(lambda: cmd_cancel(-1), id="cancel-negativo"),
    pytest.param(lambda: cmd_cancel(True), id="cancel-bool"),
    pytest.param(lambda: cmd_cancel_allsymb(""), id="allsymb-vacio"),
    pytest.param(lambda: cmd_login("a b", "c", "d", False), id="login-usuario-con-espacio"),
    pytest.param(lambda: cmd_login("a", "", "d", False), id="login-clave-vacia"),
    pytest.param(lambda: cmd_sb("ABCD", "DAYCHART"), id="R-A-06-sb-daychart"),
    pytest.param(lambda: cmd_sb("ABCD", "TopList"), id="R-A-06-sb-toplist"),
    pytest.param(lambda: cmd_sl_inquire("ABCD", 0, "ALLROUTEWTTYPE1"), id="inquire-qty-cero"),
    pytest.param(lambda: cmd_sl_neworder("ABCD", 100, "LOC3", 2**31), id="API-5.18-token-fuera-int32"),
    pytest.param(lambda: cmd_sl_neworder("ABCD", 100, "LOC3", 1.0), id="token-float"),
    pytest.param(lambda: cmd_sl_offer(0, True), id="offer-id-cero"),
])
def test_cmd_rechazan_argumentos_invalidos(llamada):
    with pytest.raises(ValueError):
        llamada()


@pytest.mark.parametrize("nombre, arg, literal", [
    pytest.param("BP", None, "GET BP", id="L989-bp"),
    pytest.param("bp", None, "GET BP", id="L2037-minusculas"),
    pytest.param("SHORTINFO", "ABCD", "GET SHORTINFO ABCD", id="L1007-shortinfo"),
    pytest.param("LDLU", "ABCD", "GET LDLU ABCD", id="API-5.8-ldlu-con-simbolo"),
    pytest.param("LDLU", None, "GET LDLU", id="API-5.8-ldlu-sin-simbolo"),
    pytest.param("symstatus", "ABCD", "GET SymStatus ABCD", id="API-5.8-symstatus"),
    pytest.param("SymStatus", None, "GET SymStatus", id="API-5.8-symstatus-sin-simbolo"),
    pytest.param("AccountInfo", None, "GET AccountInfo", id="L1134-accountinfo"),
    pytest.param("POSITIONS", None, "GET POSITIONS", id="R-K-01-positions"),
    pytest.param("ORDERS", None, "GET ORDERS", id="R-K-01-orders"),
    pytest.param("TRADES", None, "GET TRADES", id="R-K-01-trades"),
    pytest.param("LOCATES", None, "GET LOCATES", id="R-K-01-locates"),
    pytest.param("RouteStatus", None, "GET RouteStatus", id="API-5.27-routestatus"),
    pytest.param("INTMSGS", None, "GET INTMSGS", id="L1611-intmsgs"),
    pytest.param("POSREFRESH", None, "POSREFRESH", id="R-J-02-posrefresh"),
    pytest.param("ECHO", None, "ECHO", id="L1460-echo"),
    pytest.param("echo", "on", "ECHO ON", id="L1461-echo-on"),
    pytest.param("ECHO", "OFF", "ECHO OFF", id="L1462-echo-off"),
    pytest.param("CLIENT", None, "CLIENT", id="L1466-client"),
])
def test_cmd_get_conjunto_cerrado(nombre, arg, literal):
    assert cmd_get(nombre, arg) == literal
    assert not es_mutante(literal)


@pytest.mark.parametrize("nombre, arg", [
    pytest.param("FOO", None, id="desconocido"),
    pytest.param("NEWORDER", None, id="R-O-03-mutante-por-get"),
    pytest.param("SHORTINFO", None, id="L1007-shortinfo-sin-simbolo"),
    pytest.param("BP", "ABCD", id="bp-con-argumento"),
    pytest.param("POSREFRESH", "X", id="posrefresh-con-argumento"),
    pytest.param("ECHO", "MAYBE", id="echo-argumento-raro"),
    pytest.param("ECHO", 1, id="echo-argumento-no-texto"),
    pytest.param("LDLU", "AB CD", id="simbolo-con-espacio"),
    pytest.param(None, None, id="nombre-none"),
])
def test_cmd_get_rechaza(nombre, arg):
    with pytest.raises(ValueError):
        cmd_get(nombre, arg)


# ══════════════════════════════════════════════════════════════════════
# es_mutante (R-O-03, riesgo 10)
# ══════════════════════════════════════════════════════════════════════
def _variantes(palabra: str) -> list[str]:
    return [palabra, palabra.lower(), palabra.capitalize(), "  " + palabra, "\t" + palabra.lower()]


@pytest.mark.parametrize("linea", [
    pytest.param(f"{v} 1 2 3", id=f"R-O-03-{p}-{i}") for p in sorted(MUTANTES) for i, v in enumerate(_variantes(p))
] + [
    pytest.param("SLPRICEINQUIRE ABCD 100 ALLROUTE", id="API-5.22-allroute"),
    pytest.param("slpriceinquire ABCD 100 allroute", id="API-5.22-allroute-minusculas"),
    pytest.param("GET BP\r\nNEWORDER 1 B ABCD ARCA 1 1", id="riesgo10-salto-crlf"),
    pytest.param("GET BP\nCANCEL ALL", id="riesgo10-salto-lf"),
    pytest.param("SB ABCD Lv1\rREPLACE 1 1 1", id="riesgo10-salto-cr"),
    pytest.param("GET BP\x0bCANCEL ALL", id="riesgo10-salto-vt"),
    pytest.param("CANCEL", id="palabra-sola"),
])
def test_es_mutante_verdadero(linea):
    assert es_mutante(linea) is True


@pytest.mark.parametrize("linea", [
    pytest.param(x, id=f"R-O-03-libre-{i}") for i, x in enumerate([
        "GET BP", "get positions", "SB ABCD Lv1", "UNSB ABCD Lv1", "LOGIN prueba c CUENTA_PRUEBA 0", "QUIT",
        "POSREFRESH", "ECHO", "CLIENT", "ReturnFullLv1 NO", "SLPRICEINQUIRE ABCD 100 ALLROUTEWTTYPE1",
        "SLPRICEINQUIRE ABCD 100 LOC3", "SLReuseQuery ABCD", "SLAvailQuery CUENTA_PRUEBA ABCD",
        "SLRouteMinCharge ALLROUTE", "", "   ", "\r\n", "NEWORDERS 1", "XCANCEL 1", "GET NEWORDER",
        "SB CANCEL Lv1",
    ])
])
def test_es_mutante_falso(linea):
    assert es_mutante(linea) is False


def test_es_mutante_exige_texto():
    with pytest.raises(TypeError):
        es_mutante(b"NEWORDER 1")  # type: ignore[arg-type]


def test_cmd_de_lectura_nunca_mutantes_y_de_escritura_siempre():
    """R-O-03: los `cmd_*` que el cliente deja pasar en sombra son exactamente los de lectura."""
    lectura = [cmd_login("prueba", "x", CUENTA, True), cmd_sb("ABCD"), cmd_unsb("ABCD"), cmd_return_full_lv1(False),
               cmd_sl_inquire("ABCD", 100, "ALLROUTEWTTYPE1"), cmd_sl_reuse("ABCD"), cmd_sl_avail(CUENTA, "ABCD"),
               cmd_sl_min_charge("ALLROUTE"), cmd_quit()]
    escritura = [cmd_cancel(1), cmd_cancel_all(), cmd_cancel_allsymb("ABCD"), cmd_neworder(_o()),
                 cmd_replace(1, 1, TipoOrden.LIMITE, D("1"), None), cmd_sl_neworder("ABCD", 100, "LOC3", 3),
                 cmd_sl_offer(1, True), cmd_sl_cancel(1), cmd_sl_inquire("ABCD", 100, "ALLROUTE")]
    assert not any(es_mutante(x) for x in lectura)
    assert all(es_mutante(x) for x in escritura)


# ══════════════════════════════════════════════════════════════════════
# formatear_precio (injerto A §8.1, API-5.28, riesgo 12)
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("precio, texto", [
    pytest.param(D("10.30"), "10.3", id="API-5.28-sin-ceros"),
    pytest.param(D("3.00"), "3", id="API-5.28-entero"),
    pytest.param(D("0.1234"), "0.1234", id="regla612-4-decimales"),
    pytest.param(D("0.1000"), "0.1", id="regla612-ceros-finales"),
    pytest.param(D("100"), "100", id="API-5.28-sin-notacion-100"),
    pytest.param(D("1E+2"), "100", id="API-5.28-exponente-de-entrada"),
    pytest.param(D("1.00"), "1", id="tick-frontera-1"),
    pytest.param(D("0.9999"), "0.9999", id="tick-frontera-0.9999"),
    pytest.param(D("0.0001"), "0.0001", id="tick-minimo"),
    pytest.param(D("12345.67"), "12345.67", id="precio-alto"),
    pytest.param(D("200.5"), "200.5", id="L546"),
])
def test_formatear_precio(precio, texto):
    assert formatear_precio(precio) == texto


@pytest.mark.parametrize("precio", [
    pytest.param(D("10.299999"), id="riesgo12-coma-flotante"),
    pytest.param(D("1.005"), id="regla612-medio-centimo"),
    pytest.param(D("0.12345"), id="regla612-5-decimales"),
    pytest.param(D("0"), id="cero"),
    pytest.param(D("-1"), id="negativo"),
    pytest.param(D("NaN"), id="nan"),
    pytest.param(D("Infinity"), id="infinito"),
    pytest.param(10.3, id="float"),
    pytest.param(10, id="int"),
    pytest.param("10.3", id="texto"),
    pytest.param(None, id="none"),
])
def test_formatear_precio_lanza_fuera_de_tick(precio):
    with pytest.raises(PrecioFueraDeTick):
        formatear_precio(precio)
    assert issubclass(PrecioFueraDeTick, ValueError)


def test_formatear_precio_nunca_notacion_cientifica():
    """API-5.28: recorrido amplio de precios al tick; nunca «E», nunca más de 4 decimales, y vuelve al mismo valor."""
    rnd = random.Random(612)
    precios = [D(rnd.randrange(1, 10_000)) * D("0.0001") for _ in range(500)]
    precios += [D(rnd.randrange(100, 10_000_000)) * D("0.01") for _ in range(500)]
    precios += [D("1E+3"), D("1.0E+4"), D("50000.00")]
    for p in precios:
        texto = formatear_precio(p)
        assert "E" not in texto and "e" not in texto
        assert D(texto) == p
        assert len(texto.partition(".")[2]) <= 4
        assert not (("." in texto) and texto.endswith("0"))


# ══════════════════════════════════════════════════════════════════════
# normalizar_pos (injerto A §8.8, riesgo 9)
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("tipo, qty, esperado", [
    pytest.param(3, 100, -100, id="riesgo9-corto-positivo"),
    pytest.param(3, -100, -100, id="riesgo9-corto-negativo"),
    pytest.param(3, 0, 0, id="corto-cero"),
    pytest.param(2, 100, 100, id="margen"),
    pytest.param(2, -100, 100, id="margen-signo-raro"),
    pytest.param(1, 50, 50, id="cash"),
    pytest.param(9, -7, -7, id="tipo-desconocido-tal-cual"),
])
@pytest.mark.parametrize("bandera", [None, True, False], ids=["bandera-None", "bandera-True", "bandera-False"])
def test_normalizar_pos(tipo, qty, esperado, bandera):
    """La normalización NO depende de `qty_corto_negativa` (solo se registra el primer día)."""
    assert normalizar_pos("ABCD", tipo, qty, bandera) == esperado


@pytest.mark.parametrize("tipo, qty", [("3", 100), (3, "100"), (True, 100), (3, 1.0), (3, None)])
def test_normalizar_pos_rechaza_no_enteros(tipo, qty):
    with pytest.raises(ValueError):
        normalizar_pos("ABCD", tipo, qty, None)


# ══════════════════════════════════════════════════════════════════════
# redactar (R-Q-01, riesgo 20)
# ══════════════════════════════════════════════════════════════════════
_TOKEN_TG_FALSO = "987654321:" + "A" * 20 + "b_c-" * 4        # inventado: forma de token, ningún valor real


@pytest.mark.parametrize("linea, esperado", [
    pytest.param("LOGIN prueba s3cr3ta CUENTA_PRUEBA 0", "LOGIN prueba ***** CUENTA_PRUEBA 0", id="R-Q-01-login"),
    pytest.param("login prueba s3cr3ta CUENTA_PRUEBA 1", "login prueba ***** CUENTA_PRUEBA 1", id="R-Q-01-minusculas"),
    pytest.param("  LOGIN prueba s3cr3ta CUENTA_PRUEBA 0\r\n", "  LOGIN prueba ***** CUENTA_PRUEBA 0\r\n",
                 id="R-Q-01-espacios-y-fin"),
    pytest.param("enviado: LOGIN prueba s3cr3ta CUENTA_PRUEBA 0", "enviado: LOGIN prueba ***** CUENTA_PRUEBA 0",
                 id="R-Q-01-en-mitad"),
    pytest.param("GET BP", "GET BP", id="sin-secretos-intacta"),
    pytest.param("%OrderAct 1 Send_Rej Buy ABCD 1 2 SMAT 09:00:00 Logon:Failed 5",
                 "%OrderAct 1 Send_Rej Buy ABCD 1 2 SMAT 09:00:00 Logon:Failed 5", id="logon-no-es-login"),
    pytest.param("#OrderServer:Logon:Successful", "#OrderServer:Logon:Successful", id="conexion-intacta"),
    # A-03: el LOGIN pegado a comillas, paréntesis, corchetes o «=» también se tapa
    pytest.param("'LOGIN prueba s3cr3ta CUENTA_PRUEBA 0'", "'LOGIN prueba ***** CUENTA_PRUEBA 0'", id="A-03-repr"),
    pytest.param('"LOGIN prueba s3cr3ta CUENTA_PRUEBA 0"', '"LOGIN prueba ***** CUENTA_PRUEBA 0"', id="A-03-json"),
    pytest.param("cmd=LOGIN prueba s3cr3ta CUENTA_PRUEBA 0", "cmd=LOGIN prueba ***** CUENTA_PRUEBA 0",
                 id="A-03-igual"),
    pytest.param("(LOGIN prueba s3cr3ta CUENTA_PRUEBA 0)", "(LOGIN prueba ***** CUENTA_PRUEBA 0)",
                 id="A-03-parentesis"),
    pytest.param("[LOGIN prueba s3cr3ta CUENTA_PRUEBA 0]", "[LOGIN prueba ***** CUENTA_PRUEBA 0]",
                 id="A-03-corchete"),
    pytest.param("b'LOGIN prueba s3cr3ta CUENTA_PRUEBA 0\\r\\n'", "b'LOGIN prueba ***** CUENTA_PRUEBA 0\\r\\n'",
                 id="A-03-str-bytes"),
    pytest.param("('LOGIN prueba s3cr3ta')", "('LOGIN prueba *****", id="A-03-clave-al-final-pegada-a-comilla"),
    pytest.param("cmd_LOGIN prueba s3cr3ta CUENTA_PRUEBA 0", "cmd_LOGIN prueba ***** CUENTA_PRUEBA 0",
                 id="A-03-guion-bajo"),
    pytest.param("relogin prueba nada", "relogin prueba nada", id="A-03-letra-delante-no-es-login"),
])
def test_redactar_login(linea, esperado):
    """R-Q-01 y A-03: ninguna representación del LOGIN deja la clave en claro."""
    assert redactar(linea) == esperado
    assert "s3cr3ta" not in redactar(linea)


def test_A_03_redactar_repr_de_bytes_del_login_real():
    """A-03: `str(bytes)` y `repr` de la línea que sale por el socket no llevan la clave."""
    login = cmd_login("prueba", "s3cr3ta", CUENTA, False)
    for texto in (repr(login), str((login + "\r\n").encode("latin-1")), f"{login!r}", str({"cmd": login})):
        assert "s3cr3ta" not in redactar(texto), texto


@pytest.mark.parametrize("texto", [
    pytest.param(repr('QUIT\r\nLOGIN u secreta acc 0'), id="verificador-repr-tras-quit"),
    pytest.param(str(b'X\r\nLOGIN u secreta acc 0\r\n'), id="verificador-str-bytes"),
    pytest.param(repr('\tLOGIN u secreta acc 0'), id="verificador-repr-tab"),
    pytest.param("LOGIN u secreta acc 0", id="linea-suelta"),
    pytest.param("\r\nlogin u secreta acc 0", id="saltos-reales-minusculas"),
    pytest.param(r"X\nLogin u secreta acc 0", id="escape-n-mixto"),
    pytest.param(r"X\RLOGIN u secreta acc 0", id="escape-R-mayuscula"),
    pytest.param(r"\t\tLOGIN u secreta acc 0", id="dos-tabs-literales"),
    pytest.param(repr(["QUIT", "LOGIN u secreta acc 0"]), id="repr-lista"),
    pytest.param(repr(("LOGIN u secreta acc 0",)), id="repr-tupla-parentesis"),
    pytest.param("cmd=LOGIN u secreta acc 0", id="igual"),
    pytest.param("enviado:   LOGIN\tu\tsecreta acc 0", id="espacios-y-tabs-reales"),
    pytest.param(str(("QUIT\r\nLOGIN u secreta acc 0").encode("latin-1")), id="str-bytes-tras-quit"),
])
def test_R2_RED_1_redactar_login_tras_escapes_literales(texto):
    """R2-RED-1: el LOGIN precedido de «\\r», «\\n», «\\t» literales (barra + letra),
    comillas, corchetes, paréntesis, «=» o blancos, en cualquier caja, pierde la
    clave; usuario y cuenta se conservan."""
    tapado = redactar(texto)
    assert "secreta" not in tapado, tapado
    assert "u ***** acc 0" in tapado or "u\t***** acc 0" in tapado, tapado


def test_R2_RED_1_letra_real_delante_no_es_login():
    """R2-RED-1: una letra o cifra REAL delante descarta el LOGIN; la barra + r/n/t no."""
    assert redactar("relogin u nada acc 0") == "relogin u nada acc 0"
    assert redactar("xLOGIN u nada acc 0") == "xLOGIN u nada acc 0"
    assert redactar("9login u nada acc 0") == "9login u nada acc 0"
    assert redactar(r"\nLOGIN u nada acc 0") == r"\nLOGIN u ***** acc 0"


@pytest.mark.parametrize("usuario, clave, cuenta", [
    pytest.param("u", "mi s3cr3ta", "ACC", id="clave-con-espacio"),
    pytest.param("u", " s3cr3ta", "ACC", id="clave-con-espacio-delante"),
    pytest.param("u", "s3cr3ta\n", "ACC", id="clave-con-salto"),
    pytest.param("u s3cr3ta", "x", "ACC", id="usuario-con-espacio"),
    pytest.param("u", "x", "AC s3cr3ta", id="cuenta-con-espacio"),
])
def test_A_05_SEG_03_cmd_login_no_pone_el_valor_en_el_error(usuario, clave, cuenta):
    """A-05 / SEG-03 (R-Q-01): el ValueError de cmd_login nombra el campo, nunca su valor."""
    with pytest.raises(ValueError) as exc:
        cmd_login(usuario, clave, cuenta, False)
    assert "s3cr3ta" not in str(exc.value)
    assert "valor oculto" in str(exc.value)


def test_A_05_cmd_login_con_bytes_no_muestra_el_valor():
    with pytest.raises(ValueError) as exc:
        cmd_login("u", b"s3cr3ta", "ACC", False)          # type: ignore[arg-type]
    assert "s3cr3ta" not in str(exc.value)


def test_A_05_otros_campos_siguen_mostrando_el_valor():
    """Solo los campos del LOGIN se ocultan: un ticker inválido se sigue viendo en el error (depuración)."""
    with pytest.raises(ValueError, match="AB CD"):
        cmd_sb("AB CD")


@pytest.mark.parametrize("linea", [
    pytest.param(f"https://api.telegram.org/bot{_TOKEN_TG_FALSO}/sendMessage", id="riesgo20-url"),
    pytest.param(f"token={_TOKEN_TG_FALSO}", id="riesgo20-suelto"),
    pytest.param(f"BOT{_TOKEN_TG_FALSO} y otra vez bot{_TOKEN_TG_FALSO}", id="riesgo20-dos-veces"),
])
def test_redactar_token_telegram(linea):
    resultado = redactar(linea)
    assert _TOKEN_TG_FALSO not in resultado
    assert _TOKEN_TG_FALSO.split(":")[1] not in resultado


def test_redactar_no_toca_horas_ni_lanza():
    assert redactar("%TRADE 1 ABCD B 100 2.4 SMAT 09:50:01 7") == "%TRADE 1 ABCD B 100 2.4 SMAT 09:50:01 7"
    assert redactar(12345) == "12345"          # type: ignore[arg-type]
    assert redactar(None) == "None"            # type: ignore[arg-type]
