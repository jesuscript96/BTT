"""Tests del decisor (lote G1): los flujos F1-F14 de §5 contra un DAS falso, con reloj simulado y sin red.

QUÉ PRUEBA. El decisor de verdad (`app.bot_das.decisor.Decisor`) con TODAS sus
piezas reales: `MercadoDAS` alimentado con `$Quote`, `Referencia` de Massive
con un `abrir` falso (fichas y splits en memoria), el catálogo de rechazos
real y el `Emparejador` del simulador como DAS (cada acción del decisor se
serializa con `protocolo.cmd_*`, el Emparejador contesta con líneas de DAS y
esas líneas vuelven al decisor parseadas por `protocolo.Parser`, como hará el
ejecutor). Flujo a flujo: F1 exacto, las seis permutaciones de
`%OrderAct`/`%TRADE`/`%POS`, F2 (parcial del stop único de Jaume 29-sep:
sigue vivo con lo que queda, nunca otra compra), F3 (dos señales con el intento vivo), F4 (TP con prioridad sobre la
entrada), F5 (hora y EOD con persecución y control humano), F6 (halt con la
guardia de la MKT), F7 (cisne negro, informes y cierre humano), F8
(rechazos), F9 (locates de dos estrategias), F10 (los seis casos de la
reconciliación), F11 (modos degradados), F12/F13 (arranque desde el diario)
y F14 (estrategia desactivada). Y las trampas: H-5, señal repetida,
multicuenta, largo con corto abierto, config en caliente, fill con un
REPLACE pendiente, grupo A primero, comandos de R-M-04 y la coherencia con
`diario.reconstruir` (H-2). Al final, un escenario por cada hallazgo de la
revisión del 27-sep (el id va en el nombre del test: halt escenario 2 con
los stops reducidos y restaurados, cisne negro + halt, rearranque con EOD
vencido, intento cancelado al quedar plana la posición, dos /cerrar
seguidos, TP antes que la entrada, OrdenDescartada, referencia lenta…).

`Banco` hace también de hilo «referencia» del ejecutor (G1A-03): entre
mensajes precarga los splits del día y las fichas que el decisor pidió.

POR QUÉ ASÍ. El decisor es puro respecto a la E/S: `Banco` hace de
ejecutor (ejecuta las acciones en orden, guarda los temporizadores y los
dispara con el reloj simulado, manda `Tic` y el latido del feed) y de DAS
(el Emparejador). Así los flujos se prueban de punta a punta sin sockets ni
hilos, deterministas y en milisegundos.

LAS TRAMPAS.
  * Ninguna credencial real: la «clave» de Massive es un texto inventado que
    solo sirve para que `Referencia` llame a su `abrir` falso; la cuenta es
    la del simulador (CUENTA_PRUEBA) y el chat_id (111) es inventado.
  * El calendario es `CalendarioPrueba` (franja por la hora): el de verdad
    lanzaría un hilo que pregunta a Massive.
  * `Banco.das_contesta = False` corta el DAS falso: las acciones se graban
    pero no llegan al Emparejador (para provocar carreras a propósito).
  * El `Evento` es el REAL del bot de alertas (con `pd.Timestamp`) y el id el
    de `fuente_senales.id_de_evento` (R-A-05).
"""
from __future__ import annotations

import dataclasses
import json
import re
import subprocess
import sys
from collections import deque
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Optional

import pandas as pd
import pytest

from app.bot_das import comandos, protocolo
from app.bot_das.decisor import (
    MOTIVO_CRUCE_ESPERA,
    T_BARRIDO,
    T_CRUCE,
    T_EOD_COMPROBAR,
    T_HORA_AGREGAR,
    T_HORA_ASK,
    Decisor,
)
from app.bot_das.diario import a_json_seguro, reconstruir
from app.bot_das.fuente_senales import id_de_evento
from app.bot_das.mercado_das import MercadoDAS
from app.bot_das.referencia_massive import Referencia
from app.bot_das.reglas import cisne_negro, entrada as reglas_entrada, rechazos
from app.bot_das.reloj import ET, RelojSimulado
from app.bot_das.simulador_das import Emparejador, LibroSimulado
from app.bot_das.tipos import (
    Accion,
    Anotar,
    Avisar,
    Cancelar,
    CancelarTicker,
    ComandoRecibido,
    ConexionDAS,
    Config,
    ConfigNueva,
    Consultar,
    DeDAS,
    Desprogramar,
    EnviarOrden,
    EstadoBot,
    EstadoLote,
    EstadoOrden,
    EstadoTicker,
    EstrategiaConfig,
    Fase,
    Fill,
    Grupo,
    HiloCaido,
    InvalidarSerie,
    Lado,
    Locate,
    LocateCancelar,
    LocateComprar,
    LocateInquire,
    LocateOferta,
    Lote,
    Mensaje,
    MsgSLAvail,
    Nivel,
    Orden,
    OrdenDescartada,
    OrdenNueva,
    Origen,
    PosicionTicker,
    Programar,
    Proposito,
    PublicarFoto,
    Registro,
    Reemplazar,
    Senal,
    SenalRecibida,
    Suscribir,
    Temporizador,
    Tic,
    TipoOrden,
)
from app.bot_das.tokens import GeneradorTokens, descomponer, es_nuestro
from app.services.bot_alerts_engine import Evento
from canal_falso import CanalFalso

D = Decimal
INICIO = datetime(2026, 9, 25, 9, 30, tzinfo=ET)            # viernes con sesión (RTH)
HOY = INICIO.date()
TICKER = "XYZ"
OTRO = "ABC"
SID = "prueba-1"
SID2 = "prueba-2"
CUENTA = "CUENTA_PRUEBA"                                     # la del simulador: inventada
CHAT = 111                                                   # chat_id inventado
AUTORIZADOS = frozenset({CHAT})
CLAVE_MASSIVE = "clave-inventada-solo-para-tests"            # no es una credencial: solo activa el `abrir` falso
ORDEN_DEFECTO = ("OrderAct", "TRADE", "POS")
PERMUTACIONES = [
    ("OrderAct", "TRADE", "POS"), ("OrderAct", "POS", "TRADE"), ("TRADE", "OrderAct", "POS"),
    ("TRADE", "POS", "OrderAct"), ("POS", "OrderAct", "TRADE"), ("POS", "TRADE", "OrderAct"),
]
HASH_B = "sha256:" + "b" * 64
STOPS = (Proposito.STOP, Proposito.STOP_PROTECCION)            # stop único (Jaume 29-sep, R-C-01 v4)
# D2-09: el catálogo real ya no tiene ninguna entrada «reintentar» (PostOnly pasa al cruce); la mecánica del
# reintento con token nuevo se prueba con una entrada sintética delante de las reales
CATALOGO_CON_REINTENTO = rechazos.validar_catalogo(
    [{"clave": "rechazo_de_prueba", "regex": r"rechazo\s+de\s+prueba", "accion": "reintentar", "nivel": 2,
      "fuente": "test_das_decisor (entrada sintética)", "ejemplos": ["Rechazo de prueba"]}]
    + rechazos.cargar_catalogo(rechazos.RUTA_CATALOGO))


# ═══════════════════════════ dobles: calendario y Massive ════════════════
class CalendarioPrueba:
    """Franja de mercado por la hora ET, sin festivos ni red (el real lanza un hilo contra Massive)."""

    def __init__(self, media_sesion: bool = False) -> None:
        self._media = media_sesion

    def franja_de_mercado(self, ahora: datetime) -> str:
        minutos = ahora.hour * 60 + ahora.minute
        if 4 * 60 <= minutos < 9 * 60 + 30:
            return "premercado"
        if 9 * 60 + 30 <= minutos < 16 * 60:
            return "RTH"
        if 16 * 60 <= minutos < 20 * 60:
            return "postmercado"
        return "cerrado"

    def media_sesion(self, dia) -> Optional[str]:
        return "media sesión de prueba" if self._media else None


class _Respuesta:
    def __init__(self, cuerpo: bytes) -> None:
        self._cuerpo = cuerpo

    def read(self) -> bytes:
        return self._cuerpo

    def close(self) -> None:
        return None


class MassiveFalso:
    """El `abrir(Request, timeout=)` de `Referencia`: fichas y splits en memoria; lo que no sabe es un error de red."""

    def __init__(self, splits: tuple = (), falla_splits: bool = False) -> None:
        ficha = {"list_date": "2020-01-01", "sic_code": "1234", "type": "CS", "name": "Prueba SA", "market_cap": 1e8}
        self.fichas = {TICKER: dict(ficha), OTRO: dict(ficha)}
        self.splits = list(splits)
        self.falla_splits = falla_splits
        self.urls: list[str] = []

    def __call__(self, peticion: Any, timeout: Optional[float] = None) -> _Respuesta:
        url = peticion.full_url
        self.urls.append(url)
        if "/v3/reference/tickers/" in url:
            simbolo = url.rsplit("/", 1)[-1]
            if simbolo not in self.fichas:
                raise OSError("ficha inexistente (simulado)")
            return _Respuesta(json.dumps({"results": self.fichas[simbolo]}).encode())
        if "/v3/reference/splits" in url:
            if self.falla_splits:
                raise OSError("sin red (simulado)")
            filas = [{"ticker": t, "execution_date": HOY.isoformat()} for t in self.splits]
            return _Respuesta(json.dumps({"results": filas, "next_url": None}).encode())
        raise OSError(f"url no prevista: {url}")


# ═══════════════════════════ el banco: ejecutor + DAS falso ══════════════
class Banco:
    """El decisor real contra el Emparejador: ejecuta las acciones EN ORDEN como el ejecutor y dispara los temporizadores."""

    def __init__(self, cfg: Config, directorio: Path, *, orden_mensajes: tuple = ORDEN_DEFECTO,
                 estado: Optional[EstadoBot] = None, massive: Optional[MassiveFalso] = None,
                 replace_conserva_pp: bool = True, latidos: bool = True, inicio: datetime = INICIO,
                 catalogo: Optional[list] = None, referencia: Any = None, memoria: Any = None) -> None:
        self.reloj = RelojSimulado(inicio)
        self.hoy = self.reloj.hoy()
        self.libro = LibroSimulado()
        self.das = Emparejador(self.libro, self.reloj, orden_mensajes=tuple(orden_mensajes),
                               replace_conserva_pp=replace_conserva_pp)
        self.parser = protocolo.Parser(lambda t: es_nuestro(t, self.hoy), cuenta=CUENTA)
        self.canal = CanalFalso()
        self.mercado = MercadoDAS(self.reloj)
        self.massive = massive if massive is not None else MassiveFalso()
        self.referencia = (referencia if referencia is not None
                           else Referencia(CLAVE_MASSIVE, directorio / "cache", self.reloj, abrir=self.massive))
        self.estado = estado if estado is not None else EstadoBot(fase=Fase.SOMBRA, dia=self.hoy)
        self.tokens = GeneradorTokens(Origen.EJECUTOR, self.hoy, self.estado.ultimo_seq_token)
        self.disco_roto = False
        self.decisor = Decisor(cfg, self.estado, self.mercado, self.referencia, self.tokens,
                               catalogo if catalogo is not None else rechazos.cargar_catalogo(rechazos.RUTA_CATALOGO),
                               lambda: self.disco_roto, calendario=CalendarioPrueba(), memoria=memoria)
        self.temporizadores: dict[str, tuple[float, int, dict]] = {}
        self._orden_temporizador = 0
        self.cola: deque[Mensaje] = deque()
        self.historial: list[Accion] = []
        self.rechazar: dict[Proposito, str] = {}                 # propósito → texto de Send_Rej de DAS (siempre)
        self.das_contesta = True
        self.latidos = latidos
        self._ultimo_latido: Optional[float] = None
        self._proximo_tic: Optional[float] = None
        self._comandos = 0
        self.precarga_auto = True                                 # el hilo «referencia» del ejecutor (G1A-03)
        self._splits_precargados = False

    # ── reloj y cola ──
    def ahora(self) -> float:
        return self.reloj.mono()

    def procesar(self, msg: Mensaje, bombear: bool = True) -> list[Accion]:
        acciones = self.decisor.procesar(msg, self.reloj.mono(), self.reloj.ahora())
        self.historial.extend(acciones)
        for a in acciones:
            self._ejecutar(a)
        if self.precarga_auto:
            self.precargar_referencia()
        if bombear:
            self.bombear()
        return acciones

    def precargar_referencia(self) -> None:
        """Lo que hace el HiloVigilado «referencia» del ejecutor (G1A-03): los splits del día al arrancar y las fichas
        que el decisor pidió. Aquí va sincrónico ENTRE mensajes (nunca dentro de `procesar`)."""
        if not hasattr(self.referencia, "tomar_pendientes"):
            return
        if not self._splits_precargados:
            self._splits_precargados = True
            self.referencia.precargar_splits(self.hoy)
        for t in self.referencia.tomar_pendientes():
            self.referencia.precargar_ficha(t)

    def simstatus(self, ticker: str = TICKER) -> None:
        """El estado del símbolo recién preguntado a DAS (G1A-05: un ticker plano no abre sin él)."""
        self._a_das(protocolo.cmd_get("SymStatus", ticker))
        self.bombear()

    def bombear(self) -> None:
        vueltas = 0
        while self.cola:
            vueltas += 1
            assert vueltas < 50_000, "cola sin fin"
            self.procesar(self.cola.popleft(), bombear=False)

    def dar(self, lineas: list[str]) -> None:
        for linea in lineas:
            self.cola.append(DeDAS(self.parser.parsear(linea)))
        self.bombear()

    def _a_das(self, linea: str, serie: Optional[str] = None, version: int = 0) -> None:
        self.canal.enviar(linea, serie, version)
        if self.das_contesta:
            for respuesta in self.das.recibir(linea):
                self.cola.append(DeDAS(self.parser.parsear(respuesta)))

    def _ejecutar(self, a: Accion) -> None:
        if isinstance(a, EnviarOrden):
            if a.orden.proposito in self.rechazar:
                self.libro.rechazar_siguiente(self.rechazar[a.orden.proposito], "Send_Rej", a.orden.token)
            self._a_das(protocolo.cmd_neworder(a.orden), a.serie, a.orden.version)
        elif isinstance(a, Cancelar):
            self._a_das(protocolo.cmd_cancel(a.id_das))
        elif isinstance(a, CancelarTicker):
            self._a_das(protocolo.cmd_cancel_allsymb(a.ticker))
        elif isinstance(a, Reemplazar):
            tipo = (TipoOrden.STOP_LIMITE_PP if a.stop is not None
                    else TipoOrden.LIMITE if a.precio is not None else TipoOrden.MERCADO)
            self._a_das(protocolo.cmd_replace(a.id_das, a.qty, tipo, a.precio, a.stop), a.serie, a.version)
        elif isinstance(a, InvalidarSerie):
            self.canal.invalidar(a.serie, a.version)
        elif isinstance(a, Consultar):
            self._a_das(a.comando)
        elif isinstance(a, LocateInquire):
            self._a_das(protocolo.cmd_sl_inquire(a.ticker, a.qty, a.ruta))
        elif isinstance(a, LocateComprar):
            self._a_das(protocolo.cmd_sl_neworder(a.ticker, a.qty, a.ruta, a.token))
        elif isinstance(a, LocateOferta):
            self._a_das(protocolo.cmd_sl_offer(a.id_das, a.aceptar))
        elif isinstance(a, LocateCancelar):
            self._a_das(protocolo.cmd_sl_cancel(a.id_das))
        elif isinstance(a, Suscribir):
            self.canal.enviar(protocolo.cmd_sb(a.ticker) if a.alta else protocolo.cmd_unsb(a.ticker))
            if a.alta and self.das_contesta and self.libro.cotizacion(a.ticker) is not None:
                self.cola.append(DeDAS(self.parser.parsear(self.libro.linea_quote(a.ticker))))
        elif isinstance(a, Programar):
            self._orden_temporizador += 1
            self.temporizadores[a.clave] = (self.ahora() + a.en_s, self._orden_temporizador, dict(a.datos))
        elif isinstance(a, Desprogramar):
            self.temporizadores.pop(a.clave, None)

    def avanzar(self, segundos: float, tic: float = 1.0) -> None:
        """Avanza el reloj disparando los temporizadores vencidos (en orden) y un `Tic` (con el tic del DAS) cada `tic` s."""
        fin = self.ahora() + segundos
        if self._proximo_tic is None:
            self._proximo_tic = self.ahora() + tic
        vueltas = 0
        while True:
            vueltas += 1
            assert vueltas < 200_000, "temporizadores sin fin"
            vencidos = sorted((v, n, k) for k, (v, n, _) in self.temporizadores.items() if v <= self.ahora() + 1e-9)
            if vencidos:
                clave = vencidos[0][2]
                _, _, datos = self.temporizadores.pop(clave)
                self.procesar(Temporizador(clave, datos))
                continue
            if self.ahora() >= self._proximo_tic - 1e-9:
                self._proximo_tic = self.ahora() + tic
                self._latir()
                self.dar(self.das.tic() if self.das_contesta else [])
                self.procesar(Tic())
                continue
            if self.ahora() >= fin - 1e-9:
                return
            siguiente = min([fin, self._proximo_tic] + [v for v, _, _ in self.temporizadores.values()])
            self.reloj.avanzar(max(siguiente - self.ahora(), 0.0))

    def avanzar_hasta(self, hora: datetime, tic: float = 1.0) -> None:
        self.avanzar(max((hora - self.reloj.ahora()).total_seconds(), 0.0), tic)

    def _latir(self) -> None:
        if not self.latidos:
            return
        if self._ultimo_latido is not None and self.ahora() - self._ultimo_latido < 5.0:
            return
        self._ultimo_latido = self.ahora()
        self.procesar(SenalRecibida(Senal(clase="latido_feed", ticker=None, id=None, recibida_en=self.ahora(),
                                          feed={"ultima_vela_en": self.reloj.ahora().timestamp(), "vivo": True})))

    # ── atajos ──
    def conectar(self) -> list[Accion]:
        return self.procesar(ConexionDAS(True, "conectado"))

    def arrancar(self) -> list[Accion]:
        acciones = self.decisor.arrancar(self.reloj.mono(), self.reloj.ahora())
        self.historial.extend(acciones)
        for a in acciones:
            self._ejecutar(a)
        self.bombear()
        return acciones

    def cotizar(self, ticker: str, bid: str, ask: str, last: Optional[str] = None, volumen: int = 500_000,
                tam_bid: Optional[int] = None, tam_ask: Optional[int] = None) -> None:
        self.dar(self.libro.cotizar(ticker, D(bid), D(ask), D(last) if last is not None else None, volumen=volumen,
                                    vwap=D("3.40"), tamano_bid=tam_bid, tamano_ask=tam_ask))

    def tic_das(self) -> None:
        self.dar(self.das.tic())

    def preparar(self, locates: tuple = ((TICKER, SID, 1000),), cotizaciones: tuple = ((TICKER, "3.44", "3.46", "3.45"),),
                 reconciliar: bool = True) -> None:
        """Conectado, arrancado, con cotización fresca, locates y (si `reconciliar`) la primera reconciliación hecha."""
        self.conectar()
        self.arrancar()
        for ticker, bid, ask, last in cotizaciones:
            self.cotizar(ticker, bid, ask, last)
        for ticker in sorted({TICKER, OTRO} | {c[0] for c in cotizaciones}):
            self.referencia.pedir_ficha(ticker)                   # como si el radar ya los hubiera visto (G1A-03)
        self.precargar_referencia()
        for ticker, sid, n in locates:
            self.estado.locates[(ticker, sid)] = Locate(ticker=ticker, strategy_id=sid, pedidas=n, localizadas=n,
                                                        estado="Located")
            self.libro.sembrar_locate(ticker, n)          # decisión 55: DAS sabe lo que el bot tiene localizado
        if reconciliar:
            self.avanzar(0)
            assert not self.estado.modo_degradado, self.estado.modo_degradado

    def senal(self, ev: Evento, bombear: bool = True) -> list[Accion]:
        s = Senal(clase="evento", ticker=ev.ticker, id=id_de_evento(ev), evento=ev, momento=ev.momento,
                  recibida_en=self.ahora(), origen="tuberia")
        return self.procesar(SenalRecibida(s), bombear=bombear)

    def comando(self, texto: str, confirmar: bool = True) -> list[Accion]:
        self._comandos += 1
        c = comandos.parsear(texto, CHAT, AUTORIZADOS, id_comando=f"c{self._comandos}")
        assert c is not None, texto
        acciones = self.procesar(ComandoRecibido(c))
        if confirmar and c.requiere == comandos.REQUIERE_CONFIRMACION:
            respuesta = [a.texto for a in acciones if isinstance(a, Avisar)][-1]
            ident = re.search(r"/confirmar (\d{4})", respuesta)
            assert ident is not None, respuesta
            confirmacion = comandos.parsear(f"/confirmar {ident.group(1)}", CHAT, AUTORIZADOS, id_comando=f"k{self._comandos}")
            acciones = acciones + self.procesar(ComandoRecibido(confirmacion))
        return acciones

    def marca(self) -> int:
        return len(self.historial)

    def desde(self, marca: int) -> list[Accion]:
        return self.historial[marca:]

    def enviadas(self, *propositos: Proposito, desde: int = 0) -> list[OrdenNueva]:
        return [a.orden for a in self.historial[desde:] if isinstance(a, EnviarOrden)
                and (not propositos or a.orden.proposito in propositos)]

    def pos(self, ticker: str = TICKER) -> PosicionTicker:
        return self.estado.posiciones[ticker]

    def orden(self, token: int) -> Orden:
        return self.estado.ordenes[token]


# ═══════════════════════════ constructores ═══════════════════════════════
def momento_de(hora: datetime) -> pd.Timestamp:
    """Momento (INICIO de la vela, naive ET) de la vela que CIERRA a `hora` (R-B-04: la caducidad cuenta desde el cierre)."""
    return pd.Timestamp((hora - timedelta(minutes=1)).replace(tzinfo=None))


def otra_vela(b: "Banco") -> pd.Timestamp:
    """Un segundo después y la vela que cierra AHORA: otra señal de la misma estrategia con otro id (R-A-05)."""
    b.avanzar(1)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    return momento_de(b.reloj.ahora())


def evento(**cambios: Any) -> Evento:
    base = dict(tipo="entrada", ticker=TICKER, strategy_id=SID, estrategia="PM (A) prueba", momento=momento_de(INICIO),
                precio=3.45, direccion="Short", acciones=100.0, stop=4.0, distancia_stop=0.55, riesgo_usd=55.0)
    base.update(cambios)
    return Evento(**base)


def salida(**cambios: Any) -> Evento:
    base = dict(tipo="salida", ticker=TICKER, strategy_id=SID, estrategia="PM (A) prueba",
                momento=pd.Timestamp("2026-09-25 09:31:00"), precio=3.40, direccion="Short", motivo="TP",
                acciones=50.0, entrada_idx=None)
    base.update(cambios)
    return Evento(**base)


def estrategia_b(cfg: Config) -> EstrategiaConfig:
    return dataclasses.replace(cfg.estrategias[SID], strategy_id=SID2, name="PM (B) prueba", definition_hash=HASH_B)


def cfg_con(cfg: Config, *, estrategias: Optional[list[EstrategiaConfig]] = None, grupo_a: bool = False,
            **cambios: Any) -> Config:
    """La config de ejemplo con cambios; `estrategias` sustituye al diccionario entero."""
    if estrategias is not None:
        cambios["estrategias"] = {e.strategy_id: e for e in estrategias}
    if grupo_a:
        cambios["alertas_grupo_a"] = {**cfg.alertas_grupo_a, "activo": True}
    return dataclasses.replace(cfg, **cambios)


def lote_de(ev: Evento) -> str:
    return id_de_evento(ev)


def llenar_entrada(b: Banco, bid: str = "3.45", ask: str = "3.47") -> None:
    """El bid sube al precio de la venta que agrega (3,45) y el tic del DAS la llena."""
    b.cotizar(TICKER, bid, ask, "3.45")
    b.tic_das()


def abrir_posicion(b: Banco, ev: Optional[Evento] = None) -> Evento:
    """F1 entero: señal → agregar → fill de 100 → stops. Devuelve el evento."""
    ev = ev or evento()
    b.senal(ev)
    llenar_entrada(b)
    assert b.pos().neta_fills == -100
    return ev


def acciones_de(acciones: list[Accion], tipo: type) -> list:
    return [a for a in acciones if isinstance(a, tipo)]


def anotaciones(acciones: list[Accion], tipo: str) -> list[Anotar]:
    return [a for a in acciones if isinstance(a, Anotar) and a.tipo == tipo]


def resumen(a: Accion) -> tuple:
    """La forma de una acción que el test de secuencia EXACTA compara (tipo y campos clave)."""
    if isinstance(a, Anotar):
        return ("Anotar", a.tipo)
    if isinstance(a, EnviarOrden):
        o = a.orden
        return ("EnviarOrden", o.lado.value, o.tipo.value, o.qty, o.precio, o.stop, o.proposito.value, o.ruta,
                o.post_only, a.serie)
    if isinstance(a, Programar):
        return ("Programar", a.clave.split(":", 1)[0], round(a.en_s, 3))
    if isinstance(a, Desprogramar):
        return ("Desprogramar", a.clave)
    if isinstance(a, Avisar):
        return ("Avisar", int(a.nivel), a.grupo.value)
    if isinstance(a, InvalidarSerie):
        return ("InvalidarSerie", a.serie, a.version)
    if isinstance(a, Consultar):
        return ("Consultar", a.comando)
    if isinstance(a, Cancelar):
        return ("Cancelar", a.token)
    if isinstance(a, Reemplazar):
        return ("Reemplazar", a.qty, a.stop, a.precio, a.version)
    return (type(a).__name__,)


def segundos_hasta(hora: datetime, desde: datetime) -> float:
    return round((hora - desde).total_seconds(), 3)


@pytest.fixture
def banco(cfg: Config, tmp_path: Path) -> Banco:
    b = Banco(cfg, tmp_path)
    b.preparar()
    return b


# ═══════════════════════════ F1: la entrada entera, exacta ═══════════════
def test_f1_secuencia_exacta_de_senal_a_stops(banco: Banco) -> None:
    """F1 (R-B-01 v3, R-C-01 v3, F1.9): la señal, el fill y el cierre del intento con sus acciones EXACTAS y en orden.

    COB-03: la primera métrica es `retraso_senal_pct` (último de DAS contra el
    precio de la señal). G1A-05: el estado del símbolo está fresco (si no, la
    señal esperaría al `GET SymStatus`). COB-05: la métrica del slippage se
    llama `slippage_vs_senal_pct`. L0-01: la serie de stops se invalida ANTES
    de enviar los stops nuevos.
    """
    b = banco
    ev = evento()
    lote_id = lote_de(ev)
    b.simstatus()
    acciones = b.senal(ev, bombear=False)
    assert [resumen(a) for a in acciones] == [
        ("Anotar", "senal_principal"),              # Jaume 29-sep: la primera señal principal del día de la pareja
        ("Anotar", "metrica"),
        ("Anotar", "senal"),
        ("Anotar", "lote"),
        ("Anotar", "locate_estado"),
        ("Anotar", "metrica"),
        ("Anotar", "intento"),
        ("EnviarOrden", "SS", "LMT", 100, D("3.45"), None, "entrada_agregar", "SAGEREB", True, None),
        ("Programar", T_CRUCE, 15.0),          # decisión 56: 15 s agregando
        ("Anotar", "locate_estado"),                 # Jaume 29-sep: dentro → fase C
        ("Anotar", "metrica"),
    ]
    retraso = anotaciones(acciones, "metrica")[0].datos
    assert (retraso["nombre"], retraso["valor"]) == ("retraso_senal_pct", D("0"))      # COB-03: último 3,45 = señal
    assert anotaciones(acciones, "lote")[0].datos["estado"] == "abriendo"
    assert anotaciones(acciones, "locate_estado")[0].datos["usadas"] == 100
    assert anotaciones(acciones, "metrica")[-1].datos["nombre"] == "senal_a_orden_ms"
    b.bombear()
    agregar = b.enviadas(Proposito.ENTRADA_AGREGAR)[0]
    assert b.orden(agregar.token).estado is EstadoOrden.ACCEPTED
    assert f"NEWORDER {agregar.token} SS XYZ SAGEREB 100 3.45 PostOnly TIF=DAY+" in b.canal.enviadas()
    assert b.canal.series_invalidadas == []

    b.cotizar(TICKER, "3.45", "3.47", "3.45")
    marca = b.marca()
    b.dar(b.das.tic())
    execute = b.historial[marca:]
    corte = next(i for i, a in enumerate(execute[1:], 1) if isinstance(a, Anotar) and a.tipo == "orden_estado")
    ahora_et = b.reloj.ahora()
    eod = datetime(2026, 9, 25, 11, 30, tzinfo=ET)
    assert [resumen(a) for a in execute[:corte]] == [
        ("Anotar", "orden_act"),
        ("InvalidarSerie", "stops:XYZ", 1),
        ("Anotar", "fill"),
        ("Anotar", "lote"),
        ("Anotar", "stop_plan"),
        ("EnviarOrden", "B", "STOPLMTP", 100, D("6.00"), D("4.00"), "stop", "SMAT", False, "stops:XYZ"),   # R-C-01 v4
        ("Anotar", "lote"),
        ("Anotar", "intento_fin"),
        ("Programar", T_HORA_AGREGAR, segundos_hasta(eod - timedelta(seconds=60), ahora_et)),
        ("Programar", T_HORA_ASK, segundos_hasta(eod, ahora_et)),
        ("Programar", T_EOD_COMPROBAR, segundos_hasta(eod + timedelta(seconds=30), ahora_et)),
        ("Avisar", 1, "B"),
        ("Anotar", "metrica"),
        ("Desprogramar", f"cruce:{TICKER}"),
        ("Desprogramar", f"cancel_espera:{TICKER}"),
        ("Desprogramar", f"cruce_espera:{TICKER}"),
        ("Consultar", f"GET LDLU {TICKER}"),
        ("Programar", T_BARRIDO, 0.0),
    ]
    fill = anotaciones(execute, "fill")[0].datos
    assert fill["id_trade"] is None and fill["origen"] == "execute"
    eco = [a.datos for a in anotaciones(execute, "fill") if a.datos["eco"]]
    assert len(eco) == 1 and eco[0]["id_trade"] == 5001
    lote = b.pos().lotes[lote_id]
    assert (lote.estado, lote.llenas, lote.precio_medio, lote.nivel_stop) == (EstadoLote.ABIERTO, 100, D("3.45"), D("4.0"))
    assert b.pos().intento is None and b.pos().version_stops == 1
    assert b.pos().neta_das == -100
    assert f"cruce:{TICKER}" not in b.temporizadores
    avisos_fill = [a for a in execute if isinstance(a, Avisar) and a.clave == f"fill:{lote_id}"]
    assert avisos_fill and avisos_fill[0].texto.startswith("[SOMBRA]")
    slippage = [a.datos for a in anotaciones(execute, "metrica") if a.datos["nombre"].startswith("slippage")]
    assert [m["nombre"] for m in slippage] == ["slippage_vs_senal_pct"]                  # COB-05 (§11.1)
    assert slippage[0]["valor"] == D("0") and slippage[0]["bps"] == D("0")
    (stop,) = b.enviadas(*STOPS)                                         # stop único (Jaume 29-sep): uno, no dos
    assert b.orden(stop.token).estado is EstadoOrden.ACCEPTED
    assert all(isinstance(a.datos.get("mono"), float) for a in anotaciones(b.historial, "fill"))
    assert b.canal.series_invalidadas == [("stops:XYZ", 1)]
    assert b.canal.invalida_antes_de_enviar("stops:XYZ", 1)                              # L0-01 / riesgo 7
    lineas_stop = [(linea, serie, version) for linea, serie, version in b.canal.lineas if "STOPLMTP" in linea]
    assert lineas_stop == [(f"NEWORDER {stop.token} B XYZ SMAT 100 STOPLMTP 4 6 TIF=DAY+", "stops:XYZ", 1)]


@pytest.mark.parametrize("orden_mensajes", PERMUTACIONES, ids=["-".join(p) for p in PERMUTACIONES])
def test_f1_permutaciones_orderact_trade_pos(cfg: Config, tmp_path: Path, orden_mensajes: tuple) -> None:
    """Riesgo 8 / corrección 2: en cualquier orden de Execute, %TRADE y %POS, UN fill y UN stop (único, Jaume 29-sep)."""
    b = Banco(cfg, tmp_path, orden_mensajes=orden_mensajes)
    b.preparar()
    abrir_posicion(b)
    agregar = b.enviadas(Proposito.ENTRADA_AGREGAR)[0]
    assert len(b.estado.fills[agregar.token]) == 1
    assert b.estado.fills[agregar.token][0].id_trade == 5001            # el eco del Execute se completa con el id real
    contados = [a.datos for a in anotaciones(b.historial, "fill") if a.datos["id_trade"] is not None]
    assert len(contados) == 1                                           # lo que `reconstruir` cuenta: una vez
    assert [o.proposito for o in b.enviadas(*STOPS)] == [Proposito.STOP]
    assert all(o.qty == 100 for o in b.enviadas(*STOPS))
    assert b.pos().neta_fills == -100 and b.pos().neta_das == -100 and b.pos().version_stops == 1
    assert b.pos().intento is None
    b.avanzar(3)
    assert len(b.enviadas(*STOPS)) == 1                                 # el barrido tampoco duplica


def test_f1_h2_el_diario_reconstruye_el_mismo_estado(banco: Banco) -> None:
    """H-2: lo que el decisor anota (más las intenciones que escribe el ejecutor) reconstruye el estado vivo."""
    b = banco
    ev = abrir_posicion(b)
    b.avanzar(2)
    registros = [Registro(v=1, seq=1, t="2026-09-25T09:29:00-04:00", proceso="ejecutor", tipo="locate_estado",
                          datos={"ticker": TICKER, "strategy_id": SID, "estado": "Located", "localizadas": 1000,
                                 "qty": 1000, "coste_nuevo": "0"})]
    for a in b.historial:
        if isinstance(a, Anotar):
            registros.append(Registro(v=1, seq=len(registros) + 1, t="t", proceso="ejecutor", tipo=a.tipo,
                                      datos=a_json_seguro(a.datos)))
        elif isinstance(a, EnviarOrden):
            o = a.orden
            viva = b.orden(o.token)
            registros.append(Registro(v=1, seq=len(registros) + 1, t="t", proceso="ejecutor", tipo="orden_intencion",
                                      datos=a_json_seguro({"token": o.token, "ticker": o.ticker, "lado": o.lado,
                                                           "tipo_orden": o.tipo, "qty": o.qty, "precio": o.precio,
                                                           "stop": o.stop, "ruta": o.ruta, "proposito": o.proposito,
                                                           "lote_id": o.lote_id, "nivel": o.nivel,
                                                           "version": o.version, "intentos": viva.intentos,
                                                           "mono": viva.enviada_en})))
    rehecho = reconstruir(registros, HOY)
    vivo = b.estado
    assert rehecho.senales_vistas == vivo.senales_vistas == {id_de_evento(ev)}
    p_rehecha, p_viva = rehecho.posiciones[TICKER], vivo.posiciones[TICKER]
    assert (p_rehecha.neta_fills, p_rehecha.neta_das, p_rehecha.version_stops) == \
           (p_viva.neta_fills, p_viva.neta_das, p_viva.version_stops)
    for lote_id, lote in p_viva.lotes.items():
        otro = p_rehecha.lotes[lote_id]
        assert (otro.llenas, otro.estado, otro.nivel_stop, otro.precio_medio, otro.pedidas, otro.eod) == \
               (lote.llenas, lote.estado, lote.nivel_stop, lote.precio_medio, lote.pedidas, lote.eod)
    for token, orden in vivo.ordenes.items():
        otra = rehecho.ordenes[token]
        assert (otra.estado, otra.llenas, otra.proposito, otra.id_das) == (orden.estado, orden.llenas, orden.proposito,
                                                                           orden.id_das), token
    assert rehecho.locates[(TICKER, SID)].usadas == vivo.locates[(TICKER, SID)].usadas == 100


def _linea_act(accion: str, orden: OrdenNueva, id_das: int, qty: int, precio: str, lado: str = "Shrt") -> str:
    """Una `%OrderAct` escrita a mano (manual L434-494; notas vacías = dos espacios) para provocar carreras a propósito."""
    return f"%OrderAct {id_das} {accion} {lado} {orden.ticker} {qty} {precio} {orden.ruta} 09:31:00  {orden.token}"


def test_f1_el_resto_se_cruza_solo_con_el_canceled_cuadrado(banco: Banco) -> None:
    """Injerto §8.7 / riesgo 5: Canceled de 70 con 30 en vuelo → NADA se cruza hasta que llega el fill; luego se cruzan 70."""
    b = banco
    b.senal(evento())
    agregar = b.enviadas(Proposito.ENTRADA_AGREGAR)[0]
    id_das = b.orden(agregar.token).id_das
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 30, 14, tzinfo=ET))
    b.das_contesta = False                                              # la cancelación no llega al DAS falso
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 30, 15, 200_000, tzinfo=ET))
    assert [c.token for c in acciones_de(b.historial, Cancelar)] == [agregar.token]
    b.das_contesta = True
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    b.dar([_linea_act("Canceled", agregar, id_das, 70, "3.45")])
    assert not b.enviadas(Proposito.ENTRADA_CRUCE)                      # 30 acciones en vuelo: el resto aún no se sabe
    assert b.pos().intento is not None and b.pos().intento.token_agregar == agregar.token
    b.dar([_linea_act("Execute", agregar, id_das, 30, "3.45")])
    assert [(o.qty, o.precio, o.ruta) for o in b.enviadas(Proposito.ENTRADA_CRUCE)] == [(70, D("3.42"), "SAGEPRO")]
    assert b.pos().neta_fills == -100 and b.pos().intento is None      # el cruce llenó 70 al bid y el intento se cerró


