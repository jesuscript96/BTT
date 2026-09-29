"""Halts: k, banda, decisión de reapertura, OPEN un minuto antes con guardia, PM y T1/T12.

QUÉ HACE. Las reglas del área F del libro (R-F-01..R-F-06), el aviso de halt
(R-G-02) y la cancelación de entradas vivas al parar (B18 / R-F-04 a), como
funciones PURAS: reciben el estado del símbolo (`EstadoSimbolo`, que rellena
`mercado_das.py` con `$IssueStatus`/`$LDLU`), la posición, la cotización, los
niveles de stop YA calculados (`NivelesStop`, ajuste (a): aquí no se importa
`reglas.stops`), la franja de mercado y la hora ET, y devuelven acciones o
una decisión de texto. `momento_envio_open` + `debe_enviar_open` son el
injerto A §8.23: la orden a mercado por la ruta OPEN se envía UN minuto antes
del fin previsto del halt y solo una vez aunque `$IssueStatus` se repita.

POR QUÉ ESTÁ AQUÍ. El decisor (lote G) es el único que muta `EstadoBot`; la
lógica de halts se prueba con tablas de casos (k = 1/2/3 × stop encima/debajo
× PM/RTH × primera vela </≥ 6 %) sin DAS ni reloj. Todo lo que necesita
tiempo llega como parámetro (`ahora_et`, `duracion_min`, `hora_et`).

LAS TRAMPAS.
  * DAS no dice si un halt es LULD, T1 o T12: solo `TA:H` (halted) o `TA:P`
    (paused, la pausa de volatilidad LULD de 5 min, manual L1128-1133). Aquí
    `P` = LULD (manda k, sin tope de subida) y `H` = T1/T12 u otro (aplica el
    tope del 250 % de R-F-05 y, por duración, el T12 pasa a control humano).
  * `fin_previsto` solo existe para `P` (TAT + 5 min). Si la bolsa extiende la
    pausa otros 5 min, el fin queda en el pasado: `momento_envio_open` devuelve
    0 (= ahora) y la orden espera en DAS al cruce de reapertura (riesgo 27).
  * `debe_enviar_open` exige además que el símbolo SIGA en halt: si ya reabrió,
    una MKT por OPEN no entra en ningún cruce; la salida va entonces por la
    ruta de cruzar (F6.2 «reintento al reabrir por ruta cruzar al ask»). Es
    también la segunda red contra la DOBLE salida: la reapertura borra
    `orden_open_enviada` y, si el fill de la primera MKT aún no ha llegado,
    una segunda MKT dejaría la cuenta del otro lado (riesgo 6 y 27).
  * `TA` se compara normalizado (sin espacios, en mayúsculas): el parser lo
    deja tal cual llega del socket. `Q` («quotation resumed», manual
    L1113-1124) es todavía PARADO (E1-05): solo cotiza antes del cruce de
    reapertura; se reabre con `T` o sin TA. R2-DEC-3: si DAS no manda el `T`,
    `MercadoDAS` da el símbolo por reabierto con prints nuevos 5 s seguidos en
    `Q` y le quita el TA (aquí se ve como «se negocia»).
  * E1-01: en un halt que NO es LULD (`H`/`Q`) el `last` durante el halt es el
    print de ANTES de parar, así que la subida medida sale ~0 % y el tope del
    250 % de R-F-05 no se puede medir al decidir. Por eso la salida por OPEN
    no es una MKT sin tope: es un LÍMITE a `precio_parada · (1 + t1/100)`
    redondeado abajo (si reabre por encima, no llena y decide el humano). Lo
    mismo capa el límite del reintento. `tope_t1_superado` es la función ÚNICA
    que el decisor usa al reabrir con el precio real (E1-02).
  * E1-04 (R-F-06, 2.ª parte): en un halt `H` de premercado con decisión
    «mantener», `ensanchar_stops_pm` REEMPLAZA el límite de los stops de compra
    residentes por `con_techo(disparo, margen_limite_pm_pct)` (nunca lo baja,
    nunca mueve el disparo): remueve más liquidez al reabrir. Con el stop
    único (Jaume 29-sep, R-C-01 v4: límite L + 50 %) el límite ya es mucho
    más ancho que el 5 % y el ensanche NO cambia nada en los stops de nivel;
    se conserva como red para un stop de compra con un límite más estrecho
    (una protección o una orden adoptada puesta con otra config).
  * En premercado no hay órdenes a mercado (R-F-06): `decidir_reapertura`
    devuelve «cerrar_limite_pm» en cualquier franja que no sea RTH, y
    `orden_reapertura` pone un LÍMITE que cruza el ask con margen y TIF DAY+.
  * Sin precio de referencia (ni last ni precio de parada) no se decide a
    ciegas: «control_humano». Sin precio de parada no se puede medir el +250 %
    de T1 y prima cerrar (los stops residentes no cubren un hueco de +250 %).
  * `cerca_de_banda` se evalúa con k == k_max − 1 (2 con los defectos): con
    k_max = 2 configurado, el «evitar el siguiente halt» sería en k = 1.
  * Todo precio es `Decimal`; los porcentajes de la config (floats del JSON)
    pasan por `precios.de_float` una vez.
"""
from __future__ import annotations

