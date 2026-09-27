"""Stops residentes STOPLMTP: niveles, conjunto deseado, plan idempotente, limpieza, reasignación y protección.

QUÉ HACE. Las reglas del área C del libro que deciden QUÉ órdenes de stop
deben vivir en DAS para cada posición corta y cómo se llega a ese conjunto
sin duplicar nada ni quedarse largo:
  * `niveles`: los cuatro precios de R-C-01 v3 (+3 / +13 / +63 SUMADOS sobre
    el nivel L de la estrategia), recortados bajo la banda limit up (R-F-02).
  * `conjunto_deseado`: UN principal por nivel L distinto y UNA emergencia
    con toda la posición sobre el L más alto (decisión (a) de Jaume, 22-sep);
    un principal que ya no dispara ANTES que la emergencia no se pone (D2a-01).
  * `plan`: casa lo deseado con las órdenes vivas de CUALQUIER origen (aquí
    está el neteo con el vigilante de R-C-07) y devuelve lo mínimo que falta,
    sobra o tiene otra cantidad. IDEMPOTENTE: aplicado dos veces, la segunda
    no produce nada.
  * `limpieza_tras_fill_stop`: R-C-11 por EVENTO (neta 0 → cancelar todo;
    LARGA → vender SOLO el exceso que no se esté vendiendo ya, a
    bid·(1 − 1 %), y comprobarlo a 1 s; sigue corta → principal consumido y
    `plan`).
  * `verificar_venta_exceso`: el temporizador `exceso_verificar` (D2a-04):
    persigue la venta del exceso al bid nuevo hasta 3 veces y después avisa
    nivel 3 «VENDER A MANO».
  * `reasignar_principal_rebasado`: R-C-01 decisión (a) cuando el PRECIO (el
    último y el ask) pasa de largo el límite de un principal sin llenarlo.
  * `inferir_proposito`, `tipo_conserva_pp`, `stop_proteccion`, `descubiertas`,
    `cantidad_cancelada` y `primer_disparo` (el primer stop que de verdad
    salta, D2a-01): las piezas que usan el vigilante, la reconciliación y el
    decisor alrededor de los stops.

POR QUÉ ESTÁ AQUÍ. Es lógica PURA: sin reloj, sin I/O, sin red, sin logging.
Recibe la posición, las órdenes vivas, la configuración y la hora ET como
parámetros y devuelve acciones (`tipos.Accion`) que el ejecutor ejecuta EN
ORDEN. Así se prueba con tablas de casos sin DAS (documento §10) y el decisor
(lote G) y el vigilante (lote E, que importa `inferir_proposito`) comparten
EXACTAMENTE la misma aritmética.

LAS TRAMPAS.
  * `pos.neta` es la neta de FILLS (verdad inmediata, corrección 2 del juez).
    Si `neta_das` (lo último que dijo %POS) es conocida y NO coincide (riesgo
    8: el %POS suele llegar después del fill), `plan` pide `GET POSITIONS` y
    no CREA ni SUBE nada: una emergencia con más acciones que el corto real
    deja la cuenta LARGA (R-C-11 b). Pero BAJAR nunca deja la cuenta larga y
    R-C-11 (1) pide hacerlo con cada fill (D2a-05): con las dos netas cortas
    calcula lo deseado con n = min(−neta_fills, −neta_das) y emite SOLO los
    `Reemplazar` que bajan cantidad y los `Cancelar` de lo que sobra teniendo
    la emergencia casada (así nunca se quita la única cobertura). Con signos
    opuestos o una a cero, solo consulta. Como el %POS que cuadra llega antes
    que el `Replaced`/`Canceled`, el `plan` siguiente repetiría lo que acaba
    de pedir el del fill: el decisor le pasa `pedidos_en_vuelo` (REPLACE y
    CANCEL sin confirmar) y así no se repite nada.
  * Versión del objetivo (injerto A §8.6, riesgo 7): todo `EnviarOrden` y
    `Reemplazar` de stops lleva `serie="stops:X"` y `version`;
    `limpieza_tras_fill_stop` empieza SIEMPRE por `InvalidarSerie` para que un
    REPLACE viejo encolado nunca salga después del fill.
  * Una orden sin `id_das` puede NO haber salido nunca (D2a-06): si un
    `InvalidarSerie` posterior sube la versión mientras su NEWORDER espera en
    la cola, el emisor la purga y devuelve `OrdenDescartada(token)`; el decisor
    la pasa a CLOSED y replanifica en el acto. Hasta entonces `plan` la cuenta
    viva (Sending: no la duplica) y, si hay que tocarla, reprograma
    `stops_plan`; en cuanto deja de estar viva, el siguiente `plan` la repone.
  * El casado deseado↔viva es por PROPÓSITO y por DISPARO (±1 tick), no solo
    por `nivel`: con R-F-02 el disparo deseado ya no es L, y casar por
    `nivel` dejaría para siempre un stop por encima de una banda nueva (R-F-02
    «cada vez que la banda cambia»). Entre las candidatas, primero cada
    deseado reclama la puesta para SU nivel (dos niveles distintos pueden
    compartir disparo al redondear al tick, 10,201 y 10,209 → 10,21, y sin eso
    un segundo `plan` intercambiaría cantidades) y después el resto va por
    disparo y antigüedad. Una viva sin disparo ni nivel se IGNORA (ni cuenta
    ni se cancela).
  * Lo que no se entiende NO se cancela: si hay corto y no sale ningún stop
    deseado (lotes sin nivel válido, o ningún lote vivo), `plan` no toca las
    órdenes vivas; con lotes sin nivel avisa nivel 3 (los stops no se pueden
    calcular). Una posición sin lotes es de la reconciliación (R-C-10 caso 4).
    Un stop de compra NUESTRO que se infiere como protección teniendo lotes
    vivos (riesgo 1: el %ORDER no trae el disparo y `precio` es el límite)
    tampoco se toca, pero si `plan` pone su par al lado avisa nivel 2 y lo
    anota (`stop_no_reconocido`, D2a-10): no queda en silencio la posible
    doble cobertura.
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
    del escalón principal nunca pase de la posición (R-C-07) y lo cancela si
    su disparo alcanza el de la emergencia (D2a-01).
  * La cantidad VIVA de una orden es min(`lvqty`, `qty − llenas`) cuando DAS
    ya ha dicho `lvqty` (Partial/Triggered) y `qty − llenas` si no: nunca «lo
    pedido» (injerto A §8.7). El mínimo (D2a-07) vale en los dos órdenes de
    llegada: el `Execute` sube `llenas` sin tocar un `lvqty` que el %ORDER aún
    no ha actualizado. `cantidad_cancelada` lee `cxlqty` / `Canceled qty`,
    jamás `qty`.
  * El `share` de un REPLACE (A-02 / D2a-08): el manual no dice si es la
    cantidad ABIERTA nueva o la TOTAL. Todo `Reemplazar` de este módulo lo
    calcula `tipos.share_de_replace` con el interruptor
    `cfg.stops.replace_share_es_abierta` (defecto
    `tipos.REPLACE_SHARE_ES_ABIERTA`, ABIERTA); `qty_objetivo` de
    `replace_verificar` es siempre la cantidad ABIERTA buscada. Mientras la
    config no fije el interruptor (semántica sin confirmar por el canario de
    comprobar_das), un REPLACE sobre una orden con llenas lleva `Avisar(2)`.
  * «La más nueva» es la de `id_das` mayor (lo asigna el servidor y vale entre
    procesos); sin `id_das` (aún Sending) es más nueva que cualquiera con id,
    y entre ellas decide `enviada_en`. `enviada_en` es el reloj monotónico del
    proceso que envió: el de una orden adoptada del vigilante no es comparable.
  * Con R-F-02 cada disparo se recorta por separado bajo la banda: con L ≥
    banda el principal y la emergencia salen con el MISMO disparo y límite, y
    con L a menos de un 1,5 % de la banda la emergencia recortada queda POR
    DEBAJO del principal. D2a-01: todo principal cuyo disparo (recortado o
    no) sea ≥ el de la emergencia se QUITA del conjunto deseado; la
    emergencia, con toda la posición, ya lo cubre, y dos stops sobre las
    mismas acciones al mismo precio compran dos veces (medido 15-sep: 55-65 %
    con disparos pegados). Los disparos comprimidos pero no invertidos
    (principal justo por debajo de la emergencia) se mantienen: el umbral es
    pregunta para Jaume.
  * `inferir_proposito` mira primero los disparos VIGENTES (lo que
    `conjunto_deseado` pondría hoy con esta banda: principales no quitados y
    la emergencia del L más alto) y solo después los de antes de la banda o de
    otros niveles; dentro de cada grupo gana el más cercano y, a igualdad,
    PRINCIPAL. Sin ese orden, con la banda la emergencia del vigilante
    recortada (que coincide con un principal quitado) se leería como
    principal: el ejecutor la cancelaría, pondría otra y el vigilante la
    vería descubierta (bucle).
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
    `compras_cierre` (D2a-09 / G1A-01) deja al decisor decir cuántas acciones
    cierra ya una compra en la que confía (la MKT por OPEN del halt): los
    stops se dimensionan para el resto y no se compra dos veces al reabrir.
  * Venta del exceso (R-C-11 b-3; D2a-03, D2a-04, R2-STOPS-1/2): «en vuelo»
    son SOLO las VENTA_EXCESO vivas del ticker; se vende
    max(neta − en_vuelo, 0). NINGUNA otra venta cubre la larga: el bot solo
    va corto, así que una ENTRADA_AGREGAR / ENTRADA_CRUCE viva es una venta
    CORTA que, si llena, deja la cuenta corta sin stops (los lotes ya están
    cerrados); con la cuenta larga se CANCELA, igual que toda venta no stop
    que no sea VENTA_EXCESO (la del vigilante sin etiqueta, una a mano: si
    llenara junto a la nuestra, venderíamos de más). Sin VENTA_EXCESO viva →
    CANCEL ALLSYMB (se lo lleva todo) + venta; con una viva NO (se la
    llevaría): `Cancelar` una a una de las compras y de esas ventas con id.
    Una venta así SIN id no se puede cancelar aún: `Anotar("cancelar_al_tener_id",
    {token, …})` para que el decisor la cancele al llegar su Accept (las
    compras sin id las cancela el barrido: son huérfanas con la cuenta
    larga). Precio vendible: bid·(1 − 1 %) redondeado abajo. Con la cuenta
    larga se programa SIEMPRE `exceso_verificar:X` a 1 s (aunque lo que ya se
    vende cubra la larga: puede no llenar). 1 % y 3 persecuciones son
    PROVISIONALES (pregunta a Jaume).
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
    REPLACE_SHARE_ES_ABIERTA,
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
    share_de_replace,
    tick_de,
)

# ── claves y plazos de los temporizadores que este módulo programa (§5 F2) ──
CLAVE_REPLANIFICAR = "stops_plan"               # F2.1: volver a planificar cuando falta información (GET POSITIONS, id_das)
REPLANIFICAR_EN_S = 0.5
CLAVE_VERIFICAR_REPLACE = "replace_verificar"   # F2.2 / 2h.8: comprobar el tipo (y la cantidad) tras un REPLACE
VERIFICAR_REPLACE_EN_S = 1.0
CLAVE_EXCESO_VERIFICAR = "exceso_verificar"     # D2a-04: la venta del exceso se comprueba a 1 s («exceso_verificar:X»)
EXCESO_VERIFICAR_EN_S = 1.0
COMANDO_POSICIONES = "GET POSITIONS"

# ── venta del exceso (R-C-11 b-3; D2a-04, PROVISIONAL: pregunta 1 a Jaume) ──
VENTA_EXCESO_MARGEN_PCT = Decimal("1")          # se vende a bid·(1 − 1 %) redondeado abajo: vendible, no el bid exacto
VENTA_EXCESO_PERSECUCIONES = 3                  # REPLACE al bid nuevo hasta 3 veces; después Avisar(3) «VENDER A MANO»

# ── REPLACE (A-02 / D2a-08): interruptor de cfg.stops que decide qué es el `share` ──
CLAVE_SHARE_ES_ABIERTA = "replace_share_es_abierta"

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


def clave_exceso_verificar(ticker: str) -> str:
    """D2a-04: clave CON dueño del temporizador de la venta del exceso («exceso_verificar:X», una por ticker).

    Lleva el ticker desde aquí para que dos tickers largos a la vez no se
    pisen el temporizador (§6.1: una clave repetida SUSTITUYE a la anterior).
    """
    return f"{CLAVE_EXCESO_VERIFICAR}:{ticker}"


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
    recorta por separado: aquí salen los PRECIOS; qué órdenes se ponen con
    ellos lo decide `conjunto_deseado` (D2a-01, ver trampas). Una banda que no
    es un precio es «sin banda». Porcentajes ausentes → constantes de `tipos`
    (riesgo 32). Lanza ValueError si L no es un precio > 0, si un porcentaje
    es negativo o si el margen deja el disparo en ≤ 0; TypeError si
    `cfg_stops` no es un dict.
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


# ── conjunto deseado (R-C-01 v3 decisión (a), R-C-06, R-C-07, R-B-03, D2a-01) ──
def conjunto_deseado(pos: PosicionTicker, cfg_stops: Mapping, limit_up: Optional[Decimal]) -> list[StopDeseado]:
    """R-C-01 v3 (a): UN principal por nivel L distinto y UNA emergencia con toda la posición sobre el L más alto.

    Sobre `pos.neta` (fills): n = −neta; n ≤ 0 → []. Cada principal lleva la
    suma de `llenas` de los lotes vivos de ese nivel con
    `principal_consumido=False` (R-C-11 c; R-C-06: dos estrategias al mismo
    nivel comparten orden), capada ACUMULATIVAMENTE a n en orden ascendente de
    nivel: el nivel más bajo, que dispara antes, conserva su cantidad entera y
    la suma de principales nunca supera la posición (área E, R-C-07). La
    emergencia lleva n entera sobre el nivel más alto de TODOS los lotes vivos
    (también los de principal consumido: la posición sigue ahí). D2a-01: un
    principal cuyo disparo (recortado bajo la banda o no, R-F-02) es ≥ el de
    la emergencia NO se pone: la emergencia ya cubre esas acciones y dos stops
    al mismo precio comprarían dos veces (R-C-11 b). No cuentan los lotes
    cerrados/cancelados, sin llenas, largos (R-E-01) ni los que no tienen un
    nivel válido (A12: `Decimal` finito > 0); sin ningún lote válido → [].
    Orden: principales ascendentes y la emergencia al final. No muta nada.
    """
    return _conjunto(pos, cfg_stops, limit_up, -pos.neta)


def primer_disparo(pos: PosicionTicker, cfg_stops: Mapping, limit_up: Optional[Decimal]) -> Optional[Decimal]:
    """D2a-01: disparo del primer stop que DE VERDAD salta (el menor del conjunto deseado); None sin corto o sin stops calculables.

    Con la banda el principal del L más bajo puede no existir (lo cubre una
    emergencia recortada más baja) y un principal consumido tampoco está: lo
    que halts (R-F-01 «stop por encima/debajo del precio») y el informe de
    cisne negro deben comparar con el precio es ESTE disparo, no el principal
    de `niveles(L más bajo)`. No muta nada.
    """
    return min((d.disparo for d in conjunto_deseado(pos, cfg_stops, limit_up)), default=None)


def _conjunto(pos: PosicionTicker, cfg_stops: Mapping, limit_up: Optional[Decimal], n: int) -> list[StopDeseado]:
    """`conjunto_deseado` para n acciones cortas (el `plan` de D2a-05 lo llama con min(−neta_fills, −neta_das))."""
    if n <= 0:
        return []
    lotes = _lotes_vivos(pos)
    if not lotes:
        return []
    nivel_max = lotes[-1].nivel_stop
    niv_max = niveles(nivel_max, cfg_stops, limit_up)   # type: ignore[arg-type]
    emergencia = StopDeseado(proposito=Proposito.STOP_EMERGENCIA, nivel=nivel_max, qty=n,   # type: ignore[arg-type]
                             disparo=niv_max.emergencia_disparo, limite=niv_max.emergencia_limite)
    por_nivel: dict[Decimal, int] = {}
    for lote in lotes:
        if not lote.principal_consumido:
            por_nivel[lote.nivel_stop] = por_nivel.get(lote.nivel_stop, 0) + lote.llenas   # type: ignore[index]
    deseados: list[StopDeseado] = []
    restante = n
    for nivel in sorted(por_nivel):
        if restante <= 0:
            break
        niv = niveles(nivel, cfg_stops, limit_up)
        if niv.principal_disparo >= emergencia.disparo:
            continue                                   # D2a-01: la emergencia (toda la posición) ya lo cubre
        qty = min(por_nivel[nivel], restante)
        deseados.append(StopDeseado(proposito=Proposito.STOP_PRINCIPAL, nivel=nivel, qty=qty,
                                    disparo=niv.principal_disparo, limite=niv.principal_limite))
        restante -= qty
    deseados.append(emergencia)
    return deseados


# ── propósito de una orden que no está en el diario del ejecutor (corrección 3) ──
def inferir_proposito(o: OrdenOMensaje, niveles_lotes: list[Decimal], cfg_stops: Mapping,
                      limit_up: Optional[Decimal] = None) -> Proposito:
    """Corrección 3 del juez: clasifica una STOPLMTP de COMPRA que puso el vigilante (o que no tiene diario).

    disparo ≈ principal de algún L (±1 tick) → STOP_PRINCIPAL; disparo ≈
    emergencia de algún L (L·1,13, ±1 tick) → STOP_EMERGENCIA; otra cosa →
    STOP_PROTECCION. Primero se miran los disparos VIGENTES (los que
    `conjunto_deseado` pondría hoy: principales no quitados por D2a-01 y la
    emergencia del L más alto, con la banda si la hay) y después el resto (sin
    recortar, de antes de una banda, y las emergencias de los demás L); dentro
    de cada grupo gana el disparo más cercano y, a igualdad, PRINCIPAL (dos
    niveles a 13 %: 11,30 es principal de 11,30 y emergencia de 10 →
    PRINCIPAL). Con `limit_up` (opcional, añadido sobre §3.16) casan TANTO los
    valores recortados bajo la banda (R-F-02) como los sin recortar: un stop
    puesto antes de la banda se reconoce, `plan` lo ve distinto del deseado y
    lo sustituye (si pasara por protección quedaría huérfano); y la emergencia
    recortada que coincide con un principal quitado es EMERGENCIA (D2a-01).
    Lo que no es un stop de compra → DESCONOCIDA (`plan` no lo cuenta). El
    disparo de un `MsgOrden` es el primer número del campo de tipo («SLP: 2.97
    2.99» → 2.97, captura del socio 24-sep; coma decimal admitida) o, sin
    números, `precio`; su tipo se reconoce por `TIPO_STOP_EN_ORDER` o por
    `cfg_stops["tipo_esperado_en_order"]` (PROVISIONAL, riesgo 1).
    """
    if not _es_stop_compra(o, cfg_stops):
        return Proposito.DESCONOCIDA
    disparo = _disparo_de(o)
    if disparo is None:
        return Proposito.STOP_PROTECCION
    niveles_ok = _niveles_validos(niveles_lotes)
    if not niveles_ok:
        return Proposito.STOP_PROTECCION
    for candidatos in (_disparos_vigentes(niveles_ok, cfg_stops, limit_up),
                       _disparos_de_variantes(niveles_ok, cfg_stops, limit_up)):
        casan = [(abs(disparo - precio), 0 if proposito is Proposito.STOP_PRINCIPAL else 1, proposito)
                 for (precio, proposito) in candidatos if _mismo_precio(disparo, precio)]
        if casan:
            return min(casan, key=lambda c: (c[0], c[1]))[2]
    return Proposito.STOP_PROTECCION


# ── plan idempotente (R-C-01 v3, R-C-04, R-C-06, R-C-07 neteo, R-C-11, corrección 2) ──
def plan(pos: PosicionTicker, vivas: list[Orden], cfg_stops: Mapping, limit_up: Optional[Decimal],
         tokens: Callable[[], int], hora_et: datetime, ruta_stop: str, version: int,
         compras_cierre: int = 0, pedidos_en_vuelo: Optional[Mapping[int, Optional[int]]] = None) -> list[Accion]:
    """R-C-01 v3 / R-C-04 / R-C-06 / R-C-07 (neteo con el vigilante) / R-C-11: lleva las órdenes vivas al conjunto deseado.

    IDEMPOTENTE y neutral al `Origen`: casa cada `StopDeseado` con las
    STOPLMTP de compra vivas del ticker (Sending/Accepted/Partial/Hold/
    Triggered) del mismo propósito y disparo ±1 tick (primero la puesta para
    su mismo `nivel`; después la de disparo más cercano y la más antigua),
    infiriendo el propósito de las del vigilante con `inferir_proposito`.
    Falta → `EnviarOrden(STOPLMTP B, serie="stops:X", version, propósito,
    nivel, lote de ese nivel)` (R-C-03/04 reponer); cantidad distinta →
    `Reemplazar(version, serie)` con el `share` de `tipos.share_de_replace`
    + `Programar("replace_verificar", 1 s, {token, ticker, qty_objetivo})`
    (R-C-06 subir, R-C-07 bajar; 2h.8; A-02/D2a-08: + `Avisar(2)` si la
    orden tiene llenas y la config no fija el interruptor); sobrante →
    `Cancelar` (con varias iguales se conserva la más antigua y se cancela la
    MÁS NUEVA, R-C-07 plan B). El «principal al ask» de
    `reasignar_principal_rebasado` se recorta con lo que dejan los principales
    (nunca sube) y se cancela si su disparo alcanza el de la emergencia
    (D2a-01). Orden de las acciones: nuevas, ajustes, cancelaciones (R-C-05:
    primero lo nuevo, luego lo viejo). Si pone órdenes nuevas junto a un stop
    nuestro que no casa con ningún nivel (inferido protección teniendo lotes,
    riesgo 1) → + `Avisar(2)` + `Anotar("stop_no_reconocido")` (D2a-10).
    Netas en desacuerdo (corrección 2, riesgo 8; D2a-05): `pos.neta_das`
    conocida y ≠ `pos.neta_fills` → con las dos cortas, lo deseado con
    n = min(−neta_fills, −neta_das) y SOLO `Reemplazar` que BAJAN y `Cancelar`
    de lo que sobra con la emergencia deseada casada con una viva (nunca
    `EnviarOrden` ni subidas: así nunca se queda larga ni pierde su única
    cobertura); con signos opuestos o una a cero, nada. En los dos casos
    termina con `Consultar("GET POSITIONS")` + `Programar("stops_plan",
    0,5 s)`. n ≤ 0 → cancela todos los stops gestionados (R-C-11 2). Corto sin
    ningún stop deseado → no toca nada (+ Avisar(3) si hay lotes sin nivel
    válido). Una orden sin `id_das` que habría que reemplazar o cancelar se
    deja y se reprograma `stops_plan` (D2a-06: puede no haber salido nunca;
    la cierra el decisor con `OrdenDescartada`). `compras_cierre` (opcional,
    D2a-09 / G1A-01): acciones que ya cierra una compra VIVA en la que el
    decisor confía (la MKT por OPEN o la HALT_BANDA de un halt, nunca un TP
    pasivo): los stops se dimensionan para lo que no cubre (a 0 se cancelan) y
    al quitarla vuelven solos a la posición entera. `pedidos_en_vuelo`
    (opcional, D2a-05): lo que el decisor YA pidió y DAS aún no confirmó,
    token → None (CANCEL en vuelo: la orden cuenta como ya cancelada, no se
    vuelve a cancelar) o → k (REPLACE en vuelo que deja k ABIERTAS: su
    cantidad viva es k). Sin él, el plan que llega con el %POS que cuadra
    repetiría el REPLACE y el CANCEL que el plan del fill acaba de mandar;
    solo peticiones vivas (fuera al llegar Canceled/Replaced/CancelRej/
    ReplaceRej, y un REPLACE de una versión ya invalidada no cuenta). Otros
    valores se ignoran. En cisne negro devuelve [] (R-G-03). `hora_et` se
    conserva por el contrato de §3.16 (la ruta ya llega resuelta). No muta
    nada.
    """
    ticker = pos.ticker
    if pos.estado is EstadoTicker.BS:
        return []
    en_vuelo = _pedidos_validos(pedidos_en_vuelo)
    vivas = [o for o in _unicas(vivas) if o.token not in en_vuelo or _viva_pedida(o, en_vuelo) > 0]
    consulta: list[Accion] = [Consultar(COMANDO_POSICIONES),
                              Programar(CLAVE_REPLANIFICAR, REPLANIFICAR_EN_S, {"ticker": ticker})]
    solo_bajar = pos.neta_das is not None and pos.neta_das != pos.neta_fills
    if solo_bajar:
        if not (pos.neta_das < 0 and pos.neta_fills < 0):   # type: ignore[operator]
            return consulta                               # signos opuestos o una a cero: solo consultar
        n = min(-pos.neta_fills, -pos.neta_das)           # type: ignore[operator]
    else:
        n = -pos.neta
    n_stops = n - _entero_positivo(compras_cierre) if n > 0 else n
    deseados = _conjunto(pos, cfg_stops, limit_up, n_stops)
    if n_stops > 0 and not deseados:
        return _aviso_sin_nivel(pos, n) + (consulta if solo_bajar else [])
    serie = serie_stops(ticker)
    pendientes = _stops_gestionados(pos, vivas, cfg_stops, limit_up)
    asignadas = _emparejar(deseados, pendientes)
    emergencia = next((d for d in deseados if d.proposito is Proposito.STOP_EMERGENCIA), None)
    emergencia_casada = any(d.proposito is Proposito.STOP_EMERGENCIA and i in asignadas for i, d in enumerate(deseados))
    quitar_ok = emergencia_casada or not solo_bajar       # D2a-05: sin la emergencia casada no se quita cobertura
    nuevas: list[Accion] = []
    ajustes: list[Accion] = []
    cancelaciones: list[Accion] = []
    replanificar = False
    for i, d in enumerate(deseados):
        o = asignadas.get(i)
        if o is None:
            if solo_bajar:
                continue                                  # D2a-05: con las netas en desacuerdo no se crea nada
            lote = _lote_de_nivel(pos, d.nivel, solo_sin_consumir=d.proposito is Proposito.STOP_PRINCIPAL)
            orden = _orden_stop(d, ticker, ruta_stop, tokens(), version, lote.id if lote is not None else None)
            nuevas.append(EnviarOrden(orden=orden, serie=serie))
            continue
        viva = _viva_pedida(o, en_vuelo)
        if viva == d.qty or (solo_bajar and d.qty > viva):
            continue                                      # D2a-05: nunca se sube con las netas en desacuerdo
        if o.id_das is None:
            replanificar = True
            continue
        ajustes.extend(_reemplazo(
            o, d.qty, o.stop if o.stop is not None else d.disparo, o.precio if o.precio is not None else d.limite,
            f"R-C-06/R-C-07: {d.proposito.value} de {ticker} a {d.qty} acciones (tenía {viva})", version, serie,
            cfg_stops))
    capacidad = max(n_stops, 0) - sum(d.qty for d in deseados if d.proposito is Proposito.STOP_PRINCIPAL)
    for o in _principales_al_ask(pos, vivas):
        viva = _viva_pedida(o, en_vuelo)
        disparo = _disparo_de(o)
        por_encima = emergencia is not None and disparo is not None and disparo >= emergencia.disparo
        objetivo = 0 if por_encima else min(viva, max(capacidad, 0))
        capacidad -= objetivo
        if objetivo == viva:
            continue
        if o.id_das is None:
            replanificar = True
            continue
        if objetivo > 0 and o.stop is not None and o.precio is not None:
            ajustes.extend(_reemplazo(o, objetivo, o.stop, o.precio,
                                      f"R-C-07: principal al ask de {ticker} a {objetivo} acciones (tenía {viva})",
                                      version, serie, cfg_stops))
        elif quitar_ok:
            motivo = (f"D2a-01: principal al ask de {ticker} con disparo {disparo} ≥ el de la emergencia"
                      if por_encima else f"R-C-07/R-C-11: principal al ask de {ticker} sin acciones que cubrir")
            cancelaciones.append(Cancelar(id_das=o.id_das, token=o.token, motivo=motivo))
    for o, p in pendientes:
        if not quitar_ok:
            continue                                      # D2a-05: la sobrante puede ser la única cobertura (banda nueva)
        if o.id_das is None:
            replanificar = True
            continue
        disparo = _disparo_de(o)
        if (p is Proposito.STOP_PRINCIPAL and emergencia is not None and disparo is not None
                and disparo >= emergencia.disparo):
            motivo = (f"D2a-01: principal de {ticker} con disparo {disparo} ≥ el de la emergencia {emergencia.disparo}: "
                      f"la emergencia (toda la posición) ya cubre esas acciones")
        else:
            motivo = f"R-C-07/R-C-11: {p.value} sobrante en {ticker} (se conserva la más antigua)"
        cancelaciones.append(Cancelar(id_das=o.id_das, token=o.token, motivo=motivo))
    acciones = nuevas + ajustes + cancelaciones
    if nuevas:
        acciones.extend(_avisar_no_reconocidas(pos, vivas, cfg_stops, limit_up))
    if solo_bajar:
        acciones.extend(consulta)
    elif replanificar:
        acciones.append(Programar(CLAVE_REPLANIFICAR, REPLANIFICAR_EN_S, {"ticker": ticker}))
    return acciones


# ── limpieza tras el fill de un stop (R-C-11, injerto A §8.6) ────────────
def limpieza_tras_fill_stop(pos: PosicionTicker, vivas: list[Orden], cot: Optional[Cotizacion], tokens: Callable[[], int],
                            cfg: Any, hora_et: datetime, version: int, orden_stop: Optional[Orden] = None,
                            limit_up: Optional[Decimal] = None, compras_cierre: int = 0,
                            pedidos_en_vuelo: Optional[Mapping[int, Optional[int]]] = None) -> list[Accion]:
    """R-C-11 (limpieza estricta, por EVENTO) tras el fill de un stop; empieza SIEMPRE por `InvalidarSerie` (injerto A §8.6).

    neta == 0 → `CancelarTicker` (R-C-11 a: todo fuera al instante, incluida
    una principal colgada). neta > 0 (LARGA) → vende SOLO el exceso (R-C-11 b:
    100 cortas, principal 20, emergencia 100 → larga 20 → se venden 20, JAMÁS
    100) descontando lo que ya se está vendiendo: SOLO las VENTA_EXCESO vivas
    (D2a-03, R2-STOPS-1; una ENTRADA_* es una venta CORTA, jamás cubre la
    larga). Sin ninguna VENTA_EXCESO viva, `CancelarTicker` antes (ninguna
    compra ni venta de entrada puede seguir viva; supone el emisor FIFO: el
    CANCEL ALLSYMB sale antes que la venta nueva); con una viva NO (se la
    llevaría): `Cancelar` una a una de las COMPRAS vivas con id y de toda
    venta no stop que no sea VENTA_EXCESO con id (entradas, la del vigilante
    sin etiqueta…). Una de esas ventas SIN id (aún Sending) se deja escrita
    con `Anotar("cancelar_al_tener_id", {token, ticker, proposito, qty,
    motivo, regla})` en las dos ramas: el decisor la cancela en cuanto llegue
    su Accept con id (su `_cancelar_al_aceptar`). Si lo que se vende pasa de
    la larga, se recortan las VENTA_EXCESO nuestras de la más nueva a la más
    vieja (nunca vender de más: dejaría un corto sin stops). La venta nueva:
    `EnviarOrden(S, LMT a bid·(1 − 1 %) redondeado abajo, ruta cruzar,
    VENTA_EXCESO)` (D2a-04: vendible, no el bid exacto; sin bid, el último
    precio) + `Avisar(2)` + `Anotar("incidente")`. Sin ningún precio, aviso
    nivel 3 (vender a mano) y sin orden. Con la cuenta larga termina SIEMPRE
    con `Programar("exceso_verificar:X", 1 s, {ticker, persecuciones: 0})`
    (R2-STOPS-2: también si lo que ya se vende cubre o pasa la larga, o sin
    precio: esas ventas pueden no llenar; ver `verificar_venta_exceso`). La
    clave del aviso lleva la versión (un incidente nuevo no se calla por el
    dedupe de 60 s de `avisos`). neta < 0 (sigue corta) →
    marca `principal_consumido` en los lotes cuyo principal ya quedó bajo el
    precio (20-sep: «se CANCELA el principal, su momento pasó»): si llenó un
    principal, los de su nivel y los inferiores (por `nivel` o por disparo,
    también el recortado bajo la banda); si llenó la emergencia o una
    protección, todos; si no se sabe cuál, por el precio (last, ask, bid) y,
    sin precio, todos. Cada lote que cambia se anota (`Anotar("lote")`
    parcial, H-2: tras un reinicio no se repone su principal) y después
    `plan()` cancela esos principales y ajusta la emergencia a −neta (si DAS
    la cancela, `plan` la repone; con el %POS atrasado solo BAJA, D2a-05).
    `orden_stop`, `limit_up`, `compras_cierre` y `pedidos_en_vuelo` (estos
    dos se pasan tal cual a `plan`; con la cuenta larga, una compra con el
    CANCEL ya en vuelo no se vuelve a cancelar) son opcionales sobre §3.16
    (el decisor sabe qué token llenó); sin `orden_stop` se deduce de las
    `vivas` con `llenas > 0`. `cfg` es la `Config` (o un dict con «stops» y
    «rutas»).
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
        return acciones + _limpieza_larga(pos, vivas, cot, tokens, cfg_stops, cfg_rutas, hora_et, version, 0,
                                          ya_cancelandose=_cancelaciones_en_vuelo(pedidos_en_vuelo))
    consumidos = _marcar_principal_consumido(pos, vivas, orden_stop, cot, cfg_stops, limit_up)
    acciones.extend(_anotar_lotes(ticker, consumidos, {"principal_consumido": True}, "R-C-11 (c)"))
    ruta_stop = ruta_de(cfg_rutas, "stop", _precio_referencia(cot), hora_et)
    acciones.extend(plan(pos, vivas, cfg_stops, limit_up, tokens, hora_et, ruta_stop, version,
                         compras_cierre=compras_cierre, pedidos_en_vuelo=pedidos_en_vuelo))
    return acciones


