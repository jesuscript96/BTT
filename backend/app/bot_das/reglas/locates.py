"""Locates: paquetes de 100, EV con el coste TOTAL, máquina de compra, cerrojo, tope 3 % y reparto.

QUÉ HACE. Todas las reglas del área H del libro (R-H-01..R-H-05, H6, E9,
EP-9) como funciones PURAS:
  * `paquetes`: H6, paquetes de 100 por lo bajo; el último solo si se usa MÁS
    del 30 % (1.230 → 12 paquetes y la posición se ajusta a 1.200; 1.240 → 13).
  * `paquetes_marginal` (Jaume 29-sep, REGLA MARGINAL): con el precio del
    locate conocido, el último paquete se compra si lo que ganan las acciones
    extra paga el paquete entero: extra · precio · EV/100 ≥ 100 · precio del
    locate (en el límite, compra). Sin precio del locate (primera consulta,
    sin %SLRET) → el umbral del 30 % de `paquetes`. La usan `veredicto_ev` y
    la máquina (`_Contexto.objetivo`, E2-08); el primer paquete y el
    veredicto global siguen igual (EV contra el fade del coste TOTAL).
  * `cantidad_a_localizar`: R-H-05 escalonado, las acciones de UNA estrategia
    (entrada + sus pirámides «add», con el riesgo de cada nivel del cuadro) a
    partir de la fila del radar que lleva SU `strategy_id` (corrección 6).
  * `veredicto_ev`: R-H-01 + H6 + R-H-05, EV fijo por tramo de precio
    (`locates_gate.ev_fijo_para_precio`, la MISMA definición que la app) contra
    el fade que exige el coste TOTAL de los locates (lo ya pagado + lo nuevo).
  * FASES (Jaume 29-sep, `Locate.fase`): A radar sin señal (lo de siempre,
    cada 3 s) · B señal de entrada sin locates y C_piramide pirámide con
    locates que faltan: UN intento («a tiro» con el 3 % de R-B-01 y
    compensa) o «parado» el día · C dentro, buscando lo de las pirámides
    (cada 3 s, sin «a tiro»; lo que usan los lotes vivos cuenta como
    cubierto) · D posición cerrada, sin consultas. Las transiciones las
    anota el decisor (`locate_estado` con «fase»); aquí se aplican.
  * `siguiente_paso`: la máquina de un (ticker, estrategia): buscando →
    `LocateInquire` cada 3 s → con `%SLRET` tipo 1 y EV a favor y bajo el tope
    → `locate_intencion` + `LocateComprar` → comprando → `%SLOrder` Pending /
    Waiting / Offered / Located → hecho, o parcial y sigue buscando el resto
    (R-H-04; decisión 51, Jaume 1-oct: sin tope de tiempo, hasta que acabe la
    fase). Hora límite → parado; `AlreadyShortable` → no_hace_falta.
  * Decisión 50 (Jaume 1-oct), tope GLOBAL: la primera compra que no cabe en
    el tope con lo YA PAGADO devuelve `Anotar("locates_tope_global")`; el
    decisor corta entonces las compras de TODOS los tickers el resto del día
    (`corte_dia`) y cancela las que estén en vuelo.
  * `tope_superado` (R-H-03), `compra_repetida` (R-H-02), `asignar_a_lote`
    (E9), `caducados` (R-H-05), `tras_reentrada` (EP-9) y el reductor
    `aplicar_anotaciones` + `gasto_de` con los que el decisor lleva el estado.

POR QUÉ ESTÁ AQUÍ. El decisor es el único que muta `EstadoBot` (H-5, §6.1).
Esta máquina no toca nada: devuelve acciones (`tipos.Accion`) y describe cada
cambio de estado con un `Anotar("locate_inquire" | "locate_intencion" |
"locate_estado", datos)`, que el decisor aplica con `aplicar_anotaciones` y el
diario reproduce al arrancar (`diario.reconstruir`, H-2): una sola descripción
del estado, la misma en caliente y tras un reinicio (F13: no se recompra).
Solo importa `tipos`, `tokens`, `reglas.precios` y `locates_gate` (de este
último SOLO `ev_fijo_para_precio`: corrección 1). Nada de red, ni el módulo
`time`, ni la hora del sistema, ni logging, ni variables de entorno: el
monotónico (`ahora`) y la hora ET (`ahora_et`) llegan como parámetros.

LAS TRAMPAS.
  * `locates_gate.evaluar` NO sirve (corrección 1, riesgo 34): cobra
    `ceil(qty/100)` paquetes (1.230 → 13, H6 dice 12) y no admite el coste ya
    pagado. Aquí el fade usa `paquetes()` y `coste_ya_pagado + coste_nuevo`
    sobre las acciones que se van a USAR: la segunda compra de un parcial o de
    una reentrada sin reutilización se rechaza si el TOTAL ya no compensa.
  * Se compran PAQUETES enteros: `LocateComprar.qty` es `paquetes · 100`
    (1.240 → 1.300, «se compran las 100 y sobran 60»; H-7: los locates siempre
    ≥ 100), mientras `qty_ajustada` son las acciones que la posición usará.
  * Cerrojo R-H-02 (riesgo 11, bucle de locates): «Located» cubriendo lo
    pedido es terminal; con una compra en curso no se consulta ni se compra;
    solo se vuelve a comprar si faltan acciones (parcial R-H-04 o reentrada sin
    reutilización, EP-9) y siempre con el coste TOTAL y el tope del 3 %.
  * `%SLOrder` se casa con el locate por `token` (el de `Origen.EJECUTOR_
    LOCATE` que se generó al comprar) y, si DAS no lo devuelve, por `id`. Un
    mensaje con el `id` ya conocido y la compra ya cerrada es un duplicado (un
    `GET LOCATES` repite los Located): se ignora, o el gasto se contaría dos
    veces. Un Located de una compra NUESTRA que llega tarde (tras pasar a
    «parado» o «no_hace_falta») SÍ se contabiliza: el dinero ya se gastó.
  * `%SLRET` tipo 2 cubre también el fallo de `SLNEWORDER` (manual L1701-
    1720). Con una compra en curso NO se da por fallida (podría ser la
    respuesta tardía de otra ruta a la consulta): se anota y se avisa nivel 2;
    `AlreadyShortable` sí se acepta siempre (ETB: no hace falta locate).
  * `SLPRICEINQUIRE … ALLROUTE` crea órdenes `Offered` en las rutas tipo 1
    (§5.22): la ruta de consulta `ALLROUTE` se rechaza (ValueError).
  * Precios del locate por ACCIÓN (manual L1712); `SLRouteMinCharge`
    (`minimo_cargo`) sube el coste de una compra pequeña hasta el mínimo.
  * Los parámetros del cuadro llegan como números del JSON (3.0, 30): se
    convierten con `precios.de_float`; nada de float en la aritmética de dinero.
"""
from __future__ import annotations

import dataclasses
import html
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable, Mapping, Optional, Union
from zoneinfo import ZoneInfo

from app.bot_das.protocolo import cmd_get, cmd_sl_reuse
from app.bot_das.reglas.precios import de_float
from app.bot_das.tipos import (
    ENTRADA_TOPE_CAIDA_BID_PCT,
    LOCATES_INQUIRE_S,
    LOCATES_TOPE_GASTO_DIA_USD,
    LOCATES_UMBRAL_ULTIMO_PAQUETE_PCT,
    Accion,
    Anotar,
    Avisar,
    Consultar,
    Desprogramar,
    EstrategiaConfig,
    Grupo,
    Locate,
    LocateComprar,
    LocateInquire,
    LocateOferta,
    MsgSLOrder,
    MsgSLRet,
    MsgSLReuse,
    Nivel,
    Origen,
    Programar,
)
from app.bot_das.tokens import descomponer
from app.services.locates_gate import ev_fijo_para_precio

# ── constantes del módulo ─────────────────────────────────────────────
PAQUETE = 100                                   # H6: los locates van en paquetes de 100
RUTA_INQUIRE_DEFECTO = "ALLROUTEWTTYPE1"        # R-H-01; ALLROUTE crea órdenes Offered (§5.22)

ESTADO_BUSCANDO = "buscando"                    # consultando precio cada 3 s (R-H-01)
ESTADO_COMPRANDO = "comprando"                  # SLNEWORDER enviado, sin %SLOrder aún (el diario usa el mismo nombre)
ESTADO_PENDIENTE = "Pending"                    # %SLOrder (manual L1760-1790)
ESTADO_ESPERANDO = "Waiting"
ESTADO_OFRECIDO = "Offered"
ESTADO_LOCALIZADO = "Located"                   # cobra; con lo pedido cubierto es TERMINAL (cerrojo R-H-02)
ESTADO_PARADO = "parado"                        # hora límite, fallo de la ruta o dato imposible
ESTADO_NO_HACE_FALTA = "no_hace_falta"          # AlreadyShortable (ETB): se opera sin locate

# Jaume 29-sep: locates por FASES, enlazados con la señal (campo `Locate.fase`, persistido como el resto)
FASE_RADAR = "A"              # en el radar, sin señal: consulta cada 3 s y compra cuando compensa
FASE_SENAL = "B"              # llegó la señal de entrada sin locates: UN intento (a tiro + compensa) o parado el día
FASE_DENTRO = "C"             # dentro; faltan locates para las pirámides: cada 3 s, sin mirar «a tiro»
FASE_PIRAMIDE = "C_piramide"  # llegó la pirámide y faltan: UN intento (a tiro + compensa) o parado el día
FASE_FUERA = "D"              # posición cerrada: nada hasta una reentrada legítima (que vuelve a B)
FASE_SIN_BASE = "P"           # decisión 47: entrada perdida por locates; cada 3 s, sin «a tiro», las pirámides pendientes
FASES = (FASE_RADAR, FASE_SENAL, FASE_DENTRO, FASE_PIRAMIDE, FASE_FUERA, FASE_SIN_BASE)
FASES_INTENTO = frozenset({FASE_SENAL, FASE_PIRAMIDE})

ESTADOS_EN_CURSO = frozenset({ESTADO_COMPRANDO, ESTADO_PENDIENTE, ESTADO_ESPERANDO, ESTADO_OFRECIDO})
ESTADOS_FALLO_DAS = frozenset({"Canceled", "Rejected", "Closed", "Declined"})
# Decisión 19 (Jaume 30-sep): un rechazo de la ruta a la COMPRA no para la pareja en las fases de búsqueda continua
ESTADOS_RECHAZO_RUTA = frozenset({"Rejected", "Declined"})
CLAVE_AVISO_RECHAZO = "locate_rechazo"          # «locate_rechazo:<ticker>:<estrategia>»: el decisor lo avisa 1 vez al día
ESTADOS_TERMINALES = frozenset({ESTADO_PARADO, ESTADO_NO_HACE_FALTA})

REUSO_REUTILIZA = "reutiliza"                   # EP-9: Yes
REUSO_CONSULTAR = "consultar"                   # EP-9: sin respuesta aún → SLReuseQuery

ANOTACION_INQUIRE = "locate_inquire"
ANOTACION_INTENCION = "locate_intencion"        # fsync ANTES de SLNEWORDER (diario.FSYNC)
ANOTACION_ESTADO = "locate_estado"
ANOTACION_CADUCADOS = "locates_caducados"
TIPOS_ANOTACION = (ANOTACION_INQUIRE, ANOTACION_INTENCION, ANOTACION_ESTADO)

CLAVE_AVISO_TOPE = "locates_tope"              # decisión 50: el aviso ÚNICO del corte lo da el decisor con esta clave
ANOTACION_TOPE_GLOBAL = "locates_tope_global"   # decisión 50 (Jaume 1-oct): el corte del día; `diario.reconstruir` lo rehace
COMPRA_SIN_RESPUESTA_S = 30.0                   # E2-04: tiempo máximo en «comprando» sin %SLOrder antes de avisar

