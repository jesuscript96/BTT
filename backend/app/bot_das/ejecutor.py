"""Proceso ejecutor del bot de DAS: una cola, hilos de borde vigilados, bucle, temporizadores, latido y write-ahead.

QUÉ HACE. `Ejecutor` es el proceso que opera (§3.27, §6.1). Todo lo que pasa
entra por UNA cola (`Buzon`): mensajes de DAS (hilo `das-lector`), señales
(hilo `fuente-tuberia`), comandos (Telegram y `estado/comandos.jsonl`),
configuración nueva (`config-vigia`), caídas de hilos y el estado de la
conexión. El hilo principal saca un mensaje (o un `Tic` si en 0,2 s no llega
nada), dispara los temporizadores vencidos, pasa cada mensaje al `Decisor` (el
ÚNICO que muta el estado) y EJECUTA en orden las acciones que devuelve:
órdenes, cancelaciones, consultas, avisos, diario, temporizadores, foto del
panel, peticiones al supervisor y la salida. `arrancar()` es el flujo F12:
cerrojo → reloj (R-J-07) → hash del motor (H-6) → diario → reconstrucción del
estado (H-2) → conexión con DAS → reconciliación ANTES de nada (R-J-02.5) →
receptores y fuente de señales. `construir_desde_env` monta las piezas de
producción desde el entorno y `main` es `python -m app.bot_das.ejecutor`.

POR QUÉ ESTÁ AQUÍ. El decisor es puro respecto a la E/S; alguien tiene que
escribir el diario ANTES de mandar (M6, H-2), hablar con el socket, llevar el
reloj de los temporizadores, publicar la foto, latir para el supervisor
(R-J-04) y aplicar la política cuando el disco falla (corrección 4). Eso vive
aquí, y solo aquí: ninguna otra pieza manda nada a DAS.

LAS TRAMPAS.
  * Write-ahead (M6, riesgo 3): cada `EnviarOrden` escribe `orden_intencion`
    (con fsync) ANTES de `cliente.enviar` y `orden_enviada` (u
    `orden_simulada` en sombra) DESPUÉS; `Cancelar`/`CancelarTicker` y
    `Reemplazar` escriben `cancel_intencion`/`replace_intencion` antes. Si
    tras `anotar` el diario sigue `degradado`, el registro NO llegó al disco:
    una orden que ABRE (entrada, pirámide «add», cualquier venta en corto) y
    una compra de locate NO salen (`senal_descartada` / `locate_bloqueado` y
    aviso 3 una vez por episodio); los stops, cancelaciones, ventas de
    exceso, cierres y REPLACE SÍ salen: proteger manda sobre registrar
    (corrección 4). La orden bloqueada queda en el estado del decisor como
    SENDING sin eco: la reconciliación la cierra «sin eco» (riesgo 3).
  * El decisor se construye DESPUÉS de reconstruir el estado del diario: el
    generador de tokens arranca en el último `seq` del día (un token nunca se
    reutiliza, H-2). Por eso el `Ejecutor` recibe una FÁBRICA `estado →
    Decisor`, no un decisor ya hecho.
  * Sombra (R-O-03): el cliente es `ClienteSombra`; los mutantes van al
    `Emparejador` interno. La CUENTA de la sombra es la del emparejador: las
    consultas de cuenta (`GET BP/POSITIONS/ORDERS/TRADES/LOCATES/AccountInfo`,
    `POSREFRESH`, `SLReuseQuery`, `SLAvailQuery`) se le preguntan a él y los
    mensajes de cuenta que manda el DAS real (volcado del LOGIN, `%POS`,
    `%ORDER`, `%OrderAct`, `%TRADE`, `BP`, `#…`) se descartan; si no, la
    reconciliación («DAS manda», M7) borraría la posición simulada al primer
    barrido. El mercado (cotizaciones, halts, bandas, SHORTINFO, rutas,
    `%SLRET`) sí es el real, y cada `$Quote` real alimenta el libro del
    emparejador para que las órdenes simuladas se llenen con precios reales.
  * Un comando `Consultar` que sea mutante es un error de programación: NO
    sale (aviso 3). `EnvioProhibido` en un envío tampoco debería pasar nunca
    (el `ClienteSombra` desvía antes): si pasa se anota `orden_simulada`
    con `bug=True` y se avisa nivel 3.
  * La reconexión con DAS (R-J-02: 2/4/8/16 y luego 30 s) la lleva el
    ejecutor con `PlanReconexion`, en un hilo de un solo uso: un `connect`
    que tarde 5 s en el hilo principal pararía el latido y el supervisor
    mataría al ejecutor por colgado (3 s).
  * Latido (injerto §8.11, riesgo 30): `Latido.tocar(todo_vivo)` solo escribe
    si los hilos CRÍTICOS viven (`das-lector` + `das-emisor`, la fuente de
    señales y `avisos-envio`). Un ejecutor sordo se ve «colgado» y el
    supervisor lo relanza. Sin conexión con DAS el cliente no tiene hilos y
    eso NO cuenta como muerto (la caída de DAS la lleva el plan de
    reconexión, no el supervisor).
  * Relojes: los temporizadores y todo lo que decide van con el reloj
    inyectado (`reloj.mono()`, simulable); la CADENCIA del bucle (espera de
    la cola y el `Tic` forzado cada segundo con la cola llena) va con
    `time.monotonic()` real, porque es el ritmo del proceso, no del mercado.
  * La doble instancia (F11 e) no toca el diario ni la foto: son los
    ficheros de la instancia viva. Los fallos de reloj y de hash del motor
    ocurren ANTES de abrir el diario (orden de F12): van al log y a los
    avisos.
  * `estado/orden_supervisor.jsonl` se lee desde el tamaño que tenía al
    arrancar: una petición «parar» de un apagado anterior no para al
    ejecutor nuevo. Se lee solo hasta el último salto de línea. Lo que el
    ejecutor ESCRIBE ahí (PedirAlSupervisor) nunca es un «parar».
  * Latido del feed con una fuente EN PROCESO (`proceso`, `grabacion`): no
    hay `bot.py` que mande «latido» cada 5 s, así que el ejecutor lo saca de
    `fuente.salud()["ultimo_en"]` (R-J-01, F11 b). Sin eso el decisor daría
    el feed por muerto a los 60 s y el replay no abriría nada.
  * Replay (R-O-02): el ritmo lo marca el reloj simulado. La cola no espera
    tiempo real salvo `REPLAY_ESPERA_S` cuando acaba de salir algo por el
    socket (su respuesta entra antes de mover el reloj, con una sola vuelta
    de gracia para que un DAS mudo no congele la repetición).
  * `main` carga el `.env` de `RUTA_DOTENV` (por defecto `backend/.env`);
    los tests lo apuntan a un fichero inexistente: jamás leen el real.
  * Nada se registra con secretos: el diario lleva el limpiador de
    `FiltroSecretos` (ajuste h) y la foto pasa por el mismo antes de
    escribirse; el log tiene el filtro instalado por `main` ANTES de la
    primera línea (el `.env` se carga antes, en silencio, para conocer los
    valores que hay que tapar).
  * G2-02: en `arrancar()` el SNTP (hasta 3 s), el hash del motor (disco
    mecánico) y el `connect` con DAS (hasta 5 s) corren en un hilo de un
    solo uso mientras el principal toca el latido cada `LATIDO_ARRANQUE_S`:
    nada bloquea el hilo principal más de 1 s y el supervisor no mata por
    «colgado» a un ejecutor que solo espera a la red.
  * G2-05: `cliente.enviar` devuelve False cuando DESCARTA la línea en el acto
    (sin conexión o cola llena): entonces NO se anota `orden_enviada`, se
    anota `orden_descartada` y el decisor recibe `OrdenDescartada` (la orden
    pasa a CLOSED y se replanifican los stops, D2a-06). Lo que el emisor purga
    después (versión vieja, sesión caída) llega por `ClienteDAS.al_descartar`
    a la misma cola.
  * G1A-03 / G1B-08: la referencia de Massive (REST, 8 s de timeout, hasta 50
    páginas) NUNCA corre en el hilo del decisor. El `HiloVigilado`
    «referencia» precarga los splits del día al arrancar (reintento cada
    `REFERENCIA_SPLITS_REINTENTO_S` si fallan) y, en bucle, las fichas que el
    decisor dejó pedidas (`tomar_pendientes` + `precargar_ficha`). Sin ese
    hilo, con la `Referencia` real toda señal sería A12 y no se operaría: si
    muere sin relanzarse, aviso 3.
  * H-2 fuera de `EstadoBot`: tras `reconstruir` se siembra el decisor con
    `diario.memoria_decisor` (k de halts, veto R-F-03, control manual,
    cambios de Telegram) y los ids de comando ya vistos hoy (C-02).
  * Importar este módulo no abre red, no lee ficheros, no arranca hilos y no
    importa pandas (`BOT_DAS_FUENTE=tuberia`, injerto §8.25; lo comprueba
    `test_das_seguridad`).
"""
from __future__ import annotations

import argparse
import copy
import dataclasses
import heapq
import json
import logging
import math
import os
import queue
import re
import signal
import sys
import threading
import time
import traceback
import types
from collections import deque
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence

from app.bot_das import VERSION
from app.bot_das import avisos as mod_avisos
from app.bot_das import config as mod_config
from app.bot_das import protocolo
from app.bot_das import reloj as mod_reloj
from app.bot_das import tokens as mod_tokens
from app.bot_das.cerrojo import CerrojoInstancia, HiloVigilado, Latido
from app.bot_das.cliente import ClienteDAS, ClienteSombra, CuotaComandos, EnvioProhibido, PlanReconexion
from app.bot_das.comandos import FICHERO_OFFSET_TELEGRAM, LectorComandosFichero, ReceptorTelegram
from app.bot_das.decisor import Decisor
from app.bot_das.diario import Diario, LectorDiario, memoria_decisor, reconstruir
from app.bot_das.enlace_bot_alertas import authkey_de_entorno, direccion_de_entorno
from app.bot_das.fuente_senales import FuenteEnProceso, FuenteGrabacion, FuenteTuberia
from app.bot_das.mercado_das import MercadoDAS
from app.bot_das.reglas import rechazos
from app.bot_das.referencia_massive import Referencia
from app.bot_das.simulador_das import Emparejador, LibroSimulado
from app.bot_das.tipos import (
    LATIDO_S,
    LOCATES_INQUIRE_S,
    MAX_LV1,
    RELOJ_AVISO_S,
    RELOJ_NEGARSE_S,
    REPLACE_SHARE_ES_ABIERTA,
    Accion,
    Anotar,
    Avisar,
    Cancelar,
    CancelarTicker,
    Comando,
    ComandoRecibido,
    Config,
    ConfigNueva,
    ConexionDAS,
    Consultar,
    DeDAS,
    Desprogramar,
    EnviarOrden,
    EstadoBot,
    Fase,
    Grupo,
    HiloCaido,
    InvalidarSerie,
    Lado,
    LocateComprar,
    LocateInquire,
    LocateOferta,
    Mensaje,
    MensajeDAS,
    MsgAccountInfo,
    MsgBP,
    MsgMarcador,
    MsgOrden,
    MsgOrderAct,
    MsgPos,
    MsgQuote,
    MsgSLAvail,
    MsgSLOrder,
    MsgSLReuse,
    MsgTrade,
    Nivel,
    OrdenDescartada,
    OrdenNueva,
    Origen,
    PedirAlSupervisor,
    Programar,
    Proposito,
    PublicarFoto,
    Reemplazar,
    Salir,
    Senal,
    SenalRecibida,
    Suscribir,
    Temporizador,
    Tic,
    TipoOrden,
)
from app.bot_das.tokens import GeneradorTokens

__all__ = [
    "Buzon", "Temporizadores", "Ejecutor", "construir_desde_env", "directorio_bot", "main",
    "CODIGO_OK", "CODIGO_ERROR", "CODIGO_RELOJ", "CODIGO_DOBLE_INSTANCIA", "CODIGO_MOTOR", "CODIGO_CONFIG",
    "ESPERA_COLA_S", "TIC_MAX_S", "TEMPORIZADORES_POR_PASO", "ESPERA_RECONCILIACION_S", "RELOJ_REVISION_S",
    "ESPERA_AVISOS_S", "REPLAY_PASO_S", "REPLAY_TICS_FINALES", "REPLAY_ESPERA_S", "AVISOS_BORDE_TOPE",
    "LATIDO_FEED_S", "RUTA_DOTENV", "LATIDO_ARRANQUE_S", "REFERENCIA_ESPERA_S", "REFERENCIA_SPLITS_REINTENTO_S",
    "PETICION_REPETIR_S", "MOTIVO_NO_ENCOLADA",
    "NOMBRE_FOTO", "NOMBRE_ORDEN_SUPERVISOR", "NOMBRE_LATIDO", "NOMBRE_CERROJO", "NOMBRE_COMANDOS",
    "SUBCARPETAS_BOT", "ENV_FUENTE", "ENV_CHAT_IDS", "FUENTE_TUBERIA", "FUENTE_PROCESO", "FUENTE_GRABACION",
    "CONSULTAS_DE_CUENTA", "MENSAJES_DE_CUENTA",
]

logger = logging.getLogger("btt.bot_das.ejecutor")

# ── códigos de salida del proceso (el supervisor los registra) ─────────────
CODIGO_OK = 0                   # parada ordenada (supervisor, comando, fin de grabación)
CODIGO_ERROR = 1                # excepción no prevista en main (se relanza: R-J-04 a)
CODIGO_RELOJ = 2                # R-J-07: reloj desviado > 2 s → se niega a operar (F12)
CODIGO_DOBLE_INSTANCIA = 3      # R-J-04 c / F11 e: otra instancia tiene el cerrojo
CODIGO_MOTOR = 4                # H-6: el motor no es el de la config (F12)
CODIGO_CONFIG = 5               # config o entorno imposibles (main): relanzar no lo arregla