def test_f1_cruce_sin_llenar_un_reintento_y_se_queda_lo_llenado(banco: Banco) -> None:
    """F1.8 / R-B-02: el cruce que no llena en `cruce_espera_s` se cancela y se reintenta UNA vez con el bid nuevo."""
    b = banco
    b.senal(evento())
    b.cotizar(TICKER, "3.44", "3.46", "3.45", tam_bid=0)               # nadie compra: ni agregando ni cruzando
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 30, 15, 500_000, tzinfo=ET))
    b.cotizar(TICKER, "3.43", "3.45", "3.44", tam_bid=0)
    b.avanzar(5)
    cruces = b.enviadas(Proposito.ENTRADA_CRUCE)
    assert [(o.qty, o.precio) for o in cruces] == [(100, D("3.42")), (100, D("3.41"))]
    assert all(b.orden(o.token).estado is EstadoOrden.CANCELED for o in cruces)
    # cada cruce lo cancela SU `cruce_espera` y nadie más: la espera vieja de la cancelación no toca la orden nueva
    tokens_cruce = {o.token for o in cruces}
    cancelaciones = [c for c in acciones_de(b.historial, Cancelar) if c.token in tokens_cruce]
    assert [c.token for c in cancelaciones] == [o.token for o in cruces]
    assert all(c.motivo.startswith(MOTIVO_CRUCE_ESPERA) for c in cancelaciones)
    assert b.pos().intento is None
    assert b.pos().lotes[lote_de(evento())].estado is EstadoLote.CANCELADO
    fin = anotaciones(b.historial, "intento_fin")[-1].datos
    assert fin["llenas"] == 0 and "reintento" in fin["motivo"]
    assert b.estado.locates[(TICKER, SID)].usadas == 0                 # las acciones localizadas vuelven a estar libres


def test_f1_bid_caido_mas_del_tope_no_se_cruza(banco: Banco) -> None:
    """R-B-01 v3 paso 3: si al vencer el bid cayó más del 3 % desde el de la señal, no se cruza; se avisa y se cierra."""
    b = banco
    b.senal(evento())
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 30, 14, tzinfo=ET))
    b.cotizar(TICKER, "3.30", "3.32", "3.31")                           # 3,30 < 3,44 · 0,97 = 3,3368
    b.avanzar(2)
    assert not b.enviadas(Proposito.ENTRADA_CRUCE)
    assert anotaciones(b.historial, "intento_fin")[-1].datos["motivo"] == reglas_entrada.MOTIVO_FIN_BID_CAYO
    assert any(isinstance(a, Avisar) and "entrada terminada sin fills" in a.texto for a in b.historial)


def test_f1_cancelacion_sin_confirmar_cierra_y_un_fill_tardio_revive_el_lote(banco: Banco) -> None:
    """F1.7 / F13: sin Canceled en 3 s el intento se cierra con lo llenado; un fill que llega después revive el lote con stops."""
    b = banco
    b.senal(evento())
    agregar = b.enviadas(Proposito.ENTRADA_AGREGAR)[0]
    id_das = b.orden(agregar.token).id_das
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 30, 14, tzinfo=ET))
    b.das_contesta = False
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 30, 19, tzinfo=ET))
    lote_id = lote_de(evento())
    assert b.pos().intento is None and b.pos().lotes[lote_id].estado is EstadoLote.CANCELADO
    assert any(isinstance(a, Avisar) and a.clave == f"cancel_sin_confirmar:{TICKER}" for a in b.historial)
    b.das_contesta = True
    marca = b.marca()
    b.dar([_linea_act("Execute", agregar, id_das, 100, "3.45")])
    lote = b.pos().lotes[lote_id]
    assert (lote.estado, lote.llenas) == (EstadoLote.ABIERTO, 100)
    assert [o.proposito.value for o in b.enviadas(*STOPS, desde=marca)] == ["stop"]      # stop único (Jaume 29-sep)
    assert f"hora_ask:{lote_id}" in b.temporizadores


def test_cambio_de_dia_renueva_tokens_y_caduca_los_locates(banco: Banco) -> None:
    """R-H-05 / tokens.py: a medianoche los locates sin usar caducan (al diario), el gasto vuelve a 0 y los tokens son del día."""
    b = banco
    b.reloj.fijar(datetime(2026, 9, 28, 4, 0, tzinfo=ET))
    acciones = b.procesar(Tic())
    assert anotaciones(acciones, "dia_nuevo")[0].datos["hoy"] == datetime(2026, 9, 28).date()
    caducados = anotaciones(acciones, "locates_caducados")[0].datos["locates"]
    assert [(c["ticker"], c["libres"]) for c in caducados] == [(TICKER, 1000)]
    assert b.estado.dia == datetime(2026, 9, 28).date()
    assert b.estado.locates == {} and b.estado.gasto_locates_dia == 0
    assert b.tokens.hoy == b.estado.dia


def test_f2_stop_cancelado_por_das_sin_pedirlo_se_repone_y_avisa(banco: Banco) -> None:
    """R-C-04 / F2.6: DAS cancela el stop sin que el bot lo pida → aviso 2 y el plan lo repone al momento (con el
    stop único, Jaume 29-sep, la posición no tiene otra red: sale igual, disparo en L y límite L + 50 %)."""
    b = banco
    abrir_posicion(b)
    stop = b.enviadas(Proposito.STOP)[0]
    marca = b.marca()
    b.dar(b.das.recibir(f"CANCEL {b.orden(stop.token).id_das}"))
    aviso = [a for a in b.desde(marca) if isinstance(a, Avisar) and (a.clave or "").startswith(f"stop_cancelado:{TICKER}")]
    assert len(aviso) == 1 and aviso[0].nivel is Nivel.AVISO
    assert [(o.qty, o.stop, o.precio) for o in b.enviadas(Proposito.STOP, desde=marca)] == \
           [(100, D("4.00"), D("6.00"))]


def test_f2_replace_que_pierde_el_pre_post_se_repone(cfg: Config, tmp_path: Path) -> None:
    """2h.8 / F2.2: si tras el REPLACE el tipo de %ORDER ya no es el de pre/post, se pone uno nuevo y se cancela el viejo."""
    config = cfg_con(cfg, stops={**cfg.stops, "tipo_esperado_en_order": "^SLP"})
    b = Banco(config, tmp_path, replace_conserva_pp=False)
    b.preparar()
    abrir_posicion(b)
    viejos = {o.token for o in b.enviadas(*STOPS)}
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    ev = salida()
    b.procesar(SenalRecibida(Senal(clase="evento", ticker=TICKER, id=id_de_evento(ev), evento=ev, momento=ev.momento,
                                   recibida_en=b.ahora())))
    b.cotizar(TICKER, "3.43", "3.45", "3.44")                           # el TP (compra 3,45) llena 50
    b.tic_das()
    assert sorted(r.qty for r in acciones_de(b.historial, Reemplazar)) == [50]              # el stop único
    marca = b.marca()
    b.avanzar(1.5)
    repuestos = anotaciones(b.desde(marca), "replace_sin_pp")
    assert len(repuestos) == 1 and all(a.datos["tipo_das_crudo"].startswith("SL:") for a in repuestos)
    nuevos = b.enviadas(*STOPS, desde=marca)
    assert sorted((o.proposito.value, o.qty) for o in nuevos) == [("stop", 50)]
    assert viejos <= {c.token for c in acciones_de(b.desde(marca), Cancelar)}


def test_a7_simbolo_sin_cotizacion_en_das_queda_sin_simbolo_hasta_que_cotiza(banco: Banco) -> None:
    """A7: el ticker del radar que DAS no cotiza en 5 s tras suscribirlo → SIN_SIMBOLO y aviso; su primera $Quote lo devuelve."""
    b = banco
    b.procesar(SenalRecibida(Senal(clase="radar", ticker="ZZZ", id=None, estimacion=[], precio_radar=D("2"),
                                   recibida_en=b.ahora())))
    b.avanzar(7)
    assert Suscribir("ZZZ", True) in b.historial
    assert b.estado.posiciones["ZZZ"].estado is EstadoTicker.SIN_SIMBOLO
    assert any(isinstance(a, Avisar) and a.clave == "sin_simbolo:ZZZ" for a in b.historial)
    b.cotizar("ZZZ", "1.99", "2.01", "2.00")
    assert b.estado.posiciones["ZZZ"].estado is EstadoTicker.NORMAL


# ═══════════════════════════ F2: parcial del stop ═══════════════════════
@pytest.mark.parametrize("orden_mensajes", PERMUTACIONES, ids=["F2-" + "-".join(p) for p in PERMUTACIONES])
def test_f2_stop_parcial_sigue_vivo_con_lo_que_queda_y_nunca_compra_de_mas(cfg: Config, tmp_path: Path,
                                                                           orden_mensajes: tuple) -> None:
    """F2.3 / R-C-11 con el stop único (Jaume 29-sep, R-C-01 v4): el stop llena 20 → sigue vivo con las 80 que quedan
    (ni REPLACE, ni cancelación, ni otra compra: nunca dos compras por las mismas acciones); cuando llena el resto la
    posición queda plana sin venta del exceso.

    En las seis permutaciones: con `%POS` detrás del fill el plan ESPERA a que DAS cuadre (corrección 2) y replanifica
    en cuanto llega; con `%POS` delante, planifica al momento. El resultado es el mismo.
    """
    b = Banco(cfg, tmp_path, orden_mensajes=orden_mensajes)
    b.preparar()
    abrir_posicion(b)
    (stop,) = b.enviadas(*STOPS)
    assert (stop.qty, stop.stop, stop.precio) == (100, D("4.00"), D("6.00"))
    b.cotizar(TICKER, "4.00", "4.05", "4.01", tam_ask=20)
    marca = b.marca()
    b.tic_das()                                     # el stop se dispara y llena 20 a 4,05
    tras_parcial = b.desde(marca)
    assert b.pos().neta_fills == -80
    assert acciones_de(tras_parcial, Reemplazar) == []
    assert stop.token not in [c.token for c in acciones_de(tras_parcial, Cancelar)]
    assert [o for o in b.enviadas(desde=marca) if o.lado is Lado.COMPRA] == []
    viva = b.orden(stop.token)
    assert viva.llenas == 20 and viva.estado in (EstadoOrden.PARTIAL, EstadoOrden.TRIGGERED, EstadoOrden.ACCEPTED)
    b.avanzar(2)                                    # el barrido no lo «completa» con otra orden
    assert [o for o in b.enviadas(desde=marca) if o.lado is Lado.COMPRA] == []

    marca = b.marca()                               # el resto del stop llena: plana, sin exceso que vender
    b.cotizar(TICKER, "4.58", "4.60", "4.60")
    b.tic_das()
    assert b.pos().neta_fills == 0 and b.pos().neta_das == 0
    assert b.enviadas(Proposito.VENTA_EXCESO, desde=marca) == []
    assert not anotaciones(b.desde(marca), "incidente")


# ═══════════════════════════ F3: dos señales con el intento vivo ═════════
def test_f3_segunda_senal_suma_y_reinicia_con_el_total(cfg: Config, tmp_path: Path) -> None:
    """F3 / R-B-03: la segunda estrategia SUMA; tras el Canceled se reagrega el total con el MISMO t_limite; un stop por
    nivel (stop único, Jaume 29-sep)."""
    config = cfg_con(cfg, estrategias=[cfg.estrategias[SID], estrategia_b(cfg)])
    b = Banco(config, tmp_path)
    b.preparar(locates=((TICKER, SID, 1000), (TICKER, SID2, 1000)))
    ev_a = evento()
    b.senal(ev_a)
    limite = b.temporizadores[f"cruce:{TICKER}"][0]
    primera = b.enviadas(Proposito.ENTRADA_AGREGAR)[0]
    b.avanzar(2)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    ev_b = evento(strategy_id=SID2, estrategia="PM (B) prueba", acciones=50.0, stop=4.0)
    marca = b.marca()
    acciones = b.senal(ev_b, bombear=False)
    assert [c.token for c in acciones_de(acciones, Cancelar)] == [primera.token]
    assert anotaciones(acciones, "intento")[0].datos["qty_total"] == 150
    b.bombear()
    agregar = b.enviadas(Proposito.ENTRADA_AGREGAR, desde=marca)
    assert [o.qty for o in agregar] == [150]
    assert b.temporizadores[f"cruce:{TICKER}"][0] == limite            # la caducidad es la de la primera señal
    assert b.pos().intento is not None and b.pos().intento.lotes == [lote_de(ev_a), lote_de(ev_b)]
    llenar_entrada(b)
    lotes = b.pos().lotes
    assert (lotes[lote_de(ev_a)].llenas, lotes[lote_de(ev_b)].llenas) == (100, 50)
    stops_ = b.enviadas(*STOPS)
    assert sorted((o.proposito, o.stop, o.precio, o.qty) for o in stops_) == [
        (Proposito.STOP, D("4.00"), D("6.00"), 150)]   # R-C-01 v4 + un solo nivel por ticker (Jaume 30-sep): aglutina


def test_f1_6_b_con_otro_nivel_no_entra_un_solo_nivel_por_ticker(cfg: Config, tmp_path: Path) -> None:
    """Jaume 30-sep: un solo nivel de stop por ticker. Con el stop de A (4,00) vivo, la señal de B con otro nivel
    (4,20) se descarta con aviso y no manda ninguna orden (el F1.6 de v3, «el primer fill de un nivel nuevo pone su
    stop», queda sin objeto: no puede haber un segundo nivel)."""
    config = cfg_con(cfg, estrategias=[cfg.estrategias[SID], estrategia_b(cfg)])
    b = Banco(config, tmp_path)
    b.preparar(locates=((TICKER, SID, 1000), (TICKER, SID2, 1000)))
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    marca = b.marca()
    acciones = b.senal(evento(strategy_id=SID2, estrategia="PM (B) prueba", acciones=50.0, stop=4.2,
                              momento=momento_de(b.reloj.ahora())))
    assert anotaciones(acciones, "senal_descartada")[0].datos["motivo"] == reglas_entrada.MOTIVO_NIVEL_DISTINTO
    assert any(isinstance(a, Avisar) for a in acciones)
    assert not b.enviadas(desde=marca) and b.pos().neta_fills == -100


def test_f4_tp_parcial_agrega_y_cruza_el_resto_con_techo(banco: Banco) -> None:
    """R-D-03 v2: sin conflicto el TP agrega 60 s en el punto medio; luego, CONFIRMADO el Canceled, al ask con techo 3 %.

    D2-07: el temporizador del cruce es POR ORDEN (`tp_cruce:<lote>:<token>`): dos TP del mismo lote no se pisan.
    """
    b = banco
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    ev = salida()
    acciones = b.procesar(SenalRecibida(Senal(clase="evento", ticker=TICKER, id=id_de_evento(ev), evento=ev,
                                              momento=ev.momento, recibida_en=b.ahora())))
    tp = [a.orden for a in acciones if isinstance(a, EnviarOrden)]
    assert [(o.proposito, o.qty, o.precio, o.post_only) for o in tp] == [(Proposito.TP_AGREGAR, 50, D("3.45"), True)]
    clave = f"tp_cruce:{lote_de(evento())}:{tp[0].token}"
    assert clave in b.temporizadores
    marca = b.marca()
    b.avanzar(60.5)
    cruce = b.enviadas(Proposito.TP_CRUCE, desde=marca)
    assert [(o.qty, o.precio) for o in cruce] == [(50, D("3.46"))]
    cancelado = [a for a in b.desde(marca) if isinstance(a, Cancelar) and a.token == tp[0].token]
    assert cancelado and b.desde(marca).index(cancelado[0]) < b.desde(marca).index(
        next(a for a in b.desde(marca) if isinstance(a, EnviarOrden) and a.orden.proposito is Proposito.TP_CRUCE))
    assert b.pos().neta_fills == -50
    assert b.pos().lotes[lote_de(evento())].llenas == 50


def test_f4_tp_rechazado_se_reintenta_y_conserva_su_cruce(cfg: Config, tmp_path: Path) -> None:
    """R-B-07 + R-D-03 v2 / D2-07: un TP rechazado con un motivo conocido de «reintentar» sale con token nuevo y SU
    `tp_cruce:<lote>:<token>` pasa a la orden nueva (el de la rechazada se desprograma)."""
    b = Banco(cfg, tmp_path, catalogo=CATALOGO_CON_REINTENTO)
    b.preparar()
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    b.libro.rechazar_siguiente("Rechazo de prueba")
    ev = salida()
    b.procesar(SenalRecibida(Senal(clase="evento", ticker=TICKER, id=id_de_evento(ev), evento=ev, momento=ev.momento,
                                   recibida_en=b.ahora())))
    rechazado, reintento = b.enviadas(Proposito.TP_AGREGAR)
    assert b.orden(rechazado.token).estado is EstadoOrden.REJECTED
    assert b.orden(reintento.token).intentos == 1 and reintento.qty == 50
    lote_id = lote_de(evento())
    assert b.temporizadores[f"tp_cruce:{lote_id}:{reintento.token}"][2]["token"] == reintento.token
    assert f"tp_cruce:{lote_id}:{rechazado.token}" not in b.temporizadores
    assert b.pos().estado is EstadoTicker.NORMAL                         # reintento conocido: sin pausa
    marca = b.marca()
    b.avanzar(60.5)
    assert [(o.qty, o.precio) for o in b.enviadas(Proposito.TP_CRUCE, desde=marca)] == [(50, D("3.46"))]


def test_d2_09_tp_rechazado_por_postonly_cruza_ya_con_techo_y_vigila_el_limbo(banco: Banco) -> None:
    """D2-09 (decisión del director) / D2-13: el TP rechazado por «PostOnly would cross» NO se reintenta al mismo precio:
    pasa YA al cruce (al ask con techo 3 %), sin pausa, y se programa el aviso de limbo de ESA orden."""
    b = banco
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    b.libro.rechazar_siguiente("PostOnly would cross")
    ev = salida()
    b.procesar(SenalRecibida(Senal(clase="evento", ticker=TICKER, id=id_de_evento(ev), evento=ev, momento=ev.momento,
                                   recibida_en=b.ahora())), bombear=False)
    rechazado = b.enviadas(Proposito.TP_AGREGAR)[0]
    b.cotizar(TICKER, "3.44", "3.46", "3.45", tam_ask=0)                # el cruce no encuentra acciones al ask
    cruce = b.enviadas(Proposito.TP_CRUCE)
    assert [(o.qty, o.precio, o.post_only) for o in cruce] == [(50, D("3.46"), False)]
    assert len(b.enviadas(Proposito.TP_AGREGAR)) == 1                   # nunca otro agregar al mismo precio
    assert b.orden(rechazado.token).estado is EstadoOrden.REJECTED
    assert b.pos().estado is EstadoTicker.NORMAL
    lote_id = lote_de(evento())
    assert f"tp_cruce:{lote_id}:{rechazado.token}" not in b.temporizadores
    # decisión 13 (Jaume 30-sep): primero se persigue el ask (3 vueltas de 1 s) y, agotada, el limbo a 5 s
    assert b.temporizadores[f"perseguir_ask:{cruce[0].token}"][2]["tp"] is True
    marca = b.marca()
    b.avanzar(3.5)
    assert f"tp_limbo:{lote_id}:{cruce[0].token}" in b.temporizadores
    b.avanzar(5.5)
    limbo = [a for a in b.desde(marca) if isinstance(a, Avisar) and (a.clave or "").startswith("limbo:")]
    assert len(limbo) == 1 and limbo[0].nivel is Nivel.AVISO


def test_decision_13_tp_cruce_persigue_el_ask_tres_veces_con_techo_y_luego_limbo(banco: Banco) -> None:
    """Decisión 13 (Jaume 30-sep): el TP agrega 60 s y, si no llena, REMUEVE al ask persiguiendo hasta 3 veces (REPLACE
    de precio cada `tp_parcial.perseguir_ask_s`), con el techo del 3 % sobre el último en cada una; tras la 3.ª sin
    llenar, el aviso de limbo de siempre (D2-13). Nunca una cuarta ni Cancelar + nueva."""
    b = banco
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45", tam_ask=0)                # nada llena al ask
    ev = salida()
    b.procesar(SenalRecibida(Senal(clase="evento", ticker=TICKER, id=id_de_evento(ev), evento=ev, momento=ev.momento,
                                   recibida_en=b.ahora())))
    b.avanzar(60.5)
    cruce = b.enviadas(Proposito.TP_CRUCE)
    assert [(o.qty, o.precio) for o in cruce] == [(50, D("3.46"))]
    for ask in ("3.48", "3.50", "3.70", "3.75"):                        # 3,70 > techo 3,46·1,03 = 3,5638 → 3,57
        b.cotizar(TICKER, "3.44", ask, "3.46", tam_ask=0)
        b.avanzar(1)
    persecuciones = [a for a in b.historial if isinstance(a, Reemplazar) and a.token == cruce[0].token]
    assert [r.precio for r in persecuciones] == [D("3.48"), D("3.50"), D("3.57")]
    assert all("decisión 13" in r.motivo for r in persecuciones)
    assert not [a for a in b.historial if isinstance(a, Cancelar) and a.token == cruce[0].token]
    assert [a.datos["n"] for a in anotaciones(b.historial, "persecucion_ask")] == [1, 2, 3]
    marca = b.marca()
    b.avanzar(5)
    limbo = [a for a in b.desde(marca) if isinstance(a, Avisar) and (a.clave or "").startswith("limbo:")]
    assert len(limbo) == 1 and "tras perseguir" in limbo[0].texto
    assert b.pos().estado is EstadoTicker.NORMAL


def test_decision_13_tp_cruce_que_llena_no_sigue_persiguiendo(banco: Banco) -> None:
    """Decisión 13: si la persecución llena, se acaba (sin más REPLACE ni limbo)."""
    b = banco
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45", tam_ask=0)
    ev = salida()
    b.procesar(SenalRecibida(Senal(clase="evento", ticker=TICKER, id=id_de_evento(ev), evento=ev, momento=ev.momento,
                                   recibida_en=b.ahora())))
    b.avanzar(60.5)
    cruce = b.enviadas(Proposito.TP_CRUCE)
    b.cotizar(TICKER, "3.44", "3.48", "3.46")                            # hay liquidez: el REPLACE a 3,48 llena
    b.avanzar(10)
    persecuciones = [a for a in b.historial if isinstance(a, Reemplazar) and a.token == cruce[0].token]
    assert [r.precio for r in persecuciones] == [D("3.48")]
    assert b.pos().neta_fills == -50
    assert not [a for a in b.historial if isinstance(a, Avisar) and (a.clave or "").startswith("limbo:")]


# ═══════════════════════════ F5: hora y EOD ══════════════════════════════
def test_f5_hora_agrega_va_al_ask_persigue_tres_veces_y_pasa_a_control_humano(cfg: Config, tmp_path: Path) -> None:
    """F5 (R-D-08, R-D-02, corrección 11): agregar a t−60 s, al ask a t, 3 REPLACE de precio como mucho y +30 s control humano."""
    config = cfg_con(cfg, estrategias=[dataclasses.replace(cfg.estrategias[SID], hora_fin_sesion="09:33")])
    b = Banco(config, tmp_path)
    b.preparar()
    abrir_posicion(b)
    lote_id = lote_de(evento())
    assert b.pos().lotes[lote_id].eod == "09:33:00"
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 32, 0, tzinfo=ET))
    agregar = b.enviadas(Proposito.HORA_AGREGAR)
    assert [(o.qty, o.precio, o.post_only) for o in agregar] == [(100, D("3.46"), True)]
    b.cotizar(TICKER, "3.45", "3.47", "3.46", tam_ask=0)                # sin liquidez al ask: nada llena
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 33, 0, tzinfo=ET))
    al_ask = b.enviadas(Proposito.HORA_ASK)
    assert [(o.qty, o.precio) for o in al_ask] == [(100, D("3.47"))]
    assert b.orden(agregar[0].token).estado is EstadoOrden.CANCELED
    for ask in ("3.50", "3.55", "3.60", "3.65"):
        b.cotizar(TICKER, "3.45", ask, "3.46", tam_ask=0)
        b.avanzar(1)
    persecuciones = [a for a in b.historial if isinstance(a, Reemplazar) and a.token == al_ask[0].token]
    assert [r.precio for r in persecuciones] == [D("3.50"), D("3.55"), D("3.60")]   # nunca una cuarta
    assert not [a for a in b.historial if isinstance(a, Cancelar) and a.token == al_ask[0].token]
    assert b.pos().estado is EstadoTicker.NORMAL
    marca = b.marca()
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 33, 31, tzinfo=ET))
    avisos3 = [a for a in b.desde(marca) if isinstance(a, Avisar) and a.nivel is Nivel.MAXIMO]
    assert any("EOD sin cerrar" in a.texto for a in avisos3)
    assert b.pos().estado is EstadoTicker.CONTROL_HUMANO
    assert anotaciones(b.desde(marca), "pausa")[0].datos["estado"] == "control_humano"


# ═══════════════════════════ F6: halt ════════════════════════════════════
def test_f6_halt_una_sola_mkt_por_open_aunque_se_repita_el_issuestatus(banco: Banco) -> None:
    """F6 / injerto §8.23: la MKT por OPEN sale una vez un minuto antes del fin; un $IssueStatus repetido no manda otra."""
    b = banco
    abrir_posicion(b)
    b.libro.halt(TICKER, "P", "09:27:00")                              # LULD: fin previsto 09:32:00
    b.cotizar(TICKER, "4.04", "4.06", "4.05")                           # parado por encima del stop (escenario 2)
    b.avanzar(1.5)
    assert b.pos().estado is EstadoTicker.HALT
    assert f"halt_decidir:{TICKER}" in b.temporizadores
    assert any(isinstance(a, Avisar) and (a.clave or "").startswith(f"halt:{TICKER}") for a in b.historial)
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 31, 1, tzinfo=ET))
    mkt = b.enviadas(Proposito.HALT_OPEN)
    assert [(o.tipo, o.ruta, o.qty, o.lado) for o in mkt] == [(TipoOrden.MERCADO, "OPEN", 100, Lado.COMPRA)]
    assert b.mercado.simbolo(TICKER).orden_open_enviada is True
    b.libro.halt(TICKER, "P", "09:28:30")                               # la bolsa alarga la pausa: $IssueStatus nuevo
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 32, 45, tzinfo=ET))
    assert len(b.enviadas(Proposito.HALT_OPEN)) == 1                    # la guardia: NUNCA una segunda MKT
    assert anotaciones(b.historial, "halt_guardia")
    b.libro.reabrir(TICKER, D("3.95"))
    b.avanzar(2)
    assert b.pos().neta_fills == 0
    assert b.pos().estado is EstadoTicker.NORMAL
    assert all(lote.estado is EstadoLote.CERRADO for lote in b.pos().lotes.values())
    assert any(isinstance(a, Avisar) and a.texto.startswith("[SOMBRA] REABRE") for a in b.historial)


# ═══════════════════════════ F7: cisne negro ═════════════════════════════
def test_f7_cisne_negro_informes_con_cadencia_y_cierre_humano(banco: Banco) -> None:
    """F7 (R-G-01 v2, R-G-03): activación con aviso 3, informes 60 s × 5 y luego 300 s; /cerrar cancela el stop ANTES.

    Stop único (Jaume 29-sep): el umbral es el límite del stop (L + 50 % = 6,00 sobre L = 4,00)."""
    b = banco
    abrir_posicion(b)
    (stop,) = b.enviadas(*STOPS)
    b.cotizar(TICKER, "6.90", "7.10", "7.00")                          # pasa de largo el límite del stop (6,00)
    b.tic_das()
    assert b.pos().estado is EstadoTicker.BS and b.pos().bs is not None
    activacion = [a for a in b.historial if isinstance(a, Avisar) and a.clave == f"bs:{TICKER}"]
    assert len(activacion) == 1 and activacion[0].nivel is Nivel.MAXIMO
    assert cisne_negro.TITULO_INFORME in activacion[0].texto
    b.avanzar(605, tic=5.0)
    claves = [a.clave for a in b.historial if isinstance(a, Avisar) and (a.clave or "").startswith(f"bs:{TICKER}:")]
    assert claves == [f"bs:{TICKER}:{n}" for n in range(1, 7)]          # 5 al minuto y el 6.º a los 5 min del 5.º
    assert not b.enviadas(*STOPS, desde=0)[1:]                           # en BS no se repone ni se persigue nada
    marca = b.marca()
    acciones = b.comando("/cerrar XYZ SI")
    cancelados = [a.token for a in acciones if isinstance(a, Cancelar)]
    assert cancelados[:1] == [stop.token]                               # el stop PRIMERO (R-G-03 (3))
    b.avanzar(1.0)                         # E2-03: la compra sale en la vuelta en que el stop ya figura cancelado
    cierre = b.enviadas(Proposito.CIERRE_HUMANO, desde=marca)
    assert [(o.qty, o.precio) for o in cierre] == [(100, D("7.46"))]   # techo 5 % sobre el ask (R-D-06)
    assert b.pos().neta_fills == 0
    assert b.pos().bs is None and b.pos().sin_reentrada_hasta_sigue is True
    assert not [a for a in b.desde(marca) if isinstance(a, Avisar) and cisne_negro.FRASE_EXITO in a.texto]
    assert anotaciones(b.desde(marca), "bs")[-1].datos["evento"] == "cerrado"


def test_f7_cierre_dentro_del_margen_del_stop_avisa_exito_y_veta_la_reentrada(banco: Banco) -> None:
    """R-G-01 (3): si el stop saca la posición tras activarse el protocolo (dentro de su límite) → aviso 3 con la frase
    literal y veto."""
    b = banco
    abrir_posicion(b)
    b.cotizar(TICKER, "6.90", "7.10", "7.00")
    b.tic_das()
    assert b.pos().estado is EstadoTicker.BS
    marca = b.marca()
    b.cotizar(TICKER, "5.95", "6.00", "6.00")                           # vuelve: el stop (límite 6,00) llena
    b.tic_das()
    assert b.pos().neta_fills == 0 and b.pos().bs is None
    exito = [a for a in b.desde(marca) if isinstance(a, Avisar) and cisne_negro.FRASE_EXITO in a.texto]
    assert len(exito) == 1 and exito[0].nivel is Nivel.MAXIMO
    assert b.pos().sin_reentrada_hasta_sigue is True
    acciones = b.senal(evento(momento=otra_vela(b)))
    assert anotaciones(acciones, "senal_descartada")[0].datos["motivo"] == reglas_entrada.MOTIVO_REENTRADA


def test_f7_parar_avisos_silencia_solo_los_informes(banco: Banco) -> None:
    """F7: /parar_avisos (dos pasos) deja de mandar el informe periódico; el protocolo sigue."""
    b = banco
    abrir_posicion(b)
    b.cotizar(TICKER, "6.90", "7.10", "7.00")
    b.tic_das()
    b.comando("/parar_avisos")
    marca = b.marca()
    b.avanzar(130, tic=5.0)
    assert not [a for a in b.desde(marca) if isinstance(a, Avisar) and (a.clave or "").startswith(f"bs:{TICKER}")]
    assert b.pos().estado is EstadoTicker.BS and b.pos().bs.silenciado is True


# ═══════════════════════════ F8: rechazos ════════════════════════════════
def test_f8_rechazo_conocido_reintenta_con_token_nuevo_y_nunca_un_tercero(cfg: Config, tmp_path: Path) -> None:
    """R-B-07: un rechazo conocido de «reintentar» → 2 reintentos con token NUEVO (re-preciados al libro) y al tercero,
    pausa. (D2-09: «PostOnly would cross» ya no es de «reintentar»; la mecánica va con una entrada sintética.)"""
    b = Banco(cfg, tmp_path, catalogo=CATALOGO_CON_REINTENTO)
    b.preparar()
    for _ in range(3):
        b.libro.rechazar_siguiente("Rechazo de prueba")
    b.senal(evento())
    envios = b.enviadas(Proposito.ENTRADA_AGREGAR)
    assert len(envios) == 3 and len({o.token for o in envios}) == 3
    assert [b.orden(o.token).intentos for o in envios] == [0, 1, 2]
    assert all(b.orden(o.token).estado is EstadoOrden.REJECTED for o in envios)
    avisos_rechazo = [a for a in b.historial if isinstance(a, Avisar) and (a.clave or "").startswith(f"rechazo:{TICKER}:")]
    assert len(avisos_rechazo) == 3 and all("Rechazo de prueba" in a.texto for a in avisos_rechazo)
    assert b.pos().estado is EstadoTicker.PAUSADO and b.pos().intento is None
    assert anotaciones(b.historial, "rechazo")[-1].datos["decision"] == rechazos.DECISION_PAUSA


def test_d2_09_entrada_rechazada_por_postonly_pasa_al_cruce_sin_pausa(banco: Banco) -> None:
    """D2-09 (decisión del director): el agregar de la entrada rechazado por «PostOnly would cross» NO se reintenta al
    mismo precio ni pausa el ticker: pasa YA a la fase de cruce de R-B-01 v3 (bid · (1 − 0,5 %))."""
    b = banco
    b.libro.rechazar_siguiente("PostOnly would cross")
    b.simstatus()
    b.senal(evento())
    assert b.temporizadores[next(k for k in b.temporizadores if k.startswith("cruce_postonly:"))][0] == b.ahora()
    b.avanzar(0)                                                        # el temporizador de 0 s: el cruce sale ya
    agregar = b.enviadas(Proposito.ENTRADA_AGREGAR)
    cruce = b.enviadas(Proposito.ENTRADA_CRUCE)
    assert len(agregar) == 1 and b.orden(agregar[0].token).estado is EstadoOrden.REJECTED
    assert [(o.qty, o.precio, o.post_only) for o in cruce] == [(100, D("3.42"), False)]
    assert b.pos().estado is EstadoTicker.NORMAL
    assert f"cruce:{TICKER}" not in b.temporizadores                   # ya no se espera a t_limite
    assert any(a.datos.get("fase") == "cruzando" for a in anotaciones(b.historial, "intento"))


def test_f8_rechazo_desconocido_con_la_posicion_cubierta_pausa(banco: Banco) -> None:
    """R-B-07 (3): texto desconocido y el stop CONFIRMADO → ticker PAUSADO, aviso 2 y ninguna orden nueva."""
    b = banco
    abrir_posicion(b)
    b.libro.rechazar_siguiente("Algo raro 123")
    marca = b.marca()
    ev = salida()
    b.procesar(SenalRecibida(Senal(clase="evento", ticker=TICKER, id=id_de_evento(ev), evento=ev, momento=ev.momento,
                                   recibida_en=b.ahora())))
    tras = b.desde(marca)
    rechazado = b.enviadas(Proposito.TP_AGREGAR, desde=marca)
    assert len(rechazado) == 1 and b.orden(rechazado[0].token).estado is EstadoOrden.REJECTED
    aviso = [a for a in tras if isinstance(a, Avisar) and (a.clave or "").startswith("rechazo:")]
    assert len(aviso) == 1 and aviso[0].nivel is Nivel.AVISO
    assert b.pos().estado is EstadoTicker.PAUSADO
    assert len(b.enviadas(desde=marca)) == 1                            # solo el TP rechazado: ningún reintento


def test_f8_rechazo_desconocido_sin_cubrir_avisa_3_sin_orden_y_repone_el_stop(banco: Banco) -> None:
    """R-B-07 (3) / R-C-03 / EP-1: el stop rechazado deja la posición sin cubrir (stop único, Jaume 29-sep) → nivel 3,
    control humano, sin orden al instante; tras la separación se repone (reintento 1/5)."""
    b = banco
    b.senal(evento())
    b.libro.rechazar_siguiente("Algo raro 123")                         # el siguiente NEWORDER: el stop
    b.cotizar(TICKER, "3.45", "3.47", "3.45")
    marca = b.marca()
    b.dar(b.das.tic())
    rechazo = anotaciones(b.desde(marca), "rechazo")
    assert len(rechazo) == 1 and rechazo[0].datos["cubierta"] is False
    lote_rechazo = next(i for i, a in enumerate(b.desde(marca)) if isinstance(a, Anotar) and a.tipo == "rechazo")
    tanda = []
    for a in b.desde(marca)[lote_rechazo:]:
        if isinstance(a, Anotar) and a.tipo == "orden_estado":
            break
        tanda.append(a)
    assert [a.nivel for a in tanda if isinstance(a, Avisar)] == [Nivel.MAXIMO]
    assert not [a for a in tanda if isinstance(a, EnviarOrden)]         # EP-1: el bot no cierra ni repone al instante
    assert b.pos().estado is EstadoTicker.CONTROL_HUMANO
    marca = b.marca()
    b.avanzar(2.5)
    repuesto = b.enviadas(Proposito.STOP, desde=marca)
    assert len(repuesto) == 1 and b.orden(repuesto[0].token).intentos == 1   # R-C-03: reintento 1/5


def test_f8_stop_rechazado_siempre_se_reintenta_cinco_veces_y_nunca_en_bucle(banco: Banco) -> None:
    """R-C-03: un stop que DAS rechaza siempre → 5 reintentos separados 2 s (6 envíos) y ninguno más, ni desde el barrido.

    Stop único (Jaume 29-sep): agotados los reintentos esas acciones quedan
    SIN stop → aviso MÁXIMO y CONTROL HUMANO; el bot NO cierra (EP-1) y el
    ejecutor no insiste (lo sigue intentando el vigilante, plan B)."""
    b = banco
    b.rechazar[Proposito.STOP] = "Algo raro 123"
    abrir_posicion(b)
    b.avanzar(1.5)
    assert len(b.enviadas(Proposito.STOP)) == 1                          # el barrido NO lo repone durante la separación
    b.avanzar(20, tic=0.5)
    stops_ = b.enviadas(Proposito.STOP)
    assert [b.orden(o.token).intentos for o in stops_] == [0, 1, 2, 3, 4, 5]
    assert all(b.orden(o.token).estado is EstadoOrden.REJECTED for o in stops_)
    agotado = [a for a in anotaciones(b.historial, "rechazo") if a.datos["decision"] == rechazos.DECISION_STOP_AGOTADO]
    assert len(agotado) == 1
    aviso = [a for a in b.historial if isinstance(a, Avisar) and "SIN STOP" in a.texto]
    assert aviso and all(a.nivel is Nivel.MAXIMO for a in aviso) and "vigilante" in aviso[-1].texto
    b.avanzar(30, tic=2.0)
    assert len(b.enviadas(Proposito.STOP)) == 6                          # agotado: ni el plan ni la reconciliación insisten
    assert b.pos().estado is EstadoTicker.CONTROL_HUMANO and b.pos().neta_fills == -100
    assert [o for o in b.enviadas() if o.lado is Lado.COMPRA and o.proposito is not Proposito.STOP] == []   # no cierra


