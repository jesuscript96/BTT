"""Estrategias compartidas entre devs (pestana "Compartidas" del backtester).

Prefijo propio `/api/shared-strategies` a proposito: bajo `/api/strategies`
la ruta `GET /{strategy_id}` se comeria `/shared` como si fuera un id.

El import no vive aqui: el frontend llama al `POST /api/strategies/` normal
con `{name, description, ...definition}`, reusando toda la validacion Pydantic
y el flujo de guardado (copia nueva, siempre).
"""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_user_id, scope_clause
from app.database import get_user_db_connection
from app.services import shared_strategies as svc

router = APIRouter()


class ShareRequest(BaseModel):
    strategy_id: str


@router.get("/")
def list_shared():
    """Ficheros compartidos de TODOS los devs + que subcarpeta es la tuya
    (para que la UI sepa cuales puede quitar)."""
    return {"owner": svc.shared_owner(), "strategies": svc.list_shared()}


@router.post("/")
def share_strategy(body: ShareRequest, user_id: Optional[str] = Depends(get_current_user_id)):
    """Vuelca una de TUS estrategias guardadas a un JSON en tu subcarpeta de
    `estrategias_compartidas/`. Re-compartir sobreescribe el mismo fichero."""
    scope_sql, scope_params = scope_clause(user_id)
    con = get_user_db_connection(read_only=True)
    try:
        row = con.execute(
            f"SELECT name, description, definition FROM strategies WHERE id = ?{scope_sql}",
            [body.strategy_id, *scope_params],
        ).fetchone()
    finally:
        con.close()
    if not row:
        raise HTTPException(status_code=404, detail="Strategy not found")

    definition = json.loads(row[2]) if isinstance(row[2], str) else (row[2] or {})
    try:
        return svc.write_shared(
            name=row[0] or "",
            description=row[1],
            source_strategy_id=body.strategy_id,
            definition=definition,
        )
    except svc.InvalidSharedFilename as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{filename}")
def delete_shared(filename: str):
    """Quita del repo uno de TUS ficheros compartidos (los del otro dev no)."""
    try:
        svc.delete_shared(filename)
    except svc.InvalidSharedFilename as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"status": "success", "deleted": filename}
