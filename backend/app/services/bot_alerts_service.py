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

import datetime
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
        # MIGRACION (2026-09-03). Columnas nuevas para las tablas que ya
        # existen; sin esto la fila vieja no tendria donde guardarlas y el
        # INSERT fallaria. Son NULL a proposito: NULL = "no dicho", que no es lo
        # mismo que 0 y permite caer a la definicion de la estrategia.
        #   riesgo_piramide_usd: el anyadido puede arriesgar algo distinto de la
        #     entrada, y hasta hoy solo se podia fijar el de la entrada.
        #   capital_usd: la cuenta real de Jaume. El bot no la conoce, y el stop
        #     hibrido no puede calcular su techo sin ella.
        #   ev_pct: la esperanza de la estrategia, en % del precio de entrada.
        #     La teclea Jaume — el bot no puede saber que backtest considera
        #     valido. La usa `/evf` para no tener que repetirla en cada mensaje.
        for columna, tipo in (("riesgo_piramide_usd", "DOUBLE"),
                              ("capital_usd", "DOUBLE"),
                              ("ev_pct", "DOUBLE")):
            try:
                con.execute(f"ALTER TABLE bot_alert_watch ADD COLUMN {columna} {tipo}")
            except Exception:
                pass          # ya existe
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
        # `estado`: 'prealerta' mientras la vela se esta formando, 'alerta'
        # cuando cierra y se confirma.
        #
        # NO HACE FALTA NADA MAS PARA QUE LA FILA SE TRANSFORME EN VEZ DE
        # DUPLICARSE: el id es ticker|estrategia|momento|tipo, asi que la
        # prealerta del segundo 50 y la alerta del cierre de ESE MISMO minuto
        # comparten id, y el INSERT OR REPLACE actualiza la fila que ya existe.
        con.execute("ALTER TABLE bot_alert_eventos ADD COLUMN IF NOT EXISTS estado VARCHAR DEFAULT 'alerta'")
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


# ── Cache en memoria ─────────────────────────────────────────────────────────
#
# EL CUADRO DE MANDOS CONSULTA CADA 2 SEGUNDOS, y sin esta cache eso BLOQUEA las
# escrituras. El motivo esta en `database.get_user_db_connection`: ignora el
# parametro `read_only` y abre TODAS las conexiones en modo escritura, y DuckDB
# solo admite un escritor. Medido: con la pagina abierta, un DELETE se quedaba
# esperando mas de 60 s; con la pagina cerrada, 0,2 s.
#
# La cache es fiable porque el backend es el UNICO que escribe en estas tablas:
# el bot no toca el fichero, publica por HTTP y pasa por aqui.
_CACHE_LOCK = threading.Lock()
_cache_eventos: dict[str, list[dict]] = {}   # fecha (o "" = ultimos) -> filas
_cache_estado: Optional[dict] = None

# Contador que sube con CADA cambio. El WebSocket lo vigila para empujar a la
# pagina en el momento en que algo cambia, en vez de que ella pregunte cada
# 2 s: en una prealerta, donde el margen son segundos, esa espera se nota.
# Comparar un entero es gratis, asi que se puede mirar muchas veces por segundo
# sin tocar la base de datos.
_version = 0


def version() -> int:
    with _CACHE_LOCK:
        return _version


def _marcar_cambio() -> None:
    global _version
    _version += 1


# Lo que el radar esta mirando ahora mismo. SOLO EN MEMORIA, sin tabla: es una
# foto que se reemplaza cada 30 s y no interesa guardarla — y cada escritura en
# DuckDB compite con las demas (ver la nota de arriba).
_cache_radar: list[dict] = []
_radar_at: Optional[str] = None


def set_radar(candidatos: list[dict]) -> None:
    """Lo publica el BOT en cada barrido."""
    global _cache_radar, _radar_at
    with _CACHE_LOCK:
        _cache_radar = list(candidatos)
        _radar_at = str(datetime.datetime.now())
        _marcar_cambio()          # despierta al WebSocket de la pagina


def get_radar() -> dict:
    with _CACHE_LOCK:
        return {"candidatos": list(_cache_radar), "actualizado": _radar_at}


# El diario del bot: su log y lo que le ha saltado. Tambien SOLO EN MEMORIA, y
# por el mismo motivo que el radar — se reemplaza entero cada pocos segundos.
_cache_diario: dict = {}
_diario_at: Optional[str] = None


def set_diario(d: dict) -> None:
    """Lo publica el BOT cada pocos segundos.

    OJO: esto NO llama a `_marcar_cambio()`, a proposito. El log crece con cada
    linea, y despertar al WebSocket por cada una empujaria el paquete entero
    —estado, 500 eventos y radar— a la pagina varias veces por minuto solo
    porque el bot ha escrito «latencia». El diario se lee con su propio GET y
    solo cuando su cuadro esta abierto: si no lo miras, no cuesta nada.
    """
    global _cache_diario, _diario_at
    with _CACHE_LOCK:
        _cache_diario = dict(d)
        _diario_at = str(datetime.datetime.now())


