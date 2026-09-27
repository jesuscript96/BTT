"""Tests del decisor (lote G1): los flujos F1-F14 de §5 contra un DAS falso, con reloj simulado y sin red.

QUÉ PRUEBA. El decisor de verdad (`app.bot_das.decisor.Decisor`) con TODAS sus
piezas reales: `MercadoDAS` alimentado con `$Quote`, `Referencia` de Massive
con un `abrir` falso (fichas y splits en memoria), el catálogo de rechazos
real y el `Emparejador` del simulador como DAS (cada acción del decisor se
serializa con `protocolo.cmd_*`, el Emparejador contesta con líneas de DAS y
esas líneas vuelven al decisor parseadas por `protocolo.Parser`, como hará el
ejecutor). Flujo a flujo: F1 exacto, las seis permutaciones de
`%OrderAct`/`%TRADE`/`%POS`, F2 (parcial del principal: se venden 20, nunca
100), F3 (dos señales con el intento vivo), F4 (TP con prioridad sobre la
entrada), F5 (hora y EOD con persecución y control humano), F6 (halt con la
guardia de la MKT), F7 (cisne negro, informes y cierre humano), F8
(rechazos), F9 (locates de dos estrategias), F10 (los seis casos de la
reconciliación), F11 (modos degradados), F12/F13 (arranque desde el diario)
y F14 (estrategia desactivada). Y las trampas: H-5, señal repetida,
multicuenta, largo con corto abierto, config en caliente, fill con un
REPLACE pendiente, grupo A primero, comandos de R-M-04 y la coherencia con
`diario.reconstruir` (H-2).

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
    Grupo,
    HiloCaido,
    InvalidarSerie,
    Lado,
    Locate,
    LocateComprar,
    LocateInquire,
    LocateOferta,
    Lote,
    Mensaje,
    Nivel,
    Orden,
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
STOPS = (Proposito.STOP_PRINCIPAL, Proposito.STOP_EMERGENCIA, Proposito.STOP_PROTECCION)


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
                 replace_conserva_pp: bool = True, latidos: bool = True, inicio: datetime = INICIO) -> None:
        self.reloj = RelojSimulado(inicio)
        self.hoy = self.reloj.hoy()
        self.libro = LibroSimulado()
        self.das = Emparejador(self.libro, self.reloj, orden_mensajes=tuple(orden_mensajes),
                               replace_conserva_pp=replace_conserva_pp)
        self.parser = protocolo.Parser(lambda t: es_nuestro(t, self.hoy), cuenta=CUENTA)
        self.canal = CanalFalso()
        self.mercado = MercadoDAS(self.reloj)
        self.massive = massive if massive is not None else MassiveFalso()
        self.referencia = Referencia(CLAVE_MASSIVE, directorio / "cache", self.reloj, abrir=self.massive)
        self.estado = estado if estado is not None else EstadoBot(fase=Fase.SOMBRA, dia=self.hoy)
        self.tokens = GeneradorTokens(Origen.EJECUTOR, self.hoy, self.estado.ultimo_seq_token)
        self.disco_roto = False
        self.decisor = Decisor(cfg, self.estado, self.mercado, self.referencia, self.tokens,
                               rechazos.cargar_catalogo(rechazos.RUTA_CATALOGO), lambda: self.disco_roto,
                               calendario=CalendarioPrueba())
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

    # ── reloj y cola ──
    def ahora(self) -> float:
        return self.reloj.mono()

    def procesar(self, msg: Mensaje, bombear: bool = True) -> list[Accion]:
        acciones = self.decisor.procesar(msg, self.reloj.mono(), self.reloj.ahora())
        self.historial.extend(acciones)
        for a in acciones:
            self._ejecutar(a)
        if bombear:
            self.bombear()
        return acciones

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
        for ticker, sid, n in locates:
            self.estado.locates[(ticker, sid)] = Locate(ticker=ticker, strategy_id=sid, pedidas=n, localizadas=n,
                                                        estado="Located")
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
    """F1 (R-B-01 v3, R-C-01 v3, F1.9): la señal, el fill y el cierre del intento con sus acciones EXACTAS y en orden."""
    b = banco
    ev = evento()
    lote_id = lote_de(ev)
    acciones = b.senal(ev, bombear=False)
    assert [resumen(a) for a in acciones] == [
        ("Anotar", "senal"),
        ("Anotar", "lote"),
        ("Anotar", "locate_estado"),
        ("Anotar", "metrica"),
        ("Anotar", "intento"),
        ("EnviarOrden", "SS", "LMT", 100, D("3.45"), None, "entrada_agregar", "SAGEREB", True, None),
        ("Programar", T_CRUCE, 60.0),
        ("Anotar", "metrica"),
    ]
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
        ("EnviarOrden", "B", "STOPLMTP", 100, D("4.12"), D("4.00"), "stop_principal", "STOP", False, "stops:XYZ"),
        ("EnviarOrden", "B", "STOPLMTP", 100, D("6.52"), D("4.52"), "stop_emergencia", "STOP", False, "stops:XYZ"),
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
    principal, emergencia = b.enviadas(*STOPS)
    assert b.orden(principal.token).estado is EstadoOrden.ACCEPTED
    assert b.orden(emergencia.token).estado is EstadoOrden.ACCEPTED
    assert all(isinstance(a.datos.get("mono"), float) for a in anotaciones(b.historial, "fill"))
    assert b.canal.series_invalidadas == [("stops:XYZ", 1)]
    lineas_stop = [(linea, serie, version) for linea, serie, version in b.canal.lineas if "STOPLMTP" in linea]
    assert lineas_stop == [(f"NEWORDER {principal.token} B XYZ STOP 100 STOPLMTP 4 4.12 TIF=DAY+", "stops:XYZ", 1),
                           (f"NEWORDER {emergencia.token} B XYZ STOP 100 STOPLMTP 4.52 6.52 TIF=DAY+", "stops:XYZ", 1)]


@pytest.mark.parametrize("orden_mensajes", PERMUTACIONES, ids=["-".join(p) for p in PERMUTACIONES])
def test_f1_permutaciones_orderact_trade_pos(cfg: Config, tmp_path: Path, orden_mensajes: tuple) -> None:
    """Riesgo 8 / corrección 2: en cualquier orden de Execute, %TRADE y %POS, UN fill, UN principal y UNA emergencia."""
    b = Banco(cfg, tmp_path, orden_mensajes=orden_mensajes)
    b.preparar()
    abrir_posicion(b)
    agregar = b.enviadas(Proposito.ENTRADA_AGREGAR)[0]
    assert len(b.estado.fills[agregar.token]) == 1
    assert b.estado.fills[agregar.token][0].id_trade == 5001            # el eco del Execute se completa con el id real
    contados = [a.datos for a in anotaciones(b.historial, "fill") if a.datos["id_trade"] is not None]
    assert len(contados) == 1                                           # lo que `reconstruir` cuenta: una vez
    assert [o.proposito for o in b.enviadas(*STOPS)] == [Proposito.STOP_PRINCIPAL, Proposito.STOP_EMERGENCIA]
    assert all(o.qty == 100 for o in b.enviadas(*STOPS))
    assert b.pos().neta_fills == -100 and b.pos().neta_das == -100 and b.pos().version_stops == 1
    assert b.pos().intento is None
    b.avanzar(3)
    assert len(b.enviadas(*STOPS)) == 2                                 # el barrido tampoco duplica


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
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 30, 59, tzinfo=ET))
    b.das_contesta = False                                              # la cancelación no llega al DAS falso
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 31, 0, 200_000, tzinfo=ET))
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
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 31, 0, 500_000, tzinfo=ET))
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
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 30, 59, tzinfo=ET))
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
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 30, 59, tzinfo=ET))
    b.das_contesta = False
    b.avanzar_hasta(datetime(2026, 9, 25, 9, 31, 4, tzinfo=ET))
    lote_id = lote_de(evento())
    assert b.pos().intento is None and b.pos().lotes[lote_id].estado is EstadoLote.CANCELADO
    assert any(isinstance(a, Avisar) and a.clave == f"cancel_sin_confirmar:{TICKER}" for a in b.historial)
    b.das_contesta = True
    marca = b.marca()
    b.dar([_linea_act("Execute", agregar, id_das, 100, "3.45")])
    lote = b.pos().lotes[lote_id]
    assert (lote.estado, lote.llenas) == (EstadoLote.ABIERTO, 100)
    assert sorted(o.proposito.value for o in b.enviadas(*STOPS, desde=marca)) == ["stop_emergencia", "stop_principal"]
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
    """R-C-04 / F2.6: DAS cancela la emergencia sin que el bot lo pida → aviso 2 y el plan la repone al momento."""
    b = banco
    abrir_posicion(b)
    emergencia = b.enviadas(Proposito.STOP_EMERGENCIA)[0]
    marca = b.marca()
    b.dar(b.das.recibir(f"CANCEL {b.orden(emergencia.token).id_das}"))
    aviso = [a for a in b.desde(marca) if isinstance(a, Avisar) and (a.clave or "").startswith(f"stop_cancelado:{TICKER}")]
    assert len(aviso) == 1 and aviso[0].nivel is Nivel.AVISO
    assert [(o.qty, o.stop, o.precio) for o in b.enviadas(Proposito.STOP_EMERGENCIA, desde=marca)] == \
           [(100, D("4.52"), D("6.52"))]


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
    assert sorted(r.qty for r in acciones_de(b.historial, Reemplazar)) == [50, 50]
    marca = b.marca()
    b.avanzar(1.5)
    repuestos = anotaciones(b.desde(marca), "replace_sin_pp")
    assert len(repuestos) == 2 and all(a.datos["tipo_das_crudo"].startswith("SL:") for a in repuestos)
    nuevos = b.enviadas(*STOPS, desde=marca)
    assert sorted((o.proposito.value, o.qty) for o in nuevos) == [("stop_emergencia", 50), ("stop_principal", 50)]
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


# ═══════════════════════════ F2: parcial del principal ═══════════════════
@pytest.mark.parametrize("orden_mensajes", PERMUTACIONES, ids=["F2-" + "-".join(p) for p in PERMUTACIONES])
def test_f2_principal_parcial_reemplaza_la_emergencia_y_nunca_vende_de_mas(cfg: Config, tmp_path: Path,
                                                                           orden_mensajes: tuple) -> None:
    """F2.3 / R-C-11: el principal llena 20 → emergencia a 80; si la emergencia llena 100 antes del REPLACE → se venden 20.

    En las seis permutaciones: con `%POS` detrás del fill el plan ESPERA a que DAS cuadre (corrección 2) y replanifica
    en cuanto llega; con `%POS` delante, planifica al momento. El resultado es el mismo.
    """
    b = Banco(cfg, tmp_path, orden_mensajes=orden_mensajes)
    b.preparar()
    abrir_posicion(b)
    principal, emergencia = b.enviadas(*STOPS)
    b.cotizar(TICKER, "4.00", "4.05", "4.01", tam_ask=20)
    b.das_contesta = False                          # el REPLACE y la cancelación quedan en vuelo (carrera de riesgo 8)
    marca = b.marca()
    b.das_contesta = True
    lineas = b.das.tic()                            # el principal se dispara y llena 20 a 4,05
    b.das_contesta = False
    b.dar(lineas)
    tras_parcial = b.desde(marca)
    assert b.pos().neta_fills == -80
    reemplazos = acciones_de(tras_parcial, Reemplazar)
    assert [(r.token, r.qty, r.stop, r.precio) for r in reemplazos] == [(emergencia.token, 80, D("4.52"), D("6.52"))]
    assert principal.token in [c.token for c in acciones_de(tras_parcial, Cancelar)]
    invalidar = acciones_de(tras_parcial, InvalidarSerie)
    assert invalidar and tras_parcial.index(invalidar[0]) < tras_parcial.index(reemplazos[0])
    assert reemplazos[0].version == invalidar[0].version == b.pos().version_stops
    assert all(lote.principal_consumido for lote in b.pos().lotes.values())

    b.das_contesta = True                           # la emergencia (aún de 100 en DAS) llena 100 de golpe
    marca = b.marca()
    b.cotizar(TICKER, "4.58", "4.60", "4.60")
    b.tic_das()
    ventas = b.enviadas(Proposito.VENTA_EXCESO, desde=marca)
    assert b.pos().neta_fills == 0 and b.pos().neta_das == 0      # +20 largo… y la venta del exceso lo deja plano
    assert [(v.lado, v.qty) for v in ventas] == [(Lado.VENTA, 20)]
    assert not [o for o in b.enviadas(desde=marca) if o.lado is Lado.VENTA and o.qty == 100]
    assert anotaciones(b.desde(marca), "incidente")[0].datos["tipo"] == "cuenta_larga"


# ═══════════════════════════ F3: dos señales con el intento vivo ═════════
def test_f3_segunda_senal_suma_y_reinicia_con_el_total(cfg: Config, tmp_path: Path) -> None:
    """F3 / R-B-03: la segunda estrategia SUMA; tras el Canceled se reagrega el total con el MISMO t_limite; dos principales."""
    config = cfg_con(cfg, estrategias=[cfg.estrategias[SID], estrategia_b(cfg)])
    b = Banco(config, tmp_path)
    b.preparar(locates=((TICKER, SID, 1000), (TICKER, SID2, 1000)))
    ev_a = evento()
    b.senal(ev_a)
    limite = b.temporizadores[f"cruce:{TICKER}"][0]
    primera = b.enviadas(Proposito.ENTRADA_AGREGAR)[0]
    b.avanzar(2)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    ev_b = evento(strategy_id=SID2, estrategia="PM (B) prueba", acciones=50.0, stop=4.2)
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
    principales = sorted((o.stop, o.qty) for o in stops_ if o.proposito is Proposito.STOP_PRINCIPAL)
    emergencias = [(o.stop, o.precio, o.qty) for o in stops_ if o.proposito is Proposito.STOP_EMERGENCIA]
    assert principales == [(D("4.00"), 100), (D("4.20"), 50)]
    assert emergencias == [(D("4.75"), D("6.85"), 150)]                 # sobre el L más alto (4,20), toda la posición


# ═══════════════════════════ F4: take profit ═════════════════════════════
def test_f4_tp_con_prioridad_sobre_la_entrada_viva(cfg: Config, tmp_path: Path) -> None:
    """F4 / R-D-07: con una entrada viva en el ticker, el TP va PRIMERO al ask y la entrada espera; luego se retoma."""
    config = cfg_con(cfg, estrategias=[cfg.estrategias[SID], estrategia_b(cfg)])
    b = Banco(config, tmp_path)
    b.preparar(locates=((TICKER, SID, 1000), (TICKER, SID2, 1000)))
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    b.senal(evento(strategy_id=SID2, estrategia="PM (B) prueba", acciones=50.0, stop=4.2,
                   momento=momento_de(b.reloj.ahora())))
    entrada_b = b.enviadas(Proposito.ENTRADA_AGREGAR)[-1]
    marca = b.marca()
    acciones = b.procesar(SenalRecibida(Senal(clase="evento", ticker=TICKER, id=id_de_evento(salida()),
                                              evento=salida(), momento=salida().momento, recibida_en=b.ahora())),
                          bombear=False)
    tps = [a for a in acciones if isinstance(a, EnviarOrden)]
    assert [(o.orden.proposito, o.orden.lado, o.orden.qty, o.orden.precio) for o in tps] == \
           [(Proposito.TP_CRUCE, Lado.COMPRA, 50, D("3.46"))]
    cancelacion = acciones_de(acciones, Cancelar)
    assert [c.token for c in cancelacion] == [entrada_b.token]
    assert acciones.index(tps[0]) < acciones.index(cancelacion[0])      # el TP sale ANTES de pausar la entrada
    b.bombear()
    assert b.pos().neta_fills == -50
    assert b.pos().intento is not None and f"tp_espera_entrada:{TICKER}" in b.temporizadores
    tras_tp = b.desde(marca)
    reemplazos = acciones_de(tras_tp, Reemplazar)
    assert sorted(r.qty for r in reemplazos) == [50, 50]                # principal y emergencia bajan a lo que queda
    assert tras_tp.index(acciones_de(tras_tp, InvalidarSerie)[0]) < tras_tp.index(reemplazos[0])
    marca = b.marca()
    b.avanzar(1.5)
    retomada = b.enviadas(Proposito.ENTRADA_AGREGAR, desde=marca)
    assert [o.qty for o in retomada] == [50]                            # la entrada de B se retoma tras el TP


def test_f4_tp_parcial_agrega_y_cruza_el_resto_con_techo(banco: Banco) -> None:
    """R-D-03 v2: sin conflicto el TP agrega 60 s en el punto medio; luego, CONFIRMADO el Canceled, al ask con techo 3 %."""
    b = banco
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    ev = salida()
    acciones = b.procesar(SenalRecibida(Senal(clase="evento", ticker=TICKER, id=id_de_evento(ev), evento=ev,
                                              momento=ev.momento, recibida_en=b.ahora())))
    tp = [a.orden for a in acciones if isinstance(a, EnviarOrden)]
    assert [(o.proposito, o.qty, o.precio, o.post_only) for o in tp] == [(Proposito.TP_AGREGAR, 50, D("3.45"), True)]
    clave = f"tp_cruce:{lote_de(evento())}"
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


def test_f4_tp_rechazado_se_reintenta_y_conserva_su_cruce(banco: Banco) -> None:
    """R-B-07 + R-D-03 v2: el TP rechazado («PostOnly would cross») sale con token nuevo y SU `tp_cruce` sigue a la orden nueva."""
    b = banco
    abrir_posicion(b)
    b.cotizar(TICKER, "3.44", "3.46", "3.45")
    b.libro.rechazar_siguiente("PostOnly would cross")
    ev = salida()
    b.procesar(SenalRecibida(Senal(clase="evento", ticker=TICKER, id=id_de_evento(ev), evento=ev, momento=ev.momento,
                                   recibida_en=b.ahora())))
    rechazado, reintento = b.enviadas(Proposito.TP_AGREGAR)
    assert b.orden(rechazado.token).estado is EstadoOrden.REJECTED
    assert b.orden(reintento.token).intentos == 1 and reintento.qty == 50
    clave = f"tp_cruce:{lote_de(evento())}"
    assert b.temporizadores[clave][2]["token"] == reintento.token
    assert b.pos().estado is EstadoTicker.NORMAL                         # reintento conocido: sin pausa
    marca = b.marca()
    b.avanzar(60.5)
    assert [(o.qty, o.precio) for o in b.enviadas(Proposito.TP_CRUCE, desde=marca)] == [(50, D("3.46"))]


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
    b.cotizar(TICKER, "4.04", "4.06", "4.05")                           # parado por encima del principal (escenario 2)
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
    """F7 (R-G-01 v2, R-G-03): activación con aviso 3, informes 60 s × 5 y luego 300 s; /cerrar cancela la emergencia ANTES."""
    b = banco
    abrir_posicion(b)
    principal, emergencia = b.enviadas(*STOPS)
    b.cotizar(TICKER, "6.90", "7.10", "7.00")                          # pasa de largo el límite de la emergencia (6,52)
    b.tic_das()
    assert b.pos().estado is EstadoTicker.BS and b.pos().bs is not None
    activacion = [a for a in b.historial if isinstance(a, Avisar) and a.clave == f"bs:{TICKER}"]
    assert len(activacion) == 1 and activacion[0].nivel is Nivel.MAXIMO
    assert cisne_negro.TITULO_INFORME in activacion[0].texto
    b.avanzar(605, tic=5.0)
    claves = [a.clave for a in b.historial if isinstance(a, Avisar) and (a.clave or "").startswith(f"bs:{TICKER}:")]
    assert claves == [f"bs:{TICKER}:{n}" for n in range(1, 7)]          # 5 al minuto y el 6.º a los 5 min del 5.º
    assert not b.enviadas(*STOPS, desde=0)[2:]                           # en BS no se repone ni se persigue nada
    marca = b.marca()
    acciones = b.comando("/cerrar XYZ SI")
    cancelados = [a.token for a in acciones if isinstance(a, Cancelar)]
    assert cancelados[:2] == [emergencia.token, principal.token]        # la emergencia PRIMERO (R-G-03 (3))
    cierre = b.enviadas(Proposito.CIERRE_HUMANO, desde=marca)
    assert [(o.qty, o.precio) for o in cierre] == [(100, D("7.46"))]   # techo 5 % sobre el ask (R-D-06)
    assert b.pos().neta_fills == 0
    assert b.pos().bs is None and b.pos().sin_reentrada_hasta_sigue is True
    assert not [a for a in b.desde(marca) if isinstance(a, Avisar) and cisne_negro.FRASE_EXITO in a.texto]
    assert anotaciones(b.desde(marca), "bs")[-1].datos["evento"] == "cerrado"


def test_f7_cierre_dentro_de_la_emergencia_avisa_exito_y_veta_la_reentrada(banco: Banco) -> None:
    """R-G-01 (3): si la emergencia saca la posición tras activarse el protocolo → aviso 3 con la frase literal y veto."""
    b = banco
    abrir_posicion(b)
    b.cotizar(TICKER, "6.90", "7.10", "7.00")
    b.tic_das()
    assert b.pos().estado is EstadoTicker.BS
    marca = b.marca()
    b.cotizar(TICKER, "5.95", "6.00", "6.00")                           # vuelve: la emergencia (límite 6,52) llena
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
def test_f8_rechazo_conocido_reintenta_con_token_nuevo_y_nunca_un_tercero(banco: Banco) -> None:
    """R-B-07: «PostOnly would cross» → 2 reintentos con token NUEVO (re-preciados al libro) y al tercero, pausa."""
    b = banco
    for _ in range(3):
        b.libro.rechazar_siguiente("PostOnly would cross")
    b.senal(evento())
    envios = b.enviadas(Proposito.ENTRADA_AGREGAR)
    assert len(envios) == 3 and len({o.token for o in envios}) == 3
    assert [b.orden(o.token).intentos for o in envios] == [0, 1, 2]
    assert all(b.orden(o.token).estado is EstadoOrden.REJECTED for o in envios)
    avisos_rechazo = [a for a in b.historial if isinstance(a, Avisar) and (a.clave or "").startswith(f"rechazo:{TICKER}:")]
    assert len(avisos_rechazo) == 3 and all("PostOnly would cross" in a.texto for a in avisos_rechazo)
    assert b.pos().estado is EstadoTicker.PAUSADO and b.pos().intento is None
    assert anotaciones(b.historial, "rechazo")[-1].datos["decision"] == rechazos.DECISION_PAUSA


def test_f8_rechazo_desconocido_con_la_posicion_cubierta_pausa(banco: Banco) -> None:
    """R-B-07 (3): texto desconocido y la emergencia CONFIRMADA → ticker PAUSADO, aviso 2 y ninguna orden nueva."""
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
    """R-B-07 (3) / R-C-03 / EP-1: el principal rechazado con la emergencia sin confirmar → nivel 3, control humano, sin orden."""
    b = banco
    b.senal(evento())
    b.libro.rechazar_siguiente("Algo raro 123")                         # el siguiente NEWORDER: el principal
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
    repuesto = b.enviadas(Proposito.STOP_PRINCIPAL, desde=marca)
    assert len(repuesto) == 1 and b.orden(repuesto[0].token).intentos == 1   # R-C-03: reintento 1/5


def test_f8_stop_rechazado_siempre_se_reintenta_cinco_veces_y_nunca_en_bucle(banco: Banco) -> None:
    """R-C-03: un stop que DAS rechaza siempre → 5 reintentos separados 2 s (6 envíos) y ninguno más, ni desde el barrido."""
    b = banco
    b.rechazar[Proposito.STOP_PRINCIPAL] = "Algo raro 123"
    abrir_posicion(b)
    b.avanzar(1.5)
    assert len(b.enviadas(Proposito.STOP_PRINCIPAL)) == 1                # el barrido NO lo repone durante la separación
    b.avanzar(20, tic=0.5)
    principales = b.enviadas(Proposito.STOP_PRINCIPAL)
    assert [b.orden(o.token).intentos for o in principales] == [0, 1, 2, 3, 4, 5]
    assert all(b.orden(o.token).estado is EstadoOrden.REJECTED for o in principales)
    agotado = [a for a in anotaciones(b.historial, "rechazo") if a.datos["decision"] == rechazos.DECISION_STOP_AGOTADO]
    assert len(agotado) == 1
    b.avanzar(30, tic=2.0)
    assert len(b.enviadas(Proposito.STOP_PRINCIPAL)) == 6                # agotado: ni el plan ni la reconciliación insisten
    assert len(b.enviadas(Proposito.STOP_EMERGENCIA)) == 1 and b.pos().estado is EstadoTicker.CONTROL_HUMANO


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
            emergencia = b.enviadas(Proposito.STOP_EMERGENCIA)[0]
            b.das.recibir(f"REPLACE {b.orden(emergencia.token).id_das} 60 STOPLMT 4.52 6.52")   # la mano humana
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
        emergencia = b.enviadas(Proposito.STOP_EMERGENCIA)[0]
        assert [(r.token, r.qty) for r in acciones_de(tras, Reemplazar)][:1] == [(emergencia.token, 100)]
    elif n == 3:
        assert sorted(o.proposito.value for o in b.enviadas(*STOPS, desde=marca)) == ["stop_emergencia",
                                                                                      "stop_principal"]
        assert any(isinstance(a, Avisar) and (a.clave or "").startswith("reconciliacion_sin_stop") for a in tras)
    elif n == 4:
        assert b.estado.pausa_global is True and b.estado.ordenes_ajenas
        assert any(isinstance(a, Avisar) and a.nivel is Nivel.MAXIMO and (a.clave or "").startswith("ajena:")
                   for a in tras)
    elif n == 5:
        assert all(lote.estado is EstadoLote.CERRADO for lote in b.pos().lotes.values())
        assert b.pos().neta_fills == 0
    else:
        assert b.pos().neta_fills == -60
        assert anotaciones(tras, "discrepancia")[0].datos["neta_das"] == -60
        assert sorted((o.proposito.value, o.qty) for o in b.enviadas(*STOPS, desde=marca)) == \
               [("stop_emergencia", 60), ("stop_principal", 60)]


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
    assert sorted((o.proposito.value, o.qty) for o in stops_) == [("stop_emergencia", 40), ("stop_principal", 40)]
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
    for stop, limite in ((D("4.00"), D("4.12")), (D("4.52"), D("6.52"))):
        b.das.recibir(protocolo.cmd_neworder(OrdenNueva(token=vigilante.siguiente(), lado=Lado.COMPRA, ticker=TICKER,
                                                        ruta="STOP", qty=100, tipo=TipoOrden.STOP_LIMITE_PP,
                                                        precio=limite, stop=stop)))
    b.preparar(locates=())
    b.avanzar(3)
    assert not b.enviadas(*STOPS)
    adoptadas = [o for o in b.estado.ordenes.values() if o.origen is Origen.VIGILANTE]
    assert len(adoptadas) == 2 and len(anotaciones(b.historial, "orden_adoptada")) == 2
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
    assert sorted((o.proposito.value, o.qty) for o in b.enviadas(*STOPS)) == [("stop_emergencia", 30),
                                                                               ("stop_principal", 30)]


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


def test_senal_larga_con_un_corto_abierto_se_descarta(banco: Banco) -> None:
    """R-E-01: solo cortos; un largo contra un corto vivo se descarta y se avisa nivel 1."""
    b = banco
    abrir_posicion(b)
    momento = otra_vela(b)
    marca = b.marca()
    acciones = b.senal(evento(direccion="Long", momento=momento))
    assert anotaciones(acciones, "senal_descartada")[0].datos["motivo"] == reglas_entrada.MOTIVO_LADO
    assert [a.nivel for a in acciones if isinstance(a, Avisar)] == [Nivel.INFO]
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
    assert sorted(r.qty for r in nuevos) == [80, 80]


def test_grupo_a_sale_primero_aunque_la_senal_se_descarte(cfg: Config, tmp_path: Path) -> None:
    """F1.1 / R-M-05: con el grupo A activo, `Avisar(1, A)` es la PRIMERA acción y sale aunque luego no se entre."""
    config = cfg_con(cfg, grupo_a=True,
                     estrategias=[dataclasses.replace(cfg.estrategias[SID], avisar_grupo_a=True)])
    b = Banco(config, tmp_path)
    b.preparar(locates=())                                              # sin locates: la señal se descartará
    acciones = b.senal(evento(), bombear=False)
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
    ("/cerrar XYZ 40 SI", None, lambda b, a: b.pos().neta_fills == -60 or pytest.fail("no cerró 40")),
    ("/cancelar_ordenes XYZ SI", None,
     lambda b, a: (acciones_de(a, CancelarTicker) and b.pos().estado is EstadoTicker.CONTROL_HUMANO)
     or pytest.fail("no canceló")),
    ("/stop XYZ 4.50 SI", None,
     lambda b, a: (all(lote.nivel_stop == D("4.50") for lote in b.pos().lotes.values())
                   and sorted((e.orden.proposito.value, e.orden.stop) for e in acciones_de(a, EnviarOrden))
                   == [("stop_emergencia", D("5.09")), ("stop_principal", D("4.50"))]
                   and len(acciones_de(a, Cancelar)) == 2)
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
    assert {o["proposito"] for o in foto["ordenes"]} == {"stop_principal", "stop_emergencia"}
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
