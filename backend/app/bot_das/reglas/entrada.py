"""Guardas de una señal de entrada y máquina de estados de la entrada en corto (R-B-01 v3).

QUÉ HACE. Dos cosas, las dos PURAS:
  1. `evaluar_senal`: las 16 comprobaciones, en ORDEN FIJO, que decide si una
     señal (entrada o pirámide «add», D13) se opera. Cada comprobación tiene su
     motivo (`MOTIVO_*`), estable y distinto, que el decisor lleva al diario
     (`senal_descartada`) y que los tests usan fila a fila.
  2. La entrada v3: `abrir_intento` → `orden_agregar` (venta límite PostOnly en
     el punto medio redondeado ARRIBA, ruta «agregar») → `sumar_senal` si llega
     otra estrategia (R-B-03) → `al_vencer` a los 60 s → `resto_a_cruzar` +
     `orden_cruce` (bid × (1 − 0,5 %), ruta «cruzar», SOLO si el bid no cayó
     más del 3 % desde el de la señal) → `repartir_fill` / `acumular_fill` por
     cada fill → `cerrar_intento` (R-B-02: se queda lo llenado).
  Además, las conversiones de la frontera con el `Evento` del motor:
  `t_cierre_vela` (epoch del CIERRE de la vela) y `qty_de_evento` (el ÚNICO
  sitio donde las acciones float del `Evento` pasan a int).

POR QUÉ ESTÁ AQUÍ. El decisor es el único que muta `EstadoBot` (H-5, §6.1);
todo lo que se puede decidir sin reloj ni socket vive aquí y se prueba con
tablas. Solo importa de `tipos`, de `reglas.precios` y de dos reglas puras
hermanas para no duplicar su verdad: `reglas.locates.asignar_a_lote`
(comprobación 16, E9: D1-02/G1A-07) y `reglas.salidas.puede_reentrar`
(comprobación 14, R-D-04 con paridad del backtester: D1-04). Nada de red, ni
de `time`, ni `datetime.now()`, ni logging, ni variables de entorno. Recibe
`ahora` (monotónico) y `ahora_et` (datetime aware ET) como parámetros.

LAS TRAMPAS.
  * `Evento.momento` es el INICIO del minuto, naive ET: `vela_de_mensaje`
    (`bot_alerts_feed.py` l.177-187) pone `timestamp` = campo `s` del mensaje
    AM y el motor copia `frame["timestamp"].iloc[i]` (`bot_alerts_engine.py`
    l.1027; runner l.40: frames sin zona, hora de Nueva York). El cierre es
    momento + 60 s. Si un día la fuente usara `e` (fin), la caducidad de R-B-04
    se correría 60 s SIN error: el test lo ata a la fixture `AM_recorte`.
  * `t_cierre_vela` y `IntentoEntrada.t_limite` son EPOCH, no monotónico: el
    plazo de un temporizador es `t_limite − ahora_et.timestamp()`
    (`segundos_hasta_limite`), NUNCA `t_limite − ahora`. Un `ahora_et` naive
    se rechaza: `.timestamp()` lo tomaría como hora LOCAL de la máquina (el PC
    de Jaume está en Madrid) y la caducidad se correría seis horas.
  * Acciones: el motor manda `float(round(acciones))` (engine l.1208-1210);
    `qty_de_evento` hace `int(round(Decimal(str(x))))` y devuelve 0 con None,
    NaN, ±inf, bool o ≤ 0. Nadie más convierte (injerto A §8.2).
  * El resto que se cruza sale SOLO de lo confirmado (injerto/corrección 5,
    riesgo 5): mientras quede un token vivo en el intento (orden viva o
    cancelación sin `Canceled`), `resto_a_cruzar` devuelve 0. Contrato con el
    decisor: `token_agregar`/`token_cruce` se ponen a None ÚNICAMENTE al llegar
    `Canceled` (con `cantidad_cancelada`), un `Executed` completo o un rechazo.
  * Una venta que descansa tiene que ir POR ENCIMA del bid: el punto medio
    redondeado arriba lo cumple con spread ≥ 1 tick y, con libro «bloqueado»
    (bid = ask), `orden_agregar` sube a bid + 1 tick. Eso es también el suelo
    de la SSR (B19): con SSR el cruce tampoco puede ir al bid.
  * Una señal guardada por halt (comprobación 7) NO debe entrar en
    `senales_vistas` hasta que se ejecute o se descarte: la comprobación 1 la
    rechazaría en la reapertura. En la reapertura se evalúa con
    `es_reapertura=True`, que se salta la caducidad (13) y el retraso (10,
    D1-03): el filtro de la reapertura es `halts.senal_guardada_valida`
    (primera vela < X %, R-F-04 b); el precio de la señal es el de ANTES del
    halt y un LULD mueve el 5-10 %, así que la 10 la descartaría siempre.
  * Los parámetros de la config llegan como float del JSON (3.0, 0.5): se
    convierten con `precios.de_float`, nunca se opera con float.
"""
from __future__ import annotations

import copy
import dataclasses
import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from functools import lru_cache
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.bot_das.reglas.locates import asignar_a_lote
from app.bot_das.reglas.precios import (
    bajo_bid,
    de_float,
    distancia_pct,
    punto_medio_arriba,
    redondear_arriba,
    ruta,
)
from app.bot_das.reglas.salidas import puede_reentrar
from app.bot_das.tipos import (
    COTIZACION_FRESCA_MAX_S,
    ENTRADA_AGREGAR_S,
    ENTRADA_CADUCIDAD_S,
    ENTRADA_CRUCE_BAJO_BID_PCT,
    ENTRADA_DISTANCIA_ULTIMO_BID_PCT,
    ENTRADA_RETRASO_MAX_PCT,
    ENTRADA_TOPE_CAIDA_BID_PCT,
    MODO_SEGURIDAD_DOLLAR_VOLUME_MIN,
    MODO_SEGURIDAD_PRECIO_MIN,
    Accion,
    Cancelar,
    Config,
    Cotizacion,
    EstadoBot,
    EstadoLote,
    EstadoSimbolo,
    EstadoTicker,
    EstrategiaConfig,
    FaseIntento,
    IntentoEntrada,
    Lado,
    Lote,
    OrdenNueva,
    PosicionTicker,
    Proposito,
    Senal,
    TipoOrden,
    tick_de,
)

