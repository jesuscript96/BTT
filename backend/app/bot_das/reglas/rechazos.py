"""Rechazos de DAS: catálogo de motivos, reintentos, pausa por ticker, control humano y reintento del stop.

QUÉ HACE. Todo lo que el bot decide cuando DAS dice que no a una orden:
  * `cargar_catalogo` / `validar_catalogo`: lee y valida `catalogo_rechazos.json`
    (texto de `Send_Rej` → tratamiento). Cada entrada lleva `clave`, `regex`,
    `accion` ∈ `ACCIONES_TRATAMIENTO`, `nivel` 2|3, `fuente`, `provisional`
    y, opcionalmente, `ejemplos` (textos reales o previstos que DEBEN casar
    con su entrada; se comprueban al cargar) y `descripcion`.
  * `clasificar`: primera entrada cuya regex casa con el texto literal de DAS,
    sin distinguir mayúsculas. Nunca lanza; lo que no casa es «desconocido».
  * `decidir`: R-B-07 entero para un `Send_Rej`. SIEMPRE anota el rechazo y
    avisa al grupo B con el texto literal, la orden y el estado del ticker
    (nivel 2 si la posición está cubierta, 3 si no); motivo conocido y
    reintentos disponibles → reintento con el tratamiento y un token NUEVO;
    si no, posición cubierta → ticker PAUSADO, sin cubrir → CONTROL HUMANO
    sin cerrar nada (EP-1). Un stop rechazado sigue R-C-03 (`reintento_stop`).
  * `reintento_stop`: R-C-03 (1)-(2), hasta `stops.reintentos` (5) con
    `stops.separacion_reintentos_s` (2 s) entre intentos.
  * `tras_cancel_o_replace_rej`: injerto A §8.7, CancelRej/ReplaceRej →
    aviso 2 + `GET ORDERS` + barrido inmediato.

POR QUÉ ESTÁ AQUÍ. Es lógica PURA (sin reloj, sin red, sin logging, sin
variables de entorno): el decisor le pasa la orden, la posición, las vivas,
la config, el generador de tokens, la cotización y la hora, y ejecuta EN
ORDEN las acciones que devuelve. La única excepción es `cargar_catalogo`, que
lee UN fichero al arrancar (§3.20 la pone aquí); la validación es pura
(`validar_catalogo`) y es la que se prueba con tablas.

LAS TRAMPAS.
  * «Cubierta» = `stops.descubiertas(...) == 0`: solo cubren emergencias o
    protecciones CONFIRMADAS por DAS (Accepted/Partial/Hold/Triggered), nunca
    una Sending. Una posición plana está cubierta (no hay nada al descubierto).
  * El bot NO cierra jamás por un rechazo (R-B-07 (3), EP-1): con acciones al
    descubierto avisa nivel 3 y CONTROL HUMANO; puede ser justo un cisne negro
    en el que no toca cerrar al ask. El punto (3) de R-C-03 («cerrar tras 5
    intentos») NO se implementa: prima R-B-07/EP-1.
  * Reintento = orden NUEVA con token NUEVO (`tokens()`), nunca el token
    rechazado: DAS lo vería repetido y el diario no distinguiría los dos
    intentos. El contador viaja en `Anotar("rechazo")["intentos_nuevo"]` y en
    los `datos` de cada `Programar`: el decisor lo copia a `Orden.intentos` de
    la orden nueva (y `primer_intento_en`), así el tercero no sale.
  * Un stop NO usa el tratamiento del catálogo ni los 2 reintentos de
    entrada: sigue R-C-03 (5 intentos, `Programar("stop_reintento")`, y el
    decisor vuelve a llamar a `stops.plan`, que es idempotente). `decidir` ya
    lo incluye: el decisor NO debe llamar además a `reintento_stop` (se
    duplicaría el stop, riesgo 11).
  * La pausa NUNCA rebaja un estado más grave ni pisa uno que es de otra
    regla: solo pasa NORMAL → PAUSADO/CONTROL_HUMANO y PAUSADO →
    CONTROL_HUMANO. Un ticker en BS, HALT, SIN_SIMBOLO o CONTROL_HUMANO
    conserva su estado (el aviso sale igual). En BS no se reintenta nada
    (R-G-03: nunca reponer); en PAUSADO o HALT no se reintenta lo que ABRE
    posición (venta en corto o propósito de entrada).
  * `Anotar("pausa")` lleva SIEMPRE `ticker` (sin él, el diario lo leería
    como pausa GLOBAL) y `estado` ∈ {"pausado", "control_humano"}: es el
    registro que el decisor aplica a `pos.estado` y el que `diario.reconstruir`
    reproduce tras un reinicio.
  * La clave del aviso lleva el token: el dedupe de 60 s de los avisos no
    puede callar un rechazo distinto, y sí el `Send_Rej` repetido del mismo.
  * Regex tolerantes y TODO el catálogo PROVISIONAL hasta el canario (DAS
    confirmó que no hay lista oficial de textos de rechazo). Una regex que
    casa con el texto vacío clasificaría como conocido cualquier rechazo: se
    rechaza al cargar y se ignora en `clasificar`.
  * Precios `Decimal` y acciones `int`: «subir un tick» usa el tick del precio
    (regla 612) y, si el precio cruza 1 $, recalcula la ruta del tramo nuevo.
"""
from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from app.bot_das.reglas.precios import redondear_arriba, tramo
from app.bot_das.reglas.precios import ruta as ruta_de
from app.bot_das.reglas.stops import PROPOSITOS_STOP, descubiertas
from app.bot_das.tipos import (
    ENTRADA_REINTENTOS_RECHAZO,
    STOP_REINTENTOS,
    STOP_VENTANA_MIN,
    Accion,
    Anotar,
    Avisar,
    Consultar,
    Cotizacion,
    EnviarOrden,
    EstadoTicker,
    Grupo,
    Lado,
    Nivel,
    Orden,
    OrdenNueva,
    PosicionTicker,
    Programar,
    Proposito,
    TipoOrden,
    en_tick,
    tick_de,
)

