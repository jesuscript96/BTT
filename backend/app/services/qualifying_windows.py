"""
Columnas de ventana (LAG/LEAD) del qualifying compartidas por las tres vias
que construyen o consultan el universo de un dataset:

  1. Materializacion de pares de datasets  -> app/routers/query.py
  2. Qualifying local (DuckDB)             -> app/services/data_service.py
  3. Qualifying GCS (Parquet)              -> app/db/gcs_cache.py

El filtro "Añadir filtro de mercado -> Gap -1" viaja como columna lag_<col>_1
dentro de las rules del dataset. Si alguna via no materializa esa columna, la
regla o bien tira la query (Binder Error: columna inexistente) o bien se
ignora en silencio. Esta unica definicion evita que las vias diverjan: tocar
aqui actualiza las tres.
"""

# Fuentes del dia anterior (Gap -1) filtrables desde la UI. El alias de cada
# una es lag_<fuente>_1. rth_close y rth_volume ya existian como LAG 1 en las
# vias qualifying; se listan aqui para que la materializacion de datasets
# (que solo tenia LEADs) tambien las tenga.
#
# day_return_pct (2026-09-25): filtro 1.6 del Bloque 1 de la investigacion de
# criterios (docs/INFORME_BLOQUE1_VELA_VISPERA_20260925.md) — la vispera roja
# (neto RTH < umbral) sube el fade premarket del gap. Columna intra-RTH
# ((rth_close-rth_open)/rth_open) presente en la tabla local y en el parquet
# del lago; util SOLO para estrategias PM de fade, neutra en RTH.
PREV_DAY_LAG_SOURCES = [
    "rth_close",
    "rth_volume",
    "gap_pct",
    "pm_volume",
    "open",
    "pmh_gap_pct",
    "rth_range_pct",
    "day_return_pct",
]

# Fuentes LAG 1 que el stage-2 del qualifying (data_service / gcs_cache) ya
# construia a mano antes de que existiera este modulo. Sus select no se
# duplican; solo se anaden las que faltan.
STAGE2_BUILTIN_LAG1_SOURCES = {
    "rth_open", "rth_high", "rth_low", "pm_high", "rth_close", "rth_volume",
}


def _lag1_select(src: str) -> str:
    return f'LAG({src}, 1) OVER (PARTITION BY ticker ORDER BY "timestamp") AS lag_{src}_1'


# ── Filtro 3.2 del Bloque 3 (2026-09-27): retorno acumulado 5 días ──────────
#
# Definición EXACTA del estudio (docs/INFORME_BLOQUE3_REINCIDENCIA_20260925.md
# §1 y .tmp_bloque3/paso1_features.py, la misma con la que salieron los grupos
# de la prueba de cartera): retorno del cierre de la víspera frente al cierre
# de 5 sesiones antes, en % — implementado como producto de los retornos
# diarios r = close/prev_close − 1 de las 5 sesiones D−5..D−1 (prev_close
# PERSISTIDA del ETL, splits horneados, para que la ventana no explote al
# cruzar splits — hallazgo 25-sep·01). Si algún día de la ventana es inválido
# (prev_close ≤ 0 o |r| > 500 %) o faltan las 5 sesiones, la columna queda
# NULL y la regla no selecciona ese ticker-día (igual que el estudio lo dejaba
# NaN). En % (×100): el estudio medía el ratio; el umbral movible de la UI va
# en puntos de porcentaje.
#
# Ventanas de D-1 referidas al día del gap D → alias de la familia Gap -1.
RET5D_WINDOW_ALIAS = "lag_ret5d_pct_1"

_RET5D_FRAME = (
    'PARTITION BY ticker ORDER BY "timestamp" '
    "ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING"
)


def _ret5d_select() -> str:
    return (
        "CASE WHEN COUNT(*) OVER (" + _RET5D_FRAME + ") = 5 "
        'AND COUNT(CASE WHEN "prev_close" > 0 '
        'AND abs("close" / "prev_close" - 1) <= 5.0 THEN 1 END) '
        "OVER (" + _RET5D_FRAME + ") = 5 "
        'THEN 100.0 * (EXP(SUM(CASE WHEN "prev_close" > 0 '
        'AND abs("close" / "prev_close" - 1) <= 5.0 '
        'THEN ln("close" / "prev_close") ELSE 0 END) '
        "OVER (" + _RET5D_FRAME + ")) - 1) "
        f"ELSE NULL END AS {RET5D_WINDOW_ALIAS}"
    )


