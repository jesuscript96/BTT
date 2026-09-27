"""
Tests del filtro de universo "Gap -1" (dia anterior al gap).

Los "Añadir filtro de mercado" viajan como columnas lag_<col>_1 en las rules
del dataset. Estos tests validan SIN lago real que:

  1. La subquery de materializacion de pares (_compute_dataset_pairs) calcula
     los LAG 1 y filtra bien por ellos (DuckDB in-memory).
  2. build_screener_query deja pasar la regla lag_* como columna (passthrough,
     igual que las lead_*).
  3. _build_where_clause (via local/GCS) tambien la deja pasar.
  4. El hot cache RECHAZA reglas lead_/lag_ (alli se ignorarian en silencio;
     ver hallazgo 2026-08-29 en docs/MEMORIA_MADRE.md).
  5. Las vias qualifying (data_service / gcs_cache) usan la MISMA definicion
     compartida de columnas LAG (qualifying_windows).
"""
import duckdb
import inspect

import pytest

from app.services.qualifying_windows import (
    PREV_DAY_LAG_SOURCES,
    dataset_pairs_subquery_lagged_sql,
    prev_day_lag1_aliases,
    prev_day_lag1_selects,
    stage2_prev_day_lag1_selects,
)
from app.services.query_service import build_screener_query
from app.services import data_service


# ─── Mini-lago in-memory: 2 tickers x 3 dias ─────────────────────────────────

def _make_mini_lake() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    con.execute("CREATE SCHEMA massive")
    con.execute("CREATE TABLE massive.tickers (ticker VARCHAR, type VARCHAR)")
    con.execute("CREATE TABLE massive.splits (ticker VARCHAR, execution_date DATE)")
    con.execute("""
        CREATE TABLE daily_metrics (
            ticker VARCHAR,
            "timestamp" TIMESTAMP,
            rth_close DOUBLE,
            rth_volume BIGINT,
            gap_pct DOUBLE,
            pm_volume BIGINT,
            "open" DOUBLE,
            pmh_gap_pct DOUBLE,
            rth_range_pct DOUBLE,
            day_return_pct DOUBLE,
            "close" DOUBLE,
            "prev_close" DOUBLE
        )
    """)
    rows = [
        # AAA: volumen del dia anterior 1M -> 3M (creciendo);
        # neto RTH (day_return_pct): roja, roja, verde
        ("AAA", "2024-01-02", 10.0, 1_000_000, -1.0),
        ("AAA", "2024-01-03", 11.0, 3_000_000, -2.0),
        ("AAA", "2024-01-04", 12.0, 9_000_000, 3.0),
        # BBB: volumen del dia anterior 2M -> 1M (decreciente);
        # neto RTH: verde, verde, roja
        ("BBB", "2024-01-02", 20.0, 2_000_000, 2.0),
        ("BBB", "2024-01-03", 21.0, 1_000_000, 1.0),
        ("BBB", "2024-01-04", 22.0, 1_000_000, -0.5),
    ]
    for t, d, close, vol, day_ret in rows:
        con.execute(
            'INSERT INTO daily_metrics VALUES (?, ?, ?, ?, 5.0, 500_000, ?, 10.0, 3.0, ?, 10.0, 10.0)',
            [t, d, close, vol, close, day_ret],
        )
    con.execute("INSERT INTO massive.tickers VALUES ('AAA', 'CS'), ('BBB', 'CS')")
    return con


