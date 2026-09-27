"""Capital de la cuenta: margen de Sage por tramo, BP, tope corto y orden de llegada.

QUÉ HACE. Calcula el margen INICIAL que exige un corto (Reg T de Sage, con la
tasa del símbolo de GET SHORTINFO si exige más), el margen de MANTENIMIENTO
por tramos FINRA 4210, cuántas acciones de una señal caben con el BP de DAS y
el tope de exposición corta total (1× equity; 0,5× en «alto riesgo»), la
exposición corta nominal del libro de posiciones y si un cambio de precio
mete una posición en un tramo de mantenimiento más exigente. Además lleva la
reserva de BP entre dos lecturas de GET BP (R-E-02, orden de llegada).

POR QUÉ ESTÁ AQUÍ. Libro, apartado 2c (consecuencia 1): el «capital libre» de
R-I-01 no es el nominal, es el MARGEN; un corto de 1.000 acciones a 1 $
exige 2.500 $. El decisor dimensiona con esto ANTES de enviar (F1 paso 3:
`qty_de_evento` → `acciones_que_caben` → `locates` → `entrada.qty_final` →
`reservar`). Son funciones PURAS (sin I/O, sin reloj, sin logging): reciben
`ahora` (monotónico) como parámetro. Solo `reservar` y `liberar_reservas`
mutan, y solo la `Cuenta` que se les pasa (la del `EstadoBot`, que es del
decisor).

LAS TRAMPAS.
  * Todo en `Decimal` y las acciones en `int`: un `float` como precio, tasa o
    exposición es un `ValueError`, no una conversión silenciosa (la única
    puerta de floats es `reglas.precios.de_float`, riesgo 12). `bool` no es
    una cantidad aunque `isinstance(True, int)`.
  * Margen LINEAL en acciones: máx(2,50·q, p·q) = q·máx(2,50, p) y la tasa
    del símbolo también es proporcional, así que lo que cabe es
    floor(BP libre / margen de UNA acción), sin tanteos. Se comprueba de
    todos modos con `margen_inicial_corto` (red de seguridad).
  * BP no legible = no se entra (R-I-01 «si la acción falla», R-K-03): sin
    `bp`, sin `leida_en`, lectura con más de `max_edad_s` (30 s) o con
    `leida_en` en el FUTURO del reloj monotónico (incoherencia: se trata
    como no legible, lo conservador). Sin `equity` tampoco se entra: sin él
    no hay tope corto que comprobar (2c consecuencia 2).
  * Orden de llegada (R-E-02): lo que una señal ya aceptada va a consumir no
    lo refleja DAS hasta el próximo GET BP; `reservar` lo descuenta del BP
    (`cuenta.bp_reservado`) y `liberar_reservas` lo suelta al llegar cada
    `MsgBP`. La segunda señal recibe SOLO lo que sobre, sin reparto
    proporcional. Del lado del tope corto, `exposicion_corta` cuenta también
    lo PENDIENTE de los intentos vivos (lo pedido y aún no llenado), por la
    misma razón: una entrada aceptada todavía no está en `neta_fills`.
  * El margen de mantenimiento SUBE cuando el corto va a favor (5,20 → 4,90:
    del 30 % al 100 %): `requiere_mas_margen` compara tramos, no dólares.
  * Los tramos FINRA están duplicados en `reglas.vigilancia` (regla de
    reparto del §12); su test compara las dos copias.
"""
from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Optional

from app.bot_das.tipos import (
    RECONCILIACION_CADUCA_S,
    Cotizacion,
    Cuenta,
    FaseIntento,
    PosicionTicker,
)

# ── motivos estables de `acciones_que_caben` (el decisor los anota en el diario) ──
MOTIVO_ENTERA = "cabe entera"
MOTIVO_PARCIAL_BP = "cabe parte: BP"
MOTIVO_PARCIAL_TOPE = "cabe parte: tope corto"
MOTIVO_SIN_BP = "sin BP"
MOTIVO_SIN_EQUITY = "sin equity"
MOTIVO_BP_AGOTADO = "BP agotado"
MOTIVO_TOPE_ALCANZADO = "tope corto alcanzado"
MOTIVO_NADA_PEDIDO = "nada pedido"

