"""Cisne negro: activación, informe de 16 campos, cadencia, ajuste de los stops y cierre humano.

QUÉ HACE. Las reglas del área G del libro para cuando el precio PASA DE LARGO
el límite de un stop sin llenarlo y quedan acciones cortas al descubierto.
Con el stop único (Jaume 29-sep, R-C-01 v4: UN stop por nivel, disparo en L,
límite L + 50 %) el cisne negro es: el stop del primer nivel con acciones
(el que salta antes) DISPARADO y sin llenar, con el precio por encima de SU
límite. En v3 era el límite de la emergencia (L más alto + 63 %); sin
emergencia, el último límite que protege esas acciones es el de su stop.
  * `se_activa` / `activar`: la condición del protocolo (R-G-01, aclaración
    del 24-sep en R-G-03) y el `EstadoBS` con el que arranca.
  * `toca_informe`, `segundos_hasta_informe`, `registrar_informe`,
    `actualizar_maximo`, `clave_aviso_informe`: la cadencia de R-G-01 v2
    (cada minuto los 5 primeros, luego cada 5 min; `/parar_avisos X BS`
    silencia SOLO ese mensaje) sin mutar el estado.
  * `informe`: el mensaje «Posible BS <TICKER>» con los 16 campos de R-G-01
    (2) en HTML de Telegram (`ETIQUETAS_INFORME`).
  * `acciones_durante_bs`: R-G-03 (1): SOLO se BAJA la cantidad de los
    stops de compra vivos (el de cada nivel y cualquier duplicado, E2-01) a
    las acciones que siguen cortas. Nada más.
  * `al_cerrar`: R-G-01 (3) y el veto de reentrada de R-G-03.
  * `fogonazo_visto`: R-G-01 (4): máximo, duración y devolución para el diario.
  * `cierre_humano`: `/cerrar X SI` y `/cerrar X N SI` durante el protocolo
    (R-G-03 (3) + R-D-06): los stops se cancelan ANTES y se cierra con
    techo del 5 % sobre el ask del momento, con dos reintentos.

POR QUÉ ESTÁ AQUÍ. Es lógica PURA (documento §3.19, flujo F7): sin reloj, sin
I/O, sin logging, sin variables de entorno. Recibe `ahora` (monotónico) y
`ahora_et`/`hora_et` (aware) como parámetros y devuelve acciones de `tipos`
que el decisor (lote G) ejecuta EN ORDEN. Ninguna función muta la posición,
el `EstadoBS` ni las órdenes: las que «cambian» el estado devuelven uno nuevo
(`dataclasses.replace`) y el decisor lo guarda.

LAS TRAMPAS.
  * El bot NO decide en un cisne negro (R-G-01, Jaume 20-sep): ni persigue
    al precio, ni repone un stop si DAS lo cancela, ni mueve su límite o su
    disparo (R-G-03). `acciones_durante_bs` nunca devuelve `EnviarOrden` ni
    `Cancelar`: solo `Reemplazar` de CANTIDAD a la baja de TODA STOPLMTP de
    compra viva (un stop disparado sin llenar con más acciones de las que
    quedan dejaría la cuenta LARGA al volver el precio, E2-01; el `share` sale
    de `tipos.share_de_replace`, A-02) (con su
    `Programar("replace_verificar")`, 2h.8: el REPLACE de un STOPLMTP no
    está documentado) o, si DAS y los fills discrepan, `Consultar("GET
    POSITIONS")` sin tocar nada (riesgo 8: un stop con más acciones que el
    corto real deja la cuenta LARGA). `stops.plan` ya devuelve [] con el
    ticker en `EstadoTicker.BS`.
  * Sin protocolo si los stops cierran TODA la posición (aclaración 24-sep):
    `se_activa` exige −neta > 0 y que el stop que el precio pasó no se haya
    llenado del todo. El `%OrderAct Execute` puede llegar ANTES que los
    `%TRADE` (riesgo 8): ese stop con `llenas` ≥ lo que queda corto significa
    «fills en vuelo», no cisne negro. Solo cuenta el stop del nivel que se
    mira (se reconoce por su disparo): el de un nivel más bajo que llenó
    antes, entero y legítimamente, no tapa el cisne negro del siguiente.
  * Los stops se AJUSTAN a lo que queda corto MENOS lo que ya está
    comprando un cierre humano vivo: si no, un `/cerrar X N SI` en curso y el
    ajuste se pisarían y al volver el precio las dos comprarían encima. Cada
    stop se capa por separado a ese objetivo (como el par de v3): con varios
    niveles la suma puede pasar de lo que queda y, si llenan todos al volver,
    R-C-11 vende el exceso.
  * `Reemplazar` de un stop lleva `serie="stops:X"` y la versión VIGENTE del
    objetivo (`pos.version_stops` o la que pase el decisor): con versión 0 el
    emisor la descartaría en silencio (injerto A §8.6).
  * La cadencia se mide desde el ÚLTIMO informe (el de la activación cuenta
    como el cero) y no dispara antes de tiempo; los avisos periódicos llevan
    una clave DISTINTA cada uno (`bs:X:n`): `avisos.py` deduplica por clave
    en 60 s y con la misma clave un informe a los 60 s justos se perdería.
  * `cierre_humano`: el techo de R-D-06 es 5 % sobre el ASK del momento (no
    sobre el último: en un fogonazo el spread es del 25 %), así que se usa
    `salidas.orden_cierre_posicion`, no `salidas.orden_al_ask` (que limita a
    min(ask, last·1,05) y en un cisne negro no llenaría nunca). Si no hay
    cotización NO se cancela nada: cancelar los stops sin poder comprar
    dejaría la posición desnuda. E2-03: la compra de cierre sale DESPUÉS de
    ver los stops Canceled/Executed (o reducidos), nunca en la misma tanda
    que sus `Cancelar`/`Reemplazar` (esperas de 0,5 s). Con `N` (cierre por tramos, G6)
    los stops NO se cancelan: se bajan a lo que va a quedar, para que el resto
    siga cubierto y ellos no compren también lo que compra el humano. En cada
    reintento las órdenes de cierre vivas se REEMPLAZAN al precio del momento
    (nunca «cancelar + nueva»: la carrera fill↔cancelación compraría de más,
    riesgo 5) y solo se envía orden nueva por lo que no cubren. Un reintento
    nunca cierra en el sentido CONTRARIO al original (si la cuenta quedó
    larga por un fill cruzado, eso es R-C-11, no esto).
  * La neta del cierre es la de fills; si DAS dice otra con el mismo signo se
    cierra la MENOR (quedarse corto sigue avisando por el protocolo; comprar
    de más deja la cuenta larga) y se pide `GET POSITIONS`; si DAS dice plana
    o del otro signo no se envía nada y se avisa nivel 3.
  * Precios siempre `Decimal` (los floats pasan UNA vez por
    `precios.de_float`), acciones `int`; los tiempos son el reloj monotónico
    del proceso (float) y el texto usa formato español.
"""
from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Optional

from app.bot_das.reglas.precios import con_techo, de_float
from app.bot_das.reglas.salidas import ESPERA_REINTENTO_CERRAR_TODO_S, orden_cierre_posicion
from app.bot_das.reglas.stops import (
    CLAVE_SHARE_ES_ABIERTA,
    CLAVE_VERIFICAR_REPLACE,
    COMANDO_POSICIONES,
    ESTADOS_VIVOS,
    VERIFICAR_REPLACE_EN_S,
    conjunto_deseado,
    inferir_proposito,
    serie_stops,
)
from app.bot_das.reloj import ET
from app.bot_das.tipos import (
    BS_CADENCIA_DESPUES_S,
    BS_CADENCIA_INICIAL_S,
    BS_PRIMEROS_INFORMES,
    CERRAR_TODO_REINTENTOS,
    CERRAR_TODO_TECHO_PCT,
    REPLACE_SHARE_ES_ABIERTA,
    share_de_replace,
    Accion,
    Anotar,
    Avisar,
    Cancelar,
    Consultar,
    Cotizacion,
    Cuenta,
    EnviarOrden,
    EstadoBS,
    EstadoLote,
    EstadoOrden,
    EstadoSimbolo,
    EstadoTicker,
    Fill,
    Grupo,
    Lado,
    Nivel,
    NivelesStop,
    Orden,
    PosicionTicker,
    Programar,
    Proposito,
    Reemplazar,
    TipoOrden,
    tick_de,
)