# ── la venta del exceso no llena (R-C-11 b-3, D2a-04) ───────────────────
def verificar_venta_exceso(pos: PosicionTicker, vivas: list[Orden], cot: Optional[Cotizacion], tokens: Callable[[], int],
                           cfg: Any, hora_et: datetime, version: int, persecuciones: int = 0,
                           pedidos_en_vuelo: Optional[Mapping[int, Optional[int]]] = None) -> list[Accion]:
    """D2a-04 / R-C-11 (3): lo que hace el temporizador `exceso_verificar:X` 1 s después de vender el exceso.

    Neta ≤ 0 → [] (el exceso ya se vendió; si cruzó a corto lo protege el
    decisor con `plan`). Con la cuenta aún LARGA tras
    `VENTA_EXCESO_PERSECUCIONES` (3) vueltas → `Avisar(3)` «VENDER A MANO: la
    cuenta está LARGA» + `Anotar("incidente")` y nada más: la venta del bot,
    si sigue viva, NO se cancela (el barrido de R-C-11 pondría otra) y el
    aviso lo dice para que el humano la cancele antes de vender a mano y no
    se venda dos veces. Antes de eso: sin ninguna VENTA_EXCESO viva nuestra
    → se repite la limpieza de la cuenta larga (R2-STOPS-2: CANCEL ALLSYMB,
    que se lleva también una entrada o una venta ajena viva, + venta de la
    neta) y la vuelta cuenta; con VENTA_EXCESO vivas → se cancelan las
    demás ventas no stop vivas con id (una ENTRADA_* no cubre la larga,
    R2-STOPS-1; sin id, `Anotar("cancelar_al_tener_id")`; las que ya tienen
    el CANCEL en vuelo según `pedidos_en_vuelo` no se repiten), las
    VENTA_EXCESO se recortan si pasan de la larga y cada una con id que esté
    por encima del precio nuevo (bid·(1 − 1 %), el mismo margen) se
    REEMPLAZA a ese precio (`share` de `tipos.share_de_replace`); +
    `Anotar("venta_exceso_perseguida")` y el `Programar` de la vuelta
    siguiente (`persecuciones` + 1). Aquí NO se abre otra venta por la
    diferencia con VENTA_EXCESO vivas: la vende la limpieza del fill que la
    creó (o el barrido), y si esa limpieza no tenía precio ya pidió «vender
    a mano»: venderla aquí podría vender dos veces. Sin cotización, esa
    vuelta no persigue pero cuenta. `persecuciones` = vueltas ya hechas (0
    la primera; llega en los datos del temporizador). PURA: no muta nada.
    """
    ticker = pos.ticker
    neta = pos.neta
    if neta <= 0:
        return []
    cfg_stops = _bloque(cfg, "stops")
    cfg_rutas = _bloque(cfg, "rutas")
    hechas = persecuciones if type(persecuciones) is int and persecuciones > 0 else 0
    ya_cancelandose = _cancelaciones_en_vuelo(pedidos_en_vuelo)
    ventas = _ventas_exceso_vivas(ticker, vivas)
    en_vuelo = sum(_qty_viva(o) for o in ventas)
    if hechas >= VENTA_EXCESO_PERSECUCIONES:
        return _aviso_vender_a_mano(pos, ventas, en_vuelo, hechas)
    if not ventas:
        return _limpieza_larga(pos, vivas, cot, tokens, cfg_stops, cfg_rutas, hora_et, version, hechas + 1,
                               ya_cancelandose)
    siguiente = Programar(clave_exceso_verificar(ticker), EXCESO_VERIFICAR_EN_S,
                          {"ticker": ticker, "persecuciones": hechas + 1})
    referencia, precio = _precio_venta_exceso(cot)
    acciones = _cancelar_ventas_ajenas(ticker, vivas, neta, True, ya_cancelandose)
    acciones += _ajustar_ventas(ticker, ventas, neta, precio, version, cfg_stops,
                                f"D2a-04: la venta del exceso de {ticker} no llenó: se persigue al bid (vuelta {hechas + 1})")
    acciones.append(Anotar("venta_exceso_perseguida", {
        "ticker": ticker, "neta": neta, "en_vuelo": en_vuelo, "persecucion": hechas + 1,
        "referencia": None if referencia is None else str(referencia), "precio": None if precio is None else str(precio),
        "tokens": [o.token for o in ventas], "regla": "R-C-11 (3) D2a-04"}))
    acciones.append(siguiente)
    return acciones


