"""Reconciliación diario ↔ DAS: los 6 casos, barrido adaptativo, caducidad y acumulador de volcados.

QUÉ HACE. Compara lo que el bot cree (su `EstadoBot`: lotes, libro de fills,
órdenes por token) con lo que DAS dice en un barrido (`GET POSITIONS/ORDERS`
o el volcado del LOGIN) y lo clasifica en los casos de R-C-10 ampliados:
  1 coincide · 2 los stops difieren (o hay órdenes nuestras huérfanas) ·
  3 posición conocida SIN stop · 4 algo AJENO (orden de otro origen o posición
  que ningún diario conoce: intervención humana, R-K-02 / R-M-03) · 5 el
  diario la tiene abierta y DAS plana · 6 neta de fills ≠ neta de DAS.
`acciones` convierte cada discrepancia en lo que hay que hacer (plan de stops,
protección + aviso 3 + el ticker al humano (R-M-03 por ticker, Jaume
29-sep; antes pausa global), lotes cerrados, «DAS manda»).
`cadencia_barrido`, `comandos_barrido` y `barrido_caducado` son R-K-01 y
R-K-03; `AcumuladorVolcado` junta un volcado en una foto completa (§5.11).
También ofrece las piezas que comparte con `reglas.vigilancia`: `es_ajena`,
`orden_de_msg`, `cobertura` y `huerfanas`.

POR QUÉ ESTÁ AQUÍ. Es lógica PURA (sin reloj, I/O, red ni logging): recibe el
estado, la foto de DAS y `ahora`/`hora_et` como parámetros y devuelve
`Discrepancia` y `Accion` que el decisor ejecuta en orden (F10, F12). Importa
solo `tipos`, `tokens`, `reglas.precios` y `reglas.stops` (la aritmética de
los stops es UNA, la de `stops.plan`).

LAS TRAMPAS.
  * «Ajena» = `orderSrc` presente y distinto de CMDAPI, o token que no es
    nuestro HOY (`tokens.es_nuestro`: un token de AYER es ajeno, 2f.5). Una
    ajena ya tratada está en `estado.ordenes_ajenas` y no se vuelve a avisar;
    las canceladas o rechazadas sin nada ejecutado no afectan a la posición y
    no se consideran (si no, cada reinicio pausaría por órdenes muertas).
    E2c-01: cada caso 4 anota SIEMPRE `ajenas_tratadas` {ticker, ids}; el
    diario las repone en `estado.ordenes_ajenas` al reconstruir, así un
    reinicio no vuelve a pausar por las mismas órdenes manuales.
  * Un barrido puede llegar INCOMPLETO (un BP empujado que cierra el volcado
    antes de tiempo, un volcado sin marcadores, §5.11). Por eso: (a) un ticker
    AUSENTE de las posiciones de DAS es «sin información», nunca «plano»: los
    casos 4/5/6 y la clasificación de stops exigen que DAS lo liste (una
    posición cerrada hoy sigue en la lista con 0); (b) las órdenes vivas son
    la UNIÓN de lo que DAS lista y lo nuestro que DAS no contradice (una orden
    nuestra que DAS no menciona se da por viva, salvo una Sending sin eco
    pasados `SIN_ECO_S`): así un volcado a medias nunca duplica un stop
    (riesgo 11).
  * Riesgo 8 (orden de `Execute`/`%TRADE`/`%POS` no documentado): durante
    `GRACIA_TRAS_FILL_S` tras el último fill, un ticker con neta de fills ≠
    neta de DAS NO se clasifica (DAS puede ir por detrás); pasada la gracia,
    manda DAS (caso 6, M7). Sin `ahora` no hay gracia (contrato de §3.24).
  * `comparar` es PURA. `acciones` MUTA el estado a propósito (como
    `stops.limpieza_tras_fill_stop`) y lo deja escrito con `Anotar` ANTES de
    las órdenes para que `diario.reconstruir` lo reproduzca (H-2): caso 4 →
    ticker en CONTROL_HUMANO + `intervencion_humana` (registro «pausa» CON
    ticker, Jaume 29-sep) y `ordenes_ajenas`; caso 5 →
    lotes CERRADO + neta 0 («discrepancia»); caso 6 → `neta_fills := neta_das`
    («discrepancia»). Además ADOPTA en `estado.ordenes` las órdenes nuestras
    que DAS tiene y el ejecutor no (las del vigilante, F13): sin eso el plan
    por evento las ignoraría y duplicaría stops.
  * Las protecciones de R-C-10 (4) (`stops.stop_proteccion`) salen sin
    `serie`: un `InvalidarSerie` de un fill no debe descartarlas. Se cuenta
    como cobertura TODA STOPLMTP nuestra viva del lado que reduce (incluida
    Sending): lo ajeno no cubre (puede desaparecer sin aviso) y si hubiera
    doble compra la limpieza R-C-11 vende el exceso.
  * En cisne negro (`EstadoTicker.BS`) no se repone ni se protege (R-G-03):
    el caso sale 1 con el motivo.
"""
from __future__ import annotations

import html
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from app.bot_das import tokens as mod_tokens
from app.bot_das.protocolo import cmd_get
from app.bot_das.reglas import stops
from app.bot_das.reglas.precios import de_float
from app.bot_das.tipos import (
    BARRIDO_CON_POSICIONES_S,
    BARRIDO_SIN_NADA_S,
    BARRIDO_TRAS_FILL_S,
    BARRIDO_VENTANA_TRAS_FILL_S,
    RECONCILIACION_CADUCA_S,
    STOP_PROTECCION_PCT,
    Accion,
    Anotar,
    Avisar,
    Cancelar,
    Consultar,
    Cotizacion,
    EnviarOrden,
    EstadoBot,
    EstadoLote,
    EstadoOrden,
    EstadoTicker,
    FaseIntento,
    Grupo,
    Lado,
    Lote,
    MensajeDAS,
    MsgBP,
    MsgMarcador,
    MsgOrden,
    MsgPos,
    MsgTrade,
    Nivel,
    Orden,
    PosicionTicker,
    Proposito,
    Reemplazar,
    TipoOrden,
)

# ── casos (R-C-10 ampliado, §3.24) ───────────────────────────────────────
CASO_COINCIDE = 1
CASO_STOP_DIFIERE = 2
CASO_SIN_STOP = 3
CASO_AJENA = 4
CASO_CERRADA_EN_DAS = 5
CASO_NETA_DISTINTA = 6
CASOS = (CASO_COINCIDE, CASO_STOP_DIFIERE, CASO_SIN_STOP, CASO_AJENA, CASO_CERRADA_EN_DAS, CASO_NETA_DISTINTA)