_NOTA_YA_SHORTABLE = "alreadyshortable"
_ESTADOS_DAS_CANONICOS = {e.lower(): e for e in
                          (ESTADO_PENDIENTE, ESTADO_ESPERANDO, ESTADO_OFRECIDO, ESTADO_LOCALIZADO,
                           "Canceled", "Rejected", "Closed", "Declined")}
_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_CERO = Decimal("0")
_CIEN = Decimal("100")


# ── API pública ───────────────────────────────────────────────────────
def clave_temporizador(ticker: str, strategy_id: str) -> str:
    """Clave del temporizador de consulta de un (ticker, estrategia): `locate_inquire:X:S` (§3.26, F9)."""
    return f"locate_inquire:{ticker}:{strategy_id}"


def consulta_reuso(ticker: str) -> Consultar:
    """EP-9: `SLReuseQuery X` (manual L1810-1817), al comprar y tras cada reentrada (A-06: `protocolo.cmd_sl_reuse`)."""
    _exigir_ticker(ticker)
    return Consultar(cmd_sl_reuse(ticker))


def consulta_locates() -> Consultar:
    """E2-04: `GET LOCATES` (A-06: `protocolo.cmd_get`) para rescatar una compra que no ha devuelto `%SLOrder`."""
    return Consultar(cmd_get("LOCATES"))


def gasto_comprometido(locates: Mapping[tuple[str, str], Locate],
                       umbral_ultimo_pct: Union[Decimal, int, float, str] = LOCATES_UMBRAL_ULTIMO_PAQUETE_PCT,
                       excluir: Optional[tuple[str, str]] = None) -> Decimal:
    """E2-02 (R-H-03, riesgo 11): gasto del día YA pagado (Located) + el previsto de las compras EN CURSO.

    Pagado = Σ `coste` de cada locate (solo lo mueve un Located: es lo mismo
    que `estado.gasto_locates_dia`). En curso (comprando, Pending, Waiting,
    Offered) = paquetes que faltan por cubrir · 100 · `precio_accion` del
    `%SLRET`/oferta con el que se decidió (lo que la compra va a cobrar; un
    mínimo por ruta no se conoce aquí: el tope puede quedarse un poco corto,
    nunca largo por esto). `excluir` = (ticker, strategy_id) cuyo previsto no
    se cuenta (el locate que se está evaluando: su coste nuevo ya entra aparte).
    Así dos estrategias o dos tickers con compras a la vez no superan juntos el 3 %.
    """
    pagado = sum((loc.coste for loc in locates.values()
                  if isinstance(loc, Locate) and isinstance(loc.coste, Decimal) and loc.coste.is_finite()
                  and loc.coste > 0), _CERO)
    return pagado + _previsto_en_curso(locates, umbral_ultimo_pct, excluir=excluir)


def paquetes(qty: int, umbral_ultimo_pct: Union[Decimal, int, float, str] = LOCATES_UMBRAL_ULTIMO_PAQUETE_PCT) -> tuple[int, int]:
    """H6 (FIJADA 21-sep): paquetes de 100 por lo BAJO; el último solo si se usa MÁS del umbral (30 %).

    Devuelve `(n_paquetes, qty_ajustada)`: 1.230 → (12, 1.200) (el paquete 13
    se usaría al 30 %, no «más»: se sacrifican 30 acciones); 1.240 → (13,
    1.240) (se compran las 100 y sobran 60); 1.200 → (12, 1.200); 50 → (1,
    50). Mínimo UN paquete: 30 → (1, 30) (pregunta 2 a Jaume: 30 % exacto no
    es «más del 30 %», pero H-7 dice «locates siempre ≥ 100»). qty ≤ 0 → (0,
    0). Trampa evitada: `locates_gate.paquetes_marginales` redondea hacia
    arriba (riesgo 34). ValueError si qty no es int (bool incluido) o el
    umbral no está en [0, 100].
    """
    _exigir_int(qty, "qty")
    return _paquetes_con(qty, _umbral(umbral_ultimo_pct), None)


def paquetes_marginal(qty: int, precio: Optional[Decimal], ev_pct: Optional[Decimal], precio_locate: Optional[Decimal],
                      umbral_ultimo_pct: Union[Decimal, int, float, str] = LOCATES_UMBRAL_ULTIMO_PAQUETE_PCT
                      ) -> tuple[int, int]:
    """Jaume 29-sep: regla MARGINAL del último paquete. Devuelve `(n_paquetes, qty_ajustada)` como `paquetes`.

    Los paquetes completos se compran siempre (por lo bajo); el ÚLTIMO, el que
    llevaría el resto `acciones_extra = qty − 100·⌊qty/100⌋`, se compra si lo
    que ganan esas acciones paga el paquete ENTERO:

        acciones_extra · precio · EV/100  ≥  100 · precio_locate   (en el límite exacto, se compra)

    `precio` = precio actual de la acción; `ev_pct` = EV en % (el mismo
    `ev_fijo_para_precio` que usa `veredicto_ev`); `precio_locate` = precio por
    acción ofertado o el de la última consulta. Si NO se conoce el precio del
    locate (None: primera consulta sin %SLRET) o falta el precio o el EV, cae a
    la regla del umbral (30 %) de `paquetes` (red de seguridad). Mínimo UN
    paquete (H-7); qty ≤ 0 → (0, 0). Tabla (EV 4 %, 5 $): 113 acciones y
    locate 0,01 → (2, 113); 0,05 o 0,15 → (1, 100); 160 → (2, 160) salvo con
    0,15 (60·5·0,04 = 12 < 15 → (1, 100)). ValueError con qty no int, umbral
    fuera de [0, 100] o importes no Decimal finitos (precio ≤ 0, locate < 0).
    """
    _exigir_int(qty, "qty")
    return _paquetes_con(qty, _umbral(umbral_ultimo_pct), _marginal(precio, ev_pct, precio_locate))


def cantidad_a_localizar(e: EstrategiaConfig, estimacion: Optional[list[dict]], precio: Decimal) -> int:
    """R-H-05 (FIJADA 22-sep) + R-H-01 «cantidad»: entrada + pirámides «add» de UNA estrategia al precio actual.

    Casa la fila del radar por `fila["strategy_id"] == e.strategy_id` (lo añade
    la fuente, corrección 6; riesgo 25: por `nombre` se compraría para la
    estrategia equivocada). Ninguna fila o MÁS de una → 0 (no se compra a
    ciegas). Entrada = `acciones` de la fila (float del motor → int al par,
    como `entrada.qty_de_evento`; None, NaN, ±inf, bool o ≤ 0 → 0). Cada nivel
    «add» de `e.niveles_piramide` (acción distinta de «reduce», como
    `strategy_engine.compile_strategy_def`) suma `acciones · riesgo_nivel /
    riesgo_fila` redondeado al par, con riesgo_nivel = `riesgos_piramide[k]`
    del cuadro (k = posición en la definición, `def_index`) si es > 0, si no
    `riesgo_piramide_usd`, si no `riesgo_usd` (§4.4b; la misma cadena que
    `bot_alerts_engine._riesgo_del_nivel` más el riesgo de entrada como último
    respaldo). `precio` solo se valida (finito > 0; si no → 0): la fila ya
    viene calculada a ese precio.

    APROXIMACIÓN (E2-09, a documentar en §14): cuando el nivel no tiene riesgo
    propio ni global, el motor (`bot_alerts_engine._riesgo_del_nivel` → None)
    usa «lo que diga la estrategia»; aquí se usa el riesgo de ENTRADA y se
    escala en proporción suponiendo la MISMA distancia al stop que la entrada.
    Puede localizar de más o de menos respecto a lo que la pirámide pedirá de
    verdad. Lo exacto sería que la fuente del radar añadiera a cada fila las
    acciones por nivel calculadas por el motor (otra unidad). Nunca compra a
    ciegas: sigue pasando por el EV con el coste TOTAL y el tope del 3 %.

    REPETICIONES (decisión 20, Jaume 30-sep): cada nivel cuenta UNA sola vez
    aunque lleve `times` ≥ 2 (o ilimitado): nunca se multiplica, para no poder
    comprar locates sin tope. Esas estrategias, además, no ejecutan
    (`config.niveles_con_repeticiones`).
    """
    if not _decimal_positivo(precio):
        return 0
    filas = [f for f in (estimacion or []) if isinstance(f, Mapping) and f.get("strategy_id") == e.strategy_id]
    if len(filas) != 1:
        return 0
    fila = filas[0]
    acciones = _decimal_positivo(fila.get("acciones"))
    if acciones is None:
        return 0
    entrada = int(round(acciones))
    if entrada <= 0:
        return 0
    return entrada + sum(n for _, n in acciones_piramides(e, acciones, fila.get("riesgo_usd")))


def acciones_piramides(e: EstrategiaConfig, acciones_entrada: Any, riesgo_entrada: Any) -> list[tuple[int, int]]:
    """R-H-05: (k, acciones) de cada nivel «add» de la estrategia, con la MISMA fórmula que `cantidad_a_localizar`.

    k = posición del nivel en `e.niveles_piramide` (`def_index`); acciones =
    `acciones_entrada · riesgo_nivel / riesgo_entrada` redondeado al par, con
    el riesgo del nivel de `_riesgo_del_nivel` y el de la entrada (o, sin él,
    `e.riesgo_usd`). Sin acciones o sin riesgo de entrada válidos → [] (no se
    localiza a ciegas). Niveles con 0 acciones no se devuelven. Decisión 47
    (Jaume 30-sep): con la entrada perdida por locates, la fase P busca SOLO
    estas acciones (las de la entrada perdida no).
    """
    acciones = _decimal_positivo(acciones_entrada)
    if acciones is None:
        return []
    riesgo = _decimal_positivo(riesgo_entrada) or _decimal_positivo(e.riesgo_usd)
    if riesgo is None:
        return []
    salida: list[tuple[int, int]] = []
    for k, nivel in enumerate(e.niveles_piramide or []):
        if not _es_nivel_add(nivel):
            continue
        riesgo_nivel = _riesgo_del_nivel(e, k)
        if riesgo_nivel is None:
            continue
        n = int(round(acciones * riesgo_nivel / riesgo))
        if n > 0:
            salida.append((k, n))
    return salida


