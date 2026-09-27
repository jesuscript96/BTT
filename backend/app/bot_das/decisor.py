"""El decisor del bot de ejecución en DAS: el ÚNICO que muta `EstadoBot` (H-5, §3.26, §5 F1-F14).

QUÉ HACE. `Decisor.procesar(mensaje, ahora, ahora_et)` recibe TODO lo que le
pasa al bot (señales del motor, mensajes de DAS, temporizadores, comandos de
Telegram y del cuadro, configuración nueva, caídas de la conexión o de un
hilo y el `Tic` del bucle) y devuelve la lista ORDENADA de `Accion` que el
ejecutor ejecuta: órdenes, cancelaciones, consultas, avisos, diario y
temporizadores. Por dentro llama a las reglas puras de `reglas/*` y aplica lo
que devuelven al estado: la entrada v3 y la suma de señales (F1, F3), los
stops y su limpieza (F2), el TP y la salida por hora (F4, F5), los halts
(F6), el cisne negro (F7), los rechazos (F8), los locates (F9), la
reconciliación (F10), los modos degradados (F11), el arranque y el reinicio
(F12, F13) y las estrategias desactivadas (F14). `foto()` es el panel 4.4.

POR QUÉ ESTÁ AQUÍ. Un solo hilo muta el estado (§6.1): todo entra por
`procesar`, en orden, y nada más escribe en `EstadoBot`, `MercadoDAS` ni en
los generadores de tokens. El decisor no abre sockets ni escribe ficheros: lo
que tiene que salir sale como `Accion` y el ejecutor lo ejecuta tras escribir
el diario (write-ahead). Así el mismo decisor corre en vivo, en sombra, en el
replay y en los tests contra un DAS falso. Las únicas lecturas de fuera son
la referencia de Massive (REST síncrono con caché diaria) y el calendario,
los dos inyectables.

LAS TRAMPAS.
  * H-5: cada rama que toca un ticker va en try/except → `Anotar("excepcion")`
    con el traceback, el ticker a PAUSADO (motivo «excepcion») y `Avisar(2)`;
    el bucle sigue con el mensaje siguiente. Las acciones que esa rama
    llevaba se descartan a propósito (medio plan de stops es peor que
    ninguno); una orden que ya estaba registrada y no salió la cierra la
    reconciliación como «sin eco» (riesgo 3).
  * Libro de fills por token (corrección 2, riesgo 8): `Execute` y `%TRADE`
    del mismo fill llegan en cualquier orden. Se casan por (id de la orden,
    acciones) con dos contadores: el primero que llega CUENTA y el segundo es
    su eco. El registro «fill» con `id_trade` real (el que cuenta
    `diario.reconstruir`) sale del `%TRADE`; el de un `Execute` va con
    `id_trade` None y el eco posterior lo completa.
  * `InvalidarSerie("stops:X")` va SIEMPRE antes de cualquier plan nuevo tras
    un fill (injerto §8.6): un REPLACE viejo en la cola nunca sale después.
  * El resto que se cruza (entrada) o se remata (TP, hora) sale SOLO de lo
    confirmado: un token no se suelta hasta que su orden está CUADRADA
    (terminal y llenas + canceladas ≥ pedidas, injerto §8.7). Un fill en
    vuelo detrás de un `Canceled` no se vende dos veces.
  * `ahora` es monotónico y `ahora_et` aware ET. Los plazos de la entrada
    son EPOCH (`t_limite`): se comparan con `ahora_et.timestamp()`, nunca con
    `ahora`. El latido del feed (epoch) se guarda convertido a monotónico.
  * Claves de temporizador con el ticker, el lote o el token («cruce:X»,
    «hora_ask:<lote>», «replace_verificar:<token>»): un `Programar` con la
    misma clave sustituye al anterior (§6.1). El id de un lote lleva «:» (la
    hora de la vela): se despacha por el prefijo y se lee el lote de `datos`.
  * Precios `Decimal`, acciones `int`: los floats del `Evento` pasan UNA vez
    por `precios.de_float` / `entrada.qty_de_evento`.
  * Lo que el diario no reconstruye (intentos, vetos de halt, sobrescrituras
    de Telegram, contadores de persecución) vive en memoria: tras un reinicio
    `arrancar()` cierra los intentos a medias y reprograma los temporizadores
    de salida de cada lote vivo (F12/F13).
"""
from __future__ import annotations

import dataclasses
import math
import re
import traceback
from collections import deque
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Callable, Iterable, Optional, Sequence

from app.bot_das import VERSION, avisos, comandos
from app.bot_das import config as mod_config
from app.bot_das.mercado_das import FRESCA_MAX_S, MercadoDAS
from app.bot_das.reglas import (
    capital,
    cisne_negro,
    entrada,
    exclusiones,
    halts,
    locates,
    precios,
    rechazos,
    reconciliacion,
    salidas,
    stops,
)
from app.bot_das.reloj import ET
from app.bot_das.tipos import (
    DAS_AVISO_CADA_S,
    ENTRADA_CRUCE_BAJO_BID_PCT,
    ENTRADA_TOPE_CAIDA_BID_PCT,
    FEED_EMERGENCIA_S,
    FEED_PREALERTA_S,
    PERSEGUIR_ASK_MAX,
    RECONCILIACION_CADUCA_S,
    STOP_DEBOUNCE_S,
    STOP_PRINCIPAL_LIMITE_PCT,
    STOP_PROTECCION_PCT,
    Accion,
    Anotar,
    Avisar,
    Cancelar,
    CancelarTicker,
    ClaseSalida,
    Comando,
    ComandoRecibido,
    ConexionDAS,
    Config,
    ConfigNueva,
    Consultar,
    Cotizacion,
    DeDAS,
    Desprogramar,
    EnviarOrden,
    EstadoBot,
    EstadoLote,
    EstadoOrden,
    EstadoTicker,
    EstrategiaConfig,
    Fase,
    FaseIntento,
    Fill,
    Grupo,
    HiloCaido,
    InvalidarSerie,
    Lado,
    LocateComprar,
    LocateInquire,
    LocateOferta,
    Lote,
    Mensaje,
    MensajeDAS,
    MsgAccountInfo,
    MsgBP,
    MsgConexion,
    MsgDesconocido,
    MsgIntMsg,
    MsgIssueStatus,
    MsgLDLU,
    MsgOrden,
    MsgOrderAct,
    MsgPos,
    MsgQuote,
    MsgRouteStatus,
    MsgShortInfo,
    MsgSLMinCharge,
    MsgSLOrder,
    MsgSLRet,
    MsgSLReuse,
    MsgTrade,
    Nivel,
    NivelesStop,
    Orden,
    OrdenNueva,
    Origen,
    PosicionTicker,
    Programar,
    Proposito,
    PublicarFoto,
    Reemplazar,
    Senal,
    SenalRecibida,
    Suscribir,
    Temporizador,
    Tic,
    TipoOrden,
)
from app.bot_das.tokens import GeneradorTokens, descomponer, es_nuestro

__all__ = [
    "Decisor",
    "T_CRUCE", "T_CANCEL_ESPERA", "T_CRUCE_ESPERA", "T_STOPS_AJUSTAR", "T_STOPS_PLAN", "T_REPLACE_VERIFICAR",
    "T_TP_CRUCE", "T_TP_ESPERA_ENTRADA", "T_HORA_AGREGAR", "T_HORA_ASK", "T_EOD_COMPROBAR", "T_PERSEGUIR_ASK",
    "T_HALT_DECIDIR", "T_HALT_PRIMERA_VELA", "T_SIMSTATUS", "T_BARRIDO", "T_BS_INFORME", "T_BS_CIERRE",
    "T_LOCATE_INQUIRE", "T_STOP_REINTENTO", "T_REINTENTO_RECHAZO", "T_LOCATE_RECOMPRAR", "T_CERRAR_TODO",
    "T_DAS_AVISO", "T_DAS_RECONECTAR", "T_FOTO",
    "MOTIVO_SUMA", "MOTIVO_VENCER", "MOTIVO_CRUCE_ESPERA", "MOTIVO_PRIORIDAD", "MOTIVO_HALT", "MOTIVO_CIERRE",
    "MOTIVO_BLOQUEO", "MOTIVO_RECHAZO", "MOTIVO_SIN_CONFIRMAR", "MOTIVO_CANCELADA_DAS",
]

# ── claves de temporizador (§3.26; las que tienen dueño llevan «:ticker», «:lote» o «:token») ──
T_CRUCE = "cruce"                                   # F1.7: t_limite del intento («cruce:X»)
T_CANCEL_ESPERA = "cancel_espera"                   # F1.7: sondeo de la cancelación del intento («cancel_espera:X»)
T_CRUCE_ESPERA = "cruce_espera"                     # F1.8: el cruce no llenó en `cruce_espera_s` («cruce_espera:X»)
T_STOPS_AJUSTAR = "stops_ajustar"                   # F1.6: debounce de los fills siguientes («stops_ajustar:X»)
T_STOPS_PLAN = stops.CLAVE_REPLANIFICAR             # F2.1: precondición neta_das ≠ neta_fills («stops_plan:X»)
T_REPLACE_VERIFICAR = stops.CLAVE_VERIFICAR_REPLACE  # F2.2 / 2h.8 («replace_verificar:<token>»)
T_TP_CRUCE = salidas.CLAVE_TP_CRUCE                 # F4.3 («tp_cruce:<lote>»)
T_TP_ESPERA_ENTRADA = "tp_espera_entrada"           # R-D-07 («tp_espera_entrada:X»)
T_HORA_AGREGAR = salidas.CLAVE_HORA_AGREGAR         # F5 («hora_agregar:<lote>»)
T_HORA_ASK = salidas.CLAVE_HORA_ASK                 # F5 («hora_ask:<lote>»)
T_EOD_COMPROBAR = salidas.CLAVE_EOD_COMPROBAR       # F5 / R-D-02 («eod_comprobar:<lote>»)
T_PERSEGUIR_ASK = "perseguir_ask"                   # corrección 11 («perseguir_ask:<token>»)
T_HALT_DECIDIR = "halt_decidir"                     # F6.2 («halt_decidir:X»)
T_HALT_PRIMERA_VELA = "halt_primera_vela"           # F6.3 / R-F-03 / R-F-04 (b) («halt_primera_vela:X»)
T_SIMSTATUS = "simstatus"                           # F6.1: GET SymStatus cada 1 s (global)
T_BARRIDO = rechazos.CLAVE_BARRIDO                  # F10 / R-K-01 (global)
T_BS_INFORME = cisne_negro.CLAVE_INFORME            # F7 («bs_informe:X»)
T_BS_CIERRE = cisne_negro.CLAVE_CIERRE_REINTENTO    # F7 / R-D-06 («bs_cierre:X»)
T_LOCATE_INQUIRE = "locate_inquire"                 # F9 («locate_inquire:X:S»)
T_STOP_REINTENTO = rechazos.CLAVE_STOP_REINTENTO    # R-C-03 («stop_reintento:<token>»)
T_REINTENTO_RECHAZO = rechazos.CLAVE_REINTENTO_RECHAZO  # R-B-07 (2) recalcular_bp («reintento_rechazo:<token>»)
T_LOCATE_RECOMPRAR = rechazos.CLAVE_LOCATE_RECOMPRAR    # R-B-07 caso locate («locate_recomprar:<token>»)
T_CERRAR_TODO = salidas.CLAVE_CERRAR_TODO           # R-D-06 (global)
T_DAS_AVISO = "das_aviso"                           # R-J-02 (3): DAS caído, aviso cada 5 min (global)
T_DAS_RECONECTAR = "das_reconectar"                 # R-J-02: lo reconecta el ejecutor; aquí solo se registra
T_FOTO = "foto"                                     # panel 4.4 (global; el Tic ya la publica cada foto_cada_s)
_GLOBALES = frozenset({T_SIMSTATUS, T_BARRIDO, T_CERRAR_TODO, T_DAS_AVISO, T_DAS_RECONECTAR, T_FOTO})

# ── constantes técnicas del decisor (no son reglas del libro: van anotadas en las desviaciones) ──
CANCEL_ESPERA_S = 0.5            # F1.7: GET ORDERS cada 0,5 s mientras la cancelación no se confirma
CANCEL_ESPERA_MAX = 6            # tras 6 sondeos (3 s) se cierra el intento con lo llenado y se avisa
SIMSTATUS_CADA_S = 1.0           # F6.1
LDLU_CADA_S = 60.0               # R-F-02: bandas refrescadas cada minuto en RTH
TP_ESPERA_ENTRADA_S = 1.0        # R-D-07: la entrada retenida se revisa cada segundo
PERSEGUIR_ASK_CADA_S = 1.0       # F5 («sin fill en 1 s»); `salidas.por_hora.perseguir_ask_s` manda si está
REPLACE_VERIFICAR_MAX = 3        # F2.2: tres comprobaciones del tipo tras un REPLACE
HALT_PRIMERA_VELA_S = 60.0       # R-F-01 esc. 2: la primera vela de 1 min tras reabrir
HALT_REDECIDIR_S = 60.0          # R-F-05 b: con «mantener» se vuelve a decidir (duración T12)
FOGONAZO_VENTANA_S = 300.0       # R-G-01 (4)
FOGONAZO_UMBRAL_PCT = Decimal("50")
FOGONAZO_REVISION_S = 1.0
HISTORIAL_MAX = 2000
RADAR_VIGENCIA_S = 1800.0        # un ticker del radar sigue suscrito 30 min tras su última fila
REFERENCIA_REINTENTO_S = 60.0    # una ficha o una lista de splits que falló no se vuelve a pedir antes
RESUMEN_TRAS_EOD_S = 30.0        # R-M-01: resumen del día tras el último EOD + el margen de R-D-02
FOTO_CADA_S = 2.0                # `tecnicos.foto_cada_s` manda si está
BARRIDO_VIGILANCIA_S = 5.0       # si el temporizador «barrido» se pierde, el Tic lo rearma
_ALTO_RIESGO = False             # R-I-01 (tope corto 0,5 × equity): el documento no define cuándo un día lo es

# ── motivos por los que se cancela la orden viva de un intento ──
MOTIVO_SUMA = "suma"
MOTIVO_VENCER = "vencer"
MOTIVO_CRUCE_ESPERA = "cruce_espera"
MOTIVO_PRIORIDAD = "prioridad"
MOTIVO_HALT = "halt"
MOTIVO_CIERRE = "cierre"
MOTIVO_BLOQUEO = "bloqueo"
MOTIVO_RECHAZO = "rechazo"
MOTIVO_SIN_CONFIRMAR = "sin_confirmar"
MOTIVO_CANCELADA_DAS = "cancelada_por_das"
_PESO_MOTIVO = {MOTIVO_SUMA: 1, MOTIVO_VENCER: 2, MOTIVO_CRUCE_ESPERA: 2, MOTIVO_PRIORIDAD: 3,
                MOTIVO_CANCELADA_DAS: 4, MOTIVO_RECHAZO: 4, MOTIVO_SIN_CONFIRMAR: 4,
                MOTIVO_BLOQUEO: 5, MOTIVO_CIERRE: 5, MOTIVO_HALT: 5}
_TEXTO_MOTIVO_CIERRE = {
    MOTIVO_HALT: "B18 / R-F-04 (a): halt con la entrada viva; se queda lo llenado",
    MOTIVO_CIERRE: "R-D-06: cierre pedido por el humano; se queda lo llenado",
    MOTIVO_BLOQUEO: "corrección 4 / R-J-03: entradas bloqueadas; se queda lo llenado",
    MOTIVO_RECHAZO: "R-B-07: rechazo sin reintento; se queda lo llenado",
    MOTIVO_SIN_CONFIRMAR: "F1.7: la cancelación no se confirmó; se queda lo llenado y manda la reconciliación",
    MOTIVO_CANCELADA_DAS: "DAS canceló la entrada sin pedirlo; se queda lo llenado",
}

_TERMINALES = frozenset({EstadoOrden.CANCELED, EstadoOrden.REJECTED, EstadoOrden.EXECUTED, EstadoOrden.CLOSED})
_VIVOS = frozenset(stops.ESTADOS_VIVOS)
_LOTE_VIVO = frozenset({EstadoLote.ABRIENDO, EstadoLote.ABIERTO, EstadoLote.CERRANDO})
_PROP_ENTRADA = frozenset({Proposito.ENTRADA_AGREGAR, Proposito.ENTRADA_CRUCE})
_PROP_STOP = frozenset(stops.PROPOSITOS_STOP)
_PROP_SALIDA_LOTE = frozenset({Proposito.TP_AGREGAR, Proposito.TP_CRUCE, Proposito.HORA_AGREGAR, Proposito.HORA_ASK,
                               Proposito.SALIDA_MOTOR_AGREGAR, Proposito.SALIDA_MOTOR_CRUCE,
                               Proposito.CIERRE_REINICIO})
_PROP_SALIDA = _PROP_SALIDA_LOTE | frozenset({Proposito.HALT_OPEN, Proposito.HALT_PM_LIMITE, Proposito.HALT_BANDA,
                                              Proposito.CIERRE_HUMANO})
_PROP_HALT = frozenset({Proposito.HALT_OPEN, Proposito.HALT_PM_LIMITE})
_LADOS_COMPRA = frozenset({"B", "BUY"})
_RE_HORA = re.compile(r"^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$")


class _RelojDelMensaje:
    """Reloj monotónico para `comandos.Confirmaciones`: el `ahora` del mensaje en curso (el decisor no lee el sistema)."""

    def __init__(self, decisor: "Decisor") -> None:
        self._decisor = decisor

    def mono(self) -> float:
        return self._decisor._ahora