ORDER_SRC_PROPIO = "CMDAPI"          # manual L369-371: «CMDAPI means the order is entered by API» (R-K-02)
GRACIA_TRAS_FILL_S = 2.0             # riesgo 8: margen para que %POS alcance a los fills antes de que «DAS mande»
SIN_ECO_S = 5.0                      # una orden nuestra Sending que DAS no lista pasado esto no salió (riesgo 3)
ESPERA_SIN_MARCADORES_S = 0.5        # §5.11: volcado sin marcadores = 500 ms sin líneas nuevas
# R-K-01 (+ GET TRADES tras un fill). A-06: con `protocolo.cmd_get` (nombres cerrados); mismas cadenas que antes.
COMANDOS_BARRIDO = (cmd_get("POSITIONS"), cmd_get("ORDERS"), cmd_get("BP"), cmd_get("LOCATES"))
COMANDO_TRADES = cmd_get("TRADES")
PETICION_PAUSA_GLOBAL = "pausa"      # tipo del diario que `reconstruir` convierte en pausa_global (sin «ticker»)
PETICION_PAUSA = PETICION_PAUSA_GLOBAL  # con «ticker»: `reconstruir` pausa ESE ticker (R-M-03 por ticker, Jaume 29-sep)
MOTIVO_INTERVENCION_HUMANA = "intervención humana"   # prefijo del motivo del CONTROL_HUMANO por R-M-03 (Jaume 29-sep)
# R-M-03 por ticker: estos estados pasan a CONTROL_HUMANO; BS, SIN_SIMBOLO y CONTROL_HUMANO conservan el suyo.
_ESTADOS_A_CONTROL_HUMANO = frozenset({EstadoTicker.NORMAL, EstadoTicker.PAUSADO, EstadoTicker.HALT})
ANOTACION_AJENAS = "ajenas_tratadas"  # E2c-01: {ticker, ids}; `diario.reconstruir` las mete en `estado.ordenes_ajenas`

_LOTE_MUERTO = (EstadoLote.CERRADO, EstadoLote.CANCELADO)
_RE_NUMERO = re.compile(r"\d+(?:[.,]\d+)*")
_RE_TIPO_STOP = re.compile(stops.TIPO_STOP_EN_ORDER, re.IGNORECASE)
_LADOS = {"B": Lado.COMPRA, "BUY": Lado.COMPRA, "S": Lado.VENTA, "SELL": Lado.VENTA,
          "SS": Lado.CORTO, "SHRT": Lado.CORTO, "SHORT": Lado.CORTO}
_BLOQUES_INICIO = {"#POS": "POS", "#Order": "Order", "#Trade": "Trade"}
_BLOQUES_FIN = {"#POSEND": "POS", "#OrderEnd": "Order", "#TradeEnd": "Trade"}
_RUTA_STOP_DEFECTO = "STOP"


@dataclass(frozen=True)
class Discrepancia:
    """Un ticker y su caso (1-6, R-C-10 ampliado). Los campos tras `detalle` son opcionales sobre §3.24.

    `vivas` son las órdenes NUESTRAS del ticker tal como quedan tras cruzar
    el estado con DAS (copias; lo que `acciones` le pasa a `stops.plan`),
    `ajenas` las órdenes ajenas NUEVAS (caso 4) y `huerfanas` las órdenes
    nuestras vivas que agrandarían la posición en el sentido equivocado. No
    entran en la igualdad ni en el hash.
    """
    ticker: str
    caso: int
    detalle: str
    neta_das: Optional[int] = None
    neta_fills: Optional[int] = None
    descubiertas: int = 0
    avg_das: Optional[Decimal] = None
    vivas: tuple[Orden, ...] = field(default=(), compare=False, repr=False)
    ajenas: tuple[MsgOrden, ...] = field(default=(), compare=False, repr=False)
    huerfanas: tuple[Orden, ...] = field(default=(), compare=False, repr=False)

    def __post_init__(self) -> None:
        if self.caso not in CASOS:
            raise ValueError(f"caso de reconciliación desconocido: {self.caso!r} (1-6)")


# ── piezas compartidas con reglas.vigilancia ─────────────────────────────
def es_ajena(m: MsgOrden, hoy: date) -> bool:
    """R-K-02 / R-M-03: una orden es AJENA si `orderSrc` existe y no es CMDAPI, o si su token no es nuestro HOY.

    `orderSrc` solo viene en el `%ORDER` de 19 campos (Montage, Hotkey,
    Basket, AutoStop…, manual L369-371); sin él decide el token
    (`tokens.es_nuestro`, que rechaza los de AYER a propósito, 2f.5). Un
    `order_src` vacío cuenta como ausente.
    """
    origen = str(m.order_src).strip() if m.order_src is not None else ""
    if origen and origen.upper() != ORDER_SRC_PROPIO:
        return True
    return not mod_tokens.es_nuestro(m.token, hoy)


def orden_de_msg(m: MsgOrden, hoy: date, conocida: Optional[Orden] = None,
                 cfg_stops: Optional[Mapping] = None) -> Optional[Orden]:
    """F13 / corrección 3: la `Orden` NUESTRA que describe un `%ORDER` de DAS (None si es ajena o su lado no se entiende).

    Con `conocida` (la del estado del ejecutor) se devuelve una COPIA con lo
    que DAS dice (id, estado, qty, lvqty, cxlqty, tipo crudo) y el resto
    nuestro (propósito, lote, nivel, precios). Sin ella (órdenes del
    vigilante, o de un diario perdido) se construye con propósito DESCONOCIDA
    (`stops.plan` lo infiere) y `Origen` del token. El tipo de un stop se
    reconoce por `stops.TIPO_STOP_EN_ORDER` o `tipo_esperado_en_order`
    (PROVISIONAL, riesgo 1): disparo = primer número del tipo («SLP: 2.97
    2.99»), límite = el segundo; sin números, el campo precio (mismo criterio
    que `stops.inferir_proposito`). `llenas` solo se deduce de DAS en
    Partial/Triggered con `lvqty` > 0: en Accepted un `lvqty` 0 no documentado
    no puede convertir un stop vivo en muerto (duplicaría el stop, riesgo 11).
    """
    if es_ajena(m, hoy):
        return None
    partes = mod_tokens.descomponer(m.token)   # type: ignore[arg-type]
    lado = _LADOS.get(str(m.lado).strip().upper())
    if partes is None or lado is None or not str(m.ticker).strip():
        return None
    qty = _entero_no_negativo(m.qty)
    lvqty = _entero_no_negativo(m.lvqty)
    cxlqty = _entero_no_negativo(m.cxlqty)
    parcial = m.estado in (EstadoOrden.PARTIAL, EstadoOrden.TRIGGERED) and lvqty > 0
    if conocida is not None:
        llenas = conocida.llenas
        if parcial:
            llenas = max(llenas, qty - lvqty - cxlqty)
        return replace(conocida, id_das=m.id, estado=m.estado, qty=qty if qty > 0 else conocida.qty, lvqty=lvqty,
                       cxlqty=cxlqty, llenas=max(llenas, 0), tipo_das_crudo=m.tipo)
    tipo, stop, limite = _tipo_y_precios(m, cfg_stops)
    return Orden(token=m.token, ticker=str(m.ticker).strip(), lado=lado, tipo=tipo, qty=qty,   # type: ignore[arg-type]
                 precio=limite, stop=stop, ruta=m.ruta, proposito=Proposito.DESCONOCIDA, lote_id=None, nivel=None,
                 origen=partes[0], id_das=m.id, estado=m.estado, lvqty=lvqty,
                 llenas=max(qty - lvqty - cxlqty, 0) if parcial else 0, cxlqty=cxlqty, tipo_das_crudo=m.tipo)


def cobertura(vivas: Iterable[Any], ticker: str, neta: int, solo_confirmadas: bool = False) -> int:
    """R-C-03 / R-C-10 (4): acciones que cubren las STOPLMTP NUESTRAS vivas del lado que REDUCE la posición.

    Corta (neta < 0) → stops de COMPRA; larga → stops de VENTA; plana → 0.
    Cuenta la cantidad VIVA (`lvqty` en Partial/Triggered, si no qty −
    llenas; nunca lo pedido, injerto §8.7). Con `solo_confirmadas` no cuentan
    las Sending («stop aceptado» de R-C-03); sin él sí (para no poner otra
    protección mientras la primera viaja, riesgo 11). Cualquier propósito y
    cualquier `Origen` nuestro.
    """
    if neta == 0:
        return 0
    lado = Lado.COMPRA if neta < 0 else Lado.VENTA
    estados = stops.ESTADOS_CONFIRMADOS if solo_confirmadas else stops.ESTADOS_VIVOS
    return sum(_qty_viva(o) for o in _unicas(vivas)
               if o.ticker == ticker and o.tipo is TipoOrden.STOP_LIMITE_PP and o.lado is lado and o.estado in estados)