def veredicto_ev(e: EstrategiaConfig, precio: Decimal, qty: int, precio_accion_locate: Decimal,
                 coste_ya_pagado: Decimal, *, ya_localizadas: int = 0, disponibles: Optional[int] = None,
                 umbral_ultimo_pct: Union[Decimal, int, float, str] = LOCATES_UMBRAL_ULTIMO_PAQUETE_PCT,
                 minimo_cargo: Optional[Decimal] = None) -> dict:
    """R-H-01 (EV del cuadro) + H6 (paquetes) + R-H-05 / R-H-01.4 (coste TOTAL acumulado); corrección 1.

    EV = `locates_gate.ev_fijo_para_precio(float(e.ev_pct), e.ev_rangos,
    float(precio))` (tramo de precio si lo hay, si no el completo), pasado a
    Decimal por `str`. Cuenta: `n_total, qty_aj = paquetes(qty)`; cubiertas =
    min(ya_localizadas, qty_aj); lo que falta se vuelve a pasar por H6 («sobre
    la suma de cada compra»); el ÚLTIMO paquete (y un resto sobre lo cubierto)
    va por la regla MARGINAL de `paquetes_marginal` con `precio_accion_locate`
    (Jaume 29-sep); con `disponibles` (tamaño de `%SLRET` u oferta)
    se compran solo los paquetes enteros que hay (R-H-04: se opera con lo que
    hay). coste_nuevo = paquetes · 100 · precio_accion_locate (mínimo de la
    ruta si lo hay, `SLRouteMinCharge`); fade = (coste_ya_pagado +
    coste_nuevo) / (acciones usables · precio) · 100; entra = hay algo que
    comprar y EV > fade. Devuelve {entra, ev_pct, fade_pct, margen_pct,
    paquetes, qty_ajustada (acciones usables tras esta compra), qty_comprar
    (paquetes · 100), coste_nuevo, coste_total, ev_origen ("rango" |
    "completo"), motivo (None o por qué no entra)}; todo importe en Decimal.
    ValueError con precio ≤ 0/no finito, qty o ya_localizadas no int,
    importes negativos o no Decimal finitos.
    """
    _exigir_decimal(precio, "precio", positivo=True)
    _exigir_int(qty, "qty")
    _exigir_decimal(precio_accion_locate, "precio_accion_locate")
    _exigir_decimal(coste_ya_pagado, "coste_ya_pagado")
    _exigir_int(ya_localizadas, "ya_localizadas")
    if ya_localizadas < 0:
        raise ValueError(f"ya_localizadas negativo: {ya_localizadas}")
    if disponibles is not None:
        _exigir_int(disponibles, "disponibles")
    if minimo_cargo is not None:
        _exigir_decimal(minimo_cargo, "minimo_cargo")

    ev_float, ev_origen = ev_fijo_para_precio(float(e.ev_pct), e.ev_rangos, float(precio))
    ev = de_float(ev_float)
    # Jaume 29-sep: el último paquete (y el resto sobre lo ya cubierto) por la regla MARGINAL con el precio de ESTE
    # locate; el primer paquete y el veredicto global, como siempre (EV contra el fade del coste TOTAL).
    umbral = _umbral(umbral_ultimo_pct)
    marginal = _marginal(precio, ev, precio_accion_locate)
    _, qty_aj = _paquetes_con(qty, umbral, marginal)
    cubiertas = min(ya_localizadas, qty_aj)
    falta = _falta_comprable(qty_aj, cubiertas, umbral, marginal)
    n_nuevo, falta_aj = _paquetes_con(falta, umbral, marginal) if falta > 0 else (0, 0)
    motivo: Optional[str] = None if falta > 0 else (
        "nada que localizar" if qty_aj - cubiertas <= 0 else
        "el resto no llega al umbral de un paquete (H6, E2-08): se opera con lo ya localizado")
    if disponibles is not None and n_nuevo > max(0, disponibles) // PAQUETE:
        n_nuevo = max(0, disponibles) // PAQUETE
        falta_aj = min(falta_aj, n_nuevo * PAQUETE)
        if n_nuevo == 0:
            motivo = "sin paquetes de 100 disponibles"
    qty_usable = cubiertas + falta_aj
    coste_nuevo = Decimal(n_nuevo * PAQUETE) * precio_accion_locate if n_nuevo > 0 else _CERO
    if n_nuevo > 0 and minimo_cargo is not None and coste_nuevo < minimo_cargo:
        coste_nuevo = minimo_cargo
    coste_total = coste_ya_pagado + coste_nuevo
    fade = coste_total * _CIEN / (Decimal(qty_usable) * precio) if qty_usable > 0 else _CERO
    entra = n_nuevo > 0 and ev > fade
    if n_nuevo > 0 and not entra:
        motivo = "el EV no compensa el coste total"
    return {
        "entra": entra,
        "ev_pct": ev,
        "fade_pct": fade,
        "margen_pct": ev - fade,
        "paquetes": n_nuevo,
        "qty_ajustada": qty_usable,
        "qty_comprar": n_nuevo * PAQUETE,
        "coste_nuevo": coste_nuevo,
        "coste_total": coste_total,
        "ev_origen": ev_origen,
        "motivo": motivo,
    }


def tope_superado(gasto_dia: Decimal, coste_nuevo: Decimal,
                  tope_usd: Union[Decimal, int, float, str] = LOCATES_TOPE_GASTO_DIA_USD) -> bool:
    """R-H-03 / decisión 60 (Jaume 2-oct): ¿esta compra haría SUPERAR el tope del día en DÓLARES fijos?

    `gasto_dia + coste_nuevo > tope_usd` → True; justo en el tope se permite
    («no se compra ningún locate que haga superar»). El tope ya NO depende del
    equity (antes: equity · pct / 100; sin equity legible no se compraba).
    ValueError con importes negativos o no finitos o con un tope ≤ 0.
    """
    _exigir_decimal(gasto_dia, "gasto_dia")
    _exigir_decimal(coste_nuevo, "coste_nuevo")
    tope = de_float(tope_usd)
    if not tope.is_finite() or tope <= 0:
        raise ValueError(f"tope de locates del día no válido: {tope_usd!r}")
    return gasto_dia + coste_nuevo > tope


def tope_dia_usd(cfg_loc: Any) -> Decimal:
    """Decisión 60 (Jaume 2-oct): `locates.tope_gasto_dia_usd` del cuadro (o el defecto de tipos, 400 $).

    La clave vieja `tope_gasto_pct_cuenta` (un % del equity) ya no se usa: un
    cuadro que aún la traiga carga y se ignora. Un valor imposible (≤ 0, no
    numérico) vale el defecto: el cuadro ya lo rechaza al cargar.
    """
    valor = cfg_loc.get("tope_gasto_dia_usd") if isinstance(cfg_loc, Mapping) else None
    tope = _decimal_positivo(valor)
    return tope if tope is not None else LOCATES_TOPE_GASTO_DIA_USD


def compra_repetida(locates: Mapping[tuple[str, str], Locate], ticker: str, strategy_id: str, *,
                    id_das: Optional[int] = None, token: Optional[int] = None) -> bool:
    """R-H-02 (FIJADA 16-sep): ¿un Located que llega ahora es una SEGUNDA compra NO pedida? → deshabilitar el módulo.

    El decisor la llama al recibir `%SLOrder … Located` de (ticker, estrategia)
    ANTES de aplicarlo, con `id_das` = id de ese `%SLOrder`. True si ya hubo al
    menos una compra (`compras ≥ 1`), el mensaje NO es el de la última orden
    conocida (`id_das` distinto de `loc.id_das`: los `GET LOCATES` repiten los
    Located y un duplicado no es una compra) y no hay ninguna compra pedida en
    curso (estado fuera de comprando/Pending/Waiting/Offered). Las compras
    legítimas (parcial R-H-04, reentrada sin reutilización EP-9) pasan antes por
    `locate_intencion` y llegan con el estado «comprando». Sin registro → False
    (no es una SEGUNDA compra; una orden ajena la trata la reconciliación).
    `token` (opcional, E2-04): el `%SLOrder` trae el token de NUESTRA última
    compra pedida → no es repetida aunque el locate ya esté «parado» (una
    compra sin respuesta en 30 s que por fin llega).
    """
    loc = locates.get((ticker, strategy_id))
    if loc is None or loc.compras < 1:
        return False
    if id_das is not None and loc.id_das == id_das:
        return False
    if token is not None and loc.token is not None and token == loc.token:
        return False
    return loc.estado not in ESTADOS_EN_CURSO


def asignar_a_lote(locates: Mapping[tuple[str, str], Locate], ticker: str, qty: int,
                   strategy_id: str) -> list[tuple[str, int]]:
    """E9 (Jaume, 18-sep): el locate se carga PRIMERO a la estrategia que da la señal; lo que le falte, de los sobrantes de las demás.

    Devuelve [(strategy_id cuyo locate se usa, acciones)], sin entradas a 0,
    con suma ≤ qty (lo que no se cubre no está: el decisor entra con menos,
    R-H-04). Libres propias = localizadas − usadas. Sobrante de otra
    estrategia T del mismo ticker = sus libres menos lo que T aún necesita para
    sí (max(0, pedidas − usadas)): nunca se le quita a T lo que compró para su
    propia entrada (H6: «sobran 60» del último paquete). Orden de las demás:
    compradas antes primero, luego por strategy_id (determinista). ETB
    (`no_hace_falta` en cualquier locate del ticker) → [(strategy_id, qty)]:
    no hace falta locate. qty ≤ 0 → []. ValueError si qty no es int.
    """
    _exigir_int(qty, "qty")
    if qty <= 0:
        return []
    del_ticker = [loc for (t, _), loc in locates.items() if t == ticker]
    if any(loc.estado == ESTADO_NO_HACE_FALTA for loc in del_ticker):
        return [(strategy_id, qty)]
    reparto: list[tuple[str, int]] = []
    falta = qty
    propio = locates.get((ticker, strategy_id))
    if propio is not None:
        usar = min(falta, _libres(propio))
        if usar > 0:
            reparto.append((strategy_id, usar))
            falta -= usar
    otros = sorted((loc for loc in del_ticker if loc.strategy_id != strategy_id),
                   key=lambda loc: (loc.comprado_en is None, loc.comprado_en or 0.0, loc.strategy_id))
    for loc in otros:
        if falta <= 0:
            break
        sobrante = _libres(loc) - max(0, loc.pedidas - loc.usadas)
        usar = min(falta, max(0, sobrante))
        if usar > 0:
            reparto.append((loc.strategy_id, usar))
            falta -= usar
    return reparto


def caducados(locates: Mapping[tuple[str, str], Locate]) -> list[Locate]:
    """R-H-05 / 2e.4: al cerrar el día, los locates con acciones localizadas y NO usadas (coste hundido, «caducados»).

    Caducan al cierre y no se reembolsan: se llevan al diario
    (`locates_caducados`) para medir el desperdicio. Ordenados por (ticker,
    strategy_id); los ETB (`no_hace_falta`) no cuentan.
    """
    return [loc for _, loc in sorted(locates.items(), key=lambda par: par[0])
            if loc.estado != ESTADO_NO_HACE_FALTA and _libres(loc) > 0]


def tras_reentrada(loc: Locate, reuse: Optional[MsgSLReuse]) -> str:
    """EP-9 (CERRADO 25-sep) + R-D-04: ¿el locate ya comprado vale para la reentrada?

    `$SLReuseQueryRet X Yes` → `REUSO_REUTILIZA` (el decisor pone `usadas = 0`:
    las mismas acciones vuelven a estar libres); `No` → `ESTADO_BUSCANDO`
    (locate de un solo uso: se vuelve a comprar lo que falte con el coste TOTAL
    acumulado, `siguiente_paso` lo decide por EV); sin respuesta (None) →
    `REUSO_CONSULTAR` (el decisor manda `consulta_reuso(X)`: la lista cambia
    intradía, no se supone nada). ETB → `ESTADO_NO_HACE_FALTA`. ValueError si
    la respuesta es de otro ticker.
    """
    if loc.estado == ESTADO_NO_HACE_FALTA:
        return ESTADO_NO_HACE_FALTA
    if reuse is None:
        return REUSO_CONSULTAR
    if reuse.ticker.strip().upper() != loc.ticker.strip().upper():
        raise ValueError(f"SLReuseQueryRet de {reuse.ticker!r} para el locate de {loc.ticker!r}")
    return REUSO_REUTILIZA if reuse.reutilizable else ESTADO_BUSCANDO