# ═══════════════════════════ F9: locates ═════════════════════════════════
def test_f9_locates_escalonados_de_dos_estrategias_con_su_coste(cfg: Config, tmp_path: Path) -> None:
    """F9 (R-H-01/05, E9): cada estrategia compra lo suyo con su EV; el gasto del día suma los dos; E9 no quita lo ajeno."""
    config = cfg_con(cfg, estrategias=[cfg.estrategias[SID], estrategia_b(cfg)])
    b = Banco(config, tmp_path)
    b.preparar(locates=())
    estimacion = [{"strategy_id": SID, "acciones": 1000.0, "riesgo_usd": 300.0},
                  {"strategy_id": SID2, "acciones": 500.0, "riesgo_usd": 150.0}]
    acciones = b.procesar(SenalRecibida(Senal(clase="radar", ticker=TICKER, id=None, estimacion=estimacion,
                                              precio_radar=D("3.45"), recibida_en=b.ahora())))
    consultas = [a for a in acciones if isinstance(a, LocateInquire)]
    assert [(c.ticker, c.qty, c.ruta) for c in consultas] == [(TICKER, 1000, "ALLROUTEWTTYPE1"),
                                                             (TICKER, 500, "ALLROUTEWTTYPE1")]
    assert not [a for a in b.historial if isinstance(a, LocateComprar)]  # E2-05: las ofertas se recogen 0,5 s
    b.avanzar(1)
    compras = [a for a in b.historial if isinstance(a, LocateComprar)]
    assert [(c.qty, c.ruta) for c in compras] == [(1000, "LOCSIM"), (500, "LOCSIM")]
    assert all(descomponer(c.token)[0] is Origen.EJECUTOR_LOCATE for c in compras)
    locs = b.estado.locates
    assert (locs[(TICKER, SID)].estado, locs[(TICKER, SID)].localizadas) == ("Located", 1000)
    assert (locs[(TICKER, SID2)].estado, locs[(TICKER, SID2)].localizadas) == ("Located", 500)
    assert b.estado.gasto_locates_dia == D("15.00")                    # 1.000 × 0,01 + 500 × 0,01
    b.avanzar(4)
    assert len([a for a in b.historial if isinstance(a, LocateComprar)]) == 2   # cerrojo R-H-02: no se recompra
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    b.senal(evento(strategy_id=SID2, estrategia="PM (B) prueba", acciones=800.0, momento=momento_de(b.reloj.ahora())))
    assert [o.qty for o in b.enviadas(Proposito.ENTRADA_AGREGAR)] == [500]   # E9: el locate de A no es sobrante
    assert locs[(TICKER, SID2)].usadas == 500 and locs[(TICKER, SID)].usadas == 0


# ═══════════════════════════ F10: reconciliación ═════════════════════════
def _estado_con_lote(neta: int = -100, llenas: int = 100) -> EstadoBot:
    estado = EstadoBot(fase=Fase.SOMBRA, dia=HOY)
    pos = PosicionTicker(ticker=TICKER, neta_fills=neta)
    lote = Lote(id=lote_de(evento()), strategy_id=SID, estrategia="PM (A) prueba", ticker=TICKER, direccion="Short",
                pedidas=100, llenas=llenas, precio_medio=D("3.45"), nivel_stop=D("4.0"), estado=EstadoLote.ABIERTO,
                eod="11:30:00")
    pos.lotes[lote.id] = lote
    estado.posiciones[TICKER] = pos
    estado.senales_vistas.add(lote.id)
    return estado


def _caso(cfg: Config, tmp_path: Path, n: int) -> Banco:
    if n in (1, 2):
        b = Banco(cfg, tmp_path)
        b.preparar()
        abrir_posicion(b)
        b.avanzar(3)
        if n == 2:
            stop = b.enviadas(Proposito.STOP)[0]
            b.das.recibir(f"REPLACE {b.orden(stop.token).id_das} 60 STOPLMT 4 6")               # la mano humana
        return b
    if n == 4:
        b = Banco(cfg, tmp_path)
        b.das.recibir("NEWORDER 12345 SS XYZ SAGEREB 100 5.00 TIF=DAY+")                     # token ajeno (mano humana)
        b.preparar(reconciliar=False)
        return b
    netas = {3: -100, 5: 0, 6: -60}
    b = Banco(cfg, tmp_path, estado=_estado_con_lote())
    b.libro.sembrar_posicion(TICKER, netas[n], D("3.45"))
    b.preparar(reconciliar=False)
    return b


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 6], ids=[f"R-C-10-caso{n}" for n in range(1, 7)])
def test_f10_los_seis_casos_de_la_reconciliacion(cfg: Config, tmp_path: Path, n: int) -> None:
    """F10 (R-C-10, R-K-01/02, M7): cada caso sale clasificado y con su acción."""
    b = _caso(cfg, tmp_path, n)
    marca = b.marca()
    b.avanzar(3)
    tras = b.desde(marca)
    casos = [a.datos["casos"].get(TICKER) for a in anotaciones(tras, "reconciliacion") if TICKER in a.datos["casos"]]
    assert casos and casos[0] == n
    if n == 1:
        assert not b.enviadas(*STOPS, desde=marca)
    elif n == 2:
        stop = b.enviadas(Proposito.STOP)[0]
        assert [(r.token, r.qty) for r in acciones_de(tras, Reemplazar)][:1] == [(stop.token, 100)]
    elif n == 3:
        assert [o.proposito.value for o in b.enviadas(*STOPS, desde=marca)] == ["stop"]      # stop único
        assert any(isinstance(a, Avisar) and (a.clave or "").startswith("reconciliacion_sin_stop") for a in tras)
    elif n == 4:
        # R-M-03 por ticker (Jaume 29-sep): solo ese ticker en manos del humano, sin pausa global
        assert b.estado.pausa_global is False and b.estado.ordenes_ajenas
        assert b.pos().estado is EstadoTicker.CONTROL_HUMANO and b.pos().intervencion_humana is True
        assert any(isinstance(a, Avisar) and a.nivel is Nivel.MAXIMO and (a.clave or "").startswith("ajena:")
                   for a in tras)
    elif n == 5:
        assert all(lote.estado is EstadoLote.CERRADO for lote in b.pos().lotes.values())
        assert b.pos().neta_fills == 0
    else:
        assert b.pos().neta_fills == -60
        assert anotaciones(tras, "discrepancia")[0].datos["neta_das"] == -60
        assert sorted((o.proposito.value, o.qty) for o in b.enviadas(*STOPS, desde=marca)) == [("stop", 60)]


# ═══════════════════════════ F11: modos degradados ═══════════════════════
@pytest.mark.parametrize("modo", ["feed", "das", "reconciliacion", "disco"], ids=[
    "R-J-01-feed", "R-J-02-das", "R-K-03-reconciliacion", "correccion4-disco"])
def test_f11_modo_degradado_bloquea_entradas_avisa_y_se_recupera(cfg: Config, tmp_path: Path, modo: str) -> None:
    """F11 / R-J-03: cada modo degradado se avisa, impide abrir y se levanta al recuperarse."""
    b = Banco(cfg, tmp_path, latidos=(modo != "feed"))
    b.preparar()
    marca = b.marca()
    if modo == "feed":
        b.avanzar(62)
        clave, nivel = "feed_emergencia", Nivel.MAXIMO
    elif modo == "das":
        b.procesar(ConexionDAS(False, "EOF"))
        clave, nivel = "das_caido", Nivel.MAXIMO
    elif modo == "reconciliacion":
        b.das_contesta = False
        b.avanzar(32)
        clave, nivel = "reconciliacion_caducada", Nivel.AVISO
    else:
        b.disco_roto = True
        b.avanzar(1)
        clave, nivel = "disco", Nivel.MAXIMO
    assert modo in b.estado.modo_degradado
    aviso = [a for a in b.desde(marca) if isinstance(a, Avisar) and a.clave == clave]
    assert len(aviso) == 1 and aviso[0].nivel is nivel
    b.das_contesta = True
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    acciones = b.senal(evento(momento=momento_de(b.reloj.ahora())))
    assert anotaciones(acciones, "senal_descartada")[0].datos["motivo"] == reglas_entrada.MOTIVO_DEGRADADO
    assert not b.enviadas(Proposito.ENTRADA_AGREGAR)
    if modo == "das":
        marca = b.marca()
        b.avanzar(301, tic=10.0)
        assert [a.nivel for a in b.desde(marca) if isinstance(a, Avisar) and (a.clave or "").startswith("das_caido:")] \
            == [Nivel.MAXIMO]                                           # R-J-02 (3): cada 5 min
        b.procesar(ConexionDAS(True, "reconectado"))
        assert "das" not in b.estado.modo_degradado and "reconciliacion" in b.estado.modo_degradado
    elif modo == "feed":
        b.latidos = True
    elif modo == "disco":
        b.disco_roto = False
    b.avanzar(11)
    assert modo not in b.estado.modo_degradado


def test_login_rechazado_aviso_maximo_unico_y_queda_como_das_caido(cfg: Config, tmp_path: Path) -> None:
    """DAS real (01-oct): «ERROR:INVALID PASSWORD» → aviso 3 al grupo B UNA sola vez (ni con un segundo rechazo, ni
    con la `ConexionDAS(False)` que llega detrás, ni cada 5 min), modo degradado «das» y no se abre nada. El texto dice
    qué revisar y que no se reintenta; nunca lleva la clave (solo el texto de DAS)."""
    from app.bot_das.tipos import MsgLogin
    b = Banco(cfg, tmp_path)
    b.preparar()
    marca = b.marca()
    rechazo = MsgLogin(cruda="ERROR:INVALID PASSWORD", ok=False, motivo="INVALID PASSWORD")
    tras = b.procesar(DeDAS(rechazo))
    assert {k: anotaciones(tras, "das_login")[0].datos[k] for k in ("ok", "motivo")} == {"ok": False, "motivo": "INVALID PASSWORD"}
    b.procesar(ConexionDAS(False, "DAS rechazó el LOGIN: INVALID PASSWORD; no se reintenta"))
    b.procesar(DeDAS(rechazo))
    b.avanzar(301, tic=10.0)
    avisos_ = [a for a in b.desde(marca) if isinstance(a, Avisar)]
    login = [a for a in avisos_ if a.clave == "das_logon:LOGIN"]
    assert len(login) == 1 and login[0].nivel is Nivel.MAXIMO and login[0].grupo is Grupo.B
    for trozo in ("DAS rechazó el LOGIN: INVALID PASSWORD", "DAS_USUARIO / DAS_CLAVE / DAS_CUENTA", ".env",
                  "no se reintenta"):
        assert trozo in login[0].texto
    assert not [a for a in avisos_ if (a.clave or "").startswith("das_caido")]    # ni «DESCONECTADO» ni cada 5 min
    assert "das" in b.estado.modo_degradado and b.estado.das_conectado is False
    assert b.estado.das_logon["LOGIN"] is False
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    acciones = b.senal(evento(momento=momento_de(b.reloj.ahora())))
    assert anotaciones(acciones, "senal_descartada")[0].datos["motivo"] == reglas_entrada.MOTIVO_DEGRADADO
    assert not b.enviadas(Proposito.ENTRADA_AGREGAR)


def test_login_aceptado_solo_al_diario_y_al_estado(cfg: Config, tmp_path: Path) -> None:
    """«#LOGIN SUCCESSED» no avisa: queda en el diario y en `das_logon["LOGIN"]` (lo enseña /salud)."""
    from app.bot_das.tipos import MsgLogin
    b = Banco(cfg, tmp_path)
    b.preparar()
    tras = b.procesar(DeDAS(MsgLogin(cruda="#LOGIN SUCCESSED", ok=True, motivo="SUCCESSED")))
    assert {k: anotaciones(tras, "das_login")[0].datos[k] for k in ("ok", "motivo")} == {"ok": True, "motivo": "SUCCESSED"}
    assert not [a for a in tras if isinstance(a, Avisar)]
    assert b.estado.das_logon["LOGIN"] is True and "das" not in b.estado.modo_degradado


def test_f11_con_el_disco_roto_no_sale_la_entrada_pero_si_los_stops(banco: Banco) -> None:
    """Corrección 4: diario roto → el cruce NO sale (el intento se cierra con lo llenado) y los stops de lo llenado SÍ."""
    b = banco
    b.libro.llenar_parcial(D("0.4"), TICKER)                            # la venta agregada llenará 40 de 100
    b.senal(evento())
    b.disco_roto = True
    b.avanzar(1)
    assert "disco" in b.estado.modo_degradado
    llenar_entrada(b)
    stops_ = b.enviadas(*STOPS)
    assert sorted((o.proposito.value, o.qty) for o in stops_) == [("stop", 40)]          # stop único (Jaume 29-sep)
    b.avanzar(61)
    assert not b.enviadas(Proposito.ENTRADA_CRUCE)
    assert b.pos().intento is None
    lote = b.pos().lotes[lote_de(evento())]
    assert (lote.estado, lote.llenas) == (EstadoLote.ABIERTO, 40)


# ═══════════════════════════ F12 / F13: arranque ═════════════════════════
def test_f12_f13_arranque_adopta_los_stops_del_vigilante_y_no_repite_la_senal(cfg: Config, tmp_path: Path) -> None:
    """F13 / corrección 3: los stops que puso el vigilante se ADOPTAN (no se duplican); F12: señal ya vista → 0 órdenes."""
    b = Banco(cfg, tmp_path, estado=_estado_con_lote())
    b.libro.sembrar_posicion(TICKER, -100, D("3.45"))
    vigilante = GeneradorTokens(Origen.VIGILANTE, HOY)
    for stop, limite in ((D("4.00"), D("6.00")),):                     # el stop único del nivel (Jaume 29-sep)
        b.das.recibir(protocolo.cmd_neworder(OrdenNueva(token=vigilante.siguiente(), lado=Lado.COMPRA, ticker=TICKER,
                                                        ruta="STOP", qty=100, tipo=TipoOrden.STOP_LIMITE_PP,
                                                        precio=limite, stop=stop)))
    b.preparar(locates=())
    b.avanzar(3)
    assert not b.enviadas(*STOPS)
    adoptadas = [o for o in b.estado.ordenes.values() if o.origen is Origen.VIGILANTE]
    assert len(adoptadas) == 1 and len(anotaciones(b.historial, "orden_adoptada")) == 1
    casos = [a.datos["casos"].get(TICKER) for a in anotaciones(b.historial, "reconciliacion")]
    assert casos[-1] == 1
    lote_id = lote_de(evento())
    assert any(isinstance(a, Programar) and a.clave == f"eod_comprobar:{lote_id}" for a in b.historial)
    marca = b.marca()
    acciones = b.senal(evento())
    assert [a.tipo for a in acciones if isinstance(a, Anotar)] == ["senal_repetida"]
    assert not b.enviadas(desde=marca)


def test_f13_intento_a_medias_se_cierra_con_lo_llenado(cfg: Config, tmp_path: Path) -> None:
    """F13: lotes ABRIENDO tras un reinicio → ABIERTO con lo llenado (y sus temporizadores) o CANCELADO sin fills."""
    estado = _estado_con_lote(neta=-30, llenas=30)
    lote = next(iter(estado.posiciones[TICKER].lotes.values()))
    lote.estado = EstadoLote.ABRIENDO
    vacio = dataclasses.replace(lote, id=lote.id.replace(SID, SID2), strategy_id=SID2, llenas=0)
    estado.posiciones[TICKER].lotes[vacio.id] = vacio
    b = Banco(cfg, tmp_path, estado=estado)
    b.libro.sembrar_posicion(TICKER, -30, D("3.45"))
    b.preparar(locates=())
    lotes = b.pos().lotes
    assert (lotes[lote.id].estado, lotes[lote.id].llenas) == (EstadoLote.ABIERTO, 30)
    assert lotes[vacio.id].estado is EstadoLote.CANCELADO
    assert anotaciones(b.historial, "intento_fin")
    assert f"hora_ask:{lote.id}" in b.temporizadores
    b.avanzar(3)
    assert sorted((o.proposito.value, o.qty) for o in b.enviadas(*STOPS)) == [("stop", 30)]


# ═══════════════════════════ F14: estrategia desactivada ═════════════════
@pytest.mark.parametrize("modo,cierra", [("cerrar_y_reiniciar", True), ("esperar_fin_dia", False)],
                         ids=["R-E-03-cerrar_y_reiniciar", "R-E-03-esperar_fin_dia"])
def test_f14_estrategia_desactivada_con_lote_vivo(banco: Banco, cfg: Config, modo: str, cierra: bool) -> None:
    """F14 / R-E-03: ejecutar true→false con un lote vivo: cerrar_y_reiniciar agrega y va al ask; esperar_fin_dia no toca."""
    b = banco
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    e = dataclasses.replace(cfg.estrategias[SID], ejecutar=False, al_desactivar=modo)
    nueva = dataclasses.replace(cfg, config_version=2, estrategias={SID: e})
    marca = b.marca()
    acciones = b.procesar(ConfigNueva(nueva, None))
    cambios = {a.datos["ruta"]: a.datos["aplicado"] for a in anotaciones(acciones, "config_cambio")}
    esperado = {f"estrategias.{SID}.ejecutar": True}
    if modo != cfg.estrategias[SID].al_desactivar:
        esperado[f"estrategias.{SID}.al_desactivar"] = True
    assert cambios == esperado                                          # los dos son [C]: se aplican con el bot encendido
    assert b.decisor.cfg.estrategias[SID].ejecutar is False
    cierre = b.enviadas(Proposito.CIERRE_REINICIO, desde=marca)
    lote_id = lote_de(evento())
    if not cierra:
        assert not cierre and b.pos().lotes[lote_id].estado is EstadoLote.ABIERTO
        return
    assert [(o.qty, o.post_only) for o in cierre] == [(100, True)]
    assert anotaciones(acciones, "cierre_reinicio")
    b.avanzar(61)
    al_ask = [o for o in b.enviadas(Proposito.CIERRE_REINICIO, desde=marca) if not o.post_only]
    assert [o.qty for o in al_ask] == [100]
    assert b.pos().neta_fills == 0


def test_f14_cambio_de_version_con_el_bot_encendido_se_rechaza(banco: Banco, cfg: Config) -> None:
    """R-O-01 / R-E-03: un definition_hash nuevo con el bot encendido es [A]: se rechaza, se anota y se avisa nivel 2."""
    b = banco
    abrir_posicion(b)
    e = dataclasses.replace(cfg.estrategias[SID], definition_hash=HASH_B)
    acciones = b.procesar(ConfigNueva(dataclasses.replace(cfg, config_version=3, estrategias={SID: e}), None))
    cambio = anotaciones(acciones, "config_cambio")
    assert [(a.datos["ruta"], a.datos["aplicado"]) for a in cambio] == [(f"estrategias.{SID}.definition_hash", False)]
    assert any(isinstance(a, Avisar) and a.nivel is Nivel.AVISO and "RECHAZADOS" in a.texto for a in acciones)
    assert b.decisor.cfg.estrategias[SID].definition_hash == cfg.estrategias[SID].definition_hash
    assert not acciones_de(acciones, EnviarOrden)


# ═══════════════════════════ trampas transversales ═══════════════════════
def test_h5_evento_sin_precio_pausa_su_ticker_y_el_siguiente_mensaje_se_procesa(cfg: Config, tmp_path: Path) -> None:
    """H-5: una excepción en la rama de un ticker → diario con traceback, ese ticker PAUSADO, aviso 2 y el bucle sigue."""
    b = Banco(cfg, tmp_path)
    b.preparar(locates=((TICKER, SID, 1000), (OTRO, SID, 1000)),
               cotizaciones=((TICKER, "3.44", "3.46", "3.45"), (OTRO, "3.44", "3.46", "3.45")))
    acciones = b.senal(evento(precio=None))
    excepcion = anotaciones(acciones, "excepcion")
    assert len(excepcion) == 1 and excepcion[0].datos["ticker"] == TICKER and "Traceback" in excepcion[0].datos["traceback"]
    assert b.pos().estado is EstadoTicker.PAUSADO and b.pos().motivo_estado == "excepcion"
    assert any(isinstance(a, Avisar) and a.nivel is Nivel.AVISO for a in acciones)
    b.senal(evento(ticker=OTRO))
    assert [o.ticker for o in b.enviadas(Proposito.ENTRADA_AGREGAR)] == [OTRO]


def test_senal_repetida_no_manda_ninguna_orden(banco: Banco) -> None:
    """R-A-05: la misma señal dos veces → la segunda solo se anota como repetida."""
    b = banco
    b.senal(evento())
    marca = b.marca()
    acciones = b.senal(evento())
    assert [a.tipo for a in acciones if isinstance(a, Anotar)] == ["senal_repetida"]
    assert not b.enviadas(desde=marca)


def test_senal_de_otra_cuenta_se_ignora_con_anotacion(banco: Banco) -> None:
    """Multicuenta: un `Evento` con `cuenta` no es de este ejecutor (comprobación 3): se anota, sin aviso ni orden."""
    b = banco
    acciones = b.senal(evento(cuenta="socio"))
    assert anotaciones(acciones, "senal_descartada")[0].datos["motivo"] == reglas_entrada.MOTIVO_ESTRATEGIA
    assert not acciones_de(acciones, Avisar) and not b.enviadas()


def test_estrategia_sin_ev_no_ejecuta_y_avisa_una_vez_al_dia(cfg: Config, tmp_path: Path) -> None:
    """Decisión 23 (Jaume 30-sep): sin EV en el cuadro → señales descartadas «sin ejecutar» y aviso nivel 2 al B 1 vez/día."""
    e = dataclasses.replace(cfg.estrategias[SID], ejecutar=False, sin_ev=True, ev_pct=Decimal("0"))
    b = Banco(cfg_con(cfg, estrategias=[e]), tmp_path)
    b.conectar()
    arranque = b.arrancar()
    b.preparar(locates=((TICKER, SID, 1000), (OTRO, SID, 1000)),
               cotizaciones=((TICKER, "3.44", "3.46", "3.45"), (OTRO, "3.44", "3.46", "3.45")))
    primera = b.senal(evento())
    segunda = b.senal(evento(ticker=OTRO))
    # Jaume 30-sep: el aviso sale ya AL ARRANCAR; con la señal no se repite (misma clave, una vez al día)
    avisos_ = [a for a in arranque if isinstance(a, Avisar) and a.clave == f"sin_ev:{SID}"]
    assert len(avisos_) == 1 and avisos_[0].nivel == Nivel.AVISO and avisos_[0].grupo == Grupo.B
    assert "sin EV en el cuadro: no ejecuta hasta que lo pongas" in avisos_[0].texto
    for acc in (primera, segunda):
        assert not [a for a in acc if isinstance(a, Avisar) and a.clave == f"sin_ev:{SID}"]
    for acc in (primera, segunda):
        assert anotaciones(acc, "senal_descartada")[0].datos["motivo"] == reglas_entrada.MOTIVO_ESTRATEGIA
    assert not b.enviadas()
    b.decisor._override_estrategia[SID] = {"ejecutar": True}          # /activar no la enciende sin EV
    b.decisor._recomponer_cfg()
    assert b.decisor._cfg.estrategias[SID].ejecutar is False


def test_decision_20_repeticiones_no_ejecuta_y_avisa_una_vez_al_dia(cfg: Config, tmp_path: Path) -> None:
    """Decisión 20 (Jaume 30-sep): pirámide con repeticiones → señales «sin ejecutar», aviso nivel 2 al B una vez al
    día (al arrancar; la señal no lo repite) y ni /activar la enciende."""
    e = dataclasses.replace(cfg.estrategias[SID], ejecutar=False, con_repeticiones=True)
    b = Banco(cfg_con(cfg, estrategias=[e]), tmp_path)
    b.conectar()
    arranque = b.arrancar()
    b.preparar(locates=((TICKER, SID, 1000),), cotizaciones=((TICKER, "3.44", "3.46", "3.45"),))
    primera = b.senal(evento())
    avisos_ = [a for a in arranque if isinstance(a, Avisar) and a.clave == f"repeticiones:{SID}"]
    assert len(avisos_) == 1 and avisos_[0].nivel == Nivel.AVISO and avisos_[0].grupo == Grupo.B
    assert "pirámide con repeticiones: no soportada aún" in avisos_[0].texto
    assert not [a for a in primera if isinstance(a, Avisar) and a.clave == f"repeticiones:{SID}"]
    assert anotaciones(primera, "senal_descartada")[0].datos["motivo"] == reglas_entrada.MOTIVO_ESTRATEGIA
    assert not b.enviadas()
    b.decisor._override_estrategia[SID] = {"ejecutar": True}
    b.decisor._recomponer_cfg()
    assert b.decisor._cfg.estrategias[SID].ejecutar is False


def test_decision_20_times_1_ejecuta_normal_sin_aviso(cfg: Config, tmp_path: Path) -> None:
    """Decisión 20: sin repeticiones (times=1) la estrategia ejecuta como siempre y no hay aviso."""
    b = Banco(cfg, tmp_path)
    b.conectar()
    assert b.decisor._cfg.estrategias[SID].con_repeticiones is False
    assert not [a for a in b.arrancar() if isinstance(a, Avisar) and a.clave == f"repeticiones:{SID}"]


def test_estrategia_sin_ev_avisa_al_recargar_el_cuadro_una_sola_vez(cfg: Config, tmp_path: Path) -> None:
    """Jaume 30-sep: si una recarga del cuadro deja una estrategia sin EV, aviso nivel 2 al B ya; otra recarga no lo repite."""
    b = Banco(cfg, tmp_path)
    b.conectar()
    assert not [a for a in b.arrancar() if isinstance(a, Avisar) and a.clave == f"sin_ev:{SID}"]
    e = dataclasses.replace(cfg.estrategias[SID], ejecutar=False, sin_ev=True, ev_pct=Decimal("0"))
    primera = b.procesar(ConfigNueva(dataclasses.replace(cfg, config_version=3, estrategias={SID: e}), None))
    avisos_ = [a for a in primera if isinstance(a, Avisar) and a.clave == f"sin_ev:{SID}"]
    assert len(avisos_) == 1 and avisos_[0].nivel == Nivel.AVISO and avisos_[0].grupo == Grupo.B
    segunda = b.procesar(ConfigNueva(dataclasses.replace(cfg, config_version=4, estrategias={SID: e}), None))
    assert not [a for a in segunda if isinstance(a, Avisar) and a.clave == f"sin_ev:{SID}"]
    assert not [a for a in b.arrancar() if isinstance(a, Avisar) and a.clave == f"sin_ev:{SID}"]


def test_senal_larga_con_un_corto_abierto_se_descarta(banco: Banco) -> None:
    """R-E-01: solo cortos; un largo contra un corto vivo se descarta y se avisa nivel 1."""
    b = banco
    abrir_posicion(b)
    momento = otra_vela(b)
    marca = b.marca()
    acciones = b.senal(evento(direccion="Long", momento=momento))
    # Jaume 29-sep (estricto): con la primera señal del día ya consumida por la entrada, esta se descarta antes como
    # «principal posterior»; R-E-01 (solo cortos) sigue cubierto por los tests puros de `evaluar_senal`.
    assert anotaciones(acciones, "senal_descartada") and anotaciones(acciones, "senal_principal_posterior")
    assert not b.enviadas(desde=marca)


def test_config_en_caliente_entre_mensajes_y_el_intento_conserva_su_copia(banco: Banco, cfg: Config) -> None:
    """CM2 / riesgo 21: lo [C] se aplica al siguiente mensaje; lo [T] de «entrada» se rechaza con el intento vivo, que cruza
    con SU copia congelada (bid · (1 − 0,5 %))."""
    b = banco
    b.senal(evento())
    congelada = dict(b.pos().intento.cfg_congelada)
    nueva = dataclasses.replace(cfg, config_version=2, modo_seguridad={**cfg.modo_seguridad, "activo": True},
                                entrada={**cfg.entrada, "cruce_bajo_bid_pct": 2.0})
    acciones = b.procesar(ConfigNueva(nueva, None))
    aplicado = {a.datos["ruta"]: a.datos["aplicado"] for a in anotaciones(acciones, "config_cambio")}
    assert aplicado == {"modo_seguridad.activo": True, "entrada.cruce_bajo_bid_pct": False}
    assert b.decisor.cfg.modo_seguridad["activo"] is True
    assert b.pos().intento.cfg_congelada == congelada
    b.cotizar(OTRO, "3.44", "3.46", "3.45")
    b.estado.locates[(OTRO, SID)] = Locate(ticker=OTRO, strategy_id=SID, pedidas=100, localizadas=100, estado="Located")
    descartada = b.senal(evento(ticker=OTRO))
    assert anotaciones(descartada, "senal_descartada")[0].datos["motivo"] == reglas_entrada.MOTIVO_MODO_SEGURIDAD
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    b.avanzar(60.5)
    cruce = b.enviadas(Proposito.ENTRADA_CRUCE)
    assert [(o.qty, o.precio, o.ruta) for o in cruce] == [(100, D("3.42"), "SAGEPRO")]


def test_fill_con_un_reemplazar_pendiente_invalida_la_serie_antes_del_plan_nuevo(banco: Banco) -> None:
    """Injerto §8.6: un fill nuevo con un REPLACE de stops aún en vuelo → `InvalidarSerie` (versión nueva) ANTES del plan."""
    b = banco
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    ev = salida(acciones=30.0)
    b.procesar(SenalRecibida(Senal(clase="evento", ticker=TICKER, id=id_de_evento(ev), evento=ev, momento=ev.momento,
                                   recibida_en=b.ahora())))
    b.cotizar(TICKER, "3.43", "3.45", "3.45", tam_ask=10)
    lineas = b.das.tic()                                                # el TP (compra a 3,45) llena 10
    b.das_contesta = False                                              # los REPLACE de ese plan quedan en vuelo
    b.dar(lineas)
    primero = acciones_de(b.historial, Reemplazar)
    assert primero and b.pos().version_stops == 2
    b.das_contesta = True
    b.cotizar(TICKER, "3.43", "3.45", "3.45", tam_ask=10)
    marca = b.marca()
    b.tic_das()                                                         # otros 10: fill con el REPLACE aún pendiente
    tras = b.desde(marca)
    invalidar = acciones_de(tras, InvalidarSerie)
    nuevos = acciones_de(tras, Reemplazar)
    assert invalidar and nuevos
    assert tras.index(invalidar[0]) < tras.index(nuevos[0])
    assert invalidar[0].version == nuevos[0].version == 3 == b.pos().version_stops
    assert sorted(r.qty for r in nuevos) == [80]                          # el stop único (Jaume 29-sep)


def test_grupo_a_sale_primero_aunque_la_senal_se_descarte(cfg: Config, tmp_path: Path) -> None:
    """F1.1 / R-M-05: con el grupo A activo, `Avisar(1, A)` es la PRIMERA acción y sale aunque luego no se entre."""
    config = cfg_con(cfg, grupo_a=True,
                     estrategias=[dataclasses.replace(cfg.estrategias[SID], avisar_grupo_a=True)])
    b = Banco(config, tmp_path)
    b.preparar(locates=())
    # tamaño 0: la señal se descartará (sin locates ya no se descarta: Jaume 29-sep, fase B3 = un intento)
    acciones = b.senal(evento(acciones=0.0), bombear=False)
    assert isinstance(acciones[0], Avisar) and acciones[0].grupo is Grupo.A and acciones[0].nivel is Nivel.INFO
    assert TICKER in acciones[0].texto
    assert anotaciones(acciones, "senal_descartada")[0].datos["motivo"] == reglas_entrada.MOTIVO_SIN_ACCIONES
    prealerta = b.senal(evento(estado="prealerta", momento=momento_de(INICIO + timedelta(minutes=1))), bombear=False)
    assert [a.grupo for a in prealerta] == [Grupo.A]                   # la prealerta: solo grupo A, nunca se opera
    assert id_de_evento(evento(estado="prealerta", momento=momento_de(INICIO + timedelta(minutes=1)))) \
        not in b.estado.senales_vistas


# ═══════════════════════════ comandos (R-M-04) ═══════════════════════════
def _respuesta(acciones: list[Accion]) -> str:
    textos = [a.texto for a in acciones if isinstance(a, Avisar) and a.grupo is Grupo.B and a.clave is None]
    assert textos, "el comando no contestó"
    return textos[-1]


CONSULTAS = ["/estado", "/posiciones", "/ordenes", "/locates", "/estrategias", "/salud", "/log", "/detalle XYZ"]


@pytest.mark.parametrize("texto", CONSULTAS, ids=[f"R-M-04-{t.split()[0]}" for t in CONSULTAS])
def test_comandos_de_consulta_contestan_sin_clave(banco: Banco, texto: str) -> None:
    """R-M-04: una consulta contesta al grupo B, nivel 1, SIN clave (el dedupe de 60 s callaría la segunda)."""
    abrir_posicion(banco)
    acciones = banco.comando(texto)
    assert _respuesta(acciones).startswith("[SOMBRA]")
    assert anotaciones(acciones, "comando")[0].datos["nombre"] == texto.split()[0][1:]


def _preparar_pausado(b: Banco) -> None:
    b.pos().estado = EstadoTicker.PAUSADO


def _con_bs(b: Banco) -> None:
    b.cotizar(TICKER, "6.90", "7.10", "7.00")
    b.tic_das()


ACCIONES_COMANDO: list[tuple[str, Optional[Callable[[Banco], None]], Callable[[Banco, list], None]]] = [
    ("/pausar", None, lambda b, a: b.estado.pausa_global is True or pytest.fail("sin pausa")),
    ("/reanudar", lambda b: setattr(b.estado, "pausa_global", True),
     lambda b, a: b.estado.pausa_global is False or pytest.fail("sigue en pausa")),
    ("/reanudar XYZ", _preparar_pausado, lambda b, a: b.pos().estado is EstadoTicker.NORMAL or pytest.fail("no reanudó")),
    ("/reanudar_ticker XYZ", _preparar_pausado,
     lambda b, a: b.pos().estado is EstadoTicker.NORMAL or pytest.fail("no reanudó")),
    ("/reanudar_todo", _preparar_pausado, lambda b, a: b.pos().estado is EstadoTicker.NORMAL or pytest.fail("no reanudó")),
    ("/sigue", lambda b: setattr(b.estado, "pausa_global", True),
     lambda b, a: b.estado.pausa_global is False or pytest.fail("no siguió")),
    ("/modo_seguridad on", None, lambda b, a: b.decisor.cfg.modo_seguridad["activo"] is True or pytest.fail("off")),
    ("/desactivar prueba-1", None, lambda b, a: b.decisor.cfg.estrategias[SID].ejecutar is False or pytest.fail("activa")),
    ("/activar prueba-1", None, lambda b, a: b.decisor.cfg.estrategias[SID].ejecutar is True or pytest.fail("inactiva")),
    ("/apagar", None, lambda b, a: (not b.estado.vigilando and b.estado.control_humano) or pytest.fail("encendido")),
    ("/encender", lambda b: (setattr(b.estado, "vigilando", False), setattr(b.estado, "control_humano", True)),
     lambda b, a: (b.estado.vigilando and not b.estado.control_humano) or pytest.fail("apagado")),
    ("/parar_avisos", _con_bs, lambda b, a: b.pos().bs.silenciado is True or pytest.fail("sin silenciar")),
    ("/reanudar_avisos", lambda b: (_con_bs(b), b.comando("/parar_avisos")),
     lambda b, a: b.pos().bs.silenciado is False or pytest.fail("silenciado")),
    ("/control_humano", None, lambda b, a: b.estado.control_humano is True or pytest.fail("sin control humano")),
    ("/control_humano XYZ", None,
     lambda b, a: b.pos().estado is EstadoTicker.CONTROL_HUMANO or pytest.fail("ticker sin control humano")),
    ("/cerrar_y_reiniciar prueba-1", None,
     lambda b, a: [o.proposito for o in b.enviadas(Proposito.CIERRE_REINICIO)] == [Proposito.CIERRE_REINICIO]
     or pytest.fail("sin cierre")),
    ("/esperar_fin_dia prueba-1", None,
     lambda b, a: b.decisor.cfg.estrategias[SID].al_desactivar == "esperar_fin_dia" or pytest.fail("sin cambio")),
    ("/cerrar_todo SI", None, lambda b, a: (b.enviadas(Proposito.CIERRE_HUMANO) and b.pos().neta_fills == 0)
     or pytest.fail("no cerró")),
    ("/cerrar XYZ SI", None, lambda b, a: (b.enviadas(Proposito.CIERRE_HUMANO) and b.pos().neta_fills == 0)
     or pytest.fail("no cerró")),
    ("/cerrar XYZ 40 SI", None,       # E2-03: la compra sale tras ver el stop reducido (una vuelta de 0,5 s)
     lambda b, a: (b.avanzar(1.0), b.pos().neta_fills == -60)[1] or pytest.fail("no cerró 40")),
    ("/cancelar_ordenes XYZ SI", None,
     lambda b, a: (acciones_de(a, CancelarTicker) and b.pos().estado is EstadoTicker.CONTROL_HUMANO)
     or pytest.fail("no canceló")),
    ("/stop XYZ 4.50 SI", None,
     lambda b, a: (all(lote.nivel_stop == D("4.50") for lote in b.pos().lotes.values())
                   and sorted((e.orden.proposito.value, e.orden.stop, e.orden.precio)
                              for e in acciones_de(a, EnviarOrden)) == [("stop", D("4.50"), D("6.75"))]   # R-C-01 v4
                   and len(acciones_de(a, Cancelar)) == 1)
     or pytest.fail("stop sin mover")),
]