# ── constantes técnicas del proceso (no son reglas del libro; van en las desviaciones) ──
ESPERA_COLA_S = 0.2             # §3.27 / §6.1: cola.get(timeout=0.2); sin mensaje → Tic
TIC_MAX_S = 1.0                 # con la cola siempre llena, un Tic al menos cada segundo (latido, foto, supervisor)
TEMPORIZADORES_POR_PASO = 200   # uno que se reprograma a 0 s no puede colgar una vuelta del bucle
ESPERA_RECONCILIACION_S = 10.0  # F12: cuánto espera arrancar() la primera reconciliación (objetivo R-J-04 < 10 s)
PASO_ARRANQUE_S = 0.05          # espera de la cola mientras arrancar() espera la reconciliación
RELOJ_REVISION_S = 3600.0       # riesgo 14: desvío SNTP al arrancar y cada hora
ESPERA_AVISOS_S = 30.0          # §6.2.5: avisos.parar(30)
ESPERA_HILO_RECONEXION_S = 6.0  # al parar: plazo para un connect en curso (timeout del cliente 5 s)
REPLAY_PASO_S = 60.0            # grabación: el reloj avanza como mucho una vela por paso
REPLAY_TICS_FINALES = 3         # grabación agotada: Tics con la cola vacía antes de salir
REPLAY_ESPERA_S = 0.02          # replay: espera real por la respuesta de DAS cuando salió algo por el socket
AVISOS_BORDE_TOPE = 1000        # avisos de los hilos de borde pendientes de pasar al hilo principal
LATIDO_FEED_S = 5.0             # F11 b: cadencia del latido del feed de una fuente en proceso (la de bot.py)
LATIDO_ARRANQUE_S = 0.5         # G2-02: mientras arrancar() espera a la red (SNTP, connect) el latido se toca cada 0,5 s
REFERENCIA_ESPERA_S = 0.25      # G1A-03: el hilo «referencia» mira las fichas pedidas cada 0,25 s
REFERENCIA_SPLITS_REINTENTO_S = 60.0   # G1A-03: splits del día que fallaron se reintentan cada minuto
PETICION_REPETIR_S = 10.0       # la misma petición al supervisor como mucho cada 10 s (dedupe, como el vigilante)
CUOTA_AGOTADA_TOPE = 1000       # A-07 (sombra): anotaciones «cuota_agotada» pendientes del hilo principal
MOTIVO_NO_ENCOLADA = "descartada: el cliente no la encoló (sin conexión con DAS o cola de salida llena)"
SERVIDOR_SNTP = "time.windows.com"
RUTA_DOTENV: Optional[Path] = None   # None = backend/.env (lo carga SOLO main; un test lo apunta a otro sitio)

NOMBRE_FOTO = "foto.json"                       # §1 / panel 4.4
NOMBRE_ORDEN_SUPERVISOR = "orden_supervisor.jsonl"
NOMBRE_LATIDO = "latido_ejecutor"
NOMBRE_CERROJO = "cerrojo_ejecutor.lock"
NOMBRE_COMANDOS = "comandos.jsonl"
SUBCARPETAS_BOT = ("config", "diario", "estado", "cache", "logs")

ENV_FUENTE = "BOT_DAS_FUENTE"
ENV_CHAT_IDS = "BOT_DAS_CHAT_IDS"
ENV_TOKEN_B = "TELEGRAM_BOT_TOKEN_B"
ENV_CUENTA = "DAS_CUENTA"
ENV_DIR = "BOT_DAS_DIR"
FUENTE_TUBERIA = "tuberia"
FUENTE_PROCESO = "proceso"
FUENTE_GRABACION = "grabacion"

# Sombra (R-O-03): lo que es de la CUENTA (el emparejador) y lo que es del MERCADO (el DAS real).
CONSULTAS_DE_CUENTA = frozenset({"GET BP", "GET POSITIONS", "GET ORDERS", "GET TRADES", "GET LOCATES",
                                 "GET ACCOUNTINFO", "POSREFRESH", "SLREUSEQUERY", "SLAVAILQUERY"})
MENSAJES_DE_CUENTA = (MsgPos, MsgOrden, MsgOrderAct, MsgTrade, MsgBP, MsgAccountInfo, MsgSLOrder, MsgSLReuse,
                      MsgSLAvail, MsgMarcador)

_PROPOSITOS_APERTURA = frozenset({Proposito.ENTRADA_AGREGAR, Proposito.ENTRADA_CRUCE})
_RE_FECHA_GRABACION = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_TOLERANCIA_S = 1e-9


# ══════════════════════════════════════════════════════════════════════
# Buzón: la cola única del ejecutor (§6.1)
# ══════════════════════════════════════════════════════════════════════
class Buzon:
    """La cola SIN tope del ejecutor y los callbacks de los hilos de borde, que SOLO encolan (§6.1).

    Una señal no se tira jamás (la cola no tiene tope; el ejecutor avisa si
    pasa del umbral). Los avisos de los hilos de borde (cliente: cola de
    salida llena; fuente: tubería rechazada…) se guardan aparte con tope y
    los convierte en `Avisar` el hilo principal: así el diario y la cola de
    avisos se escriben siempre desde el mismo hilo. La captura de mensajes
    SIMULADOS (sombra) solo la usa el hilo principal mientras manda una
    orden al emparejador: da los `fills_simulados` de `orden_simulada`.
    """

    def __init__(self) -> None:
        self._cola: "queue.Queue[Mensaje]" = queue.Queue()
        self._avisos: deque[tuple[Nivel, str, Optional[str]]] = deque()
        self._cerrojo = threading.Lock()
        self._captura: Optional[list[MensajeDAS]] = None
        self._hilo_captura: Optional[int] = None
        self._cuotas: deque[tuple[str, float]] = deque(maxlen=CUOTA_AGOTADA_TOPE)
        self.avisos_perdidos = 0

    # ── cola ──
    def poner(self, msg: Mensaje) -> None:
        """Encola un `Mensaje` (put_nowait: nunca bloquea). TypeError si no es un `Mensaje`."""
        if not isinstance(msg, Mensaje):
            raise TypeError(f"el buzón solo admite Mensaje, no {type(msg).__name__}")
        self._cola.put_nowait(msg)

    def sacar(self, espera_s: float) -> Optional[Mensaje]:
        """El siguiente mensaje o None si en `espera_s` no llega ninguno (0 = sin esperar)."""
        try:
            if espera_s > 0:
                return self._cola.get(timeout=espera_s)
            return self._cola.get_nowait()
        except queue.Empty:
            return None

    def tamano(self) -> int:
        """Mensajes esperando (para la foto y el aviso de cola grande, riesgo 17)."""
        return self._cola.qsize()

    # ── callbacks de los hilos de borde (solo encolan) ──
    def al_mensaje(self, msg: MensajeDAS, simulado: bool = False) -> None:
        """`ClienteDAS.al_mensaje(msg)` y `ClienteSombra.al_mensaje(msg, True)` → `DeDAS`."""
        if simulado and self._captura is not None and threading.get_ident() == self._hilo_captura:
            self._captura.append(msg)
        self.poner(DeDAS(msg, bool(simulado)))

    def al_estado(self, conectado: bool, motivo: str) -> None:
        """`ClienteDAS.al_estado` → `ConexionDAS` (R-J-02)."""
        self.poner(ConexionDAS(bool(conectado), str(motivo)))

    def al_senal(self, senal: Senal) -> None:
        """Destino de la fuente de señales → `SenalRecibida`."""
        self.poner(SenalRecibida(senal))

    def al_comando(self, comando: Comando) -> None:
        """Receptores de Telegram y del cuadro → `ComandoRecibido`."""
        self.poner(ComandoRecibido(comando))

    def al_config(self, cfg: Config, aviso: Optional[str]) -> None:
        """`VigilanteConfig.al_cambio` → `ConfigNueva` (CM1)."""
        self.poner(ConfigNueva(cfg, aviso))

    def al_caida_hilo(self, nombre: str, error: str, relanzado: bool) -> None:
        """Caída de un `HiloVigilado` de borde → `HiloCaido` (F11 g)."""
        self.poner(HiloCaido(str(nombre), str(error), bool(relanzado)))

    def al_descartar(self, msg: OrdenDescartada) -> None:
        """D2a-06 / G2-05: `ClienteDAS.al_descartar` (un NEWORDER que el emisor NO mandó) → la cola del decisor."""
        if not isinstance(msg, OrdenDescartada):
            raise TypeError(f"al_descartar espera una OrdenDescartada, no {type(msg).__name__}")
        self.poner(msg)

    def al_cuota_agotada(self, linea: str, espera_s: float) -> None:
        """A-07 (sombra): `ClienteSombra.al_cuota_agotada`; el hilo principal lo anota como «cuota_agotada»."""
        try:
            espera = float(espera_s)
        except (TypeError, ValueError):
            espera = float("nan")
        with self._cerrojo:
            self._cuotas.append((str(linea), espera))

    def cuotas_pendientes(self) -> list[tuple[str, float]]:
        """Saca (y vacía) las cuotas agotadas de la sombra pendientes de anotar."""
        with self._cerrojo:
            salida = list(self._cuotas)
            self._cuotas.clear()
        return salida

    def al_aviso(self, texto: str) -> None:
        """Aviso del cliente de DAS (nivel 2: cola de salida llena, líneas descartadas sin conexión)."""
        self._guardar_aviso(Nivel.AVISO, texto, None)

    def al_aviso_nivel(self, nivel: int, texto: str) -> None:
        """Aviso de la fuente de señales con su nivel (1-3)."""
        try:
            n = Nivel(int(nivel))
        except (TypeError, ValueError):
            n = Nivel.AVISO
        self._guardar_aviso(n, texto, None)

    def avisos_pendientes(self) -> list[tuple[Nivel, str, Optional[str]]]:
        """Saca (y vacía) los avisos de borde pendientes, en orden."""
        with self._cerrojo:
            salida = list(self._avisos)
            self._avisos.clear()
        return salida

    def _guardar_aviso(self, nivel: Nivel, texto: str, clave: Optional[str]) -> None:
        with self._cerrojo:
            if len(self._avisos) >= AVISOS_BORDE_TOPE:
                self._avisos.popleft()
                self.avisos_perdidos += 1
            self._avisos.append((nivel, str(texto), clave))

    # ── captura de mensajes simulados (solo el hilo principal) ──
    def empezar_captura(self) -> None:
        self._captura = []
        self._hilo_captura = threading.get_ident()

    def terminar_captura(self) -> list[MensajeDAS]:
        capturados = self._captura or []
        self._captura = None
        self._hilo_captura = None
        return capturados


# ══════════════════════════════════════════════════════════════════════
# Temporizadores (§6.1: heap en el hilo principal)
# ══════════════════════════════════════════════════════════════════════
class Temporizadores:
    """Heap `(cuando, orden, clave)` sobre el reloj monotónico inyectado (§6.1).

    `programar` con una clave que ya existe la SUSTITUYE; `desprogramar` de
    una clave inexistente no hace nada (supuestos del decisor). Los vencidos
    salen por (cuando, orden de programación). Las entradas sustituidas se
    quedan en el heap y se ignoran al sacarlas (borrado perezoso).
    """

    def __init__(self) -> None:
        self._heap: list[tuple[float, int, str]] = []
        self._vigentes: dict[str, tuple[float, int, dict]] = {}
        self._n = 0

    def programar(self, clave: str, cuando: float, datos: Optional[dict] = None) -> None:
        if not isinstance(clave, str) or not clave:
            raise ValueError(f"clave de temporizador inválida: {clave!r}")
        if isinstance(cuando, bool) or not isinstance(cuando, (int, float)) or not math.isfinite(cuando):
            raise ValueError(f"instante de temporizador inválido: {cuando!r}")
        self._n += 1
        self._vigentes[clave] = (float(cuando), self._n, dict(datos or {}))
        heapq.heappush(self._heap, (float(cuando), self._n, clave))

    def desprogramar(self, clave: str) -> bool:
        """True si había un temporizador con esa clave."""
        return self._vigentes.pop(clave, None) is not None

    def proximo(self) -> Optional[float]:
        """Instante del próximo temporizador vigente, o None."""
        self._limpiar_cima()
        return self._heap[0][0] if self._heap else None

    def sacar_vencido(self, ahora: float) -> Optional[tuple[str, dict]]:
        """(clave, datos) del primer temporizador con `cuando ≤ ahora`, retirado; None si no hay."""
        self._limpiar_cima()
        if not self._heap or self._heap[0][0] > ahora + _TOLERANCIA_S:
            return None
        _, _, clave = heapq.heappop(self._heap)
        _, _, datos = self._vigentes.pop(clave)
        return clave, datos

    def cuando(self, clave: str) -> Optional[float]:
        vigente = self._vigentes.get(clave)
        return vigente[0] if vigente is not None else None

    def claves(self) -> list[str]:
        """Claves vigentes por orden de vencimiento."""
        return [clave for clave, _ in sorted(self._vigentes.items(), key=lambda kv: (kv[1][0], kv[1][1]))]

    def __len__(self) -> int:
        return len(self._vigentes)

    def _limpiar_cima(self) -> None:
        while self._heap:
            cuando, n, clave = self._heap[0]
            vigente = self._vigentes.get(clave)
            if vigente is not None and vigente[1] == n:
                return
            heapq.heappop(self._heap)


