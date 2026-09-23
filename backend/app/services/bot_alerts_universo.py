"""Evalua el FILTRO DE UNIVERSO de una estrategia contra el mercado en vivo.

El radar ya no usa un umbral inventado: usa el de cada estrategia. Si 1B pide
`PM High Gap % >= 50`, se vigila lo que pase de 50; si otra pide 30, lo que pase
de 30 — y un ticker puede entrar por las dos, cada una con su etiqueta.

QUE ES UN FILTRO DE UNIVERSO Y QUE NO. Es la condicion que decide si un
ticker-dia es CANDIDATO, y en `1B` es acumulada: `PM High Gap %` es un maximo,
asi que una vez cumplida no se deshace aunque el precio retroceda. Las
condiciones de ENTRADA (el minimo de la vela anterior contra el VWAP, el cierre
bajo el minimo previo, el dollar volume, el cuerpo de la vela) son otra cosa:
cambian vela a vela y de ellas se encarga el motor, no el radar.

LO QUE NO SE PUEDE SABER EN PREMERCADO. `Open Gap %` necesita el precio de
apertura de la sesion regular: **no existe antes de las 09:30**. Las estrategias
que lo usan (2.1B, 3B) no son vigilables hasta esa hora, y aqui se dice en vez
de inventar un valor.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("btt.bot_alerts.universo")

# Metricas que se saben calcular en vivo. Las demas se declaran NO EVALUABLES en
# vez de darse por buenas: dar por cumplida una condicion que no se ha
# comprobado es peor que no vigilar el ticker — avisaria de lo que no toca.
SOPORTADAS = {
    "PM High Gap %": "PM High Gap %",
    "PMH Gap %": "PM High Gap %",
    "PM High Gap (%)": "PM High Gap %",
    "Current Gap %": "Current Gap %",
    "Current Gap (%)": "Current Gap %",
    "Open Gap %": "Open Gap %",
    "Gap %": "Open Gap %",
    "Premarket Volume": "Premarket Volume",
    "Volume": "Volume",
    "Price": "Price",
    "Previous Close": "Previous Close",
}

_OPS = {
    "GREATER_THAN": lambda a, b: a > b,
    "GREATER_THAN_OR_EQUAL": lambda a, b: a >= b,
    "LESS_THAN": lambda a, b: a < b,
    "LESS_THAN_OR_EQUAL": lambda a, b: a <= b,
    "EQUAL": lambda a, b: a == b,
    "NOT_EQUAL": lambda a, b: a != b,
}


def _num(v) -> Optional[float]:
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def reglas_de(definicion: dict) -> list[dict]:
    return list(((definicion or {}).get("universe_filters") or {}).get("rules") or [])


def analizar(definicion: dict) -> dict:
    """Que se puede vigilar de esta estrategia y que no.

    Se llama UNA vez al arrancar, para poder decirlo en el log y en la pagina en
    vez de que el usuario descubra por su cuenta que una estrategia no aparece.
    """
    reglas = reglas_de(definicion)
    evaluables, no_evaluables, solo_rth = [], [], []
    for r in reglas:
        m = str(r.get("metric") or "")
        interna = SOPORTADAS.get(m)
        if interna is None:
            no_evaluables.append(m)
        elif interna == "Open Gap %":
            solo_rth.append(m)
        else:
            evaluables.append(m)
    return {
        "reglas": len(reglas),
        "evaluables": evaluables,
        "no_evaluables": no_evaluables,
        # Se pueden evaluar, pero solo a partir de las 09:30.
        "solo_rth": solo_rth,
        "vigilable_en_premercado": bool(evaluables) and not no_evaluables and not solo_rth,
    }


def cumple(metricas: dict, definicion: dict) -> bool:
    """Si un ticker pasa el filtro de universo de esta estrategia.

    TODAS las reglas tienen que cumplirse. Una metrica a None —«todavia no se
    sabe»— hace que NO cumpla: nunca se da por buena una condicion sin
    comprobar.
    """
    reglas = reglas_de(definicion)
    if not reglas:
        return False          # sin filtro no hay universo que vigilar

    for r in reglas:
        interna = SOPORTADAS.get(str(r.get("metric") or ""))
        if interna is None:
            return False      # hay una regla que no se sabe evaluar
        valor = metricas.get(interna)
        objetivo = _num(r.get("value"))
        if valor is None or objetivo is None:
            return False
        op = _OPS.get(str(r.get("operator") or "GREATER_THAN_OR_EQUAL"))
        if op is None or not op(valor, objetivo):
            return False
    return True


def resumen_reglas(definicion: dict) -> str:
    """Las reglas en una linea, para el log y la pagina."""
    partes = []
    for r in reglas_de(definicion):
        simbolo = {
            "GREATER_THAN": ">", "GREATER_THAN_OR_EQUAL": "≥",
            "LESS_THAN": "<", "LESS_THAN_OR_EQUAL": "≤",
            "EQUAL": "=", "NOT_EQUAL": "≠",
        }.get(str(r.get("operator") or ""), "?")
        partes.append(f"{r.get('metric')} {simbolo} {r.get('value')}")
    return " y ".join(partes) if partes else "(sin filtro de universo)"