def huerfanas(vivas: Iterable[Any], ticker: str, neta: int) -> list[Orden]:
    """R-C-11 (2)-(3): órdenes NUESTRAS vivas que agrandarían la posición en el sentido equivocado.

    Con la posición plana o larga, cualquier COMPRA nuestra viva (un stop o
    una protección que ya no tienen corto que cubrir dejarían la cuenta
    LARGA); con la posición plana o corta, cualquier VENTA nuestra viva (una
    venta de exceso o la protección de un largo que ya no existe abrirían un
    corto sin stop). Las SS (entradas) nunca son huérfanas. Ordenadas de la
    más antigua a la más nueva.
    """
    salida = [o for o in _unicas(vivas) if o.ticker == ticker and o.estado in stops.ESTADOS_VIVOS and _qty_viva(o) > 0
              and ((o.lado is Lado.COMPRA and neta >= 0) or (o.lado is Lado.VENTA and neta <= 0))]
    salida.sort(key=_clave_antiguedad)
    return salida


# ── comparar (R-C-10, R-K-01, R-K-02, R-M-03, corrección 2) ───────────────
def comparar(estado: EstadoBot, pos_das: Mapping[str, MsgPos], ord_das: Mapping[int, MsgOrden], hoy: date, cfg: Any,
             ahora: Optional[float] = None, limit_up_de: Optional[Callable[[str], Optional[Decimal]]] = None,
             gracia_s: float = GRACIA_TRAS_FILL_S) -> list[Discrepancia]:
    """R-C-10 (casos 1-4) + R-K-01/02 + caso 5 y 6 (M7, corrección 2): diario y fills contra la foto de DAS. PURA.

    Por ticker (en orden alfabético) puede salir un caso 4 por órdenes ajenas
    NUEVAS (orderSrc ≠ CMDAPI o token no nuestro hoy, que no estén ya en
    `estado.ordenes_ajenas` y que estén vivas o hayan ejecutado algo) y,
    además, UN caso de posición:
      - posición que ningún diario conoce (sin lotes con acciones y sin neta
        de fills) y DAS ≠ 0 → 4 con `descubiertas` = lo que no cubre ya una
        STOPLMTP nuestra viva (si todo está cubierto, 1);
      - conocida y DAS plana → 5; conocida con neta DAS ≠ neta de fills → 6
        (ninguna de las dos dentro de la gracia tras un fill, riesgo 8);
      - conocida y cuadra → se simula `stops.plan` sobre las órdenes vivas:
        falta alguna o no hay ningún stop → 3; hay que ajustar o cancelar, o
        hay órdenes huérfanas → 2; nada → 1. En cisne negro → 1 (R-G-03).
    Un ticker que DAS no lista no se clasifica (sin información: ver
    trampas). `ahora`, `limit_up_de` y `gracia_s` son opcionales sobre §3.24.
    `cfg` es la `Config` (o un dict con «stops»).
    """
    cfg_stops = _bloque_stops(cfg)
    ruta_prueba = _ruta_stop_de(cfg)
    en_gracia = ahora is not None and estado.ultimo_fill_en is not None and ahora - estado.ultimo_fill_en < gracia_s
    vivas_por_ticker, ajenas_por_ticker = _vivas_y_ajenas(estado, ord_das, hoy, ahora, cfg_stops)
    tickers = set(pos_das) | set(ajenas_por_ticker) | set(vivas_por_ticker)
    tickers |= {t for (t, p) in estado.posiciones.items() if _conocida(p)}
    salida: list[Discrepancia] = []
    for ticker in sorted(tickers):
        ajenas = tuple(ajenas_por_ticker.get(ticker, ()))
        vivas = tuple(vivas_por_ticker.get(ticker, ()))
        msg = pos_das.get(ticker)
        pos = estado.posiciones.get(ticker)
        conocida = _conocida(pos)
        if ajenas and (msg is None or conocida):
            neta_d = msg.neta if msg is not None else None
            salida.append(Discrepancia(ticker, CASO_AJENA, _texto_ajenas(ajenas), neta_das=neta_d,
                                       neta_fills=pos.neta_fills if pos is not None else None, vivas=vivas, ajenas=ajenas))
        if msg is None:
            continue
        neta_d = int(msg.neta)
        avg = _precio_o_none(msg.avg)
        if not conocida:
            salida.extend(_caso_desconocida(ticker, neta_d, avg, vivas, ajenas, pos))
            continue
        neta_f = pos.neta_fills   # type: ignore[union-attr]
        if neta_d != neta_f:
            if en_gracia:
                continue
            caso = CASO_CERRADA_EN_DAS if neta_d == 0 else CASO_NETA_DISTINTA
            detalle = (f"R-C-10 (5): el diario tiene {ticker} abierta ({neta_f}) y DAS la da plana" if neta_d == 0 else
                       f"M7: neta de fills {neta_f} ≠ neta de DAS {neta_d} en {ticker}: manda DAS")
            salida.append(Discrepancia(ticker, caso, detalle, neta_das=neta_d, neta_fills=neta_f, avg_das=avg, vivas=vivas,
                                       huerfanas=tuple(huerfanas(vivas, ticker, neta_d))))
            continue
        if neta_d == 0:
            salida.append(Discrepancia(ticker, CASO_CERRADA_EN_DAS,
                                       f"R-C-10 (5): {ticker} plana en DAS y en los fills con lotes aún abiertos",
                                       neta_das=0, neta_fills=0, avg_das=avg, vivas=vivas,
                                       huerfanas=tuple(huerfanas(vivas, ticker, 0))))
            continue
        salida.append(_clasificar_stops(pos, neta_d, avg, vivas, cfg_stops,   # type: ignore[arg-type]
                                        limit_up_de(ticker) if limit_up_de is not None else None, hoy, ruta_prueba))
    return salida