# ══════════════════════════════════════════════════════════════════════
# Ejecutor
# ══════════════════════════════════════════════════════════════════════
class Ejecutor:
    """El proceso que opera (§3.27, §5 F11-F13, §6): bucle único, write-ahead, latido y política de disco.

    `decisor` es una FÁBRICA `EstadoBot → Decisor` (se llama en `arrancar`,
    tras reconstruir el estado del diario). `cliente` es un `ClienteDAS` o un
    `ClienteSombra` (o un doble con enviar/invalidar/conectar/cerrar/
    conectado/hilos_vivos). `fuente` cumple el Protocol `FuenteSenales`.
    `receptores` son objetos con arrancar()/parar() (Telegram, comandos del
    cuadro). `ruta_estado` es `BOT_DAS_DIR/estado`. Solo por nombre:
    `buzon` (la cola; la comparten los callbacks del cliente y la fuente),
    `base` (directorio backend para el hash del motor), `hash_motor`,
    `medir_desvio` (inyectables en tests), `lector` (por defecto
    `ruta_estado/../diario`), `plan_reconexion`, `aviso_config` (H-4, se
    avisa al arrancar), `limpiar` (FiltroSecretos para la foto),
    `espera_reconciliacion_s`, `espera_avisos_s`, `paso_replay` (gancho
    `(t, vela)` de `FuenteGrabacion.reproducir`) y `referencia` (la
    `referencia_massive.Referencia` que usa el decisor: si ofrece la precarga
    —`precargar_splits`, `tomar_pendientes`, `precargar_ficha`— el ejecutor
    arranca el `HiloVigilado` «referencia», G1A-03; una referencia en
    memoria o None no arranca nada).

    Hilos: `arrancar`, `paso`, `correr`, `ejecutar` y `parar` se llaman
    desde el hilo principal; `pedir_parada` desde cualquiera.
    """

    def __init__(self, cfg: Config, cliente: Any, fuente: Any, diario: Diario, avisos: Any, mercado: MercadoDAS,
                 decisor: Callable[[EstadoBot], Decisor], reloj: Any, latido: Latido, cerrojo: CerrojoInstancia,
                 receptores: list, config_watch: Any, ruta_estado: Path, *,
                 buzon: Optional[Buzon] = None, base: Optional[Path] = None,
                 hash_motor: Optional[Callable[[Path], str]] = None,
                 medir_desvio: Optional[Callable[[], Optional[float]]] = None,
                 lector: Optional[LectorDiario] = None, plan_reconexion: Optional[PlanReconexion] = None,
                 aviso_config: Optional[str] = None, limpiar: Optional[Callable[[str], str]] = None,
                 espera_reconciliacion_s: float = ESPERA_RECONCILIACION_S,
                 espera_avisos_s: float = ESPERA_AVISOS_S,
                 paso_replay: Optional[Callable[[datetime, dict], None]] = None,
                 referencia: Any = None) -> None:
        if not isinstance(cfg, Config):
            raise TypeError(f"cfg debe ser una Config, no {type(cfg).__name__}")
        for nombre in ("enviar", "invalidar", "conectar", "cerrar"):
            if not callable(getattr(cliente, nombre, None)):
                raise TypeError(f"cliente debe tener {nombre}()")
        for nombre in ("arrancar", "parar", "salud"):
            if not callable(getattr(fuente, nombre, None)):
                raise TypeError(f"fuente debe cumplir FuenteSenales: falta {nombre}()")
        if not isinstance(diario, Diario):
            raise TypeError(f"diario debe ser un Diario, no {type(diario).__name__}")
        for nombre in ("poner", "arrancar", "parar"):
            if not callable(getattr(avisos, nombre, None)):
                raise TypeError(f"avisos debe tener {nombre}() (ColaAvisos)")
        if not isinstance(mercado, MercadoDAS):
            raise TypeError(f"mercado debe ser un MercadoDAS, no {type(mercado).__name__}")
        if isinstance(decisor, Decisor) or not callable(decisor):
            raise TypeError("decisor debe ser una FÁBRICA estado → Decisor (el decisor se crea tras reconstruir, H-2)")
        for nombre in ("mono", "ahora", "hoy", "epoch"):
            if not callable(getattr(reloj, nombre, None)):
                raise TypeError(f"reloj debe tener {nombre}()")
        if not isinstance(latido, Latido):
            raise TypeError("latido debe ser un cerrojo.Latido")
        if not isinstance(cerrojo, CerrojoInstancia):
            raise TypeError("cerrojo debe ser un cerrojo.CerrojoInstancia")
        receptores = list(receptores or [])
        for r in receptores:
            if not (callable(getattr(r, "arrancar", None)) and callable(getattr(r, "parar", None))):
                raise TypeError(f"receptor sin arrancar()/parar(): {r!r}")
        if config_watch is not None and not (callable(getattr(config_watch, "arrancar", None))
                                             and callable(getattr(config_watch, "parar", None))):
            raise TypeError("config_watch debe tener arrancar()/parar() o ser None")
        for nombre, valor in (("espera_reconciliacion_s", espera_reconciliacion_s), ("espera_avisos_s", espera_avisos_s)):
            if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor) or valor < 0:
                raise ValueError(f"{nombre} debe ser un número finito ≥ 0: {valor!r}")
        for nombre, valor in (("hash_motor", hash_motor), ("medir_desvio", medir_desvio), ("limpiar", limpiar),
                              ("paso_replay", paso_replay)):
            if valor is not None and not callable(valor):
                raise TypeError(f"{nombre} debe ser un callable o None")
        self._cfg = cfg
        self._cliente = cliente
        self._fuente = fuente
        self._diario = diario
        self._avisos = avisos
        self._mercado = mercado
        self._fabrica = decisor
        self._reloj = reloj
        self._latido = latido
        self._cerrojo = cerrojo
        self._receptores = receptores
        self._config_watch = config_watch
        self._ruta_estado = Path(ruta_estado)
        self._buzon = buzon if buzon is not None else Buzon()
        self._base = Path(base) if base is not None else Path(__file__).resolve().parents[2]
        self._hash_motor = hash_motor if hash_motor is not None else mod_config.motor_hash
        self._medir_desvio = medir_desvio if medir_desvio is not None else self._desvio_por_defecto
        self._lector = lector if lector is not None else LectorDiario(self._ruta_estado.parent / "diario")
        self._plan = plan_reconexion if plan_reconexion is not None else _plan_de(cfg)
        self._aviso_config = aviso_config
        self._limpiar = limpiar
        self._espera_reconciliacion_s = float(espera_reconciliacion_s)
        self._espera_avisos_s = float(espera_avisos_s)
        self._paso_replay = paso_replay
        self._referencia = referencia
        self._hilo_referencia: Optional[HiloVigilado] = None
        self._aviso_referencia_dado = False
        self._peticion_en: dict[str, float] = {}
        self._sombra = isinstance(cliente, ClienteSombra)
        self._parser_sombra: Optional[protocolo.Parser] = (
            protocolo.Parser(cliente.real.es_nuestro, watch=False, cuenta=cliente.real.cuenta) if self._sombra else None)
        self._temporizadores = Temporizadores()
        self._decisor: Optional[Decisor] = None
        # ciclo de vida
        self._arrancado = False
        self._listo = False
        self._parado = False
        self._diario_abierto = False
        self._fuente_arrancada = False
        self._fuente_fallo: Optional[str] = None
        self._codigo: Optional[int] = None
        self._motivo_salida = ""
        self._parada = threading.Event()
        self._codigo_parada = CODIGO_OK
        self._motivo_parada = ""
        self._ultimo_tic = time.monotonic()
        # reconexión (R-J-02)
        self._reconectar_en: Optional[float] = None
        self._hilo_reconexion: Optional[threading.Thread] = None
        self._resultado_reconexion: Optional[bool] = None
        # reloj (R-J-07, riesgo 14)
        self._reloj_revisado_en: Optional[float] = None
        self._hilo_reloj: Optional[threading.Thread] = None
        self._desvio_medido: Optional[tuple[Optional[float]]] = None
        self._cerrojo_reloj = threading.Lock()
        # vigilancia propia
        self._orden_offset = 0
        self._aviso_disco = False
        self._cola_avisada = False
        self._latido_retenido: Optional[dict] = None
        self._sombra_ignorados: dict[str, int] = {}
        self._foto_fallos = 0
        self._tics_fin_grabacion = 0
        self._grabacion_agotada = False
        self._latido_fuente_en: Optional[float] = None
        self._latido_fuente_ultimo: Optional[float] = None
        self._al_socket = 0                  # líneas al socket de DAS desde el último Tic (ritmo del replay)
        self._replay_retenido = False
        self._enviadas = 0
        self._bloqueadas = 0

    # ── propiedades (lectura) ──
    @property
    def cfg(self) -> Config:
        """La config efectiva: la del decisor si ya existe (cambia en caliente), si no la de arranque."""
        return self._decisor.cfg if self._decisor is not None else self._cfg

    @property
    def decisor(self) -> Optional[Decisor]:
        """El decisor (None antes de `arrancar`)."""
        return self._decisor

    @property
    def buzon(self) -> Buzon:
        return self._buzon

    @property
    def cliente(self) -> Any:
        return self._cliente

    @property
    def fuente(self) -> Any:
        return self._fuente

    @property
    def diario(self) -> Diario:
        return self._diario

    @property
    def mercado(self) -> MercadoDAS:
        return self._mercado

    @property
    def avisos(self) -> Any:
        return self._avisos

    @property
    def temporizadores(self) -> Temporizadores:
        return self._temporizadores

    @property
    def receptores(self) -> tuple:
        """Los receptores de comandos (cuadro y, si hay credenciales, Telegram), en el orden en que arrancan."""
        return tuple(self._receptores)

    @property
    def sombra(self) -> bool:
        """True si el cliente es un `ClienteSombra` (R-O-03)."""
        return self._sombra

    @property
    def codigo(self) -> Optional[int]:
        """Código de salida si el bucle ya terminó (Salir, supervisor o parada pedida)."""
        return self._codigo

    @property
    def ruta_foto(self) -> Path:
        return self._ruta_estado / NOMBRE_FOTO

    @property
    def ruta_orden_supervisor(self) -> Path:
        return self._ruta_estado / NOMBRE_ORDEN_SUPERVISOR

    # ══════════════════════════ ciclo de vida ═══════════════════════════
    def arrancar(self) -> int:
        """F12 (R-C-10, R-J-06, R-J-07, H-2, H-6, R-O-01, R-J-02.5). Devuelve 0 o el código de la salida.

        Orden: cerrojo (R-J-04 c; ocupado → aviso 3 y 3) → desvío SNTP y
        `veredicto_reloj` (> 2 s → aviso 3 y 2) → `motor_hash(base) ==
        cfg.motor_hash` (si no → aviso 3 y 4) → `diario.abrir_dia` (cabecera
        con versión, hashes y desvío, R-O-01) → `reconstruir(LectorDiario.leer
        (hoy))` y la fábrica del decisor (H-2) → `cliente.conectar()` →
        `decisor.arrancar` (GET RouteStatus/BP/AccountInfo/INTMSGS,
        SLRouteMinCharge; intentos a medias; temporizadores de salida) → se
        procesa la cola hasta la PRIMERA reconciliación (volcado del LOGIN,
        `AcumuladorVolcado`) o `espera_reconciliacion_s` → config, receptores
        y, solo entonces, la fuente de señales. Trampas: la doble instancia no
        escribe en el diario de la viva; sin DAS se arranca igual (modo
        degradado «das», reconexión por plan) porque los stops residentes y
        el vigilante protegen y relanzar no conecta antes.
        """
        if self._arrancado:
            raise RuntimeError("arrancar() solo se llama una vez por Ejecutor")
        self._arrancado = True
        self._orden_offset = self._tamano_fichero(self.ruta_orden_supervisor)
        self._avisos.arrancar()
        # 1. cerrojo de instancia única (R-J-04 c, F11 e)
        if not self._cerrojo.adquirir():
            pid = CerrojoInstancia.pid_guardado(self._cerrojo.ruta)
            return self._fallo_de_arranque(CODIGO_DOBLE_INSTANCIA, "doble_instancia",
                                           f"Ya hay un ejecutor en marcha (PID {pid}): esta instancia NO arranca "
                                           f"(R-J-04 c). La viva sigue al mando.")
        self._tocar_latido()
        # 2. reloj (R-J-07); G2-02: el UDP puede tardar 3 s → en un hilo, con latido
        desvio = self._con_latido("reloj-sntp-arranque", self._medir_desvio_seguro)
        puede, texto_reloj = mod_reloj.veredicto_reloj(desvio, *self._umbrales_reloj())
        self._reloj_revisado_en = self._reloj.mono()
        if not puede:
            return self._fallo_de_arranque(CODIGO_RELOJ, "reloj",
                                           f"Reloj desviado {desvio:+.2f} s respecto a SNTP: el ejecutor se NIEGA a "
                                           f"operar (R-J-07). Sincroniza la hora y relanza.")
        # 3. hash del motor compartido (H-6, R-O-01); G2-02: lee ficheros (disco mecánico) → en un hilo, con latido
        hash_real, error_hash = self._con_latido("hash-motor", self._hash_motor_seguro)
        if hash_real != self._cfg.motor_hash:
            detalle = f"no se pudo calcular ({error_hash})" if error_hash else f"calculado {hash_real}"
            return self._fallo_de_arranque(CODIGO_MOTOR, "motor_hash",
                                           f"El motor NO es el de la configuración (esperado {self._cfg.motor_hash}; "
                                           f"{detalle}): el ejecutor no opera (H-6). Exporta la config de nuevo.")
        self._tocar_latido()
        # 4. diario del día (R-O-01)
        hoy = self._reloj.hoy()
        self._diario.abrir_dia(hoy, motor_hash=self._cfg.motor_hash, config_version=self._cfg.config_version,
                               estrategias_hash=self._cfg.estrategias_hash, reloj_desvio_s=desvio)
        self._diario_abierto = True
        self._diario.anotar("config", config_version=self._cfg.config_version, sha256=self._cfg.sha256,
                            fase=self._cfg.fase.value, generado_at=self._cfg.generado_at,
                            motor_hash=self._cfg.motor_hash, regla="R-O-01")
        if self._diario.degradado:
            self._avisar_directo(Nivel.MAXIMO, "El diario NO se puede escribir al arrancar: no se abrirán entradas "
                                               "hasta que vuelva; stops y cierres siguen (corrección 4)",
                                 "diario_arranque")
        if texto_reloj is not None:
            self._diario.anotar("reloj", desvio_s=desvio, puede_operar=True, texto=texto_reloj, regla="R-J-07")
            self._avisar_directo(Nivel.AVISO, f"Reloj: {texto_reloj} (R-J-07)", "reloj_arranque")
        if self._aviso_config:
            # R2-PRO-3 (SEG-02): usar el último bueno bajó la fase a SOMBRA → el bot deja de operar dinero real: aviso 3
            forzada = mod_config.AVISO_FASE_FORZADA in self._aviso_config
            self._avisar_directo(Nivel.MAXIMO if forzada else Nivel.AVISO, self._aviso_config, "config_respaldo")
        # 5. estado desde el diario (H-2); A-02: el REPLACE confirmado se lee con el interruptor de la config
        # G2-02: un diario grande en el disco mecánico puede tardar: se lee y se reconstruye con el latido tocándose
        registros = self._con_latido("diario-leer", lambda: self._lector.leer(hoy))
        estado = self._con_latido("diario-reconstruir", lambda: reconstruir(
            registros, hoy, replace_share_es_abierta=_share_es_abierta(self._cfg)))
        if estado.fase is not self._cfg.fase:
            self._diario.anotar("fase", diario=estado.fase.value, config=self._cfg.fase.value,
                                nota="manda la fase de la config (R-O-03)")
            estado.fase = self._cfg.fase                 # antes de existir el decisor: preparación, no mutación en marcha
        self._diario.anotar("reconstruccion", registros=len(registros), senales_vistas=len(estado.senales_vistas),
                            posiciones=sorted(estado.posiciones), ordenes=len(estado.ordenes),
                            ultimo_seq_token=estado.ultimo_seq_token, regla="H-2")
        decisor = self._fabrica(estado)
        if not isinstance(decisor, Decisor):
            raise TypeError(f"la fábrica del decisor devolvió {type(decisor).__name__}, no un Decisor")
        if decisor.estado is not estado:
            raise ValueError("la fábrica del decisor debe usar el estado reconstruido que recibe (H-2)")
        self._decisor = decisor
        self._sembrar_memoria(registros, hoy)
        self._arrancar_referencia()
        self._tocar_latido()
        # 6. conexión con DAS (R-J-02); G2-02: el connect puede tardar 5 s → en un hilo, con latido
        conectado = self._con_latido("das-conexion-arranque", self._conectar_seguro)
        if not conectado:
            self._buzon.poner(ConexionDAS(False, "no se pudo conectar con DAS al arrancar (R-J-02)"))
        # 7. F12/F13 del decisor: nada que abra sale hasta reconciliar (el decisor arranca degradado)
        self._ejecutar_todas(self._decisor.arrancar(self._reloj.mono(), self._reloj.ahora()))
        # 8. la reconciliación ANTES de nada (R-J-02.5)
        if conectado:
            self._esperar_reconciliacion()
        if self._codigo is not None:
            return self._codigo
        # 9. config en caliente, receptores de comandos y, al final, la fuente de señales
        self._arrancar_bordes()
        self._listo = True
        self._diario.anotar("ejecutor_listo", fase=self._cfg.fase.value, das_conectado=bool(self._conectado()),
                            reconciliado=self._decisor.estado.reconciliacion_ok_en is not None,
                            fuente=type(self._fuente).__name__, fuente_arrancada=self._fuente_arrancada,
                            sombra=self._sombra, version=VERSION, pid=os.getpid())
        self._tocar_latido()
        return CODIGO_OK

    def correr(self) -> int:
        """Bucle principal (§3.27, §6.1): `paso()` hasta un `Salir`, la orden «parar» del supervisor o `pedir_parada`.

        Devuelve el código de salida (0 en una parada ordenada). Lanza
        RuntimeError si `arrancar()` no devolvió 0.
        """
        if not self._listo:
            raise RuntimeError("correr() exige un arrancar() que haya devuelto 0")
        while True:
            codigo = self.paso()
            if codigo is not None:
                return codigo

    def paso(self, espera_s: float = ESPERA_COLA_S) -> Optional[int]:
        """Una vuelta del bucle (§6.1). Devuelve el código de salida si hay que parar, o None.

        (1) parada pedida → salir; (2) avisos de los hilos de borde → Avisar;
        (3) reconexión con DAS si toca (R-J-02); (4) temporizadores vencidos,
        en orden (como mucho `TEMPORIZADORES_POR_PASO`); (5) un mensaje de la
        cola esperando hasta `espera_s` (o menos si vence un temporizador);
        (6) `Tic` si no llegó nada o si hace más de `TIC_MAX_S` del último; (7)
        latido con los hilos críticos (injerto §8.11). En el replay (R-O-02)
        el ritmo lo marca el reloj simulado: la espera real es 0, o
        `REPLAY_ESPERA_S` si desde el último Tic salió algo por el socket (su
        respuesta debe entrar antes de mover el reloj).
        """
        if self._decisor is None:
            raise RuntimeError("paso() antes de arrancar()")
        if self._codigo is not None:
            return self._codigo
        if self._parada.is_set():
            self._salir(self._codigo_parada, self._motivo_parada)
            return self._codigo
        self._drenar_avisos_de_borde()
        self._revisar_reconexion()
        self._disparar_temporizadores()
        if self._codigo is not None:
            return self._codigo
        espera = self._espera_hasta_proximo(espera_s)
        if self._en_replay():
            espera = min(espera, REPLAY_ESPERA_S if self._al_socket else 0.0)
        msg = self._buzon.sacar(espera)
        if msg is not None:
            self._procesar(msg)
        if self._codigo is None and (msg is None or time.monotonic() - self._ultimo_tic >= TIC_MAX_S):
            self._tic(cola_vacia=msg is None)
        self._tocar_latido()
        return self._codigo

    def pedir_parada(self, motivo: str = "parada pedida", codigo: int = CODIGO_OK) -> None:
        """Pide al bucle que pare en la próxima vuelta (seguro desde cualquier hilo: señales de consola, tests)."""
        self._codigo_parada = int(codigo)
        self._motivo_parada = str(motivo)
        self._parada.set()

    def parar(self) -> None:
        """Parada ordenada (§6.2.5): fuente, receptores, config, `cliente.cerrar` (QUIT), `avisos.parar(30)`, diario, cerrojo.

        Idempotente; nunca lanza (cada paso es una frontera). Con el diario
        abierto deja `parada` y la última foto. La doble instancia no toca el
        diario ni la foto (son de la viva).
        """
        if self._parado:
            return
        self._parado = True
        self._listo = False
        motivo = self._motivo_salida or self._motivo_parada or "parada"
        if self._fuente_arrancada:
            self._seguro("fuente.parar", self._fuente.parar)
            self._fuente_arrancada = False
        for receptor in self._receptores:
            self._seguro(f"{type(receptor).__name__}.parar", receptor.parar)
        if self._config_watch is not None:
            self._seguro("config_watch.parar", self._config_watch.parar)
        if self._diario_abierto:
            self._seguro("diario.anotar(parada)",
                         lambda: self._diario.anotar("parada", codigo=self._codigo, motivo=motivo,
                                                     enviadas=self._enviadas, bloqueadas=self._bloqueadas))
            self._seguro("publicar foto final", lambda: self._publicar_foto(parado=True))
        hilo = self._hilo_reconexion
        if hilo is not None:
            hilo.join(ESPERA_HILO_RECONEXION_S)
        if self._hilo_referencia is not None:
            # G1A-03: un GET a Massive en curso tarda como mucho su timeout; el hilo es daemon y no retiene el proceso
            self._seguro("referencia.parar", lambda: self._hilo_referencia.parar(0.5))
        self._seguro("cliente.cerrar", self._cliente.cerrar)
        self._seguro("avisos.parar", lambda: self._avisos.parar(self._espera_avisos_s))
        self._seguro("diario.cerrar", self._diario.cerrar)
        if self._cerrojo.tomado:
            self._seguro("cerrojo.soltar", self._cerrojo.soltar)

    # ══════════════════════════ ejecución de acciones ═════════════════════
    def ejecutar(self, a: Accion) -> None:
        """Ejecuta UNA acción del decisor (§3.27), con el diario delante de lo irreversible (M6).

        EnviarOrden: `orden_intencion` (fsync) → [corrección 4: sin registro
        en disco no sale nada que ABRA] → `cliente.enviar(línea, serie,
        versión)` → `orden_enviada` (u `orden_simulada` en sombra, con los
        fills simulados). Cancelar/CancelarTicker: `cancel_intencion` → CANCEL
        / CANCEL ALLSYMB. Reemplazar: `replace_intencion` → REPLACE (STOPLMT
        si lleva stop, límite si lleva precio, MKT si ninguno). InvalidarSerie
        → `cliente.invalidar` (injerto §8.6). Consultar/Suscribir/Locate* →
        su comando (un Consultar mutante NO sale). Avisar → `avisos.poner` +
        `aviso`. Anotar → diario. Programar/Desprogramar → heap. PublicarFoto
        → `estado/foto.json` atómico. PedirAlSupervisor →
        `estado/orden_supervisor.jsonl`. Salir → termina el bucle con su
        código. TypeError si `a` no es una Accion.
        """
        if not isinstance(a, Accion):
            raise TypeError(f"ejecutar espera una Accion, no {type(a).__name__}")
        if isinstance(a, Anotar):
            self._anotar(a)
        elif isinstance(a, Avisar):
            self._avisar(a)
        elif isinstance(a, EnviarOrden):
            self._enviar_orden(a)
        elif isinstance(a, Cancelar):
            self._cancelar(a)
        elif isinstance(a, CancelarTicker):
            self._cancelar_ticker(a)
        elif isinstance(a, Reemplazar):
            self._reemplazar(a)
        elif isinstance(a, InvalidarSerie):
            self._invalidar(a)
        elif isinstance(a, Consultar):
            self._consultar(a)
        elif isinstance(a, Suscribir):
            self._mandar_simple("Suscribir", lambda: protocolo.cmd_sb(a.ticker) if a.alta else protocolo.cmd_unsb(a.ticker))
        elif isinstance(a, LocateInquire):
            self._mandar_simple("LocateInquire", lambda: protocolo.cmd_sl_inquire(a.ticker, a.qty, a.ruta))
        elif isinstance(a, LocateComprar):
            self._locate_comprar(a)
        elif isinstance(a, LocateOferta):
            self._locate_oferta(a)
        elif isinstance(a, Programar):
            self._programar(a)
        elif isinstance(a, Desprogramar):
            self._temporizadores.desprogramar(a.clave)
        elif isinstance(a, PublicarFoto):
            self._publicar_foto()
        elif isinstance(a, PedirAlSupervisor):
            self._pedir_al_supervisor(a)
        elif isinstance(a, Salir):
            self._salir(a.codigo, a.motivo)
        else:
            self._diario.anotar("accion_desconocida", tipo=type(a).__name__)

    # ── órdenes (M6, corrección 4, R-O-03) ──
    def _enviar_orden(self, a: EnviarOrden) -> None:
        o = a.orden
        try:
            linea = protocolo.cmd_neworder(o)
        except (TypeError, ValueError) as exc:  # frontera de mensaje: una orden imposible no sale (riesgo 12)
            self._accion_invalida("EnviarOrden", exc, token=o.token, ticker=o.ticker)
            return
        self._diario.anotar("orden_intencion", **self._datos_orden(o, a.serie, linea))
        if self._diario.degradado and _es_apertura(o):
            self._bloquear_por_disco("senal_descartada", o.ticker, {
                "token": o.token, "lote_id": o.lote_id, "proposito": o.proposito.value, "qty": o.qty,
                "motivo": "diario no escribible: sin orden_intencion en disco no sale una orden que abre"})
            return
        try:
            simulados, encolada = self._enviar_linea(linea, a.serie, o.version)
        except EnvioProhibido as exc:  # frontera (R-O-03): no debería pasar nunca; si pasa es un bug y no sale nada
            self._diario.anotar("orden_simulada", token=o.token, ticker=o.ticker, bug=True, error=str(exc),
                                fills_simulados=[], regla="R-O-03")
            self._avisar_directo(Nivel.MAXIMO, f"BUG: una orden mutante llegó al cliente de solo lectura y NO salió "
                                               f"({o.ticker}, token {o.token}); revisa la construcción del cliente "
                                               f"(R-O-03)", f"envio_prohibido:{o.token}")
            return
        except (TypeError, ValueError) as exc:  # frontera de mensaje: línea inválida para el socket
            self._accion_invalida("EnviarOrden", exc, token=o.token, ticker=o.ticker)
            return
        if not encolada:
            # G2-05 (M6, riesgo 3): el cliente la DESCARTÓ en el acto: el diario no puede decir que salió. El decisor la
            # pasa a CLOSED y replanifica los stops (D2a-06); con DAS caído lo hace la reconciliación al reconectar.
            self._diario.anotar("orden_descartada", token=o.token, ticker=o.ticker, proposito=o.proposito.value,
                                serie=a.serie, version=o.version, motivo=MOTIVO_NO_ENCOLADA, donde="ejecutor",
                                regla="G2-05")
            self._buzon.poner(OrdenDescartada(token=o.token, serie=a.serie, version=o.version,
                                              motivo=MOTIVO_NO_ENCOLADA, ticker=o.ticker))
            return
        self._enviadas += 1
        if self._sombra:
            self._diario.anotar("orden_simulada", token=o.token, ticker=o.ticker, proposito=o.proposito.value,
                                fills_simulados=_fills_simulados(simulados), regla="R-O-03")
        else:
            self._diario.anotar("orden_enviada", token=o.token, ticker=o.ticker, proposito=o.proposito.value,
                                serie=a.serie, version=o.version, regla="M6")

    def _cancelar(self, a: Cancelar) -> None:
        try:
            linea = protocolo.cmd_cancel(a.id_das)
        except (TypeError, ValueError) as exc:  # frontera de mensaje
            self._accion_invalida("Cancelar", exc, token=a.token, id_das=a.id_das)
            return
        self._diario.anotar("cancel_intencion", id_das=a.id_das, token=a.token, motivo=a.motivo, linea=linea,
                            regla="M6")
        self._mandar_protegido("Cancelar", linea, None, 0)

    def _cancelar_ticker(self, a: CancelarTicker) -> None:
        try:
            linea = protocolo.cmd_cancel_allsymb(a.ticker)
        except (TypeError, ValueError) as exc:  # frontera de mensaje
            self._accion_invalida("CancelarTicker", exc, ticker=a.ticker)
            return
        self._diario.anotar("cancel_intencion", ticker=a.ticker, todas=True, motivo=a.motivo, linea=linea,
                            regla="M6")
        self._mandar_protegido("CancelarTicker", linea, None, 0)

    def _reemplazar(self, a: Reemplazar) -> None:
        tipo = (TipoOrden.STOP_LIMITE_PP if a.stop is not None
                else TipoOrden.LIMITE if a.precio is not None else TipoOrden.MERCADO)
        try:
            linea = protocolo.cmd_replace(a.id_das, a.qty, tipo, a.precio, a.stop)
        except (TypeError, ValueError) as exc:  # frontera de mensaje (riesgo 12: precio fuera de tick)
            self._accion_invalida("Reemplazar", exc, token=a.token, id_das=a.id_das)
            return
        self._diario.anotar("replace_intencion", id_das=a.id_das, token=a.token, qty=a.qty, stop=a.stop,
                            precio=a.precio, version=a.version, serie=a.serie, motivo=a.motivo, linea=linea,
                            regla="M6")
        self._mandar_protegido("Reemplazar", linea, a.serie, a.version)

    def _invalidar(self, a: InvalidarSerie) -> None:
        try:
            self._cliente.invalidar(a.serie, a.version)
        except (TypeError, ValueError) as exc:  # frontera de mensaje
            self._accion_invalida("InvalidarSerie", exc, serie=a.serie)

    def _consultar(self, a: Consultar) -> None:
        comando = a.comando
        if not isinstance(comando, str) or protocolo.es_mutante(comando):
            self._diario.anotar("consulta_rechazada", comando=str(comando), regla="R-O-03")
            self._avisar_directo(Nivel.MAXIMO, "BUG: una consulta del decisor era un comando MUTANTE y no salió "
                                               "(R-O-03)", "consulta_mutante")
            return
        self._mandar_protegido("Consultar", comando, None, 0)

    def _locate_comprar(self, a: LocateComprar) -> None:
        try:
            linea = protocolo.cmd_sl_neworder(a.ticker, a.qty, a.ruta, a.token)
        except (TypeError, ValueError) as exc:  # frontera de mensaje
            self._accion_invalida("LocateComprar", exc, token=a.token, ticker=a.ticker)
            return
        if self._diario.degradado:
            # el `locate_intencion` que la regla anotó justo antes NO está en disco (corrección 4)
            self._bloquear_por_disco("locate_bloqueado", a.ticker, {
                "token": a.token, "qty": a.qty, "ruta": a.ruta,
                "motivo": "diario no escribible: sin locate_intencion en disco no se compra"})
            return
        self._mandar_protegido("LocateComprar", linea, None, 0)

    def _locate_oferta(self, a: LocateOferta) -> None:
        try:
            linea = protocolo.cmd_sl_offer(a.id_das, a.aceptar)
        except (TypeError, ValueError) as exc:  # frontera de mensaje
            self._accion_invalida("LocateOferta", exc, id_das=a.id_das)
            return
        self._diario.anotar("locate_oferta", id_das=a.id_das, aceptar=a.aceptar, linea=linea, regla="R-H-01")
        self._mandar_protegido("LocateOferta", linea, None, 0)

    def _mandar_simple(self, que: str, hacer_linea: Callable[[], str]) -> None:
        try:
            linea = hacer_linea()
        except (TypeError, ValueError) as exc:  # frontera de mensaje
            self._accion_invalida(que, exc)
            return
        self._mandar_protegido(que, linea, None, 0)

    def _mandar_protegido(self, que: str, linea: str, serie: Optional[str], version: int) -> None:
        """`_enviar_linea` con las fronteras de envío: EnvioProhibido (bug, aviso 3) y línea inválida (aviso 2).

        G2-05: un MUTANTE (CANCEL, REPLACE, locates…) que el cliente descarta
        en el acto se anota como `linea_descartada` (el diario no finge que
        salió); una lectura descartada no se anota (con DAS caído serían
        muchas y el decisor ya está en modo degradado «das»).
        """
        try:
            _, encolada = self._enviar_linea(linea, serie, version)
        except EnvioProhibido as exc:  # frontera (R-O-03): un mutante al cliente de solo lectura es un bug; no sale
            self._diario.anotar("envio_prohibido", accion=que, error=str(exc), regla="R-O-03")
            self._avisar_directo(Nivel.MAXIMO, f"BUG: {que} mutante bloqueado por el candado de sombra (R-O-03)",
                                 f"envio_prohibido:{que}")
            return
        except (TypeError, ValueError) as exc:  # frontera de mensaje
            self._accion_invalida(que, exc)
            return
        if not encolada and protocolo.es_mutante(linea):
            self._diario.anotar("linea_descartada", accion=que, linea=linea, motivo=MOTIVO_NO_ENCOLADA, regla="G2-05")

    def _enviar_linea(self, linea: str, serie: Optional[str], version: int) -> tuple[list[MensajeDAS], bool]:
        """Una línea hacia DAS; en sombra, las consultas de CUENTA al emparejador. Devuelve (mensajes simulados, encolada).

        R-O-03: en sombra la cuenta que opera el bot es la del emparejador
        (sus órdenes, fills, posiciones y BP); el DAS real solo aporta el
        mercado. Los mensajes simulados se ENCOLAN (orden de la cola) y además
        se devuelven para `orden_simulada`. G2-05: `encolada` es False solo si
        el cliente devolvió False (la descartó en el acto); un doble que no
        devuelve nada (None) cuenta como encolada.
        """
        if not self._sombra:
            resultado = self._cliente.enviar(linea, serie, version)
            encolada = resultado is not False
            if encolada:
                self._al_socket += 1
            return [], encolada
        if _es_consulta_de_cuenta(linea):
            return self._consulta_sombra(linea), True
        self._buzon.empezar_captura()
        try:
            resultado = self._cliente.enviar(linea, serie, version)
        finally:
            capturados = self._buzon.terminar_captura()
        encolada = resultado is not False
        if encolada and not protocolo.es_mutante(linea):
            self._al_socket += 1                         # lecturas al DAS real: su respuesta llega por el socket
        return capturados, encolada

    def _consulta_sombra(self, linea: str) -> list[MensajeDAS]:
        mensajes: list[MensajeDAS] = []
        for cruda in self._cliente.emparejador.recibir(linea):
            msg = self._parser_sombra.parsear(cruda)
            mensajes.append(msg)
            self._buzon.poner(DeDAS(msg, True))
        return mensajes

    def _bloquear_por_disco(self, tipo: str, ticker: str, datos: dict) -> None:
        """Corrección 4: la orden/compra no sale; registro (a pendientes) y aviso 3 UNA vez por episodio."""
        self._bloqueadas += 1
        self._diario.anotar(tipo, ticker=ticker, regla="corrección 4", **datos)
        if not self._aviso_disco:
            self._aviso_disco = True
            self._avisar_directo(Nivel.MAXIMO, "El diario NO escribe: no salen entradas, pirámides ni compras de "
                                               "locate; stops, cancelaciones y cierres SÍ (corrección 4)",
                                 "disco_ejecutor")

    # ── diario, avisos, temporizadores, foto, supervisor ──
    def _anotar(self, a: Anotar) -> None:
        datos = a.datos if isinstance(a.datos, dict) else {"datos": a.datos}
        self._diario.anotar(str(a.tipo), **{str(k): v for k, v in datos.items()})

    def _avisar(self, a: Avisar) -> None:
        """R-M-01/R-M-05: `put_nowait` en la cola de avisos (nunca bloquea) + registro `aviso` en el diario."""
        try:
            self._avisos.poner(mod_avisos.aviso_de(a, self._reloj.mono()))
        except (TypeError, ValueError) as exc:  # frontera de mensaje: un aviso mal formado no tumba el bucle
            self._diario.anotar("aviso_invalido", error=f"{type(exc).__name__}: {exc}")
        nivel = a.nivel.value if isinstance(a.nivel, Nivel) else a.nivel
        grupo = a.grupo.value if isinstance(a.grupo, Grupo) else a.grupo
        self._diario.anotar("aviso", nivel=nivel, grupo=grupo, clave=a.clave, texto=a.texto)

    def _avisar_directo(self, nivel: Nivel, texto: str, clave: Optional[str]) -> None:
        """Aviso propio del ejecutor al grupo B, con la fase delante (R-O-03) y por el mismo camino que los del decisor."""
        self._avisar(Avisar(nivel, Grupo.B, mod_avisos.con_prefijo_fase(texto, self.cfg.fase), clave))

    def _programar(self, a: Programar) -> None:
        en_s = a.en_s
        if isinstance(en_s, bool) or not isinstance(en_s, (int, float)) or not math.isfinite(en_s):
            self._diario.anotar("temporizador_invalido", clave=a.clave, en_s=str(en_s))
            en_s = 0.0
        self._temporizadores.programar(a.clave, self._reloj.mono() + max(0.0, float(en_s)),
                                       a.datos if isinstance(a.datos, dict) else {})

    def _publicar_foto(self, parado: bool = False) -> None:
        """Panel 4.4: `estado/foto.json` = foto del decisor + la del proceso, escrita con tmp + os.replace (atómica)."""
        foto: dict[str, Any] = dict(self._decisor.foto()) if self._decisor is not None else {
            "version": VERSION, "fase": self.cfg.fase.value}
        foto["ejecutor"] = self._foto_propia(parado)
        texto = json.dumps(foto, ensure_ascii=False, default=str, sort_keys=True)
        if self._limpiar is not None:
            texto = self._limpiar(texto)
        try:
            _escribir_atomico(self.ruta_foto, texto)
        except OSError as exc:  # frontera de fichero: la foto es informativa; el bucle sigue
            self._foto_fallos += 1
            if self._foto_fallos == 1:
                self._diario.anotar("foto_fallo", error=f"{type(exc).__name__}: {exc}")

    def _foto_propia(self, parado: bool) -> dict:
        vivo, hilos = self._hilos_criticos()
        return {
            "pid": os.getpid(), "parado": parado, "listo": self._listo, "sombra": self._sombra,
            "cola": self._buzon.tamano(), "temporizadores": len(self._temporizadores),
            "hilos_criticos": hilos, "todo_vivo": vivo, "das_conectado": self._conectado(),
            "reconexiones": self._plan.intentos, "enviadas": self._enviadas, "bloqueadas_disco": self._bloqueadas,
            "diario": {"degradado": self._diario.degradado, "seq": self._diario.seq, "perdidos": self._diario.perdidos},
            "avisos": self._foto_avisos(), "fuente": self._salud_fuente(),
            "sombra_ignorados": dict(self._sombra_ignorados), "avisos_borde_perdidos": self._buzon.avisos_perdidos,
        }

    def _pedir_al_supervisor(self, a: PedirAlSupervisor) -> None:
        """Corrección 16: una línea JSON en `estado/orden_supervisor.jsonl` (append + flush).

        Formato de `tipos.PedirAlSupervisor`: «relanzar X» viaja además como
        `{"relanzar": "X"}`, que es lo que lee el supervisor. Nunca se escribe
        `{"parar": …}`: esa orden es del supervisor hacia los hijos (y este
        mismo proceso la leería). Dedupe (como el vigilante): la MISMA petición
        como mucho cada `PETICION_REPETIR_S` (reloj inyectado); un decisor que
        la repitiera en cada Tic no relanza en bucle ni llena el fichero.
        """
        peticion = str(a.peticion)
        ahora = self._reloj.mono()
        anterior = self._peticion_en.get(peticion)
        if anterior is not None and ahora - anterior < PETICION_REPETIR_S:
            return
        cuerpo: dict[str, Any] = {"t": self._reloj.ahora().isoformat(), "proceso": "ejecutor", "pid": os.getpid(),
                                  "peticion": peticion}
        palabras = peticion.split()
        if len(palabras) == 2 and palabras[0].lower() == "relanzar":
            cuerpo["relanzar"] = palabras[1]
        linea = json.dumps(cuerpo, ensure_ascii=False)
        try:
            self._ruta_estado.mkdir(parents=True, exist_ok=True)
            with open(self.ruta_orden_supervisor, "a", encoding="utf-8", newline="\n") as f:
                f.write(linea + "\n")
                f.flush()
        except OSError as exc:  # frontera de fichero: la petición no llegó; se avisa (corrección 16)
            self._diario.anotar("peticion_supervisor_fallo", peticion=a.peticion, error=f"{type(exc).__name__}: {exc}")
            self._avisar_directo(Nivel.AVISO, f"No se pudo escribir la petición al supervisor ({a.peticion})",
                                 "peticion_supervisor")
            return
        self._peticion_en[peticion] = ahora
        self._diario.anotar("peticion_supervisor", peticion=a.peticion)

    def _salir(self, codigo: Any, motivo: str) -> None:
        if self._codigo is not None:
            return
        try:
            valor = int(codigo)
        except (TypeError, ValueError):
            valor = CODIGO_ERROR
        self._codigo = valor
        self._motivo_salida = str(motivo)
        if self._diario_abierto:
            self._diario.anotar("salir", codigo=valor, motivo=str(motivo))
        logger.info("[EJECUTOR] fin del bucle: código %d (%s)", valor, motivo)

    def _accion_invalida(self, que: str, exc: BaseException, **datos: Any) -> None:
        self._diario.anotar("accion_invalida", accion=que, error=f"{type(exc).__name__}: {exc}", **datos)
        self._avisar_directo(Nivel.AVISO, f"Acción {que} imposible y descartada: {type(exc).__name__}: "
                                          f"{mod_avisos.escapar_html(exc)}", f"accion_invalida:{que}")

    # ══════════════════════════ el bucle por dentro ═══════════════════════
    def _procesar(self, msg: Mensaje) -> None:
        if self._sombra and isinstance(msg, DeDAS) and not msg.simulado and isinstance(msg.msg, MENSAJES_DE_CUENTA):
            self._ignorar_en_sombra(msg.msg)
            return
        try:
            acciones = self._decisor.procesar(msg, self._reloj.mono(), self._reloj.ahora())
        except Exception as exc:  # noqa: BLE001 — frontera de mensaje (H-5): el decisor no lanza; si lo hace, el bucle no muere
            self._diario.anotar("excepcion", donde="decisor.procesar", mensaje=type(msg).__name__,
                                error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc(limit=12),
                                regla="H-5")
            self._avisar_directo(Nivel.AVISO, f"Error interno procesando {type(msg).__name__}: "
                                              f"{mod_avisos.escapar_html(exc)} (H-5: el bot sigue)",
                                 f"excepcion_ejecutor:{type(msg).__name__}")
            return
        self._ejecutar_todas(acciones)
        if isinstance(msg, ConexionDAS):
            self._tras_conexion(msg)
        elif self._sombra and isinstance(msg, DeDAS) and not msg.simulado and isinstance(msg.msg, MsgQuote):
            self._alimentar_sombra(msg.msg.ticker)

    def _ejecutar_todas(self, acciones: Iterable[Accion]) -> None:
        for a in acciones:
            try:
                self.ejecutar(a)
            except Exception as exc:  # noqa: BLE001 — frontera por acción (H-5): una acción rota no impide las siguientes (stops)
                self._diario.anotar("excepcion", donde="ejecutar", accion=type(a).__name__,
                                    error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc(limit=12),
                                    regla="H-5")
                self._avisar_directo(Nivel.AVISO, f"Error ejecutando {type(a).__name__}: "
                                                  f"{mod_avisos.escapar_html(exc)} (H-5)",
                                     f"excepcion_accion:{type(a).__name__}")

    def _disparar_temporizadores(self) -> None:
        for _ in range(TEMPORIZADORES_POR_PASO):
            vencido = self._temporizadores.sacar_vencido(self._reloj.mono())
            if vencido is None:
                return
            clave, datos = vencido
            self._procesar(Temporizador(clave, datos))
            if self._codigo is not None:
                return

    def _espera_hasta_proximo(self, espera_s: float) -> float:
        espera = max(0.0, float(espera_s))
        proximo = self._temporizadores.proximo()
        if proximo is not None:
            espera = min(espera, max(0.0, proximo - self._reloj.mono()))
        return espera

    def _tic(self, cola_vacia: bool) -> None:
        self._ultimo_tic = time.monotonic()
        self._al_socket = 0
        self._latido_fuente()
        if self._codigo is not None:
            return
        self._procesar(Tic())
        if self._codigo is not None:
            return
        if self._sombra:
            self._tic_sombra()
        self._revisar_orden_supervisor()
        self._revisar_cola()
        self._revisar_dia()
        self._revisar_reloj()
        self._revisar_referencia()
        if not self._diario.degradado:
            self._aviso_disco = False
        if not cola_vacia:
            return
        if self._al_socket and not self._replay_retenido:
            self._replay_retenido = True                 # R-O-02: una vuelta de gracia para las respuestas del socket
            return
        self._replay_retenido = False
        self._avanzar_grabacion()

    def _en_replay(self) -> bool:
        """R-O-02: la fuente es una grabación ya arrancada (el reloj simulado marca el ritmo, no la espera de la cola)."""
        return self._fuente_arrancada and isinstance(self._fuente, FuenteGrabacion)

    def _drenar_avisos_de_borde(self) -> None:
        for nivel, texto, clave in self._buzon.avisos_pendientes():
            self._avisar_directo(nivel, texto, clave)
        for linea, espera in self._buzon.cuotas_pendientes():
            # A-07: en sombra el DAS real habría retenido este mutante por cuota (se cuenta, no se espera)
            self._diario.anotar("cuota_agotada", linea=linea, espera_s=espera, regla="A-07")

    def _tras_conexion(self, msg: ConexionDAS) -> None:
        """R-J-02 (2): conectado → el plan vuelve a 2 s; caída → reconexión a 2/4/8/16/30 s (la lleva el ejecutor)."""
        if msg.conectado:
            self._plan.reiniciar()
            self._reconectar_en = None
            return
        if self._conectado() or self._hilo_reconexion is not None or self._reconectar_en is not None:
            return
        self._programar_reconexion()

    def _programar_reconexion(self) -> None:
        espera = self._plan.siguiente()
        self._reconectar_en = self._reloj.mono() + espera
        self._diario.anotar("das_reconectar", intento=self._plan.intentos, en_s=espera, regla="R-J-02")

    def _revisar_reconexion(self) -> None:
        hilo = self._hilo_reconexion
        if hilo is not None:
            if hilo.is_alive():
                return
            self._hilo_reconexion = None
            ok = bool(self._resultado_reconexion)
            self._resultado_reconexion = None
            if not ok and not self._conectado():
                self._programar_reconexion()
            return
        if self._reconectar_en is None or self._reloj.mono() + _TOLERANCIA_S < self._reconectar_en:
            return
        self._reconectar_en = None
        if self._conectado():
            return
        self._hilo_reconexion = threading.Thread(target=self._cuerpo_reconexion, name="das-reconexion", daemon=True)
        self._hilo_reconexion.start()

    def _cuerpo_reconexion(self) -> None:
        self._resultado_reconexion = self._conectar_seguro()

    def _conectar_seguro(self) -> bool:
        try:
            return bool(self._cliente.conectar())
        except Exception as exc:  # noqa: BLE001 — frontera de red (R-J-02): conectar no debe lanzar; si lo hace, cuenta como fallo
            logger.warning("[EJECUTOR] conectar() lanzó %s: %s", type(exc).__name__, exc)
            return False

    def _conectado(self) -> bool:
        try:
            return bool(getattr(self._cliente, "conectado", False))
        except Exception:  # noqa: BLE001 — frontera: una propiedad rota del cliente se trata como «sin conexión»
            return False

    def _esperar_reconciliacion(self) -> bool:
        """F12 / R-J-02.5: procesa la cola hasta la primera reconciliación con DAS (o el plazo); nada abre antes."""
        limite = time.monotonic() + self._espera_reconciliacion_s
        while self._decisor.estado.reconciliacion_ok_en is None:
            if self.paso(PASO_ARRANQUE_S) is not None:
                return False
            if time.monotonic() >= limite:
                self._diario.anotar("reconciliacion_pendiente", espera_s=self._espera_reconciliacion_s,
                                    regla="R-J-02.5")
                self._avisar_directo(Nivel.AVISO, f"Sin reconciliación con DAS en {self._espera_reconciliacion_s:.0f} s "
                                                  f"al arrancar: no se abre nada hasta que llegue (R-J-02.5)",
                                     "reconciliacion_arranque")
                return False
        return True

    def _arrancar_bordes(self) -> None:
        if self._config_watch is not None:
            self._seguro("config_watch.arrancar", self._config_watch.arrancar)
        for receptor in self._receptores:
            self._seguro(f"{type(receptor).__name__}.arrancar", receptor.arrancar)
        try:
            self._fuente.arrancar()
        except Exception as exc:  # noqa: BLE001 — frontera (fichero/red): sin fuente el ejecutor protege igual; el latido se retiene
            self._fuente_fallo = f"{type(exc).__name__}: {exc}"
            self._diario.anotar("fuente_fallo", fuente=type(self._fuente).__name__, error=self._fuente_fallo)
            self._avisar_directo(Nivel.MAXIMO, f"La fuente de señales no arranca ({mod_avisos.escapar_html(self._fuente_fallo)}): "
                                               f"sin señales; el supervisor relanzará el ejecutor (injerto §8.11)",
                                 "fuente_fallo")
            return
        self._fuente_arrancada = True

    # ── sombra (R-O-03) ──
    def _ignorar_en_sombra(self, msg: MensajeDAS) -> None:
        nombre = type(msg).__name__
        n = self._sombra_ignorados.get(nombre, 0) + 1
        self._sombra_ignorados[nombre] = n
        if n == 1:
            self._diario.anotar("sombra_ignorado", tipo=nombre,
                                nota="en sombra la cuenta es la del emparejador; el DAS real solo da mercado",
                                regla="R-O-03")

    def _alimentar_sombra(self, ticker: str) -> None:
        """La `$Quote` real al libro del emparejador y `tic()`: las órdenes simuladas se llenan con precios reales."""
        cot = self._mercado.cotizacion(ticker)
        if cot is None or cot.bid is None or cot.ask is None or cot.ask < cot.bid:
            return
        try:
            self._cliente.emparejador.libro.cotizar(
                cot.ticker, cot.bid, cot.ask, last=cot.last, volumen=cot.volumen if cot.volumen else 0,
                vwap=cot.vwap, tamano_bid=cot.bsz * 100 if cot.bsz is not None else None,
                tamano_ask=cot.asz * 100 if cot.asz is not None else None)
        except (TypeError, ValueError) as exc:  # frontera de mensaje: una cotización que el libro no admite no para nada
            self._diario.anotar("sombra_cotizacion", ticker=ticker, error=f"{type(exc).__name__}: {exc}")
            return
        self._tic_sombra()

    def _tic_sombra(self) -> None:
        try:
            self._cliente.tic()
        except Exception as exc:  # noqa: BLE001 — frontera del emparejador (sombra): no puede tumbar el bucle
            self._diario.anotar("excepcion", donde="sombra.tic", error=f"{type(exc).__name__}: {exc}")

    # ── vigilancia propia en cada Tic ──
    def _revisar_orden_supervisor(self) -> None:
        """§6.2.5: `{"parar": true}` en `estado/orden_supervisor.jsonl` (escrito tras arrancar) → parada ordenada."""
        ruta = self.ruta_orden_supervisor
        tamano = self._tamano_fichero(ruta)
        if tamano < self._orden_offset:
            self._orden_offset = 0                      # lo rotaron o lo truncaron: se relee desde el principio
        if tamano == self._orden_offset:
            return
        try:
            with open(ruta, "rb") as f:
                f.seek(self._orden_offset)
                bloque = f.read(tamano - self._orden_offset)
        except OSError:  # frontera de fichero: se vuelve a mirar en el siguiente Tic
            return
        corte = bloque.rfind(b"\n")
        if corte < 0:
            return
        self._orden_offset += corte + 1
        for cruda in bloque[:corte].splitlines():
            try:
                peticion = json.loads(cruda.decode("utf-8", errors="replace"))
            except ValueError:
                continue
            if not isinstance(peticion, dict) or peticion.get("parar") is not True:
                continue
            para = peticion.get("para", peticion.get("proceso_destino"))
            if para not in (None, "ejecutor", "todos"):
                continue
            self._diario.anotar("orden_supervisor", peticion={k: str(v) for k, v in peticion.items()},
                                regla="R-L-01")
            self._salir(CODIGO_OK, "parada pedida por el supervisor (R-L-01)")
            return

    def _revisar_cola(self) -> None:
        umbral = _entero_positivo(self.cfg.tecnicos.get("cola_aviso_umbral"), 10_000)
        n = self._buzon.tamano()
        if n > umbral and not self._cola_avisada:
            self._cola_avisada = True
            self._diario.anotar("cola_grande", tamano=n, umbral=umbral, regla="riesgo 17")
            self._avisar_directo(Nivel.AVISO, f"La cola del ejecutor tiene {n} mensajes (umbral {umbral}): va retrasado",
                                 "cola_grande")
        elif n <= umbral // 2:
            self._cola_avisada = False

    def _revisar_dia(self) -> None:
        """El diario es por día (§8): si el ejecutor sigue vivo al cambiar la fecha ET, abre el fichero del día nuevo."""
        hoy = self._reloj.hoy()
        if self._diario.dia is None or self._diario.dia == hoy:
            return
        antes = self._diario.dia
        self._diario.abrir_dia(hoy, motor_hash=self.cfg.motor_hash, config_version=self.cfg.config_version,
                               estrategias_hash=self.cfg.estrategias_hash)
        self._diario.anotar("dia_nuevo_diario", antes=antes, hoy=hoy)

    def _revisar_reloj(self) -> None:
        """Riesgo 14 / R-J-07: desvío SNTP cada hora, medido en un hilo (el UDP puede tardar 3 s)."""
        with self._cerrojo_reloj:
            medido = self._desvio_medido
            self._desvio_medido = None
        if medido is not None:
            self._hilo_reloj = None
            desvio = medido[0]
            puede, texto = mod_reloj.veredicto_reloj(desvio, *self._umbrales_reloj())
            self._diario.anotar("reloj", desvio_s=desvio, puede_operar=puede, texto=texto, regla="R-J-07")
            if not puede:
                self._avisar_directo(Nivel.MAXIMO, f"Reloj desviado {desvio:+.2f} s respecto a SNTP (R-J-07): "
                                                   f"sincroniza la hora; al relanzar el ejecutor se negará a operar",
                                     "reloj_horario")
            elif texto is not None:
                self._avisar_directo(Nivel.AVISO, f"Reloj: {texto} (R-J-07)", "reloj_horario_aviso")
            return
        if self._hilo_reloj is not None or self._reloj_revisado_en is None:
            return
        if self._reloj.mono() - self._reloj_revisado_en < RELOJ_REVISION_S:
            return
        self._reloj_revisado_en = self._reloj.mono()
        self._hilo_reloj = threading.Thread(target=self._cuerpo_reloj, name="reloj-sntp", daemon=True)
        self._hilo_reloj.start()

    def _cuerpo_reloj(self) -> None:
        desvio = self._medir_desvio_seguro()
        with self._cerrojo_reloj:
            self._desvio_medido = (desvio,)

    def _latido_fuente(self) -> None:
        """R-J-01 (F11 b) con una fuente EN ESTE PROCESO (`proceso`, `grabacion` o un doble): el latido del feed lo da ella.

        Con la tubería el latido viene de `bot.py` cada 5 s (mensaje
        «latido»). Las fuentes en proceso no mandan latido: su `salud()`
        trae `ultimo_en` (epoch de la última vela aplicada). Sin esto el
        vigilante del feed del decisor daría el feed por muerto a los 60 s
        y ninguna entrada saldría en `proceso` ni en el replay (R-O-02). Se
        entrega cada `LATIDO_FEED_S` (reloj inyectado) o en cuanto cambia
        `ultimo_en`; directo al decisor (no a la cola) para no romper la
        cuenta de «cola vacía» del replay.
        """
        if not self._fuente_arrancada or isinstance(self._fuente, FuenteTuberia):
            return
        salud = self._salud_fuente()
        ultimo = salud.get("ultimo_en")
        if isinstance(ultimo, bool) or not isinstance(ultimo, (int, float)) or not math.isfinite(ultimo):
            return
        ahora = self._reloj.mono()
        if (self._latido_fuente_en is not None and ultimo == self._latido_fuente_ultimo
                and ahora - self._latido_fuente_en < LATIDO_FEED_S):
            return
        self._latido_fuente_en = ahora
        self._latido_fuente_ultimo = ultimo
        origen = salud.get("origen")
        self._procesar(SenalRecibida(Senal(
            clase="latido_feed", ticker=None, id=None, recibida_en=ahora,
            feed={"ultima_vela_en": float(ultimo), "vivo": bool(salud.get("viva", False))},
            origen=origen if isinstance(origen, str) and origen else FUENTE_PROCESO)))

    def _avanzar_grabacion(self) -> None:
        """R-O-02: con `FuenteGrabacion`, en cada Tic con la cola vacía el reloj avanza una vela (o hasta el próximo temporizador).

        Agotada la grabación, tras `REPLAY_TICS_FINALES` Tics con la cola
        vacía se sale con código 0 (fin de la repetición).
        """
        fuente = self._fuente
        if not isinstance(fuente, FuenteGrabacion) or not self._fuente_arrancada:
            return
        if fuente.pendientes == 0:
            if not self._grabacion_agotada:
                self._grabacion_agotada = True
                self._diario.anotar("fin_grabacion", aplicadas=fuente.aplicadas, regla="R-O-02")
            self._tics_fin_grabacion += 1
            if self._tics_fin_grabacion >= REPLAY_TICS_FINALES:
                self._salir(CODIGO_OK, "fin de la grabación (R-O-02)")
            return
        ahora = self._reloj.ahora()
        limite = ahora + timedelta(seconds=REPLAY_PASO_S)
        proximo = self._temporizadores.proximo()
        if proximo is not None:
            limite = min(limite, ahora + timedelta(seconds=max(0.0, proximo - self._reloj.mono())))
        try:
            fuente.reproducir(hasta=limite, paso=self._paso_de_replay)
        except Exception as exc:  # noqa: BLE001 — frontera del replay: el guion o el fichero fallan → fin con error, registrado
            self._diario.anotar("excepcion", donde="grabacion.reproducir", error=f"{type(exc).__name__}: {exc}",
                                traceback=traceback.format_exc(limit=12))
            self._salir(CODIGO_ERROR, f"la grabación falló: {type(exc).__name__}: {exc}")
            return
        if self._reloj.ahora() < limite:
            self._reloj.fijar(limite)

    def _paso_de_replay(self, t: datetime, vela: dict) -> None:
        """R-O-02 / G2-06: el gancho del guion y, si devuelve las líneas de DAS de esa vela, su `$Quote` al libro YA.

        La cotización que el DAS simulado manda por el socket llega DESPUÉS de
        la señal de la misma vela (la fuente la entrega en el acto): sin esto,
        toda entrada del replay se descartaba «sin cotización fresca de DAS».
        Un gancho que devuelve las líneas (`SimuladorDAS.desde_vela`) hace que
        el `$Quote` se aplique a `MercadoDAS` (y al libro de la sombra) antes
        de la señal; uno que no devuelve nada se comporta como antes. El
        `$Quote` pasa por el decisor como cualquier mensaje de DAS (él es quien
        aplica el libro y reacciona); la copia que llegue luego por el socket
        repite los mismos valores.
        """
        lineas = self._paso_replay(t, vela) if self._paso_replay is not None else None
        if lineas is None or isinstance(lineas, (str, bytes)):
            lineas = [lineas] if isinstance(lineas, str) else []
        parser = protocolo.Parser(lambda token: False)
        for cruda in lineas:
            if not isinstance(cruda, str):
                continue
            msg = parser.parsear(cruda)
            if isinstance(msg, MsgQuote):
                self._procesar(DeDAS(msg, False))

    # ── latido (R-J-04 b, injerto §8.11) ──
    def _tocar_latido(self) -> None:
        vivo, hilos = self._hilos_criticos()
        if not vivo and hilos != self._latido_retenido:
            self._latido_retenido = hilos
            if self._diario_abierto:
                self._diario.anotar("latido_retenido", hilos=hilos, regla="injerto §8.11")
        elif vivo:
            self._latido_retenido = None
        self._latido.tocar(vivo)

    def _hilos_criticos(self) -> tuple[bool, dict[str, bool]]:
        """Hilos críticos (§6.1): das-lector + das-emisor, la fuente de señales y avisos-envio."""
        hilos = {"das": self._atributo_bool(self._cliente, "hilos_vivos", True),
                 "avisos": self._atributo_bool(self._avisos, "vivo", True),
                 "fuente": self._fuente_viva()}
        return all(hilos.values()), hilos

    def _fuente_viva(self) -> bool:
        if not self._fuente_arrancada:
            return self._fuente_fallo is None           # aún sin arrancar = no ha muerto; si falló al arrancar, muerta
        salud = self._salud_fuente()
        return bool(salud.get("viva", False)) if isinstance(salud, dict) else False

    def _salud_fuente(self) -> dict:
        try:
            salud = self._fuente.salud()
        except Exception as exc:  # noqa: BLE001 — frontera: una fuente que no sabe decir cómo está cuenta como muerta
            return {"viva": False, "error": f"{type(exc).__name__}: {exc}"}
        return dict(salud) if isinstance(salud, dict) else {"viva": False, "error": "salud() no devolvió un dict"}

    def _foto_avisos(self) -> Any:
        foto = getattr(self._avisos, "foto", None)
        if not callable(foto):
            return None
        try:
            return foto()
        except Exception as exc:  # noqa: BLE001 — frontera: la foto es informativa
            return {"error": f"{type(exc).__name__}: {exc}"}

    @staticmethod
    def _atributo_bool(objeto: Any, nombre: str, defecto: bool) -> bool:
        try:
            return bool(getattr(objeto, nombre, defecto))
        except Exception:  # noqa: BLE001 — frontera: una propiedad que lanza se toma como «muerto»
            return False

    # ── ayudas ──
    def _fallo_de_arranque(self, codigo: int, clave: str, texto: str) -> int:
        """F12 antes del diario: log + aviso 3 (sin tocar el diario, que puede ser de la instancia viva)."""
        logger.error("[EJECUTOR] %s", texto)
        try:
            self._avisos.poner(mod_avisos.aviso_de(
                Avisar(Nivel.MAXIMO, Grupo.B, mod_avisos.con_prefijo_fase(texto, self._cfg.fase), f"arranque:{clave}"),
                self._reloj.mono()))
        except (TypeError, ValueError) as exc:  # frontera de mensaje
            logger.error("[EJECUTOR] el aviso de arranque no se pudo encolar: %s", exc)
        self._codigo = codigo
        self._motivo_salida = texto
        return codigo

    def _con_latido(self, nombre: str, fn: Callable[[], Any]) -> Any:
        """G2-02 (R-J-04 b, §6): `fn()` en un hilo de un solo uso; el principal toca el latido cada `LATIDO_ARRANQUE_S`.

        Devuelve lo que devuelva `fn` y relanza en el principal lo que `fn`
        lance (las funciones que se pasan aquí ya son fronteras que no lanzan).
        Un SNTP o un `connect` lentos ya no dejan el latido sin tocar > 1 s:
        el supervisor no mata por «colgado» a un ejecutor que solo espera.
        """
        resultado: list[Any] = [None]
        error: list[Optional[BaseException]] = [None]

        def cuerpo() -> None:
            try:
                resultado[0] = fn()
            except BaseException as exc:  # noqa: BLE001 — se relanza en el hilo principal tal cual
                error[0] = exc

        hilo = threading.Thread(target=cuerpo, name=nombre, daemon=True)
        hilo.start()
        while True:
            hilo.join(LATIDO_ARRANQUE_S)
            if not hilo.is_alive():
                break
            self._tocar_latido()
        if error[0] is not None:
            raise error[0]
        return resultado[0]

    def _hash_motor_seguro(self) -> tuple[Optional[str], Optional[str]]:
        """(hash, error): H-6 con la frontera de fichero dentro (se ejecuta en el hilo de `_con_latido`)."""
        try:
            return self._hash_motor(self._base), None
        except Exception as exc:  # noqa: BLE001 — frontera de fichero (H-6): sin motor legible no hay hash; se niega igual
            return None, f"{type(exc).__name__}: {exc}"

    def _sembrar_memoria(self, registros: list, hoy: date) -> None:
        """H-2 fuera de `EstadoBot`: `diario.memoria_decisor` + ids de comando ya vistos hoy (C-02) → `decisor.sembrar_memoria`.

        E1-03 (k de halts), G1A-18/G1B-18 (veto R-F-03), G1A-12/G1B-10
        (control manual) y G1B-09 (cambios de Telegram) se pierden en un
        reinicio sin esto. Un decisor sin `sembrar_memoria` (doble de test) se
        deja como está. Un fallo aquí no impide arrancar (H-5): se anota y se
        avisa 2, porque la protección no depende de la memoria.
        """
        sembrar = getattr(self._decisor, "sembrar_memoria", None)
        if not callable(sembrar):
            return
        try:
            memoria = memoria_decisor(registros, hoy)
            ids = sorted({str(r.datos.get("id")) for r in registros
                          if r.tipo in ("comando", "comando_repetido") and isinstance(r.datos, dict)
                          and isinstance(r.datos.get("id"), str) and r.datos.get("id")})
            campos = {campo.name: getattr(memoria, campo.name) for campo in _campos_dataclass(memoria)}
            sembrar(types.SimpleNamespace(**campos, comandos_ids=ids))
        except Exception as exc:  # noqa: BLE001 — frontera (H-5): la memoria es una mejora; sin ella se arranca igual
            self._diario.anotar("excepcion", donde="sembrar_memoria", error=f"{type(exc).__name__}: {exc}",
                                traceback=traceback.format_exc(limit=12), regla="H-5")
            self._avisar_directo(Nivel.AVISO, f"No se pudo rehacer la memoria del decisor del diario "
                                              f"({mod_avisos.escapar_html(exc)}): k de halts, control manual y "
                                              f"cambios de Telegram empiezan de cero (H-2)", "memoria_decisor")
            return
        self._diario.anotar("memoria_decisor", k_halts_up=dict(memoria.k_halts_up), halt_hoy=sorted(memoria.halt_hoy),
                            stop_hoy=sorted(memoria.stop_hoy), manual=sorted(memoria.manual),
                            override_modo_seguridad=memoria.override_modo_seguridad,
                            override_estrategia=dict(memoria.override_estrategia), comandos_ids=len(ids), regla="H-2")

    def _arrancar_referencia(self) -> None:
        """G1A-03 / G1B-08: el `HiloVigilado` «referencia» (Massive por REST) si la referencia ofrece la precarga."""
        if self._hilo_referencia is not None or not _tiene_precarga(self._referencia):
            return
        self._hilo_referencia = HiloVigilado("referencia", self._cuerpo_referencia, self._buzon.al_caida_hilo)
        self._hilo_referencia.arrancar()
        self._diario.anotar("referencia_precarga", hilo="referencia", regla="G1A-03")

    def _cuerpo_referencia(self) -> None:
        """Hilo «referencia»: splits del día (reintento cada minuto si fallan) y, en bucle, las fichas pedidas.

        La red se hace AQUÍ, nunca en el hilo del decisor; el resultado queda
        en la caché de solo lectura de la `Referencia` (con su lock). Termina
        cuando se pide parar.
        """
        hilo = self._hilo_referencia
        parando = hilo.parando if hilo is not None else threading.Event()
        ref = self._referencia
        splits_listos: Optional[date] = None
        intento: Optional[tuple[date, float]] = None
        while not parando.is_set():
            hoy = self._reloj.hoy()
            ahora = time.monotonic()
            if splits_listos != hoy and (intento is None or intento[0] != hoy
                                         or ahora - intento[1] >= REFERENCIA_SPLITS_REINTENTO_S):
                intento = (hoy, ahora)
                if ref.precargar_splits(hoy) is not None:
                    splits_listos = hoy
            for ticker in ref.tomar_pendientes():
                if parando.is_set():
                    return
                ref.precargar_ficha(ticker)
            parando.wait(REFERENCIA_ESPERA_S)

    def _revisar_referencia(self) -> None:
        """G1A-03: si el hilo «referencia» murió y no se relanza, sin fichas no se abre nada (A12): aviso 3 una vez."""
        hilo = self._hilo_referencia
        if hilo is None or hilo.vivo or hilo.parando.is_set() or self._aviso_referencia_dado:
            return
        self._aviso_referencia_dado = True
        self._diario.anotar("referencia_muerta", caidas=hilo.caidas, regla="G1A-03")
        self._avisar_directo(Nivel.MAXIMO, "El hilo de la referencia de Massive murió y no se relanza: sin fichas no "
                                           "se abre ninguna entrada (A12); los stops siguen. Relanza el ejecutor "
                                           "(G1A-03)", "referencia_muerta")

    def _medir_desvio_seguro(self) -> Optional[float]:
        try:
            desvio = self._medir_desvio()
        except Exception as exc:  # noqa: BLE001 — frontera de red (R-J-07): sin medida = «sin SNTP» (se avisa, no se niega)
            logger.warning("[EJECUTOR] la medida SNTP falló: %s: %s", type(exc).__name__, exc)
            return None
        if desvio is None or isinstance(desvio, bool) or not isinstance(desvio, (int, float)) or not math.isfinite(desvio):
            return None
        return float(desvio)

    def _desvio_por_defecto(self) -> Optional[float]:
        servidor = str((self._cfg.tecnicos.get("reloj") or {}).get("sntp") or SERVIDOR_SNTP)
        return mod_reloj.desvio_sntp(servidor)

    def _umbrales_reloj(self) -> tuple[float, float]:
        bloque = self._cfg.tecnicos.get("reloj") or {}
        return (_numero_positivo(bloque.get("negarse_s"), RELOJ_NEGARSE_S),
                _numero_positivo(bloque.get("aviso_s"), RELOJ_AVISO_S))

    def _datos_orden(self, o: OrdenNueva, serie: Optional[str], linea: str) -> dict:
        partes = mod_tokens.descomponer(o.token)
        cot = self._mercado.cotizacion(o.ticker)
        return {
            "token": o.token, "ticker": o.ticker, "lado": o.lado.value, "tipo_orden": o.tipo.value, "qty": o.qty,
            "precio": o.precio, "stop": o.stop, "ruta": o.ruta, "post_only": o.post_only, "tif": o.tif, "pref": o.pref,
            "proposito": o.proposito.value, "lote_id": o.lote_id, "nivel": o.nivel, "version": o.version,
            "origen": int(partes[0]) if partes is not None else None, "serie": serie,
            "bid": cot.bid if cot is not None else None, "ask": cot.ask if cot is not None else None,
            "last": cot.last if cot is not None else None, "linea": linea, "regla": "M6",
        }

    def _seguro(self, que: str, fn: Callable[[], Any]) -> None:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 — frontera de apagado: un componente que falla no impide parar el resto
            logger.warning("[EJECUTOR] %s falló: %s: %s", que, type(exc).__name__, exc)

    @staticmethod
    def _tamano_fichero(ruta: Path) -> int:
        try:
            return os.stat(ruta).st_size
        except OSError:
            return 0