# ── catálogo ──────────────────────────────────────────────────────────────
RUTA_CATALOGO = Path(__file__).with_name("catalogo_rechazos.json")   # solo la ruta: importar no lee nada
ACCIONES_TRATAMIENTO = ("recalcular_bp", "recomprar_locate", "subir_tick_ssr", "reintentar", "ninguna")
NIVELES_CATALOGO = (int(Nivel.AVISO), int(Nivel.MAXIMO))
CLAVE_DESCONOCIDO = "desconocido"
CAMPOS_OBLIGATORIOS = ("clave", "regex", "accion", "nivel", "fuente")
CAMPOS_OPCIONALES = ("provisional", "ejemplos", "descripcion")
_RE_CLAVE = re.compile(r"^[a-z0-9_]+$")

# ── temporizadores y consultas que programa este módulo (§3.26 `_temporizador`) ──
CLAVE_REINTENTO_RECHAZO = "reintento_rechazo"   # R-B-07 (2) recalcular_bp: reenviar tras la respuesta de GET BP
CLAVE_LOCATE_RECOMPRAR = "locate_recomprar"     # R-B-07 caso locate → F9 (recomprar con su EV) y reenviar
CLAVE_STOP_REINTENTO = "stop_reintento"         # R-C-03 (1): el decisor vuelve a llamar a stops.plan
CLAVE_BARRIDO = "barrido"                       # injerto A §8.7: barrido inmediato tras CancelRej/ReplaceRej
COMANDO_BP = "GET BP"
COMANDO_ORDENES = "GET ORDERS"
ESPERA_RESPUESTA_BP_S = 1.0                     # PROVISIONAL: GET BP contesta en < 1 s en el simulador; se mide en canario
SEPARACION_REINTENTOS_STOP_S = 2.0              # R-C-03 «separación: por definir» → 2 s [PENDIENTE] (§3.20)

# ── decisiones que se anotan (campo `decision` de `Anotar("rechazo")`) ──
DECISION_REINTENTO = "reintento"
DECISION_STOP_REINTENTO = "stop_reintento"
DECISION_STOP_AGOTADO = "stop_agotado"
DECISION_PAUSA = "pausa"
DECISION_CONTROL_HUMANO = "control_humano"
DECISION_SIN_REINTENTO_BS = "sin_reintento_bs"

_PROPOSITOS_ENTRADA = (Proposito.ENTRADA_AGREGAR, Proposito.ENTRADA_CRUCE)
_PROPOSITOS_AGREGAR = (Proposito.ENTRADA_AGREGAR, Proposito.TP_AGREGAR, Proposito.HORA_AGREGAR,
                       Proposito.SALIDA_MOTOR_AGREGAR)
_ESTADOS_SIN_REINTENTO = (EstadoTicker.BS, EstadoTicker.CONTROL_HUMANO, EstadoTicker.SIN_SIMBOLO)
_ESTADOS_SIN_ABRIR = (EstadoTicker.PAUSADO, EstadoTicker.HALT)
_MOTIVO_MAX = 200


@dataclass(frozen=True)
class Tratamiento:
    """Resultado de `clasificar` (R-B-07): si el motivo está en el catálogo, cuál y qué tratamiento lleva.

    `nivel` (2|3) es el nivel MÍNIMO del aviso que da el catálogo (p. ej. un
    MaxLoss de la cuenta es 3 aunque la posición esté cubierta); `decidir` lo
    combina con el de la cobertura. Campo añadido a §3.20 con valor por
    defecto (la construcción de tres campos del documento sigue valiendo).
    ValueError si `accion` no es de `ACCIONES_TRATAMIENTO` o el nivel no es 2|3.
    """

    conocido: bool
    clave: str
    accion: str
    nivel: Nivel = Nivel.AVISO

    def __post_init__(self) -> None:
        if self.accion not in ACCIONES_TRATAMIENTO:
            raise ValueError(f"acción de tratamiento desconocida: {self.accion!r}")
        if isinstance(self.nivel, bool) or self.nivel not in NIVELES_CATALOGO:
            raise ValueError(f"nivel de tratamiento debe ser 2 o 3, no {self.nivel!r}")
        object.__setattr__(self, "nivel", Nivel(int(self.nivel)))


DESCONOCIDO = Tratamiento(conocido=False, clave=CLAVE_DESCONOCIDO, accion="ninguna", nivel=Nivel.AVISO)