# ── textos y claves públicas (R-G-01) ────────────────────────────────────
TITULO_INFORME = "Posible BS"
# R-G-01 (3). Con el stop único (Jaume 29-sep) ya no hay «stop de emergencia»: la frase se refiere al stop que cerró.
FRASE_EXITO = "POSICIÓN SACADA CON ÉXITO DENTRO DEL MARGEN DEL STOP"
# Los 16 campos de R-G-01 (2) + «datos añadidos» del 20-sep, en el orden en que salen en el mensaje. Con el stop único
# (Jaume 29-sep) los dos primeros son el stop que el precio pasó y el stop de cada nivel (antes: normal y emergencia).
ETIQUETAS_INFORME: tuple[str, ...] = (
    "Stop",                              # el primer stop que salta (disparo y límite): el que el precio ha pasado
    "Stops por nivel",                   # un stop por nivel L (R-C-01 v4): acciones, disparo y límite
    "Precio",                            # precio en el momento del mensaje, y bid / ask
    "Minutos desde el evento",
    "Al descubierto",                    # acciones cortas que no se han podido cerrar
    "Pérdida latente del trade",         # % sobre el trade al precio actual (y $)
    "Pérdida total sobre la cuenta",     # % y $ contando lo ya perdido en los stops
    "Máxima subida vs primer stop",      # para saber ante qué fogonazo estamos
    "Actual vs primer stop",             # el slippage que nos comeríamos si cerramos ahora
    "Pérdida ejecutada",                 # $ y % de lo que sí salió por los stops
    "Halts",                             # SOLO en sesión de mercado: parada, distancia a la banda LULD, k
    "Minutos desde el máximo",
    "Bajando",                           # si lleva N minutos bajando
    "Minutos hasta EOD",                 # de la estrategia
    "Órdenes de stop",                   # siguen vivas, su disparo y su precio límite
    "Comandos",                          # recordatorio de comandos
)
CLAVE_AVISO_BS = "bs"                    # F7: Avisar(3, informe, clave="bs:X") en la activación
CLAVE_INFORME = "bs_informe"             # F7: Temporizador("bs_informe"); el decisor la compone con el ticker
CLAVE_CIERRE_REINTENTO = "bs_cierre"     # R-D-06 aplicado a /cerrar X [N] SI: «bs_cierre:X» con {intento, objetivo, signo, esperas}
ESPERA_CANCEL_S = 0.5                    # E2-03: vuelta de espera hasta ver los stops Canceled/Executed (o reducidos)
ESPERAS_CANCEL_MAX = 6                   # E2-03: 6 × 0,5 s sin confirmación → aviso 3 «cerrar a mano», sin comprar
_ESTADOS_LLENA = (EstadoOrden.EXECUTED,)
_LADOS_VENTA = frozenset({"S", "SS", "SELL", "SHORT", "SHRT"})
_LADOS_COMPRA = frozenset({"B", "BUY"})
_TA_PARADA = frozenset({"H", "P", "Q"})  # E1-05: Q (solo cotización antes del cruce) también es «parada»
_LOTE_MUERTO = (EstadoLote.CERRADO, EstadoLote.CANCELADO)
_HOLGURA_S = 1e-6                        # sumas de floats del reloj monotónico (60.0 puede llegar como 59.99999999)
_CIEN = Decimal("100")
_CERO = Decimal("0")
_SD = "s/d"


# ── activación (R-G-01, R-G-03 aclaración 24-sep) ────────────────────────
def se_activa(pos: PosicionTicker, stops: Optional[NivelesStop], vivas: list[Orden], cot: Optional[Cotizacion],
              cfg_stops: Optional[Mapping] = None) -> bool:
    """R-G-01 v4 / R-G-03 (aclaración 24-sep): ¿arranca el protocolo de cisne negro en este ticker?

    `stops` es el primer stop que salta (Jaume 29-sep, stop único: el del
    nivel más bajo con acciones; lo calcula el decisor con `reglas.stops`).
    True solo si a la vez: (1) el precio (`last`; sin último, el `ask`, que es
    lo que tendría que pagar el stop) está POR ENCIMA de su límite
    (`stops.limite`, L + 50 %): el stop está disparado y ya no puede llenar;
    (2) quedan acciones cortas (−neta de fills > 0); (3) ESE stop no se ha
    llenado del todo: una orden de stop suya (viva o ejecutada, reconocida por
    su disparo ±1 tick) con `llenas` ≥ qty (o Executed) y `llenas` ≥ lo que
    sigue corto son fills en vuelo (riesgo 8), no un cisne negro; y (4) el
    protocolo no está ya activo en el ticker (`pos.bs` o estado BS). No exige
    que el stop exista: sin él y con el precio por encima de su límite la
    posición está igual de descubierta y decide el humano. Sin niveles o sin
    precio → False. `cfg_stops` (opcional sobre §3.19) sirve para reconocer
    con `stops.inferir_proposito` un stop sin etiqueta (el del vigilante).
    """
    if stops is None or pos.bs is not None or pos.estado is EstadoTicker.BS:
        return False
    n = -pos.neta
    if n <= 0:
        return False
    precio = _precio_actual(cot)
    if precio is None or not precio > stops.limite:
        return False
    for o in _stops_de_nivel(pos, vivas, cfg_stops, incluir_ejecutadas=True):
        if not _mismo_disparo(o, stops.disparo):
            continue
        llena = o.estado in _ESTADOS_LLENA or (o.qty > 0 and o.llenas >= o.qty)
        if llena and o.llenas >= n:
            return False
    return True


def activar(pos: PosicionTicker, stops: NivelesStop, ahora: float, precio: Optional[Decimal] = None) -> EstadoBS:
    """R-G-01: estado inicial del protocolo (F7). El decisor lo guarda en `pos.bs` y pone `pos.estado = BS`.

    `primer_stop` = disparo del primer stop que salta (contra el que se miden
    la subida máxima y el slippage del informe); `limite_stop` = su límite (el
    que el precio ha pasado, R-C-01 v4); `max_visto` = el precio de la
    activación (`precio`, opcional sobre §3.19) o, sin él, ese límite (el
    precio ya lo ha pasado). `ultimo_informe = ahora`: el aviso de la
    activación es el informe cero de la cadencia. No muta `pos`.
    """
    base = stops.limite
    valido = _dec(precio)
    maximo = valido if valido is not None and valido > base else base
    return EstadoBS(activado_en=float(ahora), primer_stop=stops.disparo, limite_stop=stops.limite, max_visto=maximo,
                    informes=0, ultimo_informe=float(ahora), silenciado=False, perdido_realizado=_CERO)


def actualizar_maximo(bs: EstadoBS, precio: Optional[Decimal]) -> EstadoBS:
    """R-G-01 (2) «máximo % de subida desde que empezó el movimiento»: devuelve un `EstadoBS` con `max_visto` al día.

    Precio no válido o no mayor → el MISMO objeto (el decisor puede comparar
    por identidad para no anotar nada). Nunca muta `bs`.
    """
    valido = _dec(precio)
    if valido is None or valido <= bs.max_visto:
        return bs
    return replace(bs, max_visto=valido)


# ── cadencia de informes (R-G-01 v2, 22-sep) ─────────────────────────────
def toca_informe(bs: Optional[EstadoBS], ahora: float, cfg_tec: Any) -> bool:
    """R-G-01 v2: cada `cadencia_inicial_s` (60) los `primeros` (5) informes, después cada `cadencia_despues_s` (300).

    Se mide desde el último informe (`ultimo_informe`; el de la activación es
    el cero). Silenciado (`/parar_avisos X BS`) → False: deja de mandar SOLO
    este mensaje; lo demás sigue. Sin protocolo → False. `cfg_tec` es el
    bloque `tecnicos` (o directamente `cisne_negro_informes`, o una `Config`);
    lo que falte sale de `tipos` (riesgo 32).
    """
    if bs is None or bs.silenciado:
        return False
    return ahora - _referencia(bs) >= _intervalo(bs, cfg_tec) - _HOLGURA_S


def segundos_hasta_informe(bs: EstadoBS, ahora: float, cfg_tec: Any) -> float:
    """Para reprogramar `bs_informe` (F7): segundos que faltan para el siguiente informe (≥ 0; 0 = ya toca)."""
    return max(_referencia(bs) + _intervalo(bs, cfg_tec) - ahora, 0.0)


