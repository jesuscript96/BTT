"""Tests de `app.bot_das.cliente` (documento §3.2, §9, §10 fila `test_das_cliente`; riesgos 7, 10, 11, 17, 20).

QUÉ HACE. Prueba `CuotaComandos` y `PlanReconexion` en seco con el reloj
simulado, y `ClienteDAS`/`ClienteSombra` contra el `SimuladorDAS` en
127.0.0.1:0: LOGIN y volcado, líneas partidas en varios `recv`, `\\r\\n` y
`\\n`, los candados de la sombra (`EnvioProhibido`, `ClienteSombra`,
`desde_env` sin `BOT_DAS_PERMITIR_ORDENES`), cuotas en el emisor, corte y
reconexión, `invalidar`, cola llena y que la clave nunca llega al log.

POR QUÉ ESTÁ AQUÍ. Es el único módulo con socket hacia DAS: lo que aquí falle
es una orden que sale cuando no debía (sombra), un REPLACE viejo después de un
fill o una clave en un log.

LAS TRAMPAS.
  * Nada de red real: solo el simulador en 127.0.0.1 con usuarios inventados
    (las credenciales de ejemplo del manual no se usan).
  * Toda espera es un sondeo con plazo (`esperar`), nunca un `sleep` largo;
    los pocos `sleep` de 0,05-0,3 s solo dejan que un `recv` vea un trozo.
  * Cada cliente se cierra en el `finally` de su fixture ANTES de parar el
    simulador (orden de desmontaje de pytest).
"""
from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from decimal import Decimal
from pathlib import Path
from typing import Callable, Optional

import pytest

import app.bot_das.cliente as cliente_mod
from app.bot_das.cliente import (
    ESPERA_COLA_LLENA_S,
    MOTIVO_COLA_LLENA,
    MOTIVO_SESION,
    MOTIVO_VERSION,
    TOPE_LINEA_BYTES,
    ClienteDAS,
    ClienteSombra,
    CuotaComandos,
    EnvioProhibido,
    PlanReconexion,
)
from app.bot_das.protocolo import MUTANTES, cmd_neworder, cmd_replace, es_mutante
from app.bot_das.reloj import RelojSimulado
from app.bot_das.tipos import (
    COLA_SALIDA_TOPE,
    Lado,
    MensajeDAS,
    MsgBP,
    MsgConexion,
    MsgDesconocido,
    MsgInformativo,
    MsgMarcador,
    MsgOrden,
    MsgOrderAct,
    MsgPos,
    MsgQuote,
    MsgTrade,
    Origen,
    OrdenDescartada,
    OrdenNueva,
    TipoOrden,
)
from app.bot_das.tokens import componer

simulador_das = pytest.importorskip("app.bot_das.simulador_das")

USUARIO = "prueba"
CLAVE = "clave-inventada-para-test"
CUENTA = "CUENTA_PRUEBA"
BACKEND = Path(__file__).resolve().parents[2]
HILOS_CLIENTE = ("das-lector", "das-emisor")


# ══════════════════════════════════════════════════════════════════════
# ayudantes
# ══════════════════════════════════════════════════════════════════════
def esperar(condicion: Callable[[], bool], plazo_s: float = 3.0) -> bool:
    """Sondea cada 10 ms hasta que `condicion()` sea cierta o venza el plazo."""
    limite = time.monotonic() + plazo_s
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.01)
    return condicion()


class Grabadora:
    """Callbacks del cliente que solo graban (como el ejecutor, que solo encola)."""

    def __init__(self) -> None:
        self._cerrojo = threading.Lock()
        self.mensajes: list[MensajeDAS] = []
        self.estados: list[tuple[bool, str]] = []
        self.avisos: list[str] = []
        self.caidas: list[tuple[str, str, bool]] = []

    def al_mensaje(self, msg: MensajeDAS) -> None:
        with self._cerrojo:
            self.mensajes.append(msg)

    def al_estado(self, conectado: bool, motivo: str) -> None:
        with self._cerrojo:
            self.estados.append((conectado, motivo))

    def al_aviso(self, texto: str) -> None:
        with self._cerrojo:
            self.avisos.append(texto)

    def al_caida_hilo(self, nombre: str, error: str, relanzado: bool) -> None:
        with self._cerrojo:
            self.caidas.append((nombre, error, relanzado))

    def de_tipo(self, clase: type) -> list:
        with self._cerrojo:
            return [m for m in self.mensajes if isinstance(m, clase)]

    def todos(self) -> list[MensajeDAS]:
        with self._cerrojo:
            return list(self.mensajes)


class CuotaControlada:
    """Cuota de prueba: mientras `bloqueada`, ninguna línea cabe (el emisor espera y la cola se llena)."""

    def __init__(self, bloqueada: bool = True) -> None:
        self.bloqueada = bloqueada
        self.anotadas: list[str] = []

    def espera_para(self, linea: str) -> float:
        return 0.05 if self.bloqueada else 0.0

    def anotar(self, linea: str) -> None:
        self.anotadas.append(linea)


def hilos_del_cliente_vivos() -> bool:
    return any(t.name in HILOS_CLIENTE and t.is_alive() for t in threading.enumerate())


def linea_neworder(reloj: RelojSimulado, seq: int, precio: str = "3.1") -> str:
    token = componer(Origen.EJECUTOR, reloj.hoy().timetuple().tm_yday, seq)
    return cmd_neworder(OrdenNueva(token=token, lado=Lado.CORTO, ticker="ABCD", ruta="SAGEREB", qty=100,
                                   tipo=TipoOrden.LIMITE, precio=Decimal(precio)))


def linea_stop(reloj: RelojSimulado, seq: int, ticker: str, qty: int = 100) -> str:
    """NEWORDER STOPLMTP de compra (un stop de la serie «stops:TICKER»), lejos del mercado."""
    token = componer(Origen.EJECUTOR, reloj.hoy().timetuple().tm_yday, seq)
    return cmd_neworder(OrdenNueva(token=token, lado=Lado.COMPRA, ticker=ticker, ruta="STOP", qty=qty,
                                   tipo=TipoOrden.STOP_LIMITE_PP, stop=Decimal("9.9"), precio=Decimal("10")))


def linea_replace_stop(qty: int) -> str:
    return cmd_replace(1001, qty, TipoOrden.STOP_LIMITE_PP, precio=Decimal("3.2"), stop=Decimal("3.1"))


def recibidas_sin_login(sim) -> list[str]:
    return [x for x in sim.recibidas() if not x.upper().startswith("LOGIN")]


# ══════════════════════════════════════════════════════════════════════
# fixtures
# ══════════════════════════════════════════════════════════════════════
@pytest.fixture
def sim(libro, reloj):
    """SimuladorDAS con un usuario inventado; parado siempre al terminar."""
    servidor = simulador_das.SimuladorDAS(libro, reloj, host="127.0.0.1", puerto=0, usuarios={USUARIO: CLAVE})
    servidor.arrancar()
    try:
        yield servidor
    finally:
        servidor.parar()


@pytest.fixture
def fabrica(sim, reloj):
    """crear(solo_lectura=True, watch=False, clave=CLAVE, **kw) → (ClienteDAS, Grabadora); todos se cierran al final."""
    creados: list[ClienteDAS] = []

    def crear(solo_lectura: bool = True, watch: bool = False, clave: str = CLAVE, **kw) -> tuple[ClienteDAS, Grabadora]:
        g = Grabadora()
        host, puerto = sim.direccion
        kw.setdefault("timeout_s", 1.0)
        c = ClienteDAS(host, puerto, USUARIO, clave, CUENTA, watch, solo_lectura, g.al_mensaje, g.al_estado,
                       kw.pop("reloj", reloj), al_aviso=g.al_aviso, al_caida_hilo=g.al_caida_hilo, **kw)
        creados.append(c)
        return c, g

    try:
        yield crear
    finally:
        for c in creados:
            c.cerrar()


@pytest.fixture
def suelto(reloj):
    """(ClienteDAS nunca conectado, Grabadora): para lo que se decide ANTES de tocar la red."""
    g = Grabadora()
    c = ClienteDAS("127.0.0.1", 9, USUARIO, CLAVE, CUENTA, False, True, g.al_mensaje, g.al_estado, reloj,
                   al_aviso=g.al_aviso)
    return c, g


# ══════════════════════════════════════════════════════════════════════
# PlanReconexion (R-J-02)
# ══════════════════════════════════════════════════════════════════════
def test_das_plan_reconexion_2_4_8_16_y_30_sin_parar():
    plan = PlanReconexion()
    assert [plan.siguiente() for _ in range(8)] == [2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0, 30.0]
    assert plan.intentos == 8
    plan.reiniciar()
    assert plan.intentos == 0
    assert plan.siguiente() == 2.0


def test_das_plan_reconexion_esperas_propias():
    plan = PlanReconexion(esperas=(1, 3), tope=5)
    assert [plan.siguiente() for _ in range(4)] == [1.0, 3.0, 5.0, 5.0]


@pytest.mark.parametrize("esperas,tope", [
    pytest.param((), 30.0, id="R-J-02-sin-esperas"),
    pytest.param((2.0, 0.0), 30.0, id="R-J-02-espera-cero"),
    pytest.param((2.0, -1.0), 30.0, id="R-J-02-espera-negativa"),
    pytest.param((2.0,), float("inf"), id="R-J-02-tope-infinito"),
    pytest.param((True,), 30.0, id="R-J-02-bool"),
])
def test_das_plan_reconexion_rechaza_parametros(esperas, tope):
    with pytest.raises(ValueError):
        PlanReconexion(esperas=esperas, tope=tope)