# ── Filtro 6.1 del Bloque 6 (2026-09-27): días desde el PRIMER DÍA del ticker
# en el lago (proxy IPO — el lago empieza en 2019, así que un listado anterior
# aparece con la edad truncada; NO es la IPO real, y la etiqueta de la UI lo
# dice). Evaluado en el DÍA del gap (D), no en la víspera: es una propiedad
# del ticker, no de una sesión. Umbral movible (p. ej. < 30 / < 90 días).
#
# ⚠️ La vía GCS lee por años: sin ayuda, MIN(timestamp) sobre la partición
# daría el primer día DEL AÑO LEÍDO (primera fecha falsa). gcs_cache amplía la
# lectura a TODO el lago cuando la regla usa esta columna (ver ahí).
DAYS_SINCE_FIRST_DAY_ALIAS = "days_since_first_day"


def _days_since_first_day_select() -> str:
    return (
        'DATEDIFF(\'day\', MIN("timestamp") OVER (PARTITION BY ticker), "timestamp") '
        f'AS {DAYS_SINCE_FIRST_DAY_ALIAS}'
    )


# ── Paquete «estrategias nuevas» (2026-09-28, ORDEN §2 de Álvaro) ─────────────
# Tres ventanas compuestas de VÍSPERA con evidencia sólida en el universo
# aunque la 1B no las cobre — material para diseñar estrategias distintas.
#
# vol $ de la víspera (criterio 2.4 del B2-bis): rth_close × rth_volume del
# día anterior, en DÓLARES (el estudio medía tramos 0,25-10 M$).
VOLUSD_PREV_ALIAS = "lag_volusd_1"

# Mecha superior de la víspera (Bloque 8): (high − máx(open, close)) /
# (high − low) del día anterior, EN % DEL RANGO (0-100). Descriptor débil del
# universo (7/8 años) que la 1B/2B no cobran: para estrategias nuevas.
WICK_SUP_PREV_ALIAS = "lag_wick_sup_1"

# Nº de gappers de la víspera (criterio 7.2a, «día caliente»): cruces del
# mercado ESE día (cuenta de filas pmh_gap_pct >= 50 por FECHA) referida a la
# sesión anterior disponible del ticker. Verificado INMUNE a la colisión del
# 7.2b (60/60: es un lookup por fecha, nunca usa minutos de entrada). NOTA de
# población: cuenta el lago ENTERO (no el universo filtrado del estudio) y en
# días sin ningún gapper hereda el último día con gappers (semántica LAG).
GAPPERS_PREV_ALIAS = "lag_gappers_prev_1"
_N_GAPPERS_DIA = "n_gappers_dia"


def _volusd_prev_select() -> str:
    return (
        'LAG("rth_close" * "rth_volume", 1) OVER (PARTITION BY ticker ORDER BY "timestamp") '
        f"AS {VOLUSD_PREV_ALIAS}"
    )


def _wick_sup_prev_select() -> str:
    return (
        'LAG(100.0 * ("high" - GREATEST("open", "close")) / NULLIF("high" - "low", 0), 1) '
        'OVER (PARTITION BY ticker ORDER BY "timestamp") '
        f"AS {WICK_SUP_PREV_ALIAS}"
    )


def _gappers_dia_select() -> str:
    """Nivel 1 (stage-1 / subquery base): gappers de CADA fecha."""
    return (
        'COUNT(*) FILTER (WHERE pmh_gap_pct >= 50) '
        f'OVER (PARTITION BY CAST("timestamp" AS DATE)) AS {_N_GAPPERS_DIA}'
    )


def _gappers_prev_select() -> str:
    """Nivel 2 (stage-2): la cuenta del día anterior, LAG por ticker."""
    return (
        f'LAG("{_N_GAPPERS_DIA}", 1) OVER (PARTITION BY ticker ORDER BY "timestamp") '
        f"AS {GAPPERS_PREV_ALIAS}"
    )


