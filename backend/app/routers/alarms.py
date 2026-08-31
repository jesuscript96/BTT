"""API de alarmas del Screener.

Interno de la app: NO se expone por la API comercial (`api_public`), igual que el
resto del Screener. Todas las lecturas van filtradas por dueño en `store`; aquí
solo se resuelve quién pregunta.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app.auth import get_current_user_id
from app.services.alarms import fields as AF
from app.services.alarms import store, telegram
from app.services.alarms.engine import alarm_engine
from app.services.alarms.evaluator import RuleError, mode_of, normalize_conditions

logger = logging.getLogger("btt.alarms.api")

router = APIRouter(prefix="/api/alarms", tags=["Alarms"])


# ── Modelos ──────────────────────────────────────────────────────────────────
class AlarmDefinition(BaseModel):
    model_config = {"extra": "allow"}

    conditions: List[Dict[str, Any]] = Field(default_factory=list)
    universe: List[Dict[str, Any]] = Field(default_factory=list)
    watchlist: List[str] = Field(default_factory=list)
    window: Optional[Dict[str, str]] = None
    cooldown: Optional[Dict[str, Any]] = None
    sizing: Optional[Dict[str, Any]] = None
    channels: Optional[Dict[str, bool]] = None


class AlarmPayload(BaseModel):
    name: str
    side: str = "long"
    enabled: bool = True
    definition: AlarmDefinition


class AlarmPatch(BaseModel):
    name: Optional[str] = None
    side: Optional[str] = None
    enabled: Optional[bool] = None
    definition: Optional[AlarmDefinition] = None


def _validate(definition: Dict[str, Any]) -> Dict[str, Any]:
    """Valida la definición y le añade el modo deducido.

    El usuario nunca elige si su alarma es instantánea o al cierre de barra: sale
    de los campos que ha usado. Se guarda calculado para que la ficha lo enseñe
    sin tener que recompilar."""
    try:
        conditions = normalize_conditions(definition.get("conditions"))
        normalize_conditions(definition.get("universe"))
    except RuleError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if not conditions:
        raise HTTPException(status_code=422,
                            detail="Una alarma necesita al menos una condición.")
    out = dict(definition)
    out["mode"] = mode_of(conditions)
    return out


# ── Catálogo ─────────────────────────────────────────────────────────────────
@router.get("/catalog")
def get_catalog():
    """Campos y operadores que entiende el constructor de reglas."""
    return AF.catalog()


@router.get("/status")
def get_status():
    return alarm_engine.status()


# ── CRUD ─────────────────────────────────────────────────────────────────────
@router.get("")
def list_alarms(user_id: Optional[str] = Depends(get_current_user_id)):
    return {"alarms": store.list_alarms(user_id)}


@router.post("", status_code=201)
def create_alarm(payload: AlarmPayload,
                 user_id: Optional[str] = Depends(get_current_user_id)):
    definition = _validate(payload.definition.model_dump())
    return store.create_alarm(user_id, payload.name.strip() or "Alarma sin nombre",
                              payload.side, definition, payload.enabled)


@router.get("/{alarm_id}")
def get_alarm(alarm_id: str, user_id: Optional[str] = Depends(get_current_user_id)):
    alarm = store.get_alarm(user_id, alarm_id)
    if alarm is None:
        # 404 también cuando existe pero es de otro: no se filtra su existencia.
        raise HTTPException(status_code=404, detail="Alarma no encontrada")
    return alarm


@router.put("/{alarm_id}")
def update_alarm(alarm_id: str, patch: AlarmPatch,
                 user_id: Optional[str] = Depends(get_current_user_id)):
    definition = _validate(patch.definition.model_dump()) if patch.definition else None
    updated = store.update_alarm(user_id, alarm_id, name=patch.name, side=patch.side,
                                 definition=definition, enabled=patch.enabled)
    if updated is None:
        raise HTTPException(status_code=404, detail="Alarma no encontrada")
    return updated


@router.delete("/{alarm_id}")
def delete_alarm(alarm_id: str, user_id: Optional[str] = Depends(get_current_user_id)):
    if not store.delete_alarm(user_id, alarm_id):
        raise HTTPException(status_code=404, detail="Alarma no encontrada")
    return {"deleted": True}


# ── Señales (el panel llega en fase 2; el registro existe desde hoy) ─────────
@router.get("/events/list")
def list_events(session_date: Optional[str] = Query(default=None),
                limit: int = Query(default=200, le=1000),
                user_id: Optional[str] = Depends(get_current_user_id)):
    return {"events": store.list_events(user_id, session_date, limit)}


# ── Reproducción sobre un día histórico ──────────────────────────────────────
class ReplayPayload(BaseModel):
    ticker: str
    date: str                      # YYYY-MM-DD, sesión ET
    deliver: bool = False          # además, mandar la primera señal a tu Telegram


@router.post("/{alarm_id}/replay")
async def replay(alarm_id: str, payload: ReplayPayload,
                 user_id: Optional[str] = Depends(get_current_user_id)):
    """Pasa un día real por el motor y devuelve lo que HABRÍA avisado.

    Existe porque Massive solo admite una conexión WS por API key: si QA y
    producción levantan las dos el screener con la misma clave, se expulsan en
    bucle y la rama de QA se queda sin manera de probar alarmas de verdad. Esto
    ejercita el motor real —mismo anclaje a las 04:00, mismo VWAP, mismo
    enfriamiento— sin tocar el WebSocket, a cualquier hora y también en fin de
    semana.

    No es un backtest: no simula ejecuciones ni calcula rendimiento.
    """
    from app.services.alarms.replay import ReplayError, replay_alarm

    alarm = store.get_alarm(user_id, alarm_id)
    if alarm is None:
        raise HTTPException(status_code=404, detail="Alarma no encontrada")
    try:
        result = await replay_alarm(alarm, payload.ticker, payload.date)
    except ReplayError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:  # noqa: BLE001
        logger.warning("[ALARMS] replay falló: %s", e)
        raise HTTPException(status_code=502, detail="No se pudieron traer los datos históricos.")

    # `deliver` manda UNA señal al Telegram del propio usuario, para ver el
    # mensaje real. Va marcada como reproducción para que no se confunda con una
    # señal en vivo.
    if payload.deliver and result["signals"]:
        link = store.get_link(user_id)
        if link and not link.get("broken"):
            first = result["signals"][0]
            await telegram.send_message(
                link["chat_id"],
                f"🧪 <b>Reproducción</b> · {payload.ticker} {payload.date}\n"
                f"<i>No es una señal en vivo</i>\n\n{first['message']}",
            )
            result["delivered"] = True
    return result


# ── Telegram ─────────────────────────────────────────────────────────────────
@router.get("/telegram/status")
def telegram_status(user_id: Optional[str] = Depends(get_current_user_id)):
    return {"configured": telegram.is_configured(), "link": store.get_link(user_id)}


@router.post("/telegram/link")
async def telegram_link(user_id: Optional[str] = Depends(get_current_user_id)):
    """Devuelve el deep-link de vinculación.

    No se pide el @usuario: un bot de Telegram solo puede escribir a quien le haya
    escrito primero, así que hace falta que la persona pulse START. El token es de
    un solo uso y caduca en minutos."""
    if not telegram.is_configured():
        raise HTTPException(status_code=503,
                            detail="El bot de Telegram no está configurado en este entorno.")
    data = await asyncio.to_thread(store.create_link_token, user_id)
    url = await telegram.deep_link(data["token"])
    if not url:
        raise HTTPException(status_code=503, detail="No se pudo contactar con Telegram.")
    return {"url": url, "expires_at": data["expires_at"], "ttl_minutes": data["ttl_minutes"]}


@router.delete("/telegram/link")
def telegram_unlink(user_id: Optional[str] = Depends(get_current_user_id)):
    store.unlink(user_id)
    return {"unlinked": True}


@router.post("/telegram/test")
async def telegram_test(user_id: Optional[str] = Depends(get_current_user_id)):
    """Aviso de prueba.

    Configuras una alarma un martes y puede que no salte nada hasta el jueves: sin
    esto no sabrías si está mal configurada o si simplemente no hubo setup."""
    link = store.get_link(user_id)
    if not link or link.get("broken"):
        raise HTTPException(status_code=400, detail="No hay ningún Telegram conectado.")
    ok = await telegram.send_message(
        link["chat_id"],
        "🔔 <b>Aviso de prueba</b>\n\nSi lees esto, tus alarmas de Edgecute "
        "llegarán a este chat.\n\n<i>Prueba manual · no es una señal</i>",
    )
    if not ok:
        raise HTTPException(status_code=502, detail="Telegram rechazó el envío.")
    return {"sent": True}


# ── Stream en vivo hacia el navegador ────────────────────────────────────────
@router.websocket("/live")
async def alarms_live(websocket: WebSocket, token: Optional[str] = Query(default=None)):
    """Empuja al navegador las alarmas del usuario conectado.

    El filtro por `user_id` es la única cosa que separa los avisos de un usuario
    de los de otro en este canal, así que se resuelve del token firmado de Clerk
    y nunca de nada que mande el cliente."""
    from app.auth.clerk import AUTH_ENABLED, verify_clerk_token

    user_id: Optional[str] = None
    if AUTH_ENABLED:
        if not token:
            await websocket.close(code=4401)
            return
        try:
            claims = verify_clerk_token(token)
            user_id = claims.get("sub")
        except Exception:  # noqa: BLE001
            await websocket.close(code=4401)
            return
        if not user_id:
            await websocket.close(code=4401)
            return

    owner = store._owner(user_id)
    await websocket.accept()
    queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue(maxsize=100)
    loop = asyncio.get_running_loop()

    def _on_alarm(event: Dict[str, Any]) -> None:
        if event.get("user_id") != owner:
            return
        payload = {k: v for k, v in event.items() if k != "user_id"}
        loop.call_soon_threadsafe(_offer, payload)

    def _offer(payload: Dict[str, Any]) -> None:
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass

    alarm_engine.add_listener(_on_alarm)
    try:
        await websocket.send_json({"type": "hello", "status": alarm_engine.status()})
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        logger.debug("[ALARMS] ws cliente: %s", e)
    finally:
        alarm_engine.remove_listener(_on_alarm)
