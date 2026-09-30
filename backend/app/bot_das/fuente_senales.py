"""Fuentes de señal del ejecutor: en proceso, por tubería y por grabación (§3.11).

QUÉ HACE. Define el `Protocol` `FuenteSenales` (arrancar / parar / salud) y
tres adaptadores que convierten lo que produce el motor de alertas en objetos
`Senal` y los entregan a un `destino` (la cola del ejecutor):

  * `FuenteEnProceso`: un `RunnerAlertas` local. `hidratar` → `Senal("hidratado")`
    + una `Senal("evento")` por `Evento`; `vela` → una `Senal("evento")` por
    `Evento` con `id = bot_alerts_cliente.id_evento` (R-A-05); `radar` →
    `Senal("radar")` con las filas de `estimacion_locates` a las que la fuente
    AÑADE `strategy_id` casando por nombre (corrección 6, riesgo 25);
    `dia_nuevo` → `runner.reiniciar()` + `Senal("dia_nuevo")`.
  * `FuenteTuberia`: `multiprocessing.connection.Listener` en un `HiloVigilado`
    (§6.1). `bot.py` conecta con `EnlaceEjecutor` (enlace_bot_alertas.py) y manda
    diccionarios con "t": «hola» (versión + hash del motor, H-6), «eventos»,
    «hidratado», «radar», «latido» y «dia_nuevo». Un cliente cada vez. NO
    importa pandas (injerto A §8.25, riesgo 29).
  * `FuenteGrabacion`: relee `grabaciones/AM_AAAA-MM-DD.jsonl.gz` (grabador.py)
    y avanza un `RelojSimulado` al cierre de cada vela (R-O-02, injerto A §8.24);
    `Guion` declara el modelo de spread, halts, rechazos y fills parciales que
    el replay necesita y la grabación no trae.

POR QUÉ ESTÁ AQUÍ. La señal se calcula UNA vez, con la vela oficial de Massive
y el MISMO motor que el bot de alertas (R-A-06): el ejecutor no reimplementa
nada del motor, solo recibe `Evento` ya decididos. Tener tres adaptadores con
el mismo `Protocol` permite probar el decisor y el ejecutor enteros sin socket
(en proceso), reproducir días grabados (grabación) y, en producción, no pagar
pandas ni el GIL de `RunnerAlertas` en el proceso que decide (tubería).

LAS TRAMPAS.
  * `pandas` y `RunnerAlertas` se importan DENTRO de `FuenteEnProceso.__init__`
    (y de `vela_de_grabacion`), nunca al importar este módulo: `test_das_seguridad`
    comprueba que el ejecutor en modo tubería no tiene pandas en `sys.modules`.
  * F-01: por la tubería NO viajan `pd.Timestamp` ni clases de `app.services`.
    `EnlaceEjecutor` manda cada `Evento` como dict de primitivos (`momento`
    como texto «AAAA-MM-DD HH:MM:SS») y `FuenteTuberia` lo reconstruye como
    `EventoLigero` (mismos atributos que `Evento`). Además la tubería despickla
    con un `Unpickler` que solo admite `decimal.Decimal`: un pickle con otra
    clase (un enlace viejo que mande el `Evento` tal cual) se descarta como
    ilegible con aviso en vez de cargar pandas en la ruta de la primera señal.
  * `bot_alerts_cliente` importa `httpx` y `bot_alerts_feed` importa `httpx` y
    `websockets` al cargarse: `id_de_evento` REPLICA `id_evento` (R-A-05; un
    test comprueba la paridad con la original) y `vela_de_mensaje` (feed
    l.177-187) se REPLICA en `vela_de_grabacion` en vez de importarse.
  * F-02: el saludo HMAC de `multiprocessing.connection` lee SIN tiempo límite.
    El Listener se abre SIN authkey y la autenticación (las mismas
    `deliver_challenge` + `answer_challenge` que haría `accept`) se hace
    aquí con un plazo (`espera_auth_s`): un cliente local que conecta y no
    habla ya no deja sorda la tubería. Si el cliente manda medio mensaje y
    calla, `SO_RCVTIMEO` saca al `recv` bloqueado (en Windows un `shutdown`
    desde otro hilo no lo despierta).
  * D2-06 / R-D-07: la tanda de `Evento` de UNA vela se entrega ordenada con
    `reglas.salidas.prioridad` (salidas/TP → pirámides reduce/lot_* → pirámides
    add → entradas): el TP de A llega al decisor antes que la entrada de B.
  * Las grabaciones reales (comprobado el 26-sep sobre AM_2026-09-2x) NO
    guardan el mensaje crudo de Massive sino la vela YA convertida (`timestamp`
    naive ET como texto, open/high/low/close/volume) más `_r` y `sym`.
    `vela_de_grabacion` admite las dos formas (cruda con `s/o/h/l/c/v` y
    convertida) y produce la MISMA vela.
  * `estimar_por_estrategia` devuelve filas SIN `strategy_id`; con nombres
    repetidos y distintos ids no hay forma segura de casar: la fila se descarta
    y se avisa (nivel 2) UNA vez al día por nombre. Casar por posición sería
    frágil (corrección 6).
  * Un `Evento` de otra versión (pickle sin `tipo`/`ticker`/`strategy_id`/
    `momento`) se descarta con aviso 2 (riesgo 18); se lee con `getattr`.
  * Sin `authkey` la tubería NO arranca (`ValueError`, riesgo 19): con
    `multiprocessing.connection` sin clave, cualquiera en localhost podría
    inyectar señales.
  * El saludo «hola» se CONTESTA («ok» o «rechazado»): el enlace no vacía su
    cola hasta recibir «ok», así un rechazo por hash (H-6) no pierde mensajes
    y un enlace viejo que no espere respuesta simplemente no encaja.
  * Los tipos de mensaje (`T_*`), el casado nombre → `strategy_id` y la
    validación de authkey/dirección viven en `enlace_bot_alertas` (stdlib
    pura) y se importan de allí: los dos extremos no pueden divergir.
  * El replay hidrata cada ticker con el corte en el INICIO de su primera vela
    grabada (memoria ELMT) sin mover el `RelojSimulado` hacia atrás.
  * `FuenteEnProceso` NO es segura para varios hilos: la llama un solo hilo
    (el del feed o el replay). `FuenteTuberia.salud()` puede llamarse desde
    otro hilo: lee contadores enteros, nada más.
  * Nada de aquí lanza hacia el ejecutor por un fallo del motor en un ticker
    (H-5): se cuenta, se avisa una vez al día y se sigue con la siguiente vela.
"""
from __future__ import annotations

import gzip
import io
import json
import pickle
import socket
import struct
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from multiprocessing import AuthenticationError
from multiprocessing.connection import Listener, answer_challenge, deliver_challenge
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, runtime_checkable

from app.bot_das import VERSION
from app.bot_das.cerrojo import HiloVigilado
from app.bot_das.enlace_bot_alertas import (   # el protocolo se define UNA vez, en el lado stdlib-only
    T_DIA_NUEVO, T_EVENTOS, T_HIDRATADO, T_HOLA, T_LATIDO, T_OK, T_RADAR, T_RECHAZADO,
    anadir_strategy_id, authkey_valida, direccion_valida, mapa_nombres,
)
from app.bot_das.reglas.precios import de_float
from app.bot_das.reloj import ET, RelojSimulado
from app.bot_das.tipos import Nivel, Senal