# ── Filtro «Hora de inicio del gap» (5.2-bis, ORDEN §3 de Álvaro) ─────────────
#
# t del PRIMER cruce de +X % sobre el cierre de la víspera en la línea
# continua 16:00 víspera → 09:30 (AH de la víspera: t 0-239; PM: t 720-1049,
# es decir, minuto-del-día + 480). Fuente: el PIVOTE gap_start.parquet que
# escribe scripts/construir_gappers_activos.py junto a la tabla del indicador
# «Gappers activos» (misma pasada sobre el lago 1m; regenerar en el mismo
# ciclo que el bygap). Columnas gap_start_min_<nivel> para los mismos
# GAPPERS_ACTIVE_LEVELS; NULL = ese ticker-día no cruzó el nivel («sin dato»).
#
# La consulta viaja como UMBRAL MOVIBLE sobre t: p. ej. «empezó antes de las
# 05:00» = gap_start_min_50 <= 780 (780 = 5*60+480). TABLA DE CONVERSIÓN para
# la UI: 240 = 20:00 víspera · 720 = 04:00 · 780 = 05:00 · 840 = 06:00 ·
# 900 = 07:00 · 960 = 08:00 · 1049 = 09:29.
#
# SIN LOOK-AHEAD SOLO SI la estrategia entra DESPUÉS del cruce: p. ej.
# exigiendo «PM High Gap % >= X» en la vela de entrada (el PMH acumulado ya
# >= X implica que el cruce de +X ya ocurrió). La UI lo avisa.
# 2026-10-01: de 5 en 5 (20→200) y ventana hasta las 16:00 (PMH = t ≤ 1049,
# RTH = t ≥ 1050). Lo genera scripts/construir_gap_start.py.
GAP_START_LEVELS = tuple(range(20, 205, 5))


def gap_start_columns() -> list[str]:
    return [f"gap_start_min_{n}" for n in GAP_START_LEVELS]


def gap_start_parquet_path() -> str:
    import os
    ruta = os.getenv("GAP_START_TABLE", "").strip()
    if ruta:
        return ruta.replace("\\", "/")
    base = os.getenv("CACHE_DIR", ".cache/intraday")
    return os.path.join(base, "gappers_activos", "gap_start.parquet").replace("\\", "/")


def needs_gap_start(where_sql: str) -> bool:
    """¿El WHERE referencia alguna columna gap_start_min_*? (gate del join)"""
    import re
    return re.search(r"\bgap_start_min_\d+\b", where_sql or "") is not None


def gap_start_join_sql(source: str) -> str:
    """LEFT JOIN con el pivote. `source` es el alias/tabla con timestamp y
    ticker (p. ej. 'dm_lagged' o una subquery envuelta). Las columnas del
    pivote llegan SIN prefijo: el WHERE las referencia tal cual."""
    return (
        f" LEFT JOIN read_parquet('{gap_start_parquet_path()}') gs "
        f"ON gs.ticker = {source}.ticker "
        f"AND CAST(gs.fecha AS DATE) = CAST({source}.\"timestamp\" AS DATE)"
    )


def prev_day_lag1_selects() -> list[str]:
    """Selects LAG 1 completos (todas las fuentes UI de Gap -1)."""
    return [_lag1_select(src) for src in PREV_DAY_LAG_SOURCES]


def prev_day_lag1_aliases() -> list[str]:
    return [f"lag_{src}_1" for src in PREV_DAY_LAG_SOURCES]


def stage2_prev_day_lag1_selects() -> list[str]:
    """Selects de Gap −1 que el stage-2 del qualifying NO tenía ya hardcodeados:
    los LAG 1 de PREV_DAY_LAG_SOURCES + la ventana compuesta 3.2 (ret 5 d) +
    days_since_first_day (6.1)."""
    return [
        _lag1_select(src)
        for src in PREV_DAY_LAG_SOURCES
        if src not in STAGE2_BUILTIN_LAG1_SOURCES
    ] + [_ret5d_select(), _days_since_first_day_select(),
         _volusd_prev_select(), _wick_sup_prev_select(), _gappers_prev_select()]


# Fuentes LEAD de la subquery de materializacion de pares (query.py). Mismo
# orden y contenido que tenia la string original inline: 7 fuentes x LEAD 1/2.
_DATASET_PAIRS_LEAD_SOURCES = [
    "rth_close", "pmh_gap_pct", "pm_volume", "gap_pct", "rth_volume",
    "rth_range_pct", "open",
]


def dataset_pairs_subquery_lagged_sql() -> str:
    """Subquery dm_lagged para _compute_dataset_pairs (routers/query.py).

    SELECT * + LEAD 1/2 (Gap+1 / Gap+2) + LAG 1 (Gap -1) sobre daily_metrics.
    El where externo referencia dm_lagged.<columna>, asi que toda metrica
    filtrable debe existir aqui.
    """
    cols: list[str] = []
    for n in (1, 2):
        for src in _DATASET_PAIRS_LEAD_SOURCES:
            cols.append(
                f'LEAD({src}, {n}) OVER (PARTITION BY ticker ORDER BY "timestamp") '
                f'AS lead_{src}_{n}'
            )
    cols.extend(prev_day_lag1_selects())
    cols.append(_ret5d_select())
    cols.append(_days_since_first_day_select())
    cols.append(_volusd_prev_select())
    cols.append(_wick_sup_prev_select())
    # El conteo de gappers necesita la columna por FECHA antes del LAG por
    # ticker: un nivel base más (ventanas anidadas no las admite DuckDB).
    cols.append(_gappers_prev_select())
    inner = ",\n                           ".join(cols)
    return (
        "(\n"
        "                    SELECT *,\n"
        f"                           {inner}\n"
        "                    FROM (\n"
        "                        SELECT *,\n"
        f"                               {_gappers_dia_select()}\n"
        "                        FROM daily_metrics\n"
        "                    ) dm_base\n"
        "                ) dm_lagged"
    )