# ── principal rebasado (R-C-01 v3, mitigación FIJADA 22-sep, decisión (a)) ──
def reasignar_principal_rebasado(pos: PosicionTicker, vivas: list[Orden], cot: Optional[Cotizacion], cfg_stops: Mapping,
                                 tokens: Callable[[], int], hora_et: datetime, ruta_stop: str, version: int,
                                 limit_up: Optional[Decimal] = None) -> list[Accion]:
    """R-C-01 decisión (a): el PRECIO pasa de largo el LÍMITE de un principal sin llenarlo.

    Rebasado = principal vivo sin fills con el ÚLTIMO precio Y el ask por
    encima de su límite (D2a-02: el STOPLMTP dispara por print; con el ask
    solo, un spread ancho de premercado o un `$Quote` absurdo empeorarían el
    stop para siempre sin que el precio haya llegado) y cuyo nivel aún tiene
    lotes sin consumir (así es IDEMPOTENTE: un `$Quote` repetido antes del
    `Canceled` no hace nada). Se cancela y sus acciones se SUMAN al principal
    del siguiente nivel por encima que no esté también pasado (límite ≥ ask):
    los lotes rebasados pasan a ese `nivel_stop` y la cantidad sale de
    `conjunto_deseado` (`Reemplazar` + `Programar("replace_verificar")`). Si
    no hay nivel por encima, las acciones se recolocan en un principal nuevo
    al ask (disparo ask, límite ask·(1 + 3 %), recortado bajo la banda si
    toca, R-F-02) con propósito STOP_PROTECCION y `lote_id` (así `plan` lo
    recorta pero no lo confunde con el principal viejo) y los lotes quedan con
    `principal_consumido=True`; si ese disparo ya alcanza el de la emergencia,
    NO se pone (compraría dos veces con ella: R-C-11, la regla de D2a-01) y
    solo se anota. La emergencia NO se toca («siempre una sola emergencia con
    toda la posición», sobre el L de la estrategia). Orden: `Anotar("lote")`
    parcial de cada lote cambiado (write-ahead, H-2), `Cancelar` los
    rebasados (la emergencia sigue cubriendo), el reemplazo o la orden nueva
    y `Anotar("stop_reasignado")`. Sin ask o sin último válidos, sin corto, en
    cisne negro (R-G-01: no perseguir), en halt (manda R-F-01), con
    `neta_das` ≠ `neta_fills` (corrección 2; `plan` ya pide GET POSITIONS) o
    sin nada rebasado con `id_das` → []. `limit_up` es opcional sobre §3.16;
    `hora_et` se conserva por el contrato.
    """
    ticker = pos.ticker
    ask = _precio_valido(getattr(cot, "ask", None))
    ultimo = _precio_valido(getattr(cot, "last", None))
    n = -pos.neta
    if ask is None or ultimo is None or n <= 0 or pos.estado in (EstadoTicker.BS, EstadoTicker.HALT):
        return []
    if pos.neta_das is not None and pos.neta_das != pos.neta_fills:
        return []
    sin_consumir = sorted({lote.nivel_stop for lote in _lotes_vivos(pos) if not lote.principal_consumido})   # type: ignore[type-var]
    if not sin_consumir:
        return []
    principales = [(o, _nivel_de_principal(o, sin_consumir, cfg_stops, limit_up))   # type: ignore[arg-type]
                   for (o, p) in _stops_gestionados(pos, vivas, cfg_stops, limit_up) if p is Proposito.STOP_PRINCIPAL]
    rebasados = [(o, L) for (o, L) in principales
                 if L is not None and o.llenas == 0 and _precio_valido(o.precio) is not None
                 and ask > o.precio and ultimo > o.precio]   # type: ignore[operator]
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
                 motivo=(f"R-C-01 (a): el precio (último {ultimo}, ask {ask}) rebasó el límite {o.precio} del principal "
                         f"de {ticker} sin fill"))
        for (o, _) in cancelables]
    serie = serie_stops(ticker)
    datos: dict[str, Any] = {"ticker": ticker, "ask": str(ask), "last": str(ultimo), "acciones": total,
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
                    version, serie, cfg_stops))
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
                 limit_up: Optional[Decimal] = None, compras_cierre: int = 0) -> int:
    """R-C-03: acciones netas cortas sin una emergencia (o protección) CONFIRMADA que las cubra.

    Cubren las STOPLMTP de compra del ticker en estado Accepted/Partial/Hold/
    Triggered (una Sending no es «stop aceptado») con propósito
    STOP_EMERGENCIA o STOP_PROTECCION (la protección es la «emergencia» de
    una posición sin lotes, R-C-10 caso 4), por su cantidad VIVA (D2a-07).
    Un principal no cubre: la emergencia es la que lleva la posición entera.
    Una orden sin etiqueta (DESCONOCIDA, p. ej. del vigilante sin diario) se
    clasifica con `inferir_proposito` sobre los niveles de los lotes
    (`cfg_stops` y `limit_up` opcionales sobre §3.16; sin ellos, constantes
    de `tipos`). `compras_cierre` (opcional, D2a-09): las acciones que ya
    cierra la compra de un halt en la que el decisor confía cuentan como
    cubiertas (con los stops reducidos por ella no se dispara R-C-03). > 0
    dispara R-C-03 (reintentos) y el plan B del vigilante
    (PLAN_B_DESCUBIERTA_S). Posición plana o larga → 0.
    """
    n = -pos.neta
    if n <= 0:
        return 0
    cfg = cfg_stops if cfg_stops is not None else {}
    niveles_lotes = _niveles_de_lotes(pos)
    cubiertas = _entero_positivo(compras_cierre)
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