Destino = Callable[[Senal], None]
AlAviso = Callable[[int, str], None]

CAMPOS_EVENTO_OBLIGATORIOS = ("tipo", "ticker", "strategy_id", "momento")   # riesgo 18
ORIGEN_PROCESO = "proceso"
ORIGEN_TUBERIA = "tuberia"
ORIGEN_GRABACION = "grabacion"
ET_NOMBRE = "America/New_York"          # el de bot_alerts_feed.ET (los frames van en hora de Nueva York, sin zona)
_ESPERA_HOLA_S = 5.0                    # cuánto espera el Listener el «hola» tras aceptar
_ESPERA_AUTH_S = 5.0                    # F-02: plazo del saludo HMAC tras aceptar (antes no tenía)
_POLL_S = 0.2                           # granularidad con la que el hilo de la tubería mira `parando`
_ACCEPT_FALLOS_MAX = 20                 # accept() fallando seguido → listener roto → se recrea vía HiloVigilado
_DRENAJE_MAX = 10_000                   # mensajes que se apuran del socket al parar (acotado)


# ── Protocol ───────────────────────────────────────────────────────────
@runtime_checkable
class FuenteSenales(Protocol):
    """Lo que el ejecutor necesita de una fuente (§3.11): arrancar, parar y decir cómo está."""

    def arrancar(self) -> None: ...

    def parar(self) -> None: ...

    def salud(self) -> dict: ...          # {"viva": bool, "ultimo_en": epoch | None, "origen": str, ...}


# ── el Evento tal y como llega por la tubería (F-01) ────────────────────
@dataclass
class EventoLigero:
    """Los MISMOS campos que `bot_alerts_engine.Evento`, reconstruidos de un dict de primitivos (F-01).

    `momento` es texto «AAAA-MM-DD HH:MM:SS» (INICIO del minuto, naive ET);
    `entrada.t_cierre_vela` y `id_de_evento` lo aceptan igual que un
    `pd.Timestamp`. Los campos que falten quedan en None (riesgo 18:
    `campo_ausente` los detecta); los que no existan en `Evento` van a `extra`
    y se leen como atributos (un `Evento` de una versión más nueva no pierde
    nada). Es un dataclass: el diario lo serializa campo a campo. Un test
    comprueba que los campos coinciden con los de `Evento`.
    """
    tipo: Optional[str] = None
    ticker: Optional[str] = None
    strategy_id: Optional[str] = None
    estrategia: Optional[str] = None
    momento: Any = None
    precio: Optional[float] = None
    direccion: Optional[str] = None
    estado: str = "alerta"
    acciones: Optional[float] = None
    stop: Optional[float] = None
    distancia_stop: Optional[float] = None
    riesgo_usd: Optional[float] = None
    motivo: Optional[str] = None
    entrada_idx: Optional[int] = None
    posicion_restante: Optional[float] = None
    nivel: Optional[int] = None
    accion_piramide: Optional[str] = None
    posicion_total: Optional[float] = None
    cuenta: Optional[str] = None
    fraccion_lote: Optional[float] = None           # TP DE LOTE (Jaume 30-sep)
    tamano_lote_backtest: Optional[float] = None
    resto_lote_backtest: Optional[float] = None
    extra: dict = field(default_factory=dict)

    def __getattr__(self, nombre: str) -> Any:
        """Solo se llama si el atributo NO existe: busca en `extra` (campos de otra versión del motor)."""
        if nombre.startswith("__"):
            raise AttributeError(nombre)
        extra = self.__dict__.get("extra")
        if extra is not None and nombre in extra:
            return extra[nombre]
        raise AttributeError(f"{type(self).__name__} no tiene {nombre!r}")

    @classmethod
    def desde_dict(cls, datos: dict) -> "EventoLigero":
        """Dict de primitivos (lo que manda `EnlaceEjecutor`) → `EventoLigero`; claves desconocidas a `extra`."""
        conocidos = _CAMPOS_EVENTO_LIGERO
        propios = {k: v for k, v in datos.items() if k in conocidos}
        extra = {str(k): v for k, v in datos.items() if k not in conocidos and k != "extra"}
        if isinstance(datos.get("extra"), dict):
            extra = {**datos["extra"], **extra}
        if "estado" in propios and propios["estado"] is None:
            propios.pop("estado")                    # como `Evento`: sin estado → «alerta»
        return cls(**propios, extra=extra)


_CAMPOS_EVENTO_LIGERO = frozenset(f for f in EventoLigero.__dataclass_fields__ if f != "extra")


# ── utilidades puras (sin pandas) ──────────────────────────────────────
def id_de_evento(ev: Any) -> str:
    """Réplica de `bot_alerts_cliente.id_evento(ev)` (R-A-05: ticker | estrategia | minuto | tipo [| cuenta]).

    Se replica en vez de importarse porque `bot_alerts_cliente` carga `httpx`
    al importarse (F-01: el ejecutor en modo tubería no paga ni httpx ni pandas
    en la primera señal). `test_id_de_evento_paridad_con_id_evento` compara las
    dos sobre `Evento` reales, con y sin cuenta, y sobre `EventoLigero`.
    """
    base = f"{ev.ticker}|{ev.strategy_id}|{str(ev.momento)[:19]}|{ev.tipo}"
    cuenta = getattr(ev, "cuenta", None)
    return f"{base}|{cuenta}" if cuenta else base


def ordenar_tanda(senales: list[Senal]) -> list[Senal]:
    """D2-06 / R-D-07: la tanda de UNA vela ordenada con `reglas.salidas.prioridad` (salidas/TP → reduce/lot_* → add → entradas).

    Import perezoso de `reglas.salidas` (no carga nada pesado, pero así este
    módulo sigue importándose ligero). Si la ordenación fallara, se entrega en
    el orden del motor: nunca se pierde una señal por ordenarla.
    """
    if len(senales) < 2:
        return list(senales)
    try:
        from app.bot_das.reglas.salidas import prioridad
        ordenadas = list(prioridad(list(senales)))
    except Exception:  # noqa: BLE001 — frontera con otra unidad: un fallo al ordenar no puede perder la tanda (R-M-05)
        return list(senales)
    if len(ordenadas) != len(senales):
        return list(senales)
    return ordenadas


def campo_ausente(ev: Any) -> Optional[str]:
    """El primer campo obligatorio (`tipo`, `ticker`, `strategy_id`, `momento`) que falta o es None, o None si el `Evento` sirve (riesgo 18).

    Se lee con `getattr`: un pickle de otra versión del bot de alertas puede
    traer una clase con menos campos, y el ejecutor no debe reventar por eso.
    """
    for campo in CAMPOS_EVENTO_OBLIGATORIOS:
        if getattr(ev, campo, None) is None:
            return campo
    return None


def version_como_tupla(version: Any) -> Optional[tuple[int, ...]]:
    """«AAAA.MM.DD» (VERSION de app.bot_das, R-O-01) → (AAAA, MM, DD); None si no es texto con ese formato."""
    if not isinstance(version, str):
        return None
    trozos = version.strip().split(".")
    if len(trozos) != 3 or not all(t.isdigit() for t in trozos):
        return None
    return tuple(int(t) for t in trozos)