# ══════════════════════════════════════════════════════════════════════
# Construcción desde el entorno (producción)
# ══════════════════════════════════════════════════════════════════════
_POR_DEFECTO: Any = object()


def directorio_bot() -> Path:
    """`BOT_DAS_DIR` (leída en la llamada) o el defecto de §1 (`config.DIR_BOT_POR_DEFECTO`)."""
    return Path(os.environ.get(ENV_DIR, "").strip() or mod_config.DIR_BOT_POR_DEFECTO)


def construir_desde_env(cfg: Config, reloj: Any, base: Path, *, ruta_config: Optional[Path] = None,
                        referencia: Any = _POR_DEFECTO, abrir_referencia: Optional[Callable[..., Any]] = None,
                        calendario: Any = None, hash_motor: Optional[Callable[[Path], str]] = None,
                        medir_desvio: Optional[Callable[[], Optional[float]]] = None,
                        canales: Optional[list] = None, aviso_config: Optional[str] = None,
                        paso_replay: Optional[Callable[[datetime, dict], None]] = None) -> Ejecutor:
    """Monta el ejecutor de producción desde el entorno (§3.27, corrección 15, R-O-03, R-Q-01).

    Cliente: fase SOMBRA → `ClienteDAS.desde_env(watch=False,
    solo_lectura=True)` envuelto en `ClienteSombra(Emparejador(LibroSimulado))`
    (aunque `BOT_DAS_PERMITIR_ORDENES=1` esté puesto: la sombra no puede
    mandar, tercer candado); CANARIO/REAL → `ClienteDAS.desde_env(
    solo_lectura=False)`, que EXIGE `BOT_DAS_PERMITIR_ORDENES=1` (si falta,
    RuntimeError). Fuente por `BOT_DAS_FUENTE`: `tuberia` (defecto; no
    importa pandas), `proceso` o `grabacion=<ruta>` (exige un
    RelojSimulado). Receptores: `LectorComandosFichero` siempre;
    `ReceptorTelegram` si hay `TELEGRAM_BOT_TOKEN_B` y chat ids en
    `BOT_DAS_CHAT_IDS`. Diario con el limpiador de `FiltroSecretos` de los
    valores de `secretos_desde_env()` (ajuste h). Los argumentos por nombre
    son para tests y replay (sin red): `referencia` (objeto con ficha/
    splits_de_hoy o None; por defecto la `Referencia` real, cuya red hace el
    hilo «referencia» del ejecutor y nunca el decisor, G1A-03), `abrir_referencia` (el `urlopen` de Massive),
    `calendario`, `hash_motor`, `medir_desvio`, `canales` de avisos.
    Construir NO abre red, NO arranca hilos y NO escribe el diario: todo eso
    ocurre en `arrancar()`. Lanza RuntimeError/ValueError con el entorno
    incompleto (los mensajes nombran la variable, nunca su valor).
    """
    if not isinstance(cfg, Config):
        raise TypeError(f"cfg debe ser una Config, no {type(cfg).__name__}")
    dir_bot = directorio_bot()
    for sub in SUBCARPETAS_BOT:
        (dir_bot / sub).mkdir(parents=True, exist_ok=True)
    ruta_estado = dir_bot / "estado"
    filtro = mod_avisos.FiltroSecretos(mod_avisos.secretos_desde_env())
    buzon = Buzon()
    diario = Diario(dir_bot / "diario", reloj, "ejecutor", VERSION, cfg.fase, limpiar=filtro.limpiar)
    cola_avisos = mod_avisos.ColaAvisos(canales if canales is not None else mod_avisos.canales_desde_env(cfg), reloj)
    mercado = MercadoDAS(reloj, max_lv1=_entero_positivo(cfg.tecnicos.get("max_lv1"), MAX_LV1))
    comun = dict(al_mensaje=buzon.al_mensaje, al_estado=buzon.al_estado, reloj=reloj, cuota=_cuota_de(cfg, reloj),
                 al_aviso=buzon.al_aviso, al_caida_hilo=buzon.al_caida_hilo,
                 al_descartar=buzon.al_descartar)           # D2a-06: lo que el emisor purga vuelve al decisor
    cliente: Any
    if cfg.fase is Fase.SOMBRA:
        real = ClienteDAS.desde_env(watch=False, solo_lectura=True, **comun)
        emparejador = Emparejador(LibroSimulado(cuenta=real.cuenta), reloj,
                                  replace_share_es_abierta=_share_es_abierta(cfg))       # A-02: el simulador lo respeta
        cliente = ClienteSombra(real, emparejador, buzon.al_mensaje, al_cuota_agotada=buzon.al_cuota_agotada)
    else:
        cliente = ClienteDAS.desde_env(watch=False, solo_lectura=False, **comun)
    fuente = _fuente_desde_env(cfg, buzon, reloj)
    if referencia is _POR_DEFECTO:
        kw = {"abrir": abrir_referencia} if abrir_referencia is not None else {}
        referencia = Referencia.desde_env(dir_bot / "cache", reloj, **kw)
    catalogo = rechazos.cargar_catalogo(rechazos.RUTA_CATALOGO)

    def fabrica(estado: EstadoBot) -> Decisor:
        tokens = GeneradorTokens(Origen.EJECUTOR, estado.dia, int(estado.ultimo_seq_token))
        return Decisor(cfg, estado, mercado, referencia, tokens, catalogo, lambda: diario.degradado,
                       calendario=calendario, lineas_log=mod_avisos.ultimas_lineas_log, tamano_cola=buzon.tamano)

    receptores: list = [LectorComandosFichero(ruta_estado / NOMBRE_COMANDOS, buzon.al_comando, reloj,
                                              al_caida=buzon.al_caida_hilo)]
    token_b = os.environ.get(ENV_TOKEN_B, "").strip()
    autorizados = _chat_ids_de_entorno()
    if token_b and autorizados:
        # C-02: el offset se persiste en estado/telegram_offset ANTES de entregar: un reinicio no repite «/cerrar X N SI»
        receptores.append(ReceptorTelegram(token_b, autorizados, buzon.al_comando, reloj, al_caida=buzon.al_caida_hilo,
                                           ruta_offset=ruta_estado / FICHERO_OFFSET_TELEGRAM))
    elif token_b:
        logger.warning("[EJECUTOR] hay %s pero no %s: no se reciben comandos por Telegram (R-Q-01)",
                       ENV_TOKEN_B, ENV_CHAT_IDS)
    ruta_cfg = Path(ruta_config) if ruta_config is not None else dir_bot / "config" / mod_config.NOMBRE_FICHERO_CONFIG
    config_watch = mod_config.VigilanteConfig(ruta_cfg, dir_bot / "config" / mod_config.NOMBRE_ULTIMO_BUENO,
                                              cfg.cuenta_das, buzon.al_config, al_caida=buzon.al_caida_hilo)
    vigilante = cfg.tecnicos.get("vigilante") or {}
    latido = Latido(ruta_estado / NOMBRE_LATIDO, reloj, cada_s=_numero_positivo(vigilante.get("latido_s"), LATIDO_S))
    cerrojo = CerrojoInstancia(ruta_estado / NOMBRE_CERROJO)
    return Ejecutor(cfg, cliente, fuente, diario, cola_avisos, mercado, fabrica, reloj, latido, cerrojo, receptores,
                    config_watch, ruta_estado, buzon=buzon, base=Path(base), hash_motor=hash_motor,
                    medir_desvio=medir_desvio, lector=LectorDiario(dir_bot / "diario"), aviso_config=aviso_config,
                    limpiar=filtro.limpiar, paso_replay=paso_replay, referencia=referencia)


