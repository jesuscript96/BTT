"""Configuracion del bot de alertas: que estrategias vigila y con cuanto riesgo.

QUE ES ESTO. El cuadro de mandos lista las estrategias del cubo `portfolio` y
deja marcar cuales quiere vigilar el bot, cada una con SU riesgo en dolares por
operacion. Eso no cabia en `portfolio_lab_assignments`, que solo guarda
pertenencia (strategy_id + bucket) y no admite parametros: de ahi la tabla
propia.

EL RIESGO DEL CUADRO DE MANDOS MANDA sobre el JSON de la estrategia. Sustituye a
`risk_r` y fuerza `risk_type=FIXED`, pero NO toca `size_by_sl`: ese sigue siendo
de la estrategia, y es el que decide si el numero significa «capital a
desplegar» (shares = riesgo / precio) o «perdida maxima» (shares = riesgo /
distancia al stop). Cambiar eso aqui daria tamanos que no son los del backtest.

Tabla perezosa y local, mismo patron que portfolio_lab_service: no se toca
init_db.py ni el esquema compartido. En produccion simplemente no existe.
"""
from __future__ import annotations

import json
import threading
from typing import Any, Optional

# Cubos de los que salen las candidatas. La INCUBADORA entra a proposito: es
# donde viven las estrategias que se estan validando, y verlas avisar en vivo es
# justo como se decide si pasan al portfolio. Los avisos de una y otra se pintan
# en tablas SEPARADAS para no mezclar lo que se opera con lo que se prueba.
CUBOS = ("portfolio", "incubadora")

# Compatibilidad: antes solo se vigilaba el portfolio.
BUCKET_ORIGEN = "portfolio"


def _cubo_de(cuadros: list[str]) -> Optional[str]:
    """De que cubo cuelga una estrategia. El portfolio manda si esta en los dos:
    lo que se opera pesa mas que lo que se prueba."""
    for c in CUBOS:
        if c in cuadros:
            return c
    return None

_DDL_LOCK = threading.Lock()
_DDL_DONE = False


def ensure_watch_table(con) -> None:
    """Crea la tabla una sola vez por proceso, serializado.

    El cerrojo no es paranoia: DuckDB lanza "Catalog write-write conflict" si
    dos hilos entran a la vez al mismo CREATE TABLE, pese al IF NOT EXISTS, y
    la pagina dispara varios GET en paralelo al abrirse.
    """
    global _DDL_DONE
    if _DDL_DONE:
        return
    with _DDL_LOCK:
        if _DDL_DONE:
            return
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_alert_watch (
                strategy_id VARCHAR PRIMARY KEY,
                activa BOOLEAN NOT NULL DEFAULT FALSE,
                riesgo_usd DOUBLE NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        _DDL_DONE = True


_DDL_EVENTOS_DONE = False


def ensure_eventos_table(con) -> None:
    """Historico de avisos + estado del bot.

    OCUPA MUY POCO: ~300 bytes por aviso y del orden de 50 avisos al dia, o sea
    menos de 4 MB al anyo. Una sola corrida de backtest guardada pesa mas que
    todo un anyo de alertas, asi que no compensa no guardarlas.
    """
    global _DDL_EVENTOS_DONE
    if _DDL_EVENTOS_DONE:
        return
    with _DDL_LOCK:
        if _DDL_EVENTOS_DONE:
            return
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_alert_eventos (
                id VARCHAR PRIMARY KEY,
                fecha DATE NOT NULL,
                momento TIMESTAMP NOT NULL,
                recibido_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                tipo VARCHAR NOT NULL,          -- entrada | piramide | salida
                ticker VARCHAR NOT NULL,
                strategy_id VARCHAR NOT NULL,
                estrategia VARCHAR,
                direccion VARCHAR,
                precio DOUBLE,
                acciones DOUBLE,
                stop DOUBLE,
                riesgo_usd DOUBLE,
                motivo VARCHAR,
                nivel INTEGER,
                accion_piramide VARCHAR,
                posicion_total DOUBLE
            )
            """
        )
        # Anyadidas despues: `origen` separa portfolio de incubadora (se pintan
        # en tablas distintas para no mezclar lo que se opera con lo que se
        # prueba) y `modo` marca los avisos de una REPRODUCCION, que si no
        # ensuciarian el historico real haciendose pasar por avisos de verdad.
        con.execute("ALTER TABLE bot_alert_eventos ADD COLUMN IF NOT EXISTS origen VARCHAR DEFAULT 'portfolio'")
        con.execute("ALTER TABLE bot_alert_eventos ADD COLUMN IF NOT EXISTS modo VARCHAR DEFAULT 'vivo'")
        # Estado del bot. Una sola fila: la pagina escribe `vigilando` y el bot
        # lo consulta. Asi la pagina lo enciende sin tener que hablar con el
        # proceso del bot, que vive aparte y no expone nada hacia dentro.
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_alert_estado (
                id INTEGER PRIMARY KEY,
                vigilando BOOLEAN NOT NULL DEFAULT FALSE,
                latido_at TIMESTAMP,
                tickers_seguidos INTEGER DEFAULT 0,
                fuente VARCHAR,                 -- 'reproduccion' | 'websocket'
                detalle VARCHAR
            )
            """
        )
        con.execute("INSERT OR IGNORE INTO bot_alert_estado (id, vigilando) VALUES (1, FALSE)")
        _DDL_EVENTOS_DONE = True