# ── acciones (R-C-10, R-K-02, R-M-03, M7, R-C-11) ─────────────────────────
def acciones(discrepancias: Iterable[Discrepancia], estado: EstadoBot, cot_de: Callable[[str], Optional[Cotizacion]],
             cfg: Any, tokens: Callable[[], int], hora_et: datetime, ruta_stop: str,
             limit_up_de: Optional[Callable[[str], Optional[Decimal]]] = None) -> list[Accion]:
    """R-C-10 / R-K-02 / R-M-03 / M7: lo que hay que hacer con cada discrepancia, en orden. MUTA el estado (ver trampas).

    1 → nada. 2/3 → `stops.plan` sobre las órdenes vivas de la discrepancia
    (+ cancelar huérfanas; + protección si hay corto sin ningún stop
    calculable; 3 además Avisar(2) «sin stop»). 4 → registra las ajenas,
    el ticker en CONTROL_HUMANO hasta /sigue X (Anotar «pausa» con ticker;
    R-M-03 por ticker, Jaume 29-sep), protección
    `stops.stop_proteccion` por lo descubierto (al `proteccion_desconocidas_pct`
    del último precio; sin cotización, del precio medio de DAS; sin nada,
    aviso para ponerla a mano), cancela huérfanas y Avisar(3). 5 → lotes
    CERRADO (Anotar «lote»), neta 0 (Anotar «discrepancia»), cancela nuestras
    órdenes huérfanas y Avisar(2). 6 → `neta_fills := neta_das` (Anotar
    «discrepancia») + Avisar(2) y: sigue corta → como 2/3; LARGA →
    `stops.limpieza_tras_fill_stop` (vende SOLO el exceso, R-C-11 b); plana
    no llega aquí (es el 5). `limit_up_de` es opcional sobre §3.24. Adopta en
    `estado.ordenes` las órdenes nuestras que el ejecutor no tenía (F13).
    """
    cfg_stops = _bloque_stops(cfg)
    salida: list[Accion] = []
    for d in discrepancias:
        _adoptar(estado, d.vivas)
        if d.caso == CASO_COINCIDE:
            continue
        ticker = d.ticker
        pos = estado.posiciones.get(ticker)
        cot = cot_de(ticker)
        limit_up = limit_up_de(ticker) if limit_up_de is not None else None
        version = pos.version_stops if pos is not None else 0
        if d.caso in (CASO_STOP_DIFIERE, CASO_SIN_STOP):
            if pos is not None and d.neta_das is not None:
                if pos.neta_das != d.neta_das:
                    # R3-SAL-1: una cifra nueva sin hora conocida queda SIN confirmar (`salidas.das_confirmada`): la
                    # hora de un %POS viejo no puede dar por buena la cifra de este volcado. El decisor, que sí sabe
                    # cuándo pidió el barrido, la fecha por su cuenta antes de llegar aquí.
                    pos.neta_das_en = None
                pos.neta_das = d.neta_das
            salida.extend(_reparar_stops(d, pos, cot, cfg, cfg_stops, tokens, hora_et, ruta_stop, version, limit_up))
            if d.caso == CASO_SIN_STOP:
                salida.append(Avisar(nivel=Nivel.AVISO, grupo=Grupo.B, clave=f"reconciliacion_sin_stop:{ticker}",
                                     texto=f"R-C-10 (3): {ticker} tenía posición sin stop en DAS; se reponen los stops"))
        elif d.caso == CASO_AJENA:
            salida.extend(_caso_ajena(d, estado, pos, cot, cfg_stops, tokens, ruta_stop, version))
        elif d.caso == CASO_CERRADA_EN_DAS:
            salida.extend(_caso_cerrada(d, pos))
        else:
            salida.extend(_caso_neta_distinta(d, pos, cot, cfg, cfg_stops, tokens, hora_et, ruta_stop, limit_up))
    return salida


# ── barrido (R-K-01, R-K-03) ──────────────────────────────────────────────
def cadencia_barrido(estado: EstadoBot, ahora: float, cfg_tec: Optional[Mapping]) -> float:
    """R-K-01 (matiz 21-sep): 1 s tras un fill (ventana 60 s) o con una entrada viva; 2 s con posiciones u órdenes vivas; 10 s sin nada.

    Los segundos salen de `cfg.tecnicos.barrido_s` (tras_fill,
    ventana_tras_fill_s, con_posiciones, sin_nada); ausentes o no positivos →
    constantes de tipos. Un fill «en el futuro» (reloj monotónico de otro
    arranque) cuenta como reciente: lo prudente es barrer más.
    """
    barrido = cfg_tec.get("barrido_s") if isinstance(cfg_tec, Mapping) else None
    barrido = barrido if isinstance(barrido, Mapping) else {}
    tras_fill = _segundos(barrido.get("tras_fill"), BARRIDO_TRAS_FILL_S)
    ventana = _segundos(barrido.get("ventana_tras_fill_s"), BARRIDO_VENTANA_TRAS_FILL_S)
    con_posiciones = _segundos(barrido.get("con_posiciones"), BARRIDO_CON_POSICIONES_S)
    sin_nada = _segundos(barrido.get("sin_nada"), BARRIDO_SIN_NADA_S)
    if estado.ultimo_fill_en is not None and ahora - estado.ultimo_fill_en < ventana:
        return tras_fill
    posiciones = list(estado.posiciones.values())
    if any(p.intento is not None and p.intento.fase is not FaseIntento.TERMINADO for p in posiciones):
        return tras_fill
    con_algo = any(p.neta_fills != 0 or (p.neta_das is not None and p.neta_das != 0) for p in posiciones)
    if con_algo or any(o.estado in stops.ESTADOS_VIVOS for o in estado.ordenes.values()):
        return con_posiciones
    return sin_nada


def comandos_barrido(tras_fill: bool) -> list[Consultar]:
    """R-K-01: GET POSITIONS, GET ORDERS (+ GET TRADES tras un fill), GET BP y GET LOCATES, en ESE orden.

    GET BP va después de las listas a propósito: su respuesta cierra el
    volcado en `AcumuladorVolcado` aunque DAS no mande marcadores (§5.11).
    """
    comandos = [Consultar(COMANDOS_BARRIDO[0]), Consultar(COMANDOS_BARRIDO[1])]
    if tras_fill:
        comandos.append(Consultar(COMANDO_TRADES))
    comandos.extend(Consultar(c) for c in COMANDOS_BARRIDO[2:])
    return comandos


def barrido_caducado(ultima_respuesta_en: Optional[float], ahora: float,
                     tolerancia_s: float = RECONCILIACION_CADUCA_S) -> bool:
    """R-K-03: más de `tolerancia_s` (30 s) sin respuesta al barrido con el socket vivo → «no abrir nuevas» y aviso.

    Sin ninguna respuesta todavía (None) → True: nada se abre hasta haber
    reconciliado (F12, R-J-02.5). Justo en el límite aún no ha caducado.
    """
    if ultima_respuesta_en is None:
        return True
    return ahora - ultima_respuesta_en > tolerancia_s


FotoDAS = tuple[dict[str, MsgPos], dict[int, MsgOrden], list[MsgTrade]]