def _fuente_desde_env(cfg: Config, buzon: Buzon, reloj: Any) -> Any:
    """`BOT_DAS_FUENTE` = tuberia (defecto) | proceso | grabacion=<ruta> (§3.27; injerto §8.25: solo la tubería evita pandas)."""
    texto = os.environ.get(ENV_FUENTE, "").strip() or FUENTE_TUBERIA
    if texto == FUENTE_TUBERIA:
        return FuenteTuberia(direccion_de_entorno(), authkey_de_entorno(), buzon.al_senal, reloj,
                             motor_hash_esperado=cfg.motor_hash, version_minima=VERSION,
                             al_aviso=buzon.al_aviso_nivel)
    if texto == FUENTE_PROCESO:
        return FuenteEnProceso(_estrategias_para_motor(cfg), buzon.al_senal, reloj, al_aviso=buzon.al_aviso_nivel)
    prefijo = FUENTE_GRABACION + "="
    if texto.startswith(prefijo) and texto[len(prefijo):].strip():
        return FuenteGrabacion(Path(texto[len(prefijo):].strip()), _estrategias_para_motor(cfg), buzon.al_senal, reloj,
                               al_aviso=buzon.al_aviso_nivel)
    raise ValueError(f"{ENV_FUENTE} debe ser «{FUENTE_TUBERIA}», «{FUENTE_PROCESO}» o «{FUENTE_GRABACION}=<ruta>»")


