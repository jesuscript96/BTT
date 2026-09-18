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

3. **Las caras salen caras, y el rango se usa ENTERO.** El precio de la accion
   fija el CENTRO del sorteo como una ley de potencia entre los dos extremos del
   rango: el gapper mas barato que se opera aqui (~0,30 $) cae en el minimo del
   rango y el mas caro (~25 $) en el maximo, y entre medias el locate crece con
   el precio pero MENOS que proporcionalmente (con 1-20, multiplicar el precio
   por 10 multiplica el locate por 4,8). Alrededor del centro se sortea con una
   dispersion lognormal moderada, recortada al rango. Medido con rango 1-20
   (dos de cada tres sorteos): una accion de 0,50 $ sale en torno a 1,4
   (1,0-2,0), una de 1 $ en torno a 2,3 (1,6-3,2), una de 3 $ en torno a 4,8
   (3,4-6,7), una de 10 $ en torno a 10,8 (7,6-15), una de 25 $ o mas pega en
   el 20. Jaume no quiso poner anclas: «que se distribuya solo».

   Hasta el 18-sep la escala iba del suelo del universo (0,10 $) al techo
   (30 $), lineal en log-precio: como los gappers que se operan viven entre
   0,3 y 25 $, la corrida nunca usaba el tramo bajo del rango (con 1-20 el
   locate mas barato de 3.445 ticker-dias fue 2,69 y una accion de 0,50-1 $
   pagaba 7,6 $ el paquete = 10 % de fade), y la puerta por EV tumbaba el 95 %
   de las acciones de menos de 1 $. Era la forma de repartir, no el EV.

El precio de referencia es la PRIMERA vela del frame del dia (arranca a las
04:00): es causal —se conoce antes de cualquier entrada— y es lo que mira un
broker al poner precio al alquiler esa manana.
"""
from __future__ import annotations

import hashlib
import math
import random
from typing import Iterable

# Anclas de la ley de potencia: el precio de referencia al que un ticker-dia
# paga el MINIMO del rango y el precio al que paga el MAXIMO. Medidas el 18-sep
# sobre 3.445 ticker-dias operados por PM (A) en 2024-2026: p1 de la referencia
# 0,54 $ (la estrategia filtra por precio; otras bajan mas), p98 30 $. Por
# debajo de la barata se paga el minimo y por encima de la cara el maximo. No
# son parametros del usuario a proposito: el rango ya es su mando.
PRECIO_BARATA = 0.30
PRECIO_CARA = 25.0

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
    """Donde cae ese precio entre los gappers, de 0 (la barata) a 1 (la cara),
    lineal en log-precio y recortado: por debajo de la barata es 0, por encima
    de la cara es 1."""
    if not precio or precio <= 0:
        return 0.0
    p = min(max(precio, PRECIO_BARATA), PRECIO_CARA)
    return math.log(p / PRECIO_BARATA) / math.log(PRECIO_CARA / PRECIO_BARATA)


def centro_por_precio(precio: float, minimo: float, maximo: float) -> float:
    """Centro del sorteo para ese precio: ley de potencia entre minimo y maximo
    (la barata paga el minimo, la cara el maximo, y en medio el locate crece con
    el precio elevado a log(max/min)/log(cara/barata)). Si el rango arranca en
    0 no hay potencia posible y se interpola lineal."""
    lo, hi = float(min(minimo, maximo)), float(max(minimo, maximo))
    if lo < 0:
        lo = 0.0
    pos = posicion_por_precio(precio)
    if lo > 0 and hi > lo:
        return lo * (hi / lo) ** pos
    return lo + (hi - lo) * pos


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
    centro = centro_por_precio(precio_ref, lo, hi)
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