# ── 2c: reglas de margen de Sage (página pública leída el 19-sep) ──────
TOPE_CORTO_EQUITY = Decimal("1")               # 2c: corto máximo 1× el equity
TOPE_CORTO_EQUITY_ALTO_RIESGO = Decimal("0.5")  # 2c: cortos «de alto riesgo» 0,5× el equity

_INICIAL_UMBRAL = Decimal("5")          # Reg T de Sage: < 5 $ / ≥ 5 $
_INICIAL_POR_ACCION_BAJO = Decimal("2.50")
_INICIAL_PCT_BAJO = Decimal("1")        # 100 % del valor
_INICIAL_POR_ACCION_ALTO = Decimal("5")
_INICIAL_PCT_ALTO = Decimal("0.30")     # 30 % del valor

_MANT_TRAMO_1 = Decimal("2.50")         # FINRA 4210 cortos: < 2,50 → 2,50 $/acción
_MANT_TRAMO_2 = Decimal("5")            # 2,50-4,99 → 100 % del valor
_MANT_TRAMO_3 = Decimal("16.67")        # 5-16,66 → 5 $/acción; ≥ 16,67 → 30 %
_MANT_POR_ACCION_BAJO = Decimal("2.50")
_MANT_POR_ACCION_MEDIO = Decimal("5")
_MANT_PCT_ALTO = Decimal("0.30")

_CIEN = Decimal("100")
_CERO = Decimal("0")


# ── margen ────────────────────────────────────────────────────────────
def margen_inicial_corto(precio: Decimal, qty: int, tasa_simbolo: Optional[Decimal]) -> Decimal:
    """Margen inicial que exige abrir `qty` cortas a `precio` (libro 2c, Reg T de Sage; manual GET SHORTINFO).

    < 5 $: el mayor de 2,50 $/acción o el 100 % del valor; ≥ 5 $: el mayor de
    5 $/acción o el 30 % del valor. `tasa_simbolo` es el shortMarginRate de
    `$SHORTINFO` (`MsgShortInfo.tasa_corta`) en PORCENTAJE del valor: None o
    0 = la tasa por defecto (no cambia nada); si exige más (p. ej. 100 = todo
    en efectivo o 300 en un HTB), manda la tasa. Nunca rebaja el Reg T.

    Trampas: precio `Decimal` finito > 0 (un float o NaN lanza `ValueError`,
    riesgo 12); `qty` int ≥ 0 (bool no); tasa negativa o no finita lanza. El
    resultado es exacto (sin redondeo): lo compara el llamador con el BP.
    """
    p = _precio(precio, "precio")
    q = _acciones(qty, "qty")
    tasa = _tasa(tasa_simbolo)
    valor = p * q
    if p < _INICIAL_UMBRAL:
        exigido = max(_INICIAL_POR_ACCION_BAJO * q, _INICIAL_PCT_BAJO * valor)
    else:
        exigido = max(_INICIAL_POR_ACCION_ALTO * q, _INICIAL_PCT_ALTO * valor)
    if tasa > 0:
        exigido = max(exigido, tasa / _CIEN * valor)
    return exigido


def margen_mantenimiento(precio: Decimal, qty: int) -> Decimal:
    """Margen de mantenimiento de `qty` cortas a `precio` (libro 2c, FINRA 4210).

    < 2,50 $ → 2,50 $/acción; 2,50-4,99 $ → 100 % del valor; 5-16,66 $ →
    5 $/acción; ≥ 16,67 $ → 30 % del valor. Lo usa el vigilante (2c
    consecuencia 4: margen de mantenimiento total frente al equity) y debe
    dar lo mismo que `reglas.vigilancia.margen_mantenimiento_corto`.

    Trampas: mismas validaciones que `margen_inicial_corto`; el límite 16,67
    es inclusivo del tramo del 30 % (16,66 aún paga 5 $/acción).
    """
    p = _precio(precio, "precio")
    q = _acciones(qty, "qty")
    if p < _MANT_TRAMO_1:
        return _MANT_POR_ACCION_BAJO * q
    if p < _MANT_TRAMO_2:
        return p * q
    if p < _MANT_TRAMO_3:
        return _MANT_POR_ACCION_MEDIO * q
    return _MANT_PCT_ALTO * p * q