# ── motivos de evaluar_senal: uno por comprobación, en el ORDEN FIJO de §3.15 ──
MOTIVO_OK = "ok"
MOTIVO_REPETIDA = "señal repetida (R-A-05)"                                                      # 1
MOTIVO_BOT_PAUSADO = "bot sin vigilar, en pausa o en control humano (R-M-03, R-D-02)"            # 2
MOTIVO_ESTRATEGIA = "estrategia ausente, sin ejecutar o de otra cuenta (CM2)"                    # 3
MOTIVO_TICKER_BLOQUEADO = "ticker pausado, en cisne negro, sin símbolo o en control humano (R-B-07, R-G-03, A7)"  # 4
MOTIVO_LADO = "lado opuesto a la posición o no operable: solo cortos (R-E-01)"                  # 5
MOTIVO_EXCLUIDA = "ticker excluido (R-A-03 v2)"                                                  # 6
MOTIVO_HALT = "halt en curso: señal guardada para la reapertura (R-F-04 b, B18)"                # 7
MOTIVO_SIN_COTIZACION = "sin cotización fresca de DAS (R-B-01)"                                 # 8
MOTIVO_MODO_SEGURIDAD = "modo de seguridad: precio o dólares acumulados bajo el mínimo (R-I-04)"  # 9
MOTIVO_RETRASO = "señal tardía: el último se alejó del precio de la señal (R-A-01)"              # 10
MOTIVO_DISTANCIA_BID = "bid demasiado lejos del último (B20 bis)"                                # 11
MOTIVO_NIVEL_STOP = "nivel de stop ausente o no por encima del último (R-C-09, A12)"             # 12
MOTIVO_NIVEL_DISTINTO = "nivel de stop distinto del de los lotes vivos del ticker (Jaume 30-sep: un solo nivel)"  # 12b
MOTIVO_CADUCADA = "señal caducada (R-B-04)"                                                      # 13
MOTIVO_REENTRADA = "reentrada no permitida (R-D-04, R-F-03, R-G-03, R-E-03)"                     # 14
MOTIVO_DEGRADADO = "modo degradado: diario, feed, DAS o reconciliación (corrección 4, R-J-03)"   # 15
MOTIVO_SIN_ACCIONES = "sin acciones: tamaño 0 o sin locates libres (R-H-04)"                     # 16

MOTIVOS_EN_ORDEN: tuple[str, ...] = (
    MOTIVO_REPETIDA, MOTIVO_BOT_PAUSADO, MOTIVO_ESTRATEGIA, MOTIVO_TICKER_BLOQUEADO,
    MOTIVO_LADO, MOTIVO_EXCLUIDA, MOTIVO_HALT, MOTIVO_SIN_COTIZACION,
    MOTIVO_MODO_SEGURIDAD, MOTIVO_RETRASO, MOTIVO_DISTANCIA_BID, MOTIVO_NIVEL_STOP, MOTIVO_NIVEL_DISTINTO,
    MOTIVO_CADUCADA, MOTIVO_REENTRADA, MOTIVO_DEGRADADO, MOTIVO_SIN_ACCIONES,
)

# Motivos que NO se avisan al grupo B: los decidió el humano (2, 3), son ruido
# (1) o ya los avisa el módulo de halts (7). El resto se avisa a nivel 1 (F1.2).
MOTIVOS_SIN_AVISO = frozenset({MOTIVO_REPETIDA, MOTIVO_BOT_PAUSADO, MOTIVO_ESTRATEGIA, MOTIVO_HALT})

# ── motivos del final de un intento (al_vencer) y de las cancelaciones ──
MOTIVO_FIN_LLENA = "entrada completa (R-B-01)"
MOTIVO_FIN_BID_CAYO = "bid cayó más del tope desde el de la señal: no se entra (R-B-01 v3)"
MOTIVO_FIN_SIN_COTIZACION = "sin cotización al vencer: no se cruza (R-B-01)"
MOTIVO_CANCELAR_SUMA = "R-B-03: señal nueva sumada, se reinicia con el total"

_SEGUNDOS_VELA = 60.0
_CIEN = Decimal("100")
_VIVOS = frozenset({EstadoLote.ABRIENDO, EstadoLote.ABIERTO, EstadoLote.CERRANDO})
_TICKER_BLOQUEADO = frozenset({EstadoTicker.PAUSADO, EstadoTicker.BS,
                               EstadoTicker.SIN_SIMBOLO, EstadoTicker.CONTROL_HUMANO})
_TA_HALT = frozenset({"H", "P"})                     # manual L1101-1133: H halted, P paused
_PIRAMIDE_ADD = frozenset({"add"})
_PIRAMIDE_REDUCE = frozenset({"reduce", "lot_stop", "lot_tp"})
_AL_DESACTIVAR_REINICIAR = "cerrar_y_reiniciar"      # R-E-03; cualquier otro valor = esperar fin de día


@dataclass(frozen=True)
class Veredicto:
    """Resultado de `evaluar_senal` (§3.15).

    `motivo` es SIEMPRE uno de `MOTIVOS_EN_ORDEN` o `MOTIVO_OK`; `qty` > 0 solo
    con `ok`; `guardar_para_reapertura` solo con `MOTIVO_HALT`; `avisar` dice si
    el decisor manda `Avisar(1, B)` además de anotar el descarte (F1.2).
    """
    ok: bool
    motivo: str
    qty: int = 0
    guardar_para_reapertura: bool = False
    avisar: bool = False


# ── frontera con el Evento del motor ────────────────────────────────────
def t_cierre_vela(momento: Any) -> float:
    """Epoch del CIERRE de la vela de la señal = momento (naive ET → aware ET) + 60 s (R-B-04).

    Correcto porque `vela_de_mensaje` (`bot_alerts_feed.py` l.177-187) pone
    `timestamp` = campo `s` del mensaje AM (INICIO del minuto), el motor copia
    `Evento.momento = frame["timestamp"].iloc[i]` (engine l.1027) y los frames
    van naive en hora de Nueva York (runner l.40). Acepta `pd.Timestamp` (vía
    `to_pydatetime`, sin importar pandas), `datetime` y `str` ISO
    («2026-09-25 09:30:00»). Naive = ET; aware se respeta. Riesgo 13: la hora
    local de la máquina no interviene. Lanza ValueError con None, NaT, números
    u otros tipos.
    """
    if isinstance(momento, str):
        texto = momento.strip()
        if not texto:
            raise ValueError("momento vacío")
        try:
            dt: Any = datetime.fromisoformat(texto)
        except ValueError as exc:
            raise ValueError(f"momento no es una fecha ISO: {momento!r}") from exc
    elif hasattr(momento, "to_pydatetime"):
        dt = momento.to_pydatetime()           # pd.Timestamp (NaT devuelve NaT, que no es datetime)
    else:
        dt = momento
    if not isinstance(dt, datetime):
        raise ValueError(f"momento no es una fecha: {momento!r}")
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        dt = dt.replace(tzinfo=_et())
    return dt.timestamp() + _SEGUNDOS_VELA


def qty_de_evento(acciones: Optional[float]) -> int:
    """Acciones del `Evento` → int: `int(round(Decimal(str(x))))`; None, bool, NaN, ±inf o ≤ 0 → 0.

    ÚNICO punto de conversión float → int del bot (injertos A §8.1-8.2, riesgo
    12). El motor ya redondea (`float(round(acciones))`, engine l.1208-1210);
    `round` de Decimal es al par, igual que el `round` del motor.
    """
    if acciones is None or isinstance(acciones, bool):
        return 0
    try:
        valor = Decimal(str(acciones))
    except (InvalidOperation, ValueError, TypeError):
        return 0
    if not valor.is_finite() or valor <= 0:
        return 0
    return int(round(valor))


def es_piramide_add(evento: Any) -> bool:
    """Pirámide que AÑADE: sigue el protocolo de entrada R-B-01/02/03 (D13). `accion_piramide` ∈ {"add"}."""
    return _tipo_de(evento) == "piramide" and _accion_piramide(evento) in _PIRAMIDE_ADD


def es_piramide_reduce(evento: Any) -> bool:
    """Pirámide que QUITA (reduce / stop de lote / TP de lote): va por salidas, no por aquí (D13, R-D-03)."""
    return _tipo_de(evento) == "piramide" and _accion_piramide(evento) in _PIRAMIDE_REDUCE


