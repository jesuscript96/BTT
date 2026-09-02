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

import asyncio
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app.auth import get_current_user_id, scope_clause
from app.database import get_user_db_connection, get_user_db_lock
from app.services import bot_alerts_service as bas
from app.services import bot_alerts_telegram as tg

router = APIRouter()
logger = logging.getLogger("btt.bot_alerts")


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
    # prealerta = la vela aun se esta formando; alerta = ha cerrado y se
    # confirma; descartada = la vela cerro y la senal se cayo. Los tres
    # comparten id, asi que el siguiente ACTUALIZA la fila del anterior en vez
    # de anyadir otra.
    estado: str = "alerta"


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
    """El BOT dice que sigue vivo. Sin esto no se distingue apagado de colgado.

    NI ABRE CONEXION NI TOMA EL CERROJO: el latido va a memoria. Llega cada 5 s
    y en este proyecto cada escritura bloquea a las demas — asi montado era la
    fuente de escritura mas frecuente de toda la aplicacion.
    """
    _guard()
    bas.latido(None, req.tickers, req.fuente, req.detalle)
    return {"ok": True}


class CandidatoRadar(BaseModel):
    ticker: str
    # De QUE estrategia viene la vigilancia, y por que regla entro. Un mismo
    # ticker puede aparecer por varias, cada una con su umbral.
    estrategia: str = ""
    metrica: str = ""
    valor: float = 0.0
    precio: float = 0.0
    volumen: float = 0.0
    prev_close: float = 0.0
    # Si el bot lo esta siguiendo de verdad o solo lo ve pasar (cupo lleno).
    seguido: bool = False


class RadarReq(BaseModel):
    candidatos: list[CandidatoRadar]


@router.post("/radar")
def publicar_radar(req: RadarReq):
    """El BOT publica a quien esta mirando. No lo llama la pagina.

    Va a memoria, no a la base: es una foto que se reemplaza cada 30 s y no
    interesa guardarla. Y cada escritura en DuckDB compite con las demas.
    """
    _guard()
    bas.set_radar([c.model_dump() for c in req.candidatos])
    return {"ok": True, "n": len(req.candidatos)}


@router.get("/radar")
def leer_radar():
    _guard()
    return bas.get_radar()


@router.websocket("/live")
async def live(websocket: WebSocket):
    """Empuja a la pagina en cuanto algo cambia.

    POR QUE NO VALE QUE LA PAGINA PREGUNTE: consultando cada 2 s, un aviso tarda
    hasta 2 s en aparecer. Telegram, que es un empujon directo, llega antes — y
    en una prealerta el margen util son segundos. Aqui se vigila un contador en
    memoria muchas veces por segundo (comparar un entero no cuesta nada y NO
    toca la base de datos) y se emite solo cuando de verdad ha cambiado algo.

    Se manda un primer paquete al conectar para que la pagina pinte sin esperar.
    """
    _guard()
    await websocket.accept()

    # El estado de Telegram se consulta UNA vez por conexion: es una llamada de
    # red a la API de Telegram y no cambia mientras la pagina esta abierta.
    # Meterla en cada envio anyadia medio segundo a cada aviso.
    tg_estado = tg.probar() if os.getenv("TELEGRAM_BOT_TOKEN") else {
        "ok": False, "detalle": "sin token configurado", "enviando": False,
    }

    def _paquete() -> dict:
        """Camino CALIENTE: memoria pura mientras la cache este viva.

        Solo se abre conexion si la cache esta fria (primer envio tras arrancar
        o tras una limpieza). En este proyecto no existen las conexiones de solo
        lectura, asi que abrir una en cada envio volveria a bloquear al bot.
        """
        estado = bas.estado_cacheado()
        eventos = bas.eventos_cacheados(None)
        if estado is None or eventos is None:
            con = get_user_db_connection(read_only=True)
            try:
                estado = bas.get_estado(con)
                eventos = bas.listar_eventos(con, None, 500)
            finally:
                con.close()
        return {
            "version": bas.version(),
            "estado": {**estado, "telegram": tg_estado},
            "eventos": eventos,
            "radar": bas.get_radar(),
        }

    ultima = -1
    try:
        while True:
            v = bas.version()
            if v != ultima:
                ultima = v
                await websocket.send_json(await asyncio.to_thread(_paquete))
            # 50 ms. Parece agresivo y no lo es: mientras no haya novedades esto
            # solo compara un entero en memoria — no toca la base de datos ni la
            # red. A 200 ms la latencia de punta a punta salia en 414 ms y el
            # aviso llegaba antes a Telegram que a la pantalla.
            await asyncio.sleep(0.05)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.debug("[BOT] ws cliente: %s", exc)


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