def _entero_positivo(x: Any) -> int:
    """`x` si es un int > 0 de verdad (no bool, no float); cualquier otra cosa → 0."""
    return x if type(x) is int and x > 0 else 0


def _pedidos_validos(pedidos: Any) -> dict[int, Optional[int]]:
    """D2a-05: las peticiones en vuelo que se entienden (token int → None = CANCEL, o int ≥ 0 = REPLACE a esas ABIERTAS)."""
    if not isinstance(pedidos, Mapping):
        return {}
    validos: dict[int, Optional[int]] = {}
    for token, valor in pedidos.items():
        if type(token) is not int:
            continue
        if valor is None or (type(valor) is int and valor >= 0):
            validos[token] = valor
    return validos


def _viva_pedida(o: Orden, en_vuelo: Mapping[int, Optional[int]]) -> int:
    """Cantidad viva contando lo pedido en vuelo: CANCEL → 0; REPLACE → lo que deja abierto; sin petición → `_qty_viva`."""
    if o.token in en_vuelo:
        pedida = en_vuelo[o.token]
        return 0 if pedida is None else pedida
    return _qty_viva(o)


def _cancelaciones_en_vuelo(pedidos: Any) -> frozenset[int]:
    """Tokens con un CANCEL ya pedido y sin confirmar (para no repetirlo)."""
    return frozenset(token for token, valor in _pedidos_validos(pedidos).items() if valor is None)