class Decisor:
    """El único mutador de `EstadoBot` (§3.26, §6.1). Puro respecto a la E/S: todo sale como `Accion`.

    Contrato de §3.26 más, solo por nombre: `tokens_locate` (el generador de
    `Origen.EJECUTOR_LOCATE`; por defecto uno nuevo del día sobre
    `estado.ultimo_seq_token`), `calendario` (objeto con
    `franja_de_mercado(ahora_et)` y `media_sesion(dia)`; por defecto el módulo
    `bot_alerts_calendario`, importado la primera vez que hace falta),
    `lineas_log` (callable `n → últimas n líneas` para `/log`) y `tamano_cola`
    (callable → tamaño de la cola del ejecutor, para la foto). Lanza TypeError
    o ValueError con argumentos imposibles; `procesar` solo lanza con un
    mensaje o un reloj inválidos.
    """

    def __init__(self, cfg: Config, estado: EstadoBot, mercado: MercadoDAS, referencia: Any,
                 tokens: GeneradorTokens, catalogo_rechazos: list[dict], diario_degradado: Callable[[], bool], *,
                 tokens_locate: Optional[GeneradorTokens] = None, calendario: Any = None,
                 lineas_log: Optional[Callable[[int], Sequence[str]]] = None,
                 tamano_cola: Optional[Callable[[], int]] = None) -> None:
        if not isinstance(cfg, Config):
            raise TypeError(f"cfg debe ser una Config, no {type(cfg).__name__}")
        if not isinstance(estado, EstadoBot):
            raise TypeError(f"estado debe ser un EstadoBot, no {type(estado).__name__}")
        if not isinstance(mercado, MercadoDAS):
            raise TypeError(f"mercado debe ser un MercadoDAS, no {type(mercado).__name__}")
        if referencia is not None and not (callable(getattr(referencia, "ficha", None))
                                           and callable(getattr(referencia, "splits_de_hoy", None))):
            raise TypeError("referencia debe tener ficha(ticker) y splits_de_hoy(dia), o ser None")
        if not isinstance(tokens, GeneradorTokens) or tokens.origen is not Origen.EJECUTOR:
            raise ValueError("tokens debe ser un GeneradorTokens de Origen.EJECUTOR")
        if tokens_locate is not None and (not isinstance(tokens_locate, GeneradorTokens)
                                          or tokens_locate.origen is not Origen.EJECUTOR_LOCATE):
            raise ValueError("tokens_locate debe ser un GeneradorTokens de Origen.EJECUTOR_LOCATE")
        if not callable(diario_degradado):
            raise TypeError("diario_degradado debe ser un callable () -> bool")
        if calendario is not None and not (callable(getattr(calendario, "franja_de_mercado", None))
                                           and callable(getattr(calendario, "media_sesion", None))):
            raise TypeError("calendario debe tener franja_de_mercado(ahora) y media_sesion(dia)")
        for nombre, valor in (("lineas_log", lineas_log), ("tamano_cola", tamano_cola)):
            if valor is not None and not callable(valor):
                raise TypeError(f"{nombre} debe ser un callable o None")
        self._catalogo = rechazos.validar_catalogo(catalogo_rechazos)
        self._cfg_base = cfg
        self._cfg = cfg
        self._override_modo_seguridad: Optional[bool] = None
        self._override_estrategia: dict[str, dict[str, Any]] = {}
        self._estado = estado
        self._mercado = mercado
        self._referencia = referencia
        self._tokens = tokens
        self._tokens_locate = tokens_locate if tokens_locate is not None else GeneradorTokens(
            Origen.EJECUTOR_LOCATE, tokens.hoy, max(0, int(estado.ultimo_seq_token)))
        self._diario_degradado = diario_degradado
        self._calendario = calendario
        self._lineas_log = lineas_log
        self._tamano_cola = tamano_cola
        self._ahora = 0.0
        self._ahora_et = datetime(estado.dia.year, estado.dia.month, estado.dia.day, tzinfo=ET)
        self._inicio_en: Optional[float] = None
        self._confirmaciones = comandos.Confirmaciones(_RelojDelMensaje(self))
        self._acumulador = reconciliacion.AcumuladorVolcado()
        # libro de fills (dedupe Execute ↔ %TRADE)
        self._trades_vistos: set[int] = set()
        self._n_execute: dict[tuple[Optional[int], int], int] = {}
        self._n_trade: dict[tuple[Optional[int], int], int] = {}
        self._fills_sin_id: dict[tuple[Optional[int], int], deque[Fill]] = {}
        self._id_sintetico = 0
        # órdenes
        self._cancel_pedido: dict[int, str] = {}
        self._cancelar_al_aceptar: dict[int, str] = {}
        self._reemplazo_pedido: dict[int, tuple[int, Optional[Decimal], Optional[Decimal]]] = {}
        self._meta_orden: dict[int, tuple[int, float]] = {}
        self._continuacion: dict[int, tuple[str, dict]] = {}
        self._persecuciones: dict[int, int] = {}
        self._verificaciones: dict[int, int] = {}
        # posiciones e intentos
        self._inicio_episodio: dict[str, float] = {}
        self._lotes_de_orden: dict[int, list[str]] = {}
        self._tokens_intento: dict[str, set[int]] = {}
        self._motivo_cancel: dict[str, str] = {}
        self._intento_pausado: set[str] = set()
        self._intento_en_reintento: set[str] = set()
        self._rechazos_tratados: set[int] = set()
        self._locates_de_lote: dict[str, list[tuple[str, int]]] = {}
        self._espera_plan: set[str] = set()
        self._stop_bloqueo: dict[str, float] = {}
        self._stop_intentos: dict[tuple[str, Proposito], tuple[int, float]] = {}
        self._manual: set[str] = set()
        self._cierre_humano: set[str] = set()
        self._entradas_en_espera: dict[str, list[Senal]] = {}
        # halts, cisne negro y fogonazos
        self._halt_en_curso: set[str] = set()
        self._halt_fin: dict[str, Optional[datetime]] = {}
        self._halt_decision: dict[str, str] = {}
        self._halt_humano_avisado: set[str] = set()
        self._halt_hoy: set[str] = set()
        self._stop_hoy: set[str] = set()
        self._reapertura_ok: set[str] = set()
        self._banda_enviada: set[str] = set()
        self._hist: dict[str, deque[tuple[float, Decimal]]] = {}
        self._fogonazo_revisado_en: dict[str, float] = {}
        self._fogonazo_anotado: dict[str, float] = {}
        # locates, radar y referencia
        self._radar: dict[str, float] = {}
        self._radar_precio: dict[str, Decimal] = {}
        self._inquires: deque[tuple[str, str]] = deque()
        self._slorders_cobrados: set[int] = set()
        self._slorders_ajenos: set[int] = set()
        self._minimo_cargo: dict[str, Decimal] = {}
        self._ficha_fallo_en: dict[str, float] = {}
        self._splits: Optional[tuple[date, set[str]]] = None
        self._splits_fallo_en: Optional[float] = None
        # vigilancia y avisos
        self._avisos_dia: set[str] = set()
        self._simstatus_armado = False
        self._ultimo_ldlu_en: Optional[float] = None
        self._ultima_foto_en: Optional[float] = None
        self._barrido_pedido_en: Optional[float] = None
        self._barrido_siguiente_en: Optional[float] = None
        self._feed_nivel = "ok"
        self._das_caido_desde: Optional[float] = None
        self._reconciliacion_avisada = False
        self._resumen_enviado: Optional[date] = None
        self._ajenas_anotadas: set[int] = set()
        self._sin_simbolo_avisado: set[str] = set()
        self._prealerta_en: dict[tuple[str, str], float] = {}
        self._rutas_avisadas: set[str] = set()
        self._reuso_consultado: set[str] = set()
        if estado.reconciliacion_ok_en is None:
            estado.modo_degradado.add("reconciliacion")      # R-J-02.5: nada se abre hasta reconciliar
        self._reconstruir_dedupe()

    # ═══════════════════════════ API pública ═══════════════════════════════
    @property
    def cfg(self) -> Config:
        """La configuración EFECTIVA (la del cuadro más lo cambiado por Telegram)."""
        return self._cfg

    @property
    def estado(self) -> EstadoBot:
        return self._estado

    def arrancar(self, ahora: float, ahora_et: datetime) -> list[Accion]:
        """F12 / F13 (R-C-10, R-J-06, H-2): lo primero tras `reconstruir` y conectar, antes de abrir nada.

        Pide `GET RouteStatus`, `GET BP`, `GET AccountInfo`, `GET INTMSGS` y
        `SLRouteMinCharge ALLROUTE`; cierra los intentos que quedaron a medias
        (lotes ABRIENDO → ABIERTO con lo llenado o CANCELADO, y cancela sus
        entradas vivas: lo que DAS diga que llenó llega con el volcado y se
        reparte al lote); reprograma los temporizadores de salida de cada lote
        vivo (son de reloj, no de estado) y los informes de un cisne negro; y
        programa el barrido inmediato, que ADOPTA las órdenes del vigilante
        (`reconciliacion.acciones`) antes de que `stops.plan` ponga nada.
        """
        self._fijar_reloj(ahora, ahora_et)
        acciones: list[Accion] = [
            Anotar("decisor_arranque", {"version": VERSION, "fase": self._estado.fase.value,
                                        "posiciones": sorted(self._estado.posiciones),
                                        "senales_vistas": len(self._estado.senales_vistas)}),
            Consultar("GET RouteStatus"), Consultar("GET BP"), Consultar("GET AccountInfo"),
            Consultar("GET INTMSGS"), Consultar("SLRouteMinCharge ALLROUTE"),
        ]
        for ticker in sorted(self._estado.posiciones):
            pos = self._estado.posiciones[ticker]
            acciones += self._proteger(ticker, "arranque", lambda p=pos: self._arrancar_ticker(p))
        acciones.append(Programar(T_BARRIDO, 0.0, {"motivo": "arranque (F12)"}))
        acciones += self._armar_simstatus()
        return self._finalizar_seguro(acciones)

    def procesar(self, msg: Mensaje, ahora: float, ahora_et: datetime) -> list[Accion]:
        """Un mensaje de la cola → las acciones a ejecutar EN ORDEN (§3.26, §6.1). Nunca lanza salvo por argumentos inválidos.

        Despacho por tipo: `SenalRecibida`, `DeDAS`, `Tic`, `Temporizador`,
        `ComandoRecibido`, `ConfigNueva`, `ConexionDAS`, `HiloCaido`. Antes, el
        cambio de día (tokens, gasto de locates, avisos diarios). Después,
        `_finalizar`: claves de temporizador normalizadas, prefijo de fase en
        los avisos del grupo B (R-O-03), `mono` en cada registro del diario,
        órdenes registradas por token y la red de la corrección 4 (con el
        diario roto no sale ninguna entrada ni compra de locate).
        """
        if not isinstance(msg, Mensaje):
            raise TypeError(f"procesar espera un Mensaje, no {type(msg).__name__}")
        self._fijar_reloj(ahora, ahora_et)
        acciones: list[Accion] = self._proteger(None, "dia", self._cambio_de_dia)
        if isinstance(msg, SenalRecibida):
            acciones += self._senal(msg.senal)
        elif isinstance(msg, DeDAS):
            acciones += self._de_das(msg.msg, bool(msg.simulado))
        elif isinstance(msg, Tic):
            acciones += self._tic()
        elif isinstance(msg, Temporizador):
            acciones += self._temporizador(msg.clave, msg.datos)
        elif isinstance(msg, ComandoRecibido):
            acciones += self._proteger(None, "comando", lambda: self._comando(msg.comando))
        elif isinstance(msg, ConfigNueva):
            acciones += self._proteger(None, "config", lambda: self._config(msg.config, msg.aviso))
        elif isinstance(msg, ConexionDAS):
            acciones += self._proteger(None, "conexion", lambda: self._conexion(msg))
        elif isinstance(msg, HiloCaido):
            acciones += self._proteger(None, "hilo", lambda: self._hilo_caido(msg))
        else:
            acciones.append(Anotar("mensaje_desconocido", {"tipo": type(msg).__name__}))
        return self._finalizar_seguro(acciones)

    def foto(self) -> dict:
        """Panel 4.4 (estado/foto.json): fase, posiciones, órdenes vivas, cuenta, locates, pausas, feed/DAS y degradados.

        Todo serializable con `json.dumps` sin `default`: Decimal → texto,
        enumeraciones → su valor, fechas → ISO.
        """
        estado = self._estado
        cuenta = estado.cuenta
        feed_en = estado.feed_ultima_vela_en
        cola: Optional[int] = None
        if self._tamano_cola is not None:
            try:
                cola = int(self._tamano_cola())
            except Exception:  # noqa: BLE001 — frontera: la cola es del ejecutor; una foto no puede tumbar al decisor (H-5)
                cola = None
        try:
            mercado: Any = self._mercado.foto()
        except Exception as exc:  # noqa: BLE001 — frontera: el libro de DAS es de otro módulo; la foto sale sin él (H-5)
            mercado = {"error": f"{type(exc).__name__}: {exc}"}
        return {
            "version": VERSION,
            "fase": estado.fase.value,
            "dia": estado.dia.isoformat(),
            "mono": self._ahora,
            "hora_et": self._ahora_et.isoformat(),
            "vigilando": self._vigilando_efectivo(),
            "pausa_global": estado.pausa_global,
            "control_humano": estado.control_humano,
            "version_config": self._cfg.config_version,
            "posiciones": {t: self._foto_posicion(p) for t, p in sorted(estado.posiciones.items())
                           if self._relevante(p)},
            "ordenes": [self._foto_orden(o) for o in sorted(estado.ordenes.values(), key=lambda o: o.token)
                        if o.estado in _VIVOS],
            "ordenes_ajenas": sorted(estado.ordenes_ajenas),
            "cuenta": {"bp": _txt(cuenta.bp), "bp_overnight": _txt(cuenta.bp_overnight),
                       "equity": _txt(cuenta.equity), "bp_reservado": _txt(cuenta.bp_reservado),
                       "htb_hoy": _txt(cuenta.htb_hoy), "leida_en": cuenta.leida_en},
            "locates": [{"ticker": loc.ticker, "strategy_id": loc.strategy_id, "estado": loc.estado,
                         "pedidas": loc.pedidas, "localizadas": loc.localizadas, "usadas": loc.usadas,
                         "coste": _txt(loc.coste)} for _, loc in sorted(estado.locates.items())],
            "gasto_locates_dia": _txt(estado.gasto_locates_dia),
            "locates_deshabilitados": estado.locates_deshabilitados,
            "tickers_pausados": [{"ticker": t, "estado": p.estado.value, "motivo": p.motivo_estado, "desde": p.desde}
                                 for t, p in sorted(estado.posiciones.items())
                                 if p.estado is not EstadoTicker.NORMAL],
            "senales_del_dia": len(estado.senales_vistas),
            "feed": {"ultima_vela_en": feed_en,
                     "edad_s": (self._ahora - feed_en) if feed_en is not None else None,
                     "nivel": self._feed_nivel},
            "das": {"conectado": estado.das_conectado, "logon": dict(estado.das_logon)},
            "ultima_reconciliacion_en": estado.reconciliacion_ok_en,
            "modos_degradados": sorted(estado.modo_degradado),
            "cola": cola,
            "mercado": mercado,
        }

    # ═══════════════════════════ reloj, protección y final ═════════════════
    def _fijar_reloj(self, ahora: float, ahora_et: datetime) -> None:
        if isinstance(ahora, bool) or not isinstance(ahora, (int, float)) or not math.isfinite(ahora):
            raise ValueError(f"ahora debe ser el reloj monotónico (float finito), no {ahora!r}")
        if not isinstance(ahora_et, datetime) or ahora_et.tzinfo is None or ahora_et.utcoffset() is None:
            raise ValueError(f"ahora_et debe ser un datetime aware en ET, no {ahora_et!r}")
        self._ahora = float(ahora)
        self._ahora_et = ahora_et.astimezone(ET)
        if self._inicio_en is None:
            self._inicio_en = self._ahora

    def _proteger(self, ticker: Optional[str], donde: str, fn: Callable[[], Iterable[Accion]]) -> list[Accion]:
        """H-5: la rama `fn` en try/except. Con ticker: excepción → diario, ticker PAUSADO y aviso 2; el bucle sigue."""
        try:
            return list(fn())
        except Exception as exc:  # noqa: BLE001 — H-5: frontera por ticker; una rama rota pausa SU ticker, no el bot
            return self._fallo(ticker, donde, exc)

    def _fallo(self, ticker: Optional[str], donde: str, exc: BaseException) -> list[Accion]:
        error = f"{type(exc).__name__}: {exc}"
        acciones: list[Accion] = [Anotar("excepcion", {"ticker": ticker, "donde": donde, "error": error,
                                                       "traceback": traceback.format_exc(limit=12),
                                                       "regla": "H-5"})]
        if ticker:
            pos = self._pos(ticker)
            if pos.estado is EstadoTicker.NORMAL:
                pos.estado = EstadoTicker.PAUSADO
                pos.motivo_estado = "excepcion"
                pos.desde = self._ahora
                acciones.append(Anotar("pausa", {"ticker": ticker, "estado": EstadoTicker.PAUSADO.value,
                                                 "motivo": "excepcion", "donde": donde, "regla": "H-5"}))
        quien = f"{ticker}: " if ticker else ""
        acciones.append(Avisar(Nivel.AVISO, Grupo.B,
                               f"Error interno {avisos.escapar_html(quien)}{avisos.escapar_html(donde)} — "
                               f"{avisos.escapar_html(error)}. "
                               + ("El ticker queda PAUSADO (H-5); el resto sigue." if ticker
                                  else "El bot sigue (H-5)."),
                               clave=f"excepcion:{ticker or '-'}:{donde}"))
        return acciones

    def _finalizar_seguro(self, acciones: list[Accion]) -> list[Accion]:
        try:
            return self._finalizar(acciones)
        except Exception as exc:  # noqa: BLE001 — H-5: un fallo al normalizar no puede perder las órdenes ya decididas
            return list(acciones) + self._fallo(None, "finalizar", exc)

    def _finalizar(self, acciones: list[Accion]) -> list[Accion]:
        """Normaliza la tanda: claves de temporizador, prefijo de fase, `mono` en el diario, registro y red de disco."""
        salida: list[Accion] = []
        for a in acciones:
            if isinstance(a, Programar):
                a = self._normalizar_programar(a)
            elif isinstance(a, Avisar) and a.grupo is Grupo.B:
                a = Avisar(a.nivel, a.grupo, avisos.con_prefijo_fase(a.texto, self._estado.fase), a.clave)
            elif isinstance(a, Anotar) and "mono" not in a.datos:
                a = Anotar(a.tipo, {**a.datos, "mono": self._ahora})
            elif isinstance(a, EnviarOrden):
                bloqueo = self._red_disco(a.orden)
                if bloqueo is not None:
                    salida.extend(self._finalizar(bloqueo))
                    continue
                self._registrar_orden(a.orden)
            elif isinstance(a, LocateComprar) and self._diario_roto():
                salida.extend(self._finalizar([
                    Anotar("locate_bloqueado", {"ticker": a.ticker, "qty": a.qty, "token": a.token,
                                                "regla": "corrección 4"}),
                    Avisar(Nivel.MAXIMO, Grupo.B, f"Diario sin escribir: NO se compra el locate de "
                                                  f"{avisos.escapar_html(a.ticker)} (corrección 4)",
                           clave=f"locate_bloqueado:{a.ticker}")]))
                continue
            elif isinstance(a, InvalidarSerie) and salida and salida[-1] == a:
                continue
            salida.append(a)
        salida = _colapsar_programar(salida)
        self._estado.ultimo_seq_token = max(int(self._estado.ultimo_seq_token), self._tokens.ultimo_seq,
                                            self._tokens_locate.ultimo_seq)
        return salida

    def _normalizar_programar(self, p: Programar) -> Programar:
        """Las claves genéricas de las reglas pasan a llevar su dueño (§6.1: una clave repetida sustituye a la anterior)."""
        datos = p.datos if isinstance(p.datos, dict) else {}
        clave = p.clave
        dueno: Any = None
        if clave == T_STOPS_PLAN:
            dueno = datos.get("ticker")
        elif clave == T_REPLACE_VERIFICAR:
            dueno = datos.get("token")
        elif clave == T_STOP_REINTENTO:
            dueno = datos.get("token_rechazado")
        elif clave in (T_REINTENTO_RECHAZO, T_LOCATE_RECOMPRAR):
            dueno = datos.get("token_original")
        if dueno is None:
            return p
        return Programar(f"{clave}:{dueno}", p.en_s, dict(datos))

    def _red_disco(self, o: OrdenNueva) -> Optional[list[Accion]]:
        """Corrección 4: con el diario roto no sale NADA que abra posición (los stops y las salidas sí)."""
        if not self._diario_roto():
            return None
        if o.proposito not in _PROP_ENTRADA and o.lado is not Lado.CORTO:
            return None
        self._registrar_orden(o)
        orden = self._estado.ordenes[o.token]
        orden.estado = EstadoOrden.REJECTED
        orden.notas = "bloqueada: diario degradado (corrección 4)"
        self._rechazos_tratados.add(o.token)
        acciones: list[Accion] = [
            Anotar("orden_bloqueada", {"token": o.token, "ticker": o.ticker, "proposito": o.proposito.value,
                                       "qty": o.qty, "regla": "corrección 4"}),
            Avisar(Nivel.MAXIMO, Grupo.B, f"Diario sin escribir: NO sale la entrada de {avisos.escapar_html(o.ticker)} "
                                          f"({o.qty} acciones). Stops y salidas siguen (corrección 4)",
                   clave=f"orden_bloqueada:{o.ticker}")]
        pos = self._estado.posiciones.get(o.ticker)
        intento = pos.intento if pos is not None else None
        if intento is not None and o.token in (intento.token_agregar, intento.token_cruce):
            self._poner_motivo(o.ticker, MOTIVO_BLOQUEO)
            intento.fase = FaseIntento.CANCELANDO          # se resuelve en el siguiente mensaje: cierre con lo llenado
            acciones.append(Programar(f"{T_CANCEL_ESPERA}:{o.ticker}", 0.0, {"ticker": o.ticker, "n": 0}))
        return acciones

    # ═══════════════════════════ ayudantes de estado ═══════════════════════
    def _pos(self, ticker: str) -> PosicionTicker:
        pos = self._estado.posiciones.get(ticker)
        if pos is None:
            pos = PosicionTicker(ticker=ticker)
            self._estado.posiciones[ticker] = pos
        return pos

    def _diario_roto(self) -> bool:
        try:
            return bool(self._diario_degradado())
        except Exception:  # noqa: BLE001 — frontera: si no se puede saber si el diario escribe, se trata como roto (corrección 4)
            return True

    def _vigilando_efectivo(self) -> bool:
        return bool(self._estado.vigilando and self._cfg.vigilando)

    def _cot(self, ticker: str) -> Optional[Cotizacion]:
        return self._mercado.cotizacion(ticker)

    def _limit_up(self, ticker: str) -> Optional[Decimal]:
        return self._mercado.simbolo(ticker).limit_up

    def _ruta_stop(self) -> str:
        return precios.ruta(self._cfg.rutas, "stop", Decimal("1"), self._ahora_et)

    def _vivas(self, ticker: str) -> list[Orden]:
        return [o for o in self._estado.ordenes.values() if o.ticker == ticker and o.estado in _VIVOS]

    def _ordenes_ticker(self, ticker: str) -> list[Orden]:
        """Órdenes del episodio: las vivas y las terminadas desde que la posición abrió (una emergencia ejecutada cuenta)."""
        inicio = self._inicio_episodio.get(ticker, -math.inf)
        return [o for o in self._estado.ordenes.values()
                if o.ticker == ticker and (o.estado in _VIVOS or o.enviada_en >= inicio)]

    def _salidas_vivas(self, ticker: str) -> bool:
        return any(o.ticker == ticker and o.estado in _VIVOS and o.proposito in _PROP_SALIDA and _qty_viva(o) > 0
                   for o in self._estado.ordenes.values())

    def _emergencia_viva(self, ticker: str) -> bool:
        return any(o.ticker == ticker and o.estado in _VIVOS and _qty_viva(o) > 0
                   and o.proposito in (Proposito.STOP_EMERGENCIA, Proposito.STOP_PROTECCION)
                   for o in self._estado.ordenes.values())

    def _lotes_vivos(self, pos: PosicionTicker) -> list[Lote]:
        return [lote for lote in pos.lotes.values() if lote.estado in _LOTE_VIVO and lote.llenas > 0]

    def _tiene_posicion(self, pos: PosicionTicker) -> bool:
        return pos.neta_fills != 0 or (pos.neta_das or 0) != 0 or bool(self._lotes_vivos(pos))

    def _relevante(self, pos: PosicionTicker) -> bool:
        return (self._tiene_posicion(pos) or pos.intento is not None or pos.estado is not EstadoTicker.NORMAL
                or bool(pos.lotes))

    def _hay_posiciones(self) -> bool:
        return any(self._tiene_posicion(p) or p.intento is not None for p in self._estado.posiciones.values())

    def _refrescar_tp_pendiente(self, pos: PosicionTicker) -> None:
        """`Lote.tp_pendiente` = acciones de las órdenes de salida VIVAS del lote (se deriva; no se anota)."""
        pendiente: dict[str, int] = {}
        for o in self._estado.ordenes.values():
            if (o.ticker == pos.ticker and o.lote_id is not None and o.estado in _VIVOS
                    and o.proposito in _PROP_SALIDA_LOTE):
                pendiente[o.lote_id] = pendiente.get(o.lote_id, 0) + _qty_viva(o)
        for lote in pos.lotes.values():
            lote.tp_pendiente = min(pendiente.get(lote.id, 0), max(lote.llenas, 0))

    def _libres(self, pos: PosicionTicker, lote: Lote) -> int:
        self._refrescar_tp_pendiente(pos)
        return max(int(lote.llenas) - int(lote.tp_pendiente), 0)

    def _estrategia(self, strategy_id: Optional[str]) -> Optional[EstrategiaConfig]:
        return self._cfg.estrategias.get(strategy_id) if strategy_id is not None else None

    def _es_mercado(self, franja: str) -> bool:
        return franja.startswith("premercado") or franja.startswith("RTH")

    def _franja(self) -> str:
        """Franja de mercado del calendario (premercado / RTH / …); un calendario roto da «desconocida» (lo conservador)."""
        try:
            return str(self._modulo_calendario().franja_de_mercado(self._ahora_et))
        except Exception:  # noqa: BLE001 — frontera: el calendario es de otro módulo; sin franja no se deja de decidir
            return "desconocida"

    def _media_sesion(self, dia: date) -> bool:
        try:
            return bool(self._modulo_calendario().media_sesion(dia))
        except Exception:  # noqa: BLE001 — frontera: sin calendario se supone sesión completa (el EOD de la estrategia manda)
            return False

    def _modulo_calendario(self) -> Any:
        if self._calendario is None:
            from app.services import bot_alerts_calendario
            self._calendario = bot_alerts_calendario
        return self._calendario

    def _poner_motivo(self, ticker: str, motivo: str) -> None:
        actual = self._motivo_cancel.get(ticker)
        if actual is None or _PESO_MOTIVO.get(motivo, 0) >= _PESO_MOTIVO.get(actual, 0):
            self._motivo_cancel[ticker] = motivo

    def _una_vez_al_dia(self, clave: str) -> bool:
        if clave in self._avisos_dia:
            return False
        self._avisos_dia.add(clave)
        return True

    def _hora_texto(self) -> str:
        return self._ahora_et.strftime("%H:%M:%S")

    # ═══════════════════════════ órdenes: registro y peticiones ════════════
    def _registrar_orden(self, o: OrdenNueva) -> None:
        """Toda `OrdenNueva` que sale queda en `estado.ordenes` por su token, en SENDING (R-C-07 «quién la puso»)."""
        if o.token in self._estado.ordenes:
            return
        partes = descomponer(o.token)
        origen = partes[0] if partes is not None else Origen.EJECUTOR
        heredado = self._stop_intentos.get((o.ticker, o.proposito)) if o.proposito in _PROP_STOP else None
        intentos, primero = self._meta_orden.pop(o.token, heredado or (0, self._ahora))
        self._estado.ordenes[o.token] = Orden(
            token=o.token, ticker=o.ticker, lado=o.lado, tipo=o.tipo, qty=o.qty, precio=o.precio, stop=o.stop,
            ruta=o.ruta, proposito=o.proposito, lote_id=o.lote_id, nivel=o.nivel, origen=origen,
            estado=EstadoOrden.SENDING, enviada_en=self._ahora, ultima_act=self._ahora, version=o.version,
            intentos=intentos, primer_intento_en=primero)

    def _absorber(self, acciones: Iterable[Accion]) -> list[Accion]:
        """Registra al momento lo que sale de las reglas: órdenes nuevas, cancelaciones y reemplazos pedidos."""
        lista = list(acciones)
        for a in lista:
            if isinstance(a, EnviarOrden):
                self._registrar_orden(a.orden)
            elif isinstance(a, Cancelar):
                token = a.token if a.token is not None else self._estado.id_a_token.get(a.id_das)
                if token is not None:
                    self._cancel_pedido[token] = a.motivo
            elif isinstance(a, CancelarTicker):
                for o in self._estado.ordenes.values():
                    if o.ticker == a.ticker and o.estado in _VIVOS:
                        self._cancel_pedido[o.token] = a.motivo
                        self._cancelar_al_aceptar.pop(o.token, None)
            elif isinstance(a, Reemplazar):
                self._reemplazo_pedido[a.token] = (a.qty, a.precio, a.stop)
                o = self._estado.ordenes.get(a.token)
                if o is not None and a.version:
                    o.version = a.version
            elif isinstance(a, Programar) and a.clave == T_STOPS_PLAN and isinstance(a.datos.get("ticker"), str):
                self._espera_plan.add(a.datos["ticker"])      # F2.1: el %POS que cuadre replanifica sin esperar 0,5 s
        return lista

    def _cancelar_orden(self, o: Orden, motivo: str) -> list[Accion]:
        """Cancela una orden viva una sola vez; sin id de DAS se cancela al llegar su Accept."""
        if o.estado not in _VIVOS or o.token in self._cancel_pedido:
            return []
        if o.id_das is None:
            self._cancelar_al_aceptar[o.token] = motivo
            return []
        return self._absorber([Cancelar(id_das=o.id_das, token=o.token, motivo=motivo)])

    def _cuadrada(self, o: Orden) -> bool:
        """Injerto §8.7: terminal Y llenas + canceladas ≥ pedidas (un rechazo o un cierre no dejan nada en vuelo)."""
        if o.estado not in _TERMINALES:
            return False
        if o.estado in (EstadoOrden.REJECTED, EstadoOrden.CLOSED):
            return True
        return o.llenas + o.cxlqty >= o.qty

    def _transicion(self, o: Orden, nuevo: EstadoOrden) -> bool:
        """Aplica el estado de DAS sin retroceder de un terminal; True si la orden ACABA de pasar a terminal."""
        if nuevo is EstadoOrden.DESCONOCIDO:
            return False
        if o.estado in _TERMINALES:
            if nuevo in _TERMINALES and nuevo is not o.estado and o.estado is not EstadoOrden.EXECUTED:
                o.estado = nuevo
            return False
        o.estado = nuevo
        return nuevo in _TERMINALES

    def _tras_cambio_orden(self, o: Orden, paso_a_terminal: bool) -> list[Accion]:
        """Lo que depende de que una orden cambie: cancelación diferida, stop cancelado sin pedirlo, cuadre del intento."""
        acciones: list[Accion] = []
        if o.proposito in _PROP_STOP and o.estado in stops.ESTADOS_CONFIRMADOS:
            self._stop_intentos.pop((o.ticker, o.proposito), None)    # R-C-03: un stop aceptado cierra la cuenta
        if o.estado in _VIVOS and o.id_das is not None and o.token in self._cancelar_al_aceptar:
            motivo = self._cancelar_al_aceptar.pop(o.token)
            acciones += self._absorber([Cancelar(id_das=o.id_das, token=o.token, motivo=motivo)])
        if paso_a_terminal:
            self._reemplazo_pedido.pop(o.token, None)
            if (o.estado is EstadoOrden.CANCELED and o.proposito in _PROP_STOP
                    and o.token not in self._cancel_pedido):
                acciones += self._stop_cancelado_sin_pedir(o)
            pos = self._estado.posiciones.get(o.ticker)
            intento = pos.intento if pos is not None else None
            if (intento is not None and o.token in (intento.token_agregar, intento.token_cruce)
                    and o.estado is EstadoOrden.CANCELED and o.token not in self._cancel_pedido):
                self._poner_motivo(o.ticker, MOTIVO_CANCELADA_DAS)
        acciones += self._revisar_cuadre(o)
        return acciones

    def _revisar_cuadre(self, o: Orden) -> list[Accion]:
        """Si la orden está cuadrada: suelta el token del intento o sigue con la continuación pendiente (TP, hora)."""
        if not self._cuadrada(o):
            return []
        acciones: list[Accion] = []
        pos = self._estado.posiciones.get(o.ticker)
        intento = pos.intento if pos is not None else None
        pendiente_de_rechazo = o.estado is EstadoOrden.REJECTED and o.token not in self._rechazos_tratados
        if (pos is not None and intento is not None and o.token in (intento.token_agregar, intento.token_cruce)
                and not pendiente_de_rechazo):
            if intento.token_agregar == o.token:
                intento.token_agregar = None
            if intento.token_cruce == o.token:
                intento.token_cruce = None
            intento.canceladas += max(int(o.cxlqty), 0)
            acciones += self._avanzar_intento(pos)
        continuacion = self._continuacion.pop(o.token, None)
        if continuacion is not None and pos is not None:
            tipo, datos = continuacion
            lote = pos.lotes.get(str(datos.get("lote_id")))
            if lote is not None and tipo == T_TP_CRUCE:
                acciones += self._tp_resto(pos, lote, o)
            elif lote is not None and tipo == T_HORA_ASK:
                acciones += self._hora_al_ask(pos, lote, _proposito(datos.get("proposito"), Proposito.HORA_ASK))
        return acciones

    def _stop_cancelado_sin_pedir(self, o: Orden) -> list[Accion]:
        """F2.6 / R-C-04: DAS canceló un stop que no pedimos cancelar → aviso 2 y plan inmediato (en BS no se repone)."""
        pos = self._pos(o.ticker)
        acciones: list[Accion] = [
            Anotar("stop_cancelado_por_das", {"ticker": o.ticker, "token": o.token, "id_das": o.id_das,
                                              "proposito": o.proposito.value, "regla": "R-C-04"}),
            Avisar(Nivel.AVISO, Grupo.B,
                   f"DAS canceló el stop {o.proposito.value} de {avisos.escapar_html(o.ticker)} (token {o.token}) sin "
                   f"que el bot lo pidiera; " + ("en cisne negro NO se repone (R-G-03)" if pos.estado is EstadoTicker.BS
                                                 else "se repone al momento (R-C-04)"),
                   clave=f"stop_cancelado:{o.ticker}:{o.token}")]
        if pos.estado is not EstadoTicker.BS:
            acciones += self._plan(o.ticker)
        return acciones

    # ═══════════════════════════ plan de stops ═════════════════════════════
    def _plan(self, ticker: str) -> list[Accion]:
        """F2.1: `stops.plan` sobre las órdenes del episodio (en BS, `cisne_negro.acciones_durante_bs`).

        No toca nada con el ticker en control manual (/cancelar_ordenes), con un
        cierre humano en curso (/cerrar, /cerrar_todo) ni durante la separación
        de R-C-03 tras un stop rechazado (lo repone `stop_reintento`, con su
        cuenta de intentos: sin esa pausa el barrido lo reenviaría cada segundo).
        """
        pos = self._estado.posiciones.get(ticker)
        if (pos is None or ticker in self._manual or ticker in self._cierre_humano
                or self._stop_bloqueo.get(ticker, -math.inf) > self._ahora):
            return []
        vivas = self._ordenes_ticker(ticker)
        if pos.estado is EstadoTicker.BS:
            acciones = cisne_negro.acciones_durante_bs(pos, vivas, self._cfg, pos.version_stops)
        else:
            acciones = stops.plan(pos, vivas, self._cfg.stops, self._limit_up(ticker), self._tokens.siguiente,
                                  self._ahora_et, self._ruta_stop(), pos.version_stops)
        acciones = self._absorber(acciones)
        if not acciones:
            return []
        return [Anotar("stop_plan", {"ticker": ticker, "version": pos.version_stops, "neta": pos.neta,
                                     "neta_das": pos.neta_das, "acciones": len(acciones)})] + acciones

    # ═══════════════════════════ señales ═══════════════════════════════════
    def _senal(self, s: Senal) -> list[Accion]:
        if not isinstance(s, Senal):
            return [Anotar("senal_invalida", {"tipo": type(s).__name__})]
        if s.clase == "evento":
            return self._senal_evento(s)
        if s.clase == "radar":
            return self._proteger(s.ticker, "radar", lambda: self._senal_radar(s))
        if s.clase == "hidratado":
            return self._proteger(None, "hidratado", lambda: self._senal_hidratado(s))
        if s.clase == "latido_feed":
            return self._proteger(None, "latido_feed", lambda: self._latido_feed(s))
        if s.clase == "dia_nuevo":
            return [Anotar("dia_nuevo_fuente", {"origen": s.origen})]
        return [Anotar("senal_desconocida", {"clase": s.clase, "ticker": s.ticker})]

    def _senal_evento(self, s: Senal) -> list[Accion]:
        """F1.1-F1.2: prealerta → solo grupo A; repetida → solo diario; si no, grupo A PRIMERO y después la rama del ticker."""
        ev = s.evento
        ticker = s.ticker
        if ev is None or not isinstance(s.id, str) or not s.id or not isinstance(ticker, str) or not ticker:
            return [Anotar("senal_invalida", {"senal_id": s.id, "ticker": ticker, "motivo": "sin evento, id o ticker"})]
        estado_ev = str(getattr(ev, "estado", "alerta") or "alerta").strip().lower()
        if estado_ev == "prealerta":
            return self._proteger(None, "grupo_a", lambda: self._grupo_a(s, prealerta=True))
        if s.id in self._estado.senales_vistas:
            return [Anotar("senal_repetida", {"senal_id": s.id, "ticker": ticker, "origen": s.origen,
                                              "regla": "R-A-05"})]
        acciones = self._proteger(None, "grupo_a", lambda: self._grupo_a(s, prealerta=False))
        acciones += self._proteger(ticker, "senal", lambda: self._rutear_evento(s))
        return acciones

    def _grupo_a(self, s: Senal, prealerta: bool) -> list[Accion]:
        """R-M-05 / F1.1: `Avisar(1, A, texto_grupo_a([evento]))` INMEDIATO, antes de cualquier guarda (el socio recibe lo de hoy)."""
        bloque = self._cfg.alertas_grupo_a or {}
        if not bloque.get("activo"):
            return []
        ev = s.evento
        e = self._estrategia(getattr(ev, "strategy_id", None))
        if e is None or not e.avisar_grupo_a:
            return []
        if prealerta:
            freno = float(bloque.get("prealerta_freno_min") or 0) * 60.0
            clave = (str(s.ticker), e.strategy_id)
            ultimo = self._prealerta_en.get(clave)
            if ultimo is not None and self._ahora - ultimo < freno:
                return []
            self._prealerta_en[clave] = self._ahora
        marca = "prealerta" if prealerta else "alerta"
        return [Avisar(Nivel.INFO, Grupo.A, texto, clave=f"grupo_a:{marca}:{s.id}:{i}")
                for i, texto in enumerate(avisos.texto_grupo_a([ev]))]

    def _rutear_evento(self, s: Senal) -> list[Accion]:
        tipo = _tipo_evento(s.evento)
        if tipo == "entrada" or entrada.es_piramide_add(s.evento):
            return self._entrada(s)
        if tipo == "salida" or entrada.es_piramide_reduce(s.evento):
            return self._salida_motor(s)
        self._estado.senales_vistas.add(s.id)
        return [Anotar("senal_descartada", {"senal_id": s.id, "ticker": s.ticker,
                                            "motivo": f"tipo de evento no operable: {tipo!r}"})]

    # ── entrada (F1, F3) ────────────────────────────────────────────────
    def _entrada(self, s: Senal, *, es_reapertura: bool = False, t_cierre: Optional[float] = None) -> list[Accion]:
        """F1 (R-B-01 v3, R-A-01, R-I-04, R-C-09, R-H-04, R-I-01, R-E-02): guardas, tamaño, lote y orden de agregar.

        R-D-07: con una salida viva en el ticker la entrada ESPERA
        («tp_espera_entrada»); R-F-03: tras stop + halt no se reentra hasta una
        reapertura válida. `evaluar_senal` recibe la exclusión ya calculada
        (ajuste (b)); el tamaño es min(señal, locates de E9, capital) y el
        margen se RESERVA (R-E-02). Con un intento vivo la señal se SUMA (F3).
        """
        estado = self._estado
        cfg = self._cfg
        ev = s.evento
        ticker = s.ticker
        if s.id in estado.senales_vistas:
            return [Anotar("senal_repetida", {"senal_id": s.id, "ticker": ticker, "regla": "R-A-05"})]
        pos = self._pos(ticker)
        if not es_reapertura and self._salidas_vivas(ticker):
            return self._retener_entrada(s)
        if (ticker not in self._halt_en_curso and ticker in self._halt_hoy and ticker in self._stop_hoy
                and ticker not in self._reapertura_ok):
            return self._descartar(s, "R-F-03: stop y halt en el ticker; sin reentrada hasta una reapertura válida",
                                   avisar=True)
        e = self._estrategia(getattr(ev, "strategy_id", None))
        acciones: list[Accion] = []
        exclusion: Optional[str] = None
        if e is not None and self._exclusion_necesaria(pos, e, ev):
            exclusion, avisos_ex = self._exclusion(ticker, e)
            acciones += avisos_ex
        cot = self._cot(ticker)
        simb = self._mercado.simbolo(ticker)
        ver = entrada.evaluar_senal(estado, cfg, s, cot, simb, exclusion, self._franja(), self._ahora,
                                    self._ahora_et, self._diario_roto(), es_reapertura=es_reapertura)
        if not ver.ok:
            if ver.guardar_para_reapertura:
                pos.senal_guardada_halt = s
                return acciones + [Anotar("senal_guardada", {"senal_id": s.id, "ticker": ticker, "motivo": ver.motivo,
                                                             "regla": "R-F-04 (b)"})]
            return acciones + self._descartar(s, ver.motivo, avisar=ver.avisar)
        if e is None or cot is None or cot.ask is None:
            raise RuntimeError("evaluar_senal aceptó una señal sin estrategia o sin libro")   # comprobaciones 3 y 8
        precio_senal = precios.de_float(ev.precio)
        pedidas = entrada.qty_de_evento(getattr(ev, "acciones", None))
        reparto = locates.asignar_a_lote(estado.locates, ticker, pedidas, e.strategy_id)
        locates_libres = sum(n for _, n in reparto)
        tasa = simb.tasa_corta
        try:
            exposicion = capital.exposicion_corta(estado.posiciones, self._cot)
            capital_qty, motivo_capital = capital.acciones_que_caben(
                pedidas, cot.ask, estado.cuenta, tasa, exposicion, _ALTO_RIESGO, self._ahora, self._max_edad_bp())
        except ValueError as exc:
            capital_qty, motivo_capital = 0, f"capital no calculable: {exc}"
        fraccion_max = cfg.entrada.get("fraccion_max_volumen_acum")
        qty, fraccion = entrada.qty_final(pedidas, locates_libres, capital_qty,
                                          precios.de_float(fraccion_max) if fraccion_max is not None else None,
                                          cot.volumen)
        if qty <= 0:
            motivo = (f"sin locates libres (R-H-04): {locates_libres}" if locates_libres <= 0
                      else f"capital (R-I-01): {motivo_capital}")
            return acciones + self._descartar(s, motivo, avisar=True)
        lote = self._nuevo_lote(s, e, qty, pos)
        estado.senales_vistas.add(s.id)
        pos.lotes[lote.id] = lote
        acciones.append(Anotar("senal", {"senal_id": s.id, "ticker": ticker, "strategy_id": e.strategy_id,
                                         "tipo": _tipo_evento(ev), "precio": precio_senal, "acciones_evento": pedidas,
                                         "qty": qty, "locates": reparto, "capital": motivo_capital,
                                         "recuperada": s.recuperada, "origen": s.origen,
                                         "reapertura": es_reapertura}))
        acciones.append(self._anotar_lote(lote))
        acciones += self._usar_locates(ticker, lote.id, reparto, qty)
        acciones.append(Anotar("metrica", {"nombre": "fraccion_volumen", "ticker": ticker, "senal_id": s.id,
                                           "valor": fraccion, "volumen": cot.volumen, "regla": "R-B-05"}))
        capital.reservar(estado.cuenta, capital.margen_inicial_corto(cot.ask, qty, tasa))
        intento_vivo = pos.intento is not None and pos.intento.fase is not FaseIntento.TERMINADO
        if intento_vivo:
            acciones += self._sumar_a_intento(pos, lote)
        else:
            cierre = t_cierre if t_cierre is not None else entrada.t_cierre_vela(
                s.momento if s.momento is not None else getattr(ev, "momento", None))
            intento = entrada.abrir_intento(pos, [lote], cot, precio_senal, cierre, cfg, self._ahora)
            pos.intento = intento
            self._tokens_intento[ticker] = set()
            acciones.append(Anotar("intento", {"ticker": ticker, "lotes": list(intento.lotes),
                                               "qty_total": intento.qty_total, "bid_senal": intento.bid_senal,
                                               "ask_senal": intento.ask_senal, "t_limite": intento.t_limite,
                                               "fase": intento.fase.value, "regla": "R-B-01 v3"}))
            acciones += self._enviar_agregar(pos)
            if pos.intento is intento:
                acciones.append(Programar(f"{T_CRUCE}:{ticker}", entrada.segundos_hasta_limite(intento, self._ahora_et),
                                          {"ticker": ticker}))
        acciones += self._armar_simstatus()
        acciones.append(Anotar("metrica", {"nombre": "senal_a_orden_ms", "ticker": ticker, "senal_id": s.id,
                                           "valor": max(0.0, (self._ahora - float(s.recibida_en)) * 1000.0),
                                           "grupo_a": bool((cfg.alertas_grupo_a or {}).get("activo")
                                                           and e.avisar_grupo_a),
                                           "regla": "R-M-05"}))
        return acciones

    def _exclusion_necesaria(self, pos: PosicionTicker, e: EstrategiaConfig, ev: Any) -> bool:
        """La exclusión (que puede abrir red) solo se calcula si las comprobaciones 1-5 de `evaluar_senal` no bastan ya."""
        estado = self._estado
        if (not estado.vigilando or not self._cfg.vigilando or estado.pausa_global or estado.control_humano
                or self._cfg.pausar_entradas):
            return False
        if not e.ejecutar or getattr(ev, "cuenta", None) is not None:
            return False
        return pos.estado in (EstadoTicker.NORMAL, EstadoTicker.HALT)

    def _exclusion(self, ticker: str, e: EstrategiaConfig) -> tuple[Optional[str], list[Accion]]:
        """R-A-03 v2 (ajuste (b)): `exclusiones.excluida` con la ficha y los splits de Massive; sin lista → no excluye + aviso."""
        acciones: list[Accion] = []
        ficha = self._ficha(ticker)
        splits = self._splits_hoy()
        if splits is None and self._una_vez_al_dia("splits_sin_lista"):
            acciones.append(Avisar(Nivel.AVISO, Grupo.B,
                                   "No se pudo leer la lista de splits de hoy en Massive: NO se excluye por split "
                                   "hasta tenerla (corrección 17)", clave="splits_sin_lista"))
            acciones.append(Anotar("referencia", {"splits": None, "regla": "corrección 17"}))
        motivo = exclusiones.excluida(ticker, e, ficha, splits, list(self._cfg.lista_negra), self._estado.dia,
                                      dict(self._cfg.exclusiones))
        return motivo, acciones

    def _ficha(self, ticker: str) -> Any:
        if self._referencia is None:
            return None
        simbolo = str(ticker).strip().upper()
        fallo = self._ficha_fallo_en.get(simbolo)
        if fallo is not None and self._ahora - fallo < REFERENCIA_REINTENTO_S:
            return None
        try:
            ficha = self._referencia.ficha(simbolo)
        except Exception:  # noqa: BLE001 — frontera de red: la referencia no debe lanzar; si lo hace, sin ficha (A12: no se opera)
            ficha = None
        if ficha is None:
            self._ficha_fallo_en[simbolo] = self._ahora
        else:
            self._ficha_fallo_en.pop(simbolo, None)
        return ficha

    def _splits_hoy(self) -> Optional[set[str]]:
        dia = self._estado.dia
        if self._splits is not None and self._splits[0] == dia:
            return set(self._splits[1])
        if self._referencia is None:
            return None
        if self._splits_fallo_en is not None and self._ahora - self._splits_fallo_en < REFERENCIA_REINTENTO_S:
            return None
        try:
            splits = self._referencia.splits_de_hoy(dia)
        except Exception:  # noqa: BLE001 — frontera de red: sin lista de splits no se excluye y se avisa (corrección 17)
            splits = None
        if splits is None:
            self._splits_fallo_en = self._ahora
            return None
        self._splits_fallo_en = None
        self._splits = (dia, set(splits))
        return set(splits)

    def _max_edad_bp(self) -> float:
        valor = self._cfg.tecnicos.get("reconciliacion_fallida_s")
        try:
            return float(valor) if valor is not None else float(RECONCILIACION_CADUCA_S)
        except (TypeError, ValueError):
            return float(RECONCILIACION_CADUCA_S)

    def _nuevo_lote(self, s: Senal, e: EstrategiaConfig, qty: int, pos: PosicionTicker) -> Lote:
        """El lote de la señal: id = id del evento, nivel L del motor, horas de salida del día (media sesión: 13:00)."""
        ev = s.evento
        piramide = entrada.es_piramide_add(ev)
        nivel = entrada.nivel_de_senal(self._estado, ev)
        riesgo = getattr(ev, "riesgo_usd", None)
        try:
            riesgo_usd = precios.de_float(riesgo) if riesgo is not None else e.riesgo_usd
        except ValueError:
            riesgo_usd = e.riesgo_usd
        dia = self._estado.dia
        cierre = datetime(dia.year, dia.month, dia.day, 13, 0, tzinfo=ET) if self._media_sesion(dia) else None
        salida, eod = salidas.horas_de_salida(e, dia, cierre)
        previas = 0 if piramide else sum(
            1 for lote in pos.lotes.values()
            if lote.strategy_id == e.strategy_id and lote.nivel_piramide is None
            and (lote.estado is not EstadoLote.CANCELADO or lote.llenas > 0))
        nivel_piramide = getattr(ev, "nivel", None) if piramide else None
        entrada_idx = getattr(ev, "entrada_idx", None)
        return Lote(
            id=s.id, strategy_id=e.strategy_id, estrategia=e.name, ticker=s.ticker,
            direccion=str(getattr(ev, "direccion", "") or ""), pedidas=qty, nivel_stop=nivel,
            riesgo_usd=riesgo_usd, estado=EstadoLote.ABRIENDO, reentrada_n=previas,
            entrada_idx=int(entrada_idx) if isinstance(entrada_idx, int) and not isinstance(entrada_idx, bool) else None,
            nivel_piramide=int(nivel_piramide) if isinstance(nivel_piramide, int) and not isinstance(nivel_piramide, bool)
            else None,
            hora_salida=salida.strftime("%H:%M:%S") if salida is not None else None,
            eod=eod.strftime("%H:%M:%S"), version_estrategia=e.definition_hash)

    def _usar_locates(self, ticker: str, lote_id: str, reparto: list[tuple[str, int]], qty: int) -> list[Accion]:
        """E9: se cargan al lote las acciones localizadas que usa, primero las de su estrategia (ETB no descuenta)."""
        restante = qty
        cargos: list[tuple[str, int]] = []
        acciones: list[Accion] = []
        for sid, n in reparto:
            if restante <= 0:
                break
            usar = min(n, restante)
            restante -= usar
            loc = self._estado.locates.get((ticker, sid))
            if loc is None or loc.estado == locates.ESTADO_NO_HACE_FALTA or usar <= 0:
                continue
            loc.usadas += usar
            cargos.append((sid, usar))
            acciones.append(Anotar(locates.ANOTACION_ESTADO, {"ticker": ticker, "strategy_id": sid, "usadas": loc.usadas,
                                                              "lote_id": lote_id, "motivo": "asignado al lote (E9)"}))
        self._locates_de_lote[lote_id] = cargos
        return acciones

    def _devolver_locates(self, lote: Lote) -> list[Accion]:
        """Al cerrar el intento, las acciones localizadas que el lote no llegó a usar vuelven a estar libres."""
        cargos = self._locates_de_lote.pop(lote.id, [])
        sobran = max(lote.pedidas - lote.llenas, 0)
        acciones: list[Accion] = []
        for sid, n in reversed(cargos):
            if sobran <= 0:
                break
            devolver = min(n, sobran)
            sobran -= devolver
            loc = self._estado.locates.get((lote.ticker, sid))
            if loc is None:
                continue
            loc.usadas = max(loc.usadas - devolver, 0)
            acciones.append(Anotar(locates.ANOTACION_ESTADO, {"ticker": lote.ticker, "strategy_id": sid,
                                                              "usadas": loc.usadas, "lote_id": lote.id,
                                                              "motivo": "devueltas al cerrar el intento"}))
        return acciones

    def _descartar(self, s: Senal, motivo: str, *, avisar: bool) -> list[Accion]:
        self._estado.senales_vistas.add(s.id)
        ev = s.evento
        acciones: list[Accion] = [Anotar("senal_descartada", {"senal_id": s.id, "ticker": s.ticker,
                                                              "strategy_id": getattr(ev, "strategy_id", None),
                                                              "tipo": _tipo_evento(ev), "motivo": motivo})]
        if avisar:
            nombre = getattr(ev, "estrategia", None) or getattr(ev, "strategy_id", "?")
            acciones.append(Avisar(Nivel.INFO, Grupo.B,
                                   f"{avisos.escapar_html(s.ticker)} · {avisos.escapar_html(nombre)}: señal descartada — "
                                   f"{avisos.escapar_html(motivo)}", clave=f"descartada:{s.id}"))
        return acciones

    def _retener_entrada(self, s: Senal) -> list[Accion]:
        """R-D-07: una entrada que llega con una salida viva en el ticker espera a que la salida termine."""
        lista = self._entradas_en_espera.setdefault(s.ticker, [])
        if all(x.id != s.id for x in lista):
            lista.append(s)
        return [Anotar("senal_en_espera", {"senal_id": s.id, "ticker": s.ticker,
                                           "motivo": "R-D-07: salida viva en el ticker; la entrada espera"}),
                Programar(f"{T_TP_ESPERA_ENTRADA}:{s.ticker}", TP_ESPERA_ENTRADA_S, {"ticker": s.ticker})]

    def _anotar_lote(self, lote: Lote) -> Anotar:
        return Anotar("lote", {
            "lote_id": lote.id, "ticker": lote.ticker, "strategy_id": lote.strategy_id, "estrategia": lote.estrategia,
            "direccion": lote.direccion, "pedidas": lote.pedidas, "llenas": lote.llenas,
            "precio_medio": lote.precio_medio, "nivel_stop": lote.nivel_stop, "riesgo_usd": lote.riesgo_usd,
            "estado": lote.estado.value, "reentrada_n": lote.reentrada_n, "entrada_idx": lote.entrada_idx,
            "nivel_piramide": lote.nivel_piramide, "hora_salida": lote.hora_salida, "eod": lote.eod,
            "principal_consumido": lote.principal_consumido, "version_estrategia": lote.version_estrategia})

    # ── máquina del intento (R-B-01 v3, R-B-02, R-B-03) ─────────────────
    def _sumar_a_intento(self, pos: PosicionTicker, lote: Lote) -> list[Accion]:
        """F3 / R-B-03: la segunda señal se SUMA; con orden viva se cancela y, confirmado el Canceled, se reinicia con el total."""
        intento = pos.intento
        if intento is None:
            raise RuntimeError(f"{pos.ticker}: sumar a un intento que no existe")
        ticker = pos.ticker
        token_vivo = (intento.token_agregar if intento.fase is FaseIntento.AGREGANDO
                      else intento.token_cruce if intento.fase is FaseIntento.CRUZANDO else None)
        orden_viva = self._estado.ordenes.get(token_vivo) if token_vivo is not None else None
        id_viva = orden_viva.id_das if orden_viva is not None else None
        nuevo, cancelaciones = entrada.sumar_senal(intento, lote, id_das_viva=id_viva)
        pos.intento = nuevo
        acciones: list[Accion] = [Anotar("intento", {"ticker": ticker, "lotes": list(nuevo.lotes),
                                                     "qty_total": nuevo.qty_total, "fase": nuevo.fase.value,
                                                     "suma": lote.id, "regla": "R-B-03"})]
        if nuevo.fase is FaseIntento.CANCELANDO and intento.fase is not FaseIntento.CANCELANDO:
            self._poner_motivo(ticker, MOTIVO_SUMA)
            if token_vivo is not None and id_viva is None:
                self._cancelar_al_aceptar[token_vivo] = entrada.MOTIVO_CANCELAR_SUMA
            acciones += self._absorber(cancelaciones)
            acciones.append(Programar(f"{T_CANCEL_ESPERA}:{ticker}", CANCEL_ESPERA_S, {"ticker": ticker, "n": 0}))
        elif nuevo.fase is FaseIntento.CANCELANDO:
            self._poner_motivo(ticker, MOTIVO_SUMA)
        return acciones

    def _enviar_agregar(self, pos: PosicionTicker) -> list[Accion]:
        """F1.4: SS de lo pendiente en el punto medio redondeado arriba, PostOnly, ruta «agregar» (`entrada.orden_agregar`)."""
        intento = pos.intento
        if intento is None:
            return []
        bloqueo = self._bloqueo_apertura(pos.ticker)
        if bloqueo is not None:
            self._poner_motivo(pos.ticker, MOTIVO_BLOQUEO)
            return self._cerrar_intento(pos, f"{_TEXTO_MOTIVO_CIERRE[MOTIVO_BLOQUEO]} ({bloqueo})")
        cot = self._cot(pos.ticker)
        if not _libro_utilizable(cot):
            return self._cerrar_intento(pos, entrada.MOTIVO_FIN_SIN_COTIZACION)
        token = self._tokens.siguiente()
        orden = entrada.orden_agregar(intento, cot, self._cfg, token, self._ahora_et, nivel=self._nivel_intento(pos))
        intento.fase = FaseIntento.AGREGANDO
        intento.token_agregar = token
        self._tokens_intento.setdefault(pos.ticker, set()).add(token)
        self._lotes_de_orden[token] = list(intento.lotes)
        return self._absorber([EnviarOrden(orden)])

    def _enviar_cruce(self, pos: PosicionTicker) -> list[Accion]:
        """F1.7: SS del resto CONFIRMADO a bid·(1 − 0,5 %) por «cruzar», solo si el bid no cayó > 3 % (`entrada.orden_cruce`)."""
        intento = pos.intento
        if intento is None:
            return []
        ticker = pos.ticker
        resto = entrada.resto_a_cruzar(intento)
        if resto <= 0:
            return self._cerrar_intento(pos, entrada.MOTIVO_FIN_LLENA)
        bloqueo = self._bloqueo_apertura(ticker)
        if bloqueo is not None:
            return self._cerrar_intento(pos, f"{_TEXTO_MOTIVO_CIERRE[MOTIVO_BLOQUEO]} ({bloqueo})")
        intento.fase = FaseIntento.CRUZANDO
        token = self._tokens.siguiente()
        orden = entrada.orden_cruce(intento, resto, self._cot(ticker), self._cfg, token, self._ahora_et,
                                    nivel=self._nivel_intento(pos), ssr=bool(self._mercado.simbolo(ticker).ssr))
        if orden is None:
            return self._cerrar_intento(pos, entrada.MOTIVO_FIN_BID_CAYO)
        intento.token_cruce = token
        self._tokens_intento.setdefault(ticker, set()).add(token)
        self._lotes_de_orden[token] = list(intento.lotes)
        espera = _segundos(intento.cfg_congelada or self._cfg.entrada, "cruce_espera_s", 2.0)
        return self._absorber([EnviarOrden(orden)]) + [
            Programar(f"{T_CRUCE_ESPERA}:{ticker}", espera, {"ticker": ticker})]

    def _nivel_intento(self, pos: PosicionTicker) -> Optional[Decimal]:
        intento = pos.intento
        if intento is None or not intento.lotes:
            return None
        lote = pos.lotes.get(intento.lotes[0])
        return lote.nivel_stop if lote is not None else None

    def _bloqueo_apertura(self, ticker: str) -> Optional[str]:
        """Lo que impide mandar una orden que ABRE posición en este momento (corrección 4, R-J-03, R-M-03, R-B-07)."""
        estado = self._estado
        if self._diario_roto():
            return "diario degradado"
        if estado.modo_degradado:
            return "modo degradado: " + ", ".join(sorted(estado.modo_degradado))
        if not self._vigilando_efectivo() or estado.control_humano:
            return "bot apagado o en control humano"
        if estado.pausa_global or self._cfg.pausar_entradas:
            return "pausa global"
        pos = estado.posiciones.get(ticker)
        if pos is not None and pos.estado is not EstadoTicker.NORMAL:
            return f"ticker en {pos.estado.value}"
        if ticker in self._manual:
            return "ticker en control manual"
        return None

    def _cancelar_intento(self, pos: PosicionTicker, motivo: str) -> list[Accion]:
        """Cancela la orden viva del intento por `motivo`; el siguiente paso sale SOLO del Canceled cuadrado (§8.7)."""
        intento = pos.intento
        if intento is None:
            return []
        ticker = pos.ticker
        self._poner_motivo(ticker, motivo)
        self._soltar_cuadrados(intento)
        acciones: list[Accion] = []
        vivos = False
        for token in (intento.token_agregar, intento.token_cruce):
            o = self._estado.ordenes.get(token) if token is not None else None
            if o is None:
                continue
            vivos = True
            acciones += self._cancelar_orden(o, f"{motivo}: se cancela la entrada viva de {ticker}")
        if not vivos:
            return acciones + self._avanzar_intento(pos)
        intento.fase = FaseIntento.CANCELANDO
        acciones.append(Programar(f"{T_CANCEL_ESPERA}:{ticker}", CANCEL_ESPERA_S, {"ticker": ticker, "n": 0}))
        return acciones

    def _avanzar_intento(self, pos: PosicionTicker) -> list[Accion]:
        """Con ningún token vivo, el siguiente paso del intento según por qué se canceló (R-B-01 v3, R-B-02, R-B-03, R-D-07)."""
        intento = pos.intento
        if intento is None or intento.token_agregar is not None or intento.token_cruce is not None:
            return []
        ticker = pos.ticker
        if ticker in self._intento_en_reintento:
            return []
        motivo = self._motivo_cancel.pop(ticker, None)
        if intento.qty_total - intento.llenas <= 0:
            return self._cerrar_intento(pos, entrada.MOTIVO_FIN_LLENA)
        if motivo in _TEXTO_MOTIVO_CIERRE:
            return self._cerrar_intento(pos, _TEXTO_MOTIVO_CIERRE[motivo])
        if motivo == MOTIVO_PRIORIDAD:
            self._intento_pausado.add(ticker)
            intento.fase = FaseIntento.AGREGANDO
            return [Anotar("intento", {"ticker": ticker, "fase": "pausado", "motivo": "R-D-07: el TP va primero"}),
                    Programar(f"{T_TP_ESPERA_ENTRADA}:{ticker}", TP_ESPERA_ENTRADA_S, {"ticker": ticker})]
        if ticker in self._intento_pausado:
            return []
        bloqueo = self._bloqueo_apertura(ticker)
        if bloqueo is not None:
            return self._cerrar_intento(pos, f"{_TEXTO_MOTIVO_CIERRE[MOTIVO_BLOQUEO]} ({bloqueo})")
        # la espera de la cancelación ya se resolvió: su temporizador no debe tocar la orden NUEVA
        sin_espera: list[Accion] = [Desprogramar(f"{T_CANCEL_ESPERA}:{ticker}")]
        if motivo == MOTIVO_CRUCE_ESPERA or (motivo is None and intento.fase is FaseIntento.CRUZANDO):
            if intento.reintento_cruce == 0:
                intento.reintento_cruce = 1
                return sin_espera + self._enviar_cruce(pos)
            return self._cerrar_intento(pos, "R-B-01 v3: el cruce no llenó tras el reintento; se queda lo llenado (R-B-02)")
        if self._ahora_et.timestamp() < intento.t_limite:
            intento.fase = FaseIntento.AGREGANDO
            return sin_espera + self._enviar_agregar(pos)
        fase, fin = entrada.al_vencer(intento, self._cot(ticker), self._cfg)
        if fase is FaseIntento.CRUZANDO:
            return sin_espera + self._enviar_cruce(pos)
        return self._cerrar_intento(pos, fin or entrada.MOTIVO_FIN_LLENA)

    def _cerrar_intento(self, pos: PosicionTicker, motivo: str) -> list[Accion]:
        """F1.9 / R-B-02: el intento termina con lo llenado; aviso del fill, temporizadores de salida y plan final."""
        intento = pos.intento
        if intento is None:
            return []
        ticker = pos.ticker
        acciones: list[Accion] = []
        for token in (intento.token_agregar, intento.token_cruce):
            o = self._estado.ordenes.get(token) if token is not None else None
            if o is not None and o.estado in _VIVOS:
                acciones += self._cancelar_orden(o, f"fin del intento de {ticker}: {motivo}")
        intento.fase = FaseIntento.TERMINADO
        intento.motivo_fin = motivo
        lotes = [pos.lotes[i] for i in intento.lotes if i in pos.lotes]
        cerrados = entrada.cerrar_intento(intento, lotes)
        for lote in cerrados:
            pos.lotes[lote.id] = lote
            acciones.append(self._anotar_lote(lote))
            acciones += self._devolver_locates(lote)
        abiertos = [lote for lote in cerrados if lote.estado is EstadoLote.ABIERTO and lote.llenas > 0]
        acciones.append(Anotar("intento_fin", {"ticker": ticker, "motivo": motivo, "qty_total": intento.qty_total,
                                               "llenas": intento.llenas, "lotes": list(intento.lotes),
                                               "precio_senal": intento.precio_senal}))
        if intento.llenas <= 0:
            acciones.append(Avisar(Nivel.INFO, Grupo.B, f"{avisos.escapar_html(ticker)}: entrada terminada sin fills — "
                                                        f"{avisos.escapar_html(motivo)}",
                                   clave=f"entrada_fin:{intento.lotes[0]}"))
        ruta = self._ruta_ultimo_fill(intento)
        for lote in abiertos:
            acciones += self._temporizadores_lote(lote)
            resumen = Fill(id_trade=0, token=None, id_orden=None, ticker=ticker, lado=Lado.CORTO.value, qty=lote.llenas,
                           precio=lote.precio_medio, ruta=ruta, hora=self._hora_texto(), liq=None, ecn_fee=None)
            acciones.append(Avisar(Nivel.INFO, Grupo.B, avisos.texto_fill(lote, resumen, self._cfg, self._estado.fase),
                                   clave=f"fill:{lote.id}"))
        if abiertos:
            llenas = sum(lote.llenas for lote in abiertos)
            medio = sum((lote.precio_medio * lote.llenas for lote in abiertos), Decimal("0")) / llenas
            acciones.append(Anotar("metrica", {"nombre": "slippage_entrada", "ticker": ticker,
                                               "precio_senal": intento.precio_senal, "precio_medio": medio,
                                               "bps": (medio - intento.precio_senal) / intento.precio_senal * 10000,
                                               "regla": "F1.9"}))
        acciones += [Desprogramar(f"{T_CRUCE}:{ticker}"), Desprogramar(f"{T_CANCEL_ESPERA}:{ticker}"),
                     Desprogramar(f"{T_CRUCE_ESPERA}:{ticker}")]
        pos.intento = None
        self._motivo_cancel.pop(ticker, None)
        self._intento_pausado.discard(ticker)
        self._intento_en_reintento.discard(ticker)
        self._tokens_intento.pop(ticker, None)
        acciones.append(Programar(T_BARRIDO, 0.0, {"motivo": "fin de intento"}))
        acciones += self._plan(ticker)
        return acciones

    def _soltar_cuadrados(self, intento: Any) -> None:
        """Suelta los tokens del intento cuyas órdenes ya están cuadradas (o ya no existen) sin que nadie lo hiciera."""
        for campo in ("token_agregar", "token_cruce"):
            token = getattr(intento, campo)
            if token is None:
                continue
            o = self._estado.ordenes.get(token)
            if o is None or self._cuadrada(o):
                setattr(intento, campo, None)
                if o is not None:
                    intento.canceladas += max(int(o.cxlqty), 0)

    def _ruta_ultimo_fill(self, intento: Any) -> str:
        for token in sorted(self._tokens_intento.get(intento.ticker, set()), reverse=True):
            for fill in reversed(self._estado.fills.get(token, [])):
                return fill.ruta
        return "—"

    def _temporizadores_lote(self, lote: Lote) -> list[Accion]:
        """F5 / R-D-08 / R-D-02: los tres temporizadores de salida del lote (con las horas con las que NACIÓ, R-E-03)."""
        e = self._estrategia(lote.strategy_id) or self._cfg_base.estrategias.get(lote.strategy_id)
        if e is None:
            return [Avisar(Nivel.AVISO, Grupo.B, f"{avisos.escapar_html(lote.ticker)}: el lote {avisos.escapar_html(lote.id)} "
                                                 f"no tiene estrategia en la config; sin salida por hora (vigilar a mano)",
                           clave=f"lote_sin_estrategia:{lote.id}")]
        return list(salidas.temporizadores_lote(lote, e, self._estado.dia, self._cfg.salidas, self._ahora_et))

    # ── salida del motor (F4) ───────────────────────────────────────────
    def _salida_motor(self, s: Senal) -> list[Accion]:
        """F4 (R-D-03 v2, R-D-07, R-C-07): el `Evento` de salida o de pirámide «reduce» → tratamiento de `salidas`.

        TP / como TP: `tp_parcial` (agregar 60 s en el punto medio) y
        `tp_cruce`; con un intento de entrada vivo en el ticker, el TP va
        PRIMERO al ask sin techo y la entrada espera (R-D-07). Hora y EOD solo
        se anotan (manda el reloj del ejecutor); el SL del motor con la
        posición abierta es una divergencia (no se persigue). En cisne negro,
        halt o control manual no se manda nada.
        """
        ev = s.evento
        ticker = s.ticker
        estado = self._estado
        estado.senales_vistas.add(s.id)
        acciones: list[Accion] = [Anotar("senal", {"senal_id": s.id, "ticker": ticker,
                                                   "strategy_id": getattr(ev, "strategy_id", None),
                                                   "tipo": _tipo_evento(ev), "motivo": getattr(ev, "motivo", None),
                                                   "acciones_evento": getattr(ev, "acciones", None),
                                                   "accion_piramide": getattr(ev, "accion_piramide", None),
                                                   "nivel": getattr(ev, "nivel", None),
                                                   "entrada_idx": getattr(ev, "entrada_idx", None)})]
        pos = estado.posiciones.get(ticker)
        if pos is None:
            return acciones + [Anotar("salida_sin_posicion", {"senal_id": s.id, "ticker": ticker})]
        lote = self._lote_de_salida(pos, ev)
        clase = _clase_salida(ev)
        self._refrescar_tp_pendiente(pos)
        vivas = self._vivas(ticker)
        codigo = salidas.tratamiento(clase, pos, lote, vivas, str(self._cfg.salidas.get("salida_motor", "como_tp")))
        for a in salidas.avisos_de_tratamiento(codigo, clase, getattr(ev, "motivo", None), pos, lote):
            if isinstance(a, Avisar) and a.clave and a.clave.startswith("daily_limit:") \
                    and not self._una_vez_al_dia(a.clave):
                continue
            acciones.append(a)
        if codigo not in (salidas.TRATAR_TP, salidas.TRATAR_COMO_TP) or lote is None:
            return acciones
        if pos.estado in (EstadoTicker.BS, EstadoTicker.HALT) or ticker in self._manual or ticker in self._cierre_humano:
            return acciones + [Anotar("salida_omitida", {"senal_id": s.id, "ticker": ticker, "estado": pos.estado.value,
                                                         "motivo": "cisne negro, halt o control manual: no se envía"})]
        libres = self._libres(pos, lote)
        pedidas = entrada.qty_de_evento(getattr(ev, "acciones", None))
        qty = min(pedidas, libres) if pedidas > 0 else libres
        if qty <= 0:
            return acciones + [Anotar("salida_omitida", {"senal_id": s.id, "ticker": ticker,
                                                         "motivo": "el lote no tiene acciones libres"})]
        cot = self._cot(ticker)
        if pos.intento is not None and pos.intento.fase is not FaseIntento.TERMINADO:
            orden = salidas.orden_al_ask(lote, qty, cot, self._cfg, self._tokens.siguiente, self._ahora_et, None,
                                         Proposito.TP_CRUCE)
            acciones += self._absorber([EnviarOrden(orden)])
            acciones.append(Anotar("prioridad_tp", {"ticker": ticker, "lote_id": lote.id, "token": orden.token,
                                                    "qty": qty, "regla": "R-D-07"}))
            acciones += self._cancelar_intento(pos, MOTIVO_PRIORIDAD)
        else:
            orden, programa = salidas.tp_parcial(lote, qty, cot, self._cfg, self._tokens.siguiente, self._ahora_et)
            acciones += self._absorber([EnviarOrden(orden)])
            acciones.append(programa)
        self._refrescar_tp_pendiente(pos)
        return acciones

    def _lote_de_salida(self, pos: PosicionTicker, ev: Any) -> Optional[Lote]:
        """El lote al que se refiere la salida: estrategia + `entrada_idx` (base) o + `nivel` (lote de pirámide)."""
        sid = getattr(ev, "strategy_id", None)
        vivos = [lote for lote in pos.lotes.values()
                 if lote.strategy_id == sid and lote.estado in _LOTE_VIVO and lote.llenas > 0]
        tipo = _tipo_evento(ev)
        accion = str(getattr(ev, "accion_piramide", "") or "").strip().lower()
        nivel = getattr(ev, "nivel", None)
        if tipo == "piramide" and accion in ("lot_stop", "lot_tp") and nivel is not None:
            candidatos = [lote for lote in vivos if lote.nivel_piramide == nivel]
        elif tipo == "piramide":
            candidatos = [lote for lote in vivos if lote.nivel_piramide is None] or vivos
        else:
            idx = getattr(ev, "entrada_idx", None)
            base = [lote for lote in vivos if lote.nivel_piramide is None]
            candidatos = [lote for lote in base if idx is None or lote.entrada_idx is None or lote.entrada_idx == idx]
            candidatos = candidatos or base
        return candidatos[-1] if candidatos else None

    # ── radar, hidratado y latido del feed ─────────────────────────────
    def _senal_radar(self, s: Senal) -> list[Accion]:
        """F9 (R-H-01/05): por cada estrategia de la estimación, el siguiente paso de su locate; y la ficha a la caché."""
        ticker = s.ticker
        if not isinstance(ticker, str) or not ticker:
            return [Anotar("senal_invalida", {"clase": "radar", "motivo": "sin ticker"})]
        self._radar[ticker] = self._ahora
        precio = s.precio_radar
        if isinstance(precio, Decimal) and precio.is_finite() and precio > 0:
            self._radar_precio[ticker] = precio
        self._ficha(ticker)
        filas = [f for f in (s.estimacion or []) if isinstance(f, dict)]
        acciones: list[Accion] = []
        for sid in sorted({str(f.get("strategy_id")) for f in filas if f.get("strategy_id")}):
            e = self._estrategia(sid)
            if e is None or not e.ejecutar:
                continue
            acciones += self._paso_locate(ticker, e, estimacion=filas)
        return acciones

    def _senal_hidratado(self, s: Senal) -> list[Accion]:
        if isinstance(s.ticker, str) and s.ticker:
            self._ficha(s.ticker)
        return []

    def _latido_feed(self, s: Senal) -> list[Accion]:
        """F11 (b): el latido trae el EPOCH de la última vela; se guarda como MONOTÓNICO (lo que mide `_vigilar_feed`)."""
        feed = s.feed if isinstance(s.feed, dict) else {}
        epoch = feed.get("ultima_vela_en")
        if isinstance(epoch, bool) or not isinstance(epoch, (int, float)) or not math.isfinite(epoch):
            return []
        self._estado.feed_ultima_vela_en = self._ahora - (self._ahora_et.timestamp() - float(epoch))
        return []

    # ═══════════════════════════ mensajes de DAS ═══════════════════════════
    def _de_das(self, m: MensajeDAS, simulado: bool) -> list[Accion]:
        ticker = self._ticker_de_msg(m)
        acciones = self._proteger(ticker, type(m).__name__, lambda: self._aplicar_das(m, simulado))
        try:
            foto = self._acumulador.aplicar(m, self._ahora)
        except Exception as exc:  # noqa: BLE001 — H-5: el acumulador no debe lanzar; si lo hace se descarta el volcado
            self._acumulador.descartar()
            return acciones + self._fallo(None, "acumulador", exc)
        if foto is not None:
            acciones += self._proteger(None, "reconciliacion", lambda: self._reconciliar(foto))
        return acciones

    def _ticker_de_msg(self, m: MensajeDAS) -> Optional[str]:
        if isinstance(m, (MsgOrderAct, MsgOrden)):
            token = m.token if m.token in self._estado.ordenes else self._estado.id_a_token.get(m.id)
            o = self._estado.ordenes.get(token) if token is not None else None
            return o.ticker if o is not None else None
        if isinstance(m, MsgTrade):
            token = self._estado.id_a_token.get(m.id_orden)
            o = self._estado.ordenes.get(token) if token is not None else None
            return o.ticker if o is not None else None
        ticker = getattr(m, "ticker", None)
        return ticker if isinstance(ticker, str) and ticker else None

    def _aplicar_das(self, m: MensajeDAS, simulado: bool) -> list[Accion]:
        if isinstance(m, MsgQuote):
            return self._msg_quote(m)
        if isinstance(m, MsgOrderAct):
            return self._msg_orderact(m, simulado)
        if isinstance(m, MsgOrden):
            return self._msg_orden(m)
        if isinstance(m, MsgTrade):
            return self._msg_trade(m, simulado)
        if isinstance(m, MsgPos):
            return self._msg_pos(m)
        if isinstance(m, MsgIssueStatus):
            return self._msg_issue_status(m)
        if isinstance(m, MsgLDLU):
            return self._msg_ldlu(m)
        if isinstance(m, MsgShortInfo):
            self._mercado.aplicar(m)
            return []
        if isinstance(m, MsgBP):
            return self._msg_bp(m)
        if isinstance(m, MsgAccountInfo):
            self._estado.cuenta.equity = m.curr_eq
            self._estado.cuenta.htb_hoy = m.htb
            return []
        if isinstance(m, MsgSLRet):
            return self._msg_slret(m)
        if isinstance(m, MsgSLOrder):
            return self._msg_slorder(m)
        if isinstance(m, MsgSLReuse):
            return self._msg_slreuse(m)
        if isinstance(m, MsgSLMinCharge):
            self._minimo_cargo[m.ruta] = m.minimo
            return [Anotar("locate_minimo", {"ruta": m.ruta, "minimo": m.minimo})]
        if isinstance(m, MsgRouteStatus):
            return self._msg_route(m)
        if isinstance(m, MsgConexion):
            return self._msg_conexion(m)
        if isinstance(m, MsgIntMsg):
            texto = "; ".join(f"{k}={v}" for k, v in sorted(m.campos.items()))[:500]
            return [Anotar("intmsg", {"campos": dict(m.campos)}),
                    Avisar(Nivel.AVISO, Grupo.B, f"Mensaje interno de DAS: {avisos.escapar_html(texto)}",
                           clave=f"intmsg:{hash(texto) & 0xFFFF}")]
        if isinstance(m, MsgDesconocido):
            return [Anotar("das_desconocido", {"palabra": m.palabra, "cruda": m.cruda[:200]})]
        return []

    # ── órdenes y fills ────────────────────────────────────────────────
    def _orden_de(self, token: Optional[int], id_das: Optional[int]) -> Optional[Orden]:
        o = self._estado.ordenes.get(token) if token is not None else None
        if o is None and id_das is not None:
            t = self._estado.id_a_token.get(id_das)
            o = self._estado.ordenes.get(t) if t is not None else None
        return o

    def _casar_id(self, o: Orden, id_das: Optional[int]) -> None:
        if id_das is not None:
            o.id_das = id_das
            self._estado.id_a_token[id_das] = o.token

    def _msg_orderact(self, m: MsgOrderAct, simulado: bool) -> list[Accion]:
        """F1.5 / F1.6 / F8 / injerto §8.7: cada acción de `%OrderAct` sobre NUESTRA orden."""
        o = self._orden_de(m.token, m.id)
        if o is None:
            o = self._adoptar_de_act(m)
            if o is None:
                return []
        self._casar_id(o, m.id)
        o.ultima_act = self._ahora
        accion = str(m.accion).strip()
        datos = {"token": o.token, "id": m.id, "accion": accion, "qty": m.qty, "precio": m.precio, "notas": m.notas,
                 "ticker": o.ticker}
        if accion == "Execute":
            return [Anotar("orden_act", datos)] + self._execute(o, m, simulado)
        acciones: list[Accion] = [Anotar("orden_act", datos)]
        if accion == "Accept":
            paso = False
            if o.estado is EstadoOrden.SENDING:
                o.estado = EstadoOrden.ACCEPTED
            acciones.append(Anotar("metrica", {"nombre": "orden_a_accept_ms", "ticker": o.ticker, "token": o.token,
                                               "valor": max(0.0, (self._ahora - o.enviada_en) * 1000.0),
                                               "regla": "J18"}))
            acciones += self._tras_cambio_orden(o, paso)
        elif accion == "Canceled":
            o.cxlqty = max(o.cxlqty, stops.cantidad_cancelada(m))
            acciones += self._tras_cambio_orden(o, self._transicion(o, EstadoOrden.CANCELED))
        elif accion == "Send_Rej":
            o.notas = m.notas
            self._transicion(o, EstadoOrden.REJECTED)
            if o.token not in self._rechazos_tratados:
                self._rechazos_tratados.add(o.token)
                acciones += self._rechazo(o)
                acciones += self._revisar_cuadre(o)
        elif accion in ("CancelRej", "ReplaceRej"):
            o.notas = m.notas
            if accion == "ReplaceRej":
                self._reemplazo_pedido.pop(o.token, None)
            acciones += self._absorber(rechazos.tras_cancel_o_replace_rej(o, accion))
        elif accion == "Replaced":
            pedido = self._reemplazo_pedido.pop(o.token, None)
            if pedido is not None:
                qty, precio, stop = pedido
                o.qty = o.llenas + qty
                o.lvqty = qty
                if precio is not None:
                    o.precio = precio
                if stop is not None:
                    o.stop = stop
        elif accion == "TimeOut":
            acciones += [Avisar(Nivel.AVISO, Grupo.B, f"DAS no confirmó a tiempo la orden {o.token} de "
                                                      f"{avisos.escapar_html(o.ticker)} (TimeOut): se consulta",
                                clave=f"timeout:{o.token}"),
                         Consultar(rechazos.COMANDO_ORDENES)]
        elif accion == "Close":
            acciones += self._tras_cambio_orden(o, self._transicion(o, EstadoOrden.CLOSED))
        return acciones

    def _adoptar_de_act(self, m: MsgOrderAct) -> Optional[Orden]:
        """Una orden NUESTRA de hoy (p. ej. del vigilante) que el decisor no conocía: se adopta con lo que dice el `%OrderAct`."""
        partes = descomponer(m.token) if m.token is not None else None
        if partes is None or m.token is None or not self._es_token_de_hoy(m.token):
            return None
        lado = {"B": Lado.COMPRA, "S": Lado.VENTA, "SS": Lado.CORTO}.get(str(m.lado).strip().upper())
        if lado is None:
            return None
        o = Orden(token=m.token, ticker=m.ticker, lado=lado, tipo=TipoOrden.LIMITE, qty=max(int(m.qty), 0),
                  precio=m.precio, stop=None, ruta=m.ruta, proposito=Proposito.DESCONOCIDA, lote_id=None, nivel=None,
                  origen=partes[0], estado=EstadoOrden.ACCEPTED, enviada_en=self._ahora, ultima_act=self._ahora)
        self._estado.ordenes[m.token] = o
        return o

    def _es_token_de_hoy(self, token: int) -> bool:
        return es_nuestro(token, self._estado.dia)

    def _execute(self, o: Orden, m: MsgOrderAct, simulado: bool) -> list[Accion]:
        """Corrección 2: un `Execute` cuenta si su `%TRADE` no llegó antes (contadores por id de orden y acciones)."""
        clave = (m.id, int(m.qty))
        if self._n_trade.get(clave, 0) > self._n_execute.get(clave, 0):
            self._n_execute[clave] = self._n_execute.get(clave, 0) + 1
            return []
        self._n_execute[clave] = self._n_execute.get(clave, 0) + 1
        return self._aplicar_fill(o, None, m.id, int(m.qty), m.precio, m.lado, m.ruta, m.hora, None, None, simulado,
                                  "execute")

    def _msg_trade(self, m: MsgTrade, simulado: bool) -> list[Accion]:
        """Corrección 2 / riesgo 8: `%TRADE` dedupe por `id_trade`; si casa con un `Execute` ya contado, solo le pone el id."""
        if m.id in self._trades_vistos:
            return []
        token = self._estado.id_a_token.get(m.id_orden)
        o = self._estado.ordenes.get(token) if token is not None else None
        if o is None:
            self._trades_vistos.add(m.id)
            return [Anotar("trade_desconocido", {"id_trade": m.id, "id_orden": m.id_orden, "ticker": m.ticker,
                                                 "lado": m.lado, "qty": m.qty, "precio": m.precio})]
        clave = (m.id_orden, int(m.qty))
        self._trades_vistos.add(m.id)
        if self._n_execute.get(clave, 0) > self._n_trade.get(clave, 0):
            self._n_trade[clave] = self._n_trade.get(clave, 0) + 1
            pendientes = self._fills_sin_id.get(clave)
            fill = pendientes.popleft() if pendientes else None
            if fill is not None:
                fill.id_trade = m.id
                fill.liq = m.liq
                fill.ecn_fee = m.ecn_fee
            return [Anotar("fill", self._datos_fill(o, m.id, m.id_orden, int(m.qty), m.precio, m.lado, m.ruta, m.hora,
                                                    m.liq, m.ecn_fee, simulado, "trade", eco=True))]
        self._n_trade[clave] = self._n_trade.get(clave, 0) + 1
        return self._aplicar_fill(o, m.id, m.id_orden, int(m.qty), m.precio, m.lado, m.ruta, m.hora, m.liq, m.ecn_fee,
                                  simulado, "trade")

    def _datos_fill(self, o: Orden, id_trade: Optional[int], id_orden: Optional[int], qty: int, precio: Decimal,
                    lado: str, ruta: str, hora: str, liq: Optional[str], ecn_fee: Optional[Decimal], simulado: bool,
                    origen: str, eco: bool = False) -> dict:
        pos = self._estado.posiciones.get(o.ticker)
        return {"id_trade": id_trade, "token": o.token, "id_orden": id_orden, "ticker": o.ticker, "lado": lado,
                "qty": qty, "precio": precio, "ruta": ruta, "hora": hora, "liq": liq, "ecn_fee": ecn_fee,
                "simulado": simulado, "origen": origen, "eco": eco, "proposito": o.proposito.value,
                "neta_fills": pos.neta_fills if pos is not None else None,
                "version_stops": pos.version_stops if pos is not None else None}

    def _aplicar_fill(self, o: Orden, id_trade: Optional[int], id_orden: Optional[int], qty: int, precio: Decimal,
                      lado: str, ruta: str, hora: str, liq: Optional[str], ecn_fee: Optional[Decimal], simulado: bool,
                      origen: str) -> list[Accion]:
        """F1.6 / F2.3: un fill NUEVO al libro por token → neta, versión de stops e `InvalidarSerie` antes de todo lo demás."""
        if qty <= 0 or not isinstance(precio, Decimal) or not precio.is_finite() or precio <= 0:
            return [Anotar("fill_invalido", {"token": o.token, "id_orden": id_orden, "qty": qty, "precio": precio})]
        estado = self._estado
        ticker = o.ticker
        pos = self._pos(ticker)
        lado_n = str(lado).strip().upper()
        if id_trade is None:
            self._id_sintetico -= 1
            id_fill = self._id_sintetico
        else:
            id_fill = id_trade
        fill = Fill(id_trade=id_fill, token=o.token, id_orden=id_orden, ticker=ticker, lado=lado_n, qty=qty,
                    precio=precio, ruta=ruta, hora=hora, liq=liq, ecn_fee=ecn_fee, simulado=simulado)
        estado.fills.setdefault(o.token, []).append(fill)
        if id_trade is None:
            self._fills_sin_id.setdefault((id_orden, qty), deque()).append(fill)
        antes = pos.neta_fills
        if not simulado or estado.fase is Fase.SOMBRA:
            pos.neta_fills += qty if lado_n in _LADOS_COMPRA else -qty
        if antes == 0 and pos.neta_fills != 0:
            self._inicio_episodio[ticker] = self._ahora
        pos.version_stops += 1
        estado.ultimo_fill_en = self._ahora
        o.llenas += qty
        o.ultima_act = self._ahora
        if o.estado not in _TERMINALES:
            o.estado = EstadoOrden.EXECUTED if o.llenas >= o.qty else EstadoOrden.PARTIAL
        acciones: list[Accion] = [
            InvalidarSerie(stops.serie_stops(ticker), pos.version_stops),
            Anotar("fill", self._datos_fill(o, id_trade, id_orden, qty, precio, lado_n, ruta, hora, liq, ecn_fee,
                                            simulado, origen)),
        ]
        if o.proposito in _PROP_ENTRADA:
            acciones += self._fill_entrada(pos, o, fill)
        elif o.proposito in _PROP_STOP or (o.proposito is Proposito.DESCONOCIDA and o.lado is Lado.COMPRA
                                           and o.tipo is TipoOrden.STOP_LIMITE_PP):
            acciones += self._fill_stop(pos, o, fill)
        elif o.proposito is Proposito.VENTA_EXCESO:
            acciones += self._fill_exceso(pos, o, fill)
        else:
            acciones += self._fill_salida(pos, o, fill)
        if antes == 0 and pos.neta_fills != 0 and self._es_rth():
            acciones.append(Consultar(f"GET LDLU {ticker}"))
        acciones += self._armar_simstatus()
        acciones.append(Programar(T_BARRIDO, 0.0, {"motivo": "fill (R-K-01)"}))
        return acciones

    def _fill_entrada(self, pos: PosicionTicker, o: Orden, fill: Fill) -> list[Accion]:
        """F1.6 / R-B-03: reparto proporcional a lo pedido, B13, stops (primer fill al instante; los siguientes con debounce)."""
        ticker = pos.ticker
        intento = pos.intento
        del_intento = intento is not None and (o.token in (intento.token_agregar, intento.token_cruce)
                                               or o.token in self._tokens_intento.get(ticker, set()))
        if del_intento and intento is not None:
            intento.llenas += fill.qty
            lote_ids = list(intento.lotes)
        else:
            lote_ids = list(self._lotes_de_orden.get(o.token) or ([o.lote_id] if o.lote_id else []))
            lote_ids += [lid for lid, lote in pos.lotes.items()
                         if lid not in lote_ids and lote.estado in (EstadoLote.ABRIENDO, EstadoLote.CANCELADO)
                         and lote.llenas < lote.pedidas]
        lotes = [pos.lotes[i] for i in lote_ids if i in pos.lotes]
        capacidad = sum(max(lote.pedidas - lote.llenas, 0) for lote in lotes)
        asignable = min(fill.qty, capacidad)
        acciones: list[Accion] = []
        if asignable > 0:
            for lote_id, n in entrada.repartir_fill(lotes, asignable, fill.precio):
                if n <= 0:
                    continue
                lote = entrada.acumular_fill(pos.lotes[lote_id], n, fill.precio)
                revivido = lote.estado is EstadoLote.CANCELADO
                if revivido:
                    lote = dataclasses.replace(lote, estado=EstadoLote.ABIERTO)
                pos.lotes[lote_id] = lote
                acciones.append(self._anotar_lote(lote))
                if revivido and not del_intento:
                    acciones += self._temporizadores_lote(lote)
        if fill.qty > asignable:
            acciones += [Anotar("incidente", {"tipo": "sobrellenado", "ticker": ticker, "token": o.token,
                                              "qty": fill.qty, "asignadas": asignable, "regla": "R-B-02"}),
                         Avisar(Nivel.AVISO, Grupo.B, f"{avisos.escapar_html(ticker)}: fill de {fill.qty} con solo "
                                                      f"{asignable} pendientes en los lotes; la emergencia cubre la "
                                                      f"neta entera", clave=f"sobrellenado:{ticker}:{o.token}")]
        if del_intento and intento is not None:
            bloque = intento.cfg_congelada or self._cfg.entrada
            tope = (_pct(bloque, "tope_caida_bid_pct", ENTRADA_TOPE_CAIDA_BID_PCT)
                    + _pct(bloque, "cruce_bajo_bid_pct", ENTRADA_CRUCE_BAJO_BID_PCT))
            if entrada.fill_peor_de_lo_permitido(fill.precio, intento.bid_senal, tope):
                acciones.append(Avisar(Nivel.AVISO, Grupo.B,
                                       f"{avisos.escapar_html(ticker)}: fill a {fill.precio} por debajo del tope "
                                       f"({tope} % bajo el bid de la señal {intento.bid_senal}); se MANTIENE (B13)",
                                       clave=f"b13:{ticker}:{o.token}"))
        if self._emergencia_viva(ticker):
            debounce = _segundos(self._cfg.stops, "debounce_s", STOP_DEBOUNCE_S)
            acciones.append(Programar(f"{T_STOPS_AJUSTAR}:{ticker}", debounce, {"ticker": ticker}))
        else:
            acciones += self._plan(ticker)
        acciones += self._revisar_cuadre(o)
        return acciones

    def _fill_stop(self, pos: PosicionTicker, o: Orden, fill: Fill) -> list[Accion]:
        """F2.3 / R-C-11: el fill de un stop reduce los lotes y `limpieza_tras_fill_stop` deja UNA emergencia o vende el exceso."""
        ticker = pos.ticker
        self._stop_hoy.add(ticker)
        preferidos: list[str] = []
        if o.proposito is Proposito.STOP_PRINCIPAL and o.nivel is not None:
            preferidos = [lote.id for lote in self._lotes_vivos(pos) if lote.nivel_stop == o.nivel]
        acciones = self._reducir_lotes(pos, fill.qty, preferidos, mas_alto_primero=True)
        acciones += self._absorber(stops.limpieza_tras_fill_stop(
            pos, self._ordenes_ticker(ticker), self._cot(ticker), self._tokens.siguiente, self._cfg, self._ahora_et,
            pos.version_stops, orden_stop=o, limit_up=self._limit_up(ticker)))
        if pos.neta == 0:
            acciones += self._posicion_cerrada(pos, dentro_de_emergencia=(
                o.proposito is Proposito.STOP_EMERGENCIA and (o.precio is None or fill.precio <= o.precio)))
        elif pos.neta < 0:
            acciones += self._capar_salidas(pos)
        return acciones

    def _fill_salida(self, pos: PosicionTicker, o: Orden, fill: Fill) -> list[Accion]:
        """F4.3 / F5 / R-C-07: una salida reduce su lote y los stops se reducen a lo que queda; plana → todo fuera."""
        preferidos = [o.lote_id] if o.lote_id is not None and o.lote_id in pos.lotes else []
        acciones = self._reducir_lotes(pos, fill.qty, preferidos, mas_alto_primero=False)
        self._refrescar_tp_pendiente(pos)
        acciones += self._revisar_cuadre(o)
        if pos.neta > 0:
            acciones += self._absorber(stops.limpieza_tras_fill_stop(
                pos, self._ordenes_ticker(pos.ticker), self._cot(pos.ticker), self._tokens.siguiente, self._cfg,
                self._ahora_et, pos.version_stops, limit_up=self._limit_up(pos.ticker)))
        elif pos.neta == 0:
            acciones += self._posicion_cerrada(pos, dentro_de_emergencia=False)
        else:
            acciones += self._plan(pos.ticker)
        return acciones

    def _fill_exceso(self, pos: PosicionTicker, o: Orden, fill: Fill) -> list[Accion]:
        """R-C-11 (b): la venta del exceso; plana → incidente resuelto; si cruzó a corto, `plan` protege lo que haya."""
        acciones: list[Accion] = [Anotar("incidente", {"tipo": "exceso_vendido", "ticker": pos.ticker, "qty": fill.qty,
                                                       "neta": pos.neta, "regla": "R-C-11 (b)"})]
        if pos.neta < 0:
            acciones += self._plan(pos.ticker)
        return acciones

    def _reducir_lotes(self, pos: PosicionTicker, qty: int, preferidos: list[str],
                       mas_alto_primero: bool) -> list[Accion]:
        """Las acciones que salen se descuentan de los lotes: primero los `preferidos`, luego el resto (lote a CERRADO en 0)."""
        vivos = self._lotes_vivos(pos)
        orden_lotes = [lote for lote in vivos if lote.id in preferidos]
        resto = [lote for lote in vivos if lote.id not in preferidos]
        resto.sort(key=lambda lote: (lote.nivel_stop or Decimal("0")), reverse=mas_alto_primero)
        acciones: list[Accion] = []
        restante = qty
        for lote in orden_lotes + resto:
            if restante <= 0:
                break
            n = min(restante, lote.llenas)
            if n <= 0:
                continue
            restante -= n
            lote.llenas -= n
            if lote.llenas == 0:
                lote.estado = EstadoLote.CERRADO
            acciones.append(Anotar("lote", {"lote_id": lote.id, "ticker": lote.ticker, "llenas": lote.llenas,
                                            "estado": lote.estado.value, "motivo": "salida"}))
            if lote.estado is EstadoLote.CERRADO:
                acciones += self._lote_cerrado(lote)
        return acciones

    def _lote_cerrado(self, lote: Lote) -> list[Accion]:
        acciones: list[Accion] = [Desprogramar(salidas.clave_lote(base, lote.id))
                                  for base in (T_HORA_AGREGAR, T_HORA_ASK, T_EOD_COMPROBAR, T_TP_CRUCE)]
        if lote.ticker not in self._reuso_consultado:
            self._reuso_consultado.add(lote.ticker)
            acciones.append(locates.consulta_reuso(lote.ticker))
        return acciones

    def _posicion_cerrada(self, pos: PosicionTicker, dentro_de_emergencia: bool) -> list[Accion]:
        """Neta 0: lotes CERRADO, nada vivo en el ticker (R-C-11 a) y, si había cisne negro, su fin (R-G-01 (3))."""
        ticker = pos.ticker
        acciones: list[Accion] = []
        for lote in self._lotes_vivos(pos):
            lote.estado = EstadoLote.CERRADO
            acciones.append(Anotar("lote", {"lote_id": lote.id, "ticker": ticker, "estado": lote.estado.value,
                                            "motivo": "posición plana"}))
            acciones += self._lote_cerrado(lote)
        for o in self._vivas(ticker):
            if o.proposito not in _PROP_ENTRADA:
                acciones += self._cancelar_orden(o, "R-C-11 (a): posición plana; no queda nada vivo que la reabra")
        acciones += self._cerrar_bs_si_toca(pos, dentro_de_emergencia)
        self._cierre_humano.discard(ticker)
        self._banda_enviada.discard(ticker)
        self._olvidar_rechazos_de_stop(ticker)
        pos.persecuciones_ask = 0
        acciones.append(Anotar("posicion_cerrada", {"ticker": ticker, "neta_das": pos.neta_das}))
        return acciones

    def _olvidar_rechazos_de_stop(self, ticker: str) -> None:
        """La posición se cerró o el humano reanudó el ticker: fuera la separación y la cuenta de R-C-03."""
        self._stop_bloqueo.pop(ticker, None)
        for clave in [k for k in self._stop_intentos if k[0] == ticker]:
            del self._stop_intentos[clave]

    def _capar_salidas(self, pos: PosicionTicker) -> list[Accion]:
        """R-C-07 / riesgo 6: las compras de salida vivas nunca suman más que lo que sigue corto (se cancelan las más nuevas)."""
        corto = -pos.neta
        salidas_vivas = sorted((o for o in self._vivas(pos.ticker) if o.proposito in _PROP_SALIDA and o.lado is Lado.COMPRA),
                               key=lambda o: (o.id_das is None, o.id_das or 0, o.enviada_en))
        total = sum(_qty_viva(o) for o in salidas_vivas)
        acciones: list[Accion] = []
        for o in reversed(salidas_vivas):
            if total <= corto:
                break
            total -= _qty_viva(o)
            acciones += self._cancelar_orden(o, f"R-C-07: la salida de {pos.ticker} superaría lo que queda corto ({corto})")
        return acciones

    def _msg_orden(self, m: MsgOrden) -> list[Accion]:
        """`%ORDER`: estado, cantidades y tipo crudo de NUESTRA orden; una propia desconocida se ADOPTA (F13); ajena al diario."""
        estado = self._estado
        if reconciliacion.es_ajena(m, estado.dia):
            if m.id in estado.ordenes_ajenas or m.id in self._ajenas_anotadas:
                return []
            self._ajenas_anotadas.add(m.id)
            return [Anotar("orden_ajena_vista", {"id": m.id, "token": m.token, "ticker": m.ticker, "lado": m.lado,
                                                 "qty": m.qty, "order_src": m.order_src, "estado": m.estado.value,
                                                 "regla": "R-K-02"})]
        o = estado.ordenes.get(m.token) if m.token is not None else None
        if o is None:
            adoptada = reconciliacion.orden_de_msg(m, estado.dia, None, self._cfg.stops)
            if adoptada is None:
                return []
            estado.ordenes[adoptada.token] = adoptada
            estado.id_a_token[m.id] = adoptada.token
            return [Anotar("orden_adoptada", {"token": adoptada.token, "id": m.id, "ticker": adoptada.ticker,
                                              "estado": m.estado.value, "tipo_das_crudo": m.tipo,
                                              "origen": adoptada.origen.value, "regla": "F13 / R-C-07"})]
        antes = (o.id_das, o.estado, o.qty, o.lvqty, o.cxlqty, o.tipo_das_crudo)
        self._casar_id(o, m.id)
        paso = self._transicion(o, m.estado)
        if m.qty > 0 and o.estado not in _TERMINALES:
            o.qty = max(m.qty, o.llenas)
        o.lvqty = max(int(m.lvqty), 0)
        o.cxlqty = max(o.cxlqty, int(m.cxlqty))
        o.tipo_das_crudo = m.tipo
        o.ultima_act = self._ahora
        acciones: list[Accion] = []
        if (o.id_das, o.estado, o.qty, o.lvqty, o.cxlqty, o.tipo_das_crudo) != antes:
            acciones.append(Anotar("orden_estado", {"token": o.token, "id": m.id, "ticker": o.ticker,
                                                    "estado": o.estado.value, "qty": o.qty, "lvqty": o.lvqty,
                                                    "cxlqty": o.cxlqty, "tipo_das_crudo": m.tipo}))
        acciones += self._tras_cambio_orden(o, paso)
        return acciones

    def _msg_pos(self, m: MsgPos) -> list[Accion]:
        """`%POS`: SOLO lo que dice DAS (neta_das); si el plan esperaba a que cuadrara con los fills, se planifica ya."""
        pos = self._pos(m.ticker)
        cambio = (pos.neta_das, pos.avg_das, pos.tipo_das) != (m.neta, m.avg, m.tipo)
        pos.neta_das = m.neta
        pos.avg_das = m.avg
        pos.tipo_das = m.tipo
        pos.neta_das_en = self._ahora
        acciones: list[Accion] = []
        if self._estado.qty_corto_negativa is None and m.tipo == 3 and m.qty_cruda != 0:
            self._estado.qty_corto_negativa = m.qty_cruda < 0
            acciones.append(Anotar("qty_corto_negativa", {"valor": m.qty_cruda < 0, "ticker": m.ticker,
                                                          "regla": "injerto A §8.8"}))
        if cambio:
            acciones.append(Anotar("pos", {"ticker": m.ticker, "neta": m.neta, "avg": m.avg, "tipo": m.tipo}))
        if m.ticker in self._espera_plan and pos.neta_das == pos.neta_fills:
            self._espera_plan.discard(m.ticker)
            acciones.append(Desprogramar(f"{T_STOPS_PLAN}:{m.ticker}"))
            acciones += self._plan(m.ticker)
        return acciones

    # ── rechazos (F8) ──────────────────────────────────────────────────
    def _rechazo(self, o: Orden) -> list[Accion]:
        """F8 (R-B-07, R-C-03, EP-1): `rechazos.decidir` y su aplicación: pausa, token nuevo, entrada re-precio al libro."""
        pos = self._pos(o.ticker)
        ticker = o.ticker
        intento = pos.intento
        del_intento = intento is not None and o.token in (intento.token_agregar, intento.token_cruce)
        motivo_previo = self._motivo_cancel.get(ticker) if del_intento else None
        tratamiento = rechazos.clasificar(o.notas, self._catalogo)
        crudas = rechazos.decidir(o, tratamiento, pos, self._ordenes_ticker(ticker), self._cfg,
                                  self._tokens.siguiente, self._cot(ticker), self._ahora_et, self._ahora)
        if o.proposito in _PROP_STOP or o.tipo is TipoOrden.STOP_LIMITE_PP:
            self._bloquear_stops_tras_rechazo(o, crudas)
        if del_intento and intento is not None:
            if intento.token_agregar == o.token:
                intento.token_agregar = None
            if intento.token_cruce == o.token:
                intento.token_cruce = None
        acciones: list[Accion] = []
        reintento = False
        diferido = False
        for a in crudas:
            if isinstance(a, Anotar) and a.tipo == "rechazo":
                token_nuevo = a.datos.get("token_nuevo")
                if isinstance(token_nuevo, int):
                    primero = a.datos.get("primer_intento_en")
                    self._meta_orden[token_nuevo] = (int(a.datos.get("intentos_nuevo") or 0),
                                                     float(primero) if isinstance(primero, (int, float)) else self._ahora)
            elif isinstance(a, Anotar) and a.tipo == "pausa":
                nuevo = _estado_ticker(a.datos.get("estado"))
                if nuevo is not None:
                    pos.estado = nuevo
                    pos.motivo_estado = str(a.datos.get("motivo", ""))
                    pos.desde = self._ahora
            elif isinstance(a, EnviarOrden) and del_intento and intento is not None:
                reenvio = None if motivo_previo is not None else self._reintento_de_entrada(pos, intento, a)
                if reenvio is None:
                    acciones.append(Anotar("reintento_descartado", {
                        "ticker": ticker, "token": a.orden.token, "token_rechazado": o.token,
                        "motivo": (f"el intento ya se estaba cancelando ({motivo_previo})" if motivo_previo
                                   else "entradas bloqueadas o sin libro")}))
                    continue
                a = reenvio
                reintento = True
            elif (isinstance(a, Programar) and a.clave in (T_REINTENTO_RECHAZO, T_LOCATE_RECOMPRAR)
                  and del_intento and motivo_previo is None):
                diferido = True
            acciones.append(a)
            if isinstance(a, EnviarOrden) and not del_intento:
                acciones += self._seguimiento_de_reintento(o, a.orden)
        acciones = self._absorber(acciones)
        if del_intento and not reintento:
            if diferido:
                self._intento_en_reintento.add(ticker)
            else:
                if motivo_previo is None:
                    self._poner_motivo(ticker, MOTIVO_RECHAZO)
                acciones += self._avanzar_intento(pos)
        return acciones

    def _seguimiento_de_reintento(self, rechazada: Orden, nueva: OrdenNueva) -> list[Accion]:
        """La orden de salida que sustituye a una rechazada hereda su seguimiento: el cruce del TP y la persecución al ask."""
        if nueva.proposito is Proposito.TP_AGREGAR and nueva.lote_id is not None:
            espera = _segundos((self._cfg.salidas or {}).get("tp_parcial") or {}, "agregar_s", 60.0)
            return [Programar(salidas.clave_lote(T_TP_CRUCE, nueva.lote_id), espera,
                              {"lote_id": nueva.lote_id, "ticker": nueva.ticker, "token": nueva.token, "qty": nueva.qty})]
        if nueva.proposito in (Proposito.HORA_ASK, Proposito.CIERRE_REINICIO) and not nueva.post_only:
            self._persecuciones[nueva.token] = self._persecuciones.pop(rechazada.token, 0)
            return [Programar(f"{T_PERSEGUIR_ASK}:{nueva.token}", self._perseguir_cada(),
                              {"token": nueva.token, "ticker": nueva.ticker, "lote_id": nueva.lote_id})]
        return []

    def _bloquear_stops_tras_rechazo(self, o: Orden, crudas: list[Accion]) -> None:
        """R-C-03: tras un stop rechazado no se repone nada hasta su `stop_reintento` (separación) y la cuenta de intentos
        pasa a la orden siguiente de ese propósito venga de donde venga (plan, barrido); agotados, no se repone solo."""
        programa = next((a for a in crudas if isinstance(a, Programar) and a.clave == T_STOP_REINTENTO), None)
        if programa is not None:
            primero = programa.datos.get("primer_intento_en")
            self._stop_intentos[(o.ticker, o.proposito)] = (
                int(programa.datos.get("intento") or o.intentos + 1),
                float(primero) if isinstance(primero, (int, float)) else self._ahora)
            hasta = self._ahora + float(programa.en_s)
        else:
            hasta = math.inf
        self._stop_bloqueo[o.ticker] = max(self._stop_bloqueo.get(o.ticker, -math.inf), hasta)

    def _reintento_de_entrada(self, pos: PosicionTicker, intento: Any, a: EnviarOrden) -> Optional[EnviarOrden]:
        """R-B-07 (2) «reintentar»: el agregar se RE-PRECIA al libro de ahora (el mismo precio volvería a cruzar)."""
        orden = a.orden
        if self._bloqueo_apertura(pos.ticker) is not None:
            return None
        if orden.proposito is Proposito.ENTRADA_AGREGAR and intento.fase is FaseIntento.AGREGANDO:
            cot = self._cot(pos.ticker)
            if not _libro_utilizable(cot):
                return None
            nueva = entrada.orden_agregar(intento, cot, self._cfg, orden.token, self._ahora_et,
                                          nivel=self._nivel_intento(pos))
            intento.token_agregar = orden.token
            a = EnviarOrden(nueva, serie=a.serie)
        elif orden.proposito is Proposito.ENTRADA_CRUCE and intento.fase is FaseIntento.CRUZANDO:
            intento.token_cruce = orden.token
        else:
            return None
        self._tokens_intento.setdefault(pos.ticker, set()).add(orden.token)
        self._lotes_de_orden[orden.token] = list(intento.lotes)
        return a

    # ── halts (F6) y mercado ───────────────────────────────────────────
    def _msg_issue_status(self, m: MsgIssueStatus) -> list[Accion]:
        """F6.1: `$IssueStatus` → transición de halt (k, precio de parada) con `mercado.marcar_halt`."""
        ticker = m.ticker
        cot = self._cot(ticker)
        franja = self._franja()
        transicion = self._mercado.marcar_halt(ticker, m, self._ahora_et, cot.last if cot is not None else None, franja)
        if transicion == "halt":
            return self._al_halt(ticker, franja)
        if transicion == "reapertura":
            return self._al_reabrir(ticker)
        simb = self._mercado.simbolo(ticker)
        pos = self._estado.posiciones.get(ticker)
        if halts.es_halt(simb) and ticker in self._halt_en_curso and pos is not None and pos.neta != 0:
            fin = halts.fin_previsto(simb, self._ahora_et)
            if fin != self._halt_fin.get(ticker):
                self._halt_fin[ticker] = fin
                return [Programar(f"{T_HALT_DECIDIR}:{ticker}", self._segundos_envio_open(fin), {"ticker": ticker})]
        return []

    def _segundos_envio_open(self, fin: Optional[datetime]) -> float:
        antes = int(_segundos(self._cfg.halts, "enviar_antes_fin_halt_s", 60.0))
        return halts.momento_envio_open(fin, self._ahora_et, antes)

    def _al_halt(self, ticker: str, franja: str) -> list[Accion]:
        """F6.1 (B18, R-F-04 a, R-G-02): cancelar entradas, aviso 2, ticker en HALT y `halt_decidir` un minuto antes del fin."""
        simb = self._mercado.simbolo(ticker)
        self._halt_en_curso.add(ticker)
        self._halt_hoy.add(ticker)
        self._reapertura_ok.discard(ticker)
        pos = self._estado.posiciones.get(ticker)
        if pos is None or (not self._tiene_posicion(pos) and pos.intento is None
                           and not any(o.proposito in _PROP_ENTRADA for o in self._vivas(ticker))):
            return [Anotar("halt", {"ticker": ticker, "ta": simb.ta, "tat": simb.tat, "k": simb.k_halts_up,
                                    "sin_posicion": True})]
        acciones = self._absorber(halts.al_entrar_en_halt(pos, self._ordenes_ticker(ticker), simb, self._cot(ticker),
                                                          franja))
        if pos.intento is not None:
            acciones += self._cancelar_intento(pos, MOTIVO_HALT)
        if pos.estado is EstadoTicker.NORMAL:
            pos.estado = EstadoTicker.HALT
            pos.motivo_estado = f"halt {simb.ta or ''}".strip()
            pos.desde = self._ahora
        if pos.neta != 0:
            fin = halts.fin_previsto(simb, self._ahora_et)
            self._halt_fin[ticker] = fin
            acciones.append(Programar(f"{T_HALT_DECIDIR}:{ticker}", self._segundos_envio_open(fin), {"ticker": ticker}))
        return acciones

    def _t_halt_decidir(self, clave: str, datos: dict) -> list[Accion]:
        """F6.2 (R-F-01/05/06, EP-2, injerto §8.23): decidir la reapertura; la MKT por OPEN sale UNA vez (guardia)."""
        ticker = str(datos.get("ticker") or clave.split(":", 1)[1])
        simb = self._mercado.simbolo(ticker)
        pos = self._estado.posiciones.get(ticker)
        if pos is None or pos.neta == 0 or not halts.es_halt(simb):
            return []
        franja = self._franja()
        duracion = ((self._ahora_et - simb.halt_desde).total_seconds() / 60.0) if simb.halt_desde is not None else 0.0
        cot = self._cot(ticker)
        decision = halts.decidir_reapertura(pos, simb, self._niveles_principal(pos), cot, dict(self._cfg.halts), franja,
                                            duracion)
        self._halt_decision[ticker] = decision
        acciones: list[Accion] = [Anotar("halt_decision", {"ticker": ticker, "decision": decision,
                                                           "k": simb.k_halts_up, "duracion_min": duracion,
                                                           "franja": franja, "regla": "R-F-01"})]
        if decision in ("cerrar_mercado", "cerrar_limite_pm"):
            if decision == "cerrar_mercado" and not halts.debe_enviar_open(simb):
                return acciones + [Anotar("halt_guardia", {"ticker": ticker, "motivo": "la MKT por OPEN ya salió",
                                                           "regla": "injerto A §8.23"})]
            if self._orden_halt_viva(ticker):
                return acciones + [Anotar("halt_guardia", {"ticker": ticker, "motivo": "orden de salida del halt viva"})]
            qty = abs(pos.neta) - self._comprando(ticker)
            if qty <= 0:
                return acciones
            orden = halts.orden_reapertura(pos, qty, cot, decision, self._cfg, self._tokens.siguiente(), self._ahora_et)
            acciones += self._absorber([EnviarOrden(orden)])
            if decision == "cerrar_mercado":
                simb.orden_open_enviada = True
            acciones.append(Avisar(Nivel.AVISO, Grupo.B,
                                   f"HALT {avisos.escapar_html(ticker)}: se sale ({decision}) con {qty} acciones por "
                                   f"{avisos.escapar_html(orden.ruta)}; los stops siguen residentes",
                                   clave=f"halt_salida:{ticker}:{simb.tat}"))
        elif decision == "control_humano":
            if ticker not in self._halt_humano_avisado:
                self._halt_humano_avisado.add(ticker)
                acciones.append(Avisar(Nivel.MAXIMO, Grupo.B,
                                       f"HALT {avisos.escapar_html(ticker)}: CONTROL HUMANO (T1 &gt; 250 %, T12 o sin "
                                       f"precio). Posición {pos.neta:+d}; stops residentes (R-F-05)",
                                       clave=f"halt_humano:{ticker}"))
                if pos.estado in (EstadoTicker.NORMAL, EstadoTicker.HALT, EstadoTicker.PAUSADO):
                    pos.estado = EstadoTicker.CONTROL_HUMANO
                    pos.motivo_estado = "halt: control humano"
                    pos.desde = self._ahora
                    acciones.append(Anotar("pausa", {"ticker": ticker, "estado": EstadoTicker.CONTROL_HUMANO.value,
                                                     "motivo": "halt: control humano (R-F-05)"}))
        else:
            acciones.append(Programar(f"{T_HALT_DECIDIR}:{ticker}", HALT_REDECIDIR_S, {"ticker": ticker}))
        return acciones

    def _niveles_principal(self, pos: PosicionTicker) -> Optional[NivelesStop]:
        niveles = sorted(lote.nivel_stop for lote in self._lotes_vivos(pos) if _es_precio(lote.nivel_stop))
        if not niveles:
            return None
        return stops.niveles(niveles[0], self._cfg.stops, self._limit_up(pos.ticker))

    def _orden_halt_viva(self, ticker: str) -> bool:
        return any(o.ticker == ticker and o.estado in _VIVOS and o.proposito in _PROP_HALT
                   for o in self._estado.ordenes.values())

    def _comprando(self, ticker: str) -> int:
        return sum(_qty_viva(o) for o in self._vivas(ticker) if o.proposito in _PROP_SALIDA and o.lado is Lado.COMPRA)

    def _al_reabrir(self, ticker: str) -> list[Accion]:
        """F6.3: segundo aviso, ticker a NORMAL, reintento EP-2 por «cruzar» si la salida del halt no salió, y la primera vela."""
        simb = self._mercado.simbolo(ticker)
        self._halt_en_curso.discard(ticker)
        self._halt_fin.pop(ticker, None)
        cot = self._cot(ticker)
        precio = cot.last if cot is not None and cot.last is not None else simb.precio_parada
        decision = self._halt_decision.pop(ticker, None)
        acciones: list[Accion] = [Anotar("halt_reapertura", {"ticker": ticker, "k": simb.k_halts_up, "precio": precio,
                                                             "decision": decision})]
        pos = self._estado.posiciones.get(ticker)
        if pos is not None:
            if pos.estado is EstadoTicker.HALT:
                pos.estado = EstadoTicker.NORMAL
                pos.motivo_estado = ""
                pos.desde = self._ahora
            acciones.append(Avisar(Nivel.AVISO, Grupo.B,
                                   f"REABRE {avisos.escapar_html(ticker)} · precio {precio} · k={simb.k_halts_up} · "
                                   f"posición {pos.neta:+d} · decisión: {decision or 'sin decisión'}",
                                   clave=f"reapertura:{ticker}:{simb.tat}"))
            if (pos.neta != 0 and decision in ("cerrar_mercado", "cerrar_limite_pm") and not self._orden_halt_viva(ticker)
                    and _libro_utilizable(cot)):
                qty = abs(pos.neta) - self._comprando(ticker)
                if qty > 0:
                    orden = halts.orden_reapertura(pos, qty, cot, "cerrar_limite_pm", self._cfg, self._tokens.siguiente(),
                                                   self._ahora_et)
                    acciones += self._absorber([EnviarOrden(orden)])
                    acciones.append(Anotar("halt_reintento", {"ticker": ticker, "qty": qty, "token": orden.token,
                                                              "regla": "EP-2"}))
        if _es_precio(precio):
            acciones.append(Programar(f"{T_HALT_PRIMERA_VELA}:{ticker}", HALT_PRIMERA_VELA_S,
                                      {"ticker": ticker, "precio_reapertura": str(precio),
                                       "reapertura_epoch": self._ahora_et.timestamp()}))
        return acciones

    def _t_halt_primera_vela(self, clave: str, datos: dict) -> list[Accion]:
        """R-F-01 esc. 2 / R-F-03 / R-F-04 (b): primera vela < 6 % y k < 3 → se levanta el veto y la señal guardada entra."""
        ticker = str(datos.get("ticker") or clave.split(":", 1)[1])
        simb = self._mercado.simbolo(ticker)
        cot = self._cot(ticker)
        pct: Optional[Decimal] = None
        try:
            apertura = precios.de_float(str(datos.get("precio_reapertura")))
            if cot is not None and _es_precio(cot.last) and apertura > 0:
                pct = halts.primera_vela_pct(apertura, cot.last)
        except ValueError:
            pct = None
        k = simb.k_halts_up
        if halts.puede_reentrar_tras_halt(pct, k, dict(self._cfg.halts)):
            self._reapertura_ok.add(ticker)
        acciones: list[Accion] = [Anotar("halt_primera_vela", {"ticker": ticker, "pct": pct, "k": k,
                                                               "reentrada": ticker in self._reapertura_ok})]
        pos = self._estado.posiciones.get(ticker)
        guardada = pos.senal_guardada_halt if pos is not None else None
        if pos is not None and guardada is not None:
            pos.senal_guardada_halt = None
            if halts.senal_guardada_valida(guardada, pct, dict(self._cfg.halts), k):
                epoch = datos.get("reapertura_epoch")
                acciones += self._entrada(guardada, es_reapertura=True,
                                          t_cierre=float(epoch) if isinstance(epoch, (int, float)) else None)
            else:
                acciones += self._descartar(guardada, "R-F-04 (b): la primera vela tras reabrir o k no permiten entrar",
                                            avisar=True)
        return acciones

    def _msg_ldlu(self, m: MsgLDLU) -> list[Accion]:
        """R-F-02: bandas nuevas → el plan recorta los disparos bajo la banda (solo si cambió el limit up)."""
        antes = self._mercado.simbolo(m.ticker).limit_up
        self._mercado.aplicar(m)
        despues = self._mercado.simbolo(m.ticker).limit_up
        pos = self._estado.posiciones.get(m.ticker)
        if despues != antes and pos is not None and pos.neta < 0:
            return self._plan(m.ticker)
        return []

    def _msg_bp(self, m: MsgBP) -> list[Accion]:
        """R-I-01 / R-E-02: el BP de DAS se lee con su hora y suelta las reservas (ya refleja lo consumido)."""
        cuenta = self._estado.cuenta
        cuenta.bp = m.bp
        cuenta.bp_overnight = m.bp_overnight
        cuenta.leida_en = self._ahora
        capital.liberar_reservas(cuenta)
        return []

    def _msg_route(self, m: MsgRouteStatus) -> list[Accion]:
        self._estado.rutas_habilitadas[m.ruta] = m.habilitada
        if m.habilitada or m.ruta not in _rutas_de(self._cfg.rutas) or m.ruta in self._rutas_avisadas:
            return []
        self._rutas_avisadas.add(m.ruta)
        return [Avisar(Nivel.AVISO, Grupo.B, f"La ruta {avisos.escapar_html(m.ruta)} de la tabla está DESHABILITADA en "
                                             f"DAS (GET RouteStatus)", clave=f"ruta:{m.ruta}")]

    def _msg_conexion(self, m: MsgConexion) -> list[Accion]:
        """EP-7: `#…Logon:Failed` → aviso 3 «LOGIN/2FA a mano»; el resto solo al diario (la caída la trae `ConexionDAS`)."""
        evento = str(m.evento)
        if "Logon:Successful" in evento:
            self._estado.das_logon[m.servidor] = True
        elif "Logon:Failed" in evento:
            self._estado.das_logon[m.servidor] = False
        acciones: list[Accion] = [Anotar("das_conexion", {"servidor": m.servidor, "evento": evento})]
        if "Logon:Failed" in evento:
            acciones.append(Avisar(Nivel.MAXIMO, Grupo.B, f"DAS: {avisos.escapar_html(m.servidor)} rechazó el LOGIN: "
                                                          f"hacer LOGIN/2FA a mano (EP-7)",
                                   clave=f"das_logon:{m.servidor}"))
        return acciones

    def _msg_quote(self, m: MsgQuote) -> list[Accion]:
        """`$Quote`: el libro y, con posición corta, cisne negro, principal rebasado y banda del halt; y los fogonazos."""
        ticker = self._mercado.aplicar(m)
        if ticker is None:
            return []
        cot = self._cot(ticker)
        acciones: list[Accion] = []
        if cot is not None and _es_precio(cot.last):
            historial = self._hist.setdefault(ticker, deque(maxlen=HISTORIAL_MAX))
            historial.append((self._ahora, cot.last))
        pos = self._estado.posiciones.get(ticker)
        if pos is not None and pos.estado is EstadoTicker.SIN_SIMBOLO and _libro_utilizable(cot):
            pos.estado = EstadoTicker.NORMAL
            pos.motivo_estado = ""
            pos.desde = self._ahora
            self._sin_simbolo_avisado.discard(ticker)
            acciones.append(Anotar("reanudar", {"ticker": ticker, "motivo": "A7: DAS ya cotiza el símbolo"}))
        if pos is not None and pos.neta < 0 and cot is not None:
            acciones += self._vigilar_bs(pos, cot)
            if (pos.estado not in (EstadoTicker.BS, EstadoTicker.HALT) and ticker not in self._manual
                    and ticker not in self._cierre_humano):
                acciones += self._absorber(stops.reasignar_principal_rebasado(
                    pos, self._ordenes_ticker(ticker), cot, self._cfg.stops, self._tokens.siguiente, self._ahora_et,
                    self._ruta_stop(), pos.version_stops, self._limit_up(ticker)))
            acciones += self._banda(pos, cot)
        acciones += self._fogonazo(ticker)
        return acciones

    def _banda(self, pos: PosicionTicker, cot: Cotizacion) -> list[Accion]:
        """R-F-01: con k = k_max − 1 y el ask a ≤ 4 % del limit up en RTH, salir a mercado por «cruzar» ANTES del halt."""
        ticker = pos.ticker
        if (ticker in self._banda_enviada or pos.estado in (EstadoTicker.BS, EstadoTicker.HALT)
                or ticker in self._manual or not self._es_rth()):
            return []
        simb = self._mercado.simbolo(ticker)
        if not halts.cerca_de_banda(cot, simb, simb.k_halts_up, dict(self._cfg.halts)):
            return []
        qty = -pos.neta - self._comprando(ticker)
        if qty <= 0 or cot.ask is None:
            return []
        self._banda_enviada.add(ticker)
        orden = OrdenNueva(token=self._tokens.siguiente(), lado=Lado.COMPRA, ticker=ticker,
                           ruta=precios.ruta(self._cfg.rutas, "cruzar", cot.ask, self._ahora_et), qty=qty,
                           tipo=TipoOrden.MERCADO, proposito=Proposito.HALT_BANDA)
        return ([Anotar("halt_banda", {"ticker": ticker, "k": simb.k_halts_up, "ask": cot.ask,
                                       "limit_up": simb.limit_up, "qty": qty, "regla": "R-F-01"})]
                + self._absorber([EnviarOrden(orden)])
                + [Avisar(Nivel.AVISO, Grupo.B, f"{avisos.escapar_html(ticker)}: k={simb.k_halts_up} y el ask {cot.ask} a "
                                                f"≤ {self._cfg.halts.get('distancia_banda_k2_pct', 4)} % del limit up "
                                                f"{simb.limit_up}: se sale a mercado ({qty}) antes del siguiente halt",
                          clave=f"halt_banda:{ticker}")])

    def _es_rth(self) -> bool:
        return self._franja().startswith("RTH")

    # ── cisne negro (F7) ───────────────────────────────────────────────
    def _niveles_bs(self, pos: PosicionTicker) -> Optional[NivelesStop]:
        """El principal del L más bajo y la emergencia del L más alto (la que lleva toda la posición, R-C-01 v3)."""
        niveles = sorted(lote.nivel_stop for lote in self._lotes_vivos(pos) if _es_precio(lote.nivel_stop))
        if not niveles:
            return None
        limit_up = self._limit_up(pos.ticker)
        bajo = stops.niveles(niveles[0], self._cfg.stops, limit_up)
        alto = stops.niveles(niveles[-1], self._cfg.stops, limit_up)
        return NivelesStop(principal_disparo=bajo.principal_disparo, principal_limite=bajo.principal_limite,
                           emergencia_disparo=alto.emergencia_disparo, emergencia_limite=alto.emergencia_limite,
                           bajo_banda=bajo.bajo_banda or alto.bajo_banda)

    def _vigilar_bs(self, pos: PosicionTicker, cot: Cotizacion) -> list[Accion]:
        """F7 (R-G-01): el precio pasa de largo el límite de la emergencia sin llenarla → protocolo, aviso 3 e informes."""
        if pos.bs is not None or pos.estado is EstadoTicker.BS:
            if pos.bs is not None:
                pos.bs = cisne_negro.actualizar_maximo(pos.bs, cot.last)
            return []
        niveles = self._niveles_bs(pos)
        if niveles is None or not cisne_negro.se_activa(pos, niveles, self._ordenes_ticker(pos.ticker), cot,
                                                        self._cfg.stops):
            return []
        ticker = pos.ticker
        bs = cisne_negro.activar(pos, niveles, self._ahora, precio=cot.last)
        anterior = pos.estado
        pos.bs = bs
        pos.estado = EstadoTicker.BS
        pos.motivo_estado = "cisne negro"
        pos.desde = self._ahora
        acciones: list[Accion] = [
            Anotar("bs", {"ticker": ticker, "evento": "activado", "activado_en": bs.activado_en,
                          "primer_stop": bs.primer_stop, "emergencia_limite": bs.emergencia_limite,
                          "max_visto": bs.max_visto, "informes": 0, "estado_anterior": anterior.value,
                          "regla": "R-G-01"}),
            Avisar(Nivel.MAXIMO, Grupo.B, self._texto_informe(pos, niveles), clave=cisne_negro.clave_aviso_informe(ticker, 0)),
            Programar(f"{T_BS_INFORME}:{ticker}", cisne_negro.segundos_hasta_informe(bs, self._ahora, self._cfg.tecnicos),
                      {"ticker": ticker}),
        ]
        if pos.intento is not None:
            acciones += self._cancelar_intento(pos, MOTIVO_CIERRE)
        return acciones

    def _texto_informe(self, pos: PosicionTicker, niveles: Optional[NivelesStop] = None) -> str:
        if pos.bs is None:
            raise RuntimeError(f"{pos.ticker}: informe de cisne negro sin protocolo activo")
        ticker = pos.ticker
        niveles = niveles or self._niveles_bs(pos) or NivelesStop(pos.bs.primer_stop, pos.bs.primer_stop,
                                                                  pos.bs.emergencia_limite, pos.bs.emergencia_limite,
                                                                  False)
        eods = [self._hora_del_dia(lote.eod) for lote in self._lotes_vivos(pos) if lote.eod]
        eod = min((e for e in eods if e is not None), default=None)
        fills = [f for lista in self._estado.fills.values() for f in lista if f.ticker == ticker]
        return cisne_negro.informe(pos, pos.bs, niveles, self._cot(ticker), self._mercado.simbolo(ticker),
                                   self._estado.cuenta, self._ahora_et, eod, self._franja(), fills, ahora=self._ahora,
                                   vivas=self._ordenes_ticker(ticker), historial=list(self._hist.get(ticker, ())),
                                   cfg_stops=self._cfg.stops)

    def _hora_del_dia(self, texto: Optional[str]) -> Optional[datetime]:
        m = _RE_HORA.match(texto or "")
        if m is None:
            return None
        dia = self._estado.dia
        return datetime(dia.year, dia.month, dia.day, int(m.group(1)), int(m.group(2)), int(m.group(3) or 0), tzinfo=ET)

    def _t_bs_informe(self, clave: str, datos: dict) -> list[Accion]:
        """F7 / R-G-01 v2: informe cada 60 s × 5 y luego cada 300 s; cada uno con su clave «bs:X:n» (dedupe de 60 s)."""
        ticker = str(datos.get("ticker") or clave.split(":", 1)[1])
        pos = self._estado.posiciones.get(ticker)
        if pos is None or pos.bs is None:
            return []
        acciones: list[Accion] = []
        if cisne_negro.toca_informe(pos.bs, self._ahora, self._cfg.tecnicos):
            n = pos.bs.informes + 1
            acciones.append(Avisar(Nivel.MAXIMO, Grupo.B, self._texto_informe(pos),
                                   clave=cisne_negro.clave_aviso_informe(ticker, n)))
            pos.bs = cisne_negro.registrar_informe(pos.bs, self._ahora)
            acciones.append(Anotar("bs_informe", {"ticker": ticker, "informes": n, "max_visto": pos.bs.max_visto}))
        espera = cisne_negro.segundos_hasta_informe(pos.bs, self._ahora, self._cfg.tecnicos)
        acciones.append(Programar(f"{T_BS_INFORME}:{ticker}", espera if espera > 0 else 60.0, {"ticker": ticker}))
        return acciones

    def _cerrar_bs_si_toca(self, pos: PosicionTicker, dentro_de_emergencia: bool) -> list[Accion]:
        """R-G-01 (3) / R-G-03: fin del protocolo con la posición a cero; veto de reentrada hasta /sigue X."""
        if (pos.bs is None and pos.estado is not EstadoTicker.BS) or pos.neta < 0:
            return []
        texto = self._texto_informe(pos) if (dentro_de_emergencia and pos.bs is not None) else None
        aviso, veto = cisne_negro.al_cerrar(pos, dentro_de_emergencia, texto_informe=texto)
        acciones: list[Accion] = [aviso] if aviso is not None else []
        pos.bs = None
        if pos.estado is EstadoTicker.BS:
            pos.estado = EstadoTicker.NORMAL
            pos.motivo_estado = ""
            pos.desde = self._ahora
        pos.sin_reentrada_hasta_sigue = bool(veto)
        self._cierre_humano.discard(pos.ticker)
        acciones += [Anotar("bs", {"ticker": pos.ticker, "evento": "cerrado", "dentro_de_emergencia": dentro_de_emergencia,
                                   "regla": "R-G-03"}),
                     Desprogramar(f"{T_BS_INFORME}:{pos.ticker}")]
        return acciones

    def _fogonazo(self, ticker: str) -> list[Accion]:
        """R-G-01 (4): un salto ≥ 50 % en la ventana de 5 min se anota una vez (con o sin posición)."""
        ultima = self._fogonazo_revisado_en.get(ticker)
        if ultima is not None and self._ahora - ultima < FOGONAZO_REVISION_S:
            return []
        self._fogonazo_revisado_en[ticker] = self._ahora
        historial = self._hist.get(ticker)
        if not historial:
            return []
        while historial and self._ahora - historial[0][0] > FOGONAZO_VENTANA_S:
            historial.popleft()
        visto = cisne_negro.fogonazo_visto(list(historial), FOGONAZO_UMBRAL_PCT)
        if visto is None or self._fogonazo_anotado.get(ticker) == visto["t_inicio"]:
            return []
        self._fogonazo_anotado[ticker] = visto["t_inicio"]
        return [Anotar("fogonazo", {"ticker": ticker, **visto, "regla": "R-G-01 (4)"})]

    # ── locates (F9) ───────────────────────────────────────────────────
    def _locates_deshabilitado(self) -> bool:
        estado = self._estado
        return (estado.locates_deshabilitados or estado.control_humano or not self._vigilando_efectivo()
                or self._diario_roto())

    def _precio_locate(self, ticker: str) -> Optional[Decimal]:
        cot = self._cot(ticker)
        if cot is not None and _es_precio(cot.last):
            return cot.last
        return self._radar_precio.get(ticker)

    def _paso_locate(self, ticker: str, e: EstrategiaConfig, *, estimacion: Optional[list] = None,
                     ret: Optional[MsgSLRet] = None, orden: Optional[MsgSLOrder] = None,
                     deshabilitado: Optional[bool] = None) -> list[Accion]:
        """F9: `locates.siguiente_paso` y su reductor sobre el estado (el mismo que aplica el diario, H-2)."""
        estado = self._estado
        loc = estado.locates.get((ticker, e.strategy_id))
        precio = self._precio_locate(ticker)
        qty = None
        if loc is None and estimacion is not None and precio is not None:
            qty = locates.cantidad_a_localizar(e, estimacion, precio)
        ruta = ret.ruta if ret is not None else (orden.ruta if orden is not None else None)
        crudas = locates.siguiente_paso(
            loc, e, ticker, precio, self._ahora, self._cfg.locates, estado.gasto_locates_dia, estado.cuenta.equity,
            self._locates_deshabilitado() if deshabilitado is None else deshabilitado, ret, self._tokens_locate,
            qty=qty, orden=orden, minimo_cargo=self._minimo_cargo.get(ruta) if ruta else None, ahora_et=self._ahora_et)
        nuevo = locates.aplicar_anotaciones(loc, crudas)
        if nuevo is not None:
            estado.locates[(ticker, e.strategy_id)] = nuevo
        estado.gasto_locates_dia += locates.gasto_de(crudas)
        for a in crudas:
            if isinstance(a, LocateInquire):
                self._inquires.append((ticker, e.strategy_id))
        return crudas

    def _t_locate_inquire(self, clave: str, datos: dict) -> list[Accion]:
        partes = clave.split(":")
        ticker = str(datos.get("ticker") or (partes[1] if len(partes) > 1 else ""))
        sid = str(datos.get("strategy_id") or (partes[2] if len(partes) > 2 else ""))
        e = self._estrategia(sid)
        if not ticker or e is None:
            return []
        return self._paso_locate(ticker, e)

    def _msg_slret(self, m: MsgSLRet) -> list[Accion]:
        """F9: el `%SLRET` se atribuye a la consulta pendiente MÁS ANTIGUA de ese ticker (FIFO); un fallo en compra, a la compra."""
        ticker = m.ticker
        sid: Optional[str] = None
        for i, (t, s) in enumerate(self._inquires):
            if t == ticker:
                sid = s
                del self._inquires[i]
                break
        if sid is None:
            comprando = [s for (t, s), loc in sorted(self._estado.locates.items())
                         if t == ticker and loc.estado == locates.ESTADO_COMPRANDO]
            sid = comprando[0] if comprando else None
        e = self._estrategia(sid)
        if e is None:
            return [Anotar("slret_sin_consulta", {"ticker": ticker, "tipo": m.tipo, "ruta": m.ruta, "notas": m.notas})]
        return self._paso_locate(ticker, e, ret=m)

    def _msg_slorder(self, m: MsgSLOrder) -> list[Accion]:
        """F9 / R-H-02: `%SLOrder` casado por token (o id); un Located que es una SEGUNDA compra no pedida deshabilita locates.

        Un Located ya contabilizado (su id) no vuelve a pasar por la máquina:
        `GET LOCATES` repite en cada barrido TODAS las compras del día y la de
        un parcial anterior (otro id, otro token) se cobraría otra vez o se
        tomaría por una compra repetida.
        """
        ticker = m.ticker
        if m.id in self._slorders_cobrados:
            return []
        casado: Optional[str] = None
        for (t, s), loc in sorted(self._estado.locates.items()):
            if t != ticker:
                continue
            if (m.token is not None and loc.token == m.token) or (loc.id_das is not None and loc.id_das == m.id):
                casado = s
                break
        e = self._estrategia(casado)
        if e is None:
            if m.id in self._slorders_ajenos:
                return []
            self._slorders_ajenos.add(m.id)
            return [Anotar("locate_ajeno", {"ticker": ticker, "id": m.id, "token": m.token, "estado": m.estado})]
        acciones: list[Accion] = []
        estado_das = str(m.estado).strip().lower()
        if estado_das == "located":
            self._slorders_cobrados.add(m.id)
        if estado_das == "located" and locates.compra_repetida(self._estado.locates, ticker, e.strategy_id, id_das=m.id):
            self._estado.locates_deshabilitados = True
            acciones += [Anotar("locates_deshabilitar", {"ticker": ticker, "strategy_id": e.strategy_id, "id": m.id,
                                                         "regla": "R-H-02"}),
                         Avisar(Nivel.MAXIMO, Grupo.B, f"Locates: segunda compra NO pedida en "
                                                       f"{avisos.escapar_html(ticker)} (id {m.id}); módulo de locates "
                                                       f"DESHABILITADO (R-H-02)", clave="locates_deshabilitados")]
        if estado_das == "offered" and self._locates_deshabilitado():
            return acciones + [LocateOferta(m.id, False),
                               Anotar(locates.ANOTACION_ESTADO, {"ticker": ticker, "strategy_id": e.strategy_id,
                                                                 "id_das_rechazada": m.id,
                                                                 "motivo": "oferta con locates deshabilitados"})]
        return acciones + self._paso_locate(ticker, e, orden=m, deshabilitado=False)

    def _msg_slreuse(self, m: MsgSLReuse) -> list[Accion]:
        """EP-9: `SLReuseQueryRet` → el locate ya usado se libera (Yes) o vuelve a buscar con el coste TOTAL (No)."""
        ticker = m.ticker
        pos = self._estado.posiciones.get(ticker)
        acciones: list[Accion] = []
        for (t, sid), loc in sorted(self._estado.locates.items()):
            if t != ticker or loc.usadas <= 0:
                continue
            if pos is not None and any(lote.strategy_id == sid and lote.estado in _LOTE_VIVO for lote in pos.lotes.values()):
                continue
            veredicto = locates.tras_reentrada(loc, m)
            if veredicto == locates.REUSO_REUTILIZA:
                datos = {"ticker": t, "strategy_id": sid, "usadas": 0, "reutilizable": True, "regla": "EP-9"}
            elif veredicto == locates.ESTADO_BUSCANDO:
                datos = {"ticker": t, "strategy_id": sid, "estado": locates.ESTADO_BUSCANDO, "reutilizable": False,
                         "regla": "EP-9"}
            else:
                continue
            anotacion = Anotar(locates.ANOTACION_ESTADO, datos)
            nuevo = locates.aplicar_anotaciones(loc, [anotacion])
            if nuevo is not None:
                self._estado.locates[(t, sid)] = nuevo
            acciones.append(anotacion)
        self._reuso_consultado.discard(ticker)
        return acciones

    # ═══════════════════════════ reconciliación (F10) ══════════════════════
    def _reconciliar(self, foto: tuple) -> list[Accion]:
        """F10 (R-K-01/02/03, R-C-10): `comparar` → `acciones` (adopta, protege, pausa, cierra lotes, DAS manda)."""
        pos_das, ord_das, _trades = foto
        estado = self._estado
        estado.ultima_respuesta_barrido_en = self._ahora
        acciones = self._cerrar_sin_eco(ord_das)
        excluir = (self._manual | self._cierre_humano
                   | {t for t, hasta in self._stop_bloqueo.items() if hasta > self._ahora})
        pos_filtradas = {t: m for t, m in pos_das.items() if t not in excluir}
        ord_filtradas = {i: m for i, m in ord_das.items() if str(m.ticker).strip() not in excluir}
        discrepancias = [d for d in reconciliacion.comparar(estado, pos_filtradas, ord_filtradas, estado.dia, self._cfg,
                                                            ahora=self._ahora, limit_up_de=self._limit_up)
                         if d.ticker not in excluir]
        acciones += self._absorber(reconciliacion.acciones(discrepancias, estado, self._cot, self._cfg,
                                                           self._tokens.siguiente, self._ahora_et, self._ruta_stop(),
                                                           self._limit_up))
        acciones.append(Anotar("reconciliacion", {"casos": {d.ticker: d.caso for d in discrepancias},
                                                  "posiciones": len(pos_das), "ordenes": len(ord_das)}))
        era_degradado = "reconciliacion" in estado.modo_degradado
        estado.reconciliacion_ok_en = self._ahora
        estado.modo_degradado.discard("reconciliacion")
        if era_degradado and self._reconciliacion_avisada:
            self._reconciliacion_avisada = False
            acciones.append(Avisar(Nivel.INFO, Grupo.B, "Reconciliación con DAS recuperada (R-K-03)",
                                   clave="reconciliacion_recuperada"))
        return acciones

    def _cerrar_sin_eco(self, ord_das: dict) -> list[Accion]:
        """Riesgo 3: una orden nuestra en Sending sin id que un barrido COMPLETO no lista pasado SIN_ECO_S no salió → Closed."""
        if self._barrido_pedido_en is None:
            return []
        tokens_das = {m.token for m in ord_das.values()}
        acciones: list[Accion] = []
        for o in list(self._estado.ordenes.values()):
            if (o.estado is EstadoOrden.SENDING and o.id_das is None and o.token not in tokens_das
                    and o.enviada_en < self._barrido_pedido_en - reconciliacion.SIN_ECO_S):
                o.estado = EstadoOrden.CLOSED
                o.notas = "sin eco de DAS"
                acciones.append(Anotar("orden_estado", {"token": o.token, "ticker": o.ticker, "estado": o.estado.value,
                                                        "motivo": "sin eco de DAS (riesgo 3)"}))
                acciones += self._revisar_cuadre(o)
        return acciones

    # ═══════════════════════════ temporizadores ════════════════════════════
    def _temporizador(self, clave: str, datos: Any) -> list[Accion]:
        datos = dict(datos) if isinstance(datos, dict) else {}
        if not isinstance(clave, str) or not clave:
            return [Anotar("temporizador_desconocido", {"clave": clave})]
        base = clave.split(":", 1)[0]
        manejador = self._manejadores().get(base)
        if manejador is None:
            return [Anotar("temporizador_desconocido", {"clave": clave})]
        if base in _GLOBALES:
            return self._proteger(None, f"temporizador:{base}", lambda: manejador(clave, datos))
        return self._proteger(self._ticker_de_temporizador(base, clave, datos), f"temporizador:{base}",
                              lambda: manejador(clave, datos))

    def _manejadores(self) -> dict[str, Callable[[str, dict], list[Accion]]]:
        return {
            T_CRUCE: self._t_cruce, T_CANCEL_ESPERA: self._t_cancel_espera, T_CRUCE_ESPERA: self._t_cruce_espera,
            T_STOPS_AJUSTAR: self._t_plan, T_STOPS_PLAN: self._t_plan, T_REPLACE_VERIFICAR: self._t_replace_verificar,
            T_TP_CRUCE: self._t_tp_cruce, T_TP_ESPERA_ENTRADA: self._t_tp_espera_entrada,
            T_HORA_AGREGAR: self._t_hora_agregar, T_HORA_ASK: self._t_hora_ask, T_EOD_COMPROBAR: self._t_eod_comprobar,
            T_PERSEGUIR_ASK: self._t_perseguir_ask, T_HALT_DECIDIR: self._t_halt_decidir,
            T_HALT_PRIMERA_VELA: self._t_halt_primera_vela, T_SIMSTATUS: self._t_simstatus, T_BARRIDO: self._t_barrido,
            T_BS_INFORME: self._t_bs_informe, T_BS_CIERRE: self._t_bs_cierre, T_LOCATE_INQUIRE: self._t_locate_inquire,
            T_STOP_REINTENTO: self._t_stop_reintento, T_REINTENTO_RECHAZO: self._t_reintento_rechazo,
            T_LOCATE_RECOMPRAR: self._t_locate_recomprar, T_CERRAR_TODO: self._t_cerrar_todo,
            T_DAS_AVISO: self._t_das_aviso, T_DAS_RECONECTAR: self._t_das_reconectar, T_FOTO: self._t_foto,
        }

    def _ticker_de_temporizador(self, base: str, clave: str, datos: dict) -> Optional[str]:
        ticker = datos.get("ticker")
        if isinstance(ticker, str) and ticker:
            return ticker
        resto = clave.split(":", 1)[1] if ":" in clave else ""
        if base in (T_REPLACE_VERIFICAR, T_PERSEGUIR_ASK, T_STOP_REINTENTO, T_REINTENTO_RECHAZO, T_LOCATE_RECOMPRAR):
            try:
                o = self._estado.ordenes.get(int(resto))
            except ValueError:
                o = None
            return o.ticker if o is not None else None
        if base in (T_TP_CRUCE, T_HORA_AGREGAR, T_HORA_ASK, T_EOD_COMPROBAR):
            return resto.split("|", 1)[0] or None
        if base == T_LOCATE_INQUIRE:
            return resto.split(":", 1)[0] or None
        return resto or None

    def _pos_de(self, clave: str, datos: dict) -> Optional[PosicionTicker]:
        ticker = datos.get("ticker") or (clave.split(":", 1)[1] if ":" in clave else None)
        return self._estado.posiciones.get(str(ticker)) if ticker else None

    def _t_cruce(self, clave: str, datos: dict) -> list[Accion]:
        """F1.7: al llegar t_limite, `al_vencer`: orden viva → cancelar (y el resto tras Canceled); si no, cruzar o cerrar."""
        pos = self._pos_de(clave, datos)
        intento = pos.intento if pos is not None else None
        if (pos is None or intento is None or intento.fase is FaseIntento.TERMINADO
                or pos.ticker in self._intento_pausado or pos.ticker in self._intento_en_reintento):
            return []
        self._soltar_cuadrados(intento)
        if intento.token_agregar is not None or intento.token_cruce is not None:
            return self._cancelar_intento(pos, MOTIVO_VENCER)
        fase, motivo = entrada.al_vencer(intento, self._cot(pos.ticker), self._cfg)
        if fase is FaseIntento.CRUZANDO:
            return self._enviar_cruce(pos)
        if fase is FaseIntento.TERMINADO:
            return self._cerrar_intento(pos, motivo or entrada.MOTIVO_FIN_LLENA)
        return []

    def _t_cancel_espera(self, clave: str, datos: dict) -> list[Accion]:
        """F1.7: sin `Canceled` todavía → GET ORDERS (y GET TRADES si ya es terminal sin cuadrar); tras 6 intentos se cierra."""
        pos = self._pos_de(clave, datos)
        intento = pos.intento if pos is not None else None
        if pos is None or intento is None or intento.fase is not FaseIntento.CANCELANDO:
            return []                     # temporizador de una espera ya resuelta: la orden viva es otra
        self._soltar_cuadrados(intento)
        pendientes = [self._estado.ordenes[t] for t in (intento.token_agregar, intento.token_cruce)
                      if t is not None and t in self._estado.ordenes]
        if not pendientes:
            return self._avanzar_intento(pos)
        n = int(datos.get("n", 0)) + 1
        if n > CANCEL_ESPERA_MAX:
            for o in pendientes:
                if intento.token_agregar == o.token:
                    intento.token_agregar = None
                if intento.token_cruce == o.token:
                    intento.token_cruce = None
            self._poner_motivo(pos.ticker, MOTIVO_SIN_CONFIRMAR)
            return [Avisar(Nivel.AVISO, Grupo.B, f"{avisos.escapar_html(pos.ticker)}: DAS no confirmó la cancelación de la "
                                                 f"entrada en {CANCEL_ESPERA_S * CANCEL_ESPERA_MAX:.0f} s; se cierra el "
                                                 f"intento con lo llenado y manda la reconciliación",
                           clave=f"cancel_sin_confirmar:{pos.ticker}")] + self._avanzar_intento(pos)
        acciones: list[Accion] = []
        for o in pendientes:
            if o.token in self._cancelar_al_aceptar and o.id_das is not None and o.estado in _VIVOS:
                motivo = self._cancelar_al_aceptar.pop(o.token)       # la cancelación diferida: ya se sabe su id
                acciones += self._absorber([Cancelar(id_das=o.id_das, token=o.token, motivo=motivo)])
        acciones.append(Consultar(rechazos.COMANDO_ORDENES))
        if any(o.estado in _TERMINALES for o in pendientes):
            acciones.append(Consultar(reconciliacion.COMANDO_TRADES))
        acciones.append(Programar(f"{T_CANCEL_ESPERA}:{pos.ticker}", CANCEL_ESPERA_S, {"ticker": pos.ticker, "n": n}))
        return acciones

    def _t_cruce_espera(self, clave: str, datos: dict) -> list[Accion]:
        """F1.8: el cruce no llenó entero en `cruce_espera_s` → cancelar; tras el Canceled, un reintento con el bid nuevo."""
        pos = self._pos_de(clave, datos)
        intento = pos.intento if pos is not None else None
        if pos is None or intento is None or intento.token_cruce is None:
            return []
        o = self._estado.ordenes.get(intento.token_cruce)
        if o is None or self._cuadrada(o):
            return []
        return self._cancelar_intento(pos, MOTIVO_CRUCE_ESPERA)

    def _t_plan(self, clave: str, datos: dict) -> list[Accion]:
        ticker = str(datos.get("ticker") or clave.split(":", 1)[1])
        self._espera_plan.discard(ticker)
        return self._plan(ticker)

    def _t_replace_verificar(self, clave: str, datos: dict) -> list[Accion]:
        """F2.2 / 2h.8: tras un REPLACE, si el tipo perdió el pre/post se repone (nueva y luego cancelar); si la qty no cuadra, plan."""
        token = datos.get("token")
        o = self._estado.ordenes.get(token) if isinstance(token, int) else None
        if o is None or o.estado not in _VIVOS:
            self._verificaciones.pop(token, None)
            return []
        patron = self._cfg.stops.get("tipo_esperado_en_order")
        conserva = stops.tipo_conserva_pp(o.tipo_das_crudo, patron)
        if (conserva is False and o.tipo is TipoOrden.STOP_LIMITE_PP and o.stop is not None and o.precio is not None
                and o.id_das is not None and _qty_viva(o) > 0):
            pos = self._pos(o.ticker)
            nueva = OrdenNueva(token=self._tokens.siguiente(), lado=o.lado, ticker=o.ticker, ruta=o.ruta,
                               qty=_qty_viva(o), tipo=TipoOrden.STOP_LIMITE_PP, precio=o.precio, stop=o.stop,
                               tif="DAY+", proposito=o.proposito, lote_id=o.lote_id, nivel=o.nivel,
                               version=pos.version_stops)
            self._verificaciones.pop(o.token, None)
            acciones: list[Accion] = [Anotar("replace_sin_pp", {"ticker": o.ticker, "token": o.token,
                                                                "tipo_das_crudo": o.tipo_das_crudo,
                                                                "token_nuevo": nueva.token, "regla": "2h.8"})]
            acciones += self._absorber([EnviarOrden(nueva, serie=stops.serie_stops(o.ticker))])
            acciones += self._absorber([Cancelar(o.id_das, o.token, "2h.8: el REPLACE perdió el pre/post; se repone")])
            return acciones
        if conserva is None and patron:
            n = self._verificaciones.get(o.token, 0) + 1
            self._verificaciones[o.token] = n
            if n < REPLACE_VERIFICAR_MAX:
                return [Programar(f"{T_REPLACE_VERIFICAR}:{o.token}", stops.VERIFICAR_REPLACE_EN_S, dict(datos))]
            self._verificaciones.pop(o.token, None)
            return [Avisar(Nivel.AVISO, Grupo.B, f"{avisos.escapar_html(o.ticker)}: sin %ORDER tras el REPLACE del stop "
                                                 f"{o.token}; no se sabe si conserva el pre/post (2h.8)",
                           clave=f"replace_sin_tipo:{o.token}")]
        self._verificaciones.pop(o.token, None)
        objetivo = datos.get("qty_objetivo")
        if isinstance(objetivo, int) and _qty_viva(o) != objetivo and o.token not in self._reemplazo_pedido:
            return self._plan(o.ticker)
        return []

    def _t_tp_cruce(self, clave: str, datos: dict) -> list[Accion]:
        """F4.3 (R-D-03 v2): el TP no llenó agregando → cancelar y, con el Canceled, `tp_al_vencer` con el resto CONFIRMADO."""
        pos = self._pos_de(clave, datos)
        lote = pos.lotes.get(str(datos.get("lote_id"))) if pos is not None else None
        token = datos.get("token")
        o = self._estado.ordenes.get(token) if isinstance(token, int) else None
        if pos is None or lote is None or o is None:
            return []
        if o.estado in _VIVOS and _qty_viva(o) > 0:
            self._continuacion[o.token] = (T_TP_CRUCE, {"lote_id": lote.id, "ticker": pos.ticker})
            return self._cancelar_orden(o, "R-D-03 v2: el TP no llenó agregando; se cruza el resto")
        return self._tp_resto(pos, lote, o) if self._cuadrada(o) else []

    def _tp_resto(self, pos: PosicionTicker, lote: Lote, o: Orden) -> list[Accion]:
        if lote.estado not in _LOTE_VIVO or pos.estado is EstadoTicker.BS:
            return []
        resto = min(max(o.qty - o.llenas, 0), self._libres(pos, lote))
        if resto <= 0:
            return []
        orden, aviso = salidas.tp_al_vencer(lote, resto, self._cot(pos.ticker), self._cfg, self._tokens.siguiente,
                                            self._ahora_et)
        acciones: list[Accion] = []
        if orden is not None:
            acciones += self._absorber([EnviarOrden(orden)])
        if aviso is not None:
            acciones.append(aviso)
        return acciones

    def _t_tp_espera_entrada(self, clave: str, datos: dict) -> list[Accion]:
        """R-D-07: la entrada retenida (o el intento en pausa) sigue cuando ya no queda ninguna salida viva en el ticker."""
        ticker = str(datos.get("ticker") or clave.split(":", 1)[1])
        if self._salidas_vivas(ticker):
            return [Programar(f"{T_TP_ESPERA_ENTRADA}:{ticker}", TP_ESPERA_ENTRADA_S, {"ticker": ticker})]
        acciones: list[Accion] = []
        pos = self._estado.posiciones.get(ticker)
        if ticker in self._intento_pausado:
            self._intento_pausado.discard(ticker)
            if pos is not None and pos.intento is not None:
                acciones += self._avanzar_intento(pos)
        for s in self._entradas_en_espera.pop(ticker, []):
            acciones += self._entrada(s)
        return acciones

    def _lote_de_datos(self, clave: str, datos: dict) -> tuple[Optional[PosicionTicker], Optional[Lote]]:
        pos = self._pos_de(clave, datos)
        lote_id = datos.get("lote_id") or (clave.split(":", 1)[1] if ":" in clave else None)
        if pos is None and lote_id:
            pos = self._estado.posiciones.get(str(lote_id).split("|", 1)[0])
        lote = pos.lotes.get(str(lote_id)) if pos is not None and lote_id else None
        return pos, lote

    def _salida_bloqueada(self, pos: PosicionTicker) -> bool:
        return pos.estado is EstadoTicker.BS or pos.ticker in self._manual or pos.ticker in self._cierre_humano

    def _t_hora_agregar(self, clave: str, datos: dict) -> list[Accion]:
        """F5 / R-D-08: un minuto antes de la hora, el lote AGREGA su salida en el punto medio (PostOnly)."""
        pos, lote = self._lote_de_datos(clave, datos)
        if pos is None or lote is None or lote.estado not in _LOTE_VIVO or lote.llenas <= 0 or self._salida_bloqueada(pos):
            return []
        qty = self._libres(pos, lote)
        cot = self._cot(pos.ticker)
        if qty <= 0 or not _libro_utilizable(cot):
            return [Anotar("salida_hora", {"ticker": pos.ticker, "lote_id": lote.id, "paso": "agregar",
                                           "motivo": "sin acciones libres o sin libro; decide hora_ask"})]
        proposito = _proposito(datos.get("proposito"), Proposito.HORA_AGREGAR)
        orden = salidas.orden_hora_agregar(lote, qty, cot, self._cfg, self._tokens.siguiente, self._ahora_et, proposito)
        return [Anotar("salida_hora", {"ticker": pos.ticker, "lote_id": lote.id, "paso": "agregar", "qty": qty,
                                       "motivo": datos.get("motivo"), "regla": "R-D-08"})] + self._absorber([EnviarOrden(orden)])

    def _t_hora_ask(self, clave: str, datos: dict) -> list[Accion]:
        """F5: a la hora, se cancela lo vivo del lote y, CONFIRMADO el Canceled, todo al ask sin tope y a perseguir."""
        pos, lote = self._lote_de_datos(clave, datos)
        if pos is None or lote is None or lote.estado not in _LOTE_VIVO or lote.llenas <= 0 or self._salida_bloqueada(pos):
            return []
        proposito = (Proposito.CIERRE_REINICIO if datos.get("proposito") == Proposito.CIERRE_REINICIO.value
                     else Proposito.HORA_ASK)
        vivas = [o for o in self._vivas(pos.ticker) if o.lote_id == lote.id and o.proposito in _PROP_SALIDA_LOTE]
        if not vivas:
            return self._hora_al_ask(pos, lote, proposito)
        acciones: list[Accion] = []
        for o in vivas:
            self._continuacion[o.token] = (T_HORA_ASK, {"lote_id": lote.id, "ticker": pos.ticker,
                                                        "proposito": proposito.value})
            acciones += self._cancelar_orden(o, "R-D-08: a la hora se cancela lo vivo y se va al ask")
        return acciones

    def _hora_al_ask(self, pos: PosicionTicker, lote: Lote, proposito: Proposito) -> list[Accion]:
        if lote.estado not in _LOTE_VIVO or lote.llenas <= 0:
            return []
        if any(o.lote_id == lote.id and o.proposito in _PROP_SALIDA_LOTE for o in self._vivas(pos.ticker)):
            return []
        qty = self._libres(pos, lote)
        cot = self._cot(pos.ticker)
        if qty <= 0:
            return []
        if cot is None or not _es_precio(cot.ask):
            return [Avisar(Nivel.AVISO, Grupo.B, f"{avisos.escapar_html(pos.ticker)}: hora de salida sin ask en DAS; se "
                                                 f"reintenta en 1 s", clave=f"hora_sin_ask:{lote.id}"),
                    Programar(salidas.clave_lote(T_HORA_ASK, lote.id), PERSEGUIR_ASK_CADA_S,
                              {"lote_id": lote.id, "ticker": pos.ticker, "proposito": proposito.value})]
        orden = salidas.orden_al_ask(lote, qty, cot, self._cfg, self._tokens.siguiente, self._ahora_et, None, proposito)
        self._persecuciones[orden.token] = 0
        return ([Anotar("salida_hora", {"ticker": pos.ticker, "lote_id": lote.id, "paso": "al_ask", "qty": qty,
                                        "precio": orden.precio, "regla": "R-D-08"})]
                + self._absorber([EnviarOrden(orden)])
                + [Programar(f"{T_PERSEGUIR_ASK}:{orden.token}", self._perseguir_cada(),
                             {"token": orden.token, "ticker": pos.ticker, "lote_id": lote.id})])

    def _perseguir_cada(self) -> float:
        return _segundos((self._cfg.salidas or {}).get("por_hora") or {}, "perseguir_ask_s", PERSEGUIR_ASK_CADA_S)

    def _t_perseguir_ask(self, clave: str, datos: dict) -> list[Accion]:
        """Corrección 11: sin fill, `Reemplazar` de PRECIO al ask nuevo, como mucho 3 veces (nunca cancelar + nueva)."""
        token = datos.get("token")
        o = self._estado.ordenes.get(token) if isinstance(token, int) else None
        if o is None or o.estado not in _VIVOS or _qty_viva(o) <= 0:
            self._persecuciones.pop(token, None)
            return []
        bloque = (self._cfg.salidas or {}).get("por_hora") or {}
        maximo = bloque.get("perseguir_ask_max", PERSEGUIR_ASK_MAX)
        maximo = maximo if type(maximo) is int and maximo >= 0 else PERSEGUIR_ASK_MAX
        hechas = self._persecuciones.get(o.token, 0)
        acciones: list[Accion] = []
        reemplazo = salidas.perseguir_ask(o, self._cot(o.ticker), hechas, maximo)
        if reemplazo is not None:
            hechas += 1
            self._persecuciones[o.token] = hechas
            pos = self._pos(o.ticker)
            pos.persecuciones_ask += 1
            acciones += self._absorber([reemplazo])
            acciones.append(Anotar("persecucion_ask", {"ticker": o.ticker, "token": o.token, "n": hechas,
                                                       "precio": reemplazo.precio, "regla": "corrección 11"}))
        if hechas < maximo:
            acciones.append(Programar(f"{T_PERSEGUIR_ASK}:{o.token}", self._perseguir_cada(), dict(datos)))
        return acciones

    def _t_eod_comprobar(self, clave: str, datos: dict) -> list[Accion]:
        """F5 / R-D-02: +30 s tras la hora, si al lote le quedan acciones → aviso 3 y el ticker a CONTROL_HUMANO."""
        pos, lote = self._lote_de_datos(clave, datos)
        if pos is None or lote is None:
            return []
        aviso = salidas.comprobar_eod(lote, pos)
        if aviso is None:
            return []
        acciones: list[Accion] = [aviso]
        if pos.estado in (EstadoTicker.NORMAL, EstadoTicker.PAUSADO, EstadoTicker.HALT):
            pos.estado = EstadoTicker.CONTROL_HUMANO
            pos.motivo_estado = "R-D-02: EOD sin cerrar"
            pos.desde = self._ahora
            acciones.append(Anotar("pausa", {"ticker": pos.ticker, "estado": EstadoTicker.CONTROL_HUMANO.value,
                                             "motivo": "R-D-02: EOD sin cerrar", "lote_id": lote.id}))
        return acciones

    def _t_simstatus(self, clave: str, datos: dict) -> list[Accion]:
        """F6.1: `GET SymStatus X` cada 1 s SOLO para tickers con posición o intento; LDLU cada minuto en RTH."""
        tickers = sorted(t for t, p in self._estado.posiciones.items() if self._tiene_posicion(p) or p.intento is not None)
        if not tickers or not self._estado.das_conectado:
            self._simstatus_armado = bool(tickers)
            return [Programar(T_SIMSTATUS, SIMSTATUS_CADA_S, {})] if tickers else []
        acciones: list[Accion] = [Consultar(f"GET SymStatus {t}") for t in tickers]
        if self._es_rth() and (self._ultimo_ldlu_en is None or self._ahora - self._ultimo_ldlu_en >= LDLU_CADA_S):
            self._ultimo_ldlu_en = self._ahora
            acciones += [Consultar(f"GET LDLU {t}") for t in tickers]
        acciones.append(Programar(T_SIMSTATUS, SIMSTATUS_CADA_S, {}))
        self._simstatus_armado = True
        return acciones

    def _armar_simstatus(self) -> list[Accion]:
        if self._simstatus_armado:
            return []
        self._simstatus_armado = True
        return [Programar(T_SIMSTATUS, SIMSTATUS_CADA_S, {})]

    def _t_barrido(self, clave: str, datos: dict) -> list[Accion]:
        """F10 / R-K-01: GET POSITIONS/ORDERS(/TRADES)/BP/LOCATES con la cadencia adaptativa; el volcado se junta aparte."""
        estado = self._estado
        acciones: list[Accion] = []
        if estado.das_conectado:
            ventana = _segundos(self._cfg.tecnicos.get("barrido_s") or {}, "ventana_tras_fill_s", 60.0)
            tras_fill = estado.ultimo_fill_en is not None and self._ahora - estado.ultimo_fill_en < ventana
            self._acumulador.iniciar(self._ahora, con_trades=tras_fill)
            self._barrido_pedido_en = self._ahora
            acciones += reconciliacion.comandos_barrido(tras_fill)
        cadencia = reconciliacion.cadencia_barrido(estado, self._ahora, self._cfg.tecnicos)
        self._barrido_siguiente_en = self._ahora + cadencia
        acciones.append(Programar(T_BARRIDO, cadencia, {"motivo": "cadencia (R-K-01)"}))
        return acciones

    def _t_bs_cierre(self, clave: str, datos: dict) -> list[Accion]:
        """F7 / R-D-06: reintento del cierre humano durante el protocolo con la neta de ESE momento."""
        pos = self._pos_de(clave, datos)
        if pos is None:
            return []
        acciones = self._absorber(cisne_negro.cierre_humano(
            pos, self._ordenes_ticker(pos.ticker), self._cot(pos.ticker), datos.get("n"), self._cfg,
            self._tokens.siguiente, self._ahora_et, intento=int(datos.get("intento") or 0),
            objetivo=datos.get("objetivo"), signo=datos.get("signo")))
        self._fin_cierre_humano(pos.ticker, acciones)
        return acciones

    def _fin_cierre_humano(self, ticker: str, acciones: list[Accion]) -> None:
        fin = any(isinstance(a, Anotar) and a.tipo == "cierre_humano_fin" for a in acciones)
        agotado = any(isinstance(a, Avisar) and (a.clave or "").endswith(":agotado") for a in acciones)
        if fin or agotado:
            self._cierre_humano.discard(ticker)

    def _t_cerrar_todo(self, clave: str, datos: dict) -> list[Accion]:
        """R-D-06: reintento de «cerrar todo» con la neta de ESE momento; agotado → aviso 3 y los stops vuelven a mandar."""
        tickers = [str(t) for t in datos.get("tickers") or []]
        acciones = self._absorber(salidas.cerrar_todo(
            self._estado.posiciones, self._cot, self._cfg, self._tokens.siguiente, self._ahora_et,
            _proposito(datos.get("proposito"), Proposito.CIERRE_HUMANO), int(datos.get("intento") or 0), tickers))
        sigue = any(isinstance(a, Programar) for a in acciones)
        if not sigue:
            for t in tickers:
                self._cierre_humano.discard(t)
                acciones += self._plan(t)
        return acciones

    def _t_stop_reintento(self, clave: str, datos: dict) -> list[Accion]:
        """R-C-03: el stop rechazado se repone con `stops.plan` (idempotente) llevando la cuenta de intentos."""
        ticker = str(datos.get("ticker") or "")
        pos = self._estado.posiciones.get(ticker)
        if pos is None or pos.estado is EstadoTicker.BS or pos.neta >= 0:
            return []
        if self._stop_bloqueo.get(ticker, -math.inf) != math.inf:
            self._stop_bloqueo.pop(ticker, None)       # se acabó la separación de R-C-03: el plan repone
        if (datos.get("proposito") == Proposito.STOP_PROTECCION.value and datos.get("lote_id") is None
                and not self._lotes_vivos(pos)):
            intento = int(datos.get("intento") or 0)
            primero = datos.get("primer_intento_en")
            falta = stops.descubiertas(pos, self._ordenes_ticker(ticker), self._cfg.stops, self._limit_up(ticker))
            cot = self._cot(ticker)
            ultimo = cot.last if cot is not None and _es_precio(cot.last) else pos.avg_das
            if falta <= 0 or not _es_precio(ultimo):
                return []
            pct = _pct(self._cfg.stops, "proteccion_desconocidas_pct", STOP_PROTECCION_PCT)
            orden = stops.stop_proteccion(ticker, falta, True, ultimo, pct, self._tokens.siguiente(), self._ruta_stop(),
                                          pos.version_stops)
            self._meta_orden[orden.token] = (intento, float(primero) if isinstance(primero, (int, float)) else self._ahora)
            return self._absorber([EnviarOrden(orden)])
        return self._plan(ticker)          # la orden nueva hereda la cuenta de intentos de su propósito (_stop_intentos)

    def _t_reintento_rechazo(self, clave: str, datos: dict) -> list[Accion]:
        """R-B-07 (2) recalcular_bp: con el BP recién leído se redimensiona y se reenvía con el token NUEVO."""
        ticker = str(datos.get("ticker") or "")
        token_nuevo = datos.get("token_nuevo")
        pos = self._estado.posiciones.get(ticker)
        if pos is None or not isinstance(token_nuevo, int):
            return []
        self._meta_orden[token_nuevo] = (int(datos.get("intentos") or 0), float(datos.get("primer_intento_en") or self._ahora))
        proposito = _proposito(datos.get("proposito"), Proposito.DESCONOCIDA)
        original = self._estado.ordenes.get(datos.get("token_original"))
        if proposito in _PROP_ENTRADA:
            intento = pos.intento
            if intento is None or ticker not in self._intento_en_reintento:
                return [Anotar("reintento_descartado", {"ticker": ticker, "token": token_nuevo,
                                                        "motivo": "el intento ya no espera este reintento"})]
            self._intento_en_reintento.discard(ticker)
            pendiente = intento.qty_total - intento.llenas
            cot = self._cot(ticker)
            simb = self._mercado.simbolo(ticker)
            caben = 0
            if pendiente > 0 and cot is not None and _es_precio(cot.ask):
                try:
                    caben, _ = capital.acciones_que_caben(pendiente, cot.ask, self._estado.cuenta, simb.tasa_corta,
                                                          capital.exposicion_corta(self._estado.posiciones, self._cot),
                                                          _ALTO_RIESGO, self._ahora, self._max_edad_bp())
                except ValueError:
                    caben = 0
            if caben < pendiente or self._bloqueo_apertura(ticker) is not None:
                self._poner_motivo(ticker, MOTIVO_RECHAZO)
                return ([Avisar(Nivel.AVISO, Grupo.B, f"{avisos.escapar_html(ticker)}: tras releer el BP no caben las "
                                                      f"{pendiente} acciones pendientes ({caben}); se queda lo llenado "
                                                      f"(R-B-07)", clave=f"bp_reintento:{ticker}")]
                        + self._avanzar_intento(pos))
            if proposito is Proposito.ENTRADA_CRUCE or intento.fase is FaseIntento.CRUZANDO:
                intento.fase = FaseIntento.CRUZANDO
                orden = entrada.orden_cruce(intento, pendiente, cot, self._cfg, token_nuevo, self._ahora_et,
                                            nivel=self._nivel_intento(pos), ssr=bool(simb.ssr))
                if orden is None:
                    return self._cerrar_intento(pos, entrada.MOTIVO_FIN_BID_CAYO)
                intento.token_cruce = token_nuevo
            else:
                intento.fase = FaseIntento.AGREGANDO
                orden = entrada.orden_agregar(intento, cot, self._cfg, token_nuevo, self._ahora_et,
                                              nivel=self._nivel_intento(pos))
                intento.token_agregar = token_nuevo
            self._tokens_intento.setdefault(ticker, set()).add(token_nuevo)
            self._lotes_de_orden[token_nuevo] = list(intento.lotes)
            return self._absorber([EnviarOrden(orden)])
        if original is None:
            return []
        qty = int(datos.get("qty") or 0)
        if qty <= 0:
            return []
        orden = OrdenNueva(token=token_nuevo, lado=original.lado, ticker=ticker, ruta=original.ruta, qty=qty,
                           tipo=original.tipo, precio=original.precio if original.tipo is not TipoOrden.MERCADO else None,
                           stop=original.stop if original.tipo is TipoOrden.STOP_LIMITE_PP else None, tif="DAY+",
                           post_only=False, proposito=original.proposito, lote_id=original.lote_id,
                           nivel=original.nivel, version=original.version)
        return self._absorber([EnviarOrden(orden)])

    def _t_locate_recomprar(self, clave: str, datos: dict) -> list[Accion]:
        """R-B-07 caso locate (desviación): la entrada se cierra con lo llenado y el locate de la estrategia vuelve a buscar."""
        ticker = str(datos.get("ticker") or "")
        pos = self._estado.posiciones.get(ticker)
        if pos is None:
            return []
        lote = pos.lotes.get(str(datos.get("lote_id")))
        acciones: list[Accion] = []
        if lote is not None:
            loc = self._estado.locates.get((ticker, lote.strategy_id))
            if loc is not None and loc.estado != locates.ESTADO_NO_HACE_FALTA:
                anotacion = Anotar(locates.ANOTACION_ESTADO, {"ticker": ticker, "strategy_id": lote.strategy_id,
                                                              "estado": locates.ESTADO_BUSCANDO,
                                                              "usadas": loc.localizadas,
                                                              "motivo": "R-B-07: DAS dice que no hay locate; se recompra"})
                nuevo = locates.aplicar_anotaciones(loc, [anotacion])
                if nuevo is not None:
                    self._estado.locates[(ticker, lote.strategy_id)] = nuevo
                acciones.append(anotacion)
        acciones.append(Avisar(Nivel.AVISO, Grupo.B, f"{avisos.escapar_html(ticker)}: DAS rechazó la entrada por locate; "
                                                     f"se busca locate de nuevo y la entrada se cierra con lo llenado "
                                                     f"(R-B-07)", clave=f"locate_recomprar:{ticker}"))
        if pos.intento is not None and ticker in self._intento_en_reintento:
            self._intento_en_reintento.discard(ticker)
            self._poner_motivo(ticker, MOTIVO_RECHAZO)
            acciones += self._avanzar_intento(pos)
        return acciones

    def _t_das_aviso(self, clave: str, datos: dict) -> list[Accion]:
        """R-J-02 (3): mientras DAS siga caído, aviso 3 cada 5 min."""
        if self._estado.das_conectado or self._das_caido_desde is None:
            return []
        minutos = (self._ahora - self._das_caido_desde) / 60.0
        return [Avisar(Nivel.MAXIMO, Grupo.B, f"DAS sigue DESCONECTADO desde hace {minutos:.0f} min: no se abre ni se "
                                              f"gestiona nada; los stops siguen residentes en DAS (R-J-02)",
                       clave=f"das_caido:{int(minutos)}"),
                Programar(T_DAS_AVISO, float(DAS_AVISO_CADA_S), {})]

    def _t_das_reconectar(self, clave: str, datos: dict) -> list[Accion]:
        return [Anotar("das_reconectar", {"nota": "la reconexión la lleva el ejecutor (PlanReconexion)"})]

    def _t_foto(self, clave: str, datos: dict) -> list[Accion]:
        self._ultima_foto_en = self._ahora
        return [PublicarFoto()]

    # ═══════════════════════════ Tic, conexión y degradados (F11) ══════════
    def _tic(self) -> list[Accion]:
        """F11: volcado sin marcadores, disco, feed, reconciliación caducada, suscripciones, A7, resumen y foto."""
        acciones: list[Accion] = []
        foto = None
        try:
            foto = self._acumulador.revisar(self._ahora)
        except Exception as exc:  # noqa: BLE001 — H-5: el acumulador no debe lanzar; si lo hace se descarta el volcado
            self._acumulador.descartar()
            acciones += self._fallo(None, "acumulador", exc)
        if foto is not None:
            acciones += self._proteger(None, "reconciliacion", lambda: self._reconciliar(foto))
        acciones += self._proteger(None, "disco", self._vigilar_disco)
        acciones += self._proteger(None, "feed", self._vigilar_feed)
        acciones += self._proteger(None, "reconciliacion_caducada", self._vigilar_reconciliacion)
        acciones += self._proteger(None, "barrido_vigilancia", self._vigilar_barrido)
        acciones += self._proteger(None, "suscripciones", self._suscripciones)
        acciones += self._proteger(None, "sin_simbolo", self._sin_simbolo)
        acciones += self._proteger(None, "resumen", self._resumen_diario)
        cada = _segundos(self._cfg.tecnicos, "foto_cada_s", FOTO_CADA_S)
        if self._ultima_foto_en is None or self._ahora - self._ultima_foto_en >= cada:
            self._ultima_foto_en = self._ahora
            acciones.append(PublicarFoto())
        return acciones

    def _vigilar_disco(self) -> list[Accion]:
        """Corrección 4: diario roto → modo «disco» (no se abre nada; stops y salidas siguen) y aviso 3; al volver, aviso 1."""
        degradados = self._estado.modo_degradado
        roto = self._diario_roto()
        if roto and "disco" not in degradados:
            degradados.add("disco")
            return [Anotar("degradado", {"modo": "disco", "activo": True, "regla": "corrección 4"}),
                    Avisar(Nivel.MAXIMO, Grupo.B, "El diario NO escribe: no se abren entradas ni se compran locates; "
                                                  "stops y salidas siguen (corrección 4)", clave="disco")]
        if not roto and "disco" in degradados:
            degradados.discard("disco")
            return [Anotar("degradado", {"modo": "disco", "activo": False}),
                    Avisar(Nivel.INFO, Grupo.B, "El diario vuelve a escribir: se reanudan las entradas", clave="disco_ok")]
        return []

    def _vigilar_feed(self) -> list[Accion]:
        """R-J-01: en horario de mercado, > 30 s sin vela → prealerta al diario; > 60 s → aviso 3 y modo «feed»."""
        if not self._es_mercado(self._franja()):
            return []
        estado = self._estado
        referencia = estado.feed_ultima_vela_en if estado.feed_ultima_vela_en is not None else self._inicio_en
        if referencia is None:
            return []
        edad = self._ahora - referencia
        bloque = self._cfg.tecnicos.get("feed") or {}
        prealerta = _segundos(bloque, "prealerta_s", float(FEED_PREALERTA_S))
        emergencia = _segundos(bloque, "emergencia_s", float(FEED_EMERGENCIA_S))
        acciones: list[Accion] = []
        if edad > emergencia:
            if "feed" not in estado.modo_degradado:
                estado.modo_degradado.add("feed")
                self._feed_nivel = "emergencia"
                acciones += [Anotar("feed", {"nivel": "emergencia", "edad_s": edad, "regla": "R-J-01"}),
                             Avisar(Nivel.MAXIMO, Grupo.B, f"Feed de velas parado {edad:.0f} s: no se abren entradas; "
                                                           f"posiciones con sus stops y precio de DAS (R-J-01)",
                                    clave="feed_emergencia")]
        elif edad > prealerta:
            if self._feed_nivel == "ok":
                self._feed_nivel = "prealerta"
                acciones.append(Anotar("feed", {"nivel": "prealerta", "edad_s": edad, "regla": "R-J-01"}))
        else:
            if "feed" in estado.modo_degradado:
                estado.modo_degradado.discard("feed")
                acciones += [Anotar("feed", {"nivel": "ok", "edad_s": edad}),
                             Avisar(Nivel.INFO, Grupo.B, "Feed de velas recuperado", clave="feed_ok")]
            self._feed_nivel = "ok"
        return acciones

    def _vigilar_reconciliacion(self) -> list[Accion]:
        """R-K-03: 30 s sin respuesta al barrido con el socket vivo → modo «reconciliacion» y aviso 2."""
        estado = self._estado
        if not estado.das_conectado or self._reconciliacion_avisada:
            return []
        referencia = estado.ultima_respuesta_barrido_en
        if referencia is None:
            referencia = self._inicio_en
        tolerancia = self._max_edad_bp()
        if referencia is None or not reconciliacion.barrido_caducado(referencia, self._ahora, tolerancia):
            return []
        self._reconciliacion_avisada = True
        estado.modo_degradado.add("reconciliacion")
        return [Anotar("degradado", {"modo": "reconciliacion", "activo": True, "regla": "R-K-03"}),
                Avisar(Nivel.AVISO, Grupo.B, f"Sin respuesta al barrido de DAS en {tolerancia:.0f} s con la conexión viva: "
                                             f"no se abren entradas (R-K-03)", clave="reconciliacion_caducada")]

    def _vigilar_barrido(self) -> list[Accion]:
        if not self._estado.das_conectado:
            return []
        if self._barrido_siguiente_en is None or self._ahora > self._barrido_siguiente_en + BARRIDO_VIGILANCIA_S:
            self._barrido_siguiente_en = self._ahora
            return [Programar(T_BARRIDO, 0.0, {"motivo": "vigilancia del barrido"})]
        return []

    def _suscripciones(self) -> list[Accion]:
        """R-A-06.3 / manual L1996: Lv1 con tope y prioridad posiciones > intentos > radar; SHORTINFO al dar de alta."""
        if not self._estado.das_conectado:
            return []
        posiciones = [t for t, p in self._estado.posiciones.items() if self._tiene_posicion(p)]
        intentos = [t for t, p in self._estado.posiciones.items()
                    if p.intento is not None or p.senal_guardada_halt is not None]
        radar = [t for t, en in self._radar.items() if self._ahora - en <= RADAR_VIGENCIA_S]
        altas, bajas = self._mercado.suscripciones(posiciones, intentos, radar)
        acciones: list[Accion] = []
        for t in altas:
            acciones += [Suscribir(t, True), Consultar(f"GET SHORTINFO {t}")]
        acciones += [Suscribir(t, False) for t in bajas]
        return acciones

    def _sin_simbolo(self) -> list[Accion]:
        """A7: en premercado o RTH, un símbolo suscrito sin ninguna `$Quote` en 5 s no casa con DAS → SIN_SIMBOLO + aviso."""
        if not self._estado.das_conectado or not self._es_mercado(self._franja()):
            return []
        acciones: list[Accion] = []
        for t in self._mercado.suscritos():
            en = self._mercado.suscrito_en(t)
            if en is None or t in self._sin_simbolo_avisado or not self._mercado.sin_cotizacion_desde(
                    t, en, self._ahora, FRESCA_MAX_S):
                continue
            self._sin_simbolo_avisado.add(t)
            pos = self._pos(t)
            if pos.estado is EstadoTicker.NORMAL:
                pos.estado = EstadoTicker.SIN_SIMBOLO
                pos.motivo_estado = "A7: DAS no cotiza el símbolo"
                pos.desde = self._ahora
                acciones.append(Anotar("pausa", {"ticker": t, "estado": EstadoTicker.SIN_SIMBOLO.value,
                                                 "motivo": "A7: DAS no cotiza el símbolo"}))
            acciones += [Anotar("simbolo_no_casa", {"ticker": t, "suscrito_en": en, "regla": "A7"}),
                         Avisar(Nivel.AVISO, Grupo.B, f"{avisos.escapar_html(t)}: DAS no manda cotización tras suscribir "
                                                      f"(el símbolo no casa con Massive): no se opera (A7)",
                                clave=f"sin_simbolo:{t}")]
        return acciones

    def _resumen_diario(self) -> list[Accion]:
        """R-M-01: tras el último EOD (+30 s), el resumen del día al grupo B una vez (la misma respuesta que /estado)."""
        estado = self._estado
        if self._resumen_enviado == estado.dia:
            return []
        activas = [e for e in self._cfg.estrategias.values() if e.ejecutar]
        ultimo = salidas.ultimo_eod(activas, estado.dia)
        if ultimo is None or self._ahora_et < ultimo + timedelta(seconds=RESUMEN_TRAS_EOD_S):
            return []
        self._resumen_enviado = estado.dia
        consulta = Comando(nombre="estado", args=[], chat_id=comandos.CHAT_ID_CUADRO, requiere=comandos.REQUIERE_NADA,
                           id=f"resumen:{estado.dia.isoformat()}", texto="/estado")
        texto = comandos.responder_consulta(consulta, estado, self._cfg, self._mercado, self._ahora)
        return [Avisar(Nivel.INFO, Grupo.B, f"<b>Resumen del día</b>\n{texto}", clave=f"resumen:{estado.dia.isoformat()}")]

    def _conexion(self, c: ConexionDAS) -> list[Accion]:
        """F11 (a) / R-J-02: DAS caído → aviso 3, modo «das» y aviso cada 5 min; al volver, reconciliar ANTES de abrir nada."""
        estado = self._estado
        if c.conectado:
            estado.das_conectado = True
            acciones: list[Accion] = [Anotar("das", {"conectado": True, "motivo": c.motivo})]
            if "das" in estado.modo_degradado:
                estado.modo_degradado.discard("das")
                acciones += [Avisar(Nivel.INFO, Grupo.B, "DAS reconectado: se reconcilia antes de abrir nada (R-J-02.5)",
                                    clave="das_reconectado"),
                             Desprogramar(T_DAS_AVISO)]
            self._das_caido_desde = None
            estado.modo_degradado.add("reconciliacion")
            self._mercado.reiniciar_suscripciones()
            acciones += [Consultar("GET BP"), Consultar("GET AccountInfo"),
                         Programar(T_BARRIDO, 0.0, {"motivo": "conexión (F12)"})]
            return acciones
        estado.das_conectado = False
        self._acumulador.descartar()
        self._mercado.reiniciar_suscripciones()
        if "das" in estado.modo_degradado:
            return [Anotar("das", {"conectado": False, "motivo": c.motivo})]
        estado.modo_degradado.add("das")
        self._das_caido_desde = self._ahora
        return [Anotar("das", {"conectado": False, "motivo": c.motivo}),
                Avisar(Nivel.MAXIMO, Grupo.B, f"DAS DESCONECTADO ({avisos.escapar_html(c.motivo)}): no se abre ni se "
                                              f"gestiona nada; los stops siguen residentes en DAS (R-J-02)",
                       clave="das_caido"),
                Programar(T_DAS_AVISO, float(DAS_AVISO_CADA_S), {})]

    def _hilo_caido(self, h: HiloCaido) -> list[Accion]:
        """F11 (g): un hilo de borde murió → diario y aviso 2 (el HiloVigilado ya lo relanzó o no)."""
        return [Anotar("hilo_caido", {"nombre": h.nombre, "error": h.error, "relanzado": h.relanzado}),
                Avisar(Nivel.AVISO, Grupo.B, f"Hilo {avisos.escapar_html(h.nombre)} caído ({avisos.escapar_html(h.error)}); "
                                             f"relanzado: {'sí' if h.relanzado else 'NO'}", clave=f"hilo:{h.nombre}")]

    def _cambio_de_dia(self) -> list[Accion]:
        """A medianoche ET: tokens del día nuevo, gasto de locates a cero, locates caducados al diario y avisos diarios."""
        hoy = self._ahora_et.date()
        estado = self._estado
        if hoy == estado.dia:
            return []
        antes = estado.dia
        caducados = locates.caducados(estado.locates)
        acciones: list[Accion] = [Anotar("dia_nuevo", {"antes": antes, "hoy": hoy})]
        if caducados:
            acciones.append(Anotar(locates.ANOTACION_CADUCADOS, {
                "dia": antes, "locates": [{"ticker": loc.ticker, "strategy_id": loc.strategy_id,
                                           "libres": max(loc.localizadas - loc.usadas, 0), "coste": loc.coste}
                                          for loc in caducados], "regla": "R-H-05"}))
        self._tokens.cambiar_dia(hoy)
        self._tokens_locate.cambiar_dia(hoy)
        estado.dia = hoy
        estado.gasto_locates_dia = Decimal("0")
        estado.locates.clear()
        estado.locates_deshabilitados = False
        self._avisos_dia.clear()
        self._halt_hoy.clear()
        self._stop_hoy.clear()
        self._reapertura_ok.clear()
        self._banda_enviada.clear()
        self._halt_humano_avisado.clear()
        return acciones

    # ═══════════════════════════ comandos (R-M-04) ═════════════════════════
    def _comando(self, c: Comando) -> list[Accion]:
        """R-M-04 / R-Q-01: consulta → respuesta; dos pasos → `Confirmaciones`; «SI» o confirmado → se ejecuta."""
        if not isinstance(c, Comando):
            return [Anotar("comando_invalido", {"tipo": type(c).__name__})]
        datos = {"nombre": c.nombre, "args": list(c.args), "chat_id": c.chat_id, "id": c.id, "requiere": c.requiere}
        if c.requiere == comandos.REQUIERE_CONFIRMAR:
            confirmado = self._confirmaciones.confirmar(c.chat_id, c.texto)
            if confirmado is None:
                return [Anotar("comando", {**datos, "confirmado": False}),
                        self._responder("Confirmación inexistente, caducada o de otro chat: no hago nada")]
            return self._ejecutar_comando(confirmado)
        if c.requiere == comandos.REQUIERE_CONFIRMACION:
            return [Anotar("comando", {**datos, "confirmado": False}), self._responder(self._confirmaciones.pedir(c))]
        previa = comandos.respuesta_previa(c)
        if previa is not None:
            return [Anotar("comando", {**datos, "confirmado": False}), self._responder(previa)]
        if c.requiere == comandos.REQUIERE_NADA and c.nombre in comandos.CONSULTA:
            lineas = None
            if c.nombre == "log" and self._lineas_log is not None:
                n = int(c.args[0]) if c.args else comandos.LOG_LINEAS_DEFECTO
                try:
                    lineas = list(self._lineas_log(n))
                except Exception:  # noqa: BLE001 — frontera: el log es del ejecutor; sin él la respuesta lo dice
                    lineas = None
            texto = comandos.responder_consulta(c, self._estado, self._cfg, self._mercado, self._ahora, lineas)
            return [Anotar("comando", {**datos, "confirmado": True}), self._responder(texto)]
        if c.requiere in (comandos.REQUIERE_SI, comandos.REQUIERE_CONFIRMADO):
            return self._ejecutar_comando(c)
        return [Anotar("comando", {**datos, "confirmado": False}),
                self._responder(f"Comando no ejecutable ({avisos.escapar_html(c.requiere)})")]

    def _responder(self, texto: str) -> Avisar:
        """Respuesta a un comando: nivel 1, grupo B, SIN clave (el dedupe de 60 s callaría una segunda consulta igual)."""
        return Avisar(Nivel.INFO, Grupo.B, texto, clave=None)

    def _anotar_comando(self, c: Comando, nombre: Optional[str] = None, args: Optional[list] = None) -> Anotar:
        return Anotar("comando", {"nombre": nombre or c.nombre, "args": list(c.args if args is None else args),
                                  "chat_id": c.chat_id, "id": c.id, "confirmado": True, "original": c.nombre})

    def _ejecutar_comando(self, c: Comando) -> list[Accion]:
        """Ejecuta un comando ya confirmado (dos pasos o «SI»); cada uno contesta al grupo B."""
        n = c.nombre
        args = [str(a) for a in c.args]
        estado = self._estado
        esc = avisos.escapar_html
        if n == "pausar":
            estado.pausa_global = True
            return [self._anotar_comando(c), self._responder("Pausado: no se abren entradas nuevas; stops y salidas siguen")]
        if n == "sigue":
            estado.pausa_global = False
            for pos in estado.posiciones.values():
                pos.intervencion_humana = False
            return [self._anotar_comando(c), self._responder("Sigue: se levanta la pausa por intervención humana (R-M-03)")]
        if n in ("reanudar", "reanudar_ticker"):
            if not args:
                estado.pausa_global = False
                return [self._anotar_comando(c, "reanudar"), self._responder("Reanudado: se vuelven a abrir entradas")]
            return self._reanudar_ticker(c, args[0])
        if n == "reanudar_todo":
            acciones: list[Accion] = [self._anotar_comando(c)]
            for t in sorted(estado.posiciones):
                acciones += self._reanudar_ticker(c, t, responder=False, anotar=False)
            return acciones + [self._responder("Reanudados todos los tickers (salvo cisne negro)")]
        if n == "modo_seguridad":
            activo = args[0] == "on"
            antes = bool(self._cfg.modo_seguridad.get("activo"))
            self._override_modo_seguridad = activo
            self._recomponer_cfg()
            return [self._anotar_comando(c),
                    Anotar("config_cambio", {"ruta": "modo_seguridad.activo", "antes": antes, "despues": activo,
                                             "caliente": True, "aplicado": True, "origen": "telegram"}),
                    self._responder(f"Modo de seguridad {'ON' if activo else 'off'} (R-I-04)")]
        if n in ("desactivar", "activar"):
            return self._comando_estrategia(c, ejecutar=(n == "activar"))
        if n == "apagar":
            estado.vigilando = False
            estado.control_humano = True
            acciones = [self._anotar_comando(c)]
            for pos in list(estado.posiciones.values()):
                if pos.intento is not None:
                    acciones += self._cancelar_intento(pos, MOTIVO_CIERRE)
            return acciones + [self._responder("APAGADO: no se abre nada; stops residentes y salidas siguen")]
        if n == "encender":
            estado.vigilando = True
            estado.control_humano = False
            return [self._anotar_comando(c), Programar(T_BARRIDO, 0.0, {"motivo": "encender"}),
                    self._responder("Encendido: se reconcilia y se vuelve a vigilar")]
        if n == "parar_avisos":
            return self._silenciar(c, True)
        if n == "reanudar_avisos":
            return self._silenciar(c, False)
        if n == "control_humano":
            if not args:
                estado.control_humano = True
                return [self._anotar_comando(c), self._responder("CONTROL HUMANO: el bot no abre nada; stops siguen")]
            t = args[0]
            pos = self._pos(t)
            if pos.estado is not EstadoTicker.BS:
                pos.estado = EstadoTicker.CONTROL_HUMANO
                pos.motivo_estado = "control humano (comando)"
                pos.desde = self._ahora
            return [self._anotar_comando(c, "control_humano_ticker", [t]),
                    Anotar("pausa", {"ticker": t, "estado": pos.estado.value, "motivo": "control humano (comando)"}),
                    self._responder(f"{esc(t)}: control humano; el bot no abre en este ticker")]
        if n in ("cerrar_y_reiniciar", "esperar_fin_dia"):
            return self._comando_al_desactivar(c, n)
        if n == "cerrar_todo":
            return self._comando_cerrar_todo(c)
        if n == "cerrar":
            return self._comando_cerrar(c, args)
        if n == "cancelar_ordenes":
            t = args[0]
            pos = self._pos(t)
            self._manual.add(t)
            acciones = [self._anotar_comando(c)] + self._absorber([CancelarTicker(t, "/cancelar_ordenes: lo pide el humano")])
            if pos.intento is not None:
                acciones += self._cancelar_intento(pos, MOTIVO_CIERRE)
            if pos.estado is not EstadoTicker.BS:
                pos.estado = EstadoTicker.CONTROL_HUMANO
                pos.motivo_estado = "órdenes canceladas a mano"
                pos.desde = self._ahora
            return acciones + [Anotar("pausa", {"ticker": t, "estado": pos.estado.value,
                                                "motivo": "órdenes canceladas a mano (/cancelar_ordenes)"}),
                               self._responder(f"{esc(t)}: canceladas TODAS sus órdenes; el ticker queda en control "
                                               f"manual (sin stops del bot) hasta /reanudar {esc(t)}")]
        if n == "stop":
            return self._comando_stop(c, args[0], precios.de_float(args[1]))
        return [Anotar("comando", {"nombre": n, "args": args, "confirmado": False}),
                self._responder(f"Comando /{esc(n)} sin ejecución en el bot")]

    def _reanudar_ticker(self, c: Comando, ticker: str, responder: bool = True, anotar: bool = True) -> list[Accion]:
        """R-B-07: «Reanudar ticker» quita la pausa (salvo cisne negro), el control manual y vuelve a poner los stops."""
        pos = self._estado.posiciones.get(ticker)
        acciones: list[Accion] = [self._anotar_comando(c, "reanudar_ticker", [ticker])] if anotar else []
        self._manual.discard(ticker)
        self._olvidar_rechazos_de_stop(ticker)
        manda_otra_regla = pos is not None and pos.estado in (EstadoTicker.BS, EstadoTicker.HALT)
        if pos is not None and not manda_otra_regla:
            pos.estado = EstadoTicker.NORMAL
            pos.motivo_estado = ""
            pos.desde = self._ahora
            acciones.append(Anotar("reanudar", {"ticker": ticker, "motivo": f"/{c.nombre}"}))
        if pos is not None:
            acciones += self._plan(ticker)
        if responder:
            acciones.append(self._responder(f"{avisos.escapar_html(ticker)}: reanudado"
                                            + (f" (sigue en {pos.estado.value}: esa regla manda)"
                                               if pos is not None and manda_otra_regla else "")))
        return acciones

    def _silenciar(self, c: Comando, silenciar: bool) -> list[Accion]:
        """F7: /parar_avisos silencia SOLO los informes periódicos de los cisnes negros vivos; /reanudar_avisos los devuelve."""
        acciones: list[Accion] = [self._anotar_comando(c)]
        tocados: list[str] = []
        for t, pos in sorted(self._estado.posiciones.items()):
            if pos.bs is None or pos.bs.silenciado == silenciar:
                continue
            pos.bs = dataclasses.replace(pos.bs, silenciado=silenciar)
            tocados.append(t)
            acciones.append(Anotar("bs", {"ticker": t, "evento": "silenciado" if silenciar else "avisos_reanudados",
                                          "silenciado": silenciar}))
            if not silenciar:
                acciones.append(Programar(f"{T_BS_INFORME}:{t}", 0.0, {"ticker": t}))
        texto = ("Informes de cisne negro " + ("silenciados" if silenciar else "reanudados") + ": "
                 + (", ".join(tocados) if tocados else "ninguno activo"))
        return acciones + [self._responder(avisos.escapar_html(texto))]

    def _estrategia_por_arg(self, arg: str) -> Optional[EstrategiaConfig]:
        clave = arg.strip().casefold()
        for e in self._cfg_base.estrategias.values():
            if e.strategy_id.casefold() == clave or e.name.strip().casefold() == clave:
                return self._cfg.estrategias.get(e.strategy_id, e)
        return None

    def _comando_estrategia(self, c: Comando, ejecutar: bool) -> list[Accion]:
        """/activar y /desactivar: sobrescriben `ejecutar` (en memoria); desactivar aplica R-E-03 a los lotes vivos."""
        e = self._estrategia_por_arg(c.args[0])
        if e is None:
            return [Anotar("comando", {"nombre": c.nombre, "args": list(c.args), "confirmado": False}),
                    self._responder(f"No conozco la estrategia «{avisos.escapar_html(c.args[0])}»")]
        vieja = self._cfg
        self._override_estrategia.setdefault(e.strategy_id, {})["ejecutar"] = ejecutar
        self._recomponer_cfg()
        acciones: list[Accion] = [self._anotar_comando(c),
                                  Anotar("config_cambio", {"ruta": f"estrategias.{e.strategy_id}.ejecutar",
                                                           "antes": e.ejecutar, "despues": ejecutar, "caliente": True,
                                                           "aplicado": True, "origen": "telegram"})]
        acciones += self._al_desactivar_cambios(vieja, self._cfg)
        return acciones + [self._responder(f"{avisos.escapar_html(e.name)}: ejecutar = {'sí' if ejecutar else 'no'}")]

    def _comando_al_desactivar(self, c: Comando, modo: str) -> list[Accion]:
        """R-E-03: /cerrar_y_reiniciar cierra los lotes vivos como R-D-08; /esperar_fin_dia solo fija la elección."""
        e = self._estrategia_por_arg(c.args[0])
        if e is None:
            return [Anotar("comando", {"nombre": c.nombre, "args": list(c.args), "confirmado": False}),
                    self._responder(f"No conozco la estrategia «{avisos.escapar_html(c.args[0])}»")]
        self._override_estrategia.setdefault(e.strategy_id, {})["al_desactivar"] = modo
        self._recomponer_cfg()
        acciones: list[Accion] = [self._anotar_comando(c)]
        if modo == salidas.AL_DESACTIVAR_REINICIAR:
            lotes = [lote for pos in self._estado.posiciones.values() for lote in self._lotes_vivos(pos)
                     if lote.strategy_id == e.strategy_id]
            nueva = self._cfg.estrategias.get(e.strategy_id, e)
            acciones += self._absorber(salidas.al_desactivar(e, nueva, lotes, self._cot, self._cfg, self._tokens.siguiente,
                                                             self._ahora_et))
        return acciones + [self._responder(f"{avisos.escapar_html(e.name)}: al desactivar = {modo}")]

    def _comando_cerrar_todo(self, c: Comando) -> list[Accion]:
        """R-D-06 «/cerrar_todo SI»: cancelar y cerrar TODO con techo 5 % sobre el libro; los stops no se reponen mientras."""
        acciones: list[Accion] = [self._anotar_comando(c)]
        for pos in list(self._estado.posiciones.values()):
            if pos.intento is not None:
                acciones += self._cancelar_intento(pos, MOTIVO_CIERRE)
        cierre = self._absorber(salidas.cerrar_todo(self._estado.posiciones, self._cot, self._cfg,
                                                    self._tokens.siguiente, self._ahora_et))
        for a in cierre:
            if isinstance(a, CancelarTicker):
                self._cierre_humano.add(a.ticker)
        return acciones + cierre + [self._responder("Cerrar todo: órdenes enviadas (R-D-06); los stops no se reponen "
                                                    "mientras dure el cierre")]

    def _comando_cerrar(self, c: Comando, args: list[str]) -> list[Accion]:
        """/cerrar X [N] SI: en cisne negro o con N, `cisne_negro.cierre_humano`; si no, «cerrar todo» de ese ticker."""
        ticker = args[0]
        n = int(args[1]) if len(args) > 1 else None
        pos = self._estado.posiciones.get(ticker)
        if pos is None or (pos.neta_fills == 0 and (pos.neta_das or 0) == 0):
            return [self._anotar_comando(c), self._responder(f"{avisos.escapar_html(ticker)}: no hay posición que cerrar")]
        acciones: list[Accion] = [self._anotar_comando(c)]
        if pos.intento is not None:
            acciones += self._cancelar_intento(pos, MOTIVO_CIERRE)
        self._cierre_humano.add(ticker)
        if pos.estado is EstadoTicker.BS or n is not None:
            cierre = self._absorber(cisne_negro.cierre_humano(pos, self._ordenes_ticker(ticker), self._cot(ticker), n,
                                                              self._cfg, self._tokens.siguiente, self._ahora_et))
            self._fin_cierre_humano(ticker, cierre)
        else:
            cierre = self._absorber(salidas.cerrar_todo(self._estado.posiciones, self._cot, self._cfg,
                                                        self._tokens.siguiente, self._ahora_et, tickers=[ticker]))
        return acciones + cierre + [self._responder(f"{avisos.escapar_html(ticker)}: cierre enviado"
                                                    + (f" ({n} acciones)" if n is not None else "") + " (R-D-06)")]

    def _comando_stop(self, c: Comando, ticker: str, precio: Decimal) -> list[Accion]:
        """/stop X PRECIO SI: el nivel L de los lotes vivos pasa a PRECIO y el plan recoloca; sin lotes, protección a ese disparo."""
        pos = self._estado.posiciones.get(ticker)
        if pos is None or pos.neta >= 0:
            return [self._anotar_comando(c), self._responder(f"{avisos.escapar_html(ticker)}: no hay corto al que poner stop")]
        acciones: list[Accion] = [self._anotar_comando(c)]
        vivos = self._lotes_vivos(pos)
        if vivos:
            for lote in vivos:
                lote.nivel_stop = precio
                lote.principal_consumido = False
                acciones.append(Anotar("lote", {"lote_id": lote.id, "ticker": ticker, "nivel_stop": precio,
                                                "principal_consumido": False, "motivo": "/stop"}))
            acciones += self._plan(ticker)
        else:
            limite = precios.con_techo(precio, _pct(self._cfg.stops, "principal_limite_pct", STOP_PRINCIPAL_LIMITE_PCT),
                                       arriba=True)
            orden = OrdenNueva(token=self._tokens.siguiente(), lado=Lado.COMPRA, ticker=ticker, ruta=self._ruta_stop(),
                               qty=-pos.neta, tipo=TipoOrden.STOP_LIMITE_PP, precio=limite, stop=precio, tif="DAY+",
                               proposito=Proposito.STOP_PROTECCION, nivel=precio, version=pos.version_stops)
            acciones += self._absorber([EnviarOrden(orden)])
        return acciones + [self._responder(f"{avisos.escapar_html(ticker)}: stop a {precio}")]

    # ═══════════════════════════ configuración (CM2/CM3, F14) ══════════════
    def _recomponer_cfg(self) -> None:
        base = self._cfg_base
        cambios: dict[str, Any] = {}
        if self._override_modo_seguridad is not None:
            cambios["modo_seguridad"] = {**dict(base.modo_seguridad), "activo": self._override_modo_seguridad}
        if self._override_estrategia:
            estrategias = dict(base.estrategias)
            for sid, campos in self._override_estrategia.items():
                if sid in estrategias and campos:
                    estrategias[sid] = dataclasses.replace(estrategias[sid], **campos)
            cambios["estrategias"] = estrategias
        self._cfg = dataclasses.replace(base, **cambios) if cambios else base

    def _soltar_override(self, ruta: str) -> None:
        if ruta == "modo_seguridad.activo":
            self._override_modo_seguridad = None
            return
        partes = ruta.split(".")
        if len(partes) == 3 and partes[0] == "estrategias" and partes[2] in ("ejecutar", "al_desactivar"):
            campos = self._override_estrategia.get(partes[1])
            if campos is not None:
                campos.pop(partes[2], None)
        elif len(partes) == 2 and partes[0] == "estrategias":
            self._override_estrategia.pop(partes[1], None)

    def _config(self, nueva: Config, aviso: Optional[str]) -> list[Accion]:
        """CM2 / CM3 / R-O-01 / F14: `config.aplicar` (lo [C] en caliente), cada diferencia al diario y R-E-03 si toca."""
        acciones: list[Accion] = []
        if aviso:
            acciones.append(Avisar(Nivel.AVISO, Grupo.B, f"Configuración: {avisos.escapar_html(aviso)}",
                                   clave="config_aviso"))
        if not isinstance(nueva, Config):
            return acciones + [Anotar("config_invalida", {"tipo": type(nueva).__name__})]
        vieja = self._cfg
        diferencias = mod_config.diferencias(self._cfg_base, nueva)
        resultante, rechazadas = mod_config.aplicar(self._cfg_base, nueva, self._vigilando_efectivo(),
                                                    self._hay_posiciones())
        rechazo = set(rechazadas)
        for ruta, antes, despues, caliente in diferencias:
            acciones.append(Anotar("config_cambio", {"ruta": ruta, "antes": antes, "despues": despues, "caliente": caliente,
                                                     "aplicado": ruta not in rechazo,
                                                     "config_version": nueva.config_version, "regla": "CM3"}))
            if ruta not in rechazo:
                self._soltar_override(ruta)
        if rechazadas:
            acciones.append(Avisar(Nivel.AVISO, Grupo.B,
                                   "Cambios de configuración RECHAZADOS con el bot encendido o con posiciones (se aplican "
                                   "apagado y sin posiciones, R-O-01): " + avisos.escapar_html(", ".join(rechazadas[:12])),
                                   clave=f"config_rechazada:{nueva.config_version}"))
        self._cfg_base = resultante
        self._recomponer_cfg()
        self._estado.config_version = self._cfg.config_version
        acciones.append(Anotar("config", {"config_version": self._cfg.config_version, "sha256": self._cfg.sha256,
                                          "rechazadas": list(rechazadas)}))
        acciones += self._al_desactivar_cambios(vieja, self._cfg)
        return acciones

    def _al_desactivar_cambios(self, vieja: Config, nueva: Config) -> list[Accion]:
        """F14 / R-E-03: estrategia que pasa a ejecutar=False o cambia de versión con lotes vivos → `salidas.al_desactivar`."""
        acciones: list[Accion] = []
        for sid, e_vieja in sorted(vieja.estrategias.items()):
            e_nueva = nueva.estrategias.get(sid)
            desactivada = e_nueva is None or (e_vieja.ejecutar and not e_nueva.ejecutar)
            otra_version = e_nueva is not None and e_nueva.definition_hash != e_vieja.definition_hash
            if not (desactivada or otra_version):
                continue
            lotes = [lote for pos in self._estado.posiciones.values() for lote in self._lotes_vivos(pos)
                     if lote.strategy_id == sid]
            if not lotes:
                continue

            def _aplicar(e_v: EstrategiaConfig = e_vieja, e_n: Optional[EstrategiaConfig] = e_nueva,
                         vivos: list[Lote] = lotes) -> list[Accion]:
                return [Anotar("estrategia_desactivada", {"strategy_id": e_v.strategy_id, "lotes": [x.id for x in vivos],
                                                          "al_desactivar": (e_n or e_v).al_desactivar,
                                                          "regla": "R-E-03"})] + self._absorber(
                    salidas.al_desactivar(e_v, e_n, vivos, self._cot, self._cfg, self._tokens.siguiente, self._ahora_et))

            acciones += self._proteger(None, f"al_desactivar:{sid}", _aplicar)
        return acciones

    # ═══════════════════════════ arranque (F12/F13) ════════════════════════
    def _arrancar_ticker(self, pos: PosicionTicker) -> list[Accion]:
        """F13: intentos a medias cerrados con lo llenado; temporizadores de salida y de cisne negro reprogramados."""
        acciones: list[Accion] = []
        ticker = pos.ticker
        abriendo = [lote for lote in pos.lotes.values() if lote.estado is EstadoLote.ABRIENDO]
        if abriendo:
            for o in self._vivas(ticker):
                if o.proposito in _PROP_ENTRADA:
                    acciones += self._cancelar_orden(o, "F13: intento a medias tras el reinicio")
            for lote in abriendo:
                nuevo = dataclasses.replace(lote, estado=EstadoLote.ABIERTO if lote.llenas > 0 else EstadoLote.CANCELADO)
                pos.lotes[lote.id] = nuevo
                acciones.append(self._anotar_lote(nuevo))
            acciones.append(Anotar("intento_fin", {"ticker": ticker, "lotes": [lote.id for lote in abriendo],
                                                   "motivo": "F13: intento a medias tras el reinicio; se queda lo llenado"}))
        pos.intento = None
        for lote in self._lotes_vivos(pos):
            acciones += self._temporizadores_lote(lote)
        if pos.bs is not None:
            acciones.append(Programar(f"{T_BS_INFORME}:{ticker}",
                                      cisne_negro.segundos_hasta_informe(pos.bs, self._ahora, self._cfg.tecnicos),
                                      {"ticker": ticker}))
        return acciones

    def _reconstruir_dedupe(self) -> None:
        """Tras `reconstruir`, los fills del diario ya están contados: sus `id_trade` y sus pares Execute/TRADE."""
        for lista in self._estado.fills.values():
            for fill in lista:
                if fill.id_trade is not None and fill.id_trade > 0:
                    self._trades_vistos.add(fill.id_trade)
                clave = (fill.id_orden, int(fill.qty))
                self._n_execute[clave] = self._n_execute.get(clave, 0) + 1
                self._n_trade[clave] = self._n_trade.get(clave, 0) + 1

    # ═══════════════════════════ foto: piezas ══════════════════════════════
    def _foto_posicion(self, p: PosicionTicker) -> dict:
        intento = p.intento
        return {
            "neta_fills": p.neta_fills, "neta_das": p.neta_das, "avg_das": _txt(p.avg_das), "estado": p.estado.value,
            "motivo": p.motivo_estado, "version_stops": p.version_stops,
            "sin_reentrada_hasta_sigue": p.sin_reentrada_hasta_sigue,
            "lotes": [{"id": lote.id, "strategy_id": lote.strategy_id, "estado": lote.estado.value,
                       "pedidas": lote.pedidas, "llenas": lote.llenas, "precio_medio": _txt(lote.precio_medio),
                       "nivel_stop": _txt(lote.nivel_stop), "eod": lote.eod, "hora_salida": lote.hora_salida}
                      for lote in p.lotes.values()],
            "intento": None if intento is None else {
                "fase": intento.fase.value, "qty_total": intento.qty_total, "llenas": intento.llenas,
                "lotes": list(intento.lotes), "t_limite": intento.t_limite,
                "token_agregar": intento.token_agregar, "token_cruce": intento.token_cruce},
            "bs": None if p.bs is None else {"activado_en": p.bs.activado_en, "informes": p.bs.informes,
                                             "max_visto": _txt(p.bs.max_visto), "silenciado": p.bs.silenciado},
        }

    def _foto_orden(self, o: Orden) -> dict:
        return {"token": o.token, "id_das": o.id_das, "ticker": o.ticker, "lado": o.lado.value, "tipo": o.tipo.value,
                "qty": o.qty, "llenas": o.llenas, "lvqty": o.lvqty, "precio": _txt(o.precio), "stop": _txt(o.stop),
                "estado": o.estado.value, "proposito": o.proposito.value, "lote_id": o.lote_id,
                "origen": o.origen.value}