def siguiente_paso(loc: Optional[Locate], e: EstrategiaConfig, ticker: str, precio: Optional[Decimal], ahora: float,
                   cfg_loc: Mapping[str, Any], gasto_dia: Decimal, equity: Optional[Decimal], deshabilitado: bool,
                   ret: Optional[MsgSLRet], tokens: Union[Callable[[], int], Any], *, qty: Optional[int] = None,
                   orden: Optional[MsgSLOrder] = None, minimo_cargo: Optional[Decimal] = None,
                   ahora_et: Optional[datetime] = None,
                   locates: Optional[Mapping[tuple[str, str], Locate]] = None,
                   tope_a_tiro_pct: Union[Decimal, int, float, str, None] = None,
                   en_uso_vivo: int = 0, corte_dia: bool = False) -> list[Accion]:
    """R-H-01..R-H-04 + H6 + EP-9, manual L1648-1838: el siguiente paso de la máquina de un (ticker, estrategia).

    Entradas: `loc` (None = aún no hay; entonces `qty` = acciones de
    `cantidad_a_localizar`, y con qty None o ≤ 0 no se hace nada), `ret` (un
    `%SLRET`), `orden` (un `%SLOrder`), o ninguno (radar o temporizador
    `locate_inquire:X:S`). `tokens`: callable o `GeneradorTokens` de
    `Origen.EJECUTOR_LOCATE` (se llama SOLO al comprar; otro origen →
    ValueError). `cfg_loc` = bloque `locates` del cuadro. `ahora_et` (aware)
    es obligatorio si hay `hora_limite_intentos`.

    Máquina: deshabilitado (R-H-02/03, vigilante) → []. buscando: hora límite
    → parado; si toca (cada `inquiry_intervalo_s`) → `Anotar(locate_inquire)`
    + `LocateInquire(X, paquetes·100, ALLROUTEWTTYPE1)` + `Programar`; si no
    toca → `Programar` con lo que falta. `%SLRET` 1 con tamaño > 0,
    `veredicto_ev.entra` (coste TOTAL, `disponibles` = tamaño) y NOT
    `tope_superado` → `Anotar(locate_intencion)` (write-ahead, antes del
    envío) + `LocateComprar(X, paquetes·100, ruta del %SLRET, token)` +
    `Desprogramar`; tope (decisión 60: `tope_gasto_dia_usd`, dólares fijos;
    `equity` ya no se usa para el tope) → corte del día (decisión 50). `%SLRET` 2 `AlreadyShortable` → no_hace_falta. `%SLOrder` propio:
    Pending/Waiting → anotar; Offered → `LocateOferta(Accept)` solo si el EV y
    el tope siguen bien y la oferta no pasa de lo decidido, si no `Reject` y
    vuelve a buscando; Located → `Anotar(locate_estado Located, coste_nuevo,
    coste_total)` + `SLReuseQuery` (EP-9) y, si aún faltan acciones, parcial
    (R-H-04) → buscando + consulta INMEDIATA; Canceled/Rejected/Closed/
    Declined → parado + `Avisar(2)` (H16: fallos por definir → humano).
    Decisión 19 (Jaume 30-sep): Rejected/Declined de la ruta en las fases de
    búsqueda continua (A radar y C dentro) NO para la pareja: se anota, se
    avisa (clave `locate_rechazo:X:S`, el decisor la deja salir UNA vez al
    día) y se sigue buscando con el intervalo normal (3 s), «hasta tener los
    locates con el protocolo de siempre». En B y C_piramide sigue siendo UN
    intento (parado). El cerrojo R-H-02 y el tope del 3 % no cambian.
    Located cubriendo lo pedido, parado y no_hace_falta → [] (cerrojo R-H-02).

    Correcciones de la revisión (todas aditivas):
      * E2-02: `locates` (solo por nombre; el decisor pasa `estado.locates`)
        suma al gasto del tope el coste PREVISTO de las compras en curso de
        los demás locates (`gasto_comprometido`): dos compras a la vez no
        superan juntas el 3 %. Sin `locates`, el tope ve solo `gasto_dia`.
      * E2-04: al comprar se PROGRAMA el temporizador a `COMPRA_SIN_RESPUESTA_S`
        (30 s) en vez de desprogramarlo, y la intención anota
        `ultimo_inquire_en = ahora` (la hora de la compra). Si en «comprando»
        pasan 30 s sin `%SLOrder` → `GET LOCATES` + `Avisar(2)` + parado. NUNCA
        se recompra (riesgo 11); un Located que llegue después se contabiliza.
      * E2-06: el tope por gasto YA PAGADO pasa el locate a «parado» (un solo
        aviso por locate, no uno por minuto); si solo lo superan las compras
        en curso, se anota sin aviso y se sigue buscando (puede fallar alguna).
      * E2-08: el «mínimo un paquete» solo vale cuando no hay nada cubierto: un
        resto ≤ 30 % de un paquete sobre acciones ya localizadas no se compra.

    Jaume 29-sep (locates por FASES): con `loc.fase` en `FASES_INTENTO` (B en
    la señal de entrada, C_piramide en la de pirámide) la consulta es UN
    intento: se compra solo si el precio está «a tiro» (precio actual ≥
    `loc.precio_senal` · (1 − `tope_a_tiro_pct`/100), el MISMO 3 % de
    R-B-01, `entrada.tope_caida_bid_pct`) y compensa (EV + regla marginal); si
    no (o sin tamaño, fallo de la ruta, tope, oferta rechazada) → «parado»
    para todo el día en esa pareja. `en_uso_vivo` = locates de la pareja que
    usan lotes VIVOS (lo pasa el decisor): cuentan como cubiertos, así la
    búsqueda de las pirámides (fase C) no vuelve a comprar lo que ya usa la
    entrada.

    Decisión 51 (Jaume 1-oct): tras un Located PARCIAL el resto (`necesarias −
    localizadas`) se sigue buscando con el protocolo de la fase (misma cadencia
    y mismas condiciones de fin, que aplica el decisor), sin el tope de 60 s
    del ensayo del 28-sep. Decisión 50 (Jaume 1-oct): tope GLOBAL del día. Si
    una compra no cabe en el tope con lo YA PAGADO (`gasto_dia`), la pareja
    queda parada y sale `Anotar("locates_tope_global")` (sin aviso: el aviso
    ÚNICO lo da el decisor al cortar). Con `corte_dia` (el corte ya está
    hecho) no se consulta ni se compra nada; de una compra en vuelo solo se
    contabiliza el Located (el dinero ya se gastó, sin buscar el resto), una
    oferta se rechaza y un fallo de la ruta deja la pareja parada SIN aviso.
    """
    if deshabilitado or (corte_dia and orden is None):
        return []
    _exigir_ticker(ticker)
    _exigir_int(en_uso_vivo, "en_uso_vivo")
    if loc is None:
        if qty is None:
            return []
        _exigir_int(qty, "qty")
        if qty <= 0:
            return []
        loc = Locate(ticker=ticker, strategy_id=e.strategy_id, pedidas=qty)
    elif loc.ticker != ticker or loc.strategy_id != e.strategy_id:
        raise ValueError(f"el locate ({loc.ticker}, {loc.strategy_id}) no es de ({ticker}, {e.strategy_id})")
    cfg = _ConfigLocates.de(cfg_loc)
    fuera_de_hora = _hora_limite_pasada(cfg.hora_limite, ahora_et)
    en_curso = _previsto_en_curso(locates, cfg.umbral, excluir=(loc.ticker, loc.strategy_id)) if locates else _CERO
    tope_tiro = _valor_decimal(tope_a_tiro_pct, ENTRADA_TOPE_CAIDA_BID_PCT)
    if tope_tiro < 0 or tope_tiro > _CIEN:
        raise ValueError(f"tope «a tiro» fuera de [0, 100]: {tope_a_tiro_pct!r}")
    ctx = _Contexto(loc=loc, e=e, ticker=ticker, precio=precio, ahora=ahora, cfg=cfg, gasto_dia=gasto_dia,
                    equity=equity, tokens=tokens, minimo_cargo=minimo_cargo, fuera_de_hora=fuera_de_hora,
                    gasto_en_curso=en_curso, tope_a_tiro=tope_tiro, en_uso=max(0, en_uso_vivo),
                    corte=bool(corte_dia))
    if orden is not None:
        return _tras_orden(ctx, orden)
    if loc.estado == ESTADO_COMPRANDO and ret is not None:
        return _fallo_durante_compra(ctx, ret)
    if loc.estado == ESTADO_COMPRANDO:
        return _compra_sin_respuesta(ctx)
    if loc.estado != ESTADO_BUSCANDO:
        return []                                   # Located (cerrojo), en curso, parado, no_hace_falta u otro
    if fuera_de_hora:
        return [_anotar_estado(ctx, ESTADO_PARADO, motivo="hora límite de intentos (R-H-01.5)"),
                Desprogramar(ctx.clave)]
    if ctx.falta_por_cubrir() <= 0:
        if ctx.intento_unico:
            # Jaume 29-sep: en el intento único un resto pequeño SIN precio de locate conocido se consulta igual (la
            # regla marginal decide con el %SLRET); si de verdad no queda nada que compre, el intento acaba aquí.
            if ctx.falta_bruta() <= 0 or ctx.marginal() is not None:
                return _sin_compra(ctx, _datos(ctx, motivo="nada que comprar que compense (regla marginal / H6)"))
        else:
            return [Anotar(ANOTACION_INQUIRE, _datos(ctx, motivo="nada que localizar: lo pedido ya está cubierto")),
                    Desprogramar(ctx.clave)]
    if ret is not None:
        return _tras_ret(ctx, ret)
    # Decisión 51 (Jaume 1-oct): un parcial ya cobrado sigue buscando el resto con la cadencia de la fase y SIN tope de
    # tiempo (el de 60 s del ensayo del 28-sep se quitó): el fin lo ponen las condiciones de la fase, que aplica el
    # decisor (ventana de entradas, 30 min fuera del radar, entrada hecha sin pirámides pendientes, tope global…).
    return _consultar_si_toca(ctx)


def aplicar_anotaciones(loc: Optional[Locate], acciones: Iterable[Accion]) -> Optional[Locate]:
    """El reductor: aplica los `Anotar(locate_*)` de `siguiente_paso` a un `Locate` y devuelve uno NUEVO (H-2).

    Mismas reglas que `diario.reconstruir` (`_aplicar_locate_intencion/
    estado`) para que el estado en caliente y el releído tras un reinicio sean
    el mismo: `estado` si viene; `pedidas = max(pedidas, qty_ajustada o qty)`;
    `localizadas`, `usadas`, `id_das`, `token`, `precio_accion`,
    `reutilizable`, `ultimo_inquire_en` y `comprado_en` si vienen. El coste
    SOLO lo mueve `locate_estado` (en inquire/intención es una previsión):
    al ENTRAR en Located, `compras += 1`; en Located `coste = coste_total` (o
    `coste + coste_nuevo`); fuera de Located `coste = coste_total` si viene
    (por eso las previsiones de un `locate_estado` Offered van como
    `coste_*_previsto`). Ignora las
    acciones que no son `Anotar(locate_*)` y las de otro (ticker, estrategia).
    loc None → se crea con la primera anotación que traiga ticker y estrategia.
    """
    actual = loc
    for accion in acciones:
        if not isinstance(accion, Anotar) or accion.tipo not in TIPOS_ANOTACION:
            continue
        datos = accion.datos
        ticker, sid = datos.get("ticker"), datos.get("strategy_id")
        if not isinstance(ticker, str) or not isinstance(sid, str):
            continue
        if actual is None:
            actual = Locate(ticker=ticker, strategy_id=sid, pedidas=0)
        elif actual.ticker != ticker or actual.strategy_id != sid:
            continue
        actual = _aplicar_una(actual, accion.tipo, datos)
    return actual


def gasto_de(acciones: Iterable[Accion]) -> Decimal:
    """R-H-03: lo que suman al gasto del día los `Anotar(locate_estado, estado=Located)` (su `coste_nuevo`), como el diario."""
    total = _CERO
    for accion in acciones:
        if (isinstance(accion, Anotar) and accion.tipo == ANOTACION_ESTADO
                and accion.datos.get("estado") == ESTADO_LOCALIZADO):
            coste = accion.datos.get("coste_nuevo")
            if isinstance(coste, Decimal) and coste.is_finite():
                total += coste
    return total