def nivel_de_senal(estado: EstadoBot, evento: Any) -> Optional[Decimal]:
    """Nivel de stop L de la señal (R-C-09): `Evento.stop` del motor compartido, en Decimal.

    El `Evento` de pirámide no trae `stop` (engine l.1058-1068): una «add» usa
    el `nivel_stop` de SU lote base vivo (misma estrategia y, si se conoce, el
    mismo `entrada_idx`). Sin lote base o con más de uno candidato → None
    (A12: sin nivel no se entra; «solo se piramida con la base ya dentro»,
    R-B-03). Un stop NaN/inf se trata como ausente.
    """
    stop = getattr(evento, "stop", None)
    if stop is not None:
        try:
            return de_float(stop)
        except ValueError:
            return None
    if not es_piramide_add(evento):
        return None
    base = _lote_base_vivo(estado.posiciones.get(getattr(evento, "ticker", None)), evento)
    return None if base is None else base.nivel_stop


# ── las 16 comprobaciones ──────────────────────────────────────────────
def evaluar_senal(estado: EstadoBot, cfg: Config, senal: Senal, cot: Optional[Cotizacion],
                  simb: EstadoSimbolo, exclusion: Optional[str], franja: str, ahora: float,
                  ahora_et: datetime, diario_degradado: bool, *, es_reapertura: bool = False,
                  max_edad_cot_s: float = COTIZACION_FRESCA_MAX_S) -> Veredicto:
    """¿Se opera esta señal? 16 comprobaciones en ORDEN FIJO (§3.15, ajuste (c)); la primera que falla decide.

     1 repetida: `senal.id` ∈ `senales_vistas` (R-A-05).
     2 bot: `vigilando` False (estado o cuadro), `pausa_global`, `control_humano`, `pausar_entradas` (R-M-03, R-D-02).
     3 estrategia ausente, `ejecutar=False` (CM2) o `Evento.cuenta` de otra cuenta (el ejecutor opera UNA).
     4 ticker PAUSADO / BS / SIN_SIMBOLO / CONTROL_HUMANO (R-B-07, R-G-03, A7) o pausado por el humano con
       «/pausar X» (`pausado_por_humano`, Jaume 29-sep).
     5 lado: solo cortos; señal contraria a un lote vivo o con neta larga → no (R-E-01).
     6 `exclusion` (motivo de `reglas.exclusiones.excluida`, calculado por el decisor; None = operable).
     7 halt en curso (TA H/P o ticker en HALT) → no, y `guardar_para_reapertura` (R-F-04 b, B18).
     8 cotización de DAS: bid, ask y último presentes y > 0, libro no cruzado y de hace ≤ `max_edad_cot_s`
       (R-B-01 «sin cotización no se entra»; defecto `tipos.COTIZACION_FRESCA_MAX_S`, la MISMA constante
       que `MercadoDAS.fresca`: D1-12).
     9 modo de seguridad activo: último ≥ precio_min y volumen × VWAP ≥ acum_dollar_volume_min (R-I-04; ≥ pasa).
    10 retraso: |último − precio_señal| / precio_señal > retraso_max_senal_pct → no (R-A-01; igual pasa).
       null o ausente en el cuadro = el defecto del libro (1 %), NUNCA «apagada» (D1-09: el filtro de
       R-A-01 no se apaga en silencio). Se salta con `es_reapertura=True` (D1-03, R-F-04 b): el precio
       de la señal es el de antes del halt y el filtro de la reapertura es `halts.senal_guardada_valida`.
    11 B20 bis: (último − bid) / último > distancia_max_ultimo_bid_pct → no (null = apagada; igual pasa).
       Decisión 11 (Jaume 30-sep): APAGADA por defecto («la quito porque ya tenemos el 3 %»); un número la enciende.
    12 nivel L (`nivel_de_senal`) None → no (A12); L ≤ último → no (R-C-09).
    13 caducidad: `ahora_et` > cierre de la vela + caducidad_senal_s → no (R-B-04; igual pasa). Se salta
       con `es_reapertura=True` (señal guardada por halt, validada antes por `halts.senal_guardada_valida`).
    14 reentrada: `sin_reentrada_hasta_sigue` (R-G-03, R-F-03); lote de una versión anterior de la
       estrategia (R-E-03); y el resto (lote base vivo, accept_reentries / max_reentries) lo decide
       `salidas.puede_reentrar`, con el MISMO if/elif que el backtester (D1-04, R-D-04: −1 = manda
       accept_reentries; 0 = ninguna; N > 0 = hasta N aunque accept_reentries sea false).
    15 degradado: `diario_degradado` (corrección 4) o `estado.modo_degradado` no vacío (R-J-03).
    16 acciones = min(qty_de_evento, lo que cubre `locates.asignar_a_lote`) (R-H-04, E9: D1-02/G1A-07):
       locate propio + sobrantes de las demás estrategias del ticker + ETB en CUALQUIER registro del
       ticker; la misma regla con la que el decisor reparte después. 0 → no.

    `franja` no cambia ninguna comprobación a propósito: B11 (PM sin excepciones)
    y F10 (con SSR SÍ se entra; el precio ya va ≥ bid + 1 tick, B19). `ahora` es
    monotónico (frescura de la cotización); `ahora_et`, aware ET (caducidad).
    Lanza ValueError con una señal mal formada (no «evento», sin id, sin
    ticker, tipo que no es entrada ni pirámide «add», precio no positivo,
    momento ilegible), con una cotización o un símbolo de otro ticker o con un
    `ahora_et` naive: el decisor lo convierte en pausa del ticker (H-5).
    """
    evento = _validar_senal(senal)
    _exigir_aware(ahora_et)
    ticker = senal.ticker
    if cot is not None and cot.ticker != ticker:
        raise ValueError(f"cotización de {cot.ticker!r} para una señal de {ticker!r}")
    if simb.ticker != ticker:
        raise ValueError(f"estado de símbolo de {simb.ticker!r} para una señal de {ticker!r}")
    precio_senal = de_float(getattr(evento, "precio", None))
    if precio_senal <= 0:
        raise ValueError(f"precio de la señal no positivo: {precio_senal}")
    momento = senal.momento if senal.momento is not None else getattr(evento, "momento", None)
    t_cierre = t_cierre_vela(momento)          # un momento ilegible es una señal mal formada (riesgo 18)
    pos = estado.posiciones.get(ticker)
    strategy_id = getattr(evento, "strategy_id", None)

    # 1
    if senal.id in estado.senales_vistas:
        return _descartar(MOTIVO_REPETIDA)
    # 2
    if (not estado.vigilando or not cfg.vigilando or estado.pausa_global
            or estado.control_humano or cfg.pausar_entradas):
        return _descartar(MOTIVO_BOT_PAUSADO)
    # 3
    estrategia = cfg.estrategias.get(strategy_id)
    if estrategia is None or not estrategia.ejecutar or getattr(evento, "cuenta", None) is not None:
        return _descartar(MOTIVO_ESTRATEGIA)
    # 4 (Jaume 29-sep: también «/pausar X», `pausado_por_humano`, con el ticker NORMAL)
    if pos is not None and (pos.estado in _TICKER_BLOQUEADO or pos.pausado_por_humano):
        return _descartar(MOTIVO_TICKER_BLOQUEADO)
    # 5
    if _lado_prohibido(pos, evento):
        return _descartar(MOTIVO_LADO)
    # 6
    if exclusion is not None:
        return _descartar(MOTIVO_EXCLUIDA)
    # 7
    if _en_halt(pos, simb):
        return Veredicto(ok=False, motivo=MOTIVO_HALT, guardar_para_reapertura=True, avisar=False)
    # 8
    if cot is None or not _cotizacion_valida(cot, ahora, max_edad_cot_s):
        return _descartar(MOTIVO_SIN_COTIZACION)
    # 9 (desde aquí bid, ask y último son Decimal > 0: lo garantiza la 8)
    if _modo_seguridad_bloquea(cfg.modo_seguridad, cot):
        return _descartar(MOTIVO_MODO_SEGURIDAD)
    # 10 (D1-03: no en la reapertura; D1-09: null = defecto del libro, nunca apagada)
    if not es_reapertura:
        retraso_max = _pct(cfg.entrada, "retraso_max_senal_pct", ENTRADA_RETRASO_MAX_PCT)
        referencia = _referencia_retraso(senal, evento, precio_senal)
        if referencia is not None and abs(distancia_pct(cot.last, referencia)) > retraso_max:
            return _descartar(MOTIVO_RETRASO)
    # 11
    distancia_max = _pct_opcional(cfg.entrada, "distancia_max_ultimo_bid_pct", ENTRADA_DISTANCIA_ULTIMO_BID_PCT)
    if distancia_max is not None and -distancia_pct(cot.bid, cot.last) > distancia_max:
        return _descartar(MOTIVO_DISTANCIA_BID)
    # 12
    nivel = nivel_de_senal(estado, evento)
    if nivel is None or nivel <= cot.last:
        return _descartar(MOTIVO_NIVEL_STOP)
    # 12b (Jaume 30-sep): de momento TODAS las estrategias llevan el MISMO nivel de stop en un ticker y el stop único
    # (+50 %) aglutina la posición entera. Una señal con otro nivel que el de los lotes vivos NO mete orden y avisa.
    # PENDIENTE (pregunta 45): varias estrategias con stops de distinto nivel.
    if pos is not None and any(lote.estado in _VIVOS and isinstance(lote.nivel_stop, Decimal) and lote.nivel_stop.is_finite()
                               and lote.nivel_stop > 0 and lote.nivel_stop != nivel
                               for lote in pos.lotes.values()):
        return _descartar(MOTIVO_NIVEL_DISTINTO)
    # 13
    if not es_reapertura:
        caducidad = _segundos(cfg.entrada, "caducidad_senal_s", ENTRADA_CADUCIDAD_S)
        if ahora_et.timestamp() > t_cierre + caducidad:
            return _descartar(MOTIVO_CADUCADA)
    # 14
    if _reentrada_prohibida(pos, estrategia, evento):
        return _descartar(MOTIVO_REENTRADA)
    # 15
    if diario_degradado or estado.modo_degradado:
        return _descartar(MOTIVO_DEGRADADO)
    # 16
    pedidas = qty_de_evento(getattr(evento, "acciones", None))
    qty = min(pedidas, _locates_libres(estado, ticker, strategy_id, pedidas))     # E9 (D1-02, G1A-07)
    if qty <= 0:
        return _descartar(MOTIVO_SIN_ACCIONES)
    return Veredicto(ok=True, motivo=MOTIVO_OK, qty=qty)