import html
from collections.abc import Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Optional

from app.bot_das.reglas.precios import con_techo, de_float, ruta, subida_pct
from app.bot_das.reloj import ET, hora_das_a_et
from app.bot_das.tipos import (
    HALT_DISTANCIA_BANDA_K2_PCT,
    HALT_ENVIAR_ANTES_FIN_S,
    HALT_K_MAX,
    HALT_PRIMERA_VELA_MAX_PCT,
    HALT_T1_SUBIDA_MAX_PCT,
    REPLACE_SHARE_ES_ABIERTA,
    Accion,
    Anotar,
    Avisar,
    Cancelar,
    Cotizacion,
    EstadoLote,
    EstadoOrden,
    EstadoSimbolo,
    Grupo,
    Lado,
    Nivel,
    NivelesStop,
    Orden,
    OrdenNueva,
    PosicionTicker,
    Programar,
    Proposito,
    Reemplazar,
    Senal,
    TipoOrden,
    al_tick,
    share_de_replace,
)

DECISIONES = ("mantener", "cerrar_mercado", "cerrar_limite_pm", "control_humano")
PAUSA_LULD_MIN = 5              # manual L1128-1130: «If TA is P, the trading pause will be 5 minutes»
T12_MIN_DEFECTO = 240           # halts.t12_min del cuadro: se valida pero YA NO decide (Jaume 28-sep: T1 y T12, mismo protocolo)
MARGEN_LIMITE_PM_PCT_DEFECTO = Decimal("5")   # §7 halts.margen_limite_pm_pct (R-F-06: límite que remueve liquidez)
TA_PARADO = ("H", "P", "Q")     # E1-05: Q = solo cotiza antes del cruce; reabre con T, sin TA o por prints (R2-DEC-3)
ANOTACION_STOPS_PM = "halt_stops_pm"          # E1-04: el diario registra el ensanche de los stops en premercado
# E1-04: la serie/versión y la clave del temporizador son las MISMAS cadenas que usa el módulo de stops
# (ajuste (a): aquí no se importa); un test comprueba que coinciden.
_SERIE_STOPS = "stops:{}"
_CLAVE_VERIFICAR_REPLACE = "replace_verificar"
_VERIFICAR_REPLACE_EN_S = 1.0
_CLAVE_SHARE_ES_ABIERTA = "replace_share_es_abierta"
_CIEN = Decimal("100")
_PROPOSITOS_ENTRADA = (Proposito.ENTRADA_AGREGAR, Proposito.ENTRADA_CRUCE)
_ESTADOS_MUERTOS = (EstadoOrden.CANCELED, EstadoOrden.REJECTED, EstadoOrden.EXECUTED, EstadoOrden.CLOSED)
_ESTADOS_VIVOS = (EstadoOrden.SENDING, EstadoOrden.ACCEPTED, EstadoOrden.PARTIAL, EstadoOrden.HOLD,
                  EstadoOrden.TRIGGERED)
_LOTES_VIVOS = (EstadoLote.ABRIENDO, EstadoLote.ABIERTO, EstadoLote.CERRANDO)


# ── estado del halt ─────────────────────────────────────────────────────
def es_halt(simb: EstadoSimbolo) -> bool:
    """True si el símbolo está parado: TA ∈ {H, P, Q} (manual L1113-1124; sin TA o T = se negocia o reabre).

    E1-05: `Q` (quotation resumed) es el periodo de solo cotización antes del
    cruce de reapertura: todavía no se negocia y el `last` es el de antes de
    parar. Una orden por OPEN en `Q` entra en ese cruce.
    """
    return _ta(simb) in TA_PARADO


def es_luld(simb: EstadoSimbolo) -> bool:
    """True si el halt es una pausa de volatilidad LULD (`TA:P`, manual L1128): en ella manda k (R-F-01), no el tope de T1."""
    return _ta(simb) == "P"


def tipo_halt(simb: EstadoSimbolo, franja: str) -> str:
    """Texto del tipo de halt para R-G-02 («tipo de halt si se conoce»): LULD por `P`; con `H` DAS no distingue T1/T12."""
    ta = _ta(simb)
    if ta == "P":
        return "LULD (pausa de volatilidad)"
    if ta == "H":
        return "H en premercado (T1/T12, sin LULD)" if _es_premercado(franja) else "H (T1/T12: DAS no lo distingue)"
    if ta == "Q":
        return "Q (solo cotización: cruce de reapertura inminente)"
    return "desconocido"


