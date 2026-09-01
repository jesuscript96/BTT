"""Cuadro de mandos del bot de alertas: que se vigila y con cuanto riesgo.

    GET  /api/bot-alerts/strategies  -> estrategias del portfolio + su config
    POST /api/bot-alerts/watch       -> activar/desactivar y fijar el riesgo
    GET  /api/bot-alerts/vigiladas   -> lo que el BOT pide al arrancar el dia

Gated por BOT_ALERTS_ENABLED, APAGADO por defecto (regla R7): sin la variable
en el .env local los endpoints responden 503.

POR QUE EL BOT PREGUNTA POR HTTP en vez de leer users.duckdb: el backend tiene
ese fichero abierto en escritura y DuckDB no admite un segundo escritor. El bot
corre en su PROPIO proceso, asi que pide la configuracion por aqui. Como las
estrategias no se editan con el bot encendido, le basta con leerla al arrancar.
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import get_current_user_id, scope_clause
from app.database import get_user_db_connection, get_user_db_lock
from app.services import bot_alerts_service as bas
from app.services import bot_alerts_telegram as tg

router = APIRouter()


# Se lee EN CADA PETICION, no al importar: el import puede ocurrir antes de que
# load_dotenv() haya poblado el entorno (leccion de lake_update.py).
def _enabled() -> bool:
    return os.getenv("BOT_ALERTS_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def _guard() -> None:
    if not _enabled():
        raise HTTPException(
            status_code=503,
            detail="Bot de alertas desactivado (BOT_ALERTS_ENABLED)",
        )


@router.get("/strategies")
def listar(user_id: Optional[str] = Depends(get_current_user_id)):
    """Una fila por estrategia del cubo `portfolio`, con su interruptor."""
    _guard()
    con = get_user_db_connection(read_only=True)
    scope_sql, scope_params = scope_clause(user_id)
    try:
        return bas.listar_candidatas(con, scope_sql, scope_params)
    finally:
        con.close()


class WatchReq(BaseModel):
    strategy_id: str
    activa: bool
    # gt=0 y no ge=0: un riesgo de cero daria cero acciones en toda alerta, que
    # es un bot encendido que no sirve para nada. Mejor rechazarlo aqui.
    riesgo_usd: float = Field(gt=0)


@router.post("/watch")
def guardar(req: WatchReq, user_id: Optional[str] = Depends(get_current_user_id)):
    """Activa o desactiva una estrategia y fija su riesgo por operacion."""
    _guard()
    with get_user_db_lock():
        con = get_user_db_connection()
        scope_sql, scope_params = scope_clause(user_id)
        try:
            existe = con.execute(
                f"SELECT id FROM strategies WHERE id = ?{scope_sql}",
                [req.strategy_id, *scope_params],
            ).fetchone()
            if not existe:
                raise HTTPException(status_code=404, detail="Estrategia no encontrada")

            # Solo se vigila lo que esta en el portfolio o en la incubadora. Sin
            # esta comprobacion se podria activar cualquier estrategia del baul,
            # y el bot la ignoraria luego en silencio (`vigiladas` refiltra).
            from app.services import portfolio_lab_service as pls
            cuadros = pls.get_assignments(con).get(req.strategy_id, [])
            if not any(c in cuadros for c in bas.CUBOS):
                raise HTTPException(
                    status_code=400,
                    detail="La estrategia no esta en el portfolio ni en la incubadora; "
                           "anyadela a uno de los dos antes de vigilarla",
                )

            return bas.set_watch(con, req.strategy_id, req.activa, req.riesgo_usd)
        finally:
            con.close()


class EventoIn(BaseModel):
    """Un aviso publicado por el bot.

    El `id` lo pone el bot y es estable (ticker+estrategia+momento+tipo): asi,
    si reintenta tras un fallo de red, no se duplican filas.
    """
    id: str
    fecha: str
    momento: str
    tipo: str
    ticker: str
    strategy_id: str
    estrategia: Optional[str] = None
    direccion: Optional[str] = None
    precio: Optional[float] = None
    acciones: Optional[float] = None
    stop: Optional[float] = None
    riesgo_usd: Optional[float] = None
    motivo: Optional[str] = None
    nivel: Optional[int] = None
    accion_piramide: Optional[str] = None
    posicion_total: Optional[float] = None
    origen: str = "portfolio"      # portfolio | incubadora
    modo: str = "vivo"             # vivo | reproduccion


class EventosReq(BaseModel):
    eventos: list[EventoIn]


@router.post("/eventos")
def publicar_eventos(req: EventosReq):
    """El BOT publica aqui sus avisos. No lo llama la pagina.

    El bot corre en otro proceso y no puede escribir en users.duckdb (el backend
    lo tiene abierto y DuckDB no admite un segundo escritor), asi que los manda
    por HTTP y el backend los guarda.
    """
    _guard()
    with get_user_db_lock():
        con = get_user_db_connection()
        try:
            n = bas.guardar_eventos(con, [e.model_dump() for e in req.eventos])
            return {"guardados": n}
        finally:
            con.close()


@router.get("/eventos")
def leer_eventos(fecha: Optional[str] = None, limite: int = 500):
    """Avisos de una fecha; sin fecha, los ultimos."""
    _guard()
    con = get_user_db_connection(read_only=True)
    try:
        return {"eventos": bas.listar_eventos(con, fecha, limite)}
    finally:
        con.close()


@router.get("/fechas")
def leer_fechas():
    """Dias con avisos guardados, para el selector del historico."""
    _guard()
    con = get_user_db_connection(read_only=True)
    try:
        return {"fechas": bas.fechas_con_eventos(con)}
    finally:
        con.close()


@router.delete("/eventos")
def limpiar_eventos(antes_de: str):
    """Borra los avisos anteriores a una fecha. Manual, nunca automatico."""
    _guard()
    with get_user_db_lock():
        con = get_user_db_connection()
        try:
            return {"borrados": bas.borrar_eventos_antes(con, antes_de)}
        finally:
            con.close()


@router.get("/estado")
def leer_estado():
    """Si el bot deberia estar vigilando y cuando dio senales de vida."""
    _guard()
    con = get_user_db_connection(read_only=True)
    try:
        estado = bas.get_estado(con)
        estado["telegram"] = tg.probar() if os.getenv("TELEGRAM_BOT_TOKEN") else {
            "ok": False, "detalle": "sin token configurado", "enviando": False,
        }
        return estado
    finally:
        con.close()


class EstadoReq(BaseModel):
    vigilando: bool


@router.post("/estado")
def cambiar_estado(req: EstadoReq):
    """El interruptor de la pagina.

    NO arranca ni mata ningun proceso: solo deja escrito si el bot debe estar
    vigilando. El bot lo consulta y actua. Asi la pagina no necesita hablar con
    un proceso que vive aparte.
    """
    _guard()
    with get_user_db_lock():
        con = get_user_db_connection()
        try:
            return bas.set_vigilando(con, req.vigilando)
        finally:
            con.close()


class LatidoReq(BaseModel):
    tickers: int = 0
    fuente: str = ""
    detalle: str = ""


@router.post("/latido")
def latido(req: LatidoReq):
    """El BOT dice que sigue vivo. Sin esto no se distingue apagado de colgado."""
    _guard()
    with get_user_db_lock():
        con = get_user_db_connection()
        try:
            bas.latido(con, req.tickers, req.fuente, req.detalle)
            return {"ok": True}
        finally:
            con.close()


@router.get("/vigiladas")
def vigiladas(user_id: Optional[str] = Depends(get_current_user_id)):
    """Definicion completa + riesgo de cada estrategia activa. Lo consume el bot.

    Devuelve tambien la ventana operativa de cada una, que es lo que permite al
    bot saber si un cierre "EOD" del simulador es el fin de dia de verdad o solo
    el borde del frame que tiene hasta ahora.
    """
    _guard()
    con = get_user_db_connection(read_only=True)
    scope_sql, scope_params = scope_clause(user_id)
    try:
        items = bas.vigiladas(con, scope_sql, scope_params)
        return {"total": len(items), "estrategias": items}
    finally:
        con.close()