def motivo_rechazo_hola(version: Any, motor_hash: Any, version_minima: str,
                        motor_hash_esperado: str) -> Optional[str]:
    """None si el «hola» se acepta; si no, el motivo (H-6: hash del motor distinto → el ejecutor se niega).

    El hash se compara LITERALMENTE (texto contra texto, sin normalizar): un
    `""` contra `"sha256:…"` es distinto. La versión debe ser «AAAA.MM.DD» y no
    anterior a `version_minima`; una versión ilegible se rechaza (conservador).
    """
    if not isinstance(motor_hash, str) or motor_hash != motor_hash_esperado:
        return f"hash del motor distinto: recibido {motor_hash!r}, esperado {motor_hash_esperado!r} (H-6)"
    recibida = version_como_tupla(version)
    minima = version_como_tupla(version_minima)
    if recibida is None or minima is None:
        return f"versión ilegible: recibida {version!r}, mínima {version_minima!r} (R-O-01)"
    if recibida < minima:
        return f"versión {version} anterior a la mínima {version_minima} (R-O-01)"
    return None


def vela_de_grabacion(m: dict) -> Optional[tuple[int, str, dict]]:
    """Una línea de `AM_AAAA-MM-DD.jsonl.gz` → (s_ms, ticker, vela) o None si no es una vela completa.

    Réplica de `bot_alerts_feed.vela_de_mensaje` (l.177-187: `timestamp` =
    campo `s` en ms UTC → naive ET, INICIO del minuto; precios `float`;
    `volume` `float(v or 0)`), extendida a la forma que grabador.py guarda de
    verdad (la vela ya convertida, con `timestamp` texto naive ET). Devuelve
    también `s_ms` (epoch ms del inicio del minuto) para ordenar y fijar el
    reloj, y el ticker (`sym`). Importa pandas perezosamente: solo lo usa el
    replay.
    """
    import pandas as pd

    ticker = m.get("sym") or m.get("ticker")
    if not isinstance(ticker, str) or not ticker:
        return None
    if "s" in m:                                     # mensaje crudo de Massive (feed l.177-187)
        o, h, l, c = m.get("o"), m.get("h"), m.get("l"), m.get("c")
        ts = m.get("s")
        if ts is None or None in (o, h, l, c):
            return None
        s_ms = int(ts)
        timestamp = pd.Timestamp(s_ms, unit="ms", tz="UTC").tz_convert(ET_NOMBRE).tz_localize(None)
        volumen = m.get("v")
    else:                                            # vela ya convertida (lo que grabador.vela recibe del feed)
        o, h, l, c = m.get("open"), m.get("high"), m.get("low"), m.get("close")
        ts = m.get("timestamp")
        if ts is None or None in (o, h, l, c):
            return None
        timestamp = pd.Timestamp(ts)
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_convert(ET_NOMBRE).tz_localize(None)
        s_ms = int(timestamp.tz_localize(ET_NOMBRE).timestamp() * 1000)
        volumen = m.get("volume")
    vela = {
        "timestamp": timestamp,
        "open": float(o), "high": float(h), "low": float(l), "close": float(c),
        "volume": float(volumen or 0),
    }
    return s_ms, ticker, vela


# ── Guion del replay (injerto A §8.24) ─────────────────────────────────
@dataclass(frozen=True)
class SpreadGuion:
    """Modelo de spread declarado (la grabación no trae bid/ask; grabador.py l.29-40).

    Mismos campos y defaults que `simulador_das.ModeloSpread` (§3.3, lote A);
    `como(ModeloSpread)` construye aquel sin que este módulo importe el lote A.
    `pct` es Decimal (nunca float, riesgo 12).
    """
    pct: Decimal = Decimal("0.5")
    minimo_ticks: int = 1
    tamano_bid: int = 500
    tamano_ask: int = 500

    def __post_init__(self) -> None:
        if not isinstance(self.pct, Decimal) or not self.pct.is_finite() or self.pct < 0:
            raise ValueError(f"spread.pct debe ser un Decimal finito ≥ 0: {self.pct!r}")
        for nombre, minimo in (("minimo_ticks", 0), ("tamano_bid", 1), ("tamano_ask", 1)):
            valor = getattr(self, nombre)
            if type(valor) is not int or valor < minimo:
                raise ValueError(f"spread.{nombre} debe ser un entero ≥ {minimo}: {valor!r}")

    @classmethod
    def desde_dict(cls, datos: Optional[dict]) -> "SpreadGuion":
        """De JSON: `pct` número o texto → Decimal por `de_float` (nunca float en aritmética); claves ausentes → defecto."""
        datos = datos or {}
        if not isinstance(datos, dict):
            raise ValueError(f"spread debe ser un objeto JSON: {datos!r}")
        base = cls()
        return cls(
            pct=de_float(datos["pct"]) if "pct" in datos else base.pct,
            minimo_ticks=datos.get("minimo_ticks", base.minimo_ticks),
            tamano_bid=datos.get("tamano_bid", base.tamano_bid),
            tamano_ask=datos.get("tamano_ask", base.tamano_ask),
        )

    def como(self, clase: Callable[..., Any]) -> Any:
        """`clase(pct=…, minimo_ticks=…, tamano_bid=…, tamano_ask=…)`: p. ej. `simulador_das.ModeloSpread`."""
        return clase(pct=self.pct, minimo_ticks=self.minimo_ticks,
                     tamano_bid=self.tamano_bid, tamano_ask=self.tamano_ask)


@dataclass
class Guion:
    """Lo que el replay necesita declarar porque la grabación no lo trae (injerto A §8.24, riesgo 28).

    `halts`, `rechazos` y `fills_parciales` son listas de diccionarios que
    consume quien alimenta el `LibroSimulado` desde `paso(t, vela)` (halt /
    rechazar_siguiente / llenar_parcial, §3.3); aquí solo se validan como
    listas de objetos. Formato del fichero: {"spread": {…}, "halts": […],
    "rechazos": […], "fills_parciales": […]}; toda clave es opcional.
    """
    spread: SpreadGuion = field(default_factory=SpreadGuion)
    halts: list[dict] = field(default_factory=list)
    rechazos: list[dict] = field(default_factory=list)
    fills_parciales: list[dict] = field(default_factory=list)

    @classmethod
    def desde_dict(cls, datos: dict) -> "Guion":
        if not isinstance(datos, dict):
            raise ValueError(f"el guion debe ser un objeto JSON: {datos!r}")
        listas = {}
        for nombre in ("halts", "rechazos", "fills_parciales"):
            valor = datos.get(nombre, [])
            if not isinstance(valor, list) or not all(isinstance(x, dict) for x in valor):
                raise ValueError(f"guion.{nombre} debe ser una lista de objetos: {valor!r}")
            listas[nombre] = [dict(x) for x in valor]
        return cls(spread=SpreadGuion.desde_dict(datos.get("spread")), **listas)

    @classmethod
    def cargar(cls, ruta: Path) -> "Guion":
        """Lee `fixtures/guion_replay_ejemplo.json` (o cualquier fichero con ese formato). Lanza si no existe o está mal."""
        with Path(ruta).open("r", encoding="utf-8") as f:
            return cls.desde_dict(json.load(f))