def _share_es_abierta(cfg_stops: Any) -> bool:
    """A-02: `cfg.stops.replace_share_es_abierta` si es un bool; si falta (o no es bool), el defecto de tipos."""
    valor = cfg_stops.get(CLAVE_SHARE_ES_ABIERTA) if isinstance(cfg_stops, Mapping) else None
    return valor if isinstance(valor, bool) else REPLACE_SHARE_ES_ABIERTA


def _share_confirmado(cfg_stops: Any) -> bool:
    """D2a-08: la config FIJA el interruptor (el canario de comprobar_das ya dijo qué es el `share`)."""
    return isinstance(cfg_stops, Mapping) and isinstance(cfg_stops.get(CLAVE_SHARE_ES_ABIERTA), bool)


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


def _disparos_vigentes(niveles_ok: list[Decimal], cfg_stops: Mapping,
                       limit_up: Optional[Decimal]) -> list[tuple[Decimal, Proposito]]:
    """Los disparos que `conjunto_deseado` pondría hoy: la emergencia del L más alto y los principales que no quita D2a-01."""
    emergencia = niveles(max(niveles_ok), cfg_stops, limit_up).emergencia_disparo
    candidatos: list[tuple[Decimal, Proposito]] = [(emergencia, Proposito.STOP_EMERGENCIA)]
    for L in niveles_ok:
        principal = niveles(L, cfg_stops, limit_up).principal_disparo
        if principal < emergencia:
            candidatos.append((principal, Proposito.STOP_PRINCIPAL))
    return candidatos