def registrar_informe(bs: EstadoBS, ahora: float) -> EstadoBS:
    """Tras mandar un informe periódico: `informes + 1` y `ultimo_informe = ahora` (nuevo objeto; `bs` no se toca)."""
    return replace(bs, informes=bs.informes + 1, ultimo_informe=float(ahora))


def clave_aviso_informe(ticker: str, n: int) -> str:
    """Clave de dedupe del aviso: «bs:X» para la activación (n = 0, F7) y «bs:X:n» para cada informe periódico.

    Cada informe lleva la suya porque `avisos.py` calla la misma clave durante
    60 s y un informe a los 60 s justos se perdería (ver trampas).
    """
    return f"{CLAVE_AVISO_BS}:{ticker}" if n <= 0 else f"{CLAVE_AVISO_BS}:{ticker}:{n}"


# ── el informe de 16 campos (R-G-01 (2) + datos añadidos del 20-sep) ─────
def informe(pos: PosicionTicker, bs: EstadoBS, stops: NivelesStop, cot: Optional[Cotizacion],
            simb: Optional[EstadoSimbolo], cuenta: Optional[Cuenta], ahora_et: datetime, eod: Optional[datetime],
            franja: str, fills: list[Fill], *, ahora: Optional[float] = None, vivas: Optional[list[Orden]] = None,
            historial: Optional[Sequence[tuple[float, Decimal]]] = None,
            cfg_stops: Optional[Mapping] = None) -> str:
    """R-G-01 (2): el mensaje «Posible BS <TICKER>» con los 16 campos de `ETIQUETAS_INFORME`, en HTML de Telegram.

    El stop que el precio ha pasado (`stops`: disparo y límite) y el stop de
    cada nivel (R-C-01 v4: acciones, disparo y límite, de
    `stops.conjunto_deseado` con la banda de `simb`); precio (último) con bid/ask; minutos desde
    el evento; acciones al descubierto (−neta); pérdida latente del trade (%
    y $ al precio actual sobre el precio medio del corto); pérdida total
    sobre la cuenta (latente + ejecutada, % sobre `cuenta.equity` y $);
    máxima subida y precio actual respecto al PRIMER stop; pérdida ejecutada
    ($ y % de lo que ya salió, contabilidad por coste medio de `fills` desde
    que el ticker estuvo plano; sin fills, `bs.perdido_realizado`); halts
    SOLO en RTH (parada sí/no, distancia a la banda LULD, k del día); minutos
    desde el máximo y si lleva bajando; minutos hasta el EOD de la
    estrategia; estado de las órdenes de stop (vivas, disparo, límite,
    acciones); y el recordatorio de comandos. Lo que no se sabe sale como
    «s/d»: el informe nunca lanza por un dato ausente.
    Parámetros solo por nombre añadidos sobre §3.19 (sin ellos esos campos
    salen «s/d»): `ahora` (monotónico; para los minutos desde el evento y
    desde el máximo; sin él se usa `cot.actualizada_en`), `vivas` (el estado
    de las órdenes de stop), `historial` ([(t_mono, precio)] del movimiento,
    para el momento del máximo) y `cfg_stops` (los stops por nivel y el
    reconocimiento de un stop del vigilante). Todo texto variable va escapado
    (un ticker con «<» rompería el mensaje entero).
    """
    t = html.escape(str(pos.ticker), quote=False)
    precio = _precio_actual(cot)
    bid = _dec(getattr(cot, "bid", None))
    ask = _dec(getattr(cot, "ask", None))
    mono = ahora if ahora is not None else getattr(cot, "actualizada_en", None)
    descubiertas = max(-pos.neta, 0)
    trade = _contabilidad(fills, pos.ticker)
    medio = _precio_medio_corto(pos, trade)
    maximo, t_maximo = _maximo(bs, precio, historial)

    latente_usd: Optional[Decimal] = None
    latente_pct: Optional[Decimal] = None
    if precio is not None and medio is not None:
        latente_usd = (precio - medio) * descubiertas
        latente_pct = (precio - medio) / medio * _CIEN
    if trade.cerradas > 0:
        ejecutada_usd: Optional[Decimal] = -trade.realizado
        ejecutada_pct = (-trade.realizado / trade.base_cerrada * _CIEN) if trade.base_cerrada > 0 else None
    else:
        ejecutada_usd = _dec_o_cero(bs.perdido_realizado)
        ejecutada_pct = None
    total_usd = latente_usd + ejecutada_usd if latente_usd is not None and ejecutada_usd is not None else None
    equity = _dec(getattr(cuenta, "equity", None))
    total_pct = total_usd / equity * _CIEN if total_usd is not None and equity is not None else None

    valores = [
        f"{_fmt_precio(stops.disparo)} (límite {_fmt_precio(stops.limite)})",
        _texto_stops_por_nivel(pos, cfg_stops, simb),
        f"{_fmt_precio(precio)} · bid {_fmt_precio(bid)} / ask {_fmt_precio(ask)}",
        _fmt_min(mono - bs.activado_en) if mono is not None else _SD,
        f"{_fmt_entero(descubiertas)} acciones cortas" + _texto_das(pos),
        f"{_fmt_pct(latente_pct)} ({_fmt_usd(latente_usd)}) sobre el precio medio {_fmt_precio(medio)}",
        f"{_fmt_pct(total_pct)} ({_fmt_usd(total_usd)}), con lo ya perdido en los stops",
        _fmt_pct(_subida(bs.primer_stop, maximo)) + f" (máximo {_fmt_precio(maximo)})",
        _fmt_pct(_subida(bs.primer_stop, precio)),
        f"{_fmt_usd(ejecutada_usd)} · {_fmt_pct(ejecutada_pct)} ({_fmt_entero(trade.cerradas)} acciones ya salieron)",
        _texto_halts(simb, franja, precio),
        _texto_desde_maximo(precio, maximo, mono, t_maximo),
        _texto_bajando(precio, maximo, mono, t_maximo),
        _texto_eod(ahora_et, eod),
        _texto_stops_vivos(pos, vivas, cfg_stops),
        (f"/cerrar {pos.ticker} SI (todo, al ask con techo) · /cerrar {pos.ticker} N SI (solo N) · "
         f"/estado {pos.ticker} · /parar_avisos {pos.ticker} BS · /reanudar_avisos {pos.ticker} BS"),
    ]
    lineas = [f"<b>{TITULO_INFORME} {t}</b>"]
    for etiqueta, valor in zip(ETIQUETAS_INFORME, valores):
        lineas.append(f"<b>{html.escape(etiqueta, quote=False)}:</b> {_escapar_valor(valor)}")
    return "\n".join(lineas)


# ── durante el protocolo (R-G-03) ────────────────────────────────────────
def acciones_durante_bs(pos: PosicionTicker, vivas: list[Orden], cfg: Any, version: int) -> list[Accion]:
    """R-G-03 (1) + R-C-11: SOLO se BAJA la cantidad de los stops de compra vivos a las acciones que siguen cortas.

    Objetivo = −neta (fills) − lo que ya compran los cierres humanos vivos
    del ticker. E2-01: TODA STOPLMTP de COMPRA viva del ticker (el stop de
    cada nivel, también los duplicados, y cualquier otra; de la más antigua a
    la más nueva) con `id_das`, disparo y límite conocidos y más acciones
    vivas que el objetivo → `Reemplazar(share de
    tipos.share_de_replace(objetivo, llenas), mismo disparo, mismo límite,
    version, serie "stops:X")` + `Programar("replace_verificar")` (2h.8). Así
    un stop disparado sin llenar no compra sus 1.000 cuando solo quedan 400
    cortas (la cuenta quedaría LARGA). Nunca `EnviarOrden`, nunca `Cancelar`,
    nunca sube la cantidad, nunca toca el precio ni el disparo (no persigue al
    precio), y NO repone un stop que DAS haya cancelado (R-G-03 (2)). Sin
    corto, objetivo ≤ 0 o nada que bajar → []. Neta de DAS conocida y distinta
    de la de fills → solo `Consultar("GET POSITIONS")` (riesgo 8). `cfg`
    (Config o dict) aporta el interruptor `replace_share_es_abierta` del
    bloque `stops` (A-02); `version` es la versión vigente del objetivo del
    ticker.
    """
    n = -pos.neta
    if n <= 0:
        return []
    if pos.neta_das is not None and pos.neta_das != pos.neta_fills:
        return [Consultar(COMANDO_POSICIONES)]
    objetivo = n - _pendiente_cierre(pos, vivas, signo=-1)
    if objetivo <= 0:
        return []
    stops_vivos = sorted((o for o in _unicas(vivas) if o.ticker == pos.ticker and o.estado in ESTADOS_VIVOS
                          and _es_stop_compra(o)), key=_antiguedad)
    acciones: list[Accion] = []
    for o in stops_vivos:
        viva = _qty_viva(o)
        if viva <= objetivo or o.id_das is None or o.stop is None or o.precio is None:
            continue
        acciones += [Reemplazar(id_das=o.id_das, token=o.token, qty=_share(o, objetivo, cfg), stop=o.stop,
                                precio=o.precio,
                                motivo=(f"R-G-03 (1) / E2-01: {o.proposito.value} de {pos.ticker} a {objetivo} acciones "
                                        f"(tenía {viva})"),
                                version=version, serie=serie_stops(pos.ticker)),
                     Programar(CLAVE_VERIFICAR_REPLACE, VERIFICAR_REPLACE_EN_S,
                               {"token": o.token, "ticker": pos.ticker, "qty_objetivo": objetivo})]
    return acciones