def _estrategias_para_motor(cfg: Config) -> list[dict]:
    """Las filas que espera `RunnerAlertas` (la API del motor es float: frontera única con el motor existente)."""
    filas = []
    for e in cfg.estrategias.values():
        filas.append({
            "strategy_id": e.strategy_id, "name": e.name, "riesgo_usd": float(e.riesgo_usd),
            "riesgo_piramide_usd": float(e.riesgo_piramide_usd) if e.riesgo_piramide_usd is not None else None,
            "riesgos_piramide": [float(r) if r is not None else None for r in e.riesgos_piramide],
            "ev_pct": float(e.ev_pct), "definition": copy.deepcopy(e.definition),
        })
    return filas


def _cuota_de(cfg: Config, reloj: Any) -> CuotaComandos:
    """`tecnicos.cuotas` del cuadro (manual L1996-2016 al margen) y la cadencia del inquire de locates."""
    cuotas = cfg.tecnicos.get("cuotas") or {}
    inquire = (cfg.locates or {}).get("inquiry_intervalo_s")
    return CuotaComandos(reloj, ordenes_s=_entero_positivo(cuotas.get("ordenes_s"), 50),
                         cancel_min=_entero_positivo(cuotas.get("cancel_min"), 100),
                         replace_min=_entero_positivo(cuotas.get("replace_min"), 100),
                         locate_min=_entero_positivo(cuotas.get("locate_min"), 100),
                         inquire_s=_numero_positivo(inquire, LOCATES_INQUIRE_S),
                         margen=min(1.0, _numero_positivo(cuotas.get("margen"), 0.9)))