class AcumuladorVolcado:
    """§5.11 / §5.13: junta `%POS`/`%ORDER`/`%TRADE` de un volcado y entrega (posiciones, órdenes, trades) completos.

    Un volcado empieza con `iniciar` (el decisor lo llama al mandar
    `comandos_barrido` o antes del LOGIN) o con un marcador de inicio (`#POS`,
    `#Order`, `#Trade`: volcado espontáneo). Se entrega (y se vacía) cuando:
      (1) los bloques POS y Order (y Trade si se pidió) se han cerrado con su
          marcador de fin y no queda ninguno abierto;
      (2) llega la respuesta de GET BP (`MsgBP`) en un volcado pedido sin
          bloque abierto: DAS contesta en orden, así que las listas ya
          llegaron (sirve también para listas VACÍAS sin marcadores);
      (3) sin ningún marcador en este volcado, han pasado `espera_s` (500 ms)
          desde la última línea.
    Posiciones por ticker y órdenes por id (la última gana: un `%POS`
    empujado a mitad es la verdad más reciente); trades por id sin repetir.
    Fuera de un volcado las líneas sueltas se ignoran (son eventos: el
    decisor ya los aplica). Un marcador de inicio vacía SU categoría (llega la
    lista entera). No hay reloj propio: `revisar(ahora)` (o
    `aplicar(None, ahora)`) comprueba la regla (3) sin mensaje nuevo.
    """

    def __init__(self, espera_s: float = ESPERA_SIN_MARCADORES_S) -> None:
        if espera_s <= 0:
            raise ValueError(f"espera_s debe ser > 0, no {espera_s!r}")
        self._espera_s = float(espera_s)
        self._reiniciar(activo=False, pedido=False, con_trades=False)

    @property
    def activo(self) -> bool:
        """True mientras se está juntando un volcado."""
        return self._activo

    def iniciar(self, ahora: float, con_trades: bool = False) -> None:
        """Empieza un volcado PEDIDO (barrido o LOGIN); uno anterior sin terminar se descarta."""
        self._reiniciar(activo=True, pedido=True, con_trades=con_trades)
        self._inicio_en = ahora

    def descartar(self) -> None:
        """Abandona el volcado en curso (p. ej. al caer la conexión)."""
        self._reiniciar(activo=False, pedido=False, con_trades=False)

    def revisar(self, ahora: float) -> Optional[FotoDAS]:
        """Regla (3) sin mensaje nuevo: la llama el decisor en cada `Tic`."""
        return self.aplicar(None, ahora)

    def aplicar(self, msg: Optional[MensajeDAS], ahora: float) -> Optional[FotoDAS]:
        """Incorpora un mensaje (o solo el reloj si `msg` es None) y devuelve la foto si el volcado quedó completo."""
        if isinstance(msg, MsgMarcador):
            if self._marcador(msg.nombre):
                return self._entregar()
        elif self._activo and isinstance(msg, MsgPos):
            self._posiciones[msg.ticker] = msg
            self._linea(ahora)
        elif self._activo and isinstance(msg, MsgOrden):
            self._ordenes[msg.id] = msg
            self._linea(ahora)
        elif self._activo and isinstance(msg, MsgTrade):
            self._trades[msg.id] = msg
            self._linea(ahora)
        elif self._activo and isinstance(msg, MsgBP) and self._pedido and self._abierto is None:
            return self._entregar()
        if (self._activo and self._pedido and not self._marcadores and self._lineas > 0
                and self._ultima_en is not None and ahora - self._ultima_en >= self._espera_s):
            return self._entregar()
        return None

    # ── privados ──
    def _reiniciar(self, activo: bool, pedido: bool, con_trades: bool) -> None:
        self._activo = activo
        self._pedido = pedido
        self._con_trades = con_trades
        self._abierto: Optional[str] = None
        self._cerrados: set[str] = set()
        self._marcadores = False
        self._lineas = 0
        self._ultima_en: Optional[float] = None
        self._inicio_en: Optional[float] = None
        self._posiciones: dict[str, MsgPos] = {}
        self._ordenes: dict[int, MsgOrden] = {}
        self._trades: dict[int, MsgTrade] = {}

    def _linea(self, ahora: float) -> None:
        self._lineas += 1
        self._ultima_en = ahora

    def _marcador(self, nombre: str) -> bool:
        """Aplica un marcador; True si con él el volcado queda completo (regla 1)."""
        if nombre in _BLOQUES_INICIO:
            bloque = _BLOQUES_INICIO[nombre]
            if not self._activo:
                self._reiniciar(activo=True, pedido=False, con_trades=False)
            self._marcadores = True
            self._abierto = bloque
            self._cerrados.discard(bloque)
            if bloque == "POS":
                self._posiciones = {}
            elif bloque == "Order":
                self._ordenes = {}
            else:
                self._trades = {}
            return False
        if nombre in _BLOQUES_FIN and self._activo:
            bloque = _BLOQUES_FIN[nombre]
            self._marcadores = True
            self._cerrados.add(bloque)
            if self._abierto == bloque:
                self._abierto = None
            requeridos = {"POS", "Order"} | ({"Trade"} if self._con_trades else set())
            return self._abierto is None and requeridos <= self._cerrados
        return False

    def _entregar(self) -> FotoDAS:
        foto = (dict(self._posiciones), dict(self._ordenes), list(self._trades.values()))
        self._reiniciar(activo=False, pedido=False, con_trades=False)
        return foto


# ── ayudantes privados (puros) ───────────────────────────────────────────
def _bloque_stops(cfg: Any) -> Mapping:
    """El bloque «stops» de una `Config` o de un dict; ValueError si falta (no se inventan defaults en silencio)."""
    valor = cfg.get("stops") if isinstance(cfg, Mapping) else getattr(cfg, "stops", None)
    if not isinstance(valor, Mapping):
        raise ValueError("el bloque 'stops' de la config falta o no es un dict")
    return valor


def _ruta_stop_de(cfg: Any) -> str:
    rutas = cfg.get("rutas") if isinstance(cfg, Mapping) else getattr(cfg, "rutas", None)
    ruta = rutas.get("stop") if isinstance(rutas, Mapping) else None
    return ruta if isinstance(ruta, str) and ruta.strip() else _RUTA_STOP_DEFECTO


def _segundos(valor: Any, defecto: float) -> float:
    if isinstance(valor, bool) or not isinstance(valor, (int, float, Decimal)):
        return float(defecto)
    segundos = float(valor)
    return segundos if segundos > 0 else float(defecto)


def _entero_no_negativo(x: Any) -> int:
    try:
        valor = int(x)
    except (TypeError, ValueError):
        return 0
    return valor if valor > 0 else 0


def _precio_o_none(x: Any) -> Optional[Decimal]:
    """`Decimal` finito > 0 o None (un 0 de «precio no numérico» del parser no es un precio)."""
    if x is None or isinstance(x, bool):
        return None
    try:
        valor = de_float(x)
    except ValueError:
        return None
    return valor if valor > 0 else None


def _numeros(texto: str) -> list[Decimal]:
    """Números del tipo de %ORDER («SLP: 2.97 2.99» → [2.97, 2.99]); coma decimal y coma de miles como en `stops`."""
    salida: list[Decimal] = []
    for crudo in _RE_NUMERO.findall(str(texto)):
        if "," in crudo and "." in crudo:
            crudo = crudo.replace(",", "")
        elif crudo.count(",") == 1:
            crudo = crudo.replace(",", ".")
        else:
            crudo = crudo.replace(",", "")
        precio = _precio_o_none(crudo)
        if precio is not None:
            salida.append(precio)
    return salida


def _es_tipo_stop(tipo: str, cfg_stops: Optional[Mapping]) -> bool:
    """Riesgo 1 (PROVISIONAL): tipo de stop por `stops.TIPO_STOP_EN_ORDER` o por `tipo_esperado_en_order` si compila."""
    if _RE_TIPO_STOP.search(tipo):
        return True
    patron = cfg_stops.get("tipo_esperado_en_order") if isinstance(cfg_stops, Mapping) else None
    if patron is None or not str(patron).strip():
        return False
    try:
        return re.search(str(patron), tipo, re.IGNORECASE) is not None
    except re.error:
        return False


def _tipo_y_precios(m: MsgOrden, cfg_stops: Optional[Mapping]) -> tuple[TipoOrden, Optional[Decimal], Optional[Decimal]]:
    """(tipo, disparo, límite) de un %ORDER sin orden conocida."""
    tipo = str(m.tipo)
    precio_campo = _precio_o_none(m.precio)
    if _es_tipo_stop(tipo, cfg_stops):
        numeros = _numeros(tipo)
        disparo = numeros[0] if numeros else precio_campo
        limite = numeros[1] if len(numeros) > 1 else precio_campo
        return TipoOrden.STOP_LIMITE_PP, disparo, limite if limite is not None else disparo
    if tipo.strip().upper() in ("MKT", "MARKET", "M"):
        return TipoOrden.MERCADO, None, None
    return TipoOrden.LIMITE, None, precio_campo


def _qty_viva(o: Orden) -> int:
    """Lo que la orden aún puede ejecutar: `lvqty` en Partial/Triggered si > 0; si no, qty − llenas (como `stops`)."""
    if o.estado in (EstadoOrden.PARTIAL, EstadoOrden.TRIGGERED) and o.lvqty > 0:
        return max(int(o.lvqty), 0)
    return max(int(o.qty) - int(o.llenas), 0)