# ── base común de los adaptadores ───────────────────────────────────────
class _FuenteBase:
    """Entrega, avisos con dedupe diario y contadores; lo comparten las tres fuentes."""

    origen = "?"

    def __init__(self, destino: Destino, reloj, al_aviso: Optional[AlAviso]) -> None:
        if not callable(destino):
            raise ValueError("destino debe ser una función que reciba Senal")
        self._destino = destino
        self._reloj = reloj
        self._al_aviso = al_aviso
        self._viva = False
        self._ultimo_en: Optional[float] = None
        self._avisados: set[tuple] = set()
        self.entregadas = 0
        self.fallos_destino = 0
        self.avisos = 0
        self.avisos_fallidos = 0
        self.ultimo_error: Optional[str] = None

    # ── entrega ──
    def _entregar(self, senal: Senal) -> bool:
        try:
            self._destino(senal)
        except Exception as exc:  # noqa: BLE001 — frontera de callback: la cola del ejecutor no falla, pero si el destino lanza se cuenta y se avisa, nunca se propaga a la fuente
            self.fallos_destino += 1
            self.ultimo_error = f"destino: {type(exc).__name__}: {exc}"
            self._avisar_una_vez("destino", Nivel.AVISO, f"la fuente {self.origen} no pudo entregar una señal: {self.ultimo_error}")
            return False
        self.entregadas += 1
        return True

    def _entregar_tanda(self, senales: list[Senal]) -> None:
        """D2-06: las señales de UNA vela, ordenadas por `salidas.prioridad` (R-D-07) antes de entregarlas."""
        for senal in ordenar_tanda(senales):
            self._entregar(senal)

    # ── avisos ──
    def _avisar(self, nivel: int, texto: str) -> None:
        self.avisos += 1
        if self._al_aviso is None:
            return
        try:
            self._al_aviso(int(nivel), texto)
        except Exception as exc:  # noqa: BLE001 — frontera de callback: un aviso que falla no puede tumbar la fuente (R-M-05: la señal manda)
            self.avisos_fallidos += 1
            self.ultimo_error = f"al_aviso: {type(exc).__name__}: {exc}"

    def _avisar_una_vez(self, clave: str, nivel: int, texto: str) -> bool:
        """Avisa como mucho UNA vez al día por `clave` (corrección 6: «una vez al día»)."""
        marca = (self._reloj.hoy(), clave)
        if marca in self._avisados:
            return False
        self._avisados.add(marca)
        self._avisar(nivel, texto)
        return True

    def _senal_evento(self, ev: Any, recuperada: bool = False, close: Any = None) -> Senal:
        """`close` (ensayo 28-sep): el cierre de la vela que disparó el evento, en `Senal.feed["close"]`. Una pirámide
        lleva en `Evento.precio` el precio del nivel (la apertura de la vela en la que el motor ejecuta el añadido), no
        el último precio: R-A-01 (retraso) debe compararse con el cierre, si no toda pirámide en un tramo rápido
        se descarta como «tardía»."""
        feed = {"close": close} if close is not None else None
        return Senal(clase="evento", ticker=ev.ticker, id=id_de_evento(ev), evento=ev, momento=ev.momento,
                     recibida_en=self._reloj.mono(), recuperada=bool(recuperada), origen=self.origen, feed=feed)

    def _salud_base(self) -> dict:
        return {"viva": self._viva, "ultimo_en": self._ultimo_en, "origen": self.origen,
                "entregadas": self.entregadas, "fallos_destino": self.fallos_destino,
                "ultimo_error": self.ultimo_error}


# ── 1. en proceso ──────────────────────────────────────────────────────
class FuenteEnProceso(_FuenteBase):
    """`RunnerAlertas` local: tests, replay y un futuro sin bot.py (§3.11).

    pandas y el runner se importan en `__init__` (injerto A §8.25). El runner
    queda público en `self.runner` (el radar lee `runner.motor.estrategias`).
    Un solo hilo la llama.
    """

    origen = ORIGEN_PROCESO

    def __init__(self, estrategias: list[dict], destino: Destino, reloj,
                 al_aviso: Optional[AlAviso] = None) -> None:
        super().__init__(destino, reloj, al_aviso)
        import pandas as pd                                        # perezoso: nunca al importar el módulo
        from app.services.bot_alerts_runner import RunnerAlertas   # ídem (arrastra pandas y el motor)
        self._pd = pd
        self.runner = RunnerAlertas(list(estrategias), al_avisar=None)
        self.fallos_motor = 0

    def arrancar(self) -> None:
        self._viva = True

    def parar(self) -> None:
        self._viva = False

    def salud(self) -> dict:
        salud = self._salud_base()
        salud.update({"fallos_motor": self.fallos_motor, "tickers": len(self.runner.tickers)})
        return salud

    # ── entrada de datos ──
    def hidratar(self, ticker: str, velas: list[dict], stats: Optional[dict] = None) -> None:
        """`runner.hidratar` con `ahora` = hora del reloj inyectado → `Senal("hidratado")` + una `Senal("evento")` por `Evento`.

        `ahora` sale del reloj (no de `datetime.now`) para que el corte
        «última vela completa = presente» (memoria ELMT, 14-sep) sea el mismo
        en vivo, en tests y en replay. `n_velas` y `prev_close` viajan en
        `Senal.feed` (§2 no tiene campo propio para ellos).
        """
        self._hidratar(ticker, velas, stats, self._reloj.ahora())

    def _hidratar(self, ticker: str, velas: list[dict], stats: Optional[dict], corte: datetime) -> None:
        """`hidratar` con el instante de corte explícito (aware ET): el replay corta en el INICIO de la primera vela grabada sin mover el reloj hacia atrás."""
        df = self._pd.DataFrame(list(velas))
        ahora = self._pd.Timestamp(_a_et(corte).replace(tzinfo=None))
        try:
            eventos = self.runner.hidratar(ticker, df, stats, ahora=ahora)
        except Exception as exc:  # noqa: BLE001 — frontera del motor (H-5): un ticker que revienta al hidratar se avisa y se salta; el resto sigue
            self._fallo_motor(ticker, "hidratar", exc)
            return
        self._ultimo_en = self._reloj.epoch()
        self._entregar(Senal(clase="hidratado", ticker=ticker, id=None, recibida_en=self._reloj.mono(),
                             feed={"n_velas": int(len(df)), "prev_close": (stats or {}).get("prev_close")},
                             origen=self.origen))
        self._entregar_tanda([self._senal_evento(ev) for ev in eventos])

    def vela(self, ticker: str, vela: dict) -> None:
        """`runner.nueva_vela` → una `Senal("evento")` por `Evento`, con `id = id_evento` (R-A-05) y `recibida_en = reloj.mono()`."""
        try:
            eventos = self.runner.nueva_vela(ticker, vela)
        except Exception as exc:  # noqa: BLE001 — frontera del motor (H-5): una vela que revienta no deja sordo al bot para el resto de tickers
            self._fallo_motor(ticker, "vela", exc)
            return
        self._ultimo_en = self._reloj.epoch()
        self._entregar_tanda([self._senal_evento(ev, close=vela.get("close")) for ev in eventos])

    def radar(self, ticker: str, precio: Decimal) -> None:
        """`runner.estimacion_locates(ticker, float(precio))` + `strategy_id` por nombre → `Senal("radar")` (corrección 6, riesgo 25).

        `float(precio)` es la frontera con el motor existente (su API es float);
        `precio_radar` de la señal sigue siendo Decimal. Nombres repetidos con
        ids distintos → fila descartada y aviso 2 una vez al día por nombre.
        """
        precio_dec = precio if isinstance(precio, Decimal) else de_float(precio)
        try:
            filas = self.runner.estimacion_locates(ticker, float(precio_dec))
        except Exception as exc:  # noqa: BLE001 — frontera del motor (H-5): una consulta de radar no puede tumbar la fuente
            self._fallo_motor(ticker, "radar", exc)
            return
        mapa, repetidos = mapa_nombres(self.runner.motor.estrategias)
        validas, descartados = anadir_strategy_id(filas, mapa, repetidos)
        for nombre in descartados:
            motivo = "repetido con ids distintos" if nombre in repetidos else "sin strategy_id conocido"
            self._avisar_una_vez(f"radar:{nombre}", Nivel.AVISO,
                                 f"radar: fila de la estrategia «{nombre}» descartada ({motivo}); "
                                 "no se pueden pedir locates para ella (corrección 6, riesgo 25)")
        self._ultimo_en = self._reloj.epoch()
        self._entregar(Senal(clase="radar", ticker=ticker, id=None, recibida_en=self._reloj.mono(),
                             estimacion=validas, precio_radar=precio_dec, origen=self.origen))

    def dia_nuevo(self) -> None:
        """`runner.reiniciar()` (frames y avisos del día fuera) + `Senal("dia_nuevo")`; los avisos «una vez al día» se rearman."""
        self.runner.reiniciar()
        self._avisados.clear()
        self._entregar(Senal(clase="dia_nuevo", ticker=None, id=None, recibida_en=self._reloj.mono(),
                             origen=self.origen))

    def _fallo_motor(self, ticker: str, donde: str, exc: Exception) -> None:
        self.fallos_motor += 1
        self.ultimo_error = f"{ticker} {donde}: {type(exc).__name__}: {exc}"
        self._avisar_una_vez(f"motor:{ticker}:{donde}", Nivel.AVISO,
                             f"fuente {self.origen}: el motor falló en {self.ultimo_error} (H-5: se salta)")