def qty_final(qty_senal: int, locates_libres: int, capital_qty: int, fraccion_max: Optional[Decimal],
              volumen_acum: Optional[int]) -> tuple[int, Decimal]:
    """(acciones que salen, fracción del volumen acumulado que se registra) — R-B-05, R-I-01, R-E-02, R-H-04.

    qty = min(señal, locates libres, lo que cabe por capital), nunca < 0. La
    fracción (qty / volumen acumulado del día) se MIDE siempre; sin volumen
    (None o 0, primeros minutos del PM) se registra 0 y no se limita. El tope
    solo actúa si `fraccion_max` no es None (hoy desactivado): recorta a
    floor(fraccion_max · volumen) y se entra con lo que quepa (como R-I-01).
    `fraccion_max` es una fracción (0,05 = 5 %), no un porcentaje. Lanza
    ValueError si una cantidad no es int o `fraccion_max` < 0.
    """
    for nombre, valor in (("qty_senal", qty_senal), ("locates_libres", locates_libres),
                          ("capital_qty", capital_qty)):
        if type(valor) is not int:
            raise ValueError(f"{nombre} debe ser int, no {valor!r}")
    if volumen_acum is not None and type(volumen_acum) is not int:
        raise ValueError(f"volumen_acum debe ser int o None, no {volumen_acum!r}")
    qty = max(0, min(qty_senal, locates_libres, capital_qty))
    volumen = volumen_acum if volumen_acum is not None and volumen_acum > 0 else None
    if fraccion_max is not None:
        tope_frac = de_float(fraccion_max)
        if tope_frac < 0:
            raise ValueError(f"fraccion_max negativa: {fraccion_max!r}")
        if volumen is not None:
            tope = int((tope_frac * Decimal(volumen)).to_integral_value(rounding=ROUND_FLOOR))
            qty = min(qty, tope)
    fraccion = Decimal(qty) / Decimal(volumen) if volumen is not None else Decimal("0")
    return qty, fraccion


# ── máquina de estados de la entrada v3 ───────────────────────────────
def abrir_intento(pos: PosicionTicker, lotes: list[Lote], cot: Cotizacion, precio_senal: Decimal,
                  t_cierre: float, cfg: Config, ahora: float) -> IntentoEntrada:
    """Nace el intento de UN ticker con N lotes (R-B-01 v3, R-B-03): AGREGANDO hasta t_cierre + agregar_s.

    `bid_senal`/`ask_senal` = la foto de DAS en la señal (referencia del tope
    del 3 %); `t_limite` = `t_cierre` + `entrada.agregar_s` (EPOCH, como
    `t_cierre_vela`); `cfg_congelada` = copia profunda del bloque «entrada»
    (riesgo 21: una config en caliente no cambia un intento vivo). Para una
    señal guardada por halt el decisor pasa como `t_cierre` el instante de la
    reapertura. `ahora` (monotónico) no entra en ningún plazo del intento: se
    conserva por el contrato de §3.15. Lanza ValueError sin lotes, con lotes
    repetidos o de otro ticker, pedidas ≤ 0, sin bid/ask o con `t_cierre` no finito.
    """
    if not lotes:
        raise ValueError("un intento necesita al menos un lote")
    ids = [lote.id for lote in lotes]
    if len(set(ids)) != len(ids):
        raise ValueError(f"lotes repetidos: {ids}")
    for lote in lotes:
        if lote.ticker != pos.ticker:
            raise ValueError(f"lote {lote.id!r} de {lote.ticker!r} en un intento de {pos.ticker!r}")
        if type(lote.pedidas) is not int or lote.pedidas <= 0:
            raise ValueError(f"lote {lote.id!r} con pedidas no válidas: {lote.pedidas!r}")
    _exigir_libro(cot, pos.ticker)
    precio = de_float(precio_senal)
    if precio <= 0:
        raise ValueError(f"precio de la señal no positivo: {precio}")
    if isinstance(t_cierre, bool) or not isinstance(t_cierre, (int, float)) or not math.isfinite(t_cierre):
        raise ValueError(f"t_cierre no es un epoch finito: {t_cierre!r}")
    agregar_s = _segundos(cfg.entrada, "agregar_s", ENTRADA_AGREGAR_S)
    return IntentoEntrada(
        ticker=pos.ticker,
        lotes=ids,
        qty_total=sum(lote.pedidas for lote in lotes),
        bid_senal=cot.bid,
        ask_senal=cot.ask,
        precio_senal=precio,
        t_cierre_vela=float(t_cierre),
        t_limite=float(t_cierre) + agregar_s,
        cfg_congelada=copy.deepcopy(dict(cfg.entrada)),
    )