def _disparos_de_variantes(niveles_ok: list[Decimal], cfg_stops: Mapping,
                           limit_up: Optional[Decimal]) -> list[tuple[Decimal, Proposito]]:
    """Todos los disparos reconocibles (sin banda y recortados; principal y emergencia de cada L)."""
    candidatos: list[tuple[Decimal, Proposito]] = []
    for v in _variantes(niveles_ok, cfg_stops, limit_up):
        candidatos.append((v.principal_disparo, Proposito.STOP_PRINCIPAL))
        candidatos.append((v.emergencia_disparo, Proposito.STOP_EMERGENCIA))
    return candidatos


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
    reclama las candidatas de SU MISMO nivel (identidad: dos niveles distintos pueden compartir disparo al
    redondear al tick); después, los que siguen sin orden toman del resto por disparo más cercano y antigüedad.
    Candidata = mismo propósito y disparo a ±1 tick (`_casa`).
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
    """Acciones que la orden aún puede ejecutar: min(`lvqty`, `qty − llenas`) si DAS dio `lvqty` (Partial/Triggered); si no, `qty − llenas`.

    D2a-07: el `Execute` sube `llenas` y deja un `lvqty` viejo hasta el
    siguiente %ORDER (una emergencia de 100 con 30 llenas seguiría contando
    100); el %ORDER puede llegar también ANTES que el `Execute`. El mínimo vale
    en los dos órdenes de llegada; nunca «lo pedido» (injerto A §8.7).
    """
    restante = max(int(o.qty) - int(o.llenas), 0)
    if o.estado in (EstadoOrden.PARTIAL, EstadoOrden.TRIGGERED) and o.lvqty > 0:
        return max(min(int(o.lvqty), restante), 0)
    return restante


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


def _se_infiere(o: Orden) -> bool:
    """Su propósito NO sale de una etiqueta de confianza (principal/emergencia propias o protección propia): se infiere."""
    if o.proposito in PROPOSITOS_GESTIONADOS:
        return False
    return not (o.proposito is Proposito.STOP_PROTECCION and o.origen is not Origen.VIGILANTE)


def _proposito_efectivo(o: Orden, niveles_lotes: list[Decimal], cfg_stops: Mapping,
                        limit_up: Optional[Decimal]) -> Proposito:
    """Etiqueta propia si ya es principal/emergencia; protección propia intocable; lo demás (vigilante, desconocida) se infiere."""
    if not _se_infiere(o):
        return o.proposito
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


def _avisar_no_reconocidas(pos: PosicionTicker, vivas: list[Orden], cfg_stops: Mapping,
                           limit_up: Optional[Decimal]) -> list[Accion]:
    """D2a-10 / riesgo 1: stops de compra NUESTROS vivos que se infieren protección teniendo lotes → Avisar(2) + Anotar.

    Solo lo llama `plan` cuando pone órdenes nuevas (es cuando la posible
    doble cobertura aparece); así el `plan` siguiente, con el par ya puesto,
    sigue sin producir nada. Esas órdenes NO se tocan (lo que no se entiende
    no se cancela).
    """
    niveles_lotes = _niveles_de_lotes(pos)
    if not niveles_lotes:
        return []
    raras = [o for o in _unicas(vivas) if _es_viva(o, pos.ticker) and _se_infiere(o)
             and inferir_proposito(o, niveles_lotes, cfg_stops, limit_up) is Proposito.STOP_PROTECCION]
    if not raras:
        return []
    detalle = ", ".join(f"token {o.token} (disparo {_disparo_de(o)})" for o in raras)
    return [Avisar(nivel=Nivel.AVISO, grupo=Grupo.B, clave=f"stop_no_reconocido:{pos.ticker}",
                   texto=(f"Riesgo 1 (D2a-10): {pos.ticker} tiene stops de compra NUESTROS que no casan con ningún nivel "
                          f"de sus lotes: {detalle}. Se tratan como protección y NO se tocan; el bot pone su par "
                          f"principal + emergencia aparte (posible DOBLE cobertura). Revisar el tipo del %ORDER "
                          f"(comprobar_das, paso 3)")),
            Anotar("stop_no_reconocido", {"ticker": pos.ticker, "tokens": [o.token for o in raras],
                                          "disparos": [None if _disparo_de(o) is None else str(_disparo_de(o))
                                                       for o in raras],
                                          "regla": "riesgo 1 (D2a-10)"})]


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
               serie: str, cfg_stops: Mapping) -> list[Accion]:
    """`Reemplazar` (con versión y serie, injerto §8.6) + `Programar("replace_verificar")` con la cantidad ABIERTA buscada (2h.8).

    A-02 / D2a-08: el `share` del REPLACE sale de `tipos.share_de_replace`
    (abierta, o llenas + abierta según `cfg.stops.replace_share_es_abierta`);
    `qty_objetivo` es siempre la ABIERTA. Si la orden ya tiene llenas y la
    config aún no fija el interruptor, + `Avisar(2)` para mirar en DAS lo que
    queda abierto (la semántica no está confirmada).
    """
    abierta_es_share = _share_es_abierta(cfg_stops)
    llenas = max(int(o.llenas), 0)
    share = share_de_replace(qty, llenas, abierta_es_share)
    acciones: list[Accion] = [
        Reemplazar(id_das=o.id_das, token=o.token, qty=share, stop=stop, precio=precio, motivo=motivo,   # type: ignore[arg-type]
                   version=version, serie=serie),
        Programar(CLAVE_VERIFICAR_REPLACE, VERIFICAR_REPLACE_EN_S, {"token": o.token, "ticker": o.ticker, "qty_objetivo": qty})]
    if (llenas > 0 or o.estado is EstadoOrden.PARTIAL) and not _share_confirmado(cfg_stops):
        lectura = "cantidad ABIERTA" if abierta_es_share else "TOTAL (llenas + abiertas)"
        acciones.append(Avisar(nivel=Nivel.AVISO, grupo=Grupo.B, clave=f"replace_parcial:{o.token}",
                               texto=(f"A-02/D2a-08: REPLACE de {o.ticker} sobre la orden {o.token} con {llenas} llenas: "
                                      f"se manda share={share} como {lectura}; DAS aún no ha confirmado cómo lo lee "
                                      f"(paso canario de comprobar_das). Comprobar en DAS que quedan {qty} abiertas")))
    return acciones


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