# ── 2. por tubería ─────────────────────────────────────────────────────
class FuenteTuberia(_FuenteBase):
    """Listener de `multiprocessing.connection` en un `HiloVigilado`; `bot.py` conecta con `EnlaceEjecutor` (§3.11, §6.1).

    Mensajes (dict con "t"): «hola» {version, motor_hash} → se contesta «ok» o
    «rechazado» (H-6, R-O-01); «eventos» {ticker, minuto, timestamp, eventos,
    recuperada}; «hidratado» {ticker, n_velas, eventos, prev_close}; «radar»
    {candidatos: [{ticker, precio, estimacion}]}; «latido» {ultima_vela_en,
    feed_vivo}; «dia_nuevo». Un cliente cada vez (los demás esperan en el
    backlog). NO importa pandas.
    """

    origen = ORIGEN_TUBERIA

    def __init__(self, direccion: "tuple[str, int] | str", authkey: bytes, destino: Destino, reloj,
                 motor_hash_esperado: str, version_minima: str,
                 al_aviso: Optional[AlAviso] = None, espera_hola_s: float = _ESPERA_HOLA_S,
                 espera_auth_s: float = _ESPERA_AUTH_S) -> None:
        super().__init__(destino, reloj, al_aviso)
        if not float(espera_auth_s) > 0:
            raise ValueError(f"espera_auth_s debe ser > 0: {espera_auth_s!r}")
        self._espera_auth_s = float(espera_auth_s)
        self.autenticaciones_caducadas = 0      # F-02: clientes que conectaron y no completaron el HMAC a tiempo
        self._authkey = authkey_valida(authkey)
        self._direccion = direccion_valida(direccion)
        if not isinstance(motor_hash_esperado, str):
            raise ValueError("motor_hash_esperado debe ser texto")
        if version_como_tupla(version_minima) is None:
            raise ValueError(f"version_minima debe ser «AAAA.MM.DD»: {version_minima!r}")
        self.motor_hash_esperado = motor_hash_esperado
        self.version_minima = version_minima
        self._espera_hola_s = float(espera_hola_s)
        self._listener: Optional[Listener] = None
        self._hilo: Optional[HiloVigilado] = None
        self._conn: Any = None
        self.cliente_version: Optional[str] = None
        self.conexiones = 0
        self.desconexiones = 0
        self.rechazados = 0
        self.autenticaciones_fallidas = 0
        self.saludos_fallidos = 0
        self.errores_accept = 0
        self.recibidos = 0
        self.descartados = 0
        self.malformados = 0
        self.desconocidos = 0

    # ── ciclo de vida ──
    def arrancar(self) -> None:
        """Abre el Listener (bind) y arranca el hilo `fuente-tuberia`. Idempotente."""
        if self._hilo is not None and self._hilo.vivo:
            return
        if self._listener is None:
            self._listener = Listener(self._direccion, authkey=None)   # F-02: el HMAC se hace en `_autenticar`, con plazo
        self._hilo = HiloVigilado("fuente-tuberia", self._bucle, self._al_caida)
        self._hilo.arrancar()
        self._viva = True

    def parar(self) -> None:
        """Para el hilo, despierta el `accept` si estaba bloqueado, cierra listener y conexión. Idempotente."""
        hilo = self._hilo
        if hilo is not None:
            hilo.parando.set()
        self._despertar_accept()
        self._cerrar_listener()
        if hilo is not None:
            hilo.parar(espera_s=5.0)
        conn, self._conn = self._conn, None
        if conn is not None:
            _cerrar_silencioso(conn)
        self._viva = False

    @property
    def direccion(self) -> "tuple[str, int] | str":
        """La dirección real (con el puerto asignado si se pidió 0) una vez arrancada."""
        if self._listener is not None:
            return self._listener.address
        return self._direccion

    def salud(self) -> dict:
        salud = self._salud_base()
        salud.update({
            "viva": bool(self._hilo is not None and self._hilo.vivo and self._listener is not None),
            "conectado": self._conn is not None, "cliente_version": self.cliente_version,
            "recibidos": self.recibidos, "rechazados": self.rechazados, "descartados": self.descartados,
            "malformados": self.malformados, "desconocidos": self.desconocidos,
            "conexiones": self.conexiones, "desconexiones": self.desconexiones,
            "autenticaciones_fallidas": self.autenticaciones_fallidas,
            "autenticaciones_caducadas": self.autenticaciones_caducadas,
            "caidas": self._hilo.caidas if self._hilo is not None else 0,
        })
        return salud

    # ── el hilo ──
    def _bucle(self) -> None:
        """Cuerpo del `HiloVigilado`: acepta un cliente, lo sirve hasta que corta, vuelve a aceptar."""
        parando = self._hilo.parando
        fallos_seguidos = 0
        while not parando.is_set():
            listener = self._asegurar_listener()
            try:
                conn = listener.accept()         # sin authkey: vuelve en cuanto hay un cliente (F-02)
            except (OSError, EOFError) as exc:   # frontera de red: listener cerrado por `parar`
                if parando.is_set():
                    return
                self.errores_accept += 1
                fallos_seguidos += 1
                self.ultimo_error = f"accept: {type(exc).__name__}: {exc}"
                if fallos_seguidos >= _ACCEPT_FALLOS_MAX:
                    self._cerrar_listener()
                    raise RuntimeError(f"tubería: el listener no acepta conexiones ({self.ultimo_error})")
                parando.wait(0.1)
                continue
            fallos_seguidos = 0
            if parando.is_set():
                _cerrar_silencioso(conn)
                return
            if not self._autenticar(conn):
                _cerrar_silencioso(conn)
                continue
            if parando.is_set():
                _cerrar_silencioso(conn)
                return
            self._servir(conn)

    def _autenticar(self, conn: Any) -> bool:
        """F-02: el saludo HMAC de `Listener.accept` (deliver_challenge + answer_challenge) con PLAZO.

        Cada lectura espera como mucho lo que queda de `espera_auth_s` (`poll`)
        y, además, el socket lleva `SO_RCVTIMEO` con ese mismo resto: si un
        cliente manda medio mensaje y calla, el `recv` bloqueado sale con
        TimeoutError (en Windows un `shutdown` desde otro hilo NO lo despierta;
        comprobado). Clave incorrecta → aviso (riesgo 19, una vez al día); plazo
        vencido o corte → se cuenta. En los dos casos la conexión se cierra
        (la cierra `_bucle`) y se vuelve a aceptar. True = autenticado.
        """
        limite = time.monotonic() + self._espera_auth_s
        try:
            con_plazo = _ConexionConPlazo(conn, limite)
            deliver_challenge(con_plazo, self._authkey)
            answer_challenge(con_plazo, self._authkey)
            return True
        except (AuthenticationError, AssertionError) as exc:   # frontera de red: cliente sin la clave correcta (riesgo 19)
            self.autenticaciones_fallidas += 1
            self._avisar_una_vez("auth", Nivel.AVISO,
                                 f"tubería: conexión rechazada por clave incorrecta ({exc}) (riesgo 19)")
            return False
        except (OSError, EOFError) as exc:   # frontera de red: cliente callado (TimeoutError) o que cortó durante el HMAC
            self.autenticaciones_caducadas += 1
            self.ultimo_error = f"autenticación: {type(exc).__name__}: {exc}"
            return False
        finally:
            _plazo_de_lectura(conn, None)          # la conexión autenticada vuelve a leer sin plazo (el «hola» usa poll)

    def _asegurar_listener(self) -> Listener:
        """Recrea el Listener si un relanzamiento del hilo lo encontró cerrado (accept roto)."""
        if self._listener is None:
            self._listener = Listener(self._direccion, authkey=None)   # F-02: el HMAC va en `_autenticar`
        return self._listener

    def _servir(self, conn: Any) -> None:
        parando = self._hilo.parando
        self._conn = conn
        self.conexiones += 1
        try:
            if not self._saludo(conn):
                return
            while not parando.is_set():
                if not conn.poll(_POLL_S):
                    continue
                msg = self._recibir(conn)
                if msg is not None:
                    self._procesar(msg)
            for _ in range(_DRENAJE_MAX):          # al parar: lo que ya está en el socket no se tira
                if not conn.poll(0):
                    break
                msg = self._recibir(conn)
                if msg is not None:
                    self._procesar(msg)
        except (EOFError, OSError) as exc:   # frontera de red: el cliente cerró o cortó; EnlaceEjecutor reconecta solo (§6.1)
            self.desconexiones += 1
            self.ultimo_error = f"conexión: {type(exc).__name__}: {exc}"
        finally:
            self._conn = None
            self.cliente_version = None
            _cerrar_silencioso(conn)

    def _saludo(self, conn: Any) -> bool:
        """Espera el «hola», lo juzga con `motivo_rechazo_hola` y contesta «ok» o «rechazado» (H-6). False = no servir."""
        if not conn.poll(self._espera_hola_s):
            self.saludos_fallidos += 1
            self.ultimo_error = "saludo: el cliente no mandó «hola» a tiempo"
            return False
        msg = self._recibir(conn)
        if not isinstance(msg, dict) or msg.get("t") != T_HOLA:
            self.saludos_fallidos += 1
            self.ultimo_error = f"saludo: se esperaba «hola» y llegó {type(msg).__name__}"
            _enviar_silencioso(conn, {"t": T_RECHAZADO, "motivo": "el primer mensaje debe ser «hola»"})
            return False
        version, motor_hash = msg.get("version"), msg.get("motor_hash")
        motivo = motivo_rechazo_hola(version, motor_hash, self.version_minima, self.motor_hash_esperado)
        if motivo is not None:
            self.rechazados += 1
            self.ultimo_error = f"saludo rechazado: {motivo}"
            _enviar_silencioso(conn, {"t": T_RECHAZADO, "motivo": motivo, "version_minima": self.version_minima,
                                      "motor_hash_esperado": self.motor_hash_esperado})
            self._avisar_una_vez(f"hola:{version!r}:{motor_hash!r}", Nivel.MAXIMO,
                                 f"tubería: enlace de bot.py RECHAZADO ({motivo}); el ejecutor no recibirá señales "
                                 "hasta que las versiones coincidan")
            return False
        conn.send({"t": T_OK, "version": VERSION, "motor_hash": self.motor_hash_esperado})
        self.cliente_version = str(version)
        return True

    def _recibir(self, conn: Any) -> Any:
        """`conn.recv_bytes()` + `Unpickler` restringido (F-01); None si no se puede despicklar (riesgo 18). EOF/OSError se propagan.

        Solo se admiten primitivos y `decimal.Decimal`: un pickle que nombre
        otra clase (un `Evento` con `pd.Timestamp` de un enlace viejo) se
        descarta ANTES de importar su módulo; el ejecutor nunca carga pandas
        por la tubería.
        """
        datos = conn.recv_bytes()                  # EOFError/OSError: conexión muerta → frontera en `_servir`
        try:
            return _DespickladorPrimitivos(io.BytesIO(datos)).load()
        except Exception as exc:  # noqa: BLE001 — frontera de mensaje: pickle de otra versión o clase desconocida; el flujo sigue en sincronía (mensajes con longitud)
            self.malformados += 1
            self.ultimo_error = f"mensaje ilegible: {type(exc).__name__}: {exc}"
            self._avisar_una_vez(f"ilegible:{type(exc).__name__}", Nivel.AVISO,
                                 f"tubería: mensaje ilegible descartado ({self.ultimo_error}) (riesgo 18)")
            return None

    def _procesar(self, msg: Any) -> None:
        self.recibidos += 1
        self._ultimo_en = self._reloj.epoch()
        try:
            self._despachar(msg)
        except Exception as exc:  # noqa: BLE001 — frontera de mensaje (H-5 en la fuente): un dict raro se cuenta y se avisa, el hilo sigue
            self.malformados += 1
            self.ultimo_error = f"mensaje malformado: {type(exc).__name__}: {exc}"
            self._avisar_una_vez(f"malformado:{type(exc).__name__}", Nivel.AVISO,
                                 f"tubería: mensaje malformado descartado ({self.ultimo_error})")

    def _despachar(self, msg: Any) -> None:
        if not isinstance(msg, dict):
            raise TypeError(f"se esperaba un dict y llegó {type(msg).__name__}")
        t = msg.get("t")
        if t == T_EVENTOS:
            self._eventos(msg.get("ticker"), msg.get("eventos"), bool(msg.get("recuperada", False)),
                          close=msg.get("close"))
        elif t == T_HIDRATADO:
            ticker = _ticker_valido(msg.get("ticker"))
            self._entregar(Senal(clase="hidratado", ticker=ticker, id=None, recibida_en=self._reloj.mono(),
                                 feed={"n_velas": msg.get("n_velas"), "prev_close": msg.get("prev_close")},
                                 origen=self.origen))
            self._eventos(ticker, msg.get("eventos"), False)
        elif t == T_RADAR:
            self._radar(msg.get("candidatos"))
        elif t == T_LATIDO:
            self._entregar(Senal(clase="latido_feed", ticker=None, id=None, recibida_en=self._reloj.mono(),
                                 feed={"ultima_vela_en": msg.get("ultima_vela_en"),
                                       "vivo": bool(msg.get("feed_vivo", False))},
                                 origen=self.origen))
        elif t == T_DIA_NUEVO:
            self._avisados.clear()
            self._entregar(Senal(clase="dia_nuevo", ticker=None, id=None, recibida_en=self._reloj.mono(),
                                 origen=self.origen))
        elif t == T_HOLA:
            self.desconocidos += 1                 # un segundo «hola» a mitad de conexión no es un error: se ignora
        else:
            self.desconocidos += 1
            self._avisar_una_vez(f"t:{t!r}", Nivel.AVISO, f"tubería: mensaje con tipo desconocido {t!r} ignorado")

    def _eventos(self, ticker: Any, eventos: Any, recuperada: bool, close: Any = None) -> None:
        """Una `Senal("evento")` por `Evento` válido, la tanda ordenada por prioridad (D2-06); los incompletos fuera (riesgo 18).

        Cada evento llega como dict de primitivos (F-01) y se reconstruye como
        `EventoLigero`; lo que no es dict se lee tal cual con `getattr`. `close`
        (opcional, campo «close» del mensaje) es el cierre de la vela: va en
        `Senal.feed` para el retraso de las pirámides (R-A-01).
        """
        lista = list(eventos or [])
        faltan: list[str] = []
        tanda: list[Senal] = []
        for ev in lista:
            if isinstance(ev, dict):
                ev = EventoLigero.desde_dict(ev)
            campo = campo_ausente(ev)
            if campo is not None:
                self.descartados += 1
                faltan.append(campo)
                continue
            tanda.append(self._senal_evento(ev, recuperada, close=close))
        self._entregar_tanda(tanda)
        if faltan:
            campos = sorted(set(faltan))
            self._avisar_una_vez(f"evento_incompleto:{campos}", Nivel.AVISO,
                                 f"tubería: {len(faltan)} evento(s) de {ticker!r} descartado(s): falta {campos} "
                                 "(pickle de otra versión, riesgo 18; se avisa una vez al día, `descartados` cuenta todos)")

    def _radar(self, candidatos: Any) -> None:
        """Una `Senal("radar")` por candidato; filas sin `strategy_id` fuera (riesgo 25); `precio` → Decimal por `de_float`."""
        for c in list(candidatos or []):
            if not isinstance(c, dict):
                self.descartados += 1
                continue
            try:
                ticker = _ticker_valido(c.get("ticker"))
                precio = de_float(c.get("precio"))
            except ValueError as exc:                # frontera de mensaje: candidato sin ticker o con precio inválido
                self.descartados += 1
                self._avisar_una_vez(f"radar_candidato:{c.get('ticker')!r}", Nivel.AVISO,
                                     f"tubería: candidato del radar descartado ({exc})")
                continue
            validas: list[dict] = []
            for fila in list(c.get("estimacion") or []):
                sid = fila.get("strategy_id") if isinstance(fila, dict) else None
                if not isinstance(sid, str) or not sid:
                    self.descartados += 1
                    nombre = fila.get("nombre") if isinstance(fila, dict) else None
                    self._avisar_una_vez(f"radar_fila:{nombre!r}", Nivel.AVISO,
                                         f"tubería: fila del radar de «{nombre}» sin strategy_id descartada (riesgo 25)")
                    continue
                validas.append(dict(fila))
            self._entregar(Senal(clase="radar", ticker=ticker, id=None, recibida_en=self._reloj.mono(),
                                 estimacion=validas, precio_radar=precio, origen=self.origen))

    def _al_caida(self, nombre: str, error: str, relanzado: bool) -> None:
        self.ultimo_error = f"hilo {nombre}: {error}"
        self._avisar(Nivel.AVISO, f"tubería: el hilo {nombre} cayó ({error}); "
                                  f"{'relanzado' if relanzado else 'NO relanzado: sin tubería de señales'}")

    def _despertar_accept(self) -> None:
        """Conexión de cortesía para sacar al hilo de `accept()`.

        TCP: un `connect` crudo. Tubería con nombre de Windows (F-05): cerrar el
        Listener NO despierta el `ConnectNamedPipe` pendiente, así que se abre
        un `Client` sin authkey (el Listener ya no autentica en `accept`, F-02) y
        se cierra en el acto; el hilo ve `parando` y sale.
        """
        listener = self._listener
        if listener is None:
            return
        direccion = listener.address
        if isinstance(direccion, tuple):
            try:
                with socket.create_connection(direccion, timeout=0.5):
                    pass
            except OSError:   # frontera de red: si ya está cerrado, no hay a quién despertar
                return
            return
        try:
            from multiprocessing.connection import Client
            _cerrar_silencioso(Client(direccion))
        except (OSError, EOFError, ValueError):   # frontera de red: tubería ya cerrada u ocupada: nada que despertar
            return

    def _cerrar_listener(self) -> None:
        listener, self._listener = self._listener, None
        if listener is not None:
            try:
                listener.close()
            except OSError:   # frontera de red: cerrar dos veces no es un error
                return