def al_cerrar(pos: PosicionTicker, dentro_del_margen: bool, *,
              texto_informe: Optional[str] = None) -> tuple[Optional[Avisar], bool]:
    """R-G-01 (3) y R-G-03 (reentrada): fin del protocolo. Devuelve (aviso, sin_reentrada_hasta_sigue).

    Sin protocolo activo en el ticker → (None, False): si los stops cerraron
    TODO no hubo cisne negro y el ticker sigue operable (aclaración 24-sep).
    Con protocolo y la posición aún corta → (None, True): el protocolo sigue.
    Con protocolo y la posición cerrada → veto de reentrada hasta `/sigue X`
    (True) y, si cerró un STOP dentro de su límite (`dentro_del_margen`: el
    precio volvió y el stop llenó, R-C-01 v4), `Avisar(3)` con `FRASE_EXITO`
    UNA vez (clave «bs_fin:X»), seguido del mismo informe si se pasa
    `texto_informe` (opcional sobre §3.19). Si cerró de otro modo (el humano)
    → sin aviso.
    """
    if pos.bs is None and pos.estado is not EstadoTicker.BS:
        return None, False
    if pos.neta < 0:
        return None, True
    if not dentro_del_margen:
        return None, True
    t = html.escape(str(pos.ticker), quote=False)
    texto = (f"<b>{FRASE_EXITO}</b> · {t}\n"
             f"Sin reentrada en {t} hasta /sigue {t} (R-G-03).")
    if texto_informe:
        texto = f"{texto}\n\n{texto_informe}"
    return Avisar(nivel=Nivel.MAXIMO, grupo=Grupo.B, texto=texto, clave=f"bs_fin:{pos.ticker}"), True


# ── registro de fogonazos (R-G-01 (4), G10) ──────────────────────────────
def fogonazo_visto(cot_hist: Sequence[tuple[float, Any]], umbral_pct: Any) -> Optional[dict]:
    """R-G-01 (4): ¿hubo un fogonazo en esta ventana? Máximo, duración y devolución para el diario (con o sin posición).

    `cot_hist` = [(t_mono, precio)] (se ordena por tiempo; precios no
    válidos se ignoran); base = el primer precio de la ventana. Hay fogonazo
    si el máximo sube ≥ `umbral_pct` sobre la base. Devuelve {base, maximo,
    subida_pct, t_inicio (primer precio ≥ umbral), t_maximo, t_fin (primer
    precio por debajo del umbral DESPUÉS del máximo; None si sigue arriba),
    duracion_s, ultimo, devolucion_pct (parte del salto devuelta: 100 = ha
    vuelto a la base), sigue_arriba, puntos}; precios y % en `Decimal`,
    tiempos en float. Menos de 2 precios válidos o sin fogonazo → None.
    ValueError si el umbral es negativo o no es un número.
    """
    umbral = de_float(umbral_pct)
    if umbral < 0:
        raise ValueError(f"el umbral de un fogonazo no puede ser negativo: {umbral}")
    puntos: list[tuple[float, Decimal]] = []
    for elemento in cot_hist:
        try:
            t, p = elemento
            momento = float(t)
        except (TypeError, ValueError):
            continue
        valido = _dec(p)
        if valido is not None:
            puntos.append((momento, valido))
    if len(puntos) < 2:
        return None
    puntos.sort(key=lambda par: par[0])
    base = puntos[0][1]
    nivel = base * (_CIEN + umbral) / _CIEN
    i_max = max(range(len(puntos)), key=lambda i: (puntos[i][1], -i))
    t_maximo, maximo = puntos[i_max]
    if maximo < nivel or maximo <= base:
        return None
    t_inicio = next(t for t, p in puntos if p >= nivel)
    t_fin = next((t for t, p in puntos[i_max + 1:] if p < nivel), None)
    t_ultimo, ultimo = puntos[-1]
    return {
        "base": base,
        "maximo": maximo,
        "subida_pct": (maximo - base) / base * _CIEN,
        "t_inicio": t_inicio,
        "t_maximo": t_maximo,
        "t_fin": t_fin,
        "duracion_s": (t_fin if t_fin is not None else t_ultimo) - t_inicio,
        "ultimo": ultimo,
        "devolucion_pct": (maximo - ultimo) / (maximo - base) * _CIEN,
        "sigue_arriba": t_fin is None,
        "puntos": len(puntos),
    }