def _unicas(vivas: Iterable[Any]) -> list[Orden]:
    vistas: set[int] = set()
    salida: list[Orden] = []
    for o in vivas:
        if isinstance(o, Orden) and id(o) not in vistas:
            vistas.add(id(o))
            salida.append(o)
    return salida


def _clave_antiguedad(o: Orden) -> tuple[int, int, float]:
    """La más antigua primero: por id de DAS (servidor); sin id (aún Sending) después, por `enviada_en`."""
    if o.id_das is not None:
        return (0, int(o.id_das), o.enviada_en)
    return (1, 0, o.enviada_en)


def _lote_con_acciones(lote: Lote) -> bool:
    return lote.estado not in _LOTE_MUERTO and type(lote.llenas) is int and lote.llenas > 0


def _conocida(pos: Optional[PosicionTicker]) -> bool:
    """El diario conoce la posición: neta de fills ≠ 0 o algún lote vivo con acciones."""
    return pos is not None and (pos.neta_fills != 0 or any(_lote_con_acciones(lote) for lote in pos.lotes.values()))


def _afecta(m: MsgOrden) -> bool:
    """Una orden ajena importa si sigue viva o ha ejecutado algo; cancelada/rechazada sin ejecutar, no (R-M-03)."""
    if m.estado in stops.ESTADOS_VIVOS or m.estado in (EstadoOrden.EXECUTED, EstadoOrden.DESCONOCIDO):
        return True
    if m.estado is EstadoOrden.REJECTED:
        return False
    return _entero_no_negativo(m.qty) - _entero_no_negativo(m.lvqty) - _entero_no_negativo(m.cxlqty) > 0


def _vivas_y_ajenas(estado: EstadoBot, ord_das: Mapping[int, MsgOrden], hoy: date, ahora: Optional[float],
                    cfg_stops: Mapping) -> tuple[dict[str, list[Orden]], dict[str, list[MsgOrden]]]:
    """Órdenes nuestras vivas por ticker (unión DAS ∪ estado no contradicho) y ajenas NUEVAS por ticker."""
    vivas: dict[str, list[Orden]] = {}
    ajenas: dict[str, list[MsgOrden]] = {}
    tokens_das: set[int] = set()
    ids_das: set[int] = set()
    for id_das in sorted(ord_das):
        m = ord_das[id_das]
        if es_ajena(m, hoy):
            if m.id not in estado.ordenes_ajenas and _afecta(m) and str(m.ticker).strip():
                ajenas.setdefault(str(m.ticker).strip(), []).append(m)
            continue
        tokens_das.add(m.token)   # type: ignore[arg-type]
        ids_das.add(m.id)
        if m.estado in stops.ESTADOS_VIVOS:
            o = orden_de_msg(m, hoy, estado.ordenes.get(m.token), cfg_stops)   # type: ignore[arg-type]
            if o is not None:
                vivas.setdefault(o.ticker, []).append(o)
    for token in sorted(estado.ordenes):
        o = estado.ordenes[token]
        if o.estado not in stops.ESTADOS_VIVOS or token in tokens_das or (o.id_das is not None and o.id_das in ids_das):
            continue
        if o.id_das is None and ahora is not None and ahora - o.enviada_en > SIN_ECO_S:
            continue
        vivas.setdefault(o.ticker, []).append(o)
    return vivas, ajenas


def _texto_ajenas(ajenas: tuple[MsgOrden, ...]) -> str:
    partes = [f"id {m.id} {m.lado} {m.qty} {m.tipo} ({m.order_src or 'token ' + str(m.token)}, {m.estado.value})"
              for m in ajenas]
    return "R-K-02: órdenes que no son del bot: " + "; ".join(partes)


def _caso_desconocida(ticker: str, neta_d: int, avg: Optional[Decimal], vivas: tuple[Orden, ...],
                      ajenas: tuple[MsgOrden, ...], pos: Optional[PosicionTicker]) -> list[Discrepancia]:
    """Posición que ningún diario conoce (R-C-10 4 / R-K-02) o ticker plano con órdenes nuestras huérfanas."""
    sobrantes = tuple(huerfanas(vivas, ticker, neta_d))
    neta_f = pos.neta_fills if pos is not None else None
    if neta_d == 0:
        if ajenas:
            return [Discrepancia(ticker, CASO_AJENA, _texto_ajenas(ajenas), neta_das=0, neta_fills=neta_f, vivas=vivas,
                                 ajenas=ajenas, huerfanas=sobrantes)]
        if sobrantes:
            return [Discrepancia(ticker, CASO_STOP_DIFIERE, f"R-C-11 (2): {ticker} plana con órdenes nuestras vivas",
                                 neta_das=0, neta_fills=neta_f, vivas=vivas, huerfanas=sobrantes)]
        return []
    falta = max(abs(neta_d) - cobertura(vivas, ticker, neta_d), 0)
    if falta == 0 and not ajenas:
        caso = CASO_STOP_DIFIERE if sobrantes else CASO_COINCIDE
        return [Discrepancia(ticker, caso, f"R-C-10 (4): posición desconocida de {ticker} ({neta_d}) ya protegida",
                             neta_das=neta_d, neta_fills=neta_f, avg_das=avg, vivas=vivas, huerfanas=sobrantes)]
    detalle = f"R-C-10 (4): posición de {ticker} ({neta_d}) que no está en ningún diario; sin proteger: {falta}"
    if ajenas:
        detalle += ". " + _texto_ajenas(ajenas)
    return [Discrepancia(ticker, CASO_AJENA, detalle, neta_das=neta_d, neta_fills=neta_f, descubiertas=falta, avg_das=avg,
                         vivas=vivas, ajenas=ajenas, huerfanas=sobrantes)]


def _hora_prueba(hoy: date) -> datetime:
    """`stops.plan` no usa la hora (la ruta llega resuelta); para la simulación basta el día."""
    return datetime(hoy.year, hoy.month, hoy.day, 12, 0)


def _token_prueba() -> int:
    """Token de la SIMULACIÓN de `comparar`: nada de lo simulado sale; no se gasta la secuencia real."""
    return 1


def _clasificar_stops(pos: PosicionTicker, neta_d: int, avg: Optional[Decimal], vivas: tuple[Orden, ...], cfg_stops: Mapping,
                      limit_up: Optional[Decimal], hoy: date, ruta_prueba: str) -> Discrepancia:
    """Casos 1/2/3 de una posición conocida que cuadra (simulando `stops.plan` sobre las vivas)."""
    ticker = pos.ticker
    sobrantes = tuple(huerfanas(vivas, ticker, neta_d))
    comunes = dict(neta_das=neta_d, neta_fills=pos.neta_fills, avg_das=avg, vivas=vivas, huerfanas=sobrantes)
    if neta_d > 0 and _vendiendo(vivas, ticker) < neta_d:
        return Discrepancia(ticker, CASO_STOP_DIFIERE, f"R-C-11 (3): {ticker} LARGA {neta_d} sin la venta del exceso en marcha",
                            **comunes)   # type: ignore[arg-type]
    if pos.estado is EstadoTicker.BS:
        return Discrepancia(ticker, CASO_COINCIDE, f"R-G-03: {ticker} en cisne negro: no se repone ni se ajusta",
                            neta_das=neta_d, neta_fills=pos.neta_fills, avg_das=avg, vivas=vivas)
    prueba =stops.plan(replace(pos, neta_das=neta_d), list(vivas), cfg_stops, limit_up, _token_prueba, _hora_prueba(hoy),
                        ruta_prueba, pos.version_stops)
    faltan = [a for a in prueba if isinstance(a, EnviarOrden)]
    cambios = [a for a in prueba if isinstance(a, (Reemplazar, Cancelar))]
    sin_stop = neta_d < 0 and cobertura(vivas, ticker, neta_d) == 0
    if faltan or sin_stop:
        return Discrepancia(ticker, CASO_SIN_STOP, f"R-C-10 (3): a {ticker} ({neta_d}) le faltan {len(faltan)} stops en DAS",
                            **comunes)   # type: ignore[arg-type]
    if cambios or sobrantes:
        return Discrepancia(ticker, CASO_STOP_DIFIERE,
                            f"R-C-10 (2): stops de {ticker} distintos de lo calculado ({len(cambios)} cambios, "
                            f"{len(sobrantes)} huérfanas)", **comunes)   # type: ignore[arg-type]
    return Discrepancia(ticker, CASO_COINCIDE, f"R-C-10 (1): {ticker} ({neta_d}) coincide", **comunes)   # type: ignore[arg-type]