def fin_previsto(simb: EstadoSimbolo, ahora_et: datetime) -> Optional[datetime]:
    """Fin previsto del halt: `P` → TAT + 5 min como datetime ET del día de `ahora_et` (manual L1128-1130); `H` → None.

    Sin TAT o con TAT mal formado no hay hora (None): `momento_envio_open`
    tratará el fin como desconocido y la orden saldrá al decidir.
    """
    if _ta(simb) != "P" or not simb.tat:
        return None
    try:
        inicio = hora_das_a_et(simb.tat.strip(), _a_et(ahora_et).date())
    except ValueError:
        return None
    return inicio + timedelta(minutes=PAUSA_LULD_MIN)


# ── al entrar en halt (B18 / R-F-04 a + R-G-02) ─────────────────────────
def al_entrar_en_halt(pos: PosicionTicker, vivas: list[Orden], simb: EstadoSimbolo,
                      cot: Optional[Cotizacion], franja: str) -> list[Accion]:
    """Acciones al detectar el halt: `Cancelar` cada entrada viva (B18, R-F-04 a), `Anotar("halt")` y `Avisar(2)` (R-G-02).

    Orden de las acciones: primero los `Cancelar` (el dinero antes que el
    papel), luego `Anotar` (campos de §8: ta, tat, k, precio_parada,
    decision = None, fin_previsto) y por último `Avisar`. Solo se cancelan órdenes con propósito ENTRADA_* del ticker y con `id_das`
    conocido (sin id no hay `CANCEL`; van en el diario como `sin_id` y el
    decisor las trata al llegar su `%ORDER`). Los stops NO se tocan: deben
    seguir residentes en DAS durante el halt (R-C-01). El aviso lleva ticker,
    tipo, hora, precio de parada, posición, stop, k y, en sesión, las bandas
    LULD. Al reabrir, el segundo aviso lo emite el decisor (F6.3).
    """
    acciones: list[Accion] = []
    canceladas: list[int] = []
    sin_id: list[int] = []
    for orden in vivas:
        if orden.ticker != pos.ticker or orden.proposito not in _PROPOSITOS_ENTRADA:
            continue
        if orden.estado in _ESTADOS_MUERTOS:
            continue
        if orden.id_das is None:
            sin_id.append(orden.token)
            continue
        acciones.append(Cancelar(id_das=orden.id_das, token=orden.token,
                                 motivo=f"halt en {pos.ticker}: entrada viva cancelada (B18, R-F-04 a)"))
        canceladas.append(orden.token)
    precio_parada = simb.precio_parada if simb.precio_parada is not None else (cot.last if cot is not None else None)
    niveles = _niveles_stop_lotes(pos)
    fin = fin_previsto(simb, simb.halt_desde) if simb.halt_desde is not None else None
    datos = {
        "ticker": pos.ticker,
        "ta": simb.ta,
        "tat": simb.tat,
        "tipo": tipo_halt(simb, franja),
        "franja": franja,
        "precio_parada": _txt(precio_parada),
        "neta": pos.neta,
        "lotes": {lid: lote.llenas for lid, lote in pos.lotes.items() if lote.estado in _LOTES_VIVOS},
        "niveles_stop": [_txt(n) for n in niveles],
        "k": simb.k_halts_up,
        "fin_previsto": fin.isoformat() if fin is not None else None,
        "decision": None,                    # §8: la decisión llega con `halt_decidir`, no al parar
        "limit_down": _txt(simb.limit_down),
        "limit_up": _txt(simb.limit_up),
        "entradas_canceladas": canceladas,
        "entradas_sin_id": sin_id,
        "estado_ticker": pos.estado.value,
    }
    acciones.append(Anotar("halt", datos))
    acciones.append(Avisar(Nivel.AVISO, Grupo.B, texto_halt(pos, simb, franja, precio_parada, niveles, canceladas),
                           clave=f"halt:{pos.ticker}:{_marca_halt(simb)}"))
    return acciones


def texto_halt(pos: PosicionTicker, simb: EstadoSimbolo, franja: str, precio_parada: Optional[Decimal],
               niveles: list[Decimal], canceladas: list[int]) -> str:
    """Mensaje breve de R-G-02: ticker, tipo, hora, precio de parada, posición y stop, k y bandas LULD si es en sesión."""
    partes = [f"HALT {pos.ticker}", tipo_halt(simb, franja), f"hora {simb.tat or '?'}",
              f"parada {_txt(precio_parada) or '?'}", f"posición {pos.neta:+d}",
              f"stop {'/'.join(_txt(n) for n in niveles) if niveles else 'sin lotes'}",
              f"k={simb.k_halts_up}"]
    if _es_rth(franja):
        partes.append(f"bandas LULD {_txt(simb.limit_down) or '?'}-{_txt(simb.limit_up) or '?'}")
    partes.append(franja)
    if canceladas:
        partes.append(f"entradas canceladas: {len(canceladas)} (B18)")
    return html.escape(" · ".join(partes), quote=False)   # D2-08: va a Telegram con parse_mode HTML


