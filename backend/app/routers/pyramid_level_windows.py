# -*- coding: utf-8 -*-
"""Router de la FRANJA HORARIA PROPIA POR NIVEL DE PIRÁMIDE (2026-09-30).

Solo expone el estado del flag para que la UI ofrezca (o no) el campo.
Gated por PYRAMID_LEVEL_WINDOWS_ENABLED, APAGADO por defecto (mismo patrón que
SCHEDULED_EXITS_ENABLED). No toca datos ni ejecuta nada.
"""
from fastapi import APIRouter

from app.services.strategy_engine import pyr_ventanas_nivel_activas

router = APIRouter()


@router.get("/")
def estado():
    return {"enabled": pyr_ventanas_nivel_activas()}