def segundos_hasta_limite(intento: IntentoEntrada, ahora_et: datetime) -> float:
    """Plazo del temporizador «cruce» = `t_limite` − `ahora_et` en epoch, nunca negativo (F1.4, riesgo 13).

    `t_limite` es epoch: restarle el monotónico `ahora` daría un plazo absurdo
    sin error. `ahora_et` naive → ValueError.
    """
    _exigir_aware(ahora_et)
    return max(0.0, intento.t_limite - ahora_et.timestamp())


def orden_agregar(intento: IntentoEntrada, cot: Cotizacion, cfg: Config, token: int, hora_et: datetime,
                  *, nivel: Optional[Decimal] = None) -> OrdenNueva:
    """SS de lo pendiente en el punto medio redondeado ARRIBA, PostOnly, TIF=DAY+, ruta «agregar» (R-B-01 v3).

    qty = qty_total − llenas (tras `sumar_senal`, el reinicio lleva el total
    menos lo ya llenado). Precio = max(punto_medio_arriba(bid, ask), bid + 1
    tick): con spread de 1 tick es el ask, con 2 ticks bid + 1, y con libro
    bloqueado (bid = ask) bid + 1 tick; así la venta siempre descansa y con
    SSR ya está ≥ bid + 1 tick (B19, F10). Ruta por tramo/hora con
    `precios.ruta(cfg.rutas, "agregar", precio, hora_et)`; PostOnly del bloque
    congelado (defecto True). `lote_id` = primer lote; `nivel` = L del lote
    (el decisor pasa `lotes[0].nivel_stop`). Lanza ValueError si el intento no
    está AGREGANDO, si ya tiene una orden viva (riesgo 4: dos órdenes vivas),
    si no queda nada pendiente o si no hay libro.
    """
    if intento.fase is not FaseIntento.AGREGANDO:
        raise ValueError(f"orden_agregar con el intento en fase {intento.fase.value}")
    _exigir_sin_orden_viva(intento)
    pendiente = intento.qty_total - intento.llenas
    if pendiente <= 0:
        raise ValueError(f"nada pendiente: qty_total {intento.qty_total}, llenas {intento.llenas}")
    _exigir_libro(cot, intento.ticker)
    precio = max(punto_medio_arriba(cot.bid, cot.ask), _suelo_sobre_bid(cot.bid))
    bloque = _bloque_entrada(intento, cfg)
    return OrdenNueva(
        token=token,
        lado=Lado.CORTO,
        ticker=intento.ticker,
        ruta=ruta(cfg.rutas, "agregar", precio, hora_et),
        qty=pendiente,
        tipo=TipoOrden.LIMITE,
        precio=precio,
        tif="DAY+",
        post_only=bool(bloque.get("post_only", True)),
        proposito=Proposito.ENTRADA_AGREGAR,
        lote_id=intento.lotes[0],
        nivel=nivel,
    )


def sumar_senal(intento: IntentoEntrada, lote: Lote, *,
                id_das_viva: Optional[int] = None) -> tuple[IntentoEntrada, list[Accion]]:
    """Otra estrategia pide el mismo ticker con el intento vivo: se SUMA y se reinicia con el total (R-B-03, F3).

    Devuelve un intento NUEVO (el de entrada no se toca) con el lote añadido,
    `qty_total` += pedidas y el MISMO `t_limite` (la caducidad es la de la
    primera señal) y el mismo `bid_senal` (referencia del 3 %). Si hay orden
    viva (`token_agregar` en AGREGANDO o `token_cruce` en CRUZANDO) pasa a
    CANCELANDO y, si se conoce su `id_das_viva`, devuelve su `Cancelar`; sin id
    (DAS aún no la aceptó) no hay nada que cancelar todavía: el decisor la
    cancela al llegar el Accept (la fase CANCELANDO lo marca). Ya CANCELANDO →
    solo suma. Al confirmarse `Canceled`, el decisor reinicia desde F1.4 con
    `orden_agregar` (o cruza si ya pasó `t_limite`). Lanza ValueError con el
    intento TERMINADO, un lote repetido, de otro ticker o con pedidas ≤ 0.
    """
    if intento.fase is FaseIntento.TERMINADO:
        raise ValueError("sumar_senal a un intento terminado: abrir uno nuevo")
    if lote.id in intento.lotes:
        raise ValueError(f"el lote {lote.id!r} ya está en el intento")
    if lote.ticker != intento.ticker:
        raise ValueError(f"lote de {lote.ticker!r} en un intento de {intento.ticker!r}")
    if type(lote.pedidas) is not int or lote.pedidas <= 0:
        raise ValueError(f"lote {lote.id!r} con pedidas no válidas: {lote.pedidas!r}")
    token_vivo: Optional[int] = None
    if intento.fase is FaseIntento.AGREGANDO:
        token_vivo = intento.token_agregar
    elif intento.fase is FaseIntento.CRUZANDO:
        token_vivo = intento.token_cruce
    fase = intento.fase
    acciones: list[Accion] = []
    if token_vivo is not None:
        fase = FaseIntento.CANCELANDO
        if id_das_viva is not None:
            acciones.append(Cancelar(id_das=id_das_viva, token=token_vivo, motivo=MOTIVO_CANCELAR_SUMA))
    nuevo = dataclasses.replace(
        intento,
        lotes=[*intento.lotes, lote.id],
        qty_total=intento.qty_total + lote.pedidas,
        fase=fase,
    )
    return nuevo, acciones


def al_vencer(intento: IntentoEntrada, cot: Optional[Cotizacion], cfg: Config) -> tuple[FaseIntento, Optional[str]]:
    """Qué toca al llegar `t_limite` (temporizador «cruce», F1.7; R-B-01 v3, R-B-02, B11).

    Orden viva o con cancelación sin confirmar → (CANCELANDO, None): el
    decisor cancela y espera `Canceled`. Todo lleno → (TERMINADO,
    MOTIVO_FIN_LLENA). Sin bid → (TERMINADO, MOTIVO_FIN_SIN_COTIZACION). Bid
    actual < bid_senal · (1 − tope_caida_bid_pct/100) → (TERMINADO,
    MOTIVO_FIN_BID_CAYO): no se persigue (un −3 % exacto aún cruza). Si no →
    (CRUZANDO, None). En PM igual (B11). El tope sale del bloque congelado.
    """
    if intento.token_agregar is not None or intento.token_cruce is not None:
        return FaseIntento.CANCELANDO, None
    if intento.llenas >= intento.qty_total:
        return FaseIntento.TERMINADO, MOTIVO_FIN_LLENA
    bid = _bid_utilizable(cot, intento.ticker)
    if bid is None:
        return FaseIntento.TERMINADO, MOTIVO_FIN_SIN_COTIZACION
    if not _bid_dentro_del_tope(bid, intento, cfg):
        return FaseIntento.TERMINADO, MOTIVO_FIN_BID_CAYO
    return FaseIntento.CRUZANDO, None