# ═══════════════════════════ auxiliares del módulo ═════════════════════════
def _txt(valor: Optional[Decimal]) -> Optional[str]:
    return None if valor is None else str(valor)


def _es_precio(valor: Any) -> bool:
    return isinstance(valor, Decimal) and valor.is_finite() and valor > 0


def _libro_utilizable(cot: Optional[Cotizacion]) -> bool:
    return cot is not None and _es_precio(cot.bid) and _es_precio(cot.ask) and cot.ask >= cot.bid


def _qty_viva(o: Orden) -> int:
    """Acciones que la orden aún puede ejecutar: `lvqty` si DAS la dio en Partial/Triggered; si no, qty − llenas (§8.7)."""
    if o.estado in (EstadoOrden.PARTIAL, EstadoOrden.TRIGGERED) and o.lvqty > 0:
        return max(int(o.lvqty), 0)
    return max(int(o.qty) - int(o.llenas), 0)


def _tipo_evento(ev: Any) -> str:
    return str(getattr(ev, "tipo", "") or "").strip().lower()


def _clase_salida(ev: Any) -> ClaseSalida:
    """Pirámide reduce / lot_stop / lot_tp → REDUCE / STOP_LOTE / TP; salida → `salidas.clasificar(motivo)`."""
    if _tipo_evento(ev) == "piramide":
        accion = str(getattr(ev, "accion_piramide", "") or "").strip().lower()
        return {"lot_stop": ClaseSalida.STOP_LOTE, "lot_tp": ClaseSalida.TP}.get(accion, ClaseSalida.REDUCE)
    return salidas.clasificar(getattr(ev, "motivo", None))


