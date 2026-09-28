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
  * Lo que el diario no reconstruye (intentos, contadores de persecución)
    vive en memoria: tras un reinicio `arrancar()` cierra los intentos a
    medias y reprograma los temporizadores de salida de cada lote vivo
    (F12/F13). Lo que SÍ se puede rehacer del diario (control manual, vetos
    R-F-03, k de halts, cambios por Telegram) lo siembra
    `sembrar_memoria(diario.memoria_decisor(...))` (G1A-12, G1A-18, G1B-09,
    E1-03).
  * La referencia de Massive NO se consulta desde aquí (G1A-03 / G1B-08):
    solo su caché de solo lectura (`ficha_en_cache` / `splits_en_cache`); la
    red la hace un hilo de borde del ejecutor. Sin ficha → A12 (no se opera).
  * Una salida por temporizador (TP, hora, persecución) con la guarda
    `_puede_gestionar_salida` cerrada (cisne negro, halt, control manual o
    humano, cierre humano, reconciliación pendiente o DAS caído) NO se pierde:
    se reprograma a 0,5 s (G1A-02, G1B-01). Su cantidad nunca pasa de lo que
    queda corto menos las compras de cierre vivas del ticker (G1B-05).
  * Halt con stops residentes (G1A-01): la orden de salida del halt y los
    stops nunca suman más que la posición: al enviarla, `stops.plan` recibe
    `compras_cierre` y BAJA principal y emergencia por esa cantidad; si la
    orden se rechaza o no llena 2 s tras reabrir, se retira y el plan los
    restaura (aviso 2).
  * R-C-03 agotado bloquea SOLO la reposición de ese propósito (G1B-07): el
    resto del plan (reducciones, cancelaciones, el otro stop) sigue y el
    ticker no sale de la reconciliación. Las órdenes que el plan crea se
    numeran con tokens PROVISIONALES y solo las que salen reciben un token
    real (un plan filtrado no gasta la secuencia del día).
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

from app.bot_das import VERSION, avisos, comandos, protocolo
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
    ENTRADA_CADUCIDAD_S,
    ENTRADA_CRUCE_BAJO_BID_PCT,
    ENTRADA_TOPE_CAIDA_BID_PCT,
    FEED_EMERGENCIA_S,
    FEED_PREALERTA_S,
    PERSEGUIR_ASK_MAX,
    RECONCILIACION_CADUCA_S,
    REPLACE_SHARE_ES_ABIERTA,
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
    OrdenDescartada,
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
    share_de_replace,
)
from app.bot_das.tokens import GeneradorTokens, descomponer, es_nuestro