def _precio_venta_exceso(cot: Optional[Cotizacion]) -> tuple[Optional[Decimal], Optional[Decimal]]:
    """(referencia, precio) de la venta del exceso: bid (sin bid, el último) y referencia·(1 − 1 %) redondeado ABAJO (D2a-04).

    El margen hace la orden vendible aunque el bid se mueva en el camino
    (lado permisivo de una venta). Si el margen dejara el precio en 0 (un
    penny de 1 tick), se vende a la referencia redondeada abajo. Sin ningún
    precio → (None, None).
    """
    for campo in ("bid", "last"):
        referencia = _precio_valido(getattr(cot, campo, None))
        if referencia is None:
            continue
        precio = con_techo(referencia, VENTA_EXCESO_MARGEN_PCT, arriba=False)
        if precio <= 0:
            precio = redondear_abajo(referencia)
        return referencia, (precio if precio > 0 else None)
    return None, None


def _es_venta_viva(o: Orden, ticker: str) -> bool:
    """Venta viva del ticker por CUALQUIERA de los dos lados vendedores de DAS: `S` (venta) y `SS` (venta corta).

    Las entradas del bot van con `SS` (`entrada.orden_agregar` / `orden_cruce`, manual L671-694): mirar solo `S`
    dejaría viva una entrada corta con la cuenta larga (27-sep, lectura del director; los tests construían las
    entradas con `S` y no lo veían).
    """
    return (o.ticker == ticker and o.lado in (Lado.VENTA, Lado.CORTO) and o.estado in ESTADOS_VIVOS
            and _qty_viva(o) > 0)


def _ventas_exceso_vivas(ticker: str, vivas: Iterable[Any]) -> list[Orden]:
    """D2a-03 / R2-STOPS-1: las VENTA_EXCESO vivas del ticker, de la más vieja a la más nueva: lo ÚNICO que está «en vuelo».

    Ninguna otra venta cubre la larga: una ENTRADA_AGREGAR / ENTRADA_CRUCE es
    una venta CORTA (si llena, la cuenta queda corta sin stops) y una venta
    sin etiqueta o a mano puede llenar a la vez que la nuestra; todas esas se
    cancelan (`_cancelar_ventas_ajenas`). Una VENTA STOPLMTP (protección de
    un largo, R-C-10 caso 4) tampoco: solo vende si el precio cae hasta su
    disparo.
    """
    salida = [o for o in _unicas(vivas)
              if _es_venta_viva(o, ticker) and o.proposito is Proposito.VENTA_EXCESO
              and o.tipo is not TipoOrden.STOP_LIMITE_PP]
    salida.sort(key=_clave_antiguedad)
    return salida


def _ventas_ajenas_vivas(ticker: str, vivas: Iterable[Any]) -> list[Orden]:
    """R2-STOPS-1: ventas NO stop vivas del ticker que NO son VENTA_EXCESO (ENTRADA_*, la del vigilante sin etiqueta, una a mano…)."""
    salida = [o for o in _unicas(vivas)
              if _es_venta_viva(o, ticker) and o.proposito is not Proposito.VENTA_EXCESO
              and o.tipo is not TipoOrden.STOP_LIMITE_PP]
    salida.sort(key=_clave_antiguedad)
    return salida


def _cancelar_ventas_ajenas(ticker: str, vivas: Iterable[Any], neta: int, con_id: bool,
                            ya_cancelandose: frozenset[int] = frozenset()) -> list[Accion]:
    """R2-STOPS-1 (R-C-11 a/b «cancelar todo lo que la reabra»): con la cuenta LARGA ninguna venta que no sea VENTA_EXCESO sigue viva.

    `con_id` → `Cancelar` de cada una con id (la rama con una VENTA_EXCESO
    viva, donde no se puede usar CANCEL ALLSYMB; sin `con_id` el CANCEL
    ALLSYMB que va delante ya se las lleva). Las que aún NO tienen id (Sending)
    → `Anotar("cancelar_al_tener_id", {token, ticker, proposito, qty, motivo,
    regla})`: el decisor la cancela en cuanto llegue su Accept con id (su
    `_cancelar_al_aceptar`); el barrido no lo haría (una venta con la cuenta
    larga no es huérfana). Las que ya tienen el CANCEL en vuelo
    (`ya_cancelandose`, D2a-05) no se repiten.
    """
    acciones: list[Accion] = []
    for o in _ventas_ajenas_vivas(ticker, vivas):
        if o.token in ya_cancelandose:
            continue
        proposito = str(getattr(o.proposito, "value", o.proposito))
        motivo = (f"R-C-11 (3): {ticker} quedó LARGA {neta}; la venta {proposito} no cubre la larga "
                  f"(una entrada es una venta CORTA): se cancela")
        if o.id_das is None:
            acciones.append(Anotar("cancelar_al_tener_id", {
                "token": o.token, "ticker": ticker, "proposito": proposito, "qty": _qty_viva(o),
                "motivo": motivo, "regla": "R-C-11 (3) R2-STOPS-1"}))
        elif con_id:
            acciones.append(Cancelar(id_das=o.id_das, token=o.token, motivo=motivo))
    return acciones


def _cancelar_compras(ticker: str, vivas: Iterable[Any], motivo: str,
                      ya_cancelandose: frozenset[int] = frozenset()) -> list[Accion]:
    """D2a-03: `Cancelar` de cada COMPRA viva del ticker con id (la alternativa a CANCEL ALLSYMB que respeta la venta).

    Las que ya tienen el CANCEL en vuelo (`ya_cancelandose`, D2a-05) no se vuelven a cancelar.
    """
    compras = [o for o in _unicas(vivas)
               if o.ticker == ticker and o.lado is Lado.COMPRA and o.estado in ESTADOS_VIVOS and _qty_viva(o) > 0
               and o.id_das is not None and o.token not in ya_cancelandose]
    compras.sort(key=_clave_antiguedad)
    return [Cancelar(id_das=o.id_das, token=o.token, motivo=motivo) for o in compras]   # type: ignore[arg-type]


def _ajustar_ventas(ticker: str, ventas: list[Orden], neta: int, precio_nuevo: Optional[Decimal], version: int,
                    cfg_stops: Mapping, motivo: str) -> list[Accion]:
    """Lleva las VENTA_EXCESO nuestras con id a lo que toca: nunca más que la larga (D2a-03) y, con `precio_nuevo`, a ese precio si baja (D2a-04).

    Si lo que se está vendiendo pasa de la larga se recorta primero la MÁS
    NUEVA (Cancelar si se queda en 0, Reemplazar de cantidad si no); lo que
    no se pueda recortar (VENTA_EXCESO aún sin id) → Avisar(3):
    si llenan, la cuenta queda CORTA sin stops. UNA acción por orden (la
    cantidad y el precio van en el mismo REPLACE).
    """
    en_vuelo = sum(_qty_viva(o) for o in ventas)
    sobra = max(en_vuelo - max(neta, 0), 0)
    mias = [o for o in ventas if o.proposito is Proposito.VENTA_EXCESO]
    objetivo = {id(o): _qty_viva(o) for o in mias}
    for o in sorted(mias, key=_clave_antiguedad, reverse=True):
        if sobra <= 0:
            break
        if o.id_das is None:
            continue
        quita = min(objetivo[id(o)], sobra)
        objetivo[id(o)] -= quita
        sobra -= quita
    abierta_es_share = _share_es_abierta(cfg_stops)
    acciones: list[Accion] = []
    for o in mias:
        if o.id_das is None:
            continue
        viva = _qty_viva(o)
        queda = objetivo[id(o)]
        if queda <= 0:
            acciones.append(Cancelar(id_das=o.id_das, token=o.token,
                                     motivo=f"R-C-11 (b): {ticker}: se vende más que la larga ({neta}); sobra esta venta"))
            continue
        precio = o.precio
        if precio_nuevo is not None and (precio is None or precio_nuevo < precio):
            precio = precio_nuevo
        if queda == viva and precio == o.precio:
            continue
        acciones.append(Reemplazar(id_das=o.id_das, token=o.token,
                                   qty=share_de_replace(queda, max(int(o.llenas), 0), abierta_es_share),
                                   stop=None, precio=precio, motivo=motivo, version=version, serie=None))
    if sobra > 0:
        acciones.append(Avisar(nivel=Nivel.MAXIMO, grupo=Grupo.B, clave=f"exceso_de_mas:{ticker}",
                               texto=(f"R-C-11 (b): {ticker} está LARGA {neta} y hay {sobra} acciones MÁS en ventas vivas "
                                      f"que el bot no puede recortar: si llenan, la cuenta queda CORTA sin stops. "
                                      f"Revisar a mano")))
    return acciones