def get_diario() -> dict:
    with _CACHE_LOCK:
        return {**_cache_diario, "actualizado": _diario_at}


def _invalidar_cache_eventos() -> None:
    with _CACHE_LOCK:
        _cache_eventos.clear()
        _marcar_cambio()


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
            e.get("modo") or "vivo", e.get("estado") or "alerta",
        )
        for e in eventos
    ]
    con.executemany(
        "INSERT OR REPLACE INTO bot_alert_eventos "
        "(id, fecha, momento, tipo, ticker, strategy_id, estrategia, direccion, "
        " precio, acciones, stop, riesgo_usd, motivo, nivel, accion_piramide, "
        " posicion_total, origen, modo, estado) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        filas,
    )
    _invalidar_cache_eventos()
    return len(filas)


def eventos_cacheados(fecha: Optional[str] = None) -> Optional[list[dict]]:
    """Lo que hay en cache, o None si esta fria. SIN tocar la base de datos.

    Existe para que el WebSocket no abra una conexion en cada envio: en este
    proyecto NO hay conexiones de solo lectura (ver la nota de la cache), asi
    que abrirla —aunque luego no se use— vuelve a competir con las escrituras
    del bot. Con esto, el camino caliente es memoria pura.
    """
    with _CACHE_LOCK:
        return _cache_eventos.get(fecha or "")


def estado_cacheado() -> Optional[dict]:
    """Igual que `eventos_cacheados`, para el estado."""
    with _CACHE_LOCK:
        return dict(_cache_estado) if _cache_estado is not None else None


def listar_eventos(con, fecha: Optional[str] = None, limite: int = 500) -> list[dict]:
    """Avisos de una fecha (o los ultimos, si no se da). Mas reciente primero."""
    clave = fecha or ""
    cacheado = eventos_cacheados(fecha)
    if cacheado is not None:
        return cacheado

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
    filas = [dict(zip(cols, r)) for r in cur.fetchall()]
    # Las fechas vienen como date/datetime y hay que poder serializarlas a JSON.
    for f in filas:
        for k in ("fecha", "momento", "recibido_at"):
            if f.get(k) is not None:
                f[k] = str(f[k])
    with _CACHE_LOCK:
        _cache_eventos[clave] = filas
    return filas


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
    _invalidar_cache_eventos()
    return int(n)


def get_estado(con) -> dict:
    """Estado del bot. Cacheado por el mismo motivo que los eventos: la pagina
    lo pide cada 2 s y cada consulta abre una conexion de escritura."""
    global _cache_estado
    with _CACHE_LOCK:
        if _cache_estado is not None:
            return dict(_cache_estado)

    ensure_eventos_table(con)
    r = con.execute(
        "SELECT vigilando, latido_at, tickers_seguidos, fuente, detalle "
        "FROM bot_alert_estado WHERE id = 1"
    ).fetchone()
    if not r:
        return {"vigilando": False, "latido_at": None, "tickers_seguidos": 0,
                "fuente": None, "detalle": None}
    estado = {
        "vigilando": bool(r[0]),
        # El latido NO se lee de la base: ya no se guarda ahi (va a memoria) y
        # la columna conserva el ultimo valor de antes del cambio. Devolverlo
        # haria creer que el bot esta vivo cuando ni siquiera se ha arrancado.
        # En blanco es lo correcto: hasta que el bot no late, no hay bot.
        "latido_at": None,
        "tickers_seguidos": 0,
        "fuente": None,
        "detalle": None,
    }
    with _CACHE_LOCK:
        _cache_estado = estado
    return dict(estado)


def _refrescar_estado_cache(**cambios) -> None:
    """Actualiza la cache del estado sin volver a leer de la base."""
    global _cache_estado
    with _CACHE_LOCK:
        if _cache_estado is None:
            _cache_estado = {"vigilando": False, "latido_at": None,
                             "tickers_seguidos": 0, "fuente": None, "detalle": None}
        _cache_estado.update(cambios)
        _marcar_cambio()


def set_vigilando(con, vigilando: bool) -> dict:
    """Lo que pulsa la pagina. El bot lo consulta y actua en consecuencia."""
    ensure_eventos_table(con)
    con.execute("UPDATE bot_alert_estado SET vigilando = ? WHERE id = 1", [bool(vigilando)])
    _refrescar_estado_cache(vigilando=bool(vigilando))
    with _CACHE_LOCK:
        return dict(_cache_estado or {})


