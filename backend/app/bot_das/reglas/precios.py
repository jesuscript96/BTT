"""Aritmética de precios en Decimal: ticks, puntos medios, techos, tramo y ruta.

QUÉ HACE. Las cuentas de precio que necesitan todas las reglas: convertir el
float del `Evento` UNA vez (`de_float`), redondear al tick (regla 612: 0,01 $
desde 1 $ y 0,0001 $ por debajo), el punto medio bid-ask redondeado hacia
arriba de R-B-01 v3, techos y suelos porcentuales redondeados hacia el lado
permisivo, el tramo de precio y la ruta de cada acción según la tabla de
rutas del 24-sep (por tramo y, en pennies, por hora).

POR QUÉ ESTÁ AQUÍ. Injerto A §8.1: 10 · 1,03 = 10,299999… en coma flotante y
DAS recibe «10.3» o nada. Todo precio es `Decimal` y ningún resultado de este
módulo es `float`. Es lógica PURA (sin reloj, sin I/O): recibe la hora ET
como parámetro.

LAS TRAMPAS.
  * `Decimal(str(x))`, nunca `Decimal(x)`: `Decimal(0.1)` es
    0.1000000000000000055511151231257827…; `Decimal(str(0.1))` es 0.1.
  * NaN, ±inf, None y bool no son precios: `de_float` lanza `ValueError`.
  * Con spread de 1 tick no hay punto medio: la venta va AL ASK (se une al
    ask, sigue agregando); con 2 ticks, bid + 1 tick (Jaume, 24-sep).
  * El tick del resultado es el del precio de ENTRADA de `al_tick`: un punto
    medio de 0,99995 sube a 1,0000, que también está al tick de céntimos.
  * Un libro cruzado (ask < bid) no es un precio válido: se lanza
    `ValueError` y el decisor pausa ese ticker (H-5) en vez de mandar una
    orden a un precio inventado.
  * La ruta de cruce en pennies cambia a las 07:00 ET (EDGA cerrada de 04:00
    a 07:00): se compara hora y minuto de `hora_et`, que debe venir ya en ET
    (es lo que devuelve `reloj.ahora()`).
"""
from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.bot_das.tipos import al_tick, tick_de

ACCIONES_RUTA = ("agregar", "cruzar", "stop", "halt")
_CIEN = Decimal("100")
_HORA_EDGA = (7, 0)           # tabla de rutas: EDGA solo desde las 07:00 ET; antes, MIAX


def de_float(x: float | int | str) -> Decimal:
    """`Decimal(str(x))` (injerto A §8.1). NaN, ±inf, None, bool o texto no numérico → ValueError.

    Es el ÚNICO punto por el que un float del `Evento` (precio, stop) entra
    en la aritmética del bot. Un `Decimal` finito pasa tal cual.
    """
    if x is None or isinstance(x, bool):
        raise ValueError(f"no es un precio: {x!r}")
    if isinstance(x, Decimal):
        resultado = x
    elif isinstance(x, float):
        if not math.isfinite(x):
            raise ValueError(f"precio no finito: {x!r}")
        resultado = Decimal(str(x))
    elif isinstance(x, int):
        resultado = Decimal(x)
    elif isinstance(x, str):
        try:
            resultado = Decimal(x.strip())
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"texto no numérico: {x!r}") from exc
    else:
        raise ValueError(f"tipo no admitido para un precio: {type(x).__name__}")
    if not resultado.is_finite():
        raise ValueError(f"precio no finito: {x!r}")
    return resultado


def redondear_arriba(p: Decimal) -> Decimal:
    """Al tick hacia arriba (`al_tick(p, True)` de tipos)."""
    return al_tick(p, True)


def redondear_abajo(p: Decimal) -> Decimal:
    """Al tick hacia abajo (`al_tick(p, False)` de tipos)."""
    return al_tick(p, False)


def punto_medio_arriba(bid: Decimal, ask: Decimal) -> Decimal:
    """ceil((bid + ask) / 2 al tick): spread 1 tick → ask; 2 ticks → bid + 1 tick (R-B-01 v3, 24-sep).

    Es el precio de la venta que AGREGA: descansa en el libro por encima del
    bid y mejora el ask. Lanza ValueError con libro cruzado o precios ≤ 0.
    """
    _comprobar_libro(bid, ask)
    return redondear_arriba((bid + ask) / 2)