def _adoptar(estado: EstadoBot, vivas: Iterable[Orden]) -> None:
    """F13 / R-C-07 neteo: una orden NUESTRA que DAS tiene y el ejecutor no (p. ej. del vigilante) pasa a `estado.ordenes`."""
    for o in vivas:
        if o.token in estado.ordenes or mod_tokens.descomponer(o.token) is None:
            continue
        estado.ordenes[o.token] = o
        if o.id_das is not None:
            estado.id_a_token[o.id_das] = o.token


def _cancelar(ordenes: Iterable[Orden], motivo: str, ya: set[int]) -> list[Accion]:
    """Cancelar cada orden con id de DAS que no esté ya cancelada en esta tanda (sin id no se puede: el siguiente barrido)."""
    salida: list[Accion] = []
    for o in ordenes:
        if o.id_das is None or o.id_das in ya:
            continue
        ya.add(o.id_das)
        salida.append(Cancelar(id_das=o.id_das, token=o.token, motivo=motivo))
    return salida


def _esc(texto: Any) -> str:
    """D2-08: texto variable hacia Telegram (parse_mode HTML) escapado: un «<» de DAS no pierde el aviso."""
    return html.escape(str(texto), quote=False)


def _ids_cancelados(acciones_: Iterable[Accion]) -> set[int]:
    return {a.id_das for a in acciones_ if isinstance(a, Cancelar)}


def _pct_proteccion(cfg_stops: Mapping) -> Decimal:
    valor = cfg_stops.get("proteccion_desconocidas_pct")
    return de_float(valor) if valor is not None else STOP_PROTECCION_PCT


def _precio_referencia(cot: Optional[Cotizacion], neta: int, avg: Optional[Decimal]) -> Optional[Decimal]:
    """Para la protección: último; si no, el lado que dispararía (ask si corta, bid si larga), el otro y el medio de DAS."""
    campos = ("last", "ask", "bid") if neta < 0 else ("last", "bid", "ask")
    for campo in campos:
        precio = _precio_o_none(getattr(cot, campo, None))
        if precio is not None:
            return precio
    return avg


def _proteccion(ticker: str, falta: int, neta: int, cot: Optional[Cotizacion], avg: Optional[Decimal], cfg_stops: Mapping,
                tokens: Callable[[], int], ruta_stop: str, version: int) -> list[Accion]:
    """R-C-10 (4): `stops.stop_proteccion` por lo descubierto; sin ningún precio, aviso 3 para ponerla a mano.

    UN stop (como siempre) a `proteccion_desconocidas_pct` del precio; su límite es el del stop único
    (`stops.limite_pct`, Jaume 29-sep; en v3 era el +3 % del principal).
    """
    if falta <= 0 or neta == 0:
        return []
    precio = _precio_referencia(cot, neta, avg)
    if precio is None:
        return [Avisar(nivel=Nivel.MAXIMO, grupo=Grupo.B, clave=f"proteccion_sin_precio:{ticker}",
                       texto=(f"R-C-10 (4): {ticker} tiene {falta} acciones sin stop y no hay precio para calcular la "
                              f"protección: PONERLA A MANO"))]
    ancho = cfg_stops.get(stops.CLAVE_LIMITE_PCT)
    orden = stops.stop_proteccion(ticker, falta, neta < 0, precio, _pct_proteccion(cfg_stops), tokens(), ruta_stop, version,
                                  limite_pct=ancho)
    return [EnviarOrden(orden=orden)]


def _vendiendo(vivas: Iterable[Any], ticker: str) -> int:
    """Acciones que ya se están vendiendo con la venta del exceso de R-C-11 b: SOLO las VENTA_EXCESO nuestras vivas.

    R3-REC-1 (mismo criterio que `stops.limpieza_tras_fill_stop`, D2a-03 /
    R2-STOPS-1): una ENTRADA_AGREGAR/ENTRADA_CRUCE es una venta CORTA que
    jamás cubre la larga, y ninguna otra venta cuenta como «la venta del
    exceso en marcha». Con la cuenta larga y solo una entrada viva el
    barrido llama a la limpieza como si no hubiera nada (la limpieza cancela
    esa entrada y vende el exceso).
    """
    return sum(_qty_viva(o) for o in _unicas(vivas)
               if o.ticker == ticker and o.lado is Lado.VENTA and o.proposito is Proposito.VENTA_EXCESO
               and o.estado in stops.ESTADOS_VIVOS)


def _reparar_stops(d: Discrepancia, pos: Optional[PosicionTicker], cot: Optional[Cotizacion], cfg: Any, cfg_stops: Mapping,
                   tokens: Callable[[], int], hora_et: datetime, ruta_stop: str, version: int,
                   limit_up: Optional[Decimal]) -> list[Accion]:
    """Casos 2/3 (y 6 corta): `stops.plan` + protección si no hay stop calculable + huérfanas canceladas.

    Solo con una posición CONOCIDA se llama a `plan` (una desconocida no tiene
    conjunto deseado: `plan` pediría GET POSITIONS sin fin). Una conocida
    LARGA sin la venta del exceso en marcha → `stops.limpieza_tras_fill_stop`
    (R-C-11 b, riesgo 6: el barrido es la red de control del evento).
    """
    salida: list[Accion] = []
    neta = d.neta_das if d.neta_das is not None else (pos.neta if pos is not None else 0)
    if pos is not None and _conocida(pos):
        if neta > 0 and _vendiendo(d.vivas, d.ticker) < neta:
            return stops.limpieza_tras_fill_stop(pos, list(d.vivas), cot, tokens, cfg, hora_et, version, limit_up=limit_up)
        salida.extend(stops.plan(pos, list(d.vivas), cfg_stops, limit_up, tokens, hora_et, ruta_stop, version))
        if (neta < 0 and pos.estado is not EstadoTicker.BS and not stops.conjunto_deseado(pos, cfg_stops, limit_up)
                and not any(isinstance(a, EnviarOrden) for a in salida)):
            falta = abs(neta) - cobertura(d.vivas, d.ticker, neta)
            salida.extend(_proteccion(d.ticker, falta, neta, cot, d.avg_das, cfg_stops, tokens, ruta_stop, version))
    salida.extend(_cancelar(huerfanas(d.vivas, d.ticker, neta),
                            f"R-C-11: orden de {d.ticker} que agrandaría la posición ({neta}) en el sentido equivocado",
                            _ids_cancelados(salida)))
    return salida