# ── 3. por grabación ───────────────────────────────────────────────────
class FuenteGrabacion(FuenteEnProceso):
    """Relee `AM_AAAA-MM-DD.jsonl.gz` (grabador.py) contra un `RunnerAlertas` local avanzando un `RelojSimulado` (R-O-02).

    `reproducir` aplica las velas EN ORDEN DE TIEMPO (por `s`; a igual minuto,
    el orden de llegada), fija el reloj al CIERRE de cada vela (`s` + 60 s),
    llama a `paso(t, vela)` (el gancho para alimentar el `LibroSimulado` con el
    `ModeloSpread` del `Guion` y meter halts/fills declarados) y luego a
    `self.vela`. La primera vela de un ticker va precedida de `hidratar` con lo
    que devuelva `hidratar_desde(ticker)` (o nada: la grabación empieza cuando
    el ticker entró al radar y el pasado no se grabó).
    """

    origen = ORIGEN_GRABACION

    def __init__(self, ruta_am: Path, estrategias: list[dict], destino: Destino, reloj: RelojSimulado,
                 guion: Optional[Guion] = None, tickers: Optional[set[str]] = None,
                 hidratar_desde: Optional[Callable[[str], Any]] = None,
                 al_aviso: Optional[AlAviso] = None) -> None:
        if not isinstance(reloj, RelojSimulado):
            raise ValueError("FuenteGrabacion exige un RelojSimulado: el replay fija la hora al cierre de cada vela")
        if guion is not None and not isinstance(guion, Guion):
            raise ValueError(f"guion debe ser un Guion: {guion!r}")
        super().__init__(estrategias, destino, reloj, al_aviso)
        self.ruta_am = Path(ruta_am)
        self.guion = guion if guion is not None else Guion()
        self.tickers = set(tickers) if tickers is not None else None
        self._hidratar_desde = hidratar_desde
        self._entradas: Optional[list[tuple[int, str, dict]]] = None
        self._pos = 0
        self._hidratados: set[str] = set()
        self.aplicadas = 0
        self.lineas_malas = 0
        self.lineas_filtradas = 0

    # ── ciclo de vida ──
    def arrancar(self) -> None:
        """Lee y ordena la grabación (una vez); lanza si el fichero no existe o no es gzip."""
        if self._entradas is None:
            self._entradas = self._cargar()
        super().arrancar()

    def salud(self) -> dict:
        salud = super().salud()
        total = len(self._entradas) if self._entradas is not None else 0
        salud.update({"aplicadas": self.aplicadas, "pendientes": max(total - self._pos, 0),
                      "lineas_malas": self.lineas_malas, "lineas_filtradas": self.lineas_filtradas})
        return salud

    @property
    def pendientes(self) -> int:
        return max(len(self._entradas) - self._pos, 0) if self._entradas is not None else 0

    # ── replay ──
    def reproducir(self, hasta: Optional[datetime] = None,
                   paso: Optional[Callable[[datetime, dict], None]] = None) -> int:
        """Aplica velas hasta que el cierre supere `hasta` (o hasta el final); devuelve cuántas aplicó. Reanudable.

        `t` de `paso(t, vela)` es el cierre (aware ET) y `vela` lleva además
        `ticker`; `hasta` naive se toma como ET. Una excepción de `paso` se
        propaga: es el guion del test, no un fallo del bot.
        """
        if self._entradas is None:
            self.arrancar()
        limite = _a_et(hasta) if hasta is not None else None
        aplicadas = 0
        while self._pos < len(self._entradas):
            s_ms, ticker, vela = self._entradas[self._pos]
            t_cierre = datetime.fromtimestamp(s_ms / 1000, tz=ET) + timedelta(seconds=60)
            if limite is not None and t_cierre > limite:
                break
            self._pos += 1
            if ticker not in self._hidratados:
                self._hidratar_primera_vez(ticker, t_cierre - timedelta(seconds=60))
            self._reloj.fijar(t_cierre)
            con_ticker = dict(vela, ticker=ticker)
            if paso is not None:
                paso(t_cierre, con_ticker)
            self.vela(ticker, con_ticker)
            aplicadas += 1
        self.aplicadas += aplicadas
        return aplicadas

    def dia_nuevo(self) -> None:
        """Como `FuenteEnProceso.dia_nuevo` y, además, cada ticker vuelve a hidratarse en su primera vela."""
        super().dia_nuevo()
        self._hidratados.clear()

    def _hidratar_primera_vez(self, ticker: str, inicio: datetime) -> None:
        """Pasado del ticker por `hidratar_desde` (lista de velas, o (velas, stats)); sin gancho, hidrata vacío.

        El corte es el INICIO de la primera vela grabada (memoria ELMT): en vivo
        el radar admite el ticker justo después de cerrar la vela anterior, así
        que esa es la «última completa = presente» y la grabada es la siguiente
        que trae el feed. Lo que `hidratar_desde` devuelva desde ese minuto en
        adelante el runner lo aparta como «en curso» (no se duplica). El reloj
        no se mueve hacia atrás: el corte va explícito.
        """
        self._hidratados.add(ticker)
        velas: Any = []
        stats: Optional[dict] = None
        if self._hidratar_desde is not None:
            devuelto = self._hidratar_desde(ticker)
            if isinstance(devuelto, tuple) and len(devuelto) == 2:
                velas, stats = devuelto
            else:
                velas = devuelto
        self._hidratar(ticker, list(velas or []), stats, inicio)

    def _cargar(self) -> list[tuple[int, str, dict]]:
        """Lee el gzip (miembros concatenados incluidos: `gzip.open` los sigue), filtra por `tickers` y ordena por `s` (estable)."""
        entradas: list[tuple[int, str, dict]] = []
        with gzip.open(self.ruta_am, "rt", encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    m = json.loads(linea)
                    convertida = vela_de_grabacion(m) if isinstance(m, dict) else None
                except (ValueError, TypeError, OverflowError):   # frontera de fichero: una línea rota (volcado a medias) se cuenta y se salta
                    self.lineas_malas += 1
                    continue
                if convertida is None:
                    self.lineas_malas += 1
                    continue
                if self.tickers is not None and convertida[1] not in self.tickers:
                    self.lineas_filtradas += 1
                    continue
                entradas.append(convertida)
        entradas.sort(key=lambda e: e[0])
        return entradas


# ── validaciones y ayudas ───────────────────────────────────────────────
def _ticker_valido(ticker: Any) -> str:
    if not isinstance(ticker, str) or not ticker:
        raise ValueError(f"ticker inválido: {ticker!r}")
    return ticker


def _a_et(dt: datetime) -> datetime:
    """Naive → ET; aware → convertido a ET (mismo criterio que `RelojSimulado`)."""
    if not isinstance(dt, datetime):
        raise ValueError(f"se esperaba un datetime: {dt!r}")
    return dt.replace(tzinfo=ET) if dt.tzinfo is None else dt.astimezone(ET)


class _DespickladorPrimitivos(pickle.Unpickler):
    """F-01: despickla SOLO primitivos (dict, list, str, int, float, bool, None, bytes, set) y `decimal.Decimal`.

    Esas estructuras se codifican con opcodes propios y no pasan por
    `find_class`; cualquier otra clase se rechaza SIN importar su módulo.
    """

    _PERMITIDAS = frozenset({("decimal", "Decimal"), ("_pydecimal", "Decimal")})

    def find_class(self, module: str, name: str) -> Any:
        if (module, name) in self._PERMITIDAS:
            return super().find_class(module, name)
        raise pickle.UnpicklingError(f"clase no admitida por la tubería: {module}.{name} (F-01: solo primitivos)")


class _ConexionConPlazo:
    """F-02: envoltorio de una `Connection` para el saludo HMAC: cada `recv_bytes` espera como mucho hasta `limite` (monotónico)."""

    def __init__(self, conn: Any, limite: float) -> None:
        self._conn = conn
        self._limite = limite

    def send_bytes(self, datos: bytes) -> None:
        self._conn.send_bytes(datos)

    def recv_bytes(self, maxlength: Optional[int] = None) -> bytes:
        queda = self._limite - time.monotonic()
        if queda <= 0 or not self._conn.poll(queda):
            raise TimeoutError("el cliente no completó el saludo HMAC a tiempo (F-02)")
        _plazo_de_lectura(self._conn, max(self._limite - time.monotonic(), 0.05))
        return self._conn.recv_bytes(maxlength)


def _plazo_de_lectura(conn: Any, segundos: Optional[float]) -> None:
    """F-02: `SO_RCVTIMEO` del socket de `conn` (None = sin plazo). No cierra el socket: el handle sigue siendo de `conn`.

    Con una tubería con nombre (no es un socket) no hace nada: allí solo
    protege el `poll` de `_ConexionConPlazo`.
    """
    try:
        s = socket.socket(fileno=conn.fileno())
    except (OSError, ValueError, TypeError):   # frontera de red: tubería con nombre o conexión ya cerrada: nada que ajustar
        return
    try:
        if sys.platform == "win32":
            valor: Any = 0 if segundos is None else max(int(segundos * 1000), 1)
        else:
            seg = 0.0 if segundos is None else max(segundos, 0.001)
            valor = struct.pack("ll", int(seg), int((seg - int(seg)) * 1_000_000))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVTIMEO, valor)
    except OSError:   # frontera de red: socket ya cortado; la lectura fallará sola
        pass
    finally:
        s.detach()


def _cerrar_silencioso(conn: Any) -> None:
    try:
        conn.close()
    except OSError:   # frontera de red: cerrar una conexión ya muerta no es un error
        return


def _enviar_silencioso(conn: Any, obj: Any) -> None:
    try:
        conn.send(obj)
    except (OSError, EOFError, ValueError):   # frontera de red: si el cliente ya cerró, la respuesta no tiene destinatario
        return
