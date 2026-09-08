"""Edge: el recorrido minuto a minuto que la pestana Edge necesita.

ADITIVO. No toca el motor ni ninguno de los tres ficheros que comparte el bot en
vivo (`market_frame`, `strategy_engine`, `portfolio_sim`): reconstruye el
recorrido por fuera, leyendo la misma cache de velas que ya usa `/api/candles`.

Las operaciones vienen en el POST y no del disco a proposito: asi funciona con
un resultado recien corrido, con uno del baul o con uno que el usuario tenga en
pantalla, sin depender de que exista el job. La RESPUESTA son solo agregados —
nunca el recorrido crudo, que con miles de operaciones tumba la conexion.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services import edge_service

logger = logging.getLogger("btt.edge")

router = APIRouter(prefix="/api/edge", tags=["Edge"])


class TradeEdge(BaseModel):
    ticker: str
    fecha: str
    entrada_ts: str
    salida_ts: str
    entrada: float
    dir: str
    motivo: str = ""
    sl: float = 0.0
    sl_dist: float = 0.0
    periodo: str = "?"


class PeticionRecorrido(BaseModel):
    dataset_id: str
    trades: list[TradeEdge]
    unidad: str = Field(default="R", pattern="^(R|pct)$")
    horizonte: int = Field(default=edge_service.HORIZONTE_POR_DEFECTO, ge=15, le=720)


@router.post("/recorrido")
def recorrido(pet: PeticionRecorrido):
    """Curva por minuto, deltas pareados entre horas y tiempo hasta el MFE.

    Es un calculo pesado (relee las velas de cada ticker-dia), asi que la pagina
    lo pide con un boton y no al abrir la pestana.
    """
    if not pet.trades:
        raise HTTPException(status_code=400, detail="No hay operaciones que reconstruir")
    try:
        out = edge_service.calcular_recorrido(
            pet.dataset_id,
            [t.model_dump() for t in pet.trades],
            unidad=pet.unidad,
            horizonte=pet.horizonte,
        )
    except Exception as e:
        logger.exception("[edge] fallo reconstruyendo el recorrido")
        raise HTTPException(status_code=500, detail=f"No se pudo reconstruir el recorrido: {e}")
    if "error" in out:
        raise HTTPException(status_code=422, detail=out["error"])
    return out