def resto_a_cruzar(intento: IntentoEntrada) -> int:
    """Acciones que lleva el cruce: qty_total − llenas, SOLO con la cancelación confirmada (injerto §8.7, riesgo 5).

    Si queda un token vivo (orden viva o `Canceled` sin llegar), devuelve 0: el
    resto NUNCA se calcula a partir de lo pedido, porque un fill en vuelo haría
    que el cruce vendiera de más. Contrato: el decisor pone el token a None
    solo al confirmar `Canceled`/`Executed`/rechazo y suma a `llenas` cada fill.
    """
    if intento.token_agregar is not None or intento.token_cruce is not None:
        return 0
    return max(0, intento.qty_total - intento.llenas)


def orden_cruce(intento: IntentoEntrada, resto: int, cot: Optional[Cotizacion], cfg: Config, token: int,
                hora_et: datetime, *, nivel: Optional[Decimal] = None, ssr: bool = False) -> Optional[OrdenNueva]:
    """SS `resto` a bid · (1 − 0,5 %) redondeado ABAJO, ruta «cruzar», sin PostOnly (R-B-01 v3 paso 2).

    None (no se entra) si no hay bid o si el bid actual está por debajo de
    bid_senal · (1 − tope_caida_bid_pct/100) (paso 3; también en el reintento
    con el bid nuevo, F1.8). Con SSR (B19) la venta no puede ir al bid: el
    precio es bid + 1 tick (suelo de la SSR), mismo camino. Porcentajes del
    bloque congelado. Lanza ValueError si el intento no está CRUZANDO, si
    queda un token vivo, o si `resto` no es int, es ≤ 0 o supera lo pendiente
    (qty_total − llenas): el cruce jamás vende más de lo que falta (riesgo 5).
    """
    if intento.fase is not FaseIntento.CRUZANDO:
        raise ValueError(f"orden_cruce con el intento en fase {intento.fase.value}")
    _exigir_sin_orden_viva(intento)
    if type(resto) is not int or resto <= 0:
        raise ValueError(f"resto debe ser int > 0, no {resto!r}")
    if resto > intento.qty_total - intento.llenas:
        raise ValueError(f"resto {resto} mayor que lo pendiente ({intento.qty_total - intento.llenas})")
    bid = _bid_utilizable(cot, intento.ticker)
    if bid is None or not _bid_dentro_del_tope(bid, intento, cfg):
        return None
    if ssr:
        precio = _suelo_sobre_bid(bid)
    else:
        precio = bajo_bid(bid, _pct(_bloque_entrada(intento, cfg), "cruce_bajo_bid_pct", ENTRADA_CRUCE_BAJO_BID_PCT))
    return OrdenNueva(
        token=token,
        lado=Lado.CORTO,
        ticker=intento.ticker,
        ruta=ruta(cfg.rutas, "cruzar", precio, hora_et),
        qty=resto,
        tipo=TipoOrden.LIMITE,
        precio=precio,
        tif="DAY+",
        post_only=False,
        proposito=Proposito.ENTRADA_CRUCE,
        lote_id=intento.lotes[0],
        nivel=nivel,
    )