def guardar_eventos(con, eventos: list[dict]) -> int:
    """Guarda una tanda de avisos. Devuelve cuantos entraron.

    El `id` lo pone quien publica y es estable (ticker+estrategia+momento+tipo),
    de modo que reenviar la misma tanda no duplica filas: el bot puede
    reintentar sin miedo si se cae la red.
    """
    ensure_eventos_table(con)
    if not eventos:
        return 0
    filas = [
        (
            e["id"], e["fecha"], e["momento"], e["tipo"], e["ticker"],
            e["strategy_id"], e.get("estrategia"), e.get("direccion"),
            e.get("precio"), e.get("acciones"), e.get("stop"), e.get("riesgo_usd"),
            e.get("motivo"), e.get("nivel"), e.get("accion_piramide"),
            e.get("posicion_total"), e.get("origen") or "portfolio",
            e.get("modo") or "vivo",
        )
        for e in eventos
    ]
    con.executemany(
        "INSERT OR REPLACE INTO bot_alert_eventos "
        "(id, fecha, momento, tipo, ticker, strategy_id, estrategia, direccion, "
        " precio, acciones, stop, riesgo_usd, motivo, nivel, accion_piramide, "
        " posicion_total, origen, modo) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        filas,
    )
    return len(filas)


def listar_eventos(con, fecha: Optional[str] = None, limite: int = 500) -> list[dict]:
    """Avisos de una fecha (o los ultimos, si no se da). Mas reciente primero."""
    ensure_eventos_table(con)
    if fecha:
        sql = ("SELECT * FROM bot_alert_eventos WHERE fecha = CAST(? AS DATE) "
               "ORDER BY momento DESC LIMIT ?")
        params = [fecha, limite]
    else:
        sql = "SELECT * FROM bot_alert_eventos ORDER BY momento DESC LIMIT ?"
        params = [limite]
    cur = con.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def fechas_con_eventos(con, limite: int = 60) -> list[str]:
    """Dias que tienen avisos guardados, para el selector del historico."""
    ensure_eventos_table(con)
    rows = con.execute(
        "SELECT DISTINCT fecha FROM bot_alert_eventos ORDER BY fecha DESC LIMIT ?", [limite]
    ).fetchall()
    return [str(r[0]) for r in rows]


def borrar_eventos_antes(con, fecha: str) -> int:
    """Limpieza manual. Devuelve cuantas filas se fueron."""
    ensure_eventos_table(con)
    n = con.execute(
        "SELECT COUNT(*) FROM bot_alert_eventos WHERE fecha < CAST(? AS DATE)", [fecha]
    ).fetchone()[0]
    con.execute("DELETE FROM bot_alert_eventos WHERE fecha < CAST(? AS DATE)", [fecha])
    return int(n)


def get_estado(con) -> dict:
    ensure_eventos_table(con)
    r = con.execute(
        "SELECT vigilando, latido_at, tickers_seguidos, fuente, detalle "
        "FROM bot_alert_estado WHERE id = 1"
    ).fetchone()
    if not r:
        return {"vigilando": False, "latido_at": None, "tickers_seguidos": 0,
                "fuente": None, "detalle": None}
    return {
        "vigilando": bool(r[0]),
        "latido_at": str(r[1]) if r[1] else None,
        "tickers_seguidos": int(r[2] or 0),
        "fuente": r[3],
        "detalle": r[4],
    }


def set_vigilando(con, vigilando: bool) -> dict:
    """Lo que pulsa la pagina. El bot lo consulta y actua en consecuencia."""
    ensure_eventos_table(con)
    con.execute("UPDATE bot_alert_estado SET vigilando = ? WHERE id = 1", [bool(vigilando)])
    return get_estado(con)


def latido(con, tickers: int, fuente: str, detalle: str = "") -> None:
    """El bot dice que sigue vivo. Sin esto la pagina no puede distinguir
    'apagado' de 'colgado'."""
    ensure_eventos_table(con)
    con.execute(
        "UPDATE bot_alert_estado SET latido_at = CURRENT_TIMESTAMP, "
        "tickers_seguidos = ?, fuente = ?, detalle = ? WHERE id = 1",
        [int(tickers), fuente, detalle],
    )


def get_watch(con) -> dict[str, dict]:
    """{strategy_id: {activa, riesgo_usd, updated_at}} para TODAS las filas."""
    ensure_watch_table(con)
    rows = con.execute(
        "SELECT strategy_id, activa, riesgo_usd, updated_at FROM bot_alert_watch"
    ).fetchall()
    return {
        r[0]: {
            "activa": bool(r[1]),
            "riesgo_usd": float(r[2]),
            "updated_at": str(r[3]) if r[3] else None,
        }
        for r in rows
    }