def punto_medio_abajo(bid: Decimal, ask: Decimal) -> Decimal:
    """floor((bid + ask) / 2 al tick): para compras que agregan (TP / salida por hora, R-D-08, R-D-03 v2)."""
    _comprobar_libro(bid, ask)
    return redondear_abajo((bid + ask) / 2)


def con_techo(precio: Decimal, pct: Decimal, arriba: bool) -> Decimal:
    """precio · (1 ± pct/100) redondeado hacia el lado PERMISIVO.

    `arriba=True` → techo de una COMPRA (R-D-03 v2 +3 %, R-D-06 +5 %): se
    redondea hacia arriba, que es el lado que deja llenar. `arriba=False` →
    suelo de una VENTA: se redondea hacia abajo. `pct` ≥ 0.
    """
    _comprobar_positivo("precio", precio)
    if not pct.is_finite() or pct < 0:
        raise ValueError(f"pct debe ser ≥ 0: {pct!r}")
    factor = (_CIEN + pct) / _CIEN if arriba else (_CIEN - pct) / _CIEN
    return al_tick(precio * factor, arriba)


def bajo_bid(bid: Decimal, pct: Decimal) -> Decimal:
    """bid · (1 − pct/100) redondeado abajo: el cruce de R-B-01 v3 (bid × (1 − 0,5 %))."""
    return con_techo(bid, pct, arriba=False)


def tramo(precio: Decimal) -> str:
    """"ge_1" desde 1 $ (tick 0,01), "lt_1" por debajo (tick 0,0001): regla 612 y tabla de rutas."""
    return "ge_1" if tick_de(precio) == Decimal("0.01") else "lt_1"


def ruta(cfg_rutas: dict, accion: str, precio: Decimal, hora_et: datetime) -> str:
    """Ruta de la tabla del 24-sep (bloque «rutas» de la config, §7) para `accion` ∈ ACCIONES_RUTA.

    agregar → rutas.agregar[ge_1 | lt_1]; cruzar → rutas.cruzar[ge_1] o, en
    pennies, rutas.cruzar[lt_1_desde_0700] si `hora_et` ≥ 07:00 ET y si no
    rutas.cruzar[lt_1_antes_0700] (EDGA cerrada de 04:00 a 07:00); stop →
    rutas.stop (R-C-01: los guarda DAS); halt → rutas.halt (EP-2, ruta OPEN).
    Lanza ValueError con una acción desconocida o una ruta sin configurar.
    """
    if accion not in ACCIONES_RUTA:
        raise ValueError(f"accion desconocida: {accion!r} (admitidas: {', '.join(ACCIONES_RUTA)})")
    if accion == "agregar":
        clave: tuple[str, ...] = ("agregar", tramo(precio))
    elif accion == "cruzar":
        if tramo(precio) == "ge_1":
            clave = ("cruzar", "ge_1")
        elif (hora_et.hour, hora_et.minute) >= _HORA_EDGA:
            clave = ("cruzar", "lt_1_desde_0700")
        else:
            clave = ("cruzar", "lt_1_antes_0700")
    else:
        clave = (accion,)
    valor: object = cfg_rutas
    for parte in clave:
        if not isinstance(valor, dict) or parte not in valor:
            raise ValueError(f"ruta no configurada: {'.'.join(clave)}")
        valor = valor[parte]
    if not isinstance(valor, str) or not valor.strip():
        raise ValueError(f"ruta vacía: {'.'.join(clave)}")
    return valor


def distancia_pct(a: Decimal, b: Decimal) -> Decimal:
    """(a − b) / b · 100: distancia de `a` respecto a la referencia `b` (retraso R-A-01, caída del bid R-B-01, B20 bis)."""
    if not (a.is_finite() and b.is_finite()):
        raise ValueError(f"precios no finitos: {a!r}, {b!r}")
    if b == 0:
        raise ValueError("referencia cero: no hay distancia porcentual")
    return (a - b) / b * _CIEN


def subida_pct(desde: Decimal, hasta: Decimal) -> Decimal:
    """(hasta − desde) / desde · 100: subida desde un precio (R-F-05 T1, R-C-03, informe BS)."""
    return distancia_pct(hasta, desde)


def _comprobar_positivo(nombre: str, valor: Decimal) -> None:
    if not valor.is_finite() or valor <= 0:
        raise ValueError(f"{nombre} debe ser un precio finito > 0: {valor!r}")


def _comprobar_libro(bid: Decimal, ask: Decimal) -> None:
    _comprobar_positivo("bid", bid)
    _comprobar_positivo("ask", ask)
    if ask < bid:
        raise ValueError(f"libro cruzado: bid {bid} > ask {ask}")