@pytest.mark.parametrize("texto,preparar,comprobar", ACCIONES_COMANDO,
                         ids=[f"R-M-04-{t}" for t, _, _ in ACCIONES_COMANDO])
def test_comandos_de_accion_se_ejecutan_y_contestan(banco: Banco, texto: str,
                                                    preparar: Optional[Callable[[Banco], None]],
                                                    comprobar: Callable[[Banco, list], None]) -> None:
    """R-M-04: cada comando de acción (dos pasos o «SI») hace lo suyo, se anota confirmado y contesta al grupo B."""
    b = banco
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    if preparar is not None:
        preparar(b)
    acciones = b.comando(texto)
    comprobar(b, acciones)
    assert any(a.datos.get("confirmado") is True for a in anotaciones(acciones, "comando"))
    _respuesta(acciones)


@pytest.mark.parametrize("texto,esperado", [
    ("/cerrar_todo", "Falta «SI»"),
    ("/inventado", "Comando desconocido"),
    ("/confirmar 9999", "Confirmación inexistente"),
    ("/log 999", "No entiendo los argumentos"),
], ids=["R-M-04-sin-SI", "R-M-04-desconocido", "R-M-04-confirmar-inexistente", "R-M-04-args-invalidos"])
def test_comandos_que_no_se_ejecutan_contestan_por_que(banco: Banco, texto: str, esperado: str) -> None:
    """R-M-04: sin «SI», desconocido, confirmación caducada o argumentos malos → respuesta y NADA más."""
    acciones = banco.comando(texto, confirmar=False)
    assert esperado in _respuesta(acciones)
    assert not acciones_de(acciones, EnviarOrden) and not acciones_de(acciones, CancelarTicker)
    assert all(a.datos.get("confirmado") is False for a in anotaciones(acciones, "comando"))


def test_comando_de_dos_pasos_no_se_ejecuta_sin_confirmar(banco: Banco) -> None:
    """R-M-04 / R-Q-01: /pausar sin /confirmar no pausa; la respuesta dice cómo confirmar."""
    acciones = banco.comando("/pausar", confirmar=False)
    assert "/confirmar" in _respuesta(acciones)
    assert banco.estado.pausa_global is False


# ═══════════════════════════ foto, contratos y limpieza del import ═══════
def test_foto_es_json_con_lo_que_pinta_el_panel(banco: Banco) -> None:
    """Panel 4.4: fase, posiciones, órdenes vivas, cuenta, locates, pausas, feed/DAS, reconciliación y degradados."""
    abrir_posicion(banco)
    foto = banco.decisor.foto()
    json.dumps(foto)
    for clave in ("fase", "posiciones", "ordenes", "cuenta", "locates", "tickers_pausados", "senales_del_dia", "feed",
                  "das", "ultima_reconciliacion_en", "modos_degradados", "version_config", "cola"):
        assert clave in foto
    assert foto["posiciones"][TICKER]["neta_fills"] == -100
    assert {o["proposito"] for o in foto["ordenes"]} == {"stop"}                    # stop único (Jaume 29-sep)
    assert foto["das"]["conectado"] is True and foto["modos_degradados"] == []


def test_publica_la_foto_cada_foto_cada_s(banco: Banco) -> None:
    marca = banco.marca()
    banco.avanzar(4.5)
    assert len([a for a in banco.desde(marca) if isinstance(a, PublicarFoto)]) == 2


def test_hilo_caido_avisa_nivel_2(banco: Banco) -> None:
    acciones = banco.procesar(HiloCaido("receptor_telegram", "ConnectionError", True))
    assert [a.nivel for a in acciones if isinstance(a, Avisar)] == [Nivel.AVISO]
    assert anotaciones(acciones, "hilo_caido")[0].datos["relanzado"] is True


def test_procesar_rechaza_argumentos_imposibles(banco: Banco) -> None:
    """Contrato: `procesar` solo lanza con un mensaje o un reloj inválidos (el resto va por H-5)."""
    with pytest.raises(TypeError):
        banco.decisor.procesar("Tic", banco.ahora(), banco.reloj.ahora())          # type: ignore[arg-type]
    with pytest.raises(ValueError):
        banco.decisor.procesar(Tic(), banco.ahora(), datetime(2026, 9, 25, 9, 30))
    with pytest.raises(ValueError):
        banco.decisor.procesar(Tic(), float("nan"), banco.reloj.ahora())


def test_constructor_exige_tokens_del_ejecutor(cfg: Config, tmp_path: Path) -> None:
    b = Banco(cfg, tmp_path)
    with pytest.raises(ValueError):
        Decisor(cfg, b.estado, b.mercado, None, GeneradorTokens(Origen.VIGILANTE, HOY),
                rechazos.cargar_catalogo(rechazos.RUTA_CATALOGO), lambda: False, calendario=CalendarioPrueba())
    with pytest.raises(TypeError):
        Decisor(cfg, b.estado, b.mercado, object(), GeneradorTokens(Origen.EJECUTOR, HOY),
                rechazos.cargar_catalogo(rechazos.RUTA_CATALOGO), lambda: False, calendario=CalendarioPrueba())


def test_sin_lista_de_splits_no_excluye_y_avisa_una_vez(cfg: Config, tmp_path: Path) -> None:
    """Corrección 17: sin la lista de splits de Massive no se excluye por split y se avisa nivel 2 una sola vez al día."""
    b = Banco(cfg, tmp_path, massive=MassiveFalso(falla_splits=True))
    b.preparar(locates=((TICKER, SID, 1000), (OTRO, SID, 1000)),
               cotizaciones=((TICKER, "3.44", "3.46", "3.45"), (OTRO, "3.44", "3.46", "3.45")))
    primera = b.senal(evento())
    segunda = b.senal(evento(ticker=OTRO))
    assert [a.clave for a in primera if isinstance(a, Avisar)] == ["splits_sin_lista"]
    assert not [a for a in segunda if isinstance(a, Avisar) and a.clave == "splits_sin_lista"]
    assert [o.ticker for o in b.enviadas(Proposito.ENTRADA_AGREGAR)] == [TICKER, OTRO]


def test_split_del_dia_excluye_la_senal(cfg: Config, tmp_path: Path) -> None:
    """R-A-03 v2: un ticker con split hoy se excluye (ajuste (b): la exclusión la calcula el decisor)."""
    b = Banco(cfg, tmp_path, massive=MassiveFalso(splits=(TICKER,)))
    b.preparar()
    acciones = b.senal(evento())
    assert anotaciones(acciones, "senal_descartada")[0].datos["motivo"] == reglas_entrada.MOTIVO_EXCLUIDA
    assert not b.enviadas()


def test_importar_el_decisor_no_carga_pandas_ni_arranca_hilos() -> None:
    """§6: en modo tubería el ejecutor no carga pandas; importar el decisor no ejecuta nada ni lanza hilos."""
    codigo = ("import sys, threading; antes = threading.active_count(); import app.bot_das.decisor; "
              "print('pandas' in sys.modules, threading.active_count() - antes)")
    salida_ = subprocess.run([sys.executable, "-c", codigo], cwd=str(Path(__file__).resolve().parents[2]),
                             capture_output=True, text=True, timeout=120)
    assert salida_.returncode == 0, salida_.stderr
    assert salida_.stdout.split() == ["False", "0"]


# ═══════════════════════════ correcciones de la revisión (27-sep) ════════
# Un escenario por hallazgo (el id va en el nombre); las decisiones del director mandan sobre el arreglo del revisor.
def _vivas_compra(b: Banco, *propositos: Proposito, ticker: str = TICKER) -> int:
    """Acciones que las compras VIVAS del ticker (de esos propósitos, o todas) aún pueden ejecutar."""
    return sum(max(min(o.lvqty, o.qty - o.llenas) if o.lvqty > 0 else o.qty - o.llenas, 0)
               for o in b.estado.ordenes.values()
               if o.ticker == ticker and o.lado is Lado.COMPRA and (not propositos or o.proposito in propositos)
               and o.estado in (EstadoOrden.SENDING, EstadoOrden.ACCEPTED, EstadoOrden.PARTIAL, EstadoOrden.HOLD,
                                EstadoOrden.TRIGGERED))


def _sin_compra_doble(b: Banco, corto: int, ticker: str = TICKER) -> bool:
    """Riesgo 6 / G1A-01: los stops (uno por nivel con el stop único de Jaume 29-sep; cada uno cubre SUS acciones) más
    las compras de cierre vivas nunca pasan de lo que queda corto."""
    cierre = _vivas_compra(b, Proposito.HALT_OPEN, Proposito.HALT_PM_LIMITE, Proposito.HALT_BANDA,
                           Proposito.CIERRE_HUMANO, ticker=ticker)
    return _vivas_compra(b, *STOPS, ticker=ticker) + cierre <= corto


def _a_halt(b: Banco, ta: str = "P", tat: str = "09:27:00", cot: tuple = ("4.04", "4.06", "4.05"),
            ev: Optional[Evento] = None) -> None:
    """Posición corta de 100 (el stop único 4,00/6,00 con el evento por defecto, Jaume 29-sep) y el símbolo parado a
    `cot`."""
    abrir_posicion(b, ev)
    b.libro.halt(TICKER, ta, tat)
    b.cotizar(TICKER, *cot)
    b.avanzar(1.5)
    assert b.pos().estado is EstadoTicker.HALT


def test_g1a_01_g1b_04_halt_escenario_2_reabre_sobre_el_stop_sin_compra_doble(banco: Banco) -> None:
    """G1A-01 / G1B-04 / D2a-09 (decisión del director): la salida del halt por OPEN por Q acciones BAJA antes el stop
    único en Q (aquí se cancela: Q = toda la posición). Reabriendo POR ENCIMA de su disparo (escenario 2) la cuenta
    queda plana: ninguna compra doble, ninguna venta del exceso, ningún incidente de cuenta larga."""
    b = banco
    _a_halt(b)
    (stop,) = b.enviadas(*STOPS)
    marca = b.marca()
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 31, 1, tzinfo=ET))
    tanda = b.desde(marca)
    envio = next(i for i, a in enumerate(tanda) if isinstance(a, EnviarOrden) and a.orden.proposito is Proposito.HALT_OPEN)
    cancelados = {a.token: i for i, a in enumerate(tanda) if isinstance(a, Cancelar)}
    assert stop.token in cancelados
    assert cancelados[stop.token] < envio                               # el stop baja ANTES (Jaume 29-sep)
    assert _vivas_compra(b, *STOPS) == 0 and _sin_compra_doble(b, 100)  # nunca dos compras sobre las mismas acciones
    b.libro.reabrir(TICKER, D("4.10"))                                  # sobre el disparo del stop (4,00)
    b.avanzar(4)
    assert b.pos().neta_fills == 0 and b.pos().neta_das == 0
    assert not b.enviadas(Proposito.VENTA_EXCESO)
    assert not [a for a in anotaciones(b.historial, "incidente") if a.datos.get("tipo") == "cuenta_larga"]


def test_g1a_01_salida_del_halt_rechazada_restaura_los_stops_y_avisa(banco: Banco) -> None:
    """G1A-01 (director): si la salida del halt recibe Send_Rej, `plan()` devuelve el stop único a la posición entera y
    se avisa nivel 2."""
    b = banco
    _a_halt(b)
    b.rechazar[Proposito.HALT_OPEN] = "Route is closed"
    marca = b.marca()
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 31, 1, tzinfo=ET))
    salida_halt = b.enviadas(Proposito.HALT_OPEN, desde=marca)
    assert len(salida_halt) == 1 and b.orden(salida_halt[0].token).estado is EstadoOrden.REJECTED
    repuestos = b.enviadas(*STOPS, desde=marca)
    assert sorted((o.proposito.value, o.qty, o.stop, o.precio) for o in repuestos) == [
        ("stop", 100, D("4.00"), D("6.00"))]
    aviso = [a for a in b.desde(marca) if isinstance(a, Avisar) and (a.clave or "").startswith("halt_salida_sin_llenar:")]
    assert len(aviso) == 1 and aviso[0].nivel is Nivel.AVISO
    assert _vivas_compra(b, Proposito.STOP) == 100 and _sin_compra_doble(b, 100)   # cubierta otra vez
    assert anotaciones(b.desde(marca), "halt_salida_sin_llenar")[0].datos["regla"] == "G1A-01"


def test_g1a_01_salida_del_halt_sin_llenar_a_los_2_s_se_retira_y_vuelven_los_stops(banco: Banco) -> None:
    """G1A-01 (director): 2 s después de la reapertura, la salida del halt que no ha llenado se RETIRA y, con su
    Canceled, el stop único vuelve por lo que queda corto (aviso 2)."""
    b = banco
    _a_halt(b)
    b.libro.llenar_parcial(D("0.5"), TICKER)                            # la subasta solo llenará la mitad
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 31, 1, tzinfo=ET))
    salida_halt = b.enviadas(Proposito.HALT_OPEN)[0]
    b.libro.llenar_parcial(D("1"), TICKER)
    marca = b.marca()
    b.libro.reabrir(TICKER, D("3.95"))
    b.avanzar(1.5)
    assert b.pos().neta_fills == -50
    assert f"halt_cierre_verificar:{TICKER}" in b.temporizadores
    b.avanzar(3)
    assert salida_halt.token in [c.token for c in acciones_de(b.desde(marca), Cancelar)]
    assert b.orden(salida_halt.token).estado is EstadoOrden.CANCELED
    repuestos = b.enviadas(*STOPS, desde=marca)
    assert sorted((o.proposito.value, o.qty) for o in repuestos) == [("stop", 50)]
    assert _vivas_compra(b, Proposito.STOP) == 50 and _sin_compra_doble(b, 50)
    assert any(isinstance(a, Avisar) and (a.clave or "").startswith("halt_salida_sin_llenar:") for a in b.desde(marca))


def test_g1a_04_halt_con_cisne_negro_no_manda_ordenes_y_avisa_3(banco: Banco) -> None:
    """G1A-04 (R-G-01: «cierra el HUMANO»): con el cisne negro activo, halt_decidir y la reapertura NO envían órdenes;
    solo anotan y avisan nivel 3 con la decisión que habrían tomado."""
    b = banco
    abrir_posicion(b)
    b.cotizar(TICKER, "6.90", "7.10", "7.00")                          # fogonazo: cisne negro
    b.tic_das()
    assert b.pos().estado is EstadoTicker.BS
    b.libro.halt(TICKER, "P", "09:27:00")
    b.avanzar(1.5)
    marca = b.marca()
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 31, 1, tzinfo=ET))
    salidas_halt = (Proposito.HALT_OPEN, Proposito.HALT_PM_LIMITE, Proposito.HALT_BANDA)
    assert not b.enviadas(*salidas_halt)
    sin_orden = anotaciones(b.desde(marca), "halt_sin_orden")
    assert sin_orden and sin_orden[0].datos["motivo"] == "cisne negro"
    avisos3 = [a for a in b.desde(marca) if isinstance(a, Avisar) and (a.clave or "").startswith("halt_sin_orden:")]
    assert len(avisos3) == 1 and avisos3[0].nivel is Nivel.MAXIMO and "cierra el humano" in avisos3[0].texto
    b.libro.reabrir(TICKER, D("7.00"))
    b.avanzar(3)
    assert not b.enviadas(*salidas_halt)
    assert b.pos().neta_fills == -100 and b.pos().estado is EstadoTicker.BS


def test_g1a_04b_halt_T1_T12_en_cisne_negro_sigue_el_protocolo_del_limite_pm(banco: Banco) -> None:
    """D4 (Jaume 28-sep): en premercado solo hay halts T1/T12 (`H`): con el cisne negro activo, el halt NO espera al humano,
    manda su protocolo (límite a parada × 3,5, R-F-05). El «cierra el humano» de G1A-04 queda para la pausa LULD (`P`)."""
    b = banco
    abrir_posicion(b)
    b.cotizar(TICKER, "6.90", "7.10", "7.00")                          # fogonazo: cisne negro
    b.tic_das()
    assert b.pos().estado is EstadoTicker.BS
    b.libro.halt(TICKER, "H", "09:27:00")
    b.avanzar(1.5)
    marca = b.marca()
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 31, 1, tzinfo=ET))
    salidas = b.enviadas(Proposito.HALT_OPEN, Proposito.HALT_PM_LIMITE)
    assert len(salidas) == 1 and salidas[0].lado is Lado.COMPRA and salidas[0].qty == 100
    assert salidas[0].tipo is TipoOrden.MERCADO and salidas[0].ruta == "OPEN"   # decisión 48: H en RTH → MKT por OPEN
    assert not anotaciones(b.desde(marca), "halt_sin_orden")
    assert not [a for a in b.desde(marca) if isinstance(a, Avisar) and (a.clave or "").startswith("halt_sin_orden:")]


def test_g1b_01_rearranque_con_eod_vencido_y_das_plano_no_compra_hasta_reconciliar(cfg: Config, tmp_path: Path) -> None:
    """G1B-01 (director, R-J-02.5): al rearrancar con la hora/EOD del lote YA vencida y DAS plano, ninguna salida por
    temporizador sale antes de reconciliar (se reprograma a 0,5 s); la reconciliación (caso 5) cierra el lote y NO se
    compra nada: la cuenta nunca queda larga."""
    estado = _estado_con_lote()
    next(iter(estado.posiciones[TICKER].lotes.values())).eod = "09:20:00"
    b = Banco(cfg, tmp_path, estado=estado)
    b.libro.sembrar_posicion(TICKER, 0, D("3.45"))                      # el humano (o el vigilante) ya la cerró
    b.preparar(locates=(), reconciliar=False)
    assert "reconciliacion" in b.estado.modo_degradado
    b.avanzar(5)
    assert not [o for o in b.enviadas() if o.lado is Lado.COMPRA]
    aplazadas = anotaciones(b.historial, "salida_aplazada")
    assert aplazadas and "reconciliacion" in aplazadas[0].datos["motivo"]
    assert b.pos().neta_fills == 0 and b.pos().neta_das == 0
    assert all(lote.estado is EstadoLote.CERRADO for lote in b.pos().lotes.values())
    assert "reconciliacion" not in b.estado.modo_degradado


def test_g1b_02_intento_cancelado_al_quedar_plana_la_posicion(banco: Banco) -> None:
    """G1B-02 (director, R-C-11 a): el stop deja plana la posición con el intento de entrada vivo → el intento se CANCELA
    y se cierra con lo llenado: ninguna venta en corto posterior (antes reentraba en un lote CERRADO sin stops)."""
    b = banco
    b.libro.llenar_parcial(D("0.3"), TICKER)                            # la venta agregada llenará 30 de 100
    b.simstatus()
    b.senal(evento())
    b.libro.llenar_parcial(D("1"), TICKER)
    llenar_entrada(b)
    assert b.pos().neta_fills == -30 and b.pos().intento is not None
    marca = b.marca()
    b.cotizar(TICKER, "4.00", "4.05", "4.01")                          # el stop (4,00) llena las 30
    b.tic_das()
    b.avanzar(3)
    assert b.pos().neta_fills == 0 and b.pos().intento is None
    assert not [o for o in b.enviadas(desde=marca) if o.lado is Lado.CORTO]
    assert anotaciones(b.desde(marca), "intento_fin")
    lote = b.pos().lotes[lote_de(evento())]
    assert lote.estado is EstadoLote.CERRADO and lote.llenas == 0


def test_g1b_02_cob_01_tp_de_la_misma_estrategia_con_su_entrada_viva_cancela_el_intento(banco: Banco) -> None:
    """G1B-02 / COB-01 (director): el TP del motor de la MISMA estrategia con su entrada viva cancela el intento (R-D-07
    es solo entre estrategias DISTINTAS) y el TP sale, tras el Canceled, por lo llenado (30), nunca por las 100 del
    evento; después ninguna venta en corto."""
    b = banco
    b.libro.llenar_parcial(D("0.3"), TICKER)
    b.simstatus()
    b.senal(evento())
    agregar = b.enviadas(Proposito.ENTRADA_AGREGAR)[0]
    b.libro.llenar_parcial(D("1"), TICKER)
    llenar_entrada(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    marca = b.marca()
    ev = salida(acciones=100.0)
    acciones = b.procesar(SenalRecibida(Senal(clase="evento", ticker=TICKER, id=id_de_evento(ev), evento=ev,
                                              momento=ev.momento, recibida_en=b.ahora())), bombear=False)
    assert agregar.token in [c.token for c in acciones_de(acciones, Cancelar)]
    assert not acciones_de(acciones, EnviarOrden)                       # nunca juntas: el TP espera al Canceled
    b.bombear()
    b.avanzar(1)
    assert b.orden(agregar.token).estado is EstadoOrden.CANCELED and b.pos().intento is None
    tp = b.enviadas(Proposito.TP_AGREGAR, Proposito.TP_CRUCE, desde=marca)
    assert [o.qty for o in tp] == [30]
    assert not [o for o in b.enviadas(desde=marca) if o.lado is Lado.CORTO]
    assert anotaciones(b.desde(marca), "salida_proporcion")[0].datos["qty"] == 30          # G1A-16: siempre anotado


def test_cob_01_salida_del_motor_sin_fills_cancela_el_intento_y_no_cruza(banco: Banco) -> None:
    """COB-01 (R-B-01 v3 punto 1: «se cancela antes si la estrategia deja de decir dentro»): la salida del motor (SL) de
    la MISMA estrategia con su orden agregando SIN fills cancela el intento; al vencer t_limite no se cruza nada."""
    b = banco
    b.simstatus()
    b.senal(evento())
    agregar = b.enviadas(Proposito.ENTRADA_AGREGAR)[0]
    ev = salida(motivo="SL", acciones=100.0)
    b.procesar(SenalRecibida(Senal(clase="evento", ticker=TICKER, id=id_de_evento(ev), evento=ev, momento=ev.momento,
                                   recibida_en=b.ahora())))
    assert b.orden(agregar.token).estado is EstadoOrden.CANCELED
    b.avanzar(61)
    assert not b.enviadas(Proposito.ENTRADA_CRUCE)
    assert b.pos().intento is None and b.pos().neta_fills == 0
    assert any(a.datos.get("estrategia_fuera") == SID for a in anotaciones(b.historial, "intento"))


def test_cob_01_salida_con_fills_parciales_retira_el_intento_y_protege_lo_llenado(banco: Banco) -> None:
    """COB-01 (variante del revisor): SL del motor con fills parciales → el intento se cancela (nada se cruza) y lo
    llenado queda con su stop (único, Jaume 29-sep)."""
    b = banco
    b.libro.llenar_parcial(D("0.4"), TICKER)
    b.simstatus()
    b.senal(evento())
    b.libro.llenar_parcial(D("1"), TICKER)
    llenar_entrada(b)
    assert b.pos().neta_fills == -40
    ev = salida(motivo="SL", acciones=100.0)
    b.procesar(SenalRecibida(Senal(clase="evento", ticker=TICKER, id=id_de_evento(ev), evento=ev, momento=ev.momento,
                                   recibida_en=b.ahora())))
    b.avanzar(61)
    assert not b.enviadas(Proposito.ENTRADA_CRUCE)
    assert b.pos().intento is None and b.pos().neta_fills == -40
    assert sorted((o.proposito.value, o.qty) for o in b.enviadas(*STOPS)) == [("stop", 40)]


def _dos_posiciones(b: Banco) -> None:
    b.preparar(locates=((TICKER, SID, 1000), (OTRO, SID, 1000)),
               cotizaciones=((TICKER, "3.44", "3.46", "3.45"), (OTRO, "3.44", "3.46", "3.45")))
    abrir_posicion(b)
    b.senal(evento(ticker=OTRO))
    b.cotizar(OTRO, "3.45", "3.47", "3.45")
    b.tic_das()
    assert b.pos(OTRO).neta_fills == -100


def test_g1b_03_dos_cerrar_seguidos_cada_uno_con_sus_reintentos_aviso_y_stops(cfg: Config, tmp_path: Path) -> None:
    """G1B-03 / D2-01 (director): «/cerrar X» y «/cerrar Y» seguidos: el reintento es POR TICKER (`cerrar_todo:<t>`),
    así que cada uno hace sus reintentos, al agotarse RETIRA su orden de cierre (D2-04), avisa nivel 3 con su clave y
    vuelve a tener stops. Antes el segundo borraba el reintento del primero y X quedaba corto sin stops."""
    b = Banco(cfg, tmp_path)
    _dos_posiciones(b)
    for t in (TICKER, OTRO):
        b.cotizar(t, "3.44", "3.46", "3.45", tam_ask=0)                 # sin liquidez: el cierre no llena
    marca = b.marca()
    b.comando("/cerrar XYZ SI")
    b.avanzar(0.5)
    b.comando("/cerrar ABC SI")
    assert {k for k in b.temporizadores if k.startswith("cerrar_todo:")} == {"cerrar_todo:XYZ", "cerrar_todo:ABC"}
    b.avanzar(12)
    for t in (TICKER, OTRO):
        cierres = [o for o in b.enviadas(Proposito.CIERRE_HUMANO, desde=marca) if o.ticker == t]
        assert len(cierres) == 3                                        # el primero y sus 2 reintentos (R-D-06)
        assert all(b.orden(o.token).estado is EstadoOrden.CANCELED for o in cierres)   # el último, RETIRADO
        agotado = [a for a in b.desde(marca) if isinstance(a, Avisar) and a.clave == f"cerrar_todo:{t}:agotado"]
        assert len(agotado) == 1 and agotado[0].nivel is Nivel.MAXIMO and "RETIRADO" in agotado[0].texto
        repuestos = [o for o in b.enviadas(*STOPS, desde=marca) if o.ticker == t]
        assert sorted((o.proposito.value, o.qty) for o in repuestos) == [("stop", 100)]      # stop único
        assert _sin_compra_doble(b, 100, ticker=t)
    assert not [k for k in b.temporizadores if k.startswith("cerrar_todo:")]


def test_d2_03_g1b_15_cerrar_cancela_primero_y_la_orden_sale_tras_el_canceled(banco: Banco) -> None:
    """D2-03 / G1B-15: «/cerrar X SI» en dos pasos: CancelarTicker y, con órdenes vivas, la orden de cierre sale SOLO
    tras el Canceled de todo lo vivo, por la neta de ESE momento."""
    b = banco
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    b.das_contesta = False
    acciones = b.comando("/cerrar XYZ SI")
    assert acciones_de(acciones, CancelarTicker) and not b.enviadas(Proposito.CIERRE_HUMANO)
    assert b.temporizadores["cerrar_todo:XYZ"][2]["fase"] == "enviar"
    b.das_contesta = True
    (stop,) = b.enviadas(*STOPS)
    marca = b.marca()
    b.dar(b.das.recibir(f"CANCEL {b.orden(stop.token).id_das}"))
    cierre = b.enviadas(Proposito.CIERRE_HUMANO, desde=marca)
    assert [(o.qty, o.precio) for o in cierre] == [(100, D("3.64"))]    # ask 3,46 · 1,05 al tick de arriba (R-D-06)
    assert b.pos().neta_fills == 0


def test_d2a_06_orden_descartada_por_el_emisor_se_cierra_y_se_replanifica(banco: Banco) -> None:
    """D2a-06 (director): el emisor devuelve `OrdenDescartada` por un NEWORDER que no salió → la orden pasa a CLOSED con
    el motivo (nunca se cree viva) y el plan de stops del ticker se relanza EN EL ACTO."""
    b = banco
    abrir_posicion(b)
    stop = b.enviadas(Proposito.STOP)[0]
    b.das_contesta = False                                              # el stop nuevo se queda sin salir
    b.dar(b.das.recibir(f"CANCEL {b.orden(stop.token).id_das}"))
    nueva = b.enviadas(Proposito.STOP)[-1]
    assert nueva.token != stop.token and b.orden(nueva.token).estado is EstadoOrden.SENDING
    b.das_contesta = True
    marca = b.marca()
    acciones = b.procesar(OrdenDescartada(token=nueva.token, serie="stops:XYZ", version=nueva.version,
                                          motivo="descartada por versión", ticker=TICKER))
    assert b.orden(nueva.token).estado is EstadoOrden.CLOSED
    assert b.orden(nueva.token).notas == "descartada por versión"
    assert anotaciones(acciones, "orden_descartada")[0].datos["resultado"] == "CLOSED y plan de stops"
    repuesta = b.enviadas(Proposito.STOP, desde=marca)
    assert [(o.qty, o.stop) for o in repuesta] == [(100, D("4.00"))] and repuesta[0].token != nueva.token
    otra = b.procesar(OrdenDescartada(token=stop.token, ticker=TICKER))
    assert anotaciones(otra, "orden_descartada")[0].datos["resultado"].startswith("se ignora")


class ReferenciaLenta:
    """G1A-03: una referencia cuya RED tarda 5 s; el decisor solo puede leer su caché (que nunca abre red)."""

    def __init__(self) -> None:
        self.llamadas_red = 0
        self.pedidas: list[str] = []

    def ficha(self, ticker: str) -> None:
        self.llamadas_red += 1
        import time
        time.sleep(5)

    def splits_de_hoy(self, hoy: Any) -> None:
        self.llamadas_red += 1
        import time
        time.sleep(5)

    def ficha_en_cache(self, ticker: str) -> None:
        self.pedidas.append(ticker)
        return None

    def pedir_ficha(self, ticker: str) -> None:
        self.pedidas.append(ticker)

    def splits_en_cache(self, hoy: Any) -> None:
        return None

    def splits_pendientes(self, hoy: Any) -> bool:
        return True


def test_g1a_03_g1b_08_referencia_lenta_no_bloquea_al_decisor(cfg: Config, tmp_path: Path) -> None:
    """G1A-03 / G1B-08 (director): el decisor NUNCA hace red: radar e hidratado solo PIDEN la ficha a la precarga y una
    señal sin ficha en la caché es A12 (no se opera) sin esperar; `procesar` vuelve en milisegundos."""
    import time
    lenta = ReferenciaLenta()
    b = Banco(cfg, tmp_path, referencia=lenta)
    b.preparar()
    inicio = time.perf_counter()
    b.procesar(SenalRecibida(Senal(clase="radar", ticker=TICKER, id=None, estimacion=[], precio_radar=D("3.45"),
                                   recibida_en=b.ahora())))
    b.simstatus()
    acciones = b.senal(evento())
    assert time.perf_counter() - inicio < 1.0
    assert lenta.llamadas_red == 0 and TICKER in lenta.pedidas
    assert anotaciones(acciones, "senal_descartada")[0].datos["motivo"] == reglas_entrada.MOTIVO_EXCLUIDA
    assert anotaciones(acciones, "referencia")[0].datos["ficha"] is None
    assert not b.enviadas()


def _dos_estrategias(cfg: Config, tmp_path: Path) -> Banco:
    b = Banco(cfg_con(cfg, estrategias=[cfg.estrategias[SID], estrategia_b(cfg)]), tmp_path)
    b.preparar(locates=((TICKER, SID, 1000), (TICKER, SID2, 1000)))
    return b


def _salida_motor(b: Banco, ev: Evento, bombear: bool = True) -> list[Accion]:
    return b.procesar(SenalRecibida(Senal(clase="evento", ticker=ev.ticker, id=id_de_evento(ev), evento=ev,
                                          momento=ev.momento, recibida_en=b.ahora())), bombear=bombear)


def test_g1a_06_tp_antes_que_la_entrada_pasa_al_ask_y_la_entrada_espera(cfg: Config, tmp_path: Path) -> None:
    """G1A-06 (a) / R-D-07 (director): con el TP de A AGREGANDO, llega la entrada de B → el TP pasa AL ASK (Cancelar y,
    con el Canceled, `orden_al_ask` sin techo) y la entrada espera SOLO a que el TP termine; luego entra."""
    b = _dos_estrategias(cfg, tmp_path)
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    _salida_motor(b, salida())
    tp = b.enviadas(Proposito.TP_AGREGAR)[0]
    b.avanzar(2)
    b.cotizar(TICKER, "3.44", "3.46", "3.45", tam_ask=0)                # el ask aún sin acciones
    marca = b.marca()
    acciones = b.senal(evento(strategy_id=SID2, estrategia="PM (B) prueba", acciones=50.0, stop=4.0,
                              momento=momento_de(b.reloj.ahora())), bombear=False)
    assert [c.token for c in acciones_de(acciones, Cancelar)] == [tp.token]
    assert anotaciones(acciones, "senal_en_espera") and not acciones_de(acciones, EnviarOrden)
    b.bombear()
    al_ask = b.enviadas(Proposito.TP_CRUCE, desde=marca)
    assert [(o.qty, o.precio) for o in al_ask] == [(50, D("3.46"))]    # al ask SIN techo
    assert not b.enviadas(Proposito.ENTRADA_AGREGAR, desde=marca)      # nunca juntas
    b.cotizar(TICKER, "3.44", "3.46", "3.45")                          # el ask ya tiene acciones: el TP llena
    b.tic_das()
    assert b.pos().neta_fills == -50
    b.avanzar(2)
    entrada_b = b.enviadas(Proposito.ENTRADA_AGREGAR, desde=marca)
    assert [o.qty for o in entrada_b] == [50]


def test_g1a_06_la_entrada_retenida_nunca_espera_mas_que_su_caducidad(cfg: Config, tmp_path: Path) -> None:
    """G1A-06 (director): la entrada que espera al TP nunca pasa de su caducidad (R-B-04): caducada, se descarta y avisa;
    no se reevalúa tarde cuando el TP termina."""
    b = _dos_estrategias(cfg, tmp_path)
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45", tam_ask=0)
    _salida_motor(b, salida())
    b.senal(evento(strategy_id=SID2, estrategia="PM (B) prueba", acciones=50.0, stop=4.0,
                   momento=momento_de(b.reloj.ahora())))
    b.avanzar(63)
    descartada = [a for a in anotaciones(b.historial, "senal_descartada") if SID2 in str(a.datos.get("senal_id"))]
    assert descartada and reglas_entrada.MOTIVO_CADUCADA in descartada[0].datos["motivo"]
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    b.tic_das()
    b.avanzar(3)
    assert not [o for o in b.enviadas(Proposito.ENTRADA_AGREGAR) if o.lote_id and SID2 in o.lote_id]


def test_g1a_02_g1b_05_halt_con_eod_no_compra_por_hora_y_nunca_queda_larga(cfg: Config, tmp_path: Path) -> None:
    """G1A-02 (a) / G1B-05 (director): el EOD vence DURANTE el halt: hora_agregar y hora_ask se aplazan (guarda HALT) en
    vez de comprar encima de la salida del halt; al reabrir la salida cierra la posición y no queda larga."""
    config = cfg_con(cfg, estrategias=[dataclasses.replace(cfg.estrategias[SID], hora_fin_sesion="09:33")])
    b = Banco(config, tmp_path)
    b.preparar()
    _a_halt(b)                                                          # LULD 09:27: la OPEN sale a las 09:31
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 31, 30, tzinfo=ET))
    assert [(o.tipo, o.qty) for o in b.enviadas(Proposito.HALT_OPEN)] == [(TipoOrden.MERCADO, 100)]
    b.libro.halt(TICKER, "P", "09:28:45")                               # la bolsa alarga la pausa hasta 09:33:45
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 33, 40, tzinfo=ET))        # hora_agregar (09:32) y hora_ask (09:33)
    assert not b.enviadas(Proposito.HORA_AGREGAR, Proposito.HORA_ASK)
    assert any("halt" in a.datos["motivo"] for a in anotaciones(b.historial, "salida_aplazada"))
    assert _sin_compra_doble(b, 100)
    b.libro.reabrir(TICKER, D("3.95"))
    b.avanzar(4)
    assert b.pos().neta_fills == 0 and b.pos().neta_das == 0
    assert not b.enviadas(Proposito.HORA_AGREGAR, Proposito.HORA_ASK, Proposito.VENTA_EXCESO)


def test_g1a_02_tp_con_control_manual_no_cruza(banco: Banco) -> None:
    """G1A-02 (b): con /cancelar_ordenes (control manual) el `tp_cruce` del TP que agregaba NO compra: se aplaza."""
    b = banco
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    _salida_motor(b, salida())
    b.comando("/cancelar_ordenes XYZ SI")
    marca = b.marca()
    b.avanzar(65)
    assert not b.enviadas(desde=marca)
    assert b.pos().neta_fills == -100
    aplazadas = [a for a in anotaciones(b.desde(marca), "salida_aplazada") if a.datos["clave"].startswith("tp_cruce:")]
    assert len(aplazadas) == 1 and aplazadas[0].datos["motivo"] == "control manual"      # una vez, no cada 0,5 s


def test_g1a_02_tp_con_cierre_humano_no_cruza(banco: Banco) -> None:
    """G1A-02 (c): con «/cerrar X SI» en curso el `tp_cruce` NO manda otra compra: solo el cierre humano cierra."""
    b = banco
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    _salida_motor(b, salida())
    b.comando("/cerrar XYZ SI")
    b.avanzar(65)
    assert not b.enviadas(Proposito.TP_CRUCE)
    assert [o.qty for o in b.enviadas(Proposito.CIERRE_HUMANO)] == [100]
    assert b.pos().neta_fills == 0