# ── decisión de reapertura (R-F-01, R-F-05, R-F-06) ──────────────────────
def decidir_reapertura(pos: PosicionTicker, simb: EstadoSimbolo, stops: Optional[NivelesStop],
                       cot: Optional[Cotizacion], cfg_halts: dict, franja: str, duracion_min: float) -> str:
    """«mantener» | «cerrar_mercado» | «cerrar_limite_pm» | «control_humano» según la matriz de §3.18.

    Orden de comprobación:
      0. Sin posición (neta 0) → mantener: no hay nada que decidir (ni que pasar a un humano).
      1. (Jaume 28-sep) T1 y T12 llevan el MISMO protocolo: la duración del halt no decide nada (antes, > `t12_min`
         pasaba a control humano). Al reabrir, lo único que importa es el precio de reapertura frente al stop y al tope.
      2. Precio de referencia = último conocido (`cot.last`) o el precio de parada; sin ninguno, o sin
         niveles de stop con los que comparar (`stops` None), → control_humano (no se decide a ciegas).
      3. Escenario 1 (R-F-01): el primer stop (el del nivel más bajo) queda POR ENCIMA del precio (corto) → mantener
         si k < k_max; k ≥ k_max → cerrar. Escenario 2: stop por debajo (o igual) → cerrar sí o sí.
      4. Al cerrar en un halt que NO es LULD (`TA:H`), R-F-05 a: subida desde el precio de parada > 250 % →
         control_humano (alerta máxima; en LULD no hay tope: manda k). Sin precio de parada no se puede medir y
         prima cerrar.
      5. «cerrar» es cerrar_mercado en RTH y cerrar_limite_pm en cualquier otra franja (R-F-06: en PM no hay MKT).
    Para una neta LARGA la comparación con el stop se refleja (stop por debajo).
    `stops` son el disparo y el límite del stop que primero se cruzaría (R-C-01 v4, stop único: con varios lotes, el
    del L más bajo): los pasa el decisor ya calculados por `reglas.stops` (ajuste (a): aquí no se importa
    `reglas.stops`). Si el símbolo
    ya reabrió (`ta` fuera de {H, P}) no se sabe si el halt fue LULD o T1: el tope del 250 % se aplica igualmente,
    que es lo conservador (un humano decide con los stops residentes).
    """
    if pos.neta == 0:
        return "mantener"
    _cfg_float(cfg_halts, "t12_min", float(T12_MIN_DEFECTO))     # solo valida el cuadro; no decide (Jaume 28-sep)
    precio = _precio_ultimo(cot, simb)
    if precio is None or stops is None:
        return "control_humano"
    corto = pos.neta < 0
    stop_salvo = (precio < stops.disparo) if corto else (precio > stops.disparo)
    k_max = _cfg_int(cfg_halts, "k_max", HALT_K_MAX)
    if stop_salvo and simb.k_halts_up < k_max:
        return "mantener"
    if tope_t1_superado(simb, precio, cfg_halts):
        return "control_humano"
    return "cerrar_mercado" if _es_rth(franja) else "cerrar_limite_pm"


def tope_t1_superado(simb: EstadoSimbolo, precio_reapertura: Optional[Decimal], cfg_halts: Any,
                     luld: Optional[bool] = None) -> bool:
    """E1-01 / E1-02 (R-F-05 a): ¿la subida desde el precio de parada supera `t1_subida_max_cierre_pct` (250 %)?

    Función ÚNICA para los dos sitios: al decidir durante el halt y, sobre
    todo, al REABRIR con el precio real (el decisor la llama antes del
    reintento con el `last` de la reapertura; True → control humano, aviso
    máximo, ninguna orden). En LULD no hay tope (manda k) → False. `luld` None
    → se deduce del TA actual; si el símbolo ya reabrió (TA T o ausente) no se
    sabe si fue LULD y se aplica el tope, que es lo conservador (el decisor
    puede pasar `luld` con el TA con el que paró, `MercadoDAS.ta_ultimo_halt`).
    Sin precio de parada o sin precio de reapertura válidos no se puede medir
    → False (prima cerrar: los stops residentes no cubren un hueco así).
    Estricto: 250 % exacto NO supera. `cfg_halts` es el bloque «halts» (o la
    `Config` / un dict con «halts»).
    """
    if luld is None:
        luld = es_luld(simb)
    if luld:
        return False
    parada = simb.precio_parada
    if parada is None or not parada.is_finite() or parada <= 0:
        return False
    if precio_reapertura is None or not precio_reapertura.is_finite() or precio_reapertura <= 0:
        return False
    tope = _cfg_decimal(_bloque_halts(cfg_halts), "t1_subida_max_cierre_pct", HALT_T1_SUBIDA_MAX_PCT)
    return subida_pct(parada, precio_reapertura) > tope