def requiere_mas_margen(precio_antes: Decimal, precio_ahora: Decimal) -> bool:
    """True si el paso de `precio_antes` a `precio_ahora` mete el corto en un tramo de mantenimiento MÁS exigente (libro 2c consecuencia 4).

    Los tramos FINRA exigen, en proporción del valor, más cuanto más baja el
    precio: ≥ 16,67 (30 %) < 5-16,66 (5 $/acción) < 2,50-4,99 (100 %) <
    < 2,50 (2,50 $/acción, más del 100 %). Un corto que va a favor y cruza
    un límite hacia abajo (5,20 → 4,90: del 30 % al 100 %) devuelve True y el
    vigilante avisa; subir de precio o moverse dentro del mismo tramo, False.

    Trampa: se comparan TRAMOS, no dólares: en el límite los dólares apenas
    cambian (5,00 $ a 5,00 $ → 4,90 $ a 4,90) pero el porcentaje sí, que es
    lo que vigila la autoliquidación del bróker.
    """
    return _tramo_mantenimiento(_precio(precio_ahora, "precio_ahora")) > _tramo_mantenimiento(
        _precio(precio_antes, "precio_antes"))


# ── dimensionado ──────────────────────────────────────────────────────
def acciones_que_caben(qty_pedida: int, precio: Decimal, cuenta: Cuenta, tasa_simbolo: Optional[Decimal],
                       exposicion_corta_usd: Decimal, alto_riesgo: bool, ahora: float,
                       max_edad_s: float = RECONCILIACION_CADUCA_S) -> tuple[int, str]:
    """(acciones que caben, motivo) para un corto de `qty_pedida` a `precio` — R-I-01, R-E-02, R-K-03, libro 2c.

    1. BP no legible → (0, MOTIVO_SIN_BP): `cuenta.bp` o `cuenta.leida_en`
       None, lectura con más de `max_edad_s` (30 s, R-K-03) o `leida_en`
       posterior a `ahora` (R-I-01: «capital libre no se puede leer → no se
       entra»).
    2. Sin `cuenta.equity` → (0, MOTIVO_SIN_EQUITY): no hay tope corto que
       comprobar (2c consecuencia 2).
    3. BP libre = `cuenta.bp` − `cuenta.bp_reservado` (R-E-02: lo ya aceptado
       desde el último GET BP no está en el BP de DAS). Caben
       floor(BP libre / margen inicial de una acción) (2c consecuencia 1).
    4. Tope corto total = equity × 1 (× 0,5 si `alto_riesgo`) menos
       `exposicion_corta_usd` (la de `exposicion_corta`); caben
       floor(resto / precio) acciones de nominal.
    5. Se entra con lo que quepa (R-I-01: «si queda solo una parte, se entra
       con lo que quede»; múltiplo de una acción). El motivo dice qué limitó:
       MOTIVO_ENTERA, MOTIVO_PARCIAL_BP / MOTIVO_PARCIAL_TOPE, o con 0
       MOTIVO_BP_AGOTADO / MOTIVO_TOPE_ALCANZADO (si limitan los dos por
       igual se nombra el BP). `qty_pedida` 0 → (0, MOTIVO_NADA_PEDIDO).

    No reserva nada: el decisor llama a `reservar` con el margen de la
    cantidad FINAL (tras locates y `entrada.qty_final`). Lanza `ValueError`
    con argumentos inválidos (float, NaN, negativos, bool como cantidad).
    """
    pedidas = _acciones(qty_pedida, "qty_pedida")
    p = _precio(precio, "precio")
    tasa = _tasa(tasa_simbolo)
    exposicion = _importe(exposicion_corta_usd, "exposicion_corta_usd")
    if not isinstance(alto_riesgo, bool):
        raise ValueError(f"alto_riesgo debe ser bool, no {alto_riesgo!r}")
    ahora_s = _segundos(ahora, "ahora")
    max_edad = _segundos(max_edad_s, "max_edad_s")
    if max_edad < 0:
        raise ValueError(f"max_edad_s negativo: {max_edad_s!r}")
    if pedidas == 0:
        return 0, MOTIVO_NADA_PEDIDO
    if not _bp_legible(cuenta, ahora_s, max_edad):
        return 0, MOTIVO_SIN_BP
    if cuenta.equity is None:
        return 0, MOTIVO_SIN_EQUITY
    bp = _importe_signado(cuenta.bp, "cuenta.bp")
    reservado = _importe(cuenta.bp_reservado, "cuenta.bp_reservado")
    equity = _importe_signado(cuenta.equity, "cuenta.equity")

    bp_libre = bp - reservado
    por_accion = margen_inicial_corto(p, 1, tasa)
    caben_bp = _cociente_entero(bp_libre, por_accion)
    while caben_bp > 0 and margen_inicial_corto(p, caben_bp, tasa) > bp_libre:   # red: el margen es lineal
        caben_bp -= 1

    factor = TOPE_CORTO_EQUITY_ALTO_RIESGO if alto_riesgo else TOPE_CORTO_EQUITY
    resto_tope = equity * factor - exposicion
    caben_tope = _cociente_entero(resto_tope, p)

    qty = min(pedidas, caben_bp, caben_tope)
    if qty == pedidas:
        return qty, MOTIVO_ENTERA
    limita_bp = caben_bp <= caben_tope
    if qty == 0:
        return 0, MOTIVO_BP_AGOTADO if limita_bp else MOTIVO_TOPE_ALCANZADO
    return qty, MOTIVO_PARCIAL_BP if limita_bp else MOTIVO_PARCIAL_TOPE


