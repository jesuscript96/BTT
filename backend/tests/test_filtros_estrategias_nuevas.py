"""
Paquete de filtros «estrategias nuevas» (2026-09-28, ORDEN §2 de Álvaro):
  lag_volusd_1      (vol $ víspera, criterio 2.4 del B2-bis)
  lag_wick_sup_1    (mecha superior víspera, Bloque 8)
  lag_gappers_prev_1 (nº de gappers de la víspera, 7.2a «día caliente»)

Sin lago real (DuckDB in-memory + parquet bygap mini, patrón de
test_qualifying_bygap_lag_faltante.py):
  1. Vía stage-2 (local): cada regla devuelve EXACTO los ticker-días
     esperados, con valores a mano (incl. hueco de fechas → LAG usa la
     sesión disponible anterior).
  2. PARIDAD materializada (al-vuelo) vs stage-2 para las tres columnas
     (gappers con su envoltorio de DOS niveles).
  3. El registro al-vuelo de un nivel NO registra gappers (necesita dos).
"""
import duckdb
import pytest

from app.services.data_service import _fetch_qualifying_data_uncached
from app.services.qualifying_windows import (
    GAPPERS_PREV_ALIAS,
    VOLUSD_PREV_ALIAS,
    WICK_SUP_PREV_ALIAS,
    on_the_fly_window_selects,
    window_alias_to_expr,
)

DIAS = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-06"]

# AAA: todos los días. CCC: SOLO d1, d3 y d5 (hueco: el LAG de d3 mira d1,
# el de d5 mira d3 — semántica «sesión disponible anterior»).
FILAS = {
    "AAA": {
        # volusd = rth_close × rth_volume: [1M, 8M, 2M, 1M, 3M]
        "rth_close": [10.0, 10.0, 10.0, 10.0, 10.0],
        "rth_volume": [100_000, 800_000, 200_000, 100_000, 300_000],
        # mecha sup % = (high − máx(open, close)) / (high − low) × 100
        # d1: (10.5−10)/(10.5−9.5)=50 · d2: (12−10)/(12−9.5)=80
        # d3: (11.5−11)/(11.5−9.8)≈29.4 · d4: 50 · d5: (10.1−10)/(10.1−9.9)=50
        "open": [10.0, 10.0, 10.0, 10.0, 10.0],
        "high": [10.5, 12.0, 11.5, 10.5, 10.1],
        "low": [9.5, 9.5, 9.8, 9.5, 9.9],
        "close": [10.0, 10.0, 11.0, 10.0, 10.0],
        # gappers por fecha (≥50): d1:1 (AAA) d2:1 (CCC) d3:2 d4:0 d5:1
        "pmh_gap_pct": [60.0, 20.0, 55.0, 5.0, 70.0],
    },
    "CCC": {
        "rth_close": [20.0, None, 20.0, None, 20.0],
        "rth_volume": [50_000, None, 60_000, None, 70_000],
        "open": [20.0, None, 20.0, None, 20.0],
        "high": [20.2, None, 20.4, None, 20.2],
        "low": [19.9, None, 19.8, None, 19.9],
        "close": [20.0, None, 20.0, None, 20.0],
        # d1: 80 (gapper) · d3: 90 (gapper) · d5: 10
        "pmh_gap_pct": [80.0, None, 90.0, None, 10.0],
    },
}


def _make_con(ruta_parquet: str) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    cols = ["ticker VARCHAR", '"timestamp" TIMESTAMP', "rth_open DOUBLE",
            "rth_high DOUBLE", "rth_low DOUBLE", "rth_close DOUBLE",
            "rth_volume BIGINT", "pm_high DOUBLE", "pm_low DOUBLE",
            '"open" DOUBLE', '"high" DOUBLE', '"low" DOUBLE', '"close" DOUBLE',
            "prev_close DOUBLE", "pmh_gap_pct DOUBLE", "gap_pct DOUBLE",
            "day_return_pct DOUBLE", "pm_volume BIGINT", "rth_range_pct DOUBLE"]
    con.execute(f'CREATE TABLE daily_metrics ({", ".join(cols)})')
    vals = []
    for tk, d in FILAS.items():
        for i, dia in enumerate(DIAS):
            if d["rth_close"][i] is None:
                continue
            vals.append(
                f"('{tk}', TIMESTAMP '{dia} 00:00:00', 1, 1, 1, {d['rth_close'][i]}, "
                f"{d['rth_volume'][i]}, 1, 1, {d['open'][i]}, {d['high'][i]}, "
                f"{d['low'][i]}, {d['close'][i]}, 1, {d['pmh_gap_pct'][i]}, 5.0, 0.0, 1, 1.0)"
            )
    con.execute(f"INSERT INTO daily_metrics VALUES {', '.join(vals)}")
    con.execute(f"""
        COPY (SELECT *, LAG(rth_close, 1) OVER (
                PARTITION BY ticker ORDER BY "timestamp") AS lag_rth_close_1
              FROM daily_metrics) TO '{ruta_parquet}' (FORMAT PARQUET)
    """)
    return con


def _filtros(metrica, op, valor):
    return {
        "start_date": "2024-01-01", "end_date": "2024-12-31",
        "rules": [{"metric": metrica, "operator": op,
                   "valueType": "static", "value": str(valor)}],
    }


def _td(df):
    return sorted(zip(df["ticker"], df["date"]))