def test_g1b_06_stop_tras_cancelar_ordenes_pone_el_stop_y_dice_lo_enviado(banco: Banco) -> None:
    """G1B-06 (director): «/stop X PRECIO SI» es una orden explícita del humano: saca el ticker del control manual, pone
    el stop de verdad y contesta con lo ENVIADO (tokens y cantidades); las salidas del bot siguen paradas hasta
    /reanudar X."""
    b = banco
    abrir_posicion(b)
    b.comando("/cancelar_ordenes XYZ SI")
    assert b.pos().estado is EstadoTicker.CONTROL_HUMANO
    marca = b.marca()
    acciones = b.comando("/stop XYZ 4.50 SI")
    stops_ = b.enviadas(*STOPS, desde=marca)
    assert sorted((o.proposito.value, o.qty, o.stop, o.precio) for o in stops_) == [
        ("stop", 100, D("4.50"), D("6.75"))]                            # R-C-01 v4: disparo en L, límite L + 50 %
    respuesta = _respuesta(acciones)
    assert all(str(o.token) in respuesta for o in stops_) and "NO se ha enviado" not in respuesta
    b.avanzar(3)
    assert len(b.enviadas(*STOPS, desde=marca)) == 1                    # el barrido no lo duplica
    assert b.pos().estado is EstadoTicker.CONTROL_HUMANO                # las entradas y salidas, con /reanudar


def test_g1b_06_stop_en_cisne_negro_contesta_que_no_puso_nada(banco: Banco) -> None:
    """G1B-06: en cisne negro el stop no se mueve (R-G-01/03) y la respuesta lo DICE (antes contestaba «stop a PRECIO»)."""
    b = banco
    abrir_posicion(b)
    b.cotizar(TICKER, "6.90", "7.10", "7.00")
    b.tic_das()
    marca = b.marca()
    acciones = b.comando("/stop XYZ 8.00 SI")
    assert not b.enviadas(desde=marca)
    assert "NO se ha puesto nada" in _respuesta(acciones)


def test_g1b_06_stop_sin_lotes_mueve_la_proteccion_existente_sin_duplicarla(cfg: Config, tmp_path: Path) -> None:
    """G1B-06: sin lotes vivos, /stop MUEVE (REPLACE) la protección propia que ya cubre la posición en vez de poner otra
    encima (antes salía una segunda protección por la neta entera: dos stops sobre las mismas acciones)."""
    estado = EstadoBot(fase=Fase.SOMBRA, dia=HOY)
    estado.posiciones[TICKER] = PosicionTicker(ticker=TICKER, neta_fills=-100)
    b = Banco(cfg, tmp_path, estado=estado)
    b.libro.sembrar_posicion(TICKER, -100, D("3.45"))
    b.preparar(locates=(), reconciliar=False)
    b.avanzar(3)
    proteccion = b.enviadas(Proposito.STOP_PROTECCION)
    assert [(o.qty, o.lote_id) for o in proteccion] == [(100, None)]
    marca = b.marca()
    acciones = b.comando("/stop XYZ 4.50 SI")
    movida = [r for r in acciones_de(acciones, Reemplazar) if r.token == proteccion[0].token]
    assert [(r.qty, r.stop, r.precio) for r in movida] == [(100, D("4.50"), D("6.75"))]   # límite + 50 % (v4)
    assert not b.enviadas(*STOPS, desde=marca)                          # ninguna protección nueva encima
    assert "reemplazo token" in _respuesta(acciones)
    b.avanzar(2)
    o = b.orden(proteccion[0].token)
    assert (o.stop, o.precio) == (D("4.50"), D("6.75")) and _vivas_compra(b, *STOPS) == 100


def test_g1b_06_stop_en_una_posicion_que_no_es_del_bot_dice_por_que_no_pone_nada(cfg: Config, tmp_path: Path) -> None:
    """G1B-06 (respuesta veraz): una posición que solo conoce DAS (sin fills del bot) no se toca con /stop y la respuesta
    lo dice (antes: «no hay corto»)."""
    b = Banco(cfg, tmp_path)
    b.libro.sembrar_posicion(TICKER, -100, D("3.45"))
    b.preparar(locates=(), reconciliar=False)
    b.avanzar(3)
    marca = b.marca()
    acciones = b.comando("/stop XYZ 4.50 SI")
    assert not b.enviadas(desde=marca)
    assert "no es del bot" in _respuesta(acciones)


def test_decision_48_halt_h_en_rth_bajo_el_stop_sale_a_mercado_por_open_y_el_stop_a_0(banco: Banco) -> None:
    """Decisión 48 (Jaume 30-sep; antes E1-01/E1-09 «límite a parada · 3,5» y «reabre bajo el stop → mantener»): halt
    de noticia (H) en sesión, parado POR DEBAJO del stop (3,61 < 4,00) → MKT por OPEN por toda la posición; el stop se
    CANCELA antes (a 0: nunca un REPLACE a 0) y al reabrir la cuenta queda plana sin compra doble."""
    b = banco
    abrir_posicion(b)
    (stop,) = b.enviadas(*STOPS)
    marca = b.marca()
    b.libro.halt(TICKER, "H", "09:31:00")
    b.cotizar(TICKER, "3.60", "3.62", "3.61")
    b.avanzar(1.5)
    tanda = b.desde(marca)
    assert {a.datos["decision"] for a in anotaciones(tanda, "halt_decision")} == {"cerrar_mercado"}
    salida_halt = b.enviadas(Proposito.HALT_OPEN, desde=marca)
    assert [(o.tipo, o.ruta, o.precio, o.qty, o.lado) for o in salida_halt] == [
        (TipoOrden.MERCADO, "OPEN", None, 100, Lado.COMPRA)]
    envio = next(i for i, a in enumerate(tanda) if isinstance(a, EnviarOrden) and a.orden.proposito is Proposito.HALT_OPEN)
    cancelado = next(i for i, a in enumerate(tanda) if isinstance(a, Cancelar) and a.token == stop.token)
    assert cancelado < envio                                             # el stop baja a 0 ANTES de la OPEN
    assert not [a for a in tanda if isinstance(a, Reemplazar) and a.token == stop.token]
    assert _vivas_compra(b, *STOPS) == 0 and _sin_compra_doble(b, 100)
    b.libro.reabrir(TICKER, D("3.70"))
    b.cotizar(TICKER, "3.69", "3.71", "3.70")
    b.avanzar(3)
    assert b.pos().neta_fills == 0 and not b.enviadas(Proposito.VENTA_EXCESO)


def test_decision_48_vuelve_a_parar_antes_de_llenar_la_salida_sigue_y_se_repite_en_cada_reapertura(
        banco: Banco) -> None:
    """Decisión 48 (Jaume 30-sep): si vuelve a parar antes de que la MKT por OPEN llene, la salida viva NO se retira a
    los 2 s (entra en el cruce siguiente) ni vuelven los stops; si al final se retira sin llenar, en el halt siguiente
    sale OTRA MKT por lo que queda, hasta salir."""
    b = banco
    abrir_posicion(b)
    b.libro.llenar_parcial(D("0.5"), TICKER)                            # la primera subasta solo llena la mitad
    b.libro.halt(TICKER, "H", "09:31:00")
    b.cotizar(TICKER, "3.60", "3.62", "3.61")
    b.avanzar(1.5)
    (primera,) = b.enviadas(Proposito.HALT_OPEN)
    assert (primera.tipo, primera.qty) == (TipoOrden.MERCADO, 100)
    b.libro.reabrir(TICKER, D("3.70"))
    b.avanzar(0.5)
    assert b.pos().neta_fills == -50
    b.libro.halt(TICKER, "H", "09:31:10")                               # vuelve a parar antes de llenar el resto
    b.avanzar(3)                                                        # pasa la verificación de los 2 s
    assert b.orden(primera.token).estado is not EstadoOrden.CANCELED
    assert anotaciones(b.historial, "halt_salida_se_queda")
    assert len(b.enviadas(Proposito.HALT_OPEN)) == 1                    # la viva sirve: ninguna MKT de más
    assert _vivas_compra(b, *STOPS) == 0 and _sin_compra_doble(b, 50)
    b.libro.reabrir(TICKER, D("3.80"))                                  # el resto tampoco llena aquí (simulador)
    b.avanzar(3)
    assert b.orden(primera.token).estado is EstadoOrden.CANCELED       # G1A-01: reabierto y sin llenar → se retira
    assert _vivas_compra(b, *STOPS) == 50
    b.libro.llenar_parcial(D("1"), TICKER)
    b.libro.halt(TICKER, "H", "09:31:30")                               # otro halt: OTRA MKT por lo que queda
    b.avanzar(1.5)
    otra = b.enviadas(Proposito.HALT_OPEN)[1:]
    assert [(o.tipo, o.ruta, o.qty) for o in otra] == [(TipoOrden.MERCADO, "OPEN", 50)]
    assert _vivas_compra(b, *STOPS) == 0 and _sin_compra_doble(b, 50)
    b.libro.reabrir(TICKER, D("3.90"))
    b.avanzar(3)
    assert b.pos().neta_fills == 0 and not b.enviadas(Proposito.VENTA_EXCESO)


def test_decision_48_replace_del_stop_rechazado_con_la_salida_del_halt_viva_se_cancela(banco: Banco) -> None:
    """Decisión 48 (Jaume 30-sep): con un TP de 50 vivo la MKT por OPEN es de 50 y el stop tiene que BAJAR a 50 con un
    REPLACE (con toda la posición cubierta el plan lo cancela directamente: nunca un REPLACE a 0). Si DAS rechaza ese
    REPLACE, el stop se CANCELA y se anota: nunca stop entero + salida del halt a la vez. En el halt nada puede llenar
    antes del cruce de reapertura, así que el CANCEL llega antes de que la OPEN pueda ejecutarse."""
    b = banco
    abrir_posicion(b)
    (stop,) = b.enviadas(*STOPS)
    b.cotizar(TICKER, "3.44", "3.46", "3.45", tam_ask=0)
    _salida_motor(b, salida())
    assert [o.qty for o in b.enviadas(Proposito.TP_AGREGAR)] == [50]
    # decisión 54 (E1, Jaume 1-oct): al parar se intenta cancelar el TP; aquí DAS NO lo deja (sigue vivo y cuenta)
    b.libro.rechazar_siguiente("Cannot cancel during halt", accion="CancelRej")
    b.libro.rechazar_siguiente("Replace blocked", accion="ReplaceRej")
    marca = b.marca()
    b.libro.halt(TICKER, "H", "09:31:00")
    b.avanzar(1.5)
    tanda = b.desde(marca)
    assert [(o.tipo, o.qty) for o in b.enviadas(Proposito.HALT_OPEN, desde=marca)] == [(TipoOrden.MERCADO, 50)]
    assert [a for a in tanda if isinstance(a, Reemplazar) and a.token == stop.token]
    rechazo = anotaciones(tanda, "halt_stop_cancelado_replace_rej")
    assert len(rechazo) == 1 and rechazo[0].datos["token"] == stop.token
    assert stop.token in [c.token for c in acciones_de(tanda, Cancelar)]
    assert b.orden(stop.token).estado is EstadoOrden.CANCELED
    assert _sin_compra_doble(b, 100)


def test_decision_48_t1_en_rth_sobre_el_tope_cierra_a_mercado(cfg: Config, tmp_path: Path) -> None:
    """Decisión 48 (Jaume 30-sep; antes E1-02 «test_f6_t1_no_cierra_sin_tope»): en SESIÓN el tope del 250 % ya no se
    aplica a un halt H: la salida es una MKT por OPEN y, aunque reabra a +300 %, llena y la cuenta queda plana; ni
    control humano ni «halt_tope_t1»."""
    from app.bot_das.diario import MemoriaDecisor
    b = Banco(cfg, tmp_path, memoria=MemoriaDecisor(k_halts_up={TICKER: 3}))
    b.preparar()
    ev = evento(stop=20.0)                                              # stops lejos: el salto no es un cisne negro
    _a_halt(b, ta="H", ev=ev)
    salida_halt = b.enviadas(Proposito.HALT_OPEN)
    assert [(o.tipo, o.precio, o.ruta) for o in salida_halt] == [(TipoOrden.MERCADO, None, "OPEN")]
    marca = b.marca()
    b.libro.reabrir(TICKER, D("16.20"))                                 # +300 % sobre la parada (4,05)
    b.cotizar(TICKER, "16.10", "16.30", "16.20")
    b.avanzar(3)
    assert b.pos().neta_fills == 0 and not b.enviadas(Proposito.VENTA_EXCESO)
    assert b.pos().estado is not EstadoTicker.CONTROL_HUMANO
    assert not anotaciones(b.desde(marca), "halt_tope_t1")


def test_g1a_05_ticker_plano_en_halt_no_recibe_la_orden_y_la_senal_se_guarda(banco: Banco) -> None:
    """G1A-05 (director): un ticker PLANO sin estado de símbolo fresco pregunta `GET SymStatus X` antes de abrir; si DAS
    dice que está parado, la señal se GUARDA (R-F-04 b) y no se manda ninguna orden al símbolo parado."""
    b = banco
    b.libro.halt(TICKER, "H", "09:29:00")                               # parado y el bot aún no lo sabe
    acciones = b.senal(evento(), bombear=False)
    assert Consultar(f"GET SymStatus {TICKER}") in acciones and not acciones_de(acciones, EnviarOrden)
    assert not anotaciones(acciones, "senal")                          # la decisión espera a la respuesta
    b.bombear()
    assert not b.enviadas()
    assert anotaciones(b.historial, "senal_guardada") and b.pos().senal_guardada_halt is not None


def test_g1a_05_g1a_13_halt_que_deja_plano_detecta_la_reapertura_y_la_senal_guardada_agrega(cfg: Config,
                                                                                              tmp_path: Path) -> None:
    """G1A-05 / G1A-13 (director): el halt cancela la entrada sin fills (ticker plano) y aun así se sigue preguntando su
    estado: la reapertura se detecta, la señal guardada entra tras la primera vela y AGREGA sus 60 s (t_cierre = el
    momento en que se abre, no el de la reapertura)."""
    b = _dos_estrategias(cfg, tmp_path)
    b.simstatus()
    b.senal(evento())
    primera = b.enviadas(Proposito.ENTRADA_AGREGAR)[0]
    b.libro.halt(TICKER, "P", "09:30:10")
    b.avanzar(2)
    assert b.orden(primera.token).estado is EstadoOrden.CANCELED and b.pos().neta_fills == 0
    b.senal(evento(strategy_id=SID2, estrategia="PM (B) prueba", acciones=50.0, momento=momento_de(b.reloj.ahora())))
    assert b.pos().senal_guardada_halt is not None
    b.libro.reabrir(TICKER, D("3.45"))
    b.avanzar(3)
    assert any(a.datos.get("ticker") == TICKER for a in anotaciones(b.historial, "halt_reapertura"))
    b.avanzar(55)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")                          # libro fresco al cerrar la primera vela
    b.avanzar(5)
    assert anotaciones(b.historial, "halt_primera_vela")[-1].datos["reentrada"] is True
    segunda = [o for o in b.enviadas(Proposito.ENTRADA_AGREGAR) if o.token != primera.token]
    assert [o.qty for o in segunda] == [50]
    vence = b.temporizadores[f"cruce:{TICKER}"][0]
    assert vence - b.ahora() > 10                                       # agrega ~15 s (decisión 56), no cruza al instante


def test_g1a_08_g1b_12_sigue_x_levanta_el_veto_del_cisne_negro(banco: Banco) -> None:
    """G1A-08 / G1B-12 (director): tras el cierre de un cisne negro el ticker queda vetado; «/sigue X» (dos pasos) levanta
    ESE veto y la señal siguiente entra; «/sigue» a secas no lo levanta."""
    b = banco
    abrir_posicion(b)
    b.cotizar(TICKER, "6.90", "7.10", "7.00")
    b.tic_das()
    b.cotizar(TICKER, "5.95", "6.00", "6.00")                           # el stop (límite 6,00) saca la posición
    b.tic_das()
    assert b.pos().sin_reentrada_hasta_sigue is True
    b.comando("/sigue")
    assert b.pos().sin_reentrada_hasta_sigue is True                    # sin ticker: solo la pausa global
    acciones = b.comando("/sigue XYZ")
    assert b.pos().sin_reentrada_hasta_sigue is False and b.pos().intervencion_humana is False
    assert [a.datos["args"] for a in anotaciones(acciones, "comando") if a.datos.get("confirmado")] == [[TICKER]]
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    marca = b.marca()
    b.senal(evento(momento=otra_vela(b)))
    assert b.enviadas(Proposito.ENTRADA_AGREGAR, desde=marca)


def test_e1_03_k_se_siembra_de_la_memoria_y_el_radar_se_vigila_en_rth(cfg: Config, tmp_path: Path) -> None:
    """E1-03 (director): k de halts UP se SIEMBRA al arrancar (memoria del diario) y, en RTH, el SymStatus cubre también
    los tickers del radar suscritos (los halts anteriores a la entrada cuentan)."""
    from app.bot_das.diario import MemoriaDecisor
    b = Banco(cfg, tmp_path, memoria=MemoriaDecisor(k_halts_up={TICKER: 2}))
    assert b.mercado.simbolo(TICKER).k_halts_up == 2
    b.preparar()
    b.procesar(SenalRecibida(Senal(clase="radar", ticker=OTRO, id=None, estimacion=[], precio_radar=D("3.45"),
                                   recibida_en=b.ahora())))
    b.cotizar(OTRO, "3.44", "3.46", "3.45")
    marca = b.marca()
    b.avanzar(3)
    assert Consultar(f"GET SymStatus {OTRO}") in b.desde(marca)


def test_cob_02_resumen_del_dia_con_operaciones_resultado_locates_slippage_e_incidentes(cfg: Config,
                                                                                        tmp_path: Path) -> None:
    """COB-02 (R-M-01): tras el último EOD + 30 s, UN aviso con operaciones y resultado por estrategia, gasto de locates,
    slippage medido e incidentes (antes era solo la respuesta de /estado)."""
    config = cfg_con(cfg, estrategias=[dataclasses.replace(cfg.estrategias[SID], hora_fin_sesion="09:33")])
    b = Banco(config, tmp_path)
    b.preparar()
    abrir_posicion(b)
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 33, 5, tzinfo=ET))
    b.cotizar(TICKER, "3.40", "3.42", "3.41")
    b.tic_das()
    assert b.pos().neta_fills == 0
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 34, 0, tzinfo=ET))
    resumen_ = [a for a in b.historial if isinstance(a, Avisar) and (a.clave or "").startswith("resumen:")]
    assert len(resumen_) == 1 and resumen_[0].nivel is Nivel.INFO
    texto = resumen_[0].texto
    for trozo in ("Por estrategia", "PM (A) prueba: 1 operaciones", "Locates:", "Slippage medio", "Incidentes:"):
        assert trozo in texto, trozo
    datos = anotaciones(b.historial, "resumen_diario")[0].datos
    assert datos["por_estrategia"][0]["strategy_id"] == SID and datos["por_estrategia"][0]["operaciones"] == 1
    flujo = sum((-f.qty if f.lado == "B" else f.qty) * f.precio for lista in b.estado.fills.values() for f in lista)
    assert datos["por_estrategia"][0]["resultado"] == flujo.quantize(D("0.01"))           # ventas − compras
    assert datos["entradas_medidas"] == 1


def test_cob_03_retraso_de_la_senal_se_mide_tambien_si_se_descarta(banco: Banco) -> None:
    """COB-03 (R-A-01): `metrica retraso_senal_pct` también en una señal DESCARTADA (aquí por el propio retraso)."""
    b = banco
    b.simstatus()
    acciones = b.senal(evento(precio=3.20))                              # el último de DAS (3,45) está un 7,8 % arriba
    metrica = [a.datos for a in anotaciones(acciones, "metrica") if a.datos["nombre"] == "retraso_senal_pct"]
    assert len(metrica) == 1 and metrica[0]["valor"] > D("7")
    assert anotaciones(acciones, "senal_descartada")
    assert not b.enviadas()


def test_cob_04_get_con_simbolo_false_pregunta_sin_simbolo(cfg: Config, tmp_path: Path) -> None:
    """COB-04 (§5.8, pregunta 10): con `tecnicos.get_con_simbolo` false el SymStatus sale SIN símbolo (antes el ajuste
    era un fantasma: siempre «GET SymStatus X»)."""
    b = Banco(cfg_con(cfg, tecnicos={**cfg.tecnicos, "get_con_simbolo": False}), tmp_path)
    b.preparar()
    abrir_posicion(b)
    marca = b.marca()
    b.avanzar(3)
    consultas = [a.comando for a in b.desde(marca) if isinstance(a, Consultar) and "SymStatus" in a.comando]
    assert consultas and set(consultas) == {"GET SymStatus"}


def test_d1_05_g1b_19_cruce_al_tick_permisivo_no_da_falso_aviso_b13(cfg: Config, tmp_path: Path) -> None:
    """D1-05 / G1B-19: bid de la señal 1,34 y bid al cruzar 1,30 (−2,99 %: se cruza); el cruce 1,30 · 0,995 = 1,2935 va
    a 1,29 (tick de abajo) y llena ahí: es legal y NO avisa «fill peor de lo permitido» (antes sí, por el redondeo)."""
    b = Banco(cfg, tmp_path)
    b.preparar(cotizaciones=((TICKER, "1.34", "1.36", "1.35"),))
    b.simstatus()
    b.senal(evento(precio=1.35, stop=1.60))
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 30, 14, tzinfo=ET))
    b.cotizar(TICKER, "1.30", "1.32", "1.31", tam_bid=0)
    b.avanzar(1.5)
    cruce = b.enviadas(Proposito.ENTRADA_CRUCE)
    assert [(o.qty, o.precio) for o in cruce] == [(100, D("1.29"))]
    b.cotizar(TICKER, "1.29", "1.31", "1.30")                          # el bid baja a nuestro límite: llena a 1,29
    b.tic_das()
    assert b.pos().neta_fills == -100
    assert not [a for a in b.historial if isinstance(a, Avisar) and "peor" in a.texto.lower()]


def test_e2_05_varios_slret_de_una_consulta_se_elige_el_mas_barato(cfg: Config, tmp_path: Path) -> None:
    """E2-05: los %SLRET de una consulta «Inquire All» (uno por ruta) se juntan 0,5 s y se compra el MÁS BARATO con
    tamaño; ninguno se atribuye a la consulta de otra estrategia."""
    b = Banco(cfg, tmp_path)
    b.preparar(locates=())
    b.das_contesta = False
    b.procesar(SenalRecibida(Senal(clase="radar", ticker=TICKER, id=None,
                                   estimacion=[{"strategy_id": SID, "acciones": 1000.0, "riesgo_usd": 300.0}],
                                   precio_radar=D("3.45"), recibida_en=b.ahora())))
    b.das_contesta = True
    b.dar([f"%SLRET 1 {TICKER} 0.05 1000 LOCX  {CUENTA}", f"%SLRET 1 {TICKER} 0.01 1000 LOCSIM  {CUENTA}"])
    assert not [a for a in b.historial if isinstance(a, LocateComprar)]
    b.avanzar(1)
    compras = [a for a in b.historial if isinstance(a, LocateComprar)]
    assert [(c.qty, c.ruta) for c in compras] == [(1000, "LOCSIM")]
    elegido = anotaciones(b.historial, "slret_elegido")[0].datos
    assert (elegido["respuestas"], elegido["ruta"], elegido["estrategias"]) == (2, "LOCSIM", [SID])


def test_e2_05_con_el_reloj_parado_la_ventana_cierra_en_el_segundo_tic(cfg: Config, tmp_path: Path) -> None:
    """E2-05: la ventana también se cierra en el 2.º Tic tras abrirla (ráfaga ya entrada): con el reloj parado (replay,
    arneses del ejecutor) la compra del locate no queda colgada de un temporizador que no vence."""
    b = Banco(cfg, tmp_path)
    b.preparar(locates=())
    b.das_contesta = False
    b.procesar(SenalRecibida(Senal(clase="radar", ticker=TICKER, id=None,
                                   estimacion=[{"strategy_id": SID, "acciones": 1000.0, "riesgo_usd": 300.0}],
                                   precio_radar=D("3.45"), recibida_en=b.ahora())))
    b.das_contesta = True
    b.dar([f"%SLRET 1 {TICKER} 0.01 1000 LOCSIM  {CUENTA}"])
    b.procesar(Tic())
    assert not [a for a in b.historial if isinstance(a, LocateComprar)]
    acciones = b.procesar(Tic())
    assert [(c.qty, c.ruta) for c in acciones_de(acciones, LocateComprar)] == [(1000, "LOCSIM")]
    assert Desprogramar(f"slret_ventana:{TICKER}") in acciones


def test_e2_07_con_el_diario_roto_no_se_compra_el_locate_ni_queda_comprando(cfg: Config, tmp_path: Path) -> None:
    """E2-07 / corrección 4: disco roto + %SLRET favorable → ni LocateComprar ni el locate atascado en «comprando»; y si
    una compra llegara al filtro de `_finalizar`, el locate vuelve a «buscando» y a consultar."""
    b = Banco(cfg, tmp_path)
    b.preparar(locates=())
    b.das_contesta = False
    b.procesar(SenalRecibida(Senal(clase="radar", ticker=TICKER, id=None,
                                   estimacion=[{"strategy_id": SID, "acciones": 1000.0, "riesgo_usd": 300.0}],
                                   precio_radar=D("3.45"), recibida_en=b.ahora())))
    b.disco_roto = True
    b.das_contesta = True
    b.dar([f"%SLRET 1 {TICKER} 0.01 1000 LOCSIM  {CUENTA}"])
    b.avanzar(1)
    assert not [a for a in b.historial if isinstance(a, LocateComprar)]
    assert b.estado.locates[(TICKER, SID)].estado != "comprando"
    loc = b.estado.locates[(TICKER, SID)]
    b.estado.locates[(TICKER, SID)] = dataclasses.replace(loc, estado="comprando", token=424242)
    filtrado = b.decisor._finalizar([LocateComprar(TICKER, 1000, "LOCSIM", 424242)])   # la 2.ª barrera
    assert not [a for a in filtrado if isinstance(a, LocateComprar)]
    assert anotaciones(filtrado, "locate_bloqueado")
    assert b.estado.locates[(TICKER, SID)].estado == "buscando"
    assert any(isinstance(a, Programar) and a.clave.startswith("locate_inquire:") for a in filtrado)


def test_g1a_09_las_salidas_avisan_y_la_posicion_cerrada_libera_y_pide_equity(banco: Banco) -> None:
    """G1A-09 (R-M-01, F5): el TP que cuadra avisa al grupo B (nivel 1) una vez; al quedar plana, aviso con el
    resultado, `liberar_reservas` y `GET AccountInfo`."""
    b = banco
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    _salida_motor(b, salida(acciones=100.0))
    b.cotizar(TICKER, "3.43", "3.45", "3.44")
    marca = b.marca()
    b.tic_das()
    assert b.pos().neta_fills == 0
    tras = b.desde(marca)
    salida_ = [a for a in tras if isinstance(a, Avisar) and (a.clave or "").startswith("salida:")]
    assert len(salida_) == 1 and salida_[0].nivel is Nivel.INFO and "COMPRA 100 @ 3.45" in salida_[0].texto
    cerrada = [a for a in tras if isinstance(a, Avisar) and (a.clave or "").startswith(f"posicion_cerrada:{TICKER}")]
    assert len(cerrada) == 1 and "resultado 0.00 $" in cerrada[0].texto
    assert Consultar("GET AccountInfo") in tras
    assert b.estado.cuenta.bp_reservado == 0


def test_g1a_10_d1_08_excepcion_en_orden_agregar_no_deja_nada_a_medias(banco: Banco,
                                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    """G1A-10 / D1-08 (H-5): si `entrada.orden_agregar` lanza, no queda lote ABRIENDO, intento zombi, locates gastados
    ni margen reservado: lo puro se calcula ANTES de mutar el estado."""
    b = banco
    b.simstatus()

    def rota(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("ruta «agregar» no configurada (simulado)")

    monkeypatch.setattr(reglas_entrada, "orden_agregar", rota)
    acciones = b.senal(evento())
    assert anotaciones(acciones, "excepcion") and b.pos().estado is EstadoTicker.PAUSADO
    assert b.pos().intento is None and not b.pos().lotes
    assert b.estado.locates[(TICKER, SID)].usadas == 0 and b.estado.cuenta.bp_reservado == 0
    assert id_de_evento(evento()) not in b.estado.senales_vistas
    assert not b.enviadas()


def test_g1b_13_rama_rota_tras_registrar_stops_no_deja_stops_fantasma(banco: Banco,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """G1B-13 (H-5): la rama lanza DESPUÉS de que el plan registrara el stop (que no va a salir) → se cierra
    («no salió») y se piden barrido y plan inmediatos: el stop sale en el paso siguiente."""
    from app.bot_das import avisos as mod_avisos
    b = banco
    b.simstatus()
    b.senal(evento())

    def rota(*args: Any, **kwargs: Any) -> str:
        raise RuntimeError("texto del aviso roto (simulado)")

    monkeypatch.setattr(mod_avisos, "texto_fill", rota)
    llenar_entrada(b)
    assert b.pos().neta_fills == -100
    fantasmas = [o for o in b.estado.ordenes.values() if o.proposito in STOPS]
    assert fantasmas and all(o.estado is EstadoOrden.CLOSED and o.notas == "no salió (H-5)" for o in fantasmas)
    assert not b.enviadas(*STOPS)
    monkeypatch.undo()
    b.avanzar(1)
    reales = b.enviadas(*STOPS)
    assert sorted((o.proposito.value, o.qty) for o in reales) == [("stop", 100)]          # stop único (Jaume 29-sep)
    assert all(b.orden(o.token).estado is EstadoOrden.ACCEPTED for o in reales)


def test_g1a_12_g1b_10_control_manual_sobrevive_al_reinicio(cfg: Config, tmp_path: Path) -> None:
    """G1A-12 / G1B-10: tras /cancelar_ordenes y un reinicio (estado del diario o su memoria) el bot NO vuelve a poner
    stops en el ticker que gestiona el humano."""
    from app.bot_das.diario import MemoriaDecisor
    for via in ("estado", "memoria"):
        estado = _estado_con_lote()
        memoria = None
        if via == "estado":
            pos = estado.posiciones[TICKER]
            pos.estado = EstadoTicker.CONTROL_HUMANO
            pos.motivo_estado = "órdenes canceladas a mano (/cancelar_ordenes)"
        else:
            memoria = MemoriaDecisor(manual={TICKER})
        b = Banco(cfg, tmp_path / via, estado=estado, memoria=memoria)
        b.libro.sembrar_posicion(TICKER, -100, D("3.45"))
        b.preparar(locates=())
        b.avanzar(5)
        assert not b.enviadas(*STOPS), via


def test_g1b_09_cambios_de_telegram_sobreviven_al_reinicio(cfg: Config, tmp_path: Path) -> None:
    """G1B-09: /desactivar, /modo_seguridad y al_desactivar hechos por Telegram se reaplican al construir el decisor con
    la memoria del diario (antes, tras un relanzamiento, la estrategia desactivada volvía a operar)."""
    from app.bot_das.diario import MemoriaDecisor
    memoria = MemoriaDecisor(override_modo_seguridad=True,
                             override_estrategia={SID: {"ejecutar": False}, "desconocida": {"ejecutar": True}},
                             al_desactivar_por_arg={"PM (A) prueba": "esperar_fin_dia"})
    b = Banco(cfg, tmp_path, memoria=memoria)
    assert b.decisor.cfg.estrategias[SID].ejecutar is False
    assert b.decisor.cfg.estrategias[SID].al_desactivar == "esperar_fin_dia"
    assert b.decisor.cfg.modo_seguridad["activo"] is True
    b.preparar()
    b.simstatus()
    acciones = b.senal(evento())
    assert anotaciones(acciones, "senal_descartada") and not b.enviadas()


def test_g1b_09_al_desactivar_por_telegram_se_anota_para_rehacerlo(banco: Banco) -> None:
    """G1B-09: «/esperar_fin_dia X» deja `config_cambio` con origen telegram (la forma que `memoria_decisor` rehace)."""
    acciones = banco.comando("/esperar_fin_dia prueba-1")
    cambio = anotaciones(acciones, "config_cambio")
    assert [(a.datos["ruta"], a.datos["despues"], a.datos["origen"]) for a in cambio] == \
           [(f"estrategias.{SID}.al_desactivar", "esperar_fin_dia", "telegram")]


def test_g1a_14_fill_tardio_en_un_halt_h_programa_la_decision(banco: Banco) -> None:
    """G1A-14: la entrada cancelada al detectar un halt H llena TARDE: la neta pasa de 0 a −100 con el símbolo parado →
    se programa `halt_decidir` (antes dependía de un $IssueStatus con otro fin, que en un H nunca llega)."""
    b = banco
    b.simstatus()
    b.senal(evento())
    agregar = b.enviadas(Proposito.ENTRADA_AGREGAR)[0]
    id_das = b.orden(agregar.token).id_das
    b.das_contesta = False
    b.libro.halt(TICKER, "H", "09:30:05")
    b.dar(b.das.recibir(f"GET SymStatus {TICKER}"))
    assert TICKER in {a.datos["ticker"] for a in anotaciones(b.historial, "halt")}
    assert f"halt_decidir:{TICKER}" not in b.temporizadores              # plano: nada que decidir aún
    b.dar([_linea_act("Execute", agregar, id_das, 100, "3.45")])
    assert b.pos().neta_fills == -100
    assert f"halt_decidir:{TICKER}" in b.temporizadores
    assert b.pos().estado is EstadoTicker.HALT


def test_g1a_15_fill_tardio_de_una_entrada_cerrada_va_a_su_lote_no_al_intento_nuevo(cfg: Config,
                                                                                     tmp_path: Path) -> None:
    """G1A-15: la entrada de A se cierra sin confirmar su cancelación, B abre OTRO intento y llega el fill tardío de A:
    va entero al lote de A (reabierto), nada al de B ni a su intento."""
    b = _dos_estrategias(cfg, tmp_path)
    b.simstatus()
    b.senal(evento())
    agregar = b.enviadas(Proposito.ENTRADA_AGREGAR)[0]
    id_das = b.orden(agregar.token).id_das
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 30, 14, tzinfo=ET))
    b.das_contesta = False
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 30, 19, tzinfo=ET))
    lote_a = lote_de(evento())
    assert b.pos().intento is None and b.pos().lotes[lote_a].estado is EstadoLote.CANCELADO
    b.das_contesta = True
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    ev_b = evento(strategy_id=SID2, estrategia="PM (B) prueba", acciones=50.0, momento=momento_de(b.reloj.ahora()))
    b.simstatus()
    b.senal(ev_b)
    assert b.pos().intento is not None and b.pos().intento.lotes == [lote_de(ev_b)]
    b.dar([_linea_act("Execute", agregar, id_das, 100, "3.45")])
    lotes = b.pos().lotes
    assert (lotes[lote_a].estado, lotes[lote_a].llenas) == (EstadoLote.ABIERTO, 100)
    assert lotes[lote_de(ev_b)].llenas == 0 and b.pos().intento.llenas == 0


def test_g1a_18_g1b_18_veto_r_f_03_se_siembra_y_la_salida_del_halt_cuenta_como_stop(cfg: Config,
                                                                                    tmp_path: Path) -> None:
    """G1A-18 / G1B-18: el veto R-F-03 (stop + halt sin reapertura válida) sale de la memoria del diario tras un
    reinicio, y una salida del halt por OPEN lo activa igual que un stop."""
    from app.bot_das.diario import MemoriaDecisor
    b = Banco(cfg, tmp_path, memoria=MemoriaDecisor(halt_hoy={TICKER}, stop_hoy={TICKER}))
    b.preparar()
    b.simstatus()
    acciones = b.senal(evento())
    assert "R-F-03" in anotaciones(acciones, "senal_descartada")[0].datos["motivo"]
    otro = Banco(cfg, tmp_path / "otro")
    otro.preparar()
    _a_halt(otro)
    otro.avanzar_hasta(datetime(2026, 9, 25, 9, 31, 1, tzinfo=ET))
    otro.libro.reabrir(TICKER, D("3.95"))
    otro.avanzar(3)
    assert otro.pos().neta_fills == 0                                   # salió por la OPEN, no por un stop
    otro.cotizar(TICKER, "3.94", "3.96", "3.95")
    acciones = otro.senal(evento(momento=otra_vela(otro)))
    assert "R-F-03" in anotaciones(acciones, "senal_descartada")[0].datos["motivo"]


def _dos_cisnes(b: Banco) -> None:
    _dos_posiciones(b)
    for t in (TICKER, OTRO):
        b.cotizar(t, "6.90", "7.10", "7.00")
    b.tic_das()
    assert b.pos().estado is EstadoTicker.BS and b.pos(OTRO).estado is EstadoTicker.BS


def test_g1a_19_parar_avisos_x_bs_calla_solo_ese_cisne_negro(cfg: Config, tmp_path: Path) -> None:
    """G1A-19 (R-G-01): con dos cisnes negros vivos, «/parar_avisos X BS» calla SOLO los de X; sin ticker, se pide cuál
    (nunca se callan todos a la vez). Se anota con args [X, "BS"] (lo que rehace el diario)."""
    b = Banco(cfg, tmp_path)
    _dos_cisnes(b)
    acciones = b.comando("/parar_avisos")
    assert "indica cuál" in _respuesta(acciones)
    assert b.pos().bs.silenciado is False and b.pos(OTRO).bs.silenciado is False
    acciones = b.comando("/parar_avisos XYZ BS")
    assert b.pos().bs.silenciado is True and b.pos(OTRO).bs.silenciado is False
    assert [a.datos["args"] for a in anotaciones(acciones, "comando") if a.datos.get("confirmado")] == [[TICKER, "BS"]]