__all__ = [
    "Decisor",
    "T_CRUCE", "T_CANCEL_ESPERA", "T_CRUCE_ESPERA", "T_STOPS_AJUSTAR", "T_STOPS_PLAN", "T_REPLACE_VERIFICAR",
    "T_TP_CRUCE", "T_TP_ESPERA_ENTRADA", "T_HORA_AGREGAR", "T_HORA_ASK", "T_EOD_COMPROBAR", "T_PERSEGUIR_ASK",
    "T_HALT_DECIDIR", "T_HALT_PRIMERA_VELA", "T_SIMSTATUS", "T_BARRIDO", "T_BS_INFORME", "T_BS_CIERRE",
    "T_LOCATE_INQUIRE", "T_STOP_REINTENTO", "T_REINTENTO_RECHAZO", "T_LOCATE_RECOMPRAR", "T_CERRAR_TODO",
    "T_DAS_AVISO", "T_DAS_RECONECTAR", "T_FOTO",
    "T_EXCESO_VERIFICAR", "T_TP_LIMBO", "T_CRUCE_POSTONLY", "T_HALT_CIERRE_VERIFICAR", "T_SIMSTATUS_ESPERA",
    "T_PRIORIDAD_ASK", "T_SALIDA_ESPERA", "T_SLRET_VENTANA", "T_CIERRE_REPONER",
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
T_TP_CRUCE = salidas.CLAVE_TP_CRUCE                 # F4.3 («tp_cruce:<lote>:<token>», D2-07: por ORDEN)
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
T_CERRAR_TODO = salidas.CLAVE_CERRAR_TODO           # R-D-06 («cerrar_todo:<ticker>», D2-01 / G1B-03: por TICKER)
T_DAS_AVISO = "das_aviso"                           # R-J-02 (3): DAS caído, aviso cada 5 min (global)
T_DAS_RECONECTAR = "das_reconectar"                 # R-J-02: lo reconecta el ejecutor; aquí solo se registra
T_FOTO = "foto"                                     # panel 4.4 (global; el Tic ya la publica cada foto_cada_s)
T_EXCESO_VERIFICAR = stops.CLAVE_EXCESO_VERIFICAR   # D2a-04: la venta del exceso a 1 s («exceso_verificar:X»)
T_TP_LIMBO = salidas.CLAVE_TP_LIMBO                 # D2-13: el cruce del TP no llenó («tp_limbo:<lote>:<token>»)
T_CRUCE_POSTONLY = rechazos.CLAVE_CRUCE_POSTONLY    # D2-09: agregar rechazado por PostOnly → cruce («cruce_postonly:<token>»)
T_HALT_CIERRE_VERIFICAR = "halt_cierre_verificar"   # G1A-01: la salida del halt no llenó 2 s tras reabrir («…:X»)
T_SIMSTATUS_ESPERA = "simstatus_espera"             # G1A-05: 1 s como mucho esperando el SymStatus («simstatus_espera:X»)
T_PRIORIDAD_ASK = "prioridad_ask"                   # G1A-06 / R-D-07: el TP pasa al ask («prioridad_ask:<lote>:<token>»)
T_SALIDA_ESPERA = "salida_espera"                   # G1A-06 / R-D-07: salida que espera al Canceled de la entrada («…:X»)
T_SLRET_VENTANA = "slret_ventana"                   # E2-05: %SLRET de UNA consulta («slret_ventana:X:S»)
T_CIERRE_REPONER = "cierre_reponer"                 # D2-04 / G1B-03: stops de vuelta tras retirar el cierre («…:X»)
_GLOBALES = frozenset({T_SIMSTATUS, T_BARRIDO, T_DAS_AVISO, T_DAS_RECONECTAR, T_FOTO})

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
SALIDA_REPROGRAMAR_S = 0.5       # G1A-02 / G1B-01: salida con la guarda cerrada → se reprograma, nunca se descarta
REPLACE_EN_VUELO_MAX_S = 30.0    # ensayo 28-sep: un REPLACE idéntico pedido hace menos de 30 s no se vuelve a mandar
HALT_CIERRE_VERIFICAR_S = 2.0    # G1A-01: la salida del halt que no llenó 2 s tras reabrir se retira (stops de vuelta)
SIMSTATUS_ESPERA_S = 1.0         # G1A-05: como mucho 1 s esperando `GET SymStatus X` antes de abrir un ticker plano
SIMSTATUS_FRESCO_S = 5.0         # G1A-05: un estado de símbolo de hace ≤ 5 s vale sin volver a preguntar
SLRET_VENTANA_S = 0.5            # E2-05: los %SLRET de UNA consulta se juntan 0,5 s y se elige el más barato
ACCOUNTINFO_CADA_S = 30.0        # D1-10: GET AccountInfo en el barrido cada 30 s (el tope corto usa el equity)
OPA_REVISION_S = 60.0            # E1-08: la banda de OPA se mira como mucho una vez por minuto y ticker
TP_SIN_LIBRO_ESPERA_S = 2.0      # D2-12: TP con el libro inutilizable → el cruce se decide a los 2 s
CIERRE_REPONER_S = 1.0           # D2-04: respaldo para devolver los stops si el Canceled del cierre retirado no llega
ANOTAR_CANCELAR_AL_TENER_ID = "cancelar_al_tener_id"   # R2-DEC-4: `stops` pide cancelar una venta aún sin id (R2-STOPS-1)
SIN_LIBRES_AVISO_S = 60.0       # R2-DEC-1 (G1B-05): 60 s reprogramando una salida sin acciones libres → Avisar(2)
SIN_LIBRES_LENTO_S = 5.0         # R2-DEC-1: tras el aviso se sigue mirando, pero cada 5 s
# D1-07: el «alto riesgo» de R-I-01 (tope corto 0,5 × equity) sale de `entrada.alto_riesgo_si` con capital.es_alto_riesgo

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
_PROP_CIERRE_HALT = frozenset({Proposito.HALT_OPEN, Proposito.HALT_PM_LIMITE, Proposito.HALT_BANDA})   # G1A-01
_PROP_AGREGA_SALIDA = frozenset({Proposito.TP_AGREGAR, Proposito.HORA_AGREGAR, Proposito.SALIDA_MOTOR_AGREGAR,
                                 Proposito.CIERRE_REINICIO})                                      # G1A-06 (R-D-07)
_PROP_AVISO_SALIDA = _PROP_SALIDA | _PROP_STOP | frozenset({Proposito.VENTA_EXCESO})              # G1A-09 (R-M-01)
_LADOS_COMPRA = frozenset({"B", "BUY"})
_RE_HORA = re.compile(r"^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$")
_MOTIVO_MANUAL = "órdenes canceladas a mano"           # /cancelar_ordenes (el diario lo guarda en la pausa)
_MOTIVO_HUMANO_COMANDO = "control humano (comando)"    # /control_humano X
_MOTIVO_STOP_MANUAL = "stop puesto a mano (/stop)"     # G1B-06: /stop en control manual: stops del bot sí, salidas no
_CONT_PRIORIDAD = "prioridad"                          # continuación tras el Canceled: la salida pasa al ask (R-D-07)
_SALIDA_NORMAL = "normal"                              # G1B-02 / COB-01: la salida se trata entera tras el Canceled
_SALIDA_PRIORIDAD = "prioridad"                        # G1A-06 (b): el TP va al ask tras el Canceled de la entrada


class _RelojDelMensaje:
    """Reloj monotónico para `comandos.Confirmaciones`: el `ahora` del mensaje en curso (el decisor no lee el sistema)."""

    def __init__(self, decisor: "Decisor") -> None:
        self._decisor = decisor

    def mono(self) -> float:
        return self._decisor._ahora


class _TokensProvisionales:
    """G1B-07: tokens NEGATIVOS para `stops.plan`; solo las órdenes que el decisor deja salir reciben uno real.

    Un token negativo nunca es de DAS ni nuestro (los reales son positivos) y
    `OrdenNueva` lo admite (int32): así un plan cuyas órdenes nuevas se
    filtran (propósito agotado, halt) no gasta la secuencia del día
    (`tokens.MAX_SEQ` = 99 999 por origen y día).
    """

    def __init__(self) -> None:
        self._n = 0

    def __call__(self) -> int:
        self._n += 1
        return -self._n


class Decisor:
    """El único mutador de `EstadoBot` (§3.26, §6.1). Puro respecto a la E/S: todo sale como `Accion`.

    Contrato de §3.26 más, solo por nombre: `tokens_locate` (el generador de
    `Origen.EJECUTOR_LOCATE`; por defecto uno nuevo del día sobre
    `estado.ultimo_seq_token`), `calendario` (objeto con
    `franja_de_mercado(ahora_et)` y `media_sesion(dia)`; por defecto el módulo
    `bot_alerts_calendario`, importado la primera vez que hace falta),
    `lineas_log` (callable `n → últimas n líneas` para `/log`), `tamano_cola`
    (callable → tamaño de la cola del ejecutor, para la foto) y `memoria`
    (`diario.MemoriaDecisor`, o None: lo que el diario permite rehacer fuera de
    `EstadoBot`, ver `sembrar_memoria`). `referencia`: None, un objeto con la
    caché de solo lectura (`ficha_en_cache`, `splits_en_cache`,
    `splits_pendientes`, `pedir_ficha`: la de `referencia_massive.Referencia`,
    que el decisor usa SIN red, G1A-03) o, para tests y replay, uno en memoria
    con `ficha(ticker)` y `splits_de_hoy(dia)`. Lanza TypeError o ValueError
    con argumentos imposibles; `procesar` solo lanza con un mensaje o un reloj
    inválidos.
    """

    def __init__(self, cfg: Config, estado: EstadoBot, mercado: MercadoDAS, referencia: Any,
                 tokens: GeneradorTokens, catalogo_rechazos: list[dict], diario_degradado: Callable[[], bool], *,
                 tokens_locate: Optional[GeneradorTokens] = None, calendario: Any = None,
                 lineas_log: Optional[Callable[[int], Sequence[str]]] = None,
                 tamano_cola: Optional[Callable[[], int]] = None, memoria: Any = None) -> None:
        if not isinstance(cfg, Config):
            raise TypeError(f"cfg debe ser una Config, no {type(cfg).__name__}")
        if not isinstance(estado, EstadoBot):
            raise TypeError(f"estado debe ser un EstadoBot, no {type(estado).__name__}")
        if not isinstance(mercado, MercadoDAS):
            raise TypeError(f"mercado debe ser un MercadoDAS, no {type(mercado).__name__}")
        if referencia is not None and not (_tiene_cache_referencia(referencia) or (
                callable(getattr(referencia, "ficha", None)) and callable(getattr(referencia, "splits_de_hoy", None)))):
            raise TypeError("referencia debe tener la caché (ficha_en_cache, splits_en_cache) o ficha(ticker) y "
                            "splits_de_hoy(dia), o ser None")
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
        # token → (share enviado, precio, stop, versión, cantidad ABIERTA pedida) (D2a-05, D2a-08)
        self._reemplazo_pedido: dict[int, tuple[int, Optional[Decimal], Optional[Decimal], int, int]] = {}
        self._reemplazo_pedido_en: dict[int, float] = {}   # ensayo 28-sep: cuándo se pidió (un REPLACE igual no se repite)
        self._meta_orden: dict[int, tuple[int, float]] = {}
        self._continuacion: dict[int, tuple[str, dict]] = {}
        self._persecuciones: dict[int, int] = {}
        self._verificaciones: dict[int, int] = {}
        self._salidas_avisadas: set[int] = set()
        self._aplazadas: dict[str, str] = {}                # G1A-02: clave del temporizador aplazado → motivo anotado
        self._sin_libres_desde: dict[str, float] = {}       # R2-DEC-1: clave de la salida sin acciones libres → desde
        self._sin_libres_avisado: set[str] = set()          # R2-DEC-1: claves con el Avisar(2) de los 60 s ya enviado
        # G1B-13 / G1A-10: lo que una rama registró (se deshace si la rama lanza); se vacía al final de cada mensaje
        self._diario_rama: list[tuple[str, int]] = []
        # posiciones e intentos
        self._inicio_episodio: dict[str, float] = {}
        self._lotes_de_orden: dict[int, list[str]] = {}
        self._tokens_intento: dict[str, set[int]] = {}
        self._motivo_cancel: dict[str, str] = {}
        self._intento_pausado: set[str] = set()
        self._intento_en_reintento: set[str] = set()
        self._rechazos_tratados: set[int] = set()
        self._locates_de_lote: dict[str, list[tuple[str, int]]] = {}
        self._llenas_max_lote: dict[str, int] = {}
        self._espera_plan: set[str] = set()
        # R-C-03 por (ticker, propósito): hasta cuándo no se REPONE ese propósito (math.inf = agotado; G1B-07)
        self._stop_bloqueo: dict[tuple[str, Proposito], float] = {}
        self._stop_intentos: dict[tuple[str, Proposito], tuple[int, float]] = {}
        self._stops_diferidos_halt: set[str] = set()      # G1B-14 / R-C-04: stops que DAS quitó en un halt → al reabrir
        self._manual: set[str] = set()
        self._cierre_humano: set[str] = set()
        self._entradas_en_espera: dict[str, list[Senal]] = {}
        self._entradas_simstatus: dict[str, list[Senal]] = {}     # G1A-05: esperando el SymStatus del ticker
        self._salidas_tras_entrada: dict[str, list[tuple[Senal, str]]] = {}   # G1A-06 / G1B-02: esperan al Canceled
        self._claves_lote: dict[str, set[str]] = {}               # D2-07: tp_cruce / tp_limbo de cada lote
        self._cerrar_todo_enviar: dict[str, dict] = {}            # D2-03: paso «enviar» pendiente del Canceled
        self._retirando_cierre: set[str] = set()                  # D2-04: cierre retirado; stops tras su Canceled
        self._acciones_motor_lote: dict[str, int] = {}            # G1A-16: acciones del motor en la entrada del lote
        # halts, cisne negro y fogonazos
        self._halt_en_curso: set[str] = set()
        self._halt_fin: dict[str, Optional[datetime]] = {}
        self._halt_decision: dict[str, str] = {}
        self._halt_luld: dict[str, bool] = {}       # D4 (Jaume 28-sep): si el halt en curso era una pausa LULD (P)
        self._halt_decidir_programado: set[str] = set()   # G1A-14: el halt en curso ya tiene su halt_decidir
        self._halt_humano_avisado: set[str] = set()
        self._halt_hoy: set[str] = set()
        self._stop_hoy: set[str] = set()
        self._reapertura_ok: set[str] = set()
        self._banda_enviada: set[str] = set()
        self._hist: dict[str, deque[tuple[float, Decimal]]] = {}
        self._fogonazo_revisado_en: dict[str, float] = {}
        self._fogonazo_anotado: dict[str, float] = {}
        self._max_pm: dict[str, Decimal] = {}               # E1-08: máximo de premercado (último) por ticker
        self._opa_revisado_en: dict[str, float] = {}
        self._simstatus_en: dict[str, float] = {}           # G1A-05: último $IssueStatus/$SymStatus por ticker
        # locates, radar y referencia
        self._radar: dict[str, float] = {}
        self._radar_precio: dict[str, Decimal] = {}
        self._inquires: deque[tuple[str, str]] = deque()
        self._slret_ventana: dict[str, list[MsgSLRet]] = {}  # E2-05: %SLRET de las consultas de un ticker (0,5 s)
        self._slret_tics: dict[str, int] = {}                # E2-05: Tics vistos con la ventana abierta (cierra al 2.º)
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
        self._accountinfo_pedido_en: Optional[float] = None
        self._feed_nivel = "ok"
        self._das_caido_desde: Optional[float] = None
        self._reconciliacion_avisada = False
        self._resumen_enviado: Optional[date] = None
        self._ajenas_anotadas: set[int] = set()
        self._sin_simbolo_avisado: set[str] = set()
        self._prealerta_en: dict[tuple[str, str], float] = {}
        self._rutas_avisadas: set[str] = set()
        self._reuso_consultado: set[str] = set()
        self._comandos_vistos: set[str] = set()             # C-02: un Comando con el mismo id no se ejecuta dos veces
        # resumen del día (COB-02, G1A-09)
        self._pnl_episodio: dict[str, Decimal] = {}         # flujo de caja del trade en curso por ticker
        self._flujo_estrategia: dict[str, Decimal] = {}     # flujo realizado por estrategia (ventas − compras)
        self._operaciones_estrategia: dict[str, int] = {}
        self._slippage_bps: list[Decimal] = []
        self._incidentes_dia: dict[str, int] = {}
        if estado.reconciliacion_ok_en is None:
            estado.modo_degradado.add("reconciliacion")      # R-J-02.5: nada se abre hasta reconciliar
        self._reconstruir_dedupe()
        # G1A-12 / G1B-10: /cancelar_ordenes sobrevive a un reinicio aunque el ejecutor no pase la memoria del diario
        for ticker, pos in estado.posiciones.items():
            if (pos.estado is EstadoTicker.CONTROL_HUMANO
                    and str(pos.motivo_estado).startswith(_MOTIVO_MANUAL)):
                self._manual.add(ticker)
        if memoria is not None:
            self.sembrar_memoria(memoria)

    # ═══════════════════════════ API pública ═══════════════════════════════
    @property
    def cfg(self) -> Config:
        """La configuración EFECTIVA (la del cuadro más lo cambiado por Telegram)."""
        return self._cfg

    @property
    def estado(self) -> EstadoBot:
        return self._estado

    def sembrar_memoria(self, memoria: Any) -> None:
        """H-2 tras un reinicio: lo que el diario permite rehacer FUERA de `EstadoBot` (`diario.memoria_decisor`).

        Se llama tras `reconstruir` y antes de `arrancar` (o por el argumento
        `memoria` del constructor). Siembra: `_manual` (/cancelar_ordenes sin
        /reanudar, G1A-12/G1B-10: sin eso el primer barrido repondría los
        stops que el humano retiró), `_halt_hoy`/`_stop_hoy`/`_reapertura_ok`
        (veto R-F-03, G1A-18/G1B-18), k de halts UP en `MercadoDAS` (E1-03,
        nunca lo baja), los cambios hechos por Telegram (/modo_seguridad,
        /activar, /desactivar y al_desactivar, G1B-09) y, si la memoria los
        trae (`comandos_ids`), los ids de comando ya vistos hoy (C-02). Duck
        typing: cada campo ausente se ignora; valores imposibles también (no
        lanza).
        """
        if memoria is None:
            return
        for ticker in getattr(memoria, "manual", None) or ():
            if not isinstance(ticker, str) or not ticker:
                continue
            pos = self._estado.posiciones.get(ticker)
            if (pos is not None and pos.estado is EstadoTicker.CONTROL_HUMANO
                    and str(pos.motivo_estado).startswith(_MOTIVO_STOP_MANUAL)):
                continue          # G1B-06: un /stop posterior sacó el ticker del control manual (los stops son del bot)
            self._manual.add(ticker)
        for ident in getattr(memoria, "comandos_ids", None) or ():
            if isinstance(ident, str) and ident:
                self._comandos_vistos.add(ident)       # C-02: un comando ya visto hoy no se repite tras el reinicio
        for campo, destino in (("halt_hoy", self._halt_hoy), ("stop_hoy", self._stop_hoy),
                               ("reapertura_ok", self._reapertura_ok)):
            for ticker in getattr(memoria, campo, None) or ():
                if isinstance(ticker, str) and ticker:
                    destino.add(ticker)
        for ticker, k in dict(getattr(memoria, "k_halts_up", None) or {}).items():
            if isinstance(ticker, str) and ticker and type(k) is int and k >= 0:
                self._mercado.sembrar_k(ticker, k)
        override_ms = getattr(memoria, "override_modo_seguridad", None)
        if isinstance(override_ms, bool):
            self._override_modo_seguridad = override_ms
        for sid, campos in dict(getattr(memoria, "override_estrategia", None) or {}).items():
            if not isinstance(campos, dict) or sid not in self._cfg_base.estrategias:
                continue
            limpio = {k: v for k, v in campos.items()
                      if (k == "ejecutar" and isinstance(v, bool)) or (k == "al_desactivar" and isinstance(v, str))}
            if limpio:
                self._override_estrategia.setdefault(sid, {}).update(limpio)
        for arg, modo in dict(getattr(memoria, "al_desactivar_por_arg", None) or {}).items():
            e = self._estrategia_por_arg(str(arg)) if isinstance(modo, str) else None
            if e is not None:
                self._override_estrategia.setdefault(e.strategy_id, {})["al_desactivar"] = modo
        self._recomponer_cfg()

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
        self._diario_rama.clear()
        self._accountinfo_pedido_en = self._ahora
        acciones: list[Accion] = [
            Anotar("decisor_arranque", {"version": VERSION, "fase": self._estado.fase.value,
                                        "posiciones": sorted(self._estado.posiciones),
                                        "senales_vistas": len(self._estado.senales_vistas),
                                        "manual": sorted(self._manual)}),
            Consultar(protocolo.cmd_get("RouteStatus")), Consultar(protocolo.cmd_get("BP")),
            Consultar(protocolo.cmd_get("AccountInfo")), Consultar(protocolo.cmd_get("INTMSGS")),
            Consultar(protocolo.cmd_sl_min_charge("ALLROUTE")),
        ]
        for ticker in sorted(self._estado.posiciones):
            pos = self._estado.posiciones[ticker]
            acciones += self._proteger(ticker, "arranque", lambda p=pos: self._arrancar_ticker(p))
        acciones.append(Programar(T_BARRIDO, 0.0, {"motivo": "arranque (F12)"}))
        acciones += self._armar_simstatus()
        self._diario_rama.clear()
        return self._finalizar_seguro(acciones)

    def procesar(self, msg: Mensaje, ahora: float, ahora_et: datetime) -> list[Accion]:
        """Un mensaje de la cola → las acciones a ejecutar EN ORDEN (§3.26, §6.1). Nunca lanza salvo por argumentos inválidos.

        Despacho por tipo: `SenalRecibida`, `DeDAS`, `Tic`, `Temporizador`,
        `ComandoRecibido`, `ConfigNueva`, `ConexionDAS`, `HiloCaido` y
        `OrdenDescartada` (D2a-06: el emisor no mandó un NEWORDER). Antes, el
        cambio de día (tokens, gasto de locates, avisos diarios). Después,
        `_finalizar`: claves de temporizador normalizadas, prefijo de fase en
        los avisos del grupo B (R-O-03), `mono` en cada registro del diario,
        órdenes registradas por token y la red de la corrección 4 (con el
        diario roto no sale ninguna entrada ni compra de locate).
        """
        if not isinstance(msg, Mensaje):
            raise TypeError(f"procesar espera un Mensaje, no {type(msg).__name__}")
        self._fijar_reloj(ahora, ahora_et)
        self._diario_rama.clear()
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
        elif isinstance(msg, OrdenDescartada):
            acciones += self._proteger(self._ticker_de_descartada(msg), "orden_descartada",
                                       lambda: self._orden_descartada(msg))
        else:
            acciones.append(Anotar("mensaje_desconocido", {"tipo": type(msg).__name__}))
        self._diario_rama.clear()
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
        """H-5: la rama `fn` en try/except. Con ticker: excepción → diario, ticker PAUSADO y aviso 2; el bucle sigue.

        G1B-13 / G1A-10: lo que la rama registró y NO va a salir (sus acciones
        se descartan) se deshace: cada orden registrada en Sending sin id pasa
        a CLOSED («no salió», anotado), las cancelaciones, reemplazos y
        continuaciones pedidos se olvidan, un intento que se quedó sin su
        orden se cierra con lo llenado y se piden barrido y plan de stops
        inmediatos: ningún stop «fantasma» tapa una posición descubierta.
        """
        inicio = len(self._diario_rama)
        try:
            return list(fn())
        except Exception as exc:  # noqa: BLE001 — H-5: frontera por ticker; una rama rota pausa SU ticker, no el bot
            fallo = self._fallo(ticker, donde, exc)
            try:
                deshecho = self._deshacer_rama(inicio)
            except Exception as exc2:  # noqa: BLE001 — H-5: deshacer no puede tumbar el bucle; queda el aviso del primero
                deshecho = [Anotar("excepcion", {"ticker": ticker, "donde": f"{donde}:deshacer",
                                                 "error": f"{type(exc2).__name__}: {exc2}", "regla": "H-5"})]
            return fallo + deshecho

    def _deshacer_rama(self, inicio: int) -> list[Accion]:
        """G1B-13 / G1A-10: deshace lo que una rama rota registró desde `inicio` (ver `_proteger`)."""
        entradas = self._diario_rama[inicio:]
        del self._diario_rama[inicio:]
        acciones: list[Accion] = []
        cerrados: dict[str, set[int]] = {}
        for tipo, token in reversed(entradas):
            if tipo == "orden":
                o = self._estado.ordenes.get(token)
                if o is not None and o.estado is EstadoOrden.SENDING and o.id_das is None:
                    o.estado = EstadoOrden.CLOSED
                    o.notas = "no salió (H-5)"
                    cerrados.setdefault(o.ticker, set()).add(token)
                    acciones.append(Anotar("orden_estado", {"token": token, "ticker": o.ticker, "estado": o.estado.value,
                                                            "motivo": "H-5: la rama falló antes de enviarla (G1B-13)"}))
            elif tipo == "cancel":
                self._cancel_pedido.pop(token, None)
            elif tipo == "reemplazo":
                self._reemplazo_pedido.pop(token, None)
            elif tipo == "al_aceptar":
                self._cancelar_al_aceptar.pop(token, None)
            elif tipo == "continuacion":
                self._continuacion.pop(token, None)
        for ticker in sorted(cerrados):
            pos = self._estado.posiciones.get(ticker)
            intento = pos.intento if pos is not None else None
            if intento is not None and ({intento.token_agregar, intento.token_cruce} & cerrados[ticker]):
                self._soltar_cuadrados(intento)
                if intento.token_agregar is None and intento.token_cruce is None:
                    try:
                        acciones += self._cerrar_intento(pos, "H-5: la orden del intento no llegó a salir (G1A-10)")
                    except Exception as exc:  # noqa: BLE001 — H-5: sin cierre limpio, al menos no queda un intento zombi
                        pos.intento = None
                        acciones.append(Anotar("excepcion", {"ticker": ticker, "donde": "cerrar_intento_h5",
                                                             "error": f"{type(exc).__name__}: {exc}", "regla": "H-5"}))
            acciones += [Programar(T_BARRIDO, 0.0, {"motivo": "H-5: órdenes que no salieron (G1B-13)"}),
                         Programar(T_STOPS_PLAN, 0.0, {"ticker": ticker})]
        return acciones

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
                if a.tipo in ("incidente", "excepcion"):
                    clave_inc = str(a.datos.get("tipo") or a.tipo)
                    self._incidentes_dia[clave_inc] = self._incidentes_dia.get(clave_inc, 0) + 1
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
                           clave=f"locate_bloqueado:{a.ticker}")] + self._revertir_locate(a)))
                continue
            elif isinstance(a, InvalidarSerie) and salida and salida[-1] == a:
                continue
            salida.append(a)
        salida = _colapsar_programar(salida)
        self._estado.ultimo_seq_token = max(int(self._estado.ultimo_seq_token), self._tokens.ultimo_seq,
                                            self._tokens_locate.ultimo_seq)
        return salida

    def _normalizar_programar(self, p: Programar) -> Programar:
        """Las claves genéricas de las reglas pasan a llevar su dueño (§6.1: una clave repetida sustituye a la anterior).

        D2-07: las claves por orden de un lote (`tp_cruce:<lote>:<token>`,
        `tp_limbo:<lote>:<token>`) se recuerdan por lote para desprogramarlas
        todas cuando el lote se cierra (el ejecutor no desprograma por prefijo).
        """
        datos = p.datos if isinstance(p.datos, dict) else {}
        clave = p.clave
        base = clave.split(":", 1)[0]
        if base in (T_TP_CRUCE, T_TP_LIMBO) and ":" in clave and isinstance(datos.get("lote_id"), str):
            self._claves_lote.setdefault(datos["lote_id"], set()).add(clave)
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

    def _revertir_locate(self, a: LocateComprar) -> list[Accion]:
        """E2-07: la compra bloqueada por el diario roto no deja el locate en «comprando»: vuelve a «buscando» y a consultar."""
        for (ticker, sid), loc in sorted(self._estado.locates.items()):
            if ticker != a.ticker or loc.token != a.token:
                continue
            anotacion = Anotar(locates.ANOTACION_ESTADO, {"ticker": ticker, "strategy_id": sid,
                                                          "estado": locates.ESTADO_BUSCANDO,
                                                          "motivo": "corrección 4: compra bloqueada (diario roto); "
                                                                    "se vuelve a buscar (E2-07)"})
            nuevo = locates.aplicar_anotaciones(loc, [anotacion])
            if nuevo is not None:
                self._estado.locates[(ticker, sid)] = nuevo
            intervalo = _segundos(self._cfg.locates, "inquiry_intervalo_s", 3.0)
            return [anotacion, Programar(locates.clave_temporizador(ticker, sid), intervalo,
                                         {"ticker": ticker, "strategy_id": sid})]
        return []

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
        """Acciones del lote que una salida puede cerrar sin comprar de más (G1A-02, G1B-01, G1B-05).

        min(llenas − tp_pendiente del lote, lo que queda corto en el ticker
        menos TODAS las compras de cierre vivas del ticker: TP y hora de
        cualquier lote, salida del halt, cierre humano, cierre y reinicio). Lo
        que queda corto es la neta de fills y, si DAS ya la dijo, la menor de
        las dos (G1B-01: con DAS plano no se compra nada). Nunca negativo.
        """
        self._refrescar_tp_pendiente(pos)
        del_lote = max(int(lote.llenas) - int(lote.tp_pendiente), 0)
        if str(lote.direccion).strip().lower().startswith("long"):
            return del_lote                                  # el bot solo va corto; un lote largo conserva lo de siempre
        corto = -int(pos.neta_fills)
        if pos.neta_das is not None:
            corto = min(corto, -int(pos.neta_das))
        return max(min(del_lote, corto - self._comprando(pos.ticker)), 0)

    def _share_es_abierta(self) -> bool:
        """A-02 / D2a-08: `stops.replace_share_es_abierta` (bool) o el defecto de tipos: qué entiende DAS por `share`."""
        valor = (self._cfg.stops or {}).get(stops.CLAVE_SHARE_ES_ABIERTA) if isinstance(self._cfg.stops, dict) else None
        return valor if isinstance(valor, bool) else REPLACE_SHARE_ES_ABIERTA

    def _puede_gestionar_salida(self, pos: PosicionTicker) -> Optional[str]:
        """G1A-02 / G1B-01: None si una salida por temporizador puede salir; si no, el motivo (se reprograma a 0,5 s).

        Cerrada con: cisne negro (R-G-01: cierra el humano), halt (R-F-01),
        control manual (/cancelar_ordenes), cierre humano en curso (/cerrar),
        CONTROL_HUMANO puesto por /control_humano X, y con la reconciliación
        pendiente o DAS caído (R-J-02.5: nada sale hasta reconciliar).
        """
        ticker = pos.ticker
        if pos.estado is EstadoTicker.BS or pos.bs is not None:
            return "cisne negro"
        if pos.estado is EstadoTicker.HALT or ticker in self._halt_en_curso:
            return "halt"
        if ticker in self._manual:
            return "control manual"
        if ticker in self._cierre_humano:
            return "cierre humano en curso"
        if pos.estado is EstadoTicker.CONTROL_HUMANO and str(pos.motivo_estado).startswith(_MOTIVO_HUMANO_COMANDO):
            return "control humano"
        if pos.estado is EstadoTicker.CONTROL_HUMANO and str(pos.motivo_estado).startswith(_MOTIVO_STOP_MANUAL):
            return "control manual (/stop puesto a mano: las salidas vuelven con /reanudar)"
        degradados = self._estado.modo_degradado & {"reconciliacion", "das"}
        if degradados:
            return "modo degradado: " + ", ".join(sorted(degradados))
        return None

    def _compras_cierre(self, ticker: str) -> int:
        """G1A-01 / D2a-09: acciones que ya cierra una orden de salida del halt VIVA (HALT_OPEN, HALT_PM_LIMITE, HALT_BANDA).

        Es lo que `stops.plan` descuenta de la posición (`compras_cierre`): la
        salida del halt y los stops nunca suman más que lo que queda corto.
        D2-04: también la orden de un cierre humano AGOTADO cuya retirada
        (CANCEL) aún no confirmó DAS: si los stops vuelven por el respaldo de
        1 s, vuelven por lo que esa orden no cubre (y enteros con su Canceled).
        """
        return sum(_qty_viva(o) for o in self._vivas(ticker)
                   if o.lado is Lado.COMPRA and (o.proposito in _PROP_CIERRE_HALT or (
                       o.proposito is Proposito.CIERRE_HUMANO and o.token in self._cancel_pedido
                       and ticker not in self._cierre_humano)))

    def _pedidos_en_vuelo(self, ticker: str) -> dict[int, Optional[int]]:
        """D2a-05: lo que el decisor YA pidió a DAS en el ticker y aún no confirmó (para que `stops.plan` no lo repita).

        token → None: CANCEL en vuelo (cuenta como cancelada); token → k:
        REPLACE en vuelo que deja k ABIERTAS. Un REPLACE de stops de una
        versión ya invalidada no cuenta (el emisor pudo purgarlo).
        """
        pos = self._estado.posiciones.get(ticker)
        version = pos.version_stops if pos is not None else 0
        pedidos: dict[int, Optional[int]] = {}
        for o in self._vivas(ticker):
            if o.token in self._cancel_pedido:
                pedidos[o.token] = None
            elif o.token in self._reemplazo_pedido:
                _, _, _, version_pedida, abierta = self._reemplazo_pedido[o.token]
                if o.proposito not in _PROP_STOP or version_pedida >= version:
                    pedidos[o.token] = abierta
        return pedidos

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
        self._diario_rama.append(("orden", o.token))

    def _absorber(self, acciones: Iterable[Accion]) -> list[Accion]:
        """Registra al momento lo que sale de las reglas: órdenes nuevas, cancelaciones y reemplazos pedidos.

        Cada petición nueva queda también en el diario de la rama (G1B-13):
        si la rama lanza, `_proteger` la olvida (esa acción no sale).
        """
        lista = []
        al_tener_id: list[Anotar] = []
        for a in acciones:
            if isinstance(a, Reemplazar):
                # Ensayo 28-sep (DCOY 07:38): un REPLACE idéntico al que ya está en vuelo (misma cantidad, precio y
                # disparo) no se repite. Sin esta guarda, cada barrido de 1 s reenviaba el mismo REPLACE mientras el
                # primero esperaba su cuota: 4.530 REPLACE y la cuota de 100/min agotada (riesgo 11).
                pendiente = self._reemplazo_pedido.get(a.token)
                pedido_en = self._reemplazo_pedido_en.get(a.token)
                reciente = pedido_en is not None and self._ahora - pedido_en < REPLACE_EN_VUELO_MAX_S
                if (pendiente is not None and reciente and pendiente[0] == a.qty and pendiente[1] == a.precio
                        and pendiente[2] == a.stop):
                    orden = self._estado.ordenes.get(a.token)
                    lista.append(Anotar("replace_repetido", {"ticker": orden.ticker if orden is not None else None,
                                                             "token": a.token, "qty": a.qty,
                                                             "regla": "riesgo 11 / D2a-05"}))
                    continue
                self._reemplazo_pedido_en[a.token] = self._ahora
            lista.append(a)
        for a in lista:
            if isinstance(a, Anotar) and a.tipo == ANOTAR_CANCELAR_AL_TENER_ID:
                al_tener_id.append(a)
            elif isinstance(a, EnviarOrden):
                self._registrar_orden(a.orden)
            elif isinstance(a, Cancelar):
                token = a.token if a.token is not None else self._estado.id_a_token.get(a.id_das)
                if token is not None:
                    self._pedir_cancel(token, a.motivo)
            elif isinstance(a, CancelarTicker):
                for o in self._estado.ordenes.values():
                    if o.ticker == a.ticker and o.estado in _VIVOS:
                        self._pedir_cancel(o.token, a.motivo)
                        self._cancelar_al_aceptar.pop(o.token, None)
            elif isinstance(a, Reemplazar):
                o = self._estado.ordenes.get(a.token)
                llenas = max(int(o.llenas), 0) if o is not None else 0
                abierta = int(a.qty) if self._share_es_abierta() else max(int(a.qty) - llenas, 0)
                if a.token not in self._reemplazo_pedido:
                    self._diario_rama.append(("reemplazo", a.token))
                self._reemplazo_pedido[a.token] = (a.qty, a.precio, a.stop, int(a.version or 0), abierta)
                if o is not None and a.version:
                    o.version = a.version
            elif isinstance(a, Programar) and a.clave == T_STOPS_PLAN and isinstance(a.datos.get("ticker"), str):
                self._espera_plan.add(a.datos["ticker"])      # F2.1: el %POS que cuadre replanifica sin esperar 0,5 s
        for a in al_tener_id:                                 # después del CancelarTicker de la misma tanda (no lo borra)
            lista += self._registrar_cancelar_al_tener_id(a)
        return lista

    def _registrar_cancelar_al_tener_id(self, a: Anotar) -> list[Accion]:
        """R2-DEC-4 (R2-STOPS-1): `stops` pide cancelar una venta que aún no tiene id → al llegar su Accept (con id).

        Mismo mecanismo que `_cancelar_orden` con una orden sin id
        (`_cancelar_al_aceptar`). Se registra aunque un CANCEL ALLSYMB vaya en
        la misma tanda: una orden que DAS acepte DESPUÉS del ALLSYMB seguiría
        viva (lo conservador; como mucho, un CancelRej). Si entretanto ya tiene
        id y nadie pidió su CANCEL, el `Cancelar` sale ya.
        """
        token = a.datos.get("token") if isinstance(a.datos, dict) else None
        o = self._estado.ordenes.get(token) if type(token) is int else None
        if o is None or o.estado not in _VIVOS:
            return []
        motivo = str(a.datos.get("motivo") or "R-C-11 (3): cancelar al tener id")
        if o.id_das is not None:
            if o.token in self._cancel_pedido:
                return []
            cancelar = Cancelar(id_das=o.id_das, token=o.token, motivo=motivo)
            self._pedir_cancel(o.token, motivo)
            return [cancelar]
        if token not in self._cancelar_al_aceptar:
            self._diario_rama.append(("al_aceptar", token))
        self._cancelar_al_aceptar[token] = motivo
        return []

    def _pedir_cancel(self, token: int, motivo: str) -> None:
        if token not in self._cancel_pedido:
            self._diario_rama.append(("cancel", token))
        self._cancel_pedido[token] = motivo

    def _cancelar_orden(self, o: Orden, motivo: str) -> list[Accion]:
        """Cancela una orden viva una sola vez; sin id de DAS se cancela al llegar su Accept."""
        if o.estado not in _VIVOS or o.token in self._cancel_pedido:
            return []
        if o.id_das is None:
            if o.token not in self._cancelar_al_aceptar:
                self._diario_rama.append(("al_aceptar", o.token))
            self._cancelar_al_aceptar[o.token] = motivo
            return []
        return self._absorber([Cancelar(id_das=o.id_das, token=o.token, motivo=motivo)])

    def _poner_continuacion(self, token: int, tipo: str, datos: dict) -> None:
        if token not in self._continuacion:
            self._diario_rama.append(("continuacion", token))
        self._continuacion[token] = (tipo, datos)

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
        """Lo que depende de que una orden cambie: cancelación diferida, stop cancelado sin pedirlo, cuadre del intento.

        Además, cuando una orden pasa a terminal: la salida de un halt que NO
        llenó devuelve los stops (G1A-01), el paso «enviar» de cerrar todo
        sale en cuanto no queda nada vivo en el ticker (D2-03) y los stops
        vuelven tras retirar la orden de un cierre agotado (D2-04).
        """
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
        if paso_a_terminal:
            acciones += self._tras_terminal(o)
        return acciones

    def _tras_terminal(self, o: Orden) -> list[Accion]:
        """G1A-01 / D2-03 / D2-04: lo que desencadena que una orden quede terminal (ver `_tras_cambio_orden`)."""
        acciones: list[Accion] = []
        ticker = o.ticker
        pos = self._estado.posiciones.get(ticker)
        otra_salida_halt = any(x.proposito in _PROP_CIERRE_HALT and x.token != o.token for x in self._vivas(ticker))
        if (o.proposito in _PROP_CIERRE_HALT and o.lado is Lado.COMPRA and o.llenas < o.qty and pos is not None
                and pos.neta < 0 and not otra_salida_halt):
            plan = self._plan(ticker)
            acciones += [Anotar("halt_salida_sin_llenar", {"ticker": ticker, "token": o.token, "estado": o.estado.value,
                                                           "llenas": o.llenas, "qty": o.qty, "regla": "G1A-01"}),
                         Avisar(Nivel.AVISO, Grupo.B,
                                f"{avisos.escapar(ticker)}: la salida del halt ({avisos.escapar(o.proposito.value)}, "
                                f"token {o.token}) terminó {avisos.escapar(o.estado.value)} con {o.llenas}/{o.qty}: "
                                f"se restauran los stops a la posición (G1A-01)",
                                clave=f"halt_salida_sin_llenar:{ticker}:{o.token}")] + plan
        if ticker in self._cerrar_todo_enviar and not self._vivas(ticker):
            datos = self._cerrar_todo_enviar.pop(ticker)
            acciones += self._t_cerrar_todo(salidas.clave_cerrar_todo(ticker), datos)
        if ticker in self._retirando_cierre and not any(
                x.proposito in (Proposito.CIERRE_HUMANO, Proposito.CIERRE_REINICIO) for x in self._vivas(ticker)):
            acciones += self._reponer_tras_cierre(ticker, "la orden de cierre retirada ya está cancelada")
        elif (o.proposito is Proposito.CIERRE_HUMANO and o.lado is Lado.COMPRA and pos is not None and pos.neta < 0
              and ticker not in self._cierre_humano and ticker not in self._retirando_cierre):
            acciones += self._plan(ticker)          # D2-04: la retirada se confirmó tras el respaldo: stops enteros
        return acciones

    def _reponer_tras_cierre(self, ticker: str, motivo: str) -> list[Accion]:
        """D2-04: tras retirar la orden de un cierre agotado, los stops vuelven a mandar (sin tanda común con el cancel)."""
        self._retirando_cierre.discard(ticker)
        self._cierre_humano.discard(ticker)
        return ([Desprogramar(f"{T_CIERRE_REPONER}:{ticker}"),
                 Anotar("cierre_stops_repuestos", {"ticker": ticker, "motivo": motivo, "regla": "R-D-06 / D2-04"})]
                + self._plan(ticker))

    def _revisar_cuadre(self, o: Orden) -> list[Accion]:
        """Si la orden está cuadrada: suelta el token del intento o sigue con la continuación pendiente (TP, hora, R-D-07).

        G1A-09 (R-M-01): una salida (TP, hora, stop, cierre, halt, exceso) que
        cuadra con acciones llenas avisa al grupo B una vez. G1A-06 / G1B-02:
        sin ninguna entrada viva en el ticker, salen las salidas que esperaban
        a su Canceled (nunca juntas).
        """
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
            elif lote is not None and tipo == _CONT_PRIORIDAD:
                acciones += self._prioridad_al_ask(pos, lote, o, _proposito(datos.get("proposito"), Proposito.TP_CRUCE))
        if o.proposito in _PROP_AVISO_SALIDA and o.llenas > 0 and o.token not in self._salidas_avisadas:
            self._salidas_avisadas.add(o.token)
            acciones.append(self._aviso_salida(o))
        if o.ticker in self._salidas_tras_entrada and not self._entradas_vivas(o.ticker):
            acciones += self._salidas_pendientes(o.ticker)
        return acciones

    def _entradas_vivas(self, ticker: str) -> bool:
        return any(o.proposito in _PROP_ENTRADA for o in self._vivas(ticker))

    def _aviso_salida(self, o: Orden) -> Avisar:
        """G1A-09 (R-M-01 informativo): la salida cuadró: acciones, precio medio y motivo, al grupo B (nivel 1)."""
        fills = self._estado.fills.get(o.token, [])
        total = sum(f.qty for f in fills)
        medio = (sum((f.precio * f.qty for f in fills), Decimal("0")) / total) if total > 0 else o.precio
        pos = self._estado.posiciones.get(o.ticker)
        lote = pos.lotes.get(o.lote_id) if pos is not None and o.lote_id is not None else None
        quien = f" · {avisos.escapar(lote.estrategia)}" if lote is not None else ""
        lado = "COMPRA" if o.lado is Lado.COMPRA else "VENTA"
        neta = pos.neta if pos is not None else 0
        return Avisar(Nivel.INFO, Grupo.B,
                      f"SALIDA {avisos.escapar(o.ticker)}{quien}: {lado} {o.llenas} @ {_precio_texto(medio)} "
                      f"({avisos.escapar(o.proposito.value)}); posición {neta:+d}",
                      clave=f"salida:{o.token}")

    def _stop_cancelado_sin_pedir(self, o: Orden) -> list[Accion]:
        """F2.6 / R-C-04: DAS canceló un stop que no pedimos cancelar → aviso 2 y plan inmediato (en BS no se repone).

        G1B-14 / G1A-21 (R-C-04, excepción del HALT: «no se puede hacer nada
        hasta la reapertura»): con el ticker en halt no se repone ahora ni se
        gastan los intentos de R-C-03; se repone al reabrir (`_al_reabrir`).
        """
        pos = self._pos(o.ticker)
        en_halt = pos.estado is EstadoTicker.HALT or o.ticker in self._halt_en_curso
        if pos.estado is EstadoTicker.BS:
            que = "en cisne negro NO se repone (R-G-03)"
        elif en_halt:
            que = "el símbolo está en HALT: se repone al reabrir (R-C-04)"
        else:
            que = "se repone al momento (R-C-04)"
        acciones: list[Accion] = [
            Anotar("stop_cancelado_por_das", {"ticker": o.ticker, "token": o.token, "id_das": o.id_das,
                                              "proposito": o.proposito.value, "halt": en_halt, "regla": "R-C-04"}),
            Avisar(Nivel.AVISO, Grupo.B,
                   f"DAS canceló el stop {avisos.escapar(o.proposito.value)} de {avisos.escapar(o.ticker)} "
                   f"(token {o.token}) sin que el bot lo pidiera; {que}",
                   clave=f"stop_cancelado:{o.ticker}:{o.token}")]
        if pos.estado is EstadoTicker.BS:
            return acciones
        if en_halt:
            self._stops_diferidos_halt.add(o.ticker)
            return acciones
        return acciones + self._plan(o.ticker)

    # ═══════════════════════════ plan de stops ═════════════════════════════
    def _plan(self, ticker: str) -> list[Accion]:
        """F2.1: `stops.plan` sobre las órdenes del episodio (en BS, `cisne_negro.acciones_durante_bs`).

        No toca nada con el ticker en control manual (/cancelar_ordenes) ni con
        un cierre humano en curso (/cerrar, /cerrar_todo). A `stops.plan` le
        pasa `compras_cierre` (G1A-01: la salida del halt viva) y
        `pedidos_en_vuelo` (D2a-05: REPLACE/CANCEL sin confirmar, que no se
        repiten). G1B-07 / G1A-11: tras un stop rechazado (R-C-03) solo se
        filtran las órdenes NUEVAS de ese propósito (separación entre
        reintentos o agotado) y, con un stop que DAS quitó en un halt, las de
        cualquier stop hasta reabrir (G1B-14); reducciones, cancelaciones y los
        demás propósitos siguen. Las órdenes nuevas llevan token real solo si
        salen (tokens provisionales).
        """
        pos = self._estado.posiciones.get(ticker)
        if pos is None or ticker in self._manual or ticker in self._cierre_humano:
            return []
        vivas = self._ordenes_ticker(ticker)
        if pos.estado is EstadoTicker.BS:
            acciones = cisne_negro.acciones_durante_bs(pos, vivas, self._cfg, pos.version_stops)
        else:
            acciones = stops.plan(pos, vivas, self._cfg.stops, self._limit_up(ticker), _TokensProvisionales(),
                                  self._ahora_et, self._ruta_stop(), pos.version_stops,
                                  compras_cierre=self._compras_cierre(ticker),
                                  pedidos_en_vuelo=self._pedidos_en_vuelo(ticker))
            acciones = self._filtrar_stops_bloqueados(ticker, acciones)
            acciones = [EnviarOrden(dataclasses.replace(a.orden, token=self._tokens.siguiente()), serie=a.serie)
                        if isinstance(a, EnviarOrden) and a.orden.token < 0 else a for a in acciones]
        acciones = self._absorber(acciones)
        if not acciones:
            return []
        return [Anotar("stop_plan", {"ticker": ticker, "version": pos.version_stops, "neta": pos.neta,
                                     "neta_das": pos.neta_das, "acciones": len(acciones),
                                     "compras_cierre": self._compras_cierre(ticker)})] + acciones

    def _plan_propio(self, ticker: str) -> bool:
        """¿Los casos 2/3 de la reconciliación de este ticker los resuelve `_plan` (filtros, salida del halt, tokens)?"""
        return (ticker in self._stops_diferidos_halt or self._compras_cierre(ticker) > 0
                or any(clave[0] == ticker and hasta > self._ahora for clave, hasta in self._stop_bloqueo.items()))

    def _stop_bloqueado(self, ticker: str, proposito: Proposito) -> bool:
        """G1B-07 / G1B-14: ¿no se puede CREAR ahora un stop de ese propósito en ese ticker?"""
        if proposito in _PROP_STOP and ticker in self._stops_diferidos_halt:
            return True
        return self._stop_bloqueo.get((ticker, proposito), -math.inf) > self._ahora

    def _filtrar_stops_bloqueados(self, ticker: str, acciones: list[Accion]) -> list[Accion]:
        """Quita las órdenes NUEVAS de un propósito bloqueado (R-C-03 separación/agotado, halt); lo demás pasa."""
        filtradas: list[Accion] = []
        quitadas: list[str] = []
        for a in acciones:
            if isinstance(a, EnviarOrden) and self._stop_bloqueado(ticker, a.orden.proposito):
                quitadas.append(a.orden.proposito.value)
                continue
            filtradas.append(a)
        if quitadas and not any(isinstance(a, EnviarOrden) for a in filtradas):
            # el aviso de D2a-10 solo tiene sentido si el plan pone órdenes nuevas junto al stop no reconocido
            filtradas = [a for a in filtradas
                         if not (isinstance(a, Avisar) and (a.clave or "").startswith("stop_no_reconocido:"))
                         and not (isinstance(a, Anotar) and a.tipo == "stop_no_reconocido")]
        return filtradas

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
    def _entrada(self, s: Senal, *, es_reapertura: bool = False, t_cierre: Optional[float] = None,
                 sin_espera_simstatus: bool = False) -> list[Accion]:
        """F1 (R-B-01 v3, R-A-01, R-I-04, R-C-09, R-H-04, R-I-01, R-E-02): guardas, tamaño, lote y orden de agregar.

        R-D-07: con una salida viva en el ticker la entrada ESPERA
        («tp_espera_entrada», nunca más allá de su caducidad) y, si esa salida
        AGREGA para otra estrategia, pasa al ask (G1A-06 (a)); R-F-03: tras
        stop + halt no se reentra hasta una reapertura válida. `evaluar_senal`
        recibe la exclusión ya calculada (ajuste (b)); el tamaño es min(señal,
        locates de E9, capital con el margen de lo abierto y lo pendiente,
        D1-01/D1-06) y el margen se RESERVA (R-E-02). Con un intento vivo la
        señal se SUMA (F3). G1A-05: un ticker plano sin estado de símbolo de
        hace ≤ 5 s pregunta `GET SymStatus X` y espera la respuesta (≤ 1 s)
        antes de abrir. G1A-10 / D1-08: todo lo puro (lote, intento, orden)
        se calcula ANTES de mutar el estado; si algo lanza no queda nada a
        medias. COB-03: `metrica retraso_senal_pct` en cada decisión.
        """
        estado = self._estado
        cfg = self._cfg
        ev = s.evento
        ticker = s.ticker
        if s.id in estado.senales_vistas:
            return [Anotar("senal_repetida", {"senal_id": s.id, "ticker": ticker, "regla": "R-A-05"})]
        pos = self._pos(ticker)
        e = self._estrategia(getattr(ev, "strategy_id", None))
        if not es_reapertura and self._salidas_vivas(ticker):
            return self._prioridad_entrada(pos, e) + self._retener_entrada(s)
        if (ticker not in self._halt_en_curso and ticker in self._halt_hoy and ticker in self._stop_hoy
                and ticker not in self._reapertura_ok):
            return self._descartar(s, "R-F-03: stop y halt en el ticker; sin reentrada hasta una reapertura válida",
                                   avisar=True)
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
            return acciones + self._metrica_retraso(s, cot) + self._descartar(s, ver.motivo, avisar=ver.avisar)
        if e is None or cot is None or cot.ask is None:
            raise RuntimeError("evaluar_senal aceptó una señal sin estrategia o sin libro")   # comprobaciones 3 y 8
        if (not es_reapertura and not sin_espera_simstatus and self._abre_ticker_plano(pos)
                and not self._simstatus_fresco(ticker)):
            return acciones + self._esperar_simstatus(s)
        acciones += self._metrica_retraso(s, cot)
        precio_senal = precios.de_float(ev.precio)
        pedidas = entrada.qty_de_evento(getattr(ev, "acciones", None))
        reparto = locates.asignar_a_lote(estado.locates, ticker, pedidas, e.strategy_id)
        locates_libres = sum(n for _, n in reparto)
        tasa = simb.tasa_corta
        try:
            capital_qty, motivo_capital = self._acciones_que_caben(pedidas, cot.ask, tasa)
        except ValueError as exc:
            capital_qty, motivo_capital = 0, f"capital no calculable: {exc}"
        fraccion_max = cfg.entrada.get("fraccion_max_volumen_acum")
        qty, fraccion = entrada.qty_final(pedidas, locates_libres, capital_qty,
                                          precios.de_float(fraccion_max) if fraccion_max is not None else None,
                                          cot.volumen)
        if qty <= 0:
            motivo = (f"sin locates libres (R-H-04): {locates_libres}" if locates_libres <= 0
                      else f"capital (R-I-01): {motivo_capital}")
            extra: list[Accion] = []
            if motivo_capital == capital.MOTIVO_SIN_EQUITY:
                extra = self._pedir_equity()                       # D1-10: sin equity se reintenta con aviso 2
            return acciones + extra + self._descartar(s, motivo, avisar=True)
        # ── G1A-10 / D1-08: lo puro primero (si algo lanza aquí, el estado sigue intacto) ──
        lote = self._nuevo_lote(s, e, qty, pos)
        margen = capital.margen_inicial_corto(cot.ask, qty, tasa)
        intento_vivo = pos.intento is not None and pos.intento.fase is not FaseIntento.TERMINADO
        suma = self._preparar_suma(pos, lote) if intento_vivo else None
        intento = None
        orden: Optional[OrdenNueva] = None
        if not intento_vivo:
            cierre = t_cierre if t_cierre is not None else entrada.t_cierre_vela(
                s.momento if s.momento is not None else getattr(ev, "momento", None))
            intento = entrada.abrir_intento(pos, [lote], cot, precio_senal, cierre, cfg, self._ahora)
            if self._bloqueo_apertura(ticker) is None and _libro_utilizable(cot):
                orden = entrada.orden_agregar(intento, cot, cfg, self._tokens.siguiente(), self._ahora_et,
                                              nivel=lote.nivel_stop)
        # ── mutaciones ──
        estado.senales_vistas.add(s.id)
        pos.lotes[lote.id] = lote
        self._acciones_motor_lote[lote.id] = pedidas
        acciones.append(Anotar("senal", {"senal_id": s.id, "ticker": ticker, "strategy_id": e.strategy_id,
                                         "tipo": _tipo_evento(ev), "precio": precio_senal, "acciones_evento": pedidas,
                                         "qty": qty, "locates": reparto, "capital": motivo_capital,
                                         "recuperada": s.recuperada, "origen": s.origen,
                                         "reapertura": es_reapertura, "espera_simstatus": sin_espera_simstatus}))
        acciones.append(self._anotar_lote(lote))
        acciones += self._usar_locates(ticker, lote.id, reparto, qty)
        acciones.append(Anotar("metrica", {"nombre": "fraccion_volumen", "ticker": ticker, "senal_id": s.id,
                                           "valor": fraccion, "volumen": cot.volumen, "regla": "R-B-05"}))
        capital.reservar(estado.cuenta, margen)
        if suma is not None:
            acciones += self._sumar_a_intento(pos, lote, suma)
        elif intento is not None:
            pos.intento = intento
            self._tokens_intento[ticker] = set()
            acciones.append(Anotar("intento", {"ticker": ticker, "lotes": list(intento.lotes),
                                               "qty_total": intento.qty_total, "bid_senal": intento.bid_senal,
                                               "ask_senal": intento.ask_senal, "t_limite": intento.t_limite,
                                               "fase": intento.fase.value, "regla": "R-B-01 v3"}))
            if orden is not None:
                intento.fase = FaseIntento.AGREGANDO
                intento.token_agregar = orden.token
                self._tokens_intento.setdefault(ticker, set()).add(orden.token)
                self._lotes_de_orden[orden.token] = list(intento.lotes)
                acciones += self._absorber([EnviarOrden(orden)])
            else:
                acciones += self._enviar_agregar(pos)       # bloqueo o sin libro: cierra el intento con lo llenado (0)
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

    def _acciones_que_caben(self, pedidas: int, precio: Decimal, tasa: Optional[Decimal],
                            excluir_pendiente_de: Optional[str] = None) -> tuple[int, str]:
        """R-I-01 / 2c con el margen de lo abierto y lo pendiente (D1-01, D1-06) y el criterio de «alto riesgo» (D1-07)."""
        estado = self._estado

        def tasa_de(t: str) -> Optional[Decimal]:
            return self._mercado.simbolo(t).tasa_corta

        exposicion = capital.exposicion_corta(estado.posiciones, self._cot)
        abierto = capital.margen_corto_abierto(estado.posiciones, self._cot, tasa_de,
                                               excluir_pendiente_de=excluir_pendiente_de)
        pendiente = capital.margen_pendiente(estado.posiciones, self._cot, tasa_de,
                                             excluir_pendiente_de=excluir_pendiente_de)
        alto = capital.es_alto_riesgo(precio, tasa, self._cfg.entrada.get("alto_riesgo_si") or None)
        return capital.acciones_que_caben(pedidas, precio, estado.cuenta, tasa, exposicion, alto, self._ahora,
                                          self._max_edad_bp(), margen_corto_abierto_usd=abierto,
                                          margen_pendiente_usd=pendiente)

    def _pedir_equity(self) -> list[Accion]:
        """D1-10: sin equity no hay tope corto (no se entra): se vuelve a pedir `GET AccountInfo` y se avisa nivel 2."""
        self._accountinfo_pedido_en = self._ahora
        return [Consultar(protocolo.cmd_get("AccountInfo")),
                Avisar(Nivel.AVISO, Grupo.B, "Sin equity de la cuenta (GET AccountInfo): no se abren entradas hasta "
                                             "leerlo; se vuelve a pedir (R-I-01, D1-10)", clave="sin_equity")]

    def _metrica_retraso(self, s: Senal, cot: Optional[Cotizacion]) -> list[Accion]:
        """COB-03 (R-A-01, §11.1): el retraso de la señal (último de DAS contra el precio de la señal) al diario, acepte o no."""
        if cot is None or not _es_precio(cot.last):
            return []
        try:
            precio = precios.de_float(getattr(s.evento, "precio", None))
            valor = precios.distancia_pct(cot.last, precio)
        except (TypeError, ValueError):
            return []
        return [Anotar("metrica", {"nombre": "retraso_senal_pct", "ticker": s.ticker, "senal_id": s.id,
                                   "valor": valor, "precio_senal": precio, "ultimo": cot.last, "regla": "R-A-01"})]

    def _abre_ticker_plano(self, pos: PosicionTicker) -> bool:
        return not self._tiene_posicion(pos) and (pos.intento is None or pos.intento.fase is FaseIntento.TERMINADO)

    def _simstatus_fresco(self, ticker: str) -> bool:
        en = self._simstatus_en.get(ticker)
        return en is not None and 0 <= self._ahora - en <= SIMSTATUS_FRESCO_S

    def _consulta_simstatus(self, ticker: Optional[str]) -> Consultar:
        """COB-04 (§5.8): `GET SymStatus X` o, con `tecnicos.get_con_simbolo` false, sin símbolo."""
        con_simbolo = self._cfg.tecnicos.get("get_con_simbolo", True) is not False
        return Consultar(protocolo.cmd_get("SymStatus", ticker if con_simbolo else None))

    def _esperar_simstatus(self, s: Senal) -> list[Accion]:
        """G1A-05: el ticker está plano y no se sabe si está parado → `GET SymStatus X` y la señal espera (≤ 1 s).

        La espera no escribe en el diario (la decisión, con `espera_simstatus`
        en su registro «senal», sale al llegar la respuesta): así la señal se
        decide con el estado del diario de ese momento, no con el de una
        escritura intermedia.
        """
        ticker = s.ticker
        lista = self._entradas_simstatus.setdefault(ticker, [])
        primera = not lista
        if all(x.id != s.id for x in lista):
            lista.append(s)
        if not primera:
            return []
        return [self._consulta_simstatus(ticker),
                Programar(f"{T_SIMSTATUS_ESPERA}:{ticker}", SIMSTATUS_ESPERA_S, {"ticker": ticker})]

    def _prioridad_entrada(self, pos: PosicionTicker, e: Optional[EstrategiaConfig]) -> list[Accion]:
        """G1A-06 (a) / R-D-07: llega una entrada con una salida que AGREGA de OTRA estrategia viva → esa salida pasa al ask.

        Se cancela la orden que agrega (TP, hora, salida del motor, cierre y
        reinicio) y, CONFIRMADO su Canceled, lo que quede sale al ask sin tope
        (R-D-07: «el take profit se tira al ask»). La entrada espera a que no
        quede ninguna salida viva (y nunca más allá de su caducidad).
        """
        if e is None:
            return []
        acciones: list[Accion] = []
        for o in self._vivas(pos.ticker):
            if o.proposito not in _PROP_AGREGA_SALIDA or o.lado is not Lado.COMPRA or o.token in self._cancel_pedido:
                continue
            lote = pos.lotes.get(o.lote_id) if o.lote_id is not None else None
            if lote is None or lote.strategy_id == e.strategy_id:
                continue
            nuevo = (Proposito.HORA_ASK if o.proposito is Proposito.HORA_AGREGAR
                     else Proposito.CIERRE_REINICIO if o.proposito is Proposito.CIERRE_REINICIO
                     else Proposito.TP_CRUCE)
            self._poner_continuacion(o.token, _CONT_PRIORIDAD, {"lote_id": lote.id, "ticker": pos.ticker,
                                                                "proposito": nuevo.value})
            acciones.append(Anotar("prioridad_tp", {"ticker": pos.ticker, "lote_id": lote.id, "token": o.token,
                                                    "entrada_de": e.strategy_id, "regla": "R-D-07 (G1A-06 a)"}))
            acciones += self._cancelar_orden(o, "R-D-07: llega una entrada de otra estrategia; la salida va al ask")
        return acciones

    def _prioridad_al_ask(self, pos: PosicionTicker, lote: Lote, o: Orden, proposito: Proposito) -> list[Accion]:
        """R-D-07 (G1A-06): tras el Canceled de la salida que agregaba, lo que quede al ask SIN tope (con la guarda)."""
        if lote.estado not in _LOTE_VIVO or lote.llenas <= 0:
            return []
        clave = f"{T_PRIORIDAD_ASK}:{lote.id}:{o.token}"
        datos = {"lote_id": lote.id, "ticker": pos.ticker, "token": o.token, "proposito": proposito.value}
        guarda = self._puede_gestionar_salida(pos)
        if guarda is not None:
            return self._aplazar_salida(pos, clave, datos, guarda)
        resto = min(max(o.qty - o.llenas, 0), self._libres(pos, lote))
        if resto <= 0:
            return []
        cot = self._cot(pos.ticker)
        if cot is None or not _es_precio(cot.ask):
            return self._aplazar_salida(pos, clave, datos, "sin ask en DAS")
        orden = salidas.orden_al_ask(lote, resto, cot, self._cfg, self._tokens.siguiente, self._ahora_et, None, proposito)
        acciones: list[Accion] = [Anotar("prioridad_tp", {"ticker": pos.ticker, "lote_id": lote.id,
                                                          "token": orden.token, "qty": resto, "precio": orden.precio,
                                                          "regla": "R-D-07"})]
        acciones += self._absorber([EnviarOrden(orden)])
        acciones += self._seguimiento_salida(lote, orden)
        return acciones

    def _seguimiento_salida(self, lote: Lote, orden: OrdenNueva) -> list[Accion]:
        """Tras una orden de salida AL ASK: la hora se persigue (corrección 11) y el cruce del TP vigila el limbo (D2-13)."""
        if orden.proposito in (Proposito.HORA_ASK, Proposito.CIERRE_REINICIO):
            self._persecuciones[orden.token] = 0
            return [Programar(f"{T_PERSEGUIR_ASK}:{orden.token}", self._perseguir_cada(),
                              {"token": orden.token, "ticker": orden.ticker, "lote_id": lote.id})]
        if orden.proposito in (Proposito.TP_CRUCE, Proposito.SALIDA_MOTOR_CRUCE):
            return [salidas.programa_limbo_tp(lote, orden, self._cfg)]
        return []

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
        """R-A-03 v2 (ajuste (b)): `exclusiones.excluida` con la ficha y los splits de Massive; sin lista → no excluye + aviso.

        G1A-03: con la caché de la referencia no se abre red (sin ficha → A12,
        «sin_ficha»: no se opera y la ficha queda pedida para la precarga).
        Mientras la precarga aún no ha intentado los splits de hoy no se avisa
        (y no se excluye por split, como sin lista: corrección 17).
        """
        acciones: list[Accion] = []
        ficha = self._ficha(ticker)
        splits = self._splits_hoy()
        pendientes = self._splits_pendientes()
        if splits is None and not pendientes and self._una_vez_al_dia("splits_sin_lista"):
            acciones.append(Avisar(Nivel.AVISO, Grupo.B,
                                   "No se pudo leer la lista de splits de hoy en Massive: NO se excluye por split "
                                   "hasta tenerla (corrección 17)", clave="splits_sin_lista"))
            acciones.append(Anotar("referencia", {"splits": None, "regla": "corrección 17"}))
        motivo = exclusiones.excluida(ticker, e, ficha, splits, list(self._cfg.lista_negra), self._estado.dia,
                                      dict(self._cfg.exclusiones))
        if motivo == "sin_ficha":
            acciones.append(Anotar("referencia", {"ticker": ticker, "ficha": None,
                                                  "motivo": "A12: sin ficha de Massive en la caché; se pide a la "
                                                            "precarga y no se opera (G1A-03)"}))
        return motivo, acciones

    def _ficha(self, ticker: str) -> Any:
        """La ficha de la referencia. Con la caché (G1A-03) NUNCA red; con una referencia en memoria, la de siempre."""
        if self._referencia is None:
            return None
        simbolo = str(ticker).strip().upper()
        if _tiene_cache_referencia(self._referencia):
            try:
                return self._referencia.ficha_en_cache(simbolo)
            except Exception:  # noqa: BLE001 — frontera: la caché no debe lanzar; si lo hace, sin ficha (A12: no se opera)
                return None
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

    def _pedir_ficha(self, ticker: str) -> None:
        """G1A-03 / G1B-08: radar o hidratado → que la precarga traiga la ficha antes de la señal (sin red aquí)."""
        if self._referencia is None:
            return
        if _tiene_cache_referencia(self._referencia):
            pedir = getattr(self._referencia, "pedir_ficha", None)
            try:
                if callable(pedir):
                    pedir(str(ticker).strip().upper())
                else:
                    self._referencia.ficha_en_cache(str(ticker).strip().upper())
            except Exception:  # noqa: BLE001 — frontera: pedir una ficha nunca puede tumbar al decisor
                return
            return
        self._ficha(ticker)

    def _splits_pendientes(self) -> bool:
        if self._referencia is None or not _tiene_cache_referencia(self._referencia):
            return False
        pendientes = getattr(self._referencia, "splits_pendientes", None)
        try:
            return bool(pendientes(self._estado.dia)) if callable(pendientes) else False
        except Exception:  # noqa: BLE001 — frontera: sin saberlo, se trata como «falló» (aviso de la corrección 17)
            return False

    def _splits_hoy(self) -> Optional[set[str]]:
        dia = self._estado.dia
        if self._splits is not None and self._splits[0] == dia:
            return set(self._splits[1])
        if self._referencia is None:
            return None
        if _tiene_cache_referencia(self._referencia):
            try:
                splits = self._referencia.splits_en_cache(dia)
            except Exception:  # noqa: BLE001 — frontera: la caché no debe lanzar; sin lista no se excluye (corrección 17)
                splits = None
            if splits is None:
                return None
            self._splits = (dia, set(splits))
            return set(splits)
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
        """Al cerrar el intento, las acciones localizadas que el lote no llegó a usar vuelven a estar libres.

        Usadas = lo MÁS que llegó a llenar el lote (un stop que lo redujo
        durante el intento, G1B-02, no devuelve locates ya consumidos).
        """
        cargos = self._locates_de_lote.pop(lote.id, [])
        sobran = max(lote.pedidas - max(lote.llenas, self._llenas_max_lote.get(lote.id, 0)), 0)
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
        """R-D-07: una entrada que llega con una salida viva en el ticker espera a que la salida termine (G1A-06: ≤ caducidad)."""
        lista = self._entradas_en_espera.setdefault(s.ticker, [])
        if all(x.id != s.id for x in lista):
            lista.append(s)
        return [Anotar("senal_en_espera", {"senal_id": s.id, "ticker": s.ticker,
                                           "motivo": "R-D-07: salida viva en el ticker; la entrada espera"}),
                Programar(f"{T_TP_ESPERA_ENTRADA}:{s.ticker}", TP_ESPERA_ENTRADA_S, {"ticker": s.ticker})]

    def _caducada(self, s: Senal) -> bool:
        """R-B-04 (G1A-06): ¿pasó ya la caducidad de la señal (cierre de su vela + caducidad_senal_s)?"""
        try:
            cierre = entrada.t_cierre_vela(s.momento if s.momento is not None else getattr(s.evento, "momento", None))
        except (TypeError, ValueError):
            return False
        caducidad = _segundos(self._cfg.entrada, "caducidad_senal_s", float(ENTRADA_CADUCIDAD_S))
        return self._ahora_et.timestamp() > cierre + caducidad

    def _anotar_lote(self, lote: Lote) -> Anotar:
        return Anotar("lote", {
            "lote_id": lote.id, "ticker": lote.ticker, "strategy_id": lote.strategy_id, "estrategia": lote.estrategia,
            "direccion": lote.direccion, "pedidas": lote.pedidas, "llenas": lote.llenas,
            "precio_medio": lote.precio_medio, "nivel_stop": lote.nivel_stop, "riesgo_usd": lote.riesgo_usd,
            "estado": lote.estado.value, "reentrada_n": lote.reentrada_n, "entrada_idx": lote.entrada_idx,
            "nivel_piramide": lote.nivel_piramide, "hora_salida": lote.hora_salida, "eod": lote.eod,
            "principal_consumido": lote.principal_consumido, "version_estrategia": lote.version_estrategia})

    # ── máquina del intento (R-B-01 v3, R-B-02, R-B-03) ─────────────────
    def _preparar_suma(self, pos: PosicionTicker, lote: Lote) -> tuple[Any, list[Accion], Optional[int], Optional[int]]:
        """F3 (puro, G1A-10): el intento sumado y sus cancelaciones SIN tocar el estado (valida antes de mutar)."""
        intento = pos.intento
        if intento is None:
            raise RuntimeError(f"{pos.ticker}: sumar a un intento que no existe")
        token_vivo = (intento.token_agregar if intento.fase is FaseIntento.AGREGANDO
                      else intento.token_cruce if intento.fase is FaseIntento.CRUZANDO else None)
        orden_viva = self._estado.ordenes.get(token_vivo) if token_vivo is not None else None
        id_viva = orden_viva.id_das if orden_viva is not None else None
        nuevo, cancelaciones = entrada.sumar_senal(intento, lote, id_das_viva=id_viva)
        return nuevo, cancelaciones, token_vivo, id_viva

    def _sumar_a_intento(self, pos: PosicionTicker, lote: Lote, suma: Optional[tuple] = None) -> list[Accion]:
        """F3 / R-B-03: la segunda señal se SUMA; con orden viva se cancela y, confirmado el Canceled, se reinicia con el total."""
        intento = pos.intento
        if intento is None:
            raise RuntimeError(f"{pos.ticker}: sumar a un intento que no existe")
        ticker = pos.ticker
        nuevo, cancelaciones, token_vivo, id_viva = suma if suma is not None else self._preparar_suma(pos, lote)
        pos.intento = nuevo
        acciones: list[Accion] = [Anotar("intento", {"ticker": ticker, "lotes": list(nuevo.lotes),
                                                     "qty_total": nuevo.qty_total, "fase": nuevo.fase.value,
                                                     "suma": lote.id, "regla": "R-B-03"})]
        if nuevo.fase is FaseIntento.CANCELANDO and intento.fase is not FaseIntento.CANCELANDO:
            self._poner_motivo(ticker, MOTIVO_SUMA)
            if token_vivo is not None and id_viva is None:
                if token_vivo not in self._cancelar_al_aceptar:
                    self._diario_rama.append(("al_aceptar", token_vivo))
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
            bps = (medio - intento.precio_senal) / intento.precio_senal * 10000
            self._slippage_bps.append(bps)
            for lote in abiertos:
                self._operaciones_estrategia[lote.strategy_id] = self._operaciones_estrategia.get(lote.strategy_id, 0) + 1
            acciones.append(Anotar("metrica", {"nombre": "slippage_vs_senal_pct", "ticker": ticker,
                                               "precio_senal": intento.precio_senal, "precio_medio": medio,
                                               "valor": bps / 100, "bps": bps,
                                               "regla": "F1.9 / §11.1 ÁREA P (COB-05)"}))
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
    def _salida_motor(self, s: Senal, *, diferida: bool = False, modo: str = _SALIDA_NORMAL) -> list[Accion]:
        """F4 (R-D-03 v2, R-D-07, R-C-07): el `Evento` de salida o de pirámide «reduce» → tratamiento de `salidas`.

        TP / como TP: `tp_parcial` (agregar 60 s en el punto medio; con el
        libro inutilizable, el cruce a los 2 s: D2-12) y `tp_cruce`. Salida
        por tiempo («Partial TP (Hour)», «(Time)», «Time Limit», D2-05): la
        qty del evento al ask sin tope y a perseguir. EOD solo se anota (manda
        el reloj); el SL del motor con la posición abierta es una divergencia.
        Con un intento de entrada vivo en el ticker (G1A-06 (b), G1B-02,
        COB-01): la salida de la MISMA estrategia saca sus lotes del intento
        (se cancela si solo eran suyos) y la de OTRA pausa el intento (R-D-07);
        en los dos casos la orden de salida sale SOLO cuando ya no queda
        ninguna entrada viva en el ticker (nunca juntas; la de prioridad, al
        ask sin tope). Con la guarda cerrada (cisne negro, halt, manual, cierre
        humano) no se manda nada; con el modo degradado se espera (G1B-01).
        `diferida` = segunda pasada de una salida que esperaba.
        """
        ev = s.evento
        ticker = s.ticker
        estado = self._estado
        acciones: list[Accion] = []
        if not diferida:
            estado.senales_vistas.add(s.id)
            acciones.append(Anotar("senal", {"senal_id": s.id, "ticker": ticker,
                                             "strategy_id": getattr(ev, "strategy_id", None),
                                             "tipo": _tipo_evento(ev), "motivo": getattr(ev, "motivo", None),
                                             "acciones_evento": getattr(ev, "acciones", None),
                                             "accion_piramide": getattr(ev, "accion_piramide", None),
                                             "nivel": getattr(ev, "nivel", None),
                                             "entrada_idx": getattr(ev, "entrada_idx", None)}))
        pos = estado.posiciones.get(ticker)
        if pos is None:
            return acciones + [Anotar("salida_sin_posicion", {"senal_id": s.id, "ticker": ticker})]
        sid = getattr(ev, "strategy_id", None)
        intento = pos.intento if pos.intento is not None and pos.intento.fase is not FaseIntento.TERMINADO else None
        misma = intento is not None and any(
            pos.lotes.get(lid) is not None and pos.lotes[lid].strategy_id == sid for lid in intento.lotes)
        if not diferida and misma and _tipo_evento(ev) == "salida":
            acciones += self._retirar_estrategia_del_intento(pos, str(sid))       # COB-01 (R-B-01 v3 punto 1)
        lote = self._lote_de_salida(pos, ev)
        clase = _clase_salida(ev)
        self._refrescar_tp_pendiente(pos)
        vivas = self._vivas(ticker)
        codigo = salidas.tratamiento(clase, pos, lote, vivas, str(self._cfg.salidas.get("salida_motor", "como_tp")))
        if not diferida:
            for a in salidas.avisos_de_tratamiento(codigo, clase, getattr(ev, "motivo", None), pos, lote):
                if isinstance(a, Avisar) and a.clave and a.clave.startswith("daily_limit:") \
                        and not self._una_vez_al_dia(a.clave):
                    continue
                acciones.append(a)
        if codigo not in (salidas.TRATAR_TP, salidas.TRATAR_COMO_TP, salidas.TRATAR_HORA_EVENTO) or lote is None:
            return acciones
        guarda = self._puede_gestionar_salida(pos)
        if guarda is not None:
            if guarda.startswith("modo degradado") or diferida:
                return acciones + self._salida_en_espera(s, modo, guarda)
            return acciones + [Anotar("salida_omitida", {"senal_id": s.id, "ticker": ticker, "estado": pos.estado.value,
                                                         "motivo": f"{guarda}: no se envía"})]
        if intento is not None and pos.intento is intento and intento.fase is not FaseIntento.TERMINADO:
            if misma:
                if _tipo_evento(ev) != "salida":
                    acciones += self._cancelar_intento(pos, MOTIVO_CIERRE)           # G1B-02: su TP cancela su entrada
            elif ticker not in self._intento_pausado:
                modo = _SALIDA_PRIORIDAD
                acciones.append(Anotar("prioridad_tp", {"ticker": ticker, "lote_id": lote.id, "senal_id": s.id,
                                                        "regla": "R-D-07 (G1A-06 b)"}))
                acciones += self._cancelar_intento(pos, MOTIVO_PRIORIDAD)
        if self._entradas_vivas(ticker):
            return acciones + self._salida_en_espera(s, modo, "entrada viva en el ticker (nunca juntas, R-D-07)")
        libres = self._libres(pos, lote)
        pedidas = entrada.qty_de_evento(getattr(ev, "acciones", None))
        qty = min(pedidas, libres) if pedidas > 0 else libres
        acciones.append(self._anotar_proporcion(s, lote, pedidas, qty))
        if qty <= 0:
            # R2-DEC-1 (G1B-05): 0 libres con la posición aún corta y acciones en el lote (una HALT_BANDA o un cierre
            # humano vivos, DAS atrasado) → la salida espera y se vuelve a mirar; no se pierde en silencio
            espera = self._espera_sin_libres(pos, lote, f"salida_motor:{s.id}", "salida del motor")
            if espera is not None:
                en_s, anotado = espera
                return acciones + anotado + self._salida_en_espera(s, modo, "sin acciones libres (R2-DEC-1)", en_s)
            return acciones + [Anotar("salida_omitida", {"senal_id": s.id, "ticker": ticker,
                                                         "motivo": "el lote no tiene acciones libres"})]
        self._olvidar_sin_libres(f"salida_motor:{s.id}")
        cot = self._cot(ticker)
        if modo == _SALIDA_PRIORIDAD:
            if cot is None or not _es_precio(cot.ask):
                return acciones + self._salida_en_espera(s, modo, "sin ask en DAS")
            orden = salidas.orden_al_ask(lote, qty, cot, self._cfg, self._tokens.siguiente, self._ahora_et, None,
                                         Proposito.TP_CRUCE)
            acciones += self._absorber([EnviarOrden(orden)])
            acciones.append(Anotar("prioridad_tp", {"ticker": ticker, "lote_id": lote.id, "token": orden.token,
                                                    "qty": qty, "regla": "R-D-07"}))
            acciones += self._seguimiento_salida(lote, orden)
        elif codigo == salidas.TRATAR_HORA_EVENTO:
            acciones += self._salida_por_tiempo(s, pos, lote, pedidas, qty, cot, modo)
        else:
            orden_tp, programa = salidas.tp_parcial(lote, qty, cot, self._cfg, self._tokens.siguiente, self._ahora_et,
                                                    sin_libro_espera_s=TP_SIN_LIBRO_ESPERA_S)
            if orden_tp is not None:
                acciones += self._absorber([EnviarOrden(orden_tp)])
            else:
                acciones.append(Anotar("salida_sin_libro", {"ticker": ticker, "lote_id": lote.id, "qty": qty,
                                                            "regla": "D2-12: el cruce se decide a los 2 s"}))
            acciones.append(programa)
        self._refrescar_tp_pendiente(pos)
        return acciones

    def _salida_por_tiempo(self, s: Senal, pos: PosicionTicker, lote: Lote, pedidas: int, qty: int,
                           cot: Optional[Cotizacion], modo: str) -> list[Accion]:
        """D2-05 (R-D-01 / R-D-08): «Partial TP (Hour)», «(Time)», «Time Limit» → la qty del evento AL ASK sin tope y a perseguir."""
        if pedidas <= 0:
            return [Anotar("salida_omitida", {"senal_id": s.id, "ticker": pos.ticker, "lote_id": lote.id,
                                              "motivo": "salida por tiempo sin cantidad en el evento: el EOD cierra el "
                                                        "resto (D2-05)"})]
        if cot is None or not _es_precio(cot.ask):
            return [Avisar(Nivel.AVISO, Grupo.B, f"{avisos.escapar(pos.ticker)}: salida por tiempo sin ask en DAS; se "
                                                 f"reintenta", clave=f"hora_sin_ask:{lote.id}")] + \
                self._salida_en_espera(s, modo, "sin ask en DAS")
        try:
            orden = salidas.orden_hora_evento(lote, min(pedidas, qty), cot, self._cfg, self._tokens.siguiente,
                                              self._ahora_et)
        except ValueError as exc:
            return [Anotar("salida_omitida", {"senal_id": s.id, "ticker": pos.ticker, "lote_id": lote.id,
                                              "motivo": f"salida por tiempo imposible: {exc}"})]
        total = orden.qty >= self._libres(pos, lote)
        acciones: list[Accion] = [Anotar("salida_hora", {"ticker": pos.ticker, "lote_id": lote.id, "paso": "evento",
                                                         "qty": orden.qty, "precio": orden.precio,
                                                         "regla": "D2-05 / R-D-08"})]
        acciones += self._absorber([EnviarOrden(orden)])
        acciones += self._seguimiento_salida(lote, orden)
        if total:
            despues = _segundos((self._cfg.salidas or {}).get("eod") or {}, "comprobar_despues_s", 30.0)
            acciones.append(Programar(salidas.clave_lote(T_EOD_COMPROBAR, lote.id), despues,
                                      {"lote_id": lote.id, "ticker": pos.ticker, "motivo": "hora_evento"}))
        return acciones

    def _anotar_proporcion(self, s: Senal, lote: Lote, pedidas: int, qty: int) -> Anotar:
        """G1A-16 / G1B-16 (pregunta 3 a Jaume): la proporción del motor frente a la aplicada, SIEMPRE al diario."""
        motor = self._acciones_motor_lote.get(lote.id)
        return Anotar("salida_proporcion", {
            "senal_id": s.id, "ticker": lote.ticker, "lote_id": lote.id, "acciones_evento": pedidas,
            "acciones_motor_entrada": motor, "lote_llenas": lote.llenas, "qty": qty,
            "proporcion_motor": (Decimal(pedidas) / Decimal(motor)) if motor and pedidas > 0 else None,
            "proporcion_aplicada": (Decimal(qty) / Decimal(lote.llenas)) if lote.llenas > 0 and qty > 0 else None,
            "regla": "R-D-03 v2 / F4.1 (G1A-16: acciones del evento, no proporción; pregunta 3)"})

    def _salida_en_espera(self, s: Senal, modo: str, motivo: str,
                          en_s: float = SALIDA_REPROGRAMAR_S) -> list[Accion]:
        """G1A-06 / G1B-02 / G1B-01: la salida espera (entrada viva, sin ask o modo degradado) y se revisa cada 0,5 s.

        R2-DEC-1: `en_s` = 5 s cuando lleva ≥ 60 s sin acciones libres.
        """
        ticker = s.ticker
        lista = self._salidas_tras_entrada.setdefault(ticker, [])
        if all(x.id != s.id for x, _ in lista):
            lista.append((s, modo))
        return [Anotar("salida_en_espera", {"senal_id": s.id, "ticker": ticker, "modo": modo, "motivo": motivo}),
                Programar(f"{T_SALIDA_ESPERA}:{ticker}", en_s, {"ticker": ticker})]

    def _salidas_pendientes(self, ticker: str) -> list[Accion]:
        """Sin ninguna entrada viva en el ticker, salen (en su orden) las salidas del motor que esperaban."""
        pendientes = self._salidas_tras_entrada.pop(ticker, [])
        acciones: list[Accion] = [Desprogramar(f"{T_SALIDA_ESPERA}:{ticker}")] if pendientes else []
        for s, modo in pendientes:
            acciones += self._salida_motor(s, diferida=True, modo=modo)
        # R2-DEC-1: varias salidas que vuelven a esperar comparten `salida_espera:X`: manda la espera MÁS CORTA
        clave = f"{T_SALIDA_ESPERA}:{ticker}"
        programas = [a for a in acciones if isinstance(a, Programar) and a.clave == clave]
        if len(programas) > 1:
            corto = min(programas, key=lambda p: p.en_s)
            acciones = [a for a in acciones if not (isinstance(a, Programar) and a.clave == clave)] + [corto]
        return acciones

    def _retirar_estrategia_del_intento(self, pos: PosicionTicker, sid: str) -> list[Accion]:
        """COB-01 (R-B-01 v3 punto 1: «se cancela antes si la estrategia deja de decir dentro») / G1B-02.

        Si el intento solo tiene lotes de esa estrategia → se cancela (se queda
        lo llenado). Si hay otras estrategias sumadas (F3), se retiran SOLO sus
        lotes: su parte llenada queda ABIERTA (con sus temporizadores) y el
        intento se reinicia, tras el Canceled, con lo que piden las demás.
        """
        intento = pos.intento
        if intento is None:
            return []
        suyos = [lid for lid in intento.lotes if pos.lotes.get(lid) is not None and pos.lotes[lid].strategy_id == sid]
        if not suyos:
            return []
        if len(suyos) == len(intento.lotes):
            return [Anotar("intento", {"ticker": pos.ticker, "estrategia_fuera": sid, "motivo":
                                       "COB-01: la estrategia sale; se cancela su entrada (R-B-01 v3 punto 1)"})] + \
                self._cancelar_intento(pos, MOTIVO_CIERRE)
        acciones: list[Accion] = []
        for lid in suyos:
            lote = pos.lotes[lid]
            intento.lotes = [x for x in intento.lotes if x != lid]
            intento.qty_total -= lote.pedidas
            intento.llenas = max(intento.llenas - lote.llenas, 0)
            acciones += self._devolver_locates(lote)
            nuevo = dataclasses.replace(lote, estado=EstadoLote.ABIERTO if lote.llenas > 0 else EstadoLote.CANCELADO,
                                        pedidas=max(lote.llenas, 0) or lote.pedidas)
            pos.lotes[lid] = nuevo
            acciones.append(self._anotar_lote(nuevo))
            if nuevo.estado is EstadoLote.ABIERTO:
                acciones += self._temporizadores_lote(nuevo)
        acciones.append(Anotar("intento", {"ticker": pos.ticker, "lotes": list(intento.lotes),
                                           "qty_total": intento.qty_total, "estrategia_fuera": sid,
                                           "motivo": "COB-01: se retiran los lotes de la estrategia que sale"}))
        return acciones + self._cancelar_intento(pos, MOTIVO_SUMA)

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
        self._pedir_ficha(ticker)                           # G1A-03: la precarga la trae; aquí nunca red
        filas = [f for f in (s.estimacion or []) if isinstance(f, dict)]
        acciones: list[Accion] = []
        for sid in sorted({str(f.get("strategy_id")) for f in filas if f.get("strategy_id")}):
            e = self._estrategia(sid)
            if e is None or not e.ejecutar:
                continue
            acciones += self._paso_locate(ticker, e, estimacion=filas)
        return acciones + self._armar_simstatus()           # E1-03 / G1A-05: el radar suscrito también se vigila

    def _senal_hidratado(self, s: Senal) -> list[Accion]:
        if isinstance(s.ticker, str) and s.ticker:
            self._pedir_ficha(s.ticker)                      # G1B-08: sin red en el hilo del decisor
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
                 "ticker": o.ticker, "cruda": m.cruda}
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
                acciones += self._tras_terminal(o)
        elif accion in ("CancelRej", "ReplaceRej"):
            o.notas = m.notas
            if accion == "ReplaceRej":
                self._reemplazo_pedido.pop(o.token, None)
            else:
                self._cancel_pedido.pop(o.token, None)      # D2a-05: la orden sigue viva; ya no hay CANCEL en vuelo
            terminal = (o.estado in (EstadoOrden.EXECUTED, EstadoOrden.CANCELED, EstadoOrden.CLOSED,
                                     EstadoOrden.REJECTED) or (o.qty > 0 and o.llenas >= o.qty))
            if accion == "CancelRej" and terminal:
                # Ensayo 28-sep: el CANCEL llegó justo detrás del fill (o del Canceled) de esa misma orden y DAS
                # contesta «Order not open». No hay nada que reparar ni que avisar: se anota y se barre igual.
                acciones += [Anotar("cancel_rej_benigno", {"ticker": o.ticker, "token": o.token, "id_das": o.id_das,
                                                           "estado": o.estado.value, "notas": m.notas,
                                                           "regla": "R-C-11 / D2a-05"}),
                             Programar(T_BARRIDO, 0.0, {})]
            else:
                acciones += self._absorber(rechazos.tras_cancel_o_replace_rej(o, accion))
        elif accion == "Replaced":
            pedido = self._reemplazo_pedido.pop(o.token, None)
            if pedido is not None:
                share, precio, stop, _version, _abierta = pedido
                if self._share_es_abierta():
                    o.qty = o.llenas + share
                    o.lvqty = share
                else:                                        # D2a-08 / A-02: DAS lee el share como TOTAL
                    o.qty = max(share, o.llenas)
                    o.lvqty = max(share - o.llenas, 0)
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

    def _ticker_de_descartada(self, msg: OrdenDescartada) -> Optional[str]:
        o = self._estado.ordenes.get(msg.token)
        if o is not None:
            return o.ticker
        return msg.ticker if isinstance(msg.ticker, str) and msg.ticker else None

    def _orden_descartada(self, msg: OrdenDescartada) -> list[Accion]:
        """D2a-06: el emisor NO mandó el NEWORDER `token` (versión vieja, cola llena o sesión caída): no existe en DAS.

        La orden pasa a CLOSED con el motivo en `notas` (nunca se cree viva:
        un stop fantasma taparía una posición descubierta), se olvida lo que
        estuviera pedido sobre ella y el plan de stops del ticker se relanza en
        el acto. Una orden que DAS ya conoce (tiene id) o que ya es terminal no
        se toca: manda lo que diga DAS.
        """
        o = self._estado.ordenes.get(msg.token)
        datos = {"token": msg.token, "serie": msg.serie, "version": msg.version, "motivo": msg.motivo,
                 "ticker": o.ticker if o is not None else msg.ticker, "regla": "D2a-06"}
        if o is None:
            return [Anotar("orden_descartada", {**datos, "resultado": "orden desconocida"})]
        if o.estado is not EstadoOrden.SENDING or o.id_das is not None:
            return [Anotar("orden_descartada", {**datos, "resultado": f"se ignora: DAS ya la conoce ({o.estado.value})"})]
        o.notas = str(msg.motivo)
        o.ultima_act = self._ahora
        self._cancel_pedido.pop(o.token, None)
        self._cancelar_al_aceptar.pop(o.token, None)
        self._reemplazo_pedido.pop(o.token, None)
        paso = self._transicion(o, EstadoOrden.CLOSED)
        acciones: list[Accion] = [
            Anotar("orden_descartada", {**datos, "resultado": "CLOSED y plan de stops"}),
            Anotar("orden_estado", {"token": o.token, "ticker": o.ticker, "estado": o.estado.value, "notas": o.notas,
                                    "motivo": "D2a-06: el emisor no la envió"})]
        acciones += self._tras_cambio_orden(o, paso)
        if not self._estado.das_conectado:
            # sin DAS no sale nada: el barrido de la reconexión (F12) replanifica el ticker
            return acciones + [Anotar("orden_descartada_plan", {"ticker": o.ticker, "motivo": "DAS desconectado: el "
                                                                "plan sale con la reconciliación al reconectar"})]
        return acciones + self._plan(o.ticker)

    def _execute(self, o: Orden, m: MsgOrderAct, simulado: bool) -> list[Accion]:
        """Corrección 2: un `Execute` cuenta si su `%TRADE` no llegó antes (contadores por id de orden y acciones)."""
        clave = (m.id, int(m.qty))
        if self._n_trade.get(clave, 0) > self._n_execute.get(clave, 0):
            self._n_execute[clave] = self._n_execute.get(clave, 0) + 1
            return []
        self._n_execute[clave] = self._n_execute.get(clave, 0) + 1
        return self._aplicar_fill(o, None, m.id, int(m.qty), m.precio, m.lado, m.ruta, m.hora, None, None, simulado,
                                  "execute", cruda=m.cruda)

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
                                                    m.liq, m.ecn_fee, simulado, "trade", eco=True, cruda=m.cruda))]
        self._n_trade[clave] = self._n_trade.get(clave, 0) + 1
        return self._aplicar_fill(o, m.id, m.id_orden, int(m.qty), m.precio, m.lado, m.ruta, m.hora, m.liq, m.ecn_fee,
                                  simulado, "trade", cruda=m.cruda)

    def _datos_fill(self, o: Orden, id_trade: Optional[int], id_orden: Optional[int], qty: int, precio: Decimal,
                    lado: str, ruta: str, hora: str, liq: Optional[str], ecn_fee: Optional[Decimal], simulado: bool,
                    origen: str, eco: bool = False, cruda: Optional[str] = None) -> dict:
        pos = self._estado.posiciones.get(o.ticker)
        return {"id_trade": id_trade, "token": o.token, "id_orden": id_orden, "ticker": o.ticker, "lado": lado,
                "qty": qty, "precio": precio, "ruta": ruta, "hora": hora, "liq": liq, "ecn_fee": ecn_fee,
                "simulado": simulado, "origen": origen, "eco": eco, "proposito": o.proposito.value,
                "neta_fills": pos.neta_fills if pos is not None else None,
                "version_stops": pos.version_stops if pos is not None else None, "cruda": cruda}

    def _aplicar_fill(self, o: Orden, id_trade: Optional[int], id_orden: Optional[int], qty: int, precio: Decimal,
                      lado: str, ruta: str, hora: str, liq: Optional[str], ecn_fee: Optional[Decimal], simulado: bool,
                      origen: str, cruda: Optional[str] = None) -> list[Accion]:
        """F1.6 / F2.3: un fill NUEVO al libro por token → neta, versión de stops e `InvalidarSerie` antes de todo lo demás.

        G1A-18: un fill de salida del halt (HALT_*) activa el veto R-F-03 como
        el de un stop. G1A-14: si la neta pasa de 0 a ≠ 0 con el símbolo en
        halt y sin decisión programada, se programa `halt_decidir`. G1A-09: el
        flujo de caja del trade se acumula para el aviso y el resumen.
        """
        if qty <= 0 or not isinstance(precio, Decimal) or not precio.is_finite() or precio <= 0:
            return [Anotar("fill_invalido", {"token": o.token, "id_orden": id_orden, "qty": qty, "precio": precio,
                                             "cruda": cruda})]
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
        cuenta = not simulado or estado.fase is Fase.SOMBRA
        if cuenta:
            pos.neta_fills += qty if lado_n in _LADOS_COMPRA else -qty
        if antes == 0 and pos.neta_fills != 0:
            self._inicio_episodio[ticker] = self._ahora
            self._pnl_episodio[ticker] = Decimal("0")
        if cuenta:
            flujo = (-qty if lado_n in _LADOS_COMPRA else qty) * precio
            self._pnl_episodio[ticker] = self._pnl_episodio.get(ticker, Decimal("0")) + flujo
        pos.version_stops += 1
        estado.ultimo_fill_en = self._ahora
        # R3-DEC-1 (R3-SAL-1): la hora del último fill de ESTE ticker (real o simulado, Execute o %TRADE no duplicado):
        # «cerrar todo» solo se fía de neta_das si el %POS llegó después (salidas.das_confirmada)
        pos.ultimo_fill_en = self._ahora
        o.llenas += qty
        o.ultima_act = self._ahora
        if o.estado not in _TERMINALES:
            o.estado = EstadoOrden.EXECUTED if o.llenas >= o.qty else EstadoOrden.PARTIAL
        if o.proposito in _PROP_CIERRE_HALT:
            self._stop_hoy.add(ticker)                         # G1A-18: salida del halt = salida por stop para R-F-03
        acciones: list[Accion] = [
            InvalidarSerie(stops.serie_stops(ticker), pos.version_stops),
            Anotar("fill", self._datos_fill(o, id_trade, id_orden, qty, precio, lado_n, ruta, hora, liq, ecn_fee,
                                            simulado, origen, cruda=cruda)),
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
            acciones.append(Consultar(protocolo.cmd_get("LDLU", ticker)))
        if (antes == 0 and pos.neta_fills != 0 and ticker in self._halt_en_curso
                and ticker not in self._halt_decidir_programado):
            acciones += self._programar_halt_decidir(pos)       # G1A-14: fill tardío con el símbolo parado
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
            grupos = [[pos.lotes[i] for i in intento.lotes if i in pos.lotes]]
        else:
            # G1A-15: primero los lotes de ESTA orden; solo el sobrante a otros lotes que no sean de un intento vivo
            propios_ids = list(self._lotes_de_orden.get(o.token) or ([o.lote_id] if o.lote_id else []))
            vivos_intento = set(intento.lotes) if intento is not None and intento.fase is not FaseIntento.TERMINADO \
                else set()
            otros_ids = [lid for lid, lote in pos.lotes.items()
                         if lid not in propios_ids and lid not in vivos_intento
                         and lote.estado in (EstadoLote.ABRIENDO, EstadoLote.CANCELADO)
                         and lote.llenas < lote.pedidas]
            grupos = [[pos.lotes[i] for i in propios_ids if i in pos.lotes], [pos.lotes[i] for i in otros_ids]]
        acciones: list[Accion] = []
        restante = fill.qty
        asignable_total = 0
        for lotes in grupos:
            capacidad = sum(max(lote.pedidas - lote.llenas, 0) for lote in lotes)
            asignable = min(restante, capacidad)
            if asignable <= 0:
                continue
            restante -= asignable
            asignable_total += asignable
            for lote_id, n in entrada.repartir_fill(lotes, asignable, fill.precio):
                if n <= 0:
                    continue
                lote = entrada.acumular_fill(pos.lotes[lote_id], n, fill.precio)
                self._flujo_estrategia[lote.strategy_id] = (self._flujo_estrategia.get(lote.strategy_id, Decimal("0"))
                                                            + n * fill.precio)
                self._llenas_max_lote[lote_id] = max(self._llenas_max_lote.get(lote_id, 0), lote.llenas)
                # G1B-02: un fill que cae en un lote CERRADO (un stop lo vació durante el intento) lo reabre:
                # nunca acciones cortas sin lote vivo que lleve sus stops y sus salidas
                revivido = lote.estado in (EstadoLote.CANCELADO, EstadoLote.CERRADO)
                if revivido:
                    lote = dataclasses.replace(lote, estado=EstadoLote.ABIERTO)
                pos.lotes[lote_id] = lote
                acciones.append(self._anotar_lote(lote))
                if revivido and not (del_intento and intento is not None and intento.fase is not FaseIntento.TERMINADO):
                    acciones += self._temporizadores_lote(lote)
        if fill.qty > asignable_total:
            acciones += [Anotar("incidente", {"tipo": "sobrellenado", "ticker": ticker, "token": o.token,
                                              "qty": fill.qty, "asignadas": asignable_total, "regla": "R-B-02"}),
                         Avisar(Nivel.AVISO, Grupo.B, f"{avisos.escapar_html(ticker)}: fill de {fill.qty} con solo "
                                                      f"{asignable_total} pendientes en los lotes; la emergencia cubre "
                                                      f"la neta entera", clave=f"sobrellenado:{ticker}:{o.token}")]
        if del_intento and intento is not None:
            bloque = intento.cfg_congelada or self._cfg.entrada
            tope = _pct(bloque, "tope_caida_bid_pct", ENTRADA_TOPE_CAIDA_BID_PCT)
            cruce = _pct(bloque, "cruce_bajo_bid_pct", ENTRADA_CRUCE_BAJO_BID_PCT)
            ssr = bool(self._mercado.simbolo(ticker).ssr)
            # D1-05 / G1B-19: el suelo es el PEOR cruce legal (con el redondeo al tick), no bid·(1 − 3,5 %)
            if entrada.fill_peor_de_lo_permitido(fill.precio, intento.bid_senal, tope, cruce_pct=cruce, ssr=ssr):
                acciones.append(Avisar(Nivel.AVISO, Grupo.B,
                                       f"{avisos.escapar_html(ticker)}: fill a {fill.precio} por debajo del peor cruce "
                                       f"legal (tope {tope} % + cruce {cruce} % bajo el bid de la señal "
                                       f"{intento.bid_senal}); se MANTIENE (B13)",
                                       clave=f"b13:{ticker}:{o.token}"))
        if self._emergencia_viva(ticker):
            debounce = _segundos(self._cfg.stops, "debounce_s", STOP_DEBOUNCE_S)
            acciones.append(Programar(f"{T_STOPS_AJUSTAR}:{ticker}", debounce, {"ticker": ticker}))
        else:
            acciones += self._plan(ticker)
        acciones += self._revisar_cuadre(o)
        return acciones

    def _fill_stop(self, pos: PosicionTicker, o: Orden, fill: Fill) -> list[Accion]:
        """F2.3 / R-C-11: el fill de un stop reduce los lotes y `limpieza_tras_fill_stop` deja UNA emergencia o vende el exceso.

        A la limpieza se le pasan `compras_cierre` (G1A-01) y
        `pedidos_en_vuelo` (D2a-05). G1B-02: si la posición queda plana o un
        lote del intento vivo se cierra, el intento se cancela (nunca vuelve a
        vender en un lote cerrado).
        """
        ticker = pos.ticker
        self._stop_hoy.add(ticker)
        preferidos: list[str] = []
        if o.proposito is Proposito.STOP_PRINCIPAL and o.nivel is not None:
            preferidos = [lote.id for lote in self._lotes_vivos(pos) if lote.nivel_stop == o.nivel]
        consumidos_primero = o.proposito is not Proposito.STOP_PRINCIPAL
        acciones, cerrados = self._reducir_lotes(pos, fill.qty, preferidos, mas_alto_primero=True, precio=fill.precio,
                                                 consumidos_primero=consumidos_primero)
        acciones += self._absorber(self._filtrar_stops_bloqueados(ticker, stops.limpieza_tras_fill_stop(
            pos, self._ordenes_ticker(ticker), self._cot(ticker), self._tokens.siguiente, self._cfg, self._ahora_et,
            pos.version_stops, orden_stop=o, limit_up=self._limit_up(ticker),
            compras_cierre=self._compras_cierre(ticker), pedidos_en_vuelo=self._pedidos_en_vuelo(ticker))))
        if pos.neta == 0:
            acciones += self._posicion_cerrada(pos, dentro_de_emergencia=(
                o.proposito is Proposito.STOP_EMERGENCIA and (o.precio is None or fill.precio <= o.precio)))
        elif pos.neta < 0:
            acciones += self._capar_salidas(pos)
            acciones += self._intento_con_lote_cerrado(pos, cerrados)
        else:
            acciones += self._intento_con_lote_cerrado(pos, cerrados)
        return acciones

    def _fill_salida(self, pos: PosicionTicker, o: Orden, fill: Fill) -> list[Accion]:
        """F4.3 / F5 / R-C-07: una salida reduce su lote y los stops se reducen a lo que queda; plana → todo fuera."""
        preferidos = [o.lote_id] if o.lote_id is not None and o.lote_id in pos.lotes else []
        acciones, cerrados = self._reducir_lotes(pos, fill.qty, preferidos, mas_alto_primero=False, precio=fill.precio)
        self._refrescar_tp_pendiente(pos)
        acciones += self._revisar_cuadre(o)
        if pos.neta > 0:
            acciones += self._absorber(self._filtrar_stops_bloqueados(pos.ticker, stops.limpieza_tras_fill_stop(
                pos, self._ordenes_ticker(pos.ticker), self._cot(pos.ticker), self._tokens.siguiente, self._cfg,
                self._ahora_et, pos.version_stops, limit_up=self._limit_up(pos.ticker),
                compras_cierre=self._compras_cierre(pos.ticker), pedidos_en_vuelo=self._pedidos_en_vuelo(pos.ticker))))
            acciones += self._intento_con_lote_cerrado(pos, cerrados)
        elif pos.neta == 0:
            acciones += self._posicion_cerrada(pos, dentro_de_emergencia=False)
        else:
            acciones += self._plan(pos.ticker)
            acciones += self._intento_con_lote_cerrado(pos, cerrados)
        return acciones

    def _intento_con_lote_cerrado(self, pos: PosicionTicker, cerrados: list[str]) -> list[Accion]:
        """G1B-02: un lote del intento vivo pasó a CERRADO (un stop o una salida lo vació) → el intento se cancela."""
        intento = pos.intento
        if intento is None or intento.fase is FaseIntento.TERMINADO or not (set(cerrados) & set(intento.lotes)):
            return []
        return [Anotar("intento", {"ticker": pos.ticker, "motivo": "G1B-02: un lote del intento se cerró; se cancela "
                                                                   "la entrada (se queda lo llenado)"})] + \
            self._cancelar_intento(pos, MOTIVO_CIERRE)

    def _fill_exceso(self, pos: PosicionTicker, o: Orden, fill: Fill) -> list[Accion]:
        """R-C-11 (b): la venta del exceso; plana → incidente resuelto; si cruzó a corto, `plan` protege lo que haya."""
        acciones: list[Accion] = [Anotar("incidente", {"tipo": "exceso_vendido", "ticker": pos.ticker, "qty": fill.qty,
                                                       "neta": pos.neta, "regla": "R-C-11 (b)"})]
        if pos.neta < 0:
            acciones += self._plan(pos.ticker)
        return acciones

    def _reducir_lotes(self, pos: PosicionTicker, qty: int, preferidos: list[str], mas_alto_primero: bool,
                       precio: Optional[Decimal] = None,
                       consumidos_primero: bool = False) -> tuple[list[Accion], list[str]]:
        """Las acciones que salen se descuentan de los lotes: primero los `preferidos`, luego el resto (lote a CERRADO en 0).

        G1A-20 / G1B-20 (criterio decidido): el fill de la EMERGENCIA o de una
        protección (`consumidos_primero`) descuenta primero los lotes cuyo
        principal ya se consumió (su momento pasó) y, dentro de cada grupo,
        desde el L más ALTO (la emergencia va sobre el L más alto): así el lote
        que aún tiene su principal pendiente conserva sus acciones. Devuelve
        (acciones, ids de los lotes que se cerraron).
        """
        vivos = self._lotes_vivos(pos)
        orden_lotes = [lote for lote in vivos if lote.id in preferidos]
        resto = [lote for lote in vivos if lote.id not in preferidos]
        resto.sort(key=lambda lote: (lote.nivel_stop or Decimal("0")), reverse=mas_alto_primero)
        if consumidos_primero:
            resto.sort(key=lambda lote: 0 if lote.principal_consumido else 1)     # estable: conserva el orden por L
        acciones: list[Accion] = []
        cerrados: list[str] = []
        restante = qty
        for lote in orden_lotes + resto:
            if restante <= 0:
                break
            n = min(restante, lote.llenas)
            if n <= 0:
                continue
            restante -= n
            lote.llenas -= n
            if precio is not None:
                self._flujo_estrategia[lote.strategy_id] = (self._flujo_estrategia.get(lote.strategy_id, Decimal("0"))
                                                            - n * precio)
            if lote.llenas == 0:
                lote.estado = EstadoLote.CERRADO
                cerrados.append(lote.id)
            acciones.append(Anotar("lote", {"lote_id": lote.id, "ticker": lote.ticker, "llenas": lote.llenas,
                                            "estado": lote.estado.value, "motivo": "salida"}))
            if lote.estado is EstadoLote.CERRADO:
                acciones += self._lote_cerrado(lote)
        return acciones, cerrados

    def _lote_cerrado(self, lote: Lote) -> list[Accion]:
        """Fuera los temporizadores del lote (D2-07: TODAS sus claves por orden de tp_cruce/tp_limbo) y SLReuseQuery (EP-9)."""
        acciones: list[Accion] = [Desprogramar(salidas.clave_lote(base, lote.id))
                                  for base in (T_HORA_AGREGAR, T_HORA_ASK, T_EOD_COMPROBAR, T_TP_CRUCE)]
        acciones += [Desprogramar(clave) for clave in sorted(self._claves_lote.pop(lote.id, set()))]
        if lote.ticker not in self._reuso_consultado:
            self._reuso_consultado.add(lote.ticker)
            acciones.append(locates.consulta_reuso(lote.ticker))
        return acciones

    def _posicion_cerrada(self, pos: PosicionTicker, dentro_de_emergencia: bool) -> list[Accion]:
        """Neta 0: lotes CERRADO, nada vivo en el ticker (R-C-11 a) y, si había cisne negro, su fin (R-G-01 (3)).

        G1B-02: el intento de entrada vivo se cancela (MOTIVO_CIERRE: se queda
        lo llenado, nunca vuelve a vender). G1A-09 (F5): aviso al grupo B con
        el resultado del trade y `liberar_reservas`; D1-10: `GET AccountInfo`
        (el equity del tope corto cambia con cada trade cerrado).
        """
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
        if pos.intento is not None and pos.intento.fase is not FaseIntento.TERMINADO:
            acciones += [Anotar("intento", {"ticker": ticker, "motivo": "G1B-02: posición plana con la entrada viva; "
                                                                        "se cancela (se queda lo llenado)"})]
            acciones += self._cancelar_intento(pos, MOTIVO_CIERRE)
        acciones += self._cerrar_bs_si_toca(pos, dentro_de_emergencia)
        self._cierre_humano.discard(ticker)
        self._retirando_cierre.discard(ticker)
        self._cerrar_todo_enviar.pop(ticker, None)
        self._banda_enviada.discard(ticker)
        self._olvidar_rechazos_de_stop(ticker)
        self._stops_diferidos_halt.discard(ticker)
        pos.persecuciones_ask = 0
        resultado = self._pnl_episodio.pop(ticker, None)
        acciones.append(Anotar("posicion_cerrada", {"ticker": ticker, "neta_das": pos.neta_das,
                                                    "resultado": resultado}))
        acciones.append(Avisar(Nivel.INFO, Grupo.B,
                               f"POSICIÓN CERRADA {avisos.escapar(ticker)}"
                               + (f" · resultado {resultado.quantize(Decimal('0.01'))} $ (sin comisiones)"
                                  if resultado is not None else ""),
                               clave=f"posicion_cerrada:{ticker}:{pos.version_stops}"))
        capital.liberar_reservas(self._estado.cuenta)
        self._accountinfo_pedido_en = self._ahora
        acciones.append(Consultar(protocolo.cmd_get("AccountInfo")))
        return acciones

    def _olvidar_rechazos_de_stop(self, ticker: str) -> None:
        """La posición se cerró o el humano reanudó el ticker: fuera la separación y la cuenta de R-C-03 (todos sus propósitos)."""
        for clave in [k for k in self._stop_bloqueo if k[0] == ticker]:
            del self._stop_bloqueo[clave]
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
                                                    "cxlqty": o.cxlqty, "tipo_das_crudo": m.tipo, "cruda": m.cruda}))
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
            acciones.append(Anotar("pos", {"ticker": m.ticker, "neta": m.neta, "avg": m.avg, "tipo": m.tipo,
                                           "cruda": m.cruda}))
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
            crudas = self._bloquear_stops_tras_rechazo(o, crudas)
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
            elif (isinstance(a, Programar) and a.clave.split(":", 1)[0] == T_CRUCE_POSTONLY
                  and del_intento and motivo_previo is None):
                diferido = True                              # D2-09: el intento pasa al cruce (no se cierra)
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
        """La orden de salida que sustituye a una rechazada hereda su seguimiento (D2-07: claves por ORDEN; D2-13: limbo).

        TP que vuelve a agregar → su `tp_cruce:<lote>:<token nuevo>` (y fuera el
        de la rechazada); cruce del TP (PostOnly rechazado, D2-09) → el aviso
        de limbo si no llena; hora / cierre y reinicio al ask → la persecución.
        """
        lote_id = nueva.lote_id
        vieja: list[Accion] = ([Desprogramar(salidas.clave_tp_cruce(lote_id, rechazada.token))]
                               if lote_id is not None else [])
        if nueva.proposito is Proposito.TP_AGREGAR and lote_id is not None:
            espera = _segundos((self._cfg.salidas or {}).get("tp_parcial") or {}, "agregar_s", 60.0)
            return vieja + [Programar(salidas.clave_tp_cruce(lote_id, nueva.token), espera,
                                      {"lote_id": lote_id, "ticker": nueva.ticker, "token": nueva.token,
                                       "qty": nueva.qty})]
        if nueva.proposito in (Proposito.TP_CRUCE, Proposito.SALIDA_MOTOR_CRUCE) and lote_id is not None:
            pos = self._estado.posiciones.get(nueva.ticker)
            lote = pos.lotes.get(lote_id) if pos is not None else None
            return vieja + ([salidas.programa_limbo_tp(lote, nueva, self._cfg)] if lote is not None else [])
        if nueva.proposito in (Proposito.HORA_ASK, Proposito.CIERRE_REINICIO) and not nueva.post_only:
            self._persecuciones[nueva.token] = self._persecuciones.pop(rechazada.token, 0)
            return [Programar(f"{T_PERSEGUIR_ASK}:{nueva.token}", self._perseguir_cada(),
                              {"token": nueva.token, "ticker": nueva.ticker, "lote_id": nueva.lote_id})]
        return []

    def _bloquear_stops_tras_rechazo(self, o: Orden, crudas: list[Accion]) -> list[Accion]:
        """R-C-03: tras un stop rechazado no se repone ESE propósito hasta su `stop_reintento` (separación) y la cuenta de
        intentos pasa a la orden siguiente de ese propósito venga de donde venga (plan, barrido); agotados, no se repone
        solo (G1B-07: solo ese propósito; el resto del plan sigue).

        G1B-14 / G1A-21 (R-C-04, excepción del HALT): con el símbolo en halt no
        se gastan intentos: fuera el `stop_reintento`, sin cuenta, y los stops
        se reponen al reabrir. Devuelve las acciones de `rechazos.decidir` sin
        lo que se aplaza.
        """
        pos = self._estado.posiciones.get(o.ticker)
        if pos is not None and (pos.estado is EstadoTicker.HALT or o.ticker in self._halt_en_curso):
            self._stops_diferidos_halt.add(o.ticker)
            return [a for a in crudas if not (isinstance(a, Programar) and a.clave == T_STOP_REINTENTO)] + [
                Anotar("stop_diferido_halt", {"ticker": o.ticker, "token": o.token, "proposito": o.proposito.value,
                                              "regla": "R-C-04 (excepción del halt) / G1B-14"})]
        programa = next((a for a in crudas if isinstance(a, Programar) and a.clave == T_STOP_REINTENTO), None)
        if programa is not None:
            primero = programa.datos.get("primer_intento_en")
            self._stop_intentos[(o.ticker, o.proposito)] = (
                int(programa.datos.get("intento") or o.intentos + 1),
                float(primero) if isinstance(primero, (int, float)) else self._ahora)
            hasta = self._ahora + float(programa.en_s)
        else:
            hasta = math.inf
        clave = (o.ticker, o.proposito)
        self._stop_bloqueo[clave] = max(self._stop_bloqueo.get(clave, -math.inf), hasta)
        return crudas

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
        """F6.1: `$IssueStatus` → transición de halt (k, precio de parada) con `mercado.marcar_halt`.

        G1A-05: la respuesta fresca del símbolo libera las entradas que la
        esperaban. G1A-14: un $IssueStatus repetido programa `halt_decidir`
        si el halt en curso aún no lo tiene y hay posición.
        """
        ticker = m.ticker
        self._simstatus_en[ticker] = self._ahora
        cot = self._cot(ticker)
        franja = self._franja()
        transicion = self._mercado.marcar_halt(ticker, m, self._ahora_et, cot.last if cot is not None else None, franja)
        if transicion == "halt":
            acciones = self._al_halt(ticker, franja)
        elif transicion == "reapertura":
            acciones = self._al_reabrir(ticker)
        else:
            acciones = []
            simb = self._mercado.simbolo(ticker)
            pos = self._estado.posiciones.get(ticker)
            if halts.es_halt(simb) and ticker in self._halt_en_curso and pos is not None and pos.neta != 0:
                fin = halts.fin_previsto(simb, self._ahora_et)
                if fin != self._halt_fin.get(ticker) or ticker not in self._halt_decidir_programado:
                    acciones += self._programar_halt_decidir(pos)
        return acciones + self._liberar_entradas_simstatus(ticker)

    def _liberar_entradas_simstatus(self, ticker: str, sin_respuesta: bool = False) -> list[Accion]:
        """G1A-05: las entradas que esperaban el SymStatus del ticker se vuelven a evaluar (con el estado ya fresco)."""
        pendientes = self._entradas_simstatus.pop(ticker, [])
        if not pendientes:
            return []
        acciones: list[Accion] = [Desprogramar(f"{T_SIMSTATUS_ESPERA}:{ticker}")]
        if sin_respuesta:
            acciones.append(Anotar("simstatus_sin_respuesta", {"ticker": ticker, "senales": [s.id for s in pendientes],
                                                               "regla": "G1A-05: 1 s sin respuesta; se sigue"}))
        for s in pendientes:
            acciones += self._proteger(ticker, "senal", lambda s=s: self._entrada(s, sin_espera_simstatus=True))
        return acciones

    def _segundos_envio_open(self, fin: Optional[datetime]) -> float:
        antes = int(_segundos(self._cfg.halts, "enviar_antes_fin_halt_s", 60.0))
        return halts.momento_envio_open(fin, self._ahora_et, antes)

    def _programar_halt_decidir(self, pos: PosicionTicker) -> list[Accion]:
        """G1A-14: `halt_decidir` del halt en curso (un minuto antes del fin previsto o ya) y el ticker a HALT."""
        ticker = pos.ticker
        simb = self._mercado.simbolo(ticker)
        fin = halts.fin_previsto(simb, self._ahora_et)
        self._halt_fin[ticker] = fin
        self._halt_decidir_programado.add(ticker)
        if pos.estado is EstadoTicker.NORMAL:
            pos.estado = EstadoTicker.HALT
            pos.motivo_estado = f"halt {simb.ta or ''}".strip()
            pos.desde = self._ahora
        return [Programar(f"{T_HALT_DECIDIR}:{ticker}", self._segundos_envio_open(fin), {"ticker": ticker})]

    def _al_halt(self, ticker: str, franja: str) -> list[Accion]:
        """F6.1 (B18, R-F-04 a, R-G-02): cancelar entradas, aviso 2, ticker en HALT y `halt_decidir` un minuto antes del fin.

        E1-06: con TA:P (LULD) se piden las bandas (`GET LDLU X`) para
        clasificar el halt y recortar los stops.
        """
        simb = self._mercado.simbolo(ticker)
        self._halt_en_curso.add(ticker)
        self._halt_hoy.add(ticker)
        self._reapertura_ok.discard(ticker)
        self._halt_decidir_programado.discard(ticker)
        ldlu: list[Accion] = ([Consultar(protocolo.cmd_get("LDLU", ticker))]
                              if (simb.ta or "").strip().upper() == "P" else [])
        pos = self._estado.posiciones.get(ticker)
        if pos is None or (not self._tiene_posicion(pos) and pos.intento is None
                           and not any(o.proposito in _PROP_ENTRADA for o in self._vivas(ticker))):
            return [Anotar("halt", {"ticker": ticker, "ta": simb.ta, "tat": simb.tat, "k": simb.k_halts_up,
                                    "sin_posicion": True})] + ldlu
        acciones = self._absorber(halts.al_entrar_en_halt(pos, self._ordenes_ticker(ticker), simb, self._cot(ticker),
                                                          franja))
        if pos.intento is not None:
            acciones += self._cancelar_intento(pos, MOTIVO_HALT)
        if pos.estado is EstadoTicker.NORMAL:
            pos.estado = EstadoTicker.HALT
            pos.motivo_estado = f"halt {simb.ta or ''}".strip()
            pos.desde = self._ahora
        if pos.neta != 0:
            acciones += self._programar_halt_decidir(pos)
        return acciones + ldlu

    def _bloqueo_decision_halt(self, pos: PosicionTicker, era_luld: Optional[bool] = None) -> Optional[str]:
        """G1A-04 (R-G-01 «cierra el HUMANO»): con el ticker en cisne negro, control humano, manual o cierre humano, el
        halt no manda órdenes: solo se anota y se avisa nivel 3 con la decisión que se habría tomado."""
        ticker = pos.ticker
        if pos.estado is EstadoTicker.BS or pos.bs is not None:
            # Jaume 28-sep (D4): en premercado solo hay halts T1/T12 y ahí manda su protocolo (límite a parada × 3,5,
            # R-F-05) aunque el ticker esté en cisne negro; el «cierra el humano» queda para el LULD (P) de RTH.
            luld = era_luld if era_luld is not None else halts.es_luld(self._mercado.simbolo(ticker))
            if not luld:
                return None
            return "cisne negro"
        if pos.estado is EstadoTicker.CONTROL_HUMANO:
            return "control humano"
        if ticker in self._manual:
            return "control manual"
        if ticker in self._cierre_humano:
            return "cierre humano en curso"
        return None

    def _halt_sin_orden(self, pos: PosicionTicker, decision: str, bloqueo: str, cuando: str) -> list[Accion]:
        ticker = pos.ticker
        simb = self._mercado.simbolo(ticker)
        acciones: list[Accion] = [Anotar("halt_sin_orden", {"ticker": ticker, "decision": decision, "motivo": bloqueo,
                                                            "cuando": cuando, "regla": "R-G-01 / G1A-04"})]
        if self._una_vez_al_dia(f"halt_sin_orden:{ticker}:{simb.tat}:{cuando}"):
            acciones.append(Avisar(Nivel.MAXIMO, Grupo.B,
                                   f"HALT {avisos.escapar(ticker)} ({avisos.escapar(bloqueo)}): el bot habría decidido "
                                   f"«{avisos.escapar(decision)}» ({avisos.escapar(cuando)}) y NO envía nada: cierra el "
                                   f"humano (R-G-01). Posición {pos.neta:+d}",
                                   clave=f"halt_sin_orden:{ticker}"))
        return acciones

    def _t_halt_decidir(self, clave: str, datos: dict) -> list[Accion]:
        """F6.2 (R-F-01/05/06, EP-2, injerto §8.23): decidir la reapertura; la orden por OPEN sale UNA vez (guardia).

        G1A-01 / G1B-04 / D2a-09: al enviar la salida del halt por Q acciones,
        principal y emergencia se REDUCEN antes en Q (`stops.plan` con
        `compras_cierre`): la salida y los stops nunca compran dos veces en la
        reapertura. E1-01: en un halt H la salida por OPEN es un LÍMITE a
        parada · (1 + t1) (`orden_reapertura(simb=...)`). G1A-04: en cisne
        negro / control humano / manual / cierre humano no sale ninguna orden
        (aviso 3). E1-04: «mantener» en un halt H de premercado ensancha el
        límite de los stops residentes (R-F-06). D2a-01: el «stop» que se
        compara con el precio es el primero que DE VERDAD salta.
        """
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
        self._halt_luld[ticker] = halts.es_luld(simb)
        acciones: list[Accion] = [Anotar("halt_decision", {"ticker": ticker, "decision": decision,
                                                           "k": simb.k_halts_up, "duracion_min": duracion,
                                                           "franja": franja, "regla": "R-F-01"})]
        bloqueo = self._bloqueo_decision_halt(pos)
        if bloqueo is not None:
            if decision != "mantener":
                acciones += self._halt_sin_orden(pos, decision, bloqueo, "durante el halt")
            acciones.append(Programar(f"{T_HALT_DECIDIR}:{ticker}", HALT_REDECIDIR_S, {"ticker": ticker}))
            return acciones
        degradados = self._estado.modo_degradado & {"reconciliacion", "das"}
        if degradados and decision in ("cerrar_mercado", "cerrar_limite_pm"):
            # G1B-01 (R-J-02.5): nada sale hasta reconciliar; la misma decisión se repite a 0,5 s
            return acciones + [Anotar("salida_aplazada", {"ticker": ticker, "clave": clave, "motivo": "modo degradado: "
                                                          + ", ".join(sorted(degradados)), "regla": "G1B-01"}),
                               Programar(f"{T_HALT_DECIDIR}:{ticker}", SALIDA_REPROGRAMAR_S, {"ticker": ticker})]
        if decision in ("cerrar_mercado", "cerrar_limite_pm"):
            if decision == "cerrar_mercado" and not halts.debe_enviar_open(simb):
                return acciones + [Anotar("halt_guardia", {"ticker": ticker, "motivo": "la MKT por OPEN ya salió",
                                                           "regla": "injerto A §8.23"})]
            if self._orden_halt_viva(ticker):
                return acciones + [Anotar("halt_guardia", {"ticker": ticker, "motivo": "orden de salida del halt viva"})]
            qty = abs(pos.neta) - self._comprando(ticker)
            if qty <= 0:
                return acciones
            orden = halts.orden_reapertura(pos, qty, cot, decision, self._cfg, self._tokens.siguiente(), self._ahora_et,
                                           simb=simb)
            envio = self._absorber([EnviarOrden(orden)])
            reduccion = self._plan(ticker)                     # G1A-01: los stops bajan ANTES de que salga la orden
            acciones += reduccion + envio
            if decision == "cerrar_mercado":
                simb.orden_open_enviada = True
            tipo = "MKT" if orden.tipo is TipoOrden.MERCADO else f"LMT {orden.precio}"
            acciones.append(Avisar(Nivel.AVISO, Grupo.B,
                                   f"HALT {avisos.escapar(ticker)}: se sale ({avisos.escapar(decision)}) con {qty} "
                                   f"acciones {tipo} por {avisos.escapar(orden.ruta)}; principal y emergencia bajan a "
                                   f"{max(abs(pos.neta) - self._compras_cierre(ticker), 0)} (G1A-01: nunca dos compras "
                                   f"sobre las mismas acciones)",
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
            acciones += self._absorber(halts.ensanchar_stops_pm(pos, self._ordenes_ticker(ticker), simb, franja,
                                                                self._cfg, pos.version_stops))
            acciones.append(Programar(f"{T_HALT_DECIDIR}:{ticker}", HALT_REDECIDIR_S, {"ticker": ticker}))
        return acciones

    def _niveles_principal(self, pos: PosicionTicker) -> Optional[NivelesStop]:
        """El principal que primero se cruzaría (L más bajo) con el disparo del primer stop que DE VERDAD salta (D2a-01)."""
        niveles = sorted(lote.nivel_stop for lote in self._lotes_vivos(pos) if _es_precio(lote.nivel_stop))
        if not niveles:
            return None
        limit_up = self._limit_up(pos.ticker)
        base = stops.niveles(niveles[0], self._cfg.stops, limit_up)
        primero = stops.primer_disparo(pos, self._cfg.stops, limit_up)
        if primero is None or primero == base.principal_disparo:
            return base
        return dataclasses.replace(base, principal_disparo=primero)

    def _orden_halt_viva(self, ticker: str) -> bool:
        return any(o.ticker == ticker and o.estado in _VIVOS and o.proposito in _PROP_HALT
                   for o in self._estado.ordenes.values())

    def _comprando(self, ticker: str) -> int:
        """Compras de CIERRE vivas del ticker (salidas, halt, cierre humano; no los stops): lo que ya cierra el corto."""
        return sum(_qty_viva(o) for o in self._vivas(ticker) if o.proposito in _PROP_SALIDA and o.lado is Lado.COMPRA)

    def _stops_que_llenarian(self, ticker: str, precio: Optional[Decimal], neta: int) -> int:
        """G1A-01 (reintento al reabrir): acciones que los stops de compra vivos van a comprar YA a `precio`.

        Un STOPLMTP de compra con disparo ≤ precio ≤ límite está disparado y
        es ejecutable: sus acciones cuentan como compradas al dimensionar el
        reintento (la regla del director: `_comprando` con los stops). Como
        principal y emergencia cubren las mismas acciones, nunca pasa de la
        posición.
        """
        if not _es_precio(precio):
            return 0
        total = 0
        for o in self._vivas(ticker):
            if (o.lado is Lado.COMPRA and o.tipo is TipoOrden.STOP_LIMITE_PP and o.stop is not None
                    and o.precio is not None and o.stop <= precio <= o.precio):
                total += _qty_viva(o)
        return min(total, max(abs(neta), 0))

    def _al_reabrir(self, ticker: str) -> list[Accion]:
        """F6.3: segundo aviso, ticker a NORMAL, reintento EP-2 por «cruzar» si la salida del halt no salió, y la primera vela.

        E1-02: antes del reintento se vuelve a mirar el tope del T1 con el
        precio REAL de la reapertura (`halts.tope_t1_superado`): superado →
        control humano con aviso 3, ninguna orden, y la salida del halt que
        siga viva se retira (el plan restaura los stops). G1A-04: en cisne
        negro / control humano / manual / cierre humano, ninguna orden. El
        reintento se dimensiona contando los stops que se disparan a este
        precio y baja los demás antes de salir (G1A-01). G1A-01: 2 s después,
        la salida del halt que no haya llenado se retira y los stops vuelven.
        G1B-14: los stops que DAS quitó durante el halt se reponen ahora.
        """
        simb = self._mercado.simbolo(ticker)
        self._halt_en_curso.discard(ticker)
        self._halt_fin.pop(ticker, None)
        self._halt_decidir_programado.discard(ticker)
        cot = self._cot(ticker)
        precio = cot.last if cot is not None and cot.last is not None else simb.precio_parada
        decision = self._halt_decision.pop(ticker, None)
        era_luld = self._halt_luld.pop(ticker, halts.es_luld(simb))
        acciones: list[Accion] = [Anotar("halt_reapertura", {"ticker": ticker, "k": simb.k_halts_up, "precio": precio,
                                                             "decision": decision}),
                                  Desprogramar(f"{T_HALT_DECIDIR}:{ticker}")]
        pos = self._estado.posiciones.get(ticker)
        if pos is not None:
            if pos.estado is EstadoTicker.HALT:
                pos.estado = EstadoTicker.NORMAL
                pos.motivo_estado = ""
                pos.desde = self._ahora
            acciones.append(Avisar(Nivel.AVISO, Grupo.B,
                                   f"REABRE {avisos.escapar_html(ticker)} · precio {precio} · k={simb.k_halts_up} · "
                                   f"posición {pos.neta:+d} · decisión: {avisos.escapar(decision or 'sin decisión')}",
                                   clave=f"reapertura:{ticker}:{simb.tat}"))
            if ticker in self._stops_diferidos_halt:
                self._stops_diferidos_halt.discard(ticker)
                acciones.append(Anotar("stops_reponer_reapertura", {"ticker": ticker, "regla": "R-C-04 / G1B-14"}))
                acciones += self._plan(ticker)
            if pos.neta < 0 and decision in ("cerrar_mercado", "cerrar_limite_pm"):
                acciones += self._reintento_reapertura(pos, cot, decision, era_luld)
            if pos.neta != 0 and any(o.proposito in _PROP_CIERRE_HALT for o in self._vivas(ticker)):
                acciones.append(Programar(f"{T_HALT_CIERRE_VERIFICAR}:{ticker}", HALT_CIERRE_VERIFICAR_S,
                                          {"ticker": ticker, "reapertura": True}))     # R2-DEC-2: mira el tope T1
        if _es_precio(precio):
            acciones.append(Programar(f"{T_HALT_PRIMERA_VELA}:{ticker}", HALT_PRIMERA_VELA_S,
                                      {"ticker": ticker, "precio_reapertura": str(precio),
                                       "reapertura_epoch": self._ahora_et.timestamp()}))
        return acciones

    def _tope_t1_control_humano(self, pos: PosicionTicker, precio: Optional[Decimal],
                                cuando: str) -> Optional[list[Accion]]:
        """E1-02 / R2-DEC-2 (R-F-05 a): ¿la reapertura supera el tope del T1 con `precio` (el `last` de ESE momento)?

        Superado → se retira la salida del halt viva, `Avisar(MAXIMO)` (una vez
        por día y ticker) y el ticker a CONTROL_HUMANO; devuelve esas acciones.
        No superado (o sin precio / sin parada / LULD: `halts.tope_t1_superado`)
        → None. Se mira al reabrir y otra vez en `halt_cierre_verificar`,
        porque el `T` puede llegar con el `last` de antes del halt (subida 0 %)
        y el primer print real después.
        """
        ticker = pos.ticker
        simb = self._mercado.simbolo(ticker)
        luld = self._mercado.ta_ultimo_halt(ticker) == "P"
        if not halts.tope_t1_superado(simb, precio, self._cfg.halts, luld=luld):
            return None
        acciones: list[Accion] = [Anotar("halt_tope_t1", {"ticker": ticker, "precio": precio,
                                                          "parada": simb.precio_parada, "cuando": cuando,
                                                          "regla": "R-F-05 (a) / E1-02 / R2-DEC-2"})]
        for o in self._vivas(ticker):
            if o.proposito in _PROP_CIERRE_HALT:
                acciones += self._cancelar_orden(o, "E1-02: reabre por encima del tope del T1; se retira la salida")
        if ticker not in self._halt_humano_avisado:
            self._halt_humano_avisado.add(ticker)
            acciones.append(Avisar(Nivel.MAXIMO, Grupo.B,
                                   f"REABRE {avisos.escapar(ticker)} a {precio}: más del "
                                   f"{self._cfg.halts.get('t1_subida_max_cierre_pct', 250)} % sobre la parada "
                                   f"{simb.precio_parada}: CONTROL HUMANO, el bot no cierra (R-F-05 a). Posición "
                                   f"{pos.neta:+d}; los stops vuelven a la posición",
                                   clave=f"halt_humano:{ticker}"))
        if pos.estado in (EstadoTicker.NORMAL, EstadoTicker.HALT, EstadoTicker.PAUSADO):
            pos.estado = EstadoTicker.CONTROL_HUMANO
            pos.motivo_estado = "halt: control humano"
            pos.desde = self._ahora
            acciones.append(Anotar("pausa", {"ticker": ticker, "estado": EstadoTicker.CONTROL_HUMANO.value,
                                             "motivo": "halt: T1 por encima del tope (R-F-05 a, E1-02)"}))
        return acciones

    def _reintento_reapertura(self, pos: PosicionTicker, cot: Optional[Cotizacion], decision: str,
                              era_luld: Optional[bool] = None) -> list[Accion]:
        """EP-2 / E1-02 / G1A-04 / G1A-01: el cierre decidido en el halt, con el precio real de la reapertura."""
        ticker = pos.ticker
        simb = self._mercado.simbolo(ticker)
        precio = cot.last if cot is not None and _es_precio(cot.last) else None
        tope = self._tope_t1_control_humano(pos, precio, "al reabrir")
        if tope is not None:
            return tope
        bloqueo = self._bloqueo_decision_halt(pos, era_luld)
        if bloqueo is not None:
            return self._halt_sin_orden(pos, decision, bloqueo, "al reabrir")
        degradados = self._estado.modo_degradado & {"reconciliacion", "das"}
        if degradados:
            return [Anotar("halt_reintento_omitido", {"ticker": ticker, "motivo": "modo degradado: "
                                                      + ", ".join(sorted(degradados)) + " (los stops protegen)",
                                                      "regla": "G1B-01 / EP-2"})]
        if self._orden_halt_viva(ticker) or not _libro_utilizable(cot):
            return []
        qty = abs(pos.neta) - self._comprando(ticker) - self._stops_que_llenarian(ticker, precio, pos.neta)
        if qty <= 0:
            return [Anotar("halt_reintento_omitido", {"ticker": ticker, "motivo": "los stops que se disparan y las "
                                                      "salidas vivas ya cubren la posición (G1A-01)", "regla": "EP-2"})]
        orden = halts.orden_reapertura(pos, qty, cot, "cerrar_limite_pm", self._cfg, self._tokens.siguiente(),
                                       self._ahora_et, simb=simb)
        envio = self._absorber([EnviarOrden(orden)])
        return (self._plan(ticker) + envio
                + [Anotar("halt_reintento", {"ticker": ticker, "qty": qty, "token": orden.token, "regla": "EP-2"})])

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
                # G1A-13: el intento nace AHORA (tras la primera vela): agrega sus 60 s como cualquier entrada
                acciones += self._entrada(guardada, es_reapertura=True, t_cierre=self._ahora_et.timestamp())
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
        if self._mercado.tomar_reapertura_q(ticker):
            # R2-DEC-3: TA:Q sin T posterior pero con prints nuevos 5 s seguidos → se negocia: reapertura
            acciones.append(Anotar("halt_reapertura_por_prints", {
                "ticker": ticker, "last": cot.last if cot is not None else None,
                "volumen": cot.volumen if cot is not None else None, "regla": "R2-DEC-3 (E1-05)"}))
            acciones += self._al_reabrir(ticker)
        if cot is not None and _es_precio(cot.last):
            historial = self._hist.setdefault(ticker, deque(maxlen=HISTORIAL_MAX))
            historial.append((self._ahora, cot.last))
            if self._ahora_et.hour * 60 + self._ahora_et.minute < 9 * 60 + 30:      # E1-08: máximo de premercado
                previo = self._max_pm.get(ticker)
                if previo is None or cot.last > previo:
                    self._max_pm[ticker] = cot.last
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
                acciones += self._absorber(self._filtrar_stops_bloqueados(ticker, stops.reasignar_principal_rebasado(
                    pos, self._ordenes_ticker(ticker), cot, self._cfg.stops, self._tokens.siguiente, self._ahora_et,
                    self._ruta_stop(), pos.version_stops, self._limit_up(ticker))))
            acciones += self._banda(pos, cot)
            acciones += self._opa(pos)
        acciones += self._fogonazo(ticker)
        return acciones

    def _opa(self, pos: PosicionTicker) -> list[Accion]:
        """E1-08 (R-A-03 v2, OPA = AVISO): con posición, banda clavada 30 min con volumen → `Avisar(2)` una vez al día."""
        ticker = pos.ticker
        ultima = self._opa_revisado_en.get(ticker)
        if ultima is not None and self._ahora - ultima < OPA_REVISION_S:
            return []
        self._opa_revisado_en[ticker] = self._ahora
        if f"opa:{ticker}" in self._avisos_dia:
            return []
        aviso = exclusiones.aviso_opa(ticker, self._mercado.velas_minuto(ticker), self._max_pm.get(ticker),
                                      dict(self._cfg.exclusiones))
        if aviso is None or not self._una_vez_al_dia(f"opa:{ticker}"):
            return []
        return [Anotar("opa", {"ticker": ticker, "max_pm": self._max_pm.get(ticker), "regla": "R-A-03 v2 / E1-08"}),
                aviso]

    def _banda(self, pos: PosicionTicker, cot: Cotizacion) -> list[Accion]:
        """R-F-01: con k = k_max − 1 y el ask a ≤ 4 % del limit up en RTH, salir a mercado por «cruzar» ANTES del halt."""
        ticker = pos.ticker
        if (ticker in self._banda_enviada or pos.estado in (EstadoTicker.BS, EstadoTicker.HALT)
                or ticker in self._manual or ticker in self._cierre_humano or not self._es_rth()
                or self._estado.modo_degradado & {"reconciliacion", "das"}):      # G1B-01: nada sale sin reconciliar
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
        envio = self._absorber([EnviarOrden(orden)])
        reduccion = self._plan(ticker)                       # G1B-04: los stops bajan en qty ANTES de la MKT
        return ([Anotar("halt_banda", {"ticker": ticker, "k": simb.k_halts_up, "ask": cot.ask,
                                       "limit_up": simb.limit_up, "qty": qty, "regla": "R-F-01"})]
                + reduccion + envio
                + [Programar(f"{T_HALT_CIERRE_VERIFICAR}:{ticker}", HALT_CIERRE_VERIFICAR_S, {"ticker": ticker}),
                   Avisar(Nivel.AVISO, Grupo.B, f"{avisos.escapar_html(ticker)}: k={simb.k_halts_up} y el ask {cot.ask} a "
                                                f"≤ {self._cfg.halts.get('distancia_banda_k2_pct', 4)} % del limit up "
                                                f"{simb.limit_up}: se sale a mercado ({qty}) antes del siguiente halt; "
                                                f"los stops bajan a lo que no cubre (G1B-04)",
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
        primero = stops.primer_disparo(pos, self._cfg.stops, limit_up)     # D2a-01: el primer stop que DE VERDAD salta
        return NivelesStop(principal_disparo=primero if primero is not None else bajo.principal_disparo,
                           principal_limite=bajo.principal_limite,
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
            qty=qty, orden=orden, minimo_cargo=self._minimo_cargo.get(ruta) if ruta else None, ahora_et=self._ahora_et,
            locates=estado.locates)                          # E2-02: el 3 % cuenta las compras en curso
        nuevo = locates.aplicar_anotaciones(loc, crudas)
        if nuevo is not None:
            estado.locates[(ticker, e.strategy_id)] = nuevo
        estado.gasto_locates_dia += locates.gasto_de(crudas)
        for a in crudas:
            if isinstance(a, LocateInquire) and (ticker, e.strategy_id) not in self._inquires:
                self._inquires.append((ticker, e.strategy_id))   # ensayo 28-sep: una consulta pendiente por estrategia
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
        """F9 / E2-05: los `%SLRET` de las consultas de un ticker se juntan `SLRET_VENTANA_S` (0,5 s); un fallo en compra
        (sin consulta pendiente), a la compra.

        Una consulta «Inquire All» puede devolver un %SLRET POR RUTA y el
        %SLRET no dice a qué consulta responde: atribuirlos uno a uno (FIFO)
        daba la 2.ª oferta a la consulta de OTRA estrategia. La oferta es del
        TICKER (precio por acción y ruta): al cerrar la ventana, la elegida (el
        ETB manda; si no, la más barata con tamaño, 2e.4) va a CADA estrategia
        con una consulta pendiente de ese ticker, y cada una decide con SU EV
        y SU cantidad (`locates.siguiente_paso`).
        """
        ticker = m.ticker
        if ticker in self._slret_ventana:
            self._slret_ventana[ticker].append(m)
            return [Anotar("slret_ventana", {"ticker": ticker, "tipo": m.tipo, "ruta": m.ruta, "precio": m.precio,
                                             "tamano": m.tamano, "regla": "E2-05"})]
        # Ensayo 28-sep: la respuesta vale también si la consulta ya no está apuntada (la ventana se cerró vacía
        # porque DAS tardó más de 0,5 s, o tras un reinicio) mientras alguna estrategia del ticker siga BUSCANDO;
        # antes esas respuestas se anotaban «sin consulta» y el bot volvía a preguntar cada 3 s sin fin.
        buscando = any(t == ticker and loc.estado == locates.ESTADO_BUSCANDO
                       for (t, _s), loc in self._estado.locates.items())
        if any(t == ticker for t, _ in self._inquires) or buscando:
            self._slret_ventana[ticker] = [m]
            self._slret_tics[ticker] = 0
            return [Programar(f"{T_SLRET_VENTANA}:{ticker}", SLRET_VENTANA_S, {"ticker": ticker})]
        comprando = [s for (t, s), loc in sorted(self._estado.locates.items())
                     if t == ticker and loc.estado == locates.ESTADO_COMPRANDO]
        sid = comprando[0] if comprando else None
        e = self._estrategia(sid)
        if e is None:
            return [Anotar("slret_sin_consulta", {"ticker": ticker, "tipo": m.tipo, "ruta": m.ruta, "notas": m.notas})]
        return self._paso_locate(ticker, e, ret=m)

    def _slret_tic(self) -> list[Accion]:
        """E2-05: la ventana de un ticker también se cierra en el 2.º Tic tras abrirla (ya hubo al menos una vuelta del
        bucle sin mensajes o un segundo entero): la ráfaga de respuestas de la consulta ya entró. Con la cola ocupada
        manda el temporizador de 0,5 s; con el reloj parado (replay, arneses) la compra no queda colgada."""
        acciones: list[Accion] = []
        for ticker in sorted(self._slret_ventana):
            self._slret_tics[ticker] = self._slret_tics.get(ticker, 0) + 1
            if self._slret_tics[ticker] >= 2:
                acciones.append(Desprogramar(f"{T_SLRET_VENTANA}:{ticker}"))
                acciones += self._proteger(ticker, "slret_ventana",
                                           lambda t=ticker: self._t_slret_ventana(f"{T_SLRET_VENTANA}:{t}",
                                                                                  {"ticker": t}))
        return acciones

    def _t_slret_ventana(self, clave: str, datos: dict) -> list[Accion]:
        """E2-05: cerrada la ventana del ticker, el %SLRET que decide (ETB > el más barato > un fallo) a cada consulta."""
        partes = clave.split(":")
        ticker = str(datos.get("ticker") or (partes[1] if len(partes) > 1 else ""))
        self._slret_tics.pop(ticker, None)
        respuestas = self._slret_ventana.pop(ticker, [])
        if not respuestas:
            return []                                        # ensayo 28-sep: sin respuesta la consulta sigue pendiente
        sids: list[str] = []
        quedan: deque[tuple[str, str]] = deque()
        for t, s in self._inquires:
            if t == ticker:
                if s not in sids:
                    sids.append(s)
            else:
                quedan.append((t, s))
        self._inquires = quedan
        if not sids:                                         # respuesta sin consulta apuntada: a las que siguen buscando
            sids = [s for (t, s), loc in sorted(self._estado.locates.items())
                    if t == ticker and loc.estado == locates.ESTADO_BUSCANDO]
        elegido = _slret_elegido(respuestas)
        acciones: list[Accion] = [Anotar("slret_elegido", {"ticker": ticker, "estrategias": list(sids),
                                                           "respuestas": len(respuestas), "tipo": elegido.tipo,
                                                           "ruta": elegido.ruta, "precio": elegido.precio,
                                                           "tamano": elegido.tamano, "regla": "E2-05 / 2e.4"})]
        for sid in sids:
            e = self._estrategia(sid)
            if e is not None:
                acciones += self._proteger(ticker, "locate", lambda e=e: self._paso_locate(ticker, e, ret=elegido))
        return acciones

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
        if estado_das == "located" and locates.compra_repetida(self._estado.locates, ticker, e.strategy_id, id_das=m.id,
                                                               token=m.token):
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
        excluir = self._manual | self._cierre_humano | self._retirando_cierre
        pos_filtradas = {t: m for t, m in pos_das.items() if t not in excluir}
        ord_filtradas = {i: m for i, m in ord_das.items() if str(m.ticker).strip() not in excluir}
        discrepancias = [d for d in reconciliacion.comparar(estado, pos_filtradas, ord_filtradas, estado.dia, self._cfg,
                                                            ahora=self._ahora, limit_up_de=self._limit_up)
                         if d.ticker not in excluir]
        # G1B-07 / G1A-01 / G1B-14: los casos 2/3 de un ticker con un propósito de stop bloqueado (R-C-03), con la
        # salida de un halt viva o con los stops aplazados al reabrir los resuelve `_plan` (que filtra, descuenta la
        # salida del halt y no gasta tokens), no el `stops.plan` crudo de la reconciliación: el ticker NO se excluye.
        propios: list[str] = []
        normales = []
        for d in discrepancias:
            if d.caso in (reconciliacion.CASO_STOP_DIFIERE, reconciliacion.CASO_SIN_STOP) and self._plan_propio(d.ticker):
                propios.append(d.ticker)
                pos = estado.posiciones.get(d.ticker)
                if pos is not None and d.neta_das is not None:
                    if pos.neta_das != d.neta_das:
                        # R3-DEC-1: la cifra del volcado vale desde que se PIDIÓ (DAS ya conocía todo fill anterior);
                        # sin hora del pedido queda sin hora (salidas.das_confirmada: sin confirmar si hubo fills)
                        pos.neta_das_en = self._barrido_pedido_en
                    pos.neta_das = d.neta_das
                normales.append(dataclasses.replace(d, caso=reconciliacion.CASO_COINCIDE))   # solo adopta sus órdenes
            else:
                normales.append(d)
        acciones += self._absorber(reconciliacion.acciones(normales, estado, self._cot, self._cfg,
                                                           self._tokens.siguiente, self._ahora_et, self._ruta_stop(),
                                                           self._limit_up))
        for ticker in sorted(set(propios)):
            acciones += self._plan(ticker)
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
            T_EXCESO_VERIFICAR: self._t_exceso_verificar, T_TP_LIMBO: self._t_tp_limbo,
            T_CRUCE_POSTONLY: self._t_cruce_postonly, T_HALT_CIERRE_VERIFICAR: self._t_halt_cierre_verificar,
            T_SIMSTATUS_ESPERA: self._t_simstatus_espera, T_PRIORIDAD_ASK: self._t_prioridad_ask,
            T_SALIDA_ESPERA: self._t_salida_espera, T_SLRET_VENTANA: self._t_slret_ventana,
            T_CIERRE_REPONER: self._t_cierre_reponer,
        }

    def _ticker_de_temporizador(self, base: str, clave: str, datos: dict) -> Optional[str]:
        ticker = datos.get("ticker")
        if isinstance(ticker, str) and ticker:
            return ticker
        resto = clave.split(":", 1)[1] if ":" in clave else ""
        if base in (T_REPLACE_VERIFICAR, T_PERSEGUIR_ASK, T_STOP_REINTENTO, T_REINTENTO_RECHAZO, T_LOCATE_RECOMPRAR,
                    T_CRUCE_POSTONLY):
            try:
                o = self._estado.ordenes.get(int(resto))
            except ValueError:
                o = None
            return o.ticker if o is not None else None
        if base in (T_TP_CRUCE, T_HORA_AGREGAR, T_HORA_ASK, T_EOD_COMPROBAR, T_TP_LIMBO, T_PRIORIDAD_ASK):
            return resto.split("|", 1)[0] or None
        if base in (T_LOCATE_INQUIRE, T_SLRET_VENTANA):
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

    def _aplazar_salida(self, pos: PosicionTicker, clave: str, datos: dict, motivo: str) -> list[Accion]:
        """G1A-02 / G1B-01: la salida por temporizador con la guarda cerrada NO se descarta: el mismo temporizador a 0,5 s.

        Se anota UNA vez por clave y motivo (una guarda larga, p. ej. un
        control manual de horas, no llena el diario con una línea cada 0,5 s).
        """
        acciones: list[Accion] = []
        if self._aplazadas.get(clave) != motivo:
            self._aplazadas[clave] = motivo
            acciones.append(Anotar("salida_aplazada", {"ticker": pos.ticker, "clave": clave, "motivo": motivo,
                                                       "regla": "G1A-02 / G1B-01"}))
        return acciones + [Programar(clave, SALIDA_REPROGRAMAR_S, dict(datos))]

    def _sigue_sin_libres(self, pos: PosicionTicker, lote: Lote) -> bool:
        """R2-DEC-1: `_libres` da 0 pero hay algo que cerrar: la posición sigue corta y el lote tiene acciones sin salida.

        Corto = neta de fills y, si DAS ya la dijo, la menor de las dos (como
        `_libres`). Sin posición corta o con todo el lote ya cubierto por sus
        propias salidas vivas no hay nada que esperar.
        """
        if lote.estado not in _LOTE_VIVO:
            return False
        self._refrescar_tp_pendiente(pos)
        if int(lote.llenas) - int(lote.tp_pendiente) <= 0:
            return False
        corto = -int(pos.neta_fills)
        if pos.neta_das is not None:
            corto = min(corto, -int(pos.neta_das))
        return corto > 0

    def _espera_sin_libres(self, pos: PosicionTicker, lote: Lote, clave: str,
                           paso: str) -> Optional[tuple[float, list[Accion]]]:
        """R2-DEC-1 (G1B-05, director): una salida con 0 acciones libres NO se pierde en silencio.

        Si la posición sigue corta y el lote tiene acciones (`_sigue_sin_libres`)
        devuelve `(en_s, acciones)`: se anota UNA vez por clave y la salida se
        vuelve a mirar a 0,5 s; si lleva ≥ 60 s así, `Avisar(2)` una vez y se
        sigue mirando cada 5 s. Si no, None (y se olvida la clave): no hay nada
        que cerrar. Típico: una HALT_BANDA o un cierre humano vivos que luego se
        retiran, o una neta de DAS atrasada.
        """
        if not self._sigue_sin_libres(pos, lote):
            self._olvidar_sin_libres(clave)
            return None
        acciones: list[Accion] = []
        desde = self._sin_libres_desde.get(clave)
        if desde is None:
            desde = self._sin_libres_desde[clave] = self._ahora
            acciones.append(Anotar("salida_sin_libres", {
                "ticker": pos.ticker, "lote_id": lote.id, "clave": clave, "paso": paso,
                "comprando": self._comprando(pos.ticker), "neta_fills": pos.neta_fills, "neta_das": pos.neta_das,
                "motivo": "compras de cierre vivas o DAS dejan 0 acciones libres; se vuelve a mirar",
                "regla": "R2-DEC-1 / G1B-05"}))
        if self._ahora - desde < SIN_LIBRES_AVISO_S:
            return SALIDA_REPROGRAMAR_S, acciones
        if clave not in self._sin_libres_avisado:
            self._sin_libres_avisado.add(clave)
            acciones.append(Avisar(Nivel.AVISO, Grupo.B,
                                   f"{avisos.escapar_html(pos.ticker)}: la salida ({avisos.escapar_html(paso)}) del lote "
                                   f"{avisos.escapar_html(lote.id)} lleva {int(self._ahora - desde)} s sin acciones "
                                   f"libres (compras de cierre vivas: {self._comprando(pos.ticker)}; posición "
                                   f"{pos.neta_fills:+d}, DAS {pos.neta_das}); se sigue mirando cada "
                                   f"{int(SIN_LIBRES_LENTO_S)} s",
                                   clave=f"sin_libres:{clave}"))
        return SIN_LIBRES_LENTO_S, acciones

    def _olvidar_sin_libres(self, clave: str) -> None:
        self._sin_libres_desde.pop(clave, None)
        self._sin_libres_avisado.discard(clave)

    def _reprogramar_sin_libres(self, pos: PosicionTicker, lote: Lote, clave: str, datos: dict,
                                paso: str) -> list[Accion]:
        """R2-DEC-1: libres ≤ 0 en un temporizador de salida → anotar y el MISMO temporizador otra vez (ver `_espera_sin_libres`)."""
        espera = self._espera_sin_libres(pos, lote, clave, paso)
        if espera is None:
            return []
        en_s, acciones = espera
        return acciones + [Programar(clave, en_s, dict(datos))]

    def _t_tp_cruce(self, clave: str, datos: dict) -> list[Accion]:
        """F4.3 (R-D-03 v2): el TP no llenó agregando → cancelar y, con el Canceled, `tp_al_vencer` con el resto CONFIRMADO.

        Guarda (G1A-02 / G1B-01): cerrada → el mismo temporizador a 0,5 s.
        D2-12: un TP que se programó sin libro (`datos["token"]` None) va
        directo a `tp_al_vencer` (cruza con techo o avisa de limbo).
        """
        pos = self._pos_de(clave, datos)
        lote = pos.lotes.get(str(datos.get("lote_id"))) if pos is not None else None
        if pos is None or lote is None:
            return []
        guarda = self._puede_gestionar_salida(pos)
        if guarda is not None and lote.estado in _LOTE_VIVO:
            return self._aplazar_salida(pos, clave, datos, guarda)
        token = datos.get("token")
        if token is None and datos.get("sin_libro"):
            return self._tp_sin_libro(pos, lote, datos, clave)
        o = self._estado.ordenes.get(token) if isinstance(token, int) else None
        if o is None:
            return []
        if o.estado in _VIVOS and _qty_viva(o) > 0:
            self._poner_continuacion(o.token, T_TP_CRUCE, {"lote_id": lote.id, "ticker": pos.ticker})
            return self._cancelar_orden(o, "R-D-03 v2: el TP no llenó agregando; se cruza el resto")
        return self._tp_resto(pos, lote, o) if self._cuadrada(o) else []

    def _tp_sin_libro(self, pos: PosicionTicker, lote: Lote, datos: dict,
                      clave: Optional[str] = None) -> list[Accion]:
        """D2-12: el TP no pudo agregar (libro cruzado o bloqueado): a su vencimiento se cruza con techo o hay limbo.

        R2-DEC-1: con 0 acciones libres (p. ej. una HALT_BANDA viva) y la
        posición aún corta, el mismo `tp_cruce` se vuelve a mirar (0,5 s; tras
        60 s, aviso 2 y cada 5 s): el cruce del TP no se pierde.
        """
        if lote.estado not in _LOTE_VIVO:
            return []
        clave = clave or salidas.clave_tp_cruce(lote.id, datos.get("token_reservado"))
        qty = datos.get("qty")
        pedidas = int(qty) if type(qty) is int else 0
        libres = self._libres(pos, lote)
        resto = min(pedidas, libres)
        if resto <= 0:
            if pedidas > 0 and libres <= 0:
                return self._reprogramar_sin_libres(pos, lote, clave, datos, "tp sin libro")
            return []
        self._olvidar_sin_libres(clave)
        return self._cruce_tp(pos, lote, resto)

    def _cruce_tp(self, pos: PosicionTicker, lote: Lote, resto: int) -> list[Accion]:
        """R-D-03 v2 (1)-(3): `tp_al_vencer` (al ask con techo 3 % o limbo) y, si sale la orden, el aviso de limbo a 5 s (D2-13)."""
        orden, aviso = salidas.tp_al_vencer(lote, resto, self._cot(pos.ticker), self._cfg, self._tokens.siguiente,
                                            self._ahora_et)
        acciones: list[Accion] = []
        if orden is not None:
            acciones += self._absorber([EnviarOrden(orden)])
            acciones += self._seguimiento_salida(lote, orden)
        if aviso is not None:
            acciones.append(aviso)
        return acciones

    def _tp_resto(self, pos: PosicionTicker, lote: Lote, o: Orden) -> list[Accion]:
        """El resto CONFIRMADO del TP tras su Canceled (con la guarda: cerrada → `tp_cruce` de esa orden a 0,5 s).

        R2-DEC-1: con resto por cruzar pero 0 acciones libres y la posición aún
        corta, el `tp_cruce` de esa orden se vuelve a mirar (0,5 s; tras 60 s,
        aviso 2 y cada 5 s) en vez de perder el cruce.
        """
        if lote.estado not in _LOTE_VIVO:
            return []
        clave = salidas.clave_tp_cruce(lote.id, o.token)
        datos = {"lote_id": lote.id, "ticker": pos.ticker, "token": o.token, "qty": o.qty}
        guarda = self._puede_gestionar_salida(pos)
        if guarda is not None:
            return self._aplazar_salida(pos, clave, datos, guarda)
        pendiente = max(o.qty - o.llenas, 0)
        libres = self._libres(pos, lote)
        resto = min(pendiente, libres)
        if resto <= 0:
            if pendiente > 0 and libres <= 0:
                return self._reprogramar_sin_libres(pos, lote, clave, datos, "resto del tp")
            return []
        self._olvidar_sin_libres(clave)
        return self._cruce_tp(pos, lote, resto)

    def _t_tp_limbo(self, clave: str, datos: dict) -> list[Accion]:
        """D2-13: la orden de cruce del TP sigue viva sin llenar a los 5 s → aviso de limbo (sin perseguir ni cancelar)."""
        pos = self._pos_de(clave, datos)
        lote = pos.lotes.get(str(datos.get("lote_id"))) if pos is not None else None
        token = datos.get("token")
        o = self._estado.ordenes.get(token) if isinstance(token, int) else None
        if lote is None or o is None:
            return []
        aviso = salidas.comprobar_limbo_tp(lote, o)
        return [aviso] if aviso is not None else []

    def _t_prioridad_ask(self, clave: str, datos: dict) -> list[Accion]:
        """G1A-06: el paso al ask de R-D-07 que la guarda (o la falta de ask) aplazó."""
        pos = self._pos_de(clave, datos)
        lote = pos.lotes.get(str(datos.get("lote_id"))) if pos is not None else None
        token = datos.get("token")
        o = self._estado.ordenes.get(token) if isinstance(token, int) else None
        if pos is None or lote is None or o is None or not self._cuadrada(o):
            return []
        return self._prioridad_al_ask(pos, lote, o, _proposito(datos.get("proposito"), Proposito.TP_CRUCE))

    def _t_salida_espera(self, clave: str, datos: dict) -> list[Accion]:
        """G1A-06 / G1B-02 / G1B-01: sin entradas vivas en el ticker, salen las salidas del motor que esperaban."""
        ticker = str(datos.get("ticker") or clave.split(":", 1)[1])
        if ticker not in self._salidas_tras_entrada:
            return []
        if self._entradas_vivas(ticker):
            return [Programar(f"{T_SALIDA_ESPERA}:{ticker}", SALIDA_REPROGRAMAR_S, {"ticker": ticker})]
        return self._salidas_pendientes(ticker)

    def _t_tp_espera_entrada(self, clave: str, datos: dict) -> list[Accion]:
        """R-D-07: la entrada retenida (o el intento en pausa) sigue cuando ya no queda ninguna salida viva en el ticker.

        G1A-06: una entrada retenida NUNCA espera más allá de su caducidad
        (R-B-04): caducada, se descarta ya (no se reevalúa al terminar el TP).
        """
        ticker = str(datos.get("ticker") or clave.split(":", 1)[1])
        acciones: list[Accion] = []
        retenidas = self._entradas_en_espera.get(ticker, [])
        caducadas = [s for s in retenidas if self._caducada(s)]
        if caducadas:
            ids_caducadas = {s.id for s in caducadas}
            self._entradas_en_espera[ticker] = [s for s in retenidas if s.id not in ids_caducadas]
            if not self._entradas_en_espera[ticker]:
                self._entradas_en_espera.pop(ticker, None)
            for s in caducadas:
                acciones += self._descartar(s, f"{entrada.MOTIVO_CADUCADA}: esperaba a la salida viva (R-D-07)",
                                            avisar=True)
        if self._salidas_vivas(ticker):
            if ticker in self._entradas_en_espera or ticker in self._intento_pausado:
                acciones.append(Programar(f"{T_TP_ESPERA_ENTRADA}:{ticker}", TP_ESPERA_ENTRADA_S, {"ticker": ticker}))
            return acciones
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

    def _t_hora_agregar(self, clave: str, datos: dict) -> list[Accion]:
        """F5 / R-D-08: un minuto antes de la hora, el lote AGREGA su salida en el punto medio (PostOnly).

        G1A-02 / G1B-01: con la guarda cerrada se reprograma a 0,5 s; G1B-05:
        la cantidad nunca pasa de lo corto menos las compras de cierre vivas.
        """
        pos, lote = self._lote_de_datos(clave, datos)
        if pos is None or lote is None or lote.estado not in _LOTE_VIVO or lote.llenas <= 0:
            return []
        guarda = self._puede_gestionar_salida(pos)
        if guarda is not None:
            return self._aplazar_salida(pos, clave, datos, guarda)
        qty = self._libres(pos, lote)
        cot = self._cot(pos.ticker)
        if qty <= 0 or not salidas.libro_para_agregar(cot, str(lote.direccion).strip().lower().startswith("long")):
            return [Anotar("salida_hora", {"ticker": pos.ticker, "lote_id": lote.id, "paso": "agregar",
                                           "motivo": "sin acciones libres o sin libro; decide hora_ask"})]
        proposito = _proposito(datos.get("proposito"), Proposito.HORA_AGREGAR)
        orden = salidas.orden_hora_agregar(lote, qty, cot, self._cfg, self._tokens.siguiente, self._ahora_et, proposito)
        return [Anotar("salida_hora", {"ticker": pos.ticker, "lote_id": lote.id, "paso": "agregar", "qty": qty,
                                       "motivo": datos.get("motivo"), "regla": "R-D-08"})] + self._absorber([EnviarOrden(orden)])

    def _t_hora_ask(self, clave: str, datos: dict) -> list[Accion]:
        """F5: a la hora, se cancela lo vivo del lote y, CONFIRMADO el Canceled, todo al ask sin tope y a perseguir.

        G1A-02 / G1B-01: con la guarda cerrada (también al arrancar, hasta
        reconciliar) se reprograma a 0,5 s: nunca se compra a ciegas.
        """
        pos, lote = self._lote_de_datos(clave, datos)
        if pos is None or lote is None or lote.estado not in _LOTE_VIVO or lote.llenas <= 0:
            return []
        guarda = self._puede_gestionar_salida(pos)
        if guarda is not None:
            return self._aplazar_salida(pos, clave, datos, guarda)
        proposito = (Proposito.CIERRE_REINICIO if datos.get("proposito") == Proposito.CIERRE_REINICIO.value
                     else Proposito.HORA_ASK)
        vivas = [o for o in self._vivas(pos.ticker) if o.lote_id == lote.id and o.proposito in _PROP_SALIDA_LOTE]
        if not vivas:
            return self._hora_al_ask(pos, lote, proposito)
        acciones: list[Accion] = []
        for o in vivas:
            self._poner_continuacion(o.token, T_HORA_ASK, {"lote_id": lote.id, "ticker": pos.ticker,
                                                           "proposito": proposito.value})
            acciones += self._cancelar_orden(o, "R-D-08: a la hora se cancela lo vivo y se va al ask")
        return acciones

    def _hora_al_ask(self, pos: PosicionTicker, lote: Lote, proposito: Proposito) -> list[Accion]:
        """F5: todo lo libre del lote AL ASK sin tope y a perseguir (continuación tras el Canceled o sin nada vivo)."""
        if lote.estado not in _LOTE_VIVO or lote.llenas <= 0:
            return []
        if any(o.lote_id == lote.id and o.proposito in _PROP_SALIDA_LOTE for o in self._vivas(pos.ticker)):
            return []
        datos_hora = {"lote_id": lote.id, "ticker": pos.ticker, "proposito": proposito.value}
        guarda = self._puede_gestionar_salida(pos)
        if guarda is not None:
            return self._aplazar_salida(pos, salidas.clave_lote(T_HORA_ASK, lote.id), datos_hora, guarda)
        qty = self._libres(pos, lote)
        cot = self._cot(pos.ticker)
        if qty <= 0:
            if lote.llenas > int(lote.tp_pendiente):
                # G1B-05 / G1B-01: otras compras de cierre (halt, cierre humano) o la neta de DAS dejan 0 ahora:
                # se anota y se vuelve a mirar en 0,5 s (la hora no se negocia, pero tampoco se compra de más)
                return [Anotar("salida_hora", {"ticker": pos.ticker, "lote_id": lote.id, "paso": "al_ask",
                                               "motivo": "compras de cierre vivas o DAS dejan 0 acciones (G1B-05)"}),
                        Programar(salidas.clave_lote(T_HORA_ASK, lote.id), SALIDA_REPROGRAMAR_S, datos_hora)]
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
        guarda = self._puede_gestionar_salida(self._pos(o.ticker))
        if guarda is not None:                              # G1A-02: en BS/halt/manual no se persigue; se espera
            return self._aplazar_salida(self._pos(o.ticker), clave, datos, guarda)
        bloque = (self._cfg.salidas or {}).get("por_hora") or {}
        maximo = bloque.get("perseguir_ask_max", PERSEGUIR_ASK_MAX)
        maximo = maximo if type(maximo) is int and maximo >= 0 else PERSEGUIR_ASK_MAX
        hechas = self._persecuciones.get(o.token, 0)
        acciones: list[Accion] = []
        reemplazo = salidas.perseguir_ask(o, self._cot(o.ticker), hechas, maximo,
                                          share_es_abierta=self._share_es_abierta())
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
        """F6.1: `GET SymStatus X` cada 1 s; LDLU cada minuto en RTH.

        Tickers: con posición o intento, en HALT o con un halt en curso o con
        una señal guardada (G1A-05: la reapertura se detecta aunque el ticker
        quede plano) y, en horario de mercado, los del radar suscritos (E1-03:
        k cuenta también los halts anteriores a la entrada; y la entrada no
        espera el SymStatus). COB-04: con `tecnicos.get_con_simbolo` false, UN
        `GET SymStatus` / `GET LDLU` sin símbolo.
        """
        tickers = self._tickers_simstatus()
        if not tickers or not self._estado.das_conectado:
            self._simstatus_armado = bool(tickers)
            return [Programar(T_SIMSTATUS, SIMSTATUS_CADA_S, {})] if tickers else []
        con_simbolo = self._cfg.tecnicos.get("get_con_simbolo", True) is not False
        acciones: list[Accion] = ([Consultar(protocolo.cmd_get("SymStatus", t)) for t in tickers] if con_simbolo
                                  else [Consultar(protocolo.cmd_get("SymStatus"))])
        if self._es_rth() and (self._ultimo_ldlu_en is None or self._ahora - self._ultimo_ldlu_en >= LDLU_CADA_S):
            self._ultimo_ldlu_en = self._ahora
            acciones += ([Consultar(protocolo.cmd_get("LDLU", t)) for t in tickers] if con_simbolo
                         else [Consultar(protocolo.cmd_get("LDLU"))])
        acciones.append(Programar(T_SIMSTATUS, SIMSTATUS_CADA_S, {}))
        self._simstatus_armado = True
        return acciones

    def _tickers_simstatus(self) -> list[str]:
        """G1A-05 / E1-03: los tickers cuyo estado de símbolo se vigila cada segundo (ver `_t_simstatus`)."""
        tickers = {t for t, p in self._estado.posiciones.items()
                   if self._tiene_posicion(p) or p.intento is not None or p.estado is EstadoTicker.HALT
                   or p.senal_guardada_halt is not None}
        tickers |= self._halt_en_curso
        if self._radar and self._es_mercado(self._franja()):
            vigentes = {t for t, en in self._radar.items() if self._ahora - en <= RADAR_VIGENCIA_S}
            tickers |= {t for t in self._mercado.suscritos() if t in vigentes}
        return sorted(tickers)

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
            if (self._accountinfo_pedido_en is None
                    or self._ahora - self._accountinfo_pedido_en >= ACCOUNTINFO_CADA_S):
                self._accountinfo_pedido_en = self._ahora       # D1-10: el equity del tope corto, al día
                acciones.append(Consultar(protocolo.cmd_get("AccountInfo")))
        cadencia = reconciliacion.cadencia_barrido(estado, self._ahora, self._cfg.tecnicos)
        self._barrido_siguiente_en = self._ahora + cadencia
        acciones.append(Programar(T_BARRIDO, cadencia, {"motivo": "cadencia (R-K-01)"}))
        return acciones

    def _t_bs_cierre(self, clave: str, datos: dict) -> list[Accion]:
        """F7 / R-D-06: reintento del cierre humano durante el protocolo con la neta de ESE momento."""
        pos = self._pos_de(clave, datos)
        if pos is None:
            return []
        esperas = datos.get("esperas")
        acciones = self._absorber(cisne_negro.cierre_humano(
            pos, self._ordenes_ticker(pos.ticker), self._cot(pos.ticker), datos.get("n"), self._cfg,
            self._tokens.siguiente, self._ahora_et, intento=int(datos.get("intento") or 0),
            objetivo=datos.get("objetivo"), signo=datos.get("signo"),
            esperas=esperas if type(esperas) is int and esperas >= 0 else 0))    # E2-03: la espera tiene tope
        self._fin_cierre_humano(pos.ticker, acciones)
        return acciones

    def _fin_cierre_humano(self, ticker: str, acciones: list[Accion]) -> None:
        fin = any(isinstance(a, Anotar) and a.tipo == "cierre_humano_fin" for a in acciones)
        agotado = any(isinstance(a, Avisar) and (a.clave or "").endswith(":agotado") for a in acciones)
        if fin or agotado:
            self._cierre_humano.discard(ticker)

    def _t_cerrar_todo(self, clave: str, datos: dict) -> list[Accion]:
        """R-D-06: paso siguiente de «cerrar todo» de UN ticker (G1B-03 / D2-01: `cerrar_todo:<ticker>`, nunca global).

        D2-03 / G1B-15: en dos pasos («cancelar» → CancelarTicker y esperar
        el Canceled; «enviar» → la orden por la neta de ESE momento menos lo
        que las órdenes vivas aún pueden comprar); el paso «enviar» sale en
        cuanto no queda nada vivo en el ticker (ver `_tras_terminal`) o con el
        respaldo de 1 s. Agotado (D2-04): la orden de cierre viva se RETIRA y
        los stops vuelven cuando esa retirada está confirmada (respaldo 1 s).
        """
        ticker = str(datos.get("ticker") or (datos.get("tickers") or [""])[0] or
                     (clave.split(":", 1)[1] if ":" in clave else ""))
        if not ticker:
            return [Anotar("temporizador_desconocido", {"clave": clave, "motivo": "cerrar_todo sin ticker"})]
        fase = datos.get("fase")
        if fase not in salidas.FASES_CERRAR_TODO:
            fase = salidas.FASE_CANCELAR
        if fase == salidas.FASE_ENVIAR:
            self._cerrar_todo_enviar.pop(ticker, None)
        acciones = self._absorber(salidas.cerrar_todo(
            self._estado.posiciones, self._cot, self._cfg, self._tokens.siguiente, self._ahora_et,
            _proposito(datos.get("proposito"), Proposito.CIERRE_HUMANO), int(datos.get("intento") or 0), [ticker],
            vivas_de=self._vivas, fase=fase))
        acciones += self._seguir_cerrar_todo(ticker, acciones)
        return acciones

    def _seguir_cerrar_todo(self, ticker: str, acciones: list[Accion]) -> list[Accion]:
        """Lo que el decisor hace con la salida de `salidas.cerrar_todo` para UN ticker (pasos, agotado, fin)."""
        programas = [a for a in acciones if isinstance(a, Programar) and a.clave == salidas.clave_cerrar_todo(ticker)]
        for p in programas:
            if p.datos.get("fase") == salidas.FASE_ENVIAR:
                self._cerrar_todo_enviar[ticker] = dict(p.datos)
        if programas:
            return []
        agotado = any(isinstance(a, Avisar) and (a.clave or "") == f"{salidas.CLAVE_CERRAR_TODO}:{ticker}:agotado"
                      for a in acciones)
        retirada = any(isinstance(a, (Cancelar, CancelarTicker)) for a in acciones)
        self._cerrar_todo_enviar.pop(ticker, None)
        if agotado and retirada:
            self._retirando_cierre.add(ticker)
            return [Anotar("cierre_retirado", {"ticker": ticker, "regla": "R-D-06 / D2-04: los stops vuelven tras el "
                                                                          "Canceled de la orden retirada"}),
                    Programar(f"{T_CIERRE_REPONER}:{ticker}", CIERRE_REPONER_S, {"ticker": ticker})]
        self._cierre_humano.discard(ticker)
        return self._plan(ticker)

    def _t_cierre_reponer(self, clave: str, datos: dict) -> list[Accion]:
        """D2-04: respaldo: 1 s después de retirar el cierre agotado, los stops vuelven aunque el Canceled no haya llegado."""
        ticker = str(datos.get("ticker") or clave.split(":", 1)[1])
        if ticker not in self._retirando_cierre:
            return []
        return self._reponer_tras_cierre(ticker, "respaldo: 1 s sin confirmar la retirada")

    def _t_exceso_verificar(self, clave: str, datos: dict) -> list[Accion]:
        """D2a-04 (R-C-11 (3)): la venta del exceso no llenó → persecución al bid nuevo (3 veces) y luego «VENDER A MANO»."""
        ticker = str(datos.get("ticker") or clave.split(":", 1)[1])
        pos = self._estado.posiciones.get(ticker)
        if pos is None:
            return []
        persecuciones = datos.get("persecuciones")
        return self._absorber(stops.verificar_venta_exceso(
            pos, self._ordenes_ticker(ticker), self._cot(ticker), self._tokens.siguiente, self._cfg, self._ahora_et,
            pos.version_stops, persecuciones=persecuciones if type(persecuciones) is int else 0,
            pedidos_en_vuelo=self._pedidos_en_vuelo(ticker)))       # R2-DEC-4: un CANCEL ya pedido no se repite

    def _t_cruce_postonly(self, clave: str, datos: dict) -> list[Accion]:
        """D2-09: el agregar de la entrada rechazado por PostOnly pasa YA a la fase de cruce de R-B-01 v3 (sin pausa).

        Mismas guardas que el cruce al vencer: con las entradas bloqueadas o
        el bid caído > 3 % no se cruza (se cierra el intento con lo llenado).
        """
        ticker = str(datos.get("ticker") or "")
        pos = self._estado.posiciones.get(ticker)
        intento = pos.intento if pos is not None else None
        if pos is None or intento is None or intento.fase is FaseIntento.TERMINADO:
            return []
        self._intento_en_reintento.discard(ticker)
        self._soltar_cuadrados(intento)
        if intento.token_agregar is not None or intento.token_cruce is not None:
            return [Anotar("reintento_descartado", {"ticker": ticker, "motivo": "el intento ya tiene otra orden viva"})]
        acciones: list[Accion] = [Anotar("intento", {"ticker": ticker, "fase": "cruzando", "motivo":
                                                     "D2-09: PostOnly rechazado; se cruza sin esperar a t_limite"}),
                                  Desprogramar(f"{T_CRUCE}:{ticker}")]
        motivo = self._motivo_cancel.pop(ticker, None)
        if motivo in _TEXTO_MOTIVO_CIERRE:
            return acciones + self._cerrar_intento(pos, _TEXTO_MOTIVO_CIERRE[motivo])
        return acciones + self._enviar_cruce(pos)

    def _t_halt_cierre_verificar(self, clave: str, datos: dict) -> list[Accion]:
        """G1A-01: 2 s tras reabrir (o tras la MKT de la banda), la salida del halt que no llenó se RETIRA; con su
        Canceled el plan devuelve los stops a la posición (`_tras_terminal`) y se avisa nivel 2.

        R2-DEC-2 (E1-02): tras una REAPERTURA (`datos["reapertura"]`) se vuelve
        a mirar el tope del T1 con el `last` de ESTE momento (el primer print
        puede llegar después del `T`): superado → la salida viva se retira,
        aviso MÁXIMO y CONTROL_HUMANO (`_tope_t1_control_humano`). Tras la MKT
        de la banda (sin halt) no se mira."""
        ticker = str(datos.get("ticker") or clave.split(":", 1)[1])
        pos = self._estado.posiciones.get(ticker)
        if datos.get("reapertura") and pos is not None and pos.neta < 0:
            cot = self._cot(ticker)
            tope = self._tope_t1_control_humano(pos, cot.last if cot is not None and _es_precio(cot.last) else None,
                                                "2 s tras reabrir")
            if tope is not None:
                return tope
        acciones: list[Accion] = []
        for o in self._vivas(ticker):
            if o.proposito in _PROP_CIERRE_HALT and _qty_viva(o) > 0:
                acciones.append(Anotar("halt_salida_retirada", {"ticker": ticker, "token": o.token, "llenas": o.llenas,
                                                                "qty": o.qty, "regla": "G1A-01"}))
                acciones += self._cancelar_orden(o, "G1A-01: la salida del halt no llenó en 2 s; vuelven los stops")
        return acciones

    def _t_simstatus_espera(self, clave: str, datos: dict) -> list[Accion]:
        """G1A-05: 1 s sin respuesta al `GET SymStatus X` → las entradas siguen (el halt lo detecta el SymStatus de 1 s)."""
        ticker = str(datos.get("ticker") or clave.split(":", 1)[1])
        return self._liberar_entradas_simstatus(ticker, sin_respuesta=True)

    def _t_stop_reintento(self, clave: str, datos: dict) -> list[Accion]:
        """R-C-03: el stop rechazado se repone con `stops.plan` (idempotente) llevando la cuenta de intentos.

        G1B-07 / G1A-11: la separación era de ESE propósito: al vencer se
        levanta solo `(ticker, propósito)`; un agotado (`inf`) sigue hasta
        /stop o /reanudar. Sin propósito en los datos (contrato anterior) se
        levantan las separaciones con fin de ese ticker.
        """
        ticker = str(datos.get("ticker") or "")
        pos = self._estado.posiciones.get(ticker)
        if pos is None or pos.estado is EstadoTicker.BS or pos.neta >= 0:
            return []
        proposito = _proposito(datos.get("proposito"), Proposito.DESCONOCIDA)
        for clave_bloqueo in [k for k in self._stop_bloqueo if k[0] == ticker]:
            if proposito is not Proposito.DESCONOCIDA and clave_bloqueo[1] is not proposito:
                continue
            if self._stop_bloqueo[clave_bloqueo] != math.inf:
                self._stop_bloqueo.pop(clave_bloqueo, None)     # se acabó la separación de R-C-03: el plan repone
        if (datos.get("proposito") == Proposito.STOP_PROTECCION.value and datos.get("lote_id") is None
                and not self._lotes_vivos(pos)):
            if self._stop_bloqueado(ticker, Proposito.STOP_PROTECCION):
                return [Anotar("stop_bloqueado", {
                    "ticker": ticker, "proposito": Proposito.STOP_PROTECCION.value,
                    "motivo": ("halt: se repone al reabrir (G1B-14)" if ticker in self._stops_diferidos_halt
                               else "R-C-03 agotado: decide Jaume")})]
            intento = int(datos.get("intento") or 0)
            primero = datos.get("primer_intento_en")
            falta = stops.descubiertas(pos, self._ordenes_ticker(ticker), self._cfg.stops, self._limit_up(ticker),
                                       compras_cierre=self._compras_cierre(ticker))
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
                    # D1-01 / D1-06 / D1-07: el mismo cálculo que la entrada (margen de lo abierto y de lo pendiente de
                    # los DEMÁS tickers; lo pendiente de este es justo lo que se redimensiona)
                    caben, _ = self._acciones_que_caben(pendiente, cot.ask, simb.tasa_corta,
                                                        excluir_pendiente_de=ticker)
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
        acciones += self._proteger(None, "slret_ventana", self._slret_tic)
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
            acciones += [Suscribir(t, True), Consultar(protocolo.cmd_get("SHORTINFO", t))]
        acciones += [Suscribir(t, False) for t in bajas]
        if altas:
            acciones += self._armar_simstatus()              # E1-03: un radar recién suscrito entra en el SymStatus
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
        datos, detalle = self._resumen_del_dia()
        return [Anotar("resumen_diario", {**datos, "dia": estado.dia, "regla": "R-M-01 / COB-02"}),
                Avisar(Nivel.INFO, Grupo.B, f"<b>Resumen del día</b>\n{texto}\n{detalle}",
                       clave=f"resumen:{estado.dia.isoformat()}")]

    def _resumen_del_dia(self) -> tuple[dict, str]:
        """COB-02 (R-M-01): operaciones y resultado por estrategia, gasto de locates, slippage medido e incidentes del día.

        El resultado por estrategia es el flujo REALIZADO de sus fills (ventas
        − compras) repartido por lote; tras el último EOD las posiciones del
        bot están cerradas y es el resultado del día.
        """
        esc = avisos.escapar_html
        sids = sorted(set(self._operaciones_estrategia) | set(self._flujo_estrategia))
        por_estrategia = []
        lineas = ["<b>Por estrategia</b>"]
        for sid in sids:
            e = self._cfg.estrategias.get(sid)
            nombre = e.name if e is not None else sid
            ops = self._operaciones_estrategia.get(sid, 0)
            resultado = self._flujo_estrategia.get(sid, Decimal("0")).quantize(Decimal("0.01"))
            por_estrategia.append({"strategy_id": sid, "operaciones": ops, "resultado": resultado})
            lineas.append(f"· {esc(nombre)}: {ops} operaciones, resultado {resultado:+} $")
        if not sids:
            lineas.append("· sin operaciones")
        gasto = Decimal(self._estado.gasto_locates_dia).quantize(Decimal("0.01"))
        lineas.append(f"Locates: {gasto} $ gastados")
        slippage = None
        if self._slippage_bps:
            slippage = (sum(self._slippage_bps, Decimal("0")) / len(self._slippage_bps) / 100).quantize(Decimal("0.001"))
            lineas.append(f"Slippage medio de la entrada frente a la señal: {slippage:+} % "
                          f"({len(self._slippage_bps)} entradas)")
        else:
            lineas.append("Slippage medio de la entrada: sin entradas")
        incidentes = dict(sorted(self._incidentes_dia.items()))
        total = sum(incidentes.values())
        lineas.append(f"Incidentes: {total}" + (" (" + esc(", ".join(f"{k} {v}" for k, v in incidentes.items())) + ")"
                                                 if incidentes else ""))
        datos = {"por_estrategia": por_estrategia, "gasto_locates": gasto, "slippage_medio_pct": slippage,
                 "entradas_medidas": len(self._slippage_bps), "incidentes": incidentes}
        return datos, "\n".join(lineas)

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
            self._accountinfo_pedido_en = self._ahora
            acciones += [Consultar(protocolo.cmd_get("BP")), Consultar(protocolo.cmd_get("AccountInfo")),
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
        # lo que el resumen del día (COB-02) y la OPA (E1-08) cuentan por día
        self._max_pm.clear()
        self._opa_revisado_en.clear()
        self._flujo_estrategia.clear()
        self._operaciones_estrategia.clear()
        self._slippage_bps.clear()
        self._incidentes_dia.clear()
        self._comandos_vistos.clear()
        self._salidas_avisadas.clear()
        self._aplazadas.clear()
        self._sin_libres_desde.clear()
        self._sin_libres_avisado.clear()
        return acciones

    # ═══════════════════════════ comandos (R-M-04) ═════════════════════════
    def _comando(self, c: Comando) -> list[Accion]:
        """R-M-04 / R-Q-01: consulta → respuesta; dos pasos → `Confirmaciones`; «SI» o confirmado → se ejecuta."""
        if not isinstance(c, Comando):
            return [Anotar("comando_invalido", {"tipo": type(c).__name__})]
        datos = {"nombre": c.nombre, "args": list(c.args), "chat_id": c.chat_id, "id": c.id, "requiere": c.requiere}
        if isinstance(c.id, str) and c.id:
            if c.id in self._comandos_vistos:
                # C-02 (red extra): Telegram puede reentregar el último update tras un reinicio; «/cerrar X N SI» dos
                # veces cerraría N acciones MÁS. Un id ya visto no se ejecuta ni se contesta otra vez.
                return [Anotar("comando_repetido", {**datos, "regla": "C-02"})]
            self._comandos_vistos.add(c.id)
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
            if args:
                return self._sigue_ticker(c, args[0])
            estado.pausa_global = False
            for pos in estado.posiciones.values():
                pos.intervencion_humana = False
            vetados = sorted(t for t, p in estado.posiciones.items() if p.sin_reentrada_hasta_sigue)
            return [self._anotar_comando(c), self._responder(
                "Sigue: se levanta la pausa por intervención humana (R-M-03)"
                + (f". Siguen vetados tras un cisne negro (se levantan con /sigue TICKER, R-G-03): "
                   f"{esc(', '.join(vetados))}" if vetados else ""))]
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

    def _sigue_ticker(self, c: Comando, ticker: str) -> list[Accion]:
        """G1A-08 / G1B-12 (R-G-03): «/sigue X» levanta el veto de reentrada tras el cisne negro de X.

        Pone `sin_reentrada_hasta_sigue` e `intervencion_humana` de X a False
        y, si X estaba en CONTROL_HUMANO, lo devuelve a NORMAL: lo mismo que
        `diario.reconstruir` rehace con el comando anotado con `args=[X]`. Un
        cisne negro aún vivo manda (el ticker sigue en BS) y el control manual
        (/cancelar_ordenes) solo se levanta con /reanudar X.
        """
        esc = avisos.escapar_html
        pos = self._estado.posiciones.get(ticker)
        acciones: list[Accion] = [self._anotar_comando(c, "sigue", [ticker])]
        if pos is None:
            return acciones + [self._responder(f"{esc(ticker)}: el bot no tiene estado de este ticker; nada que levantar")]
        pos.sin_reentrada_hasta_sigue = False
        pos.intervencion_humana = False
        if pos.estado is EstadoTicker.CONTROL_HUMANO:
            pos.estado = EstadoTicker.NORMAL
            pos.motivo_estado = ""
            pos.desde = self._ahora
            acciones.append(Anotar("reanudar", {"ticker": ticker, "motivo": "/sigue (R-G-03)"}))
        extra = ""
        if pos.estado is EstadoTicker.BS:
            extra = " (el cisne negro sigue vivo: manda su protocolo)"
        elif ticker in self._manual:
            extra = " (sigue en control manual hasta /reanudar)"
        return acciones + [self._responder(f"{esc(ticker)}: se levanta el veto de reentrada tras el cisne negro "
                                           f"(R-G-03){extra}")]

    def _silenciar(self, c: Comando, silenciar: bool) -> list[Accion]:
        """F7 / G1A-19 (R-G-01): «/parar_avisos X BS» calla SOLO los informes del cisne negro de X; «/reanudar_avisos X BS»
        los devuelve.

        Sin ticker: con un único cisne negro vivo se aplica a él; con varios
        se pide el ticker (nunca se callan todos a la vez). Se anota con
        `args=[X, "BS"]`, la forma que `diario.reconstruir` rehace.
        """
        esc = avisos.escapar_html
        activos = [t for t, p in sorted(self._estado.posiciones.items()) if p.bs is not None]
        args = [str(a) for a in c.args]
        if args:
            objetivo = args[0]
        elif len(activos) == 1:
            objetivo = activos[0]
        else:
            if not activos:
                return [self._anotar_comando(c), self._responder("Informes de cisne negro: ninguno activo")]
            return [Anotar("comando", {"nombre": c.nombre, "args": [], "chat_id": c.chat_id, "id": c.id,
                                       "confirmado": False, "motivo": "varios cisnes negros: falta el ticker"}),
                    self._responder(f"Hay varios cisnes negros activos ({esc(', '.join(activos))}): indica cuál con "
                                    f"/{esc(c.nombre)} TICKER BS")]
        acciones: list[Accion] = [self._anotar_comando(c, c.nombre, [objetivo, "BS"])]
        pos = self._estado.posiciones.get(objetivo)
        if pos is None or pos.bs is None:
            return acciones + [self._responder(f"{esc(objetivo)}: no tiene un cisne negro activo")]
        if pos.bs.silenciado != silenciar:
            pos.bs = dataclasses.replace(pos.bs, silenciado=silenciar)
            acciones.append(Anotar("bs", {"ticker": objetivo,
                                          "evento": "silenciado" if silenciar else "avisos_reanudados",
                                          "silenciado": silenciar}))
            if not silenciar:
                acciones.append(Programar(f"{T_BS_INFORME}:{objetivo}", 0.0, {"ticker": objetivo}))
        texto = f"Informes del cisne negro de {objetivo} " + ("silenciados" if silenciar else "reanudados")
        return acciones + [self._responder(esc(texto))]

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
        antes = e.al_desactivar
        self._override_estrategia.setdefault(e.strategy_id, {})["al_desactivar"] = modo
        self._recomponer_cfg()
        # G1B-09: el cambio queda en el diario con la forma que `diario.memoria_decisor` rehace tras un reinicio
        acciones: list[Accion] = [self._anotar_comando(c),
                                  Anotar("config_cambio", {"ruta": f"estrategias.{e.strategy_id}.al_desactivar",
                                                           "antes": antes, "despues": modo, "caliente": True,
                                                           "aplicado": True, "origen": "telegram"})]
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
        # D2-03 / G1B-15: paso «cancelar» (CancelarTicker y, con algo vivo, la orden sale tras su Canceled); G1B-03 /
        # D2-01: un temporizador por ticker
        cierre = self._absorber(salidas.cerrar_todo(self._estado.posiciones, self._cot, self._cfg,
                                                    self._tokens.siguiente, self._ahora_et, vivas_de=self._vivas,
                                                    fase=salidas.FASE_CANCELAR))
        tickers = sorted({a.ticker for a in cierre if isinstance(a, CancelarTicker)})
        for t in tickers:
            self._cierre_humano.add(t)
        seguimiento: list[Accion] = []
        for t in tickers:
            seguimiento += self._seguir_cerrar_todo(t, cierre)
        return acciones + cierre + seguimiento + [self._responder(
            "Cerrar todo: se cancelan las órdenes y sale el cierre (R-D-06); los stops no se reponen mientras dure")]

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
            # D2-03 / G1B-15: cancelar primero; la orden de cierre sale tras el Canceled (o con el respaldo de 1 s)
            cierre = self._absorber(salidas.cerrar_todo(self._estado.posiciones, self._cot, self._cfg,
                                                        self._tokens.siguiente, self._ahora_et, tickers=[ticker],
                                                        vivas_de=self._vivas, fase=salidas.FASE_CANCELAR))
            cierre += self._seguir_cerrar_todo(ticker, cierre)
        return acciones + cierre + [self._responder(f"{avisos.escapar_html(ticker)}: cierre en marcha"
                                                    + (f" ({n} acciones)" if n is not None else "") + " (R-D-06)")]

    def _comando_stop(self, c: Comando, ticker: str, precio: Decimal) -> list[Accion]:
        """/stop X PRECIO SI: el nivel L de los lotes vivos pasa a PRECIO y el plan recoloca; sin lotes, protección a ese disparo.

        G1B-06: es una orden EXPLÍCITA del humano: saca el ticker del control
        manual (el ticker sigue en CONTROL_HUMANO para abrir y para las
        salidas del bot hasta /reanudar X, pero los stops vuelven a ser del
        bot) y de los bloqueos de R-C-03, y contesta con lo que se ENVIÓ de
        verdad (tokens y cantidades) o con el motivo por el que no salió (cisne
        negro, cierre humano en curso, halt: se pone al reabrir).
        """
        esc = avisos.escapar_html
        pos = self._estado.posiciones.get(ticker)
        if pos is None or pos.neta >= 0:
            if pos is not None and pos.neta == 0 and pos.neta_das is not None and pos.neta_das < 0:
                return [self._anotar_comando(c), self._responder(
                    f"{esc(ticker)}: NO se ha puesto nada: la posición de DAS ({pos.neta_das:+d}) no es del bot (sin "
                    f"fills suyos); la protege la reconciliación (R-C-10 caso 4). Muévela a mano en DAS")]
            return [self._anotar_comando(c), self._responder(f"{esc(ticker)}: no hay corto al que poner stop")]
        acciones: list[Accion] = [self._anotar_comando(c)]
        if pos.estado is EstadoTicker.BS or pos.bs is not None:
            return acciones + [self._responder(f"{esc(ticker)}: en cisne negro los stops no se mueven (R-G-01/R-G-03): "
                                               f"NO se ha puesto nada; para cerrar usa /cerrar {esc(ticker)} SI")]
        estaba_manual = ticker in self._manual
        self._manual.discard(ticker)
        self._olvidar_rechazos_de_stop(ticker)
        if estaba_manual and pos.estado is EstadoTicker.CONTROL_HUMANO:
            pos.motivo_estado = _MOTIVO_STOP_MANUAL
            pos.desde = self._ahora
            acciones.append(Anotar("pausa", {"ticker": ticker, "estado": pos.estado.value, "motivo": _MOTIVO_STOP_MANUAL,
                                             "regla": "G1B-06"}))
        vivos = self._lotes_vivos(pos)
        antes = len(acciones)
        motivo_sin_lotes: Optional[str] = None
        if vivos:
            for lote in vivos:
                lote.nivel_stop = precio
                lote.principal_consumido = False
                acciones.append(Anotar("lote", {"lote_id": lote.id, "ticker": ticker, "nivel_stop": precio,
                                                "principal_consumido": False, "motivo": "/stop"}))
            acciones += self._plan(ticker)
        elif ticker in self._cierre_humano or self._stop_bloqueado(ticker, Proposito.STOP_PROTECCION):
            pass                                             # el motivo va en la respuesta
        else:
            sin_lotes, motivo_sin_lotes = self._stop_manual_sin_lotes(pos, precio)
            acciones += sin_lotes
        enviadas = [a.orden for a in acciones[antes:] if isinstance(a, EnviarOrden)]
        movidas = [a for a in acciones[antes:] if isinstance(a, Reemplazar)]
        canceladas = [a for a in acciones[antes:] if isinstance(a, Cancelar)]
        if enviadas or movidas:
            partes = [f"{o.proposito.value} {o.qty} @ {o.stop} (token {o.token})" for o in enviadas]
            partes += [f"reemplazo token {a.token}: {a.qty} @ {a.stop}" for a in movidas]
            texto = f"{esc(ticker)}: stop a {precio}: " + esc("; ".join(partes))
            if canceladas:
                texto += f"; {len(canceladas)} stop(s) viejo(s) cancelado(s)"
            if estaba_manual:
                texto += ". Sale del control manual para los stops; las salidas del bot vuelven con /reanudar"
            return acciones + [self._responder(texto)]
        if ticker in self._cierre_humano:
            motivo = "hay un cierre humano en curso (R-D-06): el stop se pone si el cierre se retira"
        elif motivo_sin_lotes is not None:
            motivo = motivo_sin_lotes
        elif ticker in self._stops_diferidos_halt or pos.estado is EstadoTicker.HALT or ticker in self._halt_en_curso:
            motivo = "el símbolo está en HALT: el stop se pone al reabrir (R-C-04)"
        elif any(k[0] == ticker for k, hasta in self._stop_bloqueo.items() if hasta > self._ahora):
            motivo = "R-C-03: DAS acaba de rechazar ese stop; se repone tras la separación"
        elif vivos:
            motivo = "el stop ya estaba así (nada que cambiar)"
        else:
            motivo = "la posición ya está cubierta por otro stop"
        return acciones + [self._responder(f"{esc(ticker)}: NO se ha enviado ningún stop nuevo a {precio}: {esc(motivo)}")]

    def _stop_manual_sin_lotes(self, pos: PosicionTicker, precio: Decimal) -> tuple[list[Accion], Optional[str]]:
        """G1B-06: /stop en una posición sin lotes vivos: UNA protección propia (sin lote) a `precio`.

        Si ya hay protección propia se MUEVE por REPLACE (con su verificación
        del pre/post) y las demás propias se cancelan: nunca dos protecciones
        a la vez. Sin ninguna, sale una nueva por lo que ninguna otra compra
        viva cubre (nunca más que la posición). Devuelve (acciones, motivo si
        no salió nada).
        """
        ticker = pos.ticker
        limite = precios.con_techo(precio, _pct(self._cfg.stops, "principal_limite_pct", STOP_PRINCIPAL_LIMITE_PCT),
                                   arriba=True)
        vivas = self._vivas(ticker)
        propias = sorted((o for o in vivas if o.lado is Lado.COMPRA and o.tipo is TipoOrden.STOP_LIMITE_PP
                          and o.proposito is Proposito.STOP_PROTECCION and o.lote_id is None
                          and o.origen is not Origen.VIGILANTE and _qty_viva(o) > 0), key=lambda o: o.token)
        tokens_propias = {o.token for o in propias}
        otras = sum(_qty_viva(o) for o in vivas
                    if o.lado is Lado.COMPRA and o.token not in tokens_propias and o.token not in self._cancel_pedido)
        objetivo = max(-pos.neta - otras, 0)
        if objetivo <= 0:
            return [], "la posición ya está cubierta por otras compras vivas (stops o cierres)"
        if propias:
            if any(o.id_das is None or o.token in self._cancel_pedido or o.token in self._reemplazo_pedido
                   for o in propias):
                return ([Anotar("stop_manual_diferido", {"ticker": ticker, "tokens": sorted(tokens_propias),
                                                         "regla": "G1B-06"})],
                        "la protección anterior aún no está confirmada por DAS; repite /stop en un momento")
            primera, resto = propias[0], propias[1:]
            share = share_de_replace(objetivo, max(int(primera.llenas), 0), self._share_es_abierta())
            acciones = self._absorber([Reemplazar(id_das=primera.id_das, token=primera.token, qty=share, stop=precio,
                                                  precio=limite, motivo="/stop: lo pide el humano (G1B-06)",
                                                  version=pos.version_stops, serie=stops.serie_stops(ticker))])
            acciones.append(Programar(stops.CLAVE_VERIFICAR_REPLACE, stops.VERIFICAR_REPLACE_EN_S,
                                      {"token": primera.token, "ticker": ticker, "qty_objetivo": objetivo}))
            for o in resto:
                acciones += self._cancelar_orden(o, "/stop: una sola protección (G1B-06)")
            return acciones, None
        orden = OrdenNueva(token=self._tokens.siguiente(), lado=Lado.COMPRA, ticker=ticker, ruta=self._ruta_stop(),
                           qty=objetivo, tipo=TipoOrden.STOP_LIMITE_PP, precio=limite, stop=precio, tif="DAY+",
                           proposito=Proposito.STOP_PROTECCION, nivel=precio, version=pos.version_stops)
        return self._absorber([EnviarOrden(orden)]), None

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
        """Tras `reconstruir`, los fills del diario ya están contados: sus `id_trade` y sus pares Execute/TRADE.

        DC-02: `reconstruir` deja con id NEGATIVO (sintético) el fill de un
        Execute cuyo %TRADE no llegó a anotarse. Ese fill cuenta solo como
        Execute y espera su %TRADE en `_fills_sin_id`: cuando DAS lo mande (en
        vivo o con GET TRADES) se reconoce como su eco y NO se suma otra vez.
        Los ids sintéticos nuevos siguen por debajo de los reconstruidos.
        """
        for lista in self._estado.fills.values():
            for fill in lista:
                clave = (fill.id_orden, int(fill.qty))
                if fill.id_trade is not None and fill.id_trade < 0:
                    self._n_execute[clave] = self._n_execute.get(clave, 0) + 1
                    self._fills_sin_id.setdefault(clave, deque()).append(fill)
                    self._id_sintetico = min(self._id_sintetico, int(fill.id_trade))
                    continue
                if fill.id_trade is not None and fill.id_trade > 0:
                    self._trades_vistos.add(fill.id_trade)
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


def _precio_texto(valor: Any) -> str:
    """Un precio medio para un aviso: como mucho 4 decimales y sin ceros de cola (3,4500 → «3.45»; 30 → «30»)."""
    if not isinstance(valor, Decimal) or not valor.is_finite():
        return str(valor)
    texto = format(valor.quantize(Decimal("0.0001")), "f")
    return texto.rstrip("0").rstrip(".") if "." in texto else texto


def _tiene_cache_referencia(referencia: Any) -> bool:
    """G1A-03: la referencia ofrece la caché de solo lectura (sin red) que el decisor debe usar."""
    return (referencia is not None and callable(getattr(referencia, "ficha_en_cache", None))
            and callable(getattr(referencia, "splits_en_cache", None)))


def _slret_elegido(respuestas: list[MsgSLRet]) -> MsgSLRet:
    """E2-05 / 2e.4 («se coge el más barato»): ETB (tipo 2 AlreadyShortable) manda; si no, el tipo 1 más barato con
    tamaño; sin ninguno, la primera respuesta (un fallo se anota igual)."""
    for r in respuestas:
        if r.tipo == 2 and "alreadyshortable" in str(r.notas).replace(" ", "").lower():
            return r
    validas = [r for r in respuestas if r.tipo == 1 and r.tamano > 0 and isinstance(r.precio, Decimal)
               and r.precio.is_finite() and r.precio >= 0]
    if validas:
        return min(validas, key=lambda r: (r.precio, -r.tamano))
    return respuestas[0]


def _es_precio(valor: Any) -> bool:
    return isinstance(valor, Decimal) and valor.is_finite() and valor > 0


def _libro_utilizable(cot: Optional[Cotizacion]) -> bool:
    return cot is not None and _es_precio(cot.bid) and _es_precio(cot.ask) and cot.ask >= cot.bid


def _qty_viva(o: Orden) -> int:
    """Acciones que la orden aún puede ejecutar: min(`lvqty`, qty − llenas) si DAS dio `lvqty` (Partial/Triggered); si no,
    qty − llenas (§8.7). D2a-07: el `Execute` sube `llenas` sin tocar un `lvqty` viejo del %ORDER anterior; el mínimo
    vale en los dos órdenes de llegada (la misma fórmula que `stops._qty_viva`)."""
    restante = max(int(o.qty) - int(o.llenas), 0)
    if o.estado in (EstadoOrden.PARTIAL, EstadoOrden.TRIGGERED) and o.lvqty > 0:
        return max(min(int(o.lvqty), restante), 0)
    return restante


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