@pytest.fixture()
def entorno(tmp_path, monkeypatch):
    ruta = str(tmp_path / "bygap_mini.parquet")
    con = _make_con(ruta)
    monkeypatch.setenv("DB_PROVIDER", "local")
    monkeypatch.setenv("QUALIFYING_WINDOWED_PARQUET", ruta)
    monkeypatch.setattr("app.database.get_db_connection", lambda: con)
    yield ruta, con, monkeypatch
    con.close()


def _stage2(entorno, metrica, op, valor):
    entorno[2].delenv("QUALIFYING_WINDOWED_PARQUET")
    return _fetch_qualifying_data_uncached("dataset-test", filtros=_filtros(metrica, op, valor))


def _materializada(metrica, op, valor):
    return _fetch_qualifying_data_uncached("dataset-test", filtros=_filtros(metrica, op, valor))


# ─── 1. vía stage-2: esperados EXACTOS a mano ───

def test_volusd_stage2(entorno):
    # lag AAA d2..d5 = [1M, 8M, 2M, 1M]; CCC d3 = 1M, d5 = 1.2M
    df = _stage2(entorno, VOLUSD_PREV_ALIAS, "LESS_THAN", 2_000_000)
    assert _td(df) == [("AAA", "2024-01-03"), ("AAA", "2024-01-06"),
                       ("CCC", "2024-01-04"), ("CCC", "2024-01-06")]


def test_wick_sup_stage2(entorno):
    # lag AAA: d2=50, d3=80, d4≈29.4, d5=50 → ≥70 solo d3
    df = _stage2(entorno, WICK_SUP_PREV_ALIAS, "GREATER_THAN_OR_EQUAL", 70)
    assert _td(df) == [("AAA", "2024-01-04")]


def test_gappers_stage2_con_hueco(entorno):
    # cuentas por fecha (gappers = filas pmh≥50): d1:2 (AAA+CCC) d2:0 d3:2 d4:0 d5:1
    # AAA lag: d2=2, d3=0, d4=2, d5=0 → ≥1: d2, d4
    # CCC (hueco: solo d1/d3/d5): d3 mira d1 → 2; d5 mira d3 → 2 → ≥1: d3, d5
    df = _stage2(entorno, GAPPERS_PREV_ALIAS, "GREATER_THAN_OR_EQUAL", 1)
    assert _td(df) == [("AAA", "2024-01-03"), ("AAA", "2024-01-05"),
                       ("CCC", "2024-01-04"), ("CCC", "2024-01-06")]


# ─── 2. paridad materializada (al-vuelo) vs stage-2 ───

@pytest.mark.parametrize("metrica,op,valor", [
    (VOLUSD_PREV_ALIAS, "LESS_THAN", 2_000_000),
    (WICK_SUP_PREV_ALIAS, "GREATER_THAN_OR_EQUAL", 70),
    (GAPPERS_PREV_ALIAS, "GREATER_THAN_OR_EQUAL", 1),
])
def test_paridad_materializada_vs_stage2(entorno, metrica, op, valor):
    df_mat = _materializada(metrica, op, valor)
    df_s2 = _stage2(entorno, metrica, op, valor)
    assert _td(df_mat) == _td(df_s2), f"{metrica}: materializada != stage-2"
    m = df_mat.set_index(["ticker", "date"])[metrica].to_dict()
    s2 = df_s2.set_index(["ticker", "date"])[metrica].to_dict()
    for k in m:
        assert m[k] == s2[k]


# ─── 3. registro: gappers NO es de un nivel ───

def test_registro_un_nivel_sin_gappers():
    reg = window_alias_to_expr()
    assert VOLUSD_PREV_ALIAS in reg and WICK_SUP_PREV_ALIAS in reg
    assert GAPPERS_PREV_ALIAS not in reg  # necesita DOS niveles (envoltorio)
    sel, desc = on_the_fly_window_selects({GAPPERS_PREV_ALIAS})
    assert sel == [] and desc == [GAPPERS_PREV_ALIAS]


def test_las_tres_reglas_juntas_por_la_materializada(entorno):
    """Combinación real de la verificación 28-sep: las tres reglas en un AND.
    El envoltorio de dos niveles de gappers NO puede ser pisado por las
    selects al-vuelo de volusd/mecha (bug encontrado en la verificación real)."""
    filtros = {
        "start_date": "2024-01-01", "end_date": "2024-12-31",
        "rules": [
            {"metric": VOLUSD_PREV_ALIAS, "operator": "GREATER_THAN_OR_EQUAL",
             "valueType": "static", "value": "1000000"},
            {"metric": WICK_SUP_PREV_ALIAS, "operator": "GREATER_THAN_OR_EQUAL",
             "valueType": "static", "value": "10"},
            {"metric": GAPPERS_PREV_ALIAS, "operator": "GREATER_THAN_OR_EQUAL",
             "valueType": "static", "value": "1"},
        ],
    }
    df_mat = _fetch_qualifying_data_uncached("dataset-test", filtros=filtros)
    df_s2 = _fetch_qualifying_data_uncached("dataset-test", filtros=filtros)
    # tras delenv el parquet: la vía autoritativa stage-2
    entorno[2].delenv("QUALIFYING_WINDOWED_PARQUET")
    df_s2 = _fetch_qualifying_data_uncached("dataset-test", filtros=filtros)
    assert _td(df_mat) == _td(df_s2) and len(df_mat) > 0
