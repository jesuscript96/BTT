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


def prev_day_lag1_selects() -> list[str]:
    """Selects LAG 1 completos (todas las fuentes UI de Gap -1)."""
    return [_lag1_select(src) for src in PREV_DAY_LAG_SOURCES]


def prev_day_lag1_aliases() -> list[str]:
    return [f"lag_{src}_1" for src in PREV_DAY_LAG_SOURCES]


def stage2_prev_day_lag1_selects() -> list[str]:
    """Selects de Gap −1 que el stage-2 del qualifying NO tenía ya hardcodeados:
    los LAG 1 de PREV_DAY_LAG_SOURCES + la ventana compuesta 3.2 (ret 5 d)."""
    return [
        _lag1_select(src)
        for src in PREV_DAY_LAG_SOURCES
        if src not in STAGE2_BUILTIN_LAG1_SOURCES
    ] + [_ret5d_select()]


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
    inner = ",\n                           ".join(cols)
    return (
        "(\n"
        "                    SELECT *,\n"
        f"                           {inner}\n"
        "                    FROM daily_metrics\n"
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