def _caso_ajena(d: Discrepancia, estado: EstadoBot, pos: Optional[PosicionTicker], cot: Optional[Cotizacion],
                cfg_stops: Mapping, tokens: Callable[[], int], ruta_stop: str, version: int) -> list[Accion]:
    """Caso 4 (R-C-10 4, R-K-02, R-M-03): registrar, pasar el ticker al humano (una vez), proteger lo descubierto, avisar 3.

    Jaume 29-sep (R-M-03 POR TICKER, antes pausa global): el ticker queda con
    `intervencion_humana=True` y en CONTROL_HUMANO con motivo «intervención
    humana» (Anotar «pausa» CON ticker, que `diario.reconstruir` rehace); los
    demás tickers siguen abriendo. «/sigue X» lo devuelve a NORMAL y «/sigue»
    a secas levanta todos. Sus stops y salidas siguen como antes.

    E2c-01: las ajenas tratadas se anotan SIEMPRE (`Anotar("ajenas_tratadas",
    {ids, ticker})`, también con la pausa ya puesta) para que
    `diario.reconstruir` rellene `estado.ordenes_ajenas`: un reinicio no vuelve
    a pausar por las mismas órdenes manuales tras un /sigue. E2c-03: una
    posición DESCONOCIDA LARGA → además `Avisar(3)` «VENDER A MANO» (la
    limpieza R-C-11 solo corre en posiciones conocidas; si saltaron a la vez un
    stop manual y nuestra protección, nadie más vendería el exceso).
    """
    ticker = d.ticker
    salida: list[Accion] = []
    for m in d.ajenas:
        estado.ordenes_ajenas[m.id] = m
    if d.ajenas:
        salida.append(Anotar(ANOTACION_AJENAS, {"ticker": ticker, "ids": [m.id for m in d.ajenas],
                                                "regla": "R-K-02 / E2c-01"}))
    conocida = _conocida(pos)
    if pos is None:
        pos = PosicionTicker(ticker=ticker)
        estado.posiciones[ticker] = pos
    if not pos.intervencion_humana:
        # Jaume 29-sep: R-M-03 POR TICKER. Solo este ticker pasa a manos del humano (CONTROL_HUMANO con motivo
        # «intervención humana»); el resto sigue entrando. Un cisne negro, un ticker sin símbolo o un control humano
        # ya puesto conservan su estado (y su protocolo); solo se marca la intervención.
        pos.intervencion_humana = True
        if pos.estado in _ESTADOS_A_CONTROL_HUMANO:
            pos.estado = EstadoTicker.CONTROL_HUMANO
            pos.motivo_estado = MOTIVO_INTERVENCION_HUMANA + ": no se abre nada en este ticker hasta /sigue " + ticker
        salida.append(Anotar(PETICION_PAUSA, {
            "ticker": ticker, "estado": pos.estado.value, "intervencion_humana": True, "ticker_ajeno": ticker,
            "ordenes_ajenas": [m.id for m in d.ajenas], "motivo": pos.motivo_estado or MOTIVO_INTERVENCION_HUMANA,
            "regla": "R-M-03 por ticker (Jaume 29-sep)"}))
    neta = d.neta_das or 0
    salida.extend(_proteccion(ticker, d.descubiertas, neta, cot, d.avg_das, cfg_stops, tokens, ruta_stop, version))
    salida.extend(_cancelar(d.huerfanas, f"R-C-11: orden nuestra huérfana en {ticker} ({neta})", set()))
    salida.append(Avisar(nivel=Nivel.MAXIMO, grupo=Grupo.B, clave=f"ajena:{ticker}",
                         texto=(f"R-M-03: intervención humana en {_esc(ticker)}: {_esc(d.detalle)}. Se protege lo "
                                f"descubierto; {_esc(ticker)} en manos del humano hasta /sigue {_esc(ticker)} (el resto "
                                f"de tickers sigue operando)")))
    if neta > 0 and not conocida:
        salida.append(Avisar(nivel=Nivel.MAXIMO, grupo=Grupo.B, clave=f"desconocida_larga:{ticker}",
                             texto=(f"VENDER A MANO: la cuenta está LARGA {neta} en {_esc(ticker)} y ningún diario del bot "
                                    f"conoce esa posición (¿saltaron a la vez un stop manual y la protección del bot?). "
                                    f"El bot solo pone una protección de venta; no vende el exceso (R-C-10 (4), R-C-11 (3), "
                                    f"E2c-03).")))
    return salida


def _caso_cerrada(d: Discrepancia, pos: Optional[PosicionTicker]) -> list[Accion]:
    """Caso 5 (R-C-10, M7): DAS plana y el diario abierta → lotes CERRADO, neta 0, cancelar lo nuestro que sobra, aviso 2."""
    ticker = d.ticker
    salida: list[Accion] = []
    antes = pos.neta_fills if pos is not None else d.neta_fills
    if pos is not None:
        for lote_id in sorted(pos.lotes):
            lote = pos.lotes[lote_id]
            if lote.estado in _LOTE_MUERTO:
                continue
            lote.estado = EstadoLote.CERRADO
            salida.append(Anotar("lote", {"lote_id": lote.id, "ticker": ticker, "estado": EstadoLote.CERRADO.value,
                                          "regla": "R-C-10 (5)"}))
        pos.neta_fills = 0
        pos.neta_das = 0
    salida.append(Anotar("discrepancia", {"ticker": ticker, "caso": CASO_CERRADA_EN_DAS, "neta_fills": antes, "neta_das": 0,
                                          "detalle": d.detalle, "regla": "R-C-10 (5) / M7"}))
    salida.extend(_cancelar(huerfanas(d.vivas, ticker, 0), f"R-C-11 (2): {ticker} plana en DAS", set()))
    salida.append(Avisar(nivel=Nivel.AVISO, grupo=Grupo.B, clave=f"reconciliacion_cerrada:{ticker}",
                         texto=f"R-C-10: el diario tenía {ticker} abierta ({antes}) y DAS la da plana: lotes cerrados"))
    return salida


def _caso_neta_distinta(d: Discrepancia, pos: Optional[PosicionTicker], cot: Optional[Cotizacion], cfg: Any,
                        cfg_stops: Mapping, tokens: Callable[[], int], hora_et: datetime, ruta_stop: str,
                        limit_up: Optional[Decimal]) -> list[Accion]:
    """Caso 6 (M7, corrección 2): DAS manda → neta_fills := neta_das, anotado, aviso 2 y stops (o venta del exceso si LARGA)."""
    ticker = d.ticker
    if pos is None or d.neta_das is None:
        raise ValueError(f"caso 6 de {ticker} sin posición conocida o sin neta de DAS")
    antes = pos.neta_fills
    pos.neta_fills = d.neta_das
    pos.neta_das = d.neta_das
    salida: list[Accion] = [
        Anotar("discrepancia", {"ticker": ticker, "caso": CASO_NETA_DISTINTA, "neta_fills": antes, "neta_das": d.neta_das,
                                "detalle": d.detalle, "regla": "M7 / corrección 2: manda DAS"}),
        Avisar(nivel=Nivel.AVISO, grupo=Grupo.B, clave=f"reconciliacion_neta:{ticker}",
               texto=f"M7: {ticker} neta de fills {antes} ≠ DAS {d.neta_das}; manda DAS y se recalculan los stops")]
    salida.extend(_reparar_stops(d, pos, cot, cfg, cfg_stops, tokens, hora_et, ruta_stop, pos.version_stops, limit_up))
    return salida