# ── catálogo: carga y validación ──────────────────────────────────────────
def cargar_catalogo(ruta: Path | str) -> list[dict]:
    """R-B-07 «detección»: lee `catalogo_rechazos.json` (UTF-8) y lo valida con `validar_catalogo`.

    Único punto con I/O del módulo (se llama UNA vez al arrancar el ejecutor,
    no por mensaje). JSON mal formado o contenido inválido → ValueError con la
    ruta y el motivo; un fichero ausente o ilegible propaga su OSError (es un
    fallo de instalación: el ejecutor no debe arrancar con un catálogo
    inventado).
    """
    ruta = Path(ruta)
    texto = ruta.read_bytes()
    try:
        datos = json.loads(texto.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"catálogo de rechazos {ruta}: JSON inválido: {exc}") from exc
    try:
        return validar_catalogo(datos)
    except ValueError as exc:
        raise ValueError(f"catálogo de rechazos {ruta}: {exc}") from exc


def validar_catalogo(datos: Any) -> list[dict]:
    """Valida el contenido del catálogo (R-B-07) y devuelve copias normalizadas en el MISMO orden.

    Exige una lista no vacía de objetos con `clave` (minúsculas, dígitos y
    «_», única, distinta de «desconocido»), `regex` (compila con IGNORECASE y
    NO casa con el texto vacío), `accion` ∈ `ACCIONES_TRATAMIENTO`, `nivel`
    entero 2|3 (no bool) y `fuente` (texto no vacío); `provisional` (bool,
    por defecto True), `ejemplos` (lista de textos) y `descripcion` (texto)
    son opcionales y no se admite ninguna otra clave (una errata como
    «acion» se cazaría aquí y no en vivo). Cada ejemplo debe casar con SU
    regex y `clasificar` debe llevarlo a SU entrada (ninguna anterior la
    tapa). Cualquier incumplimiento → ValueError con el índice y la clave.
    """
    if not isinstance(datos, list) or not datos:
        raise ValueError("el catálogo debe ser una lista no vacía de entradas")
    resultado: list[dict] = []
    vistas: set[str] = set()
    for i, entrada in enumerate(datos):
        resultado.append(_validar_entrada(i, entrada, vistas))
    for i, entrada in enumerate(resultado):
        for ejemplo in entrada["ejemplos"]:
            obtenido = clasificar(ejemplo, resultado)
            if obtenido.clave != entrada["clave"]:
                raise ValueError(f"entrada {i} ({entrada['clave']}): su ejemplo {ejemplo!r} lo clasifica "
                                 f"antes {obtenido.clave!r}")
    return resultado


def clasificar(notas: Optional[str], catalogo: Iterable[Mapping]) -> Tratamiento:
    """R-B-07 «detección»: primera entrada del catálogo cuya regex casa con el texto literal de DAS (sin mayúsculas).

    Nunca lanza: notas vacías o None, un catálogo que no es iterable o una
    entrada mal formada (sin regex, regex que no compila o que casa con el
    texto vacío, acción o nivel inválidos) cuentan como «no casa» y el
    resultado es `DESCONOCIDO` (conocido=False, clave «desconocido», acción
    «ninguna»). El locate de un solo uso consumido NO es desconocido: casa
    con la entrada «sin_locate» → «recomprar_locate» (F9).
    """
    texto = notas if isinstance(notas, str) else ("" if notas is None else str(notas))
    if not texto.strip():
        return DESCONOCIDO
    try:
        entradas = list(catalogo)
    except TypeError:
        return DESCONOCIDO
    for entrada in entradas:
        tratamiento = _casa(entrada, texto)
        if tratamiento is not None:
            return tratamiento
    return DESCONOCIDO