# ══════════════════════════════════════════════════════════════════════
# CuotaComandos (manual L1996-2016, §5.29, riesgos 11 y 36)
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("linea,nominal,ventana", [
    pytest.param("NEWORDER 1 SS ABCD SAGEREB 100 3.1 TIF=DAY+", 50, 1.0, id="L2000-NEWORDER-50-por-s"),
    pytest.param("CANCEL 1001", 100, 60.0, id="L2004-CANCEL-100-por-min"),
    pytest.param("REPLACE 1001 100 3.2", 100, 60.0, id="L2006-REPLACE-100-por-min"),
    pytest.param("SLNEWORDER ABCD 100 LOCSIM 326800001", 100, 60.0, id="L2010-SLNEWORDER-100-por-min"),
])
def test_das_cuota_al_100_la_siguiente_espera_la_ventana(reloj, linea, nominal, ventana):
    cuota = CuotaComandos(reloj, margen=1.0)
    for _ in range(nominal):
        assert cuota.espera_para(linea) == 0.0
        cuota.anotar(linea)
    assert cuota.espera_para(linea) == pytest.approx(ventana)
    reloj.avanzar(ventana)
    assert cuota.espera_para(linea) == 0.0


@pytest.mark.parametrize("linea,cabida,ventana", [
    pytest.param("NEWORDER 1 SS ABCD SAGEREB 100 3.1 TIF=DAY+", 45, 1.0, id="riesgo22-NEWORDER-45"),
    pytest.param("CANCEL ALLSYMB ABCD", 90, 60.0, id="riesgo22-CANCEL-90"),
    pytest.param("REPLACE 1001 100 STOPLMT 3.1 3.2", 90, 60.0, id="riesgo22-REPLACE-90"),
    pytest.param("SLNEWORDER ABCD 100 LOCSIM 326800001", 90, 60.0, id="riesgo22-SLNEWORDER-90"),
])
def test_das_cuota_margen_0_9_trabaja_al_90_por_ciento(reloj, linea, cabida, ventana):
    cuota = CuotaComandos(reloj)
    for _ in range(cabida):
        assert cuota.espera_para(linea) == 0.0
        cuota.anotar(linea)
    assert cuota.espera_para(linea) == pytest.approx(ventana)


def test_das_cuota_51_ordenes_en_1_s_la_51_espera(reloj):
    """§10: 51 órdenes en 1 s → espera (al 100 %: 50 por segundo, ventana deslizante)."""
    cuota = CuotaComandos(reloj, margen=1.0)
    linea = "NEWORDER 1 SS ABCD SAGEREB 100 3.1 TIF=DAY+"
    for i in range(50):
        assert cuota.espera_para(linea) == 0.0
        cuota.anotar(linea)
        if i < 49:
            reloj.avanzar(0.02)
    # la primera salió en t0 y ahora es t0 + 0,98: la 51 espera a que caduque (0,02 s)
    assert cuota.espera_para(linea) == pytest.approx(0.02)
    reloj.avanzar(0.02)
    assert cuota.espera_para(linea) == 0.0


def test_das_cuota_ventana_deslizante_espera_exacta(reloj):
    cuota = CuotaComandos(reloj)
    linea = "NEWORDER 1 SS ABCD SAGEREB 100 3.1 TIF=DAY+"
    for _ in range(45):
        cuota.anotar(linea)
    reloj.avanzar(0.5)
    assert cuota.espera_para(linea) == pytest.approx(0.5)
    reloj.avanzar(0.5)
    assert cuota.espera_para(linea) == 0.0


def test_das_cuota_101_cancel_por_minuto(reloj):
    cuota = CuotaComandos(reloj, margen=1.0)
    for _ in range(100):
        cuota.anotar("CANCEL 1001")
        reloj.avanzar(0.1)                          # 100 CANCEL en 10 s
    assert cuota.espera_para("CANCEL 1002") == pytest.approx(50.0)
    reloj.avanzar(50.0)
    assert cuota.espera_para("CANCEL 1002") == 0.0


@pytest.mark.parametrize("margen,espera_a_2_9,libre_desde", [
    pytest.param(1.0, 0.1, 3.0, id="L2002-inquire-1-cada-3s"),
    pytest.param(0.9, 3.0 / 0.9 - 2.9, 3.0 / 0.9, id="riesgo22-inquire-margen-0.9"),
])
def test_das_cuota_inquire_menos_de_3_s_espera(reloj, margen, espera_a_2_9, libre_desde):
    cuota = CuotaComandos(reloj, margen=margen)
    cuota.anotar("SLPRICEINQUIRE ABCD 100 ALLROUTEWTTYPE1")
    reloj.avanzar(2.9)
    # la cuota es GLOBAL (riesgo 36): otro ticker espera lo mismo
    assert cuota.espera_para("SLPRICEINQUIRE WXYZ 300 ALLROUTEWTTYPE1") == pytest.approx(espera_a_2_9)
    reloj.avanzar(libre_desde - 2.9)
    assert cuota.espera_para("SLPRICEINQUIRE WXYZ 300 ALLROUTEWTTYPE1") == 0.0


def test_das_cuota_categorias_independientes_y_sin_cuota(reloj):
    cuota = CuotaComandos(reloj)
    for _ in range(45):
        cuota.anotar("NEWORDER 1 SS ABCD SAGEREB 100 3.1 TIF=DAY+")
    assert cuota.espera_para("NEWORDER 2 SS ABCD SAGEREB 100 3.1 TIF=DAY+") > 0
    assert cuota.espera_para("CANCEL 1001") == 0.0
    assert cuota.espera_para("REPLACE 1001 100 3.2") == 0.0
    for sin_cuota in ("GET BP", "SB ABCD Lv1", "POSREFRESH", "ECHO", "", "   ", "SLReuseQuery ABCD"):
        for _ in range(200):
            cuota.anotar(sin_cuota)
        assert cuota.espera_para(sin_cuota) == 0.0


def test_das_cuota_palabra_clave_sin_distinguir_mayusculas(reloj):
    cuota = CuotaComandos(reloj, margen=1.0, ordenes_s=2)
    cuota.anotar("neworder 1 SS ABCD SAGEREB 100 3.1")
    cuota.anotar("  NewOrder 2 SS ABCD SAGEREB 100 3.1")
    assert cuota.espera_para("NEWORDER 3 SS ABCD SAGEREB 100 3.1") == pytest.approx(1.0)


def test_das_cuota_limites_con_margen(reloj):
    assert CuotaComandos(reloj).limites == {
        "NEWORDER": (1.0, 45), "CANCEL": (60.0, 90), "REPLACE": (60.0, 90), "SLNEWORDER": (60.0, 90),
        "SLPRICEINQUIRE": (pytest.approx(3.0 / 0.9), 1),
    }


@pytest.mark.parametrize("kw", [
    pytest.param({"margen": 0.0}, id="riesgo22-margen-0"),
    pytest.param({"margen": 1.1}, id="riesgo22-margen-mayor-que-1"),
    pytest.param({"margen": float("nan")}, id="riesgo22-margen-nan"),
    pytest.param({"ordenes_s": 0}, id="L2000-ordenes-0"),
    pytest.param({"cancel_min": 1.5}, id="L2004-cancel-float"),
    pytest.param({"replace_min": True}, id="L2006-replace-bool"),
    pytest.param({"inquire_s": 0}, id="L2002-inquire-0"),
])
def test_das_cuota_rechaza_parametros(reloj, kw):
    with pytest.raises(ValueError):
        CuotaComandos(reloj, **kw)


def test_das_cuota_exige_reloj_con_mono():
    with pytest.raises(TypeError):
        CuotaComandos(object())


# ══════════════════════════════════════════════════════════════════════
# LOGIN, volcado y lector (L243-255, §5.1)
# ══════════════════════════════════════════════════════════════════════
def test_das_login_y_volcado(fabrica, sim, libro, reloj):
    libro.sembrar_posicion("ABCD", -100, Decimal("3.1"))
    c, g = fabrica()
    assert c.conectar() is True
    assert c.conectado
    assert esperar(lambda: any(isinstance(m, MsgMarcador) and m.nombre == "#TradeEnd" for m in g.todos()))
    assert sim.recibidas()[0] == f"LOGIN {USUARIO} {CLAVE} {CUENTA} 0"
    assert g.estados == [(True, f"conectado a {sim.direccion[0]}:{sim.direccion[1]}")]
    msgs = g.todos()
    assert [(m.servidor, m.evento) for m in msgs[:2]] == [("OrderServer", "Logon:Successful"),
                                                         ("QuoteServer", "Logon:Successful")]
    assert [m.nombre for m in msgs if isinstance(m, MsgMarcador)] == [
        "#POS", "#POSEND", "#Order", "#OrderEnd", "#Trade", "#TradeEnd"]
    pos = g.de_tipo(MsgPos)
    assert len(pos) == 1 and pos[0].ticker == "ABCD" and pos[0].neta == -100 and pos[0].watch is False
    assert c.logon == {"OrderServer": True, "QuoteServer": True}
    assert c.ultimo_recibido_en == reloj.mono()
    assert c.hilos_vivos
    assert {t.name for t in threading.enumerate() if t.is_alive()} >= set(HILOS_CLIENTE)


def test_das_login_watch_recibe_formas_i(fabrica, sim, libro):
    libro.sembrar_posicion("ABCD", -100, Decimal("3.1"))
    c, g = fabrica(watch=True)
    assert c.conectar()
    assert esperar(lambda: len(g.de_tipo(MsgPos)) == 1)
    assert sim.recibidas()[0] == f"LOGIN {USUARIO} {CLAVE} {CUENTA} 1"
    assert g.de_tipo(MsgPos)[0].watch is True
    assert c.watch is True


