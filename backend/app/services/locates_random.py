"""Precio de locate ALEATORIO por ticker-dia, sesgado por el precio de la accion.

Hoy `locates_cost` es un numero fijo para toda la corrida y la realidad no es
esa: el precio del locate cambia por ticker y por dia, y la cola es brutal (una
sola operacion se llevo 7.000 $ de una cuenta de 10.000). Con un coste medio
fijo ese dia no existe en el backtest.

LAS TRES REGLAS DEL SORTEO

1. **Por ticker-dia, no por trade.** El locate se alquila una vez al dia y las
   reentradas y los anadidos de piramide lo reutilizan; el motor ya lo cobra asi
   (`ceil(max_short_size_today/100) * precio`). Aqui solo cambia el precio que
   se le pasa a `simulate()` para ese ticker-dia.

2. **Determinista y sin depender del orden.** El sorteo sale de un hash de
   (semilla, ticker, fecha), NO de un generador que avanza. Dos corridas con la
   misma semilla dan los mismos precios aunque los ticker-dias se procesen en
   otro orden, y cambiar un parametro cualquiera no mueve ni un locate: la
   diferencia que veas es del parametro, no de la suerte del sorteo.

3. **Las caras salen caras, sin anclas del usuario.** El precio de la accion fija
   el CENTRO dentro del rango [minimo, maximo] en escala logaritmica entre el
   suelo del universo (0,10 $, el mismo que ya filtra el backtest) y un techo de
   30 $; y alrededor de ese centro se sortea con una dispersion lognormal
   moderada, recortada al rango. Medido con rango 1-10 (dos de cada tres
   sorteos): una accion de 0,30 $ sale en torno a 2,7 (2-3,9), una de 3 $ en
   torno a 6,4 (4,6-9), una de 15 $ en torno a 8,9 (6,4-10). Jaume no quiso
   poner anclas: «que se distribuya solo».

El precio de referencia es la PRIMERA vela del frame del dia (arranca a las
04:00): es causal —se conoce antes de cualquier entrada— y es lo que mira un
broker al poner precio al alquiler esa manana.
"""
from __future__ import annotations

import hashlib
import math
import random
from typing import Iterable

# Escala de precios del universo. El suelo es el mismo que aplica
# `data_service._filtrar_universo`; el techo es donde estas acciones dejan de
# ser «small caps» a efectos de locate. No son parametros del usuario a proposito.
PRECIO_SUELO = 0.10
PRECIO_TECHO = 30.0

# Dispersion (sigma del lognormal) alrededor del centro. Con 0,35, dos de cada
# tres sorteos caen entre x0,7 y x1,4 del centro. Si algun dia hace falta, es un
# deslizador; hoy es una constante para no anadir un campo mas a la pantalla.
SIGMA = 0.35


def _rng(seed: int, ticker: str, fecha: str) -> random.Random:
    """Generador propio de ese ticker-dia: mismo (semilla, ticker, fecha) →
    misma secuencia, independientemente de cuantos ticker-dias se hayan
    sorteado antes."""
    clave = f"{int(seed)}|{ticker}|{fecha}".encode("utf-8")
    entero = int.from_bytes(hashlib.blake2b(clave, digest_size=8).digest(), "big")
    return random.Random(entero)


def posicion_por_precio(precio: float) -> float:
    """Donde cae ese precio en el universo, de 0 (suelo) a 1 (techo), en log."""
    if not precio or precio <= 0:
        return 0.0
    p = min(max(precio, PRECIO_SUELO), PRECIO_TECHO)
    return math.log(p / PRECIO_SUELO) / math.log(PRECIO_TECHO / PRECIO_SUELO)


def precio_locate(
    precio_ref: float,
    minimo: float,
    maximo: float,
    seed: int,
    ticker: str,
    fecha: str,
) -> dict:
    """Precio del paquete de 100 para ese ticker-dia.

    Devuelve un dict con el precio y las piezas del calculo (para poder
    ensenarlas en el trade): referencia, posicion en el universo y centro.
    """
    lo, hi = float(min(minimo, maximo)), float(max(minimo, maximo))
    if lo < 0:
        lo = 0.0
    pos = posicion_por_precio(precio_ref)
    centro = lo + (hi - lo) * pos
    if hi <= lo or centro <= 0:
        precio = lo
    else:
        # Lognormal centrado en `centro`: multiplicativo, asi que la cola larga
        # queda hacia arriba (los dias carisimos existen, los negativos no).
        factor = math.exp(_rng(seed, ticker, fecha).gauss(0.0, SIGMA))
        precio = min(hi, max(lo, centro * factor))
    return {
        "precio": round(precio, 4),
        "precio_ref": round(float(precio_ref or 0.0), 4),
        "posicion": round(pos, 4),
        "centro": round(centro, 4),
    }


def resumen(precios: Iterable[float]) -> dict:
    """Percentiles del sorteo de la corrida, para la tarjeta del resultado."""
    xs = sorted(float(x) for x in precios)
    if not xs:
        return {"n": 0}

    def p(q: float) -> float:
        i = (len(xs) - 1) * q
        lo, hi = math.floor(i), math.ceil(i)
        v = xs[lo] if lo == hi else xs[lo] + (i - lo) * (xs[hi] - xs[lo])
        return round(v, 4)

    return {
        "n": len(xs),
        "media": round(sum(xs) / len(xs), 4),
        "p10": p(0.10), "p50": p(0.50), "p90": p(0.90),
        "min": round(xs[0], 4), "max": round(xs[-1], 4),
    }