def _proposito(valor: Any, defecto: Proposito) -> Proposito:
    if isinstance(valor, Proposito):
        return valor
    try:
        return Proposito(str(valor))
    except ValueError:
        return defecto


def _estado_ticker(valor: Any) -> Optional[EstadoTicker]:
    try:
        return EstadoTicker(str(valor))
    except ValueError:
        return None


def _segundos(bloque: Any, clave: str, defecto: float) -> float:
    """Segundos de un bloque de la config (número del JSON); ausente, no numérico o negativo → el defecto."""
    valor = bloque.get(clave) if isinstance(bloque, dict) else None
    if valor is None or isinstance(valor, bool) or not isinstance(valor, (int, float, Decimal)):
        return float(defecto)
    segundos = float(valor)
    return segundos if math.isfinite(segundos) and segundos >= 0 else float(defecto)


def _pct(bloque: Any, clave: str, defecto: Decimal) -> Decimal:
    valor = bloque.get(clave) if isinstance(bloque, dict) else None
    if valor is None:
        return defecto
    try:
        return precios.de_float(valor)
    except ValueError:
        return defecto


def _rutas_de(bloque: Any) -> set[str]:
    """Todas las rutas que nombra la tabla de rutas del cuadro (para avisar si DAS tiene alguna deshabilitada)."""
    if isinstance(bloque, str):
        return {bloque}
    if isinstance(bloque, dict):
        rutas: set[str] = set()
        for valor in bloque.values():
            rutas |= _rutas_de(valor)
        return rutas
    return set()


def _colapsar_programar(acciones: list[Accion]) -> list[Accion]:
    """Dos `Programar` de la misma clave en una tanda: vale el ÚLTIMO (§6.1), salvo un `Desprogramar` entre medias."""
    salida: list[Accion] = []
    for i, a in enumerate(acciones):
        if isinstance(a, Programar):
            siguiente = next((b for b in acciones[i + 1:]
                              if isinstance(b, (Programar, Desprogramar)) and b.clave == a.clave), None)
            if isinstance(siguiente, Programar):
                continue
        salida.append(a)
    return salida
