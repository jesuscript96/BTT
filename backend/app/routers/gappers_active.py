# -*- coding: utf-8 -*-
"""Estado del indicador «Gappers activos (+X %)» para la UI.

GET /api/gappers-active → {"enabled": bool, "levels": [int...], "table_ok": bool}

- enabled = GAPPERS_ACTIVE_ENABLED (apagado por defecto, como ROBUSTNESS_ENABLED).
  La UI NO ofrece el indicador si enabled es false: sin flag, nada cambia.
- levels = niveles X precomputados en la tabla (los únicos que el selector
  de la condición ofrece).
- table_ok = la tabla parquet existe en GAPPERS_ACTIVE_TABLE.

Solo lectura de entorno/disco: no toca DuckDB ni nada del bot.
"""
import os

from fastapi import APIRouter

from app.services.gappers_active import (
    GAPPERS_ACTIVE_LEVELS, gappers_activos_enabled, _ruta_tabla)

router = APIRouter()


@router.get("")
def estado_gappers_active():
    ruta = _ruta_tabla()
    return {
        "enabled": gappers_activos_enabled(),
        "levels": list(GAPPERS_ACTIVE_LEVELS),
        "table_ok": os.path.exists(ruta) and bool(GAPPERS_ACTIVE_LEVELS),
        "table_path": ruta,
    }