class TestPrevDayLagColumns:
    def test_aliases_match_sources(self):
        assert prev_day_lag1_aliases() == [f"lag_{s}_1" for s in PREV_DAY_LAG_SOURCES]
        assert "lag_rth_volume_1" in prev_day_lag1_aliases()
        assert "lag_rth_close_1" in prev_day_lag1_aliases()

    def test_dataset_pairs_subquery_has_all_prev_day_lags(self):
        sql = dataset_pairs_subquery_lagged_sql()
        for alias in prev_day_lag1_aliases():
            assert f"AS {alias}" in sql
        # Los LEAD existentes (Gap+1/+2) siguen ahi
        for alias in ("lead_rth_close_1", "lead_rth_close_2", "lead_open_2"):
            assert f"AS {alias}" in sql

    def test_qualifying_paths_use_shared_helper(self):
        # Paridad por construccion: las dos vias qualifying deben consumir la
        # MISMA lista compartida, no strings propias.
        from app.db import gcs_cache
        for mod in (data_service, gcs_cache):
            assert "stage2_prev_day_lag1_selects()" in inspect.getsource(mod)


class TestDatasetPairsPrevDayFilter:
    """Ejecuta la composicion REAL de _compute_dataset_pairs sobre el mini-lago."""

    def test_prev_day_volume_rule_filters_pairs(self):
        con = _make_mini_lake()
        filters = {
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "rules": [
                {
                    "metric": "lag_rth_volume_1",
                    "operator": "GREATER_THAN_OR_EQUAL",
                    "value": "2000000",
                }
            ],
        }
        _, params, _, _, where_m_stats, _ = build_screener_query(filters, limit=100000)
        assert "lag_rth_volume_1 >= ?" in where_m_stats

        subquery_lagged = dataset_pairs_subquery_lagged_sql()
        select_sql = f"""
            SELECT ticker, CAST(CAST("timestamp" AS DATE) AS VARCHAR) as date
            FROM {subquery_lagged}
            WHERE {where_m_stats.replace('daily_metrics.', 'dm_lagged.')}
        """
        df = con.execute(select_sql, params).fetchdf()

        got = set(zip(df["ticker"], df["date"]))
        # lag de AAA: NULL, 1M, 3M  -> solo 2024-01-04 pasa (>= 2M)
        # lag de BBB: NULL, 2M, 1M  -> solo 2024-01-03 pasa
        # El primer dia de cada ticker (LAG NULL) queda excluido: sin el filtro
        # del dia anterior no hay evidencia de que lo cumpla.
        assert got == {("AAA", "2024-01-04"), ("BBB", "2024-01-03")}

    def test_prev_day_close_rule_filters_pairs(self):
        con = _make_mini_lake()
        filters = {
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "rules": [
                {
                    "metric": "lag_rth_close_1",
                    "operator": "GREATER_THAN",
                    "value": "15",
                }
            ],
        }
        _, params, _, _, where_m_stats, _ = build_screener_query(filters, limit=100000)
        subquery_lagged = dataset_pairs_subquery_lagged_sql()
        select_sql = f"""
            SELECT ticker, CAST(CAST("timestamp" AS DATE) AS VARCHAR) as date
            FROM {subquery_lagged}
            WHERE {where_m_stats.replace('daily_metrics.', 'dm_lagged.')}
        """
        df = con.execute(select_sql, params).fetchdf()

        got = set(zip(df["ticker"], df["date"]))
        # close del dia anterior: AAA siempre < 15 (no pasa nunca);
        # BBB 20/21/22 en 01-02/03/04 -> pasan 01-03 y 01-04.
        assert got == {("BBB", "2024-01-03"), ("BBB", "2024-01-04")}


    def test_prev_day_return_rule_filters_pairs(self):
        """Filtro 1.6 del Bloque 1: víspera roja (lag_day_return_pct_1 < 0)."""
        con = _make_mini_lake()
        filters = {
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "rules": [
                {
                    "metric": "lag_day_return_pct_1",
                    "operator": "LESS_THAN",
                    "value": "0",
                }
            ],
        }
        _, params, _, _, where_m_stats, _ = build_screener_query(filters, limit=100000)
        assert "lag_day_return_pct_1 < ?" in where_m_stats

        subquery_lagged = dataset_pairs_subquery_lagged_sql()
        select_sql = f"""
            SELECT ticker, CAST(CAST("timestamp" AS DATE) AS VARCHAR) as date
            FROM {subquery_lagged}
            WHERE {where_m_stats.replace('daily_metrics.', 'dm_lagged.')}
        """
        df = con.execute(select_sql, params).fetchdf()

        got = set(zip(df["ticker"], df["date"]))
        # lag de AAA: NULL, -1.0, -2.0 -> pasan 01-03 y 01-04 (víspera roja)
        # lag de BBB: NULL, 2.0, 1.0   -> no pasa ningún día (víspera verde)
        assert got == {("AAA", "2024-01-03"), ("AAA", "2024-01-04")}