# ── cierre humano durante el protocolo (R-G-03 (3), R-D-06) ──────────────
def cierre_humano(pos: PosicionTicker, vivas: list[Orden], cot: Optional[Cotizacion], n: Optional[int], cfg: Any,
                  tokens: Callable[[], int], hora_et: datetime, *, intento: int = 0, objetivo: Optional[int] = None,
                  signo: Optional[int] = None, esperas: int = 0) -> list[Accion]:
    """R-G-03 (3) + R-D-06: `/cerrar X SI` (todo) o `/cerrar X N SI` (solo N) durante el protocolo.

    Primera llamada (`intento=0`): cierra `min(N, |neta|)` o todo. Orden de
    las acciones: `Anotar("cierre_humano")`; con discrepancia DAS/fills
    `Consultar("GET POSITIONS")` + `Anotar("discrepancia")`; si es TODO,
    `Cancelar` de los stops de compra PRIMERO y luego del resto de órdenes
    vivas del ticker (para que no compren también, R-G-03 (3), R-C-11); si es
    SOLO N, las STOPLMTP vivas con más acciones que las que van a quedar se
    `Reemplazar`n a esa cantidad (de la más antigua a la más nueva; el resto
    sigue cubierto); después las órdenes de cierre vivas se reemplazan al precio
    del momento y lo que no cubren va en una `EnviarOrden` nueva
    (`salidas.orden_cierre_posicion`: COMPRA con límite ask·(1 + techo),
    techo `salidas.cerrar_todo.techo_pct`, 5 %, ruta cruzar, CIERRE_HUMANO);
    al final `Programar("bs_cierre:X", espera, {ticker, intento + 1,
    objetivo, signo, n})`. Reintentos (`intento` 1..`reintentos`, 2): el
    decisor vuelve a llamar con esos datos; se cierra lo que falte hasta
    `objetivo` (la neta que debe quedar: 0 o la de antes menos N) y solo en
    el sentido original (`signo`). Con `intento > reintentos` no se envía
    nada: `Avisar(3)` con lo que sigue abierto y su precio (decide Jaume).
    Objetivo alcanzado → se cancelan las órdenes de cierre que sigan vivas y
    `Anotar("cierre_humano_fin")`. Sin cotización o con DAS diciendo plana /
    otro signo → NO se cancela nada, `Avisar(3)` y se reprograma. ValueError
    si `n` no es un int > 0, `intento` < 0 u `objetivo` no es int. Parámetros solo por nombre
    añadidos sobre §3.19: `intento`, `objetivo`, `signo` y `esperas`.
    E2-03 (R-G-03 (3) «cancela ANTES … para no comprar de más», riesgo 5): la
    compra de cierre NUNCA sale en la misma tanda que el `Cancelar` de los
    stops (cierre total) o el `Reemplazar` que los baja (cierre de N).
    Mientras quede una orden viva que compraría encima (cierre total: toda
    compra viva del ticker que no es un cierre, con o sin `id_das`; de N: todo
    stop de compra vivo con más acciones que las que van a quedar) se emiten
    sus `Cancelar`/`Reemplazar`, `Anotar("cierre_humano_espera")` y
    `Programar("bs_cierre:X", ESPERA_CANCEL_S, {…, intento (el MISMO),
    esperas + 1})`, sin `EnviarOrden`: la compra sale en la vuelta en que los
    stops ya figuran Canceled/Executed (o reducidos), por la neta de fills de
    ESE momento. Con `esperas` ≥ `ESPERAS_CANCEL_MAX` → `Avisar(3)` «cerrar a
    mano» (clave «…:cancel:agotado») y nada más: el bot no compra a ciegas.
    El decisor devuelve `esperas` de los datos del temporizador.
    """
    if n is not None and (type(n) is not int or n <= 0):
        raise ValueError(f"/cerrar: N debe ser un entero > 0, no {n!r}")
    if type(intento) is not int or intento < 0:
        raise ValueError(f"intento debe ser un entero ≥ 0, no {intento!r}")
    if type(esperas) is not int or esperas < 0:
        raise ValueError(f"esperas debe ser un entero ≥ 0, no {esperas!r}")
    if objetivo is not None and type(objetivo) is not int:
        raise ValueError(f"objetivo debe ser la neta entera que debe quedar, no {objetivo!r}")
    ticker = pos.ticker
    techo, reintentos, espera = _parametros_cierre(cfg)
    ref, discrepa = _neta_de_cierre(pos)
    if signo is None:
        signo = _signo(ref if ref is not None else (pos.neta_fills or pos.neta_das or 0))
    if signo not in (-1, 0, 1):
        raise ValueError(f"signo debe ser −1, 0 o 1, no {signo!r}")
    if objetivo is None and ref is not None and signo != 0 and _signo(ref) == signo:
        q_total = abs(ref)
        objetivo = ref - signo * (q_total if n is None else min(n, q_total))
    q = _por_cerrar(ref, objetivo, signo)
    datos = {"ticker": ticker, "n": n, "intento": intento, "objetivo": objetivo, "signo": signo,
             "neta_fills": pos.neta_fills, "neta_das": pos.neta_das, "por_cerrar": q, "techo_pct": str(techo)}
    acciones: list[Accion] = [Anotar("cierre_humano", datos)]
    if discrepa:
        acciones += [Consultar(COMANDO_POSICIONES),
                     Anotar("discrepancia", {"ticker": ticker, "neta_fills": pos.neta_fills, "neta_das": pos.neta_das,
                                             "origen": "cierre_humano"})]
    cierres = _cierres_vivos(pos, vivas, signo)
    programa = Programar(f"{CLAVE_CIERRE_REINTENTO}:{ticker}", espera,
                         {"ticker": ticker, "intento": intento + 1, "objetivo": objetivo, "signo": signo, "n": n})

    if q == 0:
        acciones += [Cancelar(id_das=o.id_das, token=o.token,
                              motivo=f"R-D-06: cierre de {ticker} ya completado; la orden sobra")
                     for o in cierres if o.id_das is not None]
        acciones.append(Anotar("cierre_humano_fin", {"ticker": ticker, "intento": intento, "objetivo": objetivo}))
        if intento == 0:
            acciones.append(Avisar(nivel=Nivel.INFO, grupo=Grupo.B, clave=f"{CLAVE_CIERRE_REINTENTO}:{ticker}:nada",
                                   texto=f"/cerrar {html.escape(ticker, quote=False)}: no hay posición que cerrar."))
        return acciones
    if intento > reintentos:
        acciones.append(Avisar(nivel=Nivel.MAXIMO, grupo=Grupo.B, clave=f"{CLAVE_CIERRE_REINTENTO}:{ticker}:agotado",
                               texto=_texto_agotado(pos, q, cot, reintentos)))
        return acciones
    if q is None:
        acciones += [Avisar(nivel=Nivel.MAXIMO, grupo=Grupo.B, clave=f"{CLAVE_CIERRE_REINTENTO}:{ticker}:discrepancia",
                            texto=(f"CIERRE {html.escape(ticker, quote=False)} DETENIDO: DAS dice neta {pos.neta_das} y "
                                   f"los fills {pos.neta_fills}; no se envía ni se cancela nada. Comprobar y cerrar a "
                                   f"mano si hace falta (R-D-06, riesgo 8).")),
                     programa]
        return acciones
    limite = _limite_cierre(cot, signo, techo)
    if limite is None:
        acciones += [Avisar(nivel=Nivel.MAXIMO, grupo=Grupo.B, clave=f"{CLAVE_CIERRE_REINTENTO}:{ticker}:sin_cotizacion",
                            texto=(f"CERRAR {html.escape(ticker, quote=False)} A MANO: sin "
                                   f"{'ask' if signo < 0 else 'bid'} en DAS; no se ha cancelado ningún stop ni "
                                   f"enviado nada ({q} acciones por cerrar, R-D-06).")),
                     programa]
        return acciones

    if objetivo == 0:
        previas = _cancelaciones_cierre_total(pos, vivas, cierres, cfg)
        bloqueantes = _bloqueantes_cierre_total(pos, vivas, cierres, signo)
    else:
        previas = _ajustes_cierre_parcial(pos, vivas, abs(objetivo), signo, cfg)
        bloqueantes = _bloqueantes_cierre_parcial(pos, vivas, abs(objetivo), signo)
    if bloqueantes:
        # E2-03 (R-G-03 (3) «cancela ANTES», riesgo 5): la compra de cierre NO sale en la misma tanda que el
        # Cancelar/Reemplazar de los stops: si un stop llenara antes de que DAS procese la cancelación, los dos
        # comprarían y la cuenta quedaría LARGA. Se espera a verlos Canceled/Executed (o reducidos).
        esperando = [o.token for o in bloqueantes]
        if esperas >= ESPERAS_CANCEL_MAX:
            acciones.append(Avisar(
                nivel=Nivel.MAXIMO, grupo=Grupo.B, clave=f"{CLAVE_CIERRE_REINTENTO}:{ticker}:cancel:agotado",
                texto=(f"CIERRE {html.escape(ticker, quote=False)} DETENIDO: DAS no confirma la cancelación (o la "
                       f"reducción) de {len(bloqueantes)} stop(s) de compra tras {esperas} esperas; el bot NO compra "
                       f"para no dejar la cuenta LARGA. {q} acciones por cerrar: revisar en DAS y cerrar A MANO "
                       f"(R-G-03 (3), R-D-06).")))
            acciones.append(Anotar("cierre_humano_espera", {"ticker": ticker, "intento": intento, "esperas": esperas,
                                                            "esperando": esperando, "agotado": True}))
            return acciones
        acciones += previas
        acciones.append(Anotar("cierre_humano_espera", {"ticker": ticker, "intento": intento, "esperas": esperas,
                                                        "esperando": esperando, "regla": "R-G-03 (3) / E2-03"}))
        acciones.append(Programar(f"{CLAVE_CIERRE_REINTENTO}:{ticker}", ESPERA_CANCEL_S,
                                  {"ticker": ticker, "intento": intento, "objetivo": objetivo, "signo": signo, "n": n,
                                   "esperas": esperas + 1}))
        return acciones
    acciones += previas
    restante = q - sum(_qty_viva(o) for o in cierres if o.id_das is None)
    for o in sorted((o for o in cierres if o.id_das is not None), key=_antiguedad):
        viva = _qty_viva(o)
        asignar = min(viva, max(restante, 0))
        if asignar == viva and o.precio == limite:
            restante -= asignar          # ya está como debe: un REPLACE idéntico solo gastaría cuota
            continue
        if asignar <= 0:
            acciones.append(Cancelar(id_das=o.id_das, token=o.token,   # type: ignore[arg-type]
                                     motivo=f"R-D-06: el cierre de {ticker} ya está cubierto por otras órdenes"))
            continue
        acciones.append(Reemplazar(id_das=o.id_das, token=o.token, qty=_share(o, asignar, cfg), stop=None,   # type: ignore[arg-type]
                                   precio=limite,
                                   motivo=f"R-D-06: reintento {intento} de cerrar {ticker} al {techo} % del libro"))
        restante -= asignar
    if restante > 0:
        orden = orden_cierre_posicion(ticker, signo * restante, cot, cfg, tokens, hora_et, techo_pct=techo,
                                      proposito=Proposito.CIERRE_HUMANO, lote_id=None)
        acciones.append(EnviarOrden(orden=orden))
    acciones.append(programa)
    return acciones


