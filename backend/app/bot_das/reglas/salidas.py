"""Salidas: clasificación de exit_reason, hora/EOD, TP parcial, cerrar todo, prioridad y reentradas.

QUÉ HACE. Las reglas del área D del libro que deciden CÓMO sale el bot de una
posición corta (y, por simetría, de una larga):
  * `LITERALES_EXIT_REASON` / `clasificar`: TODOS los motivos de salida que
    escribe el motor (`portfolio_sim.py` l.745-2265, más el «?» de
    `bot_alerts_engine.py` l.1142) → `ClaseSalida`; lo desconocido es MOTOR.
  * `tratamiento` / `avisos_de_tratamiento`: qué hace el ejecutor con cada
    clase (TP → F4; hora y EOD → solo se anotan, manda el reloj; SL del motor
    con la posición abierta → divergencia sin perseguir; Daily Limit →
    ignorar + aviso; Signal/Trailing/Time Limit/Escalera/? → como TP).
  * `horas_de_salida`, `ultimo_eod`, `temporizadores_lote`: la hora de salida
    y el EOD de cada estrategia en ET y los tres temporizadores por lote de
    R-D-08/R-D-02 (t − 60 s agregar, t al ask, t + 30 s comprobar).
  * `orden_hora_agregar`, `orden_al_ask`, `perseguir_ask`: las órdenes de la
    salida por hora (punto medio PostOnly, luego al ask sin tope y como mucho 3
    REPLACE de precio, corrección 11).
  * `tp_parcial`, `tp_al_vencer`: R-D-03 v2 (agregar 60 s en el punto medio;
    luego al ask con techo 3 % sobre el último DE ESE MOMENTO, o limbo).
  * `prioridad`: R-D-07 (salidas/TP → pirámides reduce/lot_* → pirámides add
    → entradas).
  * `cerrar_todo`, `orden_cierre_posicion`, `comprobar_eod`: R-D-06 y R-D-02.
  * `puede_reentrar`: R-D-04 con el mismo if/elif que el backtester, más los
    vetos de R-G-03 / R-F-03.
  * `al_desactivar`: R-E-03 (esperar fin de día | cerrar y reiniciar).

POR QUÉ ESTÁ AQUÍ. Es lógica PURA: sin reloj, sin I/O, sin logging, sin
variables de entorno. Recibe la hora ET (`hora_et` / `ahora_et`) y los tokens
(`Callable[[], int]` o un `int` ya reservado) como parámetros y devuelve
órdenes o acciones de `tipos` que el decisor (lote G) ejecuta en orden. Así
se prueba con tablas de casos sin DAS y el decisor y el cisne negro (lote E)
comparten la misma aritmética. NINGUNA función de este módulo muta la
posición, el lote ni las órdenes: el decisor aplica los cambios.

LAS TRAMPAS.
  * Riesgo 24: una salida del motor sin tratar deja la posición huérfana. Un
    test extrae con regex TODOS los literales `exit_reason` del fichero real
    `portfolio_sim.py` (incluida la f-string `f"Lot TP ({n}/{m})"`, ajuste (f)
    del orquestador: se clasifica por el PREFIJO «Lot TP») y exige que estén
    aquí. `clasificar` NUNCA lanza: None, «», un tipo raro o un literal nuevo
    → MOTOR, y `avisos_de_tratamiento` anota «salida_desconocida».
  * La hora de salida NO se negocia (R-D-08): al llegar `t` lo que quede va
    AL ASK sin tope. Pero perseguir el ask cancelando y reenviando consume la
    cuota de 100 CANCEL/min que comparten los STOPS (manual L2004-2006): la
    persecución es por `Reemplazar` de precio y como mucho 3 veces
    (corrección 11); después manda `eod_comprobar` (+30 s → control humano).
  * El techo de R-D-03 es sobre el `last` del MOMENTO del cruce, no sobre el
    de hace un minuto; si el ask ya está por encima, NO se envía nada (limbo,
    aviso 2): nunca una compra sin techo con el libro posiblemente vacío.
  * El techo de R-D-06 («cerrar todo») es otro: 5 % sobre el ASK (o bajo el
    BID) del momento, es decir, un límite agresivo que barre el libro hasta
    ese precio. Por eso `cerrar_todo` usa `orden_cierre_posicion` y no
    `orden_al_ask` (que limita a min(ask, last·(1 + techo))). Y cierra también
    las posiciones MANUALES, que no tienen lote: la cantidad sale de
    `neta_das` (lo que dice DAS de la cuenta) cuando se conoce.
  * Sobrecompra (riesgo 6): si un lote ya tiene una orden de cierre TOTAL en
    curso (hora, cierre humano o reinicio), un TP o una salida del motor NO
    añade otra orden (`tratamiento` → «anotar»): dos órdenes de compra sobre
    las mismas acciones dejan la cuenta LARGA.
  * `max_reentries = −1` NO es «ninguna» ni «ilimitadas»: «sin tope numérico,
    manda accept_reentries» (memoria «max_reentries = −1»). Con N ≥ 0 el
    backtester IGNORA accept_reentries (`portfolio_sim.py` l.2314-2318) y
    aquí se hace igual por paridad (R-D-04). Un lote CANCELADO sin fills no
    cuenta como entrada previa (en el backtest no hubo trade).
  * Los temporizadores de un lote llevan el id del lote en la CLAVE
    (`"hora_ask:<lote_id>"`): un `Programar` con una clave ya existente
    sustituye al anterior (§6.1), y con dos lotes en el mismo ticker una clave
    compartida borraría la salida del primero. El decisor despacha por el
    prefijo anterior a «:» (como `locate_inquire:X:S`); el `lote_id` va
    además en `datos`.
  * Toda cantidad es `int` puro y todo precio `Decimal`: los porcentajes de la
    config (float del JSON) y los precios de la cotización pasan UNA vez por
    `precios.de_float`; ningún resultado es float.
  * Con el libro BLOQUEADO (bid == ask) el punto medio de una compra PostOnly
    tocaría el ask y DAS la rechazaría; se deja un tick por debajo del ask
    (por encima del bid en las ventas) para que siga agregando.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Callable, Iterable, Optional, Union

from app.bot_das.reglas.precios import (
    con_techo,
    de_float,
    punto_medio_abajo,
    punto_medio_arriba,
    redondear_abajo,
    redondear_arriba,
)
from app.bot_das.reglas.precios import ruta as ruta_de
from app.bot_das.reloj import ET
from app.bot_das.tipos import (
    CERRAR_TODO_REINTENTOS,
    CERRAR_TODO_TECHO_PCT,
    EOD_COMPROBAR_DESPUES_S,
    PERSEGUIR_ASK_MAX,
    SALIDA_ANTICIPO_S,
    TP_TECHO_ASK_PCT,
    Accion,
    Anotar,
    Avisar,
    CancelarTicker,
    ClaseSalida,
    Consultar,
    Cotizacion,
    EnviarOrden,
    EstadoLote,
    EstadoOrden,
    EstadoTicker,
    EstrategiaConfig,
    Grupo,
    Lado,
    Lote,
    Nivel,
    Orden,
    OrdenNueva,
    PosicionTicker,
    Programar,
    Proposito,
    Reemplazar,
    Senal,
    TipoOrden,
    tick_de,
)

# ── literales de exit_reason (riesgo 24; corrección 5 del juez; ajuste (f)) ──
LITERALES_EXIT_REASON: dict[str, ClaseSalida] = {
    "TP": ClaseSalida.TP,
    "Partial TP": ClaseSalida.TP,
    "Lot TP": ClaseSalida.TP,                    # PREFIJO de f"Lot TP ({n}/{m})" (portfolio_sim.py l.1607, ajuste (f))
    "Partial TP (Hour)": ClaseSalida.HORA,
    "Partial TP (EOD)": ClaseSalida.EOD,
    "Partial TP (Time)": ClaseSalida.EOD,
    "EOD": ClaseSalida.EOD,
    "SL": ClaseSalida.STOP,
    "Pyramid Lot Stop": ClaseSalida.STOP_LOTE,
    "Pyramid Reduce": ClaseSalida.REDUCE,
    "Escalera": ClaseSalida.MOTOR,
    "Signal": ClaseSalida.MOTOR,
    "Trailing": ClaseSalida.MOTOR,
    "Time Limit": ClaseSalida.MOTOR,
    "?": ClaseSalida.MOTOR,                      # bot_alerts_engine.py l.1142: motivo ausente
    "Halt": ClaseSalida.HALT,
    "Halt (atrapado)": ClaseSalida.HALT,
    "BS": ClaseSalida.BS,
    "BS Manual": ClaseSalida.BS,
    "Daily Limit": ClaseSalida.DAILY_LIMIT,
}
# Literales que el motor escribe como f-string: se clasifican por prefijo (seguido de espacio o «(»).
PREFIJOS_EXIT_REASON: tuple[str, ...] = ("Lot TP",)

# ── códigos de tratamiento (§3.17) ──────────────────────────────────────
TRATAR_TP = "tp"                    # F4 / R-D-03 v2
TRATAR_COMO_TP = "como_tp"          # REDUCE / STOP_LOTE (qty del evento) y MOTOR provisional (pregunta 3)
TRATAR_ANOTAR = "anotar"            # HORA / EOD / HALT / BS, o nada que cerrar
TRATAR_DIVERGENCIA = "divergencia"  # SL del motor con la posición abierta: NO perseguir (pregunta 4)
TRATAR_IGNORAR = "ignorar"          # Daily Limit (I1: sin cortacircuito) o salida_motor = "ignorar"
TRATAMIENTOS = (TRATAR_TP, TRATAR_COMO_TP, TRATAR_ANOTAR, TRATAR_DIVERGENCIA, TRATAR_IGNORAR)

# ── claves de temporizador (§3.26 _temporizador; F4/F5; R-D-06) ─────────
CLAVE_HORA_AGREGAR = "hora_agregar"
CLAVE_HORA_ASK = "hora_ask"
CLAVE_EOD_COMPROBAR = "eod_comprobar"
CLAVE_TP_CRUCE = "tp_cruce"
CLAVE_CERRAR_TODO = "cerrar_todo_reintento"

# ── motivos de puede_reentrar (R-D-04, R-F-03, R-G-03) ──────────────────
MOTIVO_REENTRADA_PRIMERA = "primera entrada del día en este ticker (R-D-04)"
MOTIVO_REENTRADA_OK = "reentrada permitida por la estrategia (R-D-04)"
MOTIVO_REENTRADA_VETO = "veto de reentrada hasta /sigue o reapertura válida (R-G-03, R-F-03)"
MOTIVO_REENTRADA_BS = "ticker en protocolo de cisne negro (R-G-03)"
MOTIVO_REENTRADA_LOTE_VIVO = "la estrategia ya tiene un lote vivo en este ticker (R-D-04)"
MOTIVO_REENTRADA_NO_ACEPTA = "la estrategia no acepta reentradas: accept_reentries = false con max_reentries = −1 (R-D-04)"
MOTIVO_REENTRADA_TOPE = "tope de reentradas alcanzado: max_reentries (R-D-04)"
MOTIVO_REENTRADA_INVALIDO = "max_reentries imposible (< −1): no se reentra (R-D-04, conservador)"

# ── valores de salidas.salida_motor y estrategia.al_desactivar (§7) ──────
SALIDA_MOTOR_COMO_TP = "como_tp"
SALIDA_MOTOR_IGNORAR = "ignorar"
AL_DESACTIVAR_ESPERAR = "esperar_fin_dia"
AL_DESACTIVAR_REINICIAR = "cerrar_y_reiniciar"

EOD_POR_DEFECTO = "16:00"            # sin hora_fin_sesion: cierre de RTH (L4: sin posiciones overnight)
ESPERA_REINTENTO_CERRAR_TODO_S = 2.0  # R-D-06: pausa entre intentos de «cerrar todo» si el cuadro no la fija

_ESTADOS_VIVOS = (EstadoOrden.SENDING, EstadoOrden.ACCEPTED, EstadoOrden.PARTIAL, EstadoOrden.HOLD,
                  EstadoOrden.TRIGGERED)
_LOTE_VIVO = (EstadoLote.ABRIENDO, EstadoLote.ABIERTO, EstadoLote.CERRANDO)
_PROPOSITOS_CIERRE_TOTAL = (Proposito.HORA_AGREGAR, Proposito.HORA_ASK, Proposito.CIERRE_HUMANO,
                            Proposito.CIERRE_REINICIO)
_PIRAMIDE_REDUCE = frozenset({"reduce", "lot_stop", "lot_tp"})
_HORA = re.compile(r"^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$")

TokenOFabrica = Union[int, Callable[[], int]]


# ── clasificación (riesgo 24) ────────────────────────────────────────────
def clasificar(motivo: Optional[str]) -> ClaseSalida:
    """Corrección 5 del juez / riesgo 24: `exit_reason` del motor → `ClaseSalida`. NUNCA lanza.

    Exacto primero; luego los prefijos de las f-string (`"Lot TP (2/3)"` →
    TP, ajuste (f)); luego sin distinguir mayúsculas ni espacios de los
    extremos. None, «», un objeto que no es texto o un literal desconocido →
    MOTOR (tratamiento provisional «como TP», pregunta 3 a Jaume); el aviso
    `salida_desconocida` lo pone `avisos_de_tratamiento`.
    """
    try:
        if motivo is None:
            return ClaseSalida.MOTOR
        texto = motivo if isinstance(motivo, str) else str(motivo)
        exacto = LITERALES_EXIT_REASON.get(texto)
        if exacto is not None:
            return exacto
        limpio = texto.strip()
        for prefijo in PREFIJOS_EXIT_REASON:
            if limpio == prefijo or limpio.startswith(prefijo + " ") or limpio.startswith(prefijo + "("):
                return LITERALES_EXIT_REASON[prefijo]
        plegado = limpio.casefold()
        for literal, clase in LITERALES_EXIT_REASON.items():
            if literal.casefold() == plegado:
                return clase
    except Exception:  # noqa: BLE001 — frontera de mensaje: un motivo raro (str() que lanza) no puede tumbar al decisor (riesgo 24)
        return ClaseSalida.MOTOR
    return ClaseSalida.MOTOR


def es_literal_conocido(motivo: Optional[str]) -> bool:
    """True si `motivo` es un literal (o prefijo de f-string) de `LITERALES_EXIT_REASON`; para anotar «salida_desconocida». Nunca lanza."""
    if not isinstance(motivo, str):
        return False
    limpio = motivo.strip()
    if motivo in LITERALES_EXIT_REASON or any(lit.casefold() == limpio.casefold() for lit in LITERALES_EXIT_REASON):
        return True
    return any(limpio.startswith(p + " ") or limpio.startswith(p + "(") for p in PREFIJOS_EXIT_REASON)


def tratamiento(clase: ClaseSalida, pos: PosicionTicker, lote: Optional[Lote], vivas: list[Orden],
                salida_motor: str = SALIDA_MOTOR_COMO_TP) -> str:
    """§3.17 / F4 / F5: qué hace el ejecutor con una salida del motor de clase `clase` (uno de TRATAMIENTOS).

    TP → «tp» (R-D-03 v2: agregar 60 s y cruzar con techo 3 %). HORA / EOD →
    «anotar» (manda el reloj del ejecutor, R-D-08 / R-D-02). REDUCE /
    STOP_LOTE → «como_tp» con la qty del evento. STOP con la posición aún
    abierta (neta de fills o de DAS ≠ 0 y el lote con acciones) →
    «divergencia»: NO se persigue, la STOPLMTP residente manda (pregunta 4);
    con la posición ya cerrada → «anotar». MOTOR (Signal / Trailing / Time
    Limit / Escalera / ? / desconocido) → «como_tp» PROVISIONAL, o «ignorar» si
    `salida_motor == "ignorar"` (cfg.salidas.salida_motor, pregunta 3). HALT /
    BS → «anotar» (reglas F y G propias). DAILY_LIMIT → «ignorar» (I1: sin
    cortacircuito). Trampa de sobrecompra (riesgo 6): si el lote no tiene
    acciones libres (`llenas − tp_pendiente ≤ 0`), no existe, está cerrado o
    ya tiene viva una orden de cierre TOTAL (hora, cierre humano, reinicio),
    un «tp» / «como_tp» baja a «anotar».
    """
    if clase is ClaseSalida.DAILY_LIMIT:
        return TRATAR_IGNORAR
    if clase in (ClaseSalida.HORA, ClaseSalida.EOD, ClaseSalida.HALT, ClaseSalida.BS):
        return TRATAR_ANOTAR
    if clase is ClaseSalida.STOP:
        return TRATAR_DIVERGENCIA if _posicion_abierta(pos) and _lote_con_acciones(lote) else TRATAR_ANOTAR
    if clase is ClaseSalida.TP:
        codigo = TRATAR_TP
    elif clase in (ClaseSalida.REDUCE, ClaseSalida.STOP_LOTE):
        codigo = TRATAR_COMO_TP
    else:                                            # MOTOR y cualquier clase futura
        if str(salida_motor).strip().lower() == SALIDA_MOTOR_IGNORAR:
            return TRATAR_IGNORAR
        codigo = TRATAR_COMO_TP
    if (lote is None or lote.estado not in _LOTE_VIVO or _acciones_libres(lote) <= 0
            or _cierre_total_en_curso(lote, vivas)):
        return TRATAR_ANOTAR
    return codigo


def avisos_de_tratamiento(codigo: str, clase: ClaseSalida, motivo: Optional[str], pos: PosicionTicker,
                          lote: Optional[Lote]) -> list[Accion]:
    """Las acciones de diario y aviso que acompañan a cada tratamiento (§3.17; riesgo 24).

    Siempre `Anotar("salida_motor", …)` con el literal, la clase y el código;
    además: literal desconocido → `Anotar("salida_desconocida")`;
    «divergencia» → `Anotar("divergencia_sl")` + `Avisar(2)` (pregunta 4);
    MOTOR «como_tp» → `Avisar(1)` (tratamiento provisional, pregunta 3);
    DAILY_LIMIT → `Avisar(2)` con clave `daily_limit:<estrategia>` (el decisor
    lo manda una vez al día; I1: sin cortacircuito). No crea órdenes.
    """
    ticker = pos.ticker
    estrategia = lote.estrategia if lote is not None else "?"
    lote_id = lote.id if lote is not None else None
    literal = motivo if isinstance(motivo, str) else repr(motivo)
    datos = {"ticker": ticker, "lote_id": lote_id, "motivo": literal, "clase": clase.value, "tratamiento": codigo}
    acciones: list[Accion] = [Anotar("salida_motor", datos)]
    if not es_literal_conocido(motivo):
        acciones.append(Anotar("salida_desconocida", {"ticker": ticker, "lote_id": lote_id, "motivo": literal,
                                                      "regla": "riesgo 24"}))
    if codigo == TRATAR_DIVERGENCIA:
        acciones.append(Anotar("divergencia_sl", {"ticker": ticker, "lote_id": lote_id, "neta_fills": pos.neta_fills,
                                                  "neta_das": pos.neta_das, "regla": "pregunta 4"}))
        acciones.append(Avisar(nivel=Nivel.AVISO, grupo=Grupo.B, clave=f"divergencia_sl:{ticker}",
                               texto=(f"{ticker} · {estrategia}: el motor cerró por SL pero la posición sigue abierta "
                                      f"en DAS (neta {pos.neta}); no se persigue, manda la STOPLMTP residente")))
    elif codigo == TRATAR_COMO_TP and clase is ClaseSalida.MOTOR:
        acciones.append(Avisar(nivel=Nivel.INFO, grupo=Grupo.B, clave=f"salida_motor:{lote_id or ticker}",
                               texto=(f"{ticker} · {estrategia}: salida del motor «{literal}» tratada como TP "
                                      f"(agregar 60 s, luego al ask con techo 3 %; provisional, pregunta 3)")))
    elif clase is ClaseSalida.DAILY_LIMIT:
        clave_estrategia = lote.strategy_id if lote is not None else ticker
        acciones.append(Avisar(nivel=Nivel.AVISO, grupo=Grupo.B, clave=f"daily_limit:{clave_estrategia}",
                               texto=(f"{ticker} · {estrategia}: el motor marcó «Daily Limit»; el bot NO tiene "
                                      f"cortacircuito diario (I1) y lo ignora")))
    return acciones


# ── horas de salida y EOD (R-D-02, R-D-08, R-L-01) ───────────────────────
def horas_de_salida(e: EstrategiaConfig, dia: date,
                    cierre_mercado: Optional[datetime] = None) -> tuple[Optional[datetime], datetime]:
    """R-D-08 / R-D-02: (hora_salida, eod) de la estrategia en `dia`, aware en ET.

    `hora_salida` sale de `e.hora_salida` («HH:MM» o «HH:MM:SS»; None = sin
    salida por hora). `eod` = `e.hora_fin_sesion` (la hora FINAL de la
    estrategia, no las 16:00); sin ella, EOD_POR_DEFECTO (16:00, fin de RTH,
    L4). `cierre_mercado` (opcional, media sesión F10/F12: el llamador lo
    obtiene del calendario, que no es puro) recorta las dos horas. Lanza
    ValueError con una hora mal escrita.
    """
    eod = _hora_en(dia, e.hora_fin_sesion if e.hora_fin_sesion else EOD_POR_DEFECTO)
    salida = _hora_en(dia, e.hora_salida) if e.hora_salida else None
    if cierre_mercado is not None:
        tope = cierre_mercado.astimezone(ET) if cierre_mercado.tzinfo is not None else cierre_mercado.replace(tzinfo=ET)
        eod = min(eod, tope)
        salida = min(salida, tope) if salida is not None else None
    return salida, eod


def ultimo_eod(estrategias: Iterable[EstrategiaConfig], dia: date) -> Optional[datetime]:
    """R-L-01: el EOD más tardío de `estrategias` en `dia` (el apagado es este + el margen de R-D-02); None si no hay ninguna.

    No filtra por `ejecutar`: el llamador pasa las activas y las que aún tengan
    lotes vivos (R-E-03, esperar fin de día). Una hora mal escrita cuenta como
    EOD_POR_DEFECTO (16:00): el apagado nunca se ADELANTA por un error de
    configuración (sin posiciones overnight, L4).
    """
    ultimo: Optional[datetime] = None
    for e in estrategias:
        try:
            _, eod = horas_de_salida(e, dia)
        except ValueError:
            eod = _hora_en(dia, EOD_POR_DEFECTO)
        if ultimo is None or eod > ultimo:
            ultimo = eod
    return ultimo


def temporizadores_lote(lote: Lote, e: EstrategiaConfig, dia: date, cfg_salidas: dict,
                        ahora_et: datetime) -> list[Programar]:
    """R-D-08 + R-D-02 (F5): los tres temporizadores de salida de UN lote, relativos a `ahora_et`.

    t = la hora de salida si existe y es anterior al EOD; si no, el EOD. Las
    horas del LOTE (`lote.hora_salida`, `lote.eod`, copia con la que nació,
    R-E-03) mandan sobre las de `e` cuando están puestas. Devuelve, en orden:
    `hora_agregar` en t − anticipo (por_hora.anticipo_s o eod.lanzar_antes_s,
    60 s), `hora_ask` en t y `eod_comprobar` en t + comprobar_despues_s
    (30 s). Si `ahora_et` ya pasó t, no hay agregar: `hora_ask` sale a 0 s (la
    hora no se negocia) y `eod_comprobar` 30 s después. Clave
    `"<tipo>:<lote_id>"` (ver trampas); `datos` = {lote_id, ticker, motivo
    ("hora" | "eod"), proposito, cuando (ISO ET)}.
    """
    salida, eod = horas_de_salida(e, dia)
    if lote.eod:
        eod = _hora_en(dia, lote.eod)
    if lote.hora_salida:
        salida = _hora_en(dia, lote.hora_salida)
    por_hora = salida is not None and salida < eod
    t = salida if por_hora and salida is not None else eod
    motivo = "hora" if por_hora else "eod"
    bloque_hora = _sub(cfg_salidas, "por_hora")
    bloque_eod = _sub(cfg_salidas, "eod")
    anticipo = _segundos(bloque_hora if por_hora else bloque_eod,
                         "anticipo_s" if por_hora else "lanzar_antes_s", SALIDA_ANTICIPO_S)
    despues = _segundos(bloque_eod, "comprobar_despues_s", EOD_COMPROBAR_DESPUES_S)
    ahora = _exigir_aware(ahora_et)
    en_ask = max((t - ahora).total_seconds(), 0.0)
    programas: list[Programar] = []
    if en_ask > 0:
        en_agregar = max((t - timedelta(seconds=anticipo) - ahora).total_seconds(), 0.0)
        programas.append(_programa(CLAVE_HORA_AGREGAR, en_agregar, lote, motivo, Proposito.HORA_AGREGAR,
                                   t - timedelta(seconds=anticipo)))
    programas.append(_programa(CLAVE_HORA_ASK, en_ask, lote, motivo, Proposito.HORA_ASK, t))
    programas.append(_programa(CLAVE_EOD_COMPROBAR, en_ask + despues, lote, motivo, None,
                               max(t, ahora) + timedelta(seconds=despues)))
    return programas


def clave_lote(base: str, lote_id: str) -> str:
    """Clave de un temporizador POR LOTE: «base:lote_id» (§6.1: una clave repetida sustituye a la anterior)."""
    return f"{base}:{lote_id}"


# ── órdenes de salida (R-D-08, R-D-03 v2, D10, corrección 11) ────────────
def orden_hora_agregar(lote: Lote, qty: int, cot: Optional[Cotizacion], cfg: Any, token: TokenOFabrica, hora_et: datetime,
                       proposito: Proposito = Proposito.HORA_AGREGAR) -> OrdenNueva:
    """R-D-08 (y R-D-03 v2 paso 1, R-E-03): la orden que AGREGA un minuto antes de la hora.

    Lote corto → COMPRA al `punto_medio_abajo` (se queda por debajo del ask,
    cobra rebate); lote largo → VENTA al `punto_medio_arriba`. PostOnly, ruta
    «agregar» por tramo, TIF DAY+, `lote_id` del lote. Libro bloqueado → un
    tick por dentro (ver trampas). Lanza ValueError sin bid/ask válidos o con
    el libro cruzado (el decisor pausa el ticker, H-5) y `OrdenNueva` si
    `qty` no es int > 0.
    """
    bid, ask = _libro(cot, lote.ticker)
    if _es_largo(lote):
        lado = Lado.VENTA
        precio = punto_medio_arriba(bid, ask)
        if precio <= bid:
            precio = bid + tick_de(bid)
    else:
        lado = Lado.COMPRA
        precio = punto_medio_abajo(bid, ask)
        if precio >= ask:
            precio = ask - tick_de(ask)
            if precio > 0 and tick_de(precio) < tick_de(ask):
                precio = ask - tick_de(precio)       # 1,00 bloqueado → 0,9999 (el tick de abajo es otro)
            if precio <= 0:
                raise ValueError(f"{lote.ticker}: libro bloqueado en el tick mínimo, no hay precio para agregar")
    ruta = ruta_de(_bloque(cfg, "rutas"), "agregar", precio, hora_et)
    return OrdenNueva(token=_token(token), lado=lado, ticker=lote.ticker, ruta=ruta, qty=qty, tipo=TipoOrden.LIMITE,
                      precio=precio, tif="DAY+", post_only=True, proposito=proposito, lote_id=lote.id)


def orden_al_ask(lote: Lote, qty: int, cot: Optional[Cotizacion], cfg: Any, token: TokenOFabrica, hora_et: datetime,
                 techo_pct: Optional[Decimal], proposito: Proposito) -> OrdenNueva:
    """R-D-08 (al ask SIN tope), R-D-03 v2 (techo 3 % sobre el último), D10: la orden que REMUEVE.

    Lote corto → COMPRA límite al ask; con `techo_pct` → min(ask, last·(1 +
    techo)) redondeado arriba. Lote largo → VENTA límite al bid; con techo →
    max(bid, last·(1 − techo)) redondeado abajo. `techo_pct=None` = sin tope
    (la hora no se negocia). Ruta «cruzar» por tramo y hora, TIF DAY+, sin
    PostOnly. Lanza ValueError sin el lado del libro que hace falta, sin `last`
    cuando hay techo, o con techo negativo. Para «cerrar todo» (R-D-06, techo
    sobre el ask) se usa `orden_cierre_posicion`.
    """
    largo = _es_largo(lote)
    if largo:
        precio = _exigir_precio(getattr(cot, "bid", None), f"{lote.ticker}: sin bid para vender")
        if techo_pct is not None:
            suelo = con_techo(_exigir_precio(getattr(cot, "last", None), f"{lote.ticker}: sin último para el techo"),
                              _pct_valido(techo_pct), arriba=False)
            precio = max(precio, suelo)
        lado = Lado.VENTA
    else:
        precio = _exigir_precio(getattr(cot, "ask", None), f"{lote.ticker}: sin ask para comprar")
        if techo_pct is not None:
            techo = con_techo(_exigir_precio(getattr(cot, "last", None), f"{lote.ticker}: sin último para el techo"),
                              _pct_valido(techo_pct), arriba=True)
            precio = min(precio, techo)
        lado = Lado.COMPRA
    precio = redondear_abajo(precio) if largo else redondear_arriba(precio)
    ruta = ruta_de(_bloque(cfg, "rutas"), "cruzar", precio, hora_et)
    return OrdenNueva(token=_token(token), lado=lado, ticker=lote.ticker, ruta=ruta, qty=qty, tipo=TipoOrden.LIMITE,
                      precio=precio, tif="DAY+", post_only=False, proposito=proposito, lote_id=lote.id)


def perseguir_ask(orden: Orden, cot: Optional[Cotizacion], persecuciones: int,
                  max_persecuciones: int = PERSEGUIR_ASK_MAX) -> Optional[Reemplazar]:
    """Corrección 11 (F5): a la hora, si no llenó, `Reemplazar` de PRECIO al ask nuevo; como mucho `max_persecuciones` (3).

    Nunca `Cancelar` + nueva: la cuota de 100 CANCEL/min es compartida con los
    stops. None si ya se persiguió `max_persecuciones` veces, si la orden no
    tiene `id_das` o no está viva, si no le quedan acciones (lvqty, o qty −
    llenas si DAS aún no la dijo: nunca lo pedido), si no hay ask (bid en una
    venta) o si su precio ya alcanza el libro. La qty del REPLACE es la que
    QUEDA viva (nunca más). Después manda `eod_comprobar` (+30 s → humano).
    """
    if persecuciones >= max_persecuciones or orden.id_das is None or orden.estado not in _ESTADOS_VIVOS:
        return None
    restante = orden.lvqty if orden.lvqty > 0 else orden.qty - orden.llenas
    if restante <= 0:
        return None
    compra = orden.lado is Lado.COMPRA
    nuevo = _precio_valido(getattr(cot, "ask" if compra else "bid", None))
    if nuevo is None:
        return None
    if orden.precio is not None and (nuevo <= orden.precio if compra else nuevo >= orden.precio):
        return None
    lado_libro = "ask" if compra else "bid"
    return Reemplazar(id_das=orden.id_das, token=orden.token, qty=restante, stop=None, precio=nuevo,
                      motivo=(f"corrección 11: persecución {persecuciones + 1}/{max_persecuciones} "
                              f"al {lado_libro} {nuevo} (R-D-08)"))


def tp_parcial(lote: Lote, evento_qty: int, cot: Optional[Cotizacion], cfg: Any, token: TokenOFabrica,
               hora_et: datetime) -> tuple[OrdenNueva, Programar]:
    """R-D-03 v2 (1) / F4.2: el TP agrega hasta 60 s en el punto medio y luego se cruza (`tp_al_vencer`).

    qty = min(`evento_qty`, llenas − tp_pendiente del lote): la suma de órdenes
    nunca supera la posición (recordatorio del área E). Devuelve la orden
    (`orden_hora_agregar` con propósito TP_AGREGAR) y `Programar("tp_cruce:
    <lote_id>", tp_parcial.agregar_s, {lote_id, token, qty})`. Lanza
    ValueError si no queda nada que cerrar o `evento_qty` no es int.
    """
    if type(evento_qty) is not int:
        raise ValueError(f"evento_qty debe ser int, no {evento_qty!r}")
    qty = min(evento_qty, _acciones_libres(lote))
    if qty <= 0:
        raise ValueError(f"{lote.ticker}: el lote {lote.id} no tiene acciones libres para el TP")
    orden = orden_hora_agregar(lote, qty, cot, cfg, token, hora_et, Proposito.TP_AGREGAR)
    espera = _segundos(_sub(_bloque(cfg, "salidas"), "tp_parcial"), "agregar_s", SALIDA_ANTICIPO_S)
    programa = Programar(clave=clave_lote(CLAVE_TP_CRUCE, lote.id), en_s=espera,
                         datos={"lote_id": lote.id, "ticker": lote.ticker, "token": orden.token, "qty": qty})
    return orden, programa


def tp_al_vencer(lote: Lote, resto: int, cot: Optional[Cotizacion], cfg: Any, token: TokenOFabrica,
                 hora_et: datetime) -> tuple[Optional[OrdenNueva], Optional[Avisar]]:
    """R-D-03 v2 (1)-(3) / F4.3: el resto del TP se cruza AL ASK con techo 3 % sobre el `last` DE ESE MOMENTO.

    Corto: ask ≤ last·(1 + techo) → orden al ask (TP_CRUCE); ask > techo →
    (None, Avisar(2, «limbo»)): NO se persigue, mandan los dos stops
    residentes. Largo: simétrico con el bid y last·(1 − techo). Sin último o
    sin el lado del libro → limbo (sin techo no hay orden). `resto ≤ 0` →
    (None, None). Techo = salidas.tp_parcial.techo_ask_pct (3 %).
    """
    if type(resto) is not int or resto <= 0:
        return None, None
    techo = _pct(_sub(_bloque(cfg, "salidas"), "tp_parcial"), "techo_ask_pct", TP_TECHO_ASK_PCT)
    largo = _es_largo(lote)
    last = _precio_valido(getattr(cot, "last", None))
    libro = _precio_valido(getattr(cot, "bid" if largo else "ask", None))
    if last is None or libro is None:
        return None, _aviso_limbo(lote, resto, "sin último precio o sin libro en DAS", techo)
    limite = con_techo(last, techo, arriba=not largo)
    if (libro < limite) if largo else (libro > limite):
        lado_libro = "bid" if largo else "ask"
        return None, _aviso_limbo(lote, resto, f"{lado_libro} {libro} fuera del techo {limite} (último {last})", techo)
    return orden_al_ask(lote, resto, cot, cfg, token, hora_et, techo, Proposito.TP_CRUCE), None


# ── prioridad en la misma tanda (R-D-07, D13) ────────────────────────────
def prioridad(senales: list[Senal]) -> list[Senal]:
    """R-D-07: salidas/TP → pirámides reduce/lot_stop/lot_tp → pirámides add → entradas → lo demás. Estable.

    El rango sale del `Evento` de cada señal (`tipo` y `accion_piramide`,
    leídos con getattr o como dict): una pirámide sin `accion_piramide` es
    «add» (bot_alerts_engine l.1065). Las señales sin evento (radar, latido,
    hidratado, día nuevo) y los tipos desconocidos van al final en su orden:
    no producen órdenes de salida y no deben retrasar un TP. No muta la lista.
    """
    return sorted(senales, key=_rango_prioridad)


# ── cerrar todo y EOD (R-D-06, R-D-02) ───────────────────────────────────
def orden_cierre_posicion(ticker: str, neta: int, cot: Optional[Cotizacion], cfg: Any, token: TokenOFabrica,
                          hora_et: datetime, techo_pct: Decimal = CERRAR_TODO_TECHO_PCT,
                          proposito: Proposito = Proposito.CIERRE_HUMANO,
                          lote_id: Optional[str] = None) -> OrdenNueva:
    """R-D-06: cerrar una posición de la cuenta (del bot o manual) REMOVIENDO con techo sobre el libro del momento.

    `neta` signada: < 0 (corta) → COMPRA |neta| con límite ask·(1 + techo)
    redondeado arriba; > 0 (larga) → VENTA neta con límite bid·(1 − techo)
    redondeado abajo. Ruta «cruzar», TIF DAY+. Lo usa `cerrar_todo` y lo puede
    usar el cierre humano durante un cisne negro (§3.19). Lanza ValueError
    con neta 0 o sin el lado del libro.
    """
    if type(neta) is not int or neta == 0:
        raise ValueError(f"{ticker}: neta debe ser un int ≠ 0, no {neta!r}")
    pct = _pct_valido(techo_pct)
    if neta < 0:
        ask = _exigir_precio(getattr(cot, "ask", None), f"{ticker}: sin ask para cerrar el corto")
        precio, lado = con_techo(ask, pct, arriba=True), Lado.COMPRA
    else:
        bid = _exigir_precio(getattr(cot, "bid", None), f"{ticker}: sin bid para cerrar el largo")
        precio, lado = con_techo(bid, pct, arriba=False), Lado.VENTA
        if precio <= 0:
            raise ValueError(f"{ticker}: el suelo {precio} no es un precio")
    ruta = ruta_de(_bloque(cfg, "rutas"), "cruzar", precio, hora_et)
    return OrdenNueva(token=_token(token), lado=lado, ticker=ticker, ruta=ruta, qty=abs(neta), tipo=TipoOrden.LIMITE,
                      precio=precio, tif="DAY+", post_only=False, proposito=proposito, lote_id=lote_id)


def cerrar_todo(posiciones: dict[str, PosicionTicker], cot_de: Callable[[str], Optional[Cotizacion]], cfg: Any,
                tokens: Callable[[], int], hora_et: datetime, proposito: Proposito = Proposito.CIERRE_HUMANO,
                intento: int = 0, tickers: Optional[Iterable[str]] = None) -> list[Accion]:
    """R-D-06 («/cerrar_todo SI», «/cerrar X SI»): cierra TODAS las posiciones de la cuenta, manuales incluidas.

    Por ticker (en orden alfabético) con neta ≠ 0 — `neta_das` si DAS la ha
    dicho (incluye lo manual, M7), si no la neta de fills —: `CancelarTicker`
    ANTES (nada vivo puede comprar de más, R-C-11) y `EnviarOrden` con
    `orden_cierre_posicion` (techo cerrar_todo.techo_pct, 5 %, sobre el ask o
    bajo el bid del momento). Neta de fills ≠ neta de DAS → además
    `Consultar("GET POSITIONS")` + `Anotar("discrepancia")`. Sin cotización →
    `Avisar(3)` «cerrar a mano» para ese ticker. `intento` 0 es el primero;
    mientras `intento < reintentos` (2) se añade `Programar("cerrar_todo_
    reintento", espera, {intento + 1, tickers})` y el decisor vuelve a llamar
    con la neta de ESE momento; con `intento > reintentos` no se envía nada:
    `Avisar(3)` con lo que sigue abierto y su precio (decide Jaume).
    `tickers` limita a esos (cierre de un ticker). Todo `Anotar("cerrar_todo")`.
    """
    bloque = _sub(_bloque(cfg, "salidas"), "cerrar_todo")
    techo = _pct(bloque, "techo_pct", CERRAR_TODO_TECHO_PCT)
    reintentos = _entero(bloque, "reintentos", CERRAR_TODO_REINTENTOS)
    espera = _segundos(bloque, "espera_s", ESPERA_REINTENTO_CERRAR_TODO_S)
    filtro = None if tickers is None else {str(t) for t in tickers}
    abiertas: list[tuple[str, int, PosicionTicker]] = []
    for ticker in sorted(posiciones):
        if filtro is not None and ticker not in filtro:
            continue
        pos = posiciones[ticker]
        neta = pos.neta_das if pos.neta_das is not None else pos.neta_fills
        if neta != 0 or _discrepa(pos):
            abiertas.append((ticker, neta, pos))
    acciones: list[Accion] = [Anotar("cerrar_todo", {"intento": intento, "tickers": [t for t, _, _ in abiertas],
                                                     "techo_pct": str(techo), "regla": "R-D-06"})]
    if not abiertas:
        return acciones
    if intento > reintentos:
        lineas = []
        for ticker, neta, _ in abiertas:
            cot = cot_de(ticker)
            lineas.append(f"{ticker} neta {neta} (bid {getattr(cot, 'bid', None)} / ask {getattr(cot, 'ask', None)} "
                          f"/ último {getattr(cot, 'last', None)})")
        acciones.append(Avisar(nivel=Nivel.MAXIMO, grupo=Grupo.B, clave="cerrar_todo:agotado",
                               texto=(f"R-D-06: tras {reintentos} reintentos siguen abiertas: " + "; ".join(lineas)
                                      + ". Decide Jaume")))
        return acciones
    for ticker, neta, pos in abiertas:
        acciones.append(CancelarTicker(ticker=ticker, motivo=f"R-D-06: cerrar todo (intento {intento})"))
        if _discrepa(pos):
            acciones.append(Consultar("GET POSITIONS"))
            acciones.append(Anotar("discrepancia", {"ticker": ticker, "neta_fills": pos.neta_fills,
                                                    "neta_das": pos.neta_das, "usada": neta, "regla": "R-D-06 / M7"}))
        if neta == 0:
            continue                                 # DAS dice plana y los fills no: el reintento lo vuelve a mirar
        try:
            orden = orden_cierre_posicion(ticker, neta, cot_de(ticker), cfg, tokens, hora_et, techo, proposito)
        except ValueError as exc:
            acciones.append(Avisar(nivel=Nivel.MAXIMO, grupo=Grupo.B, clave=f"cerrar_todo:{ticker}",
                                   texto=f"R-D-06: {ticker} neta {neta} sin cotización válida en DAS ({exc}): CERRAR A MANO"))
            continue
        acciones.append(EnviarOrden(orden=orden))
    acciones.append(Programar(clave=CLAVE_CERRAR_TODO, en_s=espera,
                              datos={"intento": intento + 1, "tickers": [t for t, _, _ in abiertas],
                                     "proposito": proposito.value}))
    return acciones


def comprobar_eod(lote: Lote, pos: PosicionTicker) -> Optional[Avisar]:
    """R-D-02 (2) / F5: +30 s tras la hora/EOD del lote, si le quedan acciones → `Avisar(3)` «EOD sin cerrar: control humano».

    Solo mira ESE lote (R-D-02 (3): las posiciones de otra estrategia no son
    alarma hasta su EOD). Sin aviso si el lote está cerrado o cancelado, no
    tiene acciones, o el ticker está plano en fills Y en DAS. El decisor pone
    `pos.estado = CONTROL_HUMANO` (el ticker deja de abrir; los stops siguen).
    """
    if lote.estado not in _LOTE_VIVO or lote.llenas <= 0:
        return None
    if pos.neta == 0 and pos.neta_das in (None, 0):
        return None
    return Avisar(nivel=Nivel.MAXIMO, grupo=Grupo.B, clave=f"eod:{lote.id}",
                  texto=(f"EOD sin cerrar: control humano. {lote.ticker} · {lote.estrategia}: al lote le quedan "
                         f"{lote.llenas} acciones (neta fills {pos.neta_fills}, DAS {pos.neta_das}) (R-D-02)"))


# ── reentradas (R-D-04, R-F-03, R-G-03) ─────────────────────────────────
def puede_reentrar(e: EstrategiaConfig, lote_anterior: Optional[Lote], pos: Optional[PosicionTicker]) -> tuple[bool, str]:
    """R-D-04 con el MISMO if/elif que el backtester (`portfolio_sim.py` l.2314-2318) + vetos R-G-03 / R-F-03.

    Vetos: `pos.sin_reentrada_hasta_sigue` (R-G-03 tras cisne negro, R-F-03
    tras stop + halt) o `pos.estado == BS` → no. Un lote base de la estrategia
    vivo → no (un lote base por estrategia y ticker). Entradas previas = lotes
    base de la estrategia (más `lote_anterior`) que operaron (no CANCELADOS
    sin fills), o `reentrada_n + 1` si es mayor. 0 previas → sí.
    max_reentries = −1 → manda accept_reentries; ≥ 0 → sí mientras previas ≤
    max_reentries (0 = ninguna; accept_reentries no cuenta, como en el
    backtester); < −1 → no (conservador). Devuelve (permitida, motivo).
    """
    if pos is not None and pos.sin_reentrada_hasta_sigue:
        return False, MOTIVO_REENTRADA_VETO
    if pos is not None and pos.estado is EstadoTicker.BS:
        return False, MOTIVO_REENTRADA_BS
    propios: dict[str, Lote] = {}
    if pos is not None:
        for lote in pos.lotes.values():
            if lote.strategy_id == e.strategy_id and lote.nivel_piramide is None:
                propios[lote.id] = lote
    if lote_anterior is not None and lote_anterior.strategy_id == e.strategy_id and lote_anterior.nivel_piramide is None:
        propios.setdefault(lote_anterior.id, lote_anterior)
    if any(lote.estado in _LOTE_VIVO for lote in propios.values()):
        return False, MOTIVO_REENTRADA_LOTE_VIVO
    operados = [lote for lote in propios.values() if lote.estado is not EstadoLote.CANCELADO or lote.llenas > 0]
    previas = max([len(operados)] + [lote.reentrada_n + 1 for lote in operados])
    if previas == 0:
        return True, MOTIVO_REENTRADA_PRIMERA
    maximo = e.max_reentries
    if maximo == -1:
        return (True, MOTIVO_REENTRADA_OK) if e.accept_reentries else (False, MOTIVO_REENTRADA_NO_ACEPTA)
    if maximo < -1:
        return False, MOTIVO_REENTRADA_INVALIDO
    if previas > maximo:
        return False, MOTIVO_REENTRADA_TOPE
    return True, MOTIVO_REENTRADA_OK


# ── estrategia desactivada o nueva versión con lote vivo (R-E-03, F14) ───
def al_desactivar(e_vieja: EstrategiaConfig, e_nueva: Optional[EstrategiaConfig], lotes_vivos: list[Lote],
                  cot_de: Callable[[str], Optional[Cotizacion]], cfg: Any, tokens: Callable[[], int],
                  hora_et: datetime) -> list[Accion]:
    """R-E-03 (F14): qué pasa con los lotes vivos de una estrategia que se desactiva o cambia de versión.

    El modo es `al_desactivar` de la versión NUEVA (lo que eligió el humano en
    el cuadro) o, si la estrategia desaparece, el de la vieja. «esperar_fin_
    dia» (defecto, y cualquier valor desconocido: R-E-03 «sin elección del
    humano se espera») → []. «cerrar_y_reiniciar» → por cada lote vivo de la
    estrategia con acciones libres, como R-D-08: `EnviarOrden(orden_hora_
    agregar(…, CIERRE_REINICIO))` (sin cotización válida no hay agregar) +
    `Programar("hora_ask:<lote>", anticipo)` + `Programar("eod_comprobar:
    <lote>", anticipo + 30)`, y al final `Anotar("cierre_reinicio")` +
    `Avisar(1)`. La versión nueva opera desde la siguiente señal.
    """
    elegido = (e_nueva.al_desactivar if e_nueva is not None else e_vieja.al_desactivar) or AL_DESACTIVAR_ESPERAR
    if str(elegido).strip().lower() != AL_DESACTIVAR_REINICIAR:
        return []
    salidas = _bloque(cfg, "salidas")
    anticipo = _segundos(_sub(salidas, "por_hora"), "anticipo_s", SALIDA_ANTICIPO_S)
    despues = _segundos(_sub(salidas, "eod"), "comprobar_despues_s", EOD_COMPROBAR_DESPUES_S)
    acciones: list[Accion] = []
    cerrados: list[str] = []
    for lote in lotes_vivos:
        if lote.strategy_id != e_vieja.strategy_id or lote.estado not in _LOTE_VIVO:
            continue
        qty = _acciones_libres(lote)
        if qty <= 0:
            continue
        espera_ask = anticipo
        try:
            orden = orden_hora_agregar(lote, qty, cot_de(lote.ticker), cfg, tokens, hora_et,
                                       Proposito.CIERRE_REINICIO)
            acciones.append(EnviarOrden(orden=orden))
        except ValueError:
            espera_ask = 0.0                         # sin libro no se agrega: directo al ask cuando lo haya
        datos = {"lote_id": lote.id, "ticker": lote.ticker, "motivo": "cierre_reinicio",
                 "proposito": Proposito.CIERRE_REINICIO.value}
        acciones.append(Programar(clave=clave_lote(CLAVE_HORA_ASK, lote.id), en_s=espera_ask, datos=dict(datos)))
        acciones.append(Programar(clave=clave_lote(CLAVE_EOD_COMPROBAR, lote.id), en_s=espera_ask + despues,
                                  datos=dict(datos)))
        cerrados.append(lote.id)
    if not cerrados:
        return acciones
    acciones.append(Anotar("cierre_reinicio", {"strategy_id": e_vieja.strategy_id, "lotes": cerrados,
                                               "version_vieja": e_vieja.definition_hash,
                                               "version_nueva": e_nueva.definition_hash if e_nueva else None,
                                               "regla": "R-E-03"}))
    acciones.append(Avisar(nivel=Nivel.INFO, grupo=Grupo.B, clave=f"cierre_reinicio:{e_vieja.strategy_id}",
                           texto=(f"R-E-03: {e_vieja.name}: se cierran {len(cerrados)} lote(s) vivos (agregar "
                                  f"{int(anticipo)} s, luego al ask sin tope); la versión nueva opera desde la "
                                  f"siguiente señal")))
    return acciones


# ── ayudantes privados (todos puros) ─────────────────────────────────────
def _bloque(cfg: Any, nombre: str) -> dict:
    """`cfg.<nombre>` de una `Config` o `cfg[nombre]` de un dict; ValueError si falta o no es un dict."""
    if hasattr(cfg, nombre):
        valor = getattr(cfg, nombre)
    elif isinstance(cfg, dict) and nombre in cfg:
        valor = cfg[nombre]
    else:
        raise ValueError(f"la config no tiene el bloque {nombre!r}")
    if not isinstance(valor, dict):
        raise ValueError(f"bloque {nombre!r} de la config no es un dict")
    return valor


def _sub(bloque: Any, nombre: str) -> dict:
    valor = bloque.get(nombre) if isinstance(bloque, dict) else None
    return valor if isinstance(valor, dict) else {}


def _pct(bloque: Any, clave: str, defecto: Decimal) -> Decimal:
    """Porcentaje del cuadro (float del JSON) convertido UNA vez con `de_float`; ausente → la constante de tipos."""
    valor = bloque.get(clave) if isinstance(bloque, dict) else None
    return _pct_valido(valor) if valor is not None else defecto


def _pct_valido(valor: Any) -> Decimal:
    pct = de_float(valor)
    if pct < 0:
        raise ValueError(f"un techo no puede ser negativo: {pct}")
    return pct


def _segundos(bloque: Any, clave: str, defecto: float) -> float:
    valor = bloque.get(clave) if isinstance(bloque, dict) else None
    if valor is None or isinstance(valor, bool):
        return float(defecto)
    segundos = float(de_float(valor))
    if segundos < 0:
        raise ValueError(f"{clave} no puede ser negativo: {segundos}")
    return segundos


def _entero(bloque: Any, clave: str, defecto: int) -> int:
    valor = bloque.get(clave) if isinstance(bloque, dict) else None
    if valor is None:
        return defecto
    if type(valor) is not int or valor < 0:
        raise ValueError(f"{clave} debe ser un entero ≥ 0, no {valor!r}")
    return valor


def _hora_en(dia: date, hhmm: str) -> datetime:
    """«HH:MM» o «HH:MM:SS» de `dia` como datetime aware en ET; ValueError si está mal escrita."""
    m = _HORA.match(str(hhmm)) if hhmm is not None else None
    if m is None:
        raise ValueError(f"hora mal escrita: {hhmm!r} (se espera HH:MM)")
    h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    if not (0 <= h <= 23 and 0 <= mi <= 59 and 0 <= s <= 59):
        raise ValueError(f"hora fuera de rango: {hhmm!r}")
    return datetime(dia.year, dia.month, dia.day, h, mi, s, tzinfo=ET)


def _exigir_aware(ahora_et: datetime) -> datetime:
    if ahora_et.tzinfo is None or ahora_et.utcoffset() is None:
        raise ValueError("ahora_et debe llevar zona horaria (ET)")
    return ahora_et


def _programa(base: str, en_s: float, lote: Lote, motivo: str, proposito: Optional[Proposito],
              cuando: datetime) -> Programar:
    datos: dict[str, Any] = {"lote_id": lote.id, "ticker": lote.ticker, "motivo": motivo,
                             "cuando": cuando.astimezone(ET).isoformat()}
    if proposito is not None:
        datos["proposito"] = proposito.value
    return Programar(clave=clave_lote(base, lote.id), en_s=float(en_s), datos=datos)


def _token(token: TokenOFabrica) -> int:
    """Un token ya reservado (int) o una fábrica `Callable[[], int]` (GeneradorTokens.siguiente)."""
    if callable(token):
        return token()
    return token


def _precio_valido(valor: Any) -> Optional[Decimal]:
    if valor is None:
        return None
    try:
        precio = de_float(valor)
    except ValueError:
        return None
    return precio if precio > 0 else None


def _exigir_precio(valor: Any, mensaje: str) -> Decimal:
    precio = _precio_valido(valor)
    if precio is None:
        raise ValueError(mensaje)
    return precio


def _libro(cot: Optional[Cotizacion], ticker: str) -> tuple[Decimal, Decimal]:
    bid = _exigir_precio(getattr(cot, "bid", None), f"{ticker}: sin bid válido en DAS")
    ask = _exigir_precio(getattr(cot, "ask", None), f"{ticker}: sin ask válido en DAS")
    if ask < bid:
        raise ValueError(f"{ticker}: libro cruzado (bid {bid} > ask {ask})")
    return bid, ask


def _es_largo(lote: Lote) -> bool:
    """Todas las estrategias de hoy son cortas; «Long…» en `direccion` es el único caso largo."""
    return str(lote.direccion).strip().lower().startswith("long")


def _acciones_libres(lote: Lote) -> int:
    """Acciones del lote sin una orden de TP pendiente: llenas − tp_pendiente (nunca negativo)."""
    return max(int(lote.llenas) - int(lote.tp_pendiente), 0)


def _lote_con_acciones(lote: Optional[Lote]) -> bool:
    return lote is not None and lote.estado in _LOTE_VIVO and lote.llenas > 0


def _posicion_abierta(pos: PosicionTicker) -> bool:
    return pos.neta != 0 or (pos.neta_das is not None and pos.neta_das != 0)


def _discrepa(pos: PosicionTicker) -> bool:
    """Corrección 2: DAS ha dicho la neta y no coincide con la de fills."""
    return pos.neta_das is not None and pos.neta_das != pos.neta_fills


def _cierre_total_en_curso(lote: Lote, vivas: list[Orden]) -> bool:
    return any(o.lote_id == lote.id and o.ticker == lote.ticker and o.estado in _ESTADOS_VIVOS
               and o.proposito in _PROPOSITOS_CIERRE_TOTAL for o in vivas)


def _aviso_limbo(lote: Lote, resto: int, causa: str, techo: Decimal) -> Avisar:
    return Avisar(nivel=Nivel.AVISO, grupo=Grupo.B, clave=f"limbo:{lote.id}",
                  texto=(f"limbo: {lote.ticker} · {lote.estrategia}: el resto del TP ({resto} acciones) no se cruza: "
                         f"{causa}; techo {techo} %. No se persigue; mandan los stops residentes (R-D-03 v2)"))


def _campo(evento: Any, nombre: str) -> Any:
    if isinstance(evento, dict):
        return evento.get(nombre)
    return getattr(evento, nombre, None)


def _rango_prioridad(senal: Senal) -> int:
    evento = senal.evento
    if evento is None:
        return 4
    tipo = str(_campo(evento, "tipo") or "").strip().lower()
    if tipo == "salida":
        return 0
    if tipo == "piramide":
        accion = str(_campo(evento, "accion_piramide") or "add").strip().lower()
        return 1 if accion in _PIRAMIDE_REDUCE else 2
    if tipo == "entrada":
        return 3
    return 4