def test_das_login_fallido_logon_false(fabrica):
    c, g = fabrica(clave="otra-clave-inventada")
    assert c.conectar() is True                     # el socket abrió: DAS no tiene «login OK» documentado (§1)
    assert esperar(lambda: c.logon["OrderServer"] is False)
    assert c.logon["QuoteServer"] is None


def test_das_conectar_puerto_cerrado_devuelve_false(reloj):
    import socket as _socket
    s = _socket.socket()
    s.bind(("127.0.0.1", 0))
    puerto = s.getsockname()[1]
    s.close()
    g = Grabadora()
    c = ClienteDAS("127.0.0.1", puerto, USUARIO, CLAVE, CUENTA, False, True, g.al_mensaje, g.al_estado, reloj,
                   timeout_s=0.5)
    try:
        assert c.conectar() is False
        assert not c.conectado
        assert g.estados == []                      # no hubo transición: sin al_estado
        assert c.hilos_vivos                        # sin sesión no debe correr nada
    finally:
        c.cerrar()


def test_das_conectar_dos_veces_es_idempotente(fabrica, sim):
    c, g = fabrica()
    assert c.conectar() and c.conectar()
    assert esperar(lambda: sim.n_conexiones == 1)
    assert [x for x in sim.recibidas() if x.startswith("LOGIN")] == [f"LOGIN {USUARIO} {CLAVE} {CUENTA} 0"]
    assert len(g.estados) == 1


LINEA_POS = b"%POS ABCD 3 100 3.1 100 3.1 0 1970/01/01-00:00:00\r\n"


