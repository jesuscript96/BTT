"""Calculadora de locates para shorts (Edgie v1).

Determinista a propósito: el LLM NO debe hacer esta aritmética a ojo. Regla dura
del PRD: los locates se compran SIEMPRE en paquetes de 100 → ceil(shares/100),
nunca redondear hacia abajo. Ningún campo tiene valor por defecto.
"""

import math
from typing import Optional


def calc_locates(
    precio_entrada: float,
    precio_stop: float,
    coste_paquete: float,
    shares: Optional[float] = None,
    riesgo_dolares: Optional[float] = None,
) -> dict:
    """Calcula coste de locates y break-even de un short.

    - precio_stop debe ser > precio_entrada (short: el stop está por encima).
    - Se da `shares` (opción A) O `riesgo_dolares` (opción B); uno es obligatorio.
      En B: shares = round(riesgo / (stop - entrada)).
    Devuelve dict con todos los campos + `conclusion` (una frase).
    """
    if precio_entrada is None or precio_stop is None or coste_paquete is None:
        return {"error": "Faltan datos obligatorios: precio_entrada, precio_stop y coste_paquete."}
    if precio_stop <= precio_entrada:
        return {"error": "En un short el stop debe estar POR ENCIMA de la entrada (precio_stop > precio_entrada)."}

    riesgo_por_share = precio_stop - precio_entrada

    if shares is None and riesgo_dolares is None:
        return {"error": "Indica el número de acciones (shares) o el riesgo en dólares."}
    if shares is None:
        shares = round(riesgo_dolares / riesgo_por_share)
    shares = int(shares)
    if shares <= 0:
        return {"error": "El número de acciones resultante es 0; revisa los datos."}

    paquetes = math.ceil(shares / 100)                    # SIEMPRE hacia arriba
    coste_total_locates = paquetes * coste_paquete
    coste_locate_por_share = coste_total_locates / shares

    riesgo_total_sin_locates = riesgo_por_share * shares
    riesgo_total_con_locates = riesgo_total_sin_locates + coste_total_locates

    stop_pct = (riesgo_por_share / precio_entrada) * 100
    fade_break_even_locates = (coste_locate_por_share / precio_entrada) * 100
    fade_break_even_total = ((riesgo_por_share + coste_locate_por_share) / precio_entrada) * 100

    return {
        "shares": shares,
        "paquetes_locates": paquetes,
        "coste_paquete": round(coste_paquete, 4),
        "coste_total_locates": round(coste_total_locates, 2),
        "coste_locate_por_share": round(coste_locate_por_share, 4),
        "stop_loss_pct": round(stop_pct, 2),
        "riesgo_por_share": round(riesgo_por_share, 4),
        "riesgo_total_sin_locates": round(riesgo_total_sin_locates, 2),
        "riesgo_total_con_locates": round(riesgo_total_con_locates, 2),
        "fade_break_even_locates_pct": round(fade_break_even_locates, 2),
        "fade_break_even_total_pct": round(fade_break_even_total, 2),
        "conclusion": (
            f"Para que este trade tenga sentido, el precio necesita hacer un fade de "
            f"{round(fade_break_even_total, 2)}% (cubre locates + stop)."
        ),
    }