def test_g1a_20_g1b_20_el_fill_del_stop_de_un_nivel_descuenta_primero_sus_lotes(banco: Banco) -> None:
    """G1A-20 / G1B-20 con el stop único (Jaume 29-sep, R-C-01 v4): el stop de un nivel lleva las acciones de SUS lotes,
    así que su fill las descuenta de ellos primero (el nivel sale de `stops.nivel_de_stop`); lo que sobre, desde el L
    más alto. El lote del otro nivel conserva sus acciones (y su stop)."""
    b = banco
    pos = PosicionTicker(ticker=TICKER, neta_fills=-130)
    b.estado.posiciones[TICKER] = pos
    a = Lote(id="A", strategy_id=SID, estrategia="A", ticker=TICKER, direccion="Short", pedidas=100, llenas=80,
             precio_medio=D("3.45"), nivel_stop=D("4.00"), estado=EstadoLote.ABIERTO, eod="11:30:00")
    bl = Lote(id="B", strategy_id=SID2, estrategia="B", ticker=TICKER, direccion="Short", pedidas=50, llenas=50,
              precio_medio=D("3.45"), nivel_stop=D("4.20"), estado=EstadoLote.ABIERTO, eod="11:30:00")
    pos.lotes = {"A": a, "B": bl}
    stop_a = Orden(token=126800077, ticker=TICKER, lado=Lado.COMPRA, tipo=TipoOrden.STOP_LIMITE_PP, qty=80,
                   precio=D("6.00"), stop=D("4.00"), ruta="STOP", proposito=Proposito.STOP, lote_id="A",
                   nivel=D("4.00"), origen=Origen.EJECUTOR)
    from app.bot_das.reglas import stops as mod_stops
    nivel = mod_stops.nivel_de_stop(stop_a, pos, b.decisor.cfg.stops)
    assert nivel == D("4.00")
    preferidos = [lote.id for lote in pos.lotes.values() if lote.nivel_stop == nivel]
    acciones, cerrados = b.decisor._reducir_lotes(pos, 60, preferidos, mas_alto_primero=True)
    assert (a.llenas, bl.llenas, cerrados) == (20, 50, [])
    acciones, cerrados = b.decisor._reducir_lotes(pos, 30, preferidos, mas_alto_primero=True)
    assert (a.llenas, bl.llenas, cerrados) == (0, 40, ["A"])                # lo que sobra, del L más alto (B)


def test_g1a_21_g1b_14_stop_cancelado_en_un_halt_se_repone_al_reabrir(banco: Banco) -> None:
    """G1A-21 / G1B-14 (R-C-04, excepción del halt): DAS cancela el stop con el símbolo parado → aviso, NADA se
    repone durante el halt (ni se gastan intentos de R-C-03) y el stop vuelve al reabrir."""
    b = banco
    _a_halt(b, cot=("3.94", "3.96", "3.95"))
    stop = b.enviadas(Proposito.STOP)[0]
    marca = b.marca()
    b.dar(b.das.recibir(f"CANCEL {b.orden(stop.token).id_das}"))
    aviso = [a for a in b.desde(marca) if isinstance(a, Avisar) and (a.clave or "").startswith(f"stop_cancelado:{TICKER}")]
    assert len(aviso) == 1 and "HALT" in aviso[0].texto
    b.avanzar(3)
    assert not b.enviadas(*STOPS, desde=marca)
    b.libro.reabrir(TICKER, D("3.95"))
    b.avanzar(2)
    repuesta = b.enviadas(*STOPS, desde=marca)
    assert [(o.proposito, o.qty) for o in repuesta] == [(Proposito.STOP, 100)]
    assert anotaciones(b.desde(marca), "stops_reponer_reapertura")


def test_a_06_todas_las_consultas_get_salen_de_protocolo_cmd_get(banco: Banco) -> None:
    """A-06 (§4.1): cada `Consultar("GET …")` del decisor es exactamente lo que construye `protocolo.cmd_get` (conjunto
    cerrado de nombres y símbolo validado)."""
    b = banco
    abrir_posicion(b)
    b.avanzar(65)
    consultas = {a.comando for a in b.historial if isinstance(a, Consultar) and a.comando.startswith("GET ")}
    assert consultas
    for comando in consultas:
        partes = comando.split()
        assert protocolo.cmd_get(*partes[1:]) == comando, comando


def test_d1_07_alto_riesgo_con_criterio_usa_la_mitad_del_equity(cfg: Config, tmp_path: Path) -> None:
    """D1-07 (2c consecuencia 2): con `entrada.alto_riesgo_si` (p. ej. precio < 5 $) el corto usa 0,5× el equity (antes
    `_ALTO_RIESGO` era siempre False); sin criterio, el tope de siempre."""
    tamanos = {}
    for nombre, criterio in (("sin", None), ("con", {"precio_max": 5})):
        entrada_cfg = dict(cfg.entrada)
        if criterio is not None:
            entrada_cfg["alto_riesgo_si"] = criterio
        b = Banco(cfg_con(cfg, entrada=entrada_cfg), tmp_path / nombre)
        b.preparar()
        b.estado.cuenta.equity = D("500")
        b.simstatus()
        b.senal(evento())
        tamanos[nombre] = sum(o.qty for o in b.enviadas(Proposito.ENTRADA_AGREGAR))
    assert tamanos["con"] < tamanos["sin"] <= 100 and tamanos["con"] > 0


def test_d1_10_equity_se_relee_y_sin_equity_se_pide_con_aviso(banco: Banco) -> None:
    """D1-10: `GET AccountInfo` se pide periódicamente (el tope corto no usa el equity de la mañana) y, sin equity, la
    entrada se descarta, se vuelve a pedir y se avisa nivel 2."""
    b = banco
    marca = b.marca()
    b.avanzar(35)
    assert Consultar("GET AccountInfo") in b.desde(marca)
    b.estado.cuenta.equity = None
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    b.simstatus()
    acciones = b.senal(evento(momento=momento_de(b.reloj.ahora())))
    assert Consultar("GET AccountInfo") in acciones
    assert any(isinstance(a, Avisar) and a.clave == "sin_equity" and a.nivel is Nivel.AVISO for a in acciones)
    assert not b.enviadas(Proposito.ENTRADA_AGREGAR)


def test_dc_07_la_linea_cruda_de_das_va_al_diario(banco: Banco) -> None:
    """DC-07 (§8): «cruda» en orden_act, orden_estado, fill y pos."""
    b = banco
    abrir_posicion(b)
    for tipo in ("orden_act", "orden_estado", "fill", "pos"):
        registros = [a for a in anotaciones(b.historial, tipo) if a.datos.get("cruda")]
        assert registros, tipo
        assert isinstance(registros[0].datos["cruda"], str) and registros[0].datos["cruda"].startswith(("%", "$"))


def test_dc_02_fill_sintetico_reconstruido_no_se_cuenta_dos_veces_con_su_trade(cfg: Config, tmp_path: Path) -> None:
    """DC-02: `reconstruir` deja con id NEGATIVO el fill de un Execute sin su %TRADE; tras el reinicio, cuando DAS manda
    ese %TRADE, es su eco: la neta NO se duplica."""
    estado = _estado_con_lote()
    token = GeneradorTokens(Origen.EJECUTOR, HOY).siguiente()
    estado.ultimo_seq_token = descomponer(token)[2]
    lote_id = lote_de(evento())
    estado.ordenes[token] = Orden(token=token, ticker=TICKER, lado=Lado.CORTO, tipo=TipoOrden.LIMITE, qty=100,
                                  precio=D("3.45"), stop=None, ruta="SAGEREB", proposito=Proposito.ENTRADA_AGREGAR,
                                  lote_id=lote_id, nivel=D("4.0"), origen=Origen.EJECUTOR, id_das=77,
                                  estado=EstadoOrden.EXECUTED, llenas=100)
    estado.id_a_token[77] = token
    estado.fills[token] = [Fill(id_trade=-1, token=token, id_orden=77, ticker=TICKER, lado="SS", qty=100,
                                precio=D("3.45"), ruta="SAGEREB", hora="09:29:30", liq=None, ecn_fee=None)]
    b = Banco(cfg, tmp_path, estado=estado)
    b.libro.sembrar_posicion(TICKER, -100, D("3.45"))
    b.preparar(locates=())
    marca = b.marca()
    b.dar([f"%TRADE 9001 {TICKER} SS 100 3.45 SAGEREB 09:29:30 77 + 0 0.00"])
    assert b.pos().neta_fills == -100
    assert b.estado.fills[token][0].id_trade == 9001
    fill = anotaciones(b.desde(marca), "fill")
    assert len(fill) == 1 and fill[0].datos["eco"] is True


def test_d2a_04_venta_del_exceso_que_no_llena_se_persigue_al_bid(cfg: Config, tmp_path: Path) -> None:
    """D2a-04 (director): la venta del exceso sale a bid · (1 − 2 %) y, 1 s después, si no llenó y la cuenta sigue larga,
    `exceso_verificar` la REEMPLAZA al bid nuevo con el mismo margen (antes el temporizador no tenía manejador)."""
    b = Banco(cfg, tmp_path)
    b.preparar()
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    _salida_motor(b, salida(acciones=20.0))
    b.cotizar(TICKER, "3.43", "3.45", "3.44")
    lineas = b.das.tic()                                                # el TP (compra 3,45) llena 20
    b.das_contesta = False                                              # el REPLACE del stop (100 → 80) queda en vuelo
    b.dar(lineas)
    assert b.pos().neta_fills == -80
    b.das_contesta = True
    b.cotizar(TICKER, "4.58", "4.60", "4.60", tam_bid=0)               # el stop (aún 100 en DAS) llena: larga 20
    b.tic_das()
    ventas = b.enviadas(Proposito.VENTA_EXCESO)
    assert [(o.lado, o.qty, o.precio) for o in ventas] == [(Lado.VENTA, 20, D("4.48"))]     # 4,58 · 0,98
    assert f"exceso_verificar:{TICKER}" in b.temporizadores
    b.cotizar(TICKER, "4.50", "4.52", "4.51", tam_bid=0)
    b.avanzar(1.2)
    perseguida = [r for r in b.historial if isinstance(r, Reemplazar) and r.token == ventas[0].token]
    assert [(r.qty, r.precio) for r in perseguida] == [(20, D("4.41"))]  # 4,50 · 0,98 redondeado abajo
    assert anotaciones(b.historial, "venta_exceso_perseguida")
    assert not anotaciones(b.historial, "temporizador_desconocido")


def test_d2a_07_cantidad_viva_con_lvqty_viejo_tras_el_execute() -> None:
    """D2a-07: el Execute sube `llenas` sin tocar un `lvqty` viejo → viva = min(lvqty, qty − llenas) (70, no 100)."""
    from app.bot_das.decisor import _qty_viva
    o = Orden(token=1, ticker=TICKER, lado=Lado.COMPRA, tipo=TipoOrden.STOP_LIMITE_PP, qty=100, precio=D("4.12"),
              stop=D("4.00"), ruta="STOP", proposito=Proposito.STOP, lote_id=None, nivel=None,
              origen=Origen.EJECUTOR, estado=EstadoOrden.PARTIAL, lvqty=100, llenas=30)
    assert _qty_viva(o) == 70
    o.lvqty = 50
    assert _qty_viva(o) == 50
    o.estado, o.llenas = EstadoOrden.ACCEPTED, 0
    assert _qty_viva(o) == 100


def test_d2a_08_a_02_replace_con_share_total_no_compra_de_mas(cfg: Config, tmp_path: Path) -> None:
    """D2a-08 / A-02: con `stops.replace_share_es_abierta` false DAS lee el share como TOTAL: la persecución de una orden
    con 30 llenas manda share 100 (30 + 70) y, al «Replaced», el decisor deja qty 100 y 70 vivas; la cuenta acaba plana
    (nunca larga)."""
    config = cfg_con(cfg, stops={**cfg.stops, "replace_share_es_abierta": False},
                     estrategias=[dataclasses.replace(cfg.estrategias[SID], hora_fin_sesion="09:33")])
    b = Banco(config, tmp_path)
    b.das.replace_share_es_abierta = False
    b.preparar()
    abrir_posicion(b)
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 32, 30, tzinfo=ET))
    b.cotizar(TICKER, "3.45", "3.47", "3.46", tam_ask=30)
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 33, 0, 100_000, tzinfo=ET))
    al_ask = b.enviadas(Proposito.HORA_ASK)[0]
    assert b.orden(al_ask.token).llenas == 30
    b.cotizar(TICKER, "3.47", "3.50", "3.48", tam_ask=0)
    b.avanzar(1.2)
    reemplazo = [r for r in b.historial if isinstance(r, Reemplazar) and r.token == al_ask.token]
    assert [(r.qty, r.precio) for r in reemplazo] == [(100, D("3.50"))]
    o = b.orden(al_ask.token)
    assert (o.qty, o.llenas, o.lvqty) == (100, 30, 70)
    b.cotizar(TICKER, "3.48", "3.50", "3.49")
    b.tic_das()
    assert b.pos().neta_fills == 0 and b.pos().neta_das == 0
    assert not b.enviadas(Proposito.VENTA_EXCESO)


def test_d2_05_salida_por_tiempo_va_al_ask_sin_techo_con_la_qty_del_evento(banco: Banco) -> None:
    """D2-05 (director): «Partial TP (Hour)» → la qty DEL EVENTO al ask sin techo (HORA_ASK) y a perseguir (R-D-08);
    antes solo se anotaba."""
    b = banco
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45", tam_ask=0)
    _salida_motor(b, salida(motivo="Partial TP (Hour)", acciones=40.0))
    hora = b.enviadas(Proposito.HORA_ASK)
    assert [(o.qty, o.precio, o.post_only) for o in hora] == [(40, D("3.46"), False)]
    assert f"perseguir_ask:{hora[0].token}" in b.temporizadores
    b.cotizar(TICKER, "3.47", "3.50", "3.48", tam_ask=0)
    b.avanzar(1.5)
    assert [r.precio for r in b.historial if isinstance(r, Reemplazar) and r.token == hora[0].token] == [D("3.50")]


def test_d2_12_tp_sin_libro_no_lanza_y_cruza_con_techo_a_los_2_s(banco: Banco) -> None:
    """D2-12: con el libro CRUZADO (normal en premercado) el TP no puede agregar: no lanza (antes H-5 pausaba el ticker),
    se anota y a los 2 s `tp_al_vencer` cruza al ask con techo."""
    b = banco
    abrir_posicion(b)
    b.dar([f"$Quote {TICKER} A:3.44 B:3.46 V:500000 L:3.45"])          # ask < bid: DAS lo manda así en PM
    acciones = _salida_motor(b, salida())
    assert anotaciones(acciones, "salida_sin_libro") and not anotaciones(acciones, "excepcion")
    assert not b.enviadas(Proposito.TP_AGREGAR) and b.pos().estado is EstadoTicker.NORMAL
    b.cotizar(TICKER, "3.44", "3.46", "3.45", tam_ask=0)
    b.avanzar(2.5)
    assert [(o.qty, o.precio) for o in b.enviadas(Proposito.TP_CRUCE)] == [(50, D("3.46"))]


def _banco_premercado(cfg: Config, tmp_path: Path) -> Banco:
    inicio = datetime(2026, 9, 25, 8, 0, tzinfo=ET)
    b = Banco(cfg, tmp_path, inicio=inicio)
    b.preparar()
    abrir_posicion(b, evento(momento=momento_de(inicio)))
    return b


def test_e1_04_halt_h_en_premercado_con_mantener_no_estrecha_el_stop_unico(cfg: Config, tmp_path: Path) -> None:
    """E1-04 (director, R-F-06 2.ª parte) con el stop único (Jaume 29-sep): halt H de premercado con decisión «mantener»
    → el ensanche del límite a disparo · (1 + 5 %) no tiene nada que hacer: el límite del stop (L + 50 %) ya es más
    ancho. Ni se mueve el disparo ni se ESTRECHA el límite (nunca un REPLACE a 4,20 sobre un límite de 6,00)."""
    b = _banco_premercado(cfg, tmp_path)
    (stop,) = b.enviadas(*STOPS)
    assert (stop.stop, stop.precio) == (D("4.00"), D("6.00"))
    b.libro.halt(TICKER, "H", "08:00:30")
    b.cotizar(TICKER, "3.60", "3.62", "3.61")                           # bajo el stop: escenario 1, k < 3
    marca = b.marca()
    b.avanzar(2)
    assert acciones_de(b.desde(marca), Reemplazar) == []
    assert (b.orden(stop.token).stop, b.orden(stop.token).precio) == (D("4.00"), D("6.00"))
    assert not b.enviadas(Proposito.HALT_OPEN, Proposito.HALT_PM_LIMITE)
    assert _vivas_compra(b, *STOPS) == 100


def test_decision_39_el_decisor_ya_no_llama_al_ensanche_pm(cfg: Config, tmp_path: Path,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    """Decisión 39 (Jaume 30-sep): E1-04 retirado. Halt H de premercado con «mantener» → el decisor NO llama a
    `halts.ensanchar_stops_pm` (si la llamara, aquí lanzaría y el ticker quedaría pausado por H-5) y no anota nada."""
    llamadas: list[str] = []

    def _no(*_a: Any, **_k: Any) -> list:
        llamadas.append("llamada")
        raise AssertionError("E1-04 retirado: el decisor no debe ensanchar stops en PM")

    monkeypatch.setattr("app.bot_das.reglas.halts.ensanchar_stops_pm", _no)
    b = _banco_premercado(cfg, tmp_path)
    b.libro.halt(TICKER, "H", "08:00:30")
    b.cotizar(TICKER, "3.60", "3.62", "3.61")
    marca = b.marca()
    b.avanzar(2)
    decisiones = [a.datos["decision"] for a in anotaciones(b.desde(marca), "halt_decision")]
    assert decisiones and set(decisiones) == {"mantener"}
    assert llamadas == [] and not anotaciones(b.desde(marca), "halt_stops_pm") and not anotaciones(b.desde(marca),
                                                                                                    "excepcion")


def test_r_f_06_halt_de_premercado_que_reabre_en_rth_cambia_la_limite_pm_por_open(cfg: Config, tmp_path: Path) -> None:
    """R-F-06 (Jaume 29-sep): un halt H que empieza en premercado casi siempre reabre en RTH. La límite de PM (que no entra
    en el cruce de reapertura) se RETIRA al llegar RTH y sale la orden por OPEN (decisión 48: MKT, sin tope); los stops
    se reducen antes de mandarla y no queda ninguna compra doble."""
    b = _banco_premercado(cfg, tmp_path)
    b.libro.halt(TICKER, "H", "08:00:30")
    b.cotizar(TICKER, "4.08", "4.10", "4.09")                           # sobre el stop (4,00), dentro de su límite: escenario 2
    b.avanzar(2)
    pm = b.enviadas(Proposito.HALT_PM_LIMITE)
    assert len(pm) == 1 and pm[0].tipo is TipoOrden.LIMITE and pm[0].ruta != "OPEN"
    assert not b.enviadas(Proposito.HALT_OPEN)
    marca = b.marca()
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 31, 5, tzinfo=ET))
    tanda = b.desde(marca)
    assert [c.token for c in acciones_de(tanda, Cancelar) if c.token == pm[0].token]
    assert anotaciones(tanda, "halt_pm_limite_a_open")
    abiertas = b.enviadas(Proposito.HALT_OPEN)
    assert [(o.tipo, o.ruta, o.qty) for o in abiertas] == [(TipoOrden.MERCADO, "OPEN", 100)]
    assert _vivas_compra(b, Proposito.HALT_PM_LIMITE) == 0 and _vivas_compra(b, Proposito.HALT_OPEN) == 100
    b.libro.reabrir(TICKER, D("5.00"))
    b.cotizar(TICKER, "4.99", "5.01", "5.00")
    b.avanzar(3)
    assert b.pos().neta_fills == 0 and not b.enviadas(Proposito.VENTA_EXCESO)


# ── decisión 46 (Jaume 30-sep): halt H de premercado que reabre por encima del límite del stop ──
def _halt_pm_mantener(cfg: Config, tmp_path: Path) -> Banco:
    """Corto de 100 (stop único 4,00 / límite 6,00) en premercado; halt H con el precio bajo el stop: «mantener»."""
    b = _banco_premercado(cfg, tmp_path)
    b.libro.halt(TICKER, "H", "08:00:30")
    b.cotizar(TICKER, "3.60", "3.62", "3.61")
    b.avanzar(2)
    assert b.pos().estado is EstadoTicker.HALT
    assert {a.datos["decision"] for a in anotaciones(b.historial, "halt_decision")} == {"mantener"}
    return b


def _techo(b: Banco, cfg: Config) -> Decimal:
    from app.bot_das.reglas import halts as reglas_halts
    return reglas_halts.precio_tope_t1(b.decisor._mercado.simbolo(TICKER), cfg.halts)


def test_decision_46_reabre_sobre_el_limite_y_bajo_el_techo_cierra_sin_compra_doble(cfg: Config,
                                                                                       tmp_path: Path) -> None:
    """Decisión 46: el T llega con el last de antes del halt (nada todavía); el primer print real, 7,00, pasa el límite
    del stop (6,00) sin llegar al techo del T1 → el stop baja a 0 ANTES y sale una compra LÍMITE al techo por la ruta
    de cruzar. Llena, la cuenta queda plana, sin compra doble ni venta del exceso, y NO se declara cisne negro."""
    b = _halt_pm_mantener(cfg, tmp_path)
    (stop,) = b.enviadas(*STOPS)
    techo = _techo(b, cfg)
    assert techo is not None and techo > D("7.00")
    marca = b.marca()
    b.libro.reabrir(TICKER, D("7.00"))
    b.avanzar(1.2)
    assert anotaciones(b.desde(marca), "halt_reapertura") and not b.enviadas(Proposito.HALT_PM_LIMITE, desde=marca)
    b.cotizar(TICKER, "6.95", "7.05", "7.00", tam_ask=1000)
    tanda = b.desde(marca)
    cierre = b.enviadas(Proposito.HALT_PM_LIMITE, desde=marca)
    assert [(o.tipo, o.precio, o.qty, o.tif) for o in cierre] == [(TipoOrden.LIMITE, techo, 100, "DAY+")]
    assert cierre[0].ruta != "OPEN"
    envio = next(i for i, a in enumerate(tanda) if isinstance(a, EnviarOrden) and a.orden.token == cierre[0].token)
    cancelado = next(i for i, a in enumerate(tanda) if isinstance(a, Cancelar) and a.token == stop.token)
    assert cancelado < envio                                             # el stop baja ANTES (G1A-01)
    assert _sin_compra_doble(b, 100)
    assert b.pos().bs is None and not [a for a in anotaciones(tanda, "bs") if a.datos.get("evento") == "activado"]
    assert anotaciones(tanda, "halt_pm_sobre_limite")[0].datos["veredicto"] == "cerrar_tope"
    b.avanzar(3)
    assert b.pos().neta_fills == 0 and b.pos().neta_das == 0
    assert not b.enviadas(Proposito.VENTA_EXCESO) and b.pos().bs is None
    assert not [a for a in anotaciones(b.historial, "incidente") if a.datos.get("tipo") == "cuenta_larga"]


def test_decision_49_reabre_sobre_el_techo_limite_viva_stops_fuera_y_llena_al_bajar(cfg: Config,
                                                                                    tmp_path: Path) -> None:
    """Decisión 49 (Jaume 30-sep; antes decisión 46 «ninguna orden»): en premercado reabre por encima del techo del T1
    (parada · 3,5) → una compra LÍMITE VIVA en el techo por toda la posición, el stop CANCELADO (no se repone), aviso
    máximo y CONTROL_HUMANO; a los 2 s NO se retira, no hay cisne negro, y cuando el precio baja del techo llena y la
    cuenta queda plana."""
    b = _halt_pm_mantener(cfg, tmp_path)
    (stop,) = b.enviadas(*STOPS)
    techo = _techo(b, cfg)
    marca = b.marca()
    precio = techo + D("1")
    b.libro.reabrir(TICKER, precio)
    b.avanzar(1.2)
    b.cotizar(TICKER, str(precio - D("0.05")), str(precio + D("0.05")), str(precio), tam_ask=0)
    tanda = b.desde(marca)
    assert anotaciones(tanda, "halt_pm_sobre_limite")[0].datos["veredicto"] == "control_humano"
    (cierre,) = b.enviadas(Proposito.HALT_PM_LIMITE, desde=marca)
    assert (cierre.tipo, cierre.precio, cierre.qty, cierre.tif) == (TipoOrden.LIMITE, techo, 100, "DAY+")
    assert anotaciones(tanda, "halt_pm_techo_vivo")
    assert any(isinstance(a, Avisar) and a.nivel is Nivel.MAXIMO and a.clave == f"halt_pm_techo_vivo:{TICKER}"
               for a in tanda)
    assert b.pos().estado is EstadoTicker.CONTROL_HUMANO and b.pos().neta_fills == -100
    assert b.orden(stop.token).estado is EstadoOrden.CANCELED and _vivas_compra(b, *STOPS) == 0
    b.avanzar(5)                                                          # pasa la verificación de los 2 s
    assert b.orden(cierre.token).estado in (EstadoOrden.ACCEPTED, EstadoOrden.SENDING)
    assert _vivas_compra(b, *STOPS) == 0 and _sin_compra_doble(b, 100) and b.pos().bs is None
    assert anotaciones(b.desde(marca), "halt_pm_techo_sigue")
    b.cotizar(TICKER, str(techo - D("0.10")), str(techo - D("0.05")), str(techo - D("0.05")), tam_ask=1000)
    b.avanzar(2)
    assert b.pos().neta_fills == 0 and b.pos().neta_das == 0
    assert not b.enviadas(Proposito.VENTA_EXCESO) and not b.enviadas(*STOPS, desde=marca)
    assert not b.decisor._techo_vivo(TICKER)                             # se olvida con la posición cerrada


def test_decision_46_reabre_dentro_del_limite_llena_el_stop_como_hoy(cfg: Config, tmp_path: Path) -> None:
    """Decisión 46: reabre a 5,00 (sobre el disparo 4,00, dentro del límite 6,00) → lo de siempre: llena el stop."""
    b = _halt_pm_mantener(cfg, tmp_path)
    marca = b.marca()
    b.libro.reabrir(TICKER, D("5.00"))
    b.avanzar(1.2)
    b.cotizar(TICKER, "4.95", "5.05", "5.00", tam_ask=1000)
    b.avanzar(2)
    assert b.pos().neta_fills == 0
    assert not b.enviadas(Proposito.HALT_PM_LIMITE, desde=marca) and not anotaciones(b.desde(marca),
                                                                                     "halt_pm_sobre_limite")


def test_decision_48_halt_de_pm_con_mantener_que_sigue_a_las_0930_sale_a_mercado_por_open(cfg: Config,
                                                                                           tmp_path: Path) -> None:
    """Decisión 48 (Jaume 30-sep; antes «decisión 46 no aplica» y se quedaba en cisne negro): halt H de premercado con
    «mantener» (bajo el stop) que sigue parado a las 09:30 → en ese momento (no hasta 60 s después) se decide otra vez:
    MKT por OPEN por toda la posición con el stop cancelado antes; reabre a 7,00 (sobre el límite del stop), llena y la
    cuenta queda plana, sin cisne negro ni decisión 46."""
    b = _halt_pm_mantener(cfg, tmp_path)
    (stop,) = b.enviadas(*STOPS)
    assert not b.enviadas(Proposito.HALT_OPEN, Proposito.HALT_PM_LIMITE)
    marca = b.marca()
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 30, 1, tzinfo=ET))
    tanda = b.desde(marca)
    assert "cerrar_mercado" in {a.datos["decision"] for a in anotaciones(tanda, "halt_decision")}
    abiertas = b.enviadas(Proposito.HALT_OPEN, desde=marca)
    assert [(o.tipo, o.ruta, o.qty) for o in abiertas] == [(TipoOrden.MERCADO, "OPEN", 100)]
    envio = next(i for i, a in enumerate(tanda) if isinstance(a, EnviarOrden) and a.orden.proposito is Proposito.HALT_OPEN)
    cancelado = next(i for i, a in enumerate(tanda) if isinstance(a, Cancelar) and a.token == stop.token)
    assert cancelado < envio and _sin_compra_doble(b, 100)
    b.libro.reabrir(TICKER, D("7.00"))
    b.cotizar(TICKER, "6.95", "7.05", "7.00", tam_ask=1000)
    b.avanzar(3)
    assert not anotaciones(b.desde(marca), "halt_pm_sobre_limite")
    assert b.pos().neta_fills == 0 and b.pos().bs is None and not b.enviadas(Proposito.VENTA_EXCESO)


def test_decision_49_la_compra_al_techo_sin_llenar_en_2_s_se_queda_viva_y_control_humano(cfg: Config,
                                                                                           tmp_path: Path) -> None:
    """Decisión 49 (Jaume 30-sep; antes decisión 46 la retiraba y reponía el stop): la compra al techo que no llena en
    2 s se queda VIVA, el stop NO vuelve (un stop bajo el precio no tiene sentido) y el ticker pasa a CONTROL_HUMANO con
    aviso máximo; /sigue con la posición abierta retira la límite y el stop vuelve por el plan normal."""
    b = _halt_pm_mantener(cfg, tmp_path)
    marca = b.marca()
    b.libro.reabrir(TICKER, D("7.00"))
    b.avanzar(1.2)
    b.cotizar(TICKER, "6.95", "7.05", "7.00", tam_ask=0)                # sin tamaño en el ask: no llena
    (cierre,) = b.enviadas(Proposito.HALT_PM_LIMITE, desde=marca)
    b.avanzar(3)
    assert b.orden(cierre.token).estado is not EstadoOrden.CANCELED
    tanda = b.desde(marca)
    assert any(isinstance(a, Avisar) and a.nivel is Nivel.MAXIMO and a.clave == f"halt_pm_techo_vivo:{TICKER}"
               for a in tanda)
    assert [a for a in anotaciones(tanda, "pausa") if "decisión 49" in str(a.datos.get("motivo"))]
    assert b.pos().estado is EstadoTicker.CONTROL_HUMANO
    assert _vivas_compra(b, *STOPS) == 0 and _vivas_compra(b, Proposito.HALT_PM_LIMITE) == 100
    assert _sin_compra_doble(b, 100) and b.pos().neta_fills == -100 and b.pos().bs is None
    marca = b.marca()
    b.comando(f"/sigue {TICKER}")
    b.avanzar(1)
    assert b.orden(cierre.token).estado is EstadoOrden.CANCELED
    assert _vivas_compra(b, *STOPS) == 100 and _sin_compra_doble(b, 100)
    assert anotaciones(b.desde(marca), "halt_pm_techo_sigue_humano")


def test_e1_06_halt_luld_pide_las_bandas_al_momento(cfg: Config, tmp_path: Path) -> None:
    """E1-06: con TA:P se pide `GET LDLU X` al detectar el halt (clasificar UP/DOWN y recortar los stops), también fuera
    de RTH donde no hay sondeo por minuto."""
    b = _banco_premercado(cfg, tmp_path)
    b.libro.halt(TICKER, "P", "08:00:30")
    marca = b.marca()
    b.avanzar(2)
    assert Consultar(f"GET LDLU {TICKER}") in b.desde(marca)


def test_e1_08_aviso_de_opa_una_vez_al_dia(banco: Banco, monkeypatch: pytest.MonkeyPatch) -> None:
    """E1-08 (R-A-03 v2): con posición, el decisor revisa la banda de OPA con las velas de DAS y el máximo de premercado
    y manda el aviso UNA vez al día por ticker."""
    from app.bot_das.reglas import exclusiones
    llamadas: list[tuple] = []

    def falso(ticker: str, velas: Any, max_pm: Any, cfg_ex: Any) -> Avisar:
        llamadas.append((ticker, max_pm))
        return Avisar(Nivel.AVISO, Grupo.B, f"posible OPA en {ticker}", clave=f"opa:{ticker}")

    monkeypatch.setattr(exclusiones, "aviso_opa", falso)
    b = banco
    abrir_posicion(b)
    for _ in range(3):
        b.cotizar(TICKER, "3.44", "3.46", "3.45")
        b.avanzar(61)
    avisos_opa = [a for a in b.historial if isinstance(a, Avisar) and a.clave == f"opa:{TICKER}"]
    assert len(avisos_opa) == 1 and llamadas and llamadas[0][0] == TICKER


