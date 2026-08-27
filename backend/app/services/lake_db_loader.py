"""Cierre de la actualizacion del lago local, DENTRO del backend.

POR QUE EXISTE ESTE MODULO
--------------------------
El boton de actualizar de la UI lanza `actualizar_diario.py`, que deja al dia
el lago PARQUET. Pero para que un dia nuevo sea backtesteable hacen falta
CINCO capas alineadas (proyecto del lago, MEMORIA.md 6.16 y 6.17):

    1. lago Parquet                        <- actualizar_diario.py (fases 1-6)
    2. copia optimizada del mes            <- paso 4b del mismo script
    3. qualifying materializado (bygap)    <- paso 5 del mismo script
    4. tablas daily_metrics / intraday_1m  <- fase7_cargar_edgecute.py
       de local_data.duckdb
    5. ventana de fechas del dataset       <- era MANUAL, desde la interfaz

Las capas 4 y 5 se quedaban fuera del boton. Por eso el 2026-08-21 el lago
llego al dia 20 con los backtests todavia leyendo el 14, sin ningun aviso.

La capa 4 no se podia automatizar desde el script: la fase 7 abre
local_data.duckdb para escribir y ABORTA si el backend la tiene abierta — y el
backend es justo quien lanza el boton. La salida es no usar un proceso aparte:
DuckDB permite varias conexiones de escritura DENTRO del mismo proceso, asi que
la carga se hace aqui, con la conexion del propio backend. Sin cerrar nada, sin
soltar el fichero y sin bloquear la API (corre en el hilo de la actualizacion,
y las lecturas concurrentes ven la version anterior hasta el commit).

Ademas se acota a los MESES TOCADOS por el delta. La fase 7 completa gasta casi
todo su tiempo en un GROUP BY por año/mes sobre los ~3.000 M de filas de
intraday_1m solo para averiguar que meses le faltan; sabiendo cuales son de
antemano, el mismo trabajo son segundos.

PARIDAD CON LA FASE 7
---------------------
El SQL de carga (DELETE por RANGO de timestamp + INSERT desde read_parquet, y
el salto cuando el numero de filas ya coincide) es el mismo que
`fase7_cargar_edgecute.py:cargar_particionada`. Si se toca alli, tocar aqui.
Lo que este modulo NO hace, a proposito, es crear ni recrear tablas: si el
esquema no es el esperado se aborta y se avisa, porque un DROP de intraday_1m
son horas de reconstruccion.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
from datetime import date, timedelta
from typing import Callable, Iterable

# Orden de columnas del INSERT, identico al de la fase 7. daily_metrics va con
# "*" porque el Parquet de la fase 6 sale con las columnas ya en el orden de la
# tabla (year/month incluidos, que alli son columnas de verdad).
COLUMNAS_INSERT = {
    "daily_metrics": "*",
    "intraday_1m": "ticker, date, timestamp, open, high, low, close, volume",
}

# Tablas de referencia: pequeñas, se recargan enteras si el recuento no cuadra.
TABLAS_REF = ("tickers", "splits")

Log = Callable[[str], None]


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _cold_storage() -> str | None:
    """Raiz cold_storage del lago local, o None si no hay lago configurado."""
    raiz = os.getenv("LOCAL_LAKE_DIR", "").strip().rstrip("/").rstrip("\\")
    if not raiz:
        return None
    cs = os.path.join(raiz, "cold_storage")
    return cs if os.path.isdir(cs) else None


def _g(p: str) -> str:
    """Rutas para SQL: DuckDB quiere barras normales tambien en Windows."""
    return p.replace("\\", "/")


def _rango_mes(y: int, m: int) -> tuple[str, str]:
    """[inicio, fin) del mes como literales de timestamp."""
    y2, m2 = (y + 1, 1) if m == 12 else (y, m + 1)
    return f"{y:04d}-{m:02d}-01 00:00:00", f"{y2:04d}-{m2:02d}-01 00:00:00"


def _es_tabla(con, nombre: str) -> bool:
    """True solo si `main.<nombre>` es una TABLA real (no una vista)."""
    try:
        return con.execute(
            "SELECT count(*) FROM duckdb_tables() "
            "WHERE schema_name = 'main' AND table_name = ?", [nombre]
        ).fetchone()[0] > 0
    except Exception:
        return False


def meses_por_defecto(hoy: date | None = None) -> list[tuple[int, int]]:
    """Mes en curso y el anterior.

    Es el respaldo cuando la actualizacion no dice que meses toco (por ejemplo
    si no hubo delta que descargar). Sirve ademas de auto-reparacion: detecta y
    corrige un desfase Parquet-vs-tabla que se hubiera quedado de antes.
    """
    h = hoy or date.today()
    anterior = (h.replace(day=1) - timedelta(days=1))
    return sorted({(anterior.year, anterior.month), (h.year, h.month)})


# ---------------------------------------------------------------------------
# Capa 4 — Parquet -> tablas de local_data.duckdb
# ---------------------------------------------------------------------------
def cargar_meses_en_duckdb(meses: Iterable[tuple[int, int]], log: Log) -> dict:
    """Carga en `local_data.duckdb` los meses indicados. Idempotente.

    Devuelve un resumen con lo cargado y lo saltado. No lanza excepciones al
    llamador: cualquier fallo se registra y se devuelve en `error`, porque esto
    corre al final de una actualizacion de 15 minutos que ya ha hecho su
    trabajo y no debe darse por perdida.
    """
    resumen: dict = {"cargados": [], "saltados": 0, "filas": 0, "error": None,
                     # Meses que el lago NO tiene. Antes se saltaban con un
                     # `continue` mudo y la tabla se quedaba con el hueco sin
                     # que nadie se enterara ("meses en el aire").
                     "sin_parquet": []}

    cs = _cold_storage()
    if not cs:
        resumen["error"] = "LOCAL_LAKE_DIR no apunta a un lago con cold_storage/"
        log(f"[CARGA] OMITIDA: {resumen['error']}")
        return resumen

    try:
        from app.database import get_db_connection
        con = get_db_connection()
    except Exception as e:
        resumen["error"] = f"no se pudo abrir la base: {type(e).__name__}: {e}"
        log(f"[CARGA] {resumen['error']}")
        return resumen

    try:
        for tabla in COLUMNAS_INSERT:
            if not _es_tabla(con, tabla):
                resumen["error"] = (
                    f"main.{tabla} no es una tabla en local_data.duckdb; "
                    f"no se toca nada (¿DB_PROVIDER != local?)"
                )
                log(f"[CARGA] ABORTADA: {resumen['error']}")
                return resumen

        _recargar_referencias(con, cs, log)

        for tabla, cols in COLUMNAS_INSERT.items():
            for y, m in meses:
                # Se prueban los DOS paddings: nuestro lago escribe `month=01`
                # pero DuckDB por defecto escribe `month=1`, y un glob que no
                # resuelve hacia que el mes "no existiera" y la carga se
                # saltara EN SILENCIO (le paso al socio con agosto).
                patron = None
                for pad in (f"{m:02d}", str(m)):
                    cand = _g(os.path.join(cs, tabla, f"year={y}", f"month={pad}", "*.parquet"))
                    if glob.glob(cand):
                        patron = cand
                        break
                if not patron:
                    # NUNCA en silencio: un mes que falta en el lago es un
                    # hueco en la tabla, y hay que poder verlo sin leer el log
                    # entero.
                    hueco = f"{tabla} {y}-{m:02d}"
                    resumen["sin_parquet"].append(hueco)
                    log(f"[CARGA] SIN PARQUET EN EL LAGO: {hueco} — "
                        f"la tabla se queda sin ese mes")
                    continue
                esperadas = con.execute(
                    f"SELECT count(*) FROM read_parquet('{patron}')").fetchone()[0]
                ini, fin = _rango_mes(y, m)
                # El WHERE va por RANGO, nunca `year(timestamp)=Y`: envolver la
                # columna en una funcion impide a DuckDB podar por los min/max
                # de cada bloque y reescanea la tabla entera (fase 7, nota 1).
                actuales = con.execute(
                    f"SELECT count(*) FROM {tabla} "
                    f"WHERE timestamp >= TIMESTAMP '{ini}' AND timestamp < TIMESTAMP '{fin}'"
                ).fetchone()[0]

                if actuales == esperadas:
                    resumen["saltados"] += 1
                    log(f"[CARGA] {tabla} {y}-{m:02d}: al dia ({actuales:,} filas), se salta")
                    continue

                log(f"[CARGA] {tabla} {y}-{m:02d}: {actuales:,} -> {esperadas:,} filas, cargando...")
                # DELETE + INSERT en UNA transaccion. Sueltos, cada uno hace su
                # commit y un fallo del INSERT deja el mes borrado de la tabla
                # y los backtests de ese mes vacios hasta que alguien lo note.
                con.execute("BEGIN TRANSACTION")
                try:
                    con.execute(
                        f"DELETE FROM {tabla} "
                        f"WHERE timestamp >= TIMESTAMP '{ini}' AND timestamp < TIMESTAMP '{fin}'")
                    con.execute(
                        f"INSERT INTO {tabla} SELECT {cols} FROM read_parquet('{patron}')")
                    if tabla == "daily_metrics":
                        _alinear_pmh_gap_pct(con, ini, fin, log)
                    con.execute("COMMIT")
                except Exception:
                    con.execute("ROLLBACK")
                    raise
                resumen["cargados"].append(f"{tabla} {y}-{m:02d} (+{esperadas - actuales:,})")
                resumen["filas"] += esperadas - actuales
                log(f"[CARGA] {tabla} {y}-{m:02d}: OK")
    except Exception as e:
        resumen["error"] = f"{type(e).__name__}: {e}"
        log(f"[CARGA] ERROR: {resumen['error']}")

    return resumen


def _alinear_pmh_gap_pct(con, ini: str, fin: str, log: Log | None = None) -> None:
    """Recalcula pmh_gap_pct en el mes recien cargado, como hace el arranque.

    POR QUE: `init_db.py` reescribe pmh_gap_pct de TODA la tabla en cada
    arranque con su propia formula (premarket high contra prev_close). El
    Parquet del lago trae la suya. Sin esto, los dias recien insertados se
    quedan con el valor del Parquet mientras el resto de la tabla lleva el del
    backend — y `PMH Gap %` es justo el filtro que decide que dias son
    candidatos, asi que la incoherencia se paga en la seleccion, no en un
    informe. La formula se copia literal de init_db.py: si cambia alli, cambia
    aqui. Va DENTRO de la transaccion de la carga: si falla, el mes entero se
    deshace, porque media carga con el gap sin alinear es peor que ninguna.

    AJUSTE POR SPLIT (PRD_FIX_gaps_falsos_splits): la formula ahora replica la
    del ETL del lago (etl_to_edgecute.py): en el dia de execution_date el
    cierre anterior se ajusta por product(split_from/split_to) leido del
    Parquet de splits del lago (que lleva esas columnas). Sin esto, cada
    reverse-split reinsertaria su gap falso del +15.000% en la tabla al cargar
    el mes. La IPO (prev_close NULL) no se toca, igual que la formula original.

    INTERRUPTOR LAKE_PREV_CLOSE_YA_AJUSTADO (2026-08-27, propuesta de Sailor —
    MEMORIA_MADRE "Por que sus parches de splits NO se pueden adoptar aqui"):
    los DOS lagos ajustan el split, pero en CAPAS distintas. Este (cangrejo_data)
    guarda prev_close CRUDO y ajusta aqui; el de Sailor hornea el factor DENTRO
    de prev_close en su ETL, asi que recalcular aqui seria un DOBLE ajuste
    (medido: NVDA 1,08% correcto pasaria a 910,77% falso). Con la variable en
    `true` este recalculo se apaga entero y pmh_gap_pct se queda tal y como lo
    escribio el ETL. Apagado por defecto (regla R7): en este lago hace falta.
    Paridad con init_db.py: el mismo interruptor gobierna los dos sitios.
    """
    if os.getenv("LAKE_PREV_CLOSE_YA_AJUSTADO", "false").strip().lower() in ("1", "true", "yes", "on"):
        (log or print)(
            "[CARGA] LAKE_PREV_CLOSE_YA_AJUSTADO=true: pmh_gap_pct se deja como "
            "lo escribio el ETL (prev_close ya ajustado por split), no se recalcula")
        return
    # Factor de split del lago: <LOCAL_LAKE_DIR>/splits/data.parquet (donde lo
    # escribe el ETL); cold_storage/splits es un junction al mismo fichero.
    raiz = os.getenv("LOCAL_LAKE_DIR", "").strip().rstrip("/").rstrip("\\")
    candidatos = [os.path.join(raiz, "splits", "data.parquet"),
                  os.path.join(raiz, "cold_storage", "splits", "data.parquet")]
    splits_parquet = next((p for p in candidatos if p and os.path.exists(p)), None)
    if not splits_parquet:
        raise RuntimeError(
            "no hay splits/data.parquet en el lago local: no se puede alinear "
            "pmh_gap_pct con el factor de split (LOCAL_LAKE_DIR mal configurado)")
    sp = _g(splits_parquet)
    rango = (f"timestamp >= TIMESTAMP '{ini}' AND timestamp < TIMESTAMP '{fin}' "
             f"AND prev_close IS NOT NULL AND prev_close > 0")
    # Dias SIN split (la inmensa mayoria): misma formula de siempre.
    # OJO compatibilidad: el backend corre DuckDB 1.1.3, que no soporta
    # "(a, b) NOT IN (SELECT x, y ...)" — anti-join con NOT EXISTS.
    con.execute(
        f"UPDATE daily_metrics "
        f"SET pmh_gap_pct = ((pm_high - prev_close) / NULLIF(prev_close, 0) * 100) "
        f"WHERE {rango} "
        f"AND NOT EXISTS (SELECT 1 FROM read_parquet('{sp}') s "
        f"WHERE s.ticker = daily_metrics.ticker "
        f"AND CAST(s.execution_date AS DATE) = CAST(daily_metrics.timestamp AS DATE))"
    )
    # Dias CON split: prev_close ajustado por el factor del lago (espejo del
    # split_fac del ETL; product() por si hay varios splits el mismo dia).
    con.execute(
        f"UPDATE daily_metrics AS d SET pmh_gap_pct = "
        f"(d.pm_high - d.prev_close * sf.f) / NULLIF(d.prev_close * sf.f, 0) * 100 "
        f"FROM (SELECT ticker, CAST(execution_date AS DATE) AS ed, "
        f"      product(CAST(split_from AS DOUBLE) / CAST(split_to AS DOUBLE)) AS f "
        f"      FROM read_parquet('{sp}') GROUP BY 1, 2) sf "
        f"WHERE d.ticker = sf.ticker AND CAST(d.timestamp AS DATE) = sf.ed "
        f"AND d.timestamp >= TIMESTAMP '{ini}' AND d.timestamp < TIMESTAMP '{fin}' "
        f"AND d.prev_close IS NOT NULL AND d.prev_close > 0"
    )


def _recargar_referencias(con, cs: str, log: Log) -> None:
    """tickers y splits: ficheros unicos y pequeños, DELETE + INSERT entero.

    Solo si el recuento no coincide, para no reescribirlos en cada
    actualizacion (cambian de higos a brevas).
    """
    for tabla in TABLAS_REF:
        src = os.path.join(cs, tabla, "data.parquet")
        if not os.path.exists(src) or not _es_tabla(con, tabla):
            continue
        try:
            esperadas = con.execute(
                f"SELECT count(*) FROM read_parquet('{_g(src)}')").fetchone()[0]
            actuales = con.execute(f"SELECT count(*) FROM {tabla}").fetchone()[0]
            if actuales == esperadas:
                continue
            con.execute(f"DELETE FROM {tabla}")
            con.execute(f"INSERT INTO {tabla} SELECT * FROM read_parquet('{_g(src)}')")
            log(f"[CARGA] {tabla}: {actuales:,} -> {esperadas:,} filas")
        except Exception as e:
            # Un desajuste de columnas aqui (el caso conocido de `tickers`, al
            # que le falta primary_exchange) no puede tumbar la carga de las
            # tablas de mercado, que es lo que de verdad importa.
            log(f"[CARGA] {tabla}: no se pudo recargar ({type(e).__name__}: {e}); se deja como esta")


def max_fecha_en_tabla() -> str | None:
    """Ultimo dia presente en `daily_metrics`, que es lo que ve la interfaz."""
    try:
        from app.database import get_db_connection
        r = get_db_connection().execute(
            "SELECT CAST(MAX(timestamp) AS VARCHAR)[:10] FROM daily_metrics").fetchone()
        return r[0] if r and r[0] else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Capa 5 — la ventana de fechas de los datasets
# ---------------------------------------------------------------------------
def extender_datasets(max_anterior: str | None, max_nuevo: str, log: Log,
                      todos: bool = False, solo: str | None = None) -> dict:
    """Estira hasta `max_nuevo` los datasets que iban al dia, y les añade los
    pares (ticker, dia) nuevos.

    POR QUE HACE FALTA: cada dataset guarda un `date_to` FIJO en sus filtros, y
    ese `date_to` es el techo del universo del backtest
    (data_service._build_where_clause). Un dataset creado el dia 14 seguira
    parando el 14 por mucho que el lago llegue al 20 — el sintoma que parecia
    "el backtest ignora los dias nuevos".

    QUE SE TOCA Y QUE NO. Solo se estiran los datasets que estaban AL DIA, es
    decir con `date_to >= max_anterior`. Uno que acabe antes (un backtest de un
    periodo concreto, un 2022-2023) tiene esa ventana a proposito y no se
    toca: estirarlo cambiaria en silencio los resultados de un estudio cerrado.
    Nunca se acorta una ventana, solo se alarga.

    `todos=True` desactiva ese filtro y estira TODOS los que se hayan quedado
    cortos. No se usa en la actualizacion automatica: es la puerta de atras del
    endpoint /api/lake/extend-datasets, para poner al dia de una vez los que se
    quedaron congelados antes de que esto existiera. Es una decision del
    usuario, no del sistema, y por eso hay que pedirla.

    `solo=<id>` limita la operacion a ese dataset.
    """
    resumen: dict = {"extendidos": [], "rezagados": [], "pares": 0, "error": None}
    if not max_nuevo:
        return resumen
    if not max_anterior and not todos:
        # Sin saber donde acababa el lago no hay forma de distinguir un dataset
        # que iba al dia de uno con ventana propia. Antes que estirar el que no
        # tocaba, no se estira ninguno.
        log("[DATASETS] no se sabe hasta donde llegaba el lago antes; no se estira ninguno")
        return resumen

    try:
        import pandas as pd  # noqa: F401  (lo usa _compute_dataset_pairs)
        from app.database import get_user_db_connection, get_user_db_lock
        from app.routers.query import _compute_dataset_pairs, _insert_dataset_pairs
    except Exception as e:
        resumen["error"] = f"no se pudo preparar la extension: {type(e).__name__}: {e}"
        log(f"[DATASETS] {resumen['error']}")
        return resumen

    lock = get_user_db_lock()
    try:
        with lock:
            con = get_user_db_connection(read_only=True)
            try:
                filas = con.execute("SELECT id, name, filters FROM saved_queries").fetchall()
            finally:
                con.close()
    except Exception as e:
        resumen["error"] = f"no se pudieron leer los datasets: {type(e).__name__}: {e}"
        log(f"[DATASETS] {resumen['error']}")
        return resumen

    candidatos = []
    for did, nombre, filtros_raw in filas:
        if solo and did != solo:
            continue
        try:
            filtros = json.loads(filtros_raw) if isinstance(filtros_raw, str) else (filtros_raw or {})
        except Exception:
            continue
        clave = "end_date" if filtros.get("end_date") else "date_to"
        hasta = str(filtros.get("end_date") or filtros.get("date_to") or "")[:10]
        if not hasta:
            continue                      # sin techo: ya ve todo lo que haya
        if hasta >= max_nuevo and not solo:
            continue                      # ya llega (o mas alla)
        if not todos and max_anterior and hasta < max_anterior:
            resumen["rezagados"].append(f"{nombre} (hasta {hasta})")
            continue                      # ventana cerrada a proposito
        candidatos.append((did, nombre, filtros, clave, hasta))

    if not candidatos:
        log(f"[DATASETS] ninguno que estirar hasta {max_nuevo}"
            + (f"; {len(resumen['rezagados'])} con ventana propia mas corta"
               if resumen["rezagados"] else ""))
        return resumen

    # Muchos datasets comparten reglas y solo cambian de nombre o de fecha de
    # inicio. La consulta de pares es lo caro (ventanas LEAD sobre toda
    # daily_metrics), asi que se calcula una vez por combinacion de filtros.
    cache_pares: dict[str, object] = {}

    for did, nombre, filtros, clave, hasta in candidatos:
        try:
            # PRIMERO la ventana, que es lo unico que cambia lo que ve el
            # backtest (_build_where_clause). Los pares de dataset_pairs son
            # para el listado de la interfaz: si su calculo falla, el dataset
            # tiene que quedar estirado igualmente.
            if hasta < max_nuevo:          # nunca se acorta una ventana
                filtros_nuevos = dict(filtros)
                filtros_nuevos[clave] = max_nuevo
                with lock:
                    con = get_user_db_connection(read_only=False)
                    try:
                        con.execute(
                            "UPDATE saved_queries SET filters = ?, updated_at = CURRENT_TIMESTAMP "
                            "WHERE id = ?",
                            [json.dumps(filtros_nuevos), did],
                        )
                    finally:
                        con.close()
                resumen["extendidos"].append(f"{nombre}: {hasta} -> {max_nuevo}")
                log(f"[DATASETS] {nombre}: {hasta} -> {max_nuevo}")
        except Exception as e:
            log(f"[DATASETS] {nombre}: no se pudo estirar ({type(e).__name__}: {e})")
            continue

        try:
            # Se arranca EN `hasta`, no en el dia siguiente: por el mismo
            # limite exclusivo de abajo, al crear un dataset su ultimo dia
            # nunca entro en dataset_pairs (comprobado: un dataset con
            # date_to=2026-08-20 se quedaba con el maximo en el 19). Recubrir
            # ese dia sale gratis — la PK de dataset_pairs y el ON CONFLICT DO
            # NOTHING hacen que reinsertar lo que ya esta no cueste nada — y de
            # paso repara el hueco.
            # Con `solo` no se recorta el delta: se recalcula el dataset ENTERO
            # desde su propio inicio. Ese modo es la herramienta de reparacion
            # manual, y sirve para uno que se quedo con los pares a medias.
            desde_delta = hasta
            if solo:
                desde_delta = str(filtros.get("start_date")
                                  or filtros.get("date_from") or hasta)[:10]
            filtros_delta = dict(filtros)
            # OJO con el techo: build_screener_query filtra `timestamp < fin`,
            # es decir con el final EXCLUSIVO, mientras que el qualifying del
            # backtest (_build_where_clause) lo trata como INCLUSIVO. Pasarle
            # `max_nuevo` a secas devuelve cero filas cuando el delta es de un
            # solo dia — exactamente lo que paso la primera vez que corrio
            # esto. Se le da el dia siguiente; lo que se GUARDA en el dataset
            # sigue siendo max_nuevo, que es lo que el backtest espera.
            fin_exclusivo = (date.fromisoformat(max_nuevo) + timedelta(days=1)).isoformat()
            filtros_delta[clave] = fin_exclusivo
            filtros_delta["date_from" if clave == "date_to" else "start_date"] = desde_delta
            filtros_delta.pop("start_date" if clave == "date_to" else "date_from", None)

            firma = json.dumps(filtros_delta, sort_keys=True, default=str)
            if firma not in cache_pares:
                log(f"[DATASETS] calculando dias nuevos {desde_delta} -> {max_nuevo}...")
                cache_pares[firma] = _compute_dataset_pairs(filtros_delta)
            nuevos = _insert_dataset_pairs(did, cache_pares[firma])
            resumen["pares"] += nuevos
            log(f"[DATASETS] {nombre}: +{nuevos} pares nuevos")
        except Exception as e:
            # Un dataset con filtros que build_screener_query no sabe traducir
            # (`require_shortable` y compañia, que no son columnas de
            # daily_metrics) revienta aqui. Solo se pierde el recuento del
            # listado: la ventana ya esta ampliada y el backtest ve los dias.
            log(f"[DATASETS] {nombre}: ventana ampliada, pero no se pudieron "
                f"contar los pares nuevos ({type(e).__name__})")

    if resumen["rezagados"]:
        log(f"[DATASETS] {len(resumen['rezagados'])} con ventana propia mas corta, sin tocar: "
            + ", ".join(resumen["rezagados"][:6])
            + (" ..." if len(resumen["rezagados"]) > 6 else ""))
    return resumen


# ---------------------------------------------------------------------------
# Caches
# ---------------------------------------------------------------------------
def anadir_dias_al_cache(meses, log: Log) -> dict:
    """AÑADE a la copia rapida los dias que le falten. No la rehace nunca.

    QUE ES LA COPIA RAPIDA. El motor guarda un parquet por (ticker, mes) en
    `CACHE_DIR/raw/<año>/<mes>/<ticker>.parquet`. Sacar un ticker del Parquet
    del mes cuesta ~14 s, porque hay que recorrer el mes entero (28 M de velas
    con todos los tickers mezclados); con su fichero propio es instantaneo. Es
    lo que hace que un backtest repetido vaya rapido.

    EL PROBLEMA QUE TENIA. Esos ficheros se escribian una vez y no se volvian a
    mirar. Si el mes crecia —y el mes en curso crece cada dia— seguian sirviendo
    la foto vieja y los dias nuevos se descartaban EN SILENCIO. Sintoma real del
    2026-08-22: 9 ticker-dias perdidos, todos del 2026-08-21, con sus velas en
    el Parquet pero ausentes de los ficheros cacheados.

    POR QUE AÑADIR Y NO BORRAR. La primera version borraba los ficheros del mes
    para que se rehicieran solos. Correcto pero absurdo: tirar 445 ficheros
    buenos porque les falta un dia obliga a 445 lecturas frias de ~14 s la
    proxima vez. Aqui se leen UNA vez del lago los dias que faltan y se pegan a
    los ficheros que ya existen.

    POR QUE SE COMPARA CON EL LAGO Y NO CON EL DELTA DESCARGADO. Podria bastar
    con "añade los dias que acabo de bajar", pero entonces una copia que se
    hubiera quedado atras por cualquier otro motivo no se arreglaria nunca.
    Comparando cada fichero contra el maximo del mes en el lago, pulsar el boton
    repara SIEMPRE lo que falte, haya habido descarga o no. Y si todo esta al
    dia no se toca ni un fichero.

    Los tickers SIN fichero no se tocan: se crearan solos la primera vez que un
    backtest los pida, como hasta ahora.
    """
    from app.db import gcs_cache as G

    resumen = {"ficheros": 0, "velas": 0, "error": None}
    cs = _cold_storage()
    if not cs:
        resumen["error"] = "sin LOCAL_LAKE_DIR"
        return resumen

    import duckdb
    import pandas as pd

    for y, m in meses:
        carpeta = os.path.join(G.LOCAL_CACHE_DIR, "raw", str(y), f"{m:02d}")
        if not os.path.isdir(carpeta) or not glob.glob(os.path.join(carpeta, "*.parquet")):
            continue
        # Las particiones del lago van SIN cero (month=8); se prueban ambos.
        patron_lago = None
        for pad in (f"{m:02d}", str(m)):
            p = _g(os.path.join(cs, "intraday_1m", f"year={y}", f"month={pad}", "*.parquet"))
            if glob.glob(p):
                patron_lago = p
                break
        if not patron_lago:
            continue

        try:
            con = duckdb.connect()
            try:
                tope_lago = con.execute(
                    f"SELECT max(CAST(timestamp AS DATE)) FROM read_parquet('{patron_lago}')"
                ).fetchone()[0]
                if tope_lago is None:
                    continue
                # Hasta donde llega CADA fichero de la copia rapida, de una sola
                # consulta sobre los ficheros pequeños. Los vacios (marcadores de
                # "este ticker no opero ese mes") salen con NULL y se saltan.
                patron_cache = _g(os.path.join(carpeta, "*.parquet"))
                filas = con.execute(
                    "SELECT filename, max(CAST(timestamp AS DATE)) AS tope "
                    f"FROM read_parquet('{patron_cache}', filename=true, union_by_name=true) "
                    "GROUP BY 1"
                ).fetchall()
                desfasados = {os.path.basename(f)[:-8]: tope
                              for f, tope in filas
                              if tope is not None and tope < tope_lago}
                if not desfasados:
                    log(f"[CACHE] {y}-{m:02d}: la copia rapida ya llega al {tope_lago}")
                    continue
                desde = min(desfasados.values())
                lista = ",".join("'" + t.replace("'", "''") + "'" for t in desfasados)
                nuevas_todas = con.execute(
                    "SELECT ticker, date, timestamp, open, high, low, close, volume "
                    f"FROM read_parquet('{patron_lago}') "
                    f"WHERE CAST(timestamp AS DATE) > DATE '{desde}' "
                    f"AND ticker IN ({lista})"
                ).df()
            finally:
                con.close()
        except Exception as e:
            resumen["error"] = f"{type(e).__name__}: {e}"
            log(f"[CACHE] {y}-{m:02d}: no se pudo mirar que falta ({resumen['error']})")
            continue

        # OJO con lo que se dice aqui: que la ultima vela de un ticker sea
        # anterior al cierre del mes NO significa que su copia este mal — lo
        # normal es que se haya DESLISTADO. Y los deslistados nos interesan: se
        # descargaron a proposito para que entren en los backtests y no haya
        # sesgo de supervivencia. Por max(fecha) los dos casos no se distinguen,
        # asi que se revisan ambos, al deslistado no se le añade nada y su
        # fichero NO se toca. Un "3 tickers por detras" en cada pulsacion parece
        # una averia y no lo es.
        if nuevas_todas.empty:
            continue

        for tk, nuevas in nuevas_todas.groupby("ticker"):
            destino = G._ticker_cache_path(y, m, "raw", str(tk))
            try:
                viejas = pd.read_parquet(destino)
                # Idempotente: relanzar la actualizacion no duplica velas.
                unidas = pd.concat([viejas, nuevas[viejas.columns]], ignore_index=True)
                unidas = unidas.drop_duplicates(subset=["ticker", "timestamp"], keep="last")
                unidas = unidas.sort_values("timestamp", kind="stable", ignore_index=True)
                if len(unidas) == len(viejas):
                    continue
                G._atomic_write_parquet(unidas, destino)
                resumen["ficheros"] += 1
                resumen["velas"] += len(unidas) - len(viejas)
            except Exception as e:
                # Si un fichero da problemas se borra: que quede a medias es
                # peor que no tenerlo (se rehace solo, viejo miente en silencio).
                try:
                    os.remove(destino)
                except Exception:
                    pass
                log(f"[CACHE] {tk} {y}-{m:02d}: no se pudo ampliar "
                    f"({type(e).__name__}), se borra para que se rehaga")

    # La copia en RAM es la misma foto un nivel mas arriba: se suelta para que
    # se recargue de los ficheros ya ampliados.
    try:
        objetivo = {(y, m) for y, m in meses}
        with G._RAM_CACHE_LOCK:
            for clave in [k for k in G._RAM_CACHE if (k[1], k[2]) in objetivo]:
                G._RAM_CACHE.pop(clave, None)
    except Exception as e:
        log(f"[CACHE] no se pudo soltar la cache en RAM ({type(e).__name__}: {e})")

    if resumen["ficheros"]:
        log(f"[CACHE] {resumen['velas']:,} velas añadidas a {resumen['ficheros']} "
            f"tickers de la copia rapida (sin rehacerla)")
    else:
        log("[CACHE] la copia rapida ya estaba al dia")
    return resumen


def invalidar_caches_qualifying(log: Log) -> None:
    """Tira la cache del qualifying: su TTL local es de dias.

    QUALIFYING_CACHE_TTL esta en 7 dias en este equipo (la consulta tarda
    minutos y merece la pena cachearla). La clave incluye los filtros, asi que
    editar un dataset la invalida sola — pero una actualizacion del lago cambia
    el DATO sin cambiar la clave, y sin esto un dataset con la ventana ya
    abierta seguiria sirviendo el resultado viejo hasta una semana.
    """
    directorio = os.getenv("QUALIFYING_DISK_CACHE_DIR", "/tmp/btt_qualifying_cache")
    try:
        if os.path.isdir(directorio):
            shutil.rmtree(directorio, ignore_errors=True)
            os.makedirs(directorio, exist_ok=True)
            log("[CACHE] cache de qualifying en disco vaciada")
    except Exception as e:
        log(f"[CACHE] no se pudo vaciar la cache en disco ({type(e).__name__}: {e})")

    try:
        from app.redis_client import get_redis
        r = get_redis()
        if r:
            borradas = 0
            for k in r.scan_iter(match="qualifying:*", count=500):
                r.delete(k)
                borradas += 1
            log(f"[CACHE] {borradas} claves de qualifying borradas de Redis")
    except Exception as e:
        log(f"[CACHE] Redis no disponible o no se pudo limpiar ({type(e).__name__}: {e})")
