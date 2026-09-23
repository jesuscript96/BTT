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

3. **El rango del usuario es «lo normal», no un suelo y un techo.** «De 0,3 a
   15» quiere decir: 9 de cada 10 locates de una corrida caen ahi, 1 de cada 20
   sale por debajo y 1 de cada 20 por encima (la cola cara existe: como mucho
   5 veces el maximo). Con eso el sorteo fija dos cosas: el NIVEL (lo que paga
   la accion de 2 $, la mediana de los gappers: la media geometrica del rango)
   y el RUIDO (lo que falta para que la banda sea el 80 % central). La forma
   viene del mercado y es fija: el locate crece con el precio de la accion
   como precio^0,6 (una de 20 $ paga 4 veces lo que una de 2 $, no 10), y
   alrededor de esa curva la dispersion es enorme, porque manda la
   disponibilidad de prestamo, no el precio.

   Todo lo de arriba esta MEDIDO el 18-sep sobre 99 locates reales del socio de
   Jaume (un mes, DAS): $/paquete = 1,49 x precio^0,62 con una dispersion
   (sigma en log) de 1,15 alrededor; p10 0,06 (el suelo del broker: 1 de cada 7
   dias la accion es facil de prestar y cuesta 0,0006 $/accion), p50 1,96,
   p90 12,1, max 25,9; sus precios: p10 0,45, p50 2,1, p90 6. Con la banda
   0,3-15 el modelo reproduce eso (cobertura 79 %, poblacion p10 0,23, p50 1,8,
   p90 11,6). La banda 1-20 que usaba Jaume es el doble de cara que su broker.

   Historia: hasta el 18-sep el rango era un suelo y un techo duros, el centro
   iba lineal en log-precio entre 0,10 $ y 30 $ y el ruido era sigma 0,35. Con
   1-20, ningun ticker-dia de 3.445 bajaba de 2,69 y una accion de 0,50-1 $
   pagaba 7,6 $ el paquete (10 % de fade); frente a los locates reales la
   cobertura era del 21 %.

El precio de referencia es la PRIMERA vela del frame del dia (arranca a las
04:00): es causal —se conoce antes de cualquier entrada— y es lo que mira un
broker al poner precio al alquiler esa manana.
"""
from __future__ import annotations

import hashlib
import math
import random
from typing import Iterable

# Forma del mercado, medida sobre los locates reales (18-sep). No son
# parametros del usuario a proposito: su mando es el rango.
EXPONENTE_PRECIO = 0.6      # $/paquete ~ precio^0,6 (medido 0,62)
PRECIO_MEDIANO = 2.0        # $ de la accion a la que el nivel es la media geometrica del rango
SIGMA_PRECIOS = 1.0         # dispersion (log) de los precios de los gappers que se operan
Z_P90 = 1.2816              # la banda p10-p90 son +-1,28 sigmas
RUIDO_MINIMO = 0.2          # por si alguien pide una banda mas estrecha que el propio efecto del precio
SUELO_PAQUETE = 0.05        # $/paquete: el suelo del broker es 0,06 (0,0006 $/accion)
COLA_MAXIMA = 5.0           # nunca mas de 5 veces el maximo de la banda


def _rng(seed: int, ticker: str, fecha: str) -> random.Random:
    """Generador propio de ese ticker-dia: mismo (semilla, ticker, fecha) →
    misma secuencia, independientemente de cuantos ticker-dias se hayan
    sorteado antes."""
    clave = f"{int(seed)}|{ticker}|{fecha}".encode("utf-8")
    entero = int.from_bytes(hashlib.blake2b(clave, digest_size=8).digest(), "big")
    return random.Random(entero)


def parametros_banda(minimo: float, maximo: float) -> tuple[float, float, float]:
    """(nivel, ruido, techo) de una banda p10-p90.

    `nivel` = lo que paga la accion de PRECIO_MEDIANO $ en la mediana (media
    geometrica del rango); `ruido` = sigma del lognormal alrededor de la curva,
    lo que falta, descontado el efecto del precio, para que 9 de cada 10 caigan
    en la banda; `techo` = COLA_MAXIMA x maximo. Un minimo de 0 se trata como
    maximo/100 (no hay media geometrica con 0)."""
    lo, hi = float(min(minimo, maximo)), float(max(minimo, maximo))
    if hi <= 0:
        return 0.0, 0.0, 0.0
    lo_ef = lo if lo > 0 else hi / 100.0
    nivel = math.sqrt(lo_ef * hi)
    sigma_total = math.log(hi / lo_ef) / (2.0 * Z_P90)
    ruido = math.sqrt(max(sigma_total ** 2 - (EXPONENTE_PRECIO * SIGMA_PRECIOS) ** 2, RUIDO_MINIMO ** 2))
    return nivel, ruido, COLA_MAXIMA * hi


def centro_por_precio(precio: float, minimo: float, maximo: float) -> float:
    """Locate tipico (mediana del sorteo) para ese precio de accion:
    nivel x (precio / 2 $)^0,6."""
    nivel, _, _ = parametros_banda(minimo, maximo)
    if nivel <= 0:
        return 0.0
    p = max(float(precio or 0.0), 0.01)
    return nivel * (p / PRECIO_MEDIANO) ** EXPONENTE_PRECIO


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
    ensenarlas en el trade): referencia, centro (el tipico a ese precio) y el
    ruido de la banda.
    """
    _nivel, ruido, techo = parametros_banda(minimo, maximo)
    centro = centro_por_precio(precio_ref, minimo, maximo)
    if centro <= 0:
        precio = 0.0
    else:
        # Lognormal centrado en `centro`: multiplicativo, asi que la cola larga
        # queda hacia arriba (los dias carisimos existen, los negativos no).
        factor = math.exp(_rng(seed, ticker, fecha).gauss(0.0, ruido))
        precio = min(techo, max(SUELO_PAQUETE, centro * factor))
    return {
        "precio": round(precio, 4),
        "precio_ref": round(float(precio_ref or 0.0), 4),
        "centro": round(centro, 4),
        "ruido": round(ruido, 4),
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