# ── R-B-07: decidir qué hacer con un Send_Rej ─────────────────────────────
def decidir(orden: Orden, tratamiento: Tratamiento, pos: PosicionTicker, vivas: list[Orden], cfg: Any,
            tokens: Callable[[], int], cot: Optional[Cotizacion], hora_et: datetime,
            ahora: Optional[float] = None) -> list[Accion]:
    """R-B-07 (1)-(4), R-C-03 (1)-(2), EP-1: acciones ante un `Send_Rej` de `orden` (texto literal en `orden.notas`).

    Devuelve, EN ESTE ORDEN:
      1. `Anotar("rechazo", …)` SIEMPRE (R-B-07 (4)): texto literal, orden,
         hora, tratamiento, intentos, cobertura, decisión y, si hay reintento,
         `token_nuevo` e `intentos_nuevo`.
      2. `Anotar("pausa", {"ticker", "estado", "motivo", …})` si el ticker
         cambia de estado (ver trampas: solo NORMAL → PAUSADO/CONTROL_HUMANO
         y PAUSADO → CONTROL_HUMANO). El decisor pone `pos.estado =
         EstadoTicker(datos["estado"])` y `pos.motivo_estado = datos["motivo"]`.
      3. `Avisar(nivel, B, texto)` SIEMPRE (R-B-07 (1)), UNO solo: texto
         literal de DAS + la orden + el estado del ticker + la decisión. Nivel
         = máx(nivel del catálogo, 2 si la posición está cubierta y 3 si no);
         3 también al agotar los reintentos de un stop. Clave
         `rechazo:{ticker}:{token}`.
      4. El tratamiento, si lo hay.

    Stop (propósito de stop o STOPLMTP): R-C-03 con `reintento_stop` (salvo en
    BS): `Programar("stop_reintento")` mientras queden intentos; agotados →
    aviso 3 y pausa/control humano. Motivo desconocido → además pausa (si
    está cubierta) o control humano (si no), y los reintentos del stop siguen
    («los stops siguen», R-B-07 (3)).

    Resto: motivo conocido, acción ≠ «ninguna», `orden.intentos <
    cfg.entrada["reintentos_rechazo_conocido"]` (2) y el estado del ticker lo
    permite → reintento con token NUEVO:
      * reintentar → `EnviarOrden` idéntica (qty pendiente = qty − llenas);
      * subir_tick_ssr → `EnviarOrden` de venta a máx(precio, bid) + 1 tick
        (solo ventas límite; ruta recalculada si cambia el tramo de 1 $);
      * recalcular_bp → `Consultar("GET BP")` + `Programar("reintento_rechazo",
        1 s)`: el decisor redimensiona con el BP leído y envía con `token_nuevo`;
      * recomprar_locate → `Programar("locate_recomprar", 0)` (F9; solo ventas
        en corto): el decisor recompra con su EV y reenvía con `token_nuevo`.
    Si no → posición cubierta (`descubiertas() == 0`): PAUSADO + aviso 2;
    sin cubrir: CONTROL_HUMANO + aviso 3 y NINGUNA orden (EP-1).

    `ahora` (monotónico) solo lo usa el stop para medir la ventana de R-C-03;
    sin él vale `orden.ultima_act`. ValueError si la orden y la posición son
    de tickers distintos o el ticker está vacío (una pausa sin ticker sería
    GLOBAL), o si `cfg` no trae los bloques `entrada` y `stops`.
    """
    ticker = orden.ticker
    if not isinstance(ticker, str) or not ticker.strip():
        raise ValueError("la orden rechazada no tiene ticker: una pausa sin ticker sería global")
    if pos.ticker != ticker:
        raise ValueError(f"orden de {ticker!r} con la posición de {pos.ticker!r}")
    if not isinstance(tratamiento, Tratamiento):
        raise TypeError(f"tratamiento debe ser un Tratamiento, no {type(tratamiento).__name__}")
    entrada = _bloque(cfg, "entrada")
    cfg_stops = _bloque(cfg, "stops")
    max_reintentos = _entero(entrada, "reintentos_rechazo_conocido", ENTRADA_REINTENTOS_RECHAZO)
    n_descubiertas = descubiertas(pos, vivas, cfg_stops)
    cubierta = n_descubiertas == 0
    nivel = max(tratamiento.nivel, Nivel.AVISO if cubierta else Nivel.MAXIMO)
    estado_persistente = EstadoTicker.PAUSADO if cubierta else EstadoTicker.CONTROL_HUMANO

    tratamiento_acciones: list[Accion] = []
    estado_nuevo: Optional[EstadoTicker] = None
    token_nuevo: Optional[int] = None
    intentos_nuevo: Optional[int] = None
    partes: list[str] = []

    if _es_stop(orden):
        programa = None
        if pos.estado is not EstadoTicker.BS:
            programa = reintento_stop(orden, cfg_stops, orden.ultima_act if ahora is None else ahora)
        if programa is not None:
            decision = DECISION_STOP_REINTENTO
            intentos_nuevo = int(programa.datos["intento"])
            tratamiento_acciones.append(programa)
            partes.append(f"stop: reintento {intentos_nuevo}/{programa.datos['reintentos']} en "
                          f"{_segundos_texto(programa.en_s)} s (R-C-03)")
            if not tratamiento.conocido:
                estado_nuevo = estado_persistente
        elif pos.estado is EstadoTicker.BS:
            decision = DECISION_SIN_REINTENTO_BS
            partes.append("cisne negro activo: el stop NO se repone (R-G-03)")
        else:
            decision = DECISION_STOP_AGOTADO
            nivel = Nivel.MAXIMO
            estado_nuevo = estado_persistente
            partes.append(f"STOP SIN PONER tras {orden.intentos} reintentos (R-C-03); el bot NO cierra (EP-1)")
    else:
        reintento = None
        if (tratamiento.conocido and tratamiento.accion != "ninguna" and orden.intentos < max_reintentos
                and _estado_permite_reintento(pos, orden)):
            reintento = _reintento(orden, tratamiento, cot, cfg, tokens, hora_et, orden.intentos + 1)
        if reintento is not None:
            decision = DECISION_REINTENTO
            tratamiento_acciones, token_nuevo = reintento
            intentos_nuevo = orden.intentos + 1
            partes.append(f"reintento {intentos_nuevo}/{max_reintentos} ({tratamiento.accion}) con token "
                          f"{token_nuevo}")
        else:
            decision = DECISION_PAUSA if cubierta else DECISION_CONTROL_HUMANO
            estado_nuevo = estado_persistente

    if estado_nuevo is not None:
        partes.append(_texto_estado(estado_nuevo, ticker, n_descubiertas))
    estado_aplicado = estado_nuevo if estado_nuevo is not None and _sube(pos.estado, estado_nuevo) else None
    if estado_nuevo is not None and estado_aplicado is None and pos.estado is not estado_nuevo:
        partes.append(f"(el ticker sigue en «{pos.estado.value}»: ese estado manda)")

    notas = orden.notas or ""
    acciones: list[Accion] = [Anotar("rechazo", {
        "ticker": ticker,
        "token": orden.token,
        "id_das": orden.id_das,
        "notas": notas,
        "tratamiento": tratamiento.clave,
        "accion": tratamiento.accion,
        "conocido": tratamiento.conocido,
        "intentos": orden.intentos,
        "intentos_nuevo": intentos_nuevo,
        "token_nuevo": token_nuevo,
        "primer_intento_en": _primer_intento(orden),
        "cubierta": cubierta,
        "descubiertas": n_descubiertas,
        "decision": decision,
        "estado_ticker": pos.estado.value,
        "estado_nuevo": estado_aplicado.value if estado_aplicado is not None else None,
        "orden": _orden_dict(orden),
        "cotizacion": _cot_dict(cot),
        "hora": hora_et.isoformat(),
        "regla": "R-B-07",
    })]
    if estado_aplicado is not None:
        acciones.append(Anotar("pausa", {
            "ticker": ticker,
            "estado": estado_aplicado.value,
            "motivo": f"rechazo {tratamiento.clave}: {notas}"[:_MOTIVO_MAX],
            "notas": notas,
            "tratamiento": tratamiento.clave,
            "intentos": orden.intentos,
            "cubierta": cubierta,
            "accion": decision,
            "token": orden.token,
            "regla": "R-B-07 (3)" if not _es_stop(orden) else "R-B-07 (3) / R-C-03 (2)",
        }))
    acciones.append(Avisar(nivel, Grupo.B, _texto_aviso(orden, tratamiento, pos, cubierta, n_descubiertas, partes),
                           clave=f"rechazo:{ticker}:{orden.token}"))
    acciones.extend(tratamiento_acciones)
    return acciones