def reservar(cuenta: Cuenta, margen: Decimal) -> None:
    """Descuenta `margen` del BP hasta el próximo GET BP (R-E-02, orden de llegada).

    El decisor la llama con `margen_inicial_corto(precio, qty_final, tasa)`
    en cuanto acepta una entrada o pirámide, para que la SIGUIENTE señal vea
    solo lo que sobra. Muta `cuenta.bp_reservado` (la cuenta es del decisor).
    Trampa: margen negativo, float o no finito lanza `ValueError` (una
    «reserva» negativa inflaría el BP).
    """
    m = _importe(margen, "margen")
    cuenta.bp_reservado = _importe(cuenta.bp_reservado, "cuenta.bp_reservado") + m


def liberar_reservas(cuenta: Cuenta) -> None:
    """Suelta todas las reservas: el `MsgBP` recién llegado ya refleja lo consumido (R-E-02, §3.21).

    El decisor la llama con CADA `MsgBP` (junto con `cuenta.bp` y
    `cuenta.leida_en`). Trampa (duda para Jaume): si DAS respondió al GET BP
    antes de registrar una orden recién enviada, esa orden deja de contar
    hasta la lectura siguiente; el tope corto la sigue contando por el
    intento vivo de `exposicion_corta`.
    """
    cuenta.bp_reservado = Decimal("0")


def exposicion_corta(posiciones: dict[str, PosicionTicker],
                     cot_de: Callable[[str], Optional[Cotizacion]]) -> Decimal:
    """Nominal corto total de la cuenta en dólares (libro 2c consecuencia 2: tope corto total 1× equity).

    Por ticker: acciones cortas = el MÁS corto entre `neta_fills` (verdad
    inmediata) y `neta_das` (incluye intervenciones humanas, R-K-02), más lo
    pendiente de un intento de entrada vivo (`qty_total − llenas`, fase ≠
    TERMINADO: una entrada aceptada aún no está en los fills, R-E-02). Se
    valora al precio MÁS ALTO conocido de la cotización (`last`, `ask`,
    `bid`: lo conservador para un corto); sin cotización, al `avg_das`, al
    precio medio ponderado de los lotes llenos o al `precio_senal` del
    intento, en ese orden. Las posiciones largas no cuentan.

    Lanza `ValueError` si un ticker con cortos no tiene ningún precio con el
    que valorarse (no se inventa una exposición) o si un precio no es un
    `Decimal` finito > 0.
    """
    total = _CERO
    for ticker, pos in posiciones.items():
        cortas = max(-pos.neta_fills, -pos.neta_das if pos.neta_das is not None else 0, 0)
        intento = pos.intento
        if intento is not None and intento.fase is not FaseIntento.TERMINADO:
            cortas += max(intento.qty_total - intento.llenas, 0)
        if cortas == 0:
            continue
        total += _precio(_precio_de_valoracion(ticker, pos, cot_de), f"precio de {ticker}") * cortas
    return total


