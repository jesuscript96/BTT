"""Proceso vigilante del bot de DAS: conexión watch, plan B de los stops, neteo con el ejecutor y ping externo.

QUÉ HACE. `VigilanteDAS` es el segundo proceso de R-C-08 (§3.27, §6.1). Tiene
su propia conexión con DAS en modo watch (`LOGIN … 1`, solo lectura), por la
que llegan `%IPOS/%IORDER/%ITRADE` de TODA la cuenta, y con ello lleva un libro
propio de posiciones y órdenes. Cada segundo junta la `vigilancia.Foto`
(libro de DAS + lotes de los diarios + edad del latido del ejecutor +
cotizaciones de DAS + locates + equity), llama a `reglas.vigilancia.comprobar`
y ejecuta lo que devuelve: reponer el stop de cada nivel (stop único, Jaume
29-sep) si el ejecutor calla (plan B de R-C-07), proteger una posición que ningún diario
conoce (R-C-10 caso 4), cancelar sobrantes, VENDER SOLO el exceso de una
cuenta que quedó LARGA con el ejecutor muerto (E2c-02, R-C-11 (3)), avisar
(R-C-08 a, R-H-02/03, 2c) y, si no puede enviar, pedir al supervisor que
relance el ejecutor (corrección 16). La misma propuesta no se anota en cada
pasada (E2c-04: `comprobar_con_firmas` + `Foto.anotado`). Las órdenes salen por una SEGUNDA conexión normal que abre bajo demanda
(`abrir_accion`). Además manda el ping externo de R-J-05 (`PingExterno`, cada
60 s y solo si todo va bien: su silencio es la alarma), late para el
supervisor (R-J-04) y escribe su propio diario (`diario_vigilante_…`,
corrección 3). `construir_desde_env` monta las piezas de producción y `main`
es `python -m app.bot_das.vigilante`.

POR QUÉ ESTÁ AQUÍ. Toda la lógica de «qué falta y qué sobra» es la de
`reglas.vigilancia` (pura, probada con tablas); este módulo es el proceso: la
E/S (sockets, ficheros, diario, avisos) y el ritmo. Es un proceso aparte, y no
un hilo del ejecutor, porque tiene que seguir protegiendo cuando el ejecutor
es el roto (R-C-08, §6.1). Por eso NO importa `ejecutor.py` ni `decisor.py`:
si esos módulos no cargan, el vigilante sí.

LAS TRAMPAS.
  * Cerrojo sin lock compartido (R-C-08.2, §6.1): el vigilante solo ACTÚA si
    el latido del ejecutor tiene más de `plan_b_latido_s` (3 s) o si una
    posición lleva descubierta más de `plan_b_descubierta_s` (5 s); lo decide
    `vigilancia.comprobar`. «Descubierta desde» lo lleva este proceso con
    `actualizar_descubierta_desde` sobre el reloj inyectado.
  * Lo que el vigilante envía y DAS aún no ha devuelto por watch viaja en
    `Foto.pendientes` (y las cancelaciones y reemplazos pendientes se aplican
    a la vista del libro): sin eso, la pasada siguiente, un segundo después,
    pondría otra protección igual o repetiría el CANCEL (riesgo 11). Lo
    pendiente caduca a los `PENDIENTE_CADUCA_S`: si DAS no lo vio, se repone.
  * Un rechazo de DAS a un stop del vigilante no se reintenta en bucle
    (riesgo 11, R-C-03): entre dos intentos pasa `stops.separacion_reintentos_s`
    y, con `stops.reintentos` rechazos dentro de `stops.ventana_min` minutos,
    el ticker queda en CONTROL HUMANO (aviso 3, sin más envíos) hasta que
    caducan (entonces lo vuelve a intentar: con el stop único, unas
    acciones sin su stop no tienen otra red) o la posición desaparece. NO
    se olvidan porque otro stop cubra parte de la posición: el que se
    rechaza puede ser el de otro nivel.
  * Tokens del vigilante (`Origen.VIGILANTE`, R-C-07 «quién la puso»): el
    generador arranca en el último seq del día que aparezca en CUALQUIER
    registro de los dos diarios (un token no se reutiliza tras un reinicio,
    H-2). La pasada «en seco» (¿hace falta enviar?) y la que no puede enviar
    usan el token PREVISTO sin consumirlo: un vigilante bloqueado horas no
    agota la secuencia.
  * La conexión de acción se abre en un hilo de un solo uso y el bucle la
    espera como mucho `ESPERA_ABRIR_ACCION_S`: un `connect` de 5 s en el hilo
    principal pararía el latido y el supervisor mataría al vigilante por
    colgado (3 s). Si DAS no admite una segunda conexión normal (2e.1),
    `abrir_accion` devuelve None, `puede_enviar=False` y `comprobar` pide el
    relanzamiento del ejecutor (corrección 16, riesgo 31); la petición se
    escribe como mucho cada `PETICION_REPETIR_S`.
  * Fase SOMBRA (R-O-03): el vigilante NUNCA envía un mutante ni abre la
    conexión de acción. Lo que habría enviado queda en el diario como
    `vigilancia_simulada`, un tipo que `diario.reconstruir` NO convierte en
    órdenes (el ejecutor no hereda intenciones que no existieron).
  * El libro del watch se vacía en cada (re)conexión y no se actúa hasta
    tener el volcado completo (`#POSEND` y `#OrderEnd`) o hasta
    `VOLCADO_ESPERA_S`: una posición vista sin sus stops sería «descubierta» y
    se duplicarían. Si en `PEDIR_VOLCADO_S` no llega el volcado del LOGIN se
    piden `GET POSITIONS` y `GET ORDERS` (no se sabe si el watch real lo
    manda: paso 7 de comprobar_das); pedirlos siempre traería una copia VIEJA
    del libro detrás de las primeras acciones. Por lo mismo, un REPLACE o un
    CANCEL pendiente solo se da por hecho con su confirmación, nunca porque
    llegue cualquier línea de esa orden.
    Con el watch caído no se vigila: el libro está viejo; se avisa (2) una
    vez por caída y se reconecta por plan (2/4/8/16/30 s, R-J-02).
  * LOGIN RECHAZADO por DAS («ERROR:INVALID PASSWORD», DAS real 01-oct) en
    el watch o en la conexión de acción: aviso 3 UNA vez y ni el watch se
    reconecta ni se abre la de acción (una clave mala en bucle bloquea el
    usuario en DAS) hasta reiniciar el proceso con el `.env` corregido.
  * Los diarios se siguen por bytes (tamaño leído + `diario.leer_texto` del
    trozo nuevo hasta el último salto de línea): `LectorDiario.seguir` relee
    y parsea el fichero entero cada segundo. Solo se guardan los registros que
    importan para los lotes, pausas, BS y locates, y `reconstruir` solo se
    repite cuando llega alguno.
  * Relojes: todo lo que decide (plan B, pendientes, separación, dedupe)
    va con el reloj inyectado (`reloj.mono()`); el ritmo del bucle, la espera
    del volcado y las conexiones, con `time.monotonic()` real.
  * El diario no se llena cada segundo: un `Anotar("vigilancia")` sin
    acciones que repite lo mismo se escribe como mucho cada
    `ANOTAR_REPETIR_S`, y los avisos con clave cada `AVISO_REPETIR_S`.
  * Latido (injerto §8.11): solo late si el lector del watch y el hilo de
    avisos viven; un vigilante sordo se ve colgado y el supervisor lo relanza.
  * El ping nunca bloquea (hilo propio) y la URL (lleva el identificador del
    servicio) no se escribe en el log: `construir_desde_env` la añade a los
    secretos del `FiltroSecretos`.
  * Importar este módulo no abre red, no lee ficheros, no arranca hilos y no
    importa pandas.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import math
import os
import queue
import signal
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
from collections import deque
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from app.bot_das import VERSION
from app.bot_das import avisos as mod_avisos
from app.bot_das import config as mod_config
from app.bot_das import protocolo
from app.bot_das import reloj as mod_reloj
from app.bot_das import tokens as mod_tokens
from app.bot_das.cerrojo import CerrojoInstancia, Latido
from app.bot_das.cliente import ENV_PERMITIR_ORDENES, ClienteDAS, CuotaComandos, PlanReconexion
from app.bot_das.diario import Diario, LectorDiario, leer_texto, reconstruir, ultimo_seq_por_origen
from app.bot_das.mercado_das import MercadoDAS
from app.bot_das.reglas import precios, vigilancia
from app.bot_das.tipos import (
    MAX_LV1,
    PING_EXTERNO_S,
    PING_FALLOS_ALARMA,
    PLAN_B_LATIDO_S,
    STOP_REINTENTOS,
    STOP_VENTANA_MIN,
    Accion,
    Anotar,
    Avisar,
    Cancelar,
    CancelarTicker,
    Config,
    EnviarOrden,
    EstadoBot,
    EstadoOrden,
    EstadoTicker,
    Fase,
    Grupo,
    MensajeDAS,
    MsgConexion,
    MsgIssueStatus,
    MsgLDLU,
    MsgLogin,
    MsgMarcador,
    MsgOrden,
    MsgOrderAct,
    MsgPos,
    MsgQuote,
    MsgShortInfo,
    Nivel,
    Orden,
    OrdenDescartada,
    OrdenNueva,
    Origen,
    PedirAlSupervisor,
    Reemplazar,
    Registro,
    TipoOrden,
)
from app.bot_das.tokens import GeneradorTokens

__all__ = [
    "ColaVigilante", "PingExterno", "VigilanteDAS", "construir_desde_env", "directorio_bot", "main",
    "CODIGO_OK", "CODIGO_ERROR", "CODIGO_DOBLE_INSTANCIA", "CODIGO_CONFIG",
    "PERIODO_S", "ESPERA_COLA_S", "MENSAJES_POR_PASO", "PEDIR_VOLCADO_S", "VOLCADO_ESPERA_S", "PENDIENTE_CADUCA_S",
    "PENDIENTE_CADUCA_SOMBRA_S", "ESPERA_ABRIR_ACCION_S", "REABRIR_ACCION_S", "CERRAR_ACCION_INACTIVA_S",
    "PETICION_REPETIR_S", "ANOTAR_REPETIR_S", "AVISO_REPETIR_S", "EJECUTOR_CALLADO_AVISO_S", "FOTO_EJECUTOR_CADA_S",
    "PING_TIMEOUT_S", "ESPERA_AVISOS_S", "ESPERA_HILOS_S", "ESPERA_CONEXION_INICIAL_S", "AVISOS_BORDE_TOPE",
    "SEPARACION_REINTENTOS_S",
    "HORA_ENCENDER_DEFECTO", "HORA_APAGAR_DEFECTO", "TIPOS_RELEVANTES", "RUTA_DOTENV",
    "NOMBRE_LATIDO", "NOMBRE_CERROJO", "NOMBRE_LATIDO_EJECUTOR", "NOMBRE_ORDEN_SUPERVISOR", "NOMBRE_FOTO_EJECUTOR",
    "SUBCARPETAS_BOT", "ENV_DIR", "ENV_CUENTA", "ENV_PING_URL",
    "EVENTO_WATCH", "EVENTO_ESTADO_WATCH", "EVENTO_ACCION", "EVENTO_ESTADO_ACCION", "EVENTO_HILO",
    "EVENTO_INTENTO_WATCH", "EVENTO_DESCARTE",
]

logger = logging.getLogger(__name__)

# ── códigos de salida (los mismos números que el ejecutor) ────────────
CODIGO_OK = 0                   # parada ordenada (supervisor, señal)
CODIGO_ERROR = 1                # excepción no prevista en main (el supervisor relanza, R-J-04 a)
CODIGO_DOBLE_INSTANCIA = 3      # R-J-04 c / F11 e: otra instancia tiene el cerrojo
CODIGO_CONFIG = 5               # config o entorno imposibles: relanzar no lo arregla

# ── ritmo y plazos ────────────────────────────────────────────────────
PERIODO_S = 1.0                 # R-C-08 / §6.1: una pasada de vigilancia por segundo
ESPERA_COLA_S = 0.2             # espera máxima de la cola por vuelta del bucle
MENSAJES_POR_PASO = 10_000      # una ráfaga de DAS no puede dejar al bucle sin pasada ni latido
PEDIR_VOLCADO_S = 1.0           # sin volcado del LOGIN en este plazo, se piden GET POSITIONS y GET ORDERS
VOLCADO_ESPERA_S = 3.0          # sin #POSEND/#OrderEnd tras conectar, se vigila igual pasado este plazo
PENDIENTE_CADUCA_S = 5.0        # lo enviado que DAS no ha devuelto por watch en este plazo se repone (riesgo 11)
PENDIENTE_CADUCA_SOMBRA_S = 60.0   # sombra: lo «simulado» no aparece nunca en DAS; se repite como mucho cada minuto
ESPERA_ABRIR_ACCION_S = 1.0     # el bucle espera la conexión de acción como mucho esto (latido < 3 s)
REABRIR_ACCION_S = 5.0          # tras no poder abrir la conexión de acción, no se reintenta antes
CERRAR_ACCION_INACTIVA_S = 60.0   # «bajo demanda»: sin nada que enviar, la segunda conexión se cierra
PETICION_REPETIR_S = 10.0       # corrección 16: la misma petición al supervisor como mucho cada 10 s
ANOTAR_REPETIR_S = 60.0         # un «vigilancia» sin acciones idéntico al anterior no se repite antes
AVISO_REPETIR_S = mod_avisos.DEDUPE_VENTANA_S   # misma ventana de dedupe que la cola de avisos (60 s)
EJECUTOR_CALLADO_AVISO_S = 30.0   # R-C-08 (c): «el ejecutor no late» se avisa si dura más (el supervisor relanza en 1-10 s)
FOTO_EJECUTOR_CADA_S = 10.0     # el equity sale de estado/foto.json del ejecutor, releído como mucho cada 10 s
PING_TIMEOUT_S = 5.0            # R-J-05: GET con timeout 5 s
ESPERA_AVISOS_S = 30.0          # §6.2.5: avisos.parar(30)
ESPERA_HILOS_S = 6.0            # al parar: plazo para un connect en curso (timeout del cliente 5 s)
ESPERA_CONEXION_INICIAL_S = 2.0   # arrancar() espera la primera conexión watch como mucho esto
AVISOS_BORDE_TOPE = 1000        # avisos de los hilos de borde pendientes de pasar al hilo principal
SEPARACION_REINTENTOS_S = 2.0   # R-C-03: separación entre reintentos de un stop rechazado ([PENDIENTE] en §7: 2 s)
HORA_ENCENDER_DEFECTO = "03:55"   # R-L-01 / §7 horario.encender
HORA_APAGAR_DEFECTO = "20:00"   # sin horario.apagar: las DAY+ caducan a las 20:00 (no se pinga después)

# ── ficheros (dentro de BOT_DAS_DIR/estado) y entorno ─────────────────
NOMBRE_LATIDO = "latido_vigilante"
NOMBRE_CERROJO = "cerrojo_vigilante.lock"
NOMBRE_LATIDO_EJECUTOR = "latido_ejecutor"
NOMBRE_ORDEN_SUPERVISOR = "orden_supervisor.jsonl"
NOMBRE_FOTO_EJECUTOR = "foto.json"
SUBCARPETAS_BOT = ("config", "diario", "estado", "cache", "logs")
ENV_DIR = "BOT_DAS_DIR"
ENV_CUENTA = "DAS_CUENTA"
ENV_PING_URL = "BOT_DAS_PING_URL"
RUTA_DOTENV: Optional[Path] = None   # None = backend/.env (lo carga SOLO main; un test lo apunta a otro sitio)

# ── eventos de la cola del vigilante (tuplas: la etiqueta va primero) ──
EVENTO_WATCH = "watch"                    # (EVENTO_WATCH, MensajeDAS)
EVENTO_ESTADO_WATCH = "estado_watch"      # (EVENTO_ESTADO_WATCH, conectado, motivo)
EVENTO_ACCION = "accion"                  # (EVENTO_ACCION, MsgOrderAct) de la conexión de acción
EVENTO_ESTADO_ACCION = "estado_accion"    # (EVENTO_ESTADO_ACCION, conectado, motivo)
EVENTO_HILO = "hilo"                      # (EVENTO_HILO, nombre, error, relanzado)
EVENTO_INTENTO_WATCH = "intento_watch"    # (EVENTO_INTENTO_WATCH, conectado): resultado de un intento de conexión
EVENTO_DESCARTE = "descarte"              # (EVENTO_DESCARTE, OrdenDescartada): el emisor de acción NO mandó un NEWORDER

# Registros de los diarios que cambian lo que ve el vigilante (lotes, pausas/BS, locates, fase).
TIPOS_RELEVANTES = frozenset({"arranque", "config", "lote", "pausa", "reanudar", "bs", "bs_informe", "comando",
                              "locate_intencion", "locate_estado", "locates_deshabilitar"})
_TIPOS_LOCATE = ("locate_intencion", "locate_estado")
_MARCADORES_VOLCADO = frozenset({"#POSEND", "#OrderEnd"})
_ESTADOS_VIVOS = frozenset({EstadoOrden.SENDING, EstadoOrden.ACCEPTED, EstadoOrden.PARTIAL, EstadoOrden.HOLD,
                            EstadoOrden.TRIGGERED})
_RECHAZOS_ACCION = frozenset({"Send_Rej", "CancelRej", "ReplaceRej"})
_PROCESOS_DIARIO = ("ejecutor", "vigilante")
_TIPO_ANOTACION_VIGILANCIA = vigilancia.TIPO_ANOTACION


# ══════════════════════════════════════════════════════════════════════
# La cola del vigilante
# ══════════════════════════════════════════════════════════════════════
class ColaVigilante:
    """La cola única del vigilante (§6.1): lo que llega de los hilos de borde. Segura entre hilos; nunca bloquea.

    El watch entrega con `al_mensaje`/`al_estado`; la conexión de acción con
    `al_mensaje_accion`/`al_estado_accion` (de ella solo interesan los
    `%OrderAct`: el resto de su volcado y sus eventos ya llegan por watch);
    las caídas de hilos con `al_caida_hilo`. Los avisos de los hilos de borde
    (cola de salida llena, líneas descartadas, ping) van a una cola APARTE con
    tope `tope_avisos`: se descarta el más viejo y se cuenta en
    `avisos_perdidos`.
    """

    def __init__(self, tope_avisos: int = AVISOS_BORDE_TOPE) -> None:
        if type(tope_avisos) is not int or tope_avisos < 1:
            raise ValueError(f"tope_avisos debe ser un entero ≥ 1: {tope_avisos!r}")
        self._cola: "queue.Queue[tuple]" = queue.Queue()
        self._avisos: deque[tuple[Nivel, str, Optional[str]]] = deque()
        self._tope_avisos = tope_avisos
        self._cerrojo = threading.Lock()
        self._avisos_perdidos = 0
        self._descartados_accion = 0

    # ── lado de los hilos de borde ──
    def al_mensaje(self, msg: MensajeDAS) -> None:
        """Mensaje de la conexión WATCH (hilo das-lector). TypeError si no es un MensajeDAS."""
        if not isinstance(msg, MensajeDAS):
            raise TypeError(f"al_mensaje espera un MensajeDAS, no {type(msg).__name__}")
        self._cola.put((EVENTO_WATCH, msg))

    def al_estado(self, conectado: bool, motivo: str) -> None:
        """Transición de la conexión watch (el cliente llama a True ANTES del volcado)."""
        self._cola.put((EVENTO_ESTADO_WATCH, bool(conectado), str(motivo)))

    def al_mensaje_accion(self, msg: MensajeDAS) -> None:
        """Mensaje de la conexión de ACCIÓN: solo pasan los `%OrderAct` y el resultado del LOGIN (`MsgLogin`)."""
        if isinstance(msg, (MsgOrderAct, MsgLogin)):
            self._cola.put((EVENTO_ACCION, msg))
            return
        with self._cerrojo:
            self._descartados_accion += 1

    def al_estado_accion(self, conectado: bool, motivo: str) -> None:
        self._cola.put((EVENTO_ESTADO_ACCION, bool(conectado), str(motivo)))

    def al_caida_hilo(self, nombre: str, error: str, relanzado: bool) -> None:
        """Injerto §8.11: un `HiloVigilado` del cliente cayó (y quizá se relanzó)."""
        self._cola.put((EVENTO_HILO, str(nombre), str(error), bool(relanzado)))

    def al_intento_watch(self, conectado: bool) -> None:
        """Resultado de un intento de conexión watch (lo pone el hilo de reconexión)."""
        self._cola.put((EVENTO_INTENTO_WATCH, bool(conectado)))

    def al_descartar(self, msg: OrdenDescartada) -> None:
        """D2a-06 / G2-05: `ClienteDAS.al_descartar` de la conexión de ACCIÓN (un NEWORDER que no salió)."""
        self._cola.put((EVENTO_DESCARTE, msg))

    def al_aviso(self, texto: str) -> None:
        """Aviso de nivel 2 de un hilo de borde (firma de `ClienteDAS.al_aviso`)."""
        self.al_aviso_nivel(int(Nivel.AVISO), texto)

    def al_aviso_nivel(self, nivel: int, texto: str, clave: Optional[str] = None) -> None:
        """Aviso de un hilo de borde con su nivel (fuera de 1-3 pasa a 2) y clave de dedupe opcional."""
        try:
            n = Nivel(int(nivel))
        except (TypeError, ValueError):
            n = Nivel.AVISO
        with self._cerrojo:
            if len(self._avisos) >= self._tope_avisos:
                self._avisos.popleft()
                self._avisos_perdidos += 1
            self._avisos.append((n, str(texto), None if clave is None else str(clave)))

    # ── lado del hilo principal ──
    def sacar(self, espera_s: float) -> Optional[tuple]:
        """El siguiente evento, esperando hasta `espera_s` (0 = sin esperar); None si no hay."""
        try:
            if espera_s <= 0:
                return self._cola.get_nowait()
            return self._cola.get(timeout=espera_s)
        except queue.Empty:
            return None

    def tamano(self) -> int:
        return self._cola.qsize()

    def avisos_pendientes(self) -> list[tuple[Nivel, str, Optional[str]]]:
        """Saca y devuelve los avisos de borde acumulados, en orden."""
        with self._cerrojo:
            salida = list(self._avisos)
            self._avisos.clear()
        return salida

    @property
    def avisos_perdidos(self) -> int:
        return self._avisos_perdidos

    @property
    def descartados_accion(self) -> int:
        """Mensajes de la conexión de acción que no eran `%OrderAct` (volcado y eventos: ya llegan por watch)."""
        return self._descartados_accion


# ══════════════════════════════════════════════════════════════════════
# Ping externo (R-J-05)
# ══════════════════════════════════════════════════════════════════════
class PingExterno:
    """R-J-05: un GET silencioso cada `cada_s` a un servicio externo; si faltan 3 seguidos, el servicio da la alarma.

    `url` es `BOT_DAS_PING_URL`: vacía o que no sea http(s) → no pinga y avisa
    (nivel 2) UNA vez por `al_aviso(nivel, texto, clave)`. `abrir(url,
    timeout=…)` es `urllib.request.urlopen` (inyectable). El GET corre en un
    hilo de un solo uso: `tocar_si_toca` NUNCA bloquea ni lanza, y con un
    GET en curso no lanza otro. Un GET que falla (excepción o estado ≠ 2xx)
    cuenta en `fallos_seguidos`; al llegar a `fallos_alarma` se avisa (2)
    una vez por racha: el servicio externo va a alarmar y el motivo es la
    red de ESTA máquina. La URL no se escribe nunca en el log.
    """

    def __init__(self, url: str, reloj: Any, cada_s: float = PING_EXTERNO_S,
                 abrir: Callable[..., Any] = urllib.request.urlopen, *, timeout_s: float = PING_TIMEOUT_S,
                 fallos_alarma: int = PING_FALLOS_ALARMA,
                 al_aviso: Optional[Callable[[int, str, Optional[str]], None]] = None) -> None:
        for nombre, valor in (("cada_s", cada_s), ("timeout_s", timeout_s)):
            if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor) or valor <= 0:
                raise ValueError(f"{nombre} debe ser un número finito > 0: {valor!r}")
        if type(fallos_alarma) is not int or fallos_alarma < 1:
            raise ValueError(f"fallos_alarma debe ser un entero ≥ 1: {fallos_alarma!r}")
        if not callable(abrir):
            raise TypeError("abrir debe ser una función (url, timeout=…) → respuesta")
        if al_aviso is not None and not callable(al_aviso):
            raise TypeError("al_aviso debe ser una función (nivel, texto, clave) -> None")
        self._url = (url or "").strip() if isinstance(url, str) else ""
        self._activo = _url_http_valida(self._url)
        self._reloj = reloj
        self._cada_s = float(cada_s)
        self._abrir = abrir
        self._timeout_s = float(timeout_s)
        self._fallos_alarma = fallos_alarma
        self._al_aviso = al_aviso
        self._cerrojo = threading.Lock()
        self._hilo: Optional[threading.Thread] = None
        self._ultimo_intento: Optional[float] = None
        self._aviso_url_dado = False
        self._alarma_dada = False
        self._intentos = 0
        self._enviados = 0
        self._fallos = 0
        self._fallos_seguidos = 0
        self._ultimo_error: Optional[str] = None
        self._ultimo_ok_en: Optional[float] = None

    # ── propiedades ──
    @property
    def activo(self) -> bool:
        """True si hay una URL http(s) válida (sin ella no se pinga nunca)."""
        return self._activo

    @property
    def cada_s(self) -> float:
        return self._cada_s

    @property
    def intentos(self) -> int:
        return self._intentos

    @property
    def enviados(self) -> int:
        """GET que devolvieron 2xx."""
        return self._enviados

    @property
    def fallos(self) -> int:
        return self._fallos

    @property
    def fallos_seguidos(self) -> int:
        return self._fallos_seguidos

    @property
    def ultimo_error(self) -> Optional[str]:
        return self._ultimo_error

    @property
    def ultimo_ok_en(self) -> Optional[float]:
        """epoch (del reloj inyectado) del último GET bueno."""
        return self._ultimo_ok_en

    @property
    def en_curso(self) -> bool:
        hilo = self._hilo
        return hilo is not None and hilo.is_alive()

    # ── uso ──
    def avisar_si_falta_url(self) -> bool:
        """R-J-05: sin URL válida avisa (nivel 2) UNA vez y devuelve True; con URL devuelve False. Nunca lanza."""
        if self._activo:
            return False
        if not self._aviso_url_dado:
            self._aviso_url_dado = True
            texto = (f"R-J-05: sin {ENV_PING_URL} válida (http/https) no hay ping externo: si la máquina se apaga "
                     f"NADIE avisará")
            logger.warning("[VIGILANTE] %s", texto)
            self._avisar(Nivel.AVISO, texto, "ping_sin_url")
        return True

    def tocar_si_toca(self, ahora: float) -> None:
        """Lanza el GET si pasaron `cada_s` desde el último intento (reloj `ahora`) y no hay otro en curso. NUNCA lanza ni bloquea."""
        try:
            if self.avisar_si_falta_url():
                return
            with self._cerrojo:
                if self._hilo is not None and self._hilo.is_alive():
                    return
                if self._ultimo_intento is not None and float(ahora) - self._ultimo_intento < self._cada_s:
                    return
                self._ultimo_intento = float(ahora)
                self._intentos += 1
                self._hilo = threading.Thread(target=self._cuerpo, name="ping-externo", daemon=True)
                self._hilo.start()
        except Exception as exc:  # noqa: BLE001 — frontera (R-J-05): el ping nunca tumba al vigilante
            logger.warning("[VIGILANTE] el ping externo no pudo lanzarse: %s", type(exc).__name__)

    def esperar(self, espera_s: float) -> bool:
        """Espera (hasta `espera_s`) a que termine el GET en curso; True si no queda ninguno (tests y apagado)."""
        hilo = self._hilo
        if hilo is not None and hilo is not threading.current_thread():
            hilo.join(max(0.0, float(espera_s)))
        return not self.en_curso

    # ── privados ──
    def _cuerpo(self) -> None:
        error: Optional[str] = None
        try:
            respuesta = self._abrir(self._url, timeout=self._timeout_s)
            try:
                estado = getattr(respuesta, "status", None)
                if estado is None and callable(getattr(respuesta, "getcode", None)):
                    estado = respuesta.getcode()
            finally:
                cerrar = getattr(respuesta, "close", None)
                if callable(cerrar):
                    cerrar()
            if estado is not None and not (200 <= int(estado) < 300):
                error = f"estado HTTP {int(estado)}"
        except Exception as exc:  # noqa: BLE001 — frontera de red (R-J-05): un GET que falla es un fallo contado, nunca una excepción
            error = f"{type(exc).__name__}: {self._sin_url(str(exc))}"
        avisar = False
        with self._cerrojo:
            if error is None:
                self._enviados += 1
                self._fallos_seguidos = 0
                self._alarma_dada = False
                try:
                    self._ultimo_ok_en = float(self._reloj.epoch())
                except Exception:  # noqa: BLE001 — frontera: un reloj raro no convierte un ping bueno en fallo
                    self._ultimo_ok_en = None
            else:
                self._fallos += 1
                self._fallos_seguidos += 1
                self._ultimo_error = error
                if self._fallos_seguidos >= self._fallos_alarma and not self._alarma_dada:
                    self._alarma_dada = True
                    avisar = True
        if error is None:
            logger.debug("[VIGILANTE] ping externo OK")
            return
        logger.warning("[VIGILANTE] ping externo fallido (%d seguidos): %s", self._fallos_seguidos, error)
        if avisar:
            self._avisar(Nivel.AVISO, f"R-J-05: el ping externo falla {self._fallos_seguidos} veces seguidas ({error}): "
                                      f"el servicio externo dará la alarma aunque el bot siga vivo; revisar la red",
                         "ping_fallos")

    def _avisar(self, nivel: Nivel, texto: str, clave: str) -> None:
        if self._al_aviso is None:
            return
        try:
            self._al_aviso(int(nivel), texto, clave)
        except Exception as exc:  # noqa: BLE001 — frontera de callback: un aviso que falla no tumba el ping
            logger.warning("[VIGILANTE] el aviso del ping no se pudo entregar: %s", type(exc).__name__)

    def _sin_url(self, texto: str) -> str:
        return texto.replace(self._url, mod_avisos.MASCARA) if self._url else texto


# ══════════════════════════════════════════════════════════════════════
# Seguidor incremental de un diario
# ══════════════════════════════════════════════════════════════════════
class _SeguidorDiario:
    """Lo nuevo de un diario desde el último byte leído, hasta el último salto de línea (riesgo 22). Interno."""

    def __init__(self, lector: LectorDiario, proceso: str) -> None:
        self._lector = lector
        self._proceso = proceso
        self._ruta: Optional[Path] = None
        self._offset = 0

    def leer(self, dia: date) -> list[Registro]:
        ruta = self._lector.ruta(dia, self._proceso)
        if ruta != self._ruta:
            self._ruta = ruta
            self._offset = 0
        try:
            tamano = os.stat(ruta).st_size
        except OSError:  # frontera de fichero: sin diario (aún) = nada nuevo (riesgo 22)
            return []
        if tamano < self._offset:
            self._offset = 0                           # truncado o sustituido: se relee desde el principio
        if tamano == self._offset:
            return []
        try:
            with open(ruta, "rb") as fichero:
                fichero.seek(self._offset)
                bloque = fichero.read(tamano - self._offset)
        except OSError:  # frontera de fichero: se vuelve a intentar en la pasada siguiente
            return []
        corte = bloque.rfind(b"\n")
        if corte < 0:
            return []                                  # una línea a medio escribir: la verá la pasada siguiente
        self._offset += corte + 1
        texto = bloque[:corte + 1].decode("utf-8", errors="replace")
        return leer_texto(texto, self._proceso, str(ruta), cola_sin_fin=False)


# ══════════════════════════════════════════════════════════════════════
# El proceso vigilante
# ══════════════════════════════════════════════════════════════════════
class VigilanteDAS:
    """Proceso vigilante (§3.27, R-C-07 plan B, R-C-08, R-J-04, R-J-05, corrección 16).

    `watch`: `ClienteDAS` en modo watch y solo lectura que entrega a
    `cola.al_mensaje`/`cola.al_estado` (¡la MISMA `cola` que se pasa aquí!).
    `abrir_accion()`: devuelve un cliente NORMAL con permiso de envío (ya
    conectado o que se conectará con `conectar()`), o None si no se puede;
    solo se llama fuera de la fase SOMBRA. `lector`: `LectorDiario` de la
    carpeta de diarios; `diario`: el propio (proceso «vigilante»);
    `avisos`: cola de avisos (poner/arrancar/parar); `reloj`: mono/ahora/hoy/
    epoch; `latido`: el latido de este proceso; `cerrojo`: su cerrojo;
    `ruta_latido_ejecutor`: el latido del ejecutor (plan B); `ping`:
    `PingExterno` o None; `ruta_orden_supervisor`: `estado/orden_supervisor.jsonl`.
    Por nombre: `cola`, `mercado` (libro de cotizaciones de DAS), `ruta_foto_
    ejecutor` (de ella sale el equity), `dentro_de_ventana(ahora_et)` (R-L-01
    para el ping), `plan_reconexion` (R-J-02), `periodo_s`,
    `espera_avisos_s` y `aviso_config` (el aviso de
    `config.cargar_con_respaldo`; R2-PRO-3: sale al arrancar, nivel 3 si
    lleva `config.AVISO_FASE_FORZADA`).
    """

    def __init__(self, cfg: Config, watch: Any, abrir_accion: Callable[[], Any], lector: LectorDiario,
                 diario: Diario, avisos: Any, reloj: Any, latido: Latido, cerrojo: CerrojoInstancia,
                 ruta_latido_ejecutor: Path, ping: Optional[PingExterno], ruta_orden_supervisor: Path, *,
                 cola: Optional[ColaVigilante] = None, mercado: Optional[MercadoDAS] = None,
                 ruta_foto_ejecutor: Optional[Path] = None,
                 dentro_de_ventana: Optional[Callable[[datetime], bool]] = None,
                 plan_reconexion: Optional[PlanReconexion] = None, periodo_s: float = PERIODO_S,
                 espera_avisos_s: float = ESPERA_AVISOS_S, aviso_config: Optional[str] = None) -> None:
        if not isinstance(cfg, Config):
            raise TypeError(f"cfg debe ser una Config, no {type(cfg).__name__}")
        for nombre in ("conectar", "cerrar", "enviar"):
            if not callable(getattr(watch, nombre, None)):
                raise TypeError(f"watch debe tener {nombre}()")
        if not callable(abrir_accion):
            raise TypeError("abrir_accion debe ser una función () -> cliente o None")
        if not isinstance(lector, LectorDiario):
            raise TypeError("lector debe ser un LectorDiario")
        if not isinstance(diario, Diario):
            raise TypeError("diario debe ser un Diario")
        for nombre in ("poner", "arrancar", "parar"):
            if not callable(getattr(avisos, nombre, None)):
                raise TypeError(f"avisos debe tener {nombre}()")
        for nombre in ("mono", "ahora", "hoy", "epoch"):
            if not callable(getattr(reloj, nombre, None)):
                raise TypeError(f"reloj debe tener {nombre}()")
        if not isinstance(latido, Latido):
            raise TypeError("latido debe ser un cerrojo.Latido")
        if not isinstance(cerrojo, CerrojoInstancia):
            raise TypeError("cerrojo debe ser un cerrojo.CerrojoInstancia")
        if ping is not None and not isinstance(ping, PingExterno):
            raise TypeError("ping debe ser un PingExterno o None")
        if cola is not None and not isinstance(cola, ColaVigilante):
            raise TypeError("cola debe ser una ColaVigilante")
        if mercado is not None and not isinstance(mercado, MercadoDAS):
            raise TypeError("mercado debe ser un MercadoDAS")
        if dentro_de_ventana is not None and not callable(dentro_de_ventana):
            raise TypeError("dentro_de_ventana debe ser una función (ahora_et) -> bool")
        if plan_reconexion is not None and not isinstance(plan_reconexion, PlanReconexion):
            raise TypeError("plan_reconexion debe ser un cliente.PlanReconexion")
        for nombre, valor in (("periodo_s", periodo_s), ("espera_avisos_s", espera_avisos_s)):
            if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor) or valor < 0:
                raise ValueError(f"{nombre} debe ser un número finito ≥ 0: {valor!r}")
        if periodo_s <= 0:
            raise ValueError(f"periodo_s debe ser > 0: {periodo_s!r}")
        if aviso_config is not None and not isinstance(aviso_config, str):
            raise TypeError("aviso_config debe ser un texto o None")
        self._cfg = cfg
        self._aviso_config = aviso_config or None       # R2-PRO-3: aviso de cargar_con_respaldo (se da al arrancar)
        self._watch = watch
        self._abrir_accion = abrir_accion
        self._lector = lector
        self._diario = diario
        self._avisos = avisos
        self._reloj = reloj
        self._latido = latido
        self._cerrojo = cerrojo
        self._ruta_latido_ejecutor = Path(ruta_latido_ejecutor)
        self._ping = ping
        self._ruta_orden_supervisor = Path(ruta_orden_supervisor)
        self._cola = cola if cola is not None else ColaVigilante()
        vig = _bloque(cfg.tecnicos, "vigilante")
        self._mercado = mercado if mercado is not None else MercadoDAS(
            reloj, max_lv1=_entero_positivo(cfg.tecnicos.get("max_lv1"), MAX_LV1))
        self._ruta_foto_ejecutor = (Path(ruta_foto_ejecutor) if ruta_foto_ejecutor is not None
                                    else self._ruta_latido_ejecutor.parent / NOMBRE_FOTO_EJECUTOR)
        self._dentro_de_ventana = dentro_de_ventana if dentro_de_ventana is not None else _ventana_por_horario(cfg)
        self._plan = plan_reconexion if plan_reconexion is not None else _plan_de(cfg)
        self._periodo_s = float(periodo_s)
        self._espera_avisos_s = float(espera_avisos_s)
        self._sombra = cfg.fase is Fase.SOMBRA
        self._plan_b_latido_s = _numero_positivo(vig.get("plan_b_latido_s"), PLAN_B_LATIDO_S)
        self._reintentos = _entero_positivo(cfg.stops.get("reintentos"), STOP_REINTENTOS)
        self._separacion_s = _numero_positivo(cfg.stops.get("separacion_reintentos_s"), SEPARACION_REINTENTOS_S)
        self._ventana_rechazos_s = 60.0 * _numero_positivo(cfg.stops.get("ventana_min"), STOP_VENTANA_MIN)
        # libro propio (watch)
        self._posiciones: dict[str, MsgPos] = {}
        self._ordenes: dict[int, MsgOrden] = {}
        self._fines_vistos: set[str] = set()
        self._watch_conectado_en: Optional[float] = None        # time.monotonic() del último «conectado»
        self._mensajes_watch = 0
        self._volcado_pedido = False
        self._aviso_watch_caido = False
        self._anotado_sin_watch = False
        # diarios
        self._seguidores = {p: _SeguidorDiario(lector, p) for p in _PROCESOS_DIARIO}
        self._registros: list[Registro] = []
        self._estado_diario: Optional[EstadoBot] = None
        self._estado_sucio = True
        self._dia: Optional[date] = None
        self._ultimo_seq_vigilante = 0
        self._tokens: Optional[GeneradorTokens] = None
        # lo enviado que DAS aún no ha devuelto (riesgo 11)
        self._pend_nuevas: dict[int, tuple[Orden, float]] = {}
        self._pend_cancel: dict[int, float] = {}
        self._pend_replace: dict[int, tuple[int, float]] = {}
        self._estado_propias: dict[int, tuple] = {}
        self._netas_anotadas: dict[str, int] = {}
        # plan B y rechazos
        self._descubierta_desde: dict[str, float] = {}
        self._rechazos: dict[str, list[float]] = {}
        self._tokens_rechazados: set[int] = set()
        # dedupe del diario, de los avisos y de las peticiones
        self._anotado: dict[str, tuple[str, float]] = {}
        self._firmas_vigilancia: dict[str, str] = {}      # E2c-04: lo último anotado por ticker (Foto.anotado)
        self._avisado_en: dict[str, float] = {}
        self._peticion_en: dict[str, float] = {}
        # ejecutor callado (R-C-08 c)
        self._ejecutor_callado_desde: Optional[float] = None
        self._aviso_ejecutor_dado = False
        # equity (de la foto del ejecutor)
        self._equity: Optional[Decimal] = None
        self._equity_leida_en: Optional[float] = None
        # conexión de acción (corrección 16)
        self._cerrojo_accion = threading.Lock()
        self._accion: Any = None
        self._hilo_accion: Optional[threading.Thread] = None
        self._accion_fallo_en: Optional[float] = None
        self._accion_usada_en: Optional[float] = None
        self._accion_aperturas = 0
        # reconexión del watch (R-J-02)
        self._hilo_watch: Optional[threading.Thread] = None
        self._proximo_intento_watch = 0.0
        self._login_rechazado: Optional[str] = None       # DAS rechazó el LOGIN (01-oct): ni watch ni acción vuelven a entrar
        self._anotado_login_parado = False
        # bucle
        self._proxima_pasada = 0.0
        self._codigo: Optional[int] = None
        self._motivo_salida = ""
        self._arrancado = False
        self._listo = False
        self._parado = False
        self._diario_abierto = False
        self._orden_offset = 0
        self._latido_retenido: Optional[dict] = None
        self._enviadas = 0
        self._pasadas = 0
        self._excepciones = 0

    # ── propiedades ──
    @property
    def cfg(self) -> Config:
        return self._cfg

    @property
    def cola(self) -> ColaVigilante:
        return self._cola

    @property
    def mercado(self) -> MercadoDAS:
        return self._mercado

    @property
    def diario(self) -> Diario:
        return self._diario

    @property
    def watch(self) -> Any:
        return self._watch

    @property
    def ping(self) -> Optional[PingExterno]:
        return self._ping

    @property
    def sombra(self) -> bool:
        return self._sombra

    @property
    def codigo(self) -> Optional[int]:
        return self._codigo

    @property
    def posiciones(self) -> dict[str, MsgPos]:
        """Copia del libro de posiciones visto por watch (neta SIGNADA)."""
        return dict(self._posiciones)

    @property
    def ordenes(self) -> dict[int, MsgOrden]:
        """Copia del libro de órdenes visto por watch, por id de DAS."""
        return dict(self._ordenes)

    @property
    def pendientes(self) -> list[Orden]:
        """Órdenes enviadas por el vigilante que DAS aún no ha devuelto por watch."""
        return [orden for orden, _ in self._pend_nuevas.values()]

    @property
    def ultimo_seq_token(self) -> int:
        """Último seq de token del vigilante usado (o visto en los diarios de hoy)."""
        return self._tokens.ultimo_seq if self._tokens is not None else self._ultimo_seq_vigilante

    @property
    def enviadas(self) -> int:
        return self._enviadas

    @property
    def pasadas(self) -> int:
        return self._pasadas

    @property
    def listo(self) -> bool:
        return self._listo

    # ── ciclo de vida ──
    def arrancar(self) -> int:
        """R-J-04 / §6.2: avisos → cerrojo (3 si hay otra instancia) → latido → diario → diarios del día → watch.

        Devuelve 0 o el código de salida. La conexión watch se intenta en un
        hilo y se espera como mucho `ESPERA_CONEXION_INICIAL_S`; si no hay DAS
        el vigilante arranca igual y reconecta por plan (R-J-02). Una segunda
        llamada lanza RuntimeError.
        """
        if self._arrancado:
            raise RuntimeError("arrancar() solo se llama una vez")
        self._arrancado = True
        self._avisos.arrancar()
        if not self._cerrojo.adquirir():
            texto = (f"R-J-04 c: ya hay un vigilante vivo (cerrojo {self._cerrojo.ruta.name}); esta instancia NO "
                     f"arranca")
            logger.error("[VIGILANTE] %s", texto)
            self._poner_aviso(Nivel.MAXIMO, texto, "arranque:doble_instancia")
            self._codigo = CODIGO_DOBLE_INSTANCIA
            self._motivo_salida = texto
            return CODIGO_DOBLE_INSTANCIA
        self._latido.tocar(True)
        hoy = self._reloj.hoy()
        self._dia = hoy
        self._diario.abrir_dia(hoy, motor_hash=self._cfg.motor_hash, config_version=self._cfg.config_version,
                               estrategias_hash=self._cfg.estrategias_hash)
        self._diario_abierto = True
        self._diario.anotar("config", config_version=self._cfg.config_version, sha256=self._cfg.sha256,
                            fase=self._cfg.fase)
        if self._diario.degradado:
            self._avisar(Nivel.MAXIMO, "El diario del vigilante NO escribe: vigila y protege igual (corrección 4)",
                         "diario_vigilante", self._reloj.mono())
        if self._aviso_config:
            # R2-PRO-3 (SEG-02): la fase forzada a SOMBRA por usar el último bueno deja de reponer stops reales → 3
            forzada = mod_config.AVISO_FASE_FORZADA in self._aviso_config
            self._avisar(Nivel.MAXIMO if forzada else Nivel.AVISO, f"Vigilante: {self._aviso_config}",
                         "config_respaldo_vigilante", self._reloj.mono())
        self._leer_diarios(hoy)
        self._tokens = GeneradorTokens(Origen.VIGILANTE, hoy, min(self._ultimo_seq_vigilante, mod_tokens.MAX_SEQ))
        self._orden_offset = _tamano_fichero(self._ruta_orden_supervisor)
        if self._ping is not None:
            self._ping.avisar_si_falta_url()
        self._revisar_watch()
        hilo = self._hilo_watch
        if hilo is not None:
            hilo.join(ESPERA_CONEXION_INICIAL_S)
        self._drenar_avisos_de_borde()
        self._diario.anotar("vigilante_listo", fase=self._cfg.fase, sombra=self._sombra,
                            ultimo_seq_token=self._tokens.ultimo_seq, registros=len(self._registros),
                            watch_conectado=_conectado(self._watch), regla="R-C-08")
        self._listo = True
        logger.info("[VIGILANTE] listo (fase %s)", self._cfg.fase.value)
        return CODIGO_OK

    def correr(self) -> int:
        """R-C-08: `arrancar()` si no se hizo y el bucle (`paso`) hasta tener código. Devuelve el código."""
        if not self._arrancado:
            codigo = self.arrancar()
            if codigo != CODIGO_OK:
                return codigo
        elif not self._listo:
            raise RuntimeError("correr() tras un arrancar() que no devolvió 0")
        while True:
            codigo = self.paso()
            if codigo is not None:
                return codigo

    def paso(self, espera_s: float = ESPERA_COLA_S, forzar: bool = False) -> Optional[int]:
        """Una vuelta del bucle: cola (hasta `espera_s`), reconexión, orden del supervisor, pasada si toca, latido.

        La pasada de vigilancia se hace cada `periodo_s` (reales) o ya con
        `forzar=True`. Devuelve el código de salida si el bucle debe
        terminar, o None.
        """
        if self._codigo is not None:
            return self._codigo
        if not self._listo:
            raise RuntimeError("paso() antes de un arrancar() que devolviera 0")
        self._drenar_avisos_de_borde()
        espera = 0.0 if forzar else max(0.0, min(float(espera_s), self._proxima_pasada - time.monotonic()))
        evento = self._cola.sacar(espera)
        atendidos = 0
        while evento is not None:
            self._atender_seguro(evento)
            atendidos += 1
            if atendidos >= MENSAJES_POR_PASO:
                break
            evento = self._cola.sacar(0)
        self._drenar_avisos_de_borde()
        self._revisar_watch()
        self._revisar_orden_supervisor()
        if self._codigo is None and (forzar or time.monotonic() >= self._proxima_pasada):
            self._proxima_pasada = time.monotonic() + self._periodo_s
            self._pasada_segura()
            self._cerrar_accion_si_inactiva()
        self._tocar_latido()
        return self._codigo

    def pedir_parada(self, motivo: str = "parada pedida", codigo: int = CODIGO_OK) -> None:
        """Termina el bucle en la vuelta siguiente. Segura desde cualquier hilo (señales)."""
        if self._codigo is None:
            self._motivo_salida = str(motivo)
            self._codigo = int(codigo)

    def parar(self) -> None:
        """Apagado ordenado e idempotente; nunca lanza: acción, reconexión, ping, watch (QUIT), avisos, diario, cerrojo."""
        if self._parado:
            return
        self._parado = True
        if self._diario_abierto:
            self._seguro("anotar parada", lambda: self._diario.anotar(
                "parada", codigo=self._codigo, motivo=self._motivo_salida, enviadas=self._enviadas,
                pasadas=self._pasadas))
        self._seguro("hilo de la conexión de acción", lambda: self._unir(self._hilo_accion))
        self._seguro("conexión de acción", lambda: self._soltar_accion("parada del vigilante"))
        self._seguro("hilo de reconexión", lambda: self._unir(self._hilo_watch))
        if self._ping is not None:
            self._seguro("ping externo", lambda: self._ping.esperar(ESPERA_HILOS_S))
        self._seguro("conexión watch", self._watch.cerrar)
        self._seguro("avisos", lambda: self._avisos.parar(self._espera_avisos_s))
        if self._diario_abierto:
            self._seguro("diario", self._diario.cerrar)
        self._seguro("cerrojo", self._cerrojo.soltar)
        logger.info("[VIGILANTE] parado (código %s)", self._codigo)

    # ── eventos de la cola ──
    def _atender_seguro(self, evento: tuple) -> None:
        try:
            self._atender(evento)
        except Exception as exc:  # noqa: BLE001 — frontera de mensaje (H-5): un mensaje raro no deja sordo al vigilante
            self._excepcion("evento", exc)

    def _atender(self, evento: tuple) -> None:
        etiqueta = evento[0]
        if etiqueta == EVENTO_WATCH:
            self._de_watch(evento[1])
        elif etiqueta == EVENTO_ESTADO_WATCH:
            self._estado_watch(evento[1], evento[2])
        elif etiqueta == EVENTO_ACCION:
            if isinstance(evento[1], MsgLogin):
                self._login(evento[1], "accion")
            else:
                self._de_accion(evento[1])
        elif etiqueta == EVENTO_ESTADO_ACCION:
            self._diario.anotar("das_conexion", conexion="accion", conectado=evento[1], motivo=evento[2])
        elif etiqueta == EVENTO_HILO:
            self._hilo_caido(evento[1], evento[2], evento[3])
        elif etiqueta == EVENTO_INTENTO_WATCH:
            self._intento_watch(evento[1])
        elif etiqueta == EVENTO_DESCARTE:
            self._descartada(evento[1])

    def _descartada(self, msg: Any) -> None:
        """D2a-06 / G2-05: lo que el emisor no mandó deja de ser «pendiente»: la pasada siguiente lo repone ya."""
        token = getattr(msg, "token", None)
        if token is None or self._pend_nuevas.pop(token, None) is None:
            return
        self._diario.anotar("orden_descartada", token=token, ticker=getattr(msg, "ticker", None),
                            motivo=str(getattr(msg, "motivo", "")), regla="D2a-06")

    def _de_watch(self, msg: MensajeDAS) -> None:
        """Libro propio (R-C-08): %IPOS/%IORDER por clave, cotizaciones al mercado, marcadores del volcado."""
        self._mensajes_watch += 1
        ahora = self._reloj.mono()
        if isinstance(msg, MsgPos):
            ticker = str(msg.ticker).strip()
            if not ticker:
                return
            self._posiciones[ticker] = msg
            if self._netas_anotadas.get(ticker) != msg.neta:
                self._netas_anotadas[ticker] = msg.neta
                # en sombra la cuenta REAL no es la del ejecutor: «pos» la reconstruiría como su neta_das (R-O-03)
                self._diario.anotar("pos_watch" if self._sombra else "pos", ticker=ticker, tipo=msg.tipo,
                                    neta=msg.neta, avg=msg.avg, cruda=msg.cruda)
        elif isinstance(msg, MsgOrden):
            self._de_orden(msg, ahora)
        elif isinstance(msg, (MsgQuote, MsgIssueStatus, MsgLDLU, MsgShortInfo)):
            self._mercado.aplicar(msg)
        elif isinstance(msg, MsgMarcador):
            if msg.nombre in _MARCADORES_VOLCADO:
                self._fines_vistos.add(msg.nombre)
        elif isinstance(msg, MsgConexion):
            self._diario.anotar("das_conexion", conexion="watch", servidor=msg.servidor, evento=msg.evento,
                                cruda=msg.cruda)
            if msg.evento in ("Logon:Failed", "Connect:Failed"):
                self._avisar(Nivel.MAXIMO, f"EP-7: el LOGIN del vigilante (watch) falló en {msg.servidor}: "
                                           f"LOGIN/2FA a mano", "vigilante_login", ahora)
        elif isinstance(msg, MsgLogin):
            self._login(msg, "watch")

    def _login(self, msg: MsgLogin, conexion: str) -> None:
        """DAS real (01-oct): «#LOGIN SUCCESSED» / «ERROR:…». Rechazado → aviso 3 UNA vez y sin más LOGIN (watch ni acción).

        El cliente ya cerró esa sesión y no reconecta; aquí se deja de pedir
        el watch y de abrir la conexión de acción (cada una mandaría otro
        LOGIN con la misma clave). Solo el texto de DAS, nunca la clave.
        """
        motivo = str(msg.motivo)
        self._diario.anotar("das_login", conexion=conexion, ok=bool(msg.ok), motivo=motivo)
        if msg.ok:
            return
        primero = self._login_rechazado is None
        self._login_rechazado = motivo
        if primero:
            self._avisar(Nivel.MAXIMO, f"Vigilante: DAS rechazó el LOGIN: {mod_avisos.escapar_html(motivo)} (conexión "
                                       f"{conexion}). Revisar DAS_USUARIO / DAS_CLAVE / DAS_CUENTA en el .env; no se "
                                       f"reintenta. No vigila ni repone stops; los que ya estén en DAS siguen",
                         "vigilante_login_rechazado", self._reloj.mono())

    def _de_orden(self, m: MsgOrden, ahora: float) -> None:
        self._ordenes[m.id] = m
        # Lo pendiente solo se da por hecho con la CONFIRMACIÓN (cantidad nueva o estado final): una línea vieja
        # (respuesta tardía a un GET ORDERS) no puede borrarlo y provocar otro REPLACE/CANCEL (riesgo 11).
        reemplazo = self._pend_replace.get(m.id)
        if reemplazo is not None and (m.estado not in _ESTADOS_VIVOS or reemplazo[0] in (m.qty, m.lvqty)):
            del self._pend_replace[m.id]
        if m.id in self._pend_cancel and m.estado not in _ESTADOS_VIVOS:
            del self._pend_cancel[m.id]
        token = m.token
        if token is None:
            return
        self._pend_nuevas.pop(token, None)
        partes = mod_tokens.descomponer(token)
        if partes is None or partes[0] is not Origen.VIGILANTE:
            return
        firma = (m.estado, m.qty, m.lvqty, m.cxlqty)
        if self._estado_propias.get(token) != firma:
            self._estado_propias[token] = firma
            self._diario.anotar("orden_estado", ticker=m.ticker, id=m.id, token=token, estado=m.estado, qty=m.qty,
                                lvqty=m.lvqty, cxlqty=m.cxlqty, precio=m.precio, tipo_das_crudo=m.tipo, cruda=m.cruda)
        if m.estado is EstadoOrden.REJECTED:
            self._registrar_rechazo(token, str(m.ticker).strip(), ahora)

    def _de_accion(self, m: MsgOrderAct) -> None:
        """Conexión de acción: solo los `%OrderAct` de tokens del vigilante (diario + aviso de rechazo)."""
        token = m.token
        partes = mod_tokens.descomponer(token) if token is not None else None
        if partes is None or partes[0] is not Origen.VIGILANTE:
            return
        ahora = self._reloj.mono()
        self._diario.anotar("orden_act", ticker=m.ticker, id=m.id, accion=m.accion, lado=m.lado, qty=m.qty,
                            precio=m.precio, ruta=m.ruta, hora=m.hora, notas=m.notas, token=token, cruda=m.cruda)
        if m.accion not in _RECHAZOS_ACCION:
            return
        ticker = str(m.ticker).strip()
        if m.accion == "Send_Rej":
            self._registrar_rechazo(token, ticker, ahora)
            self._avisar(Nivel.MAXIMO, f"R-C-03 / R-C-08: DAS RECHAZÓ el stop del vigilante en {ticker} "
                                       f"(token {token}): «{m.notas}»", f"vigilante_rechazo:{ticker}", ahora)
        else:
            self._avisar(Nivel.AVISO, f"R-C-08: DAS rechazó un {m.accion} del vigilante en {ticker} "
                                      f"(id {m.id}): «{m.notas}»", f"vigilante_{m.accion}:{ticker}", ahora)

    def _estado_watch(self, conectado: bool, motivo: str) -> None:
        ahora = self._reloj.mono()
        self._diario.anotar("das_conexion", conexion="watch", conectado=conectado, motivo=motivo,
                            intento=self._plan.intentos)
        if conectado:
            self._posiciones.clear()                 # el volcado nuevo manda: nada viejo se mezcla con él
            self._ordenes.clear()
            self._netas_anotadas.clear()
            self._fines_vistos.clear()
            self._mercado.reiniciar_suscripciones()
            self._watch_conectado_en = time.monotonic()
            self._mensajes_watch = 0
            self._plan.reiniciar()
            if self._aviso_watch_caido:
                self._aviso_watch_caido = False
                self._avisar(Nivel.INFO, "R-J-02: el vigilante recuperó la conexión watch con DAS",
                             "vigilante_watch_vuelve", ahora)
            self._anotado_sin_watch = False
            self._volcado_pedido = False
            return
        self._watch_conectado_en = None
        self._proximo_intento_watch = time.monotonic() + self._plan.siguiente()
        if not self._aviso_watch_caido:
            self._aviso_watch_caido = True
            self._avisar(Nivel.AVISO, f"R-J-02 / R-C-08: el vigilante perdió la conexión watch con DAS ({motivo}): "
                                      f"no vigila hasta reconectar; protegen los stops residentes",
                         "vigilante_watch", ahora)

    def _intento_watch(self, conectado: bool) -> None:
        if conectado:
            return                                   # el «conectado» ya llegó por al_estado, delante del volcado
        espera = self._plan.siguiente()
        self._proximo_intento_watch = time.monotonic() + espera
        self._diario.anotar("das_conexion", conexion="watch", conectado=False, motivo="no conecta",
                            intento=self._plan.intentos, reintento_en_s=espera)
        if not self._aviso_watch_caido:
            self._aviso_watch_caido = True
            self._avisar(Nivel.AVISO, "R-J-02 / R-C-08: el vigilante no conecta con DAS (watch): no vigila hasta "
                                      "conectar; protegen los stops residentes", "vigilante_watch", self._reloj.mono())

    def _hilo_caido(self, nombre: str, error: str, relanzado: bool) -> None:
        self._diario.anotar("hilo_caido", nombre=nombre, error=error, relanzado=relanzado, regla="injerto §8.11")
        nivel = Nivel.AVISO if relanzado else Nivel.MAXIMO
        self._avisar(nivel, f"Injerto §8.11: el hilo {nombre} del vigilante cayó ({error}); "
                            f"{'relanzado' if relanzado else 'NO se relanza: el latido se retiene y el supervisor relanzará'}",
                     f"vigilante_hilo:{nombre}", self._reloj.mono())

    # ── la pasada de vigilancia ──
    def _pasada_segura(self) -> None:
        try:
            self._pasada()
        except Exception as exc:  # noqa: BLE001 — frontera (H-5): una pasada que revienta no para la vigilancia
            self._excepcion("pasada", exc)
        finally:
            self._pasadas += 1

    def _pasada(self) -> None:
        """R-C-08 / R-C-07 plan B: diarios → foto → `vigilancia.comprobar` → acciones; ping (R-J-05)."""
        ahora = self._reloj.mono()
        ahora_et = self._reloj.ahora()
        hoy = ahora_et.date()
        self._revisar_dia(hoy)
        self._leer_diarios(hoy)
        latido_ejecutor = Latido.edad(self._ruta_latido_ejecutor, self._reloj.epoch())
        dentro = self._dentro_seguro(ahora_et)
        self._revisar_ejecutor(latido_ejecutor, ahora, dentro)
        listo = self._watch_listo()
        if self._ping is not None and vigilancia.debe_hacer_ping(listo, latido_ejecutor, dentro, self._plan_b_latido_s):
            self._ping.tocar_si_toca(ahora)
        if not listo:
            if not self._anotado_sin_watch:
                self._anotado_sin_watch = True
                self._diario.anotar(_TIPO_ANOTACION_VIGILANCIA, sin_watch=True, conectado=_conectado(self._watch),
                                    latido_ejecutor_s=latido_ejecutor, regla="R-C-08: sin libro de DAS no se vigila")
            return
        self._caducar_pendientes(ahora)
        self._suscribir()
        foto = self._foto(ahora, hoy, latido_ejecutor)
        descubiertas = vigilancia.descubiertas_por_ticker(foto, self._cfg, hoy)
        self._descubierta_desde = vigilancia.actualizar_descubierta_desde(self._descubierta_desde, descubiertas, ahora)
        self._olvidar_rechazos(ahora)
        foto = dataclasses.replace(foto, descubierta_desde=dict(self._descubierta_desde))
        foto = self._sin_retenidos(foto, ahora)
        for accion in self._decidir(foto, ahora, ahora_et, hoy):
            self._ejecutar_seguro(accion, ahora)

    def _decidir(self, foto: vigilancia.Foto, ahora: float, ahora_et: datetime, hoy: date) -> list[Accion]:
        """Corrección 16: pasada en seco (¿hace falta enviar?) → conexión de acción solo si hace falta → pasada real."""
        ruta_stop = precios.ruta(self._cfg.rutas, "stop", Decimal("1"), ahora_et)
        previsto = self._token_previsto(hoy)
        # E2c-04: `comprobar_con_firmas` + `Foto.anotado`: la misma propuesta no se anota en cada pasada (1 s)
        seco, firmas = vigilancia.comprobar_con_firmas(foto, self._cfg, ahora, previsto, ahora_et, ruta_stop, True)
        if not any(isinstance(a, vigilancia.MUTANTES) for a in seco):
            self._firmas_vigilancia = dict(firmas)
            return seco                              # sin nada que mandar la pasada real sería idéntica
        tokens = self._tokens
        if tokens is None:
            raise RuntimeError("el vigilante no arrancó: sin generador de tokens")
        if self._sombra:
            acciones, firmas = vigilancia.comprobar_con_firmas(foto, self._cfg, ahora, tokens.siguiente, ahora_et,
                                                               ruta_stop, True)
        else:
            puede = self._asegurar_accion()
            acciones, firmas = vigilancia.comprobar_con_firmas(foto, self._cfg, ahora,
                                                               tokens.siguiente if puede else previsto, ahora_et,
                                                               ruta_stop, puede)
        self._firmas_vigilancia = dict(firmas)
        return acciones

    def _token_previsto(self, hoy: date) -> Callable[[], int]:
        """El token que saldría ahora SIN consumirlo (pasada en seco o bloqueada): la secuencia no se gasta."""
        seq = (self._tokens.ultimo_seq if self._tokens is not None else self._ultimo_seq_vigilante) + 1
        token = mod_tokens.componer(Origen.VIGILANTE, hoy.timetuple().tm_yday, min(max(seq, 1), mod_tokens.MAX_SEQ))
        return lambda: token

    def _foto(self, ahora: float, hoy: date, latido_ejecutor: Optional[float]) -> vigilancia.Foto:
        """§3.25: libro de DAS + lotes/estados/locates de los diarios + latido + cotizaciones + equity + pendientes."""
        estado = self._estado_de_diarios(hoy)
        posiciones = dict(self._posiciones)
        lotes = {t: list(p.lotes.values()) for t, p in estado.posiciones.items() if p.lotes}
        cotizaciones = {}
        limit_up: dict[str, Decimal] = {}
        for ticker in posiciones:
            cot = self._mercado.cotizacion(ticker)
            if cot is not None:
                cotizaciones[ticker] = cot
            banda = self._mercado.simbolo(ticker).limit_up
            if banda is not None:
                limit_up[ticker] = banda
        estados = {t: p.estado for t, p in estado.posiciones.items() if p.estado is not EstadoTicker.NORMAL}
        return vigilancia.Foto(
            posiciones=posiciones, ordenes=self._ordenes_vista(ahora), lotes=lotes,
            latido_ejecutor_s=latido_ejecutor, cotizaciones=cotizaciones, gasto_locates=estado.gasto_locates_dia,
            compras_locate=[r for r in self._registros if r.tipo in _TIPOS_LOCATE],
            equity=self._equity_ejecutor(ahora), descubierta_desde=dict(self._descubierta_desde), limit_up=limit_up,
            pendientes=[orden for orden, _ in self._pend_nuevas.values()], estados_ticker=estados,
            locates_deshabilitados=estado.locates_deshabilitados, anotado=dict(self._firmas_vigilancia))

    def _ordenes_vista(self, ahora: float) -> dict[int, MsgOrden]:
        """El libro con lo pendiente aplicado: un CANCEL enviado cuenta como hecho y un REPLACE con su cantidad nueva."""
        vista = dict(self._ordenes)
        for id_das in list(self._pend_cancel):
            m = vista.get(id_das)
            if m is not None and m.estado in _ESTADOS_VIVOS:
                vista[id_das] = dataclasses.replace(m, estado=EstadoOrden.CANCELED)
        for id_das, (qty, _) in list(self._pend_replace.items()):
            m = vista.get(id_das)
            if m is not None and m.estado in (EstadoOrden.SENDING, EstadoOrden.ACCEPTED, EstadoOrden.HOLD):
                vista[id_das] = dataclasses.replace(m, qty=qty, lvqty=qty)
        return vista

    def _caducar_pendientes(self, ahora: float) -> None:
        """Riesgo 11: lo que DAS no devolvió a tiempo deja de contar (la pasada siguiente lo repone o lo repite)."""
        for token, (orden, caduca) in list(self._pend_nuevas.items()):
            if ahora >= caduca:
                del self._pend_nuevas[token]
                self._diario.anotar("pendiente_caducado", ticker=orden.ticker, token=token, que="orden",
                                    proposito=orden.proposito, regla="riesgo 11")
        for id_das, caduca in list(self._pend_cancel.items()):
            if ahora >= caduca:
                del self._pend_cancel[id_das]
        for id_das, (_, caduca) in list(self._pend_replace.items()):
            if ahora >= caduca:
                del self._pend_replace[id_das]

    def _sin_retenidos(self, foto: vigilancia.Foto, ahora: float) -> vigilancia.Foto:
        """R-C-03 / riesgo 11: un ticker con stops rechazados espera la separación y, tras `reintentos`, queda a mano."""
        retenidos: dict[str, str] = {}
        for ticker, marcas in self._rechazos.items():
            if not marcas or ticker not in foto.posiciones:
                continue
            if len(marcas) >= self._reintentos:
                retenidos[ticker] = "agotados"
                self._avisar(Nivel.MAXIMO, f"R-C-03: DAS rechazó {len(marcas)} veces los stops del vigilante en "
                                           f"{ticker}: CONTROL HUMANO, poner la protección A MANO",
                             f"vigilante_control_humano:{ticker}", ahora)
            elif ahora - marcas[-1] < self._separacion_s:
                retenidos[ticker] = "separacion"
        if not retenidos:
            return foto
        for ticker, motivo in retenidos.items():
            self._anotar_deduplicado(ticker + ":retenido", "vigilancia_retenida", {
                "ticker": ticker, "motivo": motivo, "rechazos": len(self._rechazos[ticker]),
                "regla": "R-C-03 / riesgo 11"}, ahora, siempre=False)
        return dataclasses.replace(foto, posiciones={t: m for t, m in foto.posiciones.items() if t not in retenidos})

    def _olvidar_rechazos(self, ahora: float) -> None:
        """R-C-03 (3): los rechazos cuentan en una ventana de `stops.ventana_min` minutos; sin posición, se olvidan."""
        for ticker in list(self._rechazos):
            pos = self._posiciones.get(ticker)
            vigentes = [t for t in self._rechazos[ticker] if ahora - t < self._ventana_rechazos_s]
            if pos is None or pos.neta == 0 or not vigentes:
                del self._rechazos[ticker]
            else:
                self._rechazos[ticker] = vigentes

    def _registrar_rechazo(self, token: int, ticker: str, ahora: float) -> None:
        if token in self._tokens_rechazados or not ticker:
            return
        self._tokens_rechazados.add(token)
        self._pend_nuevas.pop(token, None)
        self._rechazos.setdefault(ticker, []).append(ahora)

    # ── ejecutar lo que decide `comprobar` ──
    def _ejecutar_seguro(self, a: Accion, ahora: float) -> None:
        try:
            self._ejecutar(a, ahora)
        except Exception as exc:  # noqa: BLE001 — frontera (H-5): una acción que revienta no impide las siguientes
            self._excepcion(f"ejecutar:{type(a).__name__}", exc)

    def _ejecutar(self, a: Accion, ahora: float) -> None:
        if isinstance(a, Anotar):
            self._anotar(a, ahora)
        elif isinstance(a, Avisar):
            self._avisar(a.nivel, a.texto, a.clave, ahora, a.grupo)
        elif isinstance(a, EnviarOrden):
            self._enviar_orden(a, ahora)
        elif isinstance(a, Cancelar):
            self._cancelar(a, ahora)
        elif isinstance(a, CancelarTicker):
            self._cancelar_ticker(a)
        elif isinstance(a, Reemplazar):
            self._reemplazar(a, ahora)
        elif isinstance(a, PedirAlSupervisor):
            self._pedir_al_supervisor(a, ahora)
        else:
            # Programar/Consultar/InvalidarSerie son del ejecutor; `comprobar` ya los quita (defensa)
            self._diario.anotar("accion_ignorada", accion=type(a).__name__, regla="§3.25")

    def _anotar(self, a: Anotar, ahora: float) -> None:
        datos = a.datos if isinstance(a.datos, dict) else {"datos": a.datos}
        if a.tipo != _TIPO_ANOTACION_VIGILANCIA:
            self._diario.anotar(str(a.tipo), **{str(k): v for k, v in datos.items()})
            return
        actua = bool(datos.get("acciones")) and not datos.get("bloqueado")
        self._anotar_deduplicado(f"{datos.get('ticker')}:vigilancia", _TIPO_ANOTACION_VIGILANCIA, datos, ahora,
                                 siempre=actua)

    def _anotar_deduplicado(self, clave: str, tipo: str, datos: dict, ahora: float, siempre: bool) -> None:
        """Diario sin ruido: lo mismo (sin contar latidos ni tokens) no se repite antes de `ANOTAR_REPETIR_S`."""
        firma = json.dumps({k: v for k, v in datos.items() if k not in ("latido_ejecutor_s", "acciones")},
                           sort_keys=True, default=str, ensure_ascii=False)
        anterior = self._anotado.get(clave)
        if not siempre and anterior is not None and anterior[0] == firma and ahora - anterior[1] < ANOTAR_REPETIR_S:
            return
        self._anotado[clave] = (firma, ahora)
        self._diario.anotar(tipo, **{str(k): v for k, v in datos.items()})

    def _avisar(self, nivel: Any, texto: str, clave: Optional[str], ahora: float, grupo: Any = Grupo.B) -> None:
        """R-M-01 / R-O-03: aviso con la fase delante, a la cola de avisos y al diario; misma clave → uno por ventana."""
        if clave is not None:
            anterior = self._avisado_en.get(clave)
            if anterior is not None and ahora - anterior < AVISO_REPETIR_S:
                return
            self._avisado_en[clave] = ahora
        texto = mod_avisos.con_prefijo_fase(str(texto), self._cfg.fase)
        try:
            n = Nivel(nivel)
            g = Grupo(grupo)
        except ValueError:
            n, g = Nivel.AVISO, Grupo.B
        self._poner_aviso(n, texto, clave, g)
        self._diario.anotar("aviso", nivel=int(n), grupo=g.value, clave=clave, texto=texto)

    def _poner_aviso(self, nivel: Nivel, texto: str, clave: Optional[str], grupo: Grupo = Grupo.B) -> None:
        try:
            self._avisos.poner(mod_avisos.aviso_de(Avisar(nivel, grupo, texto, clave), self._reloj.mono()))
        except (TypeError, ValueError) as exc:  # frontera de mensaje: un aviso mal formado no tumba el bucle
            logger.error("[VIGILANTE] aviso no encolado (%s): %s", type(exc).__name__, texto)

    def _enviar_orden(self, a: EnviarOrden, ahora: float) -> None:
        """M6: `orden_intencion` (fsync) ANTES del NEWORDER y `orden_enviada` después; un stop sale aunque el diario falle."""
        o = a.orden
        try:
            linea = protocolo.cmd_neworder(o)
        except (TypeError, ValueError) as exc:  # frontera de mensaje (riesgo 12): una orden imposible no sale
            self._accion_invalida("EnviarOrden", exc, ahora, token=o.token, ticker=o.ticker)
            return
        datos = self._datos_orden(o, a.serie, linea)
        if self._sombra:
            self._diario.anotar("vigilancia_simulada", sombra=True, **datos)
            self._pend_nuevas[o.token] = (_orden_de(o, ahora), ahora + PENDIENTE_CADUCA_SOMBRA_S)
            return
        self._diario.anotar("orden_intencion", **datos)
        if not self._mandar(linea, a.serie, o.version, "EnviarOrden", ahora, token=o.token, ticker=o.ticker):
            return
        self._pend_nuevas[o.token] = (_orden_de(o, ahora), ahora + PENDIENTE_CADUCA_S)
        self._enviadas += 1
        self._diario.anotar("orden_enviada", ticker=o.ticker, token=o.token, proposito=o.proposito, serie=a.serie,
                            version=o.version, linea=linea, regla="M6")

    def _cancelar(self, a: Cancelar, ahora: float) -> None:
        try:
            linea = protocolo.cmd_cancel(a.id_das)
        except (TypeError, ValueError) as exc:  # frontera de mensaje
            self._accion_invalida("Cancelar", exc, ahora, token=a.token, id_das=a.id_das)
            return
        m = self._ordenes.get(a.id_das)
        ticker = m.ticker if m is not None else None
        if self._sombra:
            self._diario.anotar("vigilancia_simulada", sombra=True, ticker=ticker, que="cancel", id_das=a.id_das,
                                token=a.token, motivo=a.motivo, linea=linea, regla="R-O-03")
            self._pend_cancel[a.id_das] = ahora + PENDIENTE_CADUCA_SOMBRA_S
            return
        self._diario.anotar("cancel_intencion", ticker=ticker, id_das=a.id_das, token=a.token, motivo=a.motivo,
                            linea=linea, regla="M6")
        if self._mandar(linea, None, 0, "Cancelar", ahora, token=a.token, id_das=a.id_das):
            self._pend_cancel[a.id_das] = ahora + PENDIENTE_CADUCA_S
            self._enviadas += 1

    def _cancelar_ticker(self, a: CancelarTicker) -> None:
        ahora = self._reloj.mono()
        try:
            linea = protocolo.cmd_cancel_allsymb(a.ticker)
        except (TypeError, ValueError) as exc:  # frontera de mensaje
            self._accion_invalida("CancelarTicker", exc, ahora, ticker=a.ticker)
            return
        if self._sombra:
            self._diario.anotar("vigilancia_simulada", sombra=True, ticker=a.ticker, que="cancel_todas",
                                motivo=a.motivo, linea=linea, regla="R-O-03")
            return
        self._diario.anotar("cancel_intencion", ticker=a.ticker, todas=True, motivo=a.motivo, linea=linea, regla="M6")
        if self._mandar(linea, None, 0, "CancelarTicker", ahora, ticker=a.ticker):
            self._enviadas += 1

    def _reemplazar(self, a: Reemplazar, ahora: float) -> None:
        tipo = (TipoOrden.STOP_LIMITE_PP if a.stop is not None
                else TipoOrden.LIMITE if a.precio is not None else TipoOrden.MERCADO)
        try:
            linea = protocolo.cmd_replace(a.id_das, a.qty, tipo, a.precio, a.stop)
        except (TypeError, ValueError) as exc:  # frontera de mensaje (riesgo 12: precio fuera de tick)
            self._accion_invalida("Reemplazar", exc, ahora, token=a.token, id_das=a.id_das)
            return
        m = self._ordenes.get(a.id_das)
        ticker = m.ticker if m is not None else None
        if self._sombra:
            self._diario.anotar("vigilancia_simulada", sombra=True, ticker=ticker, que="replace", id_das=a.id_das,
                                token=a.token, qty=a.qty, stop=a.stop, precio=a.precio, motivo=a.motivo, linea=linea,
                                regla="R-O-03")
            self._pend_replace[a.id_das] = (a.qty, ahora + PENDIENTE_CADUCA_SOMBRA_S)
            return
        self._diario.anotar("replace_intencion", ticker=ticker, id_das=a.id_das, token=a.token, qty=a.qty, stop=a.stop,
                            precio=a.precio, version=a.version, serie=a.serie, motivo=a.motivo, linea=linea,
                            regla="M6")
        if self._mandar(linea, a.serie, a.version, "Reemplazar", ahora, token=a.token, id_das=a.id_das):
            self._pend_replace[a.id_das] = (a.qty, ahora + PENDIENTE_CADUCA_S)
            self._enviadas += 1

    def _mandar(self, linea: str, serie: Optional[str], version: int, que: str, ahora: float, **datos: Any) -> bool:
        """Una línea por la conexión de acción (corrección 16). False si no salió (se anota; la pasada siguiente repite)."""
        with self._cerrojo_accion:
            cliente = self._accion
        if cliente is None or not _conectado(cliente):
            self._diario.anotar("envio_fallido", accion=que, motivo="sin conexión de acción", linea=linea,
                                regla="corrección 16", **datos)
            self._soltar_accion("sin conexión al enviar")
            return False
        try:
            encolada = cliente.enviar(linea, serie, version)
        except Exception as exc:  # noqa: BLE001 — frontera de red/mensaje: EnvioProhibido (bug), línea inválida o socket
            self._diario.anotar("envio_fallido", accion=que, error=f"{type(exc).__name__}: {exc}", linea=linea,
                                regla="corrección 16", **datos)
            self._avisar(Nivel.MAXIMO, f"R-C-08: el vigilante NO pudo enviar {que} ({type(exc).__name__}); "
                                       f"se reintenta con otra conexión", f"vigilante_envio:{que}", ahora)
            self._soltar_accion("fallo al enviar")
            return False
        if encolada is False:
            # G2-05: el cliente la descartó en el acto (conexión caída o cola llena): no se anota como enviada y la
            # pasada siguiente la repite (no queda como pendiente que tape la falta)
            self._diario.anotar("envio_fallido", accion=que, motivo="el cliente no la encoló", linea=linea,
                                regla="G2-05", **datos)
            self._soltar_accion("el cliente descartó la línea")
            return False
        with self._cerrojo_accion:
            self._accion_usada_en = time.monotonic()
        return True

    def _pedir_al_supervisor(self, a: PedirAlSupervisor, ahora: float) -> None:
        """Corrección 16 / riesgo 31: una línea en `estado/orden_supervisor.jsonl` (como mucho cada `PETICION_REPETIR_S`).

        Mismo formato que el ejecutor: `{"t","proceso","pid","peticion"}` y,
        si es «relanzar X», `"relanzar": "X"` (lo que lee el supervisor).
        Nunca escribe `{"parar": …}`.
        """
        peticion = str(a.peticion)
        anterior = self._peticion_en.get(peticion)
        if anterior is not None and ahora - anterior < PETICION_REPETIR_S:
            return
        cuerpo: dict[str, Any] = {"t": self._reloj.ahora().isoformat(), "proceso": "vigilante", "pid": os.getpid(),
                                  "peticion": peticion}
        palabras = peticion.split()
        if len(palabras) == 2 and palabras[0].lower() == "relanzar":
            cuerpo["relanzar"] = palabras[1]
        try:
            self._ruta_orden_supervisor.parent.mkdir(parents=True, exist_ok=True)
            with open(self._ruta_orden_supervisor, "a", encoding="utf-8", newline="\n") as fichero:
                fichero.write(json.dumps(cuerpo, ensure_ascii=False) + "\n")
                fichero.flush()
        except OSError as exc:  # frontera de fichero: el último recurso falló; aviso 3 (corrección 16)
            self._diario.anotar("peticion_supervisor_fallo", peticion=peticion, error=f"{type(exc).__name__}: {exc}")
            self._avisar(Nivel.MAXIMO, f"Corrección 16: el vigilante no pudo pedir al supervisor «{peticion}»: "
                                       f"CONTROL HUMANO", "peticion_supervisor_vigilante", ahora)
            return
        self._peticion_en[peticion] = ahora
        self._diario.anotar("peticion_supervisor", peticion=peticion, regla="corrección 16")

    def _accion_invalida(self, que: str, exc: BaseException, ahora: float, **datos: Any) -> None:
        self._diario.anotar("accion_invalida", accion=que, error=f"{type(exc).__name__}: {exc}", **datos)
        self._avisar(Nivel.AVISO, f"El vigilante descartó una acción imposible ({que}: {type(exc).__name__})",
                     f"vigilante_accion_invalida:{que}", ahora)

    def _datos_orden(self, o: OrdenNueva, serie: Optional[str], linea: str) -> dict:
        partes = mod_tokens.descomponer(o.token)
        cot = self._mercado.cotizacion(o.ticker)
        return {
            "token": o.token, "ticker": o.ticker, "lado": o.lado.value, "tipo_orden": o.tipo.value, "qty": o.qty,
            "precio": o.precio, "stop": o.stop, "ruta": o.ruta, "post_only": o.post_only, "tif": o.tif, "pref": o.pref,
            "proposito": o.proposito.value, "lote_id": o.lote_id, "nivel": o.nivel, "version": o.version,
            "origen": int(partes[0]) if partes is not None else None, "serie": serie,
            "bid": cot.bid if cot is not None else None, "ask": cot.ask if cot is not None else None,
            "last": cot.last if cot is not None else None, "linea": linea, "regla": "R-C-07 plan B / M6",
        }

    # ── conexión de acción (corrección 16, riesgo 31) ──
    def _asegurar_accion(self) -> bool:
        """True si hay una conexión normal con permiso de envío; si no, la abre en un hilo y la espera ≤ 1 s.

        Con el LOGIN rechazado (01-oct) no se abre: sería otro LOGIN con la misma clave mala.
        """
        with self._cerrojo_accion:
            cliente = self._accion
        if self._login_rechazado is not None and (cliente is None or not _conectado(cliente)):
            return False
        if cliente is not None:
            if _conectado(cliente):
                with self._cerrojo_accion:
                    self._accion_usada_en = time.monotonic()
                return True
            self._soltar_accion("la conexión de acción se cayó")
        hilo = self._hilo_accion
        if hilo is None or not hilo.is_alive():
            with self._cerrojo_accion:
                fallo = self._accion_fallo_en
            if fallo is not None and time.monotonic() - fallo < REABRIR_ACCION_S:
                return False
            hilo = threading.Thread(target=self._cuerpo_abrir_accion, name="vigilante-accion", daemon=True)
            self._hilo_accion = hilo
            hilo.start()
        hilo.join(ESPERA_ABRIR_ACCION_S)
        with self._cerrojo_accion:
            cliente = self._accion
        return cliente is not None and _conectado(cliente)

    def _cuerpo_abrir_accion(self) -> None:
        """Hilo de un solo uso: `abrir_accion()` (+ `conectar()` si hace falta). Nunca lanza."""
        cliente: Any = None
        try:
            cliente = self._abrir_accion()
            if cliente is not None and not _conectado(cliente):
                if not cliente.conectar():
                    _cerrar_sin_lanzar(cliente)
                    cliente = None
        except Exception as exc:  # noqa: BLE001 — frontera de red (corrección 16): sin conexión de acción → puede_enviar=False
            logger.warning("[VIGILANTE] no se pudo abrir la conexión de acción: %s", type(exc).__name__)
            _cerrar_sin_lanzar(cliente)
            cliente = None
        with self._cerrojo_accion:
            if self._parado:
                _cerrar_sin_lanzar(cliente)
                return
            if cliente is None:
                self._accion_fallo_en = time.monotonic()
                return
            self._accion = cliente
            self._accion_fallo_en = None
            self._accion_usada_en = time.monotonic()
            self._accion_aperturas += 1

    def _soltar_accion(self, motivo: str) -> None:
        with self._cerrojo_accion:
            cliente, self._accion = self._accion, None
        if cliente is None:
            return
        logger.info("[VIGILANTE] cierro la conexión de acción: %s", motivo)
        _cerrar_sin_lanzar(cliente)

    def _cerrar_accion_si_inactiva(self) -> None:
        with self._cerrojo_accion:
            usada = self._accion_usada_en
            abierta = self._accion is not None
        if abierta and usada is not None and time.monotonic() - usada >= CERRAR_ACCION_INACTIVA_S:
            self._soltar_accion("sin nada que enviar (bajo demanda)")

    # ── watch: reconexión, volcado y suscripciones ──
    def _revisar_watch(self) -> None:
        """R-J-02: sin conexión watch, un intento en un hilo de un solo uso cuando lo diga el plan (2/4/8/16/30 s).

        Con conexión y sin volcado del LOGIN pasado `PEDIR_VOLCADO_S`, se piden
        `GET POSITIONS` y `GET ORDERS` (una vez por conexión): no se sabe si el
        watch real manda volcado (paso 7 de comprobar_das), y pedirlo SIEMPRE
        traería una copia vieja del libro detrás de las primeras acciones.
        """
        if self._codigo is not None or self._parado:
            return
        if _conectado(self._watch):
            if (not self._volcado_pedido and self._watch_conectado_en is not None
                    and not _MARCADORES_VOLCADO <= self._fines_vistos
                    and time.monotonic() - self._watch_conectado_en >= PEDIR_VOLCADO_S):
                self._volcado_pedido = True
                self._diario.anotar("volcado_pedido", motivo="el watch no mandó volcado tras el LOGIN",
                                    regla="R-C-08")
                for comando in (protocolo.cmd_get("POSITIONS"), protocolo.cmd_get("ORDERS")):
                    self._enviar_watch(comando)
            return
        hilo = self._hilo_watch
        if hilo is not None and hilo.is_alive():
            return
        rechazado = self._login_rechazado or _login_rechazado(self._watch)
        if rechazado is not None:
            if not self._anotado_login_parado:       # una clave mala en bucle bloquearía el usuario en DAS
                self._anotado_login_parado = True
                self._diario.anotar("das_reconectar_parado", conexion="watch",
                                    motivo=f"DAS rechazó el LOGIN: {rechazado}",
                                    nota="no se reintenta: corregir el .env y reiniciar el vigilante", regla="R-J-02")
            return
        if time.monotonic() < self._proximo_intento_watch:
            return
        self._proximo_intento_watch = math.inf       # hasta que el hilo diga cómo fue
        hilo = threading.Thread(target=self._cuerpo_conectar_watch, name="vigilante-conexion", daemon=True)
        self._hilo_watch = hilo
        hilo.start()

    def _cuerpo_conectar_watch(self) -> None:
        try:
            ok = bool(self._watch.conectar())
        except Exception as exc:  # noqa: BLE001 — frontera de red (R-J-02): un intento que revienta es un intento fallido
            logger.warning("[VIGILANTE] el intento de conexión watch falló: %s", type(exc).__name__)
            ok = False
        self._cola.al_intento_watch(ok)

    def _watch_listo(self) -> bool:
        """Watch conectado, con algo recibido y con el volcado completo (o pasado `VOLCADO_ESPERA_S`)."""
        if self._watch_conectado_en is None or not _conectado(self._watch) or self._mensajes_watch == 0:
            return False
        if _MARCADORES_VOLCADO <= self._fines_vistos:
            return True
        return time.monotonic() - self._watch_conectado_en >= VOLCADO_ESPERA_S

    def _enviar_watch(self, linea: str) -> None:
        """Una lectura (GET/SB/UNSB) por el watch; el cliente es de solo lectura: un mutante ni se intenta."""
        if protocolo.es_mutante(linea) or not _conectado(self._watch):
            return
        try:
            self._watch.enviar(linea)
        except Exception as exc:  # noqa: BLE001 — frontera de red/mensaje: una lectura que no sale se repite al reconectar
            logger.warning("[VIGILANTE] no salió por watch (%s): %s", type(exc).__name__, protocolo.redactar(linea))

    def _suscribir(self) -> None:
        """R-C-08 (a): cotizaciones de DAS de los tickers con posición (Lv1) y su banda (GET LDLU, R-F-02)."""
        if not _conectado(self._watch):
            return
        tickers = [t for t, m in self._posiciones.items() if m.neta != 0]
        altas, bajas = self._mercado.suscripciones(tickers)
        for ticker in altas:
            try:
                self._enviar_watch(protocolo.cmd_sb(ticker))
                self._enviar_watch(protocolo.cmd_get("LDLU", ticker))
            except ValueError:
                logger.warning("[VIGILANTE] ticker imposible para suscribir: %r", ticker)
        for ticker in bajas:
            try:
                self._enviar_watch(protocolo.cmd_unsb(ticker))
            except ValueError:
                logger.warning("[VIGILANTE] ticker imposible para desuscribir: %r", ticker)

    # ── diarios ──
    def _leer_diarios(self, hoy: date) -> None:
        """Riesgo 22: lo nuevo de los dos diarios; se guardan los registros que importan y el último seq de token propio."""
        for proceso in _PROCESOS_DIARIO:
            nuevos = self._seguidores[proceso].leer(hoy)
            if not nuevos:
                continue
            self._ultimo_seq_vigilante = max(self._ultimo_seq_vigilante,
                                             ultimo_seq_por_origen(nuevos, hoy)[Origen.VIGILANTE])
            relevantes = [r for r in nuevos if r.tipo in TIPOS_RELEVANTES]
            if relevantes:
                self._registros.extend(relevantes)
                self._estado_sucio = True

    def _estado_de_diarios(self, hoy: date) -> EstadoBot:
        if self._estado_sucio or self._estado_diario is None or self._estado_diario.dia != hoy:
            self._estado_diario = reconstruir(self._registros, hoy)
            self._estado_sucio = False
        return self._estado_diario

    def _revisar_dia(self, hoy: date) -> None:
        """§8: el diario es por día; al cambiar la fecha ET, diario nuevo, tokens del día nuevo y lo de ayer fuera."""
        if self._dia is None or self._dia == hoy:
            return
        antes = self._dia
        self._dia = hoy
        self._diario.abrir_dia(hoy, motor_hash=self._cfg.motor_hash, config_version=self._cfg.config_version,
                               estrategias_hash=self._cfg.estrategias_hash)
        self._diario.anotar("dia_nuevo_diario", antes=antes, hoy=hoy)
        self._registros = []
        self._estado_diario = None
        self._estado_sucio = True
        self._ultimo_seq_vigilante = 0
        self._leer_diarios(hoy)
        # H-2: la secuencia del día nuevo sigue a lo que ya haya en sus diarios (normalmente nada: 0)
        self._tokens = GeneradorTokens(Origen.VIGILANTE, hoy, min(self._ultimo_seq_vigilante, mod_tokens.MAX_SEQ))
        self._pend_nuevas.clear()
        self._pend_cancel.clear()
        self._pend_replace.clear()
        self._rechazos.clear()
        self._tokens_rechazados.clear()
        self._descubierta_desde.clear()
        self._firmas_vigilancia.clear()

    # ── ejecutor, ventana, equity, supervisor, latido ──
    def _revisar_ejecutor(self, latido_ejecutor: Optional[float], ahora: float, dentro: bool) -> None:
        """R-C-08 (c): «el ejecutor no late» se anota al empezar y se avisa (2) si dura > `EJECUTOR_CALLADO_AVISO_S`."""
        callado = latido_ejecutor is None or latido_ejecutor > self._plan_b_latido_s
        if not callado:
            if self._ejecutor_callado_desde is not None:
                self._diario.anotar("ejecutor_late", latido_ejecutor_s=latido_ejecutor,
                                    callado_s=ahora - self._ejecutor_callado_desde, regla="R-C-08 (c)")
            self._ejecutor_callado_desde = None
            self._aviso_ejecutor_dado = False
            return
        if self._ejecutor_callado_desde is None:
            self._ejecutor_callado_desde = ahora
            self._diario.anotar("ejecutor_callado", latido_ejecutor_s=latido_ejecutor, regla="R-C-08 (c)")
            return
        if dentro and not self._aviso_ejecutor_dado and ahora - self._ejecutor_callado_desde >= EJECUTOR_CALLADO_AVISO_S:
            self._aviso_ejecutor_dado = True
            edad = "sin latido" if latido_ejecutor is None else f"latido de hace {latido_ejecutor:.0f} s"
            self._avisar(Nivel.AVISO, f"R-C-08 (c): el ejecutor no late ({edad}): el vigilante lleva el plan B de los "
                                      f"stops; el supervisor debería relanzarlo", "vigilante_ejecutor_callado", ahora)

    def _dentro_seguro(self, ahora_et: datetime) -> bool:
        try:
            return bool(self._dentro_de_ventana(ahora_et))
        except Exception as exc:  # noqa: BLE001 — frontera de callback: sin saber la ventana se da por dentro (se pinga)
            logger.warning("[VIGILANTE] dentro_de_ventana falló: %s", type(exc).__name__)
            return True

    def _equity_ejecutor(self, ahora: float) -> Optional[Decimal]:
        """2c / R-H-03: el equity que el ejecutor publicó en `estado/foto.json` (el watch no puede pedir AccountInfo)."""
        if self._equity_leida_en is not None and ahora - self._equity_leida_en < FOTO_EJECUTOR_CADA_S:
            return self._equity
        self._equity_leida_en = ahora
        try:
            foto = json.loads(self._ruta_foto_ejecutor.read_text(encoding="utf-8"))
        except (OSError, ValueError):  # frontera de fichero: sin foto no hay equity (vigilancia no evalúa el 3 % ni 2c)
            self._equity = None
            return None
        cuenta = foto.get("cuenta") if isinstance(foto, dict) else None
        valor = cuenta.get("equity") if isinstance(cuenta, dict) else None
        self._equity = _decimal_positivo(valor)
        return self._equity

    def _revisar_orden_supervisor(self) -> None:
        """§6.2.5: `{"parar": true}` (para None, «vigilante» o «todos») escrito tras arrancar → parada ordenada."""
        ruta = self._ruta_orden_supervisor
        tamano = _tamano_fichero(ruta)
        if tamano < self._orden_offset:
            self._orden_offset = 0
        if tamano == self._orden_offset:
            return
        try:
            with open(ruta, "rb") as fichero:
                fichero.seek(self._orden_offset)
                bloque = fichero.read(tamano - self._orden_offset)
        except OSError:  # frontera de fichero: se vuelve a mirar en la vuelta siguiente
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
            if para not in (None, "vigilante", "todos"):
                continue
            if self._diario_abierto:
                self._diario.anotar("orden_supervisor", peticion={k: str(v) for k, v in peticion.items()},
                                    regla="R-L-01")
            self.pedir_parada("parada pedida por el supervisor (R-L-01)", CODIGO_OK)
            return

    def _tocar_latido(self) -> None:
        """R-J-04 b + injerto §8.11: late solo si el lector del watch y el hilo de avisos viven."""
        hilos = {"watch": _atributo_bool(self._watch, "hilos_vivos", True),
                 "avisos": _atributo_bool(self._avisos, "vivo", True)}
        vivo = all(hilos.values())
        if not vivo and hilos != self._latido_retenido:
            self._latido_retenido = hilos
            if self._diario_abierto:
                self._diario.anotar("latido_retenido", hilos=hilos, regla="injerto §8.11")
        elif vivo:
            self._latido_retenido = None
        self._latido.tocar(vivo)

    def _drenar_avisos_de_borde(self) -> None:
        for nivel, texto, clave in self._cola.avisos_pendientes():
            self._seguro("aviso de borde", lambda n=nivel, t=texto, c=clave: self._avisar(n, t, c, self._reloj.mono()))

    def _excepcion(self, donde: str, exc: BaseException) -> None:
        self._excepciones += 1
        traza = traceback.format_exc()
        logger.error("[VIGILANTE] excepción en %s: %s: %s", donde, type(exc).__name__, exc)
        if self._diario_abierto:
            self._diario.anotar("excepcion", donde=donde, error=f"{type(exc).__name__}: {exc}", traceback=traza,
                                regla="H-5")
        self._seguro("aviso de excepción", lambda: self._avisar(
            Nivel.AVISO, f"H-5: excepción en el vigilante ({donde}: {type(exc).__name__}); sigue vigilando",
            f"excepcion_vigilante:{donde}", self._reloj.mono()))

    @staticmethod
    def _unir(hilo: Optional[threading.Thread]) -> None:
        if hilo is not None and hilo is not threading.current_thread():
            hilo.join(ESPERA_HILOS_S)

    @staticmethod
    def _seguro(que: str, fn: Callable[[], Any]) -> None:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 — frontera de apagado/aviso: un componente que falla no impide el resto
            logger.warning("[VIGILANTE] %s falló: %s: %s", que, type(exc).__name__, exc)


# ══════════════════════════════════════════════════════════════════════
# Ayudas del módulo
# ══════════════════════════════════════════════════════════════════════
def _orden_de(o: OrdenNueva, ahora: float) -> Orden:
    """La `Orden` (SENDING) que el vigilante acaba de mandar, para `Foto.pendientes` (riesgo 11)."""
    partes = mod_tokens.descomponer(o.token)
    return Orden(token=o.token, ticker=o.ticker, lado=o.lado, tipo=o.tipo, qty=o.qty, precio=o.precio, stop=o.stop,
                 ruta=o.ruta, proposito=o.proposito, lote_id=o.lote_id, nivel=o.nivel,
                 origen=partes[0] if partes is not None else Origen.VIGILANTE, estado=EstadoOrden.SENDING,
                 enviada_en=ahora, ultima_act=ahora, version=o.version)


def _conectado(objeto: Any) -> bool:
    return _atributo_bool(objeto, "conectado", False)


def _login_rechazado(objeto: Any) -> Optional[str]:
    """`ClienteDAS.login_rechazado` (motivo de DAS) o None; un cliente sin el atributo o que lanza cuenta como «no»."""
    try:
        motivo = getattr(objeto, "login_rechazado", None)
    except Exception:  # noqa: BLE001 — frontera: una propiedad que lanza no para la reconexión
        return None
    return motivo if isinstance(motivo, str) else None


def _atributo_bool(objeto: Any, nombre: str, defecto: bool) -> bool:
    try:
        return bool(getattr(objeto, nombre, defecto))
    except Exception:  # noqa: BLE001 — frontera: una propiedad que lanza cuenta como «no»
        return False


def _cerrar_sin_lanzar(cliente: Any) -> None:
    if cliente is None:
        return
    try:
        cliente.cerrar()
    except Exception as exc:  # noqa: BLE001 — frontera de red: cerrar es cortesía; nunca tumba al vigilante
        logger.info("[VIGILANTE] cerrar la conexión falló: %s", type(exc).__name__)


def _url_http_valida(url: str) -> bool:
    if not url:
        return False
    try:
        partes = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    return partes.scheme in ("http", "https") and bool(partes.netloc)


def _bloque(dic: Any, nombre: str) -> dict:
    valor = dic.get(nombre) if isinstance(dic, dict) else None
    return valor if isinstance(valor, dict) else {}


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


def _decimal_positivo(valor: Any) -> Optional[Decimal]:
    if valor is None or isinstance(valor, bool):
        return None
    try:
        numero = Decimal(str(valor).strip())
    except (InvalidOperation, ValueError):
        return None
    return numero if numero.is_finite() and numero > 0 else None


def _tamano_fichero(ruta: Path) -> int:
    try:
        return os.stat(ruta).st_size
    except OSError:
        return 0


def _plan_de(cfg: Config) -> PlanReconexion:
    """R-J-02: `tecnicos.das_reconexion_s` = [2, 4, 8, 16, 30] → esperas 2/4/8/16 y tope 30 (defecto de `cliente`)."""
    lista = cfg.tecnicos.get("das_reconexion_s")
    if isinstance(lista, list) and len(lista) >= 2:
        try:
            return PlanReconexion(tuple(float(x) for x in lista[:-1]), float(lista[-1]))
        except (TypeError, ValueError):
            logger.warning("[VIGILANTE] tecnicos.das_reconexion_s inválido: se usan 2/4/8/16/30 s")
    return PlanReconexion()


def _ventana_por_horario(cfg: Config) -> Callable[[datetime], bool]:
    """R-L-01 / R-J-05 sin red: lunes a viernes, de `horario.encender` (03:55) a `horario.apagar` (o 20:00).

    Los festivos los decide el supervisor (no lanza al vigilante sin sesión);
    esto solo evita pingar de madrugada o en fin de semana.
    """
    horario = cfg.horario if isinstance(cfg.horario, dict) else {}
    encender = _hhmm_o(horario.get("encender"), HORA_ENCENDER_DEFECTO)
    apagar = _hhmm_o(horario.get("apagar"), HORA_APAGAR_DEFECTO)

    def dentro(ahora_et: datetime) -> bool:
        if ahora_et.weekday() >= 5:
            return False
        dia = ahora_et.date()
        return mod_reloj.a_hora_et(encender, dia) <= ahora_et < mod_reloj.a_hora_et(apagar, dia)

    return dentro


def _hhmm_o(valor: Any, defecto: str) -> str:
    if not isinstance(valor, str):
        return defecto
    try:
        mod_reloj.a_hora_et(valor, date(2026, 1, 2))
    except ValueError:
        logger.warning("[VIGILANTE] hora del horario inválida (%r): se usa %s", valor, defecto)
        return defecto
    return valor


# ══════════════════════════════════════════════════════════════════════
# Construcción desde el entorno (producción)
# ══════════════════════════════════════════════════════════════════════
def directorio_bot() -> Path:
    """`BOT_DAS_DIR` (leída en la llamada) o el defecto de §1 (`config.DIR_BOT_POR_DEFECTO`)."""
    return Path(os.environ.get(ENV_DIR, "").strip() or mod_config.DIR_BOT_POR_DEFECTO)


def construir_desde_env(cfg: Config, reloj: Any, *, canales: Optional[list] = None,
                        abrir_ping: Optional[Callable[..., Any]] = None,
                        dentro_de_ventana: Optional[Callable[[datetime], bool]] = None,
                        plan_reconexion: Optional[PlanReconexion] = None,
                        aviso_config: Optional[str] = None) -> VigilanteDAS:
    """Monta el vigilante de producción desde el entorno (§3.27, R-C-08, R-J-05, corrección 15, R-Q-01).

    Watch: `ClienteDAS.desde_env(watch=True, solo_lectura=True)` (DAS_API_HOST,
    DAS_API_PORT, DAS_USUARIO, DAS_CLAVE, DAS_CUENTA). Acción, fuera de SOMBRA:
    `ClienteDAS.desde_env(watch=False, solo_lectura=False)` abierta bajo
    demanda; en CANARIO/REAL se exige ya aquí `BOT_DAS_PERMITIR_ORDENES=1`
    (corrección 15; sin ella RuntimeError, igual que el ejecutor). Ping:
    `BOT_DAS_PING_URL` (sin ella, aviso 2 al arrancar). Diario con el
    limpiador de `FiltroSecretos` (secretos del entorno + la URL del ping).
    Los argumentos por nombre son para tests (sin red). Construir NO abre
    red, NO arranca hilos y NO escribe el diario.
    """
    if not isinstance(cfg, Config):
        raise TypeError(f"cfg debe ser una Config, no {type(cfg).__name__}")
    if cfg.fase is not Fase.SOMBRA and os.environ.get(ENV_PERMITIR_ORDENES, "").strip() != "1":
        raise RuntimeError(f"{ENV_PERMITIR_ORDENES}=1 es obligatorio en el entorno (.env del VPS) en fase "
                           f"{cfg.fase.value}: el vigilante repone stops con dinero real (corrección 15, R-O-03)")
    dir_bot = directorio_bot()
    for sub in SUBCARPETAS_BOT:
        (dir_bot / sub).mkdir(parents=True, exist_ok=True)
    ruta_estado = dir_bot / "estado"
    url_ping = os.environ.get(ENV_PING_URL, "").strip()
    filtro = mod_avisos.FiltroSecretos(mod_avisos.secretos_desde_env() + ([url_ping] if url_ping else []))
    cola = ColaVigilante()
    watch = ClienteDAS.desde_env(watch=True, solo_lectura=True, al_mensaje=cola.al_mensaje, al_estado=cola.al_estado,
                                 reloj=reloj, al_aviso=cola.al_aviso, al_caida_hilo=cola.al_caida_hilo)
    cuotas = _bloque(cfg.tecnicos, "cuotas")

    def abrir_accion() -> Optional[ClienteDAS]:
        """Corrección 16: un LOGIN normal bajo demanda; None si no se puede (el vigilante pedirá relanzar el ejecutor)."""
        if cfg.fase is Fase.SOMBRA:
            return None                               # tercer candado: en sombra el vigilante no envía nunca (R-O-03)
        try:
            cuota = CuotaComandos(reloj, ordenes_s=_entero_positivo(cuotas.get("ordenes_s"), 50),
                                  cancel_min=_entero_positivo(cuotas.get("cancel_min"), 100),
                                  replace_min=_entero_positivo(cuotas.get("replace_min"), 100),
                                  locate_min=_entero_positivo(cuotas.get("locate_min"), 100),
                                  margen=min(_numero_positivo(cuotas.get("margen"), 0.9), 1.0))
            cliente = ClienteDAS.desde_env(watch=False, solo_lectura=False, al_mensaje=cola.al_mensaje_accion,
                                           al_estado=cola.al_estado_accion, reloj=reloj, cuota=cuota,
                                           al_aviso=cola.al_aviso, al_caida_hilo=cola.al_caida_hilo,
                                           al_descartar=cola.al_descartar)
        except RuntimeError as exc:  # entorno incompleto: sin conexión de acción (corrección 16)
            logger.error("[VIGILANTE] conexión de acción imposible: %s", exc)
            return None
        if not cliente.conectar():
            _cerrar_sin_lanzar(cliente)
            return None
        return cliente

    vig = _bloque(cfg.tecnicos, "vigilante")
    ping = PingExterno(url_ping, reloj, cada_s=_numero_positivo(vig.get("ping_externo_s"), PING_EXTERNO_S),
                       abrir=abrir_ping if abrir_ping is not None else urllib.request.urlopen,
                       fallos_alarma=_entero_positivo(vig.get("ping_fallos_alarma"), PING_FALLOS_ALARMA),
                       al_aviso=cola.al_aviso_nivel)
    diario = Diario(dir_bot / "diario", reloj, "vigilante", VERSION, cfg.fase, limpiar=filtro.limpiar)
    avisos = mod_avisos.ColaAvisos(canales if canales is not None else mod_avisos.canales_desde_env(cfg), reloj)
    return VigilanteDAS(
        cfg, watch, abrir_accion, LectorDiario(dir_bot / "diario"), diario, avisos, reloj,
        Latido(ruta_estado / NOMBRE_LATIDO, reloj, cada_s=_numero_positivo(vig.get("latido_s"), 1.0)),
        CerrojoInstancia(ruta_estado / NOMBRE_CERROJO), ruta_estado / NOMBRE_LATIDO_EJECUTOR, ping,
        ruta_estado / NOMBRE_ORDEN_SUPERVISOR, cola=cola, dentro_de_ventana=dentro_de_ventana,
        plan_reconexion=plan_reconexion, aviso_config=aviso_config)


# ══════════════════════════════════════════════════════════════════════
# python -m app.bot_das.vigilante
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


def _instalar_senales(vigilante: VigilanteDAS) -> None:
    """Ctrl+C / Ctrl+Break → parada ordenada (el `terminate` del supervisor no se puede capturar en Windows)."""
    def manejador(signum: int, _frame: Any) -> None:
        vigilante.pedir_parada(f"señal {signum}", CODIGO_OK)

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
    """`python -m app.bot_das.vigilante [--config ruta]`: .env → logging con FiltroSecretos → config → construir → correr.

    Códigos: 0 parada ordenada, 3 doble instancia, 5 config/entorno, 1 error
    no previsto. `parar()` siempre.
    """
    parser = argparse.ArgumentParser(prog="python -m app.bot_das.vigilante", description="Vigilante del bot de DAS")
    parser.add_argument("--config", type=Path, default=None,
                        help="fichero del cuadro (defecto: BOT_DAS_DIR/config/bot_das_config.json)")
    args = parser.parse_args(list(argv) if argv is not None else None)
    backend = Path(__file__).resolve().parents[2]
    _cargar_dotenv(RUTA_DOTENV if RUTA_DOTENV is not None else backend / ".env")
    dir_bot = directorio_bot()
    reloj = mod_reloj.Reloj()
    url_ping = os.environ.get(ENV_PING_URL, "").strip()
    mod_avisos.instalar_logging("vigilante", dir_bot / "logs",
                                mod_avisos.secretos_desde_env() + ([url_ping] if url_ping else []), reloj=reloj)
    try:
        cuenta = os.environ.get(ENV_CUENTA, "").strip()
        if not cuenta:
            logger.error("[VIGILANTE] falta %s en el entorno (R-Q-01): no se puede cargar la config", ENV_CUENTA)
            return CODIGO_CONFIG
        ruta_cfg = args.config or dir_bot / "config" / mod_config.NOMBRE_FICHERO_CONFIG
        try:
            cfg, aviso = mod_config.cargar_con_respaldo(ruta_cfg, dir_bot / "config" / mod_config.NOMBRE_ULTIMO_BUENO,
                                                        cuenta)
            vigilante = construir_desde_env(cfg, reloj, aviso_config=aviso)   # R2-PRO-3: el aviso va por avisos
        except (mod_config.ConfigInvalida, RuntimeError, ValueError, OSError) as exc:
            logger.error("[VIGILANTE] no arranca: %s: %s", type(exc).__name__, exc)
            return CODIGO_CONFIG
        if aviso:
            logger.warning("[VIGILANTE] config: %s", aviso)
        _instalar_senales(vigilante)
        codigo = CODIGO_ERROR
        try:
            codigo = vigilante.correr()
        except Exception:  # noqa: BLE001 — frontera del proceso: se registra y el supervisor relanza (R-J-04 a)
            logger.exception("[VIGILANTE] error no previsto")
            codigo = CODIGO_ERROR
        finally:
            vigilante.parar()
        logger.info("[VIGILANTE] sale con código %d", codigo)
        return codigo
    finally:
        mod_avisos.desinstalar_logging()


if __name__ == "__main__":
    sys.exit(main())
