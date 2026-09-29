"""Tests de app.bot_das.comandos (§10 fila test_das_comandos; R-M-04, R-M-06 gancho, R-Q-01, R-M-01 detalle).

Sin red real: Telegram se simula con un http.server local en un hilo.
El token de los tests es INVENTADO (no es de ninguna cuenta).
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import urllib.parse
from datetime import date
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.bot_das import comandos as C
from app.bot_das.comandos import (
    CON_SI,
    CONSULTA,
    DOS_PASOS,
    Confirmaciones,
    LectorComandosFichero,
    ReceptorTelegram,
    parsear,
    respuesta_previa,
    responder_consulta,
)
from app.bot_das.tipos import (
    Comando,
    Config,
    Cotizacion,
    Cuenta,
    EstadoBot,
    EstadoLote,
    EstadoOrden,
    EstadoTicker,
    EstrategiaConfig,
    Fase,
    Fill,
    Lado,
    Locate,
    Lote,
    MsgOrden,
    Orden,
    Origen,
    PosicionTicker,
    Proposito,
    TipoOrden,
)

TOKEN_FALSO = "123456789:TOKEN_de_PRUEBA-inventado"
JAUME = 111
SOCIO = -222          # los grupos de Telegram tienen chat_id negativo
EXTRANO = 999
AUTORIZADOS = frozenset({JAUME, SOCIO})


# ═══════════════════════════ parsear ═══════════════════════════════════
def test_conjuntos_son_los_de_3_10():
    assert CONSULTA == {"estado", "posiciones", "ordenes", "locates", "estrategias", "detalle", "salud", "log"}
    assert CON_SI == {"cerrar_todo", "cerrar", "cancelar_ordenes", "stop"}
    assert len(DOS_PASOS) == 15 and not (DOS_PASOS & CONSULTA) and not (DOS_PASOS & CON_SI)
    assert set(C.USO) == CONSULTA | DOS_PASOS | CON_SI | {"confirmar"}


@pytest.mark.parametrize("chat_id", [EXTRANO, 0, True, "111", None], ids=["R-Q-01-extrano", "R-Q-01-cero",
                                                                          "R-Q-01-bool", "R-Q-01-str", "R-Q-01-none"])
def test_chat_no_autorizado_devuelve_none_y_registra_sin_texto(chat_id, caplog):
    caplog.set_level(logging.WARNING, logger="btt.bot_das.comandos")
    assert parsear("/cerrar_todo SI secreto-del-mensaje", chat_id, AUTORIZADOS) is None
    assert "no autorizado" in caplog.text
    assert "secreto-del-mensaje" not in caplog.text and "cerrar_todo" not in caplog.text


def test_autorizados_vacio_es_nadie():
    assert parsear("/estado", JAUME, frozenset()) is None


@pytest.mark.parametrize("texto", ["hola bot, ¿qué tal?", "cierra ABC", "", "   ", "estado"],
                         ids=["R-M-06-libre", "R-M-06-accion-libre", "R-M-06-vacio", "R-M-06-blancos", "R-M-06-sin-barra"])
def test_texto_libre_es_none_gancho_r_m_06(texto):
    assert parsear(texto, JAUME, AUTORIZADOS) is None


@pytest.mark.parametrize("texto,nombre,args,requiere", [
    ("/estado", "estado", [], "nada"),
    ("  /ESTADO  ", "estado", [], "nada"),
    ("/estado@MiBotDePrueba", "estado", [], "nada"),
    ("/posiciones", "posiciones", [], "nada"),
    ("/ordenes", "ordenes", [], "nada"),
    ("/locates", "locates", [], "nada"),
    ("/estrategias", "estrategias", [], "nada"),
    ("/detalle 100500001", "detalle", ["100500001"], "nada"),
    ("/salud", "salud", [], "nada"),
    ("/log", "log", [], "nada"),
    ("/log 5", "log", ["5"], "nada"),
    ("/pausar", "pausar", [], "confirmacion"),
    ("/pausar abc", "pausar", ["ABC"], "confirmacion"),          # Jaume 29-sep: pausa por ticker
    ("/sigue abc", "sigue", ["ABC"], "confirmacion"),
    ("/reanudar", "reanudar", [], "confirmacion"),
    ("/reanudar abc", "reanudar", ["ABC"], "confirmacion"),
    ("/sigue", "sigue", [], "confirmacion"),
    ("/modo_seguridad ON", "modo_seguridad", ["on"], "confirmacion"),
    ("/desactivar prueba-1", "desactivar", ["prueba-1"], "confirmacion"),
    ("/activar prueba-1", "activar", ["prueba-1"], "confirmacion"),
    ("/apagar", "apagar", [], "confirmacion"),
    ("/encender", "encender", [], "confirmacion"),
    ("/reanudar_ticker abc", "reanudar_ticker", ["ABC"], "confirmacion"),
    ("/control_humano", "control_humano", [], "confirmacion"),
    ("/esperar_fin_dia prueba-1", "esperar_fin_dia", ["prueba-1"], "confirmacion"),
    ("/cerrar_todo SI", "cerrar_todo", [], "si"),
    ("/cerrar abc SI", "cerrar", ["ABC"], "si"),
    ("/cerrar abc 300 sí", "cerrar", ["ABC", "300"], "si"),
    ("/cancelar_ordenes ABC Si", "cancelar_ordenes", ["ABC"], "si"),
    ("/stop ABC 2,35 SI", "stop", ["ABC", "2.35"], "si"),
    ("/stop ABC 0.5123 SI", "stop", ["ABC", "0.5123"], "si"),
    ("/cerrar_todo", "cerrar_todo", [], "si_faltante"),
    ("/cerrar ABC", "cerrar", ["ABC"], "si_faltante"),
    ("/stop ABC 2.35", "stop", ["ABC", "2.35"], "si_faltante"),
    ("/confirmar 1234", "confirmar", ["1234"], "confirmar"),
], ids=lambda v: v if isinstance(v, str) else None)
def test_parsear_r_m_04(texto, nombre, args, requiere):
    c = parsear(texto, JAUME, AUTORIZADOS, id_comando="tg:7")
    assert c is not None
    assert (c.nombre, c.args, c.requiere, c.chat_id, c.id) == (nombre, args, requiere, JAUME, "tg:7")
    assert c.texto == texto.strip()


@pytest.mark.parametrize("texto", [
    "/cerrar SI",                 # sin ticker: jamás una acción de mercado a medio escribir
    "/cerrar SI ABC",             # SI no es la última palabra
    "/cerrar ABC 0 SI",
    "/cerrar ABC -5 SI",
    "/cerrar ABC mucho SI",
    "/cerrar 123 SI",
    "/cancelar_ordenes SI",
    "/stop ABC SI",
    "/stop ABC 2.355 SI",         # fuera del tick (regla 612)
    "/stop ABC 0 SI",
    "/stop ABC NaN SI",
    "/stop ABC inf SI",
    "/cerrar_todo YA SI",
    "/estado ahora",
    "/log 0",
    "/log 51",
    "/log diez",
    "/detalle",
    "/modo_seguridad",
    "/modo_seguridad quizas",
    "/pausar SI",
    "/pausar ABC DEF",
    "/reanudar_ticker",
    "/desactivar",
    "/confirmar",
    "/confirmar 12345",
    "/confirmar abcd",
], ids=lambda t: "R-M-04 " + t)
def test_args_invalidos(texto):
    c = parsear(texto, JAUME, AUTORIZADOS)
    assert c is not None and c.requiere == "args_invalidos"
    assert "Uso:" in respuesta_previa(c)


def test_desconocido_y_su_respuesta():
    c = parsear("/borrar_cuenta", JAUME, AUTORIZADOS)
    assert c.requiere == "desconocido"
    r = respuesta_previa(c)
    assert "desconocido" in r and "/estado" in r and "/cerrar_todo" in r


@pytest.mark.parametrize("texto,ejemplo", [
    ("/cerrar_todo", "/cerrar_todo SI"),
    ("/cerrar abc 10", "/cerrar ABC 10 SI"),
    ("/stop ABC 2.35", "/stop ABC 2.35 SI"),
], ids=["R-M-04-si-cerrar_todo", "R-M-04-si-cerrar", "R-M-04-si-stop"])
def test_si_obligatorio_respuesta(texto, ejemplo):
    c = parsear(texto, JAUME, AUTORIZADOS)
    assert c.requiere == "si_faltante" and c.requiere not in C.EJECUTABLES
    assert ejemplo in respuesta_previa(c)


def test_respuesta_previa_none_si_ejecutable_o_pendiente():
    for texto in ("/estado", "/pausar", "/cerrar_todo SI", "/confirmar 1234"):
        assert respuesta_previa(parsear(texto, JAUME, AUTORIZADOS)) is None


def test_respuesta_previa_escapa_html():
    c = parsear("/<b>&", JAUME, AUTORIZADOS)
    assert "<b>" not in respuesta_previa(c) and "&lt;b&gt;&amp;" in respuesta_previa(c)


# ═══════════════════════════ Confirmaciones ════════════════════════════
@pytest.fixture
def conf(reloj):
    return Confirmaciones(reloj, ttl_s=60.0)


def _id_de(texto: str) -> str:
    return texto.split("/confirmar ")[1].split()[0]


def test_dos_pasos_confirma_una_sola_vez(conf):
    c = parsear("/pausar", JAUME, AUTORIZADOS, id_comando="tg:1")
    texto = conf.pedir(c)
    assert "Confirma con /confirmar " in texto and "/pausar" in texto
    ident = _id_de(texto)
    assert len(ident) == 4 and ident.isdigit() and ident[0] != "0"
    hecho = conf.confirmar(JAUME, f"/confirmar {ident}")
    assert hecho is not None and hecho.requiere == "confirmado" and hecho.nombre == "pausar" and hecho.id == "tg:1"
    assert conf.confirmar(JAUME, f"/confirmar {ident}") is None       # un solo uso
    assert conf.pendientes == 0


def test_dos_pasos_otro_chat_no_consume(conf):
    ident = _id_de(conf.pedir(parsear("/apagar", JAUME, AUTORIZADOS)))
    assert conf.confirmar(SOCIO, f"/confirmar {ident}") is None
    assert conf.confirmar(EXTRANO, ident) is None
    assert conf.confirmar(JAUME, ident).nombre == "apagar"          # el dueño aún puede


def test_dos_pasos_caduca(conf, reloj):
    ident = _id_de(conf.pedir(parsear("/sigue", JAUME, AUTORIZADOS)))
    reloj.avanzar(59.9)
    assert conf.pendientes == 1
    reloj.avanzar(0.2)
    assert conf.confirmar(JAUME, f"/confirmar {ident}") is None
    assert conf.pendientes == 0


@pytest.mark.parametrize("texto", ["/confirmar", "/confirmar 12", "/otra 1234", "confirmar 1234", "/confirmar 1234 5",
                                   "", "12345"], ids=lambda t: "R-M-04 " + repr(t))
def test_confirmar_texto_mal_formado(conf, texto):
    conf.pedir(parsear("/pausar", JAUME, AUTORIZADOS))
    assert conf.confirmar(JAUME, texto) is None
    assert conf.pendientes == 1


def test_confirmar_con_sufijo_bot(conf):
    ident = _id_de(conf.pedir(parsear("/pausar", JAUME, AUTORIZADOS)))
    assert conf.confirmar(JAUME, f"/confirmar@MiBot {ident}") is not None


def test_ids_distintos_y_ttl_invalido(conf, reloj):
    ids = {_id_de(conf.pedir(parsear("/pausar", JAUME, AUTORIZADOS))) for _ in range(300)}
    assert len(ids) == 300
    with pytest.raises(ValueError):
        Confirmaciones(reloj, ttl_s=0)


# ═══════════════════════════ responder_consulta ════════════════════════
def _estrategia(sid: str, nombre: str, ejecutar: bool = True) -> EstrategiaConfig:
    return EstrategiaConfig(
        strategy_id=sid, name=nombre, origen="portfolio", ejecutar=ejecutar, avisar_grupo_a=True,
        riesgo_usd=Decimal("300"), riesgos_piramide=[], riesgo_piramide_usd=None, ev_pct=Decimal("4"),
        ev_rangos=[], excluir_ipo=False, al_desactivar="esperar_fin_dia", hora_fin_sesion="11:30",
        ventana_entradas=[{"from_time": "04:00", "to_time": "09:29"}], hora_salida=None, accept_reentries=True,
        max_reentries=-1, niveles_piramide=[], es_rth=False, definition_hash="sha256:" + "0" * 64, definition={})


def _cfg(estrategias=None, pausar=False) -> Config:
    estrategias = {"prueba-1": _estrategia("prueba-1", "PM <A> & prueba")} if estrategias is None else estrategias
    return Config(
        schema_version=1, config_version=7, sha256="x", motor_hash="m", estrategias_hash="e", generado_at="g",
        fase=Fase.SOMBRA, vigilando=True, horario={}, modo_seguridad={"activo": False}, lista_negra=[],
        pausar_entradas=pausar, locates={"tope_gasto_pct_cuenta": 3.0}, entrada={}, salidas={}, stops={}, halts={},
        exclusiones={}, rutas={}, tecnicos={}, alertas_grupo_a={"activo": False}, estrategias=estrategias,
        cuenta_das="CUENTA_PRUEBA")


class MercadoFalso:
    def __init__(self, cotizaciones=None, foto=None, falla=False):
        self._cot = cotizaciones or {}
        self._foto = foto if foto is not None else {"suscritos": 2, "max_lv1": 100, "halts": {"XYZ": {}}}
        self._falla = falla

    def cotizacion(self, ticker):
        if self._falla:
            raise RuntimeError("mercado roto")
        return self._cot.get(ticker)

    def foto(self):
        if self._falla:
            raise RuntimeError("mercado roto")
        return self._foto


def _orden(token, proposito, qty=100, precio=None, stop=None, estado=EstadoOrden.ACCEPTED, id_das=None,
           tipo=TipoOrden.STOP_LIMITE_PP, lado=Lado.COMPRA, lote_id="L1", ticker="ABC"):
    return Orden(token=token, ticker=ticker, lado=lado, tipo=tipo, qty=qty, precio=precio, stop=stop, ruta="STOP",
                 proposito=proposito, lote_id=lote_id, nivel=Decimal("2.10"), origen=Origen.EJECUTOR, id_das=id_das,
                 estado=estado, enviada_en=990.0)


@pytest.fixture
def estado_ejemplo(reloj) -> EstadoBot:
    """ABC corto 100 a 2,00 con principal, emergencia y TP vivos; DEF pausado; una orden ajena; un locate."""
    e = EstadoBot(fase=Fase.SOMBRA, dia=date(2026, 9, 25), das_conectado=True,
                  das_logon={"OrderServer": True, "QuoteServer": None})
    lote = Lote(id="L1", strategy_id="prueba-1", estrategia="PM <A> & prueba", ticker="ABC", direccion="short",
                pedidas=100, llenas=100, precio_medio=Decimal("2.00"), nivel_stop=Decimal("2.10"),
                riesgo_usd=Decimal("300"), estado=EstadoLote.ABIERTO)
    abc = PosicionTicker(ticker="ABC", lotes={"L1": lote}, neta_fills=-100, neta_das=-100)
    defp = PosicionTicker(ticker="DEF", estado=EstadoTicker.PAUSADO, motivo_estado="rechazo <desconocido>")
    e.posiciones = {"ABC": abc, "DEF": defp}
    e.ordenes = {
        100500001: _orden(100500001, Proposito.ENTRADA_AGREGAR, precio=Decimal("2.00"), estado=EstadoOrden.EXECUTED,
                          tipo=TipoOrden.LIMITE, lado=Lado.CORTO, id_das=41),
        100500002: _orden(100500002, Proposito.STOP_PRINCIPAL, stop=Decimal("2.10"), precio=Decimal("2.17"), id_das=42),
        100500003: _orden(100500003, Proposito.STOP_EMERGENCIA, stop=Decimal("2.38"), precio=Decimal("3.43"), id_das=43),
        100500004: _orden(100500004, Proposito.TP_AGREGAR, qty=50, precio=Decimal("1.88"), tipo=TipoOrden.LIMITE,
                          id_das=44),
    }
    e.id_a_token = {41: 100500001, 42: 100500002, 43: 100500003, 44: 100500004}
    e.fills = {100500001: [Fill(id_trade=9, token=100500001, id_orden=41, ticker="ABC", lado="SS", qty=100,
                                precio=Decimal("2.00"), ruta="SAGEREB", hora="09:31:02", liq=None, ecn_fee=None)]}
    e.ordenes_ajenas = {777: MsgOrden(cruda="%ORDER ...", id=77, token=777, ticker="GHI", lado="B", tipo="Limit",
                                      qty=10, lvqty=10, cxlqty=0, precio=Decimal("5.00"), ruta="SMAT",
                                      estado=EstadoOrden.ACCEPTED, hora="09:40:00", origoid=0, cuenta="C", trader="T",
                                      order_src="Manual", tif=None, pref=None, watch=False)}
    e.locates = {("ABC", "prueba-1"): Locate(ticker="ABC", strategy_id="prueba-1", pedidas=100, localizadas=100,
                                             precio_accion=Decimal("0.02"), coste=Decimal("2.00"), usadas=100,
                                             estado="comprado")}
    e.gasto_locates_dia = Decimal("2.00")
    e.cuenta = Cuenta(bp=Decimal("40000"), equity=Decimal("10000"), leida_en=995.0)
    e.reconciliacion_ok_en = 998.0
    e.feed_ultima_vela_en = 970.0
    e.ultimo_fill_en = 991.0
    return e


@pytest.fixture
def mercado() -> MercadoFalso:
    return MercadoFalso({"ABC": Cotizacion(ticker="ABC", bid=Decimal("1.89"), ask=Decimal("1.90"),
                                           last=Decimal("1.895"))})


def _c(texto: str) -> Comando:
    return parsear(texto, JAUME, AUTORIZADOS)


def test_consulta_estado(estado_ejemplo, mercado):
    r = responder_consulta(_c("/estado"), estado_ejemplo, _cfg(), mercado, 1000.0)
    assert "SOMBRA" in r and "EN MARCHA" in r and "DAS: conectado" in r
    assert "PM &lt;A&gt; &amp; prueba ×1" in r                   # posiciones por estrategia, escapado
    assert "PnL del día (fills, sin comisiones): 10.00 $" in r   # 200 cobrados − 100 × 1,90 al ask
    assert "DEF: pausado (rechazo &lt;desconocido&gt;)" in r and "órdenes ajenas en DAS: 1" in r
    assert "hace 2.0 s" in r


@pytest.mark.parametrize("cambio,esperado", [
    ({"vigilando": False}, "APAGADO"), ({"control_humano": True}, "CONTROL HUMANO"),
    ({"pausa_global": True}, "PAUSADO"),
], ids=["R-M-04-apagado", "R-M-04-control-humano", "R-M-04-pausado"])
def test_consulta_estado_marcha(estado_ejemplo, mercado, cambio, esperado):
    for k, v in cambio.items():
        setattr(estado_ejemplo, k, v)
    assert esperado in responder_consulta(_c("/estado"), estado_ejemplo, _cfg(), mercado, 1000.0)


def test_consulta_estado_lista_pausas_por_ticker_y_humano(estado_ejemplo, mercado):
    """Jaume 29-sep: /estado dice qué tickers están pausados con /pausar X y cuáles en manos del humano (R-M-03)."""
    pos = next(iter(estado_ejemplo.posiciones.values()))
    pos.pausado_por_humano = True
    pos.intervencion_humana = True
    r = responder_consulta(_c("/estado"), estado_ejemplo, _cfg(), mercado, 1000.0)
    assert f"Tickers pausados (/sigue TICKER): {pos.ticker}" in r
    assert f"En manos del humano (/sigue TICKER): {pos.ticker}" in r
    assert "EN MARCHA" in r                                   # la pausa de un ticker no pausa el bot


def test_consulta_estado_sin_cotizacion_no_inventa(estado_ejemplo):
    r = responder_consulta(_c("/estado"), estado_ejemplo, _cfg(), None, 1000.0)
    assert "sin cotización: ABC" in r


def test_consulta_posiciones(estado_ejemplo, mercado):
    r = responder_consulta(_c("/posiciones"), estado_ejemplo, _cfg(), mercado, 1000.0)
    assert "ABC · neta -100 (DAS -100)" in r and "bid 1.89 ask 1.90" in r
    assert "stop_principal 2.10/2.17" in r and "stop_emergencia 2.38/3.43" in r
    assert "TP 1.88 ×50" in r and "latente 10.00 $" in r and "100/100 a 2.00" in r
    assert "DEF" not in r                                         # sin neta ni lotes: no es posición


def test_consulta_posiciones_sin_stop_se_ve(estado_ejemplo, mercado):
    for t in (100500002, 100500003):
        estado_ejemplo.ordenes[t].estado = EstadoOrden.CANCELED
    r = responder_consulta(_c("/posiciones"), estado_ejemplo, _cfg(), mercado, 1000.0)
    assert "nivel 2.10 SIN ORDEN" in r


def test_consulta_posiciones_vacio(reloj):
    e = EstadoBot(fase=Fase.REAL, dia=reloj.hoy())
    assert "Sin posiciones" in responder_consulta(_c("/posiciones"), e, _cfg(), None, 1000.0)


def test_consulta_ordenes(estado_ejemplo):
    r = responder_consulta(_c("/ordenes"), estado_ejemplo, _cfg(), None, 1000.0)
    assert "100500001" not in r                                   # ejecutada: no está viva
    assert "ABC B STOPLMTP 0/100 @ 2.10→2.17 · stop_principal · Accepted · token 100500002 · id 42" in r
    assert "AJENA GHI B Limit 10 @ 5.00" in r and "hace 10.0 s" in r


def test_consulta_locates(estado_ejemplo):
    r = responder_consulta(_c("/locates"), estado_ejemplo, _cfg(), None, 1000.0)
    assert "ABC · prueba-1 · 100/100 a 0.02 $/acc · coste 2.00 $ · usadas 100" in r
    assert "Gasto: 2.00 $ de 300.00 $ (3.0 % de 10 000.00 $)" in r


def test_consulta_locates_sin_equity(reloj):
    e = EstadoBot(fase=Fase.SOMBRA, dia=reloj.hoy(), locates_deshabilitados=True)
    r = responder_consulta(_c("/locates"), e, _cfg(), None, 1000.0)
    assert "Ninguno" in r and "falta equity" in r and "DESHABILITADOS" in r


def test_consulta_estrategias(estado_ejemplo):
    cfg = _cfg({"prueba-1": _estrategia("prueba-1", "PM <A> & prueba"), "otra": _estrategia("otra", "B", False)},
               pausar=True)
    r = responder_consulta(_c("/estrategias"), estado_ejemplo, cfg, None, 1000.0)
    assert "config v7" in r and "Entradas PAUSADAS" in r
    assert "PM &lt;A&gt; &amp; prueba (prueba-1) · OPERA · avisa A · ventana 04:00-09:29 · fin 11:30 · riesgo 300.00 $" in r
    assert "B (otra) · no opera" in r
    assert "Ninguna" in responder_consulta(_c("/estrategias"), estado_ejemplo, _cfg({}), None, 1000.0)


@pytest.mark.parametrize("ident,esperado", [
    ("100500002", "Orden 100500002"),        # por token
    ("42", "Orden 100500002"),               # por id de DAS
    ("L1", "Lote L1"),
    ("abc", "Ticker ABC"),
    ("prueba-1", "Estrategia PM &lt;A&gt; &amp; prueba"),
    ("nada<x>", "No encuentro «nada&lt;x&gt;»"),
], ids=["R-M-01-token", "R-M-01-id-das", "R-M-01-lote", "R-M-01-ticker", "R-M-01-estrategia", "R-M-01-no-existe"])
def test_consulta_detalle(estado_ejemplo, mercado, ident, esperado):
    r = responder_consulta(_c(f"/detalle {ident}"), estado_ejemplo, _cfg(), mercado, 1000.0)
    assert esperado in r


def test_consulta_detalle_ticker_pnl(estado_ejemplo, mercado):
    r = responder_consulta(_c("/detalle ABC"), estado_ejemplo, _cfg(), mercado, 1000.0)
    assert "neta -100" in r and "PnL del día: 10.00 $" in r and "órdenes vivas 3" in r


def test_consulta_salud(estado_ejemplo, mercado):
    r = responder_consulta(_c("/salud"), estado_ejemplo, _cfg(), mercado, 1000.0)
    assert "OrderServer: OK" in r and "QuoteServer: ?" in r
    assert "Feed (última vela): hace 30.0 s" in r and "Último fill: hace 9.0 s" in r
    assert "Mercado DAS: 2 suscritos de 100 · halts 1" in r and "Modo degradado: no" in r


def test_consulta_con_mercado_roto_no_lanza(estado_ejemplo):
    roto = MercadoFalso(falla=True)
    assert "sin foto" in responder_consulta(_c("/salud"), estado_ejemplo, _cfg(), roto, 1000.0)
    assert "sin cotización: ABC" in responder_consulta(_c("/estado"), estado_ejemplo, _cfg(), roto, 1000.0)


def test_consulta_log(estado_ejemplo):
    lineas = [f"linea {i} <x>" for i in range(30)]
    r = responder_consulta(_c("/log 3"), estado_ejemplo, _cfg(), None, 1000.0, lineas_log=lineas)
    assert "últimas 3" in r and "linea 29 &lt;x&gt;" in r and "linea 26" not in r
    r = responder_consulta(_c("/log"), estado_ejemplo, _cfg(), None, 1000.0, lineas_log=lineas)
    assert "últimas 20" in r
    assert responder_consulta(_c("/log"), estado_ejemplo, _cfg(), None, 1000.0) == "Log no disponible"


def test_cada_consulta_responde_y_es_pura(estado_ejemplo, mercado):
    import copy
    antes = copy.deepcopy(estado_ejemplo)
    for nombre in sorted(CONSULTA):
        texto = "/detalle ABC" if nombre == "detalle" else f"/{nombre}"
        r = responder_consulta(_c(texto), estado_ejemplo, _cfg(), mercado, 1000.0, lineas_log=["x"])
        assert isinstance(r, str) and r
    assert estado_ejemplo == antes


def test_consulta_rechaza_no_consulta(estado_ejemplo):
    with pytest.raises(ValueError):
        responder_consulta(_c("/pausar"), estado_ejemplo, _cfg(), None, 1000.0)


def test_consulta_recorta_filas(reloj):
    e = EstadoBot(fase=Fase.SOMBRA, dia=reloj.hoy())
    e.ordenes = {t: _orden(t, Proposito.STOP_PRINCIPAL, stop=Decimal("2.10"), precio=Decimal("2.17"))
                 for t in range(100500001, 100500101)}
    r = responder_consulta(_c("/ordenes"), e, _cfg(), None, 1000.0)
    assert "… y " in r and len(r.splitlines()) == C.FILAS_MAX + 1


# ═══════════════════════════ Telegram local ════════════════════════════
class _ServidorTelegram:
    """http.server local que imita getUpdates: devuelve las respuestas encoladas y luego vacío."""

    def __init__(self):
        self.peticiones: list[str] = []
        self.respuestas: list[tuple[int, dict]] = []
        servidor = self

        class Manejador(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                servidor.peticiones.append(self.path)
                codigo, cuerpo = servidor.respuestas.pop(0) if servidor.respuestas else (200, {"ok": True, "result": []})
                datos = json.dumps(cuerpo).encode()
                self.send_response(codigo)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(datos)))
                self.end_headers()
                self.wfile.write(datos)

            def log_message(self, *args):
                pass

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
        self.url = f"http://127.0.0.1:{self.http.server_address[1]}"
        self.hilo = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.hilo.start()

    def cerrar(self):
        self.http.shutdown()
        self.http.server_close()


@pytest.fixture
def servidor_tg():
    s = _ServidorTelegram()
    try:
        yield s
    finally:
        s.cerrar()


def _update(uid: int, chat: int, texto, fecha: int) -> dict:
    mensaje = {"message_id": uid, "chat": {"id": chat}, "date": fecha}
    if texto is not None:
        mensaje["text"] = texto
    return {"update_id": uid, "message": mensaje}


def _receptor(servidor, reloj, recibidos, **kw):
    return ReceptorTelegram(TOKEN_FALSO, AUTORIZADOS, recibidos.append, reloj, api=servidor.url,
                            espera_polling_s=0, espera_error_s=0.01, **kw)


def test_receptor_dos_updates_y_offset(servidor_tg, reloj, caplog):
    caplog.set_level(logging.DEBUG)
    ahora = int(reloj.epoch())
    servidor_tg.respuestas.append((200, {"ok": True, "result": [
        _update(500, JAUME, "/estado", ahora),
        _update(501, SOCIO, "/cerrar abc SI", ahora),
    ]}))
    recibidos: list[Comando] = []
    rec = _receptor(servidor_tg, reloj, recibidos)
    assert rec.sondear() == 2
    assert [(c.nombre, c.chat_id, c.requiere, c.id) for c in recibidos] == [
        ("estado", JAUME, "nada", "tg:500"), ("cerrar", SOCIO, "si", "tg:501")]
    assert rec.offset == 502
    assert rec.sondear() == 0
    consulta = urllib.parse.parse_qs(urllib.parse.urlsplit(servidor_tg.peticiones[1]).query)
    assert consulta["offset"] == ["502"] and consulta["timeout"] == ["0"]
    assert servidor_tg.peticiones[0].startswith(f"/bot{TOKEN_FALSO}/getUpdates?")
    assert TOKEN_FALSO not in caplog.text and "TOKEN_de_PRUEBA" not in caplog.text


def test_receptor_filtra_chat_ignora_no_texto_y_viejos(servidor_tg, reloj, caplog):
    caplog.set_level(logging.INFO, logger="btt.bot_das.comandos")
    ahora = int(reloj.epoch())
    servidor_tg.respuestas.append((200, {"ok": True, "result": [
        _update(10, EXTRANO, "/cerrar_todo SI", ahora),          # no autorizado: ni se parsea
        _update(11, JAUME, None, ahora),                          # foto/pegatina: sin texto
        {"update_id": 12, "edited_message": {"chat": {"id": JAUME}, "text": "/pausar", "date": ahora}},
        _update(13, JAUME, "hola, ¿cómo va?", ahora),             # texto libre: gancho R-M-06
        _update(14, JAUME, "/cerrar_todo SI", ahora - 3600),      # de hace una hora: no se ejecuta
        _update(15, JAUME, "/salud", ahora - 5),
    ]}))
    recibidos: list[Comando] = []
    rec = _receptor(servidor_tg, reloj, recibidos)
    assert rec.sondear() == 1
    assert [c.nombre for c in recibidos] == ["salud"] and rec.offset == 16
    assert "no autorizado (999)" in caplog.text and "viejo" in caplog.text
    assert "cerrar_todo" not in caplog.text


@pytest.mark.parametrize("respuesta", [
    (500, {"ok": False}), (409, {"ok": False}), (401, {"ok": False}), (200, {"ok": False}), (200, {"ok": True}),
], ids=["R-Q-01-500", "R-Q-01-409", "R-Q-01-401", "R-Q-01-ok-false", "R-Q-01-sin-result"])
def test_receptor_errores_no_lanzan_ni_filtran_token(servidor_tg, reloj, caplog, respuesta):
    caplog.set_level(logging.DEBUG)
    servidor_tg.respuestas.append(respuesta)
    rec = _receptor(servidor_tg, reloj, [])
    assert rec.sondear() is None and rec.errores == 1 and rec.offset == 0
    assert TOKEN_FALSO not in caplog.text and "bot123456789" not in caplog.text


def test_receptor_sin_servidor_no_lanza_ni_filtra_token(reloj, caplog):
    caplog.set_level(logging.DEBUG)
    s = _ServidorTelegram()
    url = s.url
    s.cerrar()                                                     # puerto cerrado: conexión rechazada
    rec = ReceptorTelegram(TOKEN_FALSO, AUTORIZADOS, lambda c: None, reloj, api=url, espera_polling_s=0)
    assert rec.sondear() is None
    assert "getUpdates falló" in caplog.text and TOKEN_FALSO not in caplog.text


def test_receptor_callback_que_falla_no_para(servidor_tg, reloj):
    ahora = int(reloj.epoch())
    servidor_tg.respuestas.append((200, {"ok": True, "result": [_update(1, JAUME, "/estado", ahora),
                                                                 _update(2, JAUME, "/salud", ahora)]}))
    vistos = []

    def al_comando(c):
        vistos.append(c.nombre)
        if c.nombre == "estado":
            raise RuntimeError("fallo del decisor")

    rec = ReceptorTelegram(TOKEN_FALSO, AUTORIZADOS, al_comando, reloj, api=servidor_tg.url, espera_polling_s=0)
    assert rec.sondear() == 1 and vistos == ["estado", "salud"] and rec.offset == 3


def test_receptor_en_hilo(servidor_tg, reloj):
    ahora = int(reloj.epoch())
    servidor_tg.respuestas.append((200, {"ok": True, "result": [_update(7, JAUME, "/estado", ahora)]}))
    llegado = threading.Event()
    rec = ReceptorTelegram(TOKEN_FALSO, AUTORIZADOS, lambda c: llegado.set(), reloj, api=servidor_tg.url,
                           espera_polling_s=0)
    try:
        rec.arrancar()
        assert llegado.wait(5.0) and rec.vivo
    finally:
        rec.parar(5.0)
    assert not rec.vivo


def test_receptor_sin_token_lanza(reloj):
    with pytest.raises(ValueError):
        ReceptorTelegram("", AUTORIZADOS, lambda c: None, reloj)


# ═══════════════════════════ fichero del cuadro ════════════════════════
def _linea(ident, comando, args=(), t=None, quien="jaume", reloj=None) -> str:
    return json.dumps({"id": ident, "comando": comando, "args": list(args), "quien": quien,
                       "t": reloj.epoch() if t is None else t}) + "\n"


@pytest.fixture
def ruta_cmd(dir_bot) -> Path:
    return dir_bot / "estado" / "comandos.jsonl"


def _escribir(ruta: Path, texto: str) -> None:
    with ruta.open("a", encoding="utf-8", newline="") as f:
        f.write(texto)


def test_fichero_idempotente_por_id(ruta_cmd, reloj):
    recibidos: list[Comando] = []
    lector = LectorComandosFichero(ruta_cmd, recibidos.append, reloj)
    assert lector.leer_ahora() == 0                                   # sin fichero: nada
    _escribir(ruta_cmd, _linea("a1", "reanudar_ticker", ["abc"], reloj=reloj))
    _escribir(ruta_cmd, _linea("a1", "reanudar_ticker", ["abc"], reloj=reloj))   # reintento del cuadro
    _escribir(ruta_cmd, _linea("a2", "cerrar_todo", [], reloj=reloj))
    assert lector.leer_ahora() == 2
    assert [(c.nombre, c.args, c.requiere, c.chat_id, c.id) for c in recibidos] == [
        ("reanudar_ticker", ["ABC"], "confirmado", 0, "cuadro:a1"), ("cerrar_todo", [], "confirmado", 0, "cuadro:a2")]
    assert "(cuadro: jaume)" in recibidos[0].texto
    assert lector.leer_ahora() == 0
    guardado = json.loads((ruta_cmd.parent / "comandos_leidos").read_text(encoding="utf-8"))
    assert guardado == {"offset": ruta_cmd.stat().st_size, "ultimo_id": "a2"}
    otro: list[Comando] = []                                          # reinicio del ejecutor
    assert LectorComandosFichero(ruta_cmd, otro.append, reloj).leer_ahora() == 0 and otro == []


def test_fichero_linea_partida(ruta_cmd, reloj):
    recibidos: list[Comando] = []
    lector = LectorComandosFichero(ruta_cmd, recibidos.append, reloj)
    linea = _linea("b1", "estado", reloj=reloj)
    _escribir(ruta_cmd, linea[:15])
    assert lector.leer_ahora() == 0 and lector.offset == 0
    _escribir(ruta_cmd, linea[15:])
    assert lector.leer_ahora() == 1 and recibidos[0].requiere == "nada"


@pytest.mark.parametrize("contenido,motivo", [
    ("esto no es json\n", "json"),
    ("[1, 2]\n", "lista"),
    (json.dumps({"comando": "pausar", "t": 0}) + "\n", "sin id"),
    ("\n\n", "vacias"),
], ids=["R-B-07-json-roto", "R-B-07-no-dict", "R-B-07-sin-id", "R-B-07-vacias"])
def test_fichero_lineas_malas_se_saltan(ruta_cmd, reloj, contenido, motivo):
    recibidos: list[Comando] = []
    lector = LectorComandosFichero(ruta_cmd, recibidos.append, reloj)
    _escribir(ruta_cmd, contenido)
    _escribir(ruta_cmd, _linea("ok", "sigue", reloj=reloj))
    assert lector.leer_ahora() == 1 and recibidos[0].nombre == "sigue"


def test_fichero_viejos_y_sin_hora_se_descartan(ruta_cmd, reloj):
    recibidos: list[Comando] = []
    lector = LectorComandosFichero(ruta_cmd, recibidos.append, reloj, caducidad_s=120)
    _escribir(ruta_cmd, _linea("v1", "cerrar_todo", t=reloj.epoch() - 3600, reloj=reloj))
    _escribir(ruta_cmd, _linea("v2", "cerrar_todo", t="ayer", reloj=reloj))
    _escribir(ruta_cmd, _linea("v3", "cerrar_todo", t="2026-09-25T09:29:00", reloj=reloj))     # ISO sin zona
    _escribir(ruta_cmd, _linea("v4", "pausar", t=reloj.ahora().isoformat(), reloj=reloj))     # ISO con zona
    _escribir(ruta_cmd, _linea("v5", "pausar", t=reloj.epoch() - 100, reloj=reloj))
    assert lector.leer_ahora() == 2
    assert [c.id for c in recibidos] == ["cuadro:v4", "cuadro:v5"] and lector.descartados == 3


def test_fichero_args_invalidos_y_desconocidos_llegan_marcados(ruta_cmd, reloj):
    recibidos: list[Comando] = []
    lector = LectorComandosFichero(ruta_cmd, recibidos.append, reloj)
    _escribir(ruta_cmd, _linea("x1", "cerrar", [], reloj=reloj))
    _escribir(ruta_cmd, _linea("x2", "borrar_todo", [], reloj=reloj))
    _escribir(ruta_cmd, _linea("x3", "confirmar", ["1234"], reloj=reloj))
    _escribir(ruta_cmd, _linea("x4", "cerrar", ["abc", "SI"], reloj=reloj))
    assert lector.leer_ahora() == 4
    assert [c.requiere for c in recibidos] == ["args_invalidos", "desconocido", "desconocido", "confirmado"]
    assert recibidos[3].args == ["ABC"]


def test_fichero_callback_que_falla_ya_consta_leido(ruta_cmd, reloj):
    def al_comando(c):
        raise RuntimeError("fallo del decisor")

    lector = LectorComandosFichero(ruta_cmd, al_comando, reloj)
    _escribir(ruta_cmd, _linea("f1", "pausar", reloj=reloj))
    assert lector.leer_ahora() == 0 and lector.ultimo_id == "f1"
    assert LectorComandosFichero(ruta_cmd, al_comando, reloj).leer_ahora() == 0


def test_fichero_rotado_relee_saltando_hasta_ultimo_id(ruta_cmd, reloj):
    recibidos: list[Comando] = []
    lector = LectorComandosFichero(ruta_cmd, recibidos.append, reloj)
    _escribir(ruta_cmd, _linea("r1", "pausar", reloj=reloj) + _linea("r2", "sigue", reloj=reloj)
              + _linea("r3", "apagar", reloj=reloj))
    assert lector.leer_ahora() == 3
    ruta_cmd.write_text(_linea("r3", "apagar", reloj=reloj) + _linea("r4", "encender", reloj=reloj), encoding="utf-8")
    assert lector.leer_ahora() == 1 and recibidos[-1].id == "cuadro:r4"


def test_fichero_estado_leidos_corrupto(ruta_cmd, reloj):
    (ruta_cmd.parent / "comandos_leidos").write_text("{roto", encoding="utf-8")
    _escribir(ruta_cmd, _linea("c1", "estado", reloj=reloj))
    recibidos: list[Comando] = []
    assert LectorComandosFichero(ruta_cmd, recibidos.append, reloj).leer_ahora() == 1


def test_fichero_en_hilo(ruta_cmd, reloj):
    llegado = threading.Event()
    lector = LectorComandosFichero(ruta_cmd, lambda c: llegado.set(), reloj, intervalo_s=0.05)
    try:
        lector.arrancar()
        _escribir(ruta_cmd, _linea("h1", "salud", reloj=reloj))
        assert llegado.wait(5.0) and lector.vivo
    finally:
        lector.parar(5.0)
    assert not lector.vivo


# ═══════════════ C-01 / DC-03 / G1A-08 / G1A-19: comandos con ticker ═══════════
@pytest.mark.parametrize("texto,nombre,args", [
    ("/sigue", "sigue", []),
    ("/sigue abc", "sigue", ["ABC"]),
    ("/parar_avisos", "parar_avisos", []),
    ("/parar_avisos abc", "parar_avisos", ["ABC"]),
    ("/parar_avisos ABC BS", "parar_avisos", ["ABC"]),
    ("/reanudar_avisos abc bs", "reanudar_avisos", ["ABC"]),
    ("/reanudar_avisos ABC", "reanudar_avisos", ["ABC"]),
], ids=lambda v: v if isinstance(v, str) else None)
def test_C_01_sigue_y_avisos_aceptan_ticker(texto, nombre, args):
    """C-01 / DC-03 / G1A-08 (R-G-03: «/sigue TICKER») y G1A-19 (R-G-01: «/parar_avisos X BS»): el ticker viaja en args."""
    c = parsear(texto, JAUME, AUTORIZADOS)
    assert (c.nombre, c.args, c.requiere) == (nombre, args, "confirmacion")


@pytest.mark.parametrize("texto", [
    "/sigue ABC DEF", "/sigue 123", "/sigue ABC SI",
    "/parar_avisos ABC XY", "/parar_avisos ABC BS OTRA", "/parar_avisos 1ABC", "/reanudar_avisos ABC BS X",
], ids=lambda t: "C-01 " + t)
def test_C_01_sigue_y_avisos_args_invalidos(texto):
    """C-01: más de un ticker, un ticker mal formado o algo distinto de «BS» detrás → args_invalidos con el uso nuevo."""
    c = parsear(texto, JAUME, AUTORIZADOS)
    assert c.requiere == "args_invalidos"
    assert "TICKER" in respuesta_previa(c)


def test_C_01_sigue_con_ticker_conserva_el_ticker_al_confirmar(reloj):
    """C-01 / G1A-08: el dos pasos devuelve al decisor el MISMO args=[TICKER] que se pidió."""
    conf = Confirmaciones(reloj)
    ident = _id_de(conf.pedir(parsear("/sigue abc", JAUME, AUTORIZADOS)))
    confirmado = conf.confirmar(JAUME, f"/confirmar {ident}")
    assert (confirmado.nombre, confirmado.args, confirmado.requiere) == ("sigue", ["ABC"], "confirmado")


def test_C_01_boton_del_cuadro_sigue_con_ticker(ruta_cmd, reloj):
    """C-01: el botón del cuadro «sigue ABC» llega igual que por Telegram (args=[TICKER], ya confirmado)."""
    recibidos: list[Comando] = []
    lector = LectorComandosFichero(ruta_cmd, recibidos.append, reloj)
    _escribir(ruta_cmd, _linea("s1", "sigue", ["abc"], reloj=reloj))
    _escribir(ruta_cmd, _linea("s2", "parar_avisos", ["abc", "BS"], reloj=reloj))
    assert lector.leer_ahora() == 2
    assert [(c.nombre, c.args, c.requiere) for c in recibidos] == [
        ("sigue", ["ABC"], "confirmado"), ("parar_avisos", ["ABC"], "confirmado")]


# ═══════════════ C-02: offset de Telegram persistido ═══════════════════
def test_C_02_dos_receptores_seguidos_no_repiten_el_mismo_update(servidor_tg, reloj, dir_bot):
    """C-02: el ejecutor cae tras entregar «/cerrar ABC 100 SI»; Telegram lo devuelve otra vez → el segundo entrega 0."""
    ruta = dir_bot / "estado" / C.FICHERO_OFFSET_TELEGRAM
    ahora = int(reloj.epoch())
    lote = (200, {"ok": True, "result": [_update(900, JAUME, "/cerrar abc 100 SI", ahora)]})
    servidor_tg.respuestas.extend([lote, lote])            # Telegram repite lo no confirmado
    primeros: list[Comando] = []
    assert _receptor(servidor_tg, reloj, primeros, ruta_offset=ruta).sondear() == 1
    assert [(c.nombre, c.args) for c in primeros] == [("cerrar", ["ABC", "100"])]
    guardado = json.loads(ruta.read_text(encoding="utf-8"))
    assert (guardado["offset"], guardado["ultimo_update_id"], guardado["entregados"]) == (901, 900, [900])
    assert guardado["token_sha256"] == hashlib.sha256(TOKEN_FALSO.encode("utf-8")).hexdigest()
    assert guardado["ts"] == reloj.epoch() and TOKEN_FALSO not in ruta.read_text(encoding="utf-8")
    segundos: list[Comando] = []
    rec2 = _receptor(servidor_tg, reloj, segundos, ruta_offset=ruta)      # relanzado por el supervisor
    assert rec2.offset == 901
    assert rec2.sondear() == 0 and segundos == []
    consulta = urllib.parse.parse_qs(urllib.parse.urlsplit(servidor_tg.peticiones[1]).query)
    assert consulta["offset"] == ["901"], "el receptor nuevo pide desde el offset guardado"


def test_C_02_offset_se_guarda_antes_de_entregar(servidor_tg, reloj, dir_bot):
    """C-02: cuando al_comando se ejecuta, el offset YA está en disco (como mucho una vez)."""
    ruta = dir_bot / "estado" / C.FICHERO_OFFSET_TELEGRAM
    ahora = int(reloj.epoch())
    servidor_tg.respuestas.append((200, {"ok": True, "result": [_update(41, JAUME, "/estado", ahora),
                                                                 _update(42, JAUME, "/salud", ahora)]}))
    en_disco: list[int] = []

    def al_comando(c):
        en_disco.append(json.loads(ruta.read_text(encoding="utf-8"))["offset"])

    rec = ReceptorTelegram(TOKEN_FALSO, AUTORIZADOS, al_comando, reloj, api=servidor_tg.url, espera_polling_s=0,
                           ruta_offset=ruta)
    assert rec.sondear() == 2 and en_disco == [42, 43]


def test_C_02_updates_sin_comando_tambien_avanzan_el_offset_en_disco(servidor_tg, reloj, dir_bot):
    """C-02: una foto o un chat ajeno no se entregan, pero constan como leídos en disco."""
    ruta = dir_bot / "estado" / C.FICHERO_OFFSET_TELEGRAM
    ahora = int(reloj.epoch())
    servidor_tg.respuestas.append((200, {"ok": True, "result": [_update(70, EXTRANO, "/estado", ahora),
                                                                 _update(71, JAUME, None, ahora)]}))
    rec = _receptor(servidor_tg, reloj, [], ruta_offset=ruta)
    assert rec.sondear() == 0
    assert json.loads(ruta.read_text(encoding="utf-8"))["offset"] == 72


def test_C_02_parar_confirma_lo_leido_a_telegram(servidor_tg, reloj, dir_bot):
    """C-02: parar() hace un getUpdates final con timeout 0 y el offset: Telegram da por leído el último lote."""
    ruta = dir_bot / "estado" / C.FICHERO_OFFSET_TELEGRAM
    ahora = int(reloj.epoch())
    servidor_tg.respuestas.append((200, {"ok": True, "result": [_update(5, JAUME, "/estado", ahora)]}))
    rec = _receptor(servidor_tg, reloj, [], ruta_offset=ruta)
    assert rec.sondear() == 1
    antes = len(servidor_tg.peticiones)
    rec.parar(1.0)
    assert len(servidor_tg.peticiones) == antes + 1
    consulta = urllib.parse.parse_qs(urllib.parse.urlsplit(servidor_tg.peticiones[-1]).query)
    assert consulta["offset"] == ["6"] and consulta["timeout"] == ["0"] and consulta["limit"] == ["1"]


def test_C_02_parar_sin_nada_leido_no_llama_a_telegram(servidor_tg, reloj):
    """C-02: con offset 0 no hay nada que confirmar."""
    rec = _receptor(servidor_tg, reloj, [])
    rec.parar(1.0)
    assert servidor_tg.peticiones == []


def test_C_02_fichero_de_offset_corrupto_empieza_de_cero(servidor_tg, reloj, dir_bot, caplog):
    """C-02: un telegram_offset ilegible no tumba el receptor: offset 0 (la caducidad de 120 s protege)."""
    ruta = dir_bot / "estado" / C.FICHERO_OFFSET_TELEGRAM
    ruta.write_text("{roto", encoding="utf-8")
    caplog.set_level(logging.WARNING, logger="btt.bot_das.comandos")
    rec = _receptor(servidor_tg, reloj, [], ruta_offset=ruta)
    assert rec.offset == 0 and "ilegible" in caplog.text


# ═══════════ R2-CMD-1: el offset persistido no deja al bot sordo ═══════════
def _fichero_offset(ruta: Path, *, offset: int, entregados: list[int], ts: float,
                    token: str = TOKEN_FALSO) -> None:
    ruta.write_text(json.dumps({"offset": offset, "ultimo_update_id": offset - 1, "ts": ts, "entregados": entregados,
                                "token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest()}), encoding="utf-8")


def test_R2_CMD_1_offset_de_otro_token_se_descarta(servidor_tg, reloj, dir_bot, caplog):
    """R2-CMD-1: un telegram_offset escrito con OTRO token (bot cambiado) se descarta: offset 0 y sin memoria."""
    ruta = dir_bot / "estado" / C.FICHERO_OFFSET_TELEGRAM
    _fichero_offset(ruta, offset=901, entregados=[900], ts=reloj.epoch(), token="999:OTRO_token")
    caplog.set_level(logging.WARNING, logger="btt.bot_das.comandos")
    rec = _receptor(servidor_tg, reloj, [], ruta_offset=ruta)
    assert rec.offset == 0 and rec.ultimo_update_id is None and "otro token" in caplog.text
    ahora = int(reloj.epoch())
    servidor_tg.respuestas.append((200, {"ok": True, "result": [_update(900, JAUME, "/estado", ahora)]}))
    assert rec.sondear() == 1, "sin la memoria del otro bot, el 900 de este bot se entrega"


def test_R2_CMD_1_offset_sin_huella_del_formato_viejo_se_descarta(servidor_tg, reloj, dir_bot):
    """R2-CMD-1: el formato de la primera ronda ({offset, ultimo_update_id}, sin hash ni ts) no se usa."""
    ruta = dir_bot / "estado" / C.FICHERO_OFFSET_TELEGRAM
    ruta.write_text(json.dumps({"offset": 901, "ultimo_update_id": 900}), encoding="utf-8")
    assert _receptor(servidor_tg, reloj, [], ruta_offset=ruta).offset == 0


@pytest.mark.parametrize("edad_s", [6 * 86400.0, 30 * 86400.0, -3600.0], ids=["6 dias", "30 dias", "futuro"])
def test_R2_CMD_1_offset_viejo_se_descarta(servidor_tg, reloj, dir_bot, edad_s):
    """R2-CMD-1: con ts de 6 días o más (Telegram rebaraja la secuencia) o en el futuro → offset 0."""
    ruta = dir_bot / "estado" / C.FICHERO_OFFSET_TELEGRAM
    _fichero_offset(ruta, offset=901, entregados=[900], ts=reloj.epoch() - edad_s)
    rec = _receptor(servidor_tg, reloj, [], ruta_offset=ruta)
    assert rec.offset == 0 and rec.ultimo_update_id is None


def test_R2_CMD_1_offset_reciente_del_mismo_token_se_usa(servidor_tg, reloj, dir_bot):
    """R2-CMD-1: mismo token y menos de 6 días → se recuperan offset y memoria de entregados."""
    ruta = dir_bot / "estado" / C.FICHERO_OFFSET_TELEGRAM
    _fichero_offset(ruta, offset=901, entregados=[899, 900], ts=reloj.epoch() - 5 * 86400.0)
    rec = _receptor(servidor_tg, reloj, [], ruta_offset=ruta)
    assert (rec.offset, rec.ultimo_update_id) == (901, 900)


def test_R2_CMD_1_uid_menor_que_el_offset_no_entregado_se_entrega(servidor_tg, reloj, dir_bot, caplog):
    """R2-CMD-1: la secuencia se reinició (uid 5 con offset 901, nunca entregado) → se entrega y el offset se reajusta."""
    ruta = dir_bot / "estado" / C.FICHERO_OFFSET_TELEGRAM
    _fichero_offset(ruta, offset=901, entregados=[899, 900], ts=reloj.epoch())
    ahora = int(reloj.epoch())
    servidor_tg.respuestas.append((200, {"ok": True, "result": [_update(5, JAUME, "/cerrar abc 100 SI", ahora),
                                                                 _update(6, JAUME, "/estado", ahora)]}))
    servidor_tg.respuestas.append((200, {"ok": True, "result": []}))
    recibidos: list[Comando] = []
    caplog.set_level(logging.WARNING, logger="btt.bot_das.comandos")
    rec = _receptor(servidor_tg, reloj, recibidos, ruta_offset=ruta)
    assert rec.sondear() == 2
    assert [(c.nombre, c.args) for c in recibidos] == [("cerrar", ["ABC", "100"]), ("estado", [])]
    assert rec.offset == 7 and "secuencia nueva" in caplog.text
    guardado = json.loads(ruta.read_text(encoding="utf-8"))
    assert guardado["offset"] == 7 and guardado["entregados"][-2:] == [5, 6]
    rec.sondear()
    consulta = urllib.parse.parse_qs(urllib.parse.urlsplit(servidor_tg.peticiones[-1]).query)
    assert consulta["offset"] == ["7"], "la siguiente consulta pide desde el offset reajustado"


def test_R2_CMD_1_uid_ya_entregado_no_se_repite(servidor_tg, reloj, dir_bot):
    """R2-CMD-1: un update_id que está en la memoria persistida no se entrega otra vez, aunque sea >= offset."""
    ruta = dir_bot / "estado" / C.FICHERO_OFFSET_TELEGRAM
    _fichero_offset(ruta, offset=0, entregados=[900], ts=reloj.epoch())
    ahora = int(reloj.epoch())
    servidor_tg.respuestas.append((200, {"ok": True, "result": [_update(900, JAUME, "/cerrar abc 100 SI", ahora),
                                                                 _update(901, JAUME, "/estado", ahora)]}))
    recibidos: list[Comando] = []
    rec = _receptor(servidor_tg, reloj, recibidos, ruta_offset=ruta)
    assert rec.sondear() == 1 and [c.nombre for c in recibidos] == ["estado"]
    assert rec.offset == 902


def test_R2_CMD_1_memoria_de_entregados_acotada_a_200(servidor_tg, reloj, dir_bot):
    """R2-CMD-1: se recuerdan los ÚLTIMOS 200 update_id (el fichero no crece sin fin)."""
    ruta = dir_bot / "estado" / C.FICHERO_OFFSET_TELEGRAM
    ahora = int(reloj.epoch())
    servidor_tg.respuestas.append((200, {"ok": True, "result": [_update(i, JAUME, "/estado", ahora)
                                                                 for i in range(1, 251)]}))
    rec = _receptor(servidor_tg, reloj, [], ruta_offset=ruta)
    assert rec.sondear() == 250
    guardado = json.loads(ruta.read_text(encoding="utf-8"))
    assert guardado["entregados"] == list(range(51, 251)) and guardado["offset"] == 251


def test_R2_CMD_1_caducidad_de_120_s_sigue_vigente_sin_offset(servidor_tg, reloj, dir_bot):
    """R2-CMD-1: descartado el fichero (offset 0), un comando de hace más de 120 s no se ejecuta."""
    ruta = dir_bot / "estado" / C.FICHERO_OFFSET_TELEGRAM
    _fichero_offset(ruta, offset=901, entregados=[900], ts=reloj.epoch() - 7 * 86400.0)
    viejo = int(reloj.epoch()) - 121
    servidor_tg.respuestas.append((200, {"ok": True, "result": [_update(900, JAUME, "/cerrar abc 100 SI", viejo)]}))
    recibidos: list[Comando] = []
    rec = _receptor(servidor_tg, reloj, recibidos, ruta_offset=ruta)
    assert rec.offset == 0 and rec.sondear() == 0 and recibidos == []


# ═══════════════════════════ higiene ═══════════════════════════════════
def test_importar_en_proceso_limpio_no_arranca_hilos_ni_trae_httpx():
    import subprocess
    import sys

    backend = Path(C.__file__).resolve().parents[2]
    codigo = ("import sys, threading; import app.bot_das.comandos; "
              "print(threading.active_count(), 'httpx' in sys.modules, 'pandas' in sys.modules)")
    salida = subprocess.run([sys.executable, "-c", codigo], cwd=backend, capture_output=True, text=True, timeout=60)
    assert salida.returncode == 0, salida.stderr
    assert salida.stdout.split() == ["1", "False", "False"]
    assert "import httpx" not in Path(C.__file__).read_text(encoding="utf-8")