# ── la máquina por dentro ─────────────────────────────────────────────
@dataclasses.dataclass(frozen=True)
class _ConfigLocates:
    tope_usd: Decimal
    umbral: Decimal
    intervalo_s: float
    ruta: str
    hora_limite: Optional[tuple[int, int]]

    @staticmethod
    def de(cfg_loc: Mapping[str, Any]) -> "_ConfigLocates":
        """Bloque `locates` de §7 → valores validados (ValueError si alguno es imposible)."""
        if not isinstance(cfg_loc, Mapping):
            raise ValueError("cfg_loc debe ser el bloque «locates» de la configuración")
        tope_crudo = cfg_loc.get("tope_gasto_dia_usd")
        tope = _valor_decimal(tope_crudo, LOCATES_TOPE_GASTO_DIA_USD)
        if not tope.is_finite() or tope <= 0:
            raise ValueError(f"tope_gasto_dia_usd debe ser > 0: {tope_crudo!r}")
        umbral = _valor_decimal(cfg_loc.get("umbral_ultimo_paquete_pct"), LOCATES_UMBRAL_ULTIMO_PAQUETE_PCT)
        if umbral < 0 or umbral > _CIEN:
            raise ValueError(f"umbral_ultimo_paquete_pct fuera de [0, 100]: {umbral}")
        intervalo = float(_valor_decimal(cfg_loc.get("inquiry_intervalo_s"), Decimal(str(LOCATES_INQUIRE_S))))
        if intervalo <= 0:
            raise ValueError(f"inquiry_intervalo_s debe ser > 0: {intervalo}")
        ruta = cfg_loc.get("ruta_inquire")
        ruta = RUTA_INQUIRE_DEFECTO if ruta is None else ruta
        if not isinstance(ruta, str) or not ruta.strip() or any(c.isspace() for c in ruta.strip()):
            raise ValueError(f"ruta_inquire no válida: {ruta!r}")
        ruta = ruta.strip()
        if ruta.upper() == "ALLROUTE":
            raise ValueError("ruta_inquire ALLROUTE crea órdenes Offered en rutas tipo 1 (§5.22): usar ALLROUTEWTTYPE1")
        return _ConfigLocates(tope_usd=tope, umbral=umbral, intervalo_s=intervalo, ruta=ruta,
                              hora_limite=_hora_limite(cfg_loc.get("hora_limite_intentos")))


@dataclasses.dataclass(frozen=True)
class _Contexto:
    loc: Locate
    e: EstrategiaConfig
    ticker: str
    precio: Optional[Decimal]
    ahora: float
    cfg: _ConfigLocates
    gasto_dia: Decimal
    equity: Optional[Decimal]
    tokens: Any
    minimo_cargo: Optional[Decimal]
    fuera_de_hora: bool
    gasto_en_curso: Decimal = _CERO                    # E2-02: previsto de las compras en curso de los demás
    tope_a_tiro: Decimal = Decimal("3")                # Jaume 29-sep: el 3 % de R-B-01 (entrada.tope_caida_bid_pct)
    en_uso: int = 0                                    # Jaume 29-sep: locates de la pareja que usan lotes vivos
    corte: bool = False                                # decisión 50 (Jaume 1-oct): el tope del día ya cortó las compras

    def tope_por_lo_pagado(self, coste_nuevo: Decimal) -> bool:
        """Decisión 50: ¿la compra no cabe en el tope con lo YA PAGADO (sin contar las compras en curso)? Decisión 60
        (Jaume 2-oct): el tope son dólares fijos del cuadro; ya no hace falta el equity."""
        return tope_superado(self.gasto_dia, coste_nuevo, self.cfg.tope_usd)

    @property
    def clave(self) -> str:
        return clave_temporizador(self.ticker, self.loc.strategy_id)

    @property
    def intento_unico(self) -> bool:
        """Jaume 29-sep: fase B o C_piramide: la consulta de la señal es UN intento (si no compra → parado el día)."""
        return self.loc.fase in FASES_INTENTO

    def a_tiro(self) -> bool:
        """Jaume 29-sep: corto «a tiro» = precio actual ≥ precio de la señal · (1 − 3 %) (el límite exacto está a tiro).

        Sin precio actual o sin precio de la señal → NO está a tiro (no se compra a ciegas)."""
        referencia = self.loc.precio_senal
        if not _decimal_positivo(self.precio) or not _decimal_positivo(referencia):
            return False
        return self.precio >= referencia * (_CIEN - self.tope_a_tiro) / _CIEN

    def cubiertas(self) -> int:
        """Lo que ya cubre la pareja: libres (localizadas − usadas) + lo que usan sus lotes vivos (fase C)."""
        return _libres(self.loc) + self.en_uso

    @property
    def gasto_tope(self) -> Decimal:
        """E2-02: el gasto contra el que se mide el 3 %: lo pagado + lo comprometido por otras compras en curso."""
        return self.gasto_dia + self.gasto_en_curso

    def marginal(self, precio_locate: Optional[Decimal] = None) -> Optional[tuple[Decimal, Decimal, Decimal]]:
        """Jaume 29-sep: (precio, EV, precio del locate) para la regla marginal; el locate es `precio_locate` o el de
        la última consulta (`loc.precio_accion`; 0 = aún no se conoce). Sin precio de la acción o del locate → None
        (umbral del 30 %)."""
        pl = precio_locate if precio_locate is not None else self.loc.precio_accion
        if not _decimal_no_negativo(pl) or (precio_locate is None and pl <= 0):
            return None
        if not _decimal_positivo(self.precio):
            return None
        ev_float, _ = ev_fijo_para_precio(float(self.e.ev_pct), self.e.ev_rangos, float(self.precio))
        return self.precio, de_float(ev_float), pl

    def objetivo(self, precio_locate: Optional[Decimal] = None) -> int:
        """Acciones que la posición usará tras H6 / la regla marginal (qty_ajustada de lo pedido)."""
        return _paquetes_con(max(0, self.loc.pedidas), self.cfg.umbral, self.marginal(precio_locate))[1]

    def falta_por_cubrir(self) -> int:
        """Lo que falta y MERECE comprarse (E2-08: un resto que no compensa sobre acciones ya cubiertas no)."""
        return _falta_comprable(self.objetivo(), self.cubiertas(), self.cfg.umbral, self.marginal())

    def falta_bruta(self) -> int:
        """Lo que falta sin filtrar el resto pequeño (objetivo − cubiertas)."""
        return max(0, self.objetivo() - self.cubiertas())

    def qty_consulta(self) -> int:
        """Acciones a consultar/comprar ahora: los paquetes (H6 / marginal) de lo que falta, · 100. En el intento único
        (Jaume 29-sep) un resto que el filtro descarta sin precio conocido se consulta igual (un paquete)."""
        falta = self.falta_por_cubrir()
        if falta <= 0 and self.intento_unico:
            falta = self.falta_bruta()
        return _paquetes_con(falta, self.cfg.umbral, self.marginal())[0] * PAQUETE

    def veredicto(self, precio_accion: Decimal, disponibles: Optional[int]) -> dict:
        return veredicto_ev(self.e, self.precio, self.loc.pedidas, precio_accion, self.loc.coste,
                            ya_localizadas=self.cubiertas(), disponibles=disponibles,
                            umbral_ultimo_pct=self.cfg.umbral, minimo_cargo=self.minimo_cargo)


def _consultar_si_toca(ctx: _Contexto) -> list[Accion]:
    """R-H-01: una consulta de precio cada `inquiry_intervalo_s` (manual: 1 cada 3 s; `CuotaComandos` serializa)."""
    ultimo = ctx.loc.ultimo_inquire_en
    if ultimo is not None:
        transcurrido = ctx.ahora - ultimo
        if 0 <= transcurrido < ctx.cfg.intervalo_s:
            return [_programar(ctx, ctx.cfg.intervalo_s - transcurrido)]
    qty_consulta = ctx.qty_consulta()
    return [Anotar(ANOTACION_INQUIRE, _datos(ctx, estado=ESTADO_BUSCANDO, qty_consulta=qty_consulta,
                                             ultimo_inquire_en=ctx.ahora)),
            LocateInquire(ctx.ticker, qty_consulta, ctx.cfg.ruta),
            _programar(ctx, ctx.cfg.intervalo_s)]


def _tras_ret(ctx: _Contexto, ret: MsgSLRet) -> list[Accion]:
    """`%SLRET` en «buscando» (manual L1701-1720): tipo 2 AlreadyShortable → ETB; tipo 1 → EV, tope y compra."""
    if not _mismo_ticker(ret.ticker, ctx.ticker):
        return []
    if ret.tipo == 2:
        if _es_ya_shortable(ret.notas):
            return [_anotar_estado(ctx, ESTADO_NO_HACE_FALTA, motivo="AlreadyShortable (ETB)", notas=ret.notas),
                    Desprogramar(ctx.clave)]
        return _sin_compra(ctx, _datos(ctx, ruta=ret.ruta, fallo=ret.notas), f"fallo de la ruta: {ret.notas}")
    if ret.tipo != 1:
        return _sin_compra(ctx, _datos(ctx, ruta=ret.ruta, motivo=f"RetType {ret.tipo} desconocido"))
    if not _decimal_no_negativo(ret.precio):
        return _sin_compra(ctx, _datos(ctx, ruta=ret.ruta, motivo="precio del locate no válido"))
    if ret.tamano <= 0:
        return _sin_compra(ctx, _datos(ctx, ruta=ret.ruta, precio_accion=ret.precio, disponibles=0,
                                       motivo="sin acciones disponibles"))
    if not _decimal_positivo(ctx.precio):
        return _sin_compra(ctx, _datos(ctx, ruta=ret.ruta, precio_accion=ret.precio,
                                       motivo="sin precio de la acción para el EV"))
    if ctx.intento_unico and not ctx.a_tiro():
        return _sin_compra(ctx, _datos(ctx, ruta=ret.ruta, precio_accion=ret.precio, precio=ctx.precio,
                                       precio_senal=ctx.loc.precio_senal, tope_a_tiro_pct=ctx.tope_a_tiro,
                                       motivo="el precio no está a tiro de la señal (Jaume 29-sep)"))
    ver = ctx.veredicto(ret.precio, ret.tamano)
    datos = _datos(ctx, ruta=ret.ruta, precio_accion=ret.precio, disponibles=ret.tamano, **_de_veredicto(ver))
    if not ver["entra"]:
        return _sin_compra(ctx, datos)
    if tope_superado(ctx.gasto_tope, ver["coste_nuevo"], ctx.cfg.tope_usd):
        if ctx.tope_por_lo_pagado(ver["coste_nuevo"]):
            return _tope(ctx, datos, ver["coste_nuevo"])     # decisión 50: corte global (también en el intento único)
        if ctx.intento_unico:
            return _sin_compra(ctx, {**datos, "motivo": "tope de gasto en locates (R-H-03)"})
        return _tope(ctx, datos, ver["coste_nuevo"])
    if not ret.ruta.strip() or any(c.isspace() for c in ret.ruta.strip()):
        return _sin_compra(ctx, {**datos, "motivo": "%SLRET sin ruta: no se puede comprar"})
    token = _token_locate(ctx.tokens)
    ruta = ret.ruta.strip()
    return [Anotar(ANOTACION_INTENCION, {**datos, "estado": ESTADO_COMPRANDO, "token": token, "ruta": ruta,
                                         "qty": ver["qty_comprar"], "qty_ajustada": ctx.objetivo(),
                                         "qty_usable": ver["qty_ajustada"], "ultimo_inquire_en": ctx.ahora,
                                         "gasto_en_curso_otros": ctx.gasto_en_curso}),
            LocateComprar(ctx.ticker, ver["qty_comprar"], ruta, token),
            _programar(ctx, COMPRA_SIN_RESPUESTA_S)]