@pytest.mark.parametrize("corte", [
    pytest.param(1, id="5.1-tras-el-primer-byte"),
    pytest.param(len(LINEA_POS) // 2, id="5.1-a-mitad"),
    pytest.param(len(LINEA_POS) - 2, id="5.1-antes-del-CR"),
    pytest.param(len(LINEA_POS) - 1, id="5.1-entre-CR-y-LF"),
])
def test_das_linea_partida_en_varios_recv(fabrica, sim, corte):
    c, g = fabrica()
    assert c.conectar()
    assert esperar(lambda: any(isinstance(m, MsgMarcador) and m.nombre == "#TradeEnd" for m in g.todos()))
    antes = len(g.todos())
    sim.emitir_crudo(LINEA_POS[:corte])
    time.sleep(0.1)
    assert len(g.todos()) == antes                  # media línea: todavía nada
    sim.emitir_crudo(LINEA_POS[corte:])
    assert esperar(lambda: len(g.todos()) == antes + 1)
    msg = g.todos()[-1]
    assert isinstance(msg, MsgPos) and msg.neta == -100 and msg.qty_cruda == 100
    assert msg.cruda == LINEA_POS.decode("latin-1").rstrip("\r\n")


def test_das_quote_partido_en_tres_recv(fabrica, sim):
    c, g = fabrica()
    assert c.conectar()
    assert esperar(lambda: len(g.de_tipo(MsgMarcador)) == 6)
    sim.emitir_crudo("$Quote ABCD A:3.1")
    time.sleep(0.05)
    sim.emitir_crudo(" B:3.0\r")
    time.sleep(0.05)
    assert g.de_tipo(MsgQuote) == []
    sim.emitir_crudo("\n")
    assert esperar(lambda: len(g.de_tipo(MsgQuote)) == 1)
    q = g.de_tipo(MsgQuote)[0]
    assert q.ticker == "ABCD" and q.campos == {"A": "3.1", "B": "3.0"}
    assert q.cruda == "$Quote ABCD A:3.1 B:3.0"


def test_das_varias_lineas_en_un_recv(fabrica, sim):
    c, g = fabrica()
    assert c.conectar()
    assert esperar(lambda: len(g.de_tipo(MsgMarcador)) == 6)
    antes = len(g.todos())
    sim.emitir_crudo("ECHO ON\r\nCLIENT 1\r\n$Quote ABCD V:100\r\n")
    assert esperar(lambda: len(g.todos()) == antes + 3)
    nuevos = g.todos()[antes:]
    assert [type(m) for m in nuevos] == [MsgInformativo, MsgInformativo, MsgQuote]
    assert [m.cruda for m in nuevos] == ["ECHO ON", "CLIENT 1", "$Quote ABCD V:100"]


def test_das_fin_de_linea_solo_lf(fabrica, sim, libro):
    sim.fin_linea = "\n"
    libro.sembrar_posicion("ABCD", -100, Decimal("3.1"))
    c, g = fabrica()
    assert c.conectar()
    assert esperar(lambda: len(g.de_tipo(MsgMarcador)) == 6)
    assert g.de_tipo(MsgPos)[0].neta == -100
    sim.emitir("$Quote ABCD A:3.1")
    assert esperar(lambda: len(g.de_tipo(MsgQuote)) == 1)
    assert g.de_tipo(MsgQuote)[0].cruda == "$Quote ABCD A:3.1"
    assert all("\r" not in m.cruda and "\n" not in m.cruda for m in g.todos())


def test_das_notas_no_ascii_en_latin1(fabrica, sim):
    c, g = fabrica()
    assert c.conectar()
    assert esperar(lambda: len(g.de_tipo(MsgMarcador)) == 6)
    sim.emitir_crudo(b"%OrderAct 1001 Send_Rej Shrt ABCD 100 3.1 SAGEREB 09:30:00 Rechazo \xe9\xff\r\n")
    assert esperar(lambda: len(g.de_tipo(MsgOrderAct)) == 1)
    act = g.de_tipo(MsgOrderAct)[0]
    assert act.accion == "Send_Rej" and act.lado == "SS" and act.notas == "Rechazo \xe9\xff"


def test_das_buffer_sin_fin_de_linea_acotado(fabrica, sim):
    """Riesgo 17: un DAS que manda bytes sin '\\n' no hace crecer el buffer sin límite."""
    c, g = fabrica()
    assert c.conectar()
    assert esperar(lambda: len(g.de_tipo(MsgMarcador)) == 6)
    sim.emitir_crudo(b"A" * (TOPE_LINEA_BYTES + 100))
    assert esperar(lambda: any(isinstance(m, MsgDesconocido) and len(m.cruda) > TOPE_LINEA_BYTES
                               for m in g.todos()), plazo_s=5.0)
    sim.emitir_crudo("\r\nECHO ON\r\n")
    assert esperar(lambda: any(isinstance(m, MsgInformativo) and m.cruda == "ECHO ON" for m in g.todos()))
    assert all(len(m.cruda) <= TOPE_LINEA_BYTES + 4096 for m in g.todos())
    assert c.conectado and c.hilos_vivos


def test_das_al_mensaje_que_falla_no_deja_sordo_al_lector(sim, reloj):
    g = Grabadora()
    fallos = {"n": 0}

    def al_mensaje(msg: MensajeDAS) -> None:
        if fallos["n"] < 2:
            fallos["n"] += 1
            raise RuntimeError("callback roto")
        g.al_mensaje(msg)

    host, puerto = sim.direccion
    c = ClienteDAS(host, puerto, USUARIO, CLAVE, CUENTA, False, True, al_mensaje, g.al_estado, reloj,
                   al_caida_hilo=g.al_caida_hilo, timeout_s=1.0)
    try:
        assert c.conectar()
        assert esperar(lambda: any(isinstance(m, MsgMarcador) and m.nombre == "#TradeEnd" for m in g.todos()))
        assert fallos["n"] == 2
        assert g.caidas == [] and c.hilos_vivos
    finally:
        c.cerrar()


def test_das_hilo_caido_se_relanza_y_avisa(fabrica, sim, monkeypatch):
    """Injerto §8.11: una excepción en el lector llega a al_caida_hilo y el HiloVigilado lo relanza."""
    c, g = fabrica()
    original = ClienteDAS._entregar
    estado = {"roto": True}

    def entregar(self, s, cruda):
        if estado["roto"] and cruda.startswith(b"ECHO"):
            estado["roto"] = False
            raise RuntimeError("fallo inventado en el lector")
        return original(self, s, cruda)

    monkeypatch.setattr(ClienteDAS, "_entregar", entregar)
    assert c.conectar()
    assert esperar(lambda: len(g.de_tipo(MsgMarcador)) == 6)
    sim.emitir("ECHO ON")
    assert esperar(lambda: len(g.caidas) == 1)
    nombre, error, relanzado = g.caidas[0]
    assert nombre == "das-lector" and "fallo inventado" in error and relanzado is True
    sim.emitir("CLIENT 1")                          # tras el relanzamiento (1 s) el lector sigue leyendo
    assert esperar(lambda: any(m.cruda == "CLIENT 1" for m in g.todos()), plazo_s=4.0)
    assert c.hilos_vivos


# ══════════════════════════════════════════════════════════════════════
# Candado de la sombra: EnvioProhibido (R-O-03, §9, riesgo 10)
# ══════════════════════════════════════════════════════════════════════
def _variantes_mutantes() -> list:
    casos = []
    for palabra in sorted(MUTANTES):
        for nombre, forma in (("mayus", palabra), ("minus", palabra.lower()), ("mezcla", palabra.capitalize()),
                              ("espacios", "   " + palabra)):
            casos.append(pytest.param(f"{forma} 1 SS ABCD SAGEREB 100 3.1", id=f"R-O-03-{palabra}-{nombre}"))
    casos.append(pytest.param("SLPRICEINQUIRE ABCD 100 ALLROUTE", id="R-O-03-5.22-inquire-ALLROUTE"))
    casos.append(pytest.param("slpriceinquire ABCD 100 allroute", id="R-O-03-5.22-inquire-allroute-minus"))
    casos.append(pytest.param("GET BP\r\nNEWORDER 1 SS ABCD SAGEREB 100 3.1", id="R-O-03-riesgo10-mutante-escondido"))
    casos.append(pytest.param("GET BP\nCANCEL ALL", id="R-O-03-riesgo10-cancel-all-escondido"))
    return casos


@pytest.mark.parametrize("linea", _variantes_mutantes())
def test_das_solo_lectura_lanza_envio_prohibido_antes_de_encolar(suelto, linea):
    c, g = suelto
    with pytest.raises(EnvioProhibido):
        c.enviar(linea)
    assert c.pendientes == 0 and c.descartadas == 0 and g.avisos == []


def test_das_solo_lectura_contra_el_simulador_ningun_mutante_sale(fabrica, sim):
    c, g = fabrica(solo_lectura=True)
    assert c.conectar()
    for param in _variantes_mutantes():
        with pytest.raises(EnvioProhibido):
            c.enviar(param.values[0])
    for linea in ("GET BP", "SB ABCD Lv1", "GET SymStatus ABCD", "SLPRICEINQUIRE ABCD 100 ALLROUTEWTTYPE1",
                  "UNSB ABCD Lv1", "ECHO"):
        c.enviar(linea)
    assert esperar(lambda: "ECHO" in sim.recibidas())
    assert recibidas_sin_login(sim) == ["GET BP", "SB ABCD Lv1", "GET SymStatus ABCD",
                                        "SLPRICEINQUIRE ABCD 100 ALLROUTEWTTYPE1", "UNSB ABCD Lv1", "ECHO"]
    assert not any(es_mutante(x) for x in sim.recibidas())
    assert esperar(lambda: len(g.de_tipo(MsgBP)) == 1)


def test_das_cliente_con_ordenes_si_envia_mutantes(fabrica, sim, reloj):
    c, g = fabrica(solo_lectura=False)
    assert c.conectar()
    linea = linea_neworder(reloj, 1)
    c.enviar(linea)
    assert esperar(lambda: linea in sim.recibidas())
    assert esperar(lambda: any(isinstance(m, MsgOrden) and m.token == componer(Origen.EJECUTOR, 268, 1)
                               for m in g.todos()))


@pytest.mark.parametrize("linea,serie,version,error", [
    pytest.param(b"GET BP", None, 0, TypeError, id="3.2-bytes"),
    pytest.param(None, None, 0, TypeError, id="3.2-none"),
    pytest.param("", None, 0, ValueError, id="3.2-vacia"),
    pytest.param("   ", None, 0, ValueError, id="3.2-blancos"),
    pytest.param("GET BP\r\nGET TRADES", None, 0, ValueError, id="riesgo10-dos-comandos"),
    pytest.param("GET BP\n", None, 0, ValueError, id="riesgo10-salto-final"),
    pytest.param("SB ABCD Lv1\x0b", None, 0, ValueError, id="riesgo10-tab-vertical"),
    pytest.param("GET €", None, 0, ValueError, id="5.1-no-latin1"),
    pytest.param("GET BP", "", 0, ValueError, id="8.6-serie-vacia"),
    pytest.param("GET BP", 3, 0, ValueError, id="8.6-serie-no-texto"),
    pytest.param("GET BP", "stops:ABCD", "1", ValueError, id="8.6-version-texto"),
    pytest.param("GET BP", "stops:ABCD", True, ValueError, id="8.6-version-bool"),
])
def test_das_enviar_valida_la_linea(suelto, linea, serie, version, error):
    c, _g = suelto
    with pytest.raises(error):
        c.enviar(linea, serie, version)
    assert c.pendientes == 0


def test_das_sin_conexion_descarta_y_avisa_una_vez(suelto):
    c, g = suelto
    for _ in range(3):
        c.enviar("GET BP")
    assert c.pendientes == 0 and c.descartadas == 3
    assert len(g.avisos) == 1 and "sin conexión" in g.avisos[0]


# ══════════════════════════════════════════════════════════════════════
# Emisor: cuotas, invalidar y cola llena (riesgos 7, 11, 17)
# ══════════════════════════════════════════════════════════════════════
def test_das_emisor_respeta_la_cuota_51_ordenes(fabrica, sim, reloj):
    c, _g = fabrica(solo_lectura=False, cuota=CuotaComandos(reloj, margen=1.0))
    assert c.conectar()
    lineas = [linea_neworder(reloj, i) for i in range(1, 52)]
    for linea in lineas:
        c.enviar(linea)

    def neworders() -> list[str]:
        return [x for x in sim.recibidas() if x.startswith("NEWORDER")]

    assert esperar(lambda: len(neworders()) == 50)
    time.sleep(0.3)
    assert len(neworders()) == 50 and c.pendientes == 1   # la 51 espera: el reloj simulado no ha avanzado
    reloj.avanzar(1.0)
    assert esperar(lambda: len(neworders()) == 51)
    assert neworders() == lineas                    # en orden


def test_das_invalidar_descarta_replace_viejo_y_deja_pasar_el_nuevo(fabrica, sim):
    """Injerto A §8.6 / riesgo 7: un REPLACE encolado con la versión anterior no sale después del fill."""
    cuota = CuotaControlada(bloqueada=True)
    c, _g = fabrica(solo_lectura=False, cuota=cuota)
    assert c.conectar()
    viejo, nuevo = linea_replace_stop(100), linea_replace_stop(80)
    c.enviar(viejo, serie="stops:ABCD", version=0)
    c.enviar("GET BP")
    c.enviar(linea_replace_stop(60), serie="stops:WXYZ", version=0)     # otra serie: no se toca
    c.invalidar("stops:ABCD", 1)
    c.enviar(nuevo, serie="stops:ABCD", version=1)
    c.enviar(viejo, serie="stops:ABCD", version=0)  # llega tarde con la versión vieja: tampoco sale
    assert c.pendientes == 4                        # invalidar purgó la cola; la tardía la descarta el emisor
    cuota.bloqueada = False
    assert esperar(lambda: nuevo in sim.recibidas())
    time.sleep(0.2)
    assert recibidas_sin_login(sim) == ["GET BP", linea_replace_stop(60), nuevo]
    assert c.pendientes == 0


def test_das_invalidar_version_solo_sube(fabrica, sim):
    cuota = CuotaControlada(bloqueada=True)
    c, _g = fabrica(solo_lectura=False, cuota=cuota)
    assert c.conectar()
    c.invalidar("stops:ABCD", 5)
    c.invalidar("stops:ABCD", 2)                    # una invalidación más vieja no rebaja la vigente
    c.enviar(linea_replace_stop(90), serie="stops:ABCD", version=4)
    c.enviar(linea_replace_stop(70), serie="stops:ABCD", version=5)
    cuota.bloqueada = False
    assert esperar(lambda: linea_replace_stop(70) in sim.recibidas())
    time.sleep(0.1)
    assert recibidas_sin_login(sim) == [linea_replace_stop(70)]


@pytest.mark.parametrize("serie,version", [
    pytest.param("", 1, id="8.6-serie-vacia"),
    pytest.param(None, 1, id="8.6-serie-none"),
    pytest.param("stops:ABCD", 1.0, id="8.6-version-float"),
])
def test_das_invalidar_valida(suelto, serie, version):
    c, _g = suelto
    with pytest.raises(ValueError):
        c.invalidar(serie, version)


def test_das_cola_llena_no_bloquea_y_descarta_la_nueva(fabrica, sim):
    """Riesgo 17 y §3.2: con la cola llena el principal espera 50 ms una vez y descarta con aviso."""
    cuota = CuotaControlada(bloqueada=True)
    c, g = fabrica(cuota=cuota)
    assert c.conectar()
    t0 = time.perf_counter()
    for i in range(COLA_SALIDA_TOPE):
        c.enviar(f"SB T{i} Lv1")
    llenar_s = time.perf_counter() - t0
    assert c.pendientes == COLA_SALIDA_TOPE
    assert llenar_s < 1.0                           # 1.000 encolados sin bloquear
    t0 = time.perf_counter()
    c.enviar("GET BP")
    espera_s = time.perf_counter() - t0
    assert ESPERA_COLA_LLENA_S * 0.8 <= espera_s < 0.5
    assert c.pendientes == COLA_SALIDA_TOPE and c.descartadas == 1
    assert len(g.avisos) == 1 and "cola de salida llena" in g.avisos[0] and "GET BP" in g.avisos[0]
    cuota.bloqueada = False
    assert esperar(lambda: c.pendientes == 0, plazo_s=5.0)
    assert esperar(lambda: len(recibidas_sin_login(sim)) == COLA_SALIDA_TOPE)
    assert "GET BP" not in sim.recibidas()


def test_das_cola_llena_descarta_la_mas_vieja_de_la_misma_serie(fabrica, sim):
    """A-04 (corregido): con la cola llena solo se tira la más vieja de la serie con versión ANTERIOR a la nueva."""
    cuota = CuotaControlada(bloqueada=True)
    c, g = fabrica(solo_lectura=False, cuota=cuota, tope_cola=4)
    assert c.conectar()
    c.enviar("SB AAAA Lv1")
    c.enviar(linea_replace_stop(100), serie="stops:ABCD", version=0)
    c.enviar("SB BBBB Lv1")
    c.enviar(linea_replace_stop(90), serie="stops:ABCD", version=0)
    t0 = time.perf_counter()
    assert c.enviar(linea_replace_stop(80), serie="stops:ABCD", version=1) is True
    assert time.perf_counter() - t0 < ESPERA_COLA_LLENA_S   # había sitio que hacer: no espera
    assert c.pendientes == 4 and c.descartadas == 1
    assert len(g.avisos) == 1 and "serie stops:ABCD" in g.avisos[0]
    cuota.bloqueada = False
    assert esperar(lambda: c.pendientes == 0)
    assert esperar(lambda: len(recibidas_sin_login(sim)) == 4)
    assert recibidas_sin_login(sim) == ["SB AAAA Lv1", "SB BBBB Lv1", linea_replace_stop(90), linea_replace_stop(80)]


def test_A_04_cola_llena_no_tira_un_stop_hermano_de_la_misma_version(fabrica, sim, reloj):
    """A-04: dos NEWORDER de «stops:ABCD» v1 en la cola llena y llega un tercero v1 → no se tira ninguno de los dos."""
    cuota = CuotaControlada(bloqueada=True)
    c, g = fabrica(solo_lectura=False, cuota=cuota, tope_cola=2)
    assert c.conectar()
    primero, segundo, tercero = (linea_stop(reloj, i, "ABCD") for i in (1, 2, 3))
    assert c.enviar(primero, serie="stops:ABCD", version=1) is True
    assert c.enviar(segundo, serie="stops:ABCD", version=1) is True
    t0 = time.perf_counter()
    assert c.enviar(tercero, serie="stops:ABCD", version=1) is False     # G2-05: descartada la NUEVA, se sabe en el acto
    assert time.perf_counter() - t0 >= ESPERA_COLA_LLENA_S * 0.8         # esperó sus 50 ms antes de descartarla
    assert c.pendientes == 2 and c.descartadas == 1
    assert len(g.avisos) == 1 and "descartada la línea nueva" in g.avisos[0]
    cuota.bloqueada = False
    assert esperar(lambda: len([x for x in recibidas_sin_login(sim) if x.startswith("NEWORDER")]) == 2)
    assert recibidas_sin_login(sim) == [primero, segundo]


def test_A_04_D2a_06_cola_llena_la_version_vieja_purgada_avisa_al_decisor(fabrica, sim, reloj):
    """A-04 + D2a-06: el NEWORDER v0 que se tira para hacer sitio a una v1 llega como OrdenDescartada."""
    descartes: list[OrdenDescartada] = []
    cuota = CuotaControlada(bloqueada=True)
    c, _g = fabrica(solo_lectura=False, cuota=cuota, tope_cola=2, al_descartar=descartes.append)
    assert c.conectar()
    viejo = linea_stop(reloj, 1, "ABCD")
    c.enviar(viejo, serie="stops:ABCD", version=0)
    c.enviar("SB AAAA Lv1")
    assert c.enviar(linea_stop(reloj, 2, "ABCD"), serie="stops:ABCD", version=1) is True
    assert [(d.token, d.serie, d.version, d.ticker, d.motivo) for d in descartes] == [
        (componer(Origen.EJECUTOR, 268, 1), "stops:ABCD", 0, "ABCD", MOTIVO_COLA_LLENA)]


def test_get_identico_en_cola_no_se_repite(fabrica, sim):
    """Ensayo 28-sep: un `GET SymStatus X` por segundo y por ticker llenaba la cola de salida con consultas idénticas.
    Una consulta GET que ya espera en la cola no se encola otra vez (se cuenta en `deduplicadas`); los mutantes y las
    suscripciones sí se repiten."""
    cuota = CuotaControlada(bloqueada=True)
    c, g = fabrica(cuota=cuota)
    assert c.conectar()
    assert c.enviar("GET SymStatus ABCD") and c.enviar("GET SymStatus ABCD") and c.enviar("GET SymStatus ABCD")
    c.enviar("GET BP")
    c.enviar("SB ABCD Lv1")
    c.enviar("SB ABCD Lv1")
    assert c.pendientes == 4 and c.deduplicadas == 2 and c.descartadas == 0 and g.avisos == []
    cuota.bloqueada = False
    assert esperar(lambda: c.pendientes == 0, plazo_s=5.0)
    assert recibidas_sin_login(sim).count("GET SymStatus ABCD") == 1
    assert c.enviar("GET SymStatus ABCD") and esperar(lambda: recibidas_sin_login(sim).count("GET SymStatus ABCD") == 2)


def test_das_cola_llena_espera_y_entra_si_se_libera(fabrica, sim, monkeypatch):
    """§3.2: con la cola llena `enviar` espera (50 ms; aquí 0,5 s para no depender del planificador) y reintenta."""
    monkeypatch.setattr(cliente_mod, "ESPERA_COLA_LLENA_S", 0.5)
    cuota = CuotaControlada(bloqueada=True)
    c, g = fabrica(cuota=cuota, tope_cola=2)
    assert c.conectar()
    c.enviar("SB AAAA Lv1")
    c.enviar("SB BBBB Lv1")
    liberador = threading.Timer(0.01, lambda: setattr(cuota, "bloqueada", False))
    liberador.start()
    try:
        t0 = time.perf_counter()
        c.enviar("SB CCCC Lv1")                     # el emisor saca una durante la espera: entra
        assert time.perf_counter() - t0 < 0.5       # el hueco la despierta antes del plazo
    finally:
        liberador.join()
    assert esperar(lambda: "SB CCCC Lv1" in sim.recibidas())
    assert g.avisos == [] and c.descartadas == 0


# ══════════════════════════════════════════════════════════════════════
# A-01 / SEG-01: el emisor no se bloquea en cabeza
# ══════════════════════════════════════════════════════════════════════
def _agotar(cuota: CuotaComandos, comando: str) -> None:
    """Gasta toda la cabida de la categoría de `comando` en el instante actual del reloj simulado."""
    _ventana, cabida = cuota.limites[comando.split()[0].upper()]
    for _ in range(cabida):
        cuota.anotar(comando)
    assert cuota.espera_para(comando) > 0


def _mutantes_recibidos(sim) -> list[str]:
    return [x for x in recibidas_sin_login(sim) if es_mutante(x)]


def test_A_01_cancel_91_en_cabeza_no_retiene_el_neworder_stop_de_detras(fabrica, sim, reloj):
    """A-01 / SEG-01 (director): CANCEL nº 91 del minuto en cabeza y un NEWORDER STOPLMTP detrás → el NEWORDER sale ya."""
    cuota = CuotaComandos(reloj)
    _agotar(cuota, "CANCEL 1")
    c, _g = fabrica(solo_lectura=False, cuota=cuota)
    assert c.conectar()
    stop = linea_stop(reloj, 1, "WXYZ")
    assert c.enviar("CANCEL 424242") is True
    assert c.enviar(stop, serie="stops:WXYZ", version=0) is True
    assert esperar(lambda: stop in sim.recibidas(), plazo_s=2.0)          # sin mover el reloj
    assert "CANCEL 424242" not in sim.recibidas() and c.pendientes == 1   # el CANCEL sigue esperando su cuota
    reloj.avanzar(60.0)
    assert esperar(lambda: "CANCEL 424242" in sim.recibidas())
    assert _mutantes_recibidos(sim) == [stop, "CANCEL 424242"]


def test_A_01_replace_91_en_cabeza_no_retiene_el_stop_ni_el_get_de_otro_ticker(fabrica, sim, reloj):
    cuota = CuotaComandos(reloj)
    _agotar(cuota, "REPLACE 1 1 1")
    c, _g = fabrica(solo_lectura=False, cuota=cuota)
    assert c.conectar()
    replace = linea_replace_stop(80)
    stop = linea_stop(reloj, 2, "WXYZ")
    c.enviar(replace, serie="stops:ABCD", version=0)
    c.enviar(stop, serie="stops:WXYZ", version=0)
    c.enviar("GET POSITIONS")
    assert esperar(lambda: stop in sim.recibidas() and "GET POSITIONS" in sim.recibidas())
    assert replace not in sim.recibidas()
    reloj.avanzar(60.0)
    assert esperar(lambda: replace in sim.recibidas())


def test_SEG_01_dos_inquire_y_el_neworder_sale_antes_de_la_ventana(fabrica, sim, reloj):
    """SEG-01: SLPRICEINQUIRE ×2 y luego NEWORDER: el NEWORDER no espera los 3,33 s del segundo inquire."""
    c, _g = fabrica(solo_lectura=False, cuota=CuotaComandos(reloj))
    assert c.conectar()
    inquire_1 = "SLPRICEINQUIRE ABCD 100 ALLROUTEWTTYPE1"
    inquire_2 = "SLPRICEINQUIRE EFGH 100 ALLROUTEWTTYPE1"
    stop = linea_stop(reloj, 3, "ABCD")
    for linea in (inquire_1, inquire_2):
        c.enviar(linea)
    c.enviar(stop, serie="stops:ABCD", version=0)
    assert esperar(lambda: stop in sim.recibidas())
    assert inquire_1 in sim.recibidas() and inquire_2 not in sim.recibidas()
    reloj.avanzar(3.4)
    assert esperar(lambda: inquire_2 in sim.recibidas())


def test_A_01_misma_serie_no_adelanta_a_la_que_espera(fabrica, sim, reloj):
    """A-01: un NEWORDER de la MISMA serie que un REPLACE que espera cuota NO lo adelanta (orden dentro de la serie)."""
    cuota = CuotaComandos(reloj)
    _agotar(cuota, "REPLACE 1 1 1")
    c, _g = fabrica(solo_lectura=False, cuota=cuota)
    assert c.conectar()
    replace = linea_replace_stop(80)
    misma = linea_stop(reloj, 4, "ABCD")
    otra = linea_stop(reloj, 5, "WXYZ")
    c.enviar(replace, serie="stops:ABCD", version=0)
    c.enviar(misma, serie="stops:ABCD", version=0)
    c.enviar(otra, serie="stops:WXYZ", version=0)
    assert esperar(lambda: otra in sim.recibidas())
    time.sleep(0.2)
    assert misma not in sim.recibidas() and c.pendientes == 2
    reloj.avanzar(60.0)
    assert esperar(lambda: misma in sim.recibidas())
    assert _mutantes_recibidos(sim) == [otra, replace, misma]


def test_A_01_mismo_id_no_adelanta(fabrica, sim, reloj):
    """A-01: un CANCEL de la MISMA orden que un REPLACE que espera cuota no sale antes que él; el de otra orden sí."""
    cuota = CuotaComandos(reloj)
    _agotar(cuota, "REPLACE 1 1 1")
    c, _g = fabrica(solo_lectura=False, cuota=cuota)
    assert c.conectar()
    replace = linea_replace_stop(80)                  # REPLACE 1001 …
    c.enviar(replace)
    c.enviar("CANCEL 1001")
    c.enviar("CANCEL 2002")
    assert esperar(lambda: "CANCEL 2002" in sim.recibidas())
    time.sleep(0.2)
    assert "CANCEL 1001" not in sim.recibidas()
    reloj.avanzar(60.0)
    assert esperar(lambda: "CANCEL 1001" in sim.recibidas())
    assert _mutantes_recibidos(sim) == ["CANCEL 2002", replace, "CANCEL 1001"]


def test_A_01_mismo_ticker_por_el_id_aprendido_no_adelanta(fabrica, sim, reloj):
    """A-01: el lector aprende id → ticker de los %ORDER; un NEWORDER del MISMO ticker no adelanta al REPLACE de su orden.

    Si lo adelantara, un stop nuevo convivería con el viejo aún sin reducir: la cuenta podría quedar larga.
    """
    cuota = CuotaComandos(reloj)
    c, g = fabrica(solo_lectura=False, cuota=cuota)
    assert c.conectar()
    c.enviar(linea_stop(reloj, 6, "ABCD"))
    assert esperar(lambda: any(isinstance(m, MsgOrden) and m.ticker == "ABCD" for m in g.todos()))
    id_das = next(m.id for m in g.todos() if isinstance(m, MsgOrden) and m.ticker == "ABCD")
    _agotar(cuota, "REPLACE 1 1 1")
    replace = cmd_replace(id_das, 50, TipoOrden.STOP_LIMITE_PP, precio=Decimal("10"), stop=Decimal("9.9"))
    mismo_ticker = linea_stop(reloj, 7, "ABCD")
    otro_ticker = linea_stop(reloj, 8, "WXYZ")
    c.enviar(replace)                                 # sin serie: el orden lo da el ticker aprendido
    c.enviar(mismo_ticker)
    c.enviar(otro_ticker)
    assert esperar(lambda: otro_ticker in sim.recibidas())
    time.sleep(0.2)
    assert mismo_ticker not in sim.recibidas()
    reloj.avanzar(60.0)
    assert esperar(lambda: mismo_ticker in sim.recibidas())
    assert _mutantes_recibidos(sim)[1:] == [otro_ticker, replace, mismo_ticker]


def test_A_01_cancel_all_es_barrera_para_los_mutantes_no_para_las_lecturas(fabrica, sim, reloj):
    cuota = CuotaComandos(reloj)
    _agotar(cuota, "CANCEL 1")
    c, _g = fabrica(solo_lectura=False, cuota=cuota)
    assert c.conectar()
    stop = linea_stop(reloj, 9, "WXYZ")
    c.enviar("CANCEL ALL")
    c.enviar(stop)
    c.enviar("GET BP")
    assert esperar(lambda: "GET BP" in sim.recibidas())
    time.sleep(0.2)
    assert stop not in sim.recibidas()
    reloj.avanzar(60.0)
    assert esperar(lambda: stop in sim.recibidas())
    assert _mutantes_recibidos(sim) == ["CANCEL ALL", stop]


def test_A_01_cancel_allsymb_no_lo_adelanta_un_neworder_de_su_ticker(fabrica, sim, reloj):
    cuota = CuotaComandos(reloj)
    _agotar(cuota, "CANCEL 1")
    c, _g = fabrica(solo_lectura=False, cuota=cuota)
    assert c.conectar()
    mismo, otro = linea_stop(reloj, 10, "ABCD"), linea_stop(reloj, 11, "WXYZ")
    c.enviar("CANCEL ALLSYMB ABCD")
    c.enviar(mismo)
    c.enviar(otro)
    assert esperar(lambda: otro in sim.recibidas())
    time.sleep(0.2)
    assert mismo not in sim.recibidas()
    reloj.avanzar(60.0)
    assert esperar(lambda: mismo in sim.recibidas())
    assert _mutantes_recibidos(sim) == [otro, "CANCEL ALLSYMB ABCD", mismo]


# ══════════════════════════════════════════════════════════════════════
# D2a-06: nada se purga en silencio
# ══════════════════════════════════════════════════════════════════════
def test_D2a_06_invalidar_avisa_de_cada_neworder_purgado(fabrica, sim, reloj):
    """D2a-06: stop v0 encolado, fill → invalidar v1: la orden v0 llega al decisor como OrdenDescartada."""
    descartes: list[OrdenDescartada] = []
    cuota = CuotaControlada(bloqueada=True)
    c, _g = fabrica(solo_lectura=False, cuota=cuota, al_descartar=descartes.append)
    assert c.conectar()
    stop_v0 = linea_stop(reloj, 1, "ABCD")
    c.enviar(stop_v0, serie="stops:ABCD", version=0)
    c.enviar(linea_replace_stop(90), serie="stops:ABCD", version=0)    # REPLACE: sin token, no hay nada que cerrar
    c.enviar(linea_stop(reloj, 2, "WXYZ"), serie="stops:WXYZ", version=0)
    c.invalidar("stops:ABCD", 1)
    assert descartes == [OrdenDescartada(token=componer(Origen.EJECUTOR, 268, 1), serie="stops:ABCD", version=0,
                                         motivo=MOTIVO_VERSION, ticker="ABCD")]
    assert c.pendientes == 1
    cuota.bloqueada = False
    assert esperar(lambda: c.pendientes == 0)
    assert stop_v0 not in sim.recibidas()


def test_D2a_06_el_emisor_avisa_del_neworder_que_llega_tarde_con_version_vieja(fabrica, sim, reloj):
    descartes: list[OrdenDescartada] = []
    cuota = CuotaControlada(bloqueada=True)
    c, _g = fabrica(solo_lectura=False, cuota=cuota, al_descartar=descartes.append)
    assert c.conectar()
    c.invalidar("stops:ABCD", 3)
    tardio = linea_stop(reloj, 4, "ABCD")
    assert c.enviar(tardio, serie="stops:ABCD", version=2) is True       # encolada: la purga el emisor
    cuota.bloqueada = False
    assert esperar(lambda: len(descartes) == 1)
    assert (descartes[0].token, descartes[0].version, descartes[0].motivo) == (
        componer(Origen.EJECUTOR, 268, 4), 2, MOTIVO_VERSION)
    time.sleep(0.1)
    assert tardio not in sim.recibidas() and c.pendientes == 0


def test_D2a_06_G2_05_corte_avisa_de_los_neworder_que_no_salieron(fabrica, sim, reloj):
    """D2a-06 / G2-05: al caer la sesión, los NEWORDER encolados se comunican; lo descartado en `enviar` devuelve False."""
    descartes: list[OrdenDescartada] = []
    cuota = CuotaControlada(bloqueada=True)
    c, _g = fabrica(solo_lectura=False, cuota=cuota, al_descartar=descartes.append)
    assert c.conectar()
    c.enviar(linea_stop(reloj, 1, "ABCD"), serie="stops:ABCD", version=0)
    c.enviar("GET BP")
    sim.cortar()
    assert esperar(lambda: not c.conectado)
    assert [(d.token, d.motivo) for d in descartes] == [(componer(Origen.EJECUTOR, 268, 1), MOTIVO_SESION)]
    assert c.enviar(linea_stop(reloj, 2, "ABCD"), serie="stops:ABCD", version=0) is False   # sin conexión
    assert len(descartes) == 1                       # lo descartado en el acto NO pasa por al_descartar (sin bucles)


def test_D2a_06_al_descartar_que_falla_no_para_el_cliente(fabrica, sim, reloj):
    def roto(_d: OrdenDescartada) -> None:
        raise RuntimeError("callback roto")

    cuota = CuotaControlada(bloqueada=True)
    c, _g = fabrica(solo_lectura=False, cuota=cuota, al_descartar=roto)
    assert c.conectar()
    c.enviar(linea_stop(reloj, 1, "ABCD"), serie="stops:ABCD", version=0)
    c.invalidar("stops:ABCD", 1)                      # no lanza
    cuota.bloqueada = False
    c.enviar("GET BP")
    assert esperar(lambda: "GET BP" in sim.recibidas())
    assert c.hilos_vivos


def test_D2a_06_al_descartar_debe_ser_funcion(reloj):
    with pytest.raises(TypeError, match="al_descartar"):
        ClienteDAS("127.0.0.1", 9, USUARIO, CLAVE, CUENTA, False, True, lambda m: None, lambda e, m: None, reloj,
                   al_descartar=3)


def test_G2_05_enviar_devuelve_true_si_encola(fabrica, sim):
    c, _g = fabrica()
    assert c.conectar()
    assert c.enviar("GET BP") is True


# ══════════════════════════════════════════════════════════════════════
# Corte, reconexión y cierre (R-J-02)
# ══════════════════════════════════════════════════════════════════════
def test_das_corte_avisa_y_reconecta(fabrica, sim):
    c, g = fabrica()
    assert c.conectar()
    assert esperar(lambda: c.logon["OrderServer"] is True)
    sim.cortar()
    assert esperar(lambda: any(estado is False for estado, _ in g.estados))
    assert [e for e, _ in g.estados] == [True, False]
    assert "EOF" in g.estados[1][1] or "lectura" in g.estados[1][1]
    assert not c.conectado
    assert esperar(lambda: not hilos_del_cliente_vivos())
    assert c.hilos_vivos                            # sin conexión: nada que deba correr (no para el latido)
    c.enviar("GET BP")                              # sin conexión: descartada con aviso
    assert c.descartadas == 1 and any("sin conexión" in a for a in g.avisos)
    assert c.conectar() is True
    assert esperar(lambda: c.logon["OrderServer"] is True)
    assert [e for e, _ in g.estados] == [True, False, True]
    assert [x for x in sim.recibidas() if x.startswith("LOGIN")] == [f"LOGIN {USUARIO} {CLAVE} {CUENTA} 0"] * 2
    c.enviar("GET BP")
    assert esperar(lambda: "GET BP" in sim.recibidas())
    assert c.hilos_vivos and hilos_del_cliente_vivos()


def test_das_corte_vacia_la_cola_y_nada_sale_al_reconectar(fabrica, sim):
    """R-J-02.5: lo encolado antes del corte NO sale en la sesión nueva (antes va la reconciliación)."""
    cuota = CuotaControlada(bloqueada=True)
    c, g = fabrica(solo_lectura=False, cuota=cuota)
    assert c.conectar()
    for linea in ("GET BP", "CANCEL 1001", "SB ABCD Lv1"):
        c.enviar(linea)
    assert c.pendientes == 3
    sim.cortar()
    assert esperar(lambda: not c.conectado)
    assert c.pendientes == 0 and c.descartadas == 3
    assert esperar(lambda: any("3 líneas pendientes descartadas" in a for a in g.avisos))
    cuota.bloqueada = False
    assert c.conectar()
    c.enviar("ECHO")
    assert esperar(lambda: "ECHO" in sim.recibidas())
    assert recibidas_sin_login(sim) == ["ECHO"]


def test_das_cerrar_manda_quit_y_no_llama_a_al_estado(fabrica, sim):
    c, g = fabrica()
    assert c.conectar()
    assert esperar(lambda: sim.n_conexiones == 1)
    c.cerrar()
    assert esperar(lambda: "QUIT" in sim.recibidas())
    assert not c.conectado
    assert g.estados == [(True, f"conectado a {sim.direccion[0]}:{sim.direccion[1]}")]
    assert esperar(lambda: not hilos_del_cliente_vivos())
    c.cerrar()                                      # idempotente
    assert c.conectar()                             # y se puede volver a conectar
    assert esperar(lambda: sim.n_conexiones == 1)


def test_das_cerrar_sin_conectar_no_hace_nada(suelto):
    c, g = suelto
    c.cerrar()
    assert g.estados == [] and not c.conectado


# ══════════════════════════════════════════════════════════════════════
# Secretos (R-Q-01, riesgo 20)
# ══════════════════════════════════════════════════════════════════════
def test_das_la_clave_nunca_llega_al_log(fabrica, sim, caplog):
    caplog.set_level(logging.DEBUG, logger="app.bot_das.cliente")
    c, g = fabrica()
    assert c.conectar()
    c.enviar("GET BP")
    assert esperar(lambda: "GET BP" in sim.recibidas())
    sim.cortar()
    assert esperar(lambda: not c.conectado)
    assert CLAVE not in caplog.text
    assert f"LOGIN {USUARIO} *****" in caplog.text
    assert "GET BP" in caplog.text


def test_das_constructor_no_muestra_la_clave_en_el_error(reloj):
    g = Grabadora()
    with pytest.raises(ValueError) as exc:
        ClienteDAS("127.0.0.1", 9, USUARIO, "clave con espacios secreta", CUENTA, False, True,
                   g.al_mensaje, g.al_estado, reloj)
    assert "secreta" not in str(exc.value) and "clave" in str(exc.value)


@pytest.mark.parametrize("kw,error", [
    pytest.param({"puerto": 0}, ValueError, id="3.2-puerto-0"),
    pytest.param({"puerto": 70000}, ValueError, id="3.2-puerto-grande"),
    pytest.param({"puerto": "9800"}, ValueError, id="3.2-puerto-texto"),
    pytest.param({"host": ""}, ValueError, id="3.2-host-vacio"),
    pytest.param({"usuario": ""}, ValueError, id="L243-usuario-vacio"),
    pytest.param({"cuenta": "CUENTA PRUEBA"}, ValueError, id="L243-cuenta-con-espacio"),
    pytest.param({"al_mensaje": None}, TypeError, id="3.2-al-mensaje"),
    pytest.param({"reloj": object()}, TypeError, id="3.2-reloj"),
    pytest.param({"cuota": object()}, TypeError, id="3.2-cuota"),
    pytest.param({"timeout_s": 0}, ValueError, id="3.2-timeout-0"),
    pytest.param({"tope_cola": 0}, ValueError, id="riesgo17-tope-0"),
    pytest.param({"parser": object()}, TypeError, id="3.1-parser"),
])
def test_das_constructor_valida(reloj, kw, error):
    g = Grabadora()
    args = {"host": "127.0.0.1", "puerto": 9, "usuario": USUARIO, "clave": CLAVE, "cuenta": CUENTA, "watch": False,
            "solo_lectura": True, "al_mensaje": g.al_mensaje, "al_estado": g.al_estado, "reloj": reloj}
    args.update(kw)
    with pytest.raises(error):
        ClienteDAS(**args)


# ══════════════════════════════════════════════════════════════════════
# desde_env: segundo candado (corrección 15)
# ══════════════════════════════════════════════════════════════════════
def _entorno_das(monkeypatch, puerto: Optional[str] = "9800", **extra: str) -> None:
    if puerto is not None:
        monkeypatch.setenv("DAS_API_PORT", puerto)
    monkeypatch.setenv("DAS_USUARIO", USUARIO)
    monkeypatch.setenv("DAS_CLAVE", CLAVE)
    monkeypatch.setenv("DAS_CUENTA", CUENTA)
    for nombre, valor in extra.items():
        monkeypatch.setenv(nombre, valor)


def _kw(reloj) -> dict:
    g = Grabadora()
    return {"al_mensaje": g.al_mensaje, "al_estado": g.al_estado, "reloj": reloj}


@pytest.mark.parametrize("valor", [
    pytest.param(None, id="correccion15-sin-variable"),
    pytest.param("0", id="correccion15-cero"),
    pytest.param("true", id="correccion15-true"),
    pytest.param("", id="correccion15-vacia"),
])
def test_das_desde_env_sin_permiso_no_construye_cliente_de_ordenes(monkeypatch, reloj, valor):
    _entorno_das(monkeypatch)
    if valor is not None:
        monkeypatch.setenv("BOT_DAS_PERMITIR_ORDENES", valor)
    with pytest.raises(RuntimeError, match="BOT_DAS_PERMITIR_ORDENES"):
        ClienteDAS.desde_env(watch=False, solo_lectura=False, **_kw(reloj))


def test_das_desde_env_con_permiso_construye(monkeypatch, reloj):
    _entorno_das(monkeypatch, BOT_DAS_PERMITIR_ORDENES="1")
    c = ClienteDAS.desde_env(watch=False, solo_lectura=False, **_kw(reloj))
    assert isinstance(c, ClienteDAS) and not c.solo_lectura and c.cuenta == CUENTA and not c.conectado


def test_das_desde_env_solo_lectura_no_necesita_permiso(monkeypatch, reloj):
    _entorno_das(monkeypatch)
    c = ClienteDAS.desde_env(watch=True, solo_lectura=True, **_kw(reloj))
    assert c.solo_lectura and c.watch


@pytest.mark.parametrize("puerto", [
    pytest.param(None, id="3.2-DAS_API_PORT-ausente"),
    pytest.param("", id="3.2-DAS_API_PORT-vacio"),
    pytest.param("abc", id="3.2-DAS_API_PORT-texto"),
    pytest.param("0", id="3.2-DAS_API_PORT-cero"),
    pytest.param("70000", id="3.2-DAS_API_PORT-grande"),
])
def test_das_desde_env_puerto_obligatorio_y_valido(monkeypatch, reloj, puerto):
    _entorno_das(monkeypatch, puerto=puerto)
    with pytest.raises(RuntimeError, match="DAS_API_PORT"):
        ClienteDAS.desde_env(watch=False, solo_lectura=True, **_kw(reloj))


@pytest.mark.parametrize("falta", ["DAS_USUARIO", "DAS_CLAVE", "DAS_CUENTA"])
def test_das_desde_env_credenciales_obligatorias(monkeypatch, reloj, falta):
    _entorno_das(monkeypatch)
    monkeypatch.delenv(falta)
    with pytest.raises(RuntimeError, match=falta):
        ClienteDAS.desde_env(watch=False, solo_lectura=True, **_kw(reloj))


def test_das_desde_env_clave_invalida_no_se_muestra(monkeypatch, reloj):
    _entorno_das(monkeypatch)
    monkeypatch.setenv("DAS_CLAVE", "dos palabras-secretas")
    with pytest.raises(RuntimeError) as exc:
        ClienteDAS.desde_env(watch=False, solo_lectura=True, **_kw(reloj))
    assert "secretas" not in str(exc.value) and "secretas" not in repr(exc.value.__cause__)


def test_das_desde_env_lee_el_entorno_en_la_llamada_y_conecta(monkeypatch, sim, reloj):
    host, puerto = sim.direccion
    _entorno_das(monkeypatch, puerto=str(puerto))    # host por defecto: 127.0.0.1
    g = Grabadora()
    c = ClienteDAS.desde_env(watch=False, solo_lectura=True, al_mensaje=g.al_mensaje, al_estado=g.al_estado,
                             reloj=reloj, timeout_s=1.0)
    try:
        assert c.conectar()
        assert esperar(lambda: c.logon["OrderServer"] is True)
        assert sim.recibidas()[0] == f"LOGIN {USUARIO} {CLAVE} {CUENTA} 0"
    finally:
        c.cerrar()


# ══════════════════════════════════════════════════════════════════════
# ClienteSombra (R-O-03, §9)
# ══════════════════════════════════════════════════════════════════════
class GrabadoraSombra:
    def __init__(self) -> None:
        self.mensajes: list[tuple[MensajeDAS, bool]] = []

    def al_mensaje(self, msg: MensajeDAS, simulado: bool) -> None:
        self.mensajes.append((msg, simulado))

    def de_tipo(self, clase: type) -> list:
        return [m for m, _ in self.mensajes if isinstance(m, clase)]


@pytest.fixture
def sombra(fabrica, reloj):
    """(ClienteSombra conectado al simulador, GrabadoraSombra, Grabadora del real, libro del emparejador)."""
    real, g_real = fabrica(solo_lectura=True)
    libro_sombra = simulador_das.LibroSimulado()
    libro_sombra.cotizar("ABCD", Decimal("3.00"), Decimal("3.02"))
    emparejador = simulador_das.Emparejador(libro_sombra, reloj)
    gs = GrabadoraSombra()
    cliente = ClienteSombra(real, emparejador, gs.al_mensaje)
    assert cliente.conectar()
    return cliente, gs, g_real, libro_sombra


def test_das_sombra_exige_cliente_de_solo_lectura(fabrica, reloj):
    real, _g = fabrica(solo_lectura=False)
    emparejador = simulador_das.Emparejador(simulador_das.LibroSimulado(), reloj)
    with pytest.raises(ValueError, match="solo lectura"):
        ClienteSombra(real, emparejador, lambda m, s: None)


def test_das_sombra_valida_argumentos(fabrica, reloj):
    real, _g = fabrica()
    emparejador = simulador_das.Emparejador(simulador_das.LibroSimulado(), reloj)
    with pytest.raises(TypeError):
        ClienteSombra(object(), emparejador, lambda m, s: None)
    with pytest.raises(TypeError):
        ClienteSombra(real, object(), lambda m, s: None)
    with pytest.raises(TypeError):
        ClienteSombra(real, emparejador, None)


def test_das_sombra_mutantes_al_emparejador_y_ninguno_al_das(sombra, sim, reloj):
    cliente, gs, g_real, libro_sombra = sombra
    token = componer(Origen.EJECUTOR, 268, 7)
    cliente.enviar(linea_neworder(reloj, 7, precio="2.99"))      # SS 100 a 2,99 ≤ bid 3,00: se llena al bid
    assert gs.mensajes and all(simulado is True for _m, simulado in gs.mensajes)
    acciones = [m.accion for m in gs.de_tipo(MsgOrderAct)]
    assert acciones[:2] == ["Sending", "Accept"] and "Execute" in acciones
    assert any(m.token == token for m in gs.de_tipo(MsgOrden))
    trade = gs.de_tipo(MsgTrade)
    assert len(trade) == 1 and trade[0].qty == 100 and trade[0].precio == Decimal("3.00")
    assert gs.de_tipo(MsgPos)[-1].neta == -100
    assert libro_sombra.posiciones() == {"ABCD": -100}
    cliente.enviar("GET BP")                        # lectura: al DAS real
    assert esperar(lambda: "GET BP" in sim.recibidas())
    assert esperar(lambda: len(g_real.de_tipo(MsgBP)) == 1)
    assert not any(es_mutante(x) for x in sim.recibidas())
    assert sim.libro.ordenes() == []


def test_das_sombra_linea_con_mutante_escondido_no_llega_al_das(sombra, sim):
    cliente, gs, _g_real, _libro = sombra
    cliente.enviar("GET BP\r\nCANCEL ALL")
    assert gs.mensajes and all(s for _m, s in gs.mensajes)
    time.sleep(0.1)
    assert recibidas_sin_login(sim) == []


def test_das_sombra_tic_llena_lo_que_reposa(sombra, reloj):
    cliente, gs, _g_real, libro_sombra = sombra
    cliente.enviar(linea_neworder(reloj, 8, precio="3.1"))       # SS a 3,10 > bid 3,00: reposa
    assert gs.de_tipo(MsgTrade) == []
    libro_sombra.cotizar("ABCD", Decimal("3.10"), Decimal("3.12"))
    cliente.tic()
    trade = gs.de_tipo(MsgTrade)
    assert len(trade) == 1 and trade[0].precio == Decimal("3.1")
    assert all(s for _m, s in gs.mensajes)


def test_das_sombra_al_mensaje_que_falla_no_pierde_los_siguientes(fabrica, reloj):
    real, _g = fabrica()
    libro_sombra = simulador_das.LibroSimulado()
    libro_sombra.cotizar("ABCD", Decimal("3.00"), Decimal("3.02"))
    vistos: list[MensajeDAS] = []

    def al_mensaje(msg: MensajeDAS, simulado: bool) -> None:
        vistos.append(msg)
        if len(vistos) == 1:
            raise RuntimeError("callback roto")

    cliente = ClienteSombra(real, simulador_das.Emparejador(libro_sombra, reloj), al_mensaje)
    cliente.enviar(linea_neworder(reloj, 9, precio="2.99"))
    assert len(vistos) > 3 and any(isinstance(m, MsgTrade) for m in vistos)


def test_A_07_sombra_cuenta_la_cuota_agotada_sin_esperar(fabrica, reloj):
    """A-07: en sombra el mutante nº 46 del segundo (cabida 45 al 90 %) se cuenta y se avisa, pero NO espera."""
    real, _g = fabrica()
    libro_sombra = simulador_das.LibroSimulado()
    agotadas: list[tuple[str, float]] = []
    cliente = ClienteSombra(real, simulador_das.Emparejador(libro_sombra, reloj), lambda m, s: None,
                            al_cuota_agotada=lambda linea, espera: agotadas.append((linea, espera)))
    _ventana, cabida = CuotaComandos(reloj).limites["NEWORDER"]
    t0 = time.perf_counter()
    for i in range(1, cabida + 2):
        assert cliente.enviar(linea_neworder(reloj, i, precio="3.1")) is True
    assert time.perf_counter() - t0 < 1.0             # nunca espera
    assert cliente.cuota_agotada == 1
    assert len(agotadas) == 1 and agotadas[0][0].startswith("NEWORDER") and 0 < agotadas[0][1] <= 1.0
    assert len(libro_sombra.ordenes()) == cabida + 1  # todas llegaron al emparejador
    reloj.avanzar(1.0)
    cliente.enviar(linea_neworder(reloj, 99, precio="3.1"))
    assert cliente.cuota_agotada == 1                 # pasado el segundo vuelve a caber


def test_A_07_sombra_cuota_de_cancel_por_minuto(fabrica, reloj):
    real, _g = fabrica()
    cuota = CuotaComandos(reloj)
    cliente = ClienteSombra(real, simulador_das.Emparejador(simulador_das.LibroSimulado(), reloj),
                            lambda m, s: None, cuota=cuota)
    _ventana, cabida = cuota.limites["CANCEL"]
    for _ in range(cabida + 3):
        cliente.enviar("CANCEL 424242")
    assert cliente.cuota_agotada == 3


def test_A_07_sombra_valida_la_cuota(fabrica, reloj):
    real, _g = fabrica()
    emparejador = simulador_das.Emparejador(simulador_das.LibroSimulado(), reloj)
    with pytest.raises(TypeError, match="cuota"):
        ClienteSombra(real, emparejador, lambda m, s: None, cuota=object())
    with pytest.raises(ValueError, match="cuota"):
        ClienteSombra(real, emparejador, lambda m, s: None, cuota=real._cuota)
    with pytest.raises(TypeError, match="al_cuota_agotada"):
        ClienteSombra(real, emparejador, lambda m, s: None, al_cuota_agotada=3)


def test_A_07_sombra_al_cuota_agotada_que_falla_no_para_la_simulacion(fabrica, reloj):
    real, _g = fabrica()
    libro_sombra = simulador_das.LibroSimulado()

    def roto(_linea: str, _espera: float) -> None:
        raise RuntimeError("callback roto")

    cliente = ClienteSombra(real, simulador_das.Emparejador(libro_sombra, reloj), lambda m, s: None,
                            al_cuota_agotada=roto)
    for _ in range(3):
        cliente.enviar("SLPRICEINQUIRE ABCD 100 ALLROUTE")      # mutante en sombra; 1 cada 3,33 s
    assert cliente.cuota_agotada == 2


def test_das_sombra_delega_en_el_real(sombra, sim):
    cliente, _gs, g_real, _libro = sombra
    assert cliente.conectado and cliente.hilos_vivos
    assert esperar(lambda: cliente.logon == {"OrderServer": True, "QuoteServer": True})
    assert cliente.ultimo_recibido_en is not None
    cliente.invalidar("stops:ABCD", 3)              # no lanza: va al real
    cliente.cerrar()
    assert not cliente.conectado
    assert esperar(lambda: "QUIT" in sim.recibidas())
    assert [e for e, _ in g_real.estados] == [True]


# ══════════════════════════════════════════════════════════════════════
# Importar no ejecuta nada (§12 criterio de «hecho» 2)
# ══════════════════════════════════════════════════════════════════════
def test_das_importar_cliente_no_abre_nada():
    codigo = ("import sys, threading; import app.bot_das.cliente; "
              "print(threading.active_count(), 'pandas' in sys.modules, 'httpx' in sys.modules, "
              "'app.bot_das.simulador_das' in sys.modules)")
    salida = subprocess.run([sys.executable, "-c", codigo], cwd=str(BACKEND), capture_output=True, text=True,
                            timeout=60)
    assert salida.returncode == 0, salida.stderr
    assert salida.stdout.split() == ["1", "False", "False", "False"]