# ── ayudantes privados (todos puros) ─────────────────────────────────────
@dataclass(frozen=True)
class _Trade:
    """Contabilidad por coste medio del trade en curso (desde que el ticker estuvo plano por última vez)."""
    neta: int
    medio: Optional[Decimal]
    realizado: Decimal
    cerradas: int
    base_cerrada: Decimal


def _dec(x: Any) -> Optional[Decimal]:
    """`Decimal` finito > 0 (vía `precios.de_float`) o None: None, 0, negativos, NaN, bool y texto no son precios."""
    if x is None:
        return None
    try:
        valor = de_float(x)
    except ValueError:
        return None
    return valor if valor > 0 else None


def _dec_o_cero(x: Any) -> Decimal:
    try:
        return de_float(x) if x is not None else _CERO
    except ValueError:
        return _CERO


def _precio_actual(cot: Optional[Cotizacion]) -> Optional[Decimal]:
    """El último; sin último válido, el ask (lo que pagaría el stop)."""
    precio = _dec(getattr(cot, "last", None))
    return precio if precio is not None else _dec(getattr(cot, "ask", None))


def _signo(x: int) -> int:
    return (x > 0) - (x < 0)


def _bloque_stops(cfg: Any) -> Mapping:
    """Bloque `stops` de una `Config` o de un dict con bloques; un dict sin «stops» se toma como el bloque mismo."""
    if isinstance(cfg, Mapping):
        valor = cfg.get("stops", cfg)
    else:
        valor = getattr(cfg, "stops", None)
    return valor if isinstance(valor, Mapping) else {}


def _bloque(cfg: Any, nombre: str) -> Mapping:
    valor = cfg.get(nombre) if isinstance(cfg, Mapping) else getattr(cfg, nombre, None)
    return valor if isinstance(valor, Mapping) else {}


def _sub(bloque: Mapping, nombre: str) -> Mapping:
    valor = bloque.get(nombre)
    return valor if isinstance(valor, Mapping) else {}


def _cadencias(cfg_tec: Any) -> tuple[int, float, float]:
    """(primeros, cadencia_inicial_s, cadencia_despues_s) del cuadro; lo que falte o no valga, de `tipos`."""
    if isinstance(cfg_tec, Mapping):
        tecnicos = cfg_tec.get("tecnicos")
        bloque = tecnicos if isinstance(tecnicos, Mapping) else cfg_tec
    else:
        bloque = _bloque(cfg_tec, "tecnicos")
    sub = _sub(bloque, "cisne_negro_informes") or bloque
    primeros = sub.get("primeros", BS_PRIMEROS_INFORMES)
    if type(primeros) is not int or primeros < 0:
        primeros = BS_PRIMEROS_INFORMES
    return (primeros, _segundos(sub.get("cadencia_inicial_s"), BS_CADENCIA_INICIAL_S),
            _segundos(sub.get("cadencia_despues_s"), BS_CADENCIA_DESPUES_S))


def _segundos(valor: Any, defecto: float) -> float:
    if valor is None or isinstance(valor, bool):
        return float(defecto)
    try:
        segundos = float(de_float(valor))
    except ValueError:
        return float(defecto)
    return segundos if segundos > 0 else float(defecto)


def _referencia(bs: EstadoBS) -> float:
    return max(float(bs.ultimo_informe), float(bs.activado_en))


def _intervalo(bs: EstadoBS, cfg_tec: Any) -> float:
    primeros, inicial, despues = _cadencias(cfg_tec)
    return inicial if bs.informes < primeros else despues


def _qty_viva(o: Orden) -> int:
    """Acciones que la orden aún puede comprar/vender: `lvqty` si DAS ya lo dijo (Partial/Triggered), si no `qty − llenas`."""
    if o.estado in (EstadoOrden.PARTIAL, EstadoOrden.TRIGGERED) and o.lvqty > 0:
        return max(int(o.lvqty), 0)
    return max(int(o.qty) - int(o.llenas), 0)


def _antiguedad(o: Orden) -> tuple[int, int, float]:
    """La más ANTIGUA primero: con `id_das` por id (servidor) y, sin él (aún Sending), por `enviada_en`."""
    if o.id_das is not None:
        return (0, int(o.id_das), o.enviada_en)
    return (1, 0, o.enviada_en)


def _unicas(vivas: Optional[Sequence[Any]]) -> list[Orden]:
    vistas: set[int] = set()
    unicas: list[Orden] = []
    for o in vivas or ():
        if isinstance(o, Orden) and id(o) not in vistas:
            vistas.add(id(o))
            unicas.append(o)
    return unicas


def _niveles_lotes(pos: PosicionTicker) -> list[Decimal]:
    niveles = {lote.nivel_stop for lote in pos.lotes.values()
               if lote.estado not in _LOTE_MUERTO and _dec(lote.nivel_stop) is not None}
    return sorted(niveles)   # type: ignore[type-var]


def _es_stop_compra(o: Orden) -> bool:
    return o.lado == Lado.COMPRA and o.tipo == TipoOrden.STOP_LIMITE_PP


def _stops_de_nivel(pos: PosicionTicker, vivas: Optional[Sequence[Any]], cfg_stops: Optional[Mapping],
                    incluir_ejecutadas: bool) -> list[Orden]:
    """STOPLMTP de compra del ticker que son el stop de un nivel (R-C-01 v4: propósito STOP, o sin etiqueta —la del
    vigilante— y reconocida como tal), más antigua primero."""
    estados = ESTADOS_VIVOS + (_ESTADOS_LLENA if incluir_ejecutadas else ())
    cfg = cfg_stops if isinstance(cfg_stops, Mapping) else {}
    niveles: Optional[list[Decimal]] = None
    encontradas: list[Orden] = []
    for o in _unicas(vivas):
        if o.ticker != pos.ticker or o.estado not in estados or not _es_stop_compra(o):
            continue
        proposito = o.proposito
        if proposito is Proposito.DESCONOCIDA:
            if niveles is None:
                niveles = _niveles_lotes(pos)
            proposito = inferir_proposito(o, niveles, cfg)
        if proposito is Proposito.STOP:
            encontradas.append(o)
    encontradas.sort(key=_antiguedad)
    return encontradas


def _mismo_disparo(o: Orden, disparo: Decimal) -> bool:
    """El disparo de la orden está a ±1 tick de `disparo` (el tick del precio de referencia): es el stop de ESE nivel."""
    propio = _dec(o.stop)
    referencia = _dec(disparo)
    if propio is None or referencia is None:
        return False
    return abs(propio - referencia) <= tick_de(referencia)


def _cierres_vivos(pos: PosicionTicker, vivas: Optional[Sequence[Any]], signo: int) -> list[Orden]:
    """Órdenes CIERRE_HUMANO vivas del ticker en el lado que cierra (compra si corto, venta si largo)."""
    lado = Lado.COMPRA if signo < 0 else Lado.VENTA
    return [o for o in _unicas(vivas)
            if o.ticker == pos.ticker and o.estado in ESTADOS_VIVOS and o.proposito is Proposito.CIERRE_HUMANO
            and o.lado == lado]


def _pendiente_cierre(pos: PosicionTicker, vivas: Optional[Sequence[Any]], signo: int) -> int:
    return sum(_qty_viva(o) for o in _cierres_vivos(pos, vivas, signo))


def _neta_de_cierre(pos: PosicionTicker) -> tuple[Optional[int], bool]:
    """(neta con la que se cierra, discrepa). Fills; con DAS del mismo signo, la MENOR; plana u otro signo → (None, True)."""
    fills, das = pos.neta_fills, pos.neta_das
    if das is None or das == fills:
        return fills, False
    if fills != 0 and das != 0 and _signo(fills) == _signo(das):
        return (fills if abs(fills) <= abs(das) else das), True
    return None, True