# ── R-C-03: reintento del stop ────────────────────────────────────────────
def reintento_stop(orden: Orden, cfg_stops: Mapping, ahora: float) -> Optional[Programar]:
    """R-C-03 (1)-(2): el siguiente reintento de un stop rechazado o cancelado, o None si ya no quedan.

    Hay reintento mientras `orden.intentos < cfg_stops["reintentos"]` (5 por
    defecto, `STOP_REINTENTOS`): `Programar("stop_reintento",
    cfg_stops["separacion_reintentos_s"] (2 s [PENDIENTE]), datos)` con
    `ticker`, `token_rechazado`, `intento` (= intentos + 1), `reintentos`,
    `proposito`, `lote_id`, `nivel`, `primer_intento_en`,
    `segundos_desde_primero` y `fuera_de_ventana` (> `ventana_min` minutos: se
    calcula y se ANOTA para el informe; no cierra nada). Al agotarlos → None y
    el llamador avisa nivel 3 (`decidir` ya lo hace). El punto (3) «cerrar
    tras 5 intentos» NO se implementa: prima R-B-07/EP-1 (control humano).

    El decisor, al vencer el temporizador, vuelve a llamar a `stops.plan`
    (idempotente: pone solo lo que falta) o a `stops.stop_proteccion` si era
    una protección sin lote, y copia `intento` a `Orden.intentos` de la orden
    nueva. TypeError si `cfg_stops` no es un Mapping; ValueError con
    reintentos/separación/ventana negativos o no numéricos o `ahora` no finito.
    """
    if not isinstance(cfg_stops, Mapping):
        raise TypeError(f"cfg_stops debe ser el bloque «stops» de la config (dict), no {type(cfg_stops).__name__}")
    if isinstance(ahora, bool) or not isinstance(ahora, (int, float)) or not math.isfinite(ahora):
        raise ValueError(f"ahora debe ser el reloj monotónico (float finito), no {ahora!r}")
    maximo = _entero(cfg_stops, "reintentos", STOP_REINTENTOS)
    separacion = _segundos(cfg_stops, "separacion_reintentos_s", SEPARACION_REINTENTOS_STOP_S)
    ventana_min = _segundos(cfg_stops, "ventana_min", float(STOP_VENTANA_MIN))
    if orden.intentos >= maximo:
        return None
    primero = _primer_intento(orden)
    if primero is None:
        primero = float(ahora)
    transcurrido = max(float(ahora) - primero, 0.0)
    return Programar(CLAVE_STOP_REINTENTO, separacion, {
        "ticker": orden.ticker,
        "token_rechazado": orden.token,
        "intento": orden.intentos + 1,
        "reintentos": maximo,
        "proposito": orden.proposito.value,
        "lote_id": orden.lote_id,
        "nivel": _texto_decimal(orden.nivel),
        "primer_intento_en": primero,
        "segundos_desde_primero": transcurrido,
        "fuera_de_ventana": transcurrido > ventana_min * 60.0,
        "regla": "R-C-03 (1)",
    })


# ── injerto A §8.7: CancelRej / ReplaceRej ────────────────────────────────
def tras_cancel_o_replace_rej(orden: Orden, accion: Optional[str] = None) -> list[Accion]:
    """Injerto A §8.7: DAS no aceptó cancelar o reemplazar `orden` → aviso 2, `GET ORDERS` y barrido inmediato.

    Devuelve `[Avisar(2, B, texto literal de DAS + la orden), Consultar("GET
    ORDERS"), Programar("barrido", 0, {…})]`. No se supone nada sobre el
    estado de la orden (puede haberse llenado entre medias): lo dirá el
    barrido. `accion` («CancelRej» / «ReplaceRej», opcional) solo va al texto.
    """
    que = accion.strip() if isinstance(accion, str) and accion.strip() else "CancelRej/ReplaceRej"
    notas = orden.notas or ""
    texto = (f"[{que}] {orden.ticker}: DAS no aceptó cancelar/reemplazar la orden.\n"
             f"DAS dice: «{notas or '(sin texto)'}»\n"
             f"Orden: {_orden_texto(orden)}\n"
             f"Barrido inmediato (GET ORDERS): no se supone nada hasta ver su estado real.")
    return [
        Avisar(Nivel.AVISO, Grupo.B, texto, clave=f"cancel_replace_rej:{orden.ticker}:{orden.token}"),
        Consultar(COMANDO_ORDENES),
        Programar(CLAVE_BARRIDO, 0.0, {"ticker": orden.ticker, "token": orden.token, "id_das": orden.id_das,
                                       "motivo": que, "regla": "injerto A §8.7"}),
    ]


