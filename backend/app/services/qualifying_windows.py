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
PREV_DAY_LAG_SOURCES = [
    "rth_close",
    "rth_volume",
    "gap_pct",
    "pm_volume",
    "open",
    "pmh_gap_pct",
    "rth_range_pct",
]

# Fuentes LAG 1 que el stage-2 del qualifying (data_service / gcs_cache) ya
# construia a mano antes de que existiera este modulo. Sus select no se
# duplican; solo se anaden las que faltan.
STAGE2_BUILTIN_LAG1_SOURCES = {
    "rth_open", "rth_high", "rth_low", "pm_high", "rth_close", "rth_volume",
}


def _lag1_select(src: str) -> str:
    return f'LAG({src}, 1) OVER (PARTITION BY ticker ORDER BY "timestamp") AS lag_{src}_1'


def prev_day_lag1_selects() -> list[str]:
    """Selects LAG 1 completos (todas las fuentes UI de Gap -1)."""
    return [_lag1_select(src) for src in PREV_DAY_LAG_SOURCES]


def prev_day_lag1_aliases() -> list[str]:
    return [f"lag_{src}_1" for src in PREV_DAY_LAG_SOURCES]


def stage2_prev_day_lag1_selects() -> list[str]:
    """Selects LAG 1 que el stage-2 del qualifying NO tenia ya hardcodeados."""
    return [
        _lag1_select(src)
        for src in PREV_DAY_LAG_SOURCES
        if src not in STAGE2_BUILTIN_LAG1_SOURCES
    ]


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
    inner = ",\n                           ".join(cols)
    return (
        "(\n"
        "                    SELECT *,\n"
        f"                           {inner}\n"
        "                    FROM daily_metrics\n"
        "                ) dm_lagged"
    )