def set_watch(con, strategy_id: str, activa: bool, riesgo_usd: float) -> dict:
    """Guarda (o actualiza) la vigilancia de una estrategia. Devuelve su fila."""
    ensure_watch_table(con)
    con.execute(
        "INSERT OR REPLACE INTO bot_alert_watch (strategy_id, activa, riesgo_usd, updated_at) "
        "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
        [strategy_id, bool(activa), float(riesgo_usd)],
    )
    return {"strategy_id": strategy_id, "activa": bool(activa), "riesgo_usd": float(riesgo_usd)}


def _parse_definition(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}


def ventana_operativa(definition: dict) -> dict:
    """Franja horaria en la que la estrategia puede operar, en hora de mercado.

    Hace falta para distinguir un cierre de fin de dia REAL de la ultima vela
    que el bot tiene por ahora: el simulador etiqueta las dos como "EOD", y sin
    esta franja el bot avisaria de una salida cada minuto.

    Devuelve {inicio, fin} en "HH:MM", o None en el extremo que no este acotado.
    """
    sesiones = definition.get("market_sessions") or []
    if "custom" in sesiones:
        return {
            "inicio": definition.get("custom_start_time"),
            "fin": definition.get("custom_end_time"),
        }
    # Sesiones con nombre: los limites los pone el reloj del mercado.
    limites = {
        "premarket": ("04:00", "09:30"),
        "regular": ("09:30", "16:00"),
        "afterhours": ("16:00", "20:00"),
    }
    presentes = [limites[s] for s in sesiones if s in limites]
    if not presentes:
        return {"inicio": None, "fin": None}
    return {"inicio": min(p[0] for p in presentes), "fin": max(p[1] for p in presentes)}


def listar_candidatas(con, scope_sql: str = "", scope_params: Optional[list] = None) -> list[dict]:
    """Las estrategias del cubo `portfolio` con su configuracion de vigilancia.

    Es lo que pinta el cuadro de mandos: una fila por estrategia, con su
    interruptor y su casilla de riesgo. Las que aun no se han configurado salen
    con `activa=False` y `riesgo_usd=None`.
    """
    from app.services import portfolio_lab_service as pls

    ensure_watch_table(con)
    scope_params = list(scope_params or [])

    rows = con.execute(
        f"SELECT id, name, definition FROM strategies WHERE 1=1{scope_sql} ORDER BY name",
        scope_params,
    ).fetchall()

    asignaciones = pls.get_assignments(con)
    watch = get_watch(con)

    out = []
    for sid, name, definition_raw in rows:
        cubo = _cubo_de(asignaciones.get(sid, []))
        if cubo is None:
            continue
        definition = _parse_definition(definition_raw)
        cfg = watch.get(sid) or {}
        out.append({
            "strategy_id": sid,
            "name": name,
            "origen": cubo,               # 'portfolio' | 'incubadora'
            "activa": bool(cfg.get("activa", False)),
            "riesgo_usd": cfg.get("riesgo_usd"),
            "bias": definition.get("bias"),
            # Los dos datos que cambian el significado del riesgo y el calculo
            # de acciones. Se exponen para que el cuadro de mandos pueda
            # explicarlo en pantalla en vez de que el numero salga a ciegas.
            "size_by_sl": bool((definition.get("risk_management") or {}).get("size_by_sl", False)),
            "hard_stop": (definition.get("risk_management") or {}).get("hard_stop"),
            "ventana": ventana_operativa(definition),
        })
    return out


def vigiladas(con, scope_sql: str = "", scope_params: Optional[list] = None) -> list[dict]:
    """Lo que el bot pide al arrancar: definicion completa + riesgo, ya filtrado.

    Solo salen las que estan activas Y siguen en el cubo `portfolio` Y tienen un
    riesgo valido. Una estrategia que se saco del portfolio deja de vigilarse
    aunque su fila siga marcada como activa — asi no hace falta acordarse de
    limpiar la tabla a mano.
    """
    from app.services import portfolio_lab_service as pls

    ensure_watch_table(con)
    scope_params = list(scope_params or [])

    rows = con.execute(
        f"SELECT id, name, definition FROM strategies WHERE 1=1{scope_sql}",
        scope_params,
    ).fetchall()

    asignaciones = pls.get_assignments(con)
    watch = get_watch(con)

    out = []
    for sid, name, definition_raw in rows:
        cfg = watch.get(sid)
        if not cfg or not cfg.get("activa"):
            continue
        cubo = _cubo_de(asignaciones.get(sid, []))
        if cubo is None:
            continue
        riesgo = cfg.get("riesgo_usd")
        if riesgo is None or riesgo <= 0:
            continue
        definition = _parse_definition(definition_raw)
        out.append({
            "strategy_id": sid,
            "name": name,
            "origen": cubo,
            "riesgo_usd": float(riesgo),
            "definition": definition,
            "ventana": ventana_operativa(definition),
        })
    return out