def _sin_compra(ctx: _Contexto, datos: dict, motivo: Optional[str] = None) -> list[Accion]:
    """Un `%SLRET` que no acaba en compra. Fases A/C: se anota y se sigue buscando (lo de siempre). Fases de intento
    único (B, C_piramide; Jaume 29-sep): era LA oportunidad → «parado» para todo el día en la pareja (sin aviso aquí:
    el decisor avisa de la entrada o la pirámide perdida)."""
    if not ctx.intento_unico:
        return [Anotar(ANOTACION_INQUIRE, datos)]
    razon = motivo or datos.get("motivo") or "no compensa"
    extra = {k: v for k, v in datos.items() if k not in ("ticker", "strategy_id", "qty", "qty_ajustada", "qty_pedida",
                                                        "fase", "motivo", "coste_nuevo", "coste_total", "estado")}
    return [_anotar_estado(ctx, ESTADO_PARADO, motivo=f"intento único en la señal sin compra: {razon} (Jaume 29-sep)",
                           **extra),
            Desprogramar(ctx.clave)]


def _compra_sin_respuesta(ctx: _Contexto) -> list[Accion]:
    """E2-04: una compra en «comprando» sin `%SLOrder` que case. Nunca se recompra (riesgo 11).

    La hora de la compra es `ultimo_inquire_en` (la anota la intención). Sin
    ella (tras un reinicio: el diario no la guarda) se empieza a contar desde
    ahora (+ `Programar` de 30 s). Antes de `COMPRA_SIN_RESPUESTA_S` → nada
    (el temporizador de la compra sigue en marcha; cerrojo R-H-02: ni consulta
    ni compra). Pasado → `GET LOCATES` (el barrido puede rescatarla por su
    token) + `Avisar(2)` + «parado» para esta estrategia (un aviso, no uno por
    minuto) + `Desprogramar`. Si luego llega su Located (por token), se
    contabiliza igual: el dinero ya se gastó.
    """
    desde = ctx.loc.ultimo_inquire_en
    if desde is None or ctx.ahora < desde:
        return [Anotar(ANOTACION_INQUIRE, _datos(ctx, ultimo_inquire_en=ctx.ahora,
                                                 motivo="compra en curso sin hora conocida: se cuenta desde ahora (E2-04)")),
                _programar(ctx, COMPRA_SIN_RESPUESTA_S)]
    transcurrido = ctx.ahora - desde
    if transcurrido < COMPRA_SIN_RESPUESTA_S:
        return []
    texto = (f"Locate {_esc(ctx.ticker)} ({_esc(ctx.e.name)}): la compra (token {ctx.loc.token}) lleva {int(transcurrido)} s sin "
             f"respuesta de DAS (%SLOrder). No se recompra; se pide GET LOCATES. Revisar a mano en DAS (R-H-01, H16).")
    return [_anotar_estado(ctx, ESTADO_PARADO, motivo=f"compra sin %SLOrder en {int(COMPRA_SIN_RESPUESTA_S)} s (E2-04)"),
            consulta_locates(),
            Avisar(Nivel.AVISO, Grupo.B, texto, clave=f"locate_sin_respuesta:{ctx.ticker}:{ctx.loc.strategy_id}"),
            Desprogramar(ctx.clave)]


def _fallo_durante_compra(ctx: _Contexto, ret: MsgSLRet) -> list[Accion]:
    """`%SLRET` tipo 2 con SLNEWORDER en curso (L1701-1720): ETB → no_hace_falta; otro fallo → anotar + aviso 2, SIN cambiar de estado.

    No se da la compra por perdida: el `%SLRET` 2 puede ser la respuesta tardía
    de otra ruta a la consulta. Si la compra sale, su Located se contabiliza;
    si no, el locate queda «comprando» (nunca se recompra a ciegas) y el
    humano está avisado. Un `%SLRET` 1 tardío se ignora.
    """
    if ret.tipo != 2 or not _mismo_ticker(ret.ticker, ctx.ticker):
        return []
    if _es_ya_shortable(ret.notas):
        return [_anotar_estado(ctx, ESTADO_NO_HACE_FALTA, motivo="AlreadyShortable (ETB)", notas=ret.notas),
                Desprogramar(ctx.clave)]
    texto = (f"Locate {_esc(ctx.ticker)} ({_esc(ctx.e.name)}): DAS devolvió un fallo con la compra en curso: "
             f"«{_esc(ret.notas)}» (ruta {_esc(ret.ruta)}). Si no llega %SLOrder, revisar a mano (R-H-01, H16).")
    return [Anotar(ANOTACION_ESTADO, _datos(ctx, ruta=ret.ruta, fallo=ret.notas)),
            Avisar(Nivel.AVISO, Grupo.B, texto, clave=f"locate_fallo:{ctx.ticker}:{ctx.loc.strategy_id}")]


def _tras_orden(ctx: _Contexto, orden: MsgSLOrder) -> list[Accion]:
    """`%SLOrder` (manual L1722-1795) de NUESTRA compra: casado por token (o id), deduplicado y con cada estado a su sitio."""
    loc = ctx.loc
    if not _mismo_ticker(orden.ticker, ctx.ticker) or not _es_nuestra(loc, orden):
        return []
    estado_das = _ESTADOS_DAS_CANONICOS.get(orden.estado.strip().lower())
    if ctx.corte and loc.estado in ESTADOS_EN_CURSO:
        return _tras_orden_en_corte(ctx, orden, estado_das)
    if loc.estado not in ESTADOS_EN_CURSO:
        # Compra ya cerrada: lo del id conocido es duplicado o tardío; de otro id propio solo cuenta un Located (dinero gastado).
        if orden.id == loc.id_das or estado_das != ESTADO_LOCALIZADO:
            return []
        return _localizado(ctx, orden, seguir_buscando=False)
    if estado_das in (ESTADO_PENDIENTE, ESTADO_ESPERANDO):
        if loc.estado == estado_das and loc.id_das == orden.id:
            return []
        return [_anotar_estado(ctx, estado_das, id_das=orden.id)]
    if estado_das == ESTADO_OFRECIDO:
        return _oferta(ctx, orden)
    if estado_das == ESTADO_LOCALIZADO:
        return _localizado(ctx, orden, seguir_buscando=True)
    if estado_das in ESTADOS_FALLO_DAS:
        if estado_das in ESTADOS_RECHAZO_RUTA and not ctx.intento_unico and not ctx.fuera_de_hora:
            return _rechazo_sigue_buscando(ctx, orden, estado_das)
        if orden.localizadas > 0:
            # Cerrada con parte localizada: se cobra lo localizado (el dinero ya se gastó) y no se insiste.
            cobro = [a for a in _localizado(ctx, orden, seguir_buscando=False) if not isinstance(a, Desprogramar)]
            return cobro + _parar(ctx, orden, estado_das)
        return _parar(ctx, orden, estado_das)
    return [Anotar(ANOTACION_ESTADO, _datos(ctx, id_das=orden.id, estado_das=orden.estado,
                                           motivo="estado de %SLOrder desconocido: se registra sin cambiar"))]


def _tras_orden_en_corte(ctx: _Contexto, orden: MsgSLOrder, estado_das: Optional[str]) -> list[Accion]:
    """Decisión 50 (Jaume 1-oct): `%SLOrder` de una compra que estaba EN VUELO cuando se cortó el tope del día.

    Pending/Waiting → se anota con su id (el decisor manda `SLCANCELORDER`);
    Offered → `Reject` y parado; Located → se contabiliza (el dinero ya se
    gastó) SIN buscar el resto; Canceled/Rejected/Closed/Declined → parado SIN
    aviso (el aviso del corte es UNO y lo da el decisor), cobrando lo que
    llegara a localizar.
    """
    loc = ctx.loc
    motivo = "corte del tope de locates del día (decisión 50)"
    if estado_das in (ESTADO_PENDIENTE, ESTADO_ESPERANDO):
        if loc.estado == estado_das and loc.id_das == orden.id:
            return []
        return [_anotar_estado(ctx, estado_das, id_das=orden.id)]
    if estado_das == ESTADO_OFRECIDO:
        if loc.estado == ESTADO_OFRECIDO and loc.id_das == orden.id:
            return []                                  # la oferta aceptada antes del corte: la rechaza el decisor
        return [LocateOferta(orden.id, False),
                _anotar_estado(ctx, ESTADO_PARADO, id_das=orden.id, motivo=f"oferta rechazada: {motivo}"),
                Desprogramar(ctx.clave)]
    if estado_das == ESTADO_LOCALIZADO:
        return _localizado(ctx, orden, seguir_buscando=False)
    if estado_das in ESTADOS_FALLO_DAS:
        cobro: list[Accion] = []
        if orden.localizadas > 0:
            cobro = [a for a in _localizado(ctx, orden, seguir_buscando=False) if not isinstance(a, Desprogramar)]
        return cobro + [_anotar_estado(ctx, ESTADO_PARADO, id_das=orden.id, estado_das=estado_das,
                                       motivo=f"%SLOrder {estado_das}: {motivo}", notas=orden.notas),
                        Desprogramar(ctx.clave)]
    return [Anotar(ANOTACION_ESTADO, _datos(ctx, id_das=orden.id, estado_das=orden.estado,
                                           motivo="estado de %SLOrder desconocido: se registra sin cambiar"))]


def _oferta(ctx: _Contexto, orden: MsgSLOrder) -> list[Accion]:
    """`Offered` (ruta tipo 1): Accept SOLO si EV, tope y tamaño siguen bien; si no, Reject y a buscar otra vez (F9)."""
    loc = ctx.loc
    if loc.estado == ESTADO_OFRECIDO:
        if loc.id_das == orden.id:
            return []                                  # la oferta ya aceptada, repetida
        return [LocateOferta(orden.id, False),         # una segunda oferta con otra ya aceptada: nunca dos
                Anotar(ANOTACION_ESTADO, _datos(ctx, id_das_rechazada=orden.id,
                                               motivo="segunda oferta con otra aceptada"))]
    motivo: Optional[str] = None
    datos: dict = {}
    if ctx.fuera_de_hora:
        motivo = "hora límite de intentos (R-H-01.5)"
    elif not _decimal_positivo(ctx.precio):
        motivo = "sin precio de la acción para el EV"
    elif not _decimal_no_negativo(orden.precio):
        motivo = "precio de la oferta no válido"
    else:
        ver = ctx.veredicto(orden.precio, orden.pedidas)
        datos = _de_veredicto(ver, previsto=True)
        if not ver["entra"]:
            motivo = ver["motivo"] or "el EV no compensa el coste total"
        elif orden.pedidas > ver["qty_comprar"]:
            motivo = "la oferta pide más acciones de las decididas"
        elif tope_superado(ctx.gasto_tope, ver["coste_nuevo"], ctx.cfg.tope_usd):
            motivo = "tope de gasto en locates (R-H-03)"
            if ctx.tope_por_lo_pagado(ver["coste_nuevo"]):
                # decisión 50 (Jaume 1-oct): con lo YA PAGADO no cabe → se rechaza y se corta el día (lo hace el decisor)
                return [LocateOferta(orden.id, False)] + _tope(ctx, {**datos, "id_das": orden.id},
                                                                 ver["coste_nuevo"])
    if motivo is None:
        return [_anotar_estado(ctx, ESTADO_OFRECIDO, **{**datos, "id_das": orden.id, "precio_accion": orden.precio}),
                LocateOferta(orden.id, True)]
    if ctx.fuera_de_hora or ctx.intento_unico:          # Jaume 29-sep: en el intento único no hay segunda vuelta
        return [LocateOferta(orden.id, False),
                _anotar_estado(ctx, ESTADO_PARADO, **{**datos, "id_das": orden.id, "motivo": motivo}),
                Desprogramar(ctx.clave)]
    return [LocateOferta(orden.id, False),
            _anotar_estado(ctx, ESTADO_BUSCANDO,
                           **{**datos, "id_das": orden.id, "motivo": f"oferta rechazada: {motivo}"}),
            _programar(ctx, ctx.cfg.intervalo_s)]