# ── privados (puros) ──────────────────────────────────────────────────
def _tramo_mantenimiento(p: Decimal) -> int:
    """0 = ≥ 16,67 (30 %); 1 = 5-16,66; 2 = 2,50-4,99; 3 = < 2,50. Más alto = más exigente en proporción."""
    if p >= _MANT_TRAMO_3:
        return 0
    if p >= _MANT_TRAMO_2:
        return 1
    if p >= _MANT_TRAMO_1:
        return 2
    return 3


def _bp_legible(cuenta: Cuenta, ahora: float, max_edad: float) -> bool:
    if cuenta.bp is None or cuenta.leida_en is None:
        return False
    edad = ahora - _segundos(cuenta.leida_en, "cuenta.leida_en")
    return 0 <= edad <= max_edad


def _precio_de_valoracion(ticker: str, pos: PosicionTicker,
                          cot_de: Callable[[str], Optional[Cotizacion]]) -> Decimal:
    cot = cot_de(ticker)
    if cot is not None:
        conocidos = [x for x in (cot.last, cot.ask, cot.bid) if x is not None]
        if conocidos:
            return max(_precio(x, f"cotización de {ticker}") for x in conocidos)
    if pos.avg_das is not None and pos.avg_das > 0:
        return pos.avg_das
    llenas = sum(lote.llenas for lote in pos.lotes.values() if lote.llenas > 0)
    if llenas > 0:
        return sum((lote.precio_medio * lote.llenas for lote in pos.lotes.values() if lote.llenas > 0),
                   _CERO) / llenas
    if pos.intento is not None:
        return pos.intento.precio_senal
    raise ValueError(f"{ticker}: posición corta sin precio con que valorarla")


def _cociente_entero(dividendo: Decimal, divisor: Decimal) -> int:
    """floor(dividendo / divisor) con divisor > 0; 0 si el dividendo no es positivo."""
    if dividendo <= 0:
        return 0
    return int(dividendo // divisor)


def _precio(x: object, nombre: str) -> Decimal:
    if not isinstance(x, Decimal) or not x.is_finite() or x <= 0:
        raise ValueError(f"{nombre} debe ser un Decimal finito > 0, no {x!r}")
    return x


def _importe(x: object, nombre: str) -> Decimal:
    """Importe en dólares ≥ 0 (exposición, reserva, margen)."""
    if not isinstance(x, Decimal) or not x.is_finite() or x < 0:
        raise ValueError(f"{nombre} debe ser un Decimal finito ≥ 0, no {x!r}")
    return x


def _importe_signado(x: object, nombre: str) -> Decimal:
    """Importe que DAS puede dar negativo (BP o equity en déficit): solo se exige Decimal finito."""
    if not isinstance(x, Decimal) or not x.is_finite():
        raise ValueError(f"{nombre} debe ser un Decimal finito, no {x!r}")
    return x


def _acciones(x: object, nombre: str) -> int:
    if type(x) is not int or x < 0:
        raise ValueError(f"{nombre} debe ser int ≥ 0, no {x!r}")
    return x


def _tasa(x: object) -> Decimal:
    if x is None:
        return _CERO
    if not isinstance(x, Decimal) or not x.is_finite() or x < 0:
        raise ValueError(f"tasa_simbolo debe ser None o un Decimal finito ≥ 0, no {x!r}")
    return x


def _segundos(x: object, nombre: str) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or x != x or x in (float("inf"), float("-inf")):
        raise ValueError(f"{nombre} debe ser un número finito de segundos, no {x!r}")
    return float(x)