def precio_tope_t1(simb: EstadoSimbolo, cfg_halts: Any) -> Optional[Decimal]:
    """E1-01: `precio_parada · (1 + t1_subida_max_cierre_pct / 100)` redondeado ABAJO al tick; None si no aplica.

    No aplica (None) en LULD (`P`: manda k, sin tope) ni sin precio de parada
    válido. Es el límite máximo que paga una salida de un halt H/Q: por
    encima, R-F-05 manda control humano.
    """
    if es_luld(simb):
        return None
    parada = simb.precio_parada
    if parada is None or not parada.is_finite() or parada <= 0:
        return None
    tope = _cfg_decimal(_bloque_halts(cfg_halts), "t1_subida_max_cierre_pct", HALT_T1_SUBIDA_MAX_PCT)
    return al_tick(parada * (_CIEN + tope) / _CIEN, arriba=False)


def cerca_de_banda(cot: Optional[Cotizacion], simb: EstadoSimbolo, k: int, cfg_halts: dict) -> bool:
    """R-F-01: con k = k_max − 1 (2) y el ask a ≤ `distancia_banda_k2_pct` (4 %) del limit up → salir a mercado ANTES de que pare.

    False sin ask, sin banda, con k distinto o si el símbolo ya está parado
    (entonces decide `decidir_reapertura`). La orden la construye el decisor por
    la ruta de cruzar con propósito HALT_BANDA.
    """
    if cot is None or cot.ask is None or cot.ask <= 0 or simb.limit_up is None or simb.limit_up <= 0:
        return False
    if es_halt(simb) or k != _cfg_int(cfg_halts, "k_max", HALT_K_MAX) - 1:
        return False
    distancia = _cfg_decimal(cfg_halts, "distancia_banda_k2_pct", HALT_DISTANCIA_BANDA_K2_PCT)
    return cot.ask >= simb.limit_up * (_CIEN - distancia) / _CIEN


def orden_reapertura(pos: PosicionTicker, qty: int, cot: Optional[Cotizacion], decision: str, cfg: Any,
                     token: int, hora_et: datetime, *, simb: Optional[EstadoSimbolo] = None) -> OrdenNueva:
    """La orden de salida del halt (EP-2 / R-F-06 / R-F-05).

    «cerrar_mercado» → compra (cubre el corto) por la ruta `rutas.halt` (OPEN,
    Sage 24-sep) con propósito HALT_OPEN: a MERCADO en una pausa LULD (`P`) y,
    con `simb` (solo por nombre, E1-01) de un halt que NO es LULD (`H`/`Q`, o ya
    reabierto) y con precio de parada, un LÍMITE a `precio_tope_t1` (parada ·
    3,5 redondeado abajo): durante el halt el `last` es el de antes de parar y
    el 250 % no se puede medir; si reabre por encima, la orden no llena y el
    decisor pasa a control humano (`tope_t1_superado`). «cerrar_limite_pm» →
    LÍMITE que cruza el ask con `halts.margen_limite_pm_pct` (redondeado al lado
    que llena) por la ruta de cruzar de la tabla, TIF DAY+, propósito
    HALT_PM_LIMITE; con `simb` de un halt no LULD ese límite se CAPA también al
    tope del T1 (nunca se paga más de parada · 3,5). Una neta LARGA vende de
    forma simétrica (bid · (1 − margen)) y sin tope (el 250 % es de subida;
    una venta a MERCADO sigue siendo MERCADO). Sin `simb` el comportamiento es
    el de antes (MKT). `cfg` es la `Config` entera (o un dict con «rutas» y
    «halts»). Lanza ValueError con otra decisión, sin posición, con `qty` mayor
    que la posición (jamás quedar del otro lado: riesgo 6) o, en PM, sin ningún
    precio del que partir.
    """
    if decision not in ("cerrar_mercado", "cerrar_limite_pm"):
        raise ValueError(f"decisión sin orden: {decision!r}")
    if pos.neta == 0:
        raise ValueError(f"{pos.ticker}: sin posición, nada que cerrar")
    if qty > abs(pos.neta):
        raise ValueError(f"{pos.ticker}: qty {qty} supera la posición {abs(pos.neta)} (no se cruza al otro lado)")
    corto = pos.neta < 0
    lado = Lado.COMPRA if corto else Lado.VENTA
    rutas = _bloque(cfg, "rutas")
    tope_t1 = precio_tope_t1(simb, cfg) if (simb is not None and corto) else None
    if decision == "cerrar_mercado":
        # `precios.ruta` ignora el precio para «halt» (rutas.halt vale para todo tramo): se pasa un Decimal cualquiera.
        ruta_open = ruta(rutas, "halt", Decimal("1"), hora_et)
        if tope_t1 is not None:
            return OrdenNueva(token=token, lado=lado, ticker=pos.ticker, ruta=ruta_open, qty=qty,
                              tipo=TipoOrden.LIMITE, precio=tope_t1, proposito=Proposito.HALT_OPEN)
        return OrdenNueva(token=token, lado=lado, ticker=pos.ticker, ruta=ruta_open,
                          qty=qty, tipo=TipoOrden.MERCADO, proposito=Proposito.HALT_OPEN)
    margen = _cfg_decimal(_bloque(cfg, "halts"), "margen_limite_pm_pct", MARGEN_LIMITE_PM_PCT_DEFECTO)
    base = None
    if cot is not None:
        base = cot.ask if corto else cot.bid
        if base is None or base <= 0:
            base = cot.last if (cot.last is not None and cot.last > 0) else None
    if base is None:
        raise ValueError(f"{pos.ticker}: sin ask/bid/last para el límite de salida en premercado")
    precio = con_techo(base, margen, arriba=corto)
    if tope_t1 is not None and precio > tope_t1:
        precio = tope_t1
    return OrdenNueva(token=token, lado=lado, ticker=pos.ticker, ruta=ruta(rutas, "cruzar", precio, hora_et),
                      qty=qty, tipo=TipoOrden.LIMITE, precio=precio, tif="DAY+", proposito=Proposito.HALT_PM_LIMITE)