class TestRet5dRuleFiltersPairs:
    """Filtro 3.2 del Bloque 3: retorno acumulado 5 días de la víspera
    (lag_ret5d_pct_1 < 0 = «venía cayendo»), por la vía de materialización
    de pares. Definición EXACTA del estudio: producto de los r = close/prev_close
    de las 5 sesiones D-5..D-1 (prev_close persistida), NULL si algún día de la
    ventana es inválido (|r| > 500 % o prev_close <= 0) o faltan sesiones."""

    def _make_ret5d_lake(self) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect(":memory:")
        con.execute("CREATE SCHEMA massive")
        con.execute("CREATE TABLE massive.tickers (ticker VARCHAR, type VARCHAR)")
        con.execute("CREATE TABLE massive.splits (ticker VARCHAR, execution_date DATE)")
        con.execute(
            'CREATE TABLE daily_metrics (ticker VARCHAR, "timestamp" TIMESTAMP, '
            '"close" DOUBLE, "prev_close" DOUBLE, rth_close DOUBLE, rth_volume BIGINT, '
            "gap_pct DOUBLE, pm_volume BIGINT, \"open\" DOUBLE, pmh_gap_pct DOUBLE, "
            "rth_range_pct DOUBLE, day_return_pct DOUBLE)"
        )

        def ins(t: str, i: int, close: float, prev: float):
            dia = f"2024-01-{i + 1:02d}"
            con.execute(
                'INSERT INTO daily_metrics VALUES (?, ?, ?, ?, 10.0, 1000000, '
                "5.0, 500000, 10.0, 50.0, 3.0, 1.0)",
                [t, dia, close, prev],
            )

        # AAA: 6 sesiones con r = −0,1 cada una → ret 5 d = 0,9⁵ − 1 = −40,95 %.
        for i in range(6):
            ins("AAA", i, 10.0 * 0.9 ** i, 10.0 * 0.9 ** (i - 1) if i else 10.0)
        # BBB: r = +0,1 → +61,05 % («venía subiendo»).
        for i in range(6):
            ins("BBB", i, 10.0 * 1.1 ** i, 10.0 * 1.1 ** (i - 1) if i else 10.0)
        # CCC: solo 3 sesiones → ventana incompleta → NULL siempre.
        ins("CCC", 0, 10.0, 10.0)
        ins("CCC", 1, 9.0, 10.0)
        ins("CCC", 2, 8.0, 9.0)
        # DDD: cae, pero la sesión del 4-ene tiene |r| > 500 % → la ventana que
        # la incluye queda NULL entera (igual que el estudio dejaba NaN).
        ins("DDD", 0, 10.0, 10.0)
        ins("DDD", 1, 9.0, 10.0)
        ins("DDD", 2, 8.0, 9.0)
        ins("DDD", 3, 100.0, 1.0)   # r = +9.900 % > 500 %
        ins("DDD", 4, 6.0, 7.0)
        ins("DDD", 5, 5.0, 6.0)
        con.execute("INSERT INTO massive.tickers VALUES ('AAA','CS'), ('BBB','CS'), ('CCC','CS'), ('DDD','CS')")
        return con

    def test_ret5d_rule_filters_pairs(self):
        con = self._make_ret5d_lake()
        filters = {
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "rules": [
                {
                    "metric": "lag_ret5d_pct_1",
                    "operator": "LESS_THAN",
                    "value": "0",
                }
            ],
        }
        _, params, _, _, where_m_stats, _ = build_screener_query(filters, limit=100000)
        assert "lag_ret5d_pct_1 < ?" in where_m_stats

        subquery_lagged = dataset_pairs_subquery_lagged_sql()
        select_sql = f"""
            SELECT ticker, CAST(CAST("timestamp" AS DATE) AS VARCHAR) as date,
                   lag_ret5d_pct_1
            FROM {subquery_lagged}
            WHERE {where_m_stats.replace('daily_metrics.', 'dm_lagged.')}
        """
        df = con.execute(select_sql, params).fetchdf()

        got = set(zip(df["ticker"], df["date"]))
        # AAA: la ventana de 5 sesiones completa existe desde el 6-ene
        # (sesiones 1-5) → cae. BBB sube, CCC sin historial y DDD
        # con el día inválido dentro → no seleccionados.
        assert got == {("AAA", "2024-01-06")}
        # la ventana del 6-ene son las sesiones 0-4: la 0 es plana (r = 0,
        # close = prev_close = 10, válida) → producto 0,9⁴
        assert df["lag_ret5d_pct_1"].iloc[0] == pytest.approx(100 * (0.9 ** 4 - 1))

    def test_ret5d_ventana_con_dia_invalido_es_null(self):
        con = self._make_ret5d_lake()
        subquery_lagged = dataset_pairs_subquery_lagged_sql()
        df = con.execute(
            f'SELECT ticker, CAST(CAST("timestamp" AS DATE) AS VARCHAR) as date, '
            f"lag_ret5d_pct_1 FROM {subquery_lagged} "
            f"WHERE ticker = 'DDD' ORDER BY \"timestamp\""
        ).fetchdf()
        # ninguna fila de DDD tiene ventana computable: el |r| > 500 % del 4-ene
        # envenena las ventanas que lo incluyen y las demás están incompletas
        assert df["lag_ret5d_pct_1"].isna().all()


