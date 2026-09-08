"""Locates: la banda Monte Carlo sobre el precio del locate.

ADITIVO y sin estado. Recibe los trades de la corrida abierta (no depende de
que exista el job) y devuelve percentiles por fecha: nunca las N curvas crudas.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import locates_banda

logger = logging.getLogger("btt.locates")

router = APIRouter(prefix="/api/locates", tags=["Locates"])


class TradeBanda(BaseModel):
    ticker: str
    fecha: str
    size: float = 0.0
    dir: str = "Short"
    precio_ref: float = 0.0
    pnl: float = 0.0


class PeticionBanda(BaseModel):
    trades: list[TradeBanda]
    init_cash: float = 10000.0
    minimo: float = Field(ge=0)
    maximo: float = Field(ge=0)
    n_semillas: int = Field(default=50, ge=1, le=locates_banda.MAX_SEMILLAS)
    semilla_base: int = 1
    semilla_actual: int | None = None


@router.post("/banda")
def banda(pet: PeticionBanda):
    if not pet.trades:
        raise HTTPException(status_code=400, detail="No hay operaciones")
    if pet.maximo <= pet.minimo:
        raise HTTPException(status_code=400, detail="El máximo del rango debe superar al mínimo")
    try:
        out = locates_banda.banda(
            [t.model_dump() for t in pet.trades], pet.init_cash, pet.minimo, pet.maximo,
            pet.n_semillas, pet.semilla_base, pet.semilla_actual,
        )
    except Exception as e:
        logger.exception("[locates] fallo calculando la banda")
        raise HTTPException(status_code=500, detail=f"No se pudo calcular la banda: {e}")
    if "error" in out:
        raise HTTPException(status_code=422, detail=out["error"])
    return out