def _localizado(ctx: _Contexto, orden: MsgSLOrder, seguir_buscando: bool) -> list[Accion]:
    """Located: se cobra `localizadas · precio` (mínimo de la ruta), EP-9 SLReuseQuery y, si aún falta, R-H-04 parcial."""
    loc = ctx.loc
    if orden.localizadas <= 0:
        return _parar(ctx, orden, ESTADO_LOCALIZADO, motivo="Located sin acciones localizadas")
    precio_accion = orden.precio if _decimal_no_negativo(orden.precio) else loc.precio_accion
    coste_nuevo = Decimal(orden.localizadas) * precio_accion
    if ctx.minimo_cargo is not None and coste_nuevo < ctx.minimo_cargo:
        coste_nuevo = ctx.minimo_cargo
    localizadas = loc.localizadas + orden.localizadas
    libres_despues = ctx.cubiertas() + orden.localizadas
    acciones: list[Accion] = [
        _anotar_estado(ctx, ESTADO_LOCALIZADO, id_das=orden.id, localizadas=localizadas, precio_accion=precio_accion,
                       coste_nuevo=coste_nuevo, coste_total=loc.coste + coste_nuevo, comprado_en=ctx.ahora),
        consulta_reuso(ctx.ticker),
    ]
    pl = precio_accion if precio_accion > 0 else None
    marginal = ctx.marginal(pl)
    falta = _falta_comprable(ctx.objetivo(pl), libres_despues, ctx.cfg.umbral,
                             marginal)     # E2-08 / Jaume 29-sep: un resto que no compensa no se busca
    if not seguir_buscando or falta <= 0 or ctx.fuera_de_hora:
        acciones.append(Desprogramar(ctx.clave))
        return acciones
    qty_consulta = _paquetes_con(falta, ctx.cfg.umbral, marginal)[0] * PAQUETE
    acciones += [
        _anotar_estado(ctx, ESTADO_BUSCANDO, motivo="locate parcial: se busca el resto (R-H-04)",
                       qty_consulta=qty_consulta, ultimo_inquire_en=ctx.ahora),
        LocateInquire(ctx.ticker, qty_consulta, ctx.cfg.ruta),
        _programar(ctx, ctx.cfg.intervalo_s),
    ]
    return acciones


def _parar(ctx: _Contexto, orden: MsgSLOrder, estado_das: str, motivo: Optional[str] = None) -> list[Accion]:
    """Fallo de la ruta (H16 «por definir»): parado + aviso nivel 2 con el texto de DAS; nunca un bucle de recompras (riesgo 11)."""
    motivo = motivo or f"%SLOrder {estado_das}"
    texto = (f"Locate {_esc(ctx.ticker)} ({_esc(ctx.e.name)}): {_esc(motivo)}. Notas de DAS: «{_esc(orden.notas)}». "
             f"Se deja de buscar para esta estrategia (R-H-01, H16).")
    return [_anotar_estado(ctx, ESTADO_PARADO, id_das=orden.id, estado_das=estado_das, motivo=motivo,
                           notas=orden.notas),
            Avisar(Nivel.AVISO, Grupo.B, texto, clave=f"locate_fallo:{ctx.ticker}:{ctx.loc.strategy_id}"),
            Desprogramar(ctx.clave)]


def _rechazo_sigue_buscando(ctx: _Contexto, orden: MsgSLOrder, estado_das: str) -> list[Accion]:
    """Decisión 19 (Jaume 30-sep): Rejected/Declined de la ruta en fase A o C → anotar, aviso 2 y SEGUIR buscando.

    Lo que la orden rechazada llegara a localizar se cobra (el dinero ya se
    gastó). El locate vuelve a «buscando» con `ultimo_inquire_en = ahora`: la
    siguiente consulta sale a los `inquiry_intervalo_s` (3 s), no al instante;
    la compra siguiente pasa otra vez por la intención (cerrojo R-H-02), el EV
    con el coste TOTAL y el tope del 3 %. El aviso lleva la clave
    `locate_rechazo:<ticker>:<estrategia>`: el decisor lo deja salir una vez al día.
    """
    cobro: list[Accion] = []
    if orden.localizadas > 0:
        cobro = [a for a in _localizado(ctx, orden, seguir_buscando=False) if not isinstance(a, Desprogramar)]
    motivo = f"%SLOrder {estado_das}: la ruta rechazó la compra; se sigue buscando (decisión 19, Jaume 30-sep)"
    texto = (f"Locate {_esc(ctx.ticker)} ({_esc(ctx.e.name)}): la ruta rechazó la compra (%SLOrder {_esc(estado_das)}). "
             f"Notas de DAS: «{_esc(orden.notas)}». Se sigue buscando cada {ctx.cfg.intervalo_s:g} s con el protocolo "
             f"de siempre (decisión 19; aviso una vez al día).")
    return cobro + [_anotar_estado(ctx, ESTADO_BUSCANDO, id_das=orden.id, estado_das=estado_das, motivo=motivo,
                                   notas=orden.notas, ultimo_inquire_en=ctx.ahora),
                    Avisar(Nivel.AVISO, Grupo.B, texto,
                           clave=f"{CLAVE_AVISO_RECHAZO}:{ctx.ticker}:{ctx.loc.strategy_id}"),
                    _programar(ctx, ctx.cfg.intervalo_s)]


def _tope(ctx: _Contexto, datos: dict, coste_nuevo: Decimal) -> list[Accion]:
    """R-H-03: no se compra.

    Decisión 60 (Jaume 2-oct): el tope son dólares fijos del cuadro
    (`tope_gasto_dia_usd`); ya no depende del equity. Tope superado con el
    gasto YA PAGADO (`gasto_dia`, que solo sube) → decisión 50 (Jaume 1-oct): «parado» + `Desprogramar` +
    `Anotar("locates_tope_global")`: el decisor corta las compras de TODOS los
    tickers el resto del día, cancela las que estén en vuelo y da UN aviso
    (antes, E2-06, era un aviso por pareja). Superado solo por el coste
    previsto de otras compras EN CURSO (E2-02) → se anota sin aviso y se
    sigue buscando: si alguna falla, el gasto baja y esta puede comprar.
    """
    if not tope_superado(ctx.gasto_dia, coste_nuevo, ctx.cfg.tope_usd):
        return [Anotar(ANOTACION_INQUIRE, {**datos, "gasto_en_curso_otros": ctx.gasto_en_curso, "motivo": (
            "tope de gasto en locates (R-H-03) contando las compras en curso (E2-02): se espera")})]
    # `locate_estado` NO lleva `coste_total`/`coste_nuevo`: el reductor (y el diario) los tomarían como gasto pagado.
    return [_anotar_estado(ctx, ESTADO_PARADO, motivo="tope de gasto en locates (R-H-03, decisión 50)",
                           ruta=datos.get("ruta"), precio_accion=datos.get("precio_accion"),
                           coste_nuevo_previsto=coste_nuevo, gasto_dia=ctx.gasto_dia),
            Desprogramar(ctx.clave),
            Anotar(ANOTACION_TOPE_GLOBAL, {"ticker": ctx.ticker, "strategy_id": ctx.loc.strategy_id,
                                           "gasto_dia": ctx.gasto_dia, "coste_nuevo_previsto": coste_nuevo,
                                           "tope": ctx.cfg.tope_usd,
                                           "motivo": "la compra no cabe en el tope con lo ya pagado",
                                           "regla": "R-H-03 / decisión 50 (Jaume 1-oct)"})]


# ── piezas ────────────────────────────────────────────────────────────
def _datos(ctx: _Contexto, **extra: Any) -> dict:
    """Datos comunes de las anotaciones de locate (§8: ticker dentro de `datos`; Decimal tal cual, el diario los pasa a cadena)."""
    datos = {"ticker": ctx.ticker, "strategy_id": ctx.loc.strategy_id, "qty": ctx.loc.pedidas,
             "qty_ajustada": ctx.objetivo(), "qty_pedida": ctx.loc.pedidas, "fase": ctx.loc.fase}
    datos.update(extra)
    return datos


def _anotar_estado(ctx: _Contexto, estado: str, **extra: Any) -> Anotar:
    return Anotar(ANOTACION_ESTADO, _datos(ctx, estado=estado, **extra))


def _programar(ctx: _Contexto, en_s: float) -> Programar:
    return Programar(ctx.clave, en_s, {"ticker": ctx.ticker, "strategy_id": ctx.loc.strategy_id})


def _de_veredicto(ver: dict, previsto: bool = False) -> dict:
    """El veredicto para el diario (§8). `previsto=True` (anotaciones `locate_estado` que no son Located):
    el coste va como `coste_*_previsto`, porque el reductor del diario toma `coste_total` de un
    `locate_estado` como coste YA pagado y una previsión lo falsearía."""
    sufijo = "_previsto" if previsto else ""
    return {"paquetes": ver["paquetes"], "qty_comprar": ver["qty_comprar"], "qty_usable": ver["qty_ajustada"],
            f"coste_nuevo{sufijo}": ver["coste_nuevo"], f"coste_total{sufijo}": ver["coste_total"],
            "ev_pct": ver["ev_pct"], "fade_pct": ver["fade_pct"], "margen_pct": ver["margen_pct"],
            "ev_origen": ver["ev_origen"], "entra": ver["entra"], "motivo": ver["motivo"]}


def _aplicar_una(loc: Locate, tipo: str, datos: Mapping[str, Any]) -> Locate:
    cambios: dict[str, Any] = {}
    estado_previo = loc.estado
    estado = datos.get("estado")
    if isinstance(estado, str):
        cambios["estado"] = estado
    elif tipo == ANOTACION_INTENCION and loc.estado == ESTADO_BUSCANDO:
        cambios["estado"] = ESTADO_COMPRANDO
    qty = _entero(datos.get("qty_ajustada"))
    if qty is None:
        qty = _entero(datos.get("qty"))
    pedida = _entero(datos.get("qty_pedida"))            # Jaume 29-sep: la N original (la regla marginal la necesita)
    candidatas = [n for n in (qty, pedida) if n is not None]
    if candidatas:
        cambios["pedidas"] = max([loc.pedidas] + candidatas)
    n_nueva = _entero(datos.get("pedidas_n"))           # Jaume 29-sep: N recalculada con el precio actual (manda)
    if n_nueva is not None and n_nueva >= 0:
        cambios["pedidas"] = n_nueva
    fase = datos.get("fase")
    if isinstance(fase, str) and fase in FASES:
        cambios["fase"] = fase
    if "precio_senal" in datos:
        ps = datos.get("precio_senal")
        cambios["precio_senal"] = ps if isinstance(ps, Decimal) and ps.is_finite() and ps > 0 else None
    cambios.update(campos_sin_base(datos))                  # decisión 47 (Jaume 30-sep): fase P
    for campo in ("localizadas", "usadas", "id_das", "token"):
        valor = _entero(datos.get(campo))
        if valor is not None:
            cambios[campo] = valor
    if isinstance(datos.get("precio_accion"), Decimal):
        cambios["precio_accion"] = datos["precio_accion"]
    if isinstance(datos.get("reutilizable"), bool):
        cambios["reutilizable"] = datos["reutilizable"]
    for campo in ("ultimo_inquire_en", "comprado_en"):
        valor = datos.get(campo)
        if isinstance(valor, (int, float)) and not isinstance(valor, bool):
            cambios[campo] = float(valor)
    if tipo != ANOTACION_ESTADO:
        return dataclasses.replace(loc, **cambios)      # inquire/intención: su coste es una PREVISIÓN (el diario lo ignora igual)
    coste_total = datos.get("coste_total") if isinstance(datos.get("coste_total"), Decimal) else None
    if cambios.get("estado", loc.estado) == ESTADO_LOCALIZADO:
        coste_nuevo = datos.get("coste_nuevo") if isinstance(datos.get("coste_nuevo"), Decimal) else _CERO
        cambios["coste"] = coste_total if coste_total is not None else loc.coste + coste_nuevo
        if estado_previo != ESTADO_LOCALIZADO:
            cambios["compras"] = loc.compras + 1
    elif coste_total is not None:
        cambios["coste"] = coste_total
    return dataclasses.replace(loc, **cambios)