class TestWhereClausePassthrough:
    def test_build_where_clause_keeps_lag_column(self):
        filters = {
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "rules": [
                {
                    "metric": "lag_rth_close_1",
                    "operator": "GREATER_THAN_OR_EQUAL",
                    "value": "5.0",
                }
            ],
        }
        where = data_service._build_where_clause(filters)
        assert "lag_rth_close_1 >= 5.0" in where


class TestHotCacheGuard:
    def test_rejects_lag_rule(self):
        filters = {
            "min_gap_pct": 6.0,  # por si solo activaria el hot cache
            "rules": [
                {
                    "metric": "lag_rth_volume_1",
                    "operator": "GREATER_THAN_OR_EQUAL",
                    "value": "2000000",
                }
            ],
        }
        assert data_service._can_use_hot_cache(filters) is False

    def test_rejects_lead_rule(self):
        filters = {
            "rules": [
                {
                    "metric": "lead_rth_close_1",
                    "operator": "GREATER_THAN_OR_EQUAL",
                    "value": "5",
                },
                {
                    "metric": "Open Gap %",
                    "operator": "GREATER_THAN_OR_EQUAL",
                    "value": "6",
                },
            ],
        }
        assert data_service._can_use_hot_cache(filters) is False

    def test_accepts_same_day_gap_rule(self):
        # Las rules del propio dia (gap_day) SI funcionan en hot cache: sus
        # columnas existen en el parquet base.
        filters = {
            "rules": [
                {
                    "metric": "Open Gap %",
                    "operator": "GREATER_THAN_OR_EQUAL",
                    "value": "6",
                }
            ],
        }
        assert data_service._can_use_hot_cache(filters) is True

    def test_accepts_min_gap_pct_without_rules(self):
        assert data_service._can_use_hot_cache({"min_gap_pct": 6.0}) is True
