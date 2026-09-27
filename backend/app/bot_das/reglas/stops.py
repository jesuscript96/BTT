"""Stops residentes STOPLMTP: niveles, conjunto deseado, plan idempotente, limpieza, reasignación y protección.

QUÉ HACE. Las reglas del área C del libro que deciden QUÉ órdenes de stop
deben vivir en DAS para cada posición corta y cómo se llega a ese conjunto
sin duplicar nada ni quedarse largo:
  * `niveles`: los cuatro precios de R-C-01 v3 (+3 / +13 / +63 SUMADOS sobre
    el nivel L de la estrategia), recortados bajo la banda limit up (R-F-02).
  * `conjunto_deseado`: UN principal por nivel L distinto y UNA emergencia
    con toda la posición sobre el L más alto (decisión (a) de Jaume, 22-sep).
  * `plan`: casa lo deseado con las órdenes vivas de CUALQUIER origen (aquí
    está el neteo con el vigilante de R-C-07) y devuelve lo mínimo que falta,
    sobra o tiene otra cantidad. IDEMPOTENTE: aplicado dos veces, la segunda
    no produce nada.
  * `limpieza_tras_fill_stop`: R-C-11 por EVENTO (neta 0 → cancelar todo;
    LARGA → vender SOLO el exceso al bid; sigue corta → principal consumido
    y `plan`).
  * `reasignar_principal_rebasado`: R-C-01 decisión (a) cuando el ask pasa de
    largo el límite de un principal sin llenarlo.
  * `inferir_proposito`, `tipo_conserva_pp`, `stop_proteccion`, `descubiertas`
    y `cantidad_cancelada`: las piezas que usan el vigilante, la
    reconciliación y el decisor alrededor de los stops.

POR QUÉ ESTÁ AQUÍ. Es lógica PURA: sin reloj, sin I/O, sin red, sin logging.
Recibe la posición, las órdenes vivas, la configuración y la hora ET como
parámetros y devuelve acciones (`tipos.Accion`) que el ejecutor ejecuta EN
ORDEN. Así se prueba con tablas de casos sin DAS (documento §10) y el decisor
(lote G) y el vigilante (lote E, que importa `inferir_proposito`) comparten
EXACTAMENTE la misma aritmética.

LAS TRAMPAS.
  * `pos.neta` es la neta de FILLS (verdad inmediata, corrección 2 del juez).
    Si `neta_das` (lo último que dijo %POS) es conocida y NO coincide, `plan`
    no toca nada y pide `GET POSITIONS`: una emergencia con más acciones que
    el corto real deja la cuenta LARGA (R-C-11 b, riesgo 8).
  * Versión del objetivo (injerto A §8.6, riesgo 7): todo `EnviarOrden` y
    `Reemplazar` de stops lleva `serie="stops:X"` y `version`;
    `limpieza_tras_fill_stop` empieza SIEMPRE por `InvalidarSerie` para que un
    REPLACE viejo encolado nunca salga después del fill.
  * El casado deseado↔viva es por PROPÓSITO y por DISPARO (±1 tick), no solo
    por `nivel`: con R-F-02 el disparo deseado ya no es L, y casar por
    `nivel` dejaría para siempre un stop por encima de una banda nueva (R-F-02
    «cada vez que la banda cambia»). Entre las candidatas, primero cada
    deseado reclama la puesta para SU nivel (con la banda varios principales
    comparten disparo y, sin eso, un segundo `plan` intercambiaría
    cantidades) y después el resto va por disparo y antigüedad. Una viva sin
    disparo ni nivel se IGNORA (ni cuenta ni se cancela).
  * Lo que no se entiende NO se cancela: si hay corto y no sale ningún stop
    deseado (lotes sin nivel válido, o ningún lote vivo), `plan` no toca las
    órdenes vivas; con lotes sin nivel avisa nivel 3 (los stops no se pueden
    calcular). Una posición sin lotes es de la reconciliación (R-C-10 caso 4).
  * «Vivas» son Sending/Accepted/Partial y también Hold y Triggered (manual
    L379-405: Hold = «open, but not sent to the exchange», que es como DAS
    guarda un stop hasta el disparo). No contarlas duplicaría el stop
    (riesgo 11). Para `descubiertas` solo cubren las CONFIRMADAS (no Sending):
    R-C-03 habla de «stop aceptado».
  * Protecciones: la de R-C-10 caso 4 (`stop_proteccion`, sin lote) no la
    toca `plan` nunca: una posición desconocida no tiene conjunto deseado y
    cancelarla la dejaría desnuda. El «principal al ask» que crea
    `reasignar_principal_rebasado` (STOP_PROTECCION CON `lote_id` de la
    posición) sí: `plan` lo recorta junto con los principales para que la suma
    del escalón principal nunca pase de la posición (R-C-07).
  * La cantidad VIVA de una orden es `lvqty` cuando DAS ya la ha dicho
    (Partial/Triggered) y `qty − llenas` si no: nunca «lo pedido» (injerto A
    §8.7). `cantidad_cancelada` lee `cxlqty` / `Canceled qty`, jamás `qty`.
  * «La más nueva» es la de `id_das` mayor (lo asigna el servidor y vale entre
    procesos); sin `id_das` (aún Sending) es más nueva que cualquiera con id,
    y entre ellas decide `enviada_en`. `enviada_en` es el reloj monotónico del
    proceso que envió: el de una orden adoptada del vigilante no es comparable.
  * Con R-F-02 cada disparo se recorta por separado bajo la banda: con L a
    menos de un 1,5 % de la banda la emergencia recortada queda POR DEBAJO del
    principal. Se deja así a propósito (cubre TODA la posición; dos órdenes
    con disparos pegados se comprarían encima, medido 15-sep, 55-65 %).
  * Una banda que no es un precio (None, 0, negativa, NaN) es «sin banda»:
    DAS puede devolver 0 fuera de RTH.
  * Solo dos funciones MUTAN el estado: `limpieza_tras_fill_stop`
    (`Lote.principal_consumido`, como manda §3.16) y
    `reasignar_principal_rebasado` (`Lote.nivel_stop` / `principal_consumido`):
    sin eso el siguiente `plan()` repondría el principal recién cancelado en
    un nivel que el precio ya ha pasado. Las dos devuelven un `Anotar("lote")`
    PARCIAL por lote cambiado ANTES de las órdenes (§8: el diario conserva lo
    que el registro no trae), para que `reconstruir` tras un reinicio (H-2)
    no lo deshaga. `reasignar` es idempotente: solo actúa sobre principales
    cuyo nivel aún tiene lotes sin consumir, así un `$Quote` repetido antes
    del `Canceled` no duplica el principal al ask.
  * En cisne negro (`EstadoTicker.BS`) `plan` y `reasignar` devuelven []: ni
    se repone lo que DAS cancele ni se persigue al precio (R-G-01, R-G-03); la
    emergencia solo se ajusta con `cisne_negro.acciones_durante_bs`. En halt
    `reasignar` tampoco actúa (el libro está congelado; manda R-F-01).
  * El tipo de un STOPLMTP en `%ORDER` no está documentado (riesgo 1): se
    reconoce por `TIPO_STOP_EN_ORDER` («SLP: 2.97 2.99», «SL: …», «STOP…») o
    por `stops.tipo_esperado_en_order` cuando `comprobar_das` lo fije.
    PROVISIONAL hasta el primer STOPLMTP real.
  * Los porcentajes de la config llegan como float del JSON: pasan UNA vez por
    `precios.de_float`; todo lo demás es `Decimal` y ningún resultado es float.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Iterable, Optional, Union

from app.bot_das.reglas.precios import con_techo, de_float, redondear_abajo, redondear_arriba
from app.bot_das.reglas.precios import ruta as ruta_de
from app.bot_das.tipos import (
    STOP_EMERGENCIA_DISPARO_PCT,
    STOP_EMERGENCIA_LIMITE_PCT,
    STOP_MARGEN_BAJO_LIMIT_UP_PCT,
    STOP_PRINCIPAL_LIMITE_PCT,
    Accion,
    Anotar,
    Avisar,
    Cancelar,
    CancelarTicker,
    Consultar,
    Cotizacion,
    EnviarOrden,
    EstadoLote,
    EstadoOrden,
    EstadoTicker,
    Grupo,
    InvalidarSerie,
    Lado,
    Lote,
    MsgOrden,
    MsgOrderAct,
    Nivel,
    NivelesStop,
    Orden,
    OrdenNueva,
    Origen,
    PosicionTicker,
    Programar,
    Proposito,
    Reemplazar,
    StopDeseado,
    TipoOrden,
    tick_de,
)

# ── claves y plazos de los temporizadores que este módulo programa (§5 F2) ──
CLAVE_REPLANIFICAR = "stops_plan"               # F2.1: volver a planificar cuando falta información (GET POSITIONS, id_das)
REPLANIFICAR_EN_S = 0.5
CLAVE_VERIFICAR_REPLACE = "replace_verificar"   # F2.2 / 2h.8: comprobar el tipo (y la cantidad) tras un REPLACE
VERIFICAR_REPLACE_EN_S = 1.0
COMANDO_POSICIONES = "GET POSITIONS"

# Estados en los que una orden sigue en el libro de DAS (manual L379-405; ver trampas).
ESTADOS_VIVOS = (EstadoOrden.SENDING, EstadoOrden.ACCEPTED, EstadoOrden.PARTIAL, EstadoOrden.HOLD,
                 EstadoOrden.TRIGGERED)
# Estados CONFIRMADOS por DAS: los únicos que cubren una posición para R-C-03 («stop aceptado»).
ESTADOS_CONFIRMADOS = (EstadoOrden.ACCEPTED, EstadoOrden.PARTIAL, EstadoOrden.HOLD, EstadoOrden.TRIGGERED)
PROPOSITOS_GESTIONADOS = (Proposito.STOP_PRINCIPAL, Proposito.STOP_EMERGENCIA)
PROPOSITOS_STOP = (Proposito.STOP_PRINCIPAL, Proposito.STOP_EMERGENCIA, Proposito.STOP_PROTECCION)
# Campo Type de %ORDER de un stop (manual L369: «Same like Type column on frontend order window»). La captura del
# socio (24-sep) muestra «SLP: 2.97 2.99»; el límite es «L» (L348). PROVISIONAL hasta comprobar_das paso 3.
TIPO_STOP_EN_ORDER = r"^\s*(?:STOP|STP|SL|SM)"

_ESTADOS_LOTE_MUERTO = (EstadoLote.CERRADO, EstadoLote.CANCELADO)
_RE_TIPO_STOP = re.compile(TIPO_STOP_EN_ORDER, re.IGNORECASE)
_RE_NUMERO = re.compile(r"\d+(?:[.,]\d+)*")
_CERO = Decimal("0")

OrdenOMensaje = Union[MsgOrden, Orden]


def serie_stops(ticker: str) -> str:
    """Serie del emisor para los stops de un ticker (injerto A §8.6): «stops:X»; el emisor descarta sus versiones viejas."""
    return f"stops:{ticker}"


# ── niveles (R-C-01 v3, R-F-02) ─────────────────────────────────────────
def niveles(L: Decimal, cfg_stops: Mapping, limit_up: Optional[Decimal] = None) -> NivelesStop:
    """R-C-01 v3 (23-sep): márgenes SUMADOS sobre el nivel L de la estrategia; R-F-02: disparos bajo la banda limit up.

    principal: disparo L, límite L·(1 + principal_limite_pct); emergencia:
    disparo L·(1 + emergencia_disparo_pct), límite L·(1 + emergencia_limite_pct).
    Todo redondeado ARRIBA al tick (lado permisivo de una compra; regla 612:
    0,9999·1,03 = 1,0299 sale 1,03 porque desde 1 $ el tick es 0,01). Si un
    disparo queda ≥ `limit_up` («por encima o coincide»), ese disparo pasa a
    limit_up·(1 − margen_bajo_limit_up_pct) redondeado ABAJO y su límite a
    disparo·(1 + principal_limite_pct): `bajo_banda=True`. Cada disparo se
    recorta por separado (ver trampas). Una banda que no es un precio es «sin
    banda». Porcentajes ausentes → constantes de `tipos` (riesgo 32). Lanza
    ValueError si L no es un precio > 0, si un porcentaje es negativo o si el
    margen deja el disparo en ≤ 0; TypeError si `cfg_stops` no es un dict.
    """
    nivel = de_float(L)
    if nivel <= 0:
        raise ValueError(f"nivel de stop no positivo: {L!r}")
    p_limite = _pct(cfg_stops, "principal_limite_pct", STOP_PRINCIPAL_LIMITE_PCT)
    e_disparo = _pct(cfg_stops, "emergencia_disparo_pct", STOP_EMERGENCIA_DISPARO_PCT)
    e_limite = _pct(cfg_stops, "emergencia_limite_pct", STOP_EMERGENCIA_LIMITE_PCT)
    margen = _pct(cfg_stops, "margen_bajo_limit_up_pct", STOP_MARGEN_BAJO_LIMIT_UP_PCT)
    recorte = _recorte_banda(limit_up, margen)
    principal, p_bajo = _bajo_banda((redondear_arriba(nivel), con_techo(nivel, p_limite, arriba=True)), recorte, p_limite)
    emergencia, e_bajo = _bajo_banda((con_techo(nivel, e_disparo, arriba=True), con_techo(nivel, e_limite, arriba=True)),
                                     recorte, p_limite)
    return NivelesStop(principal_disparo=principal[0], principal_limite=principal[1],
                       emergencia_disparo=emergencia[0], emergencia_limite=emergencia[1],
                       bajo_banda=p_bajo or e_bajo)


# ── conjunto deseado (R-C-01 v3 decisión (a), R-C-06, R-C-07, R-B-03) ──
def conjunto_deseado(pos: PosicionTicker, cfg_stops: Mapping, limit_up: Optional[Decimal]) -> list[StopDeseado]:
    """R-C-01 v3 (a): UN principal por nivel L distinto y UNA emergencia con toda la posición sobre el L más alto.

    Sobre `pos.neta` (fills): n = −neta; n ≤ 0 → []. Cada principal lleva la
    suma de `llenas` de los lotes vivos de ese nivel con
    `principal_consumido=False` (R-C-11 c; R-C-06: dos estrategias al mismo
    nivel comparten orden), capada ACUMULATIVAMENTE a n en orden ascendente de
    nivel: el nivel más bajo, que dispara antes, conserva su cantidad entera y
    la suma de principales nunca supera la posición (área E, R-C-07). La
    emergencia lleva n entera sobre el nivel más alto de TODOS los lotes vivos
    (también los de principal consumido: la posición sigue ahí). No cuentan
    los lotes cerrados/cancelados, sin llenas, largos (R-E-01) ni los que no
    tienen un nivel válido (A12: `Decimal` finito > 0); sin ningún lote válido
    → []. Orden: principales ascendentes y la emergencia al final. No muta nada.
    """
    n = -pos.neta
    if n <= 0:
        return []
    lotes = _lotes_vivos(pos)
    if not lotes:
        return []
    por_nivel: dict[Decimal, int] = {}
    for lote in lotes:
        if not lote.principal_consumido:
            por_nivel[lote.nivel_stop] = por_nivel.get(lote.nivel_stop, 0) + lote.llenas   # type: ignore[index]
    deseados: list[StopDeseado] = []
    restante = n
    for nivel in sorted(por_nivel):
        qty = min(por_nivel[nivel], restante)
        if qty <= 0:
            break
        niv = niveles(nivel, cfg_stops, limit_up)
        deseados.append(StopDeseado(proposito=Proposito.STOP_PRINCIPAL, nivel=nivel, qty=qty,
                                    disparo=niv.principal_disparo, limite=niv.principal_limite))
        restante -= qty
    nivel_max = lotes[-1].nivel_stop
    niv = niveles(nivel_max, cfg_stops, limit_up)   # type: ignore[arg-type]
    deseados.append(StopDeseado(proposito=Proposito.STOP_EMERGENCIA, nivel=nivel_max, qty=n,   # type: ignore[arg-type]
                                disparo=niv.emergencia_disparo, limite=niv.emergencia_limite))
    return deseados


# ── propósito de una orden que no está en el diario del ejecutor (corrección 3) ──
def inferir_proposito(o: OrdenOMensaje, niveles_lotes: list[Decimal], cfg_stops: Mapping,
                      limit_up: Optional[Decimal] = None) -> Proposito:
    """Corrección 3 del juez: clasifica una STOPLMTP de COMPRA que puso el vigilante (o que no tiene diario).

    disparo ≈ principal de algún L (±1 tick) → STOP_PRINCIPAL; disparo ≈
    emergencia de algún L (L·1,13, ±1 tick) → STOP_EMERGENCIA; otra cosa →
    STOP_PROTECCION. Si casa con las dos (dos niveles a 13 %) gana PRINCIPAL.
    Con `limit_up` (opcional, añadido sobre §3.16) casan TANTO los valores
    recortados bajo la banda (R-F-02) como los sin recortar: un stop puesto
    antes de la banda se reconoce, `plan` lo ve distinto del deseado y lo
    sustituye (si pasara por protección quedaría huérfano). Lo que no es un
    stop de compra → DESCONOCIDA (`plan` no lo cuenta). El disparo de un
    `MsgOrden` es el primer número del campo de tipo («SLP: 2.97 2.99» → 2.97,
    captura del socio 24-sep; coma decimal admitida) o, sin números, `precio`;
    su tipo se reconoce por `TIPO_STOP_EN_ORDER` o por
    `cfg_stops["tipo_esperado_en_order"]` (PROVISIONAL, riesgo 1).
    """
    if not _es_stop_compra(o, cfg_stops):
        return Proposito.DESCONOCIDA
    disparo = _disparo_de(o)
    if disparo is None:
        return Proposito.STOP_PROTECCION
    variantes = _variantes(_niveles_validos(niveles_lotes), cfg_stops, limit_up)
    if any(_mismo_precio(disparo, v.principal_disparo) for v in variantes):
        return Proposito.STOP_PRINCIPAL
    if any(_mismo_precio(disparo, v.emergencia_disparo) for v in variantes):
        return Proposito.STOP_EMERGENCIA
    return Proposito.STOP_PROTECCION


# ── plan idempotente (R-C-01 v3, R-C-04, R-C-06, R-C-07 neteo, R-C-11, corrección 2) ──
def plan(pos: PosicionTicker, vivas: list[Orden], cfg_stops: Mapping, limit_up: Optional[Decimal],
         tokens: Callable[[], int], hora_et: datetime, ruta_stop: str, version: int) -> list[Accion]:
    """R-C-01 v3 / R-C-04 / R-C-06 / R-C-07 (neteo con el vigilante) / R-C-11: lleva las órdenes vivas al conjunto deseado.

    IDEMPOTENTE y neutral al `Origen`: casa cada `StopDeseado` con las
    STOPLMTP de compra vivas del ticker (Sending/Accepted/Partial/Hold/
    Triggered) del mismo propósito y disparo ±1 tick (primero la puesta para
    su mismo `nivel`; después la de disparo más cercano y la más antigua),
    infiriendo el propósito de las del vigilante con `inferir_proposito`.
    Falta → `EnviarOrden(STOPLMTP B,
    serie="stops:X", version, propósito, nivel, lote de ese nivel)` (R-C-03/04
    reponer); cantidad distinta → `Reemplazar(version, serie)` +
    `Programar("replace_verificar", 1 s, {token, ticker, qty_objetivo})`
    (R-C-06 subir, R-C-07 bajar; 2h.8); sobrante → `Cancelar` (con varias
    iguales se conserva la más antigua y se cancela la MÁS NUEVA, R-C-07 plan
    B). El «principal al ask» de `reasignar_principal_rebasado` se recorta con
    lo que dejan los principales (nunca sube). Orden de las acciones: nuevas,
    ajustes, cancelaciones (R-C-05: primero lo nuevo, luego lo viejo).
    Precondición (corrección 2, riesgo 8): `pos.neta_das` conocida y ≠
    `pos.neta_fills` → [Consultar("GET POSITIONS"), Programar("stops_plan",
    0,5 s)] sin tocar NADA. n ≤ 0 → cancela todos los stops gestionados
    (R-C-11 2). Corto sin ningún stop deseado → no toca nada (+ Avisar(3) si
    hay lotes sin nivel válido). Una orden sin `id_das` que habría que
    reemplazar o cancelar se deja y se reprograma `stops_plan`. En cisne negro
    devuelve [] (R-G-03). `hora_et` se conserva por el contrato de §3.16 (la
    ruta ya llega resuelta). No muta nada.
    """
    ticker = pos.ticker
    if pos.estado is EstadoTicker.BS:
        return []
    if pos.neta_das is not None and pos.neta_das != pos.neta_fills:
        return [Consultar(COMANDO_POSICIONES), Programar(CLAVE_REPLANIFICAR, REPLANIFICAR_EN_S, {"ticker": ticker})]
    n = -pos.neta
    deseados = conjunto_deseado(pos, cfg_stops, limit_up)
    if n > 0 and not deseados:
        return _aviso_sin_nivel(pos, n)
    serie = serie_stops(ticker)
    pendientes = _stops_gestionados(pos, vivas, cfg_stops, limit_up)
    asignadas = _emparejar(deseados, pendientes)
    nuevas: list[Accion] = []
    ajustes: list[Accion] = []
    cancelaciones: list[Accion] = []
    replanificar = False
    for i, d in enumerate(deseados):
        o = asignadas.get(i)
        if o is None:
            lote = _lote_de_nivel(pos, d.nivel, solo_sin_consumir=d.proposito is Proposito.STOP_PRINCIPAL)
            orden = _orden_stop(d, ticker, ruta_stop, tokens(), version, lote.id if lote is not None else None)
            nuevas.append(EnviarOrden(orden=orden, serie=serie))
            continue
        viva = _qty_viva(o)
        if viva == d.qty:
            continue
        if o.id_das is None:
            replanificar = True
            continue
        ajustes.extend(_reemplazo(
            o, d.qty, o.stop if o.stop is not None else d.disparo, o.precio if o.precio is not None else d.limite,
            f"R-C-06/R-C-07: {d.proposito.value} de {ticker} a {d.qty} acciones (tenía {viva})", version, serie))
    capacidad = max(n, 0) - sum(d.qty for d in deseados if d.proposito is Proposito.STOP_PRINCIPAL)
    for o in _principales_al_ask(pos, vivas):
        viva = _qty_viva(o)
        objetivo = min(viva, max(capacidad, 0))
        capacidad -= objetivo
        if objetivo == viva:
            continue
        if o.id_das is None:
            replanificar = True
            continue
        if objetivo > 0 and o.stop is not None and o.precio is not None:
            ajustes.extend(_reemplazo(o, objetivo, o.stop, o.precio,
                                      f"R-C-07: principal al ask de {ticker} a {objetivo} acciones (tenía {viva})",
                                      version, serie))
        else:
            cancelaciones.append(Cancelar(id_das=o.id_das, token=o.token,
                                          motivo=f"R-C-07/R-C-11: principal al ask de {ticker} sin acciones que cubrir"))
    for o, p in pendientes:
        if o.id_das is None:
            replanificar = True
            continue
        cancelaciones.append(Cancelar(id_das=o.id_das, token=o.token,
                                      motivo=f"R-C-07/R-C-11: {p.value} sobrante en {ticker} (se conserva la más antigua)"))
    acciones = nuevas + ajustes + cancelaciones
    if replanificar:
        acciones.append(Programar(CLAVE_REPLANIFICAR, REPLANIFICAR_EN_S, {"ticker": ticker}))
    return acciones


# ── limpieza tras el fill de un stop (R-C-11, injerto A §8.6) ────────────
def limpieza_tras_fill_stop(pos: PosicionTicker, vivas: list[Orden], cot: Optional[Cotizacion], tokens: Callable[[], int],
                            cfg: Any, hora_et: datetime, version: int, orden_stop: Optional[Orden] = None,
                            limit_up: Optional[Decimal] = None) -> list[Accion]:
    """R-C-11 (limpieza estricta, por EVENTO) tras el fill de un stop; empieza SIEMPRE por `InvalidarSerie` (injerto A §8.6).

    neta == 0 → `CancelarTicker` (R-C-11 a: todo fuera al instante, incluida
    una principal colgada). neta > 0 (LARGA) → `CancelarTicker` (ninguna
    compra pendiente puede seguir viva, y una venta de exceso anterior se
    sustituye por la nueva) + `EnviarOrden(S neta LMT al bid, ruta cruzar,
    VENTA_EXCESO)` + `Avisar(2)` + `Anotar("incidente")`: vende SOLO la neta
    larga, JAMÁS la cantidad inicial (R-C-11 b: 100 cortas, principal 20,
    emergencia 100 → larga 20 → se venden 20). Sin bid se vende al último
    precio; sin ninguno, aviso nivel 3 (vender a mano) y sin orden. La clave
    del aviso lleva la versión (un incidente nuevo no se calla por el dedupe
    de 60 s de `avisos`). Supone que
    el emisor respeta el orden de las acciones (FIFO): el CANCEL ALLSYMB sale
    antes que la venta nueva. neta < 0 (sigue corta) → marca
    `principal_consumido` en los lotes cuyo principal ya quedó bajo el precio
    (20-sep: «se CANCELA el principal, su momento pasó»): si llenó un
    principal, los de su nivel y los inferiores (por `nivel` o por disparo,
    también el recortado bajo la banda); si llenó la emergencia o una
    protección, todos; si no se sabe cuál, por el precio (last, ask, bid) y,
    sin precio, todos. Cada lote que cambia se anota (`Anotar("lote")`
    parcial, H-2: tras un reinicio no se repone su principal) y después
    `plan()` cancela esos principales y ajusta la emergencia a −neta (si DAS
    la cancela, `plan` la repone). `orden_stop` y
    `limit_up` son opcionales sobre §3.16 (el decisor sabe qué token llenó);
    sin `orden_stop` se deduce de las `vivas` con `llenas > 0`. `cfg` es la
    `Config` (o un dict con «stops» y «rutas»).
    """
    ticker = pos.ticker
    acciones: list[Accion] = [InvalidarSerie(serie=serie_stops(ticker), version=version)]
    neta = pos.neta
    cfg_stops = _bloque(cfg, "stops")
    cfg_rutas = _bloque(cfg, "rutas")
    if neta == 0:
        acciones.append(CancelarTicker(ticker=ticker, motivo="R-C-11 (2): posición a cero tras el fill del stop"))
        return acciones
    if neta > 0:
        acciones.append(CancelarTicker(
            ticker=ticker, motivo=f"R-C-11 (3): {ticker} quedó LARGA {neta}; ninguna compra pendiente puede seguir viva"))
        das = f" (DAS dice {pos.neta_das})" if pos.neta_das is not None and pos.neta_das != neta else ""
        precio = _precio_venta_exceso(cot)
        if precio is None:
            acciones.append(Avisar(nivel=Nivel.MAXIMO, grupo=Grupo.B, clave=f"exceso:{ticker}:{version}",
                                   texto=(f"R-C-11: {ticker} quedó LARGA {neta} acciones tras el fill del stop{das} y no hay "
                                          f"cotización de DAS para vender el exceso: VENDER A MANO {neta} acciones")))
            acciones.append(Anotar("incidente", {"tipo": "cuenta_larga_sin_cotizacion", "ticker": ticker, "neta": neta,
                                                 "neta_das": pos.neta_das, "regla": "R-C-11 (b)", "version_stops": version}))
            return acciones
        ruta_cruzar = ruta_de(cfg_rutas, "cruzar", precio, hora_et)
        orden = OrdenNueva(token=tokens(), lado=Lado.VENTA, ticker=ticker, ruta=ruta_cruzar, qty=neta,
                           tipo=TipoOrden.LIMITE, precio=precio, tif="DAY+", post_only=False,
                           proposito=Proposito.VENTA_EXCESO, version=version)
        acciones.append(EnviarOrden(orden=orden))
        acciones.append(Avisar(nivel=Nivel.AVISO, grupo=Grupo.B, clave=f"exceso:{ticker}:{version}",
                               texto=(f"R-C-11: {ticker} quedó LARGA {neta} acciones tras el fill del stop{das}; se venden "
                                      f"{neta} (solo el exceso) al bid {precio} por {ruta_cruzar}")))
        acciones.append(Anotar("incidente", {"tipo": "cuenta_larga", "ticker": ticker, "neta": neta, "vendidas": neta,
                                             "neta_das": pos.neta_das, "precio": str(precio), "ruta": ruta_cruzar,
                                             "token": orden.token, "regla": "R-C-11 (b)", "version_stops": version}))
        return acciones
    consumidos = _marcar_principal_consumido(pos, vivas, orden_stop, cot, cfg_stops, limit_up)
    acciones.extend(_anotar_lotes(ticker, consumidos, {"principal_consumido": True}, "R-C-11 (c)"))
    ruta_stop = ruta_de(cfg_rutas, "stop", _precio_referencia(cot), hora_et)
    acciones.extend(plan(pos, vivas, cfg_stops, limit_up, tokens, hora_et, ruta_stop, version))
    return acciones


# ── principal rebasado (R-C-01 v3, mitigación FIJADA 22-sep, decisión (a)) ──
def reasignar_principal_rebasado(pos: PosicionTicker, vivas: list[Orden], cot: Optional[Cotizacion], cfg_stops: Mapping,
                                 tokens: Callable[[], int], hora_et: datetime, ruta_stop: str, version: int,
                                 limit_up: Optional[Decimal] = None) -> list[Accion]:
    """R-C-01 decisión (a): el ask pasa de largo el LÍMITE de un principal sin llenarlo.

    Rebasado = principal vivo sin fills con ask > su límite y cuyo nivel aún
    tiene lotes sin consumir (así es IDEMPOTENTE: un `$Quote` repetido antes
    del `Canceled` no hace nada). Se cancela y sus acciones se SUMAN al
    principal del siguiente nivel por encima que no esté también pasado
    (límite ≥ ask): los lotes rebasados pasan a ese `nivel_stop` y la cantidad
    sale de `conjunto_deseado` (`Reemplazar` + `Programar("replace_verificar")`).
    Si no hay nivel por encima, las acciones se recolocan en un principal
    nuevo al ask (disparo ask, límite ask·(1 + 3 %), recortado bajo la banda
    si toca, R-F-02) con propósito STOP_PROTECCION y `lote_id` (así `plan` lo
    recorta pero no lo confunde con el principal viejo) y los lotes quedan con
    `principal_consumido=True`; si ese disparo ya alcanza el de la emergencia,
    NO se pone (compraría dos veces con ella: R-C-11) y solo se anota. La
    emergencia NO se toca («siempre una sola emergencia con toda la posición»,
    sobre el L de la estrategia). Orden: `Anotar("lote")` parcial de cada lote
    cambiado (write-ahead, H-2), `Cancelar` los rebasados (la emergencia sigue
    cubriendo), el reemplazo o la orden nueva y `Anotar("stop_reasignado")`.
    Sin ask, sin corto, en cisne negro (R-G-01:
    no perseguir), en halt (manda R-F-01), con `neta_das` ≠ `neta_fills`
    (corrección 2; `plan` ya pide GET POSITIONS) o sin nada rebasado con
    `id_das` → []. `limit_up` es opcional sobre §3.16; `hora_et` se conserva
    por el contrato.
    """
    ticker = pos.ticker
    ask = _precio_valido(getattr(cot, "ask", None))
    n = -pos.neta
    if ask is None or n <= 0 or pos.estado in (EstadoTicker.BS, EstadoTicker.HALT):
        return []
    if pos.neta_das is not None and pos.neta_das != pos.neta_fills:
        return []
    sin_consumir = sorted({lote.nivel_stop for lote in _lotes_vivos(pos) if not lote.principal_consumido})   # type: ignore[type-var]
    if not sin_consumir:
        return []
    principales = [(o, _nivel_de_principal(o, sin_consumir, cfg_stops, limit_up))   # type: ignore[arg-type]
                   for (o, p) in _stops_gestionados(pos, vivas, cfg_stops, limit_up) if p is Proposito.STOP_PRINCIPAL]
    rebasados = [(o, L) for (o, L) in principales
                 if L is not None and o.llenas == 0 and _precio_valido(o.precio) is not None and ask > o.precio]
    cancelables = [(o, L) for (o, L) in rebasados if o.id_das is not None]
    if not cancelables:
        return []
    niveles_movidos = sorted({L for (_, L) in cancelables})
    ya_rebasados = {id(o) for (o, _) in rebasados}
    superiores = [(o, L) for (o, L) in principales
                  if L is not None and id(o) not in ya_rebasados and L > niveles_movidos[-1]
                  and (o.precio is None or o.precio >= ask)]
    lotes_movidos = [lote for lote in _lotes_vivos(pos) if not lote.principal_consumido and lote.nivel_stop in niveles_movidos]
    total = min(sum(_qty_viva(o) for (o, _) in cancelables), n)
    cancelaciones: list[Accion] = [
        Cancelar(id_das=o.id_das, token=o.token,   # type: ignore[arg-type]
                 motivo=f"R-C-01 (a): el ask {ask} rebasó el límite {o.precio} del principal de {ticker} sin fill")
        for (o, _) in cancelables]
    serie = serie_stops(ticker)
    datos: dict[str, Any] = {"ticker": ticker, "ask": str(ask), "acciones": total,
                             "desde": [str(L) for L in niveles_movidos], "lotes": [lote.id for lote in lotes_movidos],
                             "regla": "R-C-01 (a)"}
    if superiores:
        destino, nivel_destino = min(superiores, key=lambda par: (par[1], _clave_antiguedad(par[0])))
        for lote in lotes_movidos:
            lote.nivel_stop = nivel_destino
        acciones = _anotar_lotes(ticker, lotes_movidos, {"nivel_stop": str(nivel_destino)}, "R-C-01 (a)") + cancelaciones
        deseado = _principal_deseado(pos, cfg_stops, limit_up, nivel_destino)
        viva = _qty_viva(destino)
        if deseado is not None and deseado.qty != viva:
            if destino.id_das is None:
                acciones.append(Programar(CLAVE_REPLANIFICAR, REPLANIFICAR_EN_S, {"ticker": ticker}))
            else:
                acciones.extend(_reemplazo(
                    destino, deseado.qty, destino.stop if destino.stop is not None else deseado.disparo,
                    destino.precio if destino.precio is not None else deseado.limite,
                    f"R-C-01 (a): {ticker} suma {total} acciones del principal rebasado al principal de {nivel_destino}",
                    version, serie))
        acciones.append(Anotar("stop_reasignado", {**datos, "hacia": str(nivel_destino), "modo": "sumar_al_superior"}))
        return acciones
    for lote in lotes_movidos:
        lote.principal_consumido = True
    acciones = _anotar_lotes(ticker, lotes_movidos, {"principal_consumido": True}, "R-C-01 (a)") + cancelaciones
    p_limite = _pct(cfg_stops, "principal_limite_pct", STOP_PRINCIPAL_LIMITE_PCT)
    margen = _pct(cfg_stops, "margen_bajo_limit_up_pct", STOP_MARGEN_BAJO_LIMIT_UP_PCT)
    disparo_ask = redondear_arriba(ask)
    (disparo, limite), bajo = _bajo_banda((disparo_ask, con_techo(disparo_ask, p_limite, arriba=True)),
                                          _recorte_banda(limit_up, margen), p_limite)
    emergencia = next((d for d in conjunto_deseado(pos, cfg_stops, limit_up) if d.proposito is Proposito.STOP_EMERGENCIA), None)
    if emergencia is not None and disparo >= emergencia.disparo:
        acciones.append(Anotar("stop_reasignado", {**datos, "hacia": str(emergencia.disparo),
                                                   "modo": "cubierto_por_emergencia"}))
        return acciones
    orden = OrdenNueva(token=tokens(), lado=Lado.COMPRA, ticker=ticker, ruta=ruta_stop, qty=total,
                       tipo=TipoOrden.STOP_LIMITE_PP, precio=limite, stop=disparo, tif="DAY+", post_only=False,
                       proposito=Proposito.STOP_PROTECCION, lote_id=lotes_movidos[0].id, nivel=disparo, version=version)
    acciones.append(EnviarOrden(orden=orden, serie=serie))
    acciones.append(Anotar("stop_reasignado", {**datos, "hacia": str(disparo), "limite": str(limite), "bajo_banda": bajo,
                                               "token": orden.token, "modo": "principal_nuevo_al_ask"}))
    return acciones


# ── REPLACE sobre STOPLMTP (2h.8, §5.6) ─────────────────────────────────
def tipo_conserva_pp(tipo_das_crudo: Optional[str], patron_esperado: Optional[str]) -> Optional[bool]:
    """2h.8 / §5.6: tras un REPLACE, ¿el tipo que enseña %ORDER sigue siendo el de pre/post (STOPLMTP)?

    `None` = aún no se puede saber: sin `%ORDER` (`tipo_das_crudo` None), sin
    patrón configurado (`cfg.stops.tipo_esperado_en_order` es null hasta que
    `comprobar_das.py` lo fije el primer día) o con un patrón que no compila.
    Si no, `re.search` del patrón sobre el tipo crudo sin distinguir
    mayúsculas. `False` → el decisor cancela y repone (F2.2). Nunca lanza.
    """
    if tipo_das_crudo is None or patron_esperado is None or not str(patron_esperado).strip():
        return None
    try:
        regex = re.compile(str(patron_esperado), re.IGNORECASE)
    except re.error:
        return None
    return regex.search(str(tipo_das_crudo)) is not None


# ── protección para posiciones desconocidas (R-C-10 caso 4) ─────────────
def stop_proteccion(ticker: str, qty: int, es_corta: bool, last: Decimal, pct: Decimal, token: int,
                    ruta: str, version: int) -> OrdenNueva:
    """R-C-10 (4): stop de protección a `pct` % del último precio para una posición que el bot no reconoce.

    Corta → COMPRA STOPLMTP con disparo last·(1 + pct) redondeado arriba y
    límite disparo·(1 + 3 %) (el margen del principal, R-C-01); larga → VENTA
    STOPLMTP con disparo last·(1 − pct) redondeado abajo y límite
    disparo·(1 − 3 %) redondeado abajo (lado permisivo de cada una).
    Propósito STOP_PROTECCION, SIN lote (así `plan` no la toca nunca),
    `nivel` = disparo. Lanza ValueError si `last` no es un precio > 0, si
    `pct` es negativo (`precios.con_techo`) o si `qty` no es int > 0
    (`OrdenNueva`).
    """
    ultimo = de_float(last)
    margen = de_float(pct)
    if es_corta:
        disparo = con_techo(ultimo, margen, arriba=True)
        limite = con_techo(disparo, STOP_PRINCIPAL_LIMITE_PCT, arriba=True)
        lado = Lado.COMPRA
    else:
        disparo = con_techo(ultimo, margen, arriba=False)
        limite = con_techo(disparo, STOP_PRINCIPAL_LIMITE_PCT, arriba=False)
        lado = Lado.VENTA
    return OrdenNueva(token=token, lado=lado, ticker=ticker, ruta=ruta, qty=qty, tipo=TipoOrden.STOP_LIMITE_PP,
                      precio=limite, stop=disparo, tif="DAY+", post_only=False, proposito=Proposito.STOP_PROTECCION,
                      lote_id=None, nivel=disparo, version=version)


# ── acciones cortas sin cobertura (R-C-03, plan B del vigilante) ─────────
def descubiertas(pos: PosicionTicker, vivas: list[Orden], cfg_stops: Optional[Mapping] = None,
                 limit_up: Optional[Decimal] = None) -> int:
    """R-C-03: acciones netas cortas sin una emergencia (o protección) CONFIRMADA que las cubra.

    Cubren las STOPLMTP de compra del ticker en estado Accepted/Partial/Hold/
    Triggered (una Sending no es «stop aceptado») con propósito
    STOP_EMERGENCIA o STOP_PROTECCION (la protección es la «emergencia» de
    una posición sin lotes, R-C-10 caso 4), por su cantidad VIVA. Un principal
    no cubre: la emergencia es la que lleva la posición entera. Una orden sin
    etiqueta (DESCONOCIDA, p. ej. del vigilante sin diario) se clasifica con
    `inferir_proposito` sobre los niveles de los lotes (`cfg_stops` y
    `limit_up` opcionales sobre §3.16; sin ellos, constantes de `tipos`).
    > 0 dispara R-C-03 (reintentos) y el plan B del vigilante
    (PLAN_B_DESCUBIERTA_S). Posición plana o larga → 0.
    """
    n = -pos.neta
    if n <= 0:
        return 0
    cfg = cfg_stops if cfg_stops is not None else {}
    niveles_lotes = _niveles_de_lotes(pos)
    cubiertas = 0
    for o in _unicas(vivas):
        if o.ticker != pos.ticker or not _es_stop_compra(o) or o.estado not in ESTADOS_CONFIRMADOS:
            continue
        proposito = o.proposito
        if proposito is Proposito.DESCONOCIDA:
            proposito = inferir_proposito(o, niveles_lotes, cfg, limit_up)   # type: ignore[arg-type]
        if proposito in (Proposito.STOP_EMERGENCIA, Proposito.STOP_PROTECCION):
            cubiertas += _qty_viva(o)
    return max(n - cubiertas, 0)


# ── cantidad cancelada (injerto A §8.7, riesgo 5) ────────────────────────
def cantidad_cancelada(act: Union[MsgOrderAct, MsgOrden]) -> int:
    """Injerto A §8.7: la cantidad cancelada sale SIEMPRE de `%OrderAct Canceled qty` o de `%ORDER cxlqty`, nunca de lo pedido.

    `%OrderAct` con acción distinta de `Canceled` (Canceling, Execute,
    Replaced…) → 0: nada está confirmado todavía (manual L469-471: «Canceled:
    Canceled shares»). `%ORDER` → `cxlqty` (L377), en cualquier estado. Nunca
    negativa. Lanza TypeError con otro objeto.
    """
    if isinstance(act, MsgOrderAct):
        return max(int(act.qty), 0) if str(act.accion).strip().lower() == "canceled" else 0
    if isinstance(act, MsgOrden):
        return max(int(act.cxlqty), 0)
    raise TypeError(f"cantidad_cancelada espera MsgOrderAct o MsgOrden, no {type(act).__name__}")


# ── ayudantes privados (todos puros) ─────────────────────────────────────
def _pct(cfg_stops: Any, clave: str, defecto: Decimal) -> Decimal:
    """Porcentaje del bloque `stops` (float del JSON o Decimal) convertido UNA vez; ausente o null → constante de tipos."""
    if not isinstance(cfg_stops, Mapping):
        raise TypeError(f"cfg_stops debe ser el bloque «stops» de la config (dict), no {type(cfg_stops).__name__}")
    valor = cfg_stops.get(clave)
    pct = de_float(valor) if valor is not None else defecto
    if pct < 0:
        raise ValueError(f"{clave} no puede ser negativo: {pct}")
    return pct


def _bloque(cfg: Any, nombre: str) -> Mapping:
    """`cfg.stops` / `cfg.rutas` de una `Config`, o `cfg["stops"]` si llega un dict. ValueError si falta o no es un dict."""
    if isinstance(cfg, Mapping):
        valor = cfg.get(nombre)
    else:
        valor = getattr(cfg, nombre, None)
    if not isinstance(valor, Mapping):
        raise ValueError(f"el bloque {nombre!r} de la config falta o no es un dict")
    return valor


def _precio_valido(x: Any) -> Optional[Decimal]:
    """`Decimal` finito > 0 (vía `de_float`) o None: None, 0, negativos, NaN, texto no numérico y bool no son precios."""
    if x is None:
        return None
    try:
        valor = de_float(x)
    except ValueError:
        return None
    return valor if valor > 0 else None


def _recorte_banda(limit_up: Optional[Decimal], margen: Decimal) -> Optional[tuple[Decimal, Decimal]]:
    """(banda, disparo recortado = banda·(1 − margen) redondeado abajo) o None sin banda válida (R-F-02)."""
    banda = _precio_valido(limit_up)
    if banda is None:
        return None
    recortado = con_techo(banda, margen, arriba=False)
    if recortado <= 0:
        raise ValueError(f"margen bajo la banda inválido: {margen} % sobre {banda}")
    return banda, recortado


def _bajo_banda(par: tuple[Decimal, Decimal], recorte: Optional[tuple[Decimal, Decimal]],
                p_limite: Decimal) -> tuple[tuple[Decimal, Decimal], bool]:
    """R-F-02: (disparo, límite) tal cual si queda bajo la banda; si no, (recortado, recortado·(1 + p_limite)) y True."""
    if recorte is None or par[0] < recorte[0]:
        return par, False
    recortado = recorte[1]
    return (recortado, con_techo(recortado, p_limite, arriba=True)), True


def _variantes(niveles_ok: list[Decimal], cfg_stops: Mapping, limit_up: Optional[Decimal]) -> list[NivelesStop]:
    """Los niveles de cada L sin banda y, si hay banda válida, también recortados (para reconocer las dos versiones)."""
    variantes: list[NivelesStop] = []
    con_banda = _precio_valido(limit_up) is not None
    for L in niveles_ok:
        variantes.append(niveles(L, cfg_stops))
        if con_banda:
            variantes.append(niveles(L, cfg_stops, limit_up))
    return variantes


def _nivel_de_lote(lote: Lote) -> Optional[Decimal]:
    """El nivel de stop del lote si es un `Decimal` finito > 0 (A12); cualquier otra cosa → None (no se opera sobre él)."""
    nivel = lote.nivel_stop
    if isinstance(nivel, Decimal) and nivel.is_finite() and nivel > 0:
        return nivel
    return None


def _es_lote_corto_con_acciones(lote: Lote) -> bool:
    """Lote que aún tiene acciones cortas: ni cerrado/cancelado, con llenas > 0 y no largo (R-E-01: el bot solo va corto)."""
    if lote.estado in _ESTADOS_LOTE_MUERTO or type(lote.llenas) is not int or lote.llenas <= 0:
        return False
    return not str(lote.direccion).strip().lower().startswith("long")


def _lotes_vivos(pos: PosicionTicker) -> list[Lote]:
    """Lotes cortos con acciones y nivel de stop válido, ordenados por (nivel, id)."""
    vivos = [lote for lote in pos.lotes.values() if _es_lote_corto_con_acciones(lote) and _nivel_de_lote(lote) is not None]
    vivos.sort(key=lambda lote: (lote.nivel_stop, lote.id))   # type: ignore[arg-type,return-value]
    return vivos


def _niveles_de_lotes(pos: PosicionTicker) -> list[Decimal]:
    """Niveles L distintos de los lotes vivos, ascendentes (lo que `inferir_proposito` compara)."""
    return sorted({lote.nivel_stop for lote in _lotes_vivos(pos)})   # type: ignore[type-var]


def _niveles_validos(niveles_lotes: Iterable[Any]) -> list[Decimal]:
    return [nivel for nivel in (_precio_valido(L) for L in niveles_lotes) if nivel is not None]


def _lote_de_nivel(pos: PosicionTicker, nivel: Decimal, solo_sin_consumir: bool) -> Optional[Lote]:
    """Primer lote vivo (por nivel, id) de ese nivel ±1 tick; para el principal solo los de principal no consumido."""
    for lote in _lotes_vivos(pos):
        if solo_sin_consumir and lote.principal_consumido:
            continue
        if _mismo_precio(lote.nivel_stop, nivel):
            return lote
    return None


def _tipo_es_stop(tipo: str, cfg_stops: Optional[Mapping]) -> bool:
    """Tipo crudo de %ORDER de un stop: `TIPO_STOP_EN_ORDER` o el patrón `tipo_esperado_en_order` de la config (si compila)."""
    if _RE_TIPO_STOP.search(tipo):
        return True
    patron = cfg_stops.get("tipo_esperado_en_order") if isinstance(cfg_stops, Mapping) else None
    if patron is None or not str(patron).strip():
        return False
    try:
        return re.search(str(patron), tipo, re.IGNORECASE) is not None
    except re.error:
        return False


def _es_stop_compra(o: Any, cfg_stops: Optional[Mapping] = None) -> bool:
    """STOPLMTP de COMPRA: `Orden` por lado y tipo; `MsgOrden` por lado «B» y un tipo de stop reconocido (PROVISIONAL)."""
    if isinstance(o, Orden):
        return o.lado == Lado.COMPRA and o.tipo == TipoOrden.STOP_LIMITE_PP
    if isinstance(o, MsgOrden):
        return str(o.lado).strip().upper() in ("B", "BUY") and _tipo_es_stop(str(o.tipo), cfg_stops)
    return False


def _numero_de_texto(texto: str) -> Optional[Decimal]:
    """Primer número del texto: «2.97», «2,97» (coma decimal) o «1,234.50» (coma de miles); None si no hay o no es precio."""
    encontrado = _RE_NUMERO.search(texto)
    if encontrado is None:
        return None
    crudo = encontrado.group(0)
    if "," in crudo and "." in crudo:
        crudo = crudo.replace(",", "")
    elif crudo.count(",") == 1:
        crudo = crudo.replace(",", ".")
    else:
        crudo = crudo.replace(",", "")
    return _precio_valido(crudo)


def _disparo_de(o: Any) -> Optional[Decimal]:
    """Disparo de un stop: `Orden.stop` (o `precio`); `MsgOrden`: primer número del tipo («SLP: 2.97 2.99») o `precio`."""
    if isinstance(o, Orden):
        disparo = _precio_valido(o.stop)
        return disparo if disparo is not None else _precio_valido(o.precio)
    if isinstance(o, MsgOrden):
        disparo = _numero_de_texto(str(o.tipo))
        return disparo if disparo is not None else _precio_valido(o.precio)
    return None


def _mismo_precio(a: Optional[Decimal], b: Optional[Decimal]) -> bool:
    """±1 tick (el tick del precio de referencia `b`)."""
    if a is None or b is None or not a.is_finite() or not b.is_finite():
        return False
    return abs(a - b) <= tick_de(b)


def _casa(o: Orden, d: StopDeseado) -> bool:
    """Una viva satisface un deseado si su disparo está a ±1 tick del deseado; sin disparo, por `nivel`; sin nada, no."""
    disparo = _disparo_de(o)
    if disparo is not None:
        return _mismo_precio(disparo, d.disparo)
    return _mismo_precio(_precio_valido(o.nivel), d.nivel)


def _clave_antiguedad(o: Orden) -> tuple[int, int, float]:
    """La más ANTIGUA primero: con `id_das` por id (servidor) y, sin él (aún Sending, las más nuevas), por `enviada_en`."""
    if o.id_das is not None:
        return (0, int(o.id_das), o.enviada_en)
    return (1, 0, o.enviada_en)


def _clave_casado(o: Orden, d: StopDeseado) -> tuple[Decimal, tuple[int, int, float]]:
    """Mejor candidata: disparo más cercano y, a igualdad, la más antigua (R-C-07 plan B: la que sobra es la más nueva)."""
    disparo = _disparo_de(o)
    if disparo is not None:
        distancia = abs(disparo - d.disparo)
    else:
        nivel = _precio_valido(o.nivel)
        distancia = abs(nivel - d.nivel) if nivel is not None else _CERO
    return (distancia, _clave_antiguedad(o))


def _mismo_nivel(o: Orden, d: StopDeseado) -> bool:
    """La orden se puso PARA ese deseado: su campo `nivel` es exactamente el L del deseado (igualdad de valor Decimal)."""
    nivel = _precio_valido(o.nivel)
    return nivel is not None and nivel == d.nivel


def _emparejar(deseados: list[StopDeseado], pendientes: list[tuple[Orden, Proposito]]) -> dict[int, Orden]:
    """Deseado (por índice) → orden viva que lo satisface; lo casado se QUITA de `pendientes` (lo que queda sobra).

    Dos fases para que el resultado no dependa del orden de los deseados (idempotencia): primero cada deseado
    reclama las candidatas de SU MISMO nivel (identidad: con la banda varios principales pueden compartir disparo);
    después, los que siguen sin orden toman del resto por disparo más cercano y antigüedad. Candidata = mismo
    propósito y disparo a ±1 tick (`_casa`).
    """
    asignadas: dict[int, Orden] = {}
    for solo_su_nivel in (True, False):
        for i, d in enumerate(deseados):
            if i in asignadas:
                continue
            candidatas = [o for (o, p) in pendientes
                          if p is d.proposito and _casa(o, d) and (not solo_su_nivel or _mismo_nivel(o, d))]
            if candidatas:
                elegida = min(candidatas, key=lambda o: _clave_casado(o, d))
                _quitar(pendientes, elegida)
                asignadas[i] = elegida
    return asignadas


def _qty_viva(o: Orden) -> int:
    """Acciones que la orden aún puede comprar: `lvqty` si DAS ya lo dijo (Partial/Triggered), si no `qty − llenas`."""
    if o.estado in (EstadoOrden.PARTIAL, EstadoOrden.TRIGGERED) and o.lvqty > 0:
        return max(int(o.lvqty), 0)
    return max(int(o.qty) - int(o.llenas), 0)


def _unicas(vivas: Iterable[Any]) -> list[Orden]:
    """Solo `Orden`, sin repetir el MISMO objeto (una lista con la misma orden dos veces no debe cancelarla dos veces)."""
    vistas: set[int] = set()
    unicas: list[Orden] = []
    for o in vivas:
        if isinstance(o, Orden) and id(o) not in vistas:
            vistas.add(id(o))
            unicas.append(o)
    return unicas


def _quitar(ordenes: list[tuple[Orden, Proposito]], orden: Orden) -> None:
    """Quita por IDENTIDAD (dos `Orden` con los mismos campos son iguales para `==`)."""
    for i, (o, _) in enumerate(ordenes):
        if o is orden:
            del ordenes[i]
            return


def _es_viva(o: Orden, ticker: str) -> bool:
    return o.ticker == ticker and _es_stop_compra(o) and o.estado in ESTADOS_VIVOS and _qty_viva(o) > 0


def _proposito_efectivo(o: Orden, niveles_lotes: list[Decimal], cfg_stops: Mapping,
                        limit_up: Optional[Decimal]) -> Proposito:
    """Etiqueta propia si ya es principal/emergencia; protección propia intocable; lo demás (vigilante, desconocida) se infiere."""
    if o.proposito in PROPOSITOS_GESTIONADOS:
        return o.proposito
    if o.proposito is Proposito.STOP_PROTECCION and o.origen is not Origen.VIGILANTE:
        return Proposito.STOP_PROTECCION
    return inferir_proposito(o, niveles_lotes, cfg_stops, limit_up)


def _stops_gestionados(pos: PosicionTicker, vivas: list[Orden], cfg_stops: Mapping,
                       limit_up: Optional[Decimal]) -> list[tuple[Orden, Proposito]]:
    """STOPLMTP de compra VIVAS del ticker con propósito efectivo principal/emergencia (cualquier Origen)."""
    niveles_lotes = _niveles_de_lotes(pos)
    gestionadas: list[tuple[Orden, Proposito]] = []
    for o in _unicas(vivas):
        if not _es_viva(o, pos.ticker):
            continue
        proposito = _proposito_efectivo(o, niveles_lotes, cfg_stops, limit_up)   # type: ignore[arg-type]
        if proposito in PROPOSITOS_GESTIONADOS:
            gestionadas.append((o, proposito))
    return gestionadas


def _principales_al_ask(pos: PosicionTicker, vivas: list[Orden]) -> list[Orden]:
    """Protecciones PROPIAS con `lote_id` de la posición (solo las crea `reasignar_principal_rebasado`), por disparo y antigüedad."""
    propias = [o for o in _unicas(vivas)
               if _es_viva(o, pos.ticker) and o.proposito is Proposito.STOP_PROTECCION and o.origen is not Origen.VIGILANTE
               and o.lote_id is not None and o.lote_id in pos.lotes]
    propias.sort(key=lambda o: (_disparo_de(o) or _CERO, _clave_antiguedad(o)))
    return propias


def _orden_stop(d: StopDeseado, ticker: str, ruta_stop: str, token: int, version: int, lote_id: Optional[str]) -> OrdenNueva:
    """STOPLMTP de COMPRA por la ruta de stops con la versión del objetivo (§5 F2.1)."""
    return OrdenNueva(token=token, lado=Lado.COMPRA, ticker=ticker, ruta=ruta_stop, qty=d.qty,
                      tipo=TipoOrden.STOP_LIMITE_PP, precio=d.limite, stop=d.disparo, tif="DAY+", post_only=False,
                      proposito=d.proposito, lote_id=lote_id, nivel=d.nivel, version=version)


def _reemplazo(o: Orden, qty: int, stop: Optional[Decimal], precio: Optional[Decimal], motivo: str, version: int,
               serie: str) -> list[Accion]:
    """`Reemplazar` (con versión y serie, injerto §8.6) + `Programar("replace_verificar")` con la cantidad ABIERTA buscada (2h.8)."""
    return [Reemplazar(id_das=o.id_das, token=o.token, qty=qty, stop=stop, precio=precio, motivo=motivo,   # type: ignore[arg-type]
                       version=version, serie=serie),
            Programar(CLAVE_VERIFICAR_REPLACE, VERIFICAR_REPLACE_EN_S, {"token": o.token, "ticker": o.ticker, "qty_objetivo": qty})]


def _principal_deseado(pos: PosicionTicker, cfg_stops: Mapping, limit_up: Optional[Decimal],
                       nivel: Decimal) -> Optional[StopDeseado]:
    """El principal deseado de ese nivel (±1 tick) según `conjunto_deseado`, o None si la posición ya no le deja acciones."""
    for d in conjunto_deseado(pos, cfg_stops, limit_up):
        if d.proposito is Proposito.STOP_PRINCIPAL and _mismo_precio(d.nivel, nivel):
            return d
    return None


def _nivel_de_principal(o: Orden, candidatos: list[Decimal], cfg_stops: Mapping, limit_up: Optional[Decimal]) -> Optional[Decimal]:
    """Nivel L (de los `candidatos`) al que pertenece un principal vivo: por su `nivel` o, sin él, por su disparo (±1 tick)."""
    propio = _precio_valido(o.nivel)
    if propio is not None:
        cercanos = [L for L in candidatos if _mismo_precio(propio, L)]
        return min(cercanos, key=lambda L: abs(L - propio)) if cercanos else None
    disparo = _disparo_de(o)
    if disparo is None:
        return None
    mejor: Optional[tuple[Decimal, Decimal]] = None
    for L in candidatos:
        for v in _variantes([L], cfg_stops, limit_up):
            if _mismo_precio(disparo, v.principal_disparo):
                distancia = abs(disparo - v.principal_disparo)
                if mejor is None or distancia < mejor[0]:
                    mejor = (distancia, L)
    return mejor[1] if mejor is not None else None


def _aviso_sin_nivel(pos: PosicionTicker, n: int) -> list[Accion]:
    """Corto sin ningún stop calculable: si es porque hay lotes sin nivel válido, aviso nivel 3 (deduplicado por clave)."""
    sin_nivel = sorted(lote.id for lote in pos.lotes.values()
                       if _es_lote_corto_con_acciones(lote) and _nivel_de_lote(lote) is None)
    if not sin_nivel:
        return []
    return [Avisar(nivel=Nivel.MAXIMO, grupo=Grupo.B, clave=f"stops_sin_nivel:{pos.ticker}",
                   texto=(f"R-C-03: {pos.ticker} está corto {n} acciones y sus lotes {', '.join(sin_nivel)} no tienen un nivel "
                          f"de stop válido: no se pueden calcular el principal ni la emergencia. Los stops vivos NO se tocan; "
                          f"poner la protección a mano"))]


def _maximo(valores: Iterable[Optional[Decimal]]) -> Optional[Decimal]:
    presentes = [v for v in valores if v is not None]
    return max(presentes) if presentes else None


def _marcar_principal_consumido(pos: PosicionTicker, vivas: list[Orden], orden_stop: Optional[Orden],
                                cot: Optional[Cotizacion], cfg_stops: Mapping, limit_up: Optional[Decimal]) -> list[Lote]:
    """R-C-11 (c) / decisión 20-sep: los principales cuyo disparo ya quedó bajo el precio no se reponen (ver limpieza).

    Devuelve los lotes que CAMBIAN (no estaban consumidos) para anotarlos en el diario.
    """
    vivos = _lotes_vivos(pos)
    if not vivos:
        return []
    if orden_stop is not None:
        llenados = [orden_stop]
    else:
        llenados = [o for o in _unicas(vivas) if o.ticker == pos.ticker and _es_stop_compra(o) and o.llenas > 0]
    consumir: Optional[list[Lote]] = None
    if llenados:
        niveles_lotes = _niveles_de_lotes(pos)
        propositos = [_proposito_efectivo(o, niveles_lotes, cfg_stops, limit_up) for o in llenados]   # type: ignore[arg-type]
        if any(p is not Proposito.STOP_PRINCIPAL for p in propositos):
            consumir = vivos
        else:
            techo_nivel = _maximo(_precio_valido(o.nivel) for o in llenados)
            techo_disparo = _maximo(_disparo_de(o) for o in llenados)
            if techo_nivel is not None or techo_disparo is not None:
                consumir = [lote for lote in vivos if _principal_pasado(lote, techo_nivel, techo_disparo, cfg_stops, limit_up)]
    if consumir is None:
        referencia = _precio_mercado(cot)
        consumir = vivos if referencia is None else [
            lote for lote in vivos if niveles(lote.nivel_stop, cfg_stops, limit_up).principal_disparo <= referencia]   # type: ignore[arg-type]
    cambiados = [lote for lote in consumir if not lote.principal_consumido]
    for lote in cambiados:
        lote.principal_consumido = True
    return cambiados


def _anotar_lotes(ticker: str, lotes: list[Lote], campos: dict[str, Any], regla: str) -> list[Accion]:
    """H-2 / §8: un registro `lote` PARCIAL por lote cambiado (el diario conserva los campos que no trae), con fsync."""
    return [Anotar("lote", {"lote_id": lote.id, "ticker": ticker, **campos, "regla": regla}) for lote in lotes]


def _principal_pasado(lote: Lote, techo_nivel: Optional[Decimal], techo_disparo: Optional[Decimal], cfg_stops: Mapping,
                      limit_up: Optional[Decimal]) -> bool:
    """El principal del lote ya disparó si su nivel ≤ el del principal que llenó o su disparo (con banda) ≤ el disparo que llenó."""
    if techo_nivel is not None and lote.nivel_stop <= techo_nivel + tick_de(techo_nivel):   # type: ignore[operator]
        return True
    if techo_disparo is not None:
        disparo = niveles(lote.nivel_stop, cfg_stops, limit_up).principal_disparo   # type: ignore[arg-type]
        return disparo <= techo_disparo + tick_de(techo_disparo)
    return False


def _precio_mercado(cot: Optional[Cotizacion]) -> Optional[Decimal]:
    """Precio del momento para saber qué disparos quedaron atrás: último (el STOPLMTP dispara por print), si no ask, si no bid."""
    for campo in ("last", "ask", "bid"):
        precio = _precio_valido(getattr(cot, campo, None))
        if precio is not None:
            return precio
    return None


def _precio_venta_exceso(cot: Optional[Cotizacion]) -> Optional[Decimal]:
    """Al bid (R-C-11 b); sin bid, al último precio; sin ninguno, None. Redondeado ABAJO (lado permisivo de una venta)."""
    for campo in ("bid", "last"):
        precio = _precio_valido(getattr(cot, campo, None))
        if precio is not None:
            return redondear_abajo(precio)
    return None


def _precio_referencia(cot: Optional[Cotizacion]) -> Decimal:
    """Precio para resolver la ruta de stop (la tabla no depende de él, pero `precios.ruta` lo exige)."""
    precio = _precio_mercado(cot)
    return precio if precio is not None else Decimal("1")