def _por_cerrar(ref: Optional[int], objetivo: Optional[int], signo: int) -> Optional[int]:
    """Acciones que faltan para llegar a `objetivo` cerrando SOLO en el sentido original; None si la neta no es fiable."""
    if ref is None:
        return None
    if signo == 0 or objetivo is None or ref == 0 or _signo(ref) != signo:
        return 0
    return max((objetivo - ref) * -signo, 0)


def _parametros_cierre(cfg: Any) -> tuple[Decimal, int, float]:
    """(techo_pct, reintentos, espera_s) de `salidas.cerrar_todo` (R-D-06); lo que falte, de `tipos`/`salidas`."""
    bloque = _sub(_bloque(cfg, "salidas"), "cerrar_todo")
    valor = bloque.get("techo_pct")
    techo = de_float(valor) if valor is not None else CERRAR_TODO_TECHO_PCT
    if techo < 0:
        raise ValueError(f"cerrar_todo.techo_pct no puede ser negativo: {techo}")
    reintentos = bloque.get("reintentos", CERRAR_TODO_REINTENTOS)
    if type(reintentos) is not int or reintentos < 0:
        raise ValueError(f"cerrar_todo.reintentos debe ser un entero ≥ 0, no {reintentos!r}")
    return techo, reintentos, _segundos(bloque.get("espera_s"), ESPERA_REINTENTO_CERRAR_TODO_S)


def _limite_cierre(cot: Optional[Cotizacion], signo: int, techo: Decimal) -> Optional[Decimal]:
    """R-D-06: ask·(1 + techo) redondeado arriba (corto) o bid·(1 − techo) abajo (largo); None sin ese lado del libro."""
    if signo < 0:
        ask = _dec(getattr(cot, "ask", None))
        return con_techo(ask, techo, arriba=True) if ask is not None else None
    bid = _dec(getattr(cot, "bid", None))
    if bid is None:
        return None
    suelo = con_techo(bid, techo, arriba=False)
    return suelo if suelo > 0 else None


def _cancelaciones_cierre_total(pos: PosicionTicker, vivas: Optional[Sequence[Any]], cierres: list[Orden],
                                cfg: Any) -> list[Accion]:
    """R-G-03 (3): los stops de compra PRIMERO (de la más antigua a la más nueva) y luego el resto de órdenes vivas del ticker
    (salvo los cierres, que se reemplazan). `cfg` se conserva por el contrato (el bloque `stops` ya no hace falta aquí)."""
    ids_cierre = {id(o) for o in cierres}
    stops_vivos = sorted((o for o in _unicas(vivas)
                          if o.ticker == pos.ticker and o.estado in ESTADOS_VIVOS and o.id_das is not None
                          and _es_stop_compra(o) and id(o) not in ids_cierre), key=_antiguedad)
    ids_stops = {id(o) for o in stops_vivos}
    resto = sorted((o for o in _unicas(vivas)
                    if o.ticker == pos.ticker and o.estado in ESTADOS_VIVOS and o.id_das is not None
                    and id(o) not in ids_stops and id(o) not in ids_cierre), key=_antiguedad)
    acciones: list[Accion] = [Cancelar(id_das=o.id_das, token=o.token,   # type: ignore[arg-type]
                                       motivo=(f"R-G-03 (3): /cerrar {pos.ticker} SI: el {o.proposito.value} se cancela "
                                               f"ANTES"))
                              for o in stops_vivos]
    acciones += [Cancelar(id_das=o.id_das, token=o.token,   # type: ignore[arg-type]
                          motivo=f"R-D-06 / R-C-11: /cerrar {pos.ticker} SI: {o.proposito.value} no debe comprar de más")
                 for o in resto]
    return acciones


def _lado_que_cierra(o: Orden, signo: int) -> bool:
    """La orden opera en el MISMO sentido que el cierre: compra si se cierra un corto; venta/corto si un largo."""
    if signo < 0:
        return o.lado == Lado.COMPRA
    return o.lado in (Lado.VENTA, Lado.CORTO)


def _bloqueantes_cierre_total(pos: PosicionTicker, vivas: Optional[Sequence[Any]], cierres: list[Orden],
                              signo: int) -> list[Orden]:
    """E2-03: órdenes vivas del ticker (no cierres) que comprarían (o venderían) ENCIMA del cierre; con o sin id_das."""
    ids_cierre = {id(o) for o in cierres}
    return sorted((o for o in _unicas(vivas)
                   if o.ticker == pos.ticker and o.estado in ESTADOS_VIVOS and id(o) not in ids_cierre
                   and _lado_que_cierra(o, signo) and _qty_viva(o) > 0), key=_antiguedad)


def _bloqueantes_cierre_parcial(pos: PosicionTicker, vivas: Optional[Sequence[Any]], quedan: int,
                                signo: int) -> list[Orden]:
    """E2-03 (cierre de N): stops de compra vivos que aún cubren MÁS de lo que va a quedar (su REPLACE no se ha visto)."""
    if signo >= 0:
        return []
    return sorted((o for o in _unicas(vivas)
                   if o.ticker == pos.ticker and o.estado in ESTADOS_VIVOS and _es_stop_compra(o)
                   and _qty_viva(o) > quedan), key=_antiguedad)


def _share_es_abierta(cfg: Any) -> bool:
    """A-02: `stops.replace_share_es_abierta` si la config lo fija como bool; si no, el defecto de tipos."""
    valor = _bloque_stops(cfg).get(CLAVE_SHARE_ES_ABIERTA)
    return valor if isinstance(valor, bool) else REPLACE_SHARE_ES_ABIERTA


def _share(o: Orden, abierta: int, cfg: Any) -> int:
    """A-02: el `share` de un REPLACE que deja `abierta` acciones vivas (el helper único de tipos)."""
    return share_de_replace(abierta, max(int(o.llenas), 0), _share_es_abierta(cfg))


def _ajustes_cierre_parcial(pos: PosicionTicker, vivas: Optional[Sequence[Any]], quedan: int, signo: int,
                            cfg: Any) -> list[Accion]:
    """`/cerrar X N SI`: ningún stop vivo cubre más de lo que va a quedar, de la más antigua a la más nueva (R-G-03 (1): solo
    cantidad)."""
    if signo >= 0:
        return []
    stops_vivos = sorted((o for o in _unicas(vivas) if o.ticker == pos.ticker and o.estado in ESTADOS_VIVOS
                          and _es_stop_compra(o)), key=_antiguedad)
    acciones: list[Accion] = []
    for o in stops_vivos:
        viva = _qty_viva(o)
        if viva <= quedan or o.id_das is None or o.stop is None or o.precio is None:
            continue
        acciones += [Reemplazar(id_das=o.id_das, token=o.token, qty=_share(o, quedan, cfg), stop=o.stop, precio=o.precio,
                                motivo=(f"R-G-03 (1) / G6: /cerrar {pos.ticker} N SI: {o.proposito.value} a las "
                                        f"{quedan} acciones que quedan (tenía {viva})"),
                                version=pos.version_stops, serie=serie_stops(pos.ticker)),
                     Programar(CLAVE_VERIFICAR_REPLACE, VERIFICAR_REPLACE_EN_S,
                               {"token": o.token, "ticker": pos.ticker, "qty_objetivo": quedan})]
    return acciones


def _texto_agotado(pos: PosicionTicker, q: Optional[int], cot: Optional[Cotizacion], reintentos: int) -> str:
    t = html.escape(str(pos.ticker), quote=False)
    abiertas = "neta no fiable (DAS y fills discrepan)" if q is None else f"{_fmt_entero(q)} acciones sin cerrar"
    return (f"<b>CIERRE {t} AGOTADO</b> tras {reintentos} reintentos: {abiertas}. "
            f"Último {_fmt_precio(_dec(getattr(cot, 'last', None)))} · bid {_fmt_precio(_dec(getattr(cot, 'bid', None)))}"
            f" / ask {_fmt_precio(_dec(getattr(cot, 'ask', None)))}. Decide Jaume (R-D-06).")