def campos_sin_base(datos: Mapping[str, Any]) -> dict[str, Any]:
    """Decisión 47 (Jaume 30-sep): los campos de la fase P de un `locate_estado` (el MISMO reductor para el diario).

    Solo las claves presentes: `stop_perdida` (Decimal > 0, o texto de un
    Decimal tras el JSON del diario; otro valor → None), `senal_perdida`
    (texto no vacío o None) y `piramides_pendientes` (lista de [k, acciones]
    enteros ≥ 0 / > 0; lo que no lo sea se ignora) → tupla de tuplas.
    """
    cambios: dict[str, Any] = {}
    if "stop_perdida" in datos:
        valor = datos.get("stop_perdida")
        stop = _decimal_positivo(valor) if isinstance(valor, (Decimal, str)) else None
        cambios["stop_perdida"] = stop
    if "senal_perdida" in datos:
        sid = datos.get("senal_perdida")
        cambios["senal_perdida"] = sid if isinstance(sid, str) and sid else None
    if "piramides_pendientes" in datos:
        pendientes: list[tuple[int, int]] = []
        for par in datos.get("piramides_pendientes") or ():
            if isinstance(par, (list, tuple)) and len(par) == 2:
                k, n = _entero(par[0]), _entero(par[1])
                if k is not None and n is not None and k >= 0 and n > 0:
                    pendientes.append((k, n))
        cambios["piramides_pendientes"] = tuple(pendientes)
    return cambios


def _libres(loc: Locate) -> int:
    """R-H-04: localizadas − usadas (lo mismo que `entrada._locates_libres`)."""
    return max(0, loc.localizadas - loc.usadas)


def _falta_comprable(objetivo: int, cubiertas: int, umbral_ultimo_pct: Union[Decimal, int, float, str],
                     marginal: Optional[tuple[Decimal, Decimal, Decimal]] = None) -> int:
    """E2-08 (H6 «sobre la suma de cada compra»): lo que falta y merece una compra más.

    El «mínimo un paquete» de `paquetes()` es para posiciones de menos de 100
    acciones SIN nada cubierto. Con acciones ya localizadas, un resto de menos
    de 100 que no compensa no se compra: se opera con lo cubierto (1.220
    localizadas de 1.240 → no se compran 100 para usar 20). «Compensa» es la
    regla MARGINAL (Jaume 29-sep) si se conoce `marginal` = (precio, EV,
    precio del locate); si no, pasar del umbral (30 %).
    """
    falta = max(0, objetivo - cubiertas)
    if falta <= 0 or cubiertas <= 0 or falta >= PAQUETE:
        return falta
    if _ultimo_compensa(falta, de_float(umbral_ultimo_pct), marginal):
        return falta
    return 0


def _umbral(umbral_ultimo_pct: Union[Decimal, int, float, str]) -> Decimal:
    umbral = de_float(umbral_ultimo_pct)
    if umbral < 0 or umbral > _CIEN:
        raise ValueError(f"umbral del último paquete fuera de [0, 100]: {umbral_ultimo_pct!r}")
    return umbral


def _marginal(precio: Optional[Decimal], ev_pct: Optional[Decimal],
              precio_locate: Optional[Decimal]) -> Optional[tuple[Decimal, Decimal, Decimal]]:
    """(precio, EV, precio del locate) para la regla marginal, o None (→ umbral del 30 %) si falta alguno.

    Un valor presente pero imposible (no Decimal finito, precio ≤ 0, locate < 0)
    es un error del llamador: ValueError, nunca una compra por defecto.
    """
    if precio_locate is None or precio is None or ev_pct is None:
        return None
    _exigir_decimal(precio, "precio", positivo=True)
    _exigir_decimal(ev_pct, "ev_pct", permitir_negativo=True)
    _exigir_decimal(precio_locate, "precio_locate")
    return precio, ev_pct, precio_locate


def _ultimo_compensa(extra: int, umbral: Decimal, marginal: Optional[tuple[Decimal, Decimal, Decimal]]) -> bool:
    """¿Se compra un paquete para `extra` (1-99) acciones? Marginal (Jaume 29-sep; el límite exacto compra) o > umbral %."""
    if marginal is None:
        return Decimal(extra) * _CIEN / PAQUETE > umbral
    precio, ev, precio_locate = marginal
    return Decimal(extra) * precio * ev / _CIEN >= Decimal(PAQUETE) * precio_locate


def _paquetes_con(qty: int, umbral: Decimal, marginal: Optional[tuple[Decimal, Decimal, Decimal]]) -> tuple[int, int]:
    """H6 / regla marginal: paquetes completos por lo bajo; el último según `_ultimo_compensa`; mínimo uno (H-7)."""
    if qty <= 0:
        return 0, 0
    completos, resto = divmod(qty, PAQUETE)
    if resto == 0:
        return completos, qty
    if _ultimo_compensa(resto, umbral, marginal):
        return completos + 1, qty
    if completos == 0:
        return 1, qty
    return completos, completos * PAQUETE


def _coste_previsto(loc: Locate, umbral_ultimo_pct: Union[Decimal, int, float, str]) -> Decimal:
    """E2-02: lo que va a cobrar una compra en curso: paquetes de lo que falta · 100 · precio por acción decidido."""
    precio = loc.precio_accion
    if not isinstance(precio, Decimal) or not precio.is_finite() or precio <= 0:
        return _CERO
    objetivo = paquetes(max(0, int(loc.pedidas)), umbral_ultimo_pct)[1]
    falta = _falta_comprable(objetivo, _libres(loc), umbral_ultimo_pct)
    n = paquetes(falta, umbral_ultimo_pct)[0] if falta > 0 else 0
    return Decimal(n * PAQUETE) * precio


def _previsto_en_curso(locates: Optional[Mapping[tuple[str, str], Locate]],
                       umbral_ultimo_pct: Union[Decimal, int, float, str],
                       excluir: Optional[tuple[str, str]] = None) -> Decimal:
    """E2-02: Σ coste previsto de los locates en comprando / Pending / Waiting / Offered (salvo `excluir`)."""
    total = _CERO
    for clave, loc in (locates or {}).items():
        if clave == excluir or not isinstance(loc, Locate) or loc.estado not in ESTADOS_EN_CURSO:
            continue
        total += _coste_previsto(loc, umbral_ultimo_pct)
    return total


def _esc(texto: Any) -> str:
    """D2-08: todo texto variable que va a Telegram (parse_mode HTML) se escapa: un «<» de DAS no pierde el aviso."""
    return html.escape(str(texto), quote=False)


def _es_nuestra(loc: Locate, orden: MsgSLOrder) -> bool:
    """El `%SLOrder` es de ESTA compra: por token si DAS lo trae (el parser solo lo deja si es nuestro y de hoy), si no por id."""
    if orden.token is not None:
        return loc.token is not None and orden.token == loc.token
    return loc.id_das is not None and orden.id == loc.id_das


def _token_locate(tokens: Any) -> int:
    """Token de `Origen.EJECUTOR_LOCATE` (R-A-05, R-K-02): otro origen haría que la reconciliación lo tomara por otra cosa."""
    generar = getattr(tokens, "siguiente", tokens)
    if not callable(generar):
        raise ValueError("tokens debe ser un callable o un GeneradorTokens")
    token = generar()
    partes = descomponer(token)
    if partes is None or partes[0] is not Origen.EJECUTOR_LOCATE:
        raise ValueError(f"el token {token!r} no es de Origen.EJECUTOR_LOCATE")
    return token


def _es_ya_shortable(notas: str) -> bool:
    return _NOTA_YA_SHORTABLE in "".join(str(notas or "").split()).lower()


def _mismo_ticker(a: str, b: str) -> bool:
    return str(a or "").strip().upper() == str(b or "").strip().upper()


def _hora_limite(valor: Any) -> Optional[tuple[int, int]]:
    """`hora_limite_intentos` del cuadro: None (sin límite) o "HH:MM" ET estricto."""
    if valor is None:
        return None
    if not isinstance(valor, str) or not _HHMM.match(valor.strip()):
        raise ValueError(f"hora_limite_intentos debe ser null o \"HH:MM\": {valor!r}")
    horas, minutos = valor.strip().split(":")
    return int(horas), int(minutos)


def _hora_limite_pasada(limite: Optional[tuple[int, int]], ahora_et: Optional[datetime]) -> bool:
    if limite is None:
        return False
    if not isinstance(ahora_et, datetime) or ahora_et.tzinfo is None or ahora_et.utcoffset() is None:
        raise ValueError("con hora_limite_intentos hace falta ahora_et aware (ET)")
    en_et = ahora_et.astimezone(ZoneInfo("America/New_York"))
    return (en_et.hour, en_et.minute) >= limite


def _riesgo_del_nivel(e: EstrategiaConfig, k: int) -> Optional[Decimal]:
    por_nivel = e.riesgos_piramide or []
    if 0 <= k < len(por_nivel):
        valor = _decimal_positivo(por_nivel[k])
        if valor is not None:
            return valor
    return _decimal_positivo(e.riesgo_piramide_usd) or _decimal_positivo(e.riesgo_usd)


def _es_nivel_add(nivel: Any) -> bool:
    return isinstance(nivel, Mapping) and str(nivel.get("action", "add")).lower() != "reduce"


def _valor_decimal(valor: Any, defecto: Decimal) -> Decimal:
    return defecto if valor is None else de_float(valor)


def _decimal_positivo(valor: Any) -> Optional[Decimal]:
    """Decimal finito > 0 desde Decimal/int/float/str; cualquier otra cosa (None, bool, NaN, ≤ 0) → None."""
    if valor is None or isinstance(valor, bool):
        return None
    try:
        numero = valor if isinstance(valor, Decimal) else Decimal(str(valor))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not numero.is_finite() or numero <= 0:
        return None
    return numero


def _decimal_no_negativo(valor: Any) -> bool:
    return isinstance(valor, Decimal) and valor.is_finite() and valor >= 0


def _entero(valor: Any) -> Optional[int]:
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, int):
        return valor
    try:
        return int(str(valor).strip())
    except ValueError:
        return None


def _exigir_int(valor: Any, nombre: str) -> None:
    if type(valor) is not int:
        raise ValueError(f"{nombre} debe ser int, no {valor!r}")


def _exigir_decimal(valor: Any, nombre: str, positivo: bool = False, permitir_negativo: bool = False) -> None:
    if not isinstance(valor, Decimal) or not valor.is_finite():
        raise ValueError(f"{nombre} debe ser un Decimal finito, no {valor!r}")
    if positivo and valor <= 0:
        raise ValueError(f"{nombre} debe ser > 0: {valor}")
    if not permitir_negativo and valor < 0:
        raise ValueError(f"{nombre} no puede ser negativo: {valor}")


def _exigir_ticker(ticker: Any) -> None:
    if not isinstance(ticker, str) or not ticker.strip() or any(c.isspace() for c in ticker):
        raise ValueError(f"ticker no válido: {ticker!r}")
