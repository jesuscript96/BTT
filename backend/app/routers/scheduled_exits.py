# -*- coding: utf-8 -*-
"""Router de la SALIDA PROGRAMADA CONDICIONAL (2026-09-28).

Solo expone el estado del flag para que la UI ofrezca (o no) la sección.
Gated por SCHEDULED_EXITS_ENABLED, APAGADO por defecto (mismo patrón que
ROBUSTNESS_ENABLED / GAPPERS_ACTIVE_ENABLED). No toca datos ni ejecuta nada.
"""
import os

from fastapi import APIRouter

router = APIRouter()


def _enabled() -> bool:
    return os.getenv("SCHEDULED_EXITS_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


@router.get("/")
def estado():
    return {"enabled": _enabled()}