def ensanchar_stops_pm(pos: PosicionTicker, vivas: list[Orden], simb: EstadoSimbolo, franja: str, cfg: Any,
                       version: Optional[int] = None) -> list[Accion]:
    """E1-04 (R-F-06, 2.ª parte): halt H de PREMERCADO con decisión «mantener» → stops límite con más margen.

    «Si ya hay un stop limit puesto y se entra en T1/T12 en PM, ese stop se
    cambia por otro que remueva más liquidez». Solo con la franja de
    premercado, el símbolo parado sin ser LULD (`H`/`Q`) y la posición CORTA:
    cada STOPLMTP de COMPRA viva del ticker con `id_das`, disparo y límite
    conocidos cuyo límite quede por debajo de `con_techo(disparo,
    margen_limite_pm_pct)` (5 %, redondeado arriba) → `Reemplazar` con el
    MISMO disparo, la MISMA cantidad abierta (`share` de
    `tipos.share_de_replace` según `stops.replace_share_es_abierta`) y el
    límite nuevo, con la serie «stops:X» y la versión vigente (`version` o
    `pos.version_stops`), + `Programar("replace_verificar")` (2h.8). Nunca baja
    un límite, nunca mueve el disparo, nunca envía ni cancela nada. Con el
    stop único (Jaume 29-sep, R-C-01 v4) el límite de cada stop de nivel ya es
    disparo + 50 %: aquí no hay nada que ensanchar y devuelve []; solo actúa
    sobre un stop de compra con un límite más estrecho que el margen (red para
    una protección u orden adoptada con otra config). Si cambia algo,
    `Anotar("halt_stops_pm")` delante.
    El plan de stops casa por disparo y solo corrige cantidades: no deshace el
    ensanche. `cfg` es la `Config` (o un dict con «halts» y «stops»).
    """
    if pos.neta >= 0 or not _es_premercado(franja) or not es_halt(simb) or es_luld(simb):
        return []
    margen = _cfg_decimal(_bloque_halts(cfg), "margen_limite_pm_pct", MARGEN_LIMITE_PM_PCT_DEFECTO)
    share_es_abierta = _share_es_abierta(cfg)
    vigente = pos.version_stops if version is None else version
    cambios: list[Accion] = []
    anotados: list[dict] = []
    for o in sorted(_unicas(vivas), key=_antiguedad):
        if (o.ticker != pos.ticker or o.lado is not Lado.COMPRA or o.tipo is not TipoOrden.STOP_LIMITE_PP
                or o.estado not in _ESTADOS_VIVOS or o.id_das is None or o.stop is None or o.precio is None
                or not o.stop.is_finite() or o.stop <= 0):
            continue
        abierta = _qty_viva(o)
        if abierta <= 0:
            continue
        nuevo = con_techo(o.stop, margen, arriba=True)
        if nuevo <= o.precio:
            continue
        cambios += [Reemplazar(id_das=o.id_das, token=o.token,
                               qty=share_de_replace(abierta, max(int(o.llenas), 0), share_es_abierta),
                               stop=o.stop, precio=nuevo,
                               motivo=(f"R-F-06 / E1-04: halt en premercado en {pos.ticker}: límite del stop "
                                       f"{o.precio} → {nuevo} (disparo {o.stop} + {margen} %)"),
                               version=vigente, serie=_SERIE_STOPS.format(pos.ticker)),
                    Programar(_CLAVE_VERIFICAR_REPLACE, _VERIFICAR_REPLACE_EN_S,
                              {"token": o.token, "ticker": pos.ticker, "qty_objetivo": abierta})]
        anotados.append({"token": o.token, "disparo": str(o.stop), "limite_antes": str(o.precio),
                         "limite_nuevo": str(nuevo), "qty": abierta})
    if not cambios:
        return []
    return [Anotar(ANOTACION_STOPS_PM, {"ticker": pos.ticker, "ta": simb.ta, "franja": franja,
                                        "margen_pct": str(margen), "stops": anotados, "regla": "R-F-06 / E1-04"})] + cambios