def _plan_de(cfg: Config) -> PlanReconexion:
    """R-J-02: `tecnicos.das_reconexion_s` (2, 4, 8, 16, 30): los primeros son las esperas y el último el tope."""
    valores = cfg.tecnicos.get("das_reconexion_s")
    if isinstance(valores, list) and len(valores) >= 2 and all(
            not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in valores):
        return PlanReconexion(tuple(float(v) for v in valores[:-1]), float(valores[-1]))
    return PlanReconexion()


def _chat_ids_de_entorno() -> frozenset[int]:
    """`BOT_DAS_CHAT_IDS` = enteros separados por comas (R-Q-01). Los que no son enteros se ignoran (sin mostrarlos)."""
    ids: set[int] = set()
    malos = 0
    for trozo in os.environ.get(ENV_CHAT_IDS, "").split(","):
        trozo = trozo.strip()
        if not trozo:
            continue
        try:
            ids.add(int(trozo))
        except ValueError:
            malos += 1
    if malos:
        logger.warning("[EJECUTOR] %s: %d valor(es) no enteros ignorados", ENV_CHAT_IDS, malos)
    return frozenset(ids)


# ══════════════════════════════════════════════════════════════════════
# Ayudas puras
# ══════════════════════════════════════════════════════════════════════
def _share_es_abierta(cfg: Config) -> bool:
    """A-02: `cfg.stops.replace_share_es_abierta` si es un bool; si no, el defecto de tipos (lo mismo que reglas.stops)."""
    bloque = cfg.stops if isinstance(cfg.stops, dict) else {}
    valor = bloque.get("replace_share_es_abierta")
    return valor if isinstance(valor, bool) else REPLACE_SHARE_ES_ABIERTA