# ── ayudantes privados (todos puros) ──────────────────────────────────────
def _validar_entrada(i: int, entrada: Any, vistas: set[str]) -> dict:
    """Una entrada del catálogo validada y normalizada (ver `validar_catalogo`)."""
    if not isinstance(entrada, Mapping):
        raise ValueError(f"entrada {i}: debe ser un objeto, no {type(entrada).__name__}")
    faltan = [c for c in CAMPOS_OBLIGATORIOS if c not in entrada]
    if faltan:
        raise ValueError(f"entrada {i}: faltan {faltan}")
    sobran = sorted(set(entrada) - set(CAMPOS_OBLIGATORIOS) - set(CAMPOS_OPCIONALES))
    if sobran:
        raise ValueError(f"entrada {i}: claves no admitidas {sobran}")
    clave = entrada["clave"]
    if not isinstance(clave, str) or not _RE_CLAVE.match(clave):
        raise ValueError(f"entrada {i}: clave inválida {clave!r} (minúsculas, dígitos y «_»)")
    if clave == CLAVE_DESCONOCIDO or clave in vistas:
        raise ValueError(f"entrada {i}: clave repetida o reservada {clave!r}")
    vistas.add(clave)
    regex = entrada["regex"]
    if not isinstance(regex, str) or not regex.strip():
        raise ValueError(f"entrada {i} ({clave}): regex vacía")
    try:
        patron = re.compile(regex, re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"entrada {i} ({clave}): la regex no compila: {exc}") from exc
    if patron.search(""):
        raise ValueError(f"entrada {i} ({clave}): la regex casa con el texto vacío (lo clasificaría todo)")
    if entrada["accion"] not in ACCIONES_TRATAMIENTO:
        raise ValueError(f"entrada {i} ({clave}): acción {entrada['accion']!r} no está en {ACCIONES_TRATAMIENTO}")
    nivel = entrada["nivel"]
    if isinstance(nivel, bool) or not isinstance(nivel, int) or nivel not in NIVELES_CATALOGO:
        raise ValueError(f"entrada {i} ({clave}): nivel debe ser 2 o 3, no {nivel!r}")
    fuente = entrada["fuente"]
    if not isinstance(fuente, str) or not fuente.strip():
        raise ValueError(f"entrada {i} ({clave}): falta la fuente")
    provisional = entrada.get("provisional", True)
    if not isinstance(provisional, bool):
        raise ValueError(f"entrada {i} ({clave}): provisional debe ser true/false")
    ejemplos = entrada.get("ejemplos", [])
    if not isinstance(ejemplos, list) or any(not isinstance(e, str) or not e.strip() for e in ejemplos):
        raise ValueError(f"entrada {i} ({clave}): ejemplos debe ser una lista de textos no vacíos")
    for ejemplo in ejemplos:
        if not patron.search(ejemplo):
            raise ValueError(f"entrada {i} ({clave}): su regex no casa con su ejemplo {ejemplo!r}")
    descripcion = entrada.get("descripcion", "")
    if not isinstance(descripcion, str):
        raise ValueError(f"entrada {i} ({clave}): descripcion debe ser texto")
    return {"clave": clave, "regex": regex, "accion": entrada["accion"], "nivel": nivel, "fuente": fuente,
            "provisional": provisional, "ejemplos": list(ejemplos), "descripcion": descripcion}


def _casa(entrada: Any, texto: str) -> Optional[Tratamiento]:
    """El tratamiento de `entrada` si su regex casa con `texto`; None si no casa o la entrada no es válida."""
    if not isinstance(entrada, Mapping):
        return None
    regex = entrada.get("regex")
    clave = entrada.get("clave")
    if not isinstance(regex, str) or not regex.strip() or not isinstance(clave, str) or not clave.strip():
        return None
    try:
        patron = re.compile(regex, re.IGNORECASE)
    except re.error:
        return None
    if patron.search("") or not patron.search(texto):
        return None
    try:
        return Tratamiento(conocido=True, clave=clave, accion=entrada.get("accion"), nivel=entrada.get("nivel"))
    except ValueError:
        return None


def _bloque(cfg: Any, nombre: str) -> Mapping:
    """`cfg.entrada` / `cfg.stops` / `cfg.rutas` de una `Config`, o `cfg[nombre]` si llega un dict. ValueError si falta."""
    valor = cfg.get(nombre) if isinstance(cfg, Mapping) else getattr(cfg, nombre, None)
    if not isinstance(valor, Mapping):
        raise ValueError(f"el bloque {nombre!r} de la config falta o no es un dict")
    return valor