# ── cuándo y si se envía la MKT por OPEN (injerto A §8.23, riesgo 27) ────
def momento_envio_open(fin: Optional[datetime], ahora_et: datetime, antes_s: int = HALT_ENVIAR_ANTES_FIN_S) -> float:
    """Segundos hasta (fin − `antes_s`): 0 (= AHORA) si el fin es desconocido, ya pasó o falta ≤ `antes_s` (R-F-01, 22-sep).

    «Si el halt tiene más de un minuto de espera, un minuto antes; si es de
    menos de un minuto o no tiene hora, en cuanto se decida salir».
    """
    if fin is None:
        return 0.0
    restante = (_a_et(fin) - _a_et(ahora_et)).total_seconds()
    if restante <= antes_s:
        return 0.0
    return float(restante - antes_s)


def debe_enviar_open(simb: EstadoSimbolo) -> bool:
    """Guardia del injerto A §8.23: una sola MKT por OPEN por halt, y solo mientras el símbolo siga parado.

    `orden_open_enviada` la pone el decisor al enviar y la borra
    `MercadoDAS.marcar_halt` en la reapertura (y en cada halt nuevo). Un
    `$IssueStatus` repetido reprograma `halt_decidir` pero no produce una
    segunda orden.
    """
    return es_halt(simb) and not simb.orden_open_enviada


# ── reentradas y señal guardada (R-F-01 esc. 2, R-F-03, R-F-04 b) ────────
def puede_reentrar_tras_halt(primera_vela_pct: Optional[Decimal], k: int, cfg_halts: dict) -> bool:
    """R-F-01 esc. 2 / R-F-03 / R-F-04: reentrar solo si la primera vela tras reabrir sube < 6 % Y k < k_max.

    Sin primera vela completa (None) no se sabe → False. Los umbrales son
    estrictos: 6,0 % exacto NO permite reentrar; k = 3 tampoco.
    """
    if primera_vela_pct is None:
        return False
    tope = _cfg_decimal(cfg_halts, "primera_vela_max_reentrada_pct", HALT_PRIMERA_VELA_MAX_PCT)
    return primera_vela_pct < tope and k < _cfg_int(cfg_halts, "k_max", HALT_K_MAX)


def senal_guardada_valida(senal: Optional[Senal], primera_vela_pct: Optional[Decimal], cfg_halts: dict,
                          k: int) -> bool:
    """R-F-04 (b): la señal guardada durante el halt se ejecuta al reabrir si la primera vela subió < X % y k < k_max.

    X = `halts.primera_vela_max_senal_guardada_pct` (defecto 6, [PENDIENTE
    estudio]). Solo vale una señal de ENTRADA (`clase == "evento"` con un
    `Evento` de tipo «entrada», leído con `getattr`: riesgo 18); B18: la
    escalera cancelada no se retoma, se entra de cero. `k` (=
    `simb.k_halts_up`) es OBLIGATORIO aunque §3.18 lo omita: con un valor por
    defecto un decisor que lo olvidara saltaría en silencio el «k < 3» de F6.3.
    """
    if senal is None or senal.clase != "evento" or primera_vela_pct is None:
        return False
    if getattr(senal.evento, "tipo", None) != "entrada":
        return False
    tope = _cfg_decimal(cfg_halts, "primera_vela_max_senal_guardada_pct", HALT_PRIMERA_VELA_MAX_PCT)
    return primera_vela_pct < tope and k < _cfg_int(cfg_halts, "k_max", HALT_K_MAX)


def primera_vela_pct(precio_reapertura: Decimal, cierre_primera_vela: Decimal) -> Decimal:
    """Subida de la primera vela de 1 min tras reabrir: (cierre − reapertura) / reapertura · 100 (R-F-01 esc. 2)."""
    for nombre, valor in (("precio_reapertura", precio_reapertura), ("cierre_primera_vela", cierre_primera_vela)):
        if not valor.is_finite() or valor <= 0:
            raise ValueError(f"{nombre} debe ser un precio finito > 0: {valor!r}")
    return subida_pct(precio_reapertura, cierre_primera_vela)