def _tiene_precarga(referencia: Any) -> bool:
    """G1A-03: la referencia ofrece la precarga para un hilo de borde (la `Referencia` real; no la de memoria)."""
    return referencia is not None and all(callable(getattr(referencia, nombre, None))
                                          for nombre in ("precargar_splits", "tomar_pendientes", "precargar_ficha"))


def _campos_dataclass(objeto: Any) -> tuple:
    """Los campos de una dataclass (MemoriaDecisor) o () si no lo es."""
    return dataclasses.fields(objeto) if dataclasses.is_dataclass(objeto) else ()


def _es_apertura(o: OrdenNueva) -> bool:
    """Corrección 4: abre posición toda entrada (agregar/cruce, pirámides «add» incluidas) y toda venta en CORTO."""
    return o.proposito in _PROPOSITOS_APERTURA or o.lado is Lado.CORTO


def _es_consulta_de_cuenta(linea: str) -> bool:
    """R-O-03: en sombra estas consultas se le hacen al emparejador (la cuenta simulada), no al DAS real."""
    palabras = linea.split()
    if not palabras:
        return False
    primera = palabras[0].upper()
    if primera == "GET":
        return len(palabras) >= 2 and f"GET {palabras[1].upper()}" in CONSULTAS_DE_CUENTA
    return primera in CONSULTAS_DE_CUENTA


def _fills_simulados(mensajes: Sequence[MensajeDAS]) -> list[dict]:
    """§8: `orden_simulada` lleva los fills que el emparejador dio AL RECIBIR la orden (los posteriores van como `fill`)."""
    trades = [{"id_trade": m.id, "qty": m.qty, "precio": m.precio} for m in mensajes if isinstance(m, MsgTrade)]
    if trades:
        return trades
    return [{"id": m.id, "qty": m.qty, "precio": m.precio} for m in mensajes
            if isinstance(m, MsgOrderAct) and m.accion == "Execute"]


def _escribir_atomico(ruta: Path, texto: str) -> None:
    """tmp en el MISMO directorio + os.replace (atómico en Windows): el cuadro nunca lee una foto a medias."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_name(f"{ruta.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(texto)
            f.flush()
        os.replace(tmp, ruta)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _entero_positivo(valor: Any, defecto: int) -> int:
    if isinstance(valor, bool) or not isinstance(valor, (int, float, Decimal)):
        return defecto
    try:
        entero = int(valor)
    except (TypeError, ValueError, OverflowError):
        return defecto
    return entero if entero >= 1 and entero == valor else defecto


def _numero_positivo(valor: Any, defecto: float) -> float:
    if isinstance(valor, bool) or not isinstance(valor, (int, float, Decimal)):
        return float(defecto)
    numero = float(valor)
    return numero if math.isfinite(numero) and numero > 0 else float(defecto)


# ══════════════════════════════════════════════════════════════════════
# python -m app.bot_das.ejecutor
# ══════════════════════════════════════════════════════════════════════
def _cargar_dotenv(ruta: Path) -> None:
    """Carga `backend/.env` (solo si existe) SIN pisar el entorno del proceso. No lee ni muestra valores."""
    if not ruta.is_file():
        return
    try:
        from dotenv import load_dotenv   # perezoso: importar el módulo no carga dependencias opcionales
    except ImportError:
        return
    load_dotenv(ruta, override=False)


def _reloj_para_fuente(texto: str) -> Any:
    """Reloj real, o un `RelojSimulado` a las 03:55 ET del día de la grabación (`AM_AAAA-MM-DD…`) para el replay."""
    prefijo = FUENTE_GRABACION + "="
    if not texto.startswith(prefijo):
        return mod_reloj.Reloj()
    fecha = _RE_FECHA_GRABACION.search(Path(texto[len(prefijo):].strip()).name)
    if fecha is None:
        raise ValueError("la grabación debe llamarse AM_AAAA-MM-DD…: sin fecha no se sabe qué día reproducir")
    dia = date(int(fecha.group(1)), int(fecha.group(2)), int(fecha.group(3)))
    return mod_reloj.RelojSimulado(mod_reloj.a_hora_et("03:55", dia))


def _instalar_senales(ejecutor: Ejecutor) -> None:
    """Ctrl+C / Ctrl+Break → parada ordenada (el `terminate` del supervisor no se puede capturar en Windows)."""
    def manejador(signum: int, _frame: Any) -> None:
        ejecutor.pedir_parada(f"señal {signum}", CODIGO_OK)

    if threading.current_thread() is not threading.main_thread():
        return
    for nombre in ("SIGINT", "SIGBREAK", "SIGTERM"):
        numero = getattr(signal, nombre, None)
        if numero is not None:
            try:
                signal.signal(numero, manejador)
            except (OSError, ValueError):  # frontera del SO: una señal que no se puede capturar se deja como está
                pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    """`python -m app.bot_das.ejecutor [--config ruta] [--fuente tuberia|proceso|grabacion=ruta] [--base ruta]`.

    Orden: `.env` (en silencio) → logging con `FiltroSecretos` de los
    valores del entorno ANTES de la primera línea de log (R-Q-01, corrección
    8) → config con respaldo (H-4) → `construir_desde_env` → `arrancar` →
    `correr` → `parar` siempre. Códigos: 0 parada ordenada, 2 reloj, 3 doble
    instancia, 4 motor, 5 config/entorno, 1 error no previsto.
    """
    parser = argparse.ArgumentParser(prog="python -m app.bot_das.ejecutor", description="Ejecutor del bot de DAS")
    parser.add_argument("--config", type=Path, default=None,
                        help="fichero del cuadro (defecto: BOT_DAS_DIR/config/bot_das_config.json)")
    parser.add_argument("--fuente", default=None, help="tuberia | proceso | grabacion=<ruta> (defecto: BOT_DAS_FUENTE)")
    parser.add_argument("--base", type=Path, default=None, help="directorio backend (hash del motor)")
    args = parser.parse_args(list(argv) if argv is not None else None)
    backend = Path(__file__).resolve().parents[2]
    _cargar_dotenv(RUTA_DOTENV if RUTA_DOTENV is not None else backend / ".env")
    if args.fuente:
        os.environ[ENV_FUENTE] = args.fuente
    dir_bot = directorio_bot()
    try:
        reloj = _reloj_para_fuente(os.environ.get(ENV_FUENTE, "").strip())
    except ValueError as exc:
        print(f"ejecutor: {exc}", file=sys.stderr)
        return CODIGO_CONFIG
    mod_avisos.instalar_logging("ejecutor", dir_bot / "logs", mod_avisos.secretos_desde_env(), reloj=reloj)
    try:
        cuenta = os.environ.get(ENV_CUENTA, "").strip()
        if not cuenta:
            logger.error("[EJECUTOR] falta %s en el entorno (R-Q-01): no se puede cargar la config", ENV_CUENTA)
            return CODIGO_CONFIG
        ruta_cfg = args.config or dir_bot / "config" / mod_config.NOMBRE_FICHERO_CONFIG
        try:
            cfg, aviso = mod_config.cargar_con_respaldo(ruta_cfg, dir_bot / "config" / mod_config.NOMBRE_ULTIMO_BUENO,
                                                        cuenta)
            ejecutor = construir_desde_env(cfg, reloj, args.base or backend, ruta_config=ruta_cfg, aviso_config=aviso)
        except (mod_config.ConfigInvalida, RuntimeError, ValueError, OSError) as exc:
            logger.error("[EJECUTOR] no arranca: %s: %s", type(exc).__name__, exc)
            return CODIGO_CONFIG
        _instalar_senales(ejecutor)
        codigo = CODIGO_ERROR
        try:
            codigo = ejecutor.arrancar()
            if codigo == CODIGO_OK:
                codigo = ejecutor.correr()
        except Exception:  # noqa: BLE001 — frontera del proceso: se registra y el supervisor relanza (R-J-04 a)
            logger.exception("[EJECUTOR] error no previsto")
            codigo = CODIGO_ERROR
        finally:
            ejecutor.parar()
        logger.info("[EJECUTOR] sale con código %d", codigo)
        return codigo
    finally:
        mod_avisos.desinstalar_logging()


if __name__ == "__main__":
    sys.exit(main())