# ── Columnas de ventana calculables AL VUELO (vía materializada) ────────────
#
# La vía materializada (QUALIFYING_WINDOWED_PARQUET, data_service.py) lee un
# parquet generado offline que trae las ventanas QUE EXISTÍAN cuando se generó.
# Una regla que use una columna de ventana añadida después (p. ej. una fuente
# nueva de PREV_DAY_LAG_SOURCES) revienta con "Binder Error: Referenced column
# … not found" (hallazgo 25-sep·16: el filtro 1.6 y, preexistente, cualquier
# Gap -1 de fuente añadida tras generar el parquet). En vez de obligar a
# regenerar el parquet, la vía materializada calcula al vuelo SOLO las
# columnas que falten, con la MISMA SQL con la que se materializa (paridad por
# construcción), sobre las columnas BASE del propio parquet.
#
# Registro genérico: alias -> expresión SELECT. Las LAG/LEAD estándar se
# generan programaticamente; una columna futura que NO sea LAG/LEAD (p. ej. un
# retorno acumulado de N días) se añade aquí con su expresión y la vía
# materializada la cubrirá sin más cambios.

_ON_THE_FLY_BASE_SOURCES = list(dict.fromkeys([
    "rth_open", "rth_close", "rth_high", "rth_low", "rth_volume", "pm_high",
    "open", "timestamp",
    *PREV_DAY_LAG_SOURCES,
]))


def window_alias_to_expr() -> dict[str, str]:
    """Alias de columna de ventana -> expresión SELECT equivalente (parquet)."""
    out: dict[str, str] = {}
    for src in _ON_THE_FLY_BASE_SOURCES:
        for n in (1, 2):
            out[f"lag_{src}_{n}"] = (
                f'LAG("{src}", {n}) OVER (PARTITION BY ticker ORDER BY "timestamp") '
                f'AS lag_{src}_{n}'
            )
            out[f"lead_{src}_{n}"] = (
                f'LEAD("{src}", {n}) OVER (PARTITION BY ticker ORDER BY "timestamp") '
                f'AS lead_{src}_{n}'
            )
    # Ventanas compuestas (no LAG/LEAD de una columna base): la primera real es
    # el 3.2 (retorno acumulado 5 días, Gap −1). Necesita "close"/"prev_close"
    # en el parquet (verificado en bygap y en el lago = mismo ETL que GCS).
    out[RET5D_WINDOW_ALIAS] = _ret5d_select()
    # 6.1 (2026-09-27): días desde el primer día del ticker. En la vía
    # materializada el glob cubre el lago COMPLETO → el MIN por partición es
    # la primera fecha real. OJO en GCS: gcs_cache amplía la lectura.
    out[DAYS_SINCE_FIRST_DAY_ALIAS] = _days_since_first_day_select()
    # Paquete «estrategias nuevas» (2026-09-28): nivel único, calculables al
    # vuelo sobre el parquet bygap (que trae rth_close/rth_volume/high/low/
    # open — columnas BASE del ETL).
    out[VOLUSD_PREV_ALIAS] = _volusd_prev_select()
    out[WICK_SUP_PREV_ALIAS] = _wick_sup_prev_select()
    return out


def on_the_fly_window_selects(missing) -> tuple[list[str], list[str]]:
    """Expresiones SELECT para columnas de ventana ausentes en el parquet.

    Devuelve (selects, desconocidas): `selects` son las expresiones de las
    columnas que este módulo sabe computar; `desconocidas` son las que no
    (esas seguirán fallando en el Binder, ruido a propósito: una regla que
    referencia algo que ni el parquet ni este registro pueden producir debe
    romper ruidosamente, no filtrar en silencio).
    """
    registro = window_alias_to_expr()
    faltan = [c for c in missing if c in registro]
    desconocidas = [c for c in missing if c not in registro]
    return [registro[c] for c in faltan], desconocidas
