"""Arranque del entorno: hace importable el motor desde fuera de `backend/`.

Importar ESTE modulo antes que cualquier `app.*`. Replica lo que hace el
backend al arrancar: cwd en `backend/` y el `.env` cargado ANTES de importar
el motor — `gcs_cache` lee `LOCAL_LAKE_DIR` a nivel de modulo y, sin el .env,
queda vacio y ningun mes de velas resuelve (medido en la fase 0).
"""
from __future__ import annotations

import logging
import os
import sys

BACKEND = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
DIR_TRABAJO = os.getenv("BTT_GENETICO_DIR", "D:/tmp/btt_genetico")

_preparado = False


def preparar() -> None:
    global _preparado
    if _preparado:
        return
    os.chdir(BACKEND)
    if BACKEND not in sys.path:
        sys.path.insert(0, BACKEND)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BACKEND, ".env"))

    # Con la salida por una tuberia Python usa cp1252 y cualquier caracter
    # fuera de ella (≥, →) aborta el proceso. Misma trampa que tumbo una
    # actualizacion del lago el 2026-08-20 (lake_update.py).
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    logging.basicConfig(level=logging.WARNING)
    for nombre in ("backtester", "backtester.db", "backtester.optimization", "app"):
        logging.getLogger(nombre).setLevel(logging.WARNING)
    # El listado de GCS falla con 403 en local (sin credenciales) y cae al lago
    # en disco: comportamiento normal aqui, solo ensucia la salida.
    logging.getLogger("backtester.cache").setLevel(logging.CRITICAL)
    os.makedirs(DIR_TRABAJO, exist_ok=True)
    _preparado = True


def rss_gb() -> float:
    import psutil
    return psutil.Process().memory_info().rss / 1e9


def ram_libre_gb() -> float:
    import psutil
    return psutil.virtual_memory().available / 1e9