def _entero(bloque: Mapping, clave: str, defecto: int) -> int:
    """Entero ≥ 0 de la config (JSON puede traer 2 o 2.0); ausente o null → `defecto`. ValueError si no lo es."""
    valor = bloque.get(clave)
    if valor is None:
        return defecto
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor) \
            or valor != int(valor) or valor < 0:
        raise ValueError(f"{clave} debe ser un entero ≥ 0, no {valor!r}")
    return int(valor)


def _segundos(bloque: Mapping, clave: str, defecto: float) -> float:
    """Número finito ≥ 0 de la config; ausente o null → `defecto`. ValueError si no lo es."""
    valor = bloque.get(clave)
    if valor is None:
        return defecto
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor) or valor < 0:
        raise ValueError(f"{clave} debe ser un número ≥ 0, no {valor!r}")
    return float(valor)


def _es_stop(orden: Orden) -> bool:
    """Una orden de stop (R-C-03): propósito de stop o STOPLMTP (una DESCONOCIDA con tipo stop también lo es)."""
    return orden.proposito in PROPOSITOS_STOP or orden.tipo is TipoOrden.STOP_LIMITE_PP


def _abre_posicion(orden: Orden) -> bool:
    """Venta en corto o propósito de entrada: lo que la pausa prohíbe (R-B-07 (3): entradas y pirámides)."""
    return orden.lado is Lado.CORTO or orden.proposito in _PROPOSITOS_ENTRADA


def _estado_permite_reintento(pos: PosicionTicker, orden: Orden) -> bool:
    """BS, control humano o sin símbolo: nada; pausado o halt: solo lo que no abre posición (salidas, exceso)."""
    if pos.estado in _ESTADOS_SIN_REINTENTO:
        return False
    return not (pos.estado in _ESTADOS_SIN_ABRIR and _abre_posicion(orden))


def _sube(actual: EstadoTicker, nuevo: EstadoTicker) -> bool:
    """Solo NORMAL → PAUSADO/CONTROL_HUMANO y PAUSADO → CONTROL_HUMANO: nunca se rebaja ni se pisa otro estado."""
    if actual is EstadoTicker.NORMAL:
        return nuevo in (EstadoTicker.PAUSADO, EstadoTicker.CONTROL_HUMANO)
    return actual is EstadoTicker.PAUSADO and nuevo is EstadoTicker.CONTROL_HUMANO


def _reintento(orden: Orden, tratamiento: Tratamiento, cot: Optional[Cotizacion], cfg: Any,
               tokens: Callable[[], int], hora_et: datetime, intentos_nuevo: int
               ) -> Optional[tuple[list[Accion], int]]:
    """Las acciones del tratamiento y el token nuevo, o None si el tratamiento no se puede aplicar a esta orden.

    El token se pide SOLO cuando el reintento es posible (un token no se
    gasta en balde, y nunca se reutiliza el rechazado).
    """
    qty = orden.qty - orden.llenas
    if type(qty) is not int or qty <= 0:
        return None
    accion = tratamiento.accion
    if accion in ("reintentar", "subir_tick_ssr"):
        precio = orden.precio
        ruta = orden.ruta
        if accion == "subir_tick_ssr":
            precio = _precio_ssr(orden, cot)
            if precio is None:
                return None
            ruta = _ruta_reenvio(orden, precio, cfg, hora_et)
        if not _orden_reenviable(orden, precio):
            return None
        token = tokens()
        nueva = OrdenNueva(token=token, lado=orden.lado, ticker=orden.ticker, ruta=ruta, qty=qty, tipo=orden.tipo,
                           precio=precio if orden.tipo is not TipoOrden.MERCADO else None, stop=None, tif="DAY+",
                           post_only=_post_only(orden, cfg), proposito=orden.proposito, lote_id=orden.lote_id,
                           nivel=orden.nivel, version=orden.version)
        return [EnviarOrden(nueva, serie=None)], token
    if accion == "recomprar_locate" and orden.lado is not Lado.CORTO:
        return None
    if accion not in ("recalcular_bp", "recomprar_locate"):
        return None
    token = tokens()
    datos = {
        "ticker": orden.ticker,
        "token_original": orden.token,
        "token_nuevo": token,
        "intentos": intentos_nuevo,
        "primer_intento_en": _primer_intento(orden),
        "tratamiento": tratamiento.clave,
        "accion": accion,
        "proposito": orden.proposito.value,
        "lote_id": orden.lote_id,
        "lado": orden.lado.value,
        "qty": qty,
        "regla": "R-B-07 (2)",
    }
    if accion == "recalcular_bp":
        return [Consultar(COMANDO_BP), Programar(CLAVE_REINTENTO_RECHAZO, ESPERA_RESPUESTA_BP_S, datos)], token
    return [Programar(CLAVE_LOCATE_RECOMPRAR, 0.0, datos)], token


def _precio_ssr(orden: Orden, cot: Optional[Cotizacion]) -> Optional[Decimal]:
    """SSR (KB tabla C): venta límite a máx(precio, bid) + 1 tick del precio base; None si no es una venta límite con precio."""
    if orden.lado not in (Lado.CORTO, Lado.VENTA) or orden.tipo is not TipoOrden.LIMITE:
        return None
    if not _es_precio(orden.precio):
        return None
    base = orden.precio
    bid = cot.bid if cot is not None else None
    if _es_precio(bid) and bid > base:
        base = bid
    return redondear_arriba(base + tick_de(base))