def _contabilidad(fills: Optional[Sequence[Any]], ticker: str) -> _Trade:
    """Coste medio sobre los fills del ticker EN EL ORDEN RECIBIDO; se reinicia cada vez que la posición vuelve a 0."""
    neta, medio = 0, _CERO
    realizado, cerradas, base = _CERO, 0, _CERO
    for f in fills or ():
        if not isinstance(f, Fill) or f.ticker != ticker or type(f.qty) is not int or f.qty <= 0:
            continue
        precio = _dec(f.precio)
        lado = str(f.lado).strip().upper()
        if precio is None or lado not in _LADOS_VENTA | _LADOS_COMPRA:
            continue
        sentido = 1 if lado in _LADOS_COMPRA else -1
        qty = f.qty
        if neta == 0:
            realizado, cerradas, base = _CERO, 0, _CERO
            neta, medio = sentido * qty, precio
            continue
        if _signo(neta) == sentido:
            medio = (medio * abs(neta) + precio * qty) / (abs(neta) + qty)
            neta += sentido * qty
            continue
        cierra = min(qty, abs(neta))
        realizado += (medio - precio) * cierra if neta < 0 else (precio - medio) * cierra
        cerradas += cierra
        base += medio * cierra
        neta += sentido * cierra
        sobra = qty - cierra
        if sobra > 0:
            realizado, cerradas, base = _CERO, 0, _CERO
            neta, medio = sentido * sobra, precio
    return _Trade(neta=neta, medio=medio if neta != 0 else None, realizado=realizado, cerradas=cerradas,
                  base_cerrada=base)


def _precio_medio_corto(pos: PosicionTicker, trade: _Trade) -> Optional[Decimal]:
    """Precio medio del corto: el de los fills; si no, el de los lotes ponderado por `llenas`; si no, el de DAS."""
    if trade.neta < 0 and trade.medio is not None:
        return trade.medio
    total, acciones = _CERO, 0
    for lote in pos.lotes.values():
        medio = _dec(lote.precio_medio)
        if (lote.estado in _LOTE_MUERTO or medio is None or type(lote.llenas) is not int or lote.llenas <= 0
                or str(lote.direccion).strip().lower().startswith("long")):
            continue
        total += medio * lote.llenas
        acciones += lote.llenas
    if acciones > 0:
        return total / acciones
    return _dec(pos.avg_das)


def _maximo(bs: EstadoBS, precio: Optional[Decimal],
            historial: Optional[Sequence[tuple[float, Any]]]) -> tuple[Decimal, Optional[float]]:
    """(máximo del movimiento, momento monotónico del máximo si se sabe). El historial manda en el momento."""
    maximo = bs.max_visto
    t_maximo: Optional[float] = None
    for elemento in historial or ():
        try:
            t, p = elemento
            momento = float(t)
        except (TypeError, ValueError):
            continue
        valido = _dec(p)
        if valido is not None and (valido > maximo or (valido == maximo and t_maximo is None)):
            maximo, t_maximo = valido, momento
    if precio is not None and precio > maximo:
        return precio, None
    return maximo, t_maximo


def _subida(desde: Optional[Decimal], hasta: Optional[Decimal]) -> Optional[Decimal]:
    if desde is None or hasta is None or desde <= 0:
        return None
    return (hasta - desde) / desde * _CIEN


def _texto_das(pos: PosicionTicker) -> str:
    if pos.neta_das is None or pos.neta_das == pos.neta_fills:
        return ""
    return f" (DAS dice neta {pos.neta_das}: pendiente de reconciliar)"


def _texto_halts(simb: Optional[EstadoSimbolo], franja: str, precio: Optional[Decimal]) -> str:
    """Solo en sesión de mercado (RTH): parada sí/no, distancia a la banda LULD y halts del día (k)."""
    if not str(franja or "").strip().upper().startswith("RTH"):
        return f"fuera de sesión de mercado ({franja or 's/d'}): no aplica"
    if simb is None:
        return _SD
    parada = "sí" if str(simb.ta or "").strip().upper() in _TA_PARADA else "no"
    banda = _dec(simb.limit_up)
    if banda is None:
        texto_banda = f"banda LULD {_SD}"
    elif precio is None:
        texto_banda = f"banda LULD {_fmt_precio(banda)}"
    else:
        texto_banda = f"banda LULD {_fmt_precio(banda)} (a {_fmt_pct((banda - precio) / precio * _CIEN)})"
    return f"parada: {parada} · {texto_banda} · halts hoy k = {simb.k_halts_up}"


def _texto_desde_maximo(precio: Optional[Decimal], maximo: Decimal, mono: Optional[float],
                        t_maximo: Optional[float]) -> str:
    if precio is not None and precio >= maximo:
        return "0,0 min (en máximos)"
    if mono is None or t_maximo is None:
        return _SD
    return _fmt_min(mono - t_maximo)


def _texto_bajando(precio: Optional[Decimal], maximo: Decimal, mono: Optional[float], t_maximo: Optional[float]) -> str:
    if precio is None:
        return _SD
    if precio >= maximo:
        return "no: en máximos"
    devuelto = f"{_fmt_pct((precio - maximo) / maximo * _CIEN)} desde el máximo"
    if mono is None or t_maximo is None:
        return f"sí ({devuelto}; desde hace {_SD})"
    return f"sí, desde hace {_fmt_min(mono - t_maximo)} ({devuelto})"


def _texto_eod(ahora_et: datetime, eod: Optional[datetime]) -> str:
    if eod is None:
        return _SD
    a = ahora_et if ahora_et.tzinfo is not None else ahora_et.replace(tzinfo=ET)
    e = eod if eod.tzinfo is not None else eod.replace(tzinfo=ET)
    segundos = (e - a).total_seconds()
    if segundos < 0:
        return f"EOD pasado hace {_fmt_min(-segundos)}"
    return f"{_fmt_min(segundos)} (EOD {e.astimezone(ET):%H:%M})"


def _texto_stops_por_nivel(pos: PosicionTicker, cfg_stops: Optional[Mapping], simb: Optional[EstadoSimbolo]) -> str:
    """R-C-01 v4: el stop de cada nivel (acciones, disparo y límite) según `stops.conjunto_deseado` con la banda de `simb`."""
    cfg = cfg_stops if isinstance(cfg_stops, Mapping) else {}
    try:
        deseados = conjunto_deseado(pos, cfg, getattr(simb, "limit_up", None))
    except (TypeError, ValueError):
        return _SD                                   # el informe nunca lanza por un dato raro
    if not deseados:
        return _SD
    return " · ".join(f"{_fmt_entero(d.qty)} a {_fmt_precio(d.disparo)} (límite {_fmt_precio(d.limite)})"
                      for d in deseados)


def _texto_stops_vivos(pos: PosicionTicker, vivas: Optional[list[Orden]], cfg_stops: Optional[Mapping]) -> str:
    """Las órdenes de stop de nivel vivas (R-C-01 v4: una por nivel): estado, disparo, límite y acciones de cada una."""
    if vivas is None:
        return _SD
    vivos = _stops_de_nivel(pos, vivas, cfg_stops, incluir_ejecutadas=False)
    if not vivos:
        return "NINGUNA viva (DAS las canceló o no existen): no se reponen (R-G-03)"
    return " · ".join(f"viva ({o.estado.value}) disparo {_fmt_precio(_dec(o.stop))} límite {_fmt_precio(_dec(o.precio))} "
                      f"{_fmt_entero(_qty_viva(o))} acciones" for o in vivos)


def _escapar_valor(valor: str) -> str:
    return html.escape(valor, quote=False)


def _fmt_numero(valor: Decimal, decimales: int) -> str:
    """Formato español (miles con punto, decimales con coma); nunca notación científica."""
    texto = f"{valor:,.{decimales}f}"
    return texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _fmt_precio(precio: Optional[Decimal]) -> str:
    """Con los decimales de su tick (regla 612): 2 si ≥ 1 $, 4 si < 1 $; None → «s/d»."""
    if precio is None:
        return _SD
    return _fmt_numero(precio, 2 if abs(precio) >= 1 else 4)


def _fmt_pct(valor: Optional[Decimal]) -> str:
    if valor is None:
        return _SD
    signo = "+" if valor > 0 else ""
    return f"{signo}{_fmt_numero(valor, 1)} %"


def _fmt_usd(valor: Optional[Decimal]) -> str:
    return _SD if valor is None else f"{_fmt_numero(valor, 2)} $"


def _fmt_entero(valor: int) -> str:
    return _fmt_numero(Decimal(int(valor)), 0)


def _fmt_min(segundos: float) -> str:
    return f"{_fmt_numero(Decimal(str(round(max(float(segundos), 0.0) / 60.0, 1))), 1)} min"
