"""Que cromosoma usa una corrida: el del EXPLORADOR o el de MEJORAR.

Dos modos, dos especies de individuo, un solo motor genetico:

  - `explorar` (el de siempre, por defecto) -> `cromosoma.py`. Sortea
    condiciones del catalogo y construye la estrategia entera desde cero.
  - `mejorar`  (2026-09-06)                 -> `afinar.py`. Parte de UNA
    estrategia concreta y solo mueve las rutas que el usuario haya marcado.

TODO LO QUE NO SE PIDA EXPLICITAMENTE CAE EN `explorar`. Es deliberado: el
explorador funciona y no se toca, asi que el modo nuevo tiene que ser opt-in
por config. Una corrida antigua reanudada no lleva `modo` y sigue igual.
"""
from __future__ import annotations


def es_mejorar(config: dict) -> bool:
    return str((config or {}).get("modo", "explorar")).strip().lower() == "mejorar"


def modulo(config: dict):
    """El modulo de cromosoma que toca. Mismas funciones publicas en los dos."""
    if es_mejorar(config):
        from genetico import afinar
        return afinar
    from genetico import cromosoma
    return cromosoma


def receta(config: dict, individuo: dict) -> str:
    """La lectura humana, que es lo unico con firma distinta entre los dos.

    `afinar` necesita el config para poner etiquetas a los genes; `cromosoma`
    se basta con el individuo.
    """
    mod = modulo(config)
    if es_mejorar(config):
        return mod.receta(individuo, config)
    return mod.receta(individuo)