def _ruta_reenvio(orden: Orden, precio: Decimal, cfg: Any, hora_et: datetime) -> str:
    """La ruta de la orden original; si el precio nuevo cambia de tramo (1 $), la del tramo nuevo según la tabla de rutas."""
    if _es_precio(orden.precio) and tramo(orden.precio) == tramo(precio):
        return orden.ruta
    accion_ruta = "agregar" if orden.proposito in _PROPOSITOS_AGREGAR else "cruzar"
    try:
        return ruta_de(_bloque(cfg, "rutas"), accion_ruta, precio, hora_et)
    except ValueError:
        return orden.ruta   # sin tabla de rutas utilizable se conserva la que DAS ya conocía para esta orden


def _post_only(orden: Orden, cfg: Any) -> bool:
    """`Orden` no guarda PostOnly: las límite de agregar lo llevan (entrada según `entrada.post_only`, salidas siempre)."""
    if orden.tipo is not TipoOrden.LIMITE or orden.proposito not in _PROPOSITOS_AGREGAR:
        return False
    if orden.proposito is Proposito.ENTRADA_AGREGAR:
        return bool(_bloque(cfg, "entrada").get("post_only", True))
    return True


def _orden_reenviable(orden: Orden, precio: Optional[Decimal]) -> bool:
    """Lo que `OrdenNueva.__post_init__` exigiría, comprobado ANTES de gastar un token (límite al tick; MKT sin precio)."""
    if orden.tipo is TipoOrden.LIMITE:
        return _es_precio(precio) and en_tick(precio)
    return orden.tipo is TipoOrden.MERCADO


def _es_precio(x: Any) -> bool:
    return isinstance(x, Decimal) and x.is_finite() and x > 0


def _primer_intento(orden: Orden) -> Optional[float]:
    """Monotónico del primer intento de la cadena: `primer_intento_en`, o `enviada_en` si aún no se fijó; None si ninguno."""
    for valor in (orden.primer_intento_en, orden.enviada_en):
        if isinstance(valor, (int, float)) and not isinstance(valor, bool) and math.isfinite(valor) and valor > 0:
            return float(valor)
    return None


def _texto_decimal(x: Any) -> Optional[str]:
    return str(x) if isinstance(x, Decimal) else None


def _segundos_texto(s: float) -> str:
    return f"{s:g}"


def _orden_dict(orden: Orden) -> dict:
    """La orden rechazada para el diario (§8: Decimal como cadena)."""
    return {"lado": orden.lado.value, "tipo": orden.tipo.value, "qty": orden.qty, "llenas": orden.llenas,
            "precio": _texto_decimal(orden.precio), "stop": _texto_decimal(orden.stop), "ruta": orden.ruta,
            "proposito": orden.proposito.value, "lote_id": orden.lote_id, "nivel": _texto_decimal(orden.nivel),
            "origen": int(orden.origen), "version": orden.version}


def _cot_dict(cot: Optional[Cotizacion]) -> Optional[dict]:
    if cot is None:
        return None
    return {"bid": _texto_decimal(cot.bid), "ask": _texto_decimal(cot.ask), "last": _texto_decimal(cot.last)}


def _orden_texto(orden: Orden) -> str:
    partes = [orden.lado.value, str(orden.qty), orden.ticker, orden.tipo.value]
    if orden.stop is not None:
        partes.append(f"disparo {orden.stop}")
    if orden.precio is not None:
        partes.append(f"límite {orden.precio}")
    partes.append(f"ruta {orden.ruta}")
    partes.append(f"({orden.proposito.value}, token {orden.token}"
                  + (f", id {orden.id_das}" if orden.id_das is not None else "") + ")")
    return " ".join(partes)


def _texto_estado(estado: EstadoTicker, ticker: str, n_descubiertas: int) -> str:
    if estado is EstadoTicker.CONTROL_HUMANO:
        return (f"CONTROL HUMANO: {n_descubiertas} acciones SIN STOP aceptado; el bot NO cierra (EP-1). "
                f"Arreglarlo en DAS y /reanudar {ticker}")
    return f"TICKER PAUSADO: sin órdenes nuevas en {ticker} (stops y salidas siguen) hasta /reanudar {ticker}"


def _texto_aviso(orden: Orden, tratamiento: Tratamiento, pos: PosicionTicker, cubierta: bool,
                 n_descubiertas: int, partes: list[str]) -> str:
    """R-B-07 (1): texto literal de DAS, la orden que se intentó, el estado del ticker y lo que hace el bot."""
    notas = orden.notas or ""
    neta_das = "?" if pos.neta_das is None else str(pos.neta_das)
    cobertura = "cubierta" if cubierta else f"{n_descubiertas} acciones SIN STOP aceptado"
    motivo = tratamiento.clave if tratamiento.conocido else "DESCONOCIDO (no está en el catálogo)"
    return (f"RECHAZO DAS {orden.ticker}\n"
            f"DAS dice: «{notas or '(sin texto)'}»\n"
            f"Orden: {_orden_texto(orden)} · intentos previos {orden.intentos}\n"
            f"Ticker: {pos.estado.value}, neta {pos.neta} (DAS {neta_das}), {cobertura}\n"
            f"Motivo: {motivo} → " + "; ".join(partes))