def _vender_exceso(pos: PosicionTicker, qty: int, en_vuelo: int, cot: Optional[Cotizacion], tokens: Callable[[], int],
                   cfg_rutas: Mapping, hora_et: datetime, version: int) -> list[Accion]:
    """R-C-11 (b): `EnviarOrden(S qty LMT a bid·(1 − 1 %), ruta cruzar, VENTA_EXCESO)` + `Avisar(2)` + `Anotar("incidente")`.

    Sin ningún precio de DAS → `Avisar(3)` «VENDER A MANO» + `Anotar` y sin
    orden. El `exceso_verificar` lo añade siempre `_limpieza_larga`
    (R2-STOPS-2): si al vencer ya hay precio y la cuenta sigue larga sin
    VENTA_EXCESO viva, se vende detrás de un CANCEL ALLSYMB (que retira
    también una venta a mano aún viva: nunca dos ventas a la vez).
    """
    ticker = pos.ticker
    neta = pos.neta
    das = f" (DAS dice {pos.neta_das})" if pos.neta_das is not None and pos.neta_das != neta else ""
    vuelo = f"; {en_vuelo} ya se están vendiendo" if en_vuelo > 0 else ""
    referencia, precio = _precio_venta_exceso(cot)
    if precio is None:
        return [Avisar(nivel=Nivel.MAXIMO, grupo=Grupo.B, clave=f"exceso:{ticker}:{version}",
                       texto=(f"R-C-11: {ticker} quedó LARGA {neta} acciones tras el fill del stop{das}{vuelo} y no hay "
                              f"cotización de DAS para vender el exceso: VENDER A MANO {qty} acciones")),
                Anotar("incidente", {"tipo": "cuenta_larga_sin_cotizacion", "ticker": ticker, "neta": neta, "vender": qty,
                                     "en_vuelo": en_vuelo, "neta_das": pos.neta_das, "regla": "R-C-11 (b)",
                                     "version_stops": version})]
    ruta_cruzar = ruta_de(cfg_rutas, "cruzar", precio, hora_et)
    orden = OrdenNueva(token=tokens(), lado=Lado.VENTA, ticker=ticker, ruta=ruta_cruzar, qty=qty,
                       tipo=TipoOrden.LIMITE, precio=precio, tif="DAY+", post_only=False,
                       proposito=Proposito.VENTA_EXCESO, version=version)
    return [EnviarOrden(orden=orden),
            Avisar(nivel=Nivel.AVISO, grupo=Grupo.B, clave=f"exceso:{ticker}:{version}",
                   texto=(f"R-C-11: {ticker} quedó LARGA {neta} acciones tras el fill del stop{das}{vuelo}; se venden "
                          f"{qty} (solo el exceso) a {precio} ({referencia} − {VENTA_EXCESO_MARGEN_PCT} %) por {ruta_cruzar}")),
            Anotar("incidente", {"tipo": "cuenta_larga", "ticker": ticker, "neta": neta, "vendidas": qty,
                                 "en_vuelo": en_vuelo, "neta_das": pos.neta_das, "precio": str(precio),
                                 "referencia": str(referencia), "ruta": ruta_cruzar, "token": orden.token,
                                 "regla": "R-C-11 (b)", "version_stops": version})]


def _limpieza_larga(pos: PosicionTicker, vivas: list[Orden], cot: Optional[Cotizacion], tokens: Callable[[], int],
                    cfg_stops: Mapping, cfg_rutas: Mapping, hora_et: datetime, version: int,
                    persecuciones: int, ya_cancelandose: frozenset[int] = frozenset()) -> list[Accion]:
    """R-C-11 (b)-(3) con la cuenta LARGA (D2a-03, D2a-04, R2-STOPS-1/2): nada que la reabra sigue vivo, se vende SOLO lo que
    falte (en vuelo = VENTA_EXCESO vivas, nunca una entrada) y SIEMPRE se comprueba a 1 s."""
    ticker = pos.ticker
    neta = pos.neta
    ventas = _ventas_exceso_vivas(ticker, vivas)
    en_vuelo = sum(_qty_viva(o) for o in ventas)
    acciones: list[Accion] = []
    if ventas:
        acciones.extend(_cancelar_compras(ticker, vivas, (f"R-C-11 (3): {ticker} quedó LARGA {neta}; ninguna compra puede "
                                                          f"seguir viva (la venta del exceso en vuelo NO se cancela)"),
                                          ya_cancelandose))
        acciones.extend(_cancelar_ventas_ajenas(ticker, vivas, neta, True, ya_cancelandose))
    else:
        acciones.append(CancelarTicker(
            ticker=ticker, motivo=(f"R-C-11 (3): {ticker} quedó LARGA {neta}; ninguna compra ni venta de entrada pendiente "
                                   f"puede seguir viva")))
        acciones.extend(_cancelar_ventas_ajenas(ticker, vivas, neta, False, ya_cancelandose))
    verificar = Programar(clave_exceso_verificar(ticker), EXCESO_VERIFICAR_EN_S,
                          {"ticker": ticker, "persecuciones": persecuciones})
    a_vender = neta - en_vuelo
    if a_vender < 0:
        acciones.extend(_ajustar_ventas(ticker, ventas, neta, None, version, cfg_stops,
                                        f"R-C-11 (b): {ticker}: la venta del exceso se recorta a la larga ({neta})"))
        acciones.append(Anotar("incidente", {"tipo": "venta_exceso_de_mas", "ticker": ticker, "neta": neta,
                                             "en_vuelo": en_vuelo, "neta_das": pos.neta_das, "regla": "R-C-11 (b)",
                                             "version_stops": version}))
        acciones.append(verificar)
        return acciones
    if a_vender == 0:
        acciones.append(Anotar("incidente", {"tipo": "cuenta_larga", "ticker": ticker, "neta": neta, "vendidas": 0,
                                             "en_vuelo": en_vuelo, "neta_das": pos.neta_das, "regla": "R-C-11 (b)",
                                             "version_stops": version}))
        acciones.append(verificar)
        return acciones
    acciones.extend(_vender_exceso(pos, a_vender, en_vuelo, cot, tokens, cfg_rutas, hora_et, version))
    acciones.append(verificar)
    return acciones


def _aviso_vender_a_mano(pos: PosicionTicker, ventas: list[Orden], en_vuelo: int, hechas: int) -> list[Accion]:
    """D2a-04: tras las persecuciones la cuenta sigue LARGA → Avisar(3) «VENDER A MANO» + incidente (la venta viva NO se cancela)."""
    ticker = pos.ticker
    neta = pos.neta
    if ventas:
        tokens_txt = ", ".join(str(o.token) for o in ventas)
        vivas_txt = (f"La venta del bot de {en_vuelo} acciones (token {tokens_txt}) SIGUE VIVA: si vendes a mano, "
                     f"cancélala antes (/cancelar_ordenes {ticker} SI) para no vender dos veces.")
    else:
        vivas_txt = "El bot no tiene ninguna venta viva."
    return [Avisar(nivel=Nivel.MAXIMO, grupo=Grupo.B, clave=f"exceso_a_mano:{ticker}",
                   texto=(f"VENDER A MANO: la cuenta está LARGA. R-C-11 (3): {ticker} sigue LARGA {neta} acciones tras "
                          f"{hechas} persecuciones de la venta del exceso al bid. {vivas_txt}")),
            Anotar("incidente", {"tipo": "venta_exceso_sin_llenar", "ticker": ticker, "neta": neta, "en_vuelo": en_vuelo,
                                 "persecuciones": hechas, "tokens": [o.token for o in ventas],
                                 "neta_das": pos.neta_das, "regla": "R-C-11 (3) D2a-04"})]


def _precio_referencia(cot: Optional[Cotizacion]) -> Decimal:
    """Precio para resolver la ruta de stop (la tabla no depende de él, pero `precios.ruta` lo exige)."""
    precio = _precio_mercado(cot)
    return precio if precio is not None else Decimal("1")