# ── auxiliares ──────────────────────────────────────────────────────────
def _ta(simb: EstadoSimbolo) -> str:
    """TA normalizado («» si no hay): el parser lo deja tal cual llega del socket."""
    return (simb.ta or "").strip().upper()


def _es_rth(franja: str) -> bool:
    return franja.startswith("RTH")


def _es_premercado(franja: str) -> bool:
    return franja.startswith("premercado")


def _a_et(dt: datetime) -> datetime:
    """Naive → se asume ET (como `reloj._a_et`); aware → se convierte a ET."""
    return dt.replace(tzinfo=ET) if dt.tzinfo is None else dt.astimezone(ET)


def _precio_ultimo(cot: Optional[Cotizacion], simb: EstadoSimbolo) -> Optional[Decimal]:
    """Precio de reapertura si ya hay `last` (o el último conocido antes de parar); si no, el precio de parada."""
    if cot is not None and cot.last is not None and cot.last > 0:
        return cot.last
    if simb.precio_parada is not None and simb.precio_parada > 0:
        return simb.precio_parada
    return None


def _niveles_stop_lotes(pos: PosicionTicker) -> list[Decimal]:
    niveles = {lote.nivel_stop for lote in pos.lotes.values()
               if lote.estado in _LOTES_VIVOS and lote.nivel_stop is not None}
    return sorted(niveles)


def _marca_halt(simb: EstadoSimbolo) -> str:
    if simb.halt_desde is not None:
        return simb.halt_desde.isoformat()
    return simb.tat or ""


def _txt(valor: Optional[Decimal]) -> Optional[str]:
    return None if valor is None else str(valor)


def _bloque_halts(cfg: Any) -> Mapping:
    """El bloque «halts»: el propio dict si ya lo es (no trae la clave «halts»), o el de una `Config` / dict con bloques."""
    if isinstance(cfg, Mapping):
        valor = cfg.get("halts")
        return valor if isinstance(valor, Mapping) else cfg
    valor = getattr(cfg, "halts", None)
    return valor if isinstance(valor, Mapping) else {}


def _share_es_abierta(cfg: Any) -> bool:
    """A-02: `stops.replace_share_es_abierta` si la config lo fija como bool; si no, el defecto de tipos."""
    bloque = cfg.get("stops") if isinstance(cfg, Mapping) else getattr(cfg, "stops", None)
    valor = bloque.get(_CLAVE_SHARE_ES_ABIERTA) if isinstance(bloque, Mapping) else None
    return valor if isinstance(valor, bool) else REPLACE_SHARE_ES_ABIERTA


def _unicas(vivas: Any) -> list[Orden]:
    vistas: set[int] = set()
    salida: list[Orden] = []
    for o in vivas or ():
        if isinstance(o, Orden) and id(o) not in vistas:
            vistas.add(id(o))
            salida.append(o)
    return salida


def _antiguedad(o: Orden) -> tuple[int, int, float]:
    if o.id_das is not None:
        return (0, int(o.id_das), o.enviada_en)
    return (1, 0, o.enviada_en)


def _qty_viva(o: Orden) -> int:
    """Acciones que la orden aún puede ejecutar: `lvqty` en Partial/Triggered si > 0; si no, qty − llenas."""
    if o.estado in (EstadoOrden.PARTIAL, EstadoOrden.TRIGGERED) and o.lvqty > 0:
        return max(int(o.lvqty), 0)
    return max(int(o.qty) - int(o.llenas), 0)


def _bloque(cfg: Any, nombre: str) -> dict:
    """«rutas» / «halts» de una `Config` (atributo) o de un dict (clave)."""
    if isinstance(cfg, dict):
        if nombre not in cfg:
            raise ValueError(f"config sin bloque {nombre!r}")
        return cfg[nombre]
    bloque = getattr(cfg, nombre, None)
    if bloque is None:
        raise ValueError(f"config sin bloque {nombre!r}")
    return bloque


def _cfg_decimal(cfg: dict, clave: str, defecto: Decimal) -> Decimal:
    valor = cfg.get(clave)
    return defecto if valor is None else de_float(valor)


def _cfg_int(cfg: dict, clave: str, defecto: int) -> int:
    valor = cfg.get(clave)
    if valor is None:
        return defecto
    if isinstance(valor, bool) or int(valor) != valor:
        raise ValueError(f"halts.{clave} debe ser entero: {valor!r}")
    return int(valor)


def _cfg_float(cfg: dict, clave: str, defecto: float) -> float:
    valor = cfg.get(clave)
    if valor is None:
        return defecto
    if isinstance(valor, bool):
        raise ValueError(f"halts.{clave} debe ser numérico: {valor!r}")
    return float(valor)