def repartir_fill(lotes: list[Lote], qty: int, precio: Decimal) -> list[tuple[str, int]]:
    """Reparte un fill entre los lotes del intento en proporción a lo PEDIDO, resto al primero (R-B-03, R-B-02).

    Una entrada (lote_id, acciones) por lote, en el orden recibido; la suma es
    EXACTAMENTE `qty`. Base = floor(qty · pedidas_i / Σ pedidas); lo que sobra
    se da empezando por el primero. Ningún lote pasa de sus pedidas (capacidad
    = pedidas − llenas): lo que no cabe en uno pasa al siguiente. `precio` no
    cambia el reparto: se valida (finito > 0) para que un fill basura no se
    reparta. Lanza ValueError sin lotes, con qty no int o ≤ 0, o si el fill
    excede lo que les falta a todos (sobrellenado: lo trata la reconciliación).
    """
    if not lotes:
        raise ValueError("repartir_fill sin lotes")
    if type(qty) is not int or qty <= 0:
        raise ValueError(f"qty debe ser int > 0, no {qty!r}")
    if not isinstance(precio, Decimal) or not precio.is_finite() or precio <= 0:
        raise ValueError(f"precio de fill no válido: {precio!r}")
    total_pedidas = sum(lote.pedidas for lote in lotes)
    if total_pedidas <= 0:
        raise ValueError("los lotes no piden nada")
    capacidad = [max(0, lote.pedidas - lote.llenas) for lote in lotes]
    if qty > sum(capacidad):
        raise ValueError(f"fill de {qty} mayor que lo que falta a los lotes ({sum(capacidad)})")
    reparto = [min(capacidad[i], qty * lote.pedidas // total_pedidas) for i, lote in enumerate(lotes)]
    sobra = qty - sum(reparto)
    for i in range(len(lotes)):
        if sobra == 0:
            break
        extra = min(sobra, capacidad[i] - reparto[i])
        reparto[i] += extra
        sobra -= extra
    return [(lote.id, n) for lote, n in zip(lotes, reparto)]


def acumular_fill(lote: Lote, qty: int, precio: Decimal) -> Lote:
    """Lote NUEVO con `qty` acciones más a `precio`: llenas += qty y precio_medio ponderado exacto (R-B-02).

    precio_medio = (medio · llenas + precio · qty) / (llenas + qty), en
    Decimal. Es lo que `cerrar_intento` deja como precio del lote. Lanza
    ValueError con qty no int o ≤ 0, precio no válido o si pasa de las pedidas.
    """
    if type(qty) is not int or qty <= 0:
        raise ValueError(f"qty debe ser int > 0, no {qty!r}")
    if not isinstance(precio, Decimal) or not precio.is_finite() or precio <= 0:
        raise ValueError(f"precio de fill no válido: {precio!r}")
    if lote.llenas + qty > lote.pedidas:
        raise ValueError(f"lote {lote.id!r}: {lote.llenas} + {qty} supera las pedidas ({lote.pedidas})")
    llenas = lote.llenas + qty
    medio = (lote.precio_medio * lote.llenas + precio * qty) / llenas
    return dataclasses.replace(lote, llenas=llenas, precio_medio=medio)


def cerrar_intento(intento: IntentoEntrada, lotes: list[Lote]) -> list[Lote]:
    """Fin del intento: cada lote ABRIENDO queda CANCELADO (0 llenas) o ABIERTO con lo llenado (R-B-02).

    Devuelve lotes NUEVOS en el orden recibido; el `precio_medio` ponderado es
    el que fue dejando `acumular_fill` y el stop será proporcional a `llenas`
    (R-C-01, F1.8). Un lote que ya no está ABRIENDO se devuelve igual. Lanza
    ValueError si un lote no pertenece al intento.
    """
    resultado: list[Lote] = []
    for lote in lotes:
        if lote.id not in intento.lotes:
            raise ValueError(f"el lote {lote.id!r} no pertenece al intento de {intento.ticker}")
        if lote.estado is not EstadoLote.ABRIENDO:
            resultado.append(lote)
        elif lote.llenas <= 0:
            resultado.append(dataclasses.replace(lote, estado=EstadoLote.CANCELADO))
        else:
            resultado.append(dataclasses.replace(lote, estado=EstadoLote.ABIERTO))
    return resultado


def fill_peor_de_lo_permitido(precio_fill: Decimal, bid_senal: Decimal, tope_pct: Decimal, *,
                              cruce_pct: Optional[Decimal] = None, ssr: bool = False) -> bool:
    """B13: ¿una venta en corto se llenó por DEBAJO de lo peor que permite la regla? → aviso y se MANTIENE.

    Dos formas (estrictas: el propio suelo no es «peor»):
      * `cruce_pct` None (forma antigua): suelo = bid_senal · (1 − tope_pct/100),
        con `tope_pct` = tope de caída + cruce. En 1-3 $ da falsos avisos: no
        cuenta el redondeo al tick del cruce (D1-05, G1B-19).
      * `cruce_pct` dado (D1-05): `tope_pct` es SOLO el tope de caída del bid
        y el suelo es el PEOR precio legal de R-B-01 v3: el bid más bajo con
        el que aún se cruza (bid_senal · (1 − tope/100) llevado ARRIBA al
        tick: un bid real está en la rejilla) y, desde él, el cruce
        `bajo_bid(bid, cruce_pct)` redondeado ABAJO (§3.14, el mismo cálculo
        que `orden_cruce`). Con `ssr` el cruce va a bid + 1 tick (B19). Así
        un cruce hecho según la regla nunca avisa y uno de un tick menos, sí.
    Un fill mejor que el último se acepta sin más (B13). Lanza ValueError con
    precios no positivos o porcentajes negativos.
    """
    for nombre, valor in (("precio_fill", precio_fill), ("bid_senal", bid_senal)):
        if not isinstance(valor, Decimal) or not valor.is_finite() or valor <= 0:
            raise ValueError(f"{nombre} no válido: {valor!r}")
    tope = de_float(tope_pct)
    if tope < 0:
        raise ValueError(f"tope_pct negativo: {tope_pct!r}")
    if cruce_pct is None:
        return precio_fill < bid_senal * (_CIEN - tope) / _CIEN
    cruce = de_float(cruce_pct)
    if cruce < 0:
        raise ValueError(f"cruce_pct negativo: {cruce_pct!r}")
    bid_minimo = redondear_arriba(bid_senal * (_CIEN - tope) / _CIEN)
    if bid_minimo <= 0:
        return False
    peor = _suelo_sobre_bid(bid_minimo) if ssr else bajo_bid(bid_minimo, cruce)
    return precio_fill < peor


# ── auxiliares privados ───────────────────────────────────────────────
@lru_cache(maxsize=1)
def _et() -> ZoneInfo:
    """Zona de Nueva York, creada la primera vez que se usa (importar el módulo no lee tzdata)."""
    return ZoneInfo("America/New_York")


def _descartar(motivo: str) -> Veredicto:
    return Veredicto(ok=False, motivo=motivo, avisar=motivo not in MOTIVOS_SIN_AVISO)


def _tipo_de(evento: Any) -> str:
    return str(getattr(evento, "tipo", "") or "").strip().lower()


def _referencia_retraso(senal: Senal, evento: Any, precio_senal: Decimal) -> Optional[Decimal]:
    """R-A-01: contra qué precio se mide el retraso (ensayo 28-sep, LXEH 04:50).

    Entrada: `Evento.precio` es el cierre de la vela de la señal. Pirámide:
    `Evento.precio` es el precio del NIVEL (la apertura de la vela en la que el
    motor ejecuta el añadido), que puede quedar muy lejos del último precio
    aunque la señal sea fresca: se mide contra el cierre de la vela que trae la
    fuente en `Senal.feed["close"]`; sin cierre (fuente que no lo manda) no se
    mide: la caducidad (R-B-04) y el tope de caída del bid (R-B-01) siguen
    protegiendo. Devuelve None cuando no hay referencia válida.
    """
    if _tipo_de(evento) != "piramide":
        return precio_senal
    feed = getattr(senal, "feed", None)
    cierre = feed.get("close") if isinstance(feed, dict) else None
    if cierre is None:
        return None
    try:
        valor = de_float(cierre)
    except (ValueError, TypeError, ArithmeticError):
        return None
    return valor if valor > 0 else None


def _accion_piramide(evento: Any) -> str:
    return str(getattr(evento, "accion_piramide", "") or "").strip().lower()


def _validar_senal(senal: Senal) -> Any:
    """Señal de entrada bien formada o ValueError (H-5: el decisor pausa el ticker). Devuelve el `Evento`."""
    if senal.clase != "evento":
        raise ValueError(f"evaluar_senal solo evalúa señales «evento», no {senal.clase!r}")
    if not isinstance(senal.id, str) or not senal.id:
        raise ValueError("señal sin id: sin él no hay idempotencia (R-A-05)")
    if not isinstance(senal.ticker, str) or not senal.ticker:
        raise ValueError("señal sin ticker")
    evento = senal.evento
    if evento is None:
        raise ValueError("señal sin evento")
    if getattr(evento, "ticker", senal.ticker) != senal.ticker:
        raise ValueError(f"evento de {getattr(evento, 'ticker', None)!r} en una señal de {senal.ticker!r}")
    if not getattr(evento, "strategy_id", None):
        raise ValueError("evento sin strategy_id")
    if _tipo_de(evento) != "entrada" and not es_piramide_add(evento):
        raise ValueError(f"evento {_tipo_de(evento)!r}/{_accion_piramide(evento)!r} no es una entrada")
    return evento


def _exigir_aware(ahora_et: datetime) -> None:
    if not isinstance(ahora_et, datetime) or ahora_et.tzinfo is None or ahora_et.tzinfo.utcoffset(ahora_et) is None:
        raise ValueError(f"ahora_et debe ser un datetime aware en ET, no {ahora_et!r}")


def _exigir_libro(cot: Optional[Cotizacion], ticker: str) -> None:
    """Bid y ask > 0 y no cruzados: un `bid_senal` de 0 anularía el tope del 3 % (todo bid lo cumpliría)."""
    if cot is None or not _precio_ok(cot.bid) or not _precio_ok(cot.ask):
        raise ValueError(f"sin bid/ask válidos de {ticker}")
    if cot.ask < cot.bid:
        raise ValueError(f"libro cruzado en {ticker}: bid {cot.bid} > ask {cot.ask}")
    if cot.ticker != ticker:
        raise ValueError(f"cotización de {cot.ticker!r} para {ticker!r}")


def _exigir_sin_orden_viva(intento: IntentoEntrada) -> None:
    if intento.token_agregar is not None or intento.token_cruce is not None:
        raise ValueError(f"{intento.ticker}: ya hay una orden viva (agregar={intento.token_agregar}, "
                         f"cruce={intento.token_cruce})")


def _precio_ok(valor: Optional[Decimal]) -> bool:
    return isinstance(valor, Decimal) and valor.is_finite() and valor > 0


def _cotizacion_valida(cot: Optional[Cotizacion], ahora: float, max_edad_s: float) -> bool:
    """Comprobación 8: bid, ask y último > 0, ask ≥ bid y actualizada hace ≤ max_edad_s (monotónico)."""
    if cot is None or not (_precio_ok(cot.bid) and _precio_ok(cot.ask) and _precio_ok(cot.last)):
        return False
    if cot.ask < cot.bid:
        return False
    if cot.actualizada_en is None:
        return False
    return ahora - cot.actualizada_en <= max_edad_s


def _bid_utilizable(cot: Optional[Cotizacion], ticker: str) -> Optional[Decimal]:
    if cot is None or not _precio_ok(cot.bid):
        return None
    if cot.ticker != ticker:
        raise ValueError(f"cotización de {cot.ticker!r} para {ticker!r}")
    return cot.bid


def _suelo_sobre_bid(bid: Decimal) -> Decimal:
    """bid + 1 tick al tick: lo mínimo que DESCANSA en una venta, y el suelo de la SSR (B19)."""
    return redondear_arriba(bid + tick_de(bid))


def _bloque_entrada(intento: IntentoEntrada, cfg: Config) -> dict:
    return intento.cfg_congelada if intento.cfg_congelada is not None else cfg.entrada


def _bid_dentro_del_tope(bid: Decimal, intento: IntentoEntrada, cfg: Config) -> bool:
    """R-B-01 v3: el bid actual no ha caído MÁS del tope desde `bid_senal` (−3 % exacto está dentro)."""
    tope = _pct(_bloque_entrada(intento, cfg), "tope_caida_bid_pct", ENTRADA_TOPE_CAIDA_BID_PCT)
    return bid >= intento.bid_senal * (_CIEN - tope) / _CIEN


def _pct(bloque: Optional[dict], clave: str, defecto: Decimal) -> Decimal:
    """Porcentaje del cuadro en Decimal (el JSON trae float); ausente o null → defecto del libro."""
    valor = (bloque or {}).get(clave)
    return defecto if valor is None else de_float(valor)


def _pct_opcional(bloque: Optional[dict], clave: str, defecto: Optional[Decimal]) -> Optional[Decimal]:
    """Como `_pct`, pero null EXPLÍCITO = apagada (B20 bis); clave ausente = defecto del libro."""
    bloque = bloque or {}
    if clave not in bloque:
        return defecto
    valor = bloque[clave]
    return None if valor is None else de_float(valor)


def _segundos(bloque: Optional[dict], clave: str, defecto: int) -> float:
    valor = (bloque or {}).get(clave)
    if valor is None:
        return float(defecto)
    if isinstance(valor, bool) or not isinstance(valor, (int, float, Decimal)):
        raise ValueError(f"{clave} no es un número de segundos: {valor!r}")
    segundos = float(valor)
    if not math.isfinite(segundos) or segundos < 0:
        raise ValueError(f"{clave} fuera de rango: {valor!r}")
    return segundos


def _en_halt(pos: Optional[PosicionTicker], simb: EstadoSimbolo) -> bool:
    """TA H/P (misma regla que `halts.es_halt`, que vive en otro lote) o ticker marcado HALT por el decisor."""
    ta = str(simb.ta or "").strip().upper()
    return ta in _TA_HALT or (pos is not None and pos.estado is EstadoTicker.HALT)


def _lado_prohibido(pos: Optional[PosicionTicker], evento: Any) -> bool:
    """R-E-01: el bot solo abre CORTOS; y nunca contra un lote vivo de otro lado ni con neta larga."""
    if str(getattr(evento, "direccion", "") or "").strip().lower() != "short":
        return True
    if pos is None:
        return False
    if pos.neta > 0:
        return True
    return any(lote.estado in _VIVOS and str(lote.direccion).strip().lower() != "short"
               for lote in pos.lotes.values())


def _modo_seguridad_bloquea(bloque: Optional[dict], cot: Cotizacion) -> bool:
    """R-I-04: con el interruptor encendido, último ≥ precio_min Y volumen × VWAP ≥ mínimo; si no se sabe, no."""
    bloque = bloque or {}
    if not bloque.get("activo"):
        return False
    precio_min = _pct(bloque, "precio_min", MODO_SEGURIDAD_PRECIO_MIN)
    dolares_min = _pct(bloque, "acum_dollar_volume_min", MODO_SEGURIDAD_DOLLAR_VOLUME_MIN)
    if not _precio_ok(cot.last) or cot.last < precio_min:
        return True
    # Acum. Dollar Volume ≈ V × VWAP del $Quote de DAS (pregunta 9; misma cuenta que MercadoDAS.dollar_volume).
    if cot.volumen is None or isinstance(cot.volumen, bool) or not _precio_ok(cot.vwap):
        return True
    return Decimal(cot.volumen) * cot.vwap < dolares_min


def _lote_base_vivo(pos: Optional[PosicionTicker], evento: Any) -> Optional[Lote]:
    """El lote base (no pirámide) vivo y con acciones de la estrategia del evento; None si no hay o hay dudas."""
    if pos is None:
        return None
    strategy_id = getattr(evento, "strategy_id", None)
    entrada_idx = getattr(evento, "entrada_idx", None)
    candidatos = [
        lote for lote in pos.lotes.values()
        if lote.strategy_id == strategy_id and lote.nivel_piramide is None
        and lote.estado in (EstadoLote.ABRIENDO, EstadoLote.ABIERTO) and lote.llenas > 0
        and (entrada_idx is None or lote.entrada_idx is None or lote.entrada_idx == entrada_idx)
    ]
    return candidatos[0] if len(candidatos) == 1 else None


def _reentrada_prohibida(pos: Optional[PosicionTicker], estrategia: EstrategiaConfig, evento: Any) -> bool:
    """Comprobación 14 (R-D-04, R-F-03, R-G-03, R-E-03). Una pirámide «add» no es reentrada (solo le afecta el veto).

    Aquí quedan solo lo que `salidas.puede_reentrar` no mira: el veto
    `sin_reentrada_hasta_sigue` (también lo mira ella), R-E-03 (versiones
    viejas de la estrategia) y la exención de la pirámide «add». Todo lo
    demás (lote base vivo, entradas previas, accept_reentries /
    max_reentries) lo decide `puede_reentrar`, que tiene el MISMO if/elif que
    el backtester (`portfolio_sim.py` l.2314-2318) y el motor de alertas: una
    sola fuente de verdad (D1-04, D2-salidas-rechazos-11; memoria
    «max_reentries = -1»): −1 → manda accept_reentries; 0 → ninguna; N > 0 →
    hasta N aunque accept_reentries sea false; < −1 → no (conservador).
    """
    if pos is None:
        return False
    if pos.sin_reentrada_hasta_sigue:
        return True
    propios = [lote for lote in pos.lotes.values() if lote.strategy_id == estrategia.strategy_id]
    # R-E-03: un lote nacido con otra versión de la estrategia.
    viejos = [lote for lote in propios
              if lote.version_estrategia and lote.version_estrategia != estrategia.definition_hash]
    if any(lote.estado in _VIVOS for lote in viejos):
        return True
    if viejos and estrategia.al_desactivar != _AL_DESACTIVAR_REINICIAR:
        return True
    if es_piramide_add(evento):
        return False
    permitida, _motivo = puede_reentrar(estrategia, None, pos)
    return not permitida


def _locates_libres(estado: EstadoBot, ticker: str, strategy_id: Optional[str], pedidas: int) -> int:
    """R-H-04 + E9 (D1-02, G1A-07): lo que cubre `locates.asignar_a_lote`, la MISMA regla que usa el decisor.

    Propias (localizadas − usadas) + sobrantes de las demás estrategias del
    ticker (sin quitarles lo que necesitan para sí) + ETB («no_hace_falta»
    en CUALQUIER registro del ticker: no limita). Sin nada → 0.
    """
    if not strategy_id or type(pedidas) is not int or pedidas <= 0:
        return 0
    return sum(n for _, n in asignar_a_lote(estado.locates, ticker, pedidas, strategy_id))