def latido(con, tickers: int, fuente: str, detalle: str = "") -> None:
    """El bot dice que sigue vivo. Sin esto la pagina no puede distinguir
    'apagado' de 'colgado'.

    SOLO A MEMORIA, NO A LA BASE. Llega cada 5 segundos —720 escrituras por
    hora— y en este proyecto escribir BLOQUEA (ver la nota de la cache): era la
    fuente de escritura mas frecuente que ha tenido nunca la aplicacion, y con
    ella empezaron los cuelgues del backend del 2026-09-02.

    Y no hace falta guardarlo: si el backend se reinicia, el bot vuelve a latir
    en cinco segundos. Lo unico que SI se persiste es `vigilando`, porque eso es
    una decision del usuario y tiene que sobrevivir a un reinicio.
    """
    _refrescar_estado_cache(
        latido_at=str(datetime.datetime.now()), tickers_seguidos=int(tickers),
        fuente=fuente, detalle=detalle,
    )


def get_watch(con) -> dict[str, dict]:
    """{strategy_id: {activa, riesgo_usd, updated_at}} para TODAS las filas."""
    ensure_watch_table(con)
    rows = con.execute(
        "SELECT strategy_id, activa, riesgo_usd, updated_at, "
        "riesgo_piramide_usd, capital_usd, ev_pct FROM bot_alert_watch"
    ).fetchall()
    return {
        r[0]: {
            "activa": bool(r[1]),
            "riesgo_usd": float(r[2]),
            "updated_at": str(r[3]) if r[3] else None,
            # None = no dicho. Quien lo use decide si cae a la estrategia o si
            # bloquea; aqui no se inventa un 0 que parezca una decision.
            "riesgo_piramide_usd": float(r[4]) if r[4] is not None else None,
            "capital_usd": float(r[5]) if r[5] is not None else None,
            "ev_pct": float(r[6]) if r[6] is not None else None,
        }
        for r in rows
    }


def set_watch(con, strategy_id: str, activa: bool, riesgo_usd: float,
              riesgo_piramide_usd: float | None = None,
              capital_usd: float | None = None,
              ev_pct: float | None = None) -> dict:
    """Guarda (o actualiza) la vigilancia de una estrategia. Devuelve su fila."""
    ensure_watch_table(con)
    con.execute(
        "INSERT OR REPLACE INTO bot_alert_watch "
        "(strategy_id, activa, riesgo_usd, updated_at, riesgo_piramide_usd, capital_usd, ev_pct) "
        "VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?)",
        [strategy_id, bool(activa), float(riesgo_usd),
         float(riesgo_piramide_usd) if riesgo_piramide_usd is not None else None,
         float(capital_usd) if capital_usd is not None else None,
         float(ev_pct) if ev_pct is not None else None],
    )
    return {
        "strategy_id": strategy_id, "activa": bool(activa),
        "riesgo_usd": float(riesgo_usd),
        "riesgo_piramide_usd": riesgo_piramide_usd,
        "capital_usd": capital_usd,
        "ev_pct": ev_pct,
    }


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
            # ── Stop hibrido ────────────────────────────────────────────
            # Los porcentajes vienen de la estrategia; el capital, del cuadro
            # de mandos. La pagina necesita los tres para saber que pedir y
            # para no dejar activar con datos a medias.
            "hybrid_stop": bool((definition.get("risk_management") or {}).get("hybrid_stop", False)),
            "hybrid_black_swan_pct": (definition.get("risk_management") or {}).get("hybrid_black_swan_pct"),
            "hybrid_max_loss_pct": (definition.get("risk_management") or {}).get("hybrid_max_loss_pct"),
            "capital_usd": cfg.get("capital_usd"),
            "riesgo_piramide_usd": cfg.get("riesgo_piramide_usd"),
            "ev_pct": cfg.get("ev_pct"),
            # Si piramida, hay un segundo riesgo que fijar.
            "piramida": bool(((definition.get("pyramiding") or {}).get("levels")) or []),
            # La ventana de ENTRADAS, distinta de la de sesion.
            "ventana_entradas": [
                {"inicio": w.get("from_time"), "fin": w.get("to_time")}
                for w in ((definition.get("entry_logic") or {}).get("entry_time_windows") or [])
            ],
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
            # None = no dicho en el cuadro de mandos. El motor decide entonces:
            # el riesgo de piramide cae a lo que diga la definicion, y sin
            # capital el stop hibrido no se puede aplicar (por eso `/watch` no
            # deja activar una estrategia hibrida sin el).
            "riesgo_piramide_usd": cfg.get("riesgo_piramide_usd"),
            "ev_pct": cfg.get("ev_pct"),
            "capital_usd": cfg.get("capital_usd"),
            "definition": definition,
            "ventana": ventana_operativa(definition),
            # La de SESION. La de ENTRADAS es otra cosa y vive en
            # `entry_logic.entry_time_windows`: el 2026-09-03 el bot anunciaba
            # solo esta y hacia creer que se podia entrar hasta las 09:00
            # cuando las entradas cerraban a las 08:00.
            "ventana_entradas": [
                {"inicio": w.get("from_time"), "fin": w.get("to_time")}
                for w in ((definition.get("entry_logic") or {}).get("entry_time_windows") or [])
            ],
        })
    return out