def test_e2_02_el_tope_de_locates_ve_las_compras_en_curso(cfg: Config, tmp_path: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """E2-02: `locates.siguiente_paso` recibe TODOS los locates (el 3 % cuenta lo comprometido por las demás)."""
    from app.bot_das.reglas import locates as mod_locates
    original = mod_locates.siguiente_paso
    vistos: list[Any] = []

    def espia(*args: Any, **kwargs: Any) -> Any:
        vistos.append(kwargs.get("locates"))
        return original(*args, **kwargs)

    monkeypatch.setattr(mod_locates, "siguiente_paso", espia)
    b = Banco(cfg, tmp_path)
    b.preparar(locates=())
    b.procesar(SenalRecibida(Senal(clase="radar", ticker=TICKER, id=None,
                                   estimacion=[{"strategy_id": SID, "acciones": 1000.0, "riesgo_usd": 300.0}],
                                   precio_radar=D("3.45"), recibida_en=b.ahora())))
    assert vistos and all(v is b.estado.locates for v in vistos)


def test_e2_03_el_cierre_humano_en_cisne_negro_pasa_las_esperas(banco: Banco, monkeypatch: pytest.MonkeyPatch) -> None:
    """E2-03: `_t_bs_cierre` pasa `esperas` (la espera del Canceled tiene tope) y la compra sale tras el stop."""
    original = cisne_negro.cierre_humano
    esperas: list[int] = []

    def espia(*args: Any, **kwargs: Any) -> Any:
        esperas.append(kwargs.get("esperas", 0))
        return original(*args, **kwargs)

    monkeypatch.setattr(cisne_negro, "cierre_humano", espia)
    b = banco
    abrir_posicion(b)
    b.cotizar(TICKER, "6.90", "7.10", "7.00")
    b.tic_das()
    b.das_contesta = False                                              # el Canceled del stop aún no llega
    b.comando("/cerrar XYZ SI")
    b.avanzar(0.6)
    b.das_contesta = True
    b.avanzar(1.5)
    assert esperas[:2] == [0, 1]
    assert b.pos().neta_fills == 0


def test_c_02_un_comando_con_el_mismo_id_no_se_ejecuta_dos_veces(banco: Banco) -> None:
    """C-02 (red extra): Telegram reentrega el último update tras un reinicio; «/cerrar X 40 SI» con el MISMO id no cierra
    40 acciones más: se anota y no se contesta."""
    b = banco
    abrir_posicion(b)
    c = comandos.parsear("/cerrar XYZ 40 SI", CHAT, AUTORIZADOS, id_comando="tg:77")
    b.procesar(ComandoRecibido(c))
    b.avanzar(1)
    assert b.pos().neta_fills == -60
    acciones = b.procesar(ComandoRecibido(c))
    b.avanzar(1)
    assert b.pos().neta_fills == -60
    assert anotaciones(acciones, "comando_repetido") and not acciones_de(acciones, Avisar)


def test_g1a_07_g1b_11_e9_sin_locate_propio_entra_con_el_sobrante_o_el_etb(cfg: Config, tmp_path: Path) -> None:
    """G1A-07 / G1B-11 / D1-02 (director): la estrategia SIN locate propio entra con el sobrante de otra (E9) o sin locate
    si el ticker es ETB (antes se descartaba la señal entera «sin acciones»)."""
    from app.bot_das.reglas import locates as mod_locates
    for caso in ("sobrante", "etb"):
        b = Banco(cfg_con(cfg, estrategias=[cfg.estrategias[SID], estrategia_b(cfg)]), tmp_path / caso)
        b.preparar(locates=())
        if caso == "sobrante":
            b.estado.locates[(TICKER, SID)] = Locate(ticker=TICKER, strategy_id=SID, pedidas=300, localizadas=1000,
                                                     usadas=300, estado="Located")
        else:
            b.estado.locates[(TICKER, SID)] = Locate(ticker=TICKER, strategy_id=SID, pedidas=0,
                                                     estado=mod_locates.ESTADO_NO_HACE_FALTA)
        b.simstatus()
        b.senal(evento(strategy_id=SID2, estrategia="PM (B) prueba", acciones=100.0))
        assert [o.qty for o in b.enviadas(Proposito.ENTRADA_AGREGAR)] == [100], caso


def test_g1a_05_sin_respuesta_al_symstatus_en_1_s_la_entrada_sigue(banco: Banco) -> None:
    """G1A-05 (director: «se espera la respuesta, máx. 1 s»): si DAS no contesta al `GET SymStatus X` en 1 s, la entrada
    sigue (el halt lo detecta el sondeo de cada segundo) y se anota."""
    b = banco
    b.das_contesta = False
    acciones = b.senal(evento())
    assert Consultar(f"GET SymStatus {TICKER}") in acciones and not b.enviadas()
    b.avanzar(1.2)
    assert [o.qty for o in b.enviadas(Proposito.ENTRADA_AGREGAR)] == [100]
    assert anotaciones(b.historial, "simstatus_sin_respuesta")
    assert anotaciones(b.historial, "senal")[-1].datos["espera_simstatus"] is True


def test_d2_04_cierre_agotado_sin_confirmar_la_retirada_repone_solo_lo_no_cubierto(banco: Banco) -> None:
    """D2-04 (director): agotado R-D-06, la orden de cierre se RETIRA; si su Canceled no llega en 1 s, los stops vuelven
    por lo que esa orden aún viva NO cubre (aquí nada: nunca dos compras) y, con el Canceled, vuelven enteros."""
    b = banco
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45", tam_ask=0)
    b.comando("/cerrar XYZ SI")
    b.avanzar(5)
    b.das_contesta = False                                              # la retirada no llega a DAS
    marca = b.marca()
    b.avanzar(3)
    assert any(isinstance(a, Avisar) and a.clave == f"cerrar_todo:{TICKER}:agotado" for a in b.desde(marca))
    repuesto = anotaciones(b.desde(marca), "cierre_stops_repuestos")
    assert repuesto and "respaldo" in repuesto[0].datos["motivo"]
    assert not b.enviadas(*STOPS, desde=marca) and _sin_compra_doble(b, 100)
    viva = [o for o in b.estado.ordenes.values() if o.proposito is Proposito.CIERRE_HUMANO
            and o.estado in (EstadoOrden.ACCEPTED, EstadoOrden.SENDING)]
    assert len(viva) == 1
    b.das_contesta = True
    b.dar(b.das.recibir(f"CANCEL {viva[0].id_das}"))
    stops_ = b.enviadas(*STOPS, desde=marca)
    assert sorted((o.proposito.value, o.qty) for o in stops_) == [("stop", 100)]          # stop único (Jaume 29-sep)


# ═══════════════════════════ segunda ronda de correcciones (27-sep) ══════
def _banco_con_banda(cfg: Config, tmp_path: Path) -> Banco:
    """k = 2 (k_max − 1: la banda de R-F-01 está armada) y una posición corta de 100 abierta en RTH, sin bandas aún."""
    from app.bot_das.diario import MemoriaDecisor
    b = Banco(cfg, tmp_path, memoria=MemoriaDecisor(k_halts_up={TICKER: 2}))
    b.preparar()
    abrir_posicion(b)
    return b


def _dar_bandas(b: Banco, ld: str = "3.00", lu: str = "4.05") -> None:
    """Limit up 4,05: por encima del disparo del stop (4,00), que no se recorta ni salta con el precio a 3,91."""
    b.libro.bandas(TICKER, D(ld), D(lu))
    b.dar(b.das.recibir(f"GET LDLU {TICKER}"))
    assert b.mercado.simbolo(TICKER).limit_up == D(lu)


def _enviar_banda(b: Banco) -> OrdenNueva:
    """Con el ask a ≤ 4 % del limit up sale la MKT HALT_BANDA por lo que queda corto; sin tamaño al ask no llena."""
    b.cotizar(TICKER, "3.90", "3.92", "3.91", tam_ask=0)
    banda = b.enviadas(Proposito.HALT_BANDA)
    assert [o.qty for o in banda] == [100]
    assert b.pos().neta_fills == -100
    return banda[0]


def test_r2_dec_1_tp_sin_libres_por_una_halt_banda_viva_se_reprograma_y_cruza_al_retirarla(cfg: Config,
                                                                                           tmp_path: Path) -> None:
    """R2-DEC-1 (G1B-05 parcial, director): el TP sin libro vence con 0 acciones libres (una HALT_BANDA viva cubre toda
    la posición): NO se pierde en silencio: se anota y el MISMO `tp_cruce` se vuelve a mirar cada 0,5 s; al retirarse la
    banda a los 2 s (G1A-01), el cruce del TP sale."""
    b = _banco_con_banda(cfg, tmp_path)
    b.dar([f"$Quote {TICKER} A:3.44 B:3.46 V:500000 L:3.45"])          # libro cruzado: el TP no puede agregar (D2-12)
    acciones = _salida_motor(b, salida())
    assert anotaciones(acciones, "salida_sin_libro")
    clave = next(k for k in b.temporizadores if k.startswith("tp_cruce:"))
    b.avanzar(1)
    _dar_bandas(b)
    banda = _enviar_banda(b)
    marca = b.marca()
    b.avanzar(1.2)                                                      # vence el tp_cruce con la banda viva
    assert not b.enviadas(Proposito.TP_CRUCE)
    sin_libres = anotaciones(b.desde(marca), "salida_sin_libres")
    assert len(sin_libres) == 1 and sin_libres[0].datos["clave"] == clave
    assert sin_libres[0].datos["regla"].startswith("R2-DEC-1")
    assert clave in b.temporizadores and b.temporizadores[clave][0] - b.ahora() <= 0.5 + 1e-9
    b.avanzar(2.5)                                                      # halt_cierre_verificar retira la banda
    assert b.orden(banda.token).estado is EstadoOrden.CANCELED
    cruce = b.enviadas(Proposito.TP_CRUCE)
    assert [(o.qty, o.precio) for o in cruce] == [(50, D("3.92"))]         # al ask, dentro del techo del 3 %
    assert clave not in b.temporizadores
    assert len(anotaciones(b.historial, "salida_sin_libres")) == 1       # una vez por clave, no cada 0,5 s
    assert b.pos().neta_fills == -100


def test_r2_dec_1_sin_libres_60_s_avisa_2_y_sigue_mirando_cada_5_s(cfg: Config, tmp_path: Path) -> None:
    """R2-DEC-1 (tope): si la compra de cierre que deja 0 libres no se retira, a los 60 s reprogramando → Avisar(2) UNA
    vez y se sigue mirando cada 5 s (nunca se compra de más ni se abandona el TP)."""
    b = _banco_con_banda(cfg, tmp_path)
    b.dar([f"$Quote {TICKER} A:3.44 B:3.46 V:500000 L:3.45"])
    _salida_motor(b, salida())
    clave = next(k for k in b.temporizadores if k.startswith("tp_cruce:"))
    b.avanzar(1)
    _dar_bandas(b)
    _enviar_banda(b)
    b.temporizadores.pop(f"halt_cierre_verificar:{TICKER}")             # la banda no se retira (p. ej. DAS no contesta)
    marca = b.marca()
    b.avanzar(59.5)
    assert not [a for a in b.desde(marca) if isinstance(a, Avisar) and (a.clave or "").startswith("sin_libres:")]
    b.avanzar(1.5)
    aviso = [a for a in b.desde(marca) if isinstance(a, Avisar) and a.clave == f"sin_libres:{clave}"]
    assert len(aviso) == 1 and aviso[0].nivel is Nivel.AVISO
    assert round(b.temporizadores[clave][0] - b.ahora(), 3) > 0.5         # ya cada 5 s
    b.avanzar(20)
    assert len([a for a in b.historial if isinstance(a, Avisar) and a.clave == f"sin_libres:{clave}"]) == 1
    programas = [a for a in b.desde(marca) if isinstance(a, Programar) and a.clave == clave]
    assert programas[-1].en_s == 5.0
    assert not b.enviadas(Proposito.TP_CRUCE) and b.pos().neta_fills == -100


def test_r2_dec_1_salida_del_motor_sin_libres_espera_y_sale_al_retirar_la_banda(cfg: Config, tmp_path: Path) -> None:
    """R2-DEC-1: la salida del motor que llega con 0 libres (la HALT_BANDA viva cubre la posición) no se omite: espera
    (se anota) y, retirada la banda, el TP agrega por lo que pide el evento."""
    b = _banco_con_banda(cfg, tmp_path)
    _dar_bandas(b)
    banda = _enviar_banda(b)
    acciones = _salida_motor(b, salida())
    assert not anotaciones(acciones, "salida_omitida") and anotaciones(acciones, "salida_sin_libres")
    assert anotaciones(acciones, "salida_en_espera") and f"salida_espera:{TICKER}" in b.temporizadores
    assert not b.enviadas(Proposito.TP_AGREGAR, Proposito.TP_CRUCE)
    b.cotizar(TICKER, "3.86", "3.92", "3.89", tam_ask=0)                # libro con hueco para agregar
    b.avanzar(2.5)
    assert b.orden(banda.token).estado is EstadoOrden.CANCELED
    assert [o.qty for o in b.enviadas(Proposito.TP_AGREGAR)] == [50]


def test_r2_dec_2_t1_con_last_viejo_y_primer_print_a_300_pct_en_rth_cierra_a_mercado(cfg: Config,
                                                                                     tmp_path: Path) -> None:
    """R2-DEC-2 (E1-02 parcial) tras la decisión 48 (Jaume 30-sep): en SESIÓN el tope del T1 ya no se mira ni al reabrir
    ni en `halt_cierre_verificar`: la salida es una MKT por OPEN, llena en la subasta a +300 % y la cuenta queda plana
    (antes: límite a parada · 3,5 sin llenar → control humano)."""
    from app.bot_das.diario import MemoriaDecisor
    b = Banco(cfg, tmp_path, memoria=MemoriaDecisor(k_halts_up={TICKER: 3}))
    b.preparar()
    _a_halt(b, ta="H", ev=evento(stop=20.0))                           # stops lejos: el salto no es un cisne negro
    salida_halt = b.enviadas(Proposito.HALT_OPEN)
    assert [(o.tipo, o.precio) for o in salida_halt] == [(TipoOrden.MERCADO, None)]
    marca = b.marca()
    b.libro.reabrir(TICKER, D("16.20"))                                 # la subasta a +300 %
    b.avanzar(1.2)
    b.cotizar(TICKER, "16.10", "16.30", "16.20")                        # el primer print real
    b.avanzar(2)
    assert not anotaciones(b.desde(marca), "halt_tope_t1")
    assert b.pos().estado is not EstadoTicker.CONTROL_HUMANO
    assert b.pos().neta_fills == 0 and not b.enviadas(Proposito.VENTA_EXCESO)


def test_r2_dec_2_sin_superar_el_tope_la_verificacion_sigue_como_g1a_01(banco: Banco) -> None:
    """R2-DEC-2: con el primer print por debajo del tope, `halt_cierre_verificar` solo retira la salida que no llenó
    (G1A-01) y el ticker sigue NORMAL."""
    b = banco
    abrir_posicion(b)
    b.libro.llenar_parcial(D("0.5"), TICKER)                            # la subasta solo llenará la mitad
    b.libro.halt(TICKER, "H", "09:27:00")
    b.cotizar(TICKER, "4.04", "4.06", "4.05")
    b.avanzar(1.5)
    salida_halt = b.enviadas(Proposito.HALT_OPEN)[0]
    b.libro.llenar_parcial(D("1"), TICKER)
    marca = b.marca()
    b.libro.reabrir(TICKER, D("5.00"))
    b.avanzar(1.2)
    assert b.temporizadores[f"halt_cierre_verificar:{TICKER}"][2].get("reapertura") is True
    b.cotizar(TICKER, "4.99", "5.01", "5.00", tam_ask=0)                # +23 %: muy por debajo del tope
    b.avanzar(2)
    assert not anotaciones(b.desde(marca), "halt_tope_t1")
    assert anotaciones(b.desde(marca), "halt_salida_retirada")
    assert b.pos().estado is EstadoTicker.NORMAL
    assert b.orden(salida_halt.token).estado is EstadoOrden.CANCELED
    assert b.pos().neta_fills == -50


def test_r2_dec_3_ta_q_sin_t_con_prints_5_s_seguidos_reabre_y_no_vuelve_a_parar(banco: Banco) -> None:
    """R2-DEC-3 (regresión E1-05): Q sigue siendo «parado», pero si DAS se queda en TA:Q y llegan prints nuevos (el
    volumen del $Quote crece) durante 5 s seguidos, se trata como REAPERTURA; los TA:Q repetidos del SymStatus ya no
    vuelven a dejar el ticker en HALT."""
    b = banco
    _a_halt(b, ta="H")
    b.libro.halt(TICKER, "Q", "09:27:00")                               # solo cotización; DAS nunca manda el T
    b.avanzar(1.5)
    assert b.pos().estado is EstadoTicker.HALT and TICKER in b.decisor._halt_en_curso
    marca = b.marca()
    for i in range(1, 4):                                               # 2 s de prints: todavía parado
        b.cotizar(TICKER, "4.04", "4.06", "4.05", volumen=500_000 + 1000 * i)
        b.avanzar(1)
    assert b.pos().estado is EstadoTicker.HALT and not anotaciones(b.desde(marca), "halt_reapertura_por_prints")
    for i in range(4, 8):
        b.cotizar(TICKER, "4.04", "4.06", "4.05", volumen=500_000 + 1000 * i)
        b.avanzar(1)
    assert len(anotaciones(b.desde(marca), "halt_reapertura_por_prints")) == 1
    assert anotaciones(b.desde(marca), "halt_reapertura")
    assert TICKER not in b.decisor._halt_en_curso and b.pos().estado is not EstadoTicker.HALT
    halts_antes = len(anotaciones(b.historial, "halt"))
    b.avanzar(5)                                                        # el SymStatus sigue diciendo Q cada segundo
    assert len(anotaciones(b.historial, "halt")) == halts_antes
    assert b.mercado.simbolo(TICKER).halt_desde is None and b.pos().estado is not EstadoTicker.HALT


def test_r2_dec_4_cancelar_al_tener_id_de_stops_se_cancela_al_llegar_el_accept(banco: Banco,
                                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    """R2-DEC-4 (R2-STOPS-1): `Anotar("cancelar_al_tener_id")` de `stops.verificar_venta_exceso` se registra en el
    cancelar-al-aceptar del decisor: la orden sin id se cancela en cuanto DAS la acepta. Y `_t_exceso_verificar` pasa
    `pedidos_en_vuelo` (un CANCEL ya pedido no se repite)."""
    from app.bot_das.reglas import stops as mod_stops
    b = banco
    abrir_posicion(b)
    b.cotizar(TICKER, "3.40", "3.46", "3.43")
    b.das_contesta = False                                              # la orden sale pero DAS aún no la acepta
    _salida_motor(b, salida(), bombear=False)
    tp = b.enviadas(Proposito.TP_AGREGAR)[0]
    assert b.orden(tp.token).id_das is None
    vistos: list[Any] = []

    def falso(*args: Any, **kwargs: Any) -> list[Accion]:
        vistos.append(kwargs.get("pedidos_en_vuelo"))
        return [Anotar("cancelar_al_tener_id", {"token": tp.token, "ticker": TICKER, "proposito": tp.proposito.value,
                                                "qty": tp.qty, "motivo": "prueba R2-DEC-4", "regla": "R2-STOPS-1"})]

    monkeypatch.setattr(mod_stops, "verificar_venta_exceso", falso)
    b.procesar(Temporizador(f"exceso_verificar:{TICKER}", {"ticker": TICKER, "persecuciones": 0}))
    assert vistos and isinstance(vistos[0], dict)
    assert b.decisor._cancelar_al_aceptar.get(tp.token) == "prueba R2-DEC-4"
    b.das_contesta = True
    marca = b.marca()
    b.dar(b.das.recibir(protocolo.cmd_neworder(tp)))                    # llega el Accept con id
    assert [c.token for c in acciones_de(b.desde(marca), Cancelar)] == [tp.token]
    assert b.orden(tp.token).estado is EstadoOrden.CANCELED


# ═══════════════════════════ ronda 3: R3-DEC-1 / R3-DEC-2 ═════════════════
def _callar_pos(b: Banco, monkeypatch: pytest.MonkeyPatch) -> None:
    """El DAS falso deja de mandar `%POS` (ni por evento ni en GET POSITIONS): la última cifra de DAS queda ATRASADA."""
    recibir, tic = b.das.recibir, b.das.tic
    monkeypatch.setattr(b.das, "recibir", lambda linea: [x for x in recibir(linea) if not x.startswith("%POS")])
    monkeypatch.setattr(b.das, "tic", lambda: [x for x in tic() if not x.startswith("%POS")])


def _cierre_del_bot_con_pos_atrasado(b: Banco, monkeypatch: pytest.MonkeyPatch) -> float:
    """Corto de 100 (fills y DAS −100); 1 s después salta el stop y llena 100 SIN que llegue el %POS nuevo."""
    abrir_posicion(b)
    assert b.pos().neta_das == -100 and b.pos().neta_das_en is not None
    b.avanzar(1)
    b.reloj.avanzar(0.5)                                                # el último %POS (−100) es de hace 0,5 s
    _callar_pos(b, monkeypatch)
    b.cotizar(TICKER, "4.00", "4.05", "4.01")                          # el stop (4,00) llena las 100
    b.tic_das()
    pos = b.pos()
    assert pos.neta_fills == 0 and pos.neta_das == -100                 # el -100 de DAS es de ANTES del fill
    assert pos.ultimo_fill_en == b.ahora() and pos.neta_das_en < pos.ultimo_fill_en
    return b.ahora()


def test_r3_dec_1_cerrar_todo_justo_tras_el_fill_del_cierre_con_pos_atrasado_no_compra(
        banco: Banco, monkeypatch: pytest.MonkeyPatch) -> None:
    """R3-DEC-1 (R3-SAL-1 / D2-02): el decisor apunta `pos.ultimo_fill_en` en cada fill; «/cerrar_todo SI» justo tras el
    fill del cierre del bot, con el %POS aún ATRASADO (−100 de antes del fill), no compra NADA: GET POSITIONS, anota
    «cerrar_todo_das_sin_confirmar» y programa el reintento. Antes compraba 100 y dejaba la cuenta LARGA."""
    b = banco
    _cierre_del_bot_con_pos_atrasado(b, monkeypatch)
    marca = b.marca()
    acciones = b.comando("/cerrar_todo SI")
    assert not b.enviadas(Proposito.CIERRE_HUMANO, desde=marca)
    assert Consultar(protocolo.cmd_get("POSITIONS")) in acciones_de(acciones, Consultar)
    assert anotaciones(acciones, "cerrar_todo_das_sin_confirmar")
    assert b.temporizadores[f"cerrar_todo:{TICKER}"][2]["intento"] == 1
    b.avanzar(10)                                                       # los reintentos, con el %POS aún callado
    assert not b.enviadas(Proposito.CIERRE_HUMANO, desde=marca)
    assert not [o for o in b.enviadas(desde=marca) if o.lado is Lado.COMPRA and o.proposito not in STOPS]
    assert b.pos().neta_fills == 0


def test_r3_dec_1_con_el_pos_posterior_al_fill_cierra_la_manual(banco: Banco, monkeypatch: pytest.MonkeyPatch) -> None:
    """R3-DEC-1 (R3-SAL-1): tras el fill del cierre del bot llega un %POS POSTERIOR (neta_das_en > ultimo_fill_en) con
    −50 que el bot no tiene (Jaume vendió 50 a mano): la cifra está CONFIRMADA y «/cerrar_todo SI» cierra esas 50."""
    b = banco
    _cierre_del_bot_con_pos_atrasado(b, monkeypatch)
    b.reloj.avanzar(0.5)
    b.dar([f"%POS {TICKER} 3 50 4.0100 0 0 0.00 2026/09/25-09:30:05 0.00"])
    pos = b.pos()
    assert pos.neta_das == -50 and pos.neta_das_en > pos.ultimo_fill_en
    b.das_contesta = False
    marca = b.marca()
    acciones = b.comando("/cerrar_todo SI")
    cierres = b.enviadas(Proposito.CIERRE_HUMANO, desde=marca)
    assert [(o.lado, o.qty) for o in cierres] == [(Lado.COMPRA, 50)]
    assert not anotaciones(acciones, "cerrar_todo_das_sin_confirmar")


def test_r3_dec_1_ultimo_fill_en_con_fill_simulado_y_sin_moverlo_un_trade_repetido(banco: Banco) -> None:
    """R3-DEC-1: un fill SIMULADO (sombra) también apunta la hora en `pos.ultimo_fill_en`; un %TRADE repetido (mismo
    id) no es un fill nuevo y no la mueve."""
    b = banco
    abrir_posicion(b)
    stop = b.orden(b.enviadas(Proposito.STOP)[0].token)
    assert b.pos().ultimo_fill_en is not None
    b.reloj.avanzar(1)
    linea = f"%TRADE 9201 {TICKER} B 10 4.00 SAGEREB 09:30:05 {stop.id_das} + 0 0.00"
    b.procesar(DeDAS(b.parser.parsear(linea), simulado=True))
    hora = b.ahora()
    assert b.pos().ultimo_fill_en == hora and b.pos().neta_fills == -90
    b.reloj.avanzar(1)
    b.procesar(DeDAS(b.parser.parsear(linea), simulado=True))
    assert b.pos().ultimo_fill_en == hora and b.pos().neta_fills == -90


def test_r3_dec_2_entrada_sin_id_con_la_cuenta_larga_se_cancela_al_aceptar_y_no_se_repite(cfg: Config,
                                                                                         tmp_path: Path) -> None:
    """R3-DEC-2 (R2-STOPS-1 / D2a-05): la cuenta queda LARGA con una entrada de B aún sin id (Sending):
    `stops.limpieza_tras_fill_stop` la deja en `Anotar("cancelar_al_tener_id")` y el decisor la cancela en cuanto
    llega su Accept con id. Después, `exceso_verificar` (con `pedidos_en_vuelo`) NO repite ese CANCEL en vuelo."""
    b = _dos_estrategias(cfg, tmp_path)
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    _salida_motor(b, salida(acciones=20.0))
    b.cotizar(TICKER, "3.43", "3.45", "3.44")
    lineas = b.das.tic()                                                # el TP de A (compra 3,45) llena 20
    b.das_contesta = False                                              # el REPLACE del stop (100 → 80) queda en vuelo
    b.dar(lineas)
    assert b.pos().neta_fills == -80
    b.cotizar(TICKER, "3.98", "4.00", "3.99")
    b.senal(evento(strategy_id=SID2, estrategia="PM (B) prueba", acciones=50.0, precio=3.99, stop=4.0,
                   distancia_stop=0.01, momento=momento_de(b.reloj.ahora())))       # mismo nivel que A (Jaume 30-sep)
    entradas = [o for o in b.enviadas(Proposito.ENTRADA_AGREGAR, Proposito.ENTRADA_CRUCE)
                if b.orden(o.token).id_das is None]
    assert len(entradas) == 1
    entrada_b = entradas[0]
    b.das_contesta = True
    marca = b.marca()
    b.cotizar(TICKER, "4.58", "4.60", "4.60", tam_bid=0)               # el stop (aún 100 en DAS) llena: larga 20
    b.tic_das()
    assert b.pos().neta_fills == 20
    assert [a.datos["token"] for a in anotaciones(b.desde(marca), "cancelar_al_tener_id")] == [entrada_b.token]
    assert entrada_b.token in b.decisor._cancelar_al_aceptar
    b.cotizar(TICKER, "3.98", "4.00", "3.99", tam_bid=0)               # el libro vuelve: la venta no cruza
    lineas = b.das.recibir(protocolo.cmd_neworder(entrada_b))           # DAS la acepta DESPUÉS del CANCEL ALLSYMB
    b.das_contesta = False                                              # el CANCEL del decisor queda en vuelo
    marca = b.marca()
    b.dar(lineas)
    assert b.orden(entrada_b.token).id_das is not None and b.orden(entrada_b.token).estado is EstadoOrden.ACCEPTED
    assert [c.token for c in acciones_de(b.desde(marca), Cancelar)] == [entrada_b.token]
    assert b.decisor._pedidos_en_vuelo(TICKER).get(entrada_b.token, 0) is None
    _, _, datos = b.temporizadores.pop(f"exceso_verificar:{TICKER}")
    acciones = b.procesar(Temporizador(f"exceso_verificar:{TICKER}", datos))
    assert not [c for c in acciones_de(acciones, Cancelar) if c.token == entrada_b.token]
    assert not [c for c in acciones_de(acciones, CancelarTicker)]


def test_r3_dec_1_la_cifra_de_das_del_volcado_vale_desde_que_se_pidio(banco: Banco,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """R3-DEC-1: cuando la reconciliación (casos 2/3 resueltos por `_plan`) escribe `neta_das` desde el volcado de GET
    POSITIONS, `neta_das_en` pasa a la hora en que se PIDIÓ el volcado (DAS ya conocía todo fill anterior), no se queda
    con la hora de un %POS viejo que confirmaría una cifra de otra época. Con la misma cifra no se toca."""
    from app.bot_das.reglas import reconciliacion as mod_rec
    b = banco
    abrir_posicion(b)
    pos = b.pos()
    b.decisor._stop_bloqueo[(TICKER, Proposito.STOP, D("4"))] = b.ahora() + 3600       # el caso lo resuelve `_plan`
    disc = [mod_rec.Discrepancia(TICKER, mod_rec.CASO_STOP_DIFIERE, "prueba R3-DEC-1", neta_das=-60, neta_fills=-100)]
    monkeypatch.setattr(mod_rec, "comparar", lambda *a, **k: list(disc))
    pedido = b.ahora() - 0.7
    b.decisor._barrido_pedido_en = pedido
    b.reloj.avanzar(1)
    b.procesar(Tic(), bombear=False)                                   # el decisor toma la hora nueva
    b.decisor._reconciliar(({}, {}, {}))
    assert pos.neta_das == -60 and pos.neta_das_en == pedido
    b.decisor._barrido_pedido_en = b.ahora()
    b.decisor._reconciliar(({}, {}, {}))
    assert pos.neta_das == -60 and pos.neta_das_en == pedido            # misma cifra: la hora no se mueve


# ═══════════════ Jaume 29-sep: /pausar X, /sigue X y R-M-03 POR TICKER ═══════════════
def _reconstruir_anotado(b: Banco) -> EstadoBot:
    """Lo que el decisor anotó (solo los `Anotar`), rehecho por `diario.reconstruir` (H-2)."""
    anotados = [a for a in b.historial if isinstance(a, Anotar)]
    registros = [Registro(v=1, seq=i + 1, t="t", proceso="ejecutor", tipo=a.tipo, datos=a_json_seguro(a.datos))
                 for i, a in enumerate(anotados)]
    return reconstruir(registros, HOY)


def _banco_dos_tickers(cfg: Config, tmp_path: Path, reconciliar: bool = True) -> Banco:
    b = Banco(cfg, tmp_path)
    b.preparar(locates=((TICKER, SID, 1000), (OTRO, SID, 1000)),
               cotizaciones=((TICKER, "3.44", "3.46", "3.45"), (OTRO, "3.44", "3.46", "3.45")), reconciliar=reconciliar)
    return b


def _piramide_add(**cambios: Any) -> Evento:
    base = dict(tipo="piramide", ticker=TICKER, strategy_id=SID, estrategia="PM (A) prueba", precio=3.45,
                direccion="Short", acciones=70.0, nivel=1, accion_piramide="add", posicion_total=170.0)
    base.update(cambios)
    return Evento(**base)


def test_pausar_ticker_bloquea_sus_entradas_y_no_las_de_otro(cfg: Config, tmp_path: Path) -> None:
    """Jaume 29-sep: «/pausar X» (dos pasos) → X no abre; Y sí. X sigue NORMAL y no hay pausa global."""
    b = _banco_dos_tickers(cfg, tmp_path)
    acciones = b.comando(f"/pausar {TICKER}")
    assert b.pos().pausado_por_humano is True and b.pos().estado is EstadoTicker.NORMAL
    assert b.estado.pausa_global is False
    assert f"{TICKER}: pausado" in _respuesta(acciones)
    descartada = b.senal(evento())
    assert anotaciones(descartada, "senal_descartada")[0].datos["motivo"] == reglas_entrada.MOTIVO_TICKER_BLOQUEADO
    b.senal(evento(ticker=OTRO))
    assert [o.ticker for o in b.enviadas(Proposito.ENTRADA_AGREGAR)] == [OTRO]
    assert b.decisor.foto()["tickers_pausados_por_humano"] == [TICKER]


def test_pausar_ticker_bloquea_la_piramide_pero_no_los_stops(banco: Banco) -> None:
    """Jaume 29-sep: con X pausado la pirámide «add» no entra; los stops de la posición siguen vivos."""
    b = banco
    abrir_posicion(b)
    b.avanzar(2)
    b.comando(f"/pausar {TICKER}")
    marca = b.marca()
    acciones = b.senal(_piramide_add(momento=otra_vela(b)))
    assert anotaciones(acciones, "senal_descartada")[0].datos["motivo"] == reglas_entrada.MOTIVO_TICKER_BLOQUEADO
    assert not b.enviadas(Proposito.ENTRADA_AGREGAR, desde=marca)
    vivos = [o for o in b.estado.ordenes.values() if o.proposito in STOPS and o.estado not in
             (EstadoOrden.CANCELED, EstadoOrden.CLOSED, EstadoOrden.REJECTED, EstadoOrden.EXECUTED)]
    assert sorted(o.proposito.value for o in vivos) == ["stop"]                          # stop único (Jaume 29-sep)


def test_sigue_ticker_reabre_sus_entradas(cfg: Config, tmp_path: Path) -> None:
    """Jaume 29-sep: «/sigue X» levanta la pausa de X; la siguiente señal de X entra. Y (estricto): una señal que
    llegó DURANTE la pausa ya consumió la única oportunidad del día de esa estrategia en X."""
    b = _banco_dos_tickers(cfg, tmp_path)
    b.comando(f"/pausar {TICKER}")
    b.comando(f"/sigue {TICKER}")
    assert b.pos().pausado_por_humano is False
    b.senal(evento())
    assert [o.ticker for o in b.enviadas(Proposito.ENTRADA_AGREGAR)] == [TICKER]
    b2 = _banco_dos_tickers(cfg, tmp_path / "b2")
    b2.comando(f"/pausar {TICKER}")
    b2.senal(evento())                                   # descartada por la pausa: consume la oportunidad del día
    b2.comando(f"/sigue {TICKER}")
    posterior = b2.senal(evento(momento=otra_vela(b2)))
    assert anotaciones(posterior, "senal_principal_posterior") and not b2.enviadas(Proposito.ENTRADA_AGREGAR)


def test_sigue_sin_ticker_levanta_todas_las_pausas_por_ticker(cfg: Config, tmp_path: Path) -> None:
    """Jaume 29-sep: «/sigue» a secas levanta la pausa global y las de todos los tickers."""
    b = _banco_dos_tickers(cfg, tmp_path)
    b.comando(f"/pausar {TICKER}")
    b.comando(f"/pausar {OTRO}")
    b.comando("/pausar")
    b.comando("/sigue")
    assert (b.estado.pausa_global, b.pos().pausado_por_humano, b.pos(OTRO).pausado_por_humano) == (False, False, False)


def test_pausa_por_ticker_sobrevive_a_la_reconstruccion_del_diario(cfg: Config, tmp_path: Path) -> None:
    """H-2 + Jaume 29-sep: el diario rehace «/pausar X» (y su levantamiento con /sigue X) sin tocar la pausa global."""
    b = _banco_dos_tickers(cfg, tmp_path)
    b.comando(f"/pausar {TICKER}")
    rehecho = _reconstruir_anotado(b)
    assert rehecho.posiciones[TICKER].pausado_por_humano is True and rehecho.pausa_global is False
    assert OTRO not in rehecho.posiciones or rehecho.posiciones[OTRO].pausado_por_humano is False
    b.comando(f"/sigue {TICKER}")
    assert _reconstruir_anotado(b).posiciones[TICKER].pausado_por_humano is False


def test_R_M_03_ajena_en_x_solo_x_al_humano_y_sigue_entrando_y(cfg: Config, tmp_path: Path) -> None:
    """Jaume 29-sep (R-M-03 por ticker): una orden ajena en X pone SOLO X en CONTROL_HUMANO («intervención humana»);
    Y sigue entrando; «/sigue X» devuelve X a NORMAL y su siguiente señal entra. El diario lo rehace."""
    b = Banco(cfg, tmp_path)
    b.das.recibir(f"NEWORDER 12345 SS {TICKER} SAGEREB 100 5.00 TIF=DAY+")                 # la mano humana en X
    b.preparar(locates=((TICKER, SID, 1000), (OTRO, SID, 1000)),
               cotizaciones=((TICKER, "3.44", "3.46", "3.45"), (OTRO, "3.44", "3.46", "3.45")), reconciliar=False)
    marca = b.marca()
    b.avanzar(3)
    assert b.estado.pausa_global is False
    assert b.pos().estado is EstadoTicker.CONTROL_HUMANO and b.pos().intervencion_humana is True
    avisos3 = [a for a in b.desde(marca) if isinstance(a, Avisar) and (a.clave or "").startswith("ajena:")]
    assert avisos3 and f"{TICKER} en manos del humano hasta /sigue {TICKER}" in avisos3[0].texto
    rehecho = _reconstruir_anotado(b)
    assert rehecho.posiciones[TICKER].estado is EstadoTicker.CONTROL_HUMANO and rehecho.pausa_global is False
    momento = momento_de(b.reloj.ahora())
    descartada = b.senal(evento(momento=momento))
    assert anotaciones(descartada, "senal_descartada")[0].datos["motivo"] == reglas_entrada.MOTIVO_TICKER_BLOQUEADO
    b.senal(evento(ticker=OTRO, momento=momento))
    assert [o.ticker for o in b.enviadas(Proposito.ENTRADA_AGREGAR)] == [OTRO]
    b.comando(f"/sigue {TICKER}")
    assert b.pos().estado is EstadoTicker.NORMAL and b.pos().intervencion_humana is False
    assert _reconstruir_anotado(b).posiciones[TICKER].estado is EstadoTicker.NORMAL
    b.avanzar(3)                                         # la misma ajena ya está tratada: no vuelve a pasar al humano
    assert b.pos().estado is EstadoTicker.NORMAL
    posterior = b.senal(evento(momento=otra_vela(b)))   # estricto (Jaume 29-sep): la señal de la pausa consumió el día
    assert anotaciones(posterior, "senal_principal_posterior")
    assert [o.ticker for o in b.enviadas(Proposito.ENTRADA_AGREGAR)] == [OTRO]


def test_R_M_03_sigue_sin_ticker_devuelve_todos_al_bot(cfg: Config, tmp_path: Path) -> None:
    """Jaume 29-sep: «/sigue» a secas devuelve a NORMAL todo ticker en manos del humano por intervención (y el diario
    lo rehace igual); un /control_humano X puesto a mano NO se levanta con él."""
    b = Banco(cfg, tmp_path)
    b.das.recibir(f"NEWORDER 12345 SS {TICKER} SAGEREB 100 5.00 TIF=DAY+")
    b.preparar(locates=((TICKER, SID, 1000), (OTRO, SID, 1000)),
               cotizaciones=((TICKER, "3.44", "3.46", "3.45"), (OTRO, "3.44", "3.46", "3.45")), reconciliar=False)
    b.avanzar(3)
    b.comando(f"/control_humano {OTRO}")
    assert b.pos().estado is EstadoTicker.CONTROL_HUMANO and b.pos(OTRO).estado is EstadoTicker.CONTROL_HUMANO
    b.comando("/sigue")
    assert b.pos().estado is EstadoTicker.NORMAL and b.pos().intervencion_humana is False
    assert b.pos(OTRO).estado is EstadoTicker.CONTROL_HUMANO
    rehecho = _reconstruir_anotado(b)
    assert rehecho.posiciones[TICKER].estado is EstadoTicker.NORMAL
    assert rehecho.posiciones[OTRO].estado is EstadoTicker.CONTROL_HUMANO


# ═══════════════ Jaume 29-sep: locates por FASES enlazados con la señal ═══════════════
def _radar_de(b: Banco, filas: list[dict], ticker: str = TICKER, precio: str = "3.45") -> list[Accion]:
    return b.procesar(SenalRecibida(Senal(clase="radar", ticker=ticker, id=None, estimacion=filas,
                                          precio_radar=D(precio), recibida_en=b.ahora())))


def _fila(acciones: float, sid: str = SID, riesgo: float = 55.0) -> dict:
    return {"strategy_id": sid, "acciones": acciones, "riesgo_usd": riesgo}


def _compras(b: Banco, desde: int = 0) -> list[LocateComprar]:
    return [a for a in b.historial[desde:] if isinstance(a, LocateComprar)]


def _consultas(b: Banco, desde: int = 0) -> list[LocateInquire]:
    return [a for a in b.historial[desde:] if isinstance(a, LocateInquire)]


def _cfg_ventana_larga(cfg: Config) -> Config:
    """La estrategia de ejemplo con la ventana de entradas hasta las 15:00 (la del fixture cierra a las 09:29)."""
    return cfg_con(cfg, estrategias=[dataclasses.replace(cfg.estrategias[SID],
                                                         ventana_entradas=[{"from_time": "04:00", "to_time": "15:00"}])])


def test_fase_A_se_para_al_cerrar_la_ventana_de_entrada(cfg: Config, tmp_path: Path) -> None:
    """Fase A (Jaume 29-sep): el locate que no compensa sigue buscando cada 3 s… hasta que cierra la ventana de
    entrada de la estrategia (09:29 + la vela + la caducidad de 60 s = 09:31:00): entonces PARADO y sin consultas."""
    b = Banco(cfg, tmp_path)
    b.preparar(locates=())
    b.libro.configurar_locate(TICKER, precio=D("0.50"))                  # 14 % de fade: no compensa
    _radar_de(b, [_fila(100.0)])
    b.avanzar(10)
    loc = b.estado.locates[(TICKER, SID)]
    assert (loc.fase, loc.estado) == ("A", "buscando") and len(_consultas(b)) >= 3 and not _compras(b)
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 31, 2, tzinfo=ET))
    loc = b.estado.locates[(TICKER, SID)]
    assert loc.estado == "parado" and "ventana" in [a for a in anotaciones(b.historial, "locate_estado")
                                                    if a.datos.get("estado") == "parado"][-1].datos["motivo"]
    marca = b.marca()
    b.avanzar(10)
    assert not _consultas(b, marca)


def test_fase_A_se_para_al_salir_del_radar(cfg: Config, tmp_path: Path) -> None:
    """Fase A (Jaume 29-sep): sin fila del radar en 30 min (RADAR_VIGENCIA_S) el ticker salió del radar: PARADO."""
    b = Banco(_cfg_ventana_larga(cfg), tmp_path)
    b.preparar(locates=())
    b.libro.configurar_locate(TICKER, precio=D("0.50"))
    _radar_de(b, [_fila(100.0)])
    b.avanzar(4)
    assert b.estado.locates[(TICKER, SID)].estado == "buscando"
    b.decisor._radar[TICKER] -= 1801.0                                   # la última fila fue hace más de 30 min
    b.avanzar(4)
    loc = b.estado.locates[(TICKER, SID)]
    assert loc.estado == "parado"
    assert "salió del radar" in anotaciones(b.historial, "locate_estado")[-1].datos["motivo"]
    marca = b.marca()
    b.avanzar(10)
    assert not _consultas(b, marca)


def test_decision_19_rechazo_de_la_compra_en_fase_A_se_reintenta_y_avisa_una_vez(cfg: Config, tmp_path: Path,
                                                                                    monkeypatch) -> None:
    """Decisión 19 (Jaume 30-sep): la ruta rechaza la compra (Rejected) dos veces en fase A: la pareja NO se para,
    sigue buscando cada 3 s y a la tercera compra; el aviso de nivel 2 sale UNA vez; el cerrojo R-H-02 no salta."""
    original = Emparejador._localizar
    rechazos = {"n": 0}

    def localizar(self, loc, cfg_loc):
        if rechazos["n"] < 2:
            rechazos["n"] += 1
            loc["estado"] = "Rejected"
            return
        original(self, loc, cfg_loc)

    monkeypatch.setattr(Emparejador, "_localizar", localizar)
    b = Banco(_cfg_ventana_larga(cfg), tmp_path)
    b.preparar(locates=())
    _radar_de(b, [_fila(100.0)])
    b.avanzar(1)
    loc = b.estado.locates[(TICKER, SID)]
    assert len(_compras(b)) == 1 and (loc.fase, loc.estado) == ("A", "buscando")
    b.avanzar(10)
    loc = b.estado.locates[(TICKER, SID)]
    assert len(_compras(b)) == 3 and len({c.token for c in _compras(b)}) == 3
    assert (loc.estado, loc.localizadas) == ("Located", 100)
    avisos_rechazo = [a for a in b.historial if isinstance(a, Avisar) and (a.clave or "").startswith("locate_rechazo:")]
    assert len(avisos_rechazo) == 1 and avisos_rechazo[0].nivel is Nivel.AVISO
    assert not b.estado.locates_deshabilitados


def test_decision_21_das_se_queja_del_intervalo_de_inquiry_aviso_una_vez_al_dia(banco: Banco) -> None:
    """Decisión 21 (Jaume 30-sep): la cuota de SLPRICEINQUIRE va por ticker; si DAS la rechaza por su intervalo (en un
    %SLRET 2 o en una línea que el parser no entiende), se anota siempre y se avisa nivel 2 UNA vez al día."""
    from app.bot_das.tipos import MsgDesconocido, MsgSLRet
    b = banco
    marca = b.marca()
    queja = "Price inquiry interval too short"
    b.procesar(DeDAS(MsgSLRet(cruda=f"%SLRET 2 {TICKER} 0 0 LOC3 {queja}", tipo=2, ticker=TICKER, precio=D("0"),
                              tamano=0, ruta="LOC3", notas=queja, cuenta=None)))
    b.procesar(DeDAS(MsgDesconocido(cruda="#ERROR SLPRICEINQUIRE rejected: inquiry rate limit exceeded",
                                    palabra="#ERROR")))
    b.procesar(DeDAS(MsgSLRet(cruda=f"%SLRET 2 {TICKER} 0 0 LOC3 No inventory", tipo=2, ticker=TICKER,
                              precio=D("0"), tamano=0, ruta="LOC3", notas="No inventory", cuenta=None)))
    avisos_cuota = [a for a in b.desde(marca) if isinstance(a, Avisar) and a.clave == "locate_cuota_das"]
    assert len(avisos_cuota) == 1 and avisos_cuota[0].nivel is Nivel.AVISO
    assert "DAS limita las consultas de locate: ¿cuota global?" in avisos_cuota[0].texto
    assert len(anotaciones(b.desde(marca), "locate_cuota_das")) == 2      # «No inventory» no es una queja de cuota


def test_fase_A_recalcula_N_con_el_precio_actual_antes_de_comprar(cfg: Config, tmp_path: Path) -> None:
    """Jaume 29-sep: N (entrada + pirámides al precio actual) se recalcula con cada fila del radar ANTES de comprar."""
    b = Banco(_cfg_ventana_larga(cfg), tmp_path)
    b.preparar(locates=())
    b.libro.configurar_locate(TICKER, precio=D("0.50"))
    _radar_de(b, [_fila(100.0)])
    b.avanzar(1)
    assert b.estado.locates[(TICKER, SID)].pedidas == 100 and not _compras(b)
    _radar_de(b, [_fila(300.0)], precio="3.00")                          # el precio bajó: la fila pide 300
    assert b.estado.locates[(TICKER, SID)].pedidas == 300
    assert anotaciones(b.historial, "locate_estado")[-1].datos["pedidas_n"] == 300
    b.libro.configurar_locate(TICKER, precio=D("0.01"))
    b.avanzar(4)
    assert [c.qty for c in _compras(b)] == [300]


def test_dos_estrategias_en_el_mismo_ticker_cada_una_compra_lo_suyo(cfg: Config, tmp_path: Path) -> None:
    """Jaume 29-sep (transversal): 100 de A + 300 de B en el mismo ticker = 1 + 3 = 4 paquetes, cada uno en su locate."""
    config = cfg_con(cfg, estrategias=[cfg.estrategias[SID], estrategia_b(cfg)])
    b = Banco(config, tmp_path)
    b.preparar(locates=())
    _radar_de(b, [_fila(100.0), _fila(300.0, sid=SID2)])
    b.avanzar(1)
    assert sorted(c.qty for c in _compras(b)) == [100, 300]
    assert sum(c.qty for c in _compras(b)) // 100 == 4
    locs = b.estado.locates
    assert (locs[(TICKER, SID)].localizadas, locs[(TICKER, SID2)].localizadas) == (100, 300)


def test_senal_con_otro_nivel_de_stop_que_los_lotes_vivos_no_entra_y_avisa(cfg: Config, tmp_path: Path) -> None:
    """Jaume 30-sep: un solo nivel de stop por ticker (el stop único aglutina la posición). Con A dentro con stop 4,00,
    una señal de B con stop 4,50 se descarta con aviso y no manda ninguna orden; con el MISMO nivel, entra."""
    config = cfg_con(cfg, estrategias=[cfg.estrategias[SID], estrategia_b(cfg)])
    b = Banco(config, tmp_path)
    b.preparar()
    abrir_posicion(b)                                                   # A: 100 cortas, stop 4,00
    marca = b.marca()
    acciones = b.senal(evento(strategy_id=SID2, stop=4.5, momento=otra_vela(b)))
    assert anotaciones(acciones, "senal_descartada")[0].datos["motivo"] == reglas_entrada.MOTIVO_NIVEL_DISTINTO
    assert any(isinstance(a, Avisar) for a in acciones)
    assert not b.enviadas(Proposito.ENTRADA_AGREGAR, Proposito.ENTRADA_CRUCE, desde=marca)
    b2 = Banco(config, tmp_path / "b2")
    b2.preparar(locates=((TICKER, SID, 1000), (TICKER, SID2, 1000)))
    abrir_posicion(b2)
    marca = b2.marca()
    b2.senal(evento(strategy_id=SID2, stop=4.0, momento=otra_vela(b2)))       # mismo nivel: entra y suma
    assert [o.ticker for o in b2.enviadas(Proposito.ENTRADA_AGREGAR, desde=marca)] == [TICKER]


def test_fase_B1_con_locates_entra_y_pasa_a_C(banco: Banco) -> None:
    """B1: locates ≥ lo pedido → entra (lo de siempre); la pareja queda DENTRO (fase C) y la señal es la primera."""
    b = banco
    b.senal(evento())
    assert [o.qty for o in b.enviadas(Proposito.ENTRADA_AGREGAR)] == [100]
    assert b.estado.locates[(TICKER, SID)].fase == "C"
    assert anotaciones(b.historial, "senal_principal")[0].datos["senal_id"] == lote_de(evento())
    assert b.estado.senales_principales[(TICKER, SID)] == lote_de(evento())


def test_fase_B2_con_parciales_entra_con_lo_localizado_y_pasa_a_C(banco: Banco, cfg: Config, tmp_path: Path) -> None:
    """B2: 60 localizadas de 100 → entra con 60 (sin esperar) y la pareja pasa a C (sigue a por las que faltan)."""
    b = Banco(cfg, tmp_path)
    b.preparar(locates=((TICKER, SID, 60),))
    b.senal(evento())
    assert [o.qty for o in b.enviadas(Proposito.ENTRADA_AGREGAR)] == [60]
    assert b.estado.locates[(TICKER, SID)].fase == "C" and not _consultas(b)


def test_fase_B3_sin_locates_un_intento_que_compra_y_entra(cfg: Config, tmp_path: Path) -> None:
    """B3: sin locates → UN intento en la señal: consulta, compra (a tiro y compensa) y la señal entra con lo comprado."""
    b = Banco(cfg, tmp_path)
    b.preparar(locates=())
    acciones = b.senal(evento())
    assert not b.enviadas(Proposito.ENTRADA_AGREGAR)                    # la señal espera a su locate
    assert [a.datos["fase"] for a in anotaciones(acciones, "locate_estado") if "fase" in a.datos][0] == "B"
    assert [c.qty for c in _consultas(b)] == [100]
    b.avanzar(1)
    assert [c.qty for c in _compras(b)] == [100]
    assert [o.qty for o in b.enviadas(Proposito.ENTRADA_AGREGAR)] == [100]
    loc = b.estado.locates[(TICKER, SID)]
    assert (loc.fase, loc.localizadas, loc.usadas) == ("C", 100, 100)
    assert f"locate_senal:{TICKER}:{SID}" not in b.temporizadores


@pytest.mark.parametrize("como", ["no-a-tiro", "no-compensa"])
def test_fase_B3_sin_compra_pierde_la_entrada_y_para_la_pareja(cfg: Config, tmp_path: Path, como: str) -> None:
    """B3: el intento no compra (el precio cayó más del 3 % desde la señal, o el locate no compensa) → PARADO el día,
    `locate_perdida_entrada` y aviso nivel 2 al grupo B; no se entra."""
    b = Banco(cfg, tmp_path)
    b.preparar(locates=())
    if como == "no-compensa":
        b.libro.configurar_locate(TICKER, precio=D("0.50"))
    b.senal(evento())
    if como == "no-a-tiro":
        b.cotizar(TICKER, "3.29", "3.31", "3.30")                     # 3,30 < 3,45 · 0,97 = 3,3465
    marca = b.marca()
    b.avanzar(1)
    assert not _compras(b) and not b.enviadas(Proposito.ENTRADA_AGREGAR)
    assert b.estado.locates[(TICKER, SID)].estado == "parado"
    tras = b.desde(marca)
    assert anotaciones(tras, "locate_perdida_entrada")
    avisos2 = [a for a in tras if isinstance(a, Avisar) and (a.clave or "").startswith("locate_perdida:")]
    assert avisos2 and avisos2[0].nivel is Nivel.AVISO and avisos2[0].grupo is Grupo.B
    assert lote_de(evento()) in b.estado.senales_vistas


def test_primera_senal_principal_es_la_unica_oportunidad(cfg: Config, tmp_path: Path) -> None:
    """Regla de Jaume (29-sep): tras perder la primera señal por locates, la de la vela siguiente se anota
    `senal_principal_posterior` y NO se opera ni dispara búsqueda (aunque ahora el locate compensara)."""
    b = Banco(cfg, tmp_path)
    b.preparar(locates=())
    b.libro.configurar_locate(TICKER, precio=D("0.50"))
    b.senal(evento())
    b.avanzar(1)
    b.libro.configurar_locate(TICKER, precio=D("0.01"))
    marca = b.marca()
    acciones = b.senal(evento(momento=otra_vela(b)))
    assert anotaciones(acciones, "senal_principal_posterior")
    b.avanzar(5)
    assert not _consultas(b, marca) and not b.enviadas(Proposito.ENTRADA_AGREGAR)
    rehecho = _reconstruir_anotado(b)                               # H-2: la primera señal sobrevive a un reinicio
    assert rehecho.senales_principales[(TICKER, SID)] == lote_de(evento())


def test_primera_senal_descartada_por_retraso_tambien_consume_la_oportunidad(banco: Banco) -> None:
    """Jaume 29-sep (ESTRICTO): la primera señal principal del día consume la oportunidad aunque se descarte antes de
    mirar locates (aquí por retraso, R-A-01): la vela siguiente, con locates y a tiro, tampoco se opera."""
    b = banco
    b.simstatus()
    primera = b.senal(evento(precio=3.20))                              # el último (3,45) está un 7,8 % arriba: tardía
    assert anotaciones(primera, "senal_descartada") and anotaciones(primera, "senal_principal")
    acciones = b.senal(evento(momento=otra_vela(b)))                    # misma estrategia, otra vela, a tiro
    assert anotaciones(acciones, "senal_principal_posterior")
    b.avanzar(3)
    assert not b.enviadas(Proposito.ENTRADA_AGREGAR, Proposito.ENTRADA_CRUCE)


def _salta_el_stop(b: Banco) -> None:
    b.cotizar(TICKER, "4.00", "4.05", "4.01", tam_ask=1000)
    b.tic_das()
    assert b.pos().neta_fills == 0


def test_reentrada_tras_stop_es_legitima_y_reusa_los_locates_fase_D(cfg: Config, tmp_path: Path) -> None:
    """Jaume 29-sep: si se entró y se salió por stop, la reentrada de la estrategia es legítima (no es «señal
    perdida»); cerrada la posición la pareja pasa a D (sin consultas) y la reentrada usa los locates que quedan."""
    b = Banco(cfg, tmp_path)
    b.preparar(locates=((TICKER, SID, 200),))
    abrir_posicion(b)
    _salta_el_stop(b)
    _radar_de(b, [_fila(100.0)])                                     # un paso periódico: C sin lote vivo → D
    assert b.estado.locates[(TICKER, SID)].fase == "D"
    marca = b.marca()
    b.avanzar(5)
    assert not _consultas(b, marca)
    b.cotizar(TICKER, "4.00", "4.02", "4.01")
    acciones = b.senal(evento(precio=4.01, stop=4.6, momento=momento_de(b.reloj.ahora())))
    assert not anotaciones(acciones, "senal_principal_posterior")
    assert [o.qty for o in b.enviadas(Proposito.ENTRADA_AGREGAR)] == [100, 100]
    assert not _compras(b)                                           # quedaban 100 libres: sin comprar nada
    assert b.estado.locates[(TICKER, SID)].fase == "C"


def _abrir_para_piramide(b: Banco, localizadas: int, precio_locate: str = "0.01") -> None:
    b.estado.locates[(TICKER, SID)] = Locate(ticker=TICKER, strategy_id=SID, pedidas=localizadas,
                                             localizadas=localizadas, estado="Located", precio_accion=D(precio_locate))
    abrir_posicion(b)
    b.avanzar(2)


def test_fase_C_piramide_con_tercer_paquete_a_tiempo_entra_entera(cfg: Config, tmp_path: Path) -> None:
    """C: pirámide de 70 con 50 libres (150 localizadas, 100 en la entrada) → UN intento a tiro: el tercer paquete
    compensa (20 · 3,45 · 4 % = 2,76 ≥ 1) → se compra y la pirámide entra con 70."""
    b = Banco(cfg, tmp_path)
    b.preparar(locates=())
    _abrir_para_piramide(b, 150)
    marca = b.marca()
    b.senal(_piramide_add(momento=otra_vela(b)))
    b.avanzar(1)
    assert [c.qty for c in _compras(b, marca)] == [100]
    assert [o.qty for o in b.enviadas(Proposito.ENTRADA_AGREGAR, desde=marca)] == [70]
    assert b.estado.locates[(TICKER, SID)].fase == "C"


def test_fase_C_piramide_parcial_50_de_70_y_la_pareja_queda_parada(cfg: Config, tmp_path: Path) -> None:
    """C: el tercer paquete NO compensa (20 · 3,45 · 4 % = 2,76 < 100 · 0,05) → la pirámide entra con los 50 que hay
    y la pareja queda PARADA el día: la pirámide siguiente entra con lo que quede, sin otro intento."""
    b = Banco(cfg, tmp_path)
    b.preparar(locates=())
    b.libro.configurar_locate(TICKER, precio=D("0.05"))
    _abrir_para_piramide(b, 150, precio_locate="0.05")
    marca = b.marca()
    b.senal(_piramide_add(momento=otra_vela(b)))
    b.avanzar(1)
    assert not _compras(b, marca)
    assert [o.qty for o in b.enviadas(Proposito.ENTRADA_AGREGAR, desde=marca)] == [50]
    assert b.estado.locates[(TICKER, SID)].estado == "parado"
    marca = b.marca()
    b.avanzar(10)
    assert not _consultas(b, marca)


def test_fase_B3_sin_respuesta_de_das_la_espera_vence_y_pierde_la_entrada(cfg: Config, tmp_path: Path) -> None:
    """B3: si DAS no contesta a la consulta, la señal espera como mucho `locates.espera_intento_s` (10 s): la
    pareja queda PARADA, la entrada se pierde (aviso 2) y no se entra más tarde con una respuesta tardía."""
    b = Banco(cfg, tmp_path)
    b.preparar(locates=())
    b.das_contesta = False
    b.senal(evento())
    assert f"locate_senal:{TICKER}:{SID}" in b.temporizadores
    marca = b.marca()
    b.avanzar(8)
    assert not anotaciones(b.desde(marca), "locate_perdida_entrada")       # a los 8 s aún espera
    b.avanzar(3)
    tras = b.desde(marca)
    assert anotaciones(tras, "locate_perdida_entrada")
    assert b.estado.locates[(TICKER, SID)].estado == "parado"
    assert not b.enviadas(Proposito.ENTRADA_AGREGAR)


# ── decisión 47 (Jaume 30-sep): pirámides SIN base cuando la entrada se perdió por locates ──
def _cfg_piramides(cfg: Config, *riesgos: str) -> Config:
    """La estrategia de ejemplo (ventana hasta las 15:00) con un nivel «add» por riesgo: con la entrada de 100 acciones
    y 55 $ de riesgo, 38,5 $ → 70 acciones y 27,5 $ → 50 (la fórmula de `cantidad_a_localizar`)."""
    e = dataclasses.replace(cfg.estrategias[SID], ventana_entradas=[{"from_time": "04:00", "to_time": "15:00"}],
                            niveles_piramide=[{"action": "add"} for _ in riesgos],
                            riesgos_piramide=[D(r) for r in riesgos])
    return cfg_con(cfg, estrategias=[e])


def _perder_entrada_por_locates(cfg: Config, tmp_path: Path, *riesgos: str) -> Banco:
    """B3: sin locates y el locate no compensa (0,50 $/acción) → la entrada se pierde por locates."""
    b = Banco(_cfg_piramides(cfg, *riesgos), tmp_path)
    b.preparar(locates=())
    b.libro.configurar_locate(TICKER, precio=D("0.50"))
    b.senal(evento())
    b.avanzar(1)
    assert anotaciones(b.historial, "locate_perdida_entrada") and not b.enviadas(Proposito.ENTRADA_AGREGAR)
    return b


def test_decision_47_entrada_perdida_por_locates_busca_solo_las_acciones_de_la_piramide(cfg: Config,
                                                                                         tmp_path: Path) -> None:
    """Decisión 47: con una pirámide «add» pendiente la pareja NO queda parada: fase P, guarda el stop (4,00) y el id
    de la entrada perdida, y busca cada 3 s SOLO las 70 de la pirámide (no las 100 de la entrada)."""
    b = _perder_entrada_por_locates(cfg, tmp_path, "38.5")
    loc = b.estado.locates[(TICKER, SID)]
    assert (loc.fase, loc.estado, loc.pedidas) == ("P", "buscando", 70)
    assert (loc.stop_perdida, loc.senal_perdida, loc.piramides_pendientes) == (D("4"), lote_de(evento()), ((0, 70),))
    marca = b.marca()
    b.avanzar(4)
    consultas = anotaciones(b.desde(marca), "locate_inquire")
    assert consultas and all(a.datos["qty_pedida"] == 70 for a in consultas)    # la consulta va en paquetes de 100
    assert not _compras(b, marca)                                        # 0,50 $ no compensa
    b.libro.configurar_locate(TICKER, precio=D("0.01"))
    b.avanzar(4)
    assert [c.qty for c in _compras(b, marca)] == [100]                   # un paquete (R-H-04)


def test_decision_47_con_locates_la_piramide_entra_sin_base_con_el_stop_guardado(cfg: Config, tmp_path: Path) -> None:
    """Decisión 47: conseguidos los locates, la pirámide llega sin lote base → entra como ENTRADA con SUS acciones y
    el nivel de stop de la entrada perdida (4,00); el lote es la base (fase C) y pone su stop al llenar."""
    b = _perder_entrada_por_locates(cfg, tmp_path, "38.5")
    b.libro.configurar_locate(TICKER, precio=D("0.01"))
    b.avanzar(4)
    marca = b.marca()
    acciones = b.senal(_piramide_add(momento=otra_vela(b)))
    assert anotaciones(acciones, "piramide_sin_base")
    (agregar,) = b.enviadas(Proposito.ENTRADA_AGREGAR, desde=marca)
    assert agregar.qty == 70
    lote = b.pos().lotes[lote_de(_piramide_add(momento=momento_de(b.reloj.ahora())))]
    assert (lote.nivel_stop, lote.nivel_piramide, lote.pedidas) == (D("4"), None, 70)
    llenar_entrada(b)
    b.avanzar(2)
    assert b.pos().neta_fills == -70
    assert b.enviadas(*STOPS, desde=marca) and _vivas_compra(b, *STOPS) == 70
    loc = b.estado.locates[(TICKER, SID)]
    assert (loc.fase, loc.stop_perdida, loc.piramides_pendientes) == ("C", None, ())


def test_decision_47_piramide_sin_locates_intento_unico_se_pierde_y_se_descuenta(cfg: Config, tmp_path: Path) -> None:
    """Decisión 47: la pirámide llega sin locates → UN intento (a tiro + compensa, como C_piramide); no compra → se
    pierde ESA pirámide, se descuenta y, sin más pendientes, se deja de buscar."""
    b = _perder_entrada_por_locates(cfg, tmp_path, "38.5")
    marca = b.marca()
    b.senal(_piramide_add(momento=otra_vela(b)))
    b.avanzar(2)
    assert not b.enviadas(Proposito.ENTRADA_AGREGAR, desde=marca) and not _compras(b, marca)
    assert anotaciones(b.desde(marca), "piramide_sin_base_perdida")
    loc = b.estado.locates[(TICKER, SID)]
    assert (loc.fase, loc.estado, loc.piramides_pendientes) == ("P", "parado", ())
    marca = b.marca()
    b.avanzar(10)
    assert not _consultas(b, marca)


def test_decision_47_dos_piramides_la_primera_se_pierde_y_la_segunda_entra(cfg: Config, tmp_path: Path) -> None:
    """Decisión 47: pendientes 70 + 50 → se buscan 120; la primera pirámide se pierde (no compensa) y se descuenta:
    se buscan 50; con locates, la segunda entra sin base con sus 50."""
    b = _perder_entrada_por_locates(cfg, tmp_path, "38.5", "27.5")
    assert b.estado.locates[(TICKER, SID)].pedidas == 120
    b.senal(_piramide_add(momento=otra_vela(b)))
    b.avanzar(2)
    loc = b.estado.locates[(TICKER, SID)]
    assert (loc.fase, loc.estado, loc.pedidas, loc.piramides_pendientes) == ("P", "buscando", 50, ((1, 50),))
    b.libro.configurar_locate(TICKER, precio=D("0.01"))
    marca = b.marca()
    b.avanzar(4)
    assert [c.qty for c in _compras(b, marca)] == [100]
    b.senal(_piramide_add(nivel=2, acciones=50.0, posicion_total=220.0, momento=otra_vela(b)))
    assert [o.qty for o in b.enviadas(Proposito.ENTRADA_AGREGAR, desde=marca)] == [50]


def test_decision_47_salida_total_del_motor_deja_de_buscar_y_la_entrada_siguiente_es_nueva(cfg: Config,
                                                                                          tmp_path: Path) -> None:
    """Decisión 47: el motor sale del todo (el backtest ya salió) → fase D, sin consultas; su siguiente ENTRADA no es
    «señal principal posterior»: se opera como nueva con sus locates y consume una reentrada del cupo."""
    b = _perder_entrada_por_locates(cfg, tmp_path, "38.5")
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    acciones = _salida_motor(b, salida(acciones=100.0, posicion_total=100.0, posicion_restante=0.0))
    assert anotaciones(acciones, "sin_base_fin")
    assert b.estado.locates[(TICKER, SID)].fase == "D"
    marca = b.marca()
    b.avanzar(5)
    assert not _consultas(b, marca)
    b.libro.configurar_locate(TICKER, precio=D("0.01"))
    nueva = evento(momento=otra_vela(b))
    acciones = b.senal(nueva)
    assert not anotaciones(acciones, "senal_principal_posterior")
    b.avanzar(1)
    assert [c.qty for c in _compras(b, marca)] and [o.qty for o in b.enviadas(Proposito.ENTRADA_AGREGAR,
                                                                                desde=marca)] == [100]
    assert b.pos().lotes[lote_de(nueva)].reentrada_n == 1


def test_decision_47_salida_total_con_el_cupo_agotado_descarta_la_reentrada(cfg: Config, tmp_path: Path) -> None:
    """Decisión 47 (lo conservador): la entrada perdida cuenta en el cupo; con reentradas apagadas la entrada siguiente
    del motor se descarta."""
    config = _cfg_piramides(cfg, "38.5")
    config = cfg_con(config, estrategias=[dataclasses.replace(config.estrategias[SID], accept_reentries=False)])
    b = Banco(config, tmp_path)
    b.preparar(locates=())
    b.libro.configurar_locate(TICKER, precio=D("0.50"))
    b.senal(evento())
    b.avanzar(1)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    _salida_motor(b, salida(acciones=100.0, posicion_total=100.0, posicion_restante=0.0))
    b.libro.configurar_locate(TICKER, precio=D("0.01"))
    marca = b.marca()
    acciones = b.senal(evento(momento=otra_vela(b)))
    assert anotaciones(acciones, "senal_descartada")
    b.avanzar(2)
    assert not b.enviadas(Proposito.ENTRADA_AGREGAR, desde=marca) and not _compras(b, marca)


def test_decision_47_entrada_perdida_por_retraso_no_abre_el_camino(cfg: Config, tmp_path: Path) -> None:
    """Decisión 47 (e): una entrada perdida por OTRO motivo (retraso, R-A-01) no abre la fase P: la pirámide sin base se
    descarta como siempre (A12) y no se buscan locates para ella."""
    b = Banco(_cfg_piramides(cfg, "38.5"), tmp_path)
    b.preparar(locates=())
    b.simstatus()
    primera = b.senal(evento(precio=3.20))                              # tardía: descartada por retraso
    assert anotaciones(primera, "senal_descartada") and not anotaciones(primera, "sin_base_abierta")
    loc = b.estado.locates.get((TICKER, SID))
    assert loc is None or loc.fase != "P"
    marca = b.marca()
    acciones = b.senal(_piramide_add(momento=otra_vela(b)))
    assert not anotaciones(acciones, "piramide_sin_base")
    b.avanzar(2)
    assert not b.enviadas(Proposito.ENTRADA_AGREGAR, desde=marca) and not _compras(b, marca)


def test_decision_47_el_diario_conserva_el_stop_guardado_y_la_fase(cfg: Config, tmp_path: Path) -> None:
    """Decisión 47 (H-2): la fase P, el stop guardado, la señal perdida y las pirámides pendientes sobreviven a un
    reinicio (`diario.reconstruir` con lo anotado)."""
    b = _perder_entrada_por_locates(cfg, tmp_path, "38.5", "27.5")
    b.senal(_piramide_add(momento=otra_vela(b)))
    b.avanzar(2)
    rehecho = _reconstruir_anotado(b).locates[(TICKER, SID)]
    vivo = b.estado.locates[(TICKER, SID)]
    assert (rehecho.fase, rehecho.stop_perdida, rehecho.senal_perdida, tuple(rehecho.piramides_pendientes)) == (
        "P", D("4"), lote_de(evento()), ((1, 50),))
    assert (rehecho.fase, rehecho.stop_perdida, rehecho.senal_perdida, rehecho.pedidas) == (
        vivo.fase, vivo.stop_perdida, vivo.senal_perdida, vivo.pedidas)


def test_ticker_pausado_no_gasta_en_locates_hasta_sigue(cfg: Config, tmp_path: Path) -> None:
    """Jaume 29-sep (lo conservador): con «/pausar X» el radar de X no consulta ni compra locates; tras «/sigue X» la
    siguiente fila del radar vuelve a buscar."""
    b = Banco(_cfg_ventana_larga(cfg), tmp_path)
    b.preparar(locates=())
    b.comando(f"/pausar {TICKER}")
    _radar_de(b, [_fila(100.0)])
    b.avanzar(4)
    assert not _consultas(b) and not _compras(b)
    b.comando(f"/sigue {TICKER}")
    _radar_de(b, [_fila(100.0)])
    b.avanzar(1)
    assert [c.qty for c in _compras(b)] == [100]


def test_ticker_que_das_no_cotiza_no_gasta_en_locates_hasta_que_cotiza(cfg: Config, tmp_path: Path) -> None:
    """Jaume 1-oct (A7): un ticker del radar que DAS no devuelve (no contratado) no consulta ni compra locates, ni en
    los 5 s previos al SIN_SIMBOLO ni después, por muchas filas del radar que lleguen; cuando DAS lo cotiza, busca."""
    b = Banco(_cfg_ventana_larga(cfg), tmp_path)
    b.preparar(locates=())

    def radar() -> None:
        b.procesar(SenalRecibida(Senal(clase="radar", ticker="ZZZ", id=None, precio_radar=D("3.45"),
                                       estimacion=[_fila(100.0)], recibida_en=b.ahora())))
    for _ in range(4):
        radar()
        b.avanzar(3)
    assert b.estado.posiciones["ZZZ"].estado is EstadoTicker.SIN_SIMBOLO
    assert not [c for c in _consultas(b) if c.ticker == "ZZZ"] and not [c for c in _compras(b) if c.ticker == "ZZZ"]
    b.cotizar("ZZZ", "3.44", "3.46", "3.45")
    radar()
    b.avanzar(1)
    assert b.estado.posiciones["ZZZ"].estado is EstadoTicker.NORMAL
    assert [c for c in _consultas(b) + _compras(b) if c.ticker == "ZZZ"]


# ── D8 (Jaume 30-sep): las salidas parciales van por PROPORCIÓN de nuestra posición ──
def _abrir_60(b: Banco) -> None:
    """Entramos con 60 (nuestro tamaño) aunque el backtest vaya con 100."""
    b.senal(evento(acciones=60.0))
    llenar_entrada(b)
    assert b.pos().neta_fills == -60


def test_D8_backtest_cierra_25_de_100_nosotros_15_de_60(banco: Banco) -> None:
    """D8 (Jaume 30-sep): el TP del backtest cierra 25 de sus 100 (quedan 75) → el bot cierra el 25 % de sus 60 = 15,
    no las 25 literales; el diario lo anota como «proporcion»."""
    b = banco
    _abrir_60(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    acciones = _salida_motor(b, salida(acciones=25.0, posicion_total=100.0, posicion_restante=75.0))
    tp = [a.orden for a in acciones if isinstance(a, EnviarOrden)]
    assert [(o.proposito, o.qty) for o in tp] == [(Proposito.TP_AGREGAR, 15)]
    nota = anotaciones(acciones, "salida_proporcion")[0].datos
    assert (nota["modo"], nota["fraccion_backtest"], nota["total_backtest"], nota["qty"]) == (
        "proporcion", D("0.25"), False, 15)


def test_D8_tres_parciales_25_50_25_dejan_la_posicion_a_cero(banco: Banco) -> None:
    """D8: los tres tramos de 1B (25/50/25 % sobre 100) con 60 nuestras → 15, 30 y el resto (15): posición a 0."""
    b = banco
    _abrir_60(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    tramos = [(25.0, 75.0, "09:31:00"), (50.0, 25.0, "09:32:00"), (25.0, 0.0, "09:33:00")]
    pedidas = []
    for acciones_ev, restante, hora in tramos:
        marca = b.marca()
        _salida_motor(b, salida(acciones=acciones_ev, posicion_total=100.0, posicion_restante=restante,
                                momento=pd.Timestamp(f"2026-09-25 {hora}")))
        pedidas += [o.qty for o in b.enviadas(Proposito.TP_AGREGAR, desde=marca)]
        b.avanzar(61)                                                      # el resto cruza y llena
    assert pedidas == [15, 30, 15]
    assert b.pos().neta_fills == 0


def test_D8_sin_proporcion_conocida_cierra_las_acciones_literales(banco: Banco) -> None:
    """D8: un evento sin `posicion_restante` no permite conocer la proporción → las 25 del evento (tope: lo que hay),
    como antes, y el diario lo anota como «literal»."""
    b = banco
    _abrir_60(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    acciones = _salida_motor(b, salida(acciones=25.0))
    assert [o.qty for o in (a.orden for a in acciones if isinstance(a, EnviarOrden))] == [25]
    nota = anotaciones(acciones, "salida_proporcion")[0].datos
    assert nota["modo"] == "literal" and nota["fraccion_backtest"] is None


def _abrir_con_piramide(b: Banco, base: int, piramide: int) -> tuple[str, str]:
    """D8: entrada de `base` + pirámide «add» de `piramide` (mismo SID) llenas; devuelve (lote base, lote pirámide)."""
    b.senal(evento(acciones=float(base)))
    llenar_entrada(b)
    b.avanzar(2)
    b.senal(_piramide_add(acciones=float(piramide), posicion_total=float(base + piramide), momento=otra_vela(b)))
    llenar_entrada(b)
    b.avanzar(1)
    assert b.pos().neta_fills == -(base + piramide)
    lotes = sorted(b.pos().lotes.values(), key=lambda x: x.nivel_piramide is not None)
    assert [(x.nivel_piramide is None, x.llenas) for x in lotes] == [(True, base), (False, piramide)]
    return lotes[0].id, lotes[1].id


def test_D8_base_100_piramide_50_el_25_por_ciento_son_38_repartidas(banco: Banco) -> None:
    """D8 (Jaume 30-sep: «el 25 % de la posición que tengamos»): base 100 + pirámide 50 y el backtest cierra el 25 % de
    su posición → 38 en total (redondeo de 37,5), una orden por lote: 25 + 12 = 37 proporcional y el resto al base
    (26 + 12). Antes se cerraban 25 del base y la pirámide quedaba entera hasta el EOD."""
    b = banco
    base, pir = _abrir_con_piramide(b, 100, 50)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    marca = b.marca()
    _salida_motor(b, salida(acciones=37.5, posicion_total=150.0, posicion_restante=112.5))
    tp = b.enviadas(Proposito.TP_AGREGAR, desde=marca)
    assert sorted((o.lote_id, o.qty) for o in tp) == sorted([(base, 26), (pir, 12)])
    assert sum(o.qty for o in tp) == 38


def test_D8_base_60_piramide_30_tres_parciales_dejan_todos_los_lotes_a_cero(banco: Banco) -> None:
    """D8: nosotros base 60 + pirámide 30 (backtest 100 + 50); tramos 25/50/25 % → 23, 45 y 22 (suma 90) y todos los
    lotes de la estrategia quedan a 0."""
    b = banco
    base, pir = _abrir_con_piramide(b, 60, 30)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    tramos = [(37.5, 112.5, "09:31:00"), (75.0, 37.5, "09:32:00"), (37.5, 0.0, "09:33:00")]
    totales = []
    for acciones_ev, restante, hora in tramos:
        marca = b.marca()
        _salida_motor(b, salida(acciones=acciones_ev, posicion_total=150.0, posicion_restante=restante,
                                momento=pd.Timestamp(f"2026-09-25 {hora}")))
        totales.append(sum(o.qty for o in b.enviadas(Proposito.TP_AGREGAR, desde=marca)))
        b.avanzar(61)
    assert totales == [23, 45, 22]
    assert b.pos().neta_fills == 0
    assert b.pos().lotes[base].llenas == 0 and b.pos().lotes[pir].llenas == 0


def _tp_de_lote(resto: float, hora: str, **cambios: Any) -> Evento:
    base = dict(tipo="piramide", ticker=TICKER, strategy_id=SID, estrategia="PM (A) prueba", precio=3.30,
                direccion="Short", acciones=30.0, nivel=1, accion_piramide="lot_tp", posicion_total=100.0 + resto,
                momento=pd.Timestamp(f"2026-09-25 {hora}"), fraccion_lote=1 / 3, tamano_lote_backtest=90.0,
                resto_lote_backtest=resto)
    base.update(cambios)
    return Evento(**base)


def test_tp_de_lote_nuestro_60_backtest_90_cierra_20_20_y_el_resto(banco: Banco) -> None:
    """Jaume 30-sep: TP de lote en tres peldaños del 33 % (30/30/30 de un lote de 90 del backtest) → sobre NUESTRO lote
    de pirámide de 60: 20, 20 y el resto (20), solo de ese lote; el base no se toca."""
    b = banco
    base, pir = _abrir_con_piramide(b, 100, 60)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    pedidas = []
    for resto, hora in ((60.0, "09:31:00"), (30.0, "09:32:00"), (0.0, "09:33:00")):
        marca = b.marca()
        acciones = _salida_motor(b, _tp_de_lote(resto, hora))
        enviadas = b.enviadas(Proposito.TP_AGREGAR, desde=marca)
        assert {o.lote_id for o in enviadas} <= {pir}
        pedidas += [o.qty for o in enviadas]
        nota = anotaciones(acciones, "salida_proporcion")[0].datos
        assert nota["modo"] == "proporcion"
        b.avanzar(61)
    assert pedidas == [20, 20, 20]
    assert b.pos().lotes[pir].llenas == 0 and b.pos().lotes[base].llenas == 100


def test_tp_de_lote_sin_fraccion_sigue_literal(banco: Banco) -> None:
    """Un TP de lote SIN `fraccion_lote` (motor viejo) → las acciones literales del evento, como antes."""
    b = banco
    _base, pir = _abrir_con_piramide(b, 100, 60)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    marca = b.marca()
    acciones = _salida_motor(b, _tp_de_lote(60.0, "09:31:00", fraccion_lote=None, resto_lote_backtest=None))
    assert [(o.lote_id, o.qty) for o in b.enviadas(Proposito.TP_AGREGAR, desde=marca)] == [(pir, 30)]
    assert anotaciones(acciones, "salida_proporcion")[0].datos["modo"] == "literal"
